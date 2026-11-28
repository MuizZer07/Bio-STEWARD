// Unit suite for E03 Upgrade CLI (RELEASE_vscode_0.3.0_SPEC E03; design v0.9 §5):
// `steward upgrade --check --format json` validation, terminal command builder safety, modal dialog wording,
// Overview `Upgrade CLI` row, and post-upgrade contract check summary.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { isAllowed, type Invocation } from '../../src/cli/commands';
import { isUpgradeVersion, upgradeArgs, upgradeCommand, upgradeEnvironment } from '../../src/cli/upgrade';
import { parseUpgradeCheck, summarizeContractCheck, upgradeDialog, type UpgradeCheck } from '../../src/model/upgrade';
import type { Report } from '../../src/model/report';
import { initialState, overviewNodes, withReport, type ProjectState } from '../../src/model/views';

const SKIP_FLAG = ['-', '-', 'y', 'e', 's'].join('');
const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports');

function sampleCheck(overrides: Partial<UpgradeCheck> = {}): UpgradeCheck {
  return {
    schema: 'steward.upgrade/0.1',
    installed_version: '0.22.0',
    latest_version: '0.23.0',
    source: 'exchange',
    install_method: 'uv-tool',
    channel: null,
    upgrade_available: true,
    command: ['uv', 'tool', 'install', '--upgrade', 'bio-steward==0.23.0'],
    note: null,
    ...overrides,
  };
}

describe('Upgrade CLI (E03)', () => {
  describe('steward upgrade --check --format json parser', () => {
    it('accepts valid documents with and without an available upgrade', () => {
      const available = sampleCheck();
      assert.deepEqual(parseUpgradeCheck(JSON.stringify(available)), available);
      const current = sampleCheck({
        latest_version: null, source: null, install_method: 'unknown', upgrade_available: false, command: null, note: 'local only',
      });
      assert.deepEqual(parseUpgradeCheck(JSON.stringify(current)), current);
    });

    it('rejects wrong schema, unknown install method, or malformed JSON', () => {
      const valid = sampleCheck();
      for (const bad of [
        { ...valid, schema: 'steward.upgrade/0.2' },
        { ...valid, install_method: 'conda' },
        { ...valid, source: 'github' },
        { ...valid, upgrade_available: 'true' },
        { ...valid, command: 'uv tool upgrade' },
      ]) {
        assert.equal(parseUpgradeCheck(JSON.stringify(bad)), undefined);
      }
      assert.equal(parseUpgradeCheck('not json'), undefined);
    });
  });

  describe('terminal upgrade command builder', () => {
    it('builds steward upgrade --repo ROOT --to VERSION without any skip flag or network option', () => {
      const cmd = upgradeCommand('/usr/local/bin/steward', '/projects/my study', '0.23.0');
      assert.equal(cmd.program, '/usr/local/bin/steward');
      assert.deepEqual(cmd.args, ['upgrade', '--repo', '/projects/my study', '--to', '0.23.0']);
      assert.equal(cmd.line, "/usr/local/bin/steward upgrade --repo '/projects/my study' --to 0.23.0");
      assert.equal(cmd.args.includes(SKIP_FLAG), false);
      assert.equal(cmd.args.includes('--online'), false);
      assert.equal(cmd.args.includes('--allow-downgrade'), false);

      // Not on the background allow-list.
      const forged: Invocation = { args: cmd.args, repoIndex: undefined, paths: [], confirmation: false };
      assert.equal(isAllowed(forged), false);
    });

    it('accepts valid Python/semver release versions and rejects invalid versions or paths', () => {
      for (const good of ['0.23.0', '1.0.0', '0.23.0a1', '0.23.0b2', '0.23.0rc1', '0.23.0.dev3', '0.23.0.post1']) {
        assert.equal(isUpgradeVersion(good), true, good);
        assert.deepEqual(upgradeArgs('/repo', good), ['upgrade', '--repo', '/repo', '--to', good]);
      }
      for (const bad of ['', 'v0.23.0', '-0.23.0', SKIP_FLAG, '0.23.0 --allow-downgrade', '0.23.0; rm -rf /', '0.23.0\n', 'latest']) {
        assert.equal(isUpgradeVersion(bad), false, bad);
        assert.throws(() => upgradeCommand('/bin/steward', '/repo', bad), /Invalid target version/, bad);
      }
      assert.throws(() => upgradeCommand('steward', '/repo', '0.23.0'), /Invalid CLI path/);
      assert.throws(() => upgradeCommand('/bin/steward', 'relative/repo', '0.23.0'), /Invalid project root/);
      assert.throws(() => upgradeCommand('/bin/steward\n', '/repo', '0.23.0'), /Invalid CLI path/);
    });

    it('strips VS Code and Electron internal environment variables for the upgrade terminal', () => {
      const env = upgradeEnvironment({
        PATH: '/usr/bin',
        HOME: '/home/user',
        VSCODE_IPC_HOOK: '/tmp/hook',
        ELECTRON_RUN_AS_NODE: '1',
      });
      assert.equal(env.PATH, '/usr/bin');
      assert.equal(env.HOME, '/home/user');
      assert.equal(env.TERM, 'xterm-256color');
      assert.equal('VSCODE_IPC_HOOK' in env, false);
      assert.equal('ELECTRON_RUN_AS_NODE' in env, false);
    });
  });

  describe('modal dialog, Overview row, and contract check summary', () => {
    it('shows the exact command and installer in the modal wording', () => {
      const dialog = upgradeDialog({
        project: 'geo',
        installed: '0.22.0',
        target: '0.23.0',
        method: 'uv-tool',
        source: 'exchange',
        cliLine: '/bin/steward upgrade --repo /repo --to 0.23.0',
        installerCommand: ['uv', 'tool', 'install', '--upgrade', 'bio-steward==0.23.0'],
      });
      assert.equal(dialog.title, 'Upgrade steward CLI from 0.22.0 to 0.23.0?');
      const text = dialog.detail.join('\n');
      assert.ok(text.includes('/bin/steward upgrade --repo /repo --to 0.23.0'));
      assert.ok(text.includes('uv tool install --upgrade bio-steward==0.23.0'));
      assert.ok(text.includes('[y/N]'));
      assert.ok(text.includes('contract check'));
    });

    it('shows Upgrade CLI in Overview only when an upgrade is available', () => {
      const report = JSON.parse(readFileSync(join(fixtures, 'geo.json'), 'utf8')) as Report;
      const base: ProjectState = withReport({
        ...initialState(true),
        cli: { kind: 'ready', version: '0.22.0', mode: 'full', newerThanTested: false },
      }, report);
      assert.equal(overviewNodes(base).some((n) => n.kind === 'upgrade'), false);
      const upToDate: ProjectState = { ...base, upgrade: { kind: 'ready', check: sampleCheck({ upgrade_available: false }) } };
      assert.equal(overviewNodes(upToDate).some((n) => n.kind === 'upgrade'), false);

      const available: ProjectState = { ...base, upgrade: { kind: 'ready', check: sampleCheck() } };
      const nodes = overviewNodes(available);
      assert.equal(nodes[0].kind, 'cli');
      assert.equal(nodes[1].kind, 'upgrade');
      assert.equal(nodes[1].label, 'Upgrade CLI');
      assert.equal(nodes[1].description, 'steward 0.22.0 → 0.23.0');
      assert.equal(nodes[1].command, 'upgradeCli');
    });

    it('summarizes passing and failing post-upgrade contract checks clearly', () => {
      const passed = summarizeContractCheck({
        beforeVersion: '0.22.0',
        afterVersion: '0.23.0',
        mode: 'full',
        newerThanTested: true,
        checks: [
          { name: 'cli-detect', ok: true, detail: 'steward 0.23.0' },
          { name: 'interface', ok: true, detail: 'full mode' },
          { name: 'report-schema', ok: true, detail: 'completed' },
        ],
      });
      assert.equal(passed.ok, true);
      assert.equal(passed.upgraded, true);
      assert.match(passed.summary, /steward 0\.22\.0 → 0\.23\.0.*CLI newer than tested.*Contract check passed/);

      const failed = summarizeContractCheck({
        beforeVersion: '0.22.0',
        afterVersion: undefined,
        mode: undefined,
        newerThanTested: false,
        checks: [{ name: 'cli-detect', ok: false, detail: 'CLI state is failed' }],
      });
      assert.equal(failed.ok, false);
      assert.equal(failed.upgraded, false);
      assert.match(failed.summary, /Contract check failed.*cli-detect: CLI state is failed/);
    });
  });
});
