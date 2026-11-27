// P7 Drift in its reduced form (RELEASE_vscode_0.2.0_SPEC §3; design v0.3 §4.2, §4.3): the timeline states only.
//
// The full form (moved dates, scope, order, changes without a decision) needs drift in `steward timeline --format
// json` (C15, the cockpit CLI). CLI 0.20.6 gives each milestone's state in `steward timeline --json`: "on track",
// "at risk", "late", "due (record its outcome)", "ready", or a recorded outcome ("met", "moved", "dropped"). Each row
// shows that state in the CLI's own words, never a computed drift; the CLI's order (soonest due first) is kept.
// Pure: no `vscode` import.
import { daysText, progressLines, type MilestoneRow, type TimelineState } from './timeline';
import type { Tone, ViewNode } from './views';

export const MILESTONES_FILE = 'development/milestones.toml';
// The CLI's own line for an empty timeline (milestones.render).
export const NO_MILESTONES = `No milestones. Add them to ${MILESTONES_FILE} (see the guide "Plan to a deadline").`;

export const DRIFT_REDUCED_NOTE = 'Reduced form (CLI 0.20.6): each milestone\'s state as `steward timeline --json` ' +
  'gives it (on track, at risk, late, due, …), in the CLI\'s own words. Nothing is computed here. Moved dates, scope, ' +
  'order and changes without a decision come with drift in `steward timeline --format json` in a newer CLI.';

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
      `Click to open ${MILESTONES_FILE}.`,
    ].join('\n'),
    icon: stateLook(row.state), command: 'openFile', path: `${root}/${MILESTONES_FILE}`, root,
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
  return state.rows.map((row, index) => milestoneNode(input.root, row, prefix, index));
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
  const note: ViewNode = {
    id: 'drift/reduced', kind: 'drift-note', label: 'Reduced form', description: 'timeline states only',
    tooltip: DRIFT_REDUCED_NOTE, icon: { codicon: 'info', tone: 'info' },
  };
  if (inputs.length === 1) return [note, ...projectNodes(inputs[0], `drift/${inputs[0].root}`)];
  return [note, ...inputs.map((input): ViewNode => ({
    id: `drift/${input.root}`, kind: 'drift-project', label: input.name, description: stateCounts(input.timeline),
    tooltip: input.root, icon: { codicon: 'folder' }, expanded: true, root: input.root,
    children: projectNodes(input, `drift/${input.root}`),
  }))];
}
