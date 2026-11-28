// Host suite for U05 (0.2.0 P6 Decisions and P7 Milestones and Drift) on the U01 cockpit workspaces: `cockpit`
// (geo-cockpit) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit in one window). Decisions is compared
// with the file on disk; Drift with what the pinned CLI prints in the same folder. Nothing here changes the folder.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { decisionsNewestFirst, DEFAULT_DECISIONS } from '../../src/model/decisions';
import { parseDecisions, type DecisionsDocument } from '../../src/model/full';
import { MILESTONES_FILE, milestonesLatestFirst } from '../../src/model/drift';
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
// E04: the full form of Decisions reads `steward decisions --format json`.
function decisions(root: string): DecisionsDocument {
  const stdout = execFileSync(cli(), ['decisions', '--repo', root, '--format', 'json'], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseDecisions(stdout);
  assert.ok(parsed, 'the CLI\'s decisions document is readable');
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

    it('Decisions names the default log of steward.toml, then the open questions and entries of steward decisions (E04)', () => {
      assert.ok(api);
      const nodes = api.decisions.view.tree.nodes;
      const doc = decisions(root());
      assert.deepEqual(nodes.map((n) => [n.kind, n.label, n.description]), [
        ['decisions-note', 'Decisions log', 'named by steward.toml · steward decisions'],
        ['decisions-log', DEFAULT_DECISIONS, 'the CLI\'s default development/DECISIONS.md'],
        ['decisions-group', `Open decisions (${doc.open_decisions.length})`, 'steward decisions'],
        ['decisions-group', `Decisions (${doc.entries.length})`, 'newest first'],
      ]);
      assert.deepEqual(nodes[2].children?.map((n) => n.label), doc.open_decisions.map((d) => d.question));
      assert.deepEqual(nodes[3].children?.map((n) => n.label), decisionsNewestFirst(doc.entries).map((e) => `${e.date}: ${e.title}`));
      assert.equal(nodes[1].path, join(root(), DEFAULT_DECISIONS));
      console.log(`    decisions: ${nodes.map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('Open DECISIONS.md previews the log and Open as Text opens its source', async function () {
      this.timeout(30000);
      assert.ok(api);
      const file = join(root(), DEFAULT_DECISIONS);
      const before = sha(file);
      const opened = await vscode.commands.executeCommand<vscode.Uri>('bioSteward.decisions.open');
      assert.equal(opened.fsPath, file);
      const row = api.decisions.view.tree.nodes[1];
      const item = api.decisions.view.tree.getTreeItem(row);
      assert.equal(item.command?.command, 'bioSteward.row.open');
      const clicked = await vscode.commands.executeCommand<vscode.Uri>(item.command.command, ...(item.command.arguments ?? []));
      assert.equal(clicked.fsPath, file);
      await vscode.commands.executeCommand('bioSteward.row.openText', row);
      const editor = vscode.window.activeTextEditor;
      assert.equal(editor?.document.uri.fsPath, file);
      assert.equal(editor?.document.isDirty, false);
      assert.equal(editor?.document.getText(), readFileSync(file, 'utf8'));
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      assert.equal(sha(file), before, 'the decisions log is not changed');
    });

    it('Drift shows each milestone of steward timeline --json with the CLI\'s state, the latest due first (parity, E01)', () => {
      assert.ok(api);
      const expected = timeline(root()).milestones;
      const nodes = api.drift.tree.nodes;
      assert.deepEqual([nodes[0].label, nodes[0].description], ['Milestones and drift', 'steward timeline · latest due first']);
      const rows = nodes.filter((n) => n.kind === 'drift-milestone');
      // E04: the drift fields follow the milestones, one group each.
      assert.deepEqual(nodes.filter((n) => n.kind === 'drift-group').map((n) => n.label.replace(/ \(\d+\)$/, '')),
        ['Moved dates', 'Scope', 'Order', 'Changes without a decision']);
      const latest = [...expected].sort((a, b) => Date.parse(b.due) - Date.parse(a.due));
      assert.deepEqual(rows.map((n) => n.label), latest.map((m) => `${m.id}: ${m.title}`));
      // days_left moves with the clock; the state words and the days the extension shows come from the same output.
      const shown = api.projects[0].state.timeline;
      assert.equal(shown?.kind, 'ready');
      assert.deepEqual(shown?.kind === 'ready' && shown.rows.map((m) => m.state), expected.map((m) => m.state));
      if (shown?.kind === 'ready') {
        const ordered = milestonesLatestFirst(shown.rows);
        rows.forEach((n, index) => assert.equal(n.description, `${ordered[index].state} · ${daysText(ordered[index].days_left)}`));
      }
      for (const row of rows) assert.equal(row.path, join(root(), MILESTONES_FILE));
      console.log(`    drift: ${rows.map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('the panels open no terminal: their refresh reads files, the timeline and steward decisions only', async function () {
      this.timeout(30000);
      assert.ok(api);
      const terminals = vscode.window.terminals.length;
      await vscode.commands.executeCommand('bioSteward.decisions.refresh');
      await vscode.commands.executeCommand('bioSteward.drift.refresh');
      assert.equal(vscode.window.terminals.length, terminals);
      assert.equal(api.decisions.view.tree.nodes.length, 4);
    });
  });

  describe('several projects (geo, geo-cockpit-peer, geo-cockpit)', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('Decisions and Drift show one block per project, in the Today order, never mixed (AC-multi)', async function () {
      this.timeout(60000);
      assert.ok(api);
      const order = orderProjects(api.projects, (p) => p.state.audit, (p) => p.state.next);
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
        const latest = [...expected].sort((x, y) => Date.parse(y.due) - Date.parse(x.due));
        assert.deepEqual(rows.map((n) => n.label), latest.map((m) => `${m.id}: ${m.title}`), project.name);
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
