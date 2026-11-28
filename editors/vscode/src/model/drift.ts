// P7 Milestones and Drift (RELEASE_vscode_0.2.0_SPEC §3; design v0.3 §4.2, §4.3): the timeline states.
//
// `steward timeline --json` gives each milestone's state: "on track", "at risk", "late", "due (record its outcome)",
// "ready", or a recorded outcome ("met", "moved", "dropped"). Each row shows that state in the CLI's own words, never
// a computed drift. Newest first (E01): the latest due date first, then the highest ID; the status-bar countdown
// still names the nearest. Moved dates and the other drift fields of `timeline --format json` are task E04.
// Pure: no `vscode` import.
import type { TimelineDrift } from './full';
import { highestFirst, newestFirst } from './order';
import { daysText, progressLines, type MilestoneRow, type TimelineState } from './timeline';
import type { Tone, ViewNode } from './views';

export const MILESTONES_FILE = 'development/milestones.toml';
// The CLI's own line for an empty timeline (milestones.render).
export const NO_MILESTONES = `No milestones. Add them to ${MILESTONES_FILE} (see the guide "Plan to a deadline").`;

export const DRIFT_SOURCE_NOTE = 'Each milestone\'s state as `steward timeline --json` gives it (on track, at risk, ' +
  'late, due, …), in the CLI\'s own words, the latest due date first. Nothing is computed here. Moved dates, scope, ' +
  'order and changes without a decision need steward 0.21 or newer (the drift fields of `steward timeline --format ' +
  'json`): Upgrade CLI.';

// Newest first: the latest due date first, then the highest ID.
export function milestonesLatestFirst(rows: readonly MilestoneRow[]): MilestoneRow[] {
  return newestFirst(rows, (row) => row.due, (row) => row.id);
}

// How a state looks. The word is always the CLI's; an unknown state is still shown, with no tone.
export function stateLook(state: string): { codicon: string; tone?: Tone } {
  if (state === 'late') return { codicon: 'error', tone: 'failed' };
  if (state === 'at risk') return { codicon: 'warning', tone: 'warning' };
  if (state.startsWith('due')) return { codicon: 'bell', tone: 'warning' };
  if (state === 'on track') return { codicon: 'arrow-right', tone: 'info' };
  if (state === 'ready' || state === 'met') return { codicon: 'pass', tone: 'passed' };
  if (state === 'moved' || state === 'dropped') return { codicon: 'circle-slash', tone: 'disabled' };
  return { codicon: 'milestone' };
}

export interface DriftInput {
  readonly root: string;
  readonly name: string;
  readonly timeline?: TimelineState;
}

function milestoneNode(root: string, row: MilestoneRow, prefix: string, index: number): ViewNode {
  const outcome = row.outcome
    ? [`Outcome: ${row.outcome.state}${row.outcome.on ? ` on ${row.outcome.on}` : ''} · ${row.outcome.decision}`]
    : [];
  return {
    id: `${prefix}/${index}/${row.id}`, kind: 'drift-milestone', label: `${row.id}: ${row.title}`,
    description: `${row.state} · ${daysText(row.days_left)}`,
    tooltip: [
      `${row.id}: ${row.title} (${row.kind})`,
      `State: ${row.state} (steward timeline)`,
      `Due ${row.due} (${daysText(row.days_left)}) · internal deadline ${row.internal} · open work: ${row.open_work}`,
      ...outcome,
      ...progressLines(row),
      `Configuration in ${MILESTONES_FILE}.`,
    ].join('\n'),
    icon: stateLook(row.state), code: row.id, path: `${root}/${MILESTONES_FILE}`, root,
    next: row.outcome ? 'Open the milestone record to review its outcome.' : 'Show what blocks this milestone to review the remaining work.',
  };
}

const PROBLEMS: Readonly<Record<Exclude<TimelineState['kind'], 'ready'> | 'unread', string>> = Object.freeze({
  unread: 'not read yet',
  loading: 'reading steward timeline…',
  none: NO_MILESTONES,
  'not-configured': 'not set up: the CLI found no steward.toml it accepts',
  invalid: `${MILESTONES_FILE} is not valid (steward timeline exited 65); see the log`,
  unreadable: 'the output of steward timeline was unreadable',
  failed: 'steward timeline did not finish',
});

function projectNodes(input: DriftInput, prefix: string): ViewNode[] {
  const state = input.timeline;
  if (!state || state.kind !== 'ready') {
    const kind = state?.kind ?? 'unread';
    return [{
      id: `${prefix}/state`, kind: 'drift-note', label: PROBLEMS[kind],
      icon: kind === 'loading' ? { codicon: 'sync~spin' } : kind === 'none' ? { codicon: 'info' } : { codicon: 'warning', tone: 'warning' },
      root: input.root,
    }];
  }
  const rows = milestonesLatestFirst(state.rows).map((row, index) => milestoneNode(input.root, row, prefix, index));
  return state.drift ? [...rows, ...driftGroups(input.root, state.drift, prefix)] : rows;
}

// ── P7 full form: the drift fields of steward timeline --format json (E04) ────────────────────────────────────

export const DRIFT_FULL_NOTE = 'Each milestone\'s state as `steward timeline --format json` gives it, in the CLI\'s ' +
  'own words, the latest due date first; then its drift fields: moved dates, scope (tasks without a milestone, ' +
  'missing or dropped ones), order (a later milestone\'s work started before an earlier one), and plan changes without ' +
  'a recorded decision, newest first. Nothing is computed here.';

const SCOPE_WORDS: Readonly<Record<string, string>> = Object.freeze({
  unassigned_task: 'no milestone names it', missing_task: 'a milestone names a task that has no file',
  dropped_task: 'dropped from its milestone', unstarted_task: 'not started, its milestone is close',
  roadmap_without_task: 'on the roadmap, with no task',
});

function driftGroups(root: string, drift: TimelineDrift, prefix: string): ViewNode[] {
  const group = (key: string, label: string, tooltip: string, children: ViewNode[], warn = true): ViewNode => ({
    id: `${prefix}/drift/${key}`, kind: 'drift-group', label: `${label} (${children.length})`,
    description: children.length ? 'steward timeline' : 'none', tooltip,
    icon: { codicon: children.length && warn ? 'warning' : 'pass', tone: children.length && warn ? 'warning' : undefined },
    expanded: children.length > 0 && children.length <= 5, root, children,
  });
  const file = { command: 'openFile' as const, path: `${root}/${MILESTONES_FILE}`, root };
  const moved = newestFirst(drift.date, (row) => row.current_due, (row) => row.id).map((row, i): ViewNode => ({
    id: `${prefix}/drift/date/${i}`, kind: 'drift-item', label: row.id,
    description: `${row.first_due ?? '?'} → ${row.current_due}${row.days === null ? '' : ` (${row.days >= 0 ? '+' : ''}${row.days} days)`}` +
      `${row.recorded_move ? '' : ' · no decision recorded'}`,
    tooltip: `${row.id}: due ${row.first_due ?? 'unknown'} first, ${row.current_due} now; moved ${row.moves} time${row.moves === 1 ? '' : 's'}` +
      `${row.recorded_move ? ', with a recorded decision' : ', with no recorded decision'} (steward timeline).`,
    icon: { codicon: 'calendar', tone: row.recorded_move ? undefined : 'warning' }, ...file,
  }));
  const scope = highestFirst(drift.scope, (row) => row.id).map((row, i): ViewNode => ({
    id: `${prefix}/drift/scope/${i}`, kind: 'drift-item', label: row.id,
    description: `${SCOPE_WORDS[row.reason] ?? row.reason}${row.milestone ? ` · ${row.milestone}` : ''}`,
    tooltip: `${row.id} (${row.reason}) · ${row.path}${row.line === null ? '' : `:${row.line}`} (steward timeline)`,
    icon: { codicon: 'list-unordered' },
  }));
  const order = drift.order.map((row, i): ViewNode => ({
    id: `${prefix}/drift/order/${i}`, kind: 'drift-item', label: `${row.later} before ${row.earlier}`,
    description: `started: ${highestFirst(row.started_tasks, (id) => id).join(', ')}`,
    tooltip: `Work for ${row.later} started while ${row.earlier}, due earlier, is still open (steward timeline).`,
    icon: { codicon: 'arrow-swap' },
  }));
  const changes = newestFirst(drift.changes, (row) => row.time, (row) => row.id).filter((row) => row.decision === null)
    .map((row, i): ViewNode => ({
      id: `${prefix}/drift/changes/${i}`, kind: 'drift-item', label: `${row.id}: ${row.fields.join(', ')} changed`,
      description: [row.due ? `${row.due.before} → ${row.due.after}` : undefined, row.time?.slice(0, 10),
        row.commit?.slice(0, 12)].filter(Boolean).join(' · '),
      tooltip: `${row.kind} ${row.id} in ${row.path}: ${row.fields.join(', ')} changed${row.commit ? ` in ${row.commit}` : ''}` +
        `${row.time ? ` (${row.time})` : ''}, with no decision recorded (steward timeline).`,
      icon: { codicon: 'git-commit', tone: 'warning' },
    }));
  return [
    group('date', 'Moved dates', 'Milestones whose due date moved, from the git history of the milestones file.', moved),
    group('scope', 'Scope', 'Tasks and roadmap items that sit outside the plan, or were dropped from it.', scope),
    group('order', 'Order', 'Later milestones whose work started before an earlier one was finished.', order),
    group('changes', 'Changes without a decision', 'Plan changes in the history with no recorded decision.', changes),
    ...(drift.history !== 'available' ? [{ id: `${prefix}/drift/history`, kind: 'drift-note' as const,
      label: `history ${drift.history}`, description: 'steward timeline', tooltip: 'The git history the drift is read from is not complete.',
      icon: { codicon: 'info' } }] : []),
    ...drift.notes.map((note, i): ViewNode => ({ id: `${prefix}/drift/note/${i}`, kind: 'drift-note', label: note,
      description: 'steward timeline', icon: { codicon: 'info' } })),
  ];
}

// "1 late · 1 on track · 1 met": each state the CLI gave, counted, in the order it first appears.
export function stateCounts(state: TimelineState | undefined): string {
  if (!state || state.kind !== 'ready') return state?.kind === 'none' ? 'no milestones' : PROBLEMS[state?.kind ?? 'unread'];
  const counts = new Map<string, number>();
  for (const row of state.rows) counts.set(row.state, (counts.get(row.state) ?? 0) + 1);
  return [...counts].map(([word, count]) => `${count} ${word}`).join(' · ');
}

// One project: the note, then its milestones. Several: one block per project, in the order given (the Today order).
export function driftNodes(inputs: readonly DriftInput[]): ViewNode[] {
  if (!inputs.length) return [];
  const full = inputs.every((input) => input.timeline?.kind === 'ready' && input.timeline.drift !== undefined);
  const note: ViewNode = {
    id: 'drift/source', kind: 'drift-note', label: full ? 'Milestones and drift' : 'Milestones',
    description: 'steward timeline · latest due first', tooltip: full ? DRIFT_FULL_NOTE : DRIFT_SOURCE_NOTE,
    icon: { codicon: 'info', tone: 'info' },
  };
  if (inputs.length === 1) return [note, ...projectNodes(inputs[0], `drift/${inputs[0].root}`)];
  return [note, ...inputs.map((input): ViewNode => ({
    id: `drift/${input.root}`, kind: 'drift-project', label: input.name, description: stateCounts(input.timeline),
    tooltip: input.root, icon: { codicon: 'folder' }, expanded: true, root: input.root,
    children: projectNodes(input, `drift/${input.root}`),
  }))];
}
