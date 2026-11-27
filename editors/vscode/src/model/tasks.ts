// P3 Tasks in its reduced form (RELEASE_vscode_0.2.0_SPEC §3, AC-P3; design v0.6 §3).
//
// The full form reads the task board as JSON (STW-050, C9), which CLI 0.20.6 does not print. The reduced form lists
// the task files by name and shows each one's `**Status:**` line exactly as written, labelled "read from the file":
// the one explicit format read in 0.2.0. A file without a Status line shows nothing in its place.
//
// What counts as a task file, and which statuses are closed, comes from the `[tasks]` table of steward.toml, with
// the CLI's defaults when it is absent (CLI 0.20.6 `TasksSection`). The status value is found with the pattern the
// CLI uses for R-57 (`process.STATUS_LINE`, which may take the value from the next line), and "closed" with R-57's
// rule: the value's configured status (or the value itself) is one of `closed` (`process._status`). That decides
// only a display grouping (open first), labelled as such; R-57 itself is not applicable without `[tasks]`. What is
// shown is the physical line that holds the label, unchanged (U09, AC-P3). Pure: no `vscode` import.
import { parseToml, TomlDateTime, TomlError, type TomlTable, type TomlValue } from './toml';
import type { ViewNode } from './views';

export const DEFAULT_SPECS: readonly string[] = Object.freeze(['development/tasks/**/*.md']);
export const DEFAULT_STATUSES: readonly string[] = Object.freeze(['proposed', 'on hold', 'GO recorded', 'in progress', 'in review', 'done']);
export const DEFAULT_CLOSED: readonly string[] = Object.freeze(['done']);
// At most this many task files per project are listed; the rest are counted.
export const MAX_TASK_FILES = 500;

export const READ_FROM_FILE = 'read from the file';
export const TASKS_REDUCED_NOTE = 'Reduced form (CLI 0.20.6): the task files, each with its Status line as written ' +
  '(read from the file, not from the CLI). Open tasks come first. The full form, with each task\'s window, owner, ' +
  'implementer and stale marks, needs the task board as JSON (the cockpit CLI).';

// ── steward.toml [tasks] ─────────────────────────────────────────────────────────────────────────────────────

export interface TaskSettings {
  readonly configured: boolean;
  readonly specs: readonly string[];
  readonly archive: readonly string[];
  readonly board?: string;
  readonly statuses: readonly string[];
  readonly closed: readonly string[];
}

export type TaskSettingsResult = { readonly kind: 'ok'; readonly settings: TaskSettings } | { readonly kind: 'unreadable'; readonly reason: string };

const isTable = (value: TomlValue | undefined): value is TomlTable =>
  typeof value === 'object' && value !== null && !Array.isArray(value) && !(value instanceof TomlDateTime);

function stringList(table: TomlTable, key: string, fallback: readonly string[]): readonly string[] | undefined {
  const value = table[key];
  if (value === undefined) return fallback;
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) return undefined;
  return value as string[];
}

// A configured glob that is absolute or climbs out of the project is refused, as the CLI refuses it.
export function escapesRoot(pattern: string): boolean {
  return pattern.startsWith('/') || /^[A-Za-z]:[\\/]/.test(pattern) || pattern.includes('\\') || pattern.split('/').includes('..');
}

export function taskSettings(toml: string): TaskSettingsResult {
  let parsed: TomlTable;
  try {
    parsed = parseToml(toml);
  } catch (error) {
    return { kind: 'unreadable', reason: error instanceof TomlError ? error.message : 'steward.toml could not be parsed' };
  }
  const tasks = parsed.tasks;
  if (tasks === undefined) {
    return { kind: 'ok', settings: { configured: false, specs: DEFAULT_SPECS, archive: [], statuses: DEFAULT_STATUSES, closed: DEFAULT_CLOSED } };
  }
  if (!isTable(tasks)) return { kind: 'unreadable', reason: '[tasks] is not a table' };
  const specs = stringList(tasks, 'specs', []);
  const archive = stringList(tasks, 'archive', []);
  const statuses = stringList(tasks, 'statuses', DEFAULT_STATUSES);
  const closed = stringList(tasks, 'closed', DEFAULT_CLOSED);
  const board = tasks.board;
  if (!specs || !archive || !statuses || !closed || (board !== undefined && typeof board !== 'string')) {
    return { kind: 'unreadable', reason: '[tasks] has a value of the wrong type' };
  }
  if ([...specs, ...archive, ...(board === undefined ? [] : [board])].some(escapesRoot)) {
    return { kind: 'unreadable', reason: '[tasks] names a path outside the project' };
  }
  return { kind: 'ok', settings: { configured: true, specs, archive, board, statuses, closed } };
}

// ── Globs (the CLI's rules: `**/` any folders, `**` anything, `*` and `?` within one segment) ─────────────────

export function globRegExp(pattern: string): RegExp {
  let out = '';
  for (let i = 0; i < pattern.length;) {
    if (pattern.startsWith('**/', i)) {
      out += '(?:[^\\n]*/)?';
      i += 3;
    } else if (pattern.startsWith('**', i)) {
      out += '[^\\n]*';
      i += 2;
    } else if (pattern[i] === '*') {
      out += '[^/]*';
      i += 1;
    } else if (pattern[i] === '?') {
      out += '[^/]';
      i += 1;
    } else {
      const point = String.fromCodePoint(pattern.codePointAt(i) ?? 0);
      out += point.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
      i += point.length;
    }
  }
  // As Python's `re` without DOTALL (CLI 0.20.6 `fsutil._glob_regex`): `.` stops at a line break only, and `[^/]`
  // is one code point (U09).
  return new RegExp(`^${out}$`, 'u');
}

export function globMatch(path: string, pattern: string): boolean {
  return globRegExp(pattern).test(path);
}

// The folder a glob's matches all sit under (its segments before the first wildcard), so only that folder is walked.
export function globBase(pattern: string): string {
  const parts = pattern.split('/');
  const fixed: string[] = [];
  for (const part of parts.slice(0, -1)) {
    if (/[*?]/.test(part)) break;
    fixed.push(part);
  }
  return fixed.join('/');
}

// Of every project file (POSIX paths relative to the root), the task files: matched by a spec glob, not by an
// archive glob, and not the board (as R-57 selects them). Sorted by path.
export function selectTaskFiles(files: readonly string[], settings: TaskSettings): string[] {
  return files.filter((file) => settings.specs.some((glob) => globMatch(file, glob))
    && !settings.archive.some((glob) => globMatch(file, glob)) && file !== settings.board).sort();
}

// ── The Status line ──────────────────────────────────────────────────────────────────────────────────────────

// CLI 0.20.6 `process.STATUS_LINE`, `^\s*[-*]\s*\*\*Status:\*\*\s*(.+?)\s*$` with re.M, as Python reads it: `^` at the
// start or after a line feed, `$` before a line feed or at the end, `.` anything but a line feed, `\s` Python's
// whitespace (JavaScript's without U+FEFF, with U+001C – U+001F and U+0085). `\s*` may cross line breaks.
const PY_SPACE = `(?:[^\\S\\ufeff]|[${String.fromCharCode(0x1c)}-${String.fromCharCode(0x1f)}${String.fromCharCode(0x85)}])`;
const CLI_STATUS = new RegExp(`(?:^|(?<=\\n))${PY_SPACE}*[-*]${PY_SPACE}*\\*\\*Status:\\*\\*${PY_SPACE}*([^\\n]+?)${PY_SPACE}*(?=\\n|$)`, 'u');

// The status value as the CLI reads it for R-57 (it can come from the line after the label, or be a space).
export function statusValue(text: string): string | undefined {
  return CLI_STATUS.exec(text)?.[1];
}

// The physical line that holds the label of the CLI's match, as written (without its line break), for display.
export function statusLine(text: string): string | undefined {
  const match = CLI_STATUS.exec(text);
  if (!match) return undefined;
  const label = text.indexOf('**Status:**', match.index);
  const start = text.lastIndexOf('\n', label) + 1;
  const end = text.indexOf('\n', label);
  return text.slice(start, end < 0 ? undefined : end).replace(/\r$/, '');
}

// The first `- **ID:** …` line's value (for the task-window picker of P4).
export function idLine(text: string): string | undefined {
  return /^\s*[-*]\s*\*\*ID:\*\*\s*`?([^`\s]+)`?/m.exec(text)?.[1];
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// The configured status a Status line holds: the whole value, or the longest configured status followed by a
// qualifier in brackets or after a dash ("in review (left: CI)", "done — merged"). Undefined: none.
export function configuredStatus(value: string, statuses: readonly string[]): string | undefined {
  if (statuses.includes(value)) return value;
  for (const status of [...statuses].sort((a, b) => b.length - a.length)) {
    if (new RegExp(`^${escape(status)}(?:\\s+\\(.*\\)|\\s+[—–-]\\s+.+)$`, 's').test(value)) return status;
  }
  return undefined;
}

// R-57's rule (CLI 0.20.6 `process._status`, then `status not in closed`): the configured status of `statuses` the
// value holds, or else the value itself, is one of `closed`.
export function isClosed(value: string | undefined, settings: Pick<TaskSettings, 'statuses' | 'closed'>): boolean {
  if (value === undefined) return false;
  return settings.closed.includes(configuredStatus(value, settings.statuses) ?? value);
}

// ── The list ─────────────────────────────────────────────────────────────────────────────────────────────────

export interface TaskFile {
  // POSIX, relative to the project root.
  readonly path: string;
  // The physical Status line as written; undefined when the file has none.
  readonly status?: string;
  // The value the CLI's R-57 pattern takes from it (for the open / closed grouping only).
  readonly value?: string;
  readonly id?: string;
  // The file could not be read (too large, not UTF-8, gone).
  readonly unreadable?: string;
}

export type TaskListState =
  | {
    readonly kind: 'ready'; readonly settings: TaskSettings; readonly files: readonly TaskFile[]; readonly more: number;
    // The walk stopped at its entry limit, so some task files may be missing.
    readonly truncated?: boolean;
  }
  | { readonly kind: 'unreadable'; readonly reason: string };

export interface TasksInput {
  readonly root: string;
  readonly name: string;
  readonly tasks?: TaskListState | { readonly kind: 'loading' };
}

const basename = (path: string) => path.slice(path.lastIndexOf('/') + 1);

// Open first (every file not closed, by path), then the closed ones in their own group (by path).
export function orderTasks(files: readonly TaskFile[], settings: TaskSettings): { open: TaskFile[]; closed: TaskFile[] } {
  const sorted = [...files].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return {
    open: sorted.filter((file) => !isClosed(file.value, settings)),
    closed: sorted.filter((file) => isClosed(file.value, settings)),
  };
}

function fileNode(root: string, file: TaskFile, prefix: string): ViewNode {
  const absolute = `${root}/${file.path}`;
  if (file.unreadable) {
    return { id: `${prefix}/${file.path}`, kind: 'task-file', label: basename(file.path), description: 'unreadable',
      tooltip: `${file.path}: ${file.unreadable}`, icon: { codicon: 'warning', tone: 'warning' }, command: 'openTaskFile', path: absolute, root };
  }
  // AC-P3: the Status line unchanged, labelled with where it was read; nothing at all for a file without one.
  return {
    id: `${prefix}/${file.path}`, kind: 'task-file', label: basename(file.path),
    description: file.status === undefined ? undefined : `${file.status} · ${READ_FROM_FILE}`,
    tooltip: file.status === undefined ? file.path : `${file.path}\n${file.status}\n(the line ${READ_FROM_FILE}, as written)`,
    icon: { codicon: 'tasklist' }, command: 'openTaskFile', path: absolute, root,
  };
}

function sourceText(settings: TaskSettings): string {
  const globs = settings.specs.join(', ') || '(no specs)';
  return settings.configured ? `[tasks] specs: ${globs}` : `no [tasks] table: the CLI's default ${globs}`;
}

function projectNodes(input: TasksInput, prefix: string): ViewNode[] {
  const { tasks } = input;
  if (!tasks || tasks.kind === 'loading') {
    return [{ id: `${prefix}/loading`, kind: 'task-note', label: 'Task files', description: 'not read yet',
      icon: { codicon: 'loading~spin' } }];
  }
  if (tasks.kind === 'unreadable') {
    return [{ id: `${prefix}/unreadable`, kind: 'task-note', label: 'Task files', description: 'not listed',
      tooltip: tasks.reason, icon: { codicon: 'warning', tone: 'warning' } }];
  }
  const { open, closed } = orderTasks(tasks.files, tasks.settings);
  const nodes: ViewNode[] = [];
  if (!tasks.files.length) {
    nodes.push({ id: `${prefix}/none`, kind: 'task-note', label: 'No task files', description: sourceText(tasks.settings),
      tooltip: sourceText(tasks.settings) });
    return nodes;
  }
  nodes.push(...open.map((file) => fileNode(input.root, file, `${prefix}/open`)));
  if (closed.length) {
    nodes.push({
      id: `${prefix}/closed`, kind: 'task-group', label: `Closed (${closed.length})`,
      description: `status ${tasks.settings.closed.join(', ')} · display grouping`,
      tooltip: `A display grouping, not a CLI result: files whose Status value is closed by R-57's rule, with ` +
        `${tasks.settings.configured ? '[tasks] statuses and closed' : 'the CLI\'s default statuses (R-57 itself is not applicable without [tasks])'}` +
        `: ${tasks.settings.closed.join(', ')}.`,
      icon: { codicon: 'pass' }, expanded: false,
      children: closed.map((file) => fileNode(input.root, file, `${prefix}/closed`)),
    });
  }
  if (tasks.more) {
    nodes.push({ id: `${prefix}/more`, kind: 'task-note', label: `${tasks.more} more task files`,
      description: `only the first ${MAX_TASK_FILES} are listed`, tooltip: sourceText(tasks.settings) });
  }
  if (tasks.truncated) {
    nodes.push({ id: `${prefix}/truncated`, kind: 'task-note', label: 'Not every folder was looked at',
      description: 'the walk stopped at its entry limit', tooltip: `${sourceText(tasks.settings)}: some task files may be missing.`,
      icon: { codicon: 'warning', tone: 'warning' } });
  }
  return nodes;
}

function summary(tasks: TasksInput['tasks']): string {
  if (!tasks || tasks.kind === 'loading') return 'not read yet';
  if (tasks.kind !== 'ready') return 'not listed';
  const { open, closed } = orderTasks(tasks.files, tasks.settings);
  return `${open.length} open · ${closed.length} closed`;
}

// One project: the note, then its files. Several: one block per project, in the order given (the Today order).
export function tasksNodes(inputs: readonly TasksInput[]): ViewNode[] {
  if (!inputs.length) return [];
  const note: ViewNode = {
    id: 'tasks/reduced', kind: 'task-note', label: 'Reduced form', description: `Status lines ${READ_FROM_FILE}`,
    tooltip: TASKS_REDUCED_NOTE, icon: { codicon: 'info', tone: 'info' },
  };
  if (inputs.length === 1) return [note, ...projectNodes(inputs[0], `tasks/${inputs[0].root}`)];
  return [note, ...inputs.map((input): ViewNode => ({
    id: `tasks/${input.root}`, kind: 'task-project', label: input.name, description: summary(input.tasks),
    tooltip: input.tasks?.kind === 'ready' ? `${input.root}\n${sourceText(input.tasks.settings)}` : input.root,
    icon: { codicon: 'folder' }, expanded: true, children: projectNodes(input, `tasks/${input.root}`),
  }))];
}

// The task IDs a window can be opened for: each file's ID line (open tasks first), without repeats.
export function windowCandidates(tasks: TasksInput['tasks']): { id: string; path: string; status?: string }[] {
  if (tasks?.kind !== 'ready') return [];
  const { open, closed } = orderTasks(tasks.files, tasks.settings);
  const seen = new Set<string>();
  const out: { id: string; path: string; status?: string }[] = [];
  for (const file of [...open, ...closed]) {
    if (!file.id || seen.has(file.id)) continue;
    seen.add(file.id);
    out.push({ id: file.id, path: file.path, status: file.status });
  }
  return out;
}
