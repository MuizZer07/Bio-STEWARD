// Copy for agent (S5; TOK-2) and the scoped re-checks (S8).
//
// Copy for agent puts the CLI's own bounded `steward check [--rule R-xx] --summary` text on the clipboard,
// unchanged, followed by the command that re-checks it and the text's size in bytes. No new format, no model
// call, nothing written. The text goes to the clipboard only, never into a terminal (T7).
//
// A scoped re-check (`check AREA …`, `check --rule R-xx`) shows its report as a partial run: its gates read
// NOT EVALUATED BY THIS RUN and the status bar keeps the last full verdict, marked stale (design v0.1 §5.3).
import * as vscode from 'vscode';
import { copyBriefText } from './rowBrief';
import { CHECK_AREAS, isArea, isRuleId, type Area, type Rule } from '../cli/commands';
import { agentText, recheckCommand } from '../model/agent';
import type { ViewNode } from '../model/views';
import { scopeLabel, type CheckOutcome, type CheckScope, type Project } from '../project';

export const COPY_FOR_AGENT_COMMAND = 'bioSteward.copyForAgent';
export const CHECK_AREA_COMMAND = 'bioSteward.runCheckForArea';
export const CHECK_RULE_COMMAND = 'bioSteward.runCheckForRule';

// A rule from a command argument: a tree node with a result reference, or a rule ID.
export function ruleArgument(input: unknown): Rule | undefined {
  const value = typeof input === 'object' && input !== null ? (input as Partial<ViewNode>).ref?.rule : input;
  return isRuleId(value) ? value : undefined;
}

export async function copyForAgent(project: Project | undefined, input?: unknown): Promise<string | undefined> {
  if (!project?.state.trusted) return undefined;
  if (project.state.cli.kind !== 'ready') {
    void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required to copy the summary.');
    return undefined;
  }
  const rule = ruleArgument(input);
  if (input !== undefined && typeof input !== 'object' && rule === undefined) {
    void vscode.window.showWarningMessage('Bio-STEWARD: Enter a rule ID such as R-01.');
    return undefined;
  }
  const result = await vscode.window.withProgress({
    location: vscode.ProgressLocation.Notification, cancellable: true,
    title: `Bio-STEWARD: ${recheckCommand(rule)} · ${project.name}`,
  }, async (_progress, token) => {
    const cancel = new AbortController();
    const subscription = token.onCancellationRequested(() => cancel.abort());
    try {
      return await project.summary(rule, cancel.signal);
    } finally {
      subscription.dispose();
    }
  });
  if (!result || result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return undefined;
  // `check` exits 0 – 3 with a verdict (PASS, FAIL, INCOMPLETE, UNKNOWN); anything else is not a summary.
  if (result.kind !== 'completed' || result.exitCode < 0 || result.exitCode > 3 || !result.stdout.trim()) {
    const reason = result.kind === 'completed' ? result.stderr.trim().split('\n')[0] : '';
    warnWithLog(`Bio-STEWARD: Could not get the summary${reason ? `: ${reason}` : ''}.`);
    return undefined;
  }
  const text = agentText(result.stdout, rule, project.cliVersion ?? 'unknown');
  return copyBriefText(recheckCommand(rule), text);
}

// The command returns at once; the message offers the log.
function warnWithLog(message: string): void {
  void vscode.window.showWarningMessage(message, 'Show Log').then(async (action) => {
    if (action) await vscode.commands.executeCommand('bioSteward.showLog');
  });
}

async function runScoped(project: Project, scope: CheckScope): Promise<CheckOutcome> {
  const outcome = await vscode.window.withProgress({
    location: vscode.ProgressLocation.Notification, cancellable: true,
    title: `Bio-STEWARD: steward ${scopeLabel(scope)} · ${project.name} (partial run)`,
  }, async (_progress, token) => {
    const cancel = new AbortController();
    const subscription = token.onCancellationRequested(() => cancel.abort());
    try {
      return await project.runScopedCheck(scope, cancel.signal);
    } finally {
      subscription.dispose();
    }
  });
  if (outcome === 'rejected') warnWithLog(`Bio-STEWARD: steward ${scopeLabel(scope)} was not accepted by the CLI.`);
  return outcome;
}

function ready(project: Project | undefined): project is Project {
  if (!project?.state.trusted) return false;
  if (project.state.cli.kind !== 'ready') {
    void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required to run a check.');
    return false;
  }
  return true;
}

// `bioSteward.runCheckForArea`: an area (or a list of areas) as the argument, or chosen from a quick pick.
export async function checkArea(project: Project | undefined, input?: unknown): Promise<CheckOutcome> {
  if (!ready(project)) return 'not-run';
  let areas: Area[] | undefined;
  if (input !== undefined) {
    const values = Array.isArray(input) ? input : [input];
    if (!values.length || !values.every(isArea)) {
      void vscode.window.showWarningMessage('Bio-STEWARD: Not a check area.');
      return 'not-run';
    }
    areas = values;
  } else {
    const picked = await vscode.window.showQuickPick(CHECK_AREAS.map((label) => ({ label })), {
      title: 'Bio-STEWARD: Run Check for Area (a partial run)', canPickMany: true,
      placeHolder: 'Select one or more areas',
    });
    areas = picked?.map(({ label }) => label);
  }
  if (!areas?.length) return 'not-run';
  return runScoped(project, { areas });
}

// `bioSteward.runCheckForRule`: a result node or a rule ID as the argument, or typed in.
export async function checkRule(project: Project | undefined, input?: unknown): Promise<CheckOutcome> {
  if (!ready(project)) return 'not-run';
  let rule = ruleArgument(input);
  if (input === undefined) {
    const typed = await vscode.window.showInputBox({
      title: 'Bio-STEWARD: Run Check for Rule (a partial run)', prompt: 'Enter a rule ID, such as R-60',
      validateInput: (value) => isRuleId(value.trim()) ? undefined : 'Enter a rule ID such as R-01.',
    });
    if (typed === undefined) return 'not-run';
    rule = ruleArgument(typed.trim());
  }
  if (!rule) {
    void vscode.window.showWarningMessage('Bio-STEWARD: Enter a rule ID such as R-01.');
    return 'not-run';
  }
  return runScoped(project, { rule });
}
