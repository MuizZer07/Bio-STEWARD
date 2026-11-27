// The countdown to the next milestone (S3; design v0.3 §4.3), from `steward timeline --json` (CLI 0.20.6:
// `{"milestones": [...]}`, soonest first, not schema-tagged). Every word and number is the CLI's: the state
// ("on track", "at risk", "late", …), the days left as the CLI rounds them, and the progress it read from the
// project's records. Nothing is estimated here. Pure: no `vscode` import.
import Ajv from 'ajv';
import { parseJson } from '../cli/output';
import { literal } from './views';

export interface MilestoneRow {
  readonly id: string;
  readonly title: string;
  readonly kind: string;
  readonly due: string;
  readonly internal: string;
  readonly days_left: number;
  readonly state: string;
  readonly open_work: number;
  readonly progress: Readonly<Record<string, unknown>>;
  readonly outcome?: Readonly<{ state: string; decision: string; on?: string | null }>;
}

export interface TimelineDocument {
  readonly milestones: readonly MilestoneRow[];
}

const ajv = new Ajv({ ownProperties: true });
const validateTimeline = ajv.compile<TimelineDocument>({
  type: 'object',
  required: ['milestones'],
  properties: {
    milestones: {
      type: 'array',
      maxItems: 1000,
      items: {
        type: 'object',
        required: ['id', 'title', 'kind', 'due', 'internal', 'days_left', 'state', 'open_work', 'progress'],
        properties: {
          id: { type: 'string', minLength: 1, maxLength: 64 },
          title: { type: 'string', maxLength: 1000 },
          kind: { type: 'string', maxLength: 64 },
          due: { type: 'string', maxLength: 64 },
          internal: { type: 'string', maxLength: 64 },
          days_left: { type: 'number' },
          state: { type: 'string', minLength: 1, maxLength: 64 },
          open_work: { type: 'integer', minimum: 0 },
          progress: { type: 'object' },
          outcome: {
            type: 'object',
            required: ['state', 'decision'],
            properties: { state: { type: 'string' }, decision: { type: 'string' } },
          },
        },
      },
    },
  },
});

export function parseTimeline(stdout: string): TimelineDocument | undefined {
  const parsed = parseJson(stdout, validateTimeline);
  return parsed.kind === 'valid' ? parsed.value : undefined;
}

export type TimelineState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly rows: readonly MilestoneRow[] }
  | { readonly kind: 'not-configured' | 'invalid' | 'unreadable' | 'failed' };

// The next milestone: the soonest one without a recorded outcome (met, moved or dropped). The CLI sorts the rows.
export function nextMilestone(rows: readonly MilestoneRow[]): MilestoneRow | undefined {
  return rows.find((row) => row.outcome === undefined);
}

// "12.3 days left" / "2.0 days ago", as `steward timeline` prints it.
export function daysText(days: number): string {
  return `${Math.abs(days).toFixed(1)} days ${days >= 0 ? 'left' : 'ago'}`;
}

const text = (value: unknown) => (typeof value === 'string' ? value : undefined);
const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
const record = (value: unknown) => (typeof value === 'object' && value !== null ? value as Record<string, unknown> : undefined);

const count = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;

// The gate line (T11-09). The CLI (milestones.progress) gives either an `error`, or `eligible` (true or false) with
// whole-number `passed`, `required` and `not_applicable` and a `blocking` list. Anything else, a missing
// `eligible` included, is shown as unavailable, never as a verdict.
export function gateLine(value: unknown): string {
  const gate = record(value);
  const name = gate ? text(gate.name) ?? '?' : '?';
  const final = gate?.final === true ? ' (final checks)' : '';
  if (gate && typeof gate.error === 'string') return `Gate ${name}${final}: ${gate.error}`;
  const blocking = gate?.blocking;
  if (!gate || typeof gate.eligible !== 'boolean' || !count(gate.passed) || !count(gate.required) || !count(gate.not_applicable) ||
      (blocking !== undefined && (!Array.isArray(blocking) || !blocking.every((b) => typeof b === 'string')))) {
    return `Gate ${name}${final}: unavailable (steward timeline gave no readable gate progress)`;
  }
  const rules = (blocking ?? []) as string[];
  return `Gate ${name}${final}: ${gate.eligible ? 'ELIGIBLE' : 'NOT ELIGIBLE'}, ${String(gate.passed)} of ${String(gate.required)} required passed ` +
    `(${String(gate.not_applicable)} not applicable)` + (rules.length ? `; blocking ${rules.join(', ')}` : '');
}

// What the CLI says blocks a milestone, one line per source, in the CLI's own words (milestones.render).
export function progressLines(row: MilestoneRow): string[] {
  const out: string[] = [];
  if ('gate' in row.progress) out.push(gateLine(row.progress.gate));
  const tasks = record(row.progress.tasks);
  if (tasks) {
    const open = list(tasks.open);
    out.push('Tasks: ' + (text(tasks.error) ?? `${String(tasks.done)} of ${String(tasks.total)} done` +
      (open.length ? `; open ${open.join(', ')}` : '')));
  }
  const items = record(row.progress.items);
  if (items) {
    const waiting = list(items.waiting);
    out.push('Items: ' + (text(items.error) ?? `${String(items.done)} of ${String(items.total)} settled` +
      (waiting.length ? `; waiting ${waiting.join(', ')}` : '')));
  }
  const signatures = record(row.progress.signatures);
  if (signatures) {
    const waiting = list(signatures.waiting);
    out.push(`Signatures: needs ${list(signatures.needed).join(', ')}` +
      (waiting.length ? `; waiting to be signed: ${waiting.join(', ')}` : ''));
  }
  return out;
}

export interface CountdownView {
  readonly visible: boolean;
  readonly text: string;
  readonly tooltip: readonly string[];
  readonly accessibility: string;
  readonly tone?: 'error' | 'warning';
  readonly milestone?: string;
}

const hidden: CountdownView = Object.freeze({ visible: false, text: '', tooltip: [], accessibility: '' });

// The status-bar countdown: `$(watch) preprint · 12.3 days left · AT RISK`. Hidden when there is nothing to count
// down to (no milestones file, every milestone has an outcome, the project is not set up).
export function countdownView(state: TimelineState | undefined): CountdownView {
  if (!state) return hidden;
  switch (state.kind) {
    case 'none':
    case 'not-configured':
    case 'loading':
      return hidden;
    case 'invalid':
      return {
        visible: true, text: '$(watch) milestones invalid', tone: 'warning',
        tooltip: ['development/milestones.toml is not valid (steward timeline exited 65); see the log.'],
        accessibility: 'Bio-STEWARD: milestones file invalid',
      };
    case 'unreadable':
    case 'failed':
      return {
        visible: true, text: '$(watch) milestones unreadable', tone: 'warning',
        tooltip: ['steward timeline did not give a readable answer; see the log.'],
        accessibility: 'Bio-STEWARD: milestones unreadable',
      };
    case 'ready':
      break;
  }
  const next = nextMilestone(state.rows);
  if (!next) return hidden;
  const id = literal(next.id);
  const days = daysText(next.days_left);
  const stateText = next.state.toUpperCase();
  const later = state.rows.filter((row) => row !== next && row.outcome === undefined);
  return {
    visible: true,
    text: `$(watch) ${id} · ${days} · ${literal(stateText)}`,
    milestone: next.id,
    tooltip: [
      `Next milestone: ${next.id}: ${next.title} (${next.kind})`,
      `Due ${next.due} (${days}) · internal deadline ${next.internal}`,
      `State: ${next.state} · open work: ${next.open_work}`,
      ...progressLines(next),
      ...(later.length ? [`Later: ${later.map((row) => `${row.id} (${row.state}, ${daysText(row.days_left)})`).join(' · ')}`] : []),
      'From steward timeline. Progress is read from the project\'s records, not estimated. Click for every milestone.',
    ],
    accessibility: `Bio-STEWARD: next milestone ${next.id}, ${days}, ${next.state}`,
    tone: next.state === 'late' ? 'error' : next.state === 'at risk' ? 'warning' : undefined,
  };
}
