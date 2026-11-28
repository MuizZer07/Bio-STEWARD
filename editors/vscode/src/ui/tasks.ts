// P3 Tasks (RELEASE_vscode_0.2.0_SPEC §3, AC-P3): a tree of every open project's task files, each
// with its Status line as written, "read from the file". Read-only: the files are read by src/taskFiles.ts; with CLI
// 0.21 and later, the rows come from `steward task board --format json` (E04). A row opens its file, after checking
// it again (U09).
import * as vscode from 'vscode';
import { unlinkedFile } from '../cli/paths';
import { tasksNodes } from '../model/tasks';
import { orderProjects } from '../model/today';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { NodeTree } from './tree';
import { openFile } from './preview';

export const TASKS_VIEW = 'bioSteward.tasks';
export const TASKS_REFRESH_COMMAND = 'bioSteward.tasks.refresh';
export const OPEN_TASK_FILE_COMMAND = 'bioSteward.tasks.openFile';

export class TasksView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;

  constructor() {
    this.#view = vscode.window.createTreeView(TASKS_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
  }

  // Every project, in the Today order (one block each, never mixed).
  update(projects: readonly Project[], trusted: boolean): void {
    const emptyKey = !projects.length ? 'none' : trusted ? '' : 'untrusted';
    void vscode.commands.executeCommand('setContext', 'bioSteward.tasksEmpty', emptyKey);
    if (!trusted || !projects.length) {
      this.tree.set([]);
      return;
    }
    const ordered = orderProjects(projects.filter((project) => project.state.trusted), (project) => project.state.audit, (project) => project.state.next);
    this.tree.set(tasksNodes(ordered.map((project) => ({
      root: project.root, name: project.name, tasks: project.state.tasks, board: project.state.board,
    }))));
  }

  dispose(): void {
    this.#view.dispose();
    this.tree.dispose();
  }
}

// A row's file, opened only if it is still a task file the panel listed for that project and still a regular file
// inside the project reached without a link and not through `.git` (checked when it is clicked).
export async function openTaskFile(projects: readonly Project[], input: unknown, asText = false): Promise<vscode.Uri | undefined> {
  if (!vscode.workspace.isTrusted || typeof input !== 'object' || input === null) return undefined;
  const { root, path } = input as Partial<ViewNode>;
  const project = projects.find((p) => p.root === root);
  const tasks = project?.state.tasks;
  const board = project?.state.board;
  if (!project || !project.state.trusted || typeof path !== 'string') return undefined;
  // A file the panel listed: one of the task files, or (full form, E04) a task of the CLI's board.
  const listed = (tasks?.kind === 'ready' ? tasks.files : []).find((file) => `${project.root}/${file.path}` === path) ??
    (board?.kind === 'ready' ? board.doc.tasks : []).find((task) => `${project.root}/${task.path}` === path);
  if (!listed) return undefined;
  if (!await unlinkedFile(project.root, listed.path)) {
    void vscode.window.showWarningMessage(`Bio-STEWARD: ${listed.path} is no longer a regular file reached without a link. Nothing was opened.`);
    return undefined;
  }
  const uri = vscode.Uri.file(`${project.root}/${listed.path}`);
  await openFile(uri, asText);
  return uri;
}
