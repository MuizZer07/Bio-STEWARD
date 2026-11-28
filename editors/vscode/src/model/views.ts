// Pure view models: project state → Overview and Results tree nodes and the status-bar state (M3, M4).
//
// No rule semantics live here. Statuses, eligibility, reasons and every count are read off the report; the
// only arithmetic is the length of a list the report holds. Nothing here imports `vscode`, so all of it is unit
// tested (test/unit/views.test.ts holds the parity test over every fixture report, AC-3.1, and the rule that a
// scoped run never changes a gate badge, AC-3.2).
import type { Gate, GateRef, Report, ResultItem, Status } from './report';
import { resultCode } from './findings';
import type { TimelineState } from './timeline';
import type { TaskListState } from './tasks';
import type { AuditState } from './today';
import type { TokensState } from './tokens';
import type { ApprovalsState } from './approvals';
import type { DecisionsState } from './decisions';
import type { Capabilities } from '../cli/features';
import type { BoardDocument, DecisionsDocument, FullRead, NextDocument, PendingDocument } from './full';
import type { NotificationsState } from './notifications';
import type { UpgradeState } from './upgrade';
import { formatArgv } from '../cli/upgrade';

// ── State ────────────────────────────────────────────────────────────────────────────────────────────────────

// "current" is never used on CLI 0.20.6: a report is *fresh* until something says otherwise (specification §3).
export type Freshness = 'fresh' | 'stale' | 'unknown';

export interface LoadedReport {
  readonly report: Report;
  readonly freshness: Freshness;
  // A scoped run (`check AREA`, `check --rule`): its gates are never shown as a verdict.
  readonly partial: boolean;
  // What the run was, when the extension started it ("check data"); unknown for a report read from a file.
  readonly scope?: string;
}

export type CliState =
  | { readonly kind: 'detecting' }
  | { readonly kind: 'missing' }
  | { readonly kind: 'invalid-setting' }
  | { readonly kind: 'too-old'; readonly version: string; readonly minimum: string }
  | { readonly kind: 'failed' }
  | {
    readonly kind: 'ready'; readonly version: string; readonly mode: string; readonly newerThanTested: boolean;
    // What the CLI's interface offers (src/cli/features.ts); absent: nothing beyond CLI 0.20.6 (E04).
    readonly capabilities?: Capabilities;
  };

export type RunState = 'none' | 'running' | 'completed' | 'unreadable' | 'not-configured' | 'failed';

export interface ProjectState {
  readonly trusted: boolean;
  // The project's name for views that show one of several projects (S2); the root folder's name by default.
  readonly name?: string;
  readonly cli: CliState;
  readonly run: RunState;
  // The newest full report: the only source of a gate badge.
  readonly full?: LoadedReport;
  // A scoped report newer than `full`; cleared by the next full report.
  readonly partial?: LoadedReport;
  // `steward timeline --json` for the countdown (S3); absent until the CLI is ready.
  readonly timeline?: TimelineState;
  // `steward audit progress --json` for Today and "Where am I?" (0.2.0 P1, P2).
  readonly audit?: AuditState;
  // P3: the task files and their Status lines, read from the files (no CLI call).
  readonly tasks?: TaskListState | { readonly kind: 'loading' };
  // P4: `steward tokens report --json`.
  readonly tokens?: TokensState;
  // P5: the text of `steward authorize pending --all-projects`.
  readonly approvals?: ApprovalsState;
  // P6: the decisions log steward.toml names, found on disk (no CLI call; its entries are not read).
  readonly decisions?: DecisionsState;
  // E04, the full forms (CLI 0.21 and later): `steward next` for Today, `task board` for Tasks, and `authorize pending
  // --format json` for the Approvals cards. Absent when the CLI does not offer them.
  readonly next?: FullRead<NextDocument>;
  readonly board?: FullRead<BoardDocument>;
  readonly pending?: FullRead<PendingDocument>;
  // `steward decisions --format json` for the Decisions panel.
  readonly decisionsDoc?: FullRead<DecisionsDocument>;
  // E03: `steward notifications --format json`.
  readonly notifications?: NotificationsState;
  // E03: `steward upgrade --check --format json` (local only, never --online).
  readonly upgrade?: UpgradeState;
}

export function initialState(trusted: boolean): ProjectState {
  return { trusted, cli: { kind: 'detecting' }, run: 'none' };
}

// On CLI 0.20.6 a scoped run says so only through its gates: not evaluated, reason `partial_check`.
export function isPartialReport(report: Report): boolean {
  return report.verdict.gates.some((gate) => !gate.evaluated && gate.reason === 'partial_check');
}

const stale = (loaded: LoadedReport | undefined): LoadedReport | undefined =>
  loaded && (loaded.freshness === 'fresh' ? { ...loaded, freshness: 'stale' } : loaded);

export function withReport(
  state: ProjectState, report: Report, options: { scope?: string; freshness?: Freshness } = {},
): ProjectState {
  const partial = options.scope !== undefined || isPartialReport(report);
  const loaded: LoadedReport = { report, freshness: options.freshness ?? 'fresh', partial, scope: options.scope };
  // A scoped run never replaces the full verdict; the full verdict is kept, marked stale (design v0.1 §5.3).
  if (partial) return { ...state, run: 'completed', full: stale(state.full), partial: loaded };
  return { ...state, run: 'completed', full: loaded, partial: undefined };
}

export function withRunning(state: ProjectState): ProjectState {
  return { ...state, run: 'running' };
}

// A run that produced no readable report leaves the previous reports in place, marked stale.
export function withRunFailure(state: ProjectState, run: 'unreadable' | 'not-configured' | 'failed'): ProjectState {
  return { ...state, run, full: stale(state.full), partial: stale(state.partial) };
}

// ── Vocabulary (design v0.1 §5.2: never colour alone) ───────────────────────────────────────────────────────

export type Tone = 'passed' | 'failed' | 'warning' | 'info' | 'disabled';

export interface StatusLook {
  readonly glyph: string;
  readonly codicon: string;
  readonly text: string;
  readonly tone: Tone;
}

export const STATUS_LOOK: Readonly<Record<Status, StatusLook>> = Object.freeze({
  PASS: { glyph: '✓', codicon: 'pass', text: 'PASS', tone: 'passed' },
  FAIL: { glyph: '✗', codicon: 'error', text: 'FAIL', tone: 'failed' },
  INCOMPLETE: { glyph: '◐', codicon: 'warning', text: 'INCOMPLETE', tone: 'warning' },
  UNKNOWN: { glyph: '?', codicon: 'question', text: 'UNKNOWN', tone: 'info' },
  NOT_APPLICABLE: { glyph: '–', codicon: 'circle-slash', text: 'NOT APPLICABLE', tone: 'disabled' },
});

// The order of the counts row (design v0.1 §5.1) and of the Results groups (most urgent first).
export const COUNT_ORDER: readonly Status[] = ['PASS', 'FAIL', 'INCOMPLETE', 'UNKNOWN', 'NOT_APPLICABLE'];
export const GROUP_ORDER: readonly Status[] = ['FAIL', 'INCOMPLETE', 'UNKNOWN', 'PASS', 'NOT_APPLICABLE'];

export type GateBadgeText = 'ELIGIBLE' | 'NOT ELIGIBLE' | 'NOT EVALUATED' | 'NOT EVALUATED BY THIS RUN';

export interface GateBadge {
  readonly glyph: string;
  readonly text: GateBadgeText;
  readonly codicon: string;
  readonly tone: Tone;
}

// Gate eligibility is its own badge, read off `gates[]`. Every gate of a partial run reads
// NOT EVALUATED BY THIS RUN, whatever it holds, so a scoped run can never show a verdict.
export function gateBadge(gate: Gate, partialRun: boolean): GateBadge {
  if (partialRun) return { glyph: '–', text: 'NOT EVALUATED BY THIS RUN', codicon: 'circle-slash', tone: 'disabled' };
  if (!gate.evaluated) return { glyph: '–', text: 'NOT EVALUATED', codicon: 'circle-slash', tone: 'disabled' };
  return gate.eligible
    ? { glyph: '✓', text: 'ELIGIBLE', codicon: 'pass', tone: 'passed' }
    : { glyph: '✗', text: 'NOT ELIGIBLE', codicon: 'error', tone: 'failed' };
}

const badgeText = (badge: GateBadge) => `${badge.glyph} ${badge.text}`;

// ── Tree nodes ──────────────────────────────────────────────────────────────────────────────────────────────

export type NodeKind =
  | 'cli' | 'upgrade' | 'run' | 'report' | 'gate' | 'gate-reason' | 'gate-counts' | 'blocking' | 'waived' | 'ref'
  | 'counts' | 'worst' | 'coverage' | 'areas' | 'area' | 'not-evaluated' | 'not-evaluated-item' | 'statement'
  | 'partial' | 'no-full' | 'group' | 'result' | 'detail'
  | 'skills-drift' | 'skills-folder' | 'skills-detail' | 'skill'
  | 'sprint' | 'sprint-task' | 'sprint-task-waiting' | 'sprint-detail' | 'sprint-check' | 'sprint-events' | 'sprint-event'
  | 'today-note' | 'today-project' | 'today-notifications' | 'notification-unread' | 'notification-read'
  | 'today-resume' | 'today-milestone' | 'today-section' | 'today-item'
  | 'task-note' | 'task-project' | 'task-group' | 'task-file'
  | 'tokens-note' | 'tokens-project' | 'tokens-setup' | 'tokens-total' | 'tokens-task' | 'tokens-model' | 'tokens-group'
  | 'tokens-item' | 'tokens-issue' | 'tokens-use-folder' | 'tokens-empty'
  | 'decisions-note' | 'decisions-project' | 'decisions-log' | 'decisions-missing' | 'decisions-group' | 'decisions-entry'
  | 'drift-note' | 'drift-project' | 'drift-milestone' | 'drift-group' | 'drift-item';

export interface ViewNode {
  // Unique within its tree and stable across refreshes of the same report.
  readonly id: string;
  readonly kind: NodeKind;
  readonly label: string;
  readonly description?: string;
  // Plain text; the UI never renders it as markdown or HTML.
  readonly tooltip?: string;
  readonly icon?: { readonly codicon: string; readonly tone?: Tone };
  // Dim the row label (used for read notifications, alongside the word "read" in description and accessibility).
  readonly dimmed?: boolean;
  readonly children?: readonly ViewNode[];
  readonly expanded?: boolean;
  readonly command?: 'runCheck' | 'showLog' | 'checkSkills' | 'installSkills' | 'resume' | 'showTimeline'
    | 'openFile' | 'openTokenSettings' | 'openTaskFile' | 'openDecisionLog' | 'useTokenFolder' | 'startTokenWindow'
    | 'openNotification' | 'upgradeCli';
  // The project root a command acts on (the Today panel shows several projects at once).
  readonly root?: string;
  // The notification ID for `openNotification` and per-item read/unread actions.
  readonly notificationId?: string;
  // The file `openFile` opens (an absolute path inside the project).
  readonly path?: string;
  readonly code?: string;
  readonly next?: string;
  readonly source?: string;
  readonly anchor?: Readonly<{ path: string; line?: number }>;
  readonly ref?: { readonly rule: string; readonly subject: string; readonly status: Status; readonly index?: number };
}

const statusIcon = (status: Status) => ({ codicon: STATUS_LOOK[status].codicon, tone: STATUS_LOOK[status].tone });

function findResult(report: Report, ref: GateRef): number {
  return report.verdict.results.findIndex((r) => r.rule === ref.rule && r.subject === ref.subject && r.status === ref.status);
}

function refNode(report: Report, ref: GateRef, id: string): ViewNode {
  const index = findResult(report, ref);
  const result = index >= 0 ? report.verdict.results[index] : undefined;
  const look = STATUS_LOOK[ref.status];
  return {
    id,
    kind: 'ref',
    label: result ? `${ref.rule} ${result.name}` : ref.rule,
    description: `${look.text} · ${ref.subject}`,
    tooltip: result ? `${look.text}: ${result.reason}` : look.text,
    icon: statusIcon(ref.status),
    ref: { rule: ref.rule, subject: ref.subject, status: ref.status, index: index >= 0 ? index : undefined },
  };
}

function refList(report: Report, kind: 'blocking' | 'waived', refs: readonly GateRef[], prefix: string): ViewNode {
  const title = kind === 'blocking' ? 'Blocking' : 'Waived';
  return {
    id: `${prefix}/${kind}`,
    kind,
    label: `${title} (${refs.length})`,
    description: refs.length ? undefined : 'none',
    children: refs.map((ref, i) => refNode(report, ref, `${prefix}/${kind}/${i}`)),
    expanded: kind === 'blocking' && refs.length > 0,
  };
}

function gateNode(report: Report, gate: Gate, partialRun: boolean, prefix: string): ViewNode {
  const badge = gateBadge(gate, partialRun);
  const id = `${prefix}/gate:${gate.name}`;
  const counted = [
    `${gate.evaluated_count} evaluated`,
    ...(gate.pass_count !== undefined ? [`${gate.pass_count} PASS`] : []),
    ...(gate.not_applicable_count !== undefined ? [`${gate.not_applicable_count} NOT APPLICABLE`] : []),
    `of ${gate.required_count} required`,
  ];
  return {
    id,
    kind: 'gate',
    label: `Gate ${gate.name}`,
    description: `${badgeText(badge)} · ${gate.blocking.length} blocking of ${gate.required_count} required`,
    tooltip: `Gate ${gate.name}: ${badge.text}. Reason: ${gate.reason}`,
    icon: { codicon: badge.codicon, tone: badge.tone },
    expanded: !partialRun && gate.blocking.length > 0,
    children: [
      { id: `${id}/reason`, kind: 'gate-reason', label: 'Reason', description: gate.reason, tooltip: gate.reason },
      { id: `${id}/counts`, kind: 'gate-counts', label: 'Required results', description: counted.join(' · ') },
      refList(report, 'blocking', gate.blocking, id),
      refList(report, 'waived', gate.waived, id),
    ],
  };
}

function countsNode(report: Report, prefix: string): ViewNode {
  const { counts } = report.verdict.summary;
  const parts = COUNT_ORDER.map((s) => `${STATUS_LOOK[s].glyph} ${counts[s]} ${STATUS_LOOK[s].text}`);
  return { id: `${prefix}/counts`, kind: 'counts', label: 'Counts', description: parts.join(' · '), tooltip: parts.join('\n') };
}

function worstNode(report: Report, prefix: string): ViewNode {
  const { worst } = report.verdict.summary;
  return {
    id: `${prefix}/worst`,
    kind: 'worst',
    label: 'Worst status',
    description: `${STATUS_LOOK[worst].glyph} ${STATUS_LOOK[worst].text}`,
    tooltip: 'The worst status of any result. It can differ from a gate\'s eligibility; both are shown.',
    icon: statusIcon(worst),
  };
}

function areaList(id: string, title: string, areas: readonly string[]): ViewNode {
  return {
    id,
    kind: 'areas',
    label: `${title} (${areas.length})`,
    tooltip: areas.join(', ') || 'none',
    children: areas.map((area, i) => ({ id: `${id}/${i}`, kind: 'area' as const, label: area })),
  };
}

function coverageNode(report: Report, prefix: string): ViewNode {
  const { coverage } = report.verdict;
  const configured = coverage.areas?.configured ?? [];
  const notConfigured = coverage.areas?.not_configured ?? [];
  const nothingRecorded = coverage.areas?.nothing_recorded ?? [];
  const total = configured.length + notConfigured.length + nothingRecorded.length;
  // "coverage incomplete", not INCOMPLETE: it is not a result status (design v0.1 §5.3).
  const incomplete = coverage.not_evaluated.length > 0 || nothingRecorded.length > 0;
  const id = `${prefix}/coverage`;
  return {
    id,
    kind: 'coverage',
    label: 'Coverage',
    description: [
      `${configured.length} of ${total} areas configured`,
      `${nothingRecorded.length} nothing recorded`,
      `${coverage.not_evaluated.length} not evaluated`,
      ...(incomplete ? ['coverage incomplete'] : []),
    ].join(' · '),
    tooltip: coverage.statement,
    icon: { codicon: incomplete ? 'warning' : 'info', tone: incomplete ? 'warning' : undefined },
    children: [
      { id: `${id}/statement`, kind: 'statement', label: coverage.statement, tooltip: coverage.statement },
      areaList(`${id}/configured`, 'Configured', configured),
      areaList(`${id}/not-configured`, 'Not configured', notConfigured),
      areaList(`${id}/nothing-recorded`, 'Nothing recorded', nothingRecorded),
      {
        id: `${id}/not-evaluated`,
        kind: 'not-evaluated',
        label: `Not evaluated (${coverage.not_evaluated.length})`,
        children: coverage.not_evaluated.map((item, i) => ({
          id: `${id}/not-evaluated/${i}`, kind: 'not-evaluated-item' as const, label: item.path, description: item.reason,
          tooltip: item.reason,
        })),
      },
    ],
  };
}

function reportNode(loaded: LoadedReport, prefix: string): ViewNode {
  const { envelope, verdict } = loaded.report;
  const head = typeof envelope.git === 'object' && typeof envelope.git.head === 'string' ? envelope.git.head : 'unknown';
  return {
    id: `${prefix}/report`,
    kind: 'report',
    label: 'Report',
    description: `${loaded.freshness} · ${verdict.project} · profile ${verdict.config_profile} · ${envelope.created}`,
    tooltip: [
      `Freshness: ${loaded.freshness}`,
      `Project: ${verdict.project}`,
      `Profile: ${verdict.config_profile}`,
      `Created: ${envelope.created}`,
      `Tool: ${envelope.tool} ${envelope.tool_version}`,
      `Inputs: ${verdict.inputs_digest}`,
      `Git head: ${head}`,
    ].join('\n'),
    icon: { codicon: loaded.freshness === 'fresh' ? 'file' : 'history', tone: loaded.freshness === 'fresh' ? undefined : 'warning' },
  };
}

function cliNode(state: ProjectState): ViewNode[] {
  if (state.cli.kind !== 'ready') return [];
  const newer = state.cli.newerThanTested ? ' · CLI newer than tested' : '';
  return [{
    id: 'cli',
    kind: 'cli',
    label: `steward ${state.cli.version}`,
    description: `${state.cli.mode} mode${newer}`,
    tooltip: state.cli.mode === 'limited'
      ? 'Limited mode: this CLI has no machine interface. Freshness is by file changes only, and explanations are shown as text.'
      : state.cli.mode === 'full'
        ? 'Full mode: this CLI publishes its machine interface (steward interface), and the extension reads what it lists.'
        : `${state.cli.mode} mode`,
    icon: { codicon: 'info' },
  }];
}

const RUN_MESSAGES: Partial<Record<RunState, [string, string, ViewNode['command']]>> = {
  running: ['Running steward check…', 'sync~spin', undefined],
  unreadable: ['Last run: output unreadable', 'warning', 'showLog'],
  'not-configured': ['Last run: not set up (no steward.toml the CLI accepts)', 'warning', 'showLog'],
  failed: ['Last run: the CLI did not finish', 'warning', 'showLog'],
};

function runNode(state: ProjectState): ViewNode[] {
  const message = RUN_MESSAGES[state.run];
  if (!message) return [];
  const [label, codicon, command] = message;
  return [{ id: 'run', kind: 'run', label, icon: { codicon, tone: codicon === 'warning' ? 'warning' : undefined }, command,
    description: command ? 'Show log' : undefined }];
}

export function verdictNodes(loaded: LoadedReport, prefix: string): ViewNode[] {
  const { report } = loaded;
  return [
    reportNode(loaded, prefix),
    ...report.verdict.gates.map((gate) => gateNode(report, gate, loaded.partial, prefix)),
    countsNode(report, prefix),
    worstNode(report, prefix),
    coverageNode(report, prefix),
  ];
}

function partialNode(loaded: LoadedReport): ViewNode {
  return {
    id: 'partial',
    kind: 'partial',
    label: 'Partial run',
    description: `${loaded.scope ?? 'scoped check'} · ${loaded.freshness} · gates not evaluated by this run`,
    tooltip: 'A scoped run checks part of the project. It never changes a gate badge; the gates above are from the last full run.',
    icon: { codicon: 'filter' },
    expanded: true,
    children: verdictNodes(loaded, 'partial'),
  };
}

export type EmptyState =
  | 'untrusted' | 'detecting' | 'no-cli' | 'cli-invalid' | 'cli-too-old' | 'cli-failed'
  | 'no-report' | 'running' | 'unreadable' | 'not-configured' | 'run-failed';

// Why a tree is empty; the UI shows the matching welcome text (package.json `viewsWelcome`).
export function emptyState(state: ProjectState): EmptyState | undefined {
  if (!state.trusted) return 'untrusted';
  switch (state.cli.kind) {
    case 'detecting': return 'detecting';
    case 'missing': return 'no-cli';
    case 'invalid-setting': return 'cli-invalid';
    case 'too-old': return 'cli-too-old';
    case 'failed': return 'cli-failed';
    case 'ready': break;
  }
  if (state.full || state.partial) return undefined;
  switch (state.run) {
    case 'running': return 'running';
    case 'unreadable': return 'unreadable';
    case 'not-configured': return 'not-configured';
    case 'failed': return 'run-failed';
    default: return 'no-report';
  }
}

function upgradeNode(state: ProjectState): ViewNode[] {
  if (state.cli.kind !== 'ready' || state.upgrade?.kind !== 'ready') return [];
  const { check } = state.upgrade;
  if (!check.upgrade_available || !check.latest_version) return [];
  const tooltip = [
    `Installed: steward ${check.installed_version} (${check.install_method})`,
    `Newest known: steward ${check.latest_version}${check.source ? ` (from ${check.source})` : ''}`,
    ...(check.command ? [`Install command: ${formatArgv(check.command)}`] : ['Installer could not be detected by the CLI.']),
    ...(check.note ? [check.note] : []),
    'Click to review the exact command in a modal and run steward upgrade in a terminal.',
  ].join('\n');
  return [{
    id: 'upgrade',
    kind: 'upgrade',
    label: 'Upgrade CLI',
    description: `steward ${check.installed_version} → ${check.latest_version}`,
    tooltip,
    icon: { codicon: 'arrow-circle-up', tone: 'info' },
    command: 'upgradeCli',
  }];
}

export function overviewNodes(state: ProjectState): ViewNode[] {
  if (emptyState(state)) return [];
  return [
    ...cliNode(state),
    ...upgradeNode(state),
    ...runNode(state),
    ...(state.full
      ? verdictNodes(state.full, 'full')
      : [{ id: 'no-full', kind: 'no-full' as const, label: 'No full verdict yet', description: 'Run check',
        command: 'runCheck' as const, icon: { codicon: 'play' } }]),
    ...(state.partial ? [partialNode(state.partial)] : []),
  ];
}

// ── Results tree ────────────────────────────────────────────────────────────────────────────────────────────

export type GroupBy = 'status' | 'gate' | 'file';
export const GROUP_BY: readonly GroupBy[] = ['status', 'gate', 'file'];

const REPOSITORY_LEVEL = 'Repository level';

export function gateTags(report: Report, result: ResultItem, partialRun: boolean): string[] {
  if (partialRun) return [];
  const same = (ref: GateRef) => ref.rule === result.rule && ref.subject === result.subject && ref.status === result.status;
  return report.verdict.gates.flatMap((gate) => [
    ...(gate.blocking.some(same) ? [`blocks gate ${gate.name}`] : []),
    ...(gate.waived.some(same) ? [`waived in gate ${gate.name}`] : []),
  ]);
}

function detailLabel(detail: Record<string, unknown>): { label: string; description?: string } {
  const text = (key: string) => (typeof detail[key] === 'string' ? detail[key] as string : undefined);
  const where = text('path') !== undefined
    ? `${text('path')}${typeof detail.line === 'number' ? `:${detail.line}` : ''}`
    : text('field');
  return { label: text('message') ?? text('code') ?? JSON.stringify(detail), description: where };
}

function resultNode(loaded: LoadedReport, index: number, prefix: string, showSubject: boolean): ViewNode {
  const result = loaded.report.verdict.results[index];
  const id = `${prefix}/result:${index}`;
  const tags = gateTags(loaded.report, result, loaded.partial);
  return {
    id,
    kind: 'result',
    label: `${result.rule} ${result.name}`,
    description: [STATUS_LOOK[result.status].text, ...(showSubject ? [result.subject] : []), ...tags].join(' · '),
    tooltip: [`${STATUS_LOOK[result.status].text}: ${result.reason}`, `Subject: ${result.subject}`, ...tags,
      ...(loaded.freshness === 'fresh' ? [] : [`From a ${loaded.freshness} report`])].join('\n'),
    icon: statusIcon(result.status),
    ref: { rule: result.rule, subject: result.subject, status: result.status, index },
    children: result.details.map((detail, i) => ({
      id: `${id}/detail:${i}`, kind: 'detail' as const, ...detailLabel(detail),
      code: resultCode(result.rule, detail.code),
      anchor: typeof detail.path === 'string'
        ? { path: detail.path, line: typeof detail.line === 'number' ? detail.line : undefined } : undefined,
      ref: { rule: result.rule, subject: result.subject, status: result.status, index },
    })),
  };
}

function group(id: string, label: string, indices: readonly number[], children: ViewNode[], extra: Partial<ViewNode> = {}): ViewNode {
  return { id, kind: 'group', label, description: String(indices.length), children, ...extra };
}

function byStatus(loaded: LoadedReport): ViewNode[] {
  const { results } = loaded.report.verdict;
  return GROUP_ORDER.map((status) => {
    const indices = results.flatMap((r, i) => (r.status === status ? [i] : []));
    const id = `status:${status}`;
    return group(id, `${STATUS_LOOK[status].glyph} ${STATUS_LOOK[status].text}`, indices,
      indices.map((i) => resultNode(loaded, i, id, true)),
      { icon: statusIcon(status), expanded: indices.length > 0 && status !== 'PASS' && status !== 'NOT_APPLICABLE' });
  });
}

function byGate(loaded: LoadedReport): ViewNode[] {
  const { report } = loaded;
  const referenced = new Set<number>();
  const gates = report.verdict.gates.map((gate) => {
    const id = `gate:${gate.name}`;
    const badge = gateBadge(gate, loaded.partial);
    const list = (kind: 'blocking' | 'waived', refs: readonly GateRef[]): ViewNode => {
      const indices = refs.map((ref) => findResult(report, ref));
      for (const i of indices) if (i >= 0) referenced.add(i);
      const listId = `${id}/${kind}`;
      return group(listId, kind === 'blocking' ? 'Blocking' : 'Waived', refs.map((_, i) => i),
        refs.map((ref, i) => indices[i] >= 0
          ? resultNode(loaded, indices[i], listId, true)
          : refNode(report, ref, `${listId}/${i}`)),
        { expanded: kind === 'blocking' && refs.length > 0 });
    };
    return {
      id,
      kind: 'group' as const,
      label: `Gate ${gate.name}`,
      description: badgeText(badge),
      icon: { codicon: badge.codicon, tone: badge.tone },
      expanded: true,
      children: [list('blocking', gate.blocking), list('waived', gate.waived)],
    };
  });
  const others = report.verdict.results.flatMap((_, i) => (referenced.has(i) ? [] : [i]));
  return [...gates, group('other', 'Not in a gate\'s lists', others, others.map((i) => resultNode(loaded, i, 'other', true)))];
}

function byFile(loaded: LoadedReport, files?: readonly (string | undefined)[]): ViewNode[] {
  const subjects = new Map<string, number[]>();
  loaded.report.verdict.results.forEach((r, i) => {
    const key = files ? files[i] ?? '' : r.subject === '.' ? '' : r.subject;
    subjects.set(key, [...(subjects.get(key) ?? []), i]);
  });
  const keys = [...subjects.keys()].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a < b ? -1 : a > b ? 1 : 0));
  return keys.map((subject, g) => {
    const indices = subjects.get(subject) ?? [];
    const id = `file:${g}`;
    return group(id, subject || REPOSITORY_LEVEL, indices, indices.map((i) => resultNode(loaded, i, id, false)),
      { icon: { codicon: subject ? 'file' : 'repo' }, tooltip: subject || 'Results about the whole repository',
        ...(files && subject ? { command: 'openFile' as const, path: subject } : {}) });
  });
}

// The newest report: a partial run's results when it is newer than the full verdict.
export function resultsNodes(state: ProjectState, groupBy: GroupBy, files?: readonly (string | undefined)[]): ViewNode[] {
  if (emptyState(state)) return [];
  const loaded = state.partial ?? state.full;
  if (!loaded) return [];
  const header: ViewNode[] = loaded.partial
    ? [{ id: 'partial', kind: 'partial', label: 'Partial run', description: `${loaded.scope ?? 'scoped check'} · results of this run only`,
      icon: { codicon: 'filter' } }]
    : [];
  const groups = groupBy === 'gate' ? byGate(loaded) : groupBy === 'file' ? byFile(loaded, files) : byStatus(loaded);
  return [...header, ...groups];
}

// ── Status bar (design v0.1 §5.4) ───────────────────────────────────────────────────────────────────────────

export interface StatusBarView {
  // The status-bar text, with `$(codicon)` syntax only where this function puts it.
  readonly text: string;
  // The gate badge shown, when one is: the property a scoped run never changes.
  readonly badge?: string;
  // Plain text lines; the UI escapes them.
  readonly tooltip: readonly string[];
  // The same in words, for screen readers.
  readonly accessibility: string;
  readonly tone?: 'error' | 'warning';
}

// `$(` in CLI or user text would be read as an icon by VS Code; a zero-width space keeps it literal.
export function literal(text: string): string {
  return text.replace(/\$\(/g, '$​(');
}

// The status glyphs repeat the words beside them. Keep punctuation in report text.
export function treeAccessibilityLabel(label: string, description?: string): string {
  return [label, description].filter(Boolean).join(' · ')
    .replace(/(^| · )[✓✗◐?–] (?=(?:\d+ )?(?:PASS|FAIL|INCOMPLETE|UNKNOWN|NOT APPLICABLE|ELIGIBLE|NOT ELIGIBLE|NOT EVALUATED)\b)/g, '$1')
    .replaceAll(' · ', ', ').trim();
}

function message(text: string, tooltip: string, spin = false): StatusBarView {
  return { text: `${spin ? '$(sync~spin)' : '$(shield)'} Bio-STEWARD: ${text}`, tooltip: [tooltip], accessibility: `Bio-STEWARD: ${text}` };
}

function gateLine(gate: Gate): string {
  const badge = gateBadge(gate, false);
  return `Gate ${gate.name}: ${badgeText(badge)} · ${gate.blocking.length} blocking of ${gate.required_count} required · ${gate.reason}`;
}

const FRESHNESS_NOTES: Readonly<Record<Freshness, string>> = Object.freeze({
  fresh: 'Fresh: no project file has changed since this run.',
  stale: 'Stale: a project file changed, the CLI changed, or a newer run did not replace this verdict. Run check again.',
  unknown: 'Freshness unknown: the extension cannot tell whether project files changed since this report was made.',
});

export function statusBarView(state: ProjectState, gateName: string): StatusBarView {
  if (!state.trusted) return message('Restricted Mode', 'The workspace is not trusted, so no check runs. Trust it to run checks.');
  switch (state.cli.kind) {
    case 'detecting': return message('starting', 'Looking for the steward CLI.', true);
    case 'missing': return message('CLI not found', 'No steward program was found. Install bio-steward, or set bioSteward.cliPath.');
    case 'invalid-setting': return message('CLI path invalid', 'bioSteward.cliPath does not name a program.');
    case 'too-old': return message(`CLI ${literal(state.cli.version)} too old`,
      `steward ${state.cli.version} is older than ${state.cli.minimum}, the oldest this extension supports.`);
    case 'failed': return message('CLI not working', 'The steward CLI did not answer; see the log.');
    case 'ready': break;
  }
  const icon = state.run === 'running' ? '$(sync~spin)' : '$(shield)';
  const name = literal(gateName);
  const notes: string[] = [];
  if (state.run === 'running') notes.push('A check is running.');
  if (state.run === 'unreadable') notes.push('The last run\'s output was unreadable; see the log.');
  if (state.run === 'not-configured') notes.push('The last run found no steward.toml the CLI accepts.');
  if (state.run === 'failed') notes.push('The last run did not finish; see the log.');
  if (state.partial) {
    notes.push(`A newer partial run (${state.partial.scope ?? 'scoped check'}) did not evaluate gates; the verdict is from the last full run.`);
  }

  const full = state.full;
  if (!full) {
    const why = state.run === 'unreadable' ? 'output unreadable'
      : state.run === 'not-configured' ? 'not set up'
        : state.partial ? 'no full report' : 'no report';
    return {
      text: `${icon} ${name} ? · ${why}`,
      tooltip: [...notes, 'Run check to see the verdict.'],
      accessibility: `Bio-STEWARD: gate ${gateName}, ${why}`,
    };
  }

  const { report, freshness } = full;
  const { counts } = report.verdict.summary;
  const tooltip = [
    ...report.verdict.gates.map(gateLine),
    `Counts: ${COUNT_ORDER.map((s) => `${counts[s]} ${STATUS_LOOK[s].text}`).join(' · ')}`,
    `Worst status: ${STATUS_LOOK[report.verdict.summary.worst].text}`,
    `Report: ${freshness} · created ${report.envelope.created} · steward ${report.envelope.tool_version}`,
    FRESHNESS_NOTES[freshness],
    `Coverage: ${report.verdict.coverage.statement}`,
    ...notes,
    'Click to open the Overview.',
  ];
  const gate = report.verdict.gates.find((g) => g.name === gateName);
  if (!gate) {
    return {
      text: `${icon} ${name} ? · not in report · ${freshness}`,
      tooltip: [`The report has no gate named ${gateName} (bioSteward.gate).`, ...tooltip],
      accessibility: `Bio-STEWARD: gate ${gateName} is not in the report, ${freshness}`,
      tone: 'warning',
    };
  }
  const badge = gateBadge(gate, false);
  const blocking = gate.evaluated && !gate.eligible && gate.blocking.length > 0
    ? [`${gate.blocking.length} blocking`] : [];
  return {
    text: [`${icon} ${name} ${badgeText(badge)}`, ...blocking, freshness].join(' · '),
    badge: badgeText(badge),
    tooltip,
    accessibility: [`Bio-STEWARD: gate ${gateName} ${badge.text}`, ...blocking, freshness].join(', '),
    tone: badge.text === 'NOT ELIGIBLE' ? 'error' : undefined,
  };
}
