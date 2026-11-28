// P6 Decisions (RELEASE_vscode_0.2.0_SPEC §3): **Open DECISIONS.md**. The panel names each
// open project's decisions log for preview. The owner can open the source or start an entry in the editor.
import * as vscode from 'vscode';
import { unlinkedFile } from '../cli/paths';
import { decisionsNodes, firstLog, primaryLog, type DecisionLog, type DecisionsState } from '../model/decisions';
import { orderProjects } from '../model/today';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { NodeTree } from './tree';
import { openFile } from './preview';

export const DECISIONS_VIEW = 'bioSteward.decisions';
export const DECISIONS_REFRESH_COMMAND = 'bioSteward.decisions.refresh';
export const OPEN_DECISIONS_COMMAND = 'bioSteward.decisions.open';

export class DecisionsView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;

  constructor() {
    this.#view = vscode.window.createTreeView(DECISIONS_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
  }

  // Every project, in the Today order (one block each, never mixed).
  update(projects: readonly Project[], trusted: boolean): void {
    const emptyKey = !projects.length ? 'none' : trusted ? '' : 'untrusted';
    void vscode.commands.executeCommand('setContext', 'bioSteward.decisionsEmpty', emptyKey);
    if (!trusted || !projects.length) {
      this.tree.set([]);
      return;
    }
    const ordered = orderProjects(projects.filter((project) => project.state.trusted), (project) => project.state.audit,
      (project) => project.state.next);
    this.tree.set(decisionsNodes(ordered.map((project) => ({
      root: project.root, name: project.name, decisions: project.state.decisions, doc: project.state.decisionsDoc,
    }))));
  }

  dispose(): void {
    this.#view.dispose();
    this.tree.dispose();
  }
}

// The project a command acts on: a row's root, a root given as an argument, the only project, or a pick.
async function chooseProject(projects: readonly Project[], input: unknown): Promise<Project | undefined> {
  const root = typeof input === 'string' ? input : typeof input === 'object' && input !== null ? (input as Partial<ViewNode>).root : undefined;
  if (root !== undefined) return projects.find((project) => project.root === root);
  if (projects.length <= 1) return projects[0];
  const ordered = orderProjects(projects, (project) => project.state.audit);
  const picked = await vscode.window.showQuickPick(ordered.map((project) => ({
    label: project.name, description: firstLog(project.state.decisions)?.path ?? '', detail: project.root, project,
  })), { title: 'Bio-STEWARD: Open DECISIONS.md of…' });
  return picked?.project;
}

const describe = (state: DecisionsState | undefined) =>
  state?.kind === 'ready' ? state.logs.map((log) => log.path).join(', ') || 'none' : undefined;

// The log a row names (its absolute path), if it is one of the project's listed logs.
function rowLog(state: DecisionsState | undefined, root: string, input: unknown): DecisionLog | undefined {
  const path = typeof input === 'object' && input !== null ? (input as Partial<ViewNode>).path : undefined;
  if (typeof path !== 'string' || state?.kind !== 'ready' || !path.startsWith(`${root}/`)) return undefined;
  return state.logs.find((log) => log.exists && `${root}/${log.path}` === path);
}

// Open or draft an entry in the first existing decisions log, or the log selected by the row.
// Returns the file opened, or undefined. A missing log is reported, never created. The file is checked again when
// it is opened (U09): a regular file inside the project, reached without a link and not through `.git`.
export async function openDecisions(projects: readonly Project[], input: unknown, asText = false, draft = false): Promise<vscode.Uri | undefined> {
  if (!vscode.workspace.isTrusted) return undefined;
  const project = await chooseProject(projects, input);
  if (!project || !project.state.trusted) return undefined;
  const state = project.state.decisions?.kind === 'ready' ? project.state.decisions : await project.refreshDecisions();
  if (state?.kind === 'unreadable') {
    void vscode.window.showWarningMessage(`Bio-STEWARD: The decisions log of ${project.name} could not be found: ${state.reason}.`);
    return undefined;
  }
  const row = typeof input === 'object' && input !== null && 'path' in input;
  const log = row ? rowLog(state, project.root, input) : firstLog(state);
  if (!log) {
    if (row) return undefined;
    void vscode.window.showInformationMessage(`Bio-STEWARD: No decisions log in ${project.name} (looked for ${describe(state) ?? 'it'}). ` +
      'Bio-STEWARD does not create it; `steward init` writes one, or start it yourself.');
    return undefined;
  }
  if (!await unlinkedFile(project.root, log.path)) {
    void vscode.window.showWarningMessage(`Bio-STEWARD: ${log.path} in ${project.name} is no longer a regular file reached without a link. ` +
      'Nothing was opened.');
    return undefined;
  }
  // Checked under the canonical root; opened under the project's root as the session names it (the root itself is
  // taken as given, as the CLI takes `--repo`).
  const uri = vscode.Uri.file(`${project.root}/${log.path}`);
  if (draft) {
    const editor = await vscode.window.showTextDocument(uri, { preview: false });
    const end = editor.document.positionAt(editor.document.getText().length);
    const today = new Date();
    const date = [today.getFullYear(), today.getMonth() + 1, today.getDate()]
      .map((part) => String(part).padStart(2, '0')).join('-');
    await editor.insertSnippet(new vscode.SnippetString(`\n\n## ${date}: \${1:short title}\n- **Quote:** "$2"\n- **Decision:** $3\n- **Consequences:** $0\n`), end);
  } else {
    await openFile(uri, asText);
  }
  if (!row && state?.kind === 'ready' && log.path !== primaryLog(state.settings)) {
    vscode.window.setStatusBarMessage(`Bio-STEWARD: opened ${log.path}, the first decisions log that exists ` +
      `(the CLI's single-path commands use ${primaryLog(state.settings)})`, 10000);
  }
  return uri;
}
