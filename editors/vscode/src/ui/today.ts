// P1 Today and P2 "Where am I?" (RELEASE_vscode_0.2.0_SPEC §3). Today is a tree over every open
// project; "Where am I?" is a read-only virtual markdown document holding the page of src/model/today.ts, and
// **Copy as Agent Brief** copies the same page with the handoff cut short. Read-only: the CLI calls are
// `audit progress --json` and `timeline --json` (both allow-listed); the handoff is read as a file.
import { createHash } from 'node:crypto';
import * as vscode from 'vscode';
import {
  BRIEF_HANDOFF_LINES, orderProjects, pendingSummary, reopenDue, todayNodes, whereAmIText, type HandoffInfo,
  type TodayInput, type WhereAmIInput,
} from '../model/today';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { copyText } from './clipboard';
import type { NotificationsReadStore } from './notifications';
import { NodeTree } from './tree';

export const TODAY_VIEW = 'bioSteward.today';
export const TODAY_REFRESH_COMMAND = 'bioSteward.today.refresh';
export const WHERE_AM_I_COMMAND = 'bioSteward.whereAmI';
export const COPY_BRIEF_COMMAND = 'bioSteward.whereAmI.copyBrief';
export const WHERE_SCHEME = 'bio-steward-where';

async function handoffOf(project: Project): Promise<HandoffInfo> {
  return project.readHandoff();
}

export class TodayView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;
  readonly #disposables: vscode.Disposable[] = [];
  readonly #expandedNotifications = new Set<string>();
  #projects: readonly Project[] = [];
  #trusted = false;
  #generation = 0;

  constructor(private readonly readStore?: NotificationsReadStore,
    private readonly exchangeRead: (root: string, id: string) => boolean = () => false) {
    this.#view = vscode.window.createTreeView(TODAY_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
    this.#disposables.push(
      this.#view.onDidExpandElement((event) => {
        if (event.element.kind === 'today-notifications' && event.element.root) {
          this.#expandedNotifications.add(event.element.root);
          void this.#markShownNotificationsRead(event.element.root);
        }
      }),
      this.#view.onDidCollapseElement((event) => {
        if (event.element.kind === 'today-notifications' && event.element.root) {
          this.#expandedNotifications.delete(event.element.root);
        }
      }),
      this.#view.onDidChangeVisibility((event) => {
        if (event.visible) {
          for (const root of this.#expandedNotifications) void this.#markShownNotificationsRead(root);
        }
      }),
    );
  }

  // Opening the Notifications list in Today marks every item it showed as read, and the unread count drops.
  async openNotificationsList(root?: string): Promise<boolean> {
    if (!this.#trusted) return false;
    const targets = root ? [root] : this.#projects.map((p) => p.root);
    let changed = false;
    for (const targetRoot of targets) {
      this.#expandedNotifications.add(targetRoot);
      if (await this.#markShownNotificationsRead(targetRoot)) changed = true;
    }
    return changed;
  }

  async #markShownNotificationsRead(root: string): Promise<boolean> {
    if (!this.#trusted || !this.readStore) return false;
    const project = this.#projects.find((p) => p.root === root);
    if (!project || !project.state.trusted || project.state.notifications?.kind !== 'ready') return false;
    const items = project.state.notifications.document.items;
    if (!items.length) return false;
    return this.readStore.markRead(items.map((item) => ({ root: project.root, item })));
  }

  // Every project, in the Today order. The handoffs are read on each update (a small file each, no CLI call).
  async update(projects: readonly Project[], trusted: boolean): Promise<void> {
    this.#projects = projects;
    this.#trusted = trusted;
    const generation = ++this.#generation;
    const emptyKey = !projects.length ? 'none' : trusted ? '' : 'untrusted';
    void vscode.commands.executeCommand('setContext', 'bioSteward.todayEmpty', emptyKey);
    if (!trusted || !projects.length) {
      this.tree.set([]);
      return;
    }
    const readNotifications = this.readStore?.state ?? {};
    const inputs = await Promise.all(projects.map(async (project): Promise<TodayInput> => ({
      root: project.root, name: project.name, trusted: project.state.trusted,
      audit: project.state.audit, timeline: project.state.timeline, next: project.state.next,
      notifications: project.state.notifications ?? { kind: 'none' },
      readNotifications,
      handoff: project.state.trusted ? await handoffOf(project) : undefined,
      exchangeRead: (id) => this.exchangeRead(project.root, id),
    })));
    if (generation !== this.#generation) return;
    this.tree.set(todayNodes(inputs));
  }

  dispose(): void {
    this.#disposables.forEach((d) => d.dispose());
    this.#view.dispose();
    this.tree.dispose();
  }
}

export interface WhereAmIContext {
  readonly gate: (project: Project) => string;
  readonly lastSeen: (project: Project) => string | undefined;
}

// The page as a read-only document, one per project (the query keeps two projects apart, as in Resume).
export class WhereAmIView implements vscode.TextDocumentContentProvider, vscode.Disposable {
  readonly #texts = new Map<string, string>();
  readonly #roots = new Map<string, string>();
  readonly #changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.#changed.event;
  readonly #registration = vscode.workspace.registerTextDocumentContentProvider(WHERE_SCHEME, this);
  #last: vscode.TextDocument | undefined;

  constructor(private readonly context: WhereAmIContext) {}

  get document(): vscode.TextDocument | undefined {
    return this.#last;
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.#texts.get(uri.toString()) ?? '';
  }

  // The project a page belongs to (for the Copy as Agent Brief button in the page's title bar).
  rootOf(uri: vscode.Uri): string | undefined {
    return this.#roots.get(uri.toString());
  }

  // Refresh the CLI outputs, then compose. Nothing is written.
  async input(project: Project): Promise<WhereAmIInput> {
    await Promise.all([project.refreshAudit(), project.refreshTimeline(), project.refreshNext()]);
    const { state } = project;
    return {
      root: project.root, name: project.name, trusted: state.trusted, audit: state.audit, timeline: state.timeline, next: state.next,
      handoff: await handoffOf(project), gate: this.context.gate(project), report: state.full,
      lastSeen: this.context.lastSeen(project), now: new Date(),
    };
  }

  async show(project: Project): Promise<vscode.TextDocument> {
    const text = whereAmIText(await this.input(project));
    const uri = vscode.Uri.from({ scheme: WHERE_SCHEME, path: `/${project.name}/Where am I.md`, query: encodeURIComponent(project.root) });
    const key = uri.toString();
    const changed = this.#texts.has(key) && this.#texts.get(key) !== text;
    this.#texts.set(key, text);
    this.#roots.set(key, project.root);
    if (changed) this.#changed.fire(uri);
    const document = await vscode.workspace.openTextDocument(uri);
    // An open page takes the new text asynchronously after the change event; show it only once it has.
    if (document.getText() !== text) await textOf(document, text);
    this.#last = await vscode.languages.setTextDocumentLanguage(document, 'markdown');
    await vscode.window.showTextDocument(this.#last, { preview: true });
    return this.#last;
  }

  async brief(project: Project): Promise<string> {
    return whereAmIText(await this.input(project), { brief: true, handoffLines: BRIEF_HANDOFF_LINES });
  }

  dispose(): void {
    this.#registration.dispose();
    this.#changed.dispose();
  }
}

function textOf(document: vscode.TextDocument, text: string, ms = 5000): Promise<void> {
  return new Promise((done) => {
    const timer = setTimeout(finish, ms);
    const subscription = vscode.workspace.onDidChangeTextDocument((event) => {
      if (event.document === document && document.getText() === text) finish();
    });
    function finish() {
      clearTimeout(timer);
      subscription.dispose();
      done();
    }
  });
}

// The project a command acts on: the one named by its argument (a root, or a page URI), else the only one, else
// a quick pick with one line per project in the Today order (v0.3 §3).
export async function chooseProject(projects: readonly Project[], argument: unknown, view: WhereAmIView,
  title: string): Promise<Project | undefined> {
  const root = typeof argument === 'string' ? argument : argument instanceof vscode.Uri ? view.rootOf(argument) : undefined;
  const named = projects.find((project) => project.root === root);
  if (named) return named;
  if (projects.length <= 1) return projects[0];
  await Promise.all(projects.flatMap((project) => [project.refreshAudit(), project.refreshNext()]));
  const ordered = orderProjects(projects, (project) => project.state.audit, (project) => project.state.next);
  const picked = await vscode.window.showQuickPick(ordered.map((project) => ({
    label: project.name, description: pendingSummary(project.state.audit), detail: project.root, project,
  })), { title, matchOnDescription: true });
  return picked?.project;
}

export async function copyBrief(project: Project | undefined, view: WhereAmIView): Promise<string | undefined> {
  if (!project) return undefined;
  const text = await view.brief(project);
  await copyText(text);
  void vscode.window.showInformationMessage(`Bio-STEWARD: Agent brief for ${project.name} copied.`);
  return text;
}

// ── Shown once on reopening (bioSteward.whereAmI.showOnReopen, bioSteward.whereAmI.reopenAfterDays) ────────────

const LAST_SEEN_KEY = 'bioSteward.lastSeen';

// When the extension last saw each project open, kept in the extension's own global state by a hash of the root
// (never in the repository). Updated at start-up and every 30 minutes while the window is open.
export class LastSeen implements vscode.Disposable {
  readonly #timer: ReturnType<typeof setInterval>;
  // The times as they were at start-up, before this session recorded itself.
  readonly #before = new Map<string, string | undefined>();

  constructor(private readonly memento: vscode.Memento, private readonly roots: () => readonly string[]) {
    this.#timer = setInterval(() => void this.touch(), 30 * 60 * 1000);
  }

  static key(root: string): string {
    return createHash('sha256').update(root).digest('hex').slice(0, 16);
  }

  #all(): Record<string, string> {
    const value = this.memento.get<unknown>(LAST_SEEN_KEY);
    return typeof value === 'object' && value !== null ? { ...(value as Record<string, string>) } : {};
  }

  // The time recorded before this session (what "Where am I?" reports as the last open).
  before(root: string): string | undefined {
    return this.#before.has(root) ? this.#before.get(root) : this.#all()[LastSeen.key(root)];
  }

  // Remember the earlier times of `roots` (once per root), then record now for every open project.
  async touch(now = new Date()): Promise<void> {
    const all = this.#all();
    for (const root of this.roots()) {
      if (!this.#before.has(root)) this.#before.set(root, all[LastSeen.key(root)]);
      all[LastSeen.key(root)] = now.toISOString();
    }
    await this.memento.update(LAST_SEEN_KEY, all);
  }

  // For the host tests: set the recorded time of one root, as if from an earlier session.
  async set(root: string, iso: string | undefined): Promise<void> {
    const all = this.#all();
    if (iso === undefined) delete all[LastSeen.key(root)];
    else all[LastSeen.key(root)] = iso;
    this.#before.delete(root);
    await this.memento.update(LAST_SEEN_KEY, all);
  }

  dispose(): void {
    clearInterval(this.#timer);
  }
}

export function reopenSettings(): { showOnReopen: boolean; afterDays: number } {
  const config = vscode.workspace.getConfiguration('bioSteward.whereAmI');
  return { showOnReopen: config.get<boolean>('showOnReopen', true), afterDays: config.get<number>('reopenAfterDays', 3) };
}

// The projects opened again after more than N days, by the time recorded before this session.
export function reopenedProjects(projects: readonly Project[], lastSeen: LastSeen, now = new Date()): Project[] {
  const settings = reopenSettings();
  return projects.filter((project) => reopenDue(lastSeen.before(project.root), now, settings));
}

// Wait until a project's CLI detection has ended (ready or not), at most `ms`.
export function detected(project: Project, ms = 60_000): Promise<void> {
  if (project.state.cli.kind !== 'detecting') return Promise.resolve();
  return new Promise((done) => {
    const timer = setTimeout(finish, ms);
    const subscription = project.onDidChange((state) => {
      if (state.cli.kind !== 'detecting') finish();
    });
    function finish() {
      clearTimeout(timer);
      subscription.dispose();
      done();
    }
  });
}
