// Host suite, T08: Copy for agent (S5), scoped re-check (S8) and Agent Skills (S7, AC-5.1 – AC-5.3 read for
// CLI 0.20.6), on the toy workspace from the pinned release. T12 (T11-06): no test here depends on another test or
// on file order. Each suite makes the state it needs (its own full run; the Agent Skills sequence is one test that
// restores the workspace after it), tree reads wait for the exact view update, and copies are asserted on what the
// extension copied, not on the shared system clipboard.
import { strict as assert } from 'node:assert';
import { spawnSync } from 'node:child_process';
import { appendFileSync, cpSync, existsSync, lstatSync, readdirSync, readFileSync, readlinkSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import type { ViewNode } from '../../src/model/views';

const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const env = { ...process.env, STEWARD_NO_REGISTRY: '1' };

async function until(condition: () => boolean, what: string, ms = 15000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const node = (nodes: readonly ViewNode[], id: string) => nodes.find((n) => n.id === id);

describe('Copy for agent, scoped re-check, Agent Skills (T08)', function () {
  let api: TestApi;
  let root: string;
  let cli: string;

  before(async function () {
    if (example !== 'toy') this.skip();
    const extension = vscode.extensions.getExtension<TestApi>('MuizZer07.bio-steward');
    assert.ok(extension);
    api = await extension.activate();
    root = realpathSync(vscode.workspace.workspaceFolders![0].uri.fsPath);
    cli = vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
    await until(() => api.project.state.cli.kind === 'ready', 'CLI detection');
    const { cli: state } = api.project.state;
    assert.equal(state.kind === 'ready' && state.version, '0.20.6');
    console.log('    T08 host tests use steward 0.20.6');
  });

  it('registers the T08 commands', async () => {
    const all = await vscode.commands.getCommands(true);
    for (const command of ['bioSteward.copyForAgent', 'bioSteward.runCheckForArea', 'bioSteward.runCheckForRule',
      'bioSteward.installSkills', 'bioSteward.applySkillsInstall', 'bioSteward.checkSkills', 'bioSteward.refreshSkills']) {
      assert.ok(all.includes(command), command);
    }
  });

  describe('Copy for agent (S5, TOK-2)', () => {
    for (const rule of [undefined, 'R-60'] as const) {
      it(`copies \`steward check${rule ? ` --rule ${rule}` : ''} --summary\` unchanged, with the re-check command and its size`, async function () {
        this.timeout(60000);
        const args = ['check', '--repo', root, ...(rule ? ['--rule', rule] : []), '--summary'];
        const expected = spawnSync(cli, args, { encoding: 'utf8', env });
        assert.ok(expected.status !== null && expected.status <= 3, `steward exited ${expected.status}`);
        const copies = api.clipboard.count;
        const text = await vscode.commands.executeCommand<string>('bioSteward.copyForAgent', rule && { ref: { rule } });
        // What this extension copied, not the system clipboard other programs and runs share (T11-06).
        assert.equal(api.clipboard.count, copies + 1);
        assert.equal(api.clipboard.text, text);
        const recheck = `steward check${rule ? ` --rule ${rule}` : ''} --summary`;
        assert.equal(text, `${expected.stdout}\nRe-check: ${recheck}\n` +
          `(the text above is \`${recheck}\` from steward 0.20.6, unchanged: ${Buffer.byteLength(expected.stdout)} bytes)\n`);
        console.log(`    ${recheck}: ${Buffer.byteLength(expected.stdout)} bytes`);
      });
    }
  });

  describe('scoped re-check (S8)', () => {
    let shared: Buffer;
    let sharedPath: string;

    before(async function () {
      this.timeout(60000);
      await vscode.commands.executeCommand('bioSteward.runCheck');
      assert.ok(api.project.state.full && !api.project.state.partial);
      // The reference report must exist, so the byte comparison below always runs (T11-06).
      const location = api.project.lastReportLocation;
      assert.ok(location && existsSync(location.path), `the full run wrote no report (${location?.path})`);
      sharedPath = location.path;
      shared = readFileSync(sharedPath);
    });

    for (const [command, arg, scope] of [
      ['bioSteward.runCheckForArea', 'skills', 'check skills'],
      ['bioSteward.runCheckForRule', 'R-60', 'check --rule R-60'],
    ] as const) {
      it(`${scope} is a partial run: the gate badge is kept, marked stale; the shared report is untouched`, async function () {
        this.timeout(60000);
        const full = api.project.state.full;
        assert.ok(full);
        const badge = api.statusBar.view?.badge;
        assert.equal(await vscode.commands.executeCommand(command, arg), 'completed');
        const { partial } = api.project.state;
        assert.ok(partial?.partial);
        assert.equal(partial.scope, scope);
        assert.equal(api.project.state.full?.report, full.report, 'the full verdict is kept');
        assert.equal(api.statusBar.view?.badge, badge, 'a scoped run never changes a gate badge');
        assert.match(api.statusBar.text, / · stale$/);
        const overview = node(api.overview.tree.nodes, 'partial');
        assert.ok(overview?.description?.startsWith(`${scope} · `));
        assert.ok(overview?.children?.some((n) => n.kind === 'gate' && n.description?.startsWith('– NOT EVALUATED BY THIS RUN')));
        assert.equal(api.results.tree.nodes[0].kind, 'partial');
        assert.ok(partial.report.verdict.results.some((r) => r.rule === 'R-60'));
        assert.deepEqual(readFileSync(sharedPath), shared, 'the shared report is not rewritten');
        assert.equal(api.project.lastReportLocation?.path, sharedPath);
      });
    }

    it('a rule the CLI does not have is reported, and changes nothing', async function () {
      this.timeout(60000);
      const before = api.project.state;
      assert.equal(await vscode.commands.executeCommand('bioSteward.runCheckForRule', 'R-99'), 'rejected');
      assert.equal(api.project.state.run, before.run);
      assert.equal(api.project.state.full, before.full);
      assert.equal(api.project.state.partial, before.partial);
      assert.equal(await vscode.commands.executeCommand('bioSteward.runCheckForRule', 'R-1; rm -rf'), 'not-run');
      assert.equal(await vscode.commands.executeCommand('bioSteward.runCheckForArea', '--all'), 'not-run');
    });
  });

  describe('Agent Skills (S7)', () => {
    const saved = new Map<string, string>();
    const files = ['steward.toml', 'AGENTS.md', '.gitignore'];

    before(() => {
      for (const file of files) if (existsSync(join(root, file))) saved.set(file, readFileSync(join(root, file), 'utf8'));
      assert.equal(existsSync(join(root, '.agents')), false);
      assert.equal(existsSync(join(root, '.claude')), false);
    });

    after(async function () {
      this.timeout(60000);
      rmSync(join(root, '.agents'), { recursive: true, force: true });
      rmSync(join(root, '.claude'), { recursive: true, force: true });
      for (const file of files) {
        const text = saved.get(file);
        if (text === undefined) rmSync(join(root, file), { force: true });
        else writeFileSync(join(root, file), text);
      }
      api.skillsInstall.dispose();
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });

    // `refresh()` resolves once the tree shows the newest update, even when a watcher event started a later one
    // while the folders were listed (SkillsView.update, T11-06), so the tree read here is never an older one.
    const skills = async () => {
      const renders = api.skills.renders;
      await api.skills.refresh();
      assert.ok(api.skills.renders > renders, 'the tree was drawn for this refresh');
      return api.skills.tree.nodes;
    };

    // One test for the whole sequence (T11-06): each step depends on the one before (nothing installed, install,
    // listing, a second install, drift), so they never run alone or in another order.
    it('install, list, refuse a second install and show drift, in order (AC-5.1 – AC-5.3)', async function () {
      this.timeout(240000);

      // 1. Before anything is installed: the R-60 row and no folders.
      let nodes = await skills();
      assert.equal(nodes[0].id, 'drift');
      assert.equal(node(nodes, 'no-folders')?.label, 'No skill folders');

      // 2. Install into two folders: preview equals the dry run; one copy and one link (AC-5.1).
      const options = { skills: ['.agents/skills', '.claude/skills'], kits: ['core' as const] };
      const flags = ['--skills', '.agents/skills', '--skills', '.claude/skills', '--kits', 'core'];
      const dryRun = spawnSync(cli, ['init', '--repo', root, ...flags, '--dry-run'], { encoding: 'utf8', env });
      assert.equal(dryRun.status, 0);
      assert.equal(await api.skillsInstall.preview(api.project, options), true);
      const html = api.skillsInstall.html;
      assert.ok(html);
      const escaped = dryRun.stdout.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
      assert.ok(html.includes(`<pre><span>${escaped}</span></pre>`), 'the preview is the dry run, unchanged');
      assert.match(html, /href="command:bioSteward\.applySkillsInstall"/);
      assert.match(html, /default-src 'none'/);
      // D2: the confirmation-gated exception enables exactly this one command; no scripts, no local resources.
      assert.deepEqual(api.skillsInstall.webviewOptions?.enableCommandUris, ['bioSteward.applySkillsInstall']);
      assert.equal(api.skillsInstall.webviewOptions?.enableScripts, false);
      assert.deepEqual(api.skillsInstall.webviewOptions?.localResourceRoots, []);

      let shown: readonly string[] | undefined;
      assert.equal(await api.skillsInstall.apply(async (_cli, args) => {
        shown = args;
        return true;
      }), true);
      // The runner passes the resolved, confined folders (T5).
      assert.deepEqual(shown, ['init', '--repo', root, '--skills', join(root, '.agents', 'skills'),
        '--skills', join(root, '.claude', 'skills'), '--kits', 'core']);
      assert.ok(lstatSync(join(root, '.agents', 'skills')).isDirectory());
      assert.ok(lstatSync(join(root, '.claude', 'skills')).isSymbolicLink());
      assert.equal(readlinkSync(join(root, '.claude', 'skills')), '../.agents/skills');
      assert.equal(saved.get('steward.toml'), readFileSync(join(root, 'steward.toml'), 'utf8'), 'steward.toml is never edited');

      // R-60 reads [skills]; the user adds the table the CLI printed (the CLI never edits steward.toml).
      appendFileSync(join(root, 'steward.toml'), '\n[skills]\ncanonical = ".agents/skills"\ncopies = [".claude/skills"]\n');
      assert.equal(await vscode.commands.executeCommand('bioSteward.checkSkills'), 'completed');
      nodes = await skills();
      assert.match(nodes[0].description ?? '', /^✓ PASS · 1 copy location\(s\) match the canonical directory · check skills · /);
      const link = node(nodes, 'folder:.claude/skills');
      assert.equal(link?.description, `copy · link → ../.agents/skills · ${readdirSync(join(root, '.agents', 'skills')).length} skill folders · R-60.linked`);

      // 3. The folder listing equals the folders on disk (AC-5.3 for 0.20.6).
      const onDisk = readdirSync(join(root, '.agents', 'skills'), { withFileTypes: true })
        .filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
      assert.ok(onDisk.length > 0);
      for (const id of ['folder:.agents/skills', 'folder:.claude/skills']) {
        assert.deepEqual(node(nodes, id)?.children?.filter((n) => n.kind === 'skill').map((n) => n.label), onDisk, id);
      }

      // 4. A second install of the same skills is blocked: the CLI never overwrites.
      assert.equal(await api.skillsInstall.preview(api.project, { skills: ['.agents/skills', '.claude/skills'], kits: ['core'] }), true);
      assert.match(api.skillsInstall.html ?? '', /Nothing to install/);
      assert.doesNotMatch(api.skillsInstall.html ?? '', /href="command:/);
      assert.equal(await api.skillsInstall.apply(async () => true), false);
      api.skillsInstall.dispose();

      // 5. A hand-edited copy shows the R-60 drift in the view (AC-5.2).
      const badge = api.statusBar.view?.badge;
      rmSync(join(root, '.claude', 'skills'));
      cpSync(join(root, '.agents', 'skills'), join(root, '.claude', 'skills'), { recursive: true });
      const [skill] = readdirSync(join(root, '.claude', 'skills')).sort();
      appendFileSync(join(root, '.claude', 'skills', skill, 'SKILL.md'), '\nhand edit\n');
      assert.equal(await vscode.commands.executeCommand('bioSteward.checkSkills'), 'completed');
      nodes = await skills();
      assert.match(nodes[0].description ?? '', /^✗ FAIL · a skills copy is missing, dangling or has drifted · check skills · /);
      const copy = node(nodes, 'folder:.claude/skills');
      assert.match(copy?.description ?? '', /^copy · \d+ skill folders · R-60\.drift$/);
      const detail = copy?.children?.[0];
      assert.equal(detail?.label, 'R-60.drift');
      assert.equal(detail?.description, `differs from the canonical copy: ${skill}/SKILL.md`);
      assert.equal(api.statusBar.view?.badge, badge, 'the drift run is partial: it never changes the gate badge');
    });
  });
});
