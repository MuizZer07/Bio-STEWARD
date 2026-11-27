// The live sprint view, minimal (S9; DESIGN_vscode_extension_v0.4 §1, §2, §4; VX22). Pure: no VS Code, no I/O.
//
// Everything shown comes from two files only (T12, decision D1: no git):
// - the sprint file `development/sprints/<id>.toml` (titles, order, limits, window, dispatch);
// - the sprint ledger `development/sprints/<id>.jsonl`, written by `steward sprint` (states, orders, checks, times,
//   and the commit it records when a task ends).
// Commits and changed files during a task come later from the CLI (`sprint status --format json`, STW-052).
//
// The task states and their words are the CLI's own. They are folded from the ledger with the same rules as
// `steward sprint status` (0.20.6); `ready` and `blocked` (and `planned` before any entry) are derived by those
// rules, and the view labels them as derived. The sprint file is validated as the pinned CLI validates it
// (sprint.py: SprintFile). The hash chain is not re-verified here (that is the CLI's job, `steward ledger verify`);
// a line that is not a valid ledger entry is shown as "unreadable", the fold stops there, and every surface marks
// the states as incomplete. No model is called and nothing is written.
import type { ViewNode } from './views';
import { isFloat, parseToml, TomlDateTime, type TomlTable, type TomlValue } from './toml';

export const SPRINT_DIR = 'development/sprints';
// `steward run` exits with this when a limit (wall time, no CPU progress, memory, disk) stopped the job: the
// watchdog (runner EXIT_LIMIT in CLI 0.20.6). The sprint ledger records it as "steward run exited 124".
export const WATCHDOG_EXIT = 124;
export const MAX_SPRINT_FILE_BYTES = 1024 * 1024;
export const MAX_LEDGER_BYTES = 16 * 1024 * 1024;
// Work bounds per refresh (T11-03). The CLI sets none of these; a sprint past one is shown as unreadable or
// incomplete, never half-read as if it were whole.
export const MAX_TASKS = 500;
export const MAX_DEPENDENCIES = 10_000;
export const MAX_LEDGER_EVENTS = 50_000;

export type TaskStateName = 'planned' | 'ready' | 'running' | 'checking' | 'done' | 'failed' | 'blocked' | 'skipped';
const STATE_NAMES: ReadonlySet<string> = new Set(['planned', 'ready', 'running', 'checking', 'done', 'failed', 'blocked', 'skipped']);
const TERMINAL: ReadonlySet<string> = new Set(['done', 'failed', 'blocked', 'skipped']);
const ADAPTERS: ReadonlySet<string> = new Set(['claude-code', 'codex', 'shell']);
const SIGNATURES: ReadonlySet<string> = new Set(['policy.change', 'spend', 'unseal', 'amend', 'waiver']);

export interface PlanTask {
  readonly id: string;
  readonly title: string;
  readonly agent: string;
  readonly model: string | undefined;
  readonly after: readonly string[];
  readonly wallMinutes: number;
  readonly idleMinutes: number | undefined;
  readonly done: readonly string[];
  readonly worktree: boolean;
}

export interface SprintPlan {
  readonly id: string;
  readonly windowStart: number;
  readonly windowEnd: number;
  readonly maxParallel: number;
  readonly dispatch: 'order' | 'auto';
  readonly milestone: string | undefined;
  readonly tasks: readonly PlanTask[];
  readonly byId: ReadonlyMap<string, PlanTask>;
  // The dispatcher's order (sprint.order in the CLI), computed once.
  readonly order: readonly string[];
}

const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
export const SPRINT_ID = /^[a-z0-9][a-z0-9._-]{0,63}$/;

function isTable(v: TomlValue | undefined): v is TomlTable {
  return typeof v === 'object' && v !== null && !Array.isArray(v) && !(v instanceof TomlDateTime);
}

function onlyKeys(t: TomlTable, allowed: readonly string[], what: string): void {
  const extra = Object.keys(t).filter((k) => !allowed.includes(k));
  if (extra.length) throw new Error(`${what} has unknown field(s) ${extra.join(', ')}`);
}

function str(v: TomlValue | undefined, what: string): string {
  if (typeof v !== 'string') throw new Error(`${what} is not text`);
  return v;
}

function optionalStr(v: TomlValue | undefined, what: string): string | undefined {
  return v === undefined ? undefined : str(v, what);
}

// The CLI's `Text`: not empty, not a sentinel (TBD, unknown).
function textField(v: TomlValue | undefined, what: string): string {
  const s = str(v, what);
  if (s === 'TBD' || s === 'unknown' || !s.trim()) throw new Error(`${what} is empty or a sentinel`);
  return s;
}

function strings(v: TomlValue | undefined, what: string): string[] {
  if (v === undefined) return [];
  if (!Array.isArray(v) || !v.every((x) => typeof x === 'string')) throw new Error(`${what} is not a list of text`);
  return v as string[];
}

function positive(v: TomlValue | undefined, fallback: number | undefined, what: string): number | undefined {
  if (v === undefined) return fallback;
  if (typeof v !== 'number' || !(v > 0) || !Number.isFinite(v)) throw new Error(`${what} is not a positive number`);
  return v;
}

function instant(v: TomlValue | undefined, what: string): number {
  if (!(v instanceof TomlDateTime) || v.epochMs === undefined) throw new Error(`${what} is not a date-time with its time zone`);
  return v.epochMs;
}

const TASK_FIELDS = ['id', 'title', 'ref', 'agent', 'model', 'prompt', 'command', 'after', 'worktree', 'limits', 'done', 'needs'];

// The sprint file, validated as the pinned CLI validates it (sprint.py: Window, Limits, Task, SprintMeta,
// SprintFile): unknown fields, types, the window order, max_parallel a whole number from 1 to 16, the adapters,
// at least one done-command, the task graph and its cycles. Anything malformed throws.
export function parsePlan(text: string): SprintPlan {
  const doc = parseToml(text);
  onlyKeys(doc, ['schema', 'sprint', 'task'], 'the sprint file');
  if (doc.schema !== 'steward.sprint/0.1') throw new Error('schema is not steward.sprint/0.1');
  const meta = doc.sprint;
  if (!isTable(meta)) throw new Error('no [sprint] table');
  onlyKeys(meta, ['id', 'window', 'max_parallel', 'dispatch', 'milestone'], '[sprint]');
  const id = str(meta.id, 'sprint.id');
  if (!SPRINT_ID.test(id)) throw new Error('sprint.id is not a sprint id');
  if (!isTable(meta.window)) throw new Error('sprint.window is missing');
  onlyKeys(meta.window, ['start', 'end'], 'sprint.window');
  const windowStart = instant(meta.window.start, 'window.start');
  const windowEnd = instant(meta.window.end, 'window.end');
  if (windowEnd <= windowStart) throw new Error('the window ends before it starts');
  const mp = meta.max_parallel;
  if (mp !== undefined && (typeof mp !== 'number' || isFloat(meta, 'max_parallel') || !Number.isInteger(mp) || mp < 1 || mp > 16)) {
    throw new Error('max_parallel is not a whole number from 1 to 16');
  }
  const maxParallel = typeof mp === 'number' ? mp : 1;
  const dispatch = meta.dispatch === undefined ? 'order' : meta.dispatch;
  if (dispatch !== 'order' && dispatch !== 'auto') throw new Error('dispatch is not order or auto');
  const list = doc.task === undefined ? [] : doc.task;
  if (!Array.isArray(list) || !list.every(isTable)) throw new Error('task is not a list of tables');
  if (list.length > MAX_TASKS) throw new Error(`more than ${MAX_TASKS} tasks (the view's limit)`);
  let edges = 0;
  const tasks = (list as TomlTable[]).map((t, i): PlanTask => {
    const tid = str(t.id, `task ${i + 1} id`);
    if (!TASK_ID.test(tid)) throw new Error(`task ${i + 1} id is not a task id`);
    onlyKeys(t, TASK_FIELDS, `task ${tid}`);
    const limits = t.limits === undefined ? {} : t.limits;
    if (!isTable(limits)) throw new Error(`task ${tid} limits is not a table`);
    onlyKeys(limits, ['wall_minutes', 'idle_minutes'], `task ${tid} limits`);
    const agent = t.agent === undefined ? 'shell' : str(t.agent, `task ${tid} agent`);
    if (!ADAPTERS.has(agent)) throw new Error(`task ${tid} agent is not claude-code, codex or shell`);
    optionalStr(t.ref, `task ${tid} ref`);
    optionalStr(t.prompt, `task ${tid} prompt`);
    const command = optionalStr(t.command, `task ${tid} command`);
    if (agent === 'shell' && !command) throw new Error(`task ${tid}: the shell adapter needs a command`);
    if (t.worktree !== undefined && typeof t.worktree !== 'boolean') throw new Error(`task ${tid} worktree is not true or false`);
    const done = strings(t.done, `task ${tid} done`);
    if (!done.length) throw new Error(`task ${tid}: done needs at least one command`);
    const needs = strings(t.needs, `task ${tid} needs`);
    if (needs.some((n) => !SIGNATURES.has(n.split(':')[0]))) throw new Error(`task ${tid} needs an unknown signature kind`);
    const after = strings(t.after, `task ${tid} after`);
    edges += after.length;
    if (edges > MAX_DEPENDENCIES) throw new Error(`more than ${MAX_DEPENDENCIES} dependencies (the view's limit)`);
    return {
      id: tid,
      title: textField(t.title, `task ${tid} title`),
      agent,
      model: optionalStr(t.model, `task ${tid} model`),
      after,
      wallMinutes: positive(limits.wall_minutes, 60, `task ${tid} wall_minutes`) ?? 60,
      idleMinutes: positive(limits.idle_minutes, undefined, `task ${tid} idle_minutes`),
      done,
      worktree: t.worktree !== false,
    };
  });
  const byId = new Map(tasks.map((t) => [t.id, t]));
  if (byId.size !== tasks.length) throw new Error('duplicate task ids');
  for (const t of tasks) if (t.after.some((a) => !byId.has(a))) throw new Error(`task ${t.id} waits for an unknown task`);
  const order = dispatchOrder(tasks);
  if (order.length < tasks.length) {
    const placed = new Set(order);
    throw new Error(`the tasks wait for each other in a cycle: ${tasks.filter((t) => !placed.has(t.id)).map((t) => t.id).join(', ')}`);
  }
  return {
    id, windowStart, windowEnd, maxParallel, dispatch, tasks, byId, order,
    milestone: optionalStr(meta.milestone, 'milestone'),
  };
}

// The dispatcher's order: each round takes, in file order, every task whose `after` tasks were placed in earlier
// rounds (sprint.order). Kahn's algorithm by rounds: O(tasks + dependencies), not a rescan per round. Tasks in a
// cycle are left out (parsePlan refuses such a file).
function dispatchOrder(tasks: readonly PlanTask[]): string[] {
  const index = new Map(tasks.map((t, i) => [t.id, i]));
  const waiting = tasks.map((t) => new Set(t.after).size);
  const dependants: number[][] = tasks.map(() => []);
  tasks.forEach((t, i) => new Set(t.after).forEach((a) => dependants[index.get(a)!].push(i)));
  let round = tasks.map((_, i) => i).filter((i) => waiting[i] === 0);
  const out: string[] = [];
  while (round.length) {
    const next: number[] = [];
    for (const i of round) {
      out.push(tasks[i].id);
      for (const d of dependants[i]) if (--waiting[d] === 0) next.push(d);
    }
    round = next.sort((a, b) => a - b);
  }
  return out;
}

export function taskOrder(plan: SprintPlan): readonly string[] {
  return plan.order;
}

// ------------------------------------------------------------------------------------------------ the ledger

export interface Check {
  readonly command: string;
  readonly exit: number | null;
  readonly note?: string;
}

export interface LedgerEntry {
  readonly line: number;
  readonly kind: string;
  readonly time: string | undefined;
  readonly epochMs: number | undefined;
  readonly raw: Readonly<Record<string, unknown>>;
}

export interface Ledger {
  readonly entries: readonly LedgerEntry[];
  // The first line that is not a valid ledger entry; the fold stops before it.
  readonly unreadableLine: number | undefined;
  readonly unreadableReason: string | undefined;
  // More than MAX_LEDGER_EVENTS lines: the fold stops at the limit.
  readonly truncated: boolean;
  // A last line without its newline: being written right now; read on the next refresh.
  readonly partialTail: boolean;
}

// An RFC 3339 time with its zone, on a real calendar day (the ledger writes `…Z`).
const LEDGER_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/;

export function ledgerTime(value: string): number | undefined {
  const m = LEDGER_TIME.exec(value);
  if (!m) return undefined;
  const [y, mo, d, h, mi, s, oh, om] = m.slice(1).map((x) => (x === undefined ? 0 : Number(x)));
  const days = [31, (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (mo < 1 || mo > 12 || d < 1 || d > days[mo - 1] || h > 23 || mi > 59 || s > 59 || oh > 23 || om > 59) return undefined;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : undefined;
}

const optionalText = (raw: Record<string, unknown>, key: string) =>
  !(key in raw) || raw[key] === null || typeof raw[key] === 'string';

function checksProblem(v: unknown): string | undefined {
  if (!Array.isArray(v)) return 'checks is not a list';
  for (const c of v) {
    if (typeof c !== 'object' || c === null || Array.isArray(c)) return 'a check is not an object';
    const check = c as Record<string, unknown>;
    if (typeof check.command !== 'string') return 'a check has no command';
    if (check.exit !== null && !Number.isSafeInteger(check.exit)) return 'a check exit is not a whole number or null';
    if (!optionalText(check, 'note')) return 'a check note is not text';
  }
  return undefined;
}

// Why a parsed line is not an entry the fold can use, or undefined. The fields the view reads are checked as the
// CLI writes them (sprint.py: _dispatch, go, hold, skip, stop); other fields (hash, seq, …) are the CLI's own.
export function entryProblem(raw: Record<string, unknown>): string | undefined {
  if (typeof raw.kind !== 'string' || !raw.kind) return 'no kind';
  if ('time' in raw && (typeof raw.time !== 'string' || ledgerTime(raw.time) === undefined)) return 'time is not an RFC 3339 time';
  if (raw.kind === 'state') {
    if (typeof raw.task !== 'string') return 'a state entry without its task';
    if (typeof raw.state !== 'string' || !STATE_NAMES.has(raw.state)) return 'state is not one of the CLI\'s states';
    for (const key of ['branch', 'note', 'worktree', 'commit', 'agent', 'model']) {
      if (!optionalText(raw, key)) return `${key} is not text`;
    }
    if ('checks' in raw && raw.checks !== null) return checksProblem(raw.checks);
  } else if (raw.kind === 'order') {
    if (typeof raw.task !== 'string') return 'an order without its task';
    if (raw.order !== 'go' && raw.order !== 'hold' && raw.order !== 'skip') return 'order is not go, hold or skip';
    if ('retry' in raw && typeof raw.retry !== 'boolean') return 'retry is not true or false';
    if (!optionalText(raw, 'reason') || !optionalText(raw, 'by')) return 'reason or by is not text';
  }
  return undefined;
}

export function parseLedger(text: string): Ledger {
  const lines = text.split('\n');
  const partialTail = lines[lines.length - 1] !== '';
  if (!partialTail) lines.pop();
  const complete = partialTail ? lines.length - 1 : lines.length;
  const entries: LedgerEntry[] = [];
  const stop = (i: number, reason: string): Ledger =>
    ({ entries, unreadableLine: i + 1, unreadableReason: reason, truncated: false, partialTail });
  for (let i = 0; i < complete; i++) {
    if (i >= MAX_LEDGER_EVENTS) return { entries, unreadableLine: undefined, unreadableReason: undefined, truncated: true, partialTail };
    const line = lines[i].replace(/\r$/, '');
    if (!line.trim()) return stop(i, 'an empty line');
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch {
      return stop(i, 'not JSON');
    }
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return stop(i, 'not a JSON object');
    const raw = value as Record<string, unknown>;
    const problem = entryProblem(raw);
    if (problem) return stop(i, problem);
    const time = typeof raw.time === 'string' ? raw.time : undefined;
    entries.push({ line: i + 1, kind: raw.kind as string, time, epochMs: time ? ledgerTime(time) : undefined, raw });
  }
  return { entries, unreadableLine: undefined, unreadableReason: undefined, truncated: false, partialTail };
}

export interface TaskState {
  readonly id: string;
  readonly state: TaskStateName;
  // The state is the view's own derivation from the sprint file and ledger (ready, blocked, planned before any
  // entry, planned again after a retry), by the rules of `steward sprint status`, not a state a ledger line holds.
  readonly derived: boolean;
  readonly go: boolean;
  readonly hold: boolean;
  readonly branch: string | undefined;
  readonly worktree: string | undefined;
  readonly checks: readonly Check[] | undefined;
  readonly note: string | undefined;
  readonly commit: string | undefined;
  readonly agent: string | undefined;
  // Ledger times (ms) of the last `running` state and of the state that ended the task.
  readonly runningAt: number | undefined;
  readonly endedAt: number | undefined;
  readonly runningTime: string | undefined;
  readonly endedTime: string | undefined;
}

const text = (v: unknown) => (typeof v === 'string' ? v : undefined);

function checksOf(v: unknown): Check[] | undefined {
  if (!Array.isArray(v)) return undefined;
  return v.map((c: Record<string, unknown>) => ({
    command: c.command as string,
    exit: c.exit as number | null,
    ...(typeof c.note === 'string' ? { note: c.note } : {}),
  }));
}

// Task -> state, folded from the ledger with the rules of `steward sprint status` (CLI 0.20.6, sprint.states).
// The entries are already validated (entryProblem). Linear in tasks, dependencies and entries.
export function foldStates(plan: SprintPlan, entries: readonly LedgerEntry[]): Map<string, TaskState> {
  type Mutable = { -readonly [K in keyof TaskState]: TaskState[K] };
  const out = new Map<string, Mutable>(plan.tasks.map((t) => [t.id, {
    id: t.id, state: 'planned', derived: true, go: false, hold: false, branch: undefined, worktree: undefined,
    checks: undefined, note: undefined, commit: undefined, agent: undefined, runningAt: undefined, endedAt: undefined,
    runningTime: undefined, endedTime: undefined,
  }]));
  for (const e of entries) {
    const s = out.get(text(e.raw.task) ?? '');
    if (!s) continue;
    if (e.kind === 'order') {
      const order = e.raw.order;
      if (order === 'go') {
        s.go = true;
        s.hold = false;
        if (e.raw.retry && (s.state === 'failed' || s.state === 'blocked')) {
          s.state = 'planned';
          s.derived = true;
        }
      } else if (order === 'hold') {
        s.hold = true;
      } else if (order === 'skip') {
        s.state = 'skipped';
        s.derived = false;
        s.note = text(e.raw.reason);
        s.endedAt = e.epochMs;
        s.endedTime = e.time;
      }
    } else if (e.kind === 'state') {
      const state = e.raw.state as TaskStateName;
      s.state = state;
      s.derived = false;
      if ('branch' in e.raw) s.branch = text(e.raw.branch);
      if ('checks' in e.raw) s.checks = checksOf(e.raw.checks);
      if ('note' in e.raw) s.note = text(e.raw.note);
      if ('worktree' in e.raw) s.worktree = text(e.raw.worktree);
      if ('commit' in e.raw) s.commit = text(e.raw.commit);
      if ('agent' in e.raw) s.agent = text(e.raw.agent);
      if (state === 'running') {
        s.runningAt = e.epochMs;
        s.runningTime = e.time;
        s.endedAt = undefined;
        s.endedTime = undefined;
      } else if (TERMINAL.has(state)) {
        s.endedAt = e.epochMs;
        s.endedTime = e.time;
      }
    }
  }
  // Dependants of a failed or blocked task are blocked, transitively: the CLI's fixed point, reached by one walk
  // from the failed and blocked tasks along the dependants.
  const dependants = new Map<string, string[]>(plan.tasks.map((t) => [t.id, []]));
  for (const t of plan.tasks) for (const a of new Set(t.after)) dependants.get(a)!.push(t.id);
  const stack = plan.tasks.filter((t) => ['failed', 'blocked'].includes(out.get(t.id)!.state)).map((t) => t.id);
  while (stack.length) {
    for (const d of dependants.get(stack.pop()!)!) {
      const s = out.get(d)!;
      if (s.state === 'planned' || s.state === 'ready') {
        s.state = 'blocked';
        s.derived = true;
        s.note = 'a task it waits for failed';
        stack.push(d);
      }
    }
  }
  for (const t of plan.tasks) {
    const s = out.get(t.id)!;
    if (s.state === 'planned' && t.after.every((a) => ['done', 'skipped'].includes(out.get(a)!.state))) {
      s.state = 'ready';
      s.derived = true;
    }
  }
  return out as Map<string, TaskState>;
}

// ------------------------------------------------------------------------------------------------ snapshot

export interface SprintSnapshot {
  readonly id: string;
  readonly file: string;
  readonly ledgerFile: string;
  readonly plan: SprintPlan | undefined;
  readonly planError: string | undefined;
  readonly ledger: Ledger | undefined;
  readonly ledgerError: string | undefined;
  readonly states: ReadonlyMap<string, TaskState>;
  readonly stopped: LedgerEntry | undefined;
  // Why the states may be incomplete (an unreadable ledger line, a ledger the view could not read in full), or
  // undefined. Every surface says so, and no notification is sent from such a snapshot.
  readonly incomplete: string | undefined;
}

export function snapshotOf(id: string, planText: string | undefined, ledgerText: string | undefined,
  errors: { plan?: string; ledger?: string } = {}): SprintSnapshot {
  let plan: SprintPlan | undefined;
  let planError = errors.plan;
  if (planText !== undefined && !planError) {
    try {
      plan = parsePlan(planText);
      if (plan.id !== id) {
        planError = `the file declares sprint ${plan.id}`;
        plan = undefined;
      }
    } catch (error) {
      planError = error instanceof Error ? error.message : String(error);
    }
  }
  const ledger = ledgerText === undefined ? undefined : parseLedger(ledgerText);
  const states = plan && ledger ? foldStates(plan, ledger.entries) : new Map<string, TaskState>();
  let stopped: LedgerEntry | undefined;
  for (let i = (ledger?.entries.length ?? 0) - 1; i >= 0 && !stopped; i--) {
    if (ledger!.entries[i].kind === 'stop') stopped = ledger!.entries[i];
  }
  const incomplete = errors.ledger ? `the ledger could not be read (${errors.ledger})`
    : ledger?.unreadableLine !== undefined ? `ledger line ${ledger.unreadableLine} is unreadable; states as of line ${ledger.unreadableLine - 1}`
      : ledger?.truncated ? `the ledger has more than ${MAX_LEDGER_EVENTS} entries; states as of line ${MAX_LEDGER_EVENTS}`
        : undefined;
  return {
    id, file: `${SPRINT_DIR}/${id}.toml`, ledgerFile: `${SPRINT_DIR}/${id}.jsonl`, plan, planError, ledger,
    ledgerError: errors.ledger, states, stopped, incomplete,
  };
}

const opened = (s: SprintSnapshot) => s.ledger?.entries.some((e) => e.kind === 'opened') ?? false;
const live = (t: TaskState) => t.state === 'running' || t.state === 'checking';

// A sprint the view shows: opened by `steward sprint start` and either inside its window or with a task still
// running or checking. An unreadable sprint file with a ledger is shown too, as unreadable, and so is a ledger
// that could not be read.
export function isShown(s: SprintSnapshot, now: number): boolean {
  if (!s.ledger) return s.ledgerError !== undefined && s.plan !== undefined && now < s.plan.windowEnd;
  if (!s.plan) return s.ledger.entries.length > 0 || s.ledger.unreadableLine !== undefined;
  for (const t of s.states.values()) if (live(t)) return true;
  return opened(s) && now < s.plan.windowEnd;
}

// ------------------------------------------------------------------------------------------------ words

export function duration(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

const oneLine = (s: string, max = 120) => {
  const first = s.split(/\r?\n/)[0];
  return first.length > max ? `${first.slice(0, max - 1)}…` : first;
};

function windowText(plan: SprintPlan, now: number): string {
  if (now < plan.windowStart) return `window opens in ${duration(plan.windowStart - now)}`;
  if (now < plan.windowEnd) return `window ends in ${duration(plan.windowEnd - now)}`;
  return 'window ended';
}

const STATE_ICON: Readonly<Record<string, NonNullable<ViewNode['icon']>>> = Object.freeze({
  planned: { codicon: 'circle-large-outline', tone: 'disabled' },
  ready: { codicon: 'circle-large-outline', tone: 'info' },
  running: { codicon: 'sync~spin', tone: 'info' },
  checking: { codicon: 'loading~spin', tone: 'info' },
  done: { codicon: 'pass', tone: 'passed' },
  failed: { codicon: 'error', tone: 'failed' },
  blocked: { codicon: 'circle-slash', tone: 'warning' },
  skipped: { codicon: 'debug-step-over', tone: 'disabled' },
});

export const waitsForOrder = (plan: SprintPlan, t: TaskState) =>
  t.state === 'ready' && plan.dispatch === 'order' && !t.go && !t.hold;

export const orderCommand = (sprint: string, task: string) => `steward sprint go ${sprint} ${task}`;

export function isWatchdogStop(t: TaskState): boolean {
  return t.state === 'failed' && t.note === `steward run exited ${WATCHDOG_EXIT}`;
}

// The state words: the CLI's state, upper-case, with the order and hold flags it keeps beside it.
export function stateText(plan: SprintPlan, t: TaskState, now: number): string {
  const word = t.state.toUpperCase();
  if (live(t)) return t.runningAt !== undefined ? `${word} ${duration(now - t.runningAt)}` : word;
  if (waitsForOrder(plan, t)) return `${word} · ORDER NEEDED`;
  if (t.hold && !TERMINAL.has(t.state)) return `${word} · held`;
  if ((t.state === 'ready' || t.state === 'planned') && t.go) return `${word} · ordered`;
  if (t.state === 'planned') {
    const task = plan.byId.get(t.id);
    return task?.after.length ? `${word} (waits for ${task.after.join(', ')})` : word;
  }
  return word;
}

// Where a state comes from, for the tooltip (T11-09).
export function stateSource(t: TaskState): string {
  if (!t.derived) return 'sprint ledger';
  return t.state === 'planned' ? 'derived: no ledger state yet' : 'derived from the sprint file and ledger, as steward sprint status derives it';
}

function limitsText(task: PlanTask, t: TaskState, now: number): string {
  const idle = task.idleMinutes ? ` · idle watchdog ${task.idleMinutes} min` : '';
  if (t.runningAt === undefined) return `limits: ${task.wallMinutes} min${idle}`;
  const end = live(t) ? now : t.endedAt ?? now;
  const used = Math.max(0, Math.floor((end - t.runningAt) / 60_000));
  return `limits: ${used} of ${task.wallMinutes} min${idle}`;
}

function checkNodes(prefix: string, checks: readonly Check[]): ViewNode[] {
  return checks.map((c, i) => ({
    id: `${prefix}/check/${i}`, kind: 'sprint-check',
    label: c.exit === null ? 'exit —' : `exit ${c.exit}`,
    description: oneLine(c.command, 200) + (c.note ? ` (${c.note})` : ''),
    tooltip: c.command,
    icon: c.exit === 0 ? { codicon: 'pass', tone: 'passed' } : c.exit === null ? { codicon: 'circle-slash', tone: 'warning' } : { codicon: 'error', tone: 'failed' },
  }));
}

export interface SprintEvent {
  readonly epochMs: number;
  readonly time: string;
  readonly text: string;
}

function eventText(e: LedgerEntry): string | undefined {
  const r = e.raw;
  const task = text(r.task) ?? '';
  if (e.kind === 'genesis') return undefined;
  if (e.kind === 'opened') return `sprint opened (dispatch ${text(r.dispatch) ?? '?'})`;
  if (e.kind === 'stop') return `sprint stopped by ${text(r.by) ?? '?'}${r.now ? ' (running tasks too)' : ''}`;
  if (e.kind === 'order') {
    const by = text(r.by) ?? '?';
    if (r.order === 'go') return `${task} ordered by the ${by}${r.retry ? ' (retry)' : ''}`;
    if (r.order === 'hold') return `${task} held by the ${by}`;
    return `${task} skipped by the ${by}${text(r.reason) ? `: ${oneLine(text(r.reason)!, 80)}` : ''}`;
  }
  if (e.kind === 'state') {
    const state = text(r.state) ?? '?';
    if (state === 'running') return `${task} running on ${text(r.branch) ?? '?'}`;
    const checks = checksOf(r.checks);
    const passed = checks ? ` (${checks.filter((c) => c.exit === 0).length} of ${checks.length} checks passed)` : '';
    const note = text(r.note) ? `: ${oneLine(text(r.note)!, 80)}` : '';
    return `${task} ${state}${passed}${note}`;
  }
  return `${e.kind}${task ? ` ${task}` : ''}`;
}

// The last `limit` ledger events, newest first; at equal times the later line first. Reads backwards from the
// end, so a long ledger is not sorted in full.
export function sprintEvents(s: SprintSnapshot, limit = 10): SprintEvent[] {
  const out: { e: SprintEvent; i: number }[] = [];
  const entries = s.ledger?.entries ?? [];
  for (let i = entries.length - 1; i >= 0 && out.length < limit * 4; i--) {
    const e = entries[i];
    const t = eventText(e);
    if (t && e.epochMs !== undefined && e.time) out.push({ e: { epochMs: e.epochMs, time: e.time, text: t }, i });
  }
  return out.sort((a, b) => b.e.epochMs - a.e.epochMs || b.i - a.i).slice(0, limit).map(({ e }) => e);
}

export interface SprintViewOptions {
  readonly now: number;
  // Local clock time for an event line (the tooltip keeps the ledger's own time).
  readonly clock?: (epochMs: number) => string;
}

const defaultClock = (ms: number) => {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

const MID_TASK = 'Commits and changed files during a task are not shown: the view reads no git (they come later from the CLI).';

export function sprintNodes(snapshots: readonly SprintSnapshot[], { now, clock = defaultClock }: SprintViewOptions): ViewNode[] {
  return snapshots.filter((s) => isShown(s, now)).map((s): ViewNode => {
    const prefix = `sprint/${s.id}`;
    const problems: ViewNode[] = [];
    if (s.ledger?.unreadableLine !== undefined) {
      problems.push({
        id: `${prefix}/unreadable`, kind: 'sprint-detail', icon: { codicon: 'warning', tone: 'warning' },
        label: `ledger line ${s.ledger.unreadableLine}: unreadable`,
        description: 'states shown as of the line before (incomplete)',
        tooltip: `${s.ledgerFile} line ${s.ledger.unreadableLine} is not a ledger entry (${s.ledger.unreadableReason ?? 'unreadable'}). ` +
          `The view does not verify the hash chain; steward ledger verify ${s.ledgerFile} does.`,
      });
    }
    if (s.ledger?.truncated) {
      problems.push({ id: `${prefix}/truncated`, kind: 'sprint-detail', icon: { codicon: 'warning', tone: 'warning' },
        label: `ledger: more than ${MAX_LEDGER_EVENTS} entries`, description: 'states shown as of that line (incomplete)' });
    }
    if (s.ledgerError) {
      problems.push({ id: `${prefix}/ledger-error`, kind: 'sprint-detail', icon: { codicon: 'warning', tone: 'warning' },
        label: `ledger: ${s.ledgerError}`, description: 'states unknown (incomplete)' });
    }
    // A last line without its newline is the CLI writing it right now: not unreadable, shown, read again later.
    if (s.ledger?.partialTail && s.ledger.unreadableLine === undefined && !s.ledger.truncated) {
      problems.push({ id: `${prefix}/partial`, kind: 'sprint-detail', icon: { codicon: 'history', tone: 'disabled' },
        label: `ledger line ${s.ledger.entries.length + 1}: still being written`, description: 'read again on the next change' });
    }
    if (!s.plan) {
      return {
        id: prefix, kind: 'sprint', label: `SPRINT ${s.id}`, description: 'sprint file unreadable', expanded: true,
        icon: { codicon: 'warning', tone: 'warning' }, tooltip: `${s.file}: ${s.planError ?? 'missing'}`,
        children: [...problems, { id: `${prefix}/plan-error`, kind: 'sprint-detail', label: `${s.file}: ${s.planError ?? 'missing'}` }],
      };
    }
    const plan = s.plan;
    const order = plan.order;
    const done = order.filter((id) => s.states.get(id)?.state === 'done').length;
    const parallel = plan.maxParallel === 1 ? 'one at a time' : `up to ${plan.maxParallel} at once`;
    const stopped = s.stopped ? ' · stopped' : '';
    const incomplete = s.incomplete ? ' · ledger incomplete' : '';
    const tasks = s.states.size ? order.map((id): ViewNode => {
      const t = s.states.get(id)!;
      const task = plan.byId.get(id)!;
      const tp = `${prefix}/task/${id}`;
      const children: ViewNode[] = [];
      if (t.branch) children.push({ id: `${tp}/branch`, kind: 'sprint-detail', label: `branch: ${t.branch}`, icon: { codicon: 'git-branch', tone: 'disabled' } });
      if (t.commit && !live(t)) {
        children.push({ id: `${tp}/commit`, kind: 'sprint-detail', label: `commit: ${t.commit.slice(0, 12)}`, icon: { codicon: 'git-commit' },
          tooltip: `${t.commit}: the commit the sprint ledger records when ${id} ended${t.endedTime ? ` (${t.endedTime})` : ''}` });
      }
      if ((t.state !== 'planned' && t.state !== 'ready') || t.runningAt !== undefined) {
        children.push({ id: `${tp}/limits`, kind: 'sprint-detail', label: limitsText(task, t, now), icon: { codicon: 'watch' },
          tooltip: t.runningTime ? `running since ${t.runningTime} (ledger)${t.endedTime ? ` · ended ${t.endedTime}` : ''}` : undefined });
      }
      if (t.checks && !live(t)) children.push(...checkNodes(tp, t.checks));
      if (t.note) children.push({ id: `${tp}/note`, kind: 'sprint-detail', label: `note: ${oneLine(t.note)}`, tooltip: t.note, icon: { codicon: 'note' } });
      const agent = t.agent ?? task.agent;
      return {
        id: tp, kind: waitsForOrder(plan, t) ? 'sprint-task-waiting' : 'sprint-task',
        label: `${id} ${task.title}`,
        description: `${stateText(plan, t, now)}${live(t) ? ` · ${agent}` : ''}`,
        tooltip: [`${id}: ${task.title}`, `state: ${t.state} (${stateSource(t)})`,
          s.incomplete ? `incomplete: ${s.incomplete}` : undefined,
          live(t) ? MID_TASK : undefined,
          waitsForOrder(plan, t) ? `order it with: ${orderCommand(plan.id, id)}` : undefined].filter(Boolean).join('\n'),
        icon: STATE_ICON[t.state] ?? { codicon: 'question' },
        expanded: live(t),
        children,
        code: id,
      };
    }) : [];
    const events = sprintEvents(s);
    const eventsNode: ViewNode = {
      id: `${prefix}/events`, kind: 'sprint-events', label: 'Last events', expanded: true, icon: { codicon: 'history' },
      children: events.map((e, i) => ({
        id: `${prefix}/events/${i}`, kind: 'sprint-event', label: `${clock(e.epochMs)} ${e.text}`,
        tooltip: `${e.time} (sprint ledger)`,
      })),
    };
    return {
      id: prefix, kind: 'sprint', expanded: true,
      label: `SPRINT ${plan.id}`,
      description: `${windowText(plan, now)} · ${done} of ${order.length} done · ${parallel}${stopped}${incomplete}`,
      tooltip: [`${s.file} and ${s.ledgerFile}; read-only, no git`, s.incomplete ? `Incomplete: ${s.incomplete}` : undefined]
        .filter(Boolean).join('\n'),
      icon: s.incomplete ? { codicon: 'warning', tone: 'warning' } : { codicon: 'rocket' },
      children: [...problems, ...tasks, eventsNode],
      code: plan.id,
    };
  });
}

// ------------------------------------------------------------------------------------------------ status bar

export interface SprintStatus {
  readonly visible: boolean;
  readonly text: string;
  readonly tooltip: string;
  readonly accessibility: string;
}

// `▶ T01 12 min · 1/12` while a task runs (`… checking …` while its done-commands run); hidden otherwise.
// `· incomplete` is added when the ledger could not be read in full.
export function sprintStatus(snapshots: readonly SprintSnapshot[], now: number): SprintStatus {
  for (const s of snapshots) {
    if (!s.plan || !isShown(s, now)) continue;
    const order = s.plan.order;
    const running = order.map((id) => s.states.get(id)).filter((t): t is TaskState => t !== undefined && live(t));
    if (!running.length) continue;
    const first = running[0];
    const done = order.filter((id) => s.states.get(id)?.state === 'done').length;
    const elapsed = first.runningAt !== undefined ? ` ${duration(now - first.runningAt)}` : '';
    const checking = first.state === 'checking' ? ' checking' : '';
    const more = running.length > 1 ? ` +${running.length - 1}` : '';
    const title = s.plan.byId.get(first.id)?.title ?? '';
    const incomplete = s.incomplete ? ' · incomplete' : '';
    return {
      visible: true,
      text: `▶ ${first.id}${checking}${elapsed}${more} · ${done}/${order.length}${incomplete}`,
      tooltip: `Sprint ${s.id}: ${first.id} ${title} is ${first.state}${elapsed ? ` for${elapsed}` : ''}; ${done} of ${order.length} done.` +
        `${s.incomplete ? ` Incomplete: ${s.incomplete}.` : ''} Click to show the sprint.`,
      accessibility: `Sprint ${s.id}, ${first.id} ${first.state}${elapsed}, ${done} of ${order.length} done${s.incomplete ? ', ledger incomplete' : ''}`,
    };
  }
  return { visible: false, text: '', tooltip: '', accessibility: '' };
}

// ------------------------------------------------------------------------------------------------ notifications

export type NoticeKind = 'finished' | 'waiting' | 'watchdog';

export interface Notice {
  readonly kind: NoticeKind;
  readonly sprint: string;
  readonly task: string;
  readonly message: string;
  readonly level: 'info' | 'warning';
}

// The three notifications (design v0.4 §1): a task finished (done or failed), a task waits for an order, the
// watchdog stopped a task. Only for changes between two reads of the same sprint, never on the first read, and
// never from a snapshot whose ledger was not read in full (its states may be out of date).
export function notices(before: SprintSnapshot | undefined, after: SprintSnapshot): Notice[] {
  if (!before || !before.plan || !after.plan || after.incomplete) return [];
  const plan = after.plan;
  const out: Notice[] = [];
  for (const id of plan.order) {
    const was = before.states.get(id);
    const now = after.states.get(id);
    if (!was || !now) continue;
    const ended = (now.state === 'done' || now.state === 'failed') && (was.state !== now.state || was.endedTime !== now.endedTime);
    if (ended && isWatchdogStop(now)) {
      out.push({ kind: 'watchdog', sprint: plan.id, task: id, level: 'warning',
        message: `Sprint ${plan.id}: the watchdog stopped ${id} (steward run exited ${WATCHDOG_EXIT}: a limit was reached; see the run ledger).` });
    } else if (ended) {
      const checks = now.checks ?? [];
      const passed = checks.filter((c) => c.exit === 0).length;
      out.push({ kind: 'finished', sprint: plan.id, task: id, level: now.state === 'done' ? 'info' : 'warning',
        message: `Sprint ${plan.id}: ${id} ${now.state}${checks.length ? ` (${passed} of ${checks.length} checks passed)` : ''}` +
          `${now.state === 'failed' && now.note ? `: ${oneLine(now.note, 100)}` : ''}${now.state === 'done' && now.branch ? `; ${now.branch} waits for your merge` : ''}.` });
    }
    if (waitsForOrder(plan, now) && !waitsForOrder(before.plan, was)) {
      out.push({ kind: 'waiting', sprint: plan.id, task: id, level: 'info',
        message: `Sprint ${plan.id}: ${id} is waiting for an order: ${orderCommand(plan.id, id)}` });
    }
  }
  return out;
}
