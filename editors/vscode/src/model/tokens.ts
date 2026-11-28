// P4 Tokens (RELEASE_vscode_0.2.0_SPEC §3; design v0.6 §3): `steward tokens report --json` of CLI 0.20.6, per task
// window and model, with the totals over the rows the CLI printed.
//
// The CLI reads only the agent logs it is given (`--claude FILE`, `--codex FILE`, `--gemini FILE`); it keeps no list
// of them. The extension passes the files of three machine settings (`bioSteward.tokens.claudeLogs`, `…codexLogs`,
// `…geminiLogs`). With none set, the panel says how to set them and still shows the windows the CLI reports. Every
// number shown is the CLI's; the only arithmetic is the sum of the rows' tokens for the totals, labelled as such.
// Nothing leaves the machine: the CLI reads local files and prints counts. Pure: no `vscode` import.
import { createHash } from 'node:crypto';
import { newestFirst } from './order';
import Ajv from 'ajv';
import { parseJson } from '../cli/output';
import type { ViewNode } from './views';

export const TOKEN_AGENTS = ['claude', 'codex', 'gemini'] as const;
export type TokenAgent = typeof TOKEN_AGENTS[number];

export const AGENT_NAMES: Readonly<Record<TokenAgent, string>> = Object.freeze({
  claude: 'Claude Code', codex: 'Codex', gemini: 'Gemini CLI',
});

export const SETTING_KEYS: Readonly<Record<TokenAgent, string>> = Object.freeze({
  claude: 'bioSteward.tokens.claudeLogs', codex: 'bioSteward.tokens.codexLogs', gemini: 'bioSteward.tokens.geminiLogs',
});

// Where each agent usually keeps its session logs (shown as a hint; never read without a setting).
export const LOG_HINTS: Readonly<Record<TokenAgent, string>> = Object.freeze({
  claude: '~/.claude/projects/<this project\'s folder>',
  codex: '~/.codex/sessions',
  gemini: '~/.gemini/tmp/<this project\'s hash>',
});

export const SOURCE = 'steward tokens report';

// ── steward tokens report --json ─────────────────────────────────────────────────────────────────────────────

export interface TokenModel {
  readonly agent: string;
  readonly model: string | null;
  readonly tokens: number;
  readonly input: number | null;
  readonly output: number | null;
  readonly cache_read: number | null;
  readonly cache_write: number | null;
  readonly cost: number | null;
}

// E04: one window of a task and the record it came from (CLI 0.22 `tokens report --format json`): `task-tokens` (Start
// / Done Task Window), `agents` (the agents ledger), `sprint` (a sprint ledger), `run` (the run ledger), or `all
// activity` (no window recorded).
export interface TokenWindow {
  readonly source: string;
  readonly ledger: string | null;
  readonly start: string;
  readonly end: string | null;
}

export interface TokenTask {
  readonly task: string;
  readonly tokens: number | null;
  readonly cost: number | null;
  readonly status: string;
  readonly issues: readonly string[];
  readonly models: readonly TokenModel[];
  readonly agents: readonly { readonly agent: string; readonly tokens: number }[];
  readonly files_read: readonly { readonly path: string; readonly reads: number }[];
  // With the versioned document only (CLI 0.21 and later); oldest first.
  readonly windows?: readonly TokenWindow[];
}

export interface TokenSource {
  readonly status: string;
  readonly files: readonly { readonly path: string; readonly status: string; readonly issues: readonly string[] }[];
}

export interface TokensReport {
  readonly tasks: readonly TokenTask[];
  readonly sources: Readonly<Record<string, TokenSource>>;
  readonly issues: readonly string[];
  readonly currency: string | null;
}

const text = { type: 'string', maxLength: 1000 } as const;
const texts = { type: 'array', maxItems: 1000, items: text } as const;
const count = { type: 'integer', minimum: 0 } as const;
const nullableCount = { type: ['integer', 'null'], minimum: 0 } as const;
const nullableNumber = { type: ['number', 'null'] } as const;

const ajv = new Ajv({ ownProperties: true });
const validateReport = ajv.compile<TokensReport>({
  type: 'object',
  required: ['tasks', 'sources', 'issues', 'currency'],
  properties: {
    tasks: {
      type: 'array', maxItems: 10000,
      items: {
        type: 'object',
        required: ['task', 'tokens', 'cost', 'status', 'issues', 'models', 'agents'],
        properties: {
          task: text, tokens: nullableCount, cost: nullableNumber, status: text, issues: texts,
          models: {
            type: 'array', maxItems: 1000,
            items: {
              type: 'object', required: ['agent', 'model', 'tokens'],
              properties: {
                agent: text, model: { type: ['string', 'null'], maxLength: 1000 }, tokens: count,
                input: nullableCount, output: nullableCount, cache_read: nullableCount, cache_write: nullableCount, cost: nullableNumber,
              },
            },
          },
          agents: {
            type: 'array', maxItems: 100,
            items: { type: 'object', required: ['agent', 'tokens'], properties: { agent: text, tokens: count } },
          },
          files_read: {
            type: 'array', maxItems: 1000,
            items: { type: 'object', required: ['path', 'reads'], properties: { path: text, reads: count } },
          },
          windows: {
            type: 'array', maxItems: 10000,
            items: {
              type: 'object', required: ['source', 'ledger', 'start', 'end'],
              properties: { source: text, ledger: { type: ['string', 'null'], maxLength: 1000 }, start: text,
                end: { type: ['string', 'null'], maxLength: 1000 } },
            },
          },
        },
      },
    },
    sources: {
      type: 'object', maxProperties: 100,
      additionalProperties: {
        type: 'object', required: ['status', 'files'],
        properties: {
          status: text,
          files: {
            type: 'array', maxItems: 10000,
            items: { type: 'object', required: ['path', 'status', 'issues'], properties: { path: text, status: text, issues: texts } },
          },
        },
      },
    },
    issues: texts,
    currency: { type: ['string', 'null'], maxLength: 100 },
  },
});

export function parseTokensReport(stdout: string): TokensReport | undefined {
  const parsed = parseJson(stdout, validateReport);
  if (parsed.kind !== 'valid') return undefined;
  // Defaults for the optional lists, so the views never meet `undefined`.
  return { ...parsed.value, tasks: parsed.value.tasks.map((task) => ({ ...task, files_read: task.files_read ?? [] })) };
}

// The task rows, newest first: by the start of a task's latest window (CLI 0.21 and later give windows), then by task
// label, highest first (the JSON keeps the CLI's documented order, A to Z).
export function tasksNewestFirst(tasks: readonly TokenTask[]): TokenTask[] {
  const latest = (task: TokenTask) => {
    const starts = (task.windows ?? []).map((w) => Date.parse(w.start)).filter(Number.isFinite);
    return starts.length ? Math.max(...starts) : undefined;
  };
  return newestFirst(tasks, latest, (task) => task.task);
}

// ── Where each agent usually keeps its logs for one project (E04) ──────────────────────────────────────────────
//
// Computed from the project's folder and the home folder only: nothing is read, listed or checked here. The panel
// names the folder where a setting is empty and offers "Use this folder", which writes the machine setting.
//   - Claude Code: ~/.claude/projects/<the project's absolute path, each character other than a letter or a digit
//     replaced by "-">;
//   - Codex: ~/.codex/sessions (one folder for every project);
//   - Gemini CLI: ~/.gemini/tmp/<the SHA-256 of the project's absolute path, in hex>.
// These follow the agents' current log layouts, which may change.
export function logFolderHints(root: string, home: string): Readonly<Record<TokenAgent, string>> {
  const join = (...parts: string[]) => parts.join(home.includes('\\') && !home.includes('/') ? '\\' : '/');
  return Object.freeze({
    claude: join(home, '.claude', 'projects', root.replace(/[^A-Za-z0-9]/g, '-')),
    codex: join(home, '.codex', 'sessions'),
    gemini: join(home, '.gemini', 'tmp', createHash('sha256').update(root).digest('hex')),
  });
}

export type TokensState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly report: TokensReport }
  | { readonly kind: 'not-configured' | 'unreadable' | 'failed' }
  | { readonly kind: 'refused'; readonly message: string };

// The log files the extension passes, per agent, and what it could not use (from src/tokenLogs.ts).
export interface LogSelection {
  readonly files: Readonly<Record<TokenAgent, readonly string[]>>;
  // One line per setting entry that gave no file (missing, not absolute, a link outside, …).
  readonly problems: readonly string[];
  // Entries left out because an agent had more than the limit.
  readonly capped: Readonly<Partial<Record<TokenAgent, number>>>;
  // Per file: the canonical file or folder its setting named (U09; the runner checks it again at the CLI's start).
  readonly boundaries?: Readonly<Record<string, string>>;
}

export const NO_LOGS: LogSelection = Object.freeze({ files: { claude: [], codex: [], gemini: [] }, problems: [], capped: {} });

export function configuredAgents(selection: LogSelection): TokenAgent[] {
  return TOKEN_AGENTS.filter((agent) => selection.files[agent].length > 0);
}

// ── The tree ─────────────────────────────────────────────────────────────────────────────────────────────────

const number = (value: number) => value.toLocaleString('en-US');
const or = (value: number | null | undefined) => (value === null || value === undefined ? 'unavailable' : String(value));

export function costText(cost: number | null, currency: string | null): string {
  return cost === null ? 'estimated cost unavailable' : `estimated cost ${Number(cost.toPrecision(6))} ${currency ?? ''}`.trimEnd();
}

const amount = (value: number | null | undefined) => (value === null || value === undefined ? 'unavailable' : number(value));

// "13,500 tokens · input 13,000 · output 500 · cache read 10,000 · cache write 1,000 · estimated cost 0.02025 USD":
// the CLI's numbers for one model of one task; the cost only where the CLI gives one.
export function modelText(model: TokenModel, currency: string | null): string {
  return [`${number(model.tokens)} tokens`, `input ${amount(model.input)}`, `output ${amount(model.output)}`,
    `cache read ${amount(model.cache_read)}`, `cache write ${amount(model.cache_write)}`,
    ...(model.cost === null ? [] : [costText(model.cost, currency)])].join(' · ');
}

const WINDOW_WORDS: Readonly<Record<string, string>> = Object.freeze({
  'task-tokens': 'started and done by hand', agents: 'agents ledger', sprint: 'sprint ledger', run: 'run ledger',
  'all activity': 'no window recorded',
});

function windowNode(window: TokenWindow, id: string): ViewNode {
  return {
    id, kind: 'tokens-item', label: `${window.start} → ${window.end ?? 'still open'}`,
    description: `${WINDOW_WORDS[window.source] ?? window.source}${window.ledger ? ` · ${window.ledger}` : ''}`,
    tooltip: `A window from ${window.ledger ?? window.source} (${window.source}): the usage logged in it counts for this task.`,
    icon: { codicon: 'clock' },
  };
}

// What a task's total covers: its windows (by record) and the logs the CLI read (by agent).
export function coverText(task: TokenTask, report: TokensReport): string {
  const sources = [...new Set((task.windows ?? []).map((w) => w.ledger ?? WINDOW_WORDS[w.source] ?? w.source))];
  const windows = task.windows ? `${task.windows.length} window${task.windows.length === 1 ? '' : 's'}` +
    (sources.length ? ` from ${sources.join(', ')}` : '') : 'its task windows';
  const logs = Object.entries(report.sources).filter(([, source]) => source.files.length)
    .map(([agent, source]) => `${agent} (${source.files.length} log${source.files.length === 1 ? '' : 's'}, ${source.status})`);
  return `Covers ${windows}; logs read: ${logs.length ? logs.join(', ') : 'none'}.`;
}

function modelNode(model: TokenModel, currency: string | null, id: string): ViewNode {
  return {
    id, kind: 'tokens-model', label: `${model.agent} / ${model.model ?? 'unknown model'}`,
    description: modelText(model, currency),
    tooltip: [`${number(model.tokens)} tokens (input ${or(model.input)}, output ${or(model.output)}, ` +
      `cache read ${or(model.cache_read)}, cache write ${or(model.cache_write)})`, costText(model.cost, currency),
    `From ${SOURCE}.`].join('\n'),
    icon: { codicon: 'symbol-numeric' },
  };
}

// CLI 0.20.6 names the row of every log record when no task window exists "all activity" (`tokens.py`): it is
// attributed to no task and to no project.
export const ALL_ACTIVITY = 'all activity';
export const SHARED_NOTE = 'Shared activity: the agent logs are this machine\'s, the same for every open project. ' +
  'The CLI attributes records to a task window by time, agent, model and session, not by project, so activity of ' +
  'another project in the same period is counted too.';

function taskNode(task: TokenTask, report: TokensReport, prefix: string, root: string): ViewNode {
  const { currency } = report;
  const id = `${prefix}/task/${task.task}`;
  const tokens = task.tokens === null ? 'no counts' : `${number(task.tokens)} tokens`;
  const shared = task.task === ALL_ACTIVITY;
  const children: ViewNode[] = [
    ...task.models.map((model, i) => modelNode(model, currency, `${id}/model/${i}`)),
    ...task.issues.map((issue, i): ViewNode => ({ id: `${id}/issue/${i}`, kind: 'tokens-issue', label: issue,
      icon: { codicon: 'warning', tone: 'warning' } })),
  ];
  if (task.windows?.length) {
    children.push({
      id: `${id}/windows`, kind: 'tokens-group', label: `Windows (${task.windows.length})`, expanded: false,
      description: [...new Set(task.windows.map((w) => WINDOW_WORDS[w.source] ?? w.source))].join(', '),
      tooltip: coverText(task, report), icon: { codicon: 'clock' },
      // Newest first: the CLI lists them oldest first.
      children: [...task.windows].reverse().map((window, i) => windowNode(window, `${id}/windows/${i}`)),
    });
  }
  if (task.files_read.length) {
    children.push({
      id: `${id}/files`, kind: 'tokens-group', label: `Most-read files (${task.files_read.length})`, expanded: false,
      children: task.files_read.map((file, i): ViewNode => ({ id: `${id}/files/${i}`, kind: 'tokens-item', label: file.path,
        description: `${file.reads} read${file.reads === 1 ? '' : 's'}` })),
    });
  }
  const cost = task.cost === null ? '' : ` · ${costText(task.cost, currency)}`;
  return {
    id, root, kind: 'tokens-task', label: task.task,
    description: `${tokens}${cost} · ${task.status}${shared ? ' · shared, not this project\'s alone' : ''}`,
    tooltip: [`${task.task}: ${tokens} (${task.status})`, costText(task.cost, currency), coverText(task, report), ...task.issues,
      `From ${SOURCE}.`, ...(shared ? [SHARED_NOTE] : [])].join('\n'),
    icon: { codicon: task.status === 'available' ? 'pulse' : 'circle-outline', tone: task.status === 'available' ? undefined : 'warning' },
    expanded: task.status !== 'unavailable', children,
  };
}

// The totals: the sum of the tokens of the rows the CLI printed, and per agent / model. Rows without counts add
// nothing and are counted, so a total is never read as complete when it is not.
export interface TokenTotals {
  readonly tokens: number;
  readonly rows: number;
  readonly withoutCounts: number;
  readonly partial: number;
  readonly models: readonly { readonly agent: string; readonly model: string | null; readonly tokens: number }[];
}

export function totals(report: TokensReport): TokenTotals {
  const models = new Map<string, { agent: string; model: string | null; tokens: number }>();
  for (const task of report.tasks) {
    for (const model of task.models) {
      const key = JSON.stringify([model.agent, model.model]);
      const entry = models.get(key) ?? { agent: model.agent, model: model.model, tokens: 0 };
      entry.tokens += model.tokens;
      models.set(key, entry);
    }
  }
  return {
    tokens: report.tasks.reduce((sum, task) => sum + (task.tokens ?? 0), 0),
    rows: report.tasks.length,
    withoutCounts: report.tasks.filter((task) => task.tokens === null).length,
    partial: report.tasks.filter((task) => task.status === 'partial').length,
    models: [...models.values()].sort((a, b) => (a.agent + (a.model ?? '')).localeCompare(b.agent + (b.model ?? ''))),
  };
}

function totalsNode(report: TokensReport, prefix: string): ViewNode {
  const sum = totals(report);
  const gaps = [sum.withoutCounts && `${sum.withoutCounts} without counts`, sum.partial && `${sum.partial} partial`].filter(Boolean);
  const priced = report.tasks.filter((task) => task.cost !== null);
  const cost = priced.length
    ? ` · ${costText(priced.reduce((total, task) => total + (task.cost ?? 0), 0), report.currency)} (${priced.length} of ` +
      `${report.tasks.length} tasks priced)`
    : '';
  return {
    id: `${prefix}/totals`, kind: 'tokens-total', label: 'Total',
    description: `${number(sum.tokens)} tokens · ${sum.rows} task${sum.rows === 1 ? '' : 's'}${gaps.length ? ` (${gaps.join(', ')})` : ''}${cost}`,
    tooltip: `The sum of the tasks' totals of ${SOURCE} below, added up by the extension; each task's total is the CLI's.` +
      (gaps.length ? ' Tasks without counts add nothing, so the total covers only what the logs held.' : '') +
      (cost ? ' The estimated cost adds the tasks the CLI priced; a task with a model it has no price for has none.' : ''),
    icon: { codicon: 'graph' }, expanded: false,
    children: sum.models.map((model, i): ViewNode => ({ id: `${prefix}/totals/${i}`, kind: 'tokens-item',
      label: `${model.agent} / ${model.model ?? 'unknown model'}`, description: `${number(model.tokens)} tokens` })),
  };
}

// E04: "Use this folder" for each agent whose setting is empty: the folder it usually keeps this project's logs in.
// The row's click (and its inline button) writes the machine setting; nothing is read before it.
function useFolderNodes(input: TokensInput, prefix: string): ViewNode[] {
  const hints = input.hints;
  if (!hints) return [];
  return TOKEN_AGENTS.filter((agent) => input.empty?.includes(agent)).map((agent): ViewNode => ({
    id: `${prefix}/use/${agent}`, kind: 'tokens-use-folder', label: `${AGENT_NAMES[agent]}: Use this folder`,
    description: hints[agent],
    tooltip: `${AGENT_NAMES[agent]} usually keeps this project's session logs in ${hints[agent]}. Click to set ` +
      `${SETTING_KEYS[agent]} to it in your user settings (machine scope; a repository cannot set it). Nothing is read ` +
      'before you click; then steward tokens report reads only the logs in that folder, and prints counts only.',
    icon: { codicon: 'folder-opened', tone: 'info' }, command: 'useTokenFolder', path: hints[agent], code: agent,
    root: input.root,
  }));
}

function settingsNode(selection: LogSelection, prefix: string): ViewNode {
  return {
    id: `${prefix}/setup`, kind: 'tokens-setup', label: 'Agent log settings',
    description: 'set where your agents keep their logs',
    tooltip: 'steward tokens report reads only the agent logs it is given. The settings below hold log files or ' +
      'folders (user settings; a repository cannot set them). Nothing leaves this machine.',
    icon: { codicon: 'gear', tone: 'info' }, command: 'openTokenSettings', expanded: selection.problems.length > 0,
    children: [
      ...TOKEN_AGENTS.map((agent): ViewNode => ({
        id: `${prefix}/setup/${agent}`, kind: 'tokens-item', label: AGENT_NAMES[agent], description: SETTING_KEYS[agent],
        tooltip: `${SETTING_KEYS[agent]}: absolute paths of log files or folders, for example ${LOG_HINTS[agent]}. ` +
          'A folder gives its newest .jsonl and .json files.',
        command: 'openTokenSettings',
      })),
      ...selection.problems.map((problem, i): ViewNode => ({ id: `${prefix}/setup/problem/${i}`, kind: 'tokens-issue',
        label: problem, icon: { codicon: 'warning', tone: 'warning' } })),
    ],
  };
}

function sourcesNode(report: TokensReport, selection: LogSelection, prefix: string): ViewNode {
  const agents = Object.keys(report.sources).sort();
  return {
    id: `${prefix}/sources`, kind: 'tokens-group', label: 'Sources',
    description: agents.map((agent) => `${agent} ${report.sources[agent].status}`).join(' · '),
    tooltip: `The logs ${SOURCE} read, as it names them (it never prints their paths).`, icon: { codicon: 'file-text' },
    expanded: false,
    children: [
      ...agents.map((agent): ViewNode => {
        const source = report.sources[agent];
        const capped = selection.capped[agent as TokenAgent];
        return {
          id: `${prefix}/sources/${agent}`, kind: 'tokens-item', label: agent,
          description: `${source.status} · ${source.files.length} file${source.files.length === 1 ? '' : 's'}` +
            (capped ? ` (${capped} older left out)` : ''),
          children: source.files.map((file, i): ViewNode => ({
            id: `${prefix}/sources/${agent}/${i}`, kind: 'tokens-item', label: file.path,
            description: [file.status, ...file.issues].join(' · '),
          })),
        };
      }),
      ...selection.problems.map((problem, i): ViewNode => ({ id: `${prefix}/sources/problem/${i}`, kind: 'tokens-issue',
        label: problem, icon: { codicon: 'warning', tone: 'warning' } })),
    ],
  };
}

function problemText(state: Exclude<TokensState, { kind: 'ready' }>): string {
  switch (state.kind) {
    case 'none':
    case 'loading': return 'not read yet';
    case 'not-configured': return 'not set up (no steward.toml the CLI accepts)';
    case 'unreadable': return 'no readable answer; see the log';
    case 'failed': return 'did not finish; see the log';
    case 'refused': return state.message;
  }
}

export interface TokensInput {
  readonly root: string;
  readonly name: string;
  readonly tokens?: TokensState;
  readonly logs: LogSelection;
  // E04: the agents whose log setting is empty, and the folder each usually keeps this project's logs in.
  readonly empty?: readonly TokenAgent[];
  readonly hints?: Readonly<Record<TokenAgent, string>>;
}

// Whether the report holds a task window from a record: a task row other than "all activity".
export function hasWindows(report: TokensReport): boolean {
  return report.tasks.some((task) => task.task !== ALL_ACTIVITY);
}

// E04: the one sentence an empty panel says, naming the input that is missing, and the button that fixes it.
export const EMPTY_SENTENCES = Object.freeze({
  both: 'Nothing to count yet: no agent log is selected and no task window is recorded; choose Use this folder for ' +
    'your agent, then start a task window or run a sprint task.',
  logs: 'No agent log is selected, so the task windows below have no counts: choose Use this folder for your agent.',
  windows: 'No task window is recorded yet, so usage is not split by task: start one with Start Task Window…, or run ' +
    'a sprint task.',
});

export function emptyState(input: TokensInput): keyof typeof EMPTY_SENTENCES | undefined {
  const state = input.tokens;
  if (state?.kind !== 'ready') return undefined;
  const logs = configuredAgents(input.logs).length > 0;
  const windows = hasWindows(state.report);
  if (!logs && !windows) return 'both';
  if (!logs) return 'logs';
  if (!windows) return 'windows';
  return undefined;
}

function emptyNode(key: keyof typeof EMPTY_SENTENCES, prefix: string): ViewNode {
  return {
    id: `${prefix}/empty`, kind: 'tokens-empty', label: EMPTY_SENTENCES[key],
    tooltip: EMPTY_SENTENCES[key], icon: { codicon: 'lightbulb', tone: 'info' },
    command: key === 'windows' ? 'startTokenWindow' : 'openTokenSettings',
  };
}

function projectNodes(input: TokensInput, prefix: string): ViewNode[] {
  const nodes: ViewNode[] = [];
  const empty = emptyState(input);
  if (empty) nodes.push(emptyNode(empty, prefix));
  nodes.push(...useFolderNodes(input, prefix));
  if (!configuredAgents(input.logs).length) nodes.push(settingsNode(input.logs, prefix));
  const state = input.tokens ?? { kind: 'none' };
  if (state.kind !== 'ready') {
    nodes.push({ id: `${prefix}/state`, kind: 'tokens-issue', label: SOURCE, description: problemText(state),
      icon: state.kind === 'loading' ? { codicon: 'loading~spin' } : state.kind === 'none' ? undefined : { codicon: 'warning', tone: 'warning' },
      command: state.kind === 'none' || state.kind === 'loading' ? undefined : 'showLog' });
    return nodes;
  }
  const { report } = state;
  if (report.tasks.length) nodes.push(totalsNode(report, prefix));
  // Newest first: the latest window first, then the highest task label.
  nodes.push(...tasksNewestFirst(report.tasks).map((task) => taskNode(task, report, prefix, input.root)));
  nodes.push(...report.issues.map((issue, i): ViewNode => ({ id: `${prefix}/issue/${i}`, kind: 'tokens-issue', label: issue,
    description: SOURCE, icon: { codicon: 'warning', tone: 'warning' } })));
  if (configuredAgents(input.logs).length) nodes.push(sourcesNode(report, input.logs, prefix));
  return nodes;
}

export const TOKENS_NOTE = `Each task's tokens, from ${SOURCE}: its total, then its split by agent and model (input, ` +
  'output, cache read, cache write) with the estimated cost where the CLI gives one. The windows come from the ' +
  'project\'s records: each sprint task\'s run (its sprint ledger), each steward run (the run ledger), the agents ' +
  'ledger, and the windows started and done by hand. With no window at all, the CLI reports "all activity". Newest ' +
  `first. ${SHARED_NOTE}`;

// The note on what the rows are, then one project's rows, or one block per project in the order given.
export function tokensNodes(inputs: readonly TokensInput[]): ViewNode[] {
  if (!inputs.length) return [];
  const note: ViewNode = {
    id: 'tokens/note', kind: 'tokens-note', label: 'Per task', description: SOURCE, tooltip: TOKENS_NOTE,
    icon: { codicon: 'info', tone: 'info' },
  };
  if (inputs.length === 1) return [note, ...projectNodes(inputs[0], `tokens/${inputs[0].root}`)];
  return [note, ...inputs.map((input): ViewNode => {
    const state = input.tokens;
    return {
      id: `tokens/${input.root}`, kind: 'tokens-project', label: input.name,
      description: state?.kind === 'ready' ? `${number(totals(state.report).tokens)} tokens` : problemText(state ?? { kind: 'none' }),
      tooltip: input.root, icon: { codicon: 'folder' }, expanded: true, children: projectNodes(input, `tokens/${input.root}`),
    };
  })];
}

// The CLI's task window identifier (CLI 0.20.6 `token_logs.identifier`).
export function isWindowId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$/.test(value);
}
