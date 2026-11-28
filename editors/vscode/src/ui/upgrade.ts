// E03 (design v0.9 §5; RELEASE_vscode_0.3.0_SPEC E03): Upgrade CLI from VS Code.
//
// Shows the exact command (`steward upgrade --repo ROOT --to VERSION`) and the CLI's detected installer command in
// a modal confirmation dialog. On confirmation, runs `steward upgrade --repo ROOT --to VERSION` directly as the
// process of a visible terminal with `strictEnv` (no shell, nothing typed into the terminal, never passes any flag
// that skips confirmation). When the terminal closes, re-detects the CLI with a cleared interface cache and runs
// its contract check.
import * as vscode from 'vscode';
import type { FeatureDetector } from '../cli/features';
import { isUpgradeVersion, upgradeCommand, upgradeEnvironment } from '../cli/upgrade';
import {
  summarizeContractCheck, UPGRADE_BUTTON, upgradeDialog, type ContractCheckItem, type ContractCheckResult,
  type UpgradeDialogDetails,
} from '../model/upgrade';
import type { Project } from '../project';

export const UPGRADE_CLI_COMMAND = 'bioSteward.upgradeCli';

export interface UpgradeHooks {
  confirm?: (details: UpgradeDialogDetails) => Promise<boolean>;
  openTerminal?: (options: vscode.TerminalOptions) => vscode.Terminal;
}

export interface UpgradeOutcome {
  readonly project: Project;
  readonly beforeVersion: string;
  readonly targetVersion: string;
  readonly line: string;
  readonly terminal: vscode.Terminal;
}

export async function confirmUpgrade(details: UpgradeDialogDetails): Promise<boolean> {
  const dialog = upgradeDialog(details);
  const answer = await vscode.window.showWarningMessage(
    dialog.title,
    { modal: true, detail: dialog.detail.join('\n') },
    UPGRADE_BUTTON,
  );
  return answer === UPGRADE_BUTTON;
}

export async function upgradeCli(
  projects: readonly Project[],
  active: Project | undefined,
  rootArg: unknown,
  hooks: UpgradeHooks = {},
  log?: (text: string) => void,
): Promise<UpgradeOutcome | undefined> {
  if (!vscode.workspace.isTrusted) return undefined;
  const project = typeof rootArg === 'string'
    ? projects.find((candidate) => candidate.root === rootArg)
    : active ?? projects[0];
  if (!project || !project.state.trusted) return undefined;
  if (project.state.cli.kind !== 'ready' || !project.cliPath) {
    void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required before upgrading.');
    return undefined;
  }
  const cliPath = project.cliPath;
  const state = await project.refreshUpgrade();
  if (!state || state.kind === 'unsupported') {
    void vscode.window.showInformationMessage(
      'Bio-STEWARD: CLI upgrade checks need steward 0.21.0 or newer. Upgrade bio-steward with your package tool (uv tool, pipx, or pip).');
    return undefined;
  }
  if (state.kind !== 'ready') {
    void vscode.window.showWarningMessage(`Bio-STEWARD: steward upgrade --check did not give a readable answer (${state.kind}). See Show Log.`);
    return undefined;
  }
  const { check } = state;
  if (!check.upgrade_available || !check.latest_version) {
    void vscode.window.showInformationMessage(
      `Bio-STEWARD: steward ${check.installed_version} is up to date with the newest locally known version` +
        `${check.latest_version ? ` (${check.latest_version})` : ''}.`);
    return undefined;
  }
  if (!isUpgradeVersion(check.latest_version)) {
    log?.(`[${project.name}] Upgrade CLI: CLI reported an unsupported target version string; nothing run`);
    void vscode.window.showWarningMessage('Bio-STEWARD: The target version reported by steward upgrade --check is not valid.');
    return undefined;
  }
  if (!check.command || check.command.length === 0) {
    void vscode.window.showWarningMessage(
      `Bio-STEWARD: steward ${check.latest_version} is available (installed ${check.installed_version}), but the CLI ` +
        `could not detect its installer (${check.install_method}). Upgrade it with the tool you used to install bio-steward.`);
    return undefined;
  }
  const command = upgradeCommand(cliPath, project.root, check.latest_version);
  const details: UpgradeDialogDetails = {
    project: project.name,
    installed: check.installed_version,
    target: command.version,
    method: check.install_method,
    source: check.source,
    cliLine: command.line,
    installerCommand: check.command,
  };
  if (!await (hooks.confirm ?? confirmUpgrade)(details)) return undefined;
  // Re-verify trust and CLI path after the modal dialog closes.
  if (!vscode.workspace.isTrusted || !project.state.trusted || project.cliPath !== cliPath) return undefined;
  const open = hooks.openTerminal ?? ((options: vscode.TerminalOptions) => vscode.window.createTerminal(options));
  const terminal = open({
    name: `Bio-STEWARD: upgrade CLI · ${project.name}`,
    cwd: project.root,
    shellPath: command.program,
    shellArgs: [...command.args],
    env: { ...upgradeEnvironment(process.env) },
    strictEnv: true,
    isTransient: true,
  });
  terminal.show(false);
  log?.(`[${project.name}] Upgrade CLI: confirmed in the modal; running in a terminal: ${command.line}`);
  return {
    project,
    beforeVersion: check.installed_version,
    targetVersion: command.version,
    line: command.line,
    terminal,
  };
}

// Re-detect the CLI (with a fresh interface probe) across all open projects and verify the CLI contract on the
// upgraded project: `--version`, `interface`, `notifications`, `upgrade --check`, and `check --format json` report.
export async function runPostUpgradeContractCheck(options: {
  readonly projects: readonly Project[];
  readonly upgradedProject: Project;
  readonly beforeVersion: string;
  readonly detector: FeatureDetector;
  readonly log: (text: string) => void;
  readonly notify?: boolean;
}): Promise<ContractCheckResult> {
  const { projects, upgradedProject, beforeVersion, detector, log } = options;
  detector.clear();
  await Promise.all(projects.map((project) => project.detect()));

  const checks: ContractCheckItem[] = [];
  const { cli } = upgradedProject.state;
  if (cli.kind !== 'ready') {
    checks.push({ name: 'cli-detect', ok: false, detail: `CLI state is ${cli.kind}` });
    const result = summarizeContractCheck({
      beforeVersion, afterVersion: undefined, mode: undefined, newerThanTested: false, checks,
    });
    log(`[${upgradedProject.name}] ${result.summary}`);
    if (options.notify !== false) void vscode.window.showWarningMessage(result.summary);
    return result;
  }

  checks.push({ name: 'cli-detect', ok: true, detail: `steward ${cli.version}` });
  const interfaceOk = cli.mode === 'full' || cli.mode === 'limited';
  checks.push({
    name: 'interface',
    ok: interfaceOk,
    detail: interfaceOk ? `${cli.mode} mode` : `unsupported interface mode (${cli.mode})`,
  });

  if (cli.capabilities?.notifications) {
    const state = await upgradedProject.refreshNotifications();
    const ok = state?.kind === 'ready' || state?.kind === 'not-configured';
    checks.push({ name: 'notifications', ok, detail: state?.kind ?? 'none' });
  }
  if (cli.capabilities?.upgradeCheck) {
    const state = await upgradedProject.refreshUpgrade();
    const ok = state?.kind === 'ready' || state?.kind === 'not-configured';
    checks.push({ name: 'upgrade-check', ok, detail: state?.kind ?? 'none' });
  }

  const checkOutcome = await upgradedProject.runCheck();
  const reportOk = checkOutcome === 'completed';
  checks.push({ name: 'report-schema', ok: reportOk, detail: checkOutcome });

  const result = summarizeContractCheck({
    beforeVersion,
    afterVersion: cli.version,
    mode: cli.mode,
    newerThanTested: cli.newerThanTested,
    checks,
  });
  log(`[${upgradedProject.name}] ${result.summary}`);
  if (options.notify !== false) {
    if (result.ok) void vscode.window.showInformationMessage(result.summary);
    else void vscode.window.showWarningMessage(result.summary);
  }
  return result;
}
