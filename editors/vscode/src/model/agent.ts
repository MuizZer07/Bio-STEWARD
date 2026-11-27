// Copy for agent (S5; TOK-2): the clipboard text. Pure: no `vscode` import.
//
// The text is the CLI's own `steward check [--rule R-xx] --summary` output, unchanged, then the command that
// re-checks it and the summary's size in bytes. No new format.
import type { Rule } from '../cli/commands';

// The command an agent runs to re-check what it was given.
export function recheckCommand(rule?: Rule): string {
  return rule === undefined ? 'steward check --summary' : `steward check --rule ${rule} --summary`;
}

export function agentText(summary: string, rule: Rule | undefined, version: string): string {
  const bytes = Buffer.byteLength(summary, 'utf8');
  const command = recheckCommand(rule);
  return `${summary}${summary.endsWith('\n') ? '' : '\n'}\nRe-check: ${command}\n` +
    `(the text above is \`${command}\` from steward ${version}, unchanged: ${bytes} bytes)\n`;
}
