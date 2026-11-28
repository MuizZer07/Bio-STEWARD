// A tree view over the pure view-model nodes of src/model/views.ts.
import * as vscode from 'vscode';
import { literal, treeAccessibilityLabel, type Tone, type ViewNode } from '../model/views';
import { isMarkdown } from './preview';

export const OPEN_ROW_COMMAND = 'bioSteward.row.open';

const TONE_COLOURS: Readonly<Record<Tone, string>> = Object.freeze({
  passed: 'testing.iconPassed',
  failed: 'testing.iconFailed',
  warning: 'list.warningForeground',
  info: 'charts.blue',
  disabled: 'disabledForeground',
});

export const DIMMED_NODE_SCHEME = 'bio-steward-dimmed';

// Dims tree-item labels for read notifications (alongside the "read" word and disabled icon tone).
export class DimmedDecorationProvider implements vscode.FileDecorationProvider, vscode.Disposable {
  readonly #registration = vscode.window.registerFileDecorationProvider(this);

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    if (uri.scheme !== DIMMED_NODE_SCHEME) return undefined;
    return { color: new vscode.ThemeColor('disabledForeground'), propagate: false };
  }

  dispose(): void {
    this.#registration.dispose();
  }
}

export const COMMANDS: Readonly<Record<NonNullable<ViewNode['command']>, vscode.Command>> = Object.freeze({
  runCheck: { command: 'bioSteward.runCheck', title: 'Run Check' },
  showLog: { command: 'bioSteward.showLog', title: 'Show Log' },
  checkSkills: { command: 'bioSteward.checkSkills', title: 'Check Skills' },
  installSkills: { command: 'bioSteward.installSkills', title: 'Install Agent Skills…' },
  resume: { command: 'bioSteward.resume', title: 'Resume' },
  showTimeline: { command: 'bioSteward.showTimeline', title: 'Show Milestones' },
  openFile: { command: 'bioSteward.row.open', title: 'Open File' },
  openTokenSettings: { command: 'workbench.action.openSettings', title: 'Open Settings', arguments: ['bioSteward.tokens'] },
  // A task file or a decisions log: opened by a command that checks the file again when it is clicked (U09).
  openTaskFile: { command: 'bioSteward.tasks.openFile', title: 'Open Task File' },
  openDecisionLog: { command: 'bioSteward.decisions.open', title: 'Open Decisions Log' },
  // E04: Tokens: write one agent's log setting (the row names the folder), and start a task window.
  useTokenFolder: { command: 'bioSteward.tokens.useFolder', title: 'Use This Folder' },
  startTokenWindow: { command: 'bioSteward.tokens.startWindow', title: 'Start Task Window…' },
  // E03: notification details page and Upgrade CLI modal.
  openNotification: { command: 'bioSteward.notifications.openDetails', title: 'Open Notification Details' },
  upgradeCli: { command: 'bioSteward.upgradeCli', title: 'Upgrade CLI…' },
});

export class NodeTree implements vscode.TreeDataProvider<ViewNode>, vscode.Disposable {
  #nodes: readonly ViewNode[] = [];
  readonly #roots = new Map<ViewNode, string | undefined>();
  readonly #parents = new Map<string, ViewNode>();
  readonly #changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.#changed.event;

  get nodes(): readonly ViewNode[] {
    return this.#nodes;
  }

  has(node: ViewNode): boolean {
    return this.#roots.has(node);
  }

  rootFor(node: ViewNode): string | undefined {
    return this.#roots.get(node);
  }

  set(nodes: readonly ViewNode[], root?: string): void {
    this.#nodes = nodes;
    this.#parents.clear();
    this.#roots.clear();
    const walk = (parent: ViewNode, inheritedRoot?: string) => {
      const projectRoot = parent.root ?? inheritedRoot;
      this.#roots.set(parent, projectRoot);
      for (const child of parent.children ?? []) {
        this.#parents.set(child.id, parent);
        walk(child, projectRoot);
      }
    };
    nodes.forEach((node) => walk(node, root));
    this.#changed.fire();
  }

  getChildren(node?: ViewNode): ViewNode[] {
    return [...(node ? node.children ?? [] : this.#nodes)];
  }

  getParent(node: ViewNode): ViewNode | undefined {
    return this.#parents.get(node.id);
  }

  getTreeItem(node: ViewNode): vscode.TreeItem {
    const state = node.children?.length
      ? node.expanded ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed
      : vscode.TreeItemCollapsibleState.None;
    const item = new vscode.TreeItem(literal(node.label), state);
    item.id = node.id;
    item.description = node.description === undefined ? undefined : literal(node.description);
    // A plain string tooltip is never rendered as markdown.
    item.tooltip = node.tooltip;
    item.contextValue = node.kind;
    if (node.icon) {
      item.iconPath = new vscode.ThemeIcon(node.icon.codicon,
        node.icon.tone ? new vscode.ThemeColor(TONE_COLOURS[node.icon.tone]) : undefined);
    }
    if (node.dimmed) {
      item.resourceUri = vscode.Uri.from({ scheme: DIMMED_NODE_SCHEME, path: `/${encodeURIComponent(node.id)}` });
    }
    if (node.kind === 'today-item' && node.code) item.contextValue += ` ${node.code}`;
    if (node.command && ['showLog', 'runCheck', 'checkSkills', 'installSkills', 'openTokenSettings'].includes(node.command)) {
      item.contextValue += ' next-action';
    }
    if (node.path && node.command && ['openFile', 'openTaskFile', 'openDecisionLog', 'resume'].includes(node.command)) {
      item.contextValue += isMarkdown(node.path) ? ' markdown-file' : ' editor-file';
    }
    item.command = { command: OPEN_ROW_COMMAND, title: 'Open', arguments: [node] };
    item.accessibilityInformation = { label: treeAccessibilityLabel(node.label, node.description) };
    return item;
  }

  dispose(): void {
    this.#changed.dispose();
  }
}
