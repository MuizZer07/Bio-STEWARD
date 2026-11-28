// E03 (design v0.9 §4; RELEASE_vscode_0.3.0_SPEC E03): the notifications bell, Notifications at the top of Today,
// local per-machine read state keyed by notification ID and content hash, urgent toasts, and details pages.
// Pure: no `vscode` import.
import { createHash } from 'node:crypto';
import Ajv from 'ajv';
import { parseJson } from '../cli/output';
import { newestFirst } from './order';
import { literal, type Tone, type ViewNode } from './views';

export const NOTIFICATIONS_SCHEMA = 'steward.notifications/0.1';
export const NOTIFICATIONS_MIN_CLI = '0.21.0';
export const NOTIFICATION_KINDS = Object.freeze([
  'upgrade', 'exchange', 'task_finished', 'task_failed', 'task_waiting', 'approval', 'gate', 'milestone',
] as const);

export type NotificationKind = typeof NOTIFICATION_KINDS[number];

// Design v0.9 §4: toasts appear only for these three urgent kinds.
export const URGENT_KINDS: readonly NotificationKind[] = Object.freeze(['gate', 'approval', 'task_failed']);

export function isUrgentKind(kind: NotificationKind): boolean {
  return URGENT_KINDS.includes(kind);
}

export interface NotificationItem {
  readonly id: string;
  readonly kind: NotificationKind;
  readonly time: string | null;
  readonly source: string;
  readonly title: string;
  readonly command: string;
  readonly urgent: boolean;
}

export interface NotificationsDocument {
  readonly schema: typeof NOTIFICATIONS_SCHEMA;
  readonly tool_version: string;
  readonly now: string;
  readonly days: number;
  readonly items: readonly NotificationItem[];
  readonly notes: readonly string[];
}

export type NotificationsState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly document: NotificationsDocument }
  | { readonly kind: 'unsupported'; readonly minimum: string }
  | { readonly kind: 'not-configured' | 'unreadable' | 'failed' };

const ajv = new Ajv({ ownProperties: true });
const validateNotifications = ajv.compile<NotificationsDocument>({
  type: 'object',
  required: ['schema', 'tool_version', 'now', 'days', 'items', 'notes'],
  properties: {
    schema: { const: NOTIFICATIONS_SCHEMA },
    tool_version: { type: 'string', minLength: 1, maxLength: 128 },
    now: { type: 'string', minLength: 1, maxLength: 128 },
    days: { type: 'integer' },
    notes: { type: 'array', maxItems: 500, items: { type: 'string', maxLength: 1000 } },
    items: {
      type: 'array',
      maxItems: 1000,
      items: {
        type: 'object',
        required: ['id', 'kind', 'time', 'source', 'title', 'command', 'urgent'],
        properties: {
          id: { type: 'string', minLength: 1, maxLength: 300 },
          kind: { enum: [...NOTIFICATION_KINDS] },
          time: { type: ['string', 'null'], maxLength: 128 },
          source: { type: 'string', maxLength: 500 },
          title: { type: 'string', maxLength: 1000 },
          command: { type: 'string', maxLength: 500 },
          urgent: { type: 'boolean' },
        },
      },
    },
  },
});

export function parseNotifications(stdout: string): NotificationsDocument | undefined {
  const parsed = parseJson(stdout, validateNotifications);
  return parsed.kind === 'valid' ? parsed.value : undefined;
}

// ── Local per-machine read state (ID + content hash) ──────────────────────────────────────────────────────────

export const MAX_READ_ENTRIES = 2000;

// Map of `<projectKey>/<item.id>` -> `<contentHash>`.
export type ReadState = Readonly<Record<string, string>>;

export function projectKey(root: string): string {
  return createHash('sha256').update(root).digest('hex').slice(0, 16);
}

export function notificationKey(root: string, id: string): string {
  return `${projectKey(root)}/${id}`;
}

// Content hash of every CLI field of a notification item, so the same item stays read until the CLI reports a change.
export function notificationContentHash(item: NotificationItem): string {
  const payload = JSON.stringify([item.id, item.kind, item.time, item.source, item.title, item.command, item.urgent]);
  return createHash('sha256').update(payload).digest('hex');
}

export function isNotificationRead(state: ReadState, root: string, item: NotificationItem): boolean {
  return state[notificationKey(root, item.id)] === notificationContentHash(item);
}

function capState(entries: Record<string, string>, max = MAX_READ_ENTRIES): ReadState {
  const keys = Object.keys(entries);
  if (keys.length <= max) return Object.freeze(entries);
  const trimmed: Record<string, string> = {};
  for (const key of keys.slice(keys.length - max)) trimmed[key] = entries[key];
  return Object.freeze(trimmed);
}

export function sanitizeReadState(raw: unknown): ReadState {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return Object.freeze({});
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof key === 'string' && typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)) out[key] = value;
  }
  return capState(out);
}

export function markNotificationsRead(
  state: ReadState,
  entries: readonly { readonly root: string; readonly item: NotificationItem }[],
): { readonly state: ReadState; readonly changed: boolean } {
  let changed = false;
  const next: Record<string, string> = { ...state };
  for (const { root, item } of entries) {
    const key = notificationKey(root, item.id);
    const hash = notificationContentHash(item);
    if (next[key] !== hash) {
      delete next[key];
      next[key] = hash;
      changed = true;
    }
  }
  return { state: changed ? capState(next) : state, changed };
}

export function markNotificationUnread(
  state: ReadState,
  root: string,
  id: string,
): { readonly state: ReadState; readonly changed: boolean } {
  const key = notificationKey(root, id);
  if (!(key in state)) return { state, changed: false };
  const next: Record<string, string> = { ...state };
  delete next[key];
  return { state: Object.freeze(next), changed: true };
}

// ── Project-scoped notifications and ordering ────────────────────────────────────────────────────────────────

export interface ProjectNotification {
  readonly root: string;
  readonly project: string;
  readonly item: NotificationItem;
  readonly key: string;
  readonly hash: string;
  readonly read: boolean;
}

export interface NotificationsInput {
  readonly root: string;
  readonly name: string;
  readonly trusted: boolean;
  readonly state: NotificationsState | undefined;
}

export function projectNotifications(input: NotificationsInput, readState: ReadState): ProjectNotification[] {
  if (!input.trusted || input.state?.kind !== 'ready') return [];
  return input.state.document.items.map((item) => {
    const key = notificationKey(input.root, item.id);
    const hash = notificationContentHash(item);
    return {
      root: input.root,
      project: input.name,
      item,
      key,
      hash,
      read: readState[key] === hash,
    };
  });
}

// Unread first (newest first), then read (newest first). Never mutates the input.
export function orderNotifications(entries: readonly ProjectNotification[]): ProjectNotification[] {
  const unread = newestFirst(entries.filter((entry) => !entry.read), (e) => e.item.time, (e) => e.item.id);
  const read = newestFirst(entries.filter((entry) => entry.read), (e) => e.item.time, (e) => e.item.id);
  return [...unread, ...read];
}

export function collectNotifications(inputs: readonly NotificationsInput[], readState: ReadState): ProjectNotification[] {
  return orderNotifications(inputs.flatMap((input) => projectNotifications(input, readState)));
}

// Which notifications should trigger a VS Code toast right now:
// - only when toasts are enabled;
// - only unread items (a read item never toasts again);
// - only the three urgent kinds (`gate`, `approval`, `task_failed`) with `item.urgent === true`;
// - not already toasted for this `(key, hash)` (a changed item has a new hash and can toast again).
export function urgentToToast(
  entries: readonly ProjectNotification[],
  toasted: Readonly<Record<string, string>>,
  toastsEnabled: boolean,
): ProjectNotification[] {
  if (!toastsEnabled) return [];
  return orderNotifications(entries).filter((entry) =>
    !entry.read && entry.item.urgent && isUrgentKind(entry.item.kind) && toasted[entry.key] !== entry.hash);
}

// ── Labels, icons and formatting ─────────────────────────────────────────────────────────────────────────────

const KIND_INFO: Readonly<Record<NotificationKind, { label: string; codicon: string; tone?: Tone; meaning: string }>> = Object.freeze({
  upgrade: {
    label: 'CLI upgrade',
    codicon: 'arrow-circle-up',
    tone: 'info',
    meaning: 'A release notice received through the exchange names a newer version of the steward CLI than the one installed.',
  },
  exchange: {
    label: 'Exchange',
    codicon: 'mail',
    tone: 'info',
    meaning: 'An exchange item from another project is open in your inbox and has not been decided yet.',
  },
  task_finished: {
    label: 'Task finished',
    codicon: 'pass',
    tone: 'passed',
    meaning: 'A sprint task finished recently and passed its acceptance checks in the sprint ledger.',
  },
  task_failed: {
    label: 'Task failed',
    codicon: 'error',
    tone: 'failed',
    meaning: 'A sprint task failed recently. Review its ledger and checks before retrying.',
  },
  task_waiting: {
    label: 'Task waiting',
    codicon: 'clock',
    tone: 'warning',
    meaning: 'A sprint task is ready and waiting for your order (`steward sprint go`).',
  },
  approval: {
    label: 'Approval waiting',
    codicon: 'edit',
    tone: 'warning',
    meaning: 'A prepared authorization payload waits for your signature. Only you can sign it with your own key.',
  },
  gate: {
    label: 'Gate not eligible',
    codicon: 'error',
    tone: 'failed',
    meaning: 'A gate that was previously eligible turned not eligible.',
  },
  milestone: {
    label: 'Milestone',
    codicon: 'milestone',
    tone: 'warning',
    meaning: 'A project milestone is at risk or late according to `steward timeline`.',
  },
});

export function kindLabel(kind: NotificationKind): string {
  return KIND_INFO[kind].label;
}

export function kindIcon(kind: NotificationKind, read: boolean): { readonly codicon: string; readonly tone?: Tone } {
  const { codicon, tone } = KIND_INFO[kind];
  return read ? { codicon, tone: 'disabled' } : { codicon, tone };
}

export function shortTime(iso: string | null): string | undefined {
  if (!iso) return undefined;
  const match = /^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?/.exec(iso.trim());
  if (!match) return iso;
  return match[2] ? `${match[1]} ${match[2]}Z` : match[1];
}

// ── Status-bar bell model ────────────────────────────────────────────────────────────────────────────────────

export interface BellView {
  readonly visible: boolean;
  readonly unread: number;
  readonly total: number;
  readonly urgentUnread: number;
  readonly text: string;
  readonly tooltip: readonly string[];
  readonly accessibility: string;
  readonly tone?: 'warning';
}

export function bellStatusView(
  entries: readonly ProjectNotification[],
  options: { readonly trusted: boolean; readonly hasProjects: boolean; readonly hasReady: boolean },
): BellView {
  if (!options.trusted || !options.hasProjects || !options.hasReady) {
    return { visible: false, unread: 0, total: 0, urgentUnread: 0, text: '', tooltip: [], accessibility: '' };
  }
  const ordered = orderNotifications(entries);
  const unreadItems = ordered.filter((e) => !e.read);
  const unread = unreadItems.length;
  const readCount = ordered.length - unread;
  const urgentUnread = unreadItems.filter((e) => e.item.urgent && isUrgentKind(e.item.kind)).length;
  const text = unread > 0 ? `$(bell-dot) ${unread}` : '$(bell)';
  const tooltip: string[] = [];
  if (unread > 0) {
    tooltip.push(`Bio-STEWARD notifications: ${unread} unread${readCount ? ` · ${readCount} read` : ''}`);
    if (urgentUnread > 0) tooltip.push(`Urgent: ${urgentUnread}`);
    for (const entry of unreadItems.slice(0, 5)) {
      tooltip.push(`• ${kindLabel(entry.item.kind)}: ${entry.item.title}`);
    }
    if (unread > 5) tooltip.push(`… and ${unread - 5} more unread`);
  } else {
    tooltip.push(`Bio-STEWARD notifications: no unread items${readCount ? ` (${readCount} read)` : ''}`);
  }
  tooltip.push('From steward notifications --format json. Click to open.');
  const accessibility = unread > 0
    ? `Bio-STEWARD notifications: ${unread} unread${urgentUnread ? `, ${urgentUnread} urgent` : ''}`
    : `Bio-STEWARD notifications: 0 unread${readCount ? `, ${readCount} read` : ''}`;
  return {
    visible: true,
    unread,
    total: ordered.length,
    urgentUnread,
    text,
    tooltip,
    accessibility,
    tone: urgentUnread > 0 ? 'warning' : undefined,
  };
}

// ── Today panel: Notifications section at the top of Today ───────────────────────────────────────────────────

function notificationsProblem(kind: 'not-configured' | 'unreadable' | 'failed'): string {
  switch (kind) {
    case 'not-configured': return 'steward notifications: not set up (no steward.toml it accepts)';
    case 'unreadable': return 'steward notifications gave no readable answer; see the log';
    case 'failed': return 'steward notifications did not finish; see the log';
  }
}

export function notificationsSectionNode(
  input: { readonly root: string; readonly name: string; readonly state: NotificationsState; readonly read: ReadState },
  prefix: string,
): ViewNode {
  const id = `${prefix}/notifications`;
  const { state } = input;
  if (state.kind === 'none' || state.kind === 'loading') {
    return {
      id,
      kind: 'today-notifications',
      label: 'Notifications',
      description: 'not read yet · steward notifications',
      icon: { codicon: 'loading~spin' },
      root: input.root,
    };
  }
  if (state.kind === 'unsupported') {
    return {
      id,
      kind: 'today-notifications',
      label: 'Notifications',
      description: `needs steward ${state.minimum} or newer`,
      tooltip: `The notifications feed needs steward ${state.minimum} or newer (steward notifications --format json).`,
      icon: { codicon: 'info', tone: 'info' },
      root: input.root,
    };
  }
  if (state.kind !== 'ready') {
    return {
      id,
      kind: 'today-notifications',
      label: 'Notifications',
      description: notificationsProblem(state.kind),
      icon: { codicon: 'warning', tone: 'warning' },
      command: 'showLog',
      root: input.root,
    };
  }
  const entries = orderNotifications(projectNotifications({
    root: input.root, name: input.name, trusted: true, state,
  }, input.read));
  const unread = entries.filter((e) => !e.read).length;
  const readCount = entries.length - unread;
  const urgentUnread = entries.filter((e) => !e.read && e.item.urgent && isUrgentKind(e.item.kind)).length;
  const label = entries.length === 0
    ? 'Notifications (0)'
    : unread > 0 && readCount > 0
      ? `Notifications (${unread} unread · ${readCount} read)`
      : unread > 0
        ? `Notifications (${unread} unread)`
        : `Notifications (0 unread · ${readCount} read)`;
  const description = entries.length === 0 ? 'none · steward notifications' : 'steward notifications';
  const notes = state.document.notes.length ? `\nNotes:\n${state.document.notes.map((n) => `- ${n}`).join('\n')}` : '';
  return {
    id,
    kind: 'today-notifications',
    label,
    description,
    tooltip: `From steward notifications --format json (${unread} unread, ${readCount} read). Expanding marks shown items as read.${notes}`,
    icon: { codicon: unread > 0 ? 'bell-dot' : 'bell', tone: urgentUnread > 0 ? 'warning' : unread > 0 ? 'info' : undefined },
    // Collapsed by default so opening the list actively marks the items it shows as read.
    expanded: false,
    root: input.root,
    children: entries.map((entry): ViewNode => {
      const { item, read } = entry;
      const parts = [
        ...(read ? ['read'] : []),
        kindLabel(item.kind),
        ...(shortTime(item.time) ? [shortTime(item.time)!] : []),
        ...(item.source ? [item.source] : []),
      ];
      const tooltipLines = [
        `${kindLabel(item.kind)}${item.urgent && isUrgentKind(item.kind) ? ' (urgent)' : ''} · ${read ? 'read' : 'unread'}`,
        item.title,
        ...(item.time ? [`Time: ${item.time}`] : []),
        `Source: ${item.source}`,
        `Next command: ${item.command}`,
        'From steward notifications --format json.',
      ];
      return {
        id: `${prefix}/notification/${item.id}`,
        kind: read ? 'notification-read' : 'notification-unread',
        label: item.title,
        description: parts.join(' · '),
        tooltip: tooltipLines.join('\n'),
        icon: kindIcon(item.kind, read),
        dimmed: read,
        command: 'openNotification',
        root: input.root,
        notificationId: item.id,
        code: item.kind,
      };
    }),
  };
}

// ── Details page (read-only Markdown preview) ────────────────────────────────────────────────────────────────

function escapeMarkdownText(text: string): string {
  // Blockquote plain lines so repository/CLI text cannot inject headings, HTML or links.
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .split(/\r?\n/).map((line) => (line ? `> ${line}` : '>')).join('\n');
}

export function notificationDetailsMarkdown(entry: ProjectNotification): string {
  const { item } = entry;
  const info = KIND_INFO[item.kind];
  const urgent = item.urgent && isUrgentKind(item.kind);
  const lines: string[] = [
    `# ${info.label} · ${literal(entry.project)}`,
    '',
    `Status: ${entry.read ? 'read' : 'unread'}${urgent ? ' · urgent' : ''} · ID \`${item.id}\``,
    '',
    '## What it is',
    '',
    escapeMarkdownText(item.title),
    '',
    '## Where it comes from',
    '',
    `- **Command:** \`steward notifications --format json\``,
    `- **Project:** ${entry.project}`,
    `- **Record:** \`${item.source}\``,
    `- **Time:** ${item.time ?? 'none recorded'}`,
    '',
    '## What it means',
    '',
    info.meaning,
    '',
    '## Next step',
    '',
    '```bash',
    item.command,
    '```',
  ];
  if (item.kind === 'upgrade') {
    lines.push('', 'Run **Bio-STEWARD: Upgrade CLI…** (or click **Upgrade CLI** in the Overview panel) to review the exact command in a modal and run `steward upgrade --to VERSION` in a visible terminal.');
  } else if (item.kind === 'approval') {
    lines.push('', 'Open **Now · Approvals** to review the exact payload bytes and sign in a terminal.');
  }
  lines.push('');
  return lines.join('\n');
}
