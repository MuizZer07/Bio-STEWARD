// Reads the sprints of one project for the live sprint view (S9): the sprint files and ledgers in
// `development/sprints/`, and nothing else (no git: T12, decision D1). Read-only: files are opened for reading only,
// and nothing is created, changed or deleted. No VS Code API here, so the unit tests drive it against a real scratch
// sprint.
import { constants } from 'node:fs';
import { open, readdir, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { isWithin } from './cli/paths';
import { MAX_LEDGER_BYTES, MAX_SPRINT_FILE_BYTES, snapshotOf, SPRINT_DIR, SPRINT_ID, type SprintSnapshot } from './model/sprint';

// At most this many sprints (the newest ids; sprint ids start with their date) are read per refresh (T11-03).
export const MAX_SPRINTS = 32;

type Read = { text: string } | { missing: true } | { error: string };

// A regular file in `dir` (canonical, inside the project), up to `max` bytes: opened without following a link and
// without blocking on a FIFO, then checked and read through the same descriptor, so a file that is swapped or grows
// during the read is never read past `max` (T11-03). Invalid UTF-8 is an error, not replaced (T11-04).
// `growing` (a ledger): a last line without its newline may end inside a character the CLI is still writing; it is
// never folded (model/sprint.ts: partialTail), so only the complete lines must be valid UTF-8.
export async function readBounded(dir: string, name: string, max: number, growing = false): Promise<Read> {
  let file;
  try {
    file = await open(join(dir, name), constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === 'ENOENT') return { missing: true };
    return { error: code === 'ELOOP' ? 'a link, not a regular file' : code ?? 'unreadable' };
  }
  try {
    const status = await file.stat();
    if (!status.isFile()) return { error: 'not a regular file' };
    if (status.size > max) return { error: `larger than ${Math.round(max / 1024)} KB` };
    // In chunks to the end of the file as it is now (a ledger can grow while it is read), never past `max`.
    const chunks: Buffer[] = [];
    let length = 0;
    for (;;) {
      const chunk = Buffer.allocUnsafe(Math.min(256 * 1024, max + 1 - length));
      const { bytesRead } = await file.read(chunk, 0, chunk.length, length);
      if (!bytesRead) break;
      chunks.push(chunk.subarray(0, bytesRead));
      length += bytesRead;
      if (length > max) return { error: `larger than ${Math.round(max / 1024)} KB` };
    }
    const bytes = Buffer.concat(chunks, length);
    const strict = new TextDecoder('utf-8', { fatal: true });
    try {
      return { text: strict.decode(bytes) };
    } catch {
      const end = growing ? bytes.lastIndexOf(0x0a) + 1 : -1;
      if (end <= 0 || end === bytes.length) return { error: 'not valid UTF-8' };
      try {
        return { text: strict.decode(bytes.subarray(0, end)) + new TextDecoder('utf-8').decode(bytes.subarray(end)) };
      } catch {
        return { error: 'not valid UTF-8' };
      }
    }
  } catch (error) {
    return { error: (error as NodeJS.ErrnoException).code ?? 'unreadable' };
  } finally {
    await file.close();
  }
}

// The canonical sprint folder and the ids of the sprints that have a ledger (`<id>.jsonl` next to `<id>.toml`),
// the newest MAX_SPRINTS of them.
async function sprintIds(root: string): Promise<{ dir: string; ids: string[] } | undefined> {
  try {
    const dir = await realpath(join(root, SPRINT_DIR));
    if (!isWithin(root, dir)) return undefined;
    const names = await readdir(dir);
    const ids = names.filter((n) => n.endsWith('.jsonl')).map((n) => n.slice(0, -'.jsonl'.length)).filter((id) => SPRINT_ID.test(id)).sort();
    return { dir, ids: ids.slice(-MAX_SPRINTS) };
  } catch {
    return undefined;
  }
}

export class SprintReader {
  constructor(private readonly root: string) {}

  async read(): Promise<SprintSnapshot[]> {
    const root = await realpath(this.root);
    const found = await sprintIds(root);
    if (!found) return [];
    const out: SprintSnapshot[] = [];
    for (const id of found.ids) {
      const planRead = await readBounded(found.dir, `${id}.toml`, MAX_SPRINT_FILE_BYTES);
      const ledgerRead = await readBounded(found.dir, `${id}.jsonl`, MAX_LEDGER_BYTES, true);
      const errors = {
        plan: 'error' in planRead ? planRead.error : 'missing' in planRead ? 'missing' : undefined,
        ledger: 'error' in ledgerRead ? ledgerRead.error : undefined,
      };
      out.push(snapshotOf(id, 'text' in planRead ? planRead.text : undefined, 'text' in ledgerRead ? ledgerRead.text : undefined, errors));
    }
    return out;
  }
}
