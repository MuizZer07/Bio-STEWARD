// P5 Approvals (design v0.8 §4): the one payload read of the Approvals panel, `.steward/pending/<nonce>.txt`, matched
// to the CLI's 12-character nonce prefix or named by its full nonce. No `vscode` import, so the unit tests run it on
// real folders.
//
// The read stays inside the project and never follows a link (U09, U08's fifth finding). CLI 0.20.6 `read_pending`
// walks `.steward/pending` with directory-relative opens; Node has no `openat`, so the extension holds the same
// boundary by identity instead:
//   1. `.steward` and `.steward/pending` under the project's canonical root must be real folders (lstat, no link);
//      their device and inode numbers are kept;
//   2. the file is opened with O_NOFOLLOW and must be a regular file (fstat), at most 1 MiB (what `read_pending`
//      reads), and valid UTF-8;
//   3. after the read, the two folders are looked at again (same device and inode, still no link), then the file's
//      own path (no link, and the same device and inode as the open descriptor), then the folders once more.
// A folder replaced by a link at any moment of the read makes one of these differ, and the read is refused: the
// bytes returned are those of the file at `.steward/pending/<nonce>.txt` reached without links. The text is
// returned unchanged. Read-only: nothing here writes.
import { createHash } from 'node:crypto';
import { constants, type Stats } from 'node:fs';
import { lstat, open, readdir, readFile, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { bindCard, isNonce, isPrefix, queueCode, type ApprovalsState, type PayloadRead } from './model/approvals';
import { parseToml } from './model/toml';

export const PAYLOAD_LIMIT_BYTES = 1 << 20;
// More files than this in the queue folder are not looked at (a guard against a huge folder).
const MAX_ENTRIES = 10_000;
const PAYLOAD_NAME = /^[0-9a-f]{32}\.txt$/;
const CHANGED = 'changed, or was reached through a link, while it was read';

export type PayloadText =
  | { readonly kind: 'read'; readonly nonce: string; readonly sha256: string; readonly text: string }
  | { readonly kind: 'unreadable'; readonly reason: string };

interface Folder {
  readonly path: string;
  // Device and inode of `.steward` and `.steward/pending`, as first seen.
  readonly ids: readonly (readonly [number, number])[];
  readonly paths: readonly string[];
}

const id = (entry: Stats): readonly [number, number] => [entry.dev, entry.ino];

// The project's own queue folder, or a reason it is not used.
async function pendingFolder(root: string): Promise<Folder | { reason: string }> {
  let canonicalRoot: string;
  try {
    canonicalRoot = await realpath(root);
  } catch {
    return { reason: 'project folder cannot be read' };
  }
  let folder = canonicalRoot;
  const ids: (readonly [number, number])[] = [];
  const paths: string[] = [];
  for (const part of ['.steward', 'pending']) {
    folder = join(folder, part);
    const entry = await lstat(folder).catch(() => undefined);
    if (!entry) return { reason: 'is missing' };
    if (entry.isSymbolicLink() || !entry.isDirectory()) return { reason: 'is reached through a link or not a folder' };
    ids.push(id(entry));
    paths.push(folder);
  }
  const resolved = await realpath(folder).catch(() => undefined);
  return resolved === folder ? { path: folder, ids, paths } : { reason: 'is outside the project' };
}

// The two folders are still the ones first seen, and still not links.
async function sameFolders(folder: Folder): Promise<boolean> {
  for (const [i, path] of folder.paths.entries()) {
    const entry = await lstat(path).catch(() => undefined);
    if (!entry || entry.isSymbolicLink() || !entry.isDirectory()) return false;
    if (entry.dev !== folder.ids[i][0] || entry.ino !== folder.ids[i][1]) return false;
  }
  return true;
}

async function namesIn(folder: string): Promise<ReadonlyMap<string, string> | { reason: string }> {
  const entries = await readdir(folder, { withFileTypes: true }).catch(() => undefined);
  if (!entries) return { reason: 'cannot be listed' };
  const byPrefix = new Map<string, string | null>();
  for (const entry of entries.slice(0, MAX_ENTRIES)) {
    if (!PAYLOAD_NAME.test(entry.name)) continue;
    const prefix = entry.name.slice(0, 12);
    byPrefix.set(prefix, byPrefix.has(prefix) ? null : entry.name.slice(0, 32));
  }
  return new Map([...byPrefix].filter((pair): pair is [string, string] => pair[1] !== null));
}

// The payload file names of the project's own queue, by their 12-character prefix (a prefix two files share is
// left out: the card cannot tell them apart).
export async function pendingNames(root: string): Promise<ReadonlyMap<string, string> | { reason: string }> {
  const folder = await pendingFolder(root);
  if ('reason' in folder) return folder;
  return namesIn(folder.path);
}

// Points inside the read where the unit tests replace a folder (an ancestor swapped for a link, then back).
export interface ReadSteps {
  readonly beforeOpen?: () => Promise<void> | void;
  readonly afterOpen?: () => Promise<void> | void;
}

// Read the payload a 12-character prefix or a full nonce names, unchanged.
export async function readPendingPayload(root: string, name: string, steps: ReadSteps = {}): Promise<PayloadText> {
  if (!isPrefix(name) && !isNonce(name)) return { kind: 'unreadable', reason: 'is not named by a nonce' };
  const folder = await pendingFolder(root);
  if ('reason' in folder) return { kind: 'unreadable', reason: folder.reason };
  const names = await namesIn(folder.path);
  if ('reason' in names) return { kind: 'unreadable', reason: names.reason as string };
  const nonce = names.get(name.slice(0, 12));
  if (!nonce || (isNonce(name) && nonce !== name)) return { kind: 'unreadable', reason: 'is not in this project\'s queue' };
  const path = join(folder.path, `${nonce}.txt`);
  await steps.beforeOpen?.();
  let file;
  try {
    file = await open(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  } catch {
    return { kind: 'unreadable', reason: 'cannot be opened without following a link' };
  }
  let bytes: Buffer;
  let opened: Stats;
  try {
    opened = await file.stat();
    if (!opened.isFile()) return { kind: 'unreadable', reason: 'is not a regular file' };
    if (opened.size > PAYLOAD_LIMIT_BYTES) return { kind: 'unreadable', reason: `is larger than ${PAYLOAD_LIMIT_BYTES} bytes` };
    const buffer = Buffer.alloc(PAYLOAD_LIMIT_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await file.read(buffer, length, buffer.length - length, length);
      if (!bytesRead) break;
      length += bytesRead;
    }
    if (length > PAYLOAD_LIMIT_BYTES) return { kind: 'unreadable', reason: `is larger than ${PAYLOAD_LIMIT_BYTES} bytes` };
    bytes = buffer.subarray(0, length);
  } catch {
    return { kind: 'unreadable', reason: 'cannot be read' };
  } finally {
    await file.close();
  }
  await steps.afterOpen?.();
  // The identity check: what was read is the file at this path, reached without links, inside the project.
  if (!await sameFolders(folder)) return { kind: 'unreadable', reason: CHANGED };
  const named = await lstat(path).catch(() => undefined);
  if (!named || named.isSymbolicLink() || !named.isFile() || named.dev !== opened.dev || named.ino !== opened.ino) {
    return { kind: 'unreadable', reason: CHANGED };
  }
  if (!await sameFolders(folder)) return { kind: 'unreadable', reason: CHANGED };
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    return { kind: 'unreadable', reason: 'is not UTF-8 text' };
  }
  return { kind: 'read', nonce, sha256: createHash('sha256').update(bytes).digest('hex'), text };
}

// The code the CLI prints for this project's own payloads ([exchange] code, or "."), read from steward.toml now.
export async function readQueueCode(root: string): Promise<string | undefined> {
  try {
    return queueCode(parseToml(await readFile(join(root, 'steward.toml'), 'utf8')));
  } catch {
    return undefined;
  }
}

// What a card shows of its payload: the full nonce, the SHA-256 and whether the queue line binds to it, never the
// text. `state` is the queue read the card is drawn from.
export async function payloadRead(root: string, prefix: string, state?: ApprovalsState, code?: string): Promise<PayloadRead | undefined> {
  const read = await readPendingPayload(root, prefix);
  if (read.kind === 'read') {
    return { kind: 'read', nonce: read.nonce, sha256: read.sha256, binding: bindCard(state, code, read.nonce, read.text) };
  }
  return read.reason === 'is not in this project\'s queue' || read.reason === 'is missing' ? undefined : read;
}
