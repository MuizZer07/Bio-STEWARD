// Host suite for U02 (0.2.0 P1 Today and P2 "Where am I?") on the U01 cockpit workspaces:
// `cockpit` (geo-cockpit with its peer beside it) and `multi-cockpit` (geo, geo-cockpit-peer and geo-cockpit as
// three folders of one window). Each compares the panels with what the pinned CLI prints in the same folder.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { parseNext, type NextDocument } from '../../src/model/full';
import { entriesNewestFirst, orderProjects, parseAuditProgress, type AuditProgress } from '../../src/model/today';
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
// E04: the full form reads `steward next --format json` (CLI 0.21 and later); the pinned CLI offers it.
function next(root: string): NextDocument {
  const stdout = execFileSync(cli(), ['next', '--repo', root, '--format', 'json'], { encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
  const parsed = parseNext(stdout);
  assert.ok(parsed, 'the CLI\'s next document is readable');
  return parsed;
}
const byId = (nodes: readonly ViewNode[], suffix: string) => nodes.find((n) => n.id.endsWith(suffix));
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];

describe('Today and Where am I? (U02)', () => {
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

    it('Today shows what `steward next` reports, newest first, each row with its next step (E04, full form)', () => {
      assert.ok(api);
      const expected = next(root());
      const nodes = api.today.tree.nodes;
      assert.equal(nodes[0].label, 'Sources');
      assert.equal(nodes[0].description, 'steward next');
      const section = (key: string) => (byId(nodes, `/${key}`)?.children ?? []);
      assert.deepEqual(section('human').map((c) => c.label), entriesNewestFirst(expected.waiting_on_human).map((e) => e.title));
      assert.deepEqual(section('agents').map((c) => c.label), entriesNewestFirst(expected.waiting_on_agents).map((e) => e.title));
      for (const [i, entry] of entriesNewestFirst(expected.waiting_on_human).entries()) {
        assert.ok(section('human')[i].tooltip?.includes(`Next step: ${entry.command}`), entry.id);
      }
      assert.equal(byId(nodes, '/tidy')?.label, `Needs tidying (${expected.tidy.total})`);
      assert.match(byId(nodes, '/milestone')?.description ?? '', new RegExp(`^${expected.milestone?.id ?? 'none'}`));
      assert.equal(byId(nodes, '/resume')?.command, 'resume');
      // audit progress is still read: it orders projects whose CLI has no steward next.
      assert.ok(audit(root()).pending);
      console.log(`    today: ${nodes.slice(1).map((n) => `${n.label}${n.description ? ` [${n.description}]` : ''}`).join(' | ')}`);
    });

    it('Where am I? opens a read-only page whose parts name their sources; the handoff is quoted as written', async function () {
      this.timeout(60000);
      assert.ok(api);
      const handoff = join(root(), 'development', 'HANDOFF.md');
      // The fixture workspace has a handoff of its own (E04: steward next resumes from it); it is put back after.
      const original = existsSync(handoff) ? readFileSync(handoff, 'utf8') : undefined;
      const text = '# Session handoff\n\nNext: run the model comparison `$(bug)` <b>not HTML</b>\n';
      try {
        writeFileSync(handoff, text);
        await vscode.commands.executeCommand('bioSteward.whereAmI');
        const document = api.whereAmI.document;
        assert.ok(document);
        assert.equal(document.uri.scheme, 'bio-steward-where');
        assert.equal(document.languageId, 'markdown');
        const page = document.getText();
        assert.ok(page.startsWith('# Where am I? · geo-cockpit\n\nFrom steward next'));
        assert.ok(page.includes('\n## You left off · from the session handoff (development/HANDOFF.md)\n\n> # Session handoff\n>\n' +
          '> Next: run the model comparison `$(bug)` <b>not HTML</b>\n'));
        for (const entry of next(root()).waiting_on_human) assert.ok(page.includes(`\`${entry.command}\``), entry.id);
        assert.ok(page.includes('\n## Next target · from steward timeline\n'));
        assert.equal(readFileSync(handoff, 'utf8'), text, 'nothing written');

        await vscode.commands.executeCommand('bioSteward.whereAmI.copyBrief', document.uri);
        const brief = api.clipboard.text ?? '';
        assert.ok(brief.startsWith('# Bio-STEWARD agent brief · geo-cockpit\n'));
        assert.ok(brief.includes('> Next: run the model comparison'));
        assert.ok(brief.includes('## Waiting on you · from steward next'));
      } finally {
        if (original === undefined) rmSync(handoff, { force: true });
        else writeFileSync(handoff, original);
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
      const original = existsSync(handoff) ? readFileSync(handoff, 'utf8') : undefined;
      try {
        writeFileSync(handoff, 'resume me\n');
        await vscode.commands.executeCommand('bioSteward.resume', root());
        assert.equal(api.resume.document?.getText(), 'resume me\n');
      } finally {
        if (original === undefined) rmSync(handoff, { force: true });
        else writeFileSync(handoff, original);
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      }
    });
  });

  describe('three projects in one window', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('one block per project, ordered by what steward next reports waiting, with no row of one inside another', () => {
      assert.ok(api);
      assert.deepEqual(api.projects.map((p) => p.name), ['geo', 'geo-cockpit-peer', 'geo-cockpit']);
      const nexts = new Map(api.projects.map((p) => [p.root, next(p.root)]));
      const expected = orderProjects(api.projects, () => undefined, (p) => ({ kind: 'ready', doc: nexts.get(p.root)! })).map((p) => p.name);
      const nodes = api.today.tree.nodes;
      assert.deepEqual(nodes.map((n) => n.label), ['Sources', ...expected]);
      assert.equal(expected.at(-1), 'geo', 'nothing pending comes last');
      assert.notDeepEqual(expected, api.projects.map((p) => p.name), 'the order is not the workspace order');
      for (const block of nodes.slice(1)) {
        const project: Project | undefined = api.projects.find((p) => p.name === block.label);
        assert.ok(project);
        for (const node of walk(block)) assert.ok(node.id.startsWith(block.id), node.id);
        const human = byId(block.children ?? [], '/human')?.children?.map((c) => c.label);
        assert.deepEqual(human, entriesNewestFirst(nexts.get(project.root)!.waiting_on_human).map((e) => e.title), project.name);
      }
      console.log(`    order: ${expected.join(' > ')}`);
    });

    it('Where am I? with a project named shows that project\'s page', async function () {
      this.timeout(60000);
      assert.ok(api);
      const peer = api.projects[1];
      await vscode.commands.executeCommand('bioSteward.whereAmI', peer.root);
      assert.ok(api.whereAmI.document?.getText().startsWith('# Where am I? · geo-cockpit-peer\n'));
      for (const entry of next(peer.root).waiting_on_human) assert.ok(api.whereAmI.document?.getText().includes(`\`${entry.command}\``), entry.id);
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });
  });
});
