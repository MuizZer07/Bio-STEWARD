// E03 (design v0.9 §4; RELEASE_vscode_0.3.0_SPEC E03): the status-bar notifications bell, local per-machine read
// state, read-once-seen handling, Mark read / Mark unread / Mark all read, urgent toasts (with setting), and the
// read-only Markdown details page opened on click.
import * as vscode from 'vscode';
import {
  bellStatusView, collectNotifications, isUrgentKind, kindLabel, markNotificationsRead, markNotificationUnread,
  notificationDetailsMarkdown, orderNotifications, projectNotifications, sanitizeReadState, shortTime, urgentToToast,
  type BellView, type NotificationItem, type NotificationKind, type ProjectNotification, type ReadState,
} from '../model/notifications';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';

export const OPEN_BELL_COMMAND = 'bioSteward.notifications.openBell';
export const MARK_READ_COMMAND = 'bioSteward.notifications.markRead';
export const MARK_UNREAD_COMMAND = 'bioSteward.notifications.markUnread';
export const MARK_ALL_READ_COMMAND = 'bioSteward.notifications.markAllRead';
export const OPEN_NOTIFICATION_DETAILS_COMMAND = 'bioSteward.notifications.openDetails';
export const NOTIFICATION_DETAILS_SCHEME = 'bio-steward-notification';

const READ_STATE_KEY = 'bioSteward.notifications.read';

// Local, per-machine read state kept in VS Code globalState (never written to the repository).
// Each entry maps `<projectKey>/<notification.id>` -> `<contentHash>`.
export class NotificationsReadStore implements vscode.Disposable {
  #state: ReadState;
  readonly #changed = new vscode.EventEmitter<ReadState>();
  readonly onDidChange = this.#changed.event;

  constructor(private readonly memento: vscode.Memento) {
    this.#state = sanitizeReadState(memento.get<unknown>(READ_STATE_KEY));
  }

  get state(): ReadState {
    return this.#state;
  }

  isRead(root: string, item: NotificationItem): boolean {
    const entries = projectNotifications({
      root, name: '', trusted: true,
      state: { kind: 'ready', document: { schema: 'steward.notifications/0.1', tool_version: '', now: '', days: 14, items: [item], notes: [] } },
    }, this.#state);
    return entries[0]?.read ?? false;
  }

  async markRead(entries: readonly { readonly root: string; readonly item: NotificationItem }[]): Promise<boolean> {
    const result = markNotificationsRead(this.#state, entries);
    if (!result.changed) return false;
    this.#state = result.state;
    await this.memento.update(READ_STATE_KEY, this.#state);
    this.#changed.fire(this.#state);
    return true;
  }

  async markUnread(root: string, id: string): Promise<boolean> {
    const result = markNotificationUnread(this.#state, root, id);
    if (!result.changed) return false;
    this.#state = result.state;
    await this.memento.update(READ_STATE_KEY, this.#state);
    this.#changed.fire(this.#state);
    return true;
  }

  // For tests: reset the persisted read state cleanly.
  async clear(): Promise<void> {
    this.#state = Object.freeze({});
    await this.memento.update(READ_STATE_KEY, this.#state);
    this.#changed.fire(this.#state);
  }

  dispose(): void {
    this.#changed.dispose();
  }
}

// Read-only Markdown details page for a notification item, opened in Markdown preview.
export class NotificationDetailsView implements vscode.TextDocumentContentProvider, vscode.Disposable {
  readonly #texts = new Map<string, string>();
  readonly #changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.#changed.event;
  readonly #registration = vscode.workspace.registerTextDocumentContentProvider(NOTIFICATION_DETAILS_SCHEME, this);
  #last: vscode.TextDocument | undefined;

  get document(): vscode.TextDocument | undefined {
    return this.#last;
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.#texts.get(uri.toString()) ?? '';
  }

  async show(entry: ProjectNotification): Promise<vscode.TextDocument> {
    const text = notificationDetailsMarkdown(entry);
    const safeId = entry.item.id.replace(/[^A-Za-z0-9._-]+/g, '_');
    const uri = vscode.Uri.from({
      scheme: NOTIFICATION_DETAILS_SCHEME,
      path: `/${entry.project.replaceAll('/', '∕')}/${safeId}.md`,
      query: new URLSearchParams({ root: entry.root, id: entry.item.id }).toString(),
    });
    const key = uri.toString();
    const changed = this.#texts.has(key) && this.#texts.get(key) !== text;
    this.#texts.set(key, text);
    if (changed) this.#changed.fire(uri);
    const document = await vscode.workspace.openTextDocument(uri);
    this.#last = await vscode.languages.setTextDocumentLanguage(document, 'markdown');
    await vscode.commands.executeCommand('markdown.showPreview', uri);
    return this.#last;
  }

  dispose(): void {
    this.#registration.dispose();
    this.#changed.dispose();
  }
}

export interface ShownToast {
  readonly root: string;
  readonly project: string;
  readonly id: string;
  readonly kind: NotificationKind;
  readonly title: string;
  readonly hash: string;
}

interface BellPickItem extends vscode.QuickPickItem {
  readonly entry?: ProjectNotification;
}

const MARK_UNREAD_BUTTON: vscode.QuickInputButton = {
  iconPath: new vscode.ThemeIcon('circle-outline'),
  tooltip: 'Mark Unread',
};

const REFRESH_BELL_BUTTON: vscode.QuickInputButton = {
  iconPath: new vscode.ThemeIcon('refresh'),
  tooltip: 'Refresh Notifications',
};

export class NotificationsBell implements vscode.Disposable {
  readonly #item = vscode.window.createStatusBarItem('bioSteward.notifications', vscode.StatusBarAlignment.Left, 47);
  #view: BellView = bellStatusView([], { trusted: false, hasProjects: false, hasReady: false });
  readonly #toasted: Record<string, string> = {};
  readonly #shownToasts: ShownToast[] = [];
  #activePick: vscode.QuickPick<BellPickItem> | undefined;
  #lastOpened: readonly ProjectNotification[] = [];

  constructor(
    readonly readStore: NotificationsReadStore,
    readonly details: NotificationDetailsView,
    private readonly onRefresh?: () => Promise<void>,
  ) {
    this.#item.name = 'Bio-STEWARD notifications';
    this.#item.command = { command: OPEN_BELL_COMMAND, title: 'Open Notifications' };
  }

  get view(): BellView {
    return this.#view;
  }

  get text(): string | undefined {
    return this.#view.visible ? this.#item.text : undefined;
  }

  get shownToasts(): readonly ShownToast[] {
    return this.#shownToasts;
  }

  get lastOpenedItems(): readonly ProjectNotification[] {
    return this.#lastOpened;
  }

  // Machine-scoped setting: a repository cannot mute urgent toasts.
  toastsEnabled(): boolean {
    const inspected = vscode.workspace.getConfiguration('bioSteward').inspect<boolean>('notifications.toasts');
    return inspected?.globalValue ?? true;
  }

  // For tests: clear session toast memory so a test can observe toasts from a clean slate.
  resetToasts(): void {
    for (const key of Object.keys(this.#toasted)) delete this.#toasted[key];
    this.#shownToasts.length = 0;
  }

  entriesOf(projects: readonly Project[], trusted: boolean): ProjectNotification[] {
    if (!trusted) return [];
    return collectNotifications(projects.map((project) => ({
      root: project.root,
      name: project.name,
      trusted: project.state.trusted,
      state: project.state.notifications,
    })), this.readStore.state);
  }

  update(projects: readonly Project[], trusted: boolean): void {
    const entries = this.entriesOf(projects, trusted);
    const hasReady = trusted && projects.some((project) => project.state.notifications?.kind === 'ready');
    const view = bellStatusView(entries, { trusted, hasProjects: projects.length > 0, hasReady });
    this.#view = view;
    if (!view.visible) {
      this.#item.hide();
      return;
    }
    this.#item.text = view.text;
    const tooltip = new vscode.MarkdownString(undefined, false);
    tooltip.isTrusted = false;
    tooltip.supportHtml = false;
    view.tooltip.forEach((line, i) => {
      if (i) tooltip.appendMarkdown('\n\n');
      tooltip.appendText(line);
    });
    this.#item.tooltip = tooltip;
    this.#item.accessibilityInformation = { label: view.accessibility };
    this.#item.backgroundColor = view.tone === 'warning'
      ? new vscode.ThemeColor('statusBarItem.warningBackground')
      : undefined;
    this.#item.show();

    const toToast = urgentToToast(entries, this.#toasted, this.toastsEnabled());
    for (const entry of toToast) {
      this.#toasted[entry.key] = entry.hash;
      const record: ShownToast = {
        root: entry.root, project: entry.project, id: entry.item.id, kind: entry.item.kind,
        title: entry.item.title, hash: entry.hash,
      };
      this.#shownToasts.push(record);
      if (this.#shownToasts.length > 200) this.#shownToasts.splice(0, this.#shownToasts.length - 200);
      const prefix = projects.length > 1 ? `[${entry.project}] ` : '';
      void vscode.window.showWarningMessage(
        `Bio-STEWARD: ${prefix}${kindLabel(entry.item.kind)} — ${entry.item.title}`,
        'Open Details',
        'Mark Read',
      ).then(async (choice) => {
        if (choice === 'Open Details') {
          await this.readStore.markRead([entry]);
          await this.details.show({ ...entry, read: true });
        } else if (choice === 'Mark Read') {
          await this.readStore.markRead([entry]);
        }
      });
    }
  }

  // Opening the bell shows all notifications (unread first, then read, newest first in each) and marks every
  // item it showed as read so the unread count drops immediately.
  async openBell(projects: readonly Project[], trusted: boolean): Promise<readonly ProjectNotification[]> {
    if (!trusted) return [];
    const entries = this.entriesOf(projects, trusted);
    this.#lastOpened = entries;
    const several = projects.length > 1;
    const unread = entries.filter((e) => !e.read);
    const read = entries.filter((e) => e.read);

    // Mark every item shown by the bell as read right away.
    if (unread.length > 0) {
      await this.readStore.markRead(unread);
      this.update(projects, trusted);
    }

    const toPick = (entry: ProjectNotification): BellPickItem => {
      const icon = entry.read
        ? '$(check)'
        : entry.item.urgent && isUrgentKind(entry.item.kind) ? '$(warning)' : '$(circle-filled)';
      const meta = [
        ...(entry.read ? ['read'] : ['unread']),
        ...(several ? [entry.project] : []),
        kindLabel(entry.item.kind),
        ...(shortTime(entry.item.time) ? [shortTime(entry.item.time)!] : []),
      ];
      return {
        label: `${icon} ${entry.item.title}`,
        description: meta.join(' · '),
        detail: `${entry.item.source}  →  ${entry.item.command}`,
        buttons: [MARK_UNREAD_BUTTON],
        entry,
      };
    };

    const items: BellPickItem[] = [];
    if (unread.length > 0) {
      items.push({ label: `Unread (${unread.length})`, kind: vscode.QuickPickItemKind.Separator });
      items.push(...unread.map(toPick));
    }
    if (read.length > 0) {
      items.push({ label: `Read (${read.length})`, kind: vscode.QuickPickItemKind.Separator });
      items.push(...read.map(toPick));
    }
    if (!items.length) {
      items.push({ label: '$(bell) No notifications', description: 'steward notifications --format json' });
    }

    this.#activePick?.dispose();
    const pick = vscode.window.createQuickPick<BellPickItem>();
    this.#activePick = pick;
    pick.title = 'Bio-STEWARD: Notifications';
    pick.placeholder = 'Select a notification to open its details page';
    pick.matchOnDescription = true;
    pick.matchOnDetail = true;
    pick.buttons = [REFRESH_BELL_BUTTON];
    pick.items = items;

    pick.onDidTriggerButton(async (button) => {
      if (button === REFRESH_BELL_BUTTON && this.onRefresh) {
        pick.busy = true;
        await this.onRefresh();
        pick.hide();
        await this.openBell(projects, trusted);
      }
    });
    pick.onDidTriggerItemButton(async (event) => {
      const entry = event.item.entry;
      if (!entry) return;
      if (event.button === MARK_UNREAD_BUTTON) {
        await this.readStore.markUnread(entry.root, entry.item.id);
        this.update(projects, trusted);
      }
    });
    pick.onDidAccept(async () => {
      const selected = pick.selectedItems[0]?.entry;
      pick.hide();
      if (selected) {
        await this.readStore.markRead([selected]);
        await this.details.show({ ...selected, read: true });
      }
    });
    pick.onDidHide(() => {
      if (this.#activePick === pick) this.#activePick = undefined;
      pick.dispose();
    });
    pick.show();
    return entries;
  }

  closeBell(): void {
    this.#activePick?.hide();
  }

  findEntry(projects: readonly Project[], trusted: boolean, target: unknown): ProjectNotification | undefined {
    const resolved = notificationTarget(target);
    if (!resolved) return undefined;
    const project = projects.find((p) => p.root === resolved.root);
    if (!project || !trusted || !project.state.trusted) return undefined;
    const entries = projectNotifications({
      root: project.root, name: project.name, trusted: project.state.trusted, state: project.state.notifications,
    }, this.readStore.state);
    return entries.find((entry) => entry.item.id === resolved.id);
  }

  async openDetails(projects: readonly Project[], trusted: boolean, target: unknown): Promise<vscode.TextDocument | undefined> {
    if (!trusted) return undefined;
    const entry = this.findEntry(projects, trusted, target);
    if (!entry) return undefined;
    if (!entry.read) {
      await this.readStore.markRead([entry]);
      this.update(projects, trusted);
    }
    return this.details.show({ ...entry, read: true });
  }

  async markRead(projects: readonly Project[], trusted: boolean, target: unknown): Promise<boolean> {
    if (!trusted) return false;
    const entry = this.findEntry(projects, trusted, target);
    if (!entry) return false;
    const changed = await this.readStore.markRead([entry]);
    this.update(projects, trusted);
    return changed;
  }

  async markUnread(projects: readonly Project[], trusted: boolean, target: unknown): Promise<boolean> {
    if (!trusted) return false;
    const resolved = notificationTarget(target);
    if (!resolved) return false;
    const changed = await this.readStore.markUnread(resolved.root, resolved.id);
    this.update(projects, trusted);
    return changed;
  }

  async markAllRead(projects: readonly Project[], trusted: boolean, target?: unknown): Promise<boolean> {
    if (!trusted) return false;
    const root = rootTarget(target);
    const scope = root ? projects.filter((p) => p.root === root) : projects;
    const entries = orderNotifications(scope.flatMap((project) => projectNotifications({
      root: project.root, name: project.name, trusted: project.state.trusted, state: project.state.notifications,
    }, this.readStore.state)));
    const changed = await this.readStore.markRead(entries);
    this.update(projects, trusted);
    return changed;
  }

  dispose(): void {
    this.#activePick?.dispose();
    this.#item.dispose();
  }
}

function notificationTarget(input: unknown): { root: string; id: string } | undefined {
  if (typeof input !== 'object' || input === null) return undefined;
  const candidate = input as Partial<ViewNode> & { root?: unknown; id?: unknown };
  if (typeof candidate.root === 'string' && typeof candidate.notificationId === 'string') {
    return { root: candidate.root, id: candidate.notificationId };
  }
  if (typeof candidate.root === 'string' && typeof candidate.id === 'string' && !candidate.kind) {
    return { root: candidate.root, id: candidate.id };
  }
  return undefined;
}

function rootTarget(input: unknown): string | undefined {
  if (typeof input === 'string') return input;
  if (typeof input === 'object' && input !== null && typeof (input as { root?: unknown }).root === 'string') {
    return (input as { root: string }).root;
  }
  return undefined;
}
