import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { Socket as DatagramSocket } from 'node:dgram';
import { existsSync, readFileSync, renameSync, unlinkSync } from 'node:fs';
import { Socket } from 'node:net';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import type { Report } from '../../src/model/report';

const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const extension = () => {
  const ext = vscode.extensions.getExtension<TestApi>('MuizZer07.bio-steward');
  assert.ok(ext);
  return ext;
};

if (example === 'restricted') {
  describe('Restricted Mode (T09)', () => {
    it('shows the trust prompt and never invokes steward, even through direct commands', async () => {
      assert.equal(vscode.workspace.isTrusted, false);
      const calls = process.env.BIO_STEWARD_TEST_CLI_CALLS;
      const spy = vscode.workspace.getConfiguration('bioSteward').inspect<string>('cliPath')?.globalValue;
      assert.ok(calls && spy);
      const api = await extension().activate();
      assert.equal(api.project.state.trusted, false);
      assert.equal(api.statusBar.view?.accessibility, 'Bio-STEWARD: Restricted Mode');
      assert.match(api.statusBar.view?.tooltip.join(' ') ?? '', /Trust it to run checks/);
      assert.deepEqual(api.overview.tree.nodes, []);
      assert.deepEqual(api.results.tree.nodes, []);
      const { commands, viewsWelcome } = extension().packageJSON.contributes as {
        commands: { command: string; enablement?: string }[];
        viewsWelcome: { view: string; when: string; contents: string }[];
      };
      for (const view of ['bioSteward.overview', 'bioSteward.results']) {
        const welcome = viewsWelcome.find((item) => item.view === view && item.when === "bioSteward.empty == 'untrusted'");
        assert.match(welcome?.contents ?? '', /\[Manage Workspace Trust\]\(command:workbench\.trust\.manage\)/);
      }
      const args: Record<string, string> = {
        'bioSteward.explainRule': 'R-85',
        'bioSteward.runCheckForArea': 'skills',
        'bioSteward.runCheckForRule': 'R-60',
      };
      for (const { command } of commands.filter((item) => item.enablement === 'isWorkspaceTrusted')) {
        const arg = args[command];
        if (arg === undefined) await vscode.commands.executeCommand(command);
        else await vscode.commands.executeCommand(command, arg);
      }
      await vscode.commands.executeCommand('bioSteward.showOverview');
      // E01: every panel's refresh button was among those commands; in Restricted Mode none of them ran.
      assert.deepEqual(api.refreshes, [], 'no panel refresh ran');
      // E03: notifications bell and Upgrade CLI run nothing and show no toast or bell in Restricted Mode.
      assert.equal(api.notifications.bell.view.visible, false, 'bell is hidden in Restricted Mode');
      assert.deepEqual(api.notifications.bell.shownToasts, [], 'no notification toast in Restricted Mode');
      assert.equal(api.upgrade.lastContractCheck, undefined, 'no upgrade contract check ran');
      // U04b: ✍ Sign and View open nothing in Restricted Mode, and the Approvals page has no card and no link.
      for (const command of ['bioSteward.approvals.sign', 'bioSteward.approvals.viewPayload']) {
        await vscode.commands.executeCommand(command, 'd3e83e998137', 0);
      }
      assert.equal(vscode.window.terminals.length, 0, 'no terminal was opened');
      // The panels are drawn after a short debounce (the refresh commands above return at once in Restricted Mode).
      for (let i = 0; i < 100 && !/Restricted Mode/.test(api.approvals.view.html); i++) await new Promise((done) => setTimeout(done, 50));
      assert.match(api.approvals.view.html, /Restricted Mode/);
      assert.doesNotMatch(api.approvals.view.html, /href=/);
      // U05: Decisions and Drift show nothing, read nothing and open no file in Restricted Mode.
      assert.deepEqual(api.decisions.view.tree.nodes, []);
      assert.deepEqual(api.drift.tree.nodes, []);
      assert.equal(api.project.state.decisions, undefined, 'the decisions log was not looked for');
      assert.equal(await api.decisions.open(api.project.root), undefined);
      assert.equal(vscode.window.visibleTextEditors.some((e) => e.document.uri.scheme === 'file'), false, 'no file was opened');
      assert.equal(api.project.state.run, 'none');
      assert.equal(api.project.state.full, undefined);
      assert.equal(api.explain.html, undefined);
      assert.equal(existsSync(calls), false, 'the configured CLI was never invoked');
      execFileSync(spy, ['--version']);
      assert.equal(readFileSync(calls, 'utf8'), '--version\n', 'the spy records invocations');
      unlinkSync(calls);
    });
  });
}

// Reject TCP and UDP connections from the extension host. Named pipes and Unix sockets carry VS Code IPC.
// Every rejected attempt is attributed by its stack: this extension's bundle (`extensionDist`), this test's own
// probe, or anything else in the shared extension host (VS Code's built-in components, which also try to sign in).
// The requirement is that the extension makes none (TOK-1, AC-X.2); the others are logged, not blamed on it.
function blockNetwork(extensionDist: string) {
  const connect = Socket.prototype.connect;
  const datagram = { connect: DatagramSocket.prototype.connect, send: DatagramSocket.prototype.send };
  let fromExtension = 0;
  let probes = 0;
  let others = 0;
  const deny = () => {
    // Only the callers count: drop the frames of `deny` and of the patched `connect` below, which live in this file.
    const frames = (new Error().stack ?? '').split('\n').slice(1);
    const patched = frames.findIndex((frame) => /Socket\.connect \(.*hardening\.test/.test(frame) ||
      /Socket\.(connect|send) \(.*hardening\.test/.test(frame));
    const callers = (patched >= 0 ? frames.slice(patched + 1) : frames.slice(1)).join('\n');
    if (callers.includes(extensionDist)) fromExtension++;
    else if (callers.includes('hardening.test')) probes++;
    else others++;
    throw new Error('Test network disabled');
  };
  Socket.prototype.connect = function (this: Socket, ...args: unknown[]) {
    // net.connect passes normalized arguments as one array. Direct Socket.connect calls pass them separately.
    const first: unknown = Array.isArray(args[0]) ? args[0][0] : args[0];
    if ((typeof first === 'string' && Number.isNaN(Number(first))) ||
        (typeof first === 'object' && first !== null && 'path' in first && typeof first.path === 'string')) {
      return Reflect.apply(connect, this, args);
    }
    return deny();
  };
  Object.assign(DatagramSocket.prototype, { connect: deny, send: deny });
  return {
    fromExtension: () => fromExtension,
    probes: () => probes,
    others: () => others,
    restore() {
      Socket.prototype.connect = connect;
      Object.assign(DatagramSocket.prototype, datagram);
    },
  };
}

if (example?.startsWith('offline-')) {
  describe('Extension host with networking blocked (T09)', () => {
    it('activates, checks the example and explains a rule without TCP or UDP access', async function () {
      this.timeout(60000);
      const ext = extension();
      assert.equal(ext.isActive, false, 'the guard must be in place before activation');
      const root = vscode.workspace.workspaceFolders![0].uri.fsPath;
      const name = example.slice('offline-'.length);
      const fixture = JSON.parse(readFileSync(join(__dirname, '../../../test/fixtures/reports', name + '.json'), 'utf8')) as Report;
      const guard = blockNetwork(join(ext.extensionPath, 'dist'));
      try {
        const probe = new Socket();
        try {
          assert.throws(() => probe.connect(80, '127.0.0.1'), /Test network disabled/);
        } finally {
          probe.destroy();
        }
        assert.equal(guard.probes(), 1, 'the guard rejects a connection');

        renameSync(join(root, 'fixture.toml'), join(root, 'steward.toml'));
        const start = performance.now();
        const api = await ext.activate();
        await vscode.commands.executeCommand('bioSteward.showOverview');
        const sidebarMs = performance.now() - start;
        assert.ok(api.statusBar.view, 'the sidebar and status bar have an initial state');
        const deadline = performance.now() + 15000;
        while (api.project.state.cli.kind === 'detecting' && performance.now() < deadline) {
          await new Promise((done) => setTimeout(done, 25));
        }
        const cli = api.project.state.cli;
        assert.equal(cli.kind === 'ready' && cli.version, ext.packageJSON.bioSteward.testedWithCli);
        const checkStart = performance.now();
        await vscode.commands.executeCommand('bioSteward.runCheck');
        const checkMs = performance.now() - checkStart;
        assert.equal(api.project.state.run, 'completed');
        const full = api.project.state.full;
        assert.ok(full);
        const gates = (report: Report) => report.verdict.gates.map(({ name, evaluated, eligible, blocking, waived }) =>
          ({ name, evaluated, eligible, blocking, waived }));
        assert.deepEqual(full.report.verdict.summary, fixture.verdict.summary);
        assert.deepEqual(gates(full.report), gates(fixture));
        assert.equal(full.report.verdict.coverage.statement, fixture.verdict.coverage.statement);
        assert.ok(api.overview.tree.getChildren().length);
        const groups = api.results.tree.getChildren().map((node) =>
          api.results.tree.getTreeItem(node).accessibilityInformation?.label);
        const { counts } = full.report.verdict.summary;
        assert.deepEqual(groups, [
          `FAIL, ${counts.FAIL}`, `INCOMPLETE, ${counts.INCOMPLETE}`, `UNKNOWN, ${counts.UNKNOWN}`,
          `PASS, ${counts.PASS}`, `NOT APPLICABLE, ${counts.NOT_APPLICABLE}`,
        ]);
        const gate = api.overview.tree.nodes.find((node) => node.id === 'full/gate:default');
        assert.ok(gate);
        assert.match(api.overview.tree.getTreeItem(gate).accessibilityInformation?.label ?? '',
          /^Gate default, (?:NOT )?ELIGIBLE, \d+ blocking of \d+ required$/);
        assert.match(api.statusBar.view?.accessibility ?? '', /gate default (?:NOT )?ELIGIBLE, .*fresh/);
        await vscode.commands.executeCommand('bioSteward.explainRule', 'R-60');
        assert.match(api.explain.html ?? '', /Copy CLI command/);
        const calls = process.env.BIO_STEWARD_TEST_CLI_CALLS;
        assert.ok(calls);
        assert.equal(existsSync(calls), false, 'the workspace-configured executable was ignored');
        assert.equal(guard.fromExtension(), 0, 'the extension attempted no TCP or UDP connection');
        assert.equal(guard.probes(), 1, 'only the deliberate probe came from the test');
        console.log(`    ${name}: network attempts rejected: extension ${guard.fromExtension()}, test probe ${guard.probes()}, VS Code built-ins ${guard.others()}`);
        console.log(`    ${name}: activation + Overview focus ${sidebarMs.toFixed(1)} ms; Run Check ${checkMs.toFixed(1)} ms (steward ${cli.kind === 'ready' ? cli.version : '?'})`);
        assert.ok(sidebarMs <= 300, `activation + Overview focus took ${sidebarMs.toFixed(1)} ms (PERF-2)`);
      } finally {
        guard.restore();
      }
    });
  });
}
