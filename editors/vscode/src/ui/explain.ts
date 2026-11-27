import * as vscode from 'vscode';
import { isRuleId } from '../cli/commands';
import { resultCode } from '../model/findings';
import type { ViewNode } from '../model/views';
import type { Project } from '../project';

export const EXPLAIN_COMMAND = 'bioSteward.explainRule';
export const COPY_EXPLAIN_COMMAND = 'bioSteward.copyExplainCommand';

export function commandUri(command: typeof EXPLAIN_COMMAND | typeof COPY_EXPLAIN_COMMAND, args: readonly unknown[]): vscode.Uri {
  return vscode.Uri.from({ scheme: 'command', path: command, query: JSON.stringify(args) });
}

export function escapeHtml(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

export function explainHtml(rule: string, stdout: string, code?: string): string {
  // Match a catalogue entry, so a mention of the code in an explanation is left alone.
  const lines = stdout.split('\n');
  const catalogue = lines.indexOf('Result codes:');
  const index = code && catalogue !== -1
    ? lines.findIndex((line, i) => i > catalogue && (line === `  ${code}` || line.startsWith(`  ${code}:`)))
    : -1;
  const content = lines.map((line, i) => i === index && code
    ? `  <mark>${escapeHtml(code)}</mark>${escapeHtml(line.slice(2 + code.length))}`
    : escapeHtml(line)).join('\n');
  const copy = escapeHtml(commandUri(COPY_EXPLAIN_COMMAND, [rule]).toString());
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
<title>Bio-STEWARD Explain ${escapeHtml(rule)}</title>
</head>
<body>
<a href="${copy}">Copy CLI command</a>
<pre><span>${content}</span></pre>
</body>
</html>`;
}

export class ExplainView implements vscode.Disposable {
  #panel: vscode.WebviewPanel | undefined;
  #request: AbortController | undefined;

  // The active project (S2): explanations come from its CLI.
  constructor(private readonly activeProject: () => Project | undefined) {}

  private get project(): Project {
    const project = this.activeProject();
    if (!project) throw new Error('no project');
    return project;
  }

  get html(): string | undefined {
    return this.#panel?.webview.html;
  }

  // The webview's options (D2: exactly one enabled command URI, no scripts, no local resources), for the tests.
  get webviewOptions(): vscode.WebviewOptions | undefined {
    return this.#panel?.webview.options;
  }

  async show(input?: unknown, code?: unknown): Promise<void> {
    if (!this.activeProject()?.state.trusted) return;
    const project = this.project;
    const node = typeof input === 'object' && input !== null ? input as Partial<ViewNode> : undefined;
    const rule = node ? node.ref?.rule : input ?? await vscode.window.showInputBox({
      title: 'Bio-STEWARD: Explain Rule',
      prompt: 'Enter a rule ID, such as R-01',
      validateInput: (value) => isRuleId(value.trim()) ? undefined : 'Enter a rule ID such as R-01.',
    }).then((value) => value?.trim());
    if (rule === undefined) return;
    if (!isRuleId(rule)) {
      void vscode.window.showWarningMessage('Bio-STEWARD: Enter a rule ID such as R-01.');
      return;
    }
    if (project.state.cli.kind !== 'ready') {
      void vscode.window.showWarningMessage('Bio-STEWARD: A supported steward CLI is required to explain rules.');
      return;
    }
    const highlight = resultCode(rule, node ? node.code : code);
    this.#request?.abort();
    const request = this.#request = new AbortController();
    const result = await project.explain(rule, request.signal);
    if (request.signal.aborted || this.#request !== request) return;
    this.#request = undefined;
    if (!result || result.kind === 'cancelled' || result.kind === 'superseded' || result.kind === 'untrusted') return;
    if (result.kind !== 'completed' || result.exitCode !== 0 || !result.stdout.trim()) {
      const action = await vscode.window.showWarningMessage(`Bio-STEWARD: Could not explain ${rule}.`, 'Show Log');
      if (action) await vscode.commands.executeCommand('bioSteward.showLog');
      return;
    }
    if (!this.#panel) {
      const panel = vscode.window.createWebviewPanel('bioSteward.explain', '', vscode.ViewColumn.Beside, {
        enableCommandUris: [COPY_EXPLAIN_COMMAND],
        enableScripts: false,
        localResourceRoots: [],
      });
      this.#panel = panel;
      panel.onDidDispose(() => {
        this.#panel = undefined;
      });
    }
    this.#panel.title = `Explain ${rule} · Bio-STEWARD`;
    this.#panel.webview.html = explainHtml(rule, result.stdout, highlight);
    this.#panel.reveal();
  }

  dispose(): void {
    this.#request?.abort();
    this.#panel?.dispose();
  }
}
