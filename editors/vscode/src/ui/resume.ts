// Resume (S4; design v0.2 §5): the last session handoff, shown on demand as a read-only document holding the
// file's text unchanged (AC-S4). Read from the `[session] handoff` file; no CLI call, nothing written.
import * as vscode from 'vscode';
import type { Project } from '../project';

export const RESUME_COMMAND = 'bioSteward.resume';
export const RESUME_SCHEME = 'bio-steward-handoff';

export class ResumeView implements vscode.TextDocumentContentProvider, vscode.Disposable {
  readonly #texts = new Map<string, string>();
  readonly #changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.#changed.event;
  readonly #registration = vscode.workspace.registerTextDocumentContentProvider(RESUME_SCHEME, this);
  #last: vscode.TextDocument | undefined;

  // The document last shown (for the host tests).
  get document(): vscode.TextDocument | undefined {
    return this.#last;
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.#texts.get(uri.toString()) ?? '';
  }

  async show(project: Project | undefined): Promise<void> {
    if (!project) {
      void vscode.window.showInformationMessage('Bio-STEWARD: Open a project folder to resume.');
      return;
    }
    const handoff = await project.readHandoff();
    if (handoff.kind === 'missing') {
      void vscode.window.showInformationMessage(
        `Bio-STEWARD: No handoff yet (${handoff.path}) in ${project.name}. \`steward session close\` writes it.`);
      return;
    }
    if (handoff.kind === 'unreadable') {
      void vscode.window.showWarningMessage(`Bio-STEWARD: The handoff of ${project.name} could not be read: ${handoff.reason}.`);
      return;
    }
    // One document per project and file; the query keeps two projects' handoffs apart.
    const uri = vscode.Uri.from({
      scheme: RESUME_SCHEME,
      path: `/${project.name}/${handoff.path.split(/[\\/]/).pop() ?? 'HANDOFF.md'}`,
      query: encodeURIComponent(project.root),
    });
    const key = uri.toString();
    const changed = this.#texts.has(key) && this.#texts.get(key) !== handoff.text;
    this.#texts.set(key, handoff.text);
    if (changed) this.#changed.fire(uri);
    const document = await vscode.workspace.openTextDocument(uri);
    this.#last = await vscode.languages.setTextDocumentLanguage(document, 'markdown');
    await vscode.window.showTextDocument(this.#last, { preview: true });
  }

  dispose(): void {
    this.#registration.dispose();
    this.#changed.dispose();
  }
}
