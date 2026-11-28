// P4 Tokens (RELEASE_vscode_0.2.0_SPEC §3; design v0.6 §3): `steward tokens report --json` per task window and
// model, with totals, for every open project; **Start Task Window…** and **Done Task Window…** run `steward task
// start ID` / `steward task done ID` after a modal that shows the exact command line. The agent logs come from
// three machine settings (src/tokenLogs.ts); with none set, the panel says how to set them.
import { homedir } from 'node:os';
import * as vscode from 'vscode';
import { windowCandidates } from '../model/tasks';
import { orderProjects } from '../model/today';
import {
  isWindowId, logFolderHints, SETTING_KEYS, TOKEN_AGENTS, tokensNodes, type LogSelection, type TokenAgent,
} from '../model/tokens';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import type { RunResult } from '../cli/runner';
import { selectLogs } from '../tokenLogs';
import { shellLine } from './skills';
import { NodeTree } from './tree';

export const TOKENS_VIEW = 'bioSteward.tokens';
export const TOKENS_REFRESH_COMMAND = 'bioSteward.tokens.refresh';
export const START_WINDOW_COMMAND = 'bioSteward.tokens.startWindow';
export const DONE_WINDOW_COMMAND = 'bioSteward.tokens.doneWindow';
export const USE_FOLDER_COMMAND = 'bioSteward.tokens.useFolder';

export type Confirm = (cli: string, args: readonly string[]) => Promise<boolean>;

// The settings are machine-scoped: only the user's own settings count, never a workspace's.
export function logSettings(): Record<TokenAgent, readonly unknown[] | undefined> {
  const config = vscode.workspace.getConfiguration();
  const out = {} as Record<TokenAgent, readonly unknown[] | undefined>;
  for (const agent of TOKEN_AGENTS) {
    const value = config.inspect<unknown>(SETTING_KEYS[agent])?.globalValue;
    out[agent] = Array.isArray(value) ? value : undefined;
  }
  return out;
}

// E04: the agents whose log setting is empty (no entry that names a path), by the user's own settings.
export function emptySettings(settings = logSettings()): TokenAgent[] {
  return TOKEN_AGENTS.filter((agent) => !(settings[agent] ?? []).some((entry) => typeof entry === 'string' && entry.trim()));
}

export class TokensView implements vscode.Disposable {
  readonly tree = new NodeTree();
  readonly #view: vscode.TreeView<ViewNode>;
  #logs: LogSelection | undefined;
  // The projects whose report has been read since start-up (the first read waits until the panel is shown).
  readonly #read = new Set<Project>();
  readonly #visibility: vscode.Disposable;

  constructor(private readonly projects: () => readonly Project[], private readonly trusted: () => boolean) {
    this.#view = vscode.window.createTreeView(TOKENS_VIEW, { treeDataProvider: this.tree, showCollapseAll: true });
    // The report reads the agents' logs, so it runs when the panel is first shown, then on request.
    this.#visibility = this.#view.onDidChangeVisibility(() => this.#readUnread());
  }

  // While the panel is shown, read each project whose CLI is ready and that has not been read yet.
  #readUnread(): void {
    if (!this.#view.visible || !this.trusted()) return;
    const unread = this.projects().filter((project) => project.state.cli.kind === 'ready' && !this.#read.has(project));
    if (unread.length) void this.refresh(unread);
  }

  get logs(): LogSelection | undefined {
    return this.#logs;
  }

  // Select the logs again and run the report in every project (or in the ones given).
  async refresh(only?: readonly Project[]): Promise<void> {
    if (!this.trusted()) return;
    const projects = only ?? this.projects();
    for (const project of projects) if (project.state.cli.kind === 'ready') this.#read.add(project);
    this.#logs = await selectLogs(logSettings());
    const logs = this.#logs;
    await Promise.all(projects.map((project) => project.refreshTokens(logs)));
    this.update();
  }

  update(): void {
    const projects = this.projects();
    const trusted = this.trusted();
    const emptyKey = !projects.length ? 'none' : trusted ? '' : 'untrusted';
    void vscode.commands.executeCommand('setContext', 'bioSteward.tokensEmpty', emptyKey);
    if (!trusted || !projects.length) {
      this.tree.set([]);
      return;
    }
    this.#readUnread();
    const logs = this.#logs ?? { files: { claude: [], codex: [], gemini: [] }, problems: [], capped: {} };
    const ordered = orderProjects(projects.filter((project) => project.state.trusted), (project) => project.state.audit,
      (project) => project.state.next);
    const empty = emptySettings();
    const home = homedir();
    this.tree.set(tokensNodes(ordered.map((project) => ({
      root: project.root, name: project.name, tokens: project.state.tokens, logs, empty, hints: logFolderHints(project.root, home),
    }))));
  }

  dispose(): void {
    this.#visibility.dispose();
    this.#view.dispose();
    this.tree.dispose();
  }
}

export async function confirmWindow(cli: string, args: readonly string[]): Promise<boolean> {
  const start = args[1] === 'start';
  const answer = await vscode.window.showWarningMessage(
    start ? 'Open a task window for token reporting?' : 'Close this task window?', {
      modal: true,
      detail: `${shellLine(cli, args)}\n\nThe CLI records the time in .steward/task-tokens.jsonl. Token use is counted ` +
        'from the agent logs between start and done.',
    }, start ? 'Start Window' : 'Close Window');
  return answer === (start ? 'Start Window' : 'Close Window');
}

// What a window command acts on: a Tasks row (its file's ID line), a Tokens row (its task), or (root, ID).
export function windowTarget(projects: readonly Project[], first: unknown, second: unknown):
  { project?: Project; id?: string } {
  const node = typeof first === 'object' && first !== null ? first as Partial<ViewNode> : undefined;
  if (node?.kind === 'tokens-task' && typeof node.id === 'string') {
    const project = projects.find((p) => node.id!.startsWith(`tokens/${p.root}/`)) ?? (projects.length === 1 ? projects[0] : undefined);
    return { project, id: node.label };
  }
  if (node?.kind === 'task-file' && typeof node.path === 'string') {
    const project = projects.find((p) => node.path!.startsWith(`${p.root}/`));
    const candidate = windowCandidates(project?.state.tasks).find((c) => `${project?.root}/${c.path}` === node.path);
    return { project, id: candidate?.id };
  }
  if (typeof first === 'string' && typeof second === 'string') return { project: projects.find((p) => p.root === first), id: second };
  return {};
}

async function pickProject(projects: readonly Project[], title: string): Promise<Project | undefined> {
  if (projects.length <= 1) return projects[0];
  const picked = await vscode.window.showQuickPick(projects.map((project) => ({ label: project.name, description: project.root, project })), { title });
  return picked?.project;
}

async function pickId(project: Project, action: 'start' | 'done'): Promise<string | undefined> {
  const fromTasks = windowCandidates(project.state.tasks).map((c) => ({ label: c.id, description: c.status, detail: c.path }));
  const tokens = project.state.tokens;
  const fromReport = tokens?.kind === 'ready'
    ? tokens.report.tasks.filter((t) => isWindowId(t.task)).map((t) => ({ label: t.task, description: 'a window in steward tokens report', detail: undefined }))
    : [];
  const items = action === 'done' ? [...fromReport, ...fromTasks.filter((c) => !fromReport.some((r) => r.label === c.label))] : fromTasks;
  const other = { label: 'Another task ID…', description: '', detail: undefined };
  const picked = await vscode.window.showQuickPick([...items, other], {
    title: action === 'start' ? 'Bio-STEWARD: Start a task window for…' : 'Bio-STEWARD: Close the task window of…',
    matchOnDescription: true,
  });
  if (!picked) return undefined;
  if (picked !== other) return picked.label;
  return vscode.window.showInputBox({
    title: 'Bio-STEWARD: Task ID', prompt: 'Letters, digits and . _ : / + - (the CLI\'s task ID characters)',
    validateInput: (value) => (isWindowId(value) ? undefined : 'Use letters, digits and . _ : / + -, starting with a letter or digit'),
  });
}

// Start or close a task window. Returns the CLI's result (or undefined when nothing ran). After a run, the
// project's report is read again so the panel shows the window.
export async function taskWindow(action: 'start' | 'done', projects: readonly Project[], view: TokensView, first?: unknown,
  second?: unknown, confirm: Confirm = confirmWindow): Promise<RunResult | undefined> {
  const target = windowTarget(projects, first, second);
  const project = target.project ?? await pickProject(projects, `Bio-STEWARD: ${action === 'start' ? 'Start' : 'Close'} a task window in…`);
  if (!project) return undefined;
  if (project.state.cli.kind !== 'ready') {
    void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required for task windows.');
    return undefined;
  }
  const id = target.id ?? await pickId(project, action);
  if (!id) return undefined;
  if (!isWindowId(id)) {
    void vscode.window.showWarningMessage('Bio-STEWARD: That task ID has characters the CLI does not accept.');
    return undefined;
  }
  const result = await project.taskWindow(action, id, confirm);
  if (result.kind === 'completed') {
    const said = (result.exitCode === 0 ? result.stdout : result.stderr).trim();
    if (result.exitCode === 0) void vscode.window.showInformationMessage(`Bio-STEWARD: ${said || `steward task ${action} ${id}`}`);
    else void vscode.window.showWarningMessage(`Bio-STEWARD: ${said || `steward task ${action} ${id} exited ${result.exitCode}`}`);
    await view.refresh([project]);
  } else if (result.kind !== 'unconfirmed' && result.kind !== 'cancelled') {
    void vscode.window.showWarningMessage(`Bio-STEWARD: steward task ${action} did not run (${result.kind}). See the Bio-STEWARD log.`);
  }
  return result;
}

// E04: **Use this folder**: set one agent's log setting to the folder it usually keeps an open project's logs in.
// Only that folder (as the panel computed it for an open project), only while the setting is empty, and only in the
// user's own settings (the setting is machine-scoped). Nothing is read before the write; the report is read after it.
export async function useFolder(projects: readonly Project[], view: TokensView, input: unknown): Promise<boolean> {
  if (!vscode.workspace.isTrusted || typeof input !== 'object' || input === null) return false;
  // The row's click passes { agent, path }; its inline button passes the row itself (the agent is its code).
  const row = input as { agent?: unknown; code?: unknown; kind?: unknown; path?: unknown };
  const agent = row.kind === 'tokens-use-folder' ? row.code : row.agent;
  const { path } = row;
  if (typeof agent !== 'string' || !(TOKEN_AGENTS as readonly string[]).includes(agent) || typeof path !== 'string') return false;
  const key = agent as TokenAgent;
  const home = homedir();
  if (!projects.some((project) => logFolderHints(project.root, home)[key] === path) || !emptySettings().includes(key)) return false;
  await vscode.workspace.getConfiguration().update(SETTING_KEYS[key], [path], vscode.ConfigurationTarget.Global);
  void vscode.window.showInformationMessage(`Bio-STEWARD: ${SETTING_KEYS[key]} is now [${path}] in your user settings.`);
  await view.refresh();
  return true;
}
