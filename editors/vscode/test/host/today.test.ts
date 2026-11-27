// Host suite for U02 (0.2.0 P1 Today and P2 "Where am I?", reduced forms) on the U01 cockpit workspaces:
// `cockpit` (geo-cockpit with its peer beside it) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit as
// three folders of one window). Each compares the panels with what the pinned CLI prints in the same folder.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { orderProjects, parseAuditProgress, type AuditProgress } from '../../src/model/today';
import type { ViewNode } from '../../src/model/views';
import type { Project } from '../../src/project';

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
function audit(root: string): AuditProgress {
  const stdout = execFileSync(cli(), ['audit', 'progress', '--repo', root, '--json'], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseAuditProgress(stdout);
  assert.ok(parsed, 'the CLI\'s audit progress is readable');
  return parsed;
}
const byId = (nodes: readonly ViewNode[], suffix: string) => nodes.find((n) => n.id.endsWith(suffix));
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];

describe('Today and Where am I? (U02, reduced)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit' && example !== 'multi-cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready' && p.state.audit?.kind === 'ready') ?? false,
      'CLI detection and audit progress in every project', 60000);
    await vscode.commands.executeCommand('bioSteward.today.refresh');
  });

  describe('one project (geo-cockpit)', () => {
    before(function () {
      if (example !== 'cockpit') this.skip();
    });
    const root = () => vscode.workspace.workspaceFolders![0].uri.fsPath;

    it('Today shows exactly the pending lists of `steward audit progress --json`, each labelled with its source', () => {
      assert.ok(api);
      const expected = audit(root()).pending;
      const nodes = api.today.tree.nodes;
      assert.equal(nodes[0].label, 'Reduced form');
      const labels = (key: string) => {
        const section = byId(nodes, `/${key}`);
        assert.match(section?.description ?? '', /steward audit progress$/, key);
        return (section?.children ?? []).map((c) => c.label);
      };
      assert.deepEqual(labels('signatures'), expected.signatures_waiting);
      assert.deepEqual(labels('exchange'), expected.exchange_open ?? []);
      assert.deepEqual(labels('own'), expected.own_open ?? []);
      assert.deepEqual(labels('sprints'), expected.sprints.map((s) => s.sprint));
      assert.deepEqual(labels('milestones'), expected.milestones.map((m) => m.id));
      assert.match(byId(nodes, '/milestone')?.description ?? '', / · steward timeline$/);
      assert.match(byId(nodes, '/resume')?.description ?? '', /the session handoff$/);
      console.log(`    today: ${nodes.slice(1).map((n) => `${n.label}${n.description ? ` [${n.description}]` : ''}`).join(' | ')}`);
    });

    it('Where am I? opens a read-only page whose parts name their sources; the handoff is quoted as written', async function () {
      this.timeout(60000);
      assert.ok(api);
      const handoff = join(root(), 'development', 'HANDOFF.md');
      assert.equal(existsSync(handoff), false);
      const text = '# Session handoff\n\nNext: run the model comparison `$(bug)` <b>not HTML</b>\n';
      try {
        writeFileSync(handoff, text);
        await vscode.commands.executeCommand('bioSteward.whereAmI');
        const document = api.whereAmI.document;
        assert.ok(document);
        assert.equal(document.uri.scheme, 'bio-steward-where');
        assert.equal(document.languageId, 'markdown');
        const page = document.getText();
        assert.ok(page.startsWith('# Where am I? · geo-cockpit\n\nReduced form (CLI 0.20.6)'));
        assert.ok(page.includes('\n## You left off · from the session handoff (development/HANDOFF.md)\n\n> # Session handoff\n>\n' +
          '> Next: run the model comparison `$(bug)` <b>not HTML</b>\n'));
        for (const item of audit(root()).pending.signatures_waiting) assert.ok(page.includes(`  - ${item}\n`), item);
        assert.ok(page.includes('\n## Next target · from steward timeline\n'));
        assert.equal(readFileSync(handoff, 'utf8'), text, 'nothing written');

        await vscode.commands.executeCommand('bioSteward.whereAmI.copyBrief', document.uri);
        const brief = api.clipboard.text ?? '';
        assert.ok(brief.startsWith('# Bio-STEWARD agent brief · geo-cockpit\n'));
        assert.ok(brief.includes('> Next: run the model comparison'));
        assert.ok(brief.includes('## Waiting on you · from steward audit progress'));
      } finally {
        rmSync(handoff, { force: true });
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      }
    });

    it('is shown once on reopening after more than N days; not sooner, not on a first open, not when switched off', async function () {
      this.timeout(60000);
      assert.ok(api);
      const { lastSeen, check } = api.reopen;
      const project = api.project;
      const day = 86_400_000;
      const config = vscode.workspace.getConfiguration('bioSteward.whereAmI');
      try {
        await lastSeen.set(project.root, new Date(Date.now() - 10 * day).toISOString());
        assert.equal(await check(), project);
        assert.ok(api.whereAmI.document?.getText().includes('Last open in VS Code: '));
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');

        await lastSeen.set(project.root, new Date(Date.now() - 2 * day).toISOString());
        assert.equal(await check(), undefined, '2 days is not more than 3');
        await lastSeen.set(project.root, undefined);
        assert.equal(await check(), undefined, 'a first open is not a reopening');

        await lastSeen.set(project.root, new Date(Date.now() - 10 * day).toISOString());
        await config.update('showOnReopen', false, vscode.ConfigurationTarget.Global);
        assert.equal(await check(), undefined, 'the off switch');
        await config.update('showOnReopen', undefined, vscode.ConfigurationTarget.Global);
        await config.update('reopenAfterDays', 30, vscode.ConfigurationTarget.Global);
        assert.equal(await check(), undefined, '10 days is not more than 30');
      } finally {
        await config.update('showOnReopen', undefined, vscode.ConfigurationTarget.Global);
        await config.update('reopenAfterDays', undefined, vscode.ConfigurationTarget.Global);
        await lastSeen.touch();
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      }
    });

    it('Resume acts on the project a Today row names', async () => {
      assert.ok(api);
      const handoff = join(root(), 'development', 'HANDOFF.md');
      try {
        writeFileSync(handoff, 'resume me\n');
        await vscode.commands.executeCommand('bioSteward.resume', root());
        assert.equal(api.resume.document?.getText(), 'resume me\n');
      } finally {
        rmSync(handoff, { force: true });
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      }
    });
  });

  describe('three projects in one window', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('one block per project, ordered by the audit counts the CLI reports, with no row of one inside another', () => {
      assert.ok(api);
      assert.deepEqual(api.projects.map((p) => p.name), ['geo', 'geo-cockpit-peer', 'geo-cockpit']);
      const audits = new Map(api.projects.map((p) => [p.root, audit(p.root)]));
      const expected = orderProjects(api.projects, (p) => ({ kind: 'ready', audit: audits.get(p.root)! })).map((p) => p.name);
      const nodes = api.today.tree.nodes;
      assert.deepEqual(nodes.map((n) => n.label), ['Reduced form', ...expected]);
      assert.equal(expected.at(-1), 'geo', 'nothing pending comes last');
      assert.notDeepEqual(expected, api.projects.map((p) => p.name), 'the order is not the workspace order');
      for (const block of nodes.slice(1)) {
        const project: Project | undefined = api.projects.find((p) => p.name === block.label);
        assert.ok(project);
        for (const node of walk(block)) assert.ok(node.id.startsWith(block.id), node.id);
        const signatures = byId(block.children ?? [], '/signatures')?.children?.map((c) => c.label);
        assert.deepEqual(signatures, audits.get(project.root)!.pending.signatures_waiting, project.name);
      }
      console.log(`    order: ${expected.join(' > ')}`);
    });

    it('Where am I? with a project named shows that project\'s page', async function () {
      this.timeout(60000);
      assert.ok(api);
      const peer = api.projects[1];
      await vscode.commands.executeCommand('bioSteward.whereAmI', peer.root);
      assert.ok(api.whereAmI.document?.getText().startsWith('# Where am I? · geo-cockpit-peer\n'));
      for (const item of audit(peer.root).pending.own_open ?? []) assert.ok(api.whereAmI.document?.getText().includes(`  - ${item}\n`));
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });
  });
});
