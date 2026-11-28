// E03 (design v0.9 §5; RELEASE_vscode_0.3.0_SPEC E03): upgrading the steward CLI from VS Code.
//
// After the person confirms the exact command in a modal dialog, the extension runs the CLI's own interactive
// `steward upgrade --repo ROOT --to VERSION` as the process of a dedicated, visible terminal. The CLI prints the
// detected installer command and asks `[y/N]` in the terminal before running the installer.
//
// Safety properties (parallel to src/cli/signing.ts):
// - Not on the background allow-list (src/cli/commands.ts), so CliRunner refuses it.
// - Validates the version strictly (no leading `-`, no whitespace or control characters) and absolute paths.
// - Never passes any flag that skips confirmation, never passes `--online` or `--allow-downgrade`.
// - No shell runs it and no text is sent to any terminal: the terminal's process is the CLI itself, with `strictEnv`.
import { isAbsolute } from 'node:path';
import { signingEnvironment } from './signing';

// Same version grammar as the CLI's `upgrade.py` (without an optional leading `v`).
const UPGRADE_VERSION = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:(?:\.dev|a|b|rc|\.post)(?:0|[1-9]\d*))?$/;
const CONTROL = /\p{Cc}/u;

export function isUpgradeVersion(value: unknown): value is string {
  return typeof value === 'string' && UPGRADE_VERSION.test(value);
}

function absolute(value: string, what: string): string {
  if (typeof value !== 'string' || !isAbsolute(value) || CONTROL.test(value)) {
    throw new Error(`Invalid ${what} for the upgrade command`);
  }
  return value;
}

function validVersion(value: string): string {
  if (!isUpgradeVersion(value)) throw new Error('Invalid target version for the upgrade command');
  return value;
}

// POSIX single quotes for display and logging (macOS, Linux and WSL).
export function quoteArg(part: string): string {
  return /^[\w./:=,-]+$/.test(part) ? part : `'${part.replaceAll("'", "'\\''")}'`;
}

export function formatArgv(argv: readonly string[]): string {
  return argv.map(quoteArg).join(' ');
}

export function upgradeArgs(root: string, version: string): readonly string[] {
  return Object.freeze(['upgrade', '--repo', absolute(root, 'project root'), '--to', validVersion(version)]);
}

export interface UpgradeCommand {
  readonly program: string;
  readonly args: readonly string[];
  readonly version: string;
  readonly line: string;
}

export function upgradeCommand(cli: string, root: string, version: string): UpgradeCommand {
  const program = absolute(cli, 'CLI path');
  const target = validVersion(version);
  const args = upgradeArgs(root, target);
  return Object.freeze({ program, args, version: target, line: formatArgv([program, ...args]) });
}

// Re-export the hardened terminal environment (drops VSCODE_* / ELECTRON_* and keeps workspace terminal env out).
export const upgradeEnvironment = signingEnvironment;
