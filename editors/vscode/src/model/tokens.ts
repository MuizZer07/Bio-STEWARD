// P4 Tokens (RELEASE_vscode_0.2.0_SPEC §3; design v0.6 §3): `steward tokens report --json` of CLI 0.20.6, per task
// window and model, with the totals over the rows the CLI printed.
//
// The CLI reads only the agent logs it is given (`--claude FILE`, `--codex FILE`, `--gemini FILE`); it keeps no list
// of them. The extension passes the files of three machine settings (`bioSteward.tokens.claudeLogs`, `…codexLogs`,
// `…geminiLogs`). With none set, the panel says how to set them and still shows the windows the CLI reports. Every
// number shown is the CLI's; the only arithmetic is the sum of the rows' tokens for the totals, labelled as such.
// Nothing leaves the machine: the CLI reads local files and prints counts. Pure: no `vscode` import.
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

export interface TokenTask {
  readonly task: string;
  readonly tokens: number | null;
  readonly cost: number | null;
  readonly status: string;
  readonly issues: readonly string[];
  readonly models: readonly TokenModel[];
  readonly agents: readonly { readonly agent: string; readonly tokens: number }[];
  readonly files_read: readonly { readonly path: string; readonly reads: number }[];
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

function modelNode(model: TokenModel, currency: string | null, id: string): ViewNode {
  return {
    id, kind: 'tokens-model', label: `${model.agent} / ${model.model ?? 'unknown model'}`,
    description: `${number(model.tokens)} tokens`,
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

function taskNode(task: TokenTask, currency: string | null, prefix: string): ViewNode {
  const id = `${prefix}/task/${task.task}`;
  const tokens = task.tokens === null ? 'no counts' : `${number(task.tokens)} tokens`;
  const shared = task.task === ALL_ACTIVITY;
  const children: ViewNode[] = [
    ...task.models.map((model, i) => modelNode(model, currency, `${id}/model/${i}`)),
    ...task.issues.map((issue, i): ViewNode => ({ id: `${id}/issue/${i}`, kind: 'tokens-issue', label: issue,
      icon: { codicon: 'warning', tone: 'warning' } })),
  ];
  if (task.files_read.length) {
    children.push({
      id: `${id}/files`, kind: 'tokens-group', label: `Most-read files (${task.files_read.length})`, expanded: false,
      children: task.files_read.map((file, i): ViewNode => ({ id: `${id}/files/${i}`, kind: 'tokens-item', label: file.path,
        description: `${file.reads} read${file.reads === 1 ? '' : 's'}` })),
    });
  }
  return {
    id, kind: 'tokens-task', label: task.task, description: `${tokens} · ${task.status}${shared ? ' · shared, not this project\'s alone' : ''}`,
    tooltip: [`${task.task}: ${tokens} (${task.status})`, costText(task.cost, currency), ...task.issues, `From ${SOURCE}.`,
      ...(shared ? [SHARED_NOTE] : [])].join('\n'),
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
  return {
    id: `${prefix}/totals`, kind: 'tokens-total', label: 'Total',
    description: `${number(sum.tokens)} tokens · ${sum.rows} task window${sum.rows === 1 ? '' : 's'}${gaps.length ? ` (${gaps.join(', ')})` : ''}`,
    tooltip: `The sum of the rows of ${SOURCE} below, added up by the extension.` +
      (gaps.length ? ' Rows without counts add nothing, so the total covers only what the logs held.' : ''),
    icon: { codicon: 'graph' }, expanded: false,
    children: sum.models.map((model, i): ViewNode => ({ id: `${prefix}/totals/${i}`, kind: 'tokens-item',
      label: `${model.agent} / ${model.model ?? 'unknown model'}`, description: `${number(model.tokens)} tokens` })),
  };
}

function setupNode(selection: LogSelection, prefix: string): ViewNode {
  return {
    id: `${prefix}/setup`, kind: 'tokens-setup', label: 'No agent logs selected',
    description: 'set where your agents keep their logs',
    tooltip: 'steward tokens report reads only the agent logs it is given. Add the log files or folders of your ' +
      'agents to the settings below (user settings; a repository cannot set them). Nothing leaves this machine.',
    icon: { codicon: 'gear', tone: 'info' }, command: 'openTokenSettings', expanded: true,
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
}

function projectNodes(input: TokensInput, prefix: string): ViewNode[] {
  const nodes: ViewNode[] = [];
  if (!configuredAgents(input.logs).length) nodes.push(setupNode(input.logs, prefix));
  const state = input.tokens ?? { kind: 'none' };
  if (state.kind !== 'ready') {
    nodes.push({ id: `${prefix}/state`, kind: 'tokens-issue', label: SOURCE, description: problemText(state),
      icon: state.kind === 'loading' ? { codicon: 'loading~spin' } : state.kind === 'none' ? undefined : { codicon: 'warning', tone: 'warning' },
      command: state.kind === 'none' || state.kind === 'loading' ? undefined : 'showLog' });
    return nodes;
  }
  const { report } = state;
  nodes.push(totalsNode(report, prefix), ...report.tasks.map((task) => taskNode(task, report.currency, prefix)));
  nodes.push(...report.issues.map((issue, i): ViewNode => ({ id: `${prefix}/issue/${i}`, kind: 'tokens-issue', label: issue,
    description: SOURCE, icon: { codicon: 'warning', tone: 'warning' } })));
  if (configuredAgents(input.logs).length) nodes.push(sourcesNode(report, input.logs, prefix));
  return nodes;
}

// The note on what the rows are, then one project's rows, or one block per project in the order given.
export function tokensNodes(inputs: readonly TokensInput[]): ViewNode[] {
  if (!inputs.length) return [];
  const note: ViewNode = {
    id: 'tokens/note', kind: 'tokens-note', label: 'Per task window', description: SOURCE,
    tooltip: `Rows are the task windows ${SOURCE} --json prints: those opened with steward task start / done, and ` +
      'agent attempts in the agents ledger. With no window yet, the CLI reports "all activity". Each row splits by ' +
      'agent and model, and lists the model names and the relative paths of the files read that the CLI prints. ' +
      `Totals per sprint and per day need the cockpit CLI. ${SHARED_NOTE}`,
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
