// Every text the extension copies goes through here: it is written to the system clipboard and kept as the last
// copy of this extension host, so the host tests assert on what the extension copied, not on the system clipboard,
// which other programs and test runs share (T11-06).
import * as vscode from 'vscode';

let last: string | undefined;
let count = 0;

export async function copyText(text: string): Promise<void> {
  last = text;
  count++;
  await vscode.env.clipboard.writeText(text);
}

export const lastCopy = Object.freeze({
  get text(): string | undefined {
    return last;
  },
  get count(): number {
    return count;
  },
});
