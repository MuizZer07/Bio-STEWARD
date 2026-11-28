// Host suite for E03 Upgrade CLI (RELEASE_vscode_0.3.0_SPEC E03; design v0.9 §5) on the `cockpit` workspace:
// - detects an available upgrade from `steward upgrade --check --format json` and shows Upgrade CLI in Overview;
// - declining the modal opens no terminal;
// - accepting the modal opens a visible terminal running `steward upgrade --repo ROOT --to VERSION` with strictEnv
//   and without any skip-prompt flag;
// - when the terminal closes, the extension detects the new CLI version and runs its contract check.
import { strict as assert } from 'node:assert';
import { chmodSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import type { UpgradeDialogDetails } from '../../src/model/upgrade';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const SKIP_FLAG = ['-', '-', 'y', 'e', 's'].join('');
const fixtureReport = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports', 'geo.json');

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

function inertTerminal(calls: vscode.TerminalOptions[]) {
  return (options: vscode.TerminalOptions) => {
    calls.push(options);
    const write = new vscode.EventEmitter<string>();
    return vscode.window.createTerminal({
      name: options.name ?? 'inert-upgrade',
      pty: { onDidWrite: write.event, open: () => undefined, close: () => write.dispose() },
    });
  };
}

function writeStubCli(path: string, stateFile: string, reportFile: string): void {
  const script = `#!/usr/bin/env node
const fs = require('node:fs');
const state = JSON.parse(fs.readFileSync(${JSON.stringify(stateFile)}, 'utf8'));
const args = process.argv.slice(2);
if (args[0] === '--version') {
  console.log('steward ' + state.version);
  process.exit(0);
}
if (args[0] === 'interface') {
  if (state.brokenInterface) {
    console.log('{broken');
    process.exit(0);
  }
  console.log(JSON.stringify({
    schema: 'steward.interface/1',
    interface_version: 1,
    tool_version: state.version,
    commands: {
      check: { argv: ['--format', 'json'] },
      notifications: { argv: ['--format', 'json'] },
      'upgrade --check': { argv: ['--check', '--format', 'json'] },
    },
    exit_codes: {},
  }));
  process.exit(0);
}
if (args[0] === 'upgrade' && args.includes('--check')) {
  console.log(JSON.stringify({
    schema: 'steward.upgrade/0.1',
    installed_version: state.version,
    latest_version: state.upgradeAvailable ? state.latest : null,
    source: state.upgradeAvailable ? 'exchange' : null,
    install_method: 'uv-tool',
    channel: null,
    upgrade_available: Boolean(state.upgradeAvailable),
    command: state.upgradeAvailable ? ['uv', 'tool', 'install', '--upgrade', 'bio-steward==' + state.latest] : null,
    note: null,
  }));
  process.exit(0);
}
if (args[0] === 'notifications') {
  const items = state.upgradeAvailable ? [{
    id: 'upgrade:REL-001',
    kind: 'upgrade',
    time: '2026-11-27T10:00:00Z',
    source: 'exchange/inbox/REL-001.md',
    title: 'Bio-STEWARD ' + state.latest + ' is released, newer than this CLI (steward --version)',
    command: 'steward exchange status',
    urgent: false,
  }] : [];
  console.log(JSON.stringify({
    schema: 'steward.notifications/0.1',
    tool_version: state.version,
    now: '2026-11-27T12:00:00Z',
    days: 14,
    items,
    notes: [],
  }));
  process.exit(0);
}
if (args[0] === 'check') {
  const outIndex = args.indexOf('--output');
  if (outIndex >= 0 && args[outIndex + 1]) {
    const report = JSON.parse(fs.readFileSync(${JSON.stringify(reportFile)}, 'utf8'));
    report.envelope.tool_version = state.version;
    fs.writeFileSync(args[outIndex + 1], JSON.stringify(report));
  }
  process.exit(0);
}
if (args[0] === 'timeline') {
  console.log(JSON.stringify({ schema: 'steward.timeline/0.1', milestones: [] }));
  process.exit(0);
}
if (args[0] === 'audit' && args[1] === 'progress') {
  console.log(JSON.stringify({
    schema: 'steward.progress_audit/0.1',
    pending: { signatures_waiting: [], milestones: [], sprints: [] },
  }));
  process.exit(0);
}
if (args[0] === 'authorize' && args[1] === 'pending') {
  console.log('0 waiting');
  process.exit(0);
}
process.exit(0);
`;
  writeFileSync(path, script);
  chmodSync(path, 0o700);
}

describe('Upgrade CLI from the extension (E03)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.project.state.cli.kind === 'ready', 'initial CLI detection', 60000);
  });

  it('shows Upgrade CLI in Overview, confirms the exact command in a modal, runs steward upgrade --to VERSION in a visible terminal, then detects the new CLI and runs its contract check', async function () {
    this.timeout(90000);
    assert.ok(api);
    const config = vscode.workspace.getConfiguration('bioSteward');
    const originalCli = config.inspect<string>('cliPath')?.globalValue;
    const expectedOriginalCli = originalCli ? realpathSync(originalCli) : undefined;
    const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'steward-upgrade-host-')));
    const stubCli = join(scratch, 'steward-stub');
    const stateFile = join(scratch, 'state.json');
    const reportCopy = join(scratch, 'geo.json');
    writeFileSync(reportCopy, readFileSync(fixtureReport, 'utf8'));
    writeFileSync(stateFile, JSON.stringify({ version: '0.22.0', upgradeAvailable: true, latest: '0.23.0' }));
    writeStubCli(stubCli, stateFile, reportCopy);

    try {
      await api.notifications.readStore.clear();
      api.notifications.bell.resetToasts();
      await config.update('cliPath', stubCli, vscode.ConfigurationTarget.Global);
      await until(() => api!.project.state.cli.kind === 'ready'
        && api!.project.cliPath === stubCli
        && api!.project.state.upgrade?.kind === 'ready'
        && api!.project.state.upgrade.check.upgrade_available === true
        && api!.notifications.bell.view.unread === 1,
      'stub CLI detection, upgrade check and bell update', 30000);
      await vscode.commands.executeCommand('bioSteward.runCheck');
      await until(() => api!.overview.tree.nodes.some((n) => n.kind === 'upgrade'), 'Upgrade CLI row in Overview', 10000);

      // Overview shows Upgrade CLI and the bell shows the upgrade notification (without toasting).
      const upgradeRow = api.overview.tree.nodes.find((n) => n.kind === 'upgrade');
      assert.ok(upgradeRow, 'Upgrade CLI row shown in Overview');
      assert.equal(upgradeRow.label, 'Upgrade CLI');
      assert.equal(upgradeRow.description, 'steward 0.22.0 → 0.23.0');
      assert.equal(api.notifications.bell.view.unread, 1);
      assert.equal(api.notifications.bell.shownToasts.length, 0, 'upgrade notification never triggers an urgent toast');

      // Declining the modal runs nothing and opens no terminal.
      const declinedCalls: vscode.TerminalOptions[] = [];
      let seenDetails: UpgradeDialogDetails | undefined;
      const declined = await api.upgrade.run(api.project.root, {
        confirm: async (details) => {
          seenDetails = details;
          return false;
        },
        openTerminal: inertTerminal(declinedCalls),
      });
      assert.equal(declined, undefined);
      assert.equal(declinedCalls.length, 0);
      assert.ok(seenDetails);
      assert.equal(seenDetails.installed, '0.22.0');
      assert.equal(seenDetails.target, '0.23.0');
      assert.ok(seenDetails.cliLine.includes('--to 0.23.0'));

      // Accepting the modal opens a visible terminal with exact args, strictEnv, and no skip flag.
      const acceptedCalls: vscode.TerminalOptions[] = [];
      const outcome = await api.upgrade.run(api.project.root, {
        confirm: async () => true,
        openTerminal: inertTerminal(acceptedCalls),
      });
      assert.ok(outcome);
      assert.equal(acceptedCalls.length, 1);
      const [termOpts] = acceptedCalls;
      assert.equal(termOpts.shellPath, stubCli);
      assert.deepEqual(termOpts.shellArgs, ['upgrade', '--repo', api.project.root, '--to', '0.23.0']);
      assert.equal(termOpts.strictEnv, true);
      assert.equal((termOpts.shellArgs as string[]).includes(SKIP_FLAG), false);

      // Simulate the upgrade succeeding: stub now reports 0.23.0 and no further upgrade.
      writeFileSync(stateFile, JSON.stringify({ version: '0.23.0', upgradeAvailable: false, latest: null }));

      // Closing the terminal triggers re-detection and the post-upgrade contract check.
      outcome.terminal.dispose();
      await until(() => api!.upgrade.lastContractCheck?.afterVersion === '0.23.0',
        'post-upgrade detection and contract check', 30000);
      const check = api.upgrade.lastContractCheck!;
      assert.equal(check.ok, true);
      assert.equal(check.beforeVersion, '0.22.0');
      assert.equal(check.afterVersion, '0.23.0');
      assert.equal(check.upgraded, true);
      assert.equal(check.newerThanTested, true);
      assert.ok(check.checks.some((c) => c.name === 'interface' && c.ok));
      assert.ok(check.checks.some((c) => c.name === 'notifications' && c.ok));
      assert.ok(check.checks.some((c) => c.name === 'upgrade-check' && c.ok));
      assert.ok(check.checks.some((c) => c.name === 'report-schema' && c.ok));
      assert.equal(api.project.cliVersion, '0.23.0');
      assert.equal(api.overview.tree.nodes.some((n) => n.kind === 'upgrade'), false, 'Upgrade CLI row gone once upgraded');

      // A broken CLI after upgrade fails the contract check cleanly.
      writeFileSync(stateFile, JSON.stringify({ version: '0.24.0', brokenInterface: true }));
      const failed = await api.upgrade.contractCheck(api.project, '0.23.0');
      assert.equal(failed.ok, false);
      assert.equal(failed.afterVersion, undefined);
      assert.ok(failed.checks.some((c) => c.name === 'cli-detect' && !c.ok));
    } finally {
      await config.update('cliPath', originalCli, vscode.ConfigurationTarget.Global);
      await until(() => api!.project.state.cli.kind === 'ready' && api!.project.cliPath === expectedOriginalCli,
        'restored pinned CLI', 30000);
      rmSync(scratch, { recursive: true, force: true });
    }
  });
});
