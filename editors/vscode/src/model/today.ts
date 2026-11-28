// P1 Today and P2 "Where am I?" (RELEASE_vscode_0.2.0_SPEC §3; design v0.2 §2.1, v0.3 §3; RELEASE_vscode_0.3.0_SPEC E01).
//
// Reading `steward next --format json` (CLI 0.21 and later) is task E04. Until then both are composed from:
// - `steward audit progress --json` (tagged `steward.progress_audit/0.1`): signatures waiting, sprints with open
//   tasks, milestones, exchange items open here, this project's own open requests, and where the project stands;
// - `steward timeline --json`: the next milestone (the countdown of 0.1.0);
// - the session handoff file, as written;
// - the last `steward check` report, for the gate line of "Where am I?".
// Every part is labelled with its source, and every list item is shown as the CLI wrote it. Nothing is ranked by
// meaning: with several projects the order is the counts audit progress reports (see `orderProjects`). Newest first
// (E01): items with IDs come highest ID first, milestones latest due first; the signatures keep the CLI's order
// (audit progress gives them no date, and their nonce is no order).
// Pure: no `vscode` import.
import Ajv from 'ajv';
import { parseJson } from '../cli/output';
import { fullProblem, type FullRead, type NextDocument, type NextEntry } from './full';
import { compareIds, highestFirst, newestFirst } from './order';
import { notificationsSectionNode, type NotificationsState, type ReadState } from './notifications';
import { daysText, nextMilestone, progressLines, type TimelineState } from './timeline';
import { gateBadge, type LoadedReport, type ViewNode } from './views';

// ── steward audit progress --json ──────────────────────────────────────────────────────────────────────────────

export const AUDIT_SCHEMA = 'steward.progress_audit/0.1';

export interface AuditMilestone {
  readonly id: string;
  readonly state: string;
  readonly days_left: number;
}

export interface AuditSprint {
  readonly sprint: string;
  readonly open?: readonly string[];
}

export interface AuditProgress {
  readonly schema: typeof AUDIT_SCHEMA;
  readonly pending: {
    readonly signatures_waiting: readonly string[];
    readonly milestones: readonly AuditMilestone[];
    readonly sprints: readonly AuditSprint[];
    readonly exchange_open?: readonly string[];
    readonly own_open?: readonly string[];
  };
  readonly where?: {
    readonly branch?: string | null;
    readonly latest_tag?: string | null;
    readonly project_version?: string | null;
    readonly toolkit_version?: string | null;
    readonly known_issues?: readonly unknown[];
  };
}

const strings = { type: 'array', maxItems: 1000, items: { type: 'string', maxLength: 1000 } } as const;
const nullableText = { type: ['string', 'null'], maxLength: 1000 } as const;

const ajv = new Ajv({ ownProperties: true });
const validateAudit = ajv.compile<AuditProgress>({
  type: 'object',
  required: ['schema', 'pending'],
  properties: {
    schema: { const: AUDIT_SCHEMA },
    pending: {
      type: 'object',
      required: ['signatures_waiting', 'milestones', 'sprints'],
      properties: {
        signatures_waiting: strings,
        exchange_open: strings,
        own_open: strings,
        milestones: {
          type: 'array',
          maxItems: 1000,
          items: {
            type: 'object',
            required: ['id', 'state', 'days_left'],
            properties: {
              id: { type: 'string', minLength: 1, maxLength: 64 },
              state: { type: 'string', minLength: 1, maxLength: 64 },
              days_left: { type: 'number' },
            },
          },
        },
        sprints: {
          type: 'array',
          maxItems: 1000,
          items: {
            type: 'object',
            required: ['sprint'],
            properties: { sprint: { type: 'string', minLength: 1, maxLength: 200 }, open: strings },
          },
        },
      },
    },
    where: {
      type: 'object',
      properties: {
        branch: nullableText,
        latest_tag: nullableText,
        project_version: nullableText,
        toolkit_version: nullableText,
        known_issues: { type: 'array', maxItems: 1000 },
      },
    },
  },
});

export function parseAuditProgress(stdout: string): AuditProgress | undefined {
  const parsed = parseJson(stdout, validateAudit);
  return parsed.kind === 'valid' ? parsed.value : undefined;
}

export type AuditState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly audit: AuditProgress }
  | { readonly kind: 'not-configured' | 'unreadable' | 'failed' };

// ── The parts, each with its source ────────────────────────────────────────────────────────────────────────────

export const SOURCES = Object.freeze({
  notifications: 'steward notifications',
  audit: 'steward audit progress',
  timeline: 'steward timeline',
  handoff: 'the session handoff',
  report: 'the last steward check report',
  extension: 'kept by the extension, not the repository',
});

export const SOURCES_NOTE = 'Composed from steward audit progress, steward timeline, the session handoff and the ' +
  'last check report. Each part names its source. What waits on agents and what needs tidying need steward 0.21 or ' +
  'newer (steward next): Upgrade CLI.';

// The lists of `pending`, in the CLI's own words (its text form of `audit progress`, section "Pending").
export interface PendingList {
  readonly key: 'signatures' | 'exchange' | 'own' | 'sprints' | 'milestones';
  readonly label: string;
  readonly items: readonly { readonly label: string; readonly description?: string }[];
}

// Newest first (E01): IDs highest first (exchange items, own requests, sprints and their open tasks), milestones
// latest due first (the most days left first); the signatures as the CLI lists them.
export function pendingLists(audit: AuditProgress): PendingList[] {
  const { pending } = audit;
  const ids = (values: readonly string[]) => highestFirst(values, (value) => value);
  return [
    { key: 'signatures', label: 'Signatures waiting', items: pending.signatures_waiting.map((label) => ({ label })) },
    { key: 'exchange', label: 'Exchange items open here', items: ids(pending.exchange_open ?? []).map((label) => ({ label })) },
    { key: 'own', label: 'This project\'s own requests still open', items: ids(pending.own_open ?? []).map((label) => ({ label })) },
    {
      key: 'sprints', label: 'Sprints with open tasks',
      items: highestFirst(pending.sprints, (s) => s.sprint).map((s) => ({ label: s.sprint, description: ids(s.open ?? []).join(', ') })),
    },
    {
      key: 'milestones', label: 'Milestones',
      items: [...pending.milestones].sort((a, b) => b.days_left - a.days_left || compareIds(b.id, a.id))
        .map((m) => ({ label: m.id, description: `${m.state} · ${daysText(m.days_left)}` })),
    },
  ];
}

// ── Several projects: the order ────────────────────────────────────────────────────────────────────────────────

// Without `steward next` (its urgency ranking is read in task E04), projects are ordered by the counts
// audit progress reports, compared in this order: signatures waiting, exchange items open here, this project's
// own open requests, sprints with open tasks; more comes first. Ties, and projects whose audit is not readable,
// keep the workspace order (unreadable ones last). No item is weighed by what it says.
export const NEXT_ORDER_NOTE = 'Several projects are ordered by what steward next reports: the most waiting on you ' +
  'first, then the most waiting on agents (ties keep the workspace order).';

export const ORDER_NOTE = 'Several projects are ordered by the counts steward audit progress reports: signatures ' +
  'waiting, then exchange items open here, then own requests still open, then sprints with open tasks (more ' +
  'first; ties keep the workspace order). It is not an urgency ranking: that needs steward next.';

export function orderKey(audit: AuditState | undefined, next?: FullRead<NextDocument>): readonly number[] | undefined {
  // Full form (E04): what steward next reports waiting on you, then on agents.
  if (next?.kind === 'ready') return [next.doc.waiting_on_human.length, next.doc.waiting_on_agents.length, 0, 0];
  if (audit?.kind !== 'ready') return undefined;
  const { pending } = audit.audit;
  return [pending.signatures_waiting.length, (pending.exchange_open ?? []).length, (pending.own_open ?? []).length,
    pending.sprints.length];
}

export function orderProjects<T>(projects: readonly T[], audit: (project: T) => AuditState | undefined,
  next?: (project: T) => FullRead<NextDocument> | undefined): T[] {
  const keyed = projects.map((project, index) => ({ project, index, key: orderKey(audit(project), next?.(project)) }));
  keyed.sort((a, b) => {
    if (!a.key || !b.key) return a.key ? -1 : b.key ? 1 : a.index - b.index;
    for (let i = 0; i < a.key.length; i++) if (a.key[i] !== b.key[i]) return b.key[i] - a.key[i];
    return a.index - b.index;
  });
  return keyed.map(({ project }) => project);
}

// "1 signature waiting · 1 exchange item open", in the order above; for a project's row and its quick pick.
export function pendingSummary(audit: AuditState | undefined): string {
  if (!audit || audit.kind === 'none' || audit.kind === 'loading') return 'audit progress not read yet';
  if (audit.kind !== 'ready') return auditProblem(audit.kind);
  const { pending } = audit.audit;
  const parts = [
    [pending.signatures_waiting.length, 'signature waiting', 'signatures waiting'],
    [(pending.exchange_open ?? []).length, 'exchange item open', 'exchange items open'],
    [(pending.own_open ?? []).length, 'own request open', 'own requests open'],
    [pending.sprints.length, 'sprint with open tasks', 'sprints with open tasks'],
  ] as const;
  const shown = parts.filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`);
  return shown.length ? shown.join(' · ') : 'nothing pending';
}

function auditProblem(kind: 'not-configured' | 'unreadable' | 'failed'): string {
  switch (kind) {
    case 'not-configured': return 'steward audit progress: not set up (no steward.toml it accepts)';
    case 'unreadable': return 'steward audit progress gave no readable answer; see the log';
    case 'failed': return 'steward audit progress did not finish; see the log';
  }
}

// ── The handoff, as a project hands it to the views ────────────────────────────────────────────────────────────

export type HandoffInfo =
  | { readonly kind: 'found'; readonly path: string; readonly text: string }
  | { readonly kind: 'missing'; readonly path: string }
  | { readonly kind: 'unreadable'; readonly reason: string };

export interface TodayInput {
  readonly root: string;
  readonly name: string;
  readonly trusted: boolean;
  readonly audit?: AuditState;
  readonly timeline?: TimelineState;
  readonly handoff?: HandoffInfo;
  readonly exchangeRead?: (id: string) => boolean;
  readonly notifications?: NotificationsState;
  readonly readNotifications?: ReadState;
  // E04: `steward next --format json`, when the CLI offers it; Today's full form.
  readonly next?: FullRead<NextDocument>;
}

// ── P1 Today, full form: steward next (E04) ────────────────────────────────────────────────────────────────

export const NEXT_SOURCE = 'steward next';
export const NEXT_NOTE = 'From steward next: where you left off, the next milestone and what blocks it, what waits on ' +
  'you and on your agents, and what needs tidying. Each row names its next step (the CLI command), and every list is ' +
  'newest first.';

const KIND_WORDS: Readonly<Record<string, string>> = Object.freeze({
  signature: 'signature', decision: 'decision', exchange: 'exchange item', task_waiting: 'task waits for an order',
  task_failed: 'task failed', task_done: 'task done', task_running: 'task running', task_ordered: 'task ordered',
});
const TIDY_WORDS: Readonly<Record<string, string>> = Object.freeze({
  stale_task: 'stale tasks', contradiction: 'contradicting statuses', stale_page: 'stale pages',
  exchange: 'exchange items to close', leftover: 'leftovers', memory: 'memory to review',
});
const KIND_ICONS: Readonly<Record<string, string>> = Object.freeze({
  signature: 'edit', decision: 'law', exchange: 'mail', task_waiting: 'debug-pause', task_failed: 'error',
  task_done: 'pass', task_running: 'sync', task_ordered: 'arrow-right',
});

// Newest first: by the entry's time, then its ID, highest first; an entry without a time last.
export function entriesNewestFirst(entries: readonly NextEntry[]): NextEntry[] {
  return newestFirst(entries, (entry) => entry.time, (entry) => entry.id);
}

function entryNode(entry: NextEntry, id: string, root: string): ViewNode {
  const kind = KIND_WORDS[entry.kind] ?? entry.kind;
  return {
    id, kind: 'today-item', label: entry.title, description: [kind, entry.time?.slice(0, 10)].filter(Boolean).join(' · '),
    tooltip: [`${entry.title} (${kind})`, `From ${entry.source}${entry.time ? `, ${entry.time}` : ''}.`, `Next step: ${entry.command}`].join('\n'),
    icon: { codicon: KIND_ICONS[entry.kind] ?? 'circle-small', tone: entry.kind === 'task_failed' ? 'failed' : entry.kind === 'signature' ? 'warning' : undefined },
    code: entry.id, root,
  };
}

function nextNodes(input: TodayInput, next: NextDocument, prefix: string): ViewNode[] {
  const nodes: ViewNode[] = [];
  const resume = next.resume;
  nodes.push({
    id: `${prefix}/resume`, kind: 'today-resume', label: 'Resume',
    description: resume
      ? `${resume.path}${resume.age_days === null ? '' : ` · ${resume.age_days.toFixed(1)} days old`}${resume.committed ? '' : ' · not committed'}`
      : 'no handoff yet · steward session close writes it',
    tooltip: resume
      ? [`The last session handoff, ${resume.path} (from ${NEXT_SOURCE}).`, ...resume.next.map((line) => `Next: ${line}`),
        ...resume.open_decisions.map((line) => `Open: ${line}`), `Next step: ${resume.command}`].join('\n')
      : 'No session handoff yet. steward session close writes one.',
    icon: { codicon: 'history' }, command: 'resume', root: input.root, expanded: false,
    children: resume ? [
      ...resume.next.map((line, i): ViewNode => ({ id: `${prefix}/resume/next/${i}`, kind: 'today-item', label: line, description: 'next' })),
      ...resume.open_decisions.map((line, i): ViewNode => ({ id: `${prefix}/resume/open/${i}`, kind: 'today-item', label: line, description: 'open decision' })),
    ] : undefined,
  });
  const milestone = next.milestone;
  nodes.push({
    id: `${prefix}/milestone`, kind: 'today-milestone', label: 'Next milestone',
    description: milestone ? `${milestone.id} · ${daysText(milestone.days_left)} · ${milestone.state.toUpperCase()}` : 'none without an outcome',
    tooltip: milestone
      ? [`${milestone.id}: ${milestone.title} (${milestone.kind}), due ${milestone.due}`, `State: ${milestone.state} · open work: ${milestone.open_work}`,
        `Blockers: ${milestone.blockers.length}`, `From ${NEXT_SOURCE}. Next step: ${milestone.command}`].join('\n')
      : `Every milestone has an outcome, or there are none (from ${NEXT_SOURCE}).`,
    icon: { codicon: 'watch' }, command: 'showTimeline', root: input.root, expanded: Boolean(milestone?.blockers.length),
    children: milestone?.blockers.length ? highestFirst(milestone.blockers, (b) => b.id).map((blocker, i): ViewNode => ({
      id: `${prefix}/milestone/blocker/${i}`, kind: 'today-item', label: blocker.id, description: `${blocker.kind} · blocks it`,
      tooltip: `Next step: ${blocker.command}`, icon: { codicon: 'circle-slash', tone: 'warning' }, code: blocker.id, root: input.root,
    })) : undefined,
  });
  const section = (key: 'human' | 'agents', label: string, entries: readonly NextEntry[], icon: string): ViewNode => ({
    id: `${prefix}/${key}`, kind: 'today-section', label: `${label} (${entries.length})`,
    description: entries.length ? 'newest first' : 'nothing',
    tooltip: `From ${NEXT_SOURCE}, newest first.`, icon: { codicon: icon, tone: key === 'human' && entries.length ? 'warning' : undefined },
    expanded: entries.length > 0,
    children: entriesNewestFirst(entries).map((entry, i) => entryNode(entry, `${prefix}/${key}/${i}`, input.root)),
  });
  nodes.push(section('human', 'Waiting on you', next.waiting_on_human, 'person'));
  nodes.push(section('agents', 'Waiting on agents', next.waiting_on_agents, 'robot'));
  const counts = Object.entries(next.tidy.counts).filter(([, n]) => n > 0);
  nodes.push({
    id: `${prefix}/tidy`, kind: 'today-section', label: `Needs tidying (${next.tidy.total})`,
    description: next.tidy.total ? `see ${next.tidy.command}` : 'nothing',
    tooltip: `From ${NEXT_SOURCE}. Next step: ${next.tidy.command} lists each item; agents name stale items and ask before archiving.`,
    icon: { codicon: 'trash' }, expanded: false,
    children: counts.map(([key, n]): ViewNode => ({ id: `${prefix}/tidy/${key}`, kind: 'today-item', label: `${n} ${TIDY_WORDS[key] ?? key}` })),
  });
  nodes.push(...next.notes.map((note, i): ViewNode => ({ id: `${prefix}/note/${i}`, kind: 'today-note', label: note,
    description: NEXT_SOURCE, icon: { codicon: 'info' } })));
  return nodes;
}

// "2 waiting on you · 1 on agents": one project's row in the full form.
export function nextSummary(next: NextDocument): string {
  const parts = [[next.waiting_on_human.length, 'waiting on you'], [next.waiting_on_agents.length, 'on agents']] as const;
  const shown = parts.filter(([n]) => n > 0).map(([n, words]) => `${n} ${words}`);
  return shown.length ? shown.join(' · ') : 'nothing waiting';
}

// ── P1 Today: the tree ────────────────────────────────────────────────────────────────────────────────────────

function milestoneLine(timeline: TimelineState | undefined): { description: string; tooltip: string } {
  const source = SOURCES.timeline;
  if (!timeline || timeline.kind === 'loading') return { description: `not read yet · ${source}`, tooltip: source };
  switch (timeline.kind) {
    case 'none': return { description: `no milestones · ${source}`, tooltip: 'development/milestones.toml has no milestones, or there is no such file.' };
    case 'not-configured': return { description: `not set up · ${source}`, tooltip: source };
    case 'invalid': return { description: `milestones file invalid · ${source}`, tooltip: 'steward timeline exited 65; see the log.' };
    case 'unreadable':
    case 'failed': return { description: `unreadable · ${source}`, tooltip: 'steward timeline gave no readable answer; see the log.' };
    case 'ready': break;
  }
  const next = nextMilestone(timeline.rows);
  if (!next) return { description: `every milestone has an outcome · ${source}`, tooltip: source };
  return {
    description: `${next.id} · ${daysText(next.days_left)} · ${next.state.toUpperCase()} · ${source}`,
    tooltip: [`${next.id}: ${next.title} (${next.kind}), due ${next.due}`, `State: ${next.state} · open work: ${next.open_work}`,
      ...progressLines(next), `From ${source}.`].join('\n'),
  };
}

function handoffLine(handoff: HandoffInfo | undefined): { description: string; tooltip: string } {
  if (!handoff) return { description: `not read yet · ${SOURCES.handoff}`, tooltip: SOURCES.handoff };
  switch (handoff.kind) {
    case 'found': return { description: `${handoff.path} · ${SOURCES.handoff}`, tooltip: 'Open the last session handoff, as written.' };
    case 'missing': return { description: `no handoff yet (${handoff.path}) · ${SOURCES.handoff}`, tooltip: '`steward session close` writes it.' };
    case 'unreadable': return { description: `unreadable · ${SOURCES.handoff}`, tooltip: handoff.reason };
  }
}

// E03: Notifications sit at the top of each project's part of Today, in the full form and the older one alike.
function notificationsTop(input: TodayInput, prefix: string): ViewNode[] {
  return input.notifications !== undefined
    ? [notificationsSectionNode({
      root: input.root, name: input.name, state: input.notifications, read: input.readNotifications ?? {},
    }, prefix)]
    : [];
}

function projectNodes(input: TodayInput, prefix: string): ViewNode[] {
  if (input.next?.kind === 'ready') return [...notificationsTop(input, prefix), ...nextNodes(input, input.next.doc, prefix)];
  // The CLI offers steward next, but this read gave nothing: say so, and show the parts audit progress gives.
  const nextProblem: ViewNode[] = input.next && input.next.kind !== 'none' && input.next.kind !== 'loading'
    ? [{ id: `${prefix}/next`, kind: 'today-note', label: fullProblem(input.next.kind, NEXT_SOURCE),
      description: 'showing steward audit progress', icon: { codicon: 'warning', tone: 'warning' }, command: 'showLog' }]
    : [];
  const resume = handoffLine(input.handoff);
  const milestone = milestoneLine(input.timeline);
  const nodes: ViewNode[] = [
    ...notificationsTop(input, prefix),
    ...nextProblem,
    {
      id: `${prefix}/resume`, kind: 'today-resume', label: 'Resume', description: resume.description, tooltip: resume.tooltip,
      icon: { codicon: 'history' }, command: 'resume', root: input.root,
      path: input.handoff?.kind === 'found' ? `${input.root}/${input.handoff.path}` : undefined,
    },
    {
      id: `${prefix}/milestone`, kind: 'today-milestone', label: 'Next milestone', description: milestone.description,
      tooltip: milestone.tooltip, icon: { codicon: 'watch' }, source: SOURCES.timeline, root: input.root,
    },
  ];
  const audit = input.audit;
  if (!audit || audit.kind === 'none' || audit.kind === 'loading') {
    nodes.push({ id: `${prefix}/audit`, kind: 'today-note', label: 'Pending', description: `not read yet · ${SOURCES.audit}`,
      icon: { codicon: 'loading~spin' } });
    return nodes;
  }
  if (audit.kind !== 'ready') {
    nodes.push({ id: `${prefix}/audit`, kind: 'today-note', label: 'Pending', description: auditProblem(audit.kind),
      icon: { codicon: 'warning', tone: 'warning' }, command: 'showLog' });
    return nodes;
  }
  for (const list of pendingLists(audit.audit)) {
    nodes.push({
      id: `${prefix}/${list.key}`, kind: 'today-section', label: `${list.label} (${list.items.length})`,
      description: list.items.length ? SOURCES.audit : `none · ${SOURCES.audit}`,
      tooltip: `From ${SOURCES.audit}, as written.`,
      icon: { codicon: SECTION_ICONS[list.key], tone: list.key === 'signatures' && list.items.length ? 'warning' : undefined },
      expanded: list.key !== 'milestones' && list.items.length > 0,
      children: list.items.map((item, i) => ({
        id: `${prefix}/${list.key}/${i}`, kind: 'today-item', label: item.label,
        description: list.key === 'exchange' && input.exchangeRead?.(item.label) ? 'Read' : item.description,
        root: input.root, code: list.key,
        next: {
          signatures: 'Open Approvals to review the payload and sign it.',
          exchange: 'Open the exchange item. Pull it from its peer if it is still waiting there.',
          own: 'Open the exchange item and review its state.',
          sprints: 'Open Sprint and order the task that is ready to start.',
          milestones: 'Open the milestone and review its remaining work.',
        }[list.key],
        tooltip: list.key === 'signatures'
          ? 'Waiting for your signature. `steward authorize pending` lists the queue; you sign in a terminal.'
          : undefined,
      })),
    });
  }
  return nodes;
}

const SECTION_ICONS: Readonly<Record<PendingList['key'], string>> = Object.freeze({
  signatures: 'edit', exchange: 'mail', own: 'comment-discussion', sprints: 'rocket', milestones: 'milestone',
});

// One project: its parts at the top level. Several: one block per project, in `orderProjects` order, never mixed.
// The first row names the sources, and why projects are in this order.
export function todayNodes(inputs: readonly TodayInput[]): ViewNode[] {
  const trusted = inputs.filter((input) => input.trusted);
  if (!trusted.length) return [];
  const several = trusted.length > 1;
  const full = trusted.every((input) => input.next?.kind === 'ready');
  const note: ViewNode = full ? {
    id: 'today/source', kind: 'today-note', label: 'Sources', description: NEXT_SOURCE,
    tooltip: several ? `${NEXT_NOTE}\n\n${NEXT_ORDER_NOTE}` : NEXT_NOTE, icon: { codicon: 'info', tone: 'info' },
  } : {
    id: 'today/source', kind: 'today-note', label: 'Sources', description: 'audit progress · timeline · handoff',
    tooltip: several ? `${SOURCES_NOTE}\n\n${ORDER_NOTE}` : SOURCES_NOTE, icon: { codicon: 'info', tone: 'info' },
  };
  if (!several) return [note, ...projectNodes(trusted[0], `today/${trusted[0].root}`)];
  return [note, ...orderProjects(trusted, (input) => input.audit, (input) => input.next).map((input): ViewNode => ({
    id: `today/${input.root}`, kind: 'today-project', label: input.name,
    description: input.next?.kind === 'ready' ? nextSummary(input.next.doc) : pendingSummary(input.audit),
    tooltip: input.root, icon: { codicon: 'folder' }, expanded: true, root: input.root,
    children: projectNodes(input, `today/${input.root}`),
  }))];
}

// ── P2 Where am I?: the page ─────────────────────────────────────────────────────────────────────────────────

export interface WhereAmIInput extends TodayInput {
  // The gate whose line is shown (bioSteward.gate) and the last full report, if any.
  readonly gate: string;
  readonly report?: LoadedReport;
  // When the extension last saw this project open (ISO time), and now.
  readonly lastSeen?: string;
  readonly now: Date;
}

export interface PageOptions {
  // At most this many handoff lines (the agent brief); the page shows them all.
  readonly handoffLines?: number;
  readonly brief?: boolean;
}

const quote = (text: string) => text.split(/\r?\n/).map((line) => (line ? `> ${line}` : '>')).join('\n');
const or = (value: string | null | undefined, none: string) => (value === null || value === undefined || value === '' ? none : value);

export const BRIEF_HANDOFF_LINES = 40;

export function whereAmIText(input: WhereAmIInput, options: PageOptions = {}): string {
  const out: string[] = [];
  const section = (title: string, source: string, lines: readonly string[]) => {
    out.push('', `## ${title} · from ${source}`, '', ...lines);
  };
  const next = input.next?.kind === 'ready' ? input.next.doc : undefined;
  out.push(options.brief ? `# Bio-STEWARD agent brief · ${input.name}` : `# Where am I? · ${input.name}`, '', next ? NEXT_NOTE : SOURCES_NOTE);
  if (input.lastSeen) {
    const days = (input.now.getTime() - Date.parse(input.lastSeen)) / 86_400_000;
    if (Number.isFinite(days)) {
      out.push('', `Last open in VS Code: ${input.lastSeen.slice(0, 10)} (${Math.max(0, days).toFixed(1)} days ago; ${SOURCES.extension}).`);
    }
  }

  const audit = input.audit;
  const ready = audit?.kind === 'ready' ? audit.audit : undefined;
  const auditMissing = [!audit || audit.kind === 'none' || audit.kind === 'loading'
    ? 'steward audit progress was not read.' : audit.kind === 'ready' ? '' : `${auditProblem(audit.kind)}.`];

  const where = ready?.where;
  section('Where it stands', SOURCES.audit, ready ? [
    `- branch ${or(where?.branch, 'unknown')} · project version ${or(where?.project_version, 'none')} · ` +
      `latest tag ${or(where?.latest_tag, 'none')} · toolkit ${or(where?.toolkit_version, 'unknown')}`,
    `- known issues listed for this version: ${where?.known_issues?.length ?? 0}`,
  ] : auditMissing);

  section('Gate', SOURCES.report, gateLines(input));

  const handoff = input.handoff;
  if (!handoff) {
    section('You left off', SOURCES.handoff, ['The handoff was not read.']);
  } else if (handoff.kind === 'found') {
    const lines = handoff.text.replace(/\r?\n$/, '').split(/\r?\n/);
    const limit = options.handoffLines ?? lines.length;
    const shown = lines.slice(0, limit).join('\n');
    section('You left off', `${SOURCES.handoff} (${handoff.path})`, [quote(shown),
      ...(lines.length > limit ? ['', `(The first ${limit} of ${lines.length} lines; read ${handoff.path} for the rest.)`] : [])]);
  } else if (handoff.kind === 'missing') {
    section('You left off', SOURCES.handoff, [`No handoff yet (${handoff.path}). \`steward session close\` writes it.`]);
  } else {
    section('You left off', SOURCES.handoff, [`The handoff could not be read: ${handoff.reason}.`]);
  }

  const milestone = milestoneLine(input.timeline);
  const target = input.timeline?.kind === 'ready' ? nextMilestone(input.timeline.rows) : undefined;
  section('Next target', SOURCES.timeline, target
    ? [`- ${target.id}: ${target.title} (${target.kind}) · due ${target.due} · ${daysText(target.days_left)} · ${target.state.toUpperCase()}`,
      ...progressLines(target).map((line) => `  - ${line}`)]
    : [milestone.description.replace(` · ${SOURCES.timeline}`, '')]);

  if (next) {
    const entryLines = (entries: readonly NextEntry[]) => entries.length
      ? entriesNewestFirst(entries).map((e) => `- ${e.title} (${KIND_WORDS[e.kind] ?? e.kind}${e.time ? `, ${e.time}` : ''}): \`${e.command}\``)
      : ['- nothing'];
    section('Waiting on you', NEXT_SOURCE, entryLines(next.waiting_on_human));
    section('Waiting on agents', NEXT_SOURCE, entryLines(next.waiting_on_agents));
    const counts = Object.entries(next.tidy.counts).filter(([, n]) => n > 0);
    section('Needs tidying', NEXT_SOURCE, counts.length
      ? [...counts.map(([key, n]) => `- ${n} ${TIDY_WORDS[key] ?? key}`), `- next step: \`${next.tidy.command}\``]
      : ['- nothing']);
    if (next.notes.length) section('Notes', NEXT_SOURCE, next.notes.map((note) => `- ${note}`));
  } else if (ready) {
    const lists = new Map(pendingLists(ready).map((list) => [list.key, list]));
    const listLines = (key: PendingList['key']) => {
      const list = lists.get(key);
      if (!list) return [];
      if (!list.items.length) return [`- ${list.label.toLowerCase()}: none`];
      return [`- ${list.label.toLowerCase()} (${list.items.length}):`,
        ...list.items.map((item) => `  - ${item.label}${item.description ? `: ${item.description}` : ''}`)];
    };
    section('Waiting on you', SOURCES.audit, [...listLines('signatures'), ...listLines('exchange')]);
    section('Waiting on others', SOURCES.audit, listLines('own'));
    section('Sprints', SOURCES.audit, listLines('sprints'));
    section('Milestones', SOURCES.audit, listLines('milestones'));
  } else {
    section('Waiting on you', SOURCES.audit, auditMissing);
  }

  if (!next) out.push('', '## Not on this page yet', '',
    '- what waits on you and on agents, and what needs tidying: they come from `steward next` (CLI 0.21 or newer: ' +
    'Upgrade CLI).');
  if (options.brief) {
    out.push('', 'Read-only orientation from Bio-STEWARD for VS Code. Run `steward check --summary` for the current verdict.');
  } else {
    out.push('', 'Next: **Bio-STEWARD: Resume** opens the handoff; **Bio-STEWARD: Copy as Agent Brief** copies this page ' +
      `for a new agent session (the handoff cut to ${BRIEF_HANDOFF_LINES} lines).`);
  }
  return `${out.join('\n')}\n`;
}

function gateLines(input: WhereAmIInput): string[] {
  const loaded = input.report;
  if (!loaded) return ['No check report in this session. Run **Bio-STEWARD: Run Check**.'];
  const gate = loaded.report.verdict.gates.find((g) => g.name === input.gate);
  if (!gate) return [`The report has no gate named ${input.gate} (freshness ${loaded.freshness}).`];
  const badge = gateBadge(gate, loaded.partial);
  return [`- ${gate.name}: ${badge.glyph} ${badge.text} · ${gate.blocking.length} blocking of ${gate.required_count} required · ` +
    `report ${loaded.freshness}`];
}

// ── P2: shown once on reopening ──────────────────────────────────────────────────────────────────────────────

export interface ReopenSettings {
  readonly showOnReopen: boolean;
  readonly afterDays: number;
}

// Shown once when a project is opened again after more than `afterDays` days. A first open (nothing recorded) is
// not a reopening; a time in the future or an unreadable one shows nothing.
export function reopenDue(lastSeen: string | undefined, now: Date, settings: ReopenSettings): boolean {
  if (!settings.showOnReopen || lastSeen === undefined) return false;
  const seen = Date.parse(lastSeen);
  if (!Number.isFinite(seen)) return false;
  const days = Number.isFinite(settings.afterDays) && settings.afterDays >= 1 ? settings.afterDays : 1;
  return now.getTime() - seen > days * 86_400_000;
}
