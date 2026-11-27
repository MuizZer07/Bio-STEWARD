// P3 Tasks (reduced): the task files on disk, without `vscode`, so the unit tests run it on real folders.
//
// Only the folders the task globs start from are walked (each glob's fixed prefix), as CLI 0.20.6
// `fsutil.iter_repo_files` lists files (U09): the prefix itself is reached without a link and never through `.git`,
// no link is followed below it, `.git` is skipped at every depth, and only regular files count. Each file's text is
// read for its Status and ID lines only. Read-only: nothing here writes.
import { constants } from 'node:fs';
import { open, readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { unlinkedFile, unlinkedFolder } from './cli/paths';
import {
  globBase, idLine, MAX_TASK_FILES, selectTaskFiles, statusLine, statusValue, taskSettings, type TaskFile, type TaskListState,
} from './model/tasks';

export const TASK_FILE_LIMIT_BYTES = 1024 * 1024;
// At most this many entries are looked at under the task folders (a guard against a huge tree).
export const MAX_WALKED = 20_000;

// Also used by src/decisionsFiles.ts (P6), which expands decisions-log globs the same way. `budget.truncated` is
// set when the entry limit stopped the walk.
export async function walk(root: string, base: string, out: Set<string>, budget: { left: number; truncated?: boolean }): Promise<void> {
  // The canonical root, when the walk's first folder is reached without a link.
  const top = await unlinkedFolder(root, '');
  if (!top || !await unlinkedFolder(root, base)) return;
  const stack: string[] = [base];
  while (stack.length) {
    if (budget.left <= 0) {
      budget.truncated = true;
      return;
    }
    const rel = stack.pop()!;
    const entries = await readdir(rel ? join(top, rel) : top, { withFileTypes: true }).catch(() => []);
    for (const entry of entries) {
      if (--budget.left <= 0) {
        budget.truncated = true;
        return;
      }
      if (entry.name === '.git') continue;
      const child = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) stack.push(child);
      else if (entry.isFile()) out.add(child);
    }
  }
}

async function readSmall(path: string): Promise<string> {
  const file = await open(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  try {
    const status = await file.stat();
    if (!status.isFile()) throw new Error('not a file');
    if (status.size > TASK_FILE_LIMIT_BYTES) throw new Error(`larger than ${TASK_FILE_LIMIT_BYTES} bytes`);
    return new TextDecoder('utf-8', { fatal: true }).decode(await file.readFile());
  } finally {
    await file.close();
  }
}

export async function listTaskFiles(root: string): Promise<TaskListState> {
  let toml: string;
  try {
    toml = await readFile(join(root, 'steward.toml'), 'utf8');
  } catch {
    return { kind: 'unreadable', reason: 'steward.toml could not be read' };
  }
  const read = taskSettings(toml);
  if (read.kind === 'unreadable') return { kind: 'unreadable', reason: `steward.toml: ${read.reason}` };
  const { settings } = read;
  const found = new Set<string>();
  const budget: { left: number; truncated?: boolean } = { left: MAX_WALKED };
  for (const base of [...new Set(settings.specs.map(globBase))]) await walk(root, base, found, budget);
  const paths = selectTaskFiles([...found], settings);
  const listed = paths.slice(0, MAX_TASK_FILES);
  const files = await Promise.all(listed.map(async (path): Promise<TaskFile> => {
    const inside = await unlinkedFile(root, path);
    if (!inside) return { path, unreadable: 'reached through a link, or not a regular file inside the project' };
    try {
      const text = await readSmall(inside);
      return { path, status: statusLine(text), value: statusValue(text), id: idLine(text) };
    } catch (error) {
      return { path, unreadable: error instanceof Error ? error.message : String(error) };
    }
  }));
  return { kind: 'ready', settings, files, more: paths.length - listed.length, truncated: budget.truncated };
}
