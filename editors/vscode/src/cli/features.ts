import Ajv from 'ajv';
import { commands } from './commands';
import { parseJson } from './output';
import type { CliRunner, RunResult } from './runner';

interface InterfaceDocument {
  schema: 'steward.interface/1';
  interface: 1;
  tool_version: string;
  schemas: string[];
  json_commands: string[][];
  exit_codes: Record<string, unknown>;
}

const ajv = new Ajv({ ownProperties: true });
const validateInterface = ajv.compile<InterfaceDocument>({
  type: 'object',
  required: ['schema', 'interface', 'tool_version', 'schemas', 'json_commands', 'exit_codes'],
  properties: {
    schema: { const: 'steward.interface/1' },
    interface: { const: 1 },
    tool_version: { type: 'string' },
    schemas: { type: 'array', items: { type: 'string', minLength: 1 } },
    json_commands: {
      type: 'array',
      items: { type: 'array', minItems: 1, items: { type: 'string', minLength: 1 } },
    },
    exit_codes: { type: 'object' },
  },
});

const validateNewerInterface = ajv.compile<{ schema: string; interface: number; tool_version: string }>({
  type: 'object',
  required: ['schema', 'interface', 'tool_version'],
  properties: {
    schema: { type: 'string' },
    interface: { type: 'integer', minimum: 2 },
    tool_version: { type: 'string' },
  },
});

const versions = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([A-Za-z0-9.-]+))?(?:\+[A-Za-z0-9.-]+)?$/;

function parseVersion(value: string) {
  const match = versions.exec(value);
  return match && { numbers: match.slice(1, 4).map(Number), prerelease: match[4] };
}

function compareVersions(left: string, right: string): number {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (!a || !b) throw new Error('Invalid CLI version');
  for (let i = 0; i < a.numbers.length; i++) {
    if (a.numbers[i] !== b.numbers[i]) return a.numbers[i] - b.numbers[i];
  }
  if (a.prerelease === b.prerelease) return 0;
  if (!a.prerelease || !b.prerelease) return a.prerelease ? -1 : 1;
  const leftParts = a.prerelease.split('.');
  const rightParts = b.prerelease.split('.');
  for (let i = 0; i < Math.min(leftParts.length, rightParts.length); i++) {
    const x = leftParts[i];
    const y = rightParts[i];
    if (x === y) continue;
    if (/^\d+$/.test(x)) return /^\d+$/.test(y) ? Number(x) - Number(y) : -1;
    if (/^\d+$/.test(y)) return 1;
    return x < y ? -1 : 1;
  }
  return leftParts.length - rightParts.length;
}

const legacy = Object.freeze({
  checkReport: true,
  explainJson: false,
  digest: false,
  initPreviewJson: false,
  skillsInventory: false,
});

type Capabilities = Readonly<Record<keyof typeof legacy, boolean>>;
type InterfaceFeatures =
  | { mode: 'limited' | 'newer-interface' | 'full'; capabilities: Capabilities }
  | { mode: 'unreadable'; probe: 'interface' };

export type Detection =
  | ({ path: string; version: string; newerThanTested: boolean } & (InterfaceFeatures | { mode: 'too-old' }))
  | { path: string; mode: 'unreadable'; probe: 'version' }
  | { path: string; mode: 'failed'; result: Exclude<RunResult, { kind: 'completed' }> };

interface CliVersions {
  minimumCli: string;
  testedWithCli: string;
}

type ProbeRunner = Pick<CliRunner, 'cliPath' | 'run'>;

export class FeatureDetector {
  readonly #cache = new Map<string, Promise<InterfaceFeatures | Exclude<RunResult, { kind: 'completed' }>>>();

  constructor(private readonly versions: CliVersions) {}

  async detect(runner: ProbeRunner, signal?: AbortSignal): Promise<Detection> {
    const path = runner.cliPath;
    const result = await runner.run(commands.version(), { signal });
    if (result.kind !== 'completed' && result.kind !== 'unreadable') return { path, mode: 'failed', result };
    const version = result.kind === 'completed' && result.exitCode === 0
      ? /^steward\s+(\S+)$/.exec(result.stdout.trim())?.[1]
      : undefined;
    if (!version || !parseVersion(version)) return { path, mode: 'unreadable', probe: 'version' };

    const base = { path, version, newerThanTested: compareVersions(version, this.versions.testedWithCli) > 0 };
    if (compareVersions(version, this.versions.minimumCli) < 0) return { ...base, mode: 'too-old' };

    const key = JSON.stringify([path, version]);
    let probe = this.#cache.get(key);
    if (!probe) {
      probe = this.#detectInterface(runner, version, signal);
      this.#cache.set(key, probe);
    }
    const features = await probe;
    if ('kind' in features) {
      if (this.#cache.get(key) === probe) this.#cache.delete(key);
      return { path, mode: 'failed', result: features };
    }
    return { ...base, ...features };
  }

  async #detectInterface(runner: ProbeRunner, version: string, signal?: AbortSignal): Promise<InterfaceFeatures | Exclude<RunResult, { kind: 'completed' }>> {
    const result = await runner.run(commands.interface(), { signal });
    if (result.kind === 'completed' && result.exitCode === 64) return { mode: 'limited', capabilities: legacy };
    if (result.kind !== 'completed' && result.kind !== 'unreadable') return result;
    if (result.kind === 'completed' && result.exitCode === 0) {
      const parsed = parseJson(result.stdout, validateInterface);
      if (parsed.kind === 'valid' && parsed.value.tool_version === version) {
        const offers = (...prefix: string[]) => parsed.value.json_commands.some((args) =>
          args.length >= prefix.length && prefix.every((arg, index) => args[index] === arg));
        return {
          mode: 'full',
          capabilities: Object.freeze({
            checkReport: parsed.value.json_commands.some(([command, ...flags]) =>
              command === 'check' && !flags.includes('--digest-only')),
            explainJson: offers('explain'),
            digest: offers('check', '--digest-only'),
            initPreviewJson: offers('init', '--dry-run'),
            skillsInventory: offers('skills', 'list'),
          }),
        };
      }
      const newer = parseJson(result.stdout, validateNewerInterface);
      if (newer.kind === 'valid' && newer.value.tool_version === version &&
          newer.value.schema === `steward.interface/${newer.value.interface}`) {
        return { mode: 'newer-interface', capabilities: legacy };
      }
    }
    return { mode: 'unreadable', probe: 'interface' };
  }
}
