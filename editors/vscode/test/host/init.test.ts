import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, readlinkSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import * as vscode from 'vscode';
import { guidedInitCommands, type GuidedInitOptions } from '../../src/cli/commands';
import type { TestApi } from '../../src/extension';

const powered = process.env.BIO_STEWARD_TEST_EXAMPLE === 'init';
const env = { ...process.env, STEWARD_NO_REGISTRY: '1' };

function subsets<T>(values: readonly T[]): T[][] {
  return values.reduce<T[][]>((sets, value) => [...sets, ...sets.map((set) => [...set, value])], [[]]);
}

function snapshot(root: string, folder = root): Map<string, Buffer | string> {
  const entries = new Map<string, Buffer | string>();
  for (const entry of readdirSync(folder, { withFileTypes: true })) {
    if (folder === root && entry.name === '.git') continue;
    const path = join(folder, entry.name);
    const key = relative(root, path);
    if (entry.isSymbolicLink()) entries.set(key, readlinkSync(path));
    else if (entry.isDirectory()) {
      entries.set(key, 'directory');
      for (const [child, value] of snapshot(root, path)) entries.set(child, value);
    } else entries.set(key, readFileSync(path));
  }
  return entries;
}

describe('Guided init (S6)', function () {
  let api: TestApi;
  let root: string;
  let cli: string;

  before(async function () {
    if (!powered) this.skip();
    const extension = vscode.extensions.getExtension<TestApi>('MuizZer07.bio-steward');
    assert.ok(extension);
    api = await extension.activate();
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    root = realpathSync(folder.uri.fsPath);
    cli = vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
    assert.equal(execFileSync(cli, ['--version'], { encoding: 'utf8' }).trim(), 'steward 0.20.6');
    for (let i = 0; api.project.state.cli.kind === 'detecting' && i < 100; i++) {
      await new Promise((done) => setTimeout(done, 50));
    }
    assert.equal(api.project.state.cli.kind, 'ready');
    console.log('    Guided init uses steward 0.20.6');
  });

  after(() => api?.init.dispose());

  it('opens the setup walkthrough from the registered command', async () => {
    await vscode.commands.executeCommand('bioSteward.openInitWalkthrough');
    assert.ok(vscode.window.tabGroups.all.some((group) => group.tabs.some((tab) =>
      tab.label === 'Welcome' || tab.label.includes('Set up a Bio-STEWARD project'))));
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
  });

  it('maps every selectable goal, profile, ordered harness and kit combination to exact arguments (AC-2.1)', () => {
    const harnesses = [[], ['.agents/skills'], ['.claude/skills'],
      ['.agents/skills', '.claude/skills'], ['.claude/skills', '.agents/skills']];
    let tested = 0;
    for (const goals of subsets(['reanalysis', 'benchmark', 'paper', 'agents', 'licence'] as const)) {
      for (const profile of ['exploratory', 'confirmatory'] as const) {
        for (const skills of harnesses) {
          for (const kits of skills.length ? subsets(['core', 'paper', 'talk'] as const) : [[]]) {
            const expected = ['init', '--profile', profile,
              ...goals.flatMap((goal) => ['--for', goal]), ...skills.flatMap((skill) => ['--skills', skill])];
            if (kits.length) expected.push('--kits', kits.join(','));
            const { preview, apply } = guidedInitCommands({ goals, profile, skills, kits });
            assert.deepEqual(apply.args, expected);
            assert.equal(apply.confirmation, true);
            assert.deepEqual(preview.args, [...expected, '--dry-run']);
            assert.equal(preview.confirmation, false);
            tested++;
          }
        }
      }
    }
    assert.equal(tested, 2112);
    console.log(`    ${tested} option combinations checked`);
  });

  it('shows CLI updates to existing files and blocks applying that plan (AC-2.3)', async () => {
    const ignore = join(root, '.gitignore');
    const original = Buffer.from('custom-ignore\n');
    writeFileSync(ignore, original);
    try {
      await api.init.preview(api.project, { profile: 'exploratory' });
      assert.match(api.init.html ?? '', /would update\s+\.gitignore/);
      assert.doesNotMatch(api.init.html ?? '', /href="command:bioSteward\.applyInit"/);
      const applied = await api.init.apply(async () => assert.fail('a blocked plan cannot ask for confirmation'));
      assert.equal(applied, false);
      assert.deepEqual(readFileSync(ignore), original);
      assert.equal(existsSync(join(root, 'steward.toml')), false);
    } finally {
      rmSync(ignore);
    }
  });

  it('rechecks after confirmation if the plan changed while the preview was open', async () => {
    const ignore = join(root, '.gitignore');
    try {
      await api.init.preview(api.project, { profile: 'exploratory' });
      assert.match(api.init.html ?? '', /href="command:bioSteward\.applyInit"/);
      // D2: the confirmation-gated exception enables exactly this one command; no scripts, no local resources.
      assert.deepEqual(api.init.webviewOptions?.enableCommandUris, ['bioSteward.applyInit']);
      assert.equal(api.init.webviewOptions?.enableScripts, false);
      assert.deepEqual(api.init.webviewOptions?.localResourceRoots, []);
      const applied = await api.init.apply(async () => {
        writeFileSync(ignore, 'created after preview\n');
        return true;
      });
      assert.equal(applied, false);
      assert.equal(readFileSync(ignore, 'utf8'), 'created after preview\n');
      assert.equal(existsSync(join(root, 'steward.toml')), false);
    } finally {
      rmSync(ignore);
    }
  });

  it('shows the exact dry run, applies the shown plan byte-safely and opens the first verdict (AC-2.2–2.4)', async () => {
    execFileSync('git', ['init', '-q', root]);
    for (const folder of ['development', 'paper', '.claude/skills/using-steward', '.steward']) {
      mkdirSync(join(root, folder), { recursive: true });
    }
    writeFileSync(join(root, '.gitignore'), 'custom-ignore\n# >>> steward\n.steward/\n# <<< steward\n');
    writeFileSync(join(root, '.steward/report.json'), 'previous report\n');
    writeFileSync(join(root, 'AGENTS.md'), 'existing instructions <&>\n');
    writeFileSync(join(root, 'development/DECISIONS.md'), 'existing decisions\n');
    writeFileSync(join(root, 'paper/main.tex'), 'existing manuscript\n');
    writeFileSync(join(root, '.claude/skills/using-steward/SKILL.md'), 'existing skill\n');
    const before = snapshot(root);

    const options: GuidedInitOptions = {
      profile: 'confirmatory', goals: ['reanalysis', 'paper', 'agents'],
      skills: ['.claude/skills', '.agents/skills'], kits: ['core', 'paper', 'talk'],
    };
    const args = ['init', '--repo', root, '--profile', 'confirmatory', '--for', 'reanalysis', '--for', 'paper',
      '--for', 'agents', '--skills', join(root, '.claude/skills'), '--skills', join(root, '.agents/skills'),
      '--kits', 'core,paper,talk'];
    const stdout = execFileSync(cli, [...args, '--dry-run'], { encoding: 'utf8', env });
    await api.init.preview(api.project, options);
    const preview = api.init.html ?? '';
    const shown = preview.match(/<pre><span>([\s\S]*)<\/span><\/pre>/)?.[1];
    assert.equal(shown?.replaceAll('&quot;', '"').replaceAll('&gt;', '>').replaceAll('&lt;', '<').replaceAll('&amp;', '&'), stdout);
    assert.deepEqual(snapshot(root), before);
    assert.equal(await api.init.apply(async () => false), false);
    assert.deepEqual(snapshot(root), before, 'dismissing confirmation writes nothing');

    const applied = await api.init.apply(async (program, argv) => {
      assert.equal(program, cli);
      assert.deepEqual(argv, args);
      return true;
    });
    assert.equal(applied, true);
    const after = snapshot(root);
    for (const [file, bytes] of before) assert.deepEqual(after.get(file), bytes, file);
    const planned = stdout.split('\n').filter((line) => line.startsWith('would create   '))
      .map((line) => line.split(/\s+/)[2].replace(/\/$/, ''));
    for (const path of planned) assert.ok(lstatSync(join(root, path)), path);
    for (const path of after.keys()) {
      if (!before.has(path)) assert.ok(planned.some((entry) => path === entry || path.startsWith(entry + '/') || entry.startsWith(path + '/')), path);
    }
    assert.ok(lstatSync(join(root, '.agents/skills')).isSymbolicLink());
    assert.equal(realpathSync(join(root, '.agents/skills')), join(root, '.claude/skills'));
    assert.equal(api.project.state.run, 'completed');
    assert.ok(api.project.state.full?.report);
    assert.ok(api.overview.tree.nodes.some((node) => node.id === 'full/gate:default'));
    assert.equal(api.project.lastReportLocation?.where, 'extension');
  });
});
