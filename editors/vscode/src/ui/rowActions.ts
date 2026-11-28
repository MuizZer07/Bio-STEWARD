import { createHash } from 'node:crypto';
import { join, relative, sep } from 'node:path';
import * as vscode from 'vscode';
import { commands } from '../cli/commands';
import { unlinkedFile } from '../cli/paths';
import { MILESTONES_FILE } from '../model/drift';
import { projectFiles, resultAnchors } from '../model/findings';
import type { ResultItem } from '../model/report';
import type { PanelId } from '../model/panels';
import { skillsResult } from '../model/skills';
import { tasksNewestFirst, waitsForOrder } from '../model/sprint';
import { nextMilestone, progressLines } from '../model/timeline';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';
import { copyForAgent } from './agent';
import { copyText } from './clipboard';
import { openDecisions } from './decisions';
import { DetailsView, openFile } from './preview';
import type { ResumeView } from './resume';
import { copyBriefText } from './rowBrief';
import { shellLine } from './skills';
import type { LiveSprint } from './sprint';
import { openTaskFile } from './tasks';
import { COMMANDS, type NodeTree } from './tree';

type TreePanel = Exclude<PanelId, 'approvals'>;
const SOURCES: Record<TreePanel, string> = {
  overview: 'steward check',
  results: 'steward check',
  today: 'steward audit progress',
  tasks: 'Task files named by steward.toml',
  tokens: 'steward tokens report',
  decisions: 'Decisions logs named by steward.toml',
  drift: 'steward timeline',
  sprint: 'Sprint plan and ledger under development/sprints',
  skills: 'Skill folders and the R-60 result from steward check',
};

type Row = { node: ViewNode; panel: TreePanel; project?: Project };
type Exchange = { id: string; place: string; state: string; title?: string; peer?: string };

function exchangeRows(stdout: string): Exchange[] {
  const items: unknown = JSON.parse(stdout);
  if (!Array.isArray(items)) return [];
  return items.flatMap((item: unknown) => {
    if (!item || typeof item !== 'object') return [];
    const r = item as Record<string, unknown>;
    if (typeof r.id !== 'string' || typeof r.place !== 'string' || typeof r.state !== 'string') return [];
    const delivery = r.delivery as { peer?: unknown } | undefined;
    return [{ id: r.id, place: r.place, state: r.state, title: typeof r.title === 'string' ? r.title : undefined,
      peer: typeof delivery?.peer === 'string' ? delivery.peer : undefined }];
  });
}

function nextStep({ node, panel }: Row): string {
  if (node.next) return node.next;
  if (node.ref) return 'Explain the rule, open its file if available, or re-check the rule.';
  if (node.kind === 'gate' || node.kind === 'blocking') return 'Review the blocking results before continuing.';
  if (node.kind === 'tokens-task') return 'Show the per-model split or open the corresponding task.';
  if (node.kind === 'today-milestone') return 'Show what blocks this milestone or open its configuration.';
  if (node.kind === 'sprint-task-waiting') return 'Copy the order command for the task you want to start.';
  if (node.kind === 'sprint-task') return 'Open the recorded run log to review the task.';
  if (node.children?.length) return 'Expand this row to inspect its entries.';
  if (node.command) return COMMANDS[node.command].title + '.';
  return `Refresh the ${panel === 'drift' ? 'Milestones and Drift' : panel} panel to check for updates.`;
}

export class RowActions {
  constructor(
    private readonly trees: Readonly<Record<TreePanel, NodeTree>>,
    private readonly projects: () => readonly Project[],
    private readonly liveSprint: (project: Project) => LiveSprint | undefined,
    private readonly selectProject: (project: Project) => void,
    private readonly details: DetailsView,
    private readonly resume: ResumeView,
    private readonly state: vscode.Memento,
    private readonly updateToday: () => Promise<void>,
    private readonly trusted: () => boolean,
  ) {}

  resolve(input: unknown): Row | undefined {
    if (!this.trusted() || typeof input !== 'object' || input === null) return;
    const node = input as ViewNode;
    for (const panel of Object.keys(this.trees) as TreePanel[]) {
      const tree = this.trees[panel];
      if (!tree.has(node)) continue;
      const root = tree.rootFor(node);
      const project = this.projects().find((p) => p.root === root && p.state.trusted);
      if (root && !project) return;
      return { node, panel, project };
    }
    return undefined;
  }

  async open(row: Row, asText = false): Promise<vscode.Uri | undefined> {
    const { node, project } = row;
    switch (node.command) {
      case 'openTaskFile': return openTaskFile(this.projects(), node, asText);
      case 'openDecisionLog': return openDecisions(this.projects(), node, asText);
      case 'openFile': return project && node.path ? this.projectFile(project, node.path, asText) : undefined;
      case 'resume': {
        const uri = await this.resume.show(project, asText);
        if (uri || asText) return uri;
        break;
      }
      // Rows whose click is an action of its own (E03: notifications, Upgrade CLI; E04: Tokens), not a page to open.
      case 'openNotification':
        if (asText || node.root === undefined || node.notificationId === undefined) return;
        return (await vscode.commands.executeCommand<vscode.TextDocument | undefined>(COMMANDS.openNotification.command,
          { root: node.root, id: node.notificationId }))?.uri;
      case 'useTokenFolder':
        if (!asText && node.path !== undefined && node.code !== undefined) {
          await vscode.commands.executeCommand(COMMANDS.useTokenFolder.command, { agent: node.code, path: node.path });
        }
        return;
      case 'startTokenWindow':
        if (!asText) await vscode.commands.executeCommand(COMMANDS.startTokenWindow.command);
        return;
      case 'upgradeCli':
        if (!asText) await vscode.commands.executeCommand(COMMANDS.upgradeCli.command, node.root);
        return;
    }
    if (asText) return;
    if (node.kind === 'today-item' && (node.code === 'exchange' || node.code === 'own')) {
      return this.exchange(row, 'details');
    }
    const model = row.node.kind === 'tokens-task' ? this.modelSplit(row.node) : '';
    const meaning = [...new Set([node.description, node.tooltip, model].filter(Boolean))].join('\n') || node.label;
    return this.details.show(node.label, node.source ?? SOURCES[row.panel], meaning, nextStep(row));
  }

  async useFile(row: Row, action: 'copy' | 'reveal'): Promise<vscode.Uri | undefined> {
    if (row.node.command === 'resume' && row.project) {
      const handoff = await row.project.readHandoff();
      return handoff.kind === 'found' ? this.projectFile(row.project, handoff.path, false, action) : undefined;
    }
    if (!row.project || !row.node.path) return;
    return this.projectFile(row.project, row.node.path, false, action);
  }

  async projectFile(project: Project, path: string, asText = false, action = 'open', line?: number): Promise<vscode.Uri | undefined> {
    const rel = path.startsWith(`${project.root}/`) ? relative(project.root, path).split(sep).join('/') : path;
    if (rel.split('/').some((part) => part.toLowerCase() === '.git') || !await unlinkedFile(project.root, rel) || !this.trusted() || !this.projects().includes(project)) {
      void vscode.window.showWarningMessage('Bio-STEWARD: This file is no longer available inside the project.');
      return;
    }
    const uri = vscode.Uri.joinPath(vscode.Uri.file(project.root), rel);
    if (action === 'copy') await copyText(uri.fsPath);
    else if (action === 'reveal') await vscode.commands.executeCommand('revealInExplorer', uri);
    else await openFile(uri, asText, line);
    return uri;
  }

  async openFinding({ project, node, panel }: Row): Promise<vscode.Uri | undefined> {
    if (!project || !node.ref) return;
    const { state } = project;
    const loaded = panel === 'overview' ? state.full : state.partial ?? state.full;
    const ref = node.ref;
    const results = loaded?.report.verdict.results;
    const matches = (result: ResultItem | undefined) =>
      result?.rule === ref.rule && result.subject === ref.subject && result.status === ref.status;
    const indexed = ref.index === undefined ? undefined : results?.[ref.index];
    const fromReport = matches(indexed) ? indexed : results?.find(matches);
    const result = panel === 'skills' ? skillsResult(state)?.result : fromReport;
    const lookup = projectFiles(project.root);
    const detail = node.anchor && await lookup(node.anchor.path);
    if (detail && node.anchor) {
      const line = node.anchor.line;
      return this.projectFile(project, detail, false, 'open', line && Number.isSafeInteger(line) && line > 0 ? line : undefined);
    }
    const [anchor] = result && !node.anchor ? await resultAnchors(result, lookup) : [];
    if (anchor) return this.projectFile(project, anchor.path, false, 'open', anchor.line);
    void vscode.window.showInformationMessage('Bio-STEWARD: This result has no project file to open.');
    return undefined;
  }

  async handToAgent(row: Row): Promise<string | undefined> {
    const { node, project } = row;
    if (!project) return;
    if (node.ref) return copyForAgent(project, node);
    const task = node.kind === 'task-file' ? await this.taskPath(row) : undefined;
    if (node.kind === 'task-file' && !task) return;
    if (!task && !project.supportsNextBrief) {
      void vscode.window.showInformationMessage('Bio-STEWARD: The next-step brief requires steward 0.21 or newer with the next command.');
      return;
    }
    // Relative to the project: the runner resolves it against its canonical root, so a project reached through a
    // link (macOS /tmp is /private/tmp) is still recognised as the project's own file.
    const invocation = task ? commands.taskBrief(task) : commands.nextBrief();
    const command = task ? 'steward task brief' : 'steward next --brief';
    const result = await project.rowRead(invocation);
    if (result?.kind === 'completed' && result.exitCode === 0 && result.stdout.trim()) {
      return copyBriefText(command, result.stdout);
    }
    void vscode.window.showWarningMessage(task ? 'Bio-STEWARD: Could not generate the task brief. See the Bio-STEWARD log.'
      : 'Bio-STEWARD: Could not generate the next-step brief. This action needs steward 0.21 or newer and a configured project.');
    return undefined;
  }

  async taskPath({ project, node }: Row): Promise<string | undefined> {
    const tasks = project?.state.tasks;
    const file = project && tasks?.kind === 'ready' && tasks.files.find(({ path }) => `${project.root}/${path}` === node.path);
    if (file && await unlinkedFile(project.root, file.path)) return file.path;
    void vscode.window.showWarningMessage('Bio-STEWARD: Refresh Tasks to find an available task file.');
    return undefined;
  }

  async dispatch(row: Row): Promise<void> {
    const project = row.project;
    if (!project?.cliPath) return;
    const task = await this.taskPath(row);
    if (!task) return;
    const command = shellLine(project.cliPath, ['task', 'dispatch', '--repo', project.root, join(project.root, task), '--to', 'codex']);
    const answer = await vscode.window.showWarningMessage('Copy the Codex dispatch command?', {
      modal: true, detail: `${command}\n\nRun this in your terminal when you are ready to launch Codex for a review.`,
    }, 'Copy Command');
    if (answer === 'Copy Command' && this.trusted() && this.projects().includes(project)) await copyText(command);
  }

  async openTokenTask({ node, project }: Row): Promise<vscode.Uri | undefined> {
    if (!project) return;
    const tasks = project.state.tasks;
    const matches = tasks?.kind === 'ready' ? tasks.files.filter((file) => file.id === node.label) : [];
    if (matches.length === 1) return openTaskFile(this.projects(), { root: project.root, path: `${project.root}/${matches[0].path}` });
    if (matches.length > 1) {
      const chosen = await vscode.window.showQuickPick(matches.map((file) => file.path), { title: 'Open task file' });
      if (chosen) return openTaskFile(this.projects(), { root: project.root, path: `${project.root}/${chosen}` });
      return;
    }
    void vscode.window.showInformationMessage('Bio-STEWARD: No task file matches this token window.');
    return undefined;
  }

  modelSplit(node: ViewNode): string {
    return (node.children ?? []).filter((child) => child.kind === 'tokens-model')
      .map((child) => `${child.label}\n${child.tooltip ?? child.description ?? ''}`).join('\n\n');
  }

  async showModels({ node }: Row): Promise<vscode.Uri> {
    return this.details.show(node.label, SOURCES.tokens, this.modelSplit(node) || 'The CLI reported no per-model counts.',
      'Open the task to review the work associated with this window.');
  }

  async showBlockers({ node, project }: Row): Promise<vscode.Uri | undefined> {
    const timeline = project?.state.timeline;
    const id = node.code === 'milestones' ? node.label : node.code;
    const milestone = timeline?.kind === 'ready'
      ? id ? timeline.rows.find((m) => m.id === id) : nextMilestone(timeline.rows) : undefined;
    const progress = milestone ? progressLines(milestone) : [];
    return this.details.show(milestone?.title ?? node.label, SOURCES.drift,
      [...(milestone ? [milestone.state] : []), ...(progress.length ? progress : ['The CLI reported no blocker details for this milestone.'])].join('\n'),
      'Open the milestones file to review its configured work, or use Hand to Agent for the CLI next-step brief.');
  }

  async todayNext(row: Row): Promise<unknown> {
    const { project, node } = row;
    if (!project) return;
    if (node.code === 'signatures') return vscode.commands.executeCommand('bioSteward.approvals.focus');
    if (node.code === 'exchange' || node.code === 'own') return this.exchange(row, 'open');
    if (node.code === 'milestones' || node.kind === 'today-milestone') return this.showBlockers(row);
    if (node.code === 'sprints') {
      const sprint = this.liveSprint(project)?.snapshots.find((s) => s.id === node.label);
      const plan = sprint?.plan;
      if (plan && sprint) {
        const waiting = tasksNewestFirst(sprint).map((id) => sprint.states.get(id)!).filter((s) => waitsForOrder(plan, s));
        if (waiting.length === 1) return this.copyCommand('steward', ['sprint', 'go', '--repo', project.root, sprint.id, waiting[0].id]);
      }
      this.selectProject(project);
      return vscode.commands.executeCommand('bioSteward.sprint.focus');
    }
    return undefined;
  }

  async exchange({ node, project }: Row, action: 'open' | 'pull' | 'respond' | 'read' | 'details'): Promise<vscode.Uri | undefined> {
    if (!project || (node.code !== 'exchange' && node.code !== 'own')) return;
    const result = await project.rowRead(commands.exchangeStatus());
    if (result?.kind !== 'completed' || result.exitCode !== 0) {
      return this.details.show(node.label, SOURCES.today, 'Exchange status is unavailable.',
        'Check the project exchange configuration, then refresh Today.');
    }
    let item: Exchange | undefined;
    try {
      item = exchangeRows(result.stdout).find((candidate) => candidate.id === node.label);
    } catch {
      // The CLI response may be unreadable.
    }
    if (!item) return this.details.show(node.label, 'steward exchange status', 'The current CLI listing has no matching item.', 'Refresh Today.');
    const local = /^(inbox|outbox|responses)$/.test(item.place) && /^[a-z\d_-]+$/i.test(item.id);
    const path = local ? `exchange/${item.place}/${item.id}.md` : undefined;
    if (action === 'pull' && item.place === 'peer' && item.peer && /^[a-z\d_]+$/i.test(item.peer)) {
      await this.copyCommand('steward', ['exchange', 'pull', '--repo', project.root, item.peer]);
      return;
    }
    if (action === 'respond' && item.place === 'inbox') {
      const document = await vscode.workspace.openTextDocument({ language: 'markdown',
        content: `# Response draft\n\nItem: ${item.id.replace(/[\r\n]/g, ' ')}\n\n## Decision\n\n## Reason or evidence\n\n` });
      await vscode.window.showTextDocument(document);
      return document.uri;
    }
    if (action === 'read') {
      const key = exchangeReadKey(project.root, item.id);
      await this.state.update(key, true);
      await this.updateToday();
      return;
    }
    if (action === 'open' && path && await unlinkedFile(project.root, path)) return this.projectFile(project, path);
    return this.details.show(item.title || node.label, 'steward exchange status', `${item.id} · ${item.place} · ${item.state}`,
      item.place === 'peer' ? 'Copy the pull command and run it to retrieve this peer’s items.'
        : 'Open the item file when it is available or refresh Today for the current state.');
  }

  async sprint({ node, project }: Row, action: 'log' | 'hold' | 'diff'): Promise<vscode.Uri | undefined> {
    if (!project) return;
    const [, sprintId, , taskId] = node.id.split('/');
    const sprint = this.liveSprint(project)?.snapshots.find((s) => s.id === sprintId);
    const task = sprint?.states.get(taskId);
    if (!sprint?.plan || !task) return;
    if (action === 'hold') {
      if (!waitsForOrder(sprint.plan, task) && !(task.state === 'ready' && task.go && !task.hold)) return;
      await this.copyCommand('steward', ['sprint', 'hold', '--repo', project.root, sprintId, taskId]);
      return;
    }
    const entries = sprint.ledger?.entries ?? [];
    const run = [...entries].reverse().find((e) => e.kind === 'state' && e.raw.task === taskId && e.raw.state === 'running')?.raw;
    if (action === 'diff') {
      const sha = (v: unknown): v is string => typeof v === 'string' && /^[a-f\d]{40,64}$/i.test(v);
      if (task.state === 'done' && sha(run?.base_commit) && sha(task.commit)) {
        const command = shellLine('git', ['-C', project.root, 'diff', '--no-ext-diff', '--no-textconv', run.base_commit, task.commit, '--']);
        return this.details.show(node.label, sprint.ledgerFile, command, 'Run the displayed command to view the recorded revision range.');
      }
      return this.details.show(node.label, sprint.ledgerFile, 'The ledger has no recorded base and head revision for this completed task.',
        'Open the run log or review the sprint ledger.');
    }
    for (const log of [run?.run_log, run?.log]) {
      if (typeof log === 'string' && await unlinkedFile(project.root, log)) return this.projectFile(project, log);
    }
    return this.details.show(node.label, sprint.ledgerFile, 'The ledger has no run log for this task yet.', 'Refresh Sprint after the task starts.');
  }

  async copyCommand(cli: string, args: readonly string[]): Promise<void> {
    await copyText(shellLine(cli, args));
    void vscode.window.showInformationMessage(`Bio-STEWARD: Copied the ${args.slice(0, 2).join(' ')} command.`);
  }

  async openMilestone({ project }: Row): Promise<vscode.Uri | undefined> {
    return project && this.projectFile(project, MILESTONES_FILE);
  }
}

export function exchangeReadKey(root: string, id: string): string {
  return 'bioSteward.exchange.read.' + createHash('sha256').update(JSON.stringify([root, id])).digest('hex');
}

