// Host suite for U03 (0.2.0 P3 Tasks and P4 Tokens) on the U01 cockpit workspaces: `cockpit`
// (geo-cockpit) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit in one window). The panels are compared
// with the task files the fixture script wrote (U01 manifest) and with what the pinned CLI prints in the same folder.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { parseBoard, type BoardDocument } from '../../src/model/full';
import { orderProjects } from '../../src/model/today';
import { EMPTY_SENTENCES, logFolderHints, parseTokensReport, SETTING_KEYS, type TokensReport } from '../../src/model/tokens';
import { homedir } from 'node:os';
import type { ViewNode } from '../../src/model/views';
import { emptySettings, windowTarget } from '../../src/ui/tokens';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
const taskFixtures = (JSON.parse(readFileSync(join(fixtures, 'manifest.json'), 'utf8')) as {
  cockpit: { task_files: { files: { path: string; status: string | null }[] } };
}).cockpit.task_files.files;
const claudeLog = join(fixtures, 'cockpit', 'inputs', 'claude-session.jsonl');

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const cli = () => vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
function tokensReport(root: string, ...extra: string[]): TokensReport {
  const stdout = execFileSync(cli(), ['tokens', 'report', '--repo', root, '--format', 'json', ...extra], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseTokensReport(stdout);
  assert.ok(parsed, 'the CLI\'s tokens report is readable');
  return parsed;
}
// E04: the full form of Tasks reads `steward task board --format json`.
function board(root: string): BoardDocument {
  const stdout = execFileSync(cli(), ['task', 'board', '--repo', root, '--format', 'json'], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseBoard(stdout);
  assert.ok(parsed, 'the CLI\'s task board is readable');
  return parsed;
}
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
const rowsOf = (nodes: readonly ViewNode[]) => nodes.flatMap(walk).filter((n) => n.kind === 'tokens-task');

describe('Tasks and Tokens (U03)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit' && example !== 'multi-cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready' && p.state.tasks?.kind === 'ready'
      && p.state.audit?.kind === 'ready') ?? false, 'CLI detection, the task files and audit progress in every project', 60000);
    await vscode.commands.executeCommand('bioSteward.tasks.refresh');
  });

  describe('one project (geo-cockpit)', () => {
    before(function () {
      if (example !== 'cockpit') this.skip();
    });
    const root = () => vscode.workspace.workspaceFolders![0].uri.fsPath;
    const ledger = () => join(root(), '.steward', 'task-tokens.jsonl');

    after(async () => {
      await vscode.workspace.getConfiguration().update('bioSteward.tokens.claudeLogs', undefined, vscode.ConfigurationTarget.Global);
    });

    it('Tasks lists every task of steward task board with the CLI\'s status, open first, closed after (E04, full form)', () => {
      assert.ok(api);
      const nodes = api.tasks.tree.nodes;
      assert.equal(nodes[0].label, 'Tasks');
      const expected = board(root());
      const files = nodes.flatMap(walk).filter((n) => n.kind === 'task-file');
      assert.equal(files.length, taskFixtures.length);
      assert.equal(files.length, expected.tasks.length);
      for (const task of expected.tasks) {
        const node = files.find((n) => n.path === join(root(), task.path));
        assert.ok(node, task.path);
        assert.equal(node.description, `${task.status}${task.closed ? ' · closed' : ''}${task.archived ? ' · archived' : ''}`, task.path);
      }
      const closed = nodes.find((n) => n.kind === 'task-group');
      assert.deepEqual(closed?.children?.map((n) => n.label), ['GEO-002 · GEO-002-normalise.md'], 'open first, closed after');
      console.log(`    tasks: ${files.map((n) => `${n.label}${n.description ? ` [${n.description}]` : ''}`).join(' | ')}`);
    });

    it('a Tasks row opens its file, and offers its ID line for a task window', async () => {
      assert.ok(api);
      const node = api.tasks.tree.nodes.flatMap(walk).find((n) => n.label === 'GEO-003 · GEO-003-annotate.md');
      assert.ok(node);
      const item = api.tasks.tree.getTreeItem(node);
      // The row's command checks the file again when it is clicked (U09).
      assert.equal(item.command?.command, 'bioSteward.row.open');
      const preview = await vscode.commands.executeCommand<vscode.Uri>(item.command.command, ...(item.command.arguments ?? []));
      assert.equal(preview.fsPath, node.path);
      await vscode.commands.executeCommand('bioSteward.row.openText', node);
      assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, node.path);
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
      // A path the panel did not list, or another project's root, opens nothing.
      for (const forged of [{ root: root(), path: join(root(), 'steward.toml') }, { root: '/', path: '/etc/hosts' }, 'x', undefined]) {
        await vscode.commands.executeCommand(item.command.command, forged);
        assert.notEqual(vscode.window.activeTextEditor?.document.uri.fsPath, join(root(), 'steward.toml'));
        assert.notEqual(vscode.window.activeTextEditor?.document.uri.fsPath, '/etc/hosts');
      }
      await vscode.commands.executeCommand(item.command.command, ...(item.command.arguments ?? []));
      assert.deepEqual(windowTarget(api.projects, node, undefined), { project: api.projects[0], id: 'GEO-003' });
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
    });

    it('with no agent log selected, Tokens says so in one sentence, offers each agent\'s folder, and shows the CLI\'s rows (parity)', async function () {
      this.timeout(60000);
      assert.ok(api);
      await vscode.commands.executeCommand('bioSteward.tokens.refresh');
      const project = api.projects[0];
      assert.equal(project.state.tokens?.kind, 'ready');
      assert.deepEqual(project.state.tokens?.kind === 'ready' && project.state.tokens.report, tokensReport(root()));
      const nodes = api.tokens.view.tree.nodes;
      assert.equal(nodes.find((n) => n.kind === 'tokens-setup')?.label, 'Agent log settings');
      // E04: no log and no window: one sentence, and Use this folder for every agent whose setting is empty.
      assert.equal(nodes.find((n) => n.kind === 'tokens-empty')?.label, EMPTY_SENTENCES.both);
      const hints = logFolderHints(project.root, homedir());
      assert.deepEqual(nodes.filter((n) => n.kind === 'tokens-use-folder').map((n) => [n.code, n.path]),
        [['claude', hints.claude], ['codex', hints.codex], ['gemini', hints.gemini]]);
      assert.deepEqual(rowsOf(nodes).map((n) => [n.label, n.description]), [['all activity', 'no counts · unavailable · shared, not this project\'s alone']]);
    });

    it('Use this folder writes only that agent\'s machine setting, only to the folder it names, then reads the report (E04)', async function () {
      this.timeout(60000);
      assert.ok(api);
      const key = SETTING_KEYS.gemini;
      const config = () => vscode.workspace.getConfiguration();
      const row = api.tokens.view.tree.nodes.find((n) => n.kind === 'tokens-use-folder' && n.code === 'gemini');
      assert.ok(row);
      const item = api.tokens.view.tree.getTreeItem(row);
      assert.equal(item.command?.command, 'bioSteward.row.open');  // every row opens through one command (E02)
      try {
        // A folder the panel did not name, or an unknown agent, writes nothing.
        for (const forged of [{ agent: 'gemini', path: '/etc' }, { agent: 'other', path: row.path }, 'x', undefined]) {
          assert.equal(await vscode.commands.executeCommand('bioSteward.tokens.useFolder', forged), false);
        }
        assert.equal(config().inspect(key)?.globalValue, undefined);
        const before = api.projects[0].recentRuns.length;
        await vscode.commands.executeCommand(item.command.command, ...(item.command.arguments ?? []));
        assert.deepEqual(config().inspect(key)?.globalValue, [row.path]);
        assert.equal(config().inspect(key)?.workspaceValue, undefined, 'never a workspace setting');
        assert.deepEqual(emptySettings(), ['claude', 'codex']);
        assert.ok(api.projects[0].recentRuns.slice(before).some((r) => r.args.startsWith('tokens report')), 'the report is read after the write');
        assert.equal(api.tokens.view.tree.nodes.some((n) => n.kind === 'tokens-use-folder' && n.code === 'gemini'), false);
        // Once set, it is not offered again, and a second write is refused.
        assert.equal(await vscode.commands.executeCommand('bioSteward.tokens.useFolder', { agent: 'gemini', path: row.path }), false);
      } finally {
        await config().update(key, undefined, vscode.ConfigurationTarget.Global);
      }
    });

    it('with a log selected in the user settings, shows each task window and model as the CLI counted them (parity)', async function () {
      this.timeout(60000);
      assert.ok(api);
      await vscode.workspace.getConfiguration().update('bioSteward.tokens.claudeLogs', [claudeLog], vscode.ConfigurationTarget.Global);
      await vscode.commands.executeCommand('bioSteward.tokens.refresh');
      const expected = tokensReport(root(), '--claude', claudeLog);
      const state = api.projects[0].state.tokens;
      assert.deepEqual(state?.kind === 'ready' && state.report, expected);
      assert.deepEqual(api.tokens.view.logs?.files.claude, [realpathSync(claudeLog)]);
      const nodes = api.tokens.view.tree.nodes;
      assert.equal(nodes.some((n) => n.kind === 'tokens-setup'), false);
      const rows = rowsOf(nodes);
      assert.deepEqual(rows.map((n) => n.label), expected.tasks.map((t) => t.task));
      assert.equal(rows[0].description, `${expected.tasks[0].tokens?.toLocaleString('en-US')} tokens · ${expected.tasks[0].status}` +
        (expected.tasks[0].task === 'all activity' ? ' · shared, not this project\'s alone' : ''));
      assert.deepEqual(rows[0].children?.filter((n) => n.kind === 'tokens-model').map((n) => n.label),
        expected.tasks[0].models.map((m) => `${m.agent} / ${m.model}`));
      console.log(`    tokens: ${nodes.slice(1).map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('Start and Done task window run `steward task start / done` only after confirmation, with the exact command', async function () {
      this.timeout(60000);
      assert.ok(api);
      const shown: (readonly string[])[] = [];
      const decline = async (_cli: string, args: readonly string[]) => {
        shown.push(args);
        return false;
      };
      const accept = async (_cli: string, args: readonly string[]) => {
        shown.push(args);
        return true;
      };
      assert.equal(existsSync(ledger()), false);
      const declined = await api.tokens.window('start', root(), 'GEO-001', decline);
      assert.equal(declined?.kind, 'unconfirmed');
      assert.equal(existsSync(ledger()), false, 'a declined confirmation writes nothing');

      const canonical = realpathSync(root());
      const started = await api.tokens.window('start', root(), 'GEO-001', accept);
      assert.equal(started?.kind === 'completed' && started.exitCode, 0);
      assert.equal(started?.kind === 'completed' && started.stdout.trim(), 'GEO-001 token window opened');
      assert.ok(existsSync(ledger()), 'the CLI recorded the window');
      const again = await api.tokens.window('start', root(), 'GEO-001', accept);
      assert.equal(again?.kind === 'completed' && again.exitCode, 65, 'the CLI refuses a second open window');
      assert.match(again?.kind === 'completed' ? again.stderr : '', /already has an open window/);
      assert.deepEqual(rowsOf(api.tokens.view.tree.nodes).map((n) => n.label), ['GEO-001'], 'the panel shows the window');

      const done = await api.tokens.window('done', root(), 'GEO-001', accept);
      assert.equal(done?.kind === 'completed' && done.stdout.trim(), 'GEO-001 token window closed');
      const report = tokensReport(root(), '--claude', claudeLog);
      const state = api.projects[0].state.tokens;
      assert.deepEqual(state?.kind === 'ready' && state.report, report);
      assert.deepEqual(shown, [
        ['task', 'start', '--repo', canonical, 'GEO-001'],
        ['task', 'start', '--repo', canonical, 'GEO-001'],
        ['task', 'start', '--repo', canonical, 'GEO-001'],
        ['task', 'done', '--repo', canonical, 'GEO-001'],
      ]);
      assert.ok(shown.every((args) => !args.includes('--yes')));
      const row = api.tokens.view.tree.nodes.find((n) => n.kind === 'tokens-task');
      assert.ok(row);
      assert.deepEqual(windowTarget(api.projects, row, undefined), { project: api.projects[0], id: 'GEO-001' });
    });
  });

  describe('several projects (geo, geo-cockpit-peer, geo-cockpit)', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('Tasks and Tokens show one block per project, in the Today order, with no row of one inside another', async function () {
      this.timeout(60000);
      assert.ok(api);
      await vscode.commands.executeCommand('bioSteward.tokens.refresh');
      const order = orderProjects(api.projects, (p) => p.state.audit, (p) => p.state.next).map((p) => p.name);
      for (const tree of [api.tasks.tree, api.tokens.view.tree]) {
        const blocks = tree.nodes.slice(1);
        assert.deepEqual(blocks.map((n) => n.label), order);
        for (const block of blocks) for (const node of walk(block).slice(1)) assert.ok(node.id.startsWith(`${block.id}/`), node.id);
      }
      const cockpit = api.tasks.tree.nodes.find((n) => n.label === 'geo-cockpit');
      const files = (cockpit ? walk(cockpit) : []).filter((n) => n.kind === 'task-file');
      assert.equal(files.length, taskFixtures.length);
      console.log(`    order: ${order.join(' > ')}`);
    });
  });
});
