import { createHash } from 'node:crypto';
import * as vscode from 'vscode';

export const DETAILS_SCHEME = 'bio-steward-details';

export function isMarkdown(path: string): boolean {
  return /\.(md|markdown|mdown|mkd|mkdn)$/i.test(path);
}

export async function openFile(uri: vscode.Uri, asText = false, line?: number): Promise<vscode.Uri> {
  if (!asText && isMarkdown(uri.path)) {
    await vscode.commands.executeCommand('markdown.showPreview', uri, { line: line === undefined ? undefined : line - 1 });
  } else {
    const selection = line === undefined ? undefined : new vscode.Range(line - 1, 0, line - 1, 0);
    await vscode.window.showTextDocument(uri, { preview: true, selection });
  }
  return uri;
}

// Treat every report field as literal text. Indented code blocks cannot contain active links, HTML or images.
function literalBlock(text: string): string {
  // eslint-disable-next-line no-control-regex -- remove terminal control characters while retaining tabs and line breaks.
  return text.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, ' ').split('\n').map((line) => `    ${line}`).join('\n');
}

export class DetailsView implements vscode.TextDocumentContentProvider, vscode.Disposable {
  readonly #texts = new Map<string, string>();
  readonly #provider = vscode.workspace.registerTextDocumentContentProvider(DETAILS_SCHEME, this);

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.#texts.get(uri.toString()) ?? '';
  }

  async show(title: string, source: string, meaning: string, next: string): Promise<vscode.Uri> {
    const markdown = [
      '# Record details', '## Item', literalBlock(title), '## Source', literalBlock(source),
      '## What it means', literalBlock(meaning), '## Next step', literalBlock(next),
    ].join('\n\n') + '\n';
    const key = createHash('sha256').update(markdown).digest('hex');
    const name = title.replace(/[^\p{L}\p{N} ._-]/gu, ' ').trim().slice(0, 80) || 'Details';
    const uri = vscode.Uri.from({ scheme: DETAILS_SCHEME, path: `/${name}.md`, query: key });
    this.#texts.delete(uri.toString());
    this.#texts.set(uri.toString(), markdown);
    if (this.#texts.size > 64) this.#texts.delete(this.#texts.keys().next().value!);
    return openFile(uri);
  }

  dispose(): void {
    this.#provider.dispose();
    this.#texts.clear();
  }
}
