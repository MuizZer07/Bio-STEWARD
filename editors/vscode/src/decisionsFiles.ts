// P6 Decisions: find the project's decisions logs on disk, without `vscode`, so the unit tests run it on
// real folders. Read-only: the log's text is never read here (it is opened in the editor as it is), and nothing is
// written or created. A log counts as found as CLI 0.20.6 `fsutil.iter_repo_files` would list it (U09): a regular
// file inside the project, reached without a link and not through `.git`. The same check runs again when it is opened.
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { unlinkedFile } from './cli/paths';
import { decisionsSettings, expandLogs, isGlob, MAX_DECISION_LOGS, type DecisionLog, type DecisionsState } from './model/decisions';
import { globBase, globMatch } from './model/tasks';
import { MAX_WALKED, walk } from './taskFiles';

const isRegularFile = async (root: string, path: string): Promise<boolean> => (await unlinkedFile(root, path)) !== undefined;

export async function findDecisionLogs(root: string): Promise<DecisionsState> {
  let toml: string;
  try {
    toml = await readFile(join(root, 'steward.toml'), 'utf8');
  } catch {
    return { kind: 'unreadable', reason: 'steward.toml could not be read' };
  }
  const read = decisionsSettings(toml);
  if (read.kind === 'unreadable') return { kind: 'unreadable', reason: `steward.toml: ${read.reason}` };
  const { settings } = read;
  const globs = settings.patterns.filter(isGlob);
  const files = new Set<string>();
  const budget: { left: number; truncated?: boolean } = { left: MAX_WALKED };
  for (const base of [...new Set(globs.map(globBase))]) await walk(root, base, files, budget);
  const expanded = expandLogs(settings.patterns, [...files]);
  // A glob is unmatched only when it matches no file at all (a file an earlier pattern listed still counts).
  const unmatched = globs.filter((pattern) => ![...files].some((file) => globMatch(file, pattern)));
  const listed = expanded.slice(0, MAX_DECISION_LOGS);
  const logs = await Promise.all(listed.map(async (log): Promise<DecisionLog> => ({ ...log, exists: await isRegularFile(root, log.path) })));
  return { kind: 'ready', settings, logs, unmatched, more: expanded.length - listed.length, truncated: budget.truncated };
}
