// A tree view over the pure view-model nodes of src/model/views.ts.
import * as vscode from 'vscode';
import { literal, treeAccessibilityLabel, type Tone, type ViewNode } from '../model/views';

const TONE_COLOURS: Readonly<Record<Tone, string>> = Object.freeze({
  passed: 'testing.iconPassed',
  failed: 'testing.iconFailed',
  warning: 'list.warningForeground',
  info: 'charts.blue',
  disabled: 'disabledForeground',
});

const COMMANDS: Readonly<Record<NonNullable<ViewNode['command']>, vscode.Command>> = Object.freeze({
  runCheck: { command: 'bioSteward.runCheck', title: 'Run Check' },
  showLog: { command: 'bioSteward.showLog', title: 'Show Log' },
  checkSkills: { command: 'bioSteward.checkSkills', title: 'Check Skills' },
  installSkills: { command: 'bioSteward.installSkills', title: 'Install Agent Skills…' },
  resume: { command: 'bioSteward.resume', title: 'Resume' },
  showTimeline: { command: 'bioSteward.showTimeline', title: 'Show Milestones' },
  openFile: { command: 'vscode.open', title: 'Open File' },
  openTokenSettings: { command: 'workbench.action.openSettings', title: 'Open Settings', arguments: ['bioSteward.tokens'] },
  // A task file or a decisions log: opened by a command that checks the file again when it is clicked (U09).
  openTaskFile: { command: 'bioSteward.tasks.openFile', title: 'Open Task File' },
  openDecisionLog: { command: 'bioSteward.decisions.open', title: 'Open Decisions Log' },
});

export class NodeTree implements vscode.TreeDataProvider<ViewNode>, vscode.Disposable {
  #nodes: readonly ViewNode[] = [];
  readonly #parents = new Map<string, ViewNode>();
  readonly #changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.#changed.event;

  get nodes(): readonly ViewNode[] {
    return this.#nodes;
  }

  set(nodes: readonly ViewNode[]): void {
    this.#nodes = nodes;
    this.#parents.clear();
    const walk = (parent: ViewNode) => {
      for (const child of parent.children ?? []) {
        this.#parents.set(child.id, parent);
        walk(child);
      }
    };
    nodes.forEach(walk);
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
    if (node.command === 'openFile') {
      if (node.path !== undefined) item.command = { ...COMMANDS.openFile, arguments: [vscode.Uri.file(node.path)] };
    } else if (node.command === 'openTaskFile' || node.command === 'openDecisionLog') {
      if (node.path !== undefined && node.root !== undefined) {
        item.command = { ...COMMANDS[node.command], arguments: [{ root: node.root, path: node.path }] };
      }
    } else if (node.command) {
      item.command = node.root === undefined ? COMMANDS[node.command] : { ...COMMANDS[node.command], arguments: [node.root] };
    }
    item.accessibilityInformation = { label: treeAccessibilityLabel(node.label, node.description) };
    return item;
  }

  dispose(): void {
    this.#changed.dispose();
  }
}
