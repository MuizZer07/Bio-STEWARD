// The Overview tree (M4): the CLI, the report, every gate with its blocking and waived lists, the five counts,
// the worst status and the coverage statement.
import * as vscode from 'vscode';
import { overviewNodes, type ProjectState, type ViewNode } from '../model/views';
import { NodeTree } from './tree';

export const OVERVIEW_VIEW = 'bioSteward.overview';

export class OverviewView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;

  constructor() {
    this.#view = vscode.window.createTreeView(OVERVIEW_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
  }

  update(state: ProjectState, description?: string): void {
    this.#view.description = description;
    this.tree.set(overviewNodes(state));
  }

  dispose(): void {
    this.#view.dispose();
    this.tree.dispose();
  }
}
