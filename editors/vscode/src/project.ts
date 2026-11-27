// One project (a folder with steward.toml): finds the CLI, runs `steward check`, holds the state the views show.
// Several projects in one window (S2) are several of these, each with its own runner, report, watcher and
// timeline (src/projects.ts).
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { homedir } from 'node:os';
import { lstat, mkdir, open, realpath } from 'node:fs/promises';
import { basename, join, relative } from 'node:path';
import * as vscode from 'vscode';
import { commands, isRuleId, type Area, type Invocation, type Rule } from './cli/commands';
import { FeatureDetector } from './cli/features';
import { reportIgnored } from './cli/git';
import { locateCli } from './cli/locator';
import { readJson } from './cli/output';
import { confinedPath } from './cli/paths';
import { CliRunner, type RunResult } from './cli/runner';
import { downgrade, freshnessOfRun, isWatchedInput, withInputChanged } from './model/freshness';
import { handoffSetting } from './model/handoff';
import { reportValidator, type Report } from './model/report';
import { parseTimeline, type TimelineState } from './model/timeline';
import { parseAuditProgress, type AuditState } from './model/today';
import { NO_LOGS, parseTokensReport, type LogSelection, type TokensState } from './model/tokens';
import { parsePendingText, type ApprovalsState } from './model/approvals';
import { listTaskFiles } from './taskFiles';
import { findDecisionLogs } from './decisionsFiles';
import type { DecisionsState } from './model/decisions';
import { PublishOrder, runReportRequest } from './reportRun';
import {
  initialState, withReport, withRunFailure, withRunning, type ProjectState,
} from './model/views';

interface Options {
  root: string;
  storage: string;
  detector: FeatureDetector;
  minimumCli: string;
  log: vscode.LogOutputChannel;
  isTrusted: () => boolean;
  // Every workspace folder: neither the CLI nor git is ever run from inside one (T2).
  workspaceRoots?: () => readonly string[];
  // Watch the project's files for freshness (S1). Off only in unit-style use without a VS Code watcher.
  watch?: boolean;
}

export const HANDOFF_LIMIT_BYTES = 1024 * 1024;

export type Handoff =
  | { readonly kind: 'found'; readonly path: string; readonly text: string }
  | { readonly kind: 'missing'; readonly path: string }
  | { readonly kind: 'unreadable'; readonly reason: string };

export type ReportLocation = { readonly path: string; readonly where: 'repository' | 'extension'; readonly why: string };

// S8: a scoped re-check, by area or by rule. Its report is marked partial and never shown as a gate verdict.
export type CheckScope = { readonly areas: readonly Area[]; readonly rule?: undefined } | { readonly rule: Rule; readonly areas?: undefined };

export function scopeLabel(scope: CheckScope): string {
  return scope.rule !== undefined ? `check --rule ${scope.rule}` : `check ${scope.areas.join(' ')}`;
}

// How a check run ended, for the commands that start one (the views read the state).
export type CheckOutcome = 'completed' | 'rejected' | 'failed' | 'cancelled' | 'not-run';

export class Project implements vscode.Disposable {
  #state: ProjectState;
  #runner: CliRunner | undefined;
  #timelineRunner: CliRunner | undefined;
  #summaryRunner: CliRunner | undefined;
  #auditRunner: CliRunner | undefined;
  #auditGeneration = 0;
  #tokensRunner: CliRunner | undefined;
  #tokensGeneration = 0;
  #approvalsRunner: CliRunner | undefined;
  #approvalsGeneration = 0;
  #tasksGeneration = 0;
  #tasksTimer: ReturnType<typeof setTimeout> | undefined;
  #decisionsGeneration = 0;
  #decisionsTimer: ReturnType<typeof setTimeout> | undefined;
  // Canonical folders (the runner confines paths to canonical folders; /tmp is a link on macOS, for example).
  #paths: { root: string; storage: string } | undefined;
  #generation = 0;
  #timelineGeneration = 0;
  #cliVersion: string | undefined;
  readonly #watcher: vscode.FileSystemWatcher | undefined;
  #canonicalRoot: string | undefined;
  #running = 0;
  #changedDuringRun = false;
  // The last input paths that downgraded freshness (bounded). Read by the host tests, which share a workspace with
  // other tests' late file events; a candidate for a "stale because … changed" tooltip.
  readonly #inputChanges: string[] = [];
  // Every watcher event (bounded) and whether it was a project input: the tests await the event of a file they
  // wrote instead of sleeping (T11-07).
  readonly #watchEvents: { path: string; input: boolean }[] = [];
  #lastLocation: ReportLocation | undefined;
  readonly #fullOrder = new PublishOrder();
  readonly #scopedOrder = new PublishOrder();
  readonly #lifetime = new AbortController();
  readonly #changed = new vscode.EventEmitter<ProjectState>();
  readonly onDidChange = this.#changed.event;

  constructor(private readonly options: Options) {
    this.#state = { ...initialState(options.isTrusted()), name: basename(options.root) };
    realpath(options.root).then((path) => {
      this.#canonicalRoot = path;
    }, () => undefined);
    if (options.watch !== false) {
      try {
        const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(vscode.Uri.file(options.root), '**'));
        const changed = (uri: vscode.Uri) => this.#fileChanged(uri);
        watcher.onDidCreate(changed);
        watcher.onDidChange(changed);
        watcher.onDidDelete(changed);
        this.#watcher = watcher;
      } catch (error) {
        options.log.warn(`No file watcher for ${options.root}; freshness is unknown · ${String(error)}`);
      }
    }
  }

  get root(): string {
    return this.options.root;
  }

  get name(): string {
    return this.#state.name ?? basename(this.root);
  }

  get recentInputChanges(): readonly string[] {
    return this.#inputChanges;
  }

  get recentWatchEvents(): readonly { readonly path: string; readonly input: boolean }[] {
    return this.#watchEvents;
  }

  get state(): ProjectState {
    return this.#state;
  }

  // Where the last check wrote its report, and why (for the log and the tests).
  get lastReportLocation(): ReportLocation | undefined {
    return this.#lastLocation;
  }

  #set(state: ProjectState): void {
    if (state === this.#state || this.#lifetime.signal.aborted) return;
    this.#state = state;
    this.#changed.fire(state);
  }

  dispose(): void {
    clearTimeout(this.#timelineTimer);
    clearTimeout(this.#tasksTimer);
    clearTimeout(this.#decisionsTimer);
    this.#lifetime.abort();
    this.#watcher?.dispose();
    this.#changed.dispose();
  }

  #trusted(): boolean {
    return this.options.isTrusted() && !this.#lifetime.signal.aborted;
  }

  // S1: a watched input changed. Downgrade only; a running check's report will be "unknown".
  #fileChanged(uri: vscode.Uri): void {
    let path = relative(this.root, uri.fsPath);
    // Events can name the canonical path (macOS: /tmp is /private/tmp).
    if (this.#canonicalRoot && (path === '..' || path.startsWith('..'))) path = relative(this.#canonicalRoot, uri.fsPath);
    this.#watchEvents.push({ path: path.replaceAll('\\', '/'), input: isWatchedInput(path) });
    if (this.#watchEvents.length > 200) this.#watchEvents.splice(0, this.#watchEvents.length - 200);
    // P3: a Markdown file or steward.toml changed: list the task files again (debounced; no CLI call).
    if (/\.md$/i.test(path) || path === 'steward.toml') this.#scheduleTasks();
    // P6: steward.toml or a decisions log may have changed: find the logs again (debounced; no CLI call).
    if (/\.md$/i.test(path) || path === 'steward.toml' || this.#isDecisionLog(path)) this.#scheduleDecisions();
    if (!isWatchedInput(path)) return;
    this.#inputChanges.push(path.replaceAll('\\', '/'));
    if (this.#inputChanges.length > 200) this.#inputChanges.splice(0, this.#inputChanges.length - 200);
    if (this.#running) this.#changedDuringRun = true;
    this.#set(withInputChanged(this.#state));
    if (path.replaceAll('\\', '/') === 'development/milestones.toml') this.#scheduleTimeline();
  }

  #timelineTimer: ReturnType<typeof setTimeout> | undefined;

  #scheduleTasks(): void {
    if (this.#state.tasks === undefined) return;
    clearTimeout(this.#tasksTimer);
    this.#tasksTimer = setTimeout(() => void this.refreshTasks(), 500);
  }

  #isDecisionLog(path: string): boolean {
    const state = this.#state.decisions;
    return state?.kind === 'ready' && state.logs.some((log) => log.path === path.replaceAll('\\', '/'));
  }

  #scheduleDecisions(): void {
    if (this.#state.decisions === undefined) return;
    clearTimeout(this.#decisionsTimer);
    this.#decisionsTimer = setTimeout(() => void this.refreshDecisions(), 500);
  }

  #scheduleTimeline(): void {
    clearTimeout(this.#timelineTimer);
    this.#timelineTimer = setTimeout(() => {
      void this.refreshTimeline();
      void this.refreshAudit();
    }, 1000);
  }

  #runnerFor(cli: string, flight?: string): CliRunner {
    const config = vscode.workspace.getConfiguration('bioSteward', vscode.Uri.file(this.root));
    return new CliRunner({
      cli,
      root: this.root,
      storageRoot: this.options.storage,
      flight,
      isTrusted: () => this.#trusted(),
      timeoutMs: config.get('timeoutSeconds', 120) * 1000,
      // VX8: respect the CLI's project registry unless the user opts out (a machine-scoped setting).
      registry: config.get<'respect' | 'disable'>('registry', 'respect') === 'disable' ? 'disable' : 'respect',
      logStderr: (stderr) => {
        if (!this.#lifetime.signal.aborted) this.options.log.warn(stderr);
      },
    });
  }

  // Locate the CLI and detect its features (M1). Runs nothing in an untrusted workspace.
  async detect(): Promise<void> {
    const generation = ++this.#generation;
    const current = () => generation === this.#generation && this.#trusted();
    this.#runner = undefined;
    this.#timelineRunner = undefined;
    this.#summaryRunner = undefined;
    this.#auditRunner = undefined;
    this.#tokensRunner = undefined;
    this.#approvalsRunner = undefined;
    this.#paths = undefined;
    if (!this.#trusted()) {
      this.#set({ ...this.#state, trusted: false });
      return;
    }
    this.#set({ ...this.#state, trusted: true, cli: { kind: 'detecting' } });
    const { log } = this.options;
    const config = vscode.workspace.getConfiguration('bioSteward', vscode.Uri.file(this.root));
    try {
      const location = await locateCli({
        setting: config.inspect<string>('cliPath'),
        workspaceRoots: this.#workspaceRoots(),
        env: process.env,
        home: homedir(),
      });
      if (!current()) return;
      if (location.kind !== 'found') {
        log.info(location.kind === 'missing' ? 'CLI not found' : 'The configured CLI path is invalid');
        this.#set({ ...this.#state, cli: { kind: location.kind === 'missing' ? 'missing' : 'invalid-setting' } });
        return;
      }
      await mkdir(this.options.storage, { recursive: true });
      const paths = { root: await realpath(this.root), storage: await realpath(this.options.storage) };
      const runner = this.#runnerFor(location.path);
      const detected = await this.options.detector.detect(runner, this.#lifetime.signal);
      if (!current()) return;
      if (!('version' in detected)) {
        log.warn(`CLI detection failed · ${detected.path}`);
        this.#set({ ...this.#state, cli: { kind: 'failed' } });
        return;
      }
      if (detected.mode === 'too-old') {
        log.warn(`steward ${detected.version} is older than ${this.options.minimumCli} · ${detected.path}`);
        this.#set({ ...this.#state, cli: { kind: 'too-old', version: detected.version, minimum: this.options.minimumCli } });
        return;
      }
      if (detected.mode === 'unreadable') {
        log.warn(`CLI interface output unreadable · ${detected.path}`);
        this.#set({ ...this.#state, cli: { kind: 'failed' } });
        return;
      }
      const newer = detected.newerThanTested ? ' · CLI newer than tested' : '';
      log.info(`[${this.name}] steward ${detected.version} · ${detected.mode}${newer} · ${detected.path}`);
      this.#runner = runner;
      this.#timelineRunner = this.#runnerFor(location.path, 'timeline');
      this.#summaryRunner = this.#runnerFor(location.path, 'summary');
      this.#auditRunner = this.#runnerFor(location.path, 'audit');
      this.#tokensRunner = this.#runnerFor(location.path, 'tokens');
      this.#approvalsRunner = this.#runnerFor(location.path, 'approvals');
      this.#paths = paths;
      // A report made by another CLI version is stale (design v0.1 §5.3: a tool-version change).
      const changedCli = this.#cliVersion !== undefined && this.#cliVersion !== detected.version;
      this.#cliVersion = detected.version;
      const state = changedCli ? downgrade(this.#state, 'stale') : this.#state;
      this.#set({
        ...state,
        cli: { kind: 'ready', version: detected.version, mode: detected.mode, newerThanTested: detected.newerThanTested },
      });
      if (!this.#state.full && !this.#state.partial && this.#state.run === 'none') await this.#loadSavedReport(generation);
      void this.refreshTimeline();
      void this.refreshAudit();
      void this.refreshTasks();
      void this.refreshApprovals();
      void this.refreshDecisions();
    } catch (error) {
      if (!current()) return;
      log.warn(`CLI detection failed · ${String(error)}`);
      this.#set({ ...this.#state, cli: { kind: 'failed' } });
    }
  }

  #workspaceRoots(): readonly string[] {
    return this.options.workspaceRoots?.() ?? [this.root];
  }

  async runInit(invocation: Invocation, options: {
    confirm?: (cli: string, args: readonly string[]) => Promise<boolean>;
    recheck?: boolean;
  } = {}): Promise<RunResult> {
    const runner = this.#runner;
    if (!runner || !this.#trusted()) return { kind: 'cancelled' };
    const { confirm, recheck } = options;
    // During confirmation the write holds the main flight, so only its recheck uses a separate queue.
    const result = await (recheck ? this.#runnerFor(runner.cliPath, 'init-recheck') : runner)
      .run(invocation, {
        signal: this.#lifetime.signal,
        confirm: confirm && (async (cli, args) => await confirm(cli, args) && runner === this.#runner),
      });
    if (result.kind !== 'unconfirmed') {
      const outcome = result.kind === 'completed' ? `exit ${result.exitCode}` : result.kind;
      this.options.log.info(`[${this.name}] steward init${invocation.confirmation ? '' : ' --dry-run'} · ${outcome}`);
    }
    return result;
  }

  // Where `check --output` writes (bioSteward.report.location, VX5; S10). `auto`: `.steward/report.json` when git
  // says it is ignored, otherwise the extension's storage (Muiz, 2026-11-26, option (a)).
  async #reportLocation(paths: { root: string; storage: string }, signal?: AbortSignal): Promise<ReportLocation> {
    const setting = vscode.workspace.getConfiguration('bioSteward', vscode.Uri.file(this.root)).get<string>('report.location', 'auto');
    const repository = join(paths.root, '.steward', 'report.json');
    const extension = join(paths.storage, 'report.json');
    if (setting === 'repository') return { path: repository, where: 'repository', why: 'setting: repository' };
    if (setting === 'extension') return { path: extension, where: 'extension', why: 'setting: extension' };
    const answer = await reportIgnored({
      root: paths.root,
      workspaceRoots: this.#workspaceRoots(),
      env: process.env,
      isTrusted: () => this.#trusted(),
      signal: signal ? AbortSignal.any([signal, this.#lifetime.signal]) : this.#lifetime.signal,
    });
    return answer.ignored
      ? { path: repository, where: 'repository', why: `auto · ${answer.why}` }
      : { path: extension, where: 'extension', why: `auto · ${answer.why}` };
  }

  // At start-up, the last report at the report location is shown, marked "unknown": the extension cannot tell
  // what changed since it was written (an agent may share it, VX5). Nothing is run for it.
  async #loadSavedReport(generation: number): Promise<void> {
    const paths = this.#paths;
    if (!paths) return;
    const location = await this.#reportLocation(paths);
    if (generation !== this.#generation || this.#state.full || this.#state.partial || this.#state.run !== 'none') return;
    const boundary = location.where === 'repository' ? paths.root : paths.storage;
    const output = await confinedPath(boundary, location.path);
    if (!output) return;
    const read = await readJson<Report>(location.path, reportValidator());
    if (read.kind !== 'valid' || generation !== this.#generation || this.#state.full || this.#state.partial ||
        this.#state.run !== 'none') return;
    this.options.log.info(`[${this.name}] showing the saved report ${location.path} (freshness unknown)`);
    this.#set(withReport(this.#state, read.value, { freshness: 'unknown' }));
  }

  // Run `steward check --format json --output FILE` (M2) and show its report. Returns when the run has ended.
  runCheck(signal?: AbortSignal, preserveExistingReport = false): Promise<CheckOutcome> {
    return this.#check(undefined, signal, preserveExistingReport);
  }

  // S8: `steward check AREA … --format json --output FILE` or `check --rule R-xx …`. The report goes to the
  // extension's storage, never to the shared `.steward/report.json`, so whoever reads that file (an agent, VX5)
  // never takes a partial run for the verdict. The view marks it partial; the full verdict is kept, marked stale.
  runScopedCheck(scope: CheckScope, signal?: AbortSignal): Promise<CheckOutcome> {
    if (scope.rule !== undefined ? !isRuleId(scope.rule) : !scope.areas.length) return Promise.resolve('not-run');
    return this.#check(scope, signal, false);
  }

  async #check(scope: CheckScope | undefined, signal: AbortSignal | undefined, preserveExistingReport: boolean): Promise<CheckOutcome> {
    const runner = this.#runner;
    const paths = this.#paths;
    if (!runner || !paths || this.#state.cli.kind !== 'ready' || !this.#trusted()) return 'not-run';
    const { log } = this.options;
    const before = this.#state.run;
    this.#set(withRunning(this.#state));
    this.#running++;
    if (this.#running === 1) this.#changedDuringRun = false;
    try {
      let location: ReportLocation = scope
        ? { path: paths.storage, where: 'extension', why: `${scopeLabel(scope)} · scoped runs stay out of the repository` }
        : await this.#reportLocation(paths, signal);
      if (preserveExistingReport && location.where === 'repository') {
        const missing = await lstat(location.path).then(() => false,
          (error: NodeJS.ErrnoException) => error.code === 'ENOENT');
        if (!missing || !await confinedPath(paths.root, location.path, true)) {
          location = { path: join(paths.storage, 'report.json'), where: 'extension', why: 'guided init · preserve repository files' };
        }
      }
      if (!scope) this.#lastLocation = location;
      const boundary = location.where === 'repository' ? paths.root : paths.storage;
      log.info(`[${this.name}] report location: ${location.where} (${location.why})`);
      // T11-05: a private output per request; the saved report is replaced only by a check that succeeded.
      const run = await runReportRequest<Report>({
        boundary,
        destination: scope ? { folder: paths.storage } : { replace: location.path },
        order: scope ? this.#scopedOrder : this.#fullOrder,
        validate: reportValidator(),
        execute: (output) => {
          const invocation = commands.check({ mode: 'report', output, areas: scope?.areas, rule: scope?.rule });
          log.info(`steward ${invocation.args.join(' ')}`);
          return runner.run(invocation, { signal });
        },
        show: (report) => {
          const freshness = freshnessOfRun({ watching: this.#watcher !== undefined, changedDuringRun: this.#changedDuringRun });
          if (freshness !== 'fresh') log.info(`[${this.name}] a project file changed during the run: freshness unknown`);
          this.#set(withReport(this.#state, report, { freshness, scope: scope && scopeLabel(scope) }));
        },
      });
      const keep = () => {
        if (this.#state.run === 'running') this.#set({ ...this.#state, run: before === 'running' ? 'none' : before });
      };
      switch (run.kind) {
        case 'path':
          log.warn(`[${this.name}] report path is outside its allowed directory or inaccessible`);
          this.#set(withRunFailure(this.#state, 'failed'));
          return 'failed';
        case 'run': {
          const { result } = run;
          if (result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') {
            log.info(`steward check ${result.kind}`);
            keep();
            return 'cancelled';
          }
          log.warn(`steward check: ${result.kind === 'process-error' ? result.message : result.kind}`);
          this.#set(withRunFailure(this.#state, result.kind === 'unreadable' ? 'unreadable' : 'failed'));
          return 'failed';
        }
        case 'exit':
          log.info(`steward check exited ${run.exitCode}`);
          if (run.exitCode === 64) {
            // A scoped run's usage error (a rule the CLI does not have, for example) says nothing about the project.
            if (scope) {
              keep();
              return 'rejected';
            }
            this.#set(withRunFailure(this.#state, 'not-configured'));
            return 'failed';
          }
          this.#set(withRunFailure(this.#state, 'failed'));
          return 'failed';
        case 'unreadable':
          log.warn(`steward check exited ${run.exitCode}; its report is unreadable (missing, invalid JSON, too large, or not steward.report/0.1)`);
          this.#set(withRunFailure(this.#state, 'unreadable'));
          return 'failed';
        case 'outdated':
          log.info(`steward check exited; a later ${scope ? 'scoped ' : ''}check was already shown, so this report is not`);
          keep();
          return 'cancelled';
        case 'published':
          log.info(`steward check exited ${run.exitCode}`);
          break;
      }
    } catch (error) {
      log.warn(`steward check failed · ${String(error)}`);
      this.#set(withRunFailure(this.#state, 'failed'));
      return 'failed';
    } finally {
      this.#running--;
    }
    // The countdown reads gates too; it follows a completed full run, never a file change (no background checks).
    if (!scope) {
      void this.refreshTimeline();
      void this.refreshAudit();
    }
    return 'completed';
  }

  // S5: `steward check [--rule R-xx] --summary`, the CLI's bounded text (TOK-2), on its own flight so it never
  // supersedes a queued check. Read-only; nothing is written.
  async summary(rule: Rule | undefined, signal?: AbortSignal): Promise<RunResult | undefined> {
    const runner = this.#summaryRunner;
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return undefined;
    if (rule !== undefined && !isRuleId(rule)) return undefined;
    const invocation = commands.check({ mode: 'summary', rule });
    this.options.log.info(`[${this.name}] steward ${invocation.args.join(' ')}`);
    const result = await runner.run(invocation, {
      signal: signal ? AbortSignal.any([signal, this.#lifetime.signal]) : this.#lifetime.signal,
    });
    return runner === this.#summaryRunner && this.#trusted() ? result : undefined;
  }

  // The CLI version the project's runner uses, when it is ready.
  get cliVersion(): string | undefined {
    return this.#state.cli.kind === 'ready' ? this.#state.cli.version : undefined;
  }

  // Show a report file the extension did not just produce (used by the host tests). Its freshness is unknown.
  async showReportFile(path: string, scope?: string): Promise<boolean> {
    const read = await readJson<Report>(path, reportValidator());
    if (read.kind !== 'valid') {
      this.#set(withRunFailure(this.#state, 'unreadable'));
      return false;
    }
    this.#set(withReport(this.#state, read.value, { scope, freshness: 'unknown' }));
    return true;
  }

  // S3: `steward timeline --json`, on its own flight so it never supersedes a queued check.
  async refreshTimeline(): Promise<TimelineState | undefined> {
    const runner = this.#timelineRunner;
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return this.#state.timeline;
    const generation = ++this.#timelineGeneration;
    if (!this.#state.timeline || this.#state.timeline.kind === 'none') this.#set({ ...this.#state, timeline: { kind: 'loading' } });
    const result = await runner.run(commands.timeline(), { signal: this.#lifetime.signal });
    if (generation !== this.#timelineGeneration || runner !== this.#timelineRunner) return this.#state.timeline;
    let timeline: TimelineState;
    if (result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return this.#state.timeline;
    if (result.kind === 'unreadable') timeline = { kind: 'unreadable' };
    else if (result.kind !== 'completed') timeline = { kind: 'failed' };
    else if (result.exitCode === 64) timeline = { kind: 'not-configured' };
    else if (result.exitCode === 65) timeline = { kind: 'invalid' };
    else if (result.exitCode !== 0) timeline = { kind: 'failed' };
    else {
      const parsed = parseTimeline(result.stdout);
      timeline = !parsed ? { kind: 'unreadable' } : parsed.milestones.length ? { kind: 'ready', rows: parsed.milestones } : { kind: 'none' };
    }
    if (timeline.kind !== 'ready' && timeline.kind !== 'none' && timeline.kind !== 'not-configured') {
      this.options.log.warn(`[${this.name}] steward timeline: ${timeline.kind}${result.kind === 'completed' ? ` (exit ${result.exitCode})` : ''}`);
    }
    this.#set({ ...this.#state, timeline });
    return timeline;
  }

  // P1, P2 (0.2.0, reduced): `steward audit progress --json`, on its own flight so it never supersedes a check or
  // the timeline. Read-only. Run after detection, after a full check, when the milestones file changes, and when
  // Today or "Where am I?" is refreshed; never on other file changes.
  async refreshAudit(): Promise<AuditState | undefined> {
    const runner = this.#auditRunner;
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return this.#state.audit;
    const generation = ++this.#auditGeneration;
    if (!this.#state.audit || this.#state.audit.kind === 'none') this.#set({ ...this.#state, audit: { kind: 'loading' } });
    const result = await runner.run(commands.auditProgress(), { signal: this.#lifetime.signal });
    if (generation !== this.#auditGeneration || runner !== this.#auditRunner) return this.#state.audit;
    if (result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return this.#state.audit;
    let audit: AuditState;
    if (result.kind === 'unreadable') audit = { kind: 'unreadable' };
    else if (result.kind !== 'completed') audit = { kind: 'failed' };
    else if (result.exitCode === 64) audit = { kind: 'not-configured' };
    else if (result.exitCode !== 0) audit = { kind: 'failed' };
    else {
      const parsed = parseAuditProgress(result.stdout);
      audit = parsed ? { kind: 'ready', audit: parsed } : { kind: 'unreadable' };
    }
    if (audit.kind !== 'ready' && audit.kind !== 'not-configured') {
      this.options.log.warn(`[${this.name}] steward audit progress: ${audit.kind}${result.kind === 'completed' ? ` (exit ${result.exitCode})` : ''}`);
    }
    this.#set({ ...this.#state, audit });
    return audit;
  }

  // P3 (reduced): the task files and their Status lines, read from the files. No CLI call; trusted workspaces only.
  async refreshTasks(): Promise<ProjectState['tasks']> {
    if (!this.#trusted()) return this.#state.tasks;
    const generation = ++this.#tasksGeneration;
    if (this.#state.tasks === undefined) this.#set({ ...this.#state, tasks: { kind: 'loading' } });
    let tasks: NonNullable<ProjectState['tasks']>;
    try {
      tasks = await listTaskFiles(this.#canonicalRoot ?? await realpath(this.root));
    } catch (error) {
      tasks = { kind: 'unreadable', reason: error instanceof Error ? error.message : String(error) };
    }
    if (generation !== this.#tasksGeneration || !this.#trusted()) return this.#state.tasks;
    this.#set({ ...this.#state, tasks });
    return tasks;
  }

  // P6 (reduced): the decisions logs steward.toml names, found on disk. No CLI call; the logs are not read.
  async refreshDecisions(): Promise<DecisionsState | undefined> {
    if (!this.#trusted()) return this.#state.decisions;
    const generation = ++this.#decisionsGeneration;
    if (this.#state.decisions === undefined) this.#set({ ...this.#state, decisions: { kind: 'loading' } });
    let decisions: DecisionsState;
    try {
      decisions = await findDecisionLogs(this.#canonicalRoot ?? await realpath(this.root));
    } catch (error) {
      decisions = { kind: 'unreadable', reason: error instanceof Error ? error.message : String(error) };
    }
    if (generation !== this.#decisionsGeneration || !this.#trusted()) return this.#state.decisions;
    this.#set({ ...this.#state, decisions });
    return decisions;
  }

  // P4: `steward tokens report --json` with the agent logs of the settings, on its own flight. Read-only.
  async refreshTokens(logs: LogSelection = NO_LOGS): Promise<TokensState | undefined> {
    const runner = this.#tokensRunner;
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return this.#state.tokens;
    const generation = ++this.#tokensGeneration;
    if (!this.#state.tokens || this.#state.tokens.kind === 'none') this.#set({ ...this.#state, tokens: { kind: 'loading' } });
    const invocation = commands.tokensReport({ ...logs.files, boundaries: logs.boundaries });
    this.options.log.info(`[${this.name}] steward tokens report --json (${invocation.paths.length} agent log${invocation.paths.length === 1 ? '' : 's'})`);
    const result = await runner.run(invocation, { signal: this.#lifetime.signal });
    if (generation !== this.#tokensGeneration || runner !== this.#tokensRunner) return this.#state.tokens;
    if (result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return this.#state.tokens;
    let tokens: TokensState;
    if (result.kind === 'unreadable') tokens = { kind: 'unreadable' };
    else if (result.kind === 'process-error') tokens = { kind: 'refused', message: result.message };
    else if (result.kind !== 'completed') tokens = { kind: 'failed' };
    else if (result.exitCode === 64) tokens = { kind: 'not-configured' };
    else if (result.exitCode !== 0) tokens = { kind: 'failed' };
    else {
      const report = parseTokensReport(result.stdout);
      tokens = report ? { kind: 'ready', report } : { kind: 'unreadable' };
    }
    if (tokens.kind !== 'ready') {
      this.options.log.warn(`[${this.name}] steward tokens report: ${tokens.kind}${result.kind === 'completed' ? ` (exit ${result.exitCode})` : ''}`);
    }
    this.#set({ ...this.#state, tokens });
    return tokens;
  }

  // P5 (reduced): `steward authorize pending --all-projects`, its text kept as printed, on its own flight. Read-only.
  // Run after detection, on Refresh Approvals, and when a signing terminal the extension opened is closed.
  async refreshApprovals(): Promise<ApprovalsState | undefined> {
    return (await this.#readApprovals()).state;
  }

  // The same read, but only its own answer: undefined unless this very call ran the CLI to the end (a superseded,
  // cancelled or untrusted read gives no state, so a card is never bound to an earlier queue; U09).
  async readApprovalsNow(): Promise<ApprovalsState | undefined> {
    const read = await this.#readApprovals();
    return read.fresh ? read.state : undefined;
  }

  async #readApprovals(): Promise<{ state: ApprovalsState | undefined; fresh: boolean }> {
    const runner = this.#approvalsRunner;
    const stale = () => ({ state: this.#state.approvals, fresh: false });
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return stale();
    const generation = ++this.#approvalsGeneration;
    if (!this.#state.approvals || this.#state.approvals.kind === 'none') this.#set({ ...this.#state, approvals: { kind: 'loading' } });
    const result = await runner.run(commands.authorizePending(), { signal: this.#lifetime.signal });
    if (generation !== this.#approvalsGeneration || runner !== this.#approvalsRunner) return stale();
    if (result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return stale();
    let approvals: ApprovalsState;
    if (result.kind === 'unreadable') approvals = { kind: 'unreadable' };
    else if (result.kind !== 'completed') approvals = { kind: 'failed' };
    else if (result.exitCode === 64) approvals = { kind: 'not-configured' };
    else if (result.exitCode !== 0) approvals = { kind: 'failed', message: result.stderr.trim() || undefined };
    else approvals = parsePendingText(result.stdout);
    if (approvals.kind !== 'ready') {
      this.options.log.warn(`[${this.name}] steward authorize pending: ${approvals.kind}${result.kind === 'completed' ? ` (exit ${result.exitCode})` : ''}`);
    }
    this.#set({ ...this.#state, approvals });
    return { state: approvals, fresh: this.#trusted() };
  }

  // The steward program the extension found (an absolute path), once the CLI is ready; for the signing line.
  get cliPath(): string | undefined {
    return this.#state.cli.kind === 'ready' ? this.#runner?.cliPath : undefined;
  }

  // P4: `steward task start ID` / `steward task done ID`, after `confirm` (the exact command line). The CLI writes
  // the window to `.steward/task-tokens.jsonl`; its own message is returned, errors included.
  async taskWindow(action: 'start' | 'done', id: string, confirm: (cli: string, args: readonly string[]) => Promise<boolean>): Promise<RunResult> {
    const runner = this.#runner;
    if (!runner || this.#state.cli.kind !== 'ready' || !this.#trusted()) return { kind: 'cancelled' };
    const invocation = action === 'start' ? commands.taskStart(id) : commands.taskDone(id);
    // Its own flight, so it never supersedes a queued check (and a check never supersedes it).
    const result = await this.#runnerFor(runner.cliPath, 'task-window').run(invocation, {
      signal: this.#lifetime.signal,
      confirm: async (cli, args) => await confirm(cli, args) && runner === this.#runner,
    });
    if (result.kind !== 'unconfirmed') {
      this.options.log.info(`[${this.name}] steward task ${action} ${id} · ${result.kind === 'completed' ? `exit ${result.exitCode}` : result.kind}`);
    }
    return result;
  }

  // S4: the session handoff file's text, unchanged. Read-only; confined to the project; no CLI call.
  async readHandoff(): Promise<Handoff> {
    if (!this.#trusted()) return { kind: 'unreadable', reason: 'the workspace is not trusted' };
    let toml: string;
    try {
      toml = await readText(join(this.root, 'steward.toml'), HANDOFF_LIMIT_BYTES);
    } catch {
      return { kind: 'unreadable', reason: 'steward.toml could not be read' };
    }
    const setting = handoffSetting(toml);
    if (setting.kind === 'unreadable') return { kind: 'unreadable', reason: `steward.toml: ${setting.reason}` };
    const path = await confinedPath(this.root, setting.path);
    if (!path) {
      const outside = await confinedPath(this.root, setting.path, true);
      return outside
        ? { kind: 'missing', path: setting.path }
        : { kind: 'unreadable', reason: `${setting.path} is outside the project` };
    }
    try {
      return { kind: 'found', path: setting.path, text: await readText(path, HANDOFF_LIMIT_BYTES) };
    } catch (error) {
      return { kind: 'unreadable', reason: `${setting.path}: ${error instanceof Error ? error.message : String(error)}` };
    }
  }

  async explain(rule: unknown, signal: AbortSignal): Promise<RunResult | undefined> {
    const runner = this.#runner;
    if (!runner || !this.#trusted() || !isRuleId(rule)) return undefined;
    const result = await runner.run(commands.explain(rule), {
      signal: AbortSignal.any([signal, this.#lifetime.signal]),
    });
    return runner === this.#runner && this.#trusted() ? result : undefined;
  }
}

// A regular file as UTF-8, at most `limit` bytes, not through a final symlink.
async function readText(path: string, limit: number): Promise<string> {
  const file = await open(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  try {
    const status = await file.stat();
    if (!status.isFile()) throw new Error('not a file');
    if (status.size > limit) throw new Error(`larger than ${limit} bytes`);
    const buffer = Buffer.alloc(limit + 1);
    let length = 0;
    for (;;) {
      const { bytesRead } = await file.read(buffer, length, buffer.length - length, length);
      if (!bytesRead) break;
      length += bytesRead;
      if (length > limit) throw new Error(`larger than ${limit} bytes`);
    }
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, length));
  } finally {
    await file.close();
  }
}

// The extension's own folder for one root's files, never shared across roots (design v0.1 §4.1).
export function storageFor(base: string, root: string): string {
  return join(base, 'roots', createHash('sha256').update(root).digest('hex').slice(0, 16));
}
