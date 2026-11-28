import { strict as assert } from 'node:assert';
import { existsSync } from 'node:fs';
import { chmod, mkdir, mkdtemp, readFile, realpath, rm, symlink, truncate, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { delimiter, dirname, join, relative } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import Ajv from 'ajv';
import { commands, Invocation, isAllowed } from '../../src/cli/commands';
import { FeatureDetector } from '../../src/cli/features';
import { findProjectRoot, locateCli } from '../../src/cli/locator';
import { parseJson, readJson } from '../../src/cli/output';
import { confinedPath } from '../../src/cli/paths';
import { CliRunner, RunResult } from '../../src/cli/runner';

const extensionRoot = join(__dirname, '..', '..', '..');
const manifestPath = join(extensionRoot, 'package.json');
const versions = { minimumCli: '0.20.6', testedWithCli: '0.20.6' };
const completed = (stdout = '', exitCode = 0): RunResult => ({ kind: 'completed', exitCode, stdout, stderr: '' });

describe('CLI layer', () => {
  let scratch: string;
  let root: string;
  let home: string;

  beforeEach(async () => {
    scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-cli-test-')));
    root = join(scratch, 'project with spaces');
    home = join(scratch, 'home');
    await Promise.all([mkdir(root), mkdir(home)]);
  });

  afterEach(async () => rm(scratch, { recursive: true, force: true }));

  async function executable(path: string, code = ''): Promise<string> {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, '#!/usr/bin/env node\n' + code);
    await chmod(path, 0o700);
    return path;
  }

  async function stub(code: string): Promise<string> {
    return executable(join(home, 'steward'), code);
  }

  it('T2 uses the global setting, then PATH, then pipx or uv', async () => {
    const configured = await executable(join(home, 'configured', 'steward'));
    const onPath = await executable(join(home, 'path', 'steward'));
    const pipx = await executable(join(home, '.local', 'share', 'pipx', 'venvs', 'bio-steward', 'bin', 'steward'));
    const uv = join(home, '.local', 'share', 'uv', 'tools', 'bio-steward', 'bin', 'steward');
    const env = { PATH: dirname(onPath) };
    const base = { workspaceRoots: [root], env, home };
    assert.deepEqual(await locateCli({ ...base, setting: { globalValue: configured } }),
      { kind: 'found', path: configured, source: 'setting' });
    assert.deepEqual(await locateCli({ ...base, setting: { globalValue: './steward' } }), { kind: 'invalid-setting' });
    assert.deepEqual(await locateCli(base), { kind: 'found', path: onPath, source: 'path' });
    assert.deepEqual(await locateCli({ ...base, env: {} }), { kind: 'found', path: pipx, source: 'tools' });
    await executable(uv);
    assert.deepEqual(await locateCli({ ...base, env: {} }), { kind: 'found', path: uv, source: 'tools' });
  });

  it('T2 ignores workspace settings, relative PATH, and workspace binaries reached through symlinks', async () => {
    const fake = await executable(join(root, '.venv', 'bin', 'steward'));
    const alternate = join(home, 'aliased', 'steward');
    await mkdir(dirname(alternate));
    await symlink(fake, alternate);
    const inside = await executable(join(root, 'bin', 'steward'));
    const setting = { globalValue: undefined, workspaceValue: inside, workspaceFolderValue: fake };
    const env = { PATH: ['', '.venv/bin', dirname(fake), dirname(inside), dirname(alternate)].join(delimiter) };
    assert.deepEqual(await locateCli({ workspaceRoots: [root], setting, env, home }), { kind: 'missing' });
  });

  it('finds the closest steward.toml without walking outside the workspace', async () => {
    const project = join(root, 'nested');
    const child = join(project, 'child');
    await mkdir(child, { recursive: true });
    await writeFile(join(scratch, 'steward.toml'), '');
    assert.equal(await findProjectRoot(child, root), undefined);
    await writeFile(join(root, 'steward.toml'), '');
    await writeFile(join(project, 'steward.toml'), '');
    assert.equal(await findProjectRoot(child, root), project);
  });

  it('builds the released forms and separates confirmation from preview', () => {
    assert.deepEqual(commands.version().args, ['--version']);
    assert.deepEqual(commands.interface().args, ['interface', '--format', 'json']);
    assert.deepEqual(commands.check({ mode: 'report', output: 'report.json', rule: 'R-11', areas: ['paper'] }).args,
      ['check', '--format', 'json', '--output', 'report.json', '--rule', 'R-11', 'paper']);
    assert.deepEqual(commands.check({ mode: 'summary' }).args, ['check', '--summary']);
    assert.deepEqual(commands.timeline().args, ['timeline', '--json']);
    assert.deepEqual(commands.auditProgress().args, ['audit', 'progress', '--json']);
    assert.deepEqual(commands.exchangeStatus().args, ['exchange', 'status', '--json']);
    assert.deepEqual(commands.notifications().args, ['notifications', '--format', 'json']);
    assert.equal(commands.notifications().confirmation, false);
    assert.deepEqual(commands.upgradeCheck().args, ['upgrade', '--check', '--format', 'json']);
    assert.equal(commands.upgradeCheck().confirmation, false);
    assert.equal(commands.upgradeCheck().args.includes('--online'), false, 'extension never passes --online');
    const preview = commands.init({ goals: ['agents', 'paper'], agentsMd: true, paper: true, skills: ['.agents/skills'],
      kits: ['core', 'paper'], templates: ['prior-work'], preview: 'text' });
    assert.deepEqual(preview.args, ['init', '--for', 'agents', '--for', 'paper', '--agents-md', '--skills',
      '.agents/skills', '--kits', 'core,paper', '--paper', '--templates', 'prior-work', '--dry-run']);
    assert.equal(preview.confirmation, false);
    assert.equal(commands.init().confirmation, true);
  });

  it('cannot build or run any denied command from design §6.4', async () => {
    const denied = [
      'authorize sign', 'authorize sign-pending', 'authorize anchor', 'authorize pin', 'unseal', 'seal', 'spend record',
      'freeze', 'amend apply', 'release publish', 'release go-public', 'release ack', 'sprint start', 'sprint go',
      'sprint hold', 'sprint skip', 'task dispatch', 'run', 'stage run', 'data fetch', 'storage clean', 'channel use',
      'hooks install', 'exchange respond', 'exchange announce', 'upgrade --to 0.23.0', 'exchange pull',
    ];
    const cli = await stub('throw new Error("must not execute");');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    const builders = Object.keys(commands);
    assert.deepEqual(builders.sort(), [
      'auditProgress', 'authorizePending', 'authorizePendingJson', 'check', 'decisions', 'exchangeStatus', 'explain',
      'init', 'interface', 'next', 'nextBrief', 'notifications', 'report', 'skillsList', 'sprintStatus', 'taskBoard',
      'taskBrief', 'taskDone', 'taskStart', 'timeline', 'timelineFull', 'tokensReport', 'upgradeCheck', 'version',
    ]);
    for (const name of denied) {
      assert.equal(Object.hasOwn(commands, name), false, name);
      const forged: Invocation = { args: name.split(' '), repoIndex: 1, paths: [], confirmation: false };
      assert.equal(isAllowed(forged), false, name);
      assert.deepEqual(await runner.run(forged), { kind: 'process-error', message: 'Disallowed invocation' }, name);
    }
    assert.throws(() => (commands.check({ mode: 'summary' }).args as string[]).push('--output', 'file'));
  });

  it('P5 (U04) builds authorize pending --all-projects, read-only, and runs it with --repo', async () => {
    const pending = commands.authorizePending();
    assert.deepEqual(pending.args, ['authorize', 'pending', '--all-projects']);
    assert.equal(pending.confirmation, false);
    const cli = await stub('console.log(JSON.stringify(process.argv.slice(2)));');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    const result = await runner.run(pending);
    assert.equal(result.kind, 'completed');
    if (result.kind === 'completed') {
      assert.deepEqual(JSON.parse(result.stdout), ['authorize', 'pending', '--repo', await realpath(root), '--all-projects']);
    }
  });

  it('P4 (U03) builds tokens report, task start and task done; the window commands need confirmation', async () => {
    assert.deepEqual(commands.tokensReport().args, ['tokens', 'report', '--json']);
    assert.equal(commands.tokensReport().confirmation, false);
    const logs = commands.tokensReport({ claude: ['/a.jsonl', '/b.jsonl'], gemini: ['/c.json'] });
    assert.deepEqual(logs.args, ['tokens', 'report', '--json', '--claude', '/a.jsonl', '--claude', '/b.jsonl', '--gemini', '/c.json']);
    assert.deepEqual(logs.paths.map((p) => p.use), ['log', 'log', 'log']);
    assert.deepEqual(commands.taskStart('GEO-001').args, ['task', 'start', 'GEO-001']);
    assert.deepEqual(commands.taskDone('GEO-001').args, ['task', 'done', 'GEO-001']);
    assert.equal(commands.taskStart('GEO-001').confirmation, true);
    assert.equal(commands.taskDone('GEO-001').confirmation, true);
    for (const id of ['', '-x', '--yes', 'a b', 'a;b', 'x\n', 'GEO-001 --session s']) {
      assert.throws(() => commands.taskStart(id), /Invalid task ID/, id);
      assert.throws(() => commands.taskDone(id), /Invalid task ID/, id);
    }
    assert.throws(() => commands.tokensReport({ claude: ['--claude-hook'] }), /Invalid CLI argument/);

    const cli = await stub('console.log(JSON.stringify(process.argv.slice(2)));');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    assert.deepEqual(await runner.run(commands.taskStart('GEO-001')), { kind: 'unconfirmed' });
    assert.deepEqual(await runner.run(commands.taskDone('GEO-001'), { confirm: async () => false }), { kind: 'unconfirmed' });
    const started = await runner.run(commands.taskStart('GEO-001'), { confirm: async (_program, args) => {
      assert.deepEqual(args, ['task', 'start', '--repo', root, 'GEO-001']);
      return true;
    } });
    assert.equal(started.kind === 'completed' && started.stdout, `${JSON.stringify(['task', 'start', '--repo', root, 'GEO-001'])}\n`);

    // An agent log is an absolute path to an existing regular file anywhere on the machine, resolved through links.
    const log = join(home, 'logs', 'session.jsonl');
    await mkdir(dirname(log), { recursive: true });
    await writeFile(log, '');
    await symlink(log, join(home, 'linked.jsonl'));
    const read = await runner.run(commands.tokensReport({ claude: [join(home, 'linked.jsonl')] }));
    assert.equal(read.kind, 'completed');
    assert.deepEqual(read.kind === 'completed' && JSON.parse(read.stdout), ['tokens', 'report', '--repo', root, '--json', '--claude', log]);
    for (const bad of ['relative.jsonl', join(home, 'missing.jsonl'), join(home, 'logs')]) {
      assert.deepEqual(await runner.run(commands.tokensReport({ codex: [bad] })),
        { kind: 'process-error', message: 'An agent log is not an absolute path to a readable file' }, bad);
    }
    // With the boundary its setting named (U09): refused when the file is reached through a link or lies outside it.
    const bounded = await runner.run(commands.tokensReport({ claude: [log], boundaries: { [log]: dirname(log) } }));
    assert.equal(bounded.kind, 'completed');
    for (const [file, boundary] of [[join(home, 'linked.jsonl'), home], [log, join(home, 'elsewhere')]]) {
      assert.deepEqual(await runner.run(commands.tokensReport({ claude: [file], boundaries: { [file]: boundary } })), { kind: 'process-error',
        message: 'An agent log is no longer inside the file or folder its setting names, or is reached through a link' }, file);
    }
  });

  it('T3 validates flags and sends shell metacharacters in paths and settings literally', async () => {
    assert.throws(() => commands.explain('R-11; noop' as 'R-11'), /Invalid rule ID/);
    assert.throws(() => commands.explain('R-1'), /Invalid rule ID/);
    assert.throws(() => commands.check({ mode: 'summary', gate: '--gate=other' }), /Invalid CLI argument/);
    assert.throws(() => commands.init({ paper: '../outside' }), /Invalid scaffold name/);
    const cli = await stub('console.log(JSON.stringify(process.argv.slice(2)));');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    const path = 'report ;$(literal) name.json';
    const gate = 'gate & literal';
    const result = await runner.run(commands.check({ mode: 'report', output: path, gate }));
    assert.equal(result.kind, 'completed');
    assert.deepEqual(JSON.parse(result.stdout), ['check', '--repo', root, '--format', 'json',
      '--output', join(root, path), '--gate', gate]);
  });

  it('requires trust for every command and confirmation for init writes', async () => {
    const cli = await stub('console.log(process.env.STEWARD_NO_REGISTRY); console.error("log");');
    let trusted = false;
    const stderr: string[] = [];
    const runner = new CliRunner({ cli, root, isTrusted: () => trusted, registry: 'disable',
      logStderr: (line) => stderr.push(line) });
    assert.deepEqual(await runner.run(commands.version()), { kind: 'untrusted' });
    trusted = true;
    assert.deepEqual(await runner.run(commands.init()), { kind: 'unconfirmed' });
    const res = await runner.run(commands.init(), { confirm: async (program, args) => {
      assert.equal(program, cli);
      assert.deepEqual(args, ['init', '--repo', root]);
      return true;
    } });
    assert.deepEqual(res, { kind: 'completed', exitCode: 0, stdout: '1\n', stderr: 'log\n' });
    assert.deepEqual(stderr, ['log\n']);
  });

  it('keeps a single running request and only the newest queued request per root', async () => {
    const cli = await stub('setTimeout(() => console.log(process.argv.at(-1)), 50);');
    const options = { cli, root, isTrusted: () => true };
    const runner = new CliRunner(options);
    const other = new CliRunner(options);
    const first = runner.run(commands.explain('R-11'));
    const queued = other.run(commands.explain('R-12'));
    const last = other.run(commands.explain('R-13'));
    assert.deepEqual(await queued, { kind: 'superseded' });
    const [a, b] = await Promise.all([first, last]);
    assert.equal(a.kind, 'completed');
    assert.equal(b.kind, 'completed');
    assert.equal(a.stdout, 'R-11\n');
    assert.equal(b.stdout, 'R-13\n');
  });

  for (const reason of ['timeout', 'cancelled'] as const) {
    it(`kills the process group on ${reason}`, async function () {
      this.timeout(6000);
      const started = join(root, 'started');
      const survived = join(root, 'survived');
      const grandchild = `require('fs').writeFileSync(${JSON.stringify(started)}, '');
        setTimeout(() => require('fs').writeFileSync(${JSON.stringify(survived)}, ''), 1600);`;
      const cli = await stub(`require('child_process').spawn(process.execPath, ['-e', ${JSON.stringify(grandchild)}],
        { stdio: 'inherit' }); setInterval(() => {}, 1000);`);
      const controller = new AbortController();
      const runner = new CliRunner({ cli, root, isTrusted: () => true, timeoutMs: 1100 });
      const result = runner.run(commands.version(), { signal: controller.signal });
      for (let i = 0; i < 100; i++) {
        if (await readFile(started).then(() => true, () => false)) break;
        await delay(10);
      }
      await readFile(started);
      if (reason === 'cancelled') controller.abort();
      assert.deepEqual(await result, { kind: reason });
      await delay(1700);
      await assert.rejects(readFile(survived), { code: 'ENOENT' });
    });
  }

  it('T4 caps oversized child output and rejects malformed, deep or schema-invalid JSON', async () => {
    const cli = await stub('process.stdout.write(Buffer.alloc(50 * 1024 * 1024, 65));');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    assert.deepEqual(await runner.run(commands.version()), { kind: 'unreadable' });
    const validate = new Ajv().compile<{ message: string }>({
      type: 'object', required: ['message'], properties: { message: { type: 'string' } },
    });
    const broken = await stub('process.stdout.write(\'{"message":\');');
    const run = await new CliRunner({ cli: broken, root, isTrusted: () => true }).run(commands.interface());
    assert.equal(run.kind, 'completed');
    assert.deepEqual(parseJson(run.stdout, validate), { kind: 'unreadable' });
    assert.deepEqual(parseJson('{"message":1}', validate), { kind: 'unreadable' });
    const anyJson = new Ajv().compile(true);
    const nested = (level: number) => '['.repeat(level) + ']'.repeat(level);
    assert.equal(parseJson(nested(64), anyJson).kind, 'valid');
    assert.deepEqual(parseJson(nested(65), anyJson), { kind: 'unreadable' });
    const message = 'escaped quote " followed by [[{{';
    assert.deepEqual(parseJson(JSON.stringify({ message }), validate), { kind: 'valid', value: { message } });
    const report = join(root, 'report.json');
    await writeFile(report, '{');
    assert.deepEqual(await readJson(report, validate), { kind: 'unreadable' });
    await truncate(report, 50 * 1024 * 1024);
    assert.deepEqual(await readJson(report, validate), { kind: 'unreadable' });
    await writeFile(report, JSON.stringify({ message }));
    assert.deepEqual(await readJson(report, validate), { kind: 'valid', value: { message } });
  });

  it('T5 confines paths and rejects symlink escapes even for new destinations', async () => {
    const outside = join(scratch, 'outside');
    const inside = join(root, 'inside');
    await Promise.all([writeFile(outside, ''), writeFile(inside, '')]);
    await symlink(scratch, join(root, 'escape'));
    await symlink(inside, join(root, 'alias'));
    await symlink(join(scratch, 'missing'), join(root, 'dangling'));
    assert.equal(await confinedPath(root, 'alias'), inside);
    assert.equal(await confinedPath(root, inside), inside);
    assert.equal(await confinedPath(root, 'new/report.json', true), join(root, 'new', 'report.json'));
    for (const path of ['.', '../outside', outside, 'escape/outside', 'escape/new.json', 'dangling', 'dangling/new']) {
      assert.equal(await confinedPath(root, path, true), undefined, path);
    }
    const cli = await stub('throw new Error("must not execute");');
    const runner = new CliRunner({ cli, root, isTrusted: () => true });
    const result = await runner.run(commands.check({ mode: 'report', output: 'escape/new.json' }));
    assert.equal(result.kind, 'process-error');
    if (result.kind === 'process-error') assert.match(result.message, /outside its allowed directory/);
  });

  it('probes interfaces once per path and version and enables only advertised JSON features', async () => {
    const detector = new FeatureDetector(versions);
    let version = '0.20.5';
    let interfaceCalls = 0;
    let answer = completed('', 64);
    const runner = {
      cliPath: '/steward',
      async run(command: Invocation) {
        if (command.args[0] === '--version') return completed(`steward ${version}\n`);
        interfaceCalls++;
        return answer;
      },
    };
    assert.equal((await detector.detect(runner)).mode, 'too-old');
    assert.equal(interfaceCalls, 0);
    version = '0.20.6';
    assert.equal((await detector.detect(runner)).mode, 'limited');
    assert.equal((await detector.detect(runner)).mode, 'limited');
    assert.equal(interfaceCalls, 1);
    version = '0.21.0';
    answer = completed(JSON.stringify({ schema: 'steward.interface/1', interface: 1, tool_version: version,
      schemas: [], json_commands: [['check'], ['explain'], ['skills', 'other']], exit_codes: {} }));
    const full = await detector.detect(runner);
    assert.equal(full.mode, 'full');
    assert.equal(full.newerThanTested, true);
    assert.deepEqual(full.capabilities, { checkReport: true, explainJson: true, digest: false,
      initPreviewJson: false, skillsInventory: false, next: false, taskBoard: false, pendingJson: false, decisionsJson: false,
      timelineJson: false, sprintStatusJson: false, tokensJson: false,
      notifications: false, upgradeCheck: false, nextBrief: false });
    assert.equal(interfaceCalls, 2);
    answer = completed('{"schema":"steward.interface/1","json_commands":"explain"}');
    assert.equal((await detector.detect({ ...runner, cliPath: '/another/steward' })).mode, 'unreadable');
    assert.equal(interfaceCalls, 3);
    version = '0.22.0';
    answer = completed(JSON.stringify({ schema: 'steward.interface/2', interface: 2, tool_version: version }));
    assert.equal((await detector.detect(runner)).mode, 'newer-interface');
    // The document CLI 0.21 and later publish: interface_version and a commands map (words -> JSON argv).
    version = '0.22.1';
    answer = completed(JSON.stringify({ schema: 'steward.interface/1', interface_version: 1, tool_version: version,
      commands: { check: { argv: ['--format', 'json'] }, 'check --digest-only': { argv: ['--against', 'FILE'] },
        explain: { argv: ['--all', '--format', 'json'] }, init: { argv: ['--dry-run', '--format', 'json'] },
        'skills list': { argv: ['--format', 'json'] }, next: { argv: ['--format', 'json'] },
        notifications: { argv: ['--format', 'json'] },
        'upgrade --check': { argv: ['--check', '--format', 'json'] } }, exit_codes: {} }));
    const published = await detector.detect(runner);
    assert.equal(published.mode, 'full');
    assert.deepEqual(published.capabilities, { checkReport: true, explainJson: true, digest: true,
      initPreviewJson: true, skillsInventory: true, next: true, taskBoard: false, pendingJson: false, decisionsJson: false,
      timelineJson: false, sprintStatusJson: false, tokensJson: false,
      notifications: true, upgradeCheck: true, nextBrief: true });
    // Clearing the cache forces a fresh interface probe (used after Upgrade CLI).
    const beforeClear = interfaceCalls;
    detector.clear();
    assert.equal((await detector.detect(runner)).mode, 'full');
    assert.equal(interfaceCalls, beforeClear + 1);
  });

  // The pinned CLI from `npm run cli:install` runs by default whenever it is there (rule G2). BIO_STEWARD_TEST_CLI
  // overrides it: a path selects another program, "off" skips the suite.
  const override = process.env.BIO_STEWARD_TEST_CLI;
  const pinnedCli = join(extensionRoot, '.cli', process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'steward.exe' : 'steward');
  const installedCli = override === 'off' ? undefined : override || (existsSync(pinnedCli) ? pinnedCli : undefined);
  if (!installedCli) {
    it('exercises the pinned installed CLI (skipped: no .cli/ from `npm run cli:install`, or BIO_STEWARD_TEST_CLI=off)');
  } else {
    it('exercises the pinned installed CLI against a scratch project', async function () {
      this.timeout(8000);
      const { bioSteward } = JSON.parse(await readFile(manifestPath, 'utf8')) as { bioSteward: typeof versions };
      const runner = new CliRunner({ cli: installedCli, root, isTrusted: () => true, registry: 'disable' });
      const detected = await new FeatureDetector(bioSteward).detect(runner);
      // CLI 0.22.0 publishes `steward interface` (steward.interface/1 with its commands map).
      assert.equal(detected.mode, 'full');
      assert.equal(detected.version, bioSteward.testedWithCli);
      console.log(`    Installed CLI verified: steward ${detected.version}`);
      const preview = await runner.run(commands.init({ preview: 'text' }));
      assert.equal(preview.kind, 'completed');
      assert.equal(preview.exitCode, 0, preview.stderr);
      await assert.rejects(readFile(join(root, 'steward.toml')), { code: 'ENOENT' });
      const init = await runner.run(commands.init(), { confirm: async () => true });
      assert.equal(init.kind, 'completed');
      assert.equal(init.exitCode, 0, init.stderr);
      const report = join(root, 'report.json');
      const check = await runner.run(commands.check({ mode: 'report', output: relative(root, report), areas: ['config'] }));
      assert.equal(check.kind, 'completed');
      assert.ok([0, 1, 2, 3].includes(check.exitCode), check.stderr);
      assert.equal(JSON.parse(await readFile(report, 'utf8')).schema, 'steward.report/0.1');
      const explain = await runner.run(commands.explain('R-11'));
      assert.equal(explain.kind, 'completed');
      assert.equal(explain.exitCode, 0, explain.stderr);
      assert.match(explain.stdout, /R-11/);
      const timeline = await runner.run(commands.timeline());
      assert.equal(timeline.kind, 'completed');
      assert.equal(timeline.exitCode, 0, timeline.stderr);
      assert.ok(Array.isArray(JSON.parse(timeline.stdout).milestones));
      const notifications = await runner.run(commands.notifications());
      assert.equal(notifications.kind, 'completed');
      assert.equal(notifications.exitCode, 0, notifications.stderr);
      assert.equal(JSON.parse(notifications.stdout).schema, 'steward.notifications/0.1');
      const upgrade = await runner.run(commands.upgradeCheck());
      assert.equal(upgrade.kind, 'completed');
      assert.equal(upgrade.exitCode, 0, upgrade.stderr);
      assert.equal(JSON.parse(upgrade.stdout).schema, 'steward.upgrade/0.1');
    });
  }
});
