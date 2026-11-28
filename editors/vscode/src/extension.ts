import * as vscode from 'vscode';
import { isRuleId } from './cli/commands';
import { FeatureDetector } from './cli/features';
import { isWithin } from './cli/paths';
import { printedSkillsTable } from './model/skills';
import { emptyState } from './model/views';
import { SaveTrigger, triggersCheck } from './onSave';
import { Project, storageFor } from './project';
import { ActiveProject, canInitialize, localFolders, projectFolders, type Folder } from './projects';
import { CHECK_AREA_COMMAND, CHECK_RULE_COMMAND, checkArea, checkRule, COPY_FOR_AGENT_COMMAND, copyForAgent } from './ui/agent';
import { copyText, lastCopy } from './ui/clipboard';
import { CountdownStatusBar, pickMilestone, TIMELINE_COMMAND } from './ui/countdown';
import { COPY_EXPLAIN_COMMAND, EXPLAIN_COMMAND, ExplainView } from './ui/explain';
import { APPLY_INIT_COMMAND, INIT_COMMAND, INIT_WALKTHROUGH_COMMAND, InitView, pickInitOptions } from './ui/init';
import { OVERVIEW_VIEW, OverviewView } from './ui/overview';
import { ProblemsView } from './ui/problems';
import { ResultsView } from './ui/results';
import { RESUME_COMMAND, ResumeView } from './ui/resume';
import {
  APPLY_SKILLS_COMMAND, CHECK_SKILLS_COMMAND, INSTALL_SKILLS_COMMAND, pickSkillsInstall, REFRESH_SKILLS_COMMAND,
  SkillsInstall, SkillsView,
} from './ui/skills';
import {
  copyOrderCommand, LiveSprint, showNotice, SPRINT_COPY_ORDER_COMMAND, SPRINT_REFRESH_COMMAND, SPRINT_SHOW_COMMAND,
  SPRINT_VIEW, SprintStatusBar, SprintView,
} from './ui/sprint';
import { VerdictStatusBar } from './ui/statusbar';
import {
  chooseProject, COPY_BRIEF_COMMAND, copyBrief, detected, LastSeen, reopenedProjects, TODAY_REFRESH_COMMAND,
  TodayView, WHERE_AM_I_COMMAND, WhereAmIView,
} from './ui/today';
import { OPEN_TASK_FILE_COMMAND, openTaskFile, TASKS_REFRESH_COMMAND, TasksView } from './ui/tasks';
import { DECISIONS_REFRESH_COMMAND, DecisionsView, OPEN_DECISIONS_COMMAND, openDecisions } from './ui/decisions';
import { DRIFT_REFRESH_COMMAND, DriftView } from './ui/drift';
import {
  DONE_WINDOW_COMMAND, START_WINDOW_COMMAND, taskWindow, TOKENS_REFRESH_COMMAND, TokensView, type Confirm, USE_FOLDER_COMMAND,
  useFolder,
} from './ui/tokens';
import {
  APPROVAL_DETAILS_COMMAND, APPROVALS_REFRESH_COMMAND, ApprovalsView, PayloadDocuments, SIGN_COMMAND, signCard, VIEW_PAYLOAD_COMMAND, viewPayload,
  type SigningHooks, type SigningOutcome,
} from './ui/approvals';
import {
  MARK_ALL_READ_COMMAND, MARK_READ_COMMAND, MARK_UNREAD_COMMAND, NotificationDetailsView, NotificationsBell,
  NotificationsReadStore, OPEN_BELL_COMMAND, OPEN_NOTIFICATION_DETAILS_COMMAND,
} from './ui/notifications';
import { DimmedDecorationProvider } from './ui/tree';
import {
  runPostUpgradeContractCheck, UPGRADE_CLI_COMMAND, upgradeCli, type UpgradeHooks, type UpgradeOutcome,
} from './ui/upgrade';
import type { RunResult } from './cli/runner';
import { PANELS, Refreshes, type RefreshRecord } from './ui/refresh';
import { orderProjects } from './model/today';
import { DetailsView } from './ui/preview';
import { exchangeReadKey, RowActions } from './ui/rowActions';
import { COMMANDS, OPEN_ROW_COMMAND } from './ui/tree';
import type { Notice } from './model/sprint';
import type { ContractCheckResult } from './model/upgrade';
import type { ProjectNotification } from './model/notifications';

export const OUTPUT_CHANNEL_NAME = 'Bio-STEWARD';
export const SELECT_PROJECT_COMMAND = 'bioSteward.selectProject';

// Returned from activate() only when VS Code runs the extension's own tests (ExtensionMode.Test).
export interface TestApi {
  // The active project (the one the views and the status bar show).
  readonly project: Project;
  readonly projects: readonly Project[];
  readonly selection: ActiveProject<Project>;
  readonly overview: OverviewView;
  readonly results: ResultsView;
  readonly statusBar: VerdictStatusBar;
  readonly countdown: CountdownStatusBar;
  readonly explain: ExplainView;
  readonly resume: ResumeView;
  readonly init: InitView;
  readonly skills: SkillsView;
  readonly skillsInstall: SkillsInstall;
  // 0.2.0 P1, P2: Today, the "Where am I?" page, and the reopening check.
  readonly today: TodayView;
  readonly whereAmI: WhereAmIView;
  readonly reopen: {
    readonly lastSeen: LastSeen;
    // Run the start-up check again (as on reopening): the project whose page it showed, if any.
    check(now?: Date): Promise<Project | undefined>;
  };
  // 0.2.0 P3 and P4: the Tasks and Tokens panels, and the task-window action with a test confirmation.
  readonly tasks: TasksView;
  readonly tokens: {
    readonly view: TokensView;
    window(action: 'start' | 'done', root: string, id: string, confirm: Confirm): Promise<RunResult | undefined>;
  };
  // 0.2.0 P5 (design v0.8): the Approvals cards, View exactly what you are approving, and ✍ Sign with
  // test hooks (the modal's answer, the typed name, the terminal). A link's arguments: full nonce, project index,
  // page generation (U09).
  readonly approvals: {
    readonly view: ApprovalsView;
    viewPayload(nonce: unknown, index: unknown, generation: unknown): Promise<{ uri: vscode.Uri; text: string } | undefined>;
    sign(nonce: unknown, index: unknown, generation: unknown, hooks: SigningHooks): Promise<SigningOutcome | undefined>;
  };
  // 0.2.0 P6, P7: the Decisions panel and Open DECISIONS.md, and the Drift panel (timeline states only).
  readonly decisions: {
    readonly view: DecisionsView;
    open(root?: string): Promise<vscode.Uri | undefined>;
  };
  readonly drift: DriftView;
  // S9 (T13): the live sprint view of the active project, its status bar item and the notifications shown.
  readonly sprint: {
    readonly view: SprintView;
    readonly statusBar: SprintStatusBar;
    readonly live: LiveSprint | undefined;
    readonly notices: readonly Notice[];
  };
  // E01: every panel refresh that ran (panel, start, end), newest last.
  readonly refreshes: readonly RefreshRecord[];
  // E03: the notifications bell, local per-machine read state, details page, and Upgrade CLI with test hooks.
  readonly notifications: {
    readonly readStore: NotificationsReadStore;
    readonly bell: NotificationsBell;
    readonly details: NotificationDetailsView;
    openBell(): Promise<readonly ProjectNotification[]>;
    closeBell(): void;
    openDetails(target: unknown): Promise<vscode.TextDocument | undefined>;
    markRead(target: unknown): Promise<boolean>;
    markUnread(target: unknown): Promise<boolean>;
    markAllRead(target?: unknown): Promise<boolean>;
  };
  readonly upgrade: {
    run(root?: string, hooks?: UpgradeHooks): Promise<UpgradeOutcome | undefined>;
    contractCheck(project?: Project, beforeVersion?: string): Promise<ContractCheckResult>;
    readonly lastContractCheck: ContractCheckResult | undefined;
  };
  // The last text this extension copied (src/ui/clipboard.ts), so tests never read the shared system clipboard.
  readonly clipboard: typeof lastCopy;
  // bioSteward.check.onSave (D3): every save the extension saw, and whether it asked for a check.
  readonly saves: readonly { readonly path: string; readonly triggered: boolean }[];
  readonly onSave: SaveTrigger<Project>;
}

interface Session extends vscode.Disposable {
  readonly projects: readonly Project[];
  readonly selection: ActiveProject<Project>;
  readonly sprints: ReadonlyMap<Project, LiveSprint>;
  add(folder: Folder): Project;
}

export async function activate(context: vscode.ExtensionContext): Promise<TestApi | undefined> {
  const log = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME, { log: true });
  const lifetime = new AbortController();
  context.subscriptions.push(log, { dispose: () => lifetime.abort() });

  const manifest = context.extension.packageJSON as {
    version: string;
    bioSteward: { minimumCli: string; testedWithCli: string };
  };
  const detector = new FeatureDetector(manifest.bioSteward);
  const isTrusted = () => vscode.workspace.isTrusted && !lifetime.signal.aborted;

  log.info(`Bio-STEWARD extension ${manifest.version} activated`);
  log.info(`Workspace trusted: ${vscode.workspace.isTrusted}`);

  const overview = new OverviewView();
  const results = new ResultsView(context.workspaceState);
  const statusBar = new VerdictStatusBar();
  const countdown = new CountdownStatusBar();
  const explain = new ExplainView(() => session?.selection.active);
  const resume = new ResumeView();
  const dimmedDecorations = new DimmedDecorationProvider();
  const notificationsReadStore = new NotificationsReadStore(context.globalState);
  const notificationDetails = new NotificationDetailsView();
  const today = new TodayView(notificationsReadStore,
    (root, id) => context.workspaceState.get(exchangeReadKey(root, id), false));
  const details = new DetailsView();
  const notificationsBell = new NotificationsBell(notificationsReadStore, notificationDetails, async () => {
    await Promise.all((session?.projects ?? []).map((project) => project.refreshNotifications()));
    notificationsBell.update(session?.projects ?? [], isTrusted());
    await today.update(session?.projects ?? [], isTrusted());
  });
  const tasks = new TasksView();
  const approvals = new ApprovalsView();
  const payloadDocuments = new PayloadDocuments();
  const decisions = new DecisionsView();
  const drift = new DriftView();
  const tokens = new TokensView(() => session?.projects ?? [], isTrusted);
  const lastSeen = new LastSeen(context.globalState, () => (session?.projects ?? []).map((project) => project.root));
  const whereAmI = new WhereAmIView({
    gate: (project) => vscode.workspace.getConfiguration('bioSteward', vscode.Uri.file(project.root)).get('gate', 'default'),
    lastSeen: (project) => lastSeen.before(project.root),
  });
  const init = new InitView(async (root) => {
    const folder = vscode.workspace.workspaceFolders?.find(({ uri }) => uri.fsPath === root);
    if (!folder) return;
    const current = session;
    let project = current?.projects.find((candidate) => candidate.root === root);
    if (project) {
      uninitialized.delete(root);
    } else if (current && !uninitialized.size) {
      project = current.add(folder);
    } else {
      project = await build(root);
    }
    if (!project) return;
    session?.selection.select(project);
    if (project.state.cli.kind !== 'ready') await project.detect();
    await project.runCheck(undefined, true);
    void vscode.commands.executeCommand('setContext', 'bioSteward.initCompleted', true);
    await vscode.commands.executeCommand(`${OVERVIEW_VIEW}.focus`);
  });
  const skills = new SkillsView();
  const skillsInstall = new SkillsInstall(async (project, stdout) => {
    log.info(`[${project.name}] Agent Skills installed`);
    const table = printedSkillsTable(stdout);
    if (table) {
      void vscode.window.showInformationMessage(
        'Bio-STEWARD: Skills installed. steward.toml is never edited: add the [skills] table the CLI printed, so R-60 can check drift.',
        'Copy Table').then(async (action) => {
        if (action) await copyText(`${table}\n`);
      });
    }
    await project.runScopedCheck({ areas: ['skills'] });
    if (project === session?.selection.active) await skills.update(project, (session?.projects.length ?? 0) > 1 ? project.name : undefined);
  });
  const sprintView = new SprintView();
  const sprintStatusBar = new SprintStatusBar();
  const shownNotices: Notice[] = [];
  const refreshes = new Refreshes();
  const saves: { path: string; triggered: boolean }[] = [];
  // D3: a full check after a save, debounced 2 s, one at a time per project, trusted workspaces only.
  const onSave = new SaveTrigger<Project>(async (project) => {
    if (!isTrusted() || !session?.projects.includes(project)) return;
    log.info(`[${project.name}] steward check after a save (bioSteward.check.onSave)`);
    await project.runCheck();
  });
  context.subscriptions.push(overview, results, statusBar, countdown, explain, resume, init, skills, skillsInstall,
    sprintView, sprintStatusBar, onSave, today, whereAmI, lastSeen, tasks, tokens, approvals,
    payloadDocuments, decisions, drift, dimmedDecorations, notificationsReadStore, notificationDetails, notificationsBell, details);

  let session: Session | undefined;
  let initProject: Project | undefined;
  let pickingInit = false;
  let uninitialized = new Set<string>();
  const workspaceRoots = () => (vscode.workspace.workspaceFolders ?? []).map(({ uri }) => uri.fsPath);
  const storageBase = (context.storageUri ?? context.globalStorageUri).fsPath;
  const createProject = (root: string, watch = true) => new Project({
    root, storage: storageFor(storageBase, root), detector, minimumCli: manifest.bioSteward.minimumCli,
    log, isTrusted: () => isTrusted() && workspaceRoots().includes(root), workspaceRoots, watch,
  });

  const renderSprint = () => {
    const project = session?.selection.active;
    const live = project && session?.sprints.get(project);
    const several = (session?.projects.length ?? 0) > 1 ? project?.name : undefined;
    sprintView.update(live, isTrusted(), several);
    sprintStatusBar.update(live && isTrusted() ? live.snapshots : []);
  };

  // Today shows every project, so any project's change redraws it (debounced: a check changes the state often).
  let todayTimer: ReturnType<typeof setTimeout> | undefined;
  const renderToday = () => {
    clearTimeout(todayTimer);
    todayTimer = setTimeout(() => {
      notificationsBell.update(session?.projects ?? [], isTrusted());
      void today.update(session?.projects ?? [], isTrusted());
      // P3 and P4 show every project too.
      tasks.update(session?.projects ?? [], isTrusted());
      tokens.update();
      void approvals.update(session?.projects ?? [], isTrusted());
      // P6 and P7 show every project too.
      decisions.update(session?.projects ?? [], isTrusted());
      drift.update(session?.projects ?? [], isTrusted());
    }, 100);
  };
  context.subscriptions.push({ dispose: () => clearTimeout(todayTimer) }, notificationsReadStore.onDidChange(() => {
    notificationsBell.update(session?.projects ?? [], isTrusted());
    void today.update(session?.projects ?? [], isTrusted());
  }));
  // P5: the terminals ✍ Sign opened, and the project each belongs to.
  const signingTerminals = new Map<vscode.Terminal, Project>();
  // E03: the terminals Upgrade CLI opened, and the last post-upgrade contract check result.
  const upgradeTerminals = new Map<vscode.Terminal, { readonly project: Project; readonly beforeVersion: string }>();
  let lastContractCheck: ContractCheckResult | undefined;
  const logInfo = (text: string) => log.info(text);
  const runUpgrade = async (root?: unknown, hooks?: UpgradeHooks): Promise<UpgradeOutcome | undefined> => {
    if (!isTrusted() || !session) return undefined;
    const outcome = await upgradeCli(session.projects, session.selection.active, root, hooks, logInfo);
    if (outcome) {
      upgradeTerminals.set(outcome.terminal, { project: outcome.project, beforeVersion: outcome.beforeVersion });
    }
    return outcome;
  };
  const sign = async (nonce: unknown, index: unknown, generation: unknown, hooks?: SigningHooks): Promise<SigningOutcome | undefined> => {
    if (!isTrusted() || !session) return undefined;
    const outcome = await signCard(session.projects, approvals, nonce, index, generation, hooks, logInfo);
    if (outcome) {
      signingTerminals.set(outcome.terminal, outcome.project);
      log.info(`[${outcome.project.name}] Sign: confirmed in the modal; running in a terminal: ${outcome.line}`);
    }
    return outcome;
  };
  const showPayload = (nonce: unknown, index: unknown, generation: unknown) => isTrusted() && session
    ? viewPayload(session.projects, approvals, payloadDocuments, nonce, index, generation, logInfo) : Promise.resolve(undefined);
  const projectAt = (root: unknown) => session?.projects.find((project) => project.root === root);

  const rows = new RowActions({
    overview: overview.tree, results: results.tree, today: today.tree, tasks: tasks.tree, tokens: tokens.tree,
    decisions: decisions.tree, drift: drift.tree, skills: skills.tree, sprint: sprintView.tree,
  }, () => session?.projects ?? [], (project) => session?.sprints.get(project), (project) => session?.selection.select(project),
  details, resume, context.workspaceState, () => today.update(session?.projects ?? [], isTrusted()), isTrusted);
  const rowCommands: Record<string, (row: NonNullable<ReturnType<RowActions['resolve']>>) => unknown> = {
    [OPEN_ROW_COMMAND]: (row) => rows.open(row),
    'bioSteward.row.resume': (row) => rows.open(row),
    'bioSteward.row.openText': (row) => rows.open(row, true),
    'bioSteward.row.copyPath': (row) => rows.useFile(row, 'copy'),
    'bioSteward.row.reveal': (row) => rows.useFile(row, 'reveal'),
    'bioSteward.row.openFinding': (row) => rows.openFinding(row),
    'bioSteward.row.handToAgent': (row) => rows.handToAgent(row),
    'bioSteward.row.dispatch': (row) => rows.dispatch(row),
    'bioSteward.row.tokenTask': (row) => rows.openTokenTask(row),
    'bioSteward.row.models': (row) => rows.showModels(row),
    'bioSteward.row.milestone': (row) => rows.openMilestone(row),
    'bioSteward.row.blockers': (row) => rows.showBlockers(row),
    'bioSteward.row.openDecision': (row) => openDecisions(session?.projects ?? [], row.node),
    'bioSteward.row.recordDecision': (row) => openDecisions(session?.projects ?? [], row.node, true, true),
    'bioSteward.row.todayApproval': (row) => rows.todayNext(row),
    'bioSteward.row.todaySprint': (row) => rows.todayNext(row),
    'bioSteward.row.milestoneBrief': (row) => rows.handToAgent(row),
    'bioSteward.row.exchangeOpen': (row) => rows.exchange(row, 'open'),
    'bioSteward.row.exchangePull': (row) => rows.exchange(row, 'pull'),
    'bioSteward.row.exchangeRead': (row) => rows.exchange(row, 'read'),
    'bioSteward.row.exchangeRespond': (row) => rows.exchange(row, 'respond'),
    'bioSteward.row.sprintLog': (row) => rows.sprint(row, 'log'),
    'bioSteward.row.sprintHold': (row) => rows.sprint(row, 'hold'),
    'bioSteward.row.sprintDiff': (row) => rows.sprint(row, 'diff'),
    'bioSteward.row.next': ({ node }) => {
      const command = node.command;
      if (command && ['showLog', 'runCheck', 'checkSkills', 'installSkills', 'openTokenSettings'].includes(command)) {
        return vscode.commands.executeCommand(COMMANDS[command].command, ...COMMANDS[command].arguments ?? []);
      }
      return undefined;
    },
  };

  const render = () => {
    renderSprint();
    renderToday();
    const project = session?.selection.active;
    if (!project) {
      overview.tree.set([]);
      void skills.update(undefined);
      void vscode.commands.executeCommand('setContext', 'bioSteward.empty', 'no-folder');
      void vscode.commands.executeCommand('setContext', 'bioSteward.upgradeAvailable', false);
      return;
    }
    const { state } = project;
    const settings = vscode.workspace.getConfiguration('bioSteward', vscode.Uri.file(project.root));
    const several = (session?.projects.length ?? 0) > 1 ? project.name : undefined;
    overview.update(state, several, project.root);
    void results.update(state, project.root, several);
    statusBar.update(state, settings.get('gate', 'default'), several);
    countdown.update(state.trusted ? state.timeline : undefined);
    void skills.update(project, several);
    const upgradeAvailable = Boolean(state.trusted && state.cli.kind === 'ready'
      && state.upgrade?.kind === 'ready' && state.upgrade.check.upgrade_available && state.upgrade.check.latest_version);
    void vscode.commands.executeCommand('setContext', 'bioSteward.upgradeAvailable', upgradeAvailable);
    const empty = emptyState(state);
    void vscode.commands.executeCommand('setContext', 'bioSteward.empty',
      empty === 'no-report' && uninitialized.has(project.root) ? 'uninitialized' : empty ?? '');
  };

  const build = async (initializedRoot?: string): Promise<Project | undefined> => {
    const folders = await projectFolders(vscode.workspace.workspaceFolders ?? []);
    const unconfigured = await Promise.all(folders.map(async ({ uri }) => await canInitialize(uri.fsPath) ? uri.fsPath : undefined));
    if (lifetime.signal.aborted) return;
    uninitialized = new Set(unconfigured.filter((root) => root !== undefined));
    // The setup guide (walkthrough) is for folders that are not Bio-STEWARD projects yet (pilot finding, 0.0.3).
    void vscode.commands.executeCommand('setContext', 'bioSteward.hasProject', folders.length > uninitialized.size);
    session?.dispose();
    session = undefined;
    if (!folders.length) {
      render();
      return;
    }
    const disposables: vscode.Disposable[] = [];
    const sprints = new Map<Project, LiveSprint>();
    const attach = (folder: Folder) => {
      const project = createProject(folder.uri.fsPath);
      const live = new LiveSprint({
        root: folder.uri.fsPath, log,
        // E04: the full form, when the project's CLI offers `sprint status --format json`.
        status: (id) => project.sprintStatus(id),
        isTrusted: () => isTrusted() && workspaceRoots().includes(folder.uri.fsPath),
        notify: (notice) => {
          shownNotices.push(notice);
          log.info(`[${project.name}] ${notice.message}`);
          showNotice(notice);
        },
      });
      sprints.set(project, live);
      disposables.push(live, live.onDidChange(() => {
        if (project === session?.selection.active) renderSprint();
      }));
      void live.refresh();
      const problems = new ProblemsView(folder.uri);
      const updateProblems = () => {
        const settings = vscode.workspace.getConfiguration('bioSteward', folder.uri);
        const unknown = settings.get<string>('diagnostics.unknownSeverity') === 'warning' ? 'warning' : 'information';
        void problems.update(project.state.trusted ? project.state.full : undefined, unknown);
      };
      disposables.push(project, problems, project.onDidChange(() => {
        updateProblems();
        renderToday();
        if (project === session?.selection.active) render();
      }), vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('bioSteward.diagnostics.unknownSeverity', folder.uri)) updateProblems();
      }));
      return project;
    };
    const projects = folders.map(attach);
    log.info(`Projects: ${projects.map((p) => `${p.name} (${p.root})`).join(' · ')}`);
    const selection = new ActiveProject(projects);
    selection.follow(vscode.window.activeTextEditor?.document.uri);
    const initialized = projects.find((project) => project.root === initializedRoot);
    if (initialized) selection.select(initialized);
    disposables.push(selection, selection.onDidChange(render));
    session = {
      projects, selection, sprints,
      add(folder) {
        const project = attach(folder);
        projects.push(project);
        void vscode.commands.executeCommand('setContext', 'bioSteward.multiProject', true);
        return project;
      },
      dispose: () => {
        projects.forEach((project) => onSave.forget(project));
        disposables.forEach((d) => d.dispose());
      },
    };
    void vscode.commands.executeCommand('setContext', 'bioSteward.multiProject', projects.length > 1);
    render();
    // Detection runs in the background; activation does not wait for the CLI.
    void Promise.all(projects.filter((project) => project !== initialized).map((project) => project.detect()));
    await initialized?.detect();
    return initialized;
  };

  context.subscriptions.push(
    { dispose: () => { session?.dispose(); initProject?.dispose(); } },
    ...Object.entries(rowCommands).map(([id, action]) => vscode.commands.registerCommand(id, (input: unknown) => {
      const row = rows.resolve(input);
      return row && action(row);
    })),
    vscode.commands.registerCommand('bioSteward.showLog', () => log.show(true)),
    vscode.commands.registerCommand('bioSteward.runCheck', () => {
      const project = session?.selection.active;
      if (!isTrusted() || !project) return undefined;
      return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Bio-STEWARD: steward check · ${project.name}`, cancellable: true },
        async (_progress, token) => {
          const cancel = new AbortController();
          const subscription = token.onCancellationRequested(() => cancel.abort());
          try {
            await project.runCheck(cancel.signal);
          } finally {
            subscription.dispose();
          }
        });
    }),
    ...(['overview', 'results', 'skills', 'sprint', 'today', 'whereAmI', 'tasks', 'tokens', 'approvals', 'decisions',
      'drift'] as const).map((panel) =>
      vscode.commands.registerCommand(`bioSteward.help.${panel}`, () => showPanelHelp(context, panel))),
    vscode.commands.registerCommand('bioSteward.redetect', () =>
      Promise.all((session?.projects ?? []).map((project) => project.detect()))),
    vscode.commands.registerCommand('bioSteward.showOverview', () =>
      vscode.commands.executeCommand(`${OVERVIEW_VIEW}.focus`)),
    vscode.commands.registerCommand(INIT_WALKTHROUGH_COMMAND, () =>
      isTrusted() ? vscode.commands.executeCommand('workbench.action.openWalkthrough', `${context.extension.id}#guidedInit`) : undefined),
    vscode.commands.registerCommand(INIT_COMMAND, async () => {
      if (!isTrusted() || pickingInit || init.applying) return;
      pickingInit = true;
      try {
        const folders = localFolders(vscode.workspace.workspaceFolders ?? []);
        const candidates = (await Promise.all(folders.map(async (folder) =>
          await canInitialize(folder.uri.fsPath) ? folder : undefined))).filter((folder) => folder !== undefined);
        if (!candidates.length) {
          // Pilot finding (0.0.3): in an existing project, say so and offer the next step.
          const choice = await vscode.window.showInformationMessage(
            'Bio-STEWARD: This folder is already a Bio-STEWARD project (it has a steward.toml). Run a check instead?',
            'Run Check', 'Show Overview');
          if (choice === 'Run Check') await vscode.commands.executeCommand('bioSteward.runCheck');
          else if (choice === 'Show Overview') await vscode.commands.executeCommand('bioSteward.showOverview');
          return;
        }
        const picked = candidates.length === 1 ? candidates[0] : (await vscode.window.showQuickPick(
          candidates.map((folder) => ({ label: folder.name, description: folder.uri.fsPath, folder })),
          { title: 'Bio-STEWARD: Choose a folder to initialize' }))?.folder;
        if (!picked) return;
        const root = picked.uri.fsPath;
        const options = await pickInitOptions(root);
        if (!options || !isTrusted() || init.applying || !workspaceRoots().includes(root)) return;
        const project = createProject(root, false);
        init.dispose();
        initProject?.dispose();
        initProject = project;
        await project.detect();
        if (project.state.cli.kind !== 'ready') {
          void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required to initialize a project. See the Bio-STEWARD log.');
          return;
        }
        await init.preview(project, options);
      } catch (error) {
        log.warn(`Guided init: ${String(error)}`);
        void vscode.window.showWarningMessage('Bio-STEWARD: Could not prepare initialization. See the Bio-STEWARD log.');
      } finally {
        pickingInit = false;
      }
    }),
    vscode.commands.registerCommand(APPLY_INIT_COMMAND, () => init.apply()),
    vscode.commands.registerCommand('bioSteward.results.groupBy', (choice?: unknown) => results.chooseGroup(choice)),
    vscode.commands.registerCommand(EXPLAIN_COMMAND, (rule?: unknown, code?: unknown) => {
      if (!session?.selection.active) {
        return vscode.window.showInformationMessage('Bio-STEWARD: Open a project folder to explain a rule.');
      }
      return explain.show(rule, code);
    }),
    vscode.commands.registerCommand(COPY_EXPLAIN_COMMAND, async (rule?: unknown) => {
      if (isTrusted() && isRuleId(rule)) await copyText(`steward explain ${rule}`);
    }),
    vscode.commands.registerCommand(RESUME_COMMAND, (root?: unknown) => resume.show(projectAt(root) ?? session?.selection.active)),
    // E01: each panel's refresh button runs that panel's commands now, with the panel's progress bar.
    vscode.commands.registerCommand(TODAY_REFRESH_COMMAND, () => refreshes.run('today', isTrusted(), async () => {
      await Promise.all((session?.projects ?? []).flatMap((project) => [
        project.refreshNotifications(), project.refreshAudit(), project.refreshTimeline(), project.refreshNext(),
      ]));
      notificationsBell.update(session?.projects ?? [], isTrusted());
      await today.update(session?.projects ?? [], isTrusted());
    })),
    vscode.commands.registerCommand(PANELS.overview.refresh, () => refreshes.run('overview', isTrusted(), async () => {
      const project = session?.selection.active;
      await Promise.all([project?.runCheck(), project?.refreshTimeline(), project?.refreshUpgrade()]);
    })),
    vscode.commands.registerCommand(PANELS.results.refresh, () => refreshes.run('results', isTrusted(), async () => {
      await session?.selection.active?.runCheck();
    })),
    // E03: notifications bell, read/unread actions, details page, and Upgrade CLI.
    vscode.commands.registerCommand(OPEN_BELL_COMMAND, () =>
      notificationsBell.openBell(session?.projects ?? [], isTrusted())),
    vscode.commands.registerCommand(OPEN_NOTIFICATION_DETAILS_COMMAND, (target?: unknown) =>
      notificationsBell.openDetails(session?.projects ?? [], isTrusted(), target)),
    vscode.commands.registerCommand(MARK_READ_COMMAND, (target?: unknown) =>
      notificationsBell.markRead(session?.projects ?? [], isTrusted(), target)),
    vscode.commands.registerCommand(MARK_UNREAD_COMMAND, (target?: unknown) =>
      notificationsBell.markUnread(session?.projects ?? [], isTrusted(), target)),
    vscode.commands.registerCommand(MARK_ALL_READ_COMMAND, (target?: unknown) =>
      notificationsBell.markAllRead(session?.projects ?? [], isTrusted(), target)),
    vscode.commands.registerCommand(UPGRADE_CLI_COMMAND, async (root?: unknown) => {
      await runUpgrade(root);
    }),
    vscode.commands.registerCommand(WHERE_AM_I_COMMAND, async (input?: unknown) => {
      if (!isTrusted() || !session) return undefined;
      const project = rows.resolve(input)?.project
        ?? await chooseProject(session.projects, input, whereAmI, 'Bio-STEWARD: Where am I? (most pending first)');
      return project && whereAmI.show(project);
    }),
    vscode.commands.registerCommand(COPY_BRIEF_COMMAND, async (input?: unknown) => {
      if (!isTrusted() || !session) return undefined;
      const project = await chooseProject(session.projects, input, whereAmI, 'Bio-STEWARD: Copy as Agent Brief');
      return copyBrief(project, whereAmI);
    }),
    vscode.commands.registerCommand(TASKS_REFRESH_COMMAND, () => refreshes.run('tasks', isTrusted(), async () => {
      await Promise.all((session?.projects ?? []).map((project) => project.refreshTasks()));
      tasks.update(session?.projects ?? [], isTrusted());
    })),
    // A Tasks row's file, checked again when it is clicked (U09).
    vscode.commands.registerCommand(OPEN_TASK_FILE_COMMAND, (input?: unknown) =>
      isTrusted() && session ? openTaskFile(session.projects, input) : undefined),
    // E04: Use this folder writes one agent's log setting (machine scope), then reads the report.
    vscode.commands.registerCommand(USE_FOLDER_COMMAND, (input?: unknown) =>
      isTrusted() && session ? useFolder(session.projects, tokens, input) : false),
    vscode.commands.registerCommand(TOKENS_REFRESH_COMMAND, () => refreshes.run('tokens', isTrusted(), () => tokens.refresh())),
    vscode.commands.registerCommand(START_WINDOW_COMMAND, (first?: unknown, second?: unknown) =>
      isTrusted() && session ? taskWindow('start', session.projects, tokens, first, second) : undefined),
    vscode.commands.registerCommand(DONE_WINDOW_COMMAND, (first?: unknown, second?: unknown) =>
      isTrusted() && session ? taskWindow('done', session.projects, tokens, first, second) : undefined),
    vscode.commands.registerCommand(APPROVALS_REFRESH_COMMAND, () => refreshes.run('approvals', isTrusted(), async () => {
      await Promise.all((session?.projects ?? []).map((project) => project.refreshApprovals()));
      await approvals.update(session?.projects ?? [], isTrusted());
    })),
    vscode.commands.registerCommand(APPROVAL_DETAILS_COMMAND, (position: unknown, index: unknown, generation: unknown) =>
      isTrusted() && session ? approvals.showDetails(session.projects, details, position, index, generation) : undefined),
    // The signing and payload links. An agent's executeCommand reaches the same modal; no test hook is reachable here.
    vscode.commands.registerCommand(VIEW_PAYLOAD_COMMAND, (nonce?: unknown, index?: unknown, generation?: unknown) =>
      showPayload(nonce, index, generation)),
    vscode.commands.registerCommand(SIGN_COMMAND, async (nonce?: unknown, index?: unknown, generation?: unknown) => {
      await sign(nonce, index, generation);
    }),
    vscode.commands.registerCommand(DECISIONS_REFRESH_COMMAND, () => refreshes.run('decisions', isTrusted(), async () => {
      await Promise.all((session?.projects ?? []).map((project) => project.refreshDecisions()));
      decisions.update(session?.projects ?? [], isTrusted());
    })),
    vscode.commands.registerCommand(OPEN_DECISIONS_COMMAND, (input?: unknown) =>
      isTrusted() && session ? openDecisions(session.projects, input) : undefined),
    vscode.commands.registerCommand(DRIFT_REFRESH_COMMAND, () => refreshes.run('drift', isTrusted(), async () => {
      await Promise.all((session?.projects ?? []).map((project) => project.refreshTimeline()));
      drift.update(session?.projects ?? [], isTrusted());
    })),
    // A signing or upgrade terminal that closes: refresh approvals/notifications, or detect the new CLI & run contract check.
    vscode.window.onDidCloseTerminal((terminal) => {
      const signing = signingTerminals.get(terminal);
      if (signing) {
        signingTerminals.delete(terminal);
        if (isTrusted() && session?.projects.includes(signing)) {
          void signing.refreshApprovals();
          void signing.refreshNotifications();
        }
        return;
      }
      const upgrade = upgradeTerminals.get(terminal);
      if (upgrade) {
        upgradeTerminals.delete(terminal);
        if (isTrusted() && session?.projects.includes(upgrade.project)) {
          void runPostUpgradeContractCheck({
            projects: session.projects,
            upgradedProject: upgrade.project,
            beforeVersion: upgrade.beforeVersion,
            detector,
            log: logInfo,
          }).then((result) => {
            lastContractCheck = result;
            notificationsBell.update(session?.projects ?? [], isTrusted());
            render();
          });
        }
      }
    }),
    vscode.commands.registerCommand(COPY_FOR_AGENT_COMMAND, (input?: unknown) => copyForAgent(session?.selection.active, input)),
    vscode.commands.registerCommand(CHECK_AREA_COMMAND, (input?: unknown) => checkArea(session?.selection.active, input)),
    vscode.commands.registerCommand(CHECK_RULE_COMMAND, (input?: unknown) => checkRule(session?.selection.active, input)),
    vscode.commands.registerCommand(CHECK_SKILLS_COMMAND, () => checkArea(session?.selection.active, 'skills')),
    vscode.commands.registerCommand(REFRESH_SKILLS_COMMAND, () => refreshes.run('skills', isTrusted(), () => skills.refresh())),
    vscode.commands.registerCommand(INSTALL_SKILLS_COMMAND, async () => {
      const project = session?.selection.active;
      if (!isTrusted() || !project || skillsInstall.applying) return false;
      if (project.state.cli.kind !== 'ready') {
        void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required to install Agent Skills.');
        return false;
      }
      const options = await pickSkillsInstall(project);
      if (!options || !isTrusted()) return false;
      return skillsInstall.preview(project, options);
    }),
    vscode.commands.registerCommand(APPLY_SKILLS_COMMAND, () => skillsInstall.apply()),
    vscode.commands.registerCommand(TIMELINE_COMMAND, async (root?: unknown) => {
      const project = projectAt(root) ?? session?.selection.active;
      if (!isTrusted() || !project) return;
      const timeline = await project.refreshTimeline();
      await pickMilestone(timeline, vscode.Uri.joinPath(vscode.Uri.file(project.root), 'development', 'milestones.toml'));
    }),
    // With an argument (a project root, for tests and keybindings), or from a quick pick.
    vscode.commands.registerCommand(SELECT_PROJECT_COMMAND, async (root?: unknown) => {
      if (!session) return;
      const { projects, selection } = session;
      let chosen = projects.find((project) => project.root === root);
      if (!chosen) {
        const picked = await vscode.window.showQuickPick(projects.map((project) => ({
          label: project.name, description: project.root, picked: project === selection.active, project,
        })), { title: 'Bio-STEWARD: Select Project' });
        chosen = picked?.project;
      }
      selection.select(chosen);
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => session?.selection.follow(editor?.document.uri)),
    vscode.workspace.onDidSaveTextDocument((document) => {
      if (!isTrusted() || document.uri.scheme !== 'file' || !session) return;
      const file = document.uri.fsPath;
      // The innermost project that holds the file.
      const project = session.projects.filter((p) => isWithin(p.root, file))
        .sort((a, b) => b.root.length - a.root.length)[0];
      const enabled = vscode.workspace.getConfiguration('bioSteward', document.uri).get<boolean>('check.onSave', false);
      const triggered = Boolean(project && enabled && project.state.cli.kind === 'ready' && triggersCheck(project.root, file));
      saves.push({ path: file, triggered });
      if (saves.length > 100) saves.splice(0, saves.length - 100);
      if (triggered) onSave.saved(project);
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      log.info('Workspace folders changed');
      init.dispose();
      initProject?.dispose();
      initProject = undefined;
      void build();
    }),
    vscode.commands.registerCommand(SPRINT_REFRESH_COMMAND, () => refreshes.run('sprint', isTrusted(), async () => {
      const project = session?.selection.active;
      await (project && session?.sprints.get(project))?.refreshNow();
    })),
    vscode.commands.registerCommand(SPRINT_COPY_ORDER_COMMAND, (node?: unknown) => {
      const project = session?.selection.active;
      return copyOrderCommand(project && session?.sprints.get(project), node);
    }),
    vscode.commands.registerCommand(SPRINT_SHOW_COMMAND, () => vscode.commands.executeCommand(`${SPRINT_VIEW}.focus`)),
    vscode.workspace.onDidGrantWorkspaceTrust(() => {
      log.info('Workspace trust granted');
      for (const live of session?.sprints.values() ?? []) live.schedule();
      void Promise.all((session?.projects ?? []).map((project) => project.detect()));
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (['bioSteward.cliPath', 'bioSteward.timeoutSeconds', 'bioSteward.registry'].some((key) => event.affectsConfiguration(key))) {
        init.dispose();
        initProject?.dispose();
        initProject = undefined;
        void Promise.all((session?.projects ?? []).map((project) => project.detect()));
      } else if (event.affectsConfiguration('bioSteward.gate')) {
        render();
      }
      if (event.affectsConfiguration('bioSteward.tokens') && isTrusted()) void tokens.refresh();
      if (event.affectsConfiguration('bioSteward.notifications.toasts')) {
        notificationsBell.update(session?.projects ?? [], isTrusted());
      }
    }),
  );

  // P2: "Where am I?" once, when a project is opened again after more than N days (bioSteward.whereAmI.*).
  // With several such projects, the page of the first in the Today order. Trusted workspaces only.
  const reopen = async (now = new Date()): Promise<Project | undefined> => {
    if (!isTrusted() || !session) return undefined;
    const due = reopenedProjects(session.projects, lastSeen, now);
    if (!due.length) return undefined;
    await Promise.all(due.map((project) => detected(project)));
    if (!isTrusted()) return undefined;
    await Promise.all(due.map((project) => project.refreshAudit()));
    const [first] = orderProjects(due, (project) => project.state.audit);
    log.info(`[${first.name}] reopened after more than ${vscode.workspace.getConfiguration('bioSteward.whereAmI').get('reopenAfterDays', 3)} days: showing Where am I?`);
    await whereAmI.show(first);
    return first;
  };

  await build();
  if (isTrusted()) {
    await lastSeen.touch();
    void reopen();
  }
  if (context.extensionMode !== vscode.ExtensionMode.Test || !session) return undefined;
  const current = () => session as Session;
  return {
    get project() {
      const active = current().selection.active;
      if (!active) throw new Error('no project');
      return active;
    },
    get projects() {
      return current().projects;
    },
    get selection() {
      return current().selection;
    },
    overview, results, statusBar, countdown, explain, resume, init, skills, skillsInstall, today, whereAmI,
    reopen: { lastSeen, check: reopen },
    tasks,
    approvals: { view: approvals, viewPayload: showPayload, sign: (nonce, index, generation, hooks) => sign(nonce, index, generation, hooks) },
    decisions: { view: decisions, open: async (root) => isTrusted() ? openDecisions(current().projects, root) : undefined },
    drift,
    tokens: {
      view: tokens,
      window: (action, root, id, confirm) => taskWindow(action, current().projects, tokens, root, id, confirm),
    },
    sprint: {
      view: sprintView,
      statusBar: sprintStatusBar,
      get live() {
        const active = current().selection.active;
        return active && current().sprints.get(active);
      },
      notices: shownNotices,
    },
    refreshes: refreshes.records,
    notifications: {
      readStore: notificationsReadStore,
      bell: notificationsBell,
      details: notificationDetails,
      openBell: () => notificationsBell.openBell(current().projects, isTrusted()),
      closeBell: () => notificationsBell.closeBell(),
      openDetails: (target) => notificationsBell.openDetails(current().projects, isTrusted(), target),
      markRead: (target) => notificationsBell.markRead(current().projects, isTrusted(), target),
      markUnread: (target) => notificationsBell.markUnread(current().projects, isTrusted(), target),
      markAllRead: (target) => notificationsBell.markAllRead(current().projects, isTrusted(), target),
    },
    upgrade: {
      run: (root, hooks) => runUpgrade(root, hooks),
      contractCheck: async (project, beforeVersion) => {
        const target = project ?? current().selection.active;
        if (!target) throw new Error('no project');
        const before = beforeVersion ?? (target.state.cli.kind === 'ready' ? target.state.cli.version : 'unknown');
        const result = await runPostUpgradeContractCheck({
          projects: current().projects,
          upgradedProject: target,
          beforeVersion: before,
          detector,
          log: logInfo,
          notify: false,
        });
        lastContractCheck = result;
        notificationsBell.update(current().projects, isTrusted());
        render();
        return result;
      },
      get lastContractCheck() {
        return lastContractCheck;
      },
    },
    clipboard: lastCopy,
    saves,
    onSave,
  };
}

export function deactivate(): void {
  // VS Code disposes context.subscriptions.
}

// The plain-language help for each panel, bundled with the extension (media/help/panels.md), opened in VS Code's
// Markdown preview at the panel's section. It works offline and before the guide is published.
const HELP_SECTIONS = {
  overview: 'overview', results: 'results', skills: 'agent-skills', sprint: 'sprint', today: 'today', whereAmI: 'where-am-i',
  tasks: 'tasks', tokens: 'tokens', approvals: 'approvals', decisions: 'decisions', drift: 'milestones-and-drift',
} as const;

export function panelHelpUri(extensionUri: vscode.Uri, panel: keyof typeof HELP_SECTIONS): vscode.Uri {
  return vscode.Uri.joinPath(extensionUri, 'media', 'help', 'panels.md').with({ fragment: HELP_SECTIONS[panel] });
}

async function showPanelHelp(context: vscode.ExtensionContext, panel: keyof typeof HELP_SECTIONS): Promise<void> {
  await vscode.commands.executeCommand('markdown.showPreview', panelHelpUri(context.extensionUri, panel));
}
