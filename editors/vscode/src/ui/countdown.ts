// The countdown in the status bar (S3; design v0.3 §4.3), next to the verdict: `$(watch) preprint · 12.3 days
// left · AT RISK`, the nearest milestone without an outcome. Clicking lists every milestone of the active project, in
// the CLI's words, the latest due first (E01).
import * as vscode from 'vscode';
import { milestonesLatestFirst } from '../model/drift';
import { countdownView, daysText, type CountdownView, type TimelineState } from '../model/timeline';

export const TIMELINE_COMMAND = 'bioSteward.showTimeline';

export class CountdownStatusBar implements vscode.Disposable {
  readonly #item = vscode.window.createStatusBarItem('bioSteward.countdown', vscode.StatusBarAlignment.Left, 49);
  #view: CountdownView = countdownView(undefined);

  constructor() {
    this.#item.name = 'Bio-STEWARD countdown';
    this.#item.command = { command: TIMELINE_COMMAND, title: 'Show milestones' };
  }

  get view(): CountdownView {
    return this.#view;
  }

  get text(): string | undefined {
    return this.#view.visible ? this.#item.text : undefined;
  }

  update(timeline: TimelineState | undefined): void {
    const view = countdownView(timeline);
    this.#view = view;
    if (!view.visible) {
      this.#item.hide();
      return;
    }
    this.#item.text = view.text;
    const tooltip = new vscode.MarkdownString(undefined, false);
    tooltip.isTrusted = false;
    tooltip.supportHtml = false;
    view.tooltip.forEach((line, i) => {
      if (i) tooltip.appendMarkdown('\n\n');
      tooltip.appendText(line);
    });
    this.#item.tooltip = tooltip;
    this.#item.accessibilityInformation = { label: view.accessibility };
    this.#item.backgroundColor = view.tone === 'error'
      ? new vscode.ThemeColor('statusBarItem.errorBackground')
      : view.tone === 'warning' ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    this.#item.show();
  }

  dispose(): void {
    this.#item.dispose();
  }
}

// Every milestone, the latest due first (the status bar still names the nearest); choosing one opens the file.
export async function pickMilestone(timeline: TimelineState | undefined, milestonesFile: vscode.Uri): Promise<void> {
  if (!timeline || timeline.kind !== 'ready') {
    const why = !timeline || timeline.kind === 'none' || timeline.kind === 'loading'
      ? 'This project has no milestones (development/milestones.toml).'
      : timeline.kind === 'not-configured' ? 'This project is not set up.' : 'steward timeline gave no readable answer; see the log.';
    void vscode.window.showInformationMessage(`Bio-STEWARD: ${why}`);
    return;
  }
  const picked = await vscode.window.showQuickPick(milestonesLatestFirst(timeline.rows).map((row) => ({
    label: `${row.state.toUpperCase()} · ${row.id}`,
    description: `${row.title} (${row.kind})`,
    detail: `due ${row.due} · ${daysText(row.days_left)} · open work ${row.open_work}`,
  })), { title: 'Bio-STEWARD: Milestones (steward timeline)', matchOnDescription: true });
  if (picked) await vscode.window.showTextDocument(milestonesFile, { preview: true });
}
