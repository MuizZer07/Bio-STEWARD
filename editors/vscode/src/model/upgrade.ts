// E03 (design v0.9 §5; RELEASE_vscode_0.3.0_SPEC E03): `steward upgrade --check --format json` parser, modal
// confirmation wording, and post-upgrade contract check summary. Pure: no `vscode` import.
import Ajv from 'ajv';
import { parseJson } from '../cli/output';
import { formatArgv } from '../cli/upgrade';

export const UPGRADE_SCHEMA = 'steward.upgrade/0.1';
export const UPGRADE_MIN_CLI = '0.21.0';
export const UPGRADE_BUTTON = 'Upgrade in a Terminal';

export type InstallMethod = 'uv-tool' | 'pipx' | 'pip' | 'channel' | 'unknown';

export interface UpgradeCheck {
  readonly schema: typeof UPGRADE_SCHEMA;
  readonly installed_version: string;
  readonly latest_version: string | null;
  readonly source: 'exchange' | 'pypi' | null;
  readonly install_method: InstallMethod;
  readonly channel: 'dev' | 'stable' | null;
  readonly upgrade_available: boolean;
  readonly command: readonly string[] | null;
  readonly note: string | null;
}

export type UpgradeState =
  | { readonly kind: 'none' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly check: UpgradeCheck }
  | { readonly kind: 'unsupported'; readonly minimum: string }
  | { readonly kind: 'not-configured' | 'unreadable' | 'failed' };

const ajv = new Ajv({ ownProperties: true });
const validateUpgrade = ajv.compile<UpgradeCheck>({
  type: 'object',
  required: [
    'schema', 'installed_version', 'latest_version', 'source', 'install_method', 'channel',
    'upgrade_available', 'command', 'note',
  ],
  properties: {
    schema: { const: UPGRADE_SCHEMA },
    installed_version: { type: 'string', minLength: 1, maxLength: 128 },
    latest_version: { type: ['string', 'null'], maxLength: 128 },
    source: { enum: ['exchange', 'pypi', null] },
    install_method: { enum: ['uv-tool', 'pipx', 'pip', 'channel', 'unknown'] },
    channel: { enum: ['dev', 'stable', null] },
    upgrade_available: { type: 'boolean' },
    command: {
      anyOf: [
        { type: 'array', maxItems: 64, items: { type: 'string', maxLength: 1000 } },
        { type: 'null' },
      ],
    },
    note: { type: ['string', 'null'], maxLength: 1000 },
  },
});

export function parseUpgradeCheck(stdout: string): UpgradeCheck | undefined {
  const parsed = parseJson(stdout, validateUpgrade);
  return parsed.kind === 'valid' ? parsed.value : undefined;
}

export interface UpgradeDialogDetails {
  readonly project: string;
  readonly installed: string;
  readonly target: string;
  readonly method: InstallMethod;
  readonly source: 'exchange' | 'pypi' | null;
  readonly cliLine: string;
  readonly installerCommand: readonly string[] | null;
}

export interface UpgradeDialog {
  readonly title: string;
  readonly detail: readonly string[];
}

export function upgradeDialog(details: UpgradeDialogDetails): UpgradeDialog {
  const installer = details.installerCommand ? formatArgv(details.installerCommand) : 'not detected';
  const source = details.source ?? 'local release notice';
  return {
    title: `Upgrade steward CLI from ${details.installed} to ${details.target}?`,
    detail: [
      `Project: ${details.project} (source: ${source})`,
      '',
      'Command to run in a visible terminal:',
      `  ${details.cliLine}`,
      '',
      `Installer detected by the CLI (${details.method}):`,
      `  ${installer}`,
      '',
      'The CLI will print the install command and ask [y/N] in the terminal before running the installer. ' +
        'Cancel runs nothing and opens no terminal. When the terminal closes, Bio-STEWARD will re-detect the CLI ' +
        'and run its contract check.',
    ],
  };
}

export interface ContractCheckItem {
  readonly name: string;
  readonly ok: boolean;
  readonly detail: string;
}

export interface ContractCheckResult {
  readonly ok: boolean;
  readonly beforeVersion: string;
  readonly afterVersion: string | undefined;
  readonly upgraded: boolean;
  readonly mode: string | undefined;
  readonly newerThanTested: boolean;
  readonly checks: readonly ContractCheckItem[];
  readonly summary: string;
}

export function summarizeContractCheck(input: {
  readonly beforeVersion: string;
  readonly afterVersion: string | undefined;
  readonly mode: string | undefined;
  readonly newerThanTested: boolean;
  readonly checks: readonly ContractCheckItem[];
}): ContractCheckResult {
  const ok = input.checks.length > 0 && input.checks.every((item) => item.ok);
  const upgraded = input.afterVersion !== undefined && input.afterVersion !== input.beforeVersion;
  const newer = input.newerThanTested ? ' · CLI newer than tested' : '';
  const versionPart = input.afterVersion
    ? upgraded
      ? `steward ${input.beforeVersion} → ${input.afterVersion} (${input.mode ?? 'unknown'} mode${newer})`
      : `steward ${input.afterVersion} unchanged (${input.mode ?? 'unknown'} mode${newer})`
    : `CLI not ready after upgrade (was ${input.beforeVersion})`;
  const failed = input.checks.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`);
  const summary = ok
    ? `Bio-STEWARD: ${versionPart}. Contract check passed (${input.checks.map((c) => c.name).join(', ')}).`
    : `Bio-STEWARD: ${versionPart}. Contract check failed (${failed.join('; ')}). See Show Log.`;
  return {
    ok,
    beforeVersion: input.beforeVersion,
    afterVersion: input.afterVersion,
    upgraded,
    mode: input.mode,
    newerThanTested: input.newerThanTested,
    checks: input.checks,
    summary,
  };
}
