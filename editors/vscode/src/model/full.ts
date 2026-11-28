// The full forms (RELEASE_vscode_0.3.0_SPEC E04; RELEASE_vscode_0.2.0_SPEC U06): the versioned documents CLI 0.21 and
// later publish through `steward interface`, read for Today (`next`), Tasks (`task board`), Approvals (`authorize
// pending`), Decisions (`decisions`), Milestones and Drift (the drift fields of `timeline`) and the live Sprint view
// (`sprint status`). Each document is checked against the fields the panels show (a validator per schema tag; other
// fields are allowed, so a later CLI that adds one still reads). Every word, number and date shown is the CLI's.
// Pure: no `vscode` import.
import Ajv, { type ValidateFunction } from 'ajv';
import { parseJson } from '../cli/output';

// One read of a full-form document: not read yet, reading, read, or why there is nothing to show.
export type FullRead<T> =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly doc: T }
  | { readonly kind: 'not-configured' | 'unreadable' | 'failed' };

const ajv = new Ajv({ ownProperties: true });
const text = { type: 'string', maxLength: 4000 } as const;
const nullableText = { type: ['string', 'null'], maxLength: 4000 } as const;
const texts = { type: 'array', maxItems: 2000, items: text } as const;
const nullableNumber = { type: ['number', 'null'] } as const;
const count = { type: 'integer', minimum: 0 } as const;
const tagged = (tag: string) => ({ schema: { const: tag } });
const list = (items: object, maxItems = 5000) => ({ type: 'array', maxItems, items });
const object = (required: readonly string[], properties: object) => ({ type: 'object', required, properties });

// ── steward next --format json (steward.next/0.1) ─────────────────────────────────────────────────────────────

export type NextKind = 'signature' | 'decision' | 'exchange' | 'task_waiting' | 'task_failed' | 'task_done'
  | 'task_running' | 'task_ordered';

export interface NextEntry {
  readonly kind: NextKind | string;
  readonly id: string;
  readonly title: string;
  readonly source: string;
  readonly command: string;
  readonly time: string | null;
}

export interface NextDocument {
  readonly schema: 'steward.next/0.1';
  readonly tool_version: string;
  readonly now: string;
  readonly project: string;
  readonly resume: {
    readonly path: string; readonly age_days: number | null; readonly committed: boolean;
    readonly next: readonly string[]; readonly open_decisions: readonly string[]; readonly command: string;
  } | null;
  readonly milestone: {
    readonly id: string; readonly title: string; readonly kind: string; readonly due: string; readonly days_left: number;
    readonly state: string; readonly open_work: number; readonly command: string;
    readonly blockers: readonly { readonly kind: string; readonly id: string; readonly command: string }[];
  } | null;
  readonly waiting_on_human: readonly NextEntry[];
  readonly waiting_on_agents: readonly NextEntry[];
  readonly tidy: { readonly counts: Readonly<Record<string, number>>; readonly total: number; readonly command: string };
  readonly notes: readonly string[];
}

const nextEntry = object(['kind', 'id', 'title', 'source', 'command', 'time'],
  { kind: text, id: text, title: text, source: text, command: text, time: nullableText });

const validateNext = ajv.compile<NextDocument>(object(
  ['schema', 'tool_version', 'now', 'project', 'resume', 'milestone', 'waiting_on_human', 'waiting_on_agents', 'tidy', 'notes'], {
    ...tagged('steward.next/0.1'), tool_version: text, now: text, project: text,
    resume: {
      type: ['object', 'null'], required: ['path', 'age_days', 'committed', 'next', 'open_decisions', 'command'],
      properties: { path: text, age_days: nullableNumber, committed: { type: 'boolean' }, next: texts, open_decisions: texts, command: text },
    },
    milestone: {
      type: ['object', 'null'], required: ['id', 'title', 'kind', 'due', 'days_left', 'state', 'open_work', 'blockers', 'command'],
      properties: {
        id: text, title: text, kind: text, due: text, days_left: { type: 'number' }, state: text, open_work: count, command: text,
        blockers: list(object(['kind', 'id', 'command'], { kind: text, id: text, command: text }), 1000),
      },
    },
    waiting_on_human: list(nextEntry), waiting_on_agents: list(nextEntry),
    tidy: object(['counts', 'total', 'command'], {
      counts: { type: 'object', additionalProperties: count }, total: count, command: text,
    }),
    notes: texts,
  }));

export const parseNext = (stdout: string): NextDocument | undefined => valid(stdout, validateNext);

// ── steward task board --format json (steward.task_board/0.1) ─────────────────────────────────────────────────

export interface BoardTask {
  readonly id: string;
  readonly path: string;
  readonly status: string;
  readonly closed: boolean;
  readonly archived: boolean;
}

export interface BoardDocument {
  readonly schema: 'steward.task_board/0.1';
  readonly board: string | null;
  readonly tasks: readonly BoardTask[];
}

const validateBoard = ajv.compile<BoardDocument>(object(['schema', 'board', 'tasks'], {
  ...tagged('steward.task_board/0.1'), board: nullableText,
  tasks: list(object(['id', 'path', 'status', 'closed', 'archived'],
    { id: text, path: text, status: text, closed: { type: 'boolean' }, archived: { type: 'boolean' } }), 10000),
}));

export const parseBoard = (stdout: string): BoardDocument | undefined => valid(stdout, validateBoard);

// ── steward authorize pending --all-projects --format json (steward.authorize_pending/0.1) ────────────────────

export interface PendingItem {
  readonly nonce: string;
  readonly payload_sha256: string;
  readonly repo_id: string;
  readonly project: string;
  readonly peer: string | null;
  readonly requester: string | null;
  readonly action: string;
  readonly object: string;
  readonly scope: string;
  readonly budget: string;
  readonly expires: string;
  readonly baseline: string;
  readonly state: string;
  readonly summary?: string;
  readonly tag: string;
  readonly path: string;
}

export interface PendingDocument {
  readonly schema: 'steward.authorize_pending/0.1';
  readonly items: readonly PendingItem[];
  readonly waiting: number;
  readonly skipped: readonly { readonly peer: string; readonly reason: string }[];
}

const validatePending = ajv.compile<PendingDocument>(object(['schema', 'items', 'waiting', 'skipped'], {
  ...tagged('steward.authorize_pending/0.1'), waiting: count,
  items: list(object(['nonce', 'payload_sha256', 'repo_id', 'project', 'peer', 'requester', 'action', 'object', 'scope',
    'budget', 'expires', 'baseline', 'state', 'tag', 'path'], {
    nonce: { type: 'string', pattern: '^[0-9a-f]{32}$' }, payload_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    repo_id: text, project: text, peer: nullableText, requester: nullableText, action: text, object: text, scope: text,
    budget: text, expires: text, baseline: text, state: text, summary: text, tag: text, path: text,
  }), 1000),
  skipped: list(object(['peer', 'reason'], { peer: text, reason: text }), 1000),
}));

export const parsePending = (stdout: string): PendingDocument | undefined => valid(stdout, validatePending);

// ── steward decisions --format json (steward.decisions/0.1) ───────────────────────────────────────────────────

export interface RecordedDecision {
  readonly date: string;
  readonly title: string;
  readonly heading: string;
  readonly path: string;
  readonly line: number;
  readonly quotes: readonly { readonly who: string | null; readonly text: string }[];
  readonly decision: string | null;
  readonly consequences: string | null;
  readonly body: string;
}

export interface OpenDecision {
  readonly question: string;
  readonly options: readonly string[];
  readonly path: string;
  readonly line: number;
}

export interface DecisionsDocument {
  readonly schema: 'steward.decisions/0.1';
  readonly entries: readonly RecordedDecision[];
  readonly open_decisions: readonly OpenDecision[];
}

const line = { type: 'integer', minimum: 1 } as const;
const validateDecisions = ajv.compile<DecisionsDocument>(object(['schema', 'entries', 'open_decisions'], {
  ...tagged('steward.decisions/0.1'),
  entries: list(object(['date', 'title', 'heading', 'path', 'line', 'quotes', 'decision', 'consequences', 'body'], {
    date: text, title: text, heading: text, path: text, line, decision: nullableText, consequences: nullableText,
    body: { type: 'string', maxLength: 100_000 },
    quotes: list(object(['who', 'text'], { who: nullableText, text }), 1000),
  }), 20000),
  open_decisions: list(object(['question', 'options', 'path', 'line'], { question: text, options: texts, path: text, line }), 5000),
}));

export const parseDecisions = (stdout: string): DecisionsDocument | undefined => valid(stdout, validateDecisions);

// ── The drift fields of steward timeline --format json (steward.timeline/0.1) ─────────────────────────────────

export interface TimelineDrift {
  readonly history: string;
  readonly notes: readonly string[];
  readonly date: readonly {
    readonly id: string; readonly first_due: string | null; readonly current_due: string; readonly days: number | null;
    readonly moves: number; readonly recorded_move: boolean;
  }[];
  readonly scope: readonly {
    readonly reason: string; readonly id: string; readonly milestone: string | null; readonly path: string; readonly line: number | null;
  }[];
  readonly order: readonly { readonly earlier: string; readonly later: string; readonly started_tasks: readonly string[] }[];
  readonly changes: readonly {
    readonly kind: string; readonly id: string; readonly path: string; readonly commit: string | null; readonly time: string | null;
    readonly fields: readonly string[]; readonly due: { readonly before: string; readonly after: string } | null;
    readonly decision: { readonly path: string; readonly line: number; readonly heading: string } | null;
  }[];
}

const validateDrift = ajv.compile<{ schema: 'steward.timeline/0.1'; drift: TimelineDrift }>(object(['schema', 'drift'], {
  ...tagged('steward.timeline/0.1'),
  drift: object(['history', 'notes', 'date', 'scope', 'order', 'changes'], {
    history: text, notes: texts,
    date: list(object(['id', 'first_due', 'current_due', 'days', 'moves', 'recorded_move'], {
      id: text, first_due: nullableText, current_due: text, days: nullableNumber, moves: count, recorded_move: { type: 'boolean' },
    })),
    scope: list(object(['reason', 'id', 'milestone', 'path', 'line'], {
      reason: text, id: text, milestone: nullableText, path: text, line: { type: ['integer', 'null'] },
    })),
    order: list(object(['earlier', 'later', 'started_tasks'], { earlier: text, later: text, started_tasks: texts })),
    changes: list(object(['kind', 'id', 'path', 'commit', 'time', 'fields', 'due', 'decision'], {
      kind: text, id: text, path: text, commit: nullableText, time: nullableText, fields: texts,
      due: { type: ['object', 'null'], required: ['before', 'after'], properties: { before: text, after: text } },
      decision: { type: ['object', 'null'], required: ['path', 'line', 'heading'], properties: { path: text, line, heading: text } },
    })),
  }),
}));

// The drift of a tagged timeline document, or undefined for the legacy document (CLI 0.20.6 `--json`) or another.
export function parseDrift(stdout: string): TimelineDrift | undefined {
  return valid(stdout, validateDrift)?.drift;
}

// ── steward sprint status ID --format json (steward.sprint_status/0.1) ────────────────────────────────────────

export interface SprintStatusTask {
  readonly id: string;
  readonly title: string;
  readonly state: string;
  readonly agent: string;
  readonly model: string | null;
  readonly branch: string | null;
  readonly started: string | null;
  readonly ended: string | null;
  readonly log: string | null;
  readonly run_log: string | null;
  readonly commits: readonly { readonly commit: string; readonly subject: string }[];
  readonly changed_files: readonly string[];
  readonly last_commit_subject: string | null;
  readonly last_step: { readonly tool: string; readonly command: string } | null;
  readonly uncommitted: readonly string[];
}

export interface SprintStatusDocument {
  readonly schema: 'steward.sprint_status/0.1';
  readonly id: string;
  readonly path: string;
  readonly window_state: string;
  readonly dispatch: string;
  readonly tasks: readonly SprintStatusTask[];
}

const validateSprintStatus = ajv.compile<SprintStatusDocument>(object(['schema', 'id', 'path', 'window_state', 'dispatch', 'tasks'], {
  ...tagged('steward.sprint_status/0.1'), id: text, path: text, window_state: text, dispatch: text,
  tasks: list(object(['id', 'title', 'state', 'agent', 'model', 'branch', 'started', 'ended', 'log', 'run_log', 'commits',
    'changed_files', 'last_commit_subject', 'last_step', 'uncommitted'], {
    id: text, title: text, state: text, agent: text, model: nullableText, branch: nullableText, started: nullableText,
    ended: nullableText, log: nullableText, run_log: nullableText, last_commit_subject: nullableText,
    commits: list(object(['commit', 'subject'], { commit: text, subject: text }), 2000),
    changed_files: texts, uncommitted: texts,
    last_step: { type: ['object', 'null'], required: ['tool', 'command'], properties: { tool: text, command: text } },
  }), 1000),
}));

export const parseSprintStatus = (stdout: string): SprintStatusDocument | undefined => valid(stdout, validateSprintStatus);

function valid<T>(stdout: string, validate: ValidateFunction<T>): T | undefined {
  const parsed = parseJson(stdout, validate);
  return parsed.kind === 'valid' ? parsed.value : undefined;
}

// The words for a read that gave nothing to show, naming the command.
export function fullProblem(kind: Exclude<FullRead<unknown>['kind'], 'ready'>, command: string): string {
  switch (kind) {
    case 'none':
    case 'loading': return `${command}: not read yet`;
    case 'not-configured': return `${command}: not set up (no steward.toml the CLI accepts)`;
    case 'unreadable': return `${command} gave no readable answer; see the log`;
    case 'failed': return `${command} did not finish; see the log`;
  }
}
