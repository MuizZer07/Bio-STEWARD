// P7 Drift, reduced form (RELEASE_vscode_0.2.0_SPEC §3): the timeline states only. Each open project's milestones,
// each with the state `steward timeline --json` gives it (on track, at risk, late, due, …), in the CLI's words.
// The timeline is the one the countdown already reads (src/project.ts); this view adds no CLI command.
import * as vscode from 'vscode';
import { driftNodes } from '../model/drift';
import { orderProjects } from '../model/today';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { NodeTree } from './tree';

export const DRIFT_VIEW = 'bioSteward.drift';
export const DRIFT_REFRESH_COMMAND = 'bioSteward.drift.refresh';

export class DriftView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;

  constructor() {
    this.#view = vscode.window.createTreeView(DRIFT_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
    this.#view.description = 'reduced';
  }

  // Every project, in the Today order (one block each, never mixed).
  update(projects: readonly Project[], trusted: boolean): void {
    const emptyKey = !projects.length ? 'none' : trusted ? '' : 'untrusted';
    void vscode.commands.executeCommand('setContext', 'bioSteward.driftEmpty', emptyKey);
    if (!trusted || !projects.length) {
      this.tree.set([]);
      return;
    }
    const ordered = orderProjects(projects.filter((project) => project.state.trusted), (project) => project.state.audit);
    this.tree.set(driftNodes(ordered.map((project) => ({ root: project.root, name: project.name, timeline: project.state.timeline }))));
  }

  dispose(): void {
    this.#view.dispose();
    this.tree.dispose();
  }
}
