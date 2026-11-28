// P6 Decisions (RELEASE_vscode_0.2.0_SPEC §3; design v0.3 §4.1): **Open DECISIONS.md**.
//
// The panel names the project's decisions log and opens it in the editor; it never parses the log's entries. The
// entries, newest first, come from `steward decisions --format json` (CLI 0.21 and later), which is task E04.
// Which file is the log comes from steward.toml as CLI 0.20.6 reads it (`IntegritySection.decisions`,
// `session.decisions_log`, `integrity.decision_logs`):
//   - with an `[integrity]` table: its `decisions` (a path, a list, or globs), default `development/DECISIONS.md`;
//   - without one: `<[paths] records>/DECISIONS.md`, where `records` defaults to `development`.
// Globs match with the CLI's own glob rules (the ones the Tasks panel uses). Pure: no `vscode` import.
import { fullProblem, type DecisionsDocument, type FullRead, type RecordedDecision } from './full';
import { newestFirst } from './order';
import { escapesRoot, globMatch } from './tasks';
import { parseToml, TomlDateTime, TomlError, type TomlTable, type TomlValue } from './toml';
import type { ViewNode } from './views';

export const DEFAULT_DECISIONS = 'development/DECISIONS.md';
export const DEFAULT_RECORDS = 'development';
// At most this many logs per project are listed (a glob can match many files).
export const MAX_DECISION_LOGS = 50;

export const DECISIONS_SOURCE_NOTE = 'The decisions log steward.toml names (or the CLI\'s default), opened in the ' +
  'editor as it is. Listing its entries and the open questions needs steward 0.21 or newer (`steward decisions ' +
  '--format json`): Upgrade CLI. The extension never writes a decision: you write it in the log.';

// Where the name of the log comes from, in the words the panel shows.
export type DecisionsSource = 'integrity.decisions' | 'integrity-default' | 'paths.records' | 'default';

export interface DecisionsSettings {
  readonly source: DecisionsSource;
  // As configured: paths or globs, relative to the project root, in order.
  readonly patterns: readonly string[];
}

export type DecisionsSettingsResult =
  | { readonly kind: 'ok'; readonly settings: DecisionsSettings }
  | { readonly kind: 'unreadable'; readonly reason: string };

const isTable = (value: TomlValue | undefined): value is TomlTable =>
  typeof value === 'object' && value !== null && !Array.isArray(value) && !(value instanceof TomlDateTime);

export const isGlob = (pattern: string) => /[*?[]/.test(pattern);

export function decisionsSettings(toml: string): DecisionsSettingsResult {
  let parsed: TomlTable;
  try {
    parsed = parseToml(toml);
  } catch (error) {
    return { kind: 'unreadable', reason: error instanceof TomlError ? error.message : 'steward.toml could not be parsed' };
  }
  let settings: DecisionsSettings;
  const integrity = parsed.integrity;
  if (integrity !== undefined) {
    if (!isTable(integrity)) return { kind: 'unreadable', reason: '[integrity] is not a table' };
    const value = integrity.decisions;
    if (value === undefined) {
      settings = { source: 'integrity-default', patterns: [DEFAULT_DECISIONS] };
    } else if (typeof value === 'string') {
      settings = { source: 'integrity.decisions', patterns: [value] };
    } else if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
      settings = { source: 'integrity.decisions', patterns: value as string[] };
    } else {
      return { kind: 'unreadable', reason: '[integrity] decisions is not a path or a list of paths' };
    }
  } else {
    const paths = parsed.paths;
    if (paths !== undefined && !isTable(paths)) return { kind: 'unreadable', reason: '[paths] is not a table' };
    const records = paths?.records;
    if (records !== undefined && typeof records !== 'string') return { kind: 'unreadable', reason: '[paths] records is not a path' };
    settings = records === undefined
      ? { source: 'default', patterns: [DEFAULT_DECISIONS] }
      : { source: 'paths.records', patterns: [`${records.replace(/\/+$/, '')}/DECISIONS.md`] };
  }
  if (settings.patterns.some((pattern) => !pattern || escapesRoot(pattern))) {
    return { kind: 'unreadable', reason: 'the decisions log is named outside the project' };
  }
  return { kind: 'ok', settings };
}

export function sourceText(settings: DecisionsSettings): string {
  switch (settings.source) {
    case 'integrity.decisions': return '[integrity] decisions';
    case 'integrity-default': return `[integrity] without decisions: the CLI's default ${DEFAULT_DECISIONS}`;
    case 'paths.records': return '[paths] records, then DECISIONS.md';
    case 'default': return `the CLI's default ${DEFAULT_DECISIONS}`;
  }
}

// Every log, in the order the patterns give, without repeats: a plain path as is, a glob as the project files it
// matches (sorted, as the CLI lists them). `files` are POSIX paths relative to the root.
export function expandLogs(patterns: readonly string[], files: readonly string[]): { path: string; pattern?: string }[] {
  const sorted = [...files].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const out: { path: string; pattern?: string }[] = [];
  const seen = new Set<string>();
  for (const pattern of patterns) {
    const matches = isGlob(pattern) ? sorted.filter((file) => globMatch(file, pattern)).map((path) => ({ path, pattern })) : [{ path: pattern }];
    for (const match of matches) {
      if (seen.has(match.path)) continue;
      seen.add(match.path);
      out.push(match);
    }
  }
  return out;
}

export interface DecisionLog {
  // POSIX, relative to the project root, as configured (or as a glob matched it).
  readonly path: string;
  // The glob that matched it, when it came from one.
  readonly pattern?: string;
  // A regular file inside the project.
  readonly exists: boolean;
}

export type DecisionsState =
  | { readonly kind: 'loading' }
  | {
    readonly kind: 'ready'; readonly settings: DecisionsSettings; readonly logs: readonly DecisionLog[];
    // Globs that matched no file, and logs past MAX_DECISION_LOGS.
    readonly unmatched: readonly string[]; readonly more: number;
    // The walk for the globs stopped at its entry limit, so some logs may be missing.
    readonly truncated?: boolean;
  }
  | { readonly kind: 'unreadable'; readonly reason: string };

export interface DecisionsInput {
  readonly root: string;
  readonly name: string;
  readonly decisions?: DecisionsState;
  // E04: `steward decisions --format json`, when the CLI offers it; the full form.
  readonly doc?: FullRead<DecisionsDocument>;
}

// The log **Open DECISIONS.md** opens: the first one that exists, in the configured order. This is the extension's
// choice, labelled in the panel: CLI 0.20.6's single-path commands use the first configured value
// (`IntegritySection.primary_decisions`), whether or not it exists (U09).
export function firstLog(state: DecisionsState | undefined): DecisionLog | undefined {
  return state?.kind === 'ready' ? state.logs.find((log) => log.exists) : undefined;
}

export function primaryLog(settings: DecisionsSettings): string {
  return settings.patterns[0] ?? DEFAULT_DECISIONS;
}

function logNode(root: string, log: DecisionLog, settings: DecisionsSettings, prefix: string): ViewNode {
  const from = log.pattern === undefined ? sourceText(settings) : `matches ${log.pattern} ([integrity] decisions)`;
  if (!log.exists) {
    return {
      id: `${prefix}/${log.path}`, kind: 'decisions-missing', label: log.path, description: 'not found',
      tooltip: `${log.path}: no such file in the project (named by ${from}). Bio-STEWARD does not create it; ` +
        '`steward init` writes one, or start it yourself.',
      icon: { codicon: 'warning', tone: 'warning' }, root,
    };
  }
  return {
    id: `${prefix}/${log.path}`, kind: 'decisions-log', label: log.path, description: from,
    tooltip: `${log.path}\nThe decisions log, named by ${from}. Open it in Markdown preview or use Open as Text to edit it; ` +
      'its entries are not read here.',
    icon: { codicon: 'book' }, command: 'openDecisionLog', path: `${root}/${log.path}`, root,
  };
}

// ── P6 full form: steward decisions --format json (E04) ──────────────────────────────────────────────────────

export const DECISIONS_COMMAND = 'steward decisions';
export const DECISIONS_FULL_NOTE = 'The decisions log steward.toml names, then what steward decisions reads from the ' +
  'records: the open questions with their options, and every dated decision, newest first. Click a decision to open ' +
  'its log. The extension never writes a decision: you write it in the log.';

// Newest first: the latest date first; on one date, the entry written later in its log first.
export function decisionsNewestFirst(entries: readonly RecordedDecision[]): RecordedDecision[] {
  return newestFirst(entries, (entry) => entry.date, (entry) => `${entry.path} ${String(entry.line).padStart(9, '0')}`);
}

const firstLine = (text: string | null) => (text ?? '').split(/\r?\n/)[0];

function documentNodes(input: DecisionsInput, doc: DecisionsDocument, state: Extract<DecisionsState, { kind: 'ready' }>,
  prefix: string): ViewNode[] {
  const logs = new Set(state.logs.filter((log) => log.exists).map((log) => log.path));
  const opens = (path: string) => (logs.has(path) ? { command: 'openDecisionLog' as const, path: `${input.root}/${path}`, root: input.root } : {});
  const open: ViewNode = {
    id: `${prefix}/open`, kind: 'decisions-group', label: `Open decisions (${doc.open_decisions.length})`,
    description: doc.open_decisions.length ? DECISIONS_COMMAND : `none · ${DECISIONS_COMMAND}`,
    tooltip: `Questions still open in the records (the index page and the handoff), as ${DECISIONS_COMMAND} reads them.`,
    icon: { codicon: 'question', tone: doc.open_decisions.length ? 'warning' : undefined }, expanded: doc.open_decisions.length > 0,
    children: doc.open_decisions.map((item, i): ViewNode => ({
      id: `${prefix}/open/${i}`, kind: 'decisions-entry', label: item.question,
      description: item.options.length ? `${item.options.length} option${item.options.length === 1 ? '' : 's'}` : `${item.path}:${item.line}`,
      tooltip: [item.question, ...item.options.map((option) => `- ${option}`), `${item.path}:${item.line} (${DECISIONS_COMMAND})`].join('\n'),
      icon: { codicon: 'question' }, ...opens(item.path),
      children: item.options.length ? item.options.map((option, j): ViewNode => ({
        id: `${prefix}/open/${i}/${j}`, kind: 'decisions-entry', label: option, description: 'option',
      })) : undefined,
    })),
  };
  const recorded: ViewNode = {
    id: `${prefix}/entries`, kind: 'decisions-group', label: `Decisions (${doc.entries.length})`,
    description: doc.entries.length ? 'newest first' : `none · ${DECISIONS_COMMAND}`,
    tooltip: `Every dated decision ${DECISIONS_COMMAND} reads from the log, newest first.`, icon: { codicon: 'law' }, expanded: true,
    children: decisionsNewestFirst(doc.entries).map((entry, i): ViewNode => ({
      id: `${prefix}/entries/${i}`, kind: 'decisions-entry', label: `${entry.date}: ${entry.title}`,
      description: firstLine(entry.decision ?? entry.quotes[0]?.text ?? null) || entry.path,
      tooltip: [entry.heading, entry.decision ? `Decision: ${entry.decision}` : undefined,
        ...entry.quotes.map((quote) => `${quote.who ?? 'Quote'}: ${quote.text}`),
        entry.consequences ? `Consequences: ${entry.consequences}` : undefined,
        `${entry.path}:${entry.line} (${DECISIONS_COMMAND})`].filter(Boolean).join('\n'),
      icon: { codicon: 'law' }, ...opens(entry.path),
    })),
  };
  return [open, recorded];
}

function projectNodes(input: DecisionsInput, prefix: string): ViewNode[] {
  const state = input.decisions;
  if (!state || state.kind === 'loading') {
    return [{ id: `${prefix}/loading`, kind: 'decisions-note', label: 'Decisions log', description: 'not read yet',
      icon: { codicon: 'loading~spin' } }];
  }
  if (state.kind === 'unreadable') {
    return [{ id: `${prefix}/unreadable`, kind: 'decisions-note', label: 'Decisions log', description: 'not found',
      tooltip: state.reason, icon: { codicon: 'warning', tone: 'warning' } }];
  }
  const nodes = state.logs.map((log) => logNode(input.root, log, state.settings, prefix));
  for (const pattern of state.unmatched) {
    nodes.push({ id: `${prefix}/unmatched/${pattern}`, kind: 'decisions-missing', label: pattern, description: 'no file matches',
      tooltip: `${pattern} ([integrity] decisions) matches no file in the project.`, icon: { codicon: 'warning', tone: 'warning' } });
  }
  if (!state.settings.patterns.length) {
    nodes.push({ id: `${prefix}/empty`, kind: 'decisions-missing', label: 'No decisions log named',
      description: '[integrity] decisions = []', tooltip: 'steward.toml names an empty list of decisions logs.',
      icon: { codicon: 'warning', tone: 'warning' } });
  }
  if (state.more) {
    nodes.push({ id: `${prefix}/more`, kind: 'decisions-note', label: `${state.more} more decisions logs`,
      description: `only the first ${MAX_DECISION_LOGS} are listed` });
  }
  if (state.truncated) {
    nodes.push({ id: `${prefix}/truncated`, kind: 'decisions-note', label: 'Not every folder was looked at',
      description: 'the walk stopped at its entry limit', tooltip: 'Some decisions logs a glob names may be missing here.',
      icon: { codicon: 'warning', tone: 'warning' } });
  }
  if (input.doc?.kind === 'ready') nodes.push(...documentNodes(input, input.doc.doc, state, prefix));
  else if (input.doc && input.doc.kind !== 'none' && input.doc.kind !== 'loading') {
    nodes.push({ id: `${prefix}/doc`, kind: 'decisions-note', label: fullProblem(input.doc.kind, DECISIONS_COMMAND),
      description: 'the entries are not listed', icon: { codicon: 'warning', tone: 'warning' } });
  }
  const first = firstLog(state);
  if (first && first.path !== primaryLog(state.settings)) {
    nodes.push({ id: `${prefix}/policy`, kind: 'decisions-note', label: `Open DECISIONS.md opens ${first.path}`,
      description: 'the first log that exists',
      tooltip: `The extension opens the first log that exists, in the configured order. The CLI's single-path commands ` +
        `use the first configured value, ${primaryLog(state.settings)}.`, icon: { codicon: 'info', tone: 'info' } });
  }
  return nodes;
}

export function decisionsSummary(state: DecisionsState | undefined): string {
  if (!state || state.kind === 'loading') return 'not read yet';
  if (state.kind === 'unreadable') return 'not found';
  const found = state.logs.filter((log) => log.exists).length;
  return found === 1 && state.logs.length === 1 ? state.logs[0].path : `${found} of ${state.logs.length} logs found`;
}

// One project: the note, then its logs. Several: one block per project, in the order given (the Today order).
export function decisionsNodes(inputs: readonly DecisionsInput[]): ViewNode[] {
  if (!inputs.length) return [];
  const full = inputs.every((input) => input.doc?.kind === 'ready');
  const note: ViewNode = {
    id: 'decisions/source', kind: 'decisions-note', label: 'Decisions log',
    description: full ? `named by steward.toml · ${DECISIONS_COMMAND}` : 'named by steward.toml',
    tooltip: full ? DECISIONS_FULL_NOTE : DECISIONS_SOURCE_NOTE, icon: { codicon: 'info', tone: 'info' },
  };
  if (inputs.length === 1) return [note, ...projectNodes(inputs[0], `decisions/${inputs[0].root}`)];
  return [note, ...inputs.map((input): ViewNode => ({
    id: `decisions/${input.root}`, kind: 'decisions-project', label: input.name, description: decisionsSummary(input.decisions),
    tooltip: input.decisions?.kind === 'ready' ? `${input.root}\n${sourceText(input.decisions.settings)}` : input.root,
    icon: { codicon: 'folder' }, expanded: true, root: input.root, children: projectNodes(input, `decisions/${input.root}`),
  }))];
}
