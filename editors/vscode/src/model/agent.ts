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

export const MAX_BRIEF_BYTES = 16 * 1024;
const TRUNCATED = '\n\n[Brief truncated by Bio-STEWARD.]\n';

export function boundedBrief(text: string): string {
  const bytes = Buffer.from(text, 'utf8');
  if (bytes.length <= MAX_BRIEF_BYTES) return text;
  let end = MAX_BRIEF_BYTES - Buffer.byteLength(TRUNCATED);
  while ((bytes[end] & 0xc0) === 0x80) end--;
  return bytes.subarray(0, end).toString('utf8') + TRUNCATED;
}
