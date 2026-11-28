// The live sprint view, minimal (S9; design v0.4 §1, §2, §4): a Sprint tree, the status bar item
// `▶ T01 12 min · 1/12` and three notifications. Read-only: it watches the sprint files and the ledgers (no git,
// T12 decision D1), and reads them again at most once a second. It starts nothing, writes nothing and calls no
// model. In an untrusted workspace it reads nothing.
import * as vscode from 'vscode';
import { isShown, notices, orderCommand, sprintNodes, sprintStatus, type Notice, type SprintSnapshot } from '../model/sprint';
import type { SprintStatusDocument } from '../model/full';
import type { ViewNode } from '../model/views';
import { SprintReader } from '../sprints';
import { copyText } from './clipboard';
import { NodeTree } from './tree';

export const SPRINT_VIEW = 'bioSteward.sprint';
export const SPRINT_REFRESH_COMMAND = 'bioSteward.sprint.refresh';
export const SPRINT_COPY_ORDER_COMMAND = 'bioSteward.sprint.copyOrderCommand';
export const SPRINT_SHOW_COMMAND = 'bioSteward.sprint.show';
export const MIN_REFRESH_MS = 1000;
// E04: the CLI's `sprint status` (which reads git) runs at most this often on file changes.
export const STATUS_MS = 10_000;
// The elapsed times move on without a read: the view is drawn again from what was last read.
const TICK_MS = 30_000;

export interface LiveSprintOptions {
  root: string;
  isTrusted: () => boolean;
  log: vscode.LogOutputChannel;
  notify: (notice: Notice) => void;
  watch?: boolean;
  // E04: `steward sprint status ID --format json` for a shown sprint, when the CLI offers it (undefined otherwise).
  status?: (id: string) => Promise<SprintStatusDocument | undefined>;
}

export class LiveSprint implements vscode.Disposable {
  readonly #reader: SprintReader;
  readonly #changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.#changed.event;
  readonly #disposables: vscode.Disposable[] = [];
  #snapshots: readonly SprintSnapshot[] = [];
  #lastRead = 0;
  #reading: Promise<void> | undefined;
  #timer: NodeJS.Timeout | undefined;
  #again = false;
  #disposed = false;
  // For the tests: how many reads ran.
  reads = 0;

  constructor(private readonly options: LiveSprintOptions) {
    this.#reader = new SprintReader(options.root);
    if (options.watch !== false) {
      const glob = 'development/sprints/*.{toml,jsonl}';
      try {
        const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(vscode.Uri.file(options.root), glob));
        const changed = () => this.schedule();
        this.#disposables.push(watcher, watcher.onDidCreate(changed), watcher.onDidChange(changed), watcher.onDidDelete(changed));
      } catch (error) {
        options.log.warn(`Sprint view: no file watcher for ${glob} · ${String(error)}`);
      }
      const tick = setInterval(() => {
        if (this.#snapshots.length) this.#changed.fire();
      }, TICK_MS);
      this.#disposables.push({ dispose: () => clearInterval(tick) });
    }
  }

  get root(): string {
    return this.options.root;
  }

  get snapshots(): readonly SprintSnapshot[] {
    return this.#snapshots;
  }

  // E04: the CLI's status document of each shown sprint, from the last read.
  get statuses(): ReadonlyMap<string, SprintStatusDocument> {
    return this.#statuses;
  }

  #statuses: ReadonlyMap<string, SprintStatusDocument> = new Map();
  #lastStatus = 0;

  // Read again: now, or as soon as a second has passed since the last read; never two reads at once.
  schedule(): void {
    if (this.#disposed) return;
    if (this.#reading) {
      this.#again = true;
      return;
    }
    if (this.#timer) return;
    const wait = Math.max(0, this.#lastRead + MIN_REFRESH_MS - Date.now());
    this.#timer = setTimeout(() => {
      this.#timer = undefined;
      void this.refresh();
    }, wait);
  }

  // Waits for the current read, or reads now when the last read is at least a second old.
  async refresh(): Promise<void> {
    if (this.#disposed) return;
    if (this.#reading) {
      this.#again = true;
      return this.#reading;
    }
    this.#reading = this.#read().finally(() => {
      this.#reading = undefined;
      if (this.#again) {
        this.#again = false;
        this.schedule();
      }
    });
    return this.#reading;
  }

  // The panel's refresh button (E01): read now, past the one-read-a-second pacing; after a read in progress ends,
  // a new one starts at once.
  async refreshNow(): Promise<void> {
    if (this.#disposed) return;
    if (this.#reading) await this.#reading;
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = undefined;
    this.#again = false;
    this.#lastRead = 0;
    this.#lastStatus = 0;
    return this.refresh();
  }

  async #read(): Promise<void> {
    const wait = this.#lastRead + MIN_REFRESH_MS - Date.now();
    if (wait > 0) await new Promise((done) => setTimeout(done, wait));
    if (this.#disposed) return;
    this.#lastRead = Date.now();
    this.reads++;
    if (!this.options.isTrusted()) {
      this.#snapshots = [];
      this.#changed.fire();
      return;
    }
    let next: SprintSnapshot[];
    try {
      next = await this.#reader.read();
    } catch (error) {
      this.options.log.warn(`Sprint view: ${String(error)}`);
      next = [];
    }
    if (this.#disposed) return;
    const before = new Map(this.#snapshots.map((s) => [s.id, s]));
    const first = this.reads === 1;
    // Only the sprints the view shows are kept (T11-03); a sprint that stops being shown in this read still gets
    // its notifications, because the read before kept it.
    const now = Date.now();
    this.#snapshots = next.filter((s) => isShown(s, now));
    if (!first) for (const s of next) for (const n of notices(before.get(s.id), s)) this.options.notify(n);
    this.#changed.fire();
    // The CLI's status reads git, so it runs at most every STATUS_MS while the ledgers change (and at once on the
    // panel's refresh button).
    const status = this.options.status;
    if (status && this.#snapshots.length && Date.now() - this.#lastStatus < STATUS_MS) return;
    if (status && this.#snapshots.length) {
      const read = await Promise.all(this.#snapshots.filter((s) => s.plan).map(async (s) => [s.id, await status(s.id)] as const));
      if (this.#disposed) return;
      this.#statuses = new Map(read.filter((entry): entry is readonly [string, SprintStatusDocument] => entry[1] !== undefined));
      // Paced only once the CLI answered (before its detection ends, the next read asks again).
      if (this.#statuses.size) this.#lastStatus = Date.now();
      this.#changed.fire();
    } else {
      this.#statuses = new Map();
    }
  }

  dispose(): void {
    this.#disposed = true;
    if (this.#timer) clearTimeout(this.#timer);
    this.#disposables.forEach((d) => d.dispose());
    this.#changed.dispose();
  }
}

export class SprintView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;

  constructor() {
    this.#view = vscode.window.createTreeView(SPRINT_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
  }

  update(live: LiveSprint | undefined, trusted: boolean, description?: string, now = Date.now()): void {
    this.#view.description = description;
    const nodes = live && trusted ? sprintNodes(live.snapshots, { now, statuses: live.statuses }) : [];
    this.tree.set(nodes, live?.root);
    void vscode.commands.executeCommand('setContext', 'bioSteward.sprintEmpty', !trusted ? 'untrusted' : nodes.length ? '' : 'none');
  }

  dispose(): void {
    this.#view.dispose();
    this.tree.dispose();
  }
}

export class SprintStatusBar implements vscode.Disposable {
  readonly #item = vscode.window.createStatusBarItem('bioSteward.sprint', vscode.StatusBarAlignment.Left, 48);
  #text: string | undefined;

  constructor() {
    this.#item.name = 'Bio-STEWARD sprint';
    this.#item.command = { command: SPRINT_SHOW_COMMAND, title: 'Show the sprint' };
  }

  get text(): string | undefined {
    return this.#text;
  }

  update(snapshots: readonly SprintSnapshot[], now = Date.now()): void {
    const status = sprintStatus(snapshots, now);
    if (!status.visible) {
      this.#text = undefined;
      this.#item.hide();
      return;
    }
    this.#text = status.text;
    this.#item.text = status.text;
    this.#item.tooltip = status.tooltip;
    this.#item.accessibilityInformation = { label: status.accessibility };
    this.#item.show();
  }

  dispose(): void {
    this.#item.dispose();
  }
}

// The order command for a waiting task, copied for the human to run (the view never orders anything).
export async function copyOrderCommand(live: LiveSprint | undefined, input: unknown): Promise<string | undefined> {
  const node = input as Partial<ViewNode> | undefined;
  const id = typeof node?.id === 'string' ? /^sprint\/([^/]+)\/task\/([^/]+)$/.exec(node.id) : null;
  if (!live || !id) return undefined;
  const snapshot = live.snapshots.find((s) => s.id === id[1]);
  if (!snapshot?.plan || !snapshot.states.has(id[2])) return undefined;
  const command = orderCommand(snapshot.plan.id, id[2]);
  await copyText(command);
  return command;
}

export function showNotice(notice: Notice): void {
  const message = `Bio-STEWARD: ${notice.message}`;
  const show = notice.level === 'warning' ? vscode.window.showWarningMessage : vscode.window.showInformationMessage;
  void show(message, 'Show Sprint').then((action) => {
    if (action) void vscode.commands.executeCommand(`${SPRINT_VIEW}.focus`);
  });
}
