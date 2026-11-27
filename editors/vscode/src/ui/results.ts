// The Results tree (M4): every result of the newest report, grouped by status, gate or file.
import * as vscode from 'vscode';
import { projectFiles, resultAnchors } from '../model/findings';
import { GROUP_BY, resultsNodes, type GroupBy, type ProjectState, type ViewNode } from '../model/views';
import { NodeTree } from './tree';

export const RESULTS_VIEW = 'bioSteward.results';
const GROUP_KEY = 'bioSteward.results.groupBy';

const GROUP_LABELS: Readonly<Record<GroupBy, string>> = Object.freeze({
  status: 'Status',
  gate: 'Gate',
  file: 'File',
});

export class ResultsView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;
  #groupBy: GroupBy;
  #state: ProjectState | undefined;
  #generation = 0;

  #root = '';
  #project: string | undefined;

  constructor(private readonly memento: vscode.Memento) {
    const saved = memento.get<string>(GROUP_KEY);
    this.#groupBy = GROUP_BY.find((g) => g === saved) ?? 'status';
    this.#view = vscode.window.createTreeView(RESULTS_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
    this.#describe();
  }

  get groupBy(): GroupBy {
    return this.#groupBy;
  }

  #describe(): void {
    const group = `by ${GROUP_LABELS[this.#groupBy].toLowerCase()}`;
    this.#view.description = this.#project ? `${this.#project} · ${group}` : group;
  }

  // `root` is the project the state belongs to; `project` names it when several are open (S2).
  async update(state: ProjectState, root: string = this.#root, project?: string): Promise<void> {
    this.#state = state;
    this.#root = root;
    if (project !== this.#project) {
      this.#project = project;
      this.#describe();
    }
    const generation = ++this.#generation;
    const groupBy = this.#groupBy;
    const loaded = state.partial ?? state.full;
    let files: (string | undefined)[] | undefined;
    if (groupBy === 'file' && state.trusted && loaded) {
      const file = projectFiles(root);
      files = [];
      for (const result of loaded.report.verdict.results) {
        if (generation !== this.#generation) return;
        const [anchor] = await resultAnchors(result, file);
        files.push(anchor?.path);
      }
    }
    if (generation === this.#generation) this.tree.set(resultsNodes(state, groupBy, files));
  }

  // `bioSteward.results.groupBy`: with an argument (status, gate, file), or from a quick pick.
  async chooseGroup(choice?: unknown): Promise<void> {
    let next = GROUP_BY.find((g) => g === choice);
    if (!next) {
      const picked = await vscode.window.showQuickPick(
        GROUP_BY.map((g) => ({ label: GROUP_LABELS[g], value: g, picked: g === this.#groupBy })),
        { title: 'Group results by' });
      next = picked?.value;
    }
    if (!next) return;
    this.#groupBy = next;
    await this.memento.update(GROUP_KEY, next);
    this.#describe();
    if (this.#state) await this.update(this.#state, this.#root, this.#project);
  }

  dispose(): void {
    this.#generation++;
    this.#view.dispose();
    this.tree.dispose();
  }
}
