// P5 (design v0.8 §2, which overrides v0.3 §2.2): the signing flow's one write path.
//
// The extension never signs. After the person accepts the modal confirmation of a card's ✍ Sign (and, for the
// high-stakes actions, types the action's name), it runs the CLI's own interactive `steward authorize sign-pending
// --repo ROOT` as the process of a dedicated, visible terminal. The CLI prints the exact bytes of each waiting payload
// and asks before each signature; the key's own prompt (passphrase, agent confirmation, hardware touch) completes it.
//
// What this module holds, and why it is safe:
// - The command is a program and an argument list for the terminal, never an `Invocation`, so the background runner
//   (src/cli/runner.ts) refuses it: `isAllowed` knows only what src/cli/commands.ts built.
// - The only flag is `--repo ROOT`. Nothing here can add another; the CLI's flag that skips its question is never
//   written in this extension's source.
// - No shell runs it and no text is sent to any terminal: the terminal's process is the CLI itself, so nothing can
//   be typed after it, and a path cannot be read as shell syntax.
// - No key is read and no file is opened here.
import { isAbsolute } from 'node:path';

// The CLI arguments before `--repo ROOT` (CLI 0.20.6 `authorize sign-pending`).
const SIGN_PENDING: readonly string[] = Object.freeze(['authorize', 'sign-pending']);

// Any control character (line breaks, tabs, escape, DEL and the C1 range).
const CONTROL = /\p{Cc}/u;

function absolute(value: string, what: string): string {
  if (typeof value !== 'string' || !isAbsolute(value) || CONTROL.test(value)) throw new Error(`Invalid ${what} for the signing command`);
  return value;
}

// POSIX single quotes, as src/ui/skills.ts shows a command line (macOS, Linux and WSL only, VX10). Display only.
function quote(part: string): string {
  return /^[\w./:=,-]+$/.test(part) ? part : `'${part.replaceAll("'", "'\\''")}'`;
}

// The arguments after the program: `authorize sign-pending --repo ROOT`.
export function signingArgs(root: string): readonly string[] {
  return Object.freeze([...SIGN_PENDING, '--repo', absolute(root, 'project root')]);
}

export interface SigningCommand {
  // The terminal's process: the CLI the extension found, by its absolute path.
  readonly program: string;
  readonly args: readonly string[];
  // The same command as one line, to show the person and to log.
  readonly line: string;
}

export function signingCommand(cli: string, root: string): SigningCommand {
  const program = absolute(cli, 'CLI path');
  const args = signingArgs(root);
  return Object.freeze({ program, args, line: [program, ...args].map(quote).join(' ') });
}

// The signing terminal's whole environment (U08's first high finding). The terminal is opened with `strictEnv: true`
// and this object, so VS Code adds nothing: neither a workspace's `terminal.integrated.env.*` settings nor another
// extension's environment collection (a workspace interpreter's PATH, for example) reach the CLI. The variables come
// from the extension host's own environment, which is the user's (a repository's settings cannot change it), without
// VS Code's and Electron's internal ones. TERM is set because no shell sets it here.
const INTERNAL = /^(?:VSCODE_|ELECTRON_)/;

export function signingEnvironment(host: Readonly<Record<string, string | undefined>>): Readonly<Record<string, string>> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(host)) {
    if (typeof value !== 'string' || INTERNAL.test(key) || CONTROL.test(key) || key.includes('=') || !key) continue;
    if (value.includes('\0')) continue;
    env[key] = value;
  }
  env.TERM = 'xterm-256color';
  return Object.freeze(env);
}
