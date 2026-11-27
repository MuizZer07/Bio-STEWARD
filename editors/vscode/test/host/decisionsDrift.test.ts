// Host suite for U05 (0.2.0 P6 Decisions and P7 Drift, both reduced) on the U01 cockpit workspaces: `cockpit`
// (geo-cockpit) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit in one window). Decisions is compared
// with the file on disk; Drift with what the pinned CLI prints in the same folder. Nothing here changes the folder.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { DEFAULT_DECISIONS } from '../../src/model/decisions';
import { MILESTONES_FILE } from '../../src/model/drift';
import { daysText, parseTimeline, type TimelineDocument } from '../../src/model/timeline';
import { orderProjects } from '../../src/model/today';
import type { ViewNode } from '../../src/model/views';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const cli = () => vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
function timeline(root: string): TimelineDocument {
  const stdout = execFileSync(cli(), ['timeline', '--repo', root, '--json'], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseTimeline(stdout);
  assert.ok(parsed, 'the CLI\'s timeline is readable');
  return parsed;
}
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
const sha = (path: string) => createHash('sha256').update(readFileSync(path)).digest('hex');

describe('Decisions and Drift (U05)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit' && example !== 'multi-cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready' && p.state.decisions?.kind === 'ready'
      && p.state.audit?.kind === 'ready' && p.state.timeline !== undefined && p.state.timeline.kind !== 'loading') ?? false,
    'CLI detection, the decisions log, audit progress and the timeline in every project', 60000);
    await vscode.commands.executeCommand('bioSteward.decisions.refresh');
    await vscode.commands.executeCommand('bioSteward.drift.refresh');
  });

  describe('one project (geo-cockpit)', () => {
    before(function () {
      if (example !== 'cockpit') this.skip();
    });
    const root = () => vscode.workspace.workspaceFolders![0].uri.fsPath;

    it('Decisions names the default log of steward.toml, labelled reduced, and lists none of its entries', () => {
      assert.ok(api);
      const nodes = api.decisions.view.tree.nodes;
      assert.deepEqual(nodes.map((n) => [n.kind, n.label, n.description]), [
        ['decisions-note', 'Reduced form', 'Open DECISIONS.md only'],
        ['decisions-log', DEFAULT_DECISIONS, 'the CLI\'s default development/DECISIONS.md'],
      ]);
      assert.equal(nodes[1].path, join(root(), DEFAULT_DECISIONS));
      console.log(`    decisions: ${nodes.map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('Open DECISIONS.md opens the log in an editor as it is, and writes nothing', async function () {
      this.timeout(30000);
      assert.ok(api);
      const file = join(root(), DEFAULT_DECISIONS);
      const before = sha(file);
      await vscode.commands.executeCommand('bioSteward.decisions.open');
      const editor = vscode.window.activeTextEditor;
      assert.equal(editor?.document.uri.fsPath, file);
      assert.equal(editor?.document.isDirty, false);
      assert.equal(editor?.document.getText(), readFileSync(file, 'utf8'), 'the log, unchanged');
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
      // The row's own click opens the same file.
      const row = api.decisions.view.tree.nodes[1];
      const item = api.decisions.view.tree.getTreeItem(row);
      // The row's command checks the log again when it is clicked (U09).
      assert.equal(item.command?.command, 'bioSteward.decisions.open');
      await vscode.commands.executeCommand(item.command.command, ...(item.command.arguments ?? []));
      assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, file);
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
      assert.equal(sha(file), before, 'the decisions log is not changed');
    });

    it('Drift shows each milestone of steward timeline --json with the CLI\'s state, in its order (parity)', () => {
      assert.ok(api);
      const expected = timeline(root()).milestones;
      const nodes = api.drift.tree.nodes;
      assert.deepEqual([nodes[0].label, nodes[0].description], ['Reduced form', 'timeline states only']);
      const rows = nodes.slice(1);
      assert.deepEqual(rows.map((n) => n.label), expected.map((m) => `${m.id}: ${m.title}`));
      // days_left moves with the clock; the state words and the days the extension shows come from the same output.
      const shown = api.projects[0].state.timeline;
      assert.equal(shown?.kind, 'ready');
      assert.deepEqual(shown?.kind === 'ready' && shown.rows.map((m) => m.state), expected.map((m) => m.state));
      if (shown?.kind === 'ready') {
        rows.forEach((n, index) => assert.equal(n.description, `${shown.rows[index].state} · ${daysText(shown.rows[index].days_left)}`));
      }
      for (const row of rows) assert.equal(row.path, join(root(), MILESTONES_FILE));
      console.log(`    drift: ${rows.map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('the panels run no command of their own: their refresh reads files or the timeline only', async function () {
      this.timeout(30000);
      assert.ok(api);
      const terminals = vscode.window.terminals.length;
      await vscode.commands.executeCommand('bioSteward.decisions.refresh');
      await vscode.commands.executeCommand('bioSteward.drift.refresh');
      assert.equal(vscode.window.terminals.length, terminals);
      assert.equal(api.decisions.view.tree.nodes.length, 2);
    });
  });

  describe('several projects (geo, geo-cockpit-peer, geo-cockpit)', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('Decisions and Drift show one block per project, in the Today order, never mixed (AC-multi)', async function () {
      this.timeout(60000);
      assert.ok(api);
      const order = orderProjects(api.projects, (p) => p.state.audit);
      for (const tree of [api.decisions.view.tree, api.drift.tree]) {
        const blocks = tree.nodes.slice(1);
        assert.deepEqual(blocks.map((n) => n.label), order.map((p) => p.name));
        for (const block of blocks) {
          assert.equal(block.root, order.find((p) => p.name === block.label)?.root);
          for (const node of walk(block).slice(1)) {
            assert.ok(node.id.startsWith(`${block.id}/`), node.id);
            if (node.path) assert.ok(node.path.startsWith(`${block.root}/`), node.id);
          }
        }
      }
      for (const project of order) {
        const block: ViewNode | undefined = api.drift.tree.nodes.find((n) => n.label === project.name);
        const expected = timeline(project.root).milestones;
        const rows: ViewNode[] = (block?.children ?? []).filter((n) => n.kind === 'drift-milestone');
        assert.deepEqual(rows.map((n) => n.label), expected.map((m) => `${m.id}: ${m.title}`), project.name);
      }
      // Open DECISIONS.md with a project's root opens that project's log, not another's.
      const cockpit = order.find((p) => p.name === 'geo-cockpit');
      assert.ok(cockpit);
      const opened = await api.decisions.open(cockpit.root);
      assert.equal(opened?.fsPath, join(cockpit.root, DEFAULT_DECISIONS));
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
      console.log(`    order: ${order.map((p) => `${p.name} (${api?.drift.tree.nodes.find((n) => n.label === p.name)?.description ?? ''})`).join(' > ')}`);
    });
  });
});
