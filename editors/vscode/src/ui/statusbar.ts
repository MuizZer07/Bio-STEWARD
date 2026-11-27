// The status bar (M3): the gate set by bioSteward.gate, ELIGIBLE or not, the blocking count and freshness.
import * as vscode from 'vscode';
import { literal, statusBarView, type ProjectState, type StatusBarView } from '../model/views';

export class VerdictStatusBar implements vscode.Disposable {
  readonly #item = vscode.window.createStatusBarItem('bioSteward.verdict', vscode.StatusBarAlignment.Left, 50);
  #view: StatusBarView | undefined;

  constructor() {
    this.#item.name = 'Bio-STEWARD';
    this.#item.command = { command: 'bioSteward.showOverview', title: 'Open the Overview' };
  }

  get view(): StatusBarView | undefined {
    return this.#view;
  }

  get text(): string {
    return this.#item.text;
  }

  // `project` names the project shown when several are open (S2).
  update(state: ProjectState, gate: string, project?: string): void {
    const single = statusBarView(state, gate);
    const view: StatusBarView = project === undefined ? single : {
      ...single,
      text: single.text.replace(/^(\$\([^)]+\)) /, (icon: string) => `${icon}${literal(project)} · `),
      tooltip: [`Project: ${project} (Bio-STEWARD: Select Project… to change)`, ...single.tooltip],
      accessibility: `${single.accessibility}, project ${project}`,
    };
    this.#view = view;
    this.#item.text = view.text;
    // Untrusted markdown: no HTML and no command links; every line is escaped as plain text.
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
