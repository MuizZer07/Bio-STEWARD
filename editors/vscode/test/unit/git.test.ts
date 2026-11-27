// The one git command (S10; DECISIONS.md, Muiz 2026-11-26, option (a)): `git check-ignore` for VX5's `auto`.
// T12 (D1, T11-01 / T11-02): it is the only git command left, it runs with a cleaned environment, and a hostile
// repository's filter, fsmonitor and hook programs never run.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { chmod, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { delimiter, dirname, join } from 'node:path';
import { commands } from '../../src/cli/commands';
import { CHECK_IGNORE_ARGS, gitCommands, gitEnvironment, isGitAllowed, reportIgnored } from '../../src/cli/git';
import { CliRunner } from '../../src/cli/runner';

const SYSTEM_GIT = (() => {
  try {
    return execFileSync('/bin/sh', ['-c', 'command -v git'], { encoding: 'utf8' }).trim() || undefined;
  } catch {
    return undefined;
  }
})();

describe('git check-ignore for the report location (S10)', () => {
  let scratch: string;
  let repo: string;
  const trusted = () => true;

  beforeEach(async () => {
    scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-git-test-')));
    repo = join(scratch, 'project');
    await mkdir(repo);
  });

  afterEach(async () => rm(scratch, { recursive: true, force: true }));

  async function program(path: string, code: string): Promise<string> {
    await mkdir(dirname(path), { recursive: true });
    // This Node by absolute path: git and the runner may start it with a PATH that has no `node`.
    await writeFile(path, `#!${process.execPath}\n` + code);
    await chmod(path, 0o700);
    return path;
  }

  const ask = (env: NodeJS.ProcessEnv, isTrusted = trusted) =>
    reportIgnored({ root: repo, workspaceRoots: [repo], env, isTrusted });

  it('has one builder, on its own allow-list, with core.fsmonitor, hooks and the untracked cache forced off', () => {
    assert.deepEqual(Object.keys(gitCommands), ['checkIgnoreReport']);
    const invocation = gitCommands.checkIgnoreReport();
    assert.deepEqual(invocation.args, [
      '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-c', 'core.untrackedCache=false',
      'check-ignore', '-q', '--', '.steward/report.json',
    ]);
    assert.equal(invocation.repoIndex, undefined);
    assert.deepEqual(invocation.paths, []);
    assert.equal(invocation.confirmation, false);
    assert.ok(Object.isFrozen(invocation) && Object.isFrozen(invocation.args) && Object.isFrozen(CHECK_IGNORE_ARGS));
    assert.equal(isGitAllowed(invocation), true);
    assert.equal(isGitAllowed(commands.version()), false);
    assert.equal(isGitAllowed({ ...invocation }), false, 'a copy is not on the allow-list');
  });

  it('runs no steward invocation as git and no git invocation as steward', async () => {
    const marker = join(scratch, 'ran');
    const fake = await program(join(scratch, 'bin', 'fake'), `require('fs').writeFileSync(${JSON.stringify(marker)}, '');`);
    const git = new CliRunner({ program: 'git', cli: fake, root: repo, isTrusted: trusted });
    const steward = new CliRunner({ cli: fake, root: repo, isTrusted: trusted });
    for (const invocation of [commands.version(), commands.check({ mode: 'summary' }), commands.timeline()]) {
      assert.deepEqual(await git.run(invocation), { kind: 'process-error', message: 'Disallowed invocation' });
    }
    assert.deepEqual(await steward.run(gitCommands.checkIgnoreReport()), { kind: 'process-error', message: 'Disallowed invocation' });
    assert.equal(existsSync(marker), false);
  });

  it('maps exit 0 to ignored and 1 to not ignored; anything else, untrusted or no git is not ignored', async () => {
    const bin = join(scratch, 'bin');
    const log = join(scratch, 'argv.json');
    const exitFile = join(scratch, 'exit');
    // Only the lookup uses this PATH; the child gets the cleaned environment (gitEnvironment), so the exit code
    // to give comes from a file, not a variable.
    const env = { PATH: bin };
    await program(join(bin, 'git'), `const fs = require('fs'); fs.writeFileSync(${JSON.stringify(log)},
      JSON.stringify({ argv: process.argv.slice(2), cwd: process.cwd() }));
      process.exit(Number(fs.readFileSync(${JSON.stringify(exitFile)}, 'utf8')));`);
    const exits = new Map([[0, true], [1, false], [128, false], [2, false]]);
    for (const [code, ignored] of exits) {
      await writeFile(exitFile, String(code));
      const answer = await ask(env);
      assert.equal(answer.ignored, ignored, `exit ${code}: ${answer.why}`);
    }
    const seen = JSON.parse(await readFile(log, 'utf8')) as { argv: string[]; cwd: string };
    assert.deepEqual(seen.argv, [...CHECK_IGNORE_ARGS], 'no shell, the exact arguments, no --repo');
    assert.equal(seen.cwd, repo, 'the project root is the working directory');

    await rm(log);
    assert.deepEqual(await ask(env, () => false), { ignored: false, why: 'untrusted' });
    assert.equal(existsSync(log), false, 'nothing runs in an untrusted workspace');
    assert.deepEqual(await ask({ PATH: join(scratch, 'empty') }), { ignored: false, why: 'git not found' });
    assert.deepEqual(await ask({ PATH: '' }), { ignored: false, why: 'git not found' });
  });

  it('runs git with PATH, HOME and GIT_CONFIG_NOSYSTEM=1 only: every GIT_* variable of the host is dropped', async () => {
    assert.deepEqual(gitEnvironment({ PATH: '/p', HOME: '/h', GIT_DIR: '/x', GIT_CONFIG_GLOBAL: '/y', LANG: 'C', GIT_CONFIG_NOSYSTEM: '0' }),
      { GIT_CONFIG_NOSYSTEM: '1', PATH: '/p', HOME: '/h' });
    const bin = join(scratch, 'bin');
    const log = join(scratch, 'env.json');
    await program(join(bin, 'git'), `require('fs').writeFileSync(${JSON.stringify(log)}, JSON.stringify(process.env)); process.exit(1);`);
    const saved = { ...process.env };
    Object.assign(process.env, { GIT_DIR: join(scratch, 'elsewhere'), GIT_WORK_TREE: scratch, GIT_CONFIG_COUNT: '1',
      GIT_CONFIG_KEY_0: 'core.fsmonitor', GIT_CONFIG_VALUE_0: '/bin/true', GIT_ALTERNATE_OBJECT_DIRECTORIES: scratch,
      GIT_EXEC_PATH: scratch, BIO_STEWARD_SECRET: 'not for git' });
    try {
      assert.equal((await ask({ PATH: bin })).why, 'git: not ignored');
    } finally {
      for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
      Object.assign(process.env, saved);
    }
    const seen = JSON.parse(await readFile(log, 'utf8')) as Record<string, string>;
    // macOS adds __CF_USER_TEXT_ENCODING to every process; nothing else may appear.
    delete seen.__CF_USER_TEXT_ENCODING;
    assert.deepEqual(Object.keys(seen).sort(), ['GIT_CONFIG_NOSYSTEM', 'HOME', 'PATH'].filter((k) => k !== 'HOME' || process.env.HOME));
    assert.equal(seen.GIT_CONFIG_NOSYSTEM, '1');
  });

  it('never takes git from inside a workspace folder, even when PATH names it', async () => {
    const inside = join(repo, 'bin');
    const marker = join(scratch, 'workspace-git-ran');
    await program(join(inside, 'git'), `require('fs').writeFileSync(${JSON.stringify(marker)}, ''); process.exit(0);`);
    const answer = await ask({ PATH: inside });
    assert.deepEqual(answer, { ignored: false, why: 'git not found' });
    assert.equal(existsSync(marker), false);
  });

  it('times out a hanging git and treats it as not ignored', async function () {
    this.timeout(5000);
    const bin = join(scratch, 'bin');
    await program(join(bin, 'git'), 'setTimeout(() => {}, 60000);');
    const answer = await reportIgnored({ root: repo, workspaceRoots: [repo], env: { PATH: bin }, isTrusted: trusted, timeoutMs: 300 });
    assert.deepEqual(answer, { ignored: false, why: 'git: timeout' });
  });

  if (!SYSTEM_GIT) {
    it('answers for real repositories (skipped: no git on PATH)');
  } else {
    const env = { PATH: dirname(SYSTEM_GIT) + delimiter + '/usr/bin:/bin' };
    const init = async () => {
      execFileSync('git', ['init', '-q'], { cwd: repo });
    };

    it('an ignored fixture repository: .steward/ in .gitignore → ignored', async () => {
      await init();
      await writeFile(join(repo, '.gitignore'), '# >>> steward\n.steward/\n# <<< steward\n');
      assert.deepEqual(await ask(env), { ignored: true, why: 'git: ignored' });
    });

    it('a not-ignored fixture repository → not ignored', async () => {
      await init();
      await writeFile(join(repo, '.gitignore'), 'results/\n');
      assert.deepEqual(await ask(env), { ignored: false, why: 'git: not ignored' });
    });

    it('a folder that is not a repository → not ignored (git exits 128)', async () => {
      const answer = await ask(env);
      assert.equal(answer.ignored, false);
    });

    it('a .git/config whose core.fsmonitor and hooks would create a marker file: the marker never appears', async () => {
      await init();
      await writeFile(join(repo, '.gitignore'), '.steward/\n');
      const marker = join(scratch, 'fsmonitor-ran');
      const hook = await program(join(scratch, 'hook', 'fsmonitor'),
        `require('fs').writeFileSync(${JSON.stringify(marker)}, process.argv.slice(2).join(' ')); process.stdout.write('/\\0');`);
      const hooks = join(scratch, 'hooks');
      await program(join(hooks, 'post-checkout'), `require('fs').writeFileSync(${JSON.stringify(marker)}, 'hook');`);
      execFileSync('git', ['config', 'core.fsmonitor', hook], { cwd: repo });
      execFileSync('git', ['config', 'core.hooksPath', hooks], { cwd: repo });
      execFileSync('git', ['config', 'core.untrackedCache', 'true'], { cwd: repo });

      assert.deepEqual(await ask(env), { ignored: true, why: 'git: ignored' });
      assert.equal(existsSync(marker), false, 'the repository\'s fsmonitor or hook ran');

      // Control: the same configuration does start the program under a command that consults fsmonitor, so the
      // fixture would have caught a missing override (where this git version calls the hook at all).
      execFileSync('git', ['status', '--porcelain'], { cwd: repo, stdio: 'ignore' });
      console.log(`    control: git status with this .git/config ${existsSync(marker) ? 'ran' : 'did not run'} the fsmonitor program`);
    });

    // T11-01: a repository whose own config defines a clean filter and a long-running process filter, with tracked
    // files whose stat no longer matches the index (the case where `git status` can hash them through the filter).
    // check-ignore must never start either program.
    it('a hostile .git/config with filter.*.clean and filter.*.process: neither program ever runs', async () => {
      await init();
      const marker = join(scratch, 'filter-ran');
      const clean = await program(join(scratch, 'filter', 'clean'),
        `require('fs').appendFileSync(${JSON.stringify(marker)}, 'clean\\n'); process.stdin.pipe(process.stdout);`);
      const proc = await program(join(scratch, 'filter', 'process'),
        `require('fs').appendFileSync(${JSON.stringify(marker)}, 'process\\n'); process.exit(1);`);
      const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, stdio: 'ignore',
        env: { ...env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_AUTHOR_NAME: 'T', GIT_AUTHOR_EMAIL: 't@example.invalid',
          GIT_COMMITTER_NAME: 'T', GIT_COMMITTER_EMAIL: 't@example.invalid' } });
      await writeFile(join(repo, '.gitignore'), '.steward/\n');
      await writeFile(join(repo, 'data.txt'), 'one\n');
      await writeFile(join(repo, 'data.dat'), 'one\n');
      git('add', '-A');
      git('commit', '-qm', 'init');
      // Two drivers, because git uses `process` instead of `clean` when one driver has both.
      await writeFile(join(repo, '.gitattributes'), '*.txt filter=evil\n*.dat filter=proc\n');
      git('config', 'filter.evil.clean', clean);
      git('config', 'filter.proc.process', proc);
      git('config', 'filter.proc.required', 'false');
      // Same size, new content and mtime: a refresh would hash the files through their filters.
      await writeFile(join(repo, 'data.txt'), 'two\n');
      await writeFile(join(repo, 'data.dat'), 'two\n');

      for (const subdir of ['', 'sub']) {
        if (subdir) await mkdir(join(repo, subdir), { recursive: true });
        assert.deepEqual(await ask(env), { ignored: true, why: 'git: ignored' });
      }
      assert.equal(existsSync(marker), false, `a repository filter ran during check-ignore: ${existsSync(marker) ? await readFile(marker, 'utf8') : ''}`);

      // Controls. `git status` may or may not hash the file on this git version (it depends on the stat data), so
      // it is only logged. `git hash-object` (no -w: writes nothing) always applies the configured filter, so the
      // fixture is proved live: a check-ignore that ran the filter would have left the marker.
      const ran = () => existsSync(marker) ? readFileSync(marker, 'utf8').trim().split('\n').join(', ') : 'nothing';
      try {
        git('status', '--porcelain');
      } catch {
        // A failing process filter can make status fail; whether it ran is what matters.
      }
      const status = ran();
      for (const file of ['data.txt', 'data.dat']) {
        try {
          git('hash-object', '--', file);
        } catch {
          // As above.
        }
      }
      assert.match(ran(), /clean/, 'control: git hash-object did not run the clean filter, so the fixture proves nothing');
      assert.match(ran(), /process/, 'control: git hash-object did not run the process filter, so the fixture proves nothing');
      console.log(`    control: git status ran ${status}; git hash-object ran ${ran()}; check-ignore ran nothing`);
    });
  }
});
