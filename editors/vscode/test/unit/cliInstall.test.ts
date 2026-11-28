// E01 (RELEASE_vscode_0.3.0_SPEC, last item): `npm run cli:install` takes the pinned CLI from the release tag of the
// enclosing git repository when it has it (git archive, nothing fetched from the public repository), else PyPI, else
// the public tag; `--source local|pypi|tag` picks one and the output names the source. The choice is checked with
// `--dry-run`, which installs nothing; `npm run cli:install` itself is one of the task's done-commands.
import { strict as assert } from 'node:assert';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const extensionRoot = join(__dirname, '..', '..', '..');
const script = join(extensionRoot, 'scripts', 'cli-install.mjs');
const { bioSteward } = JSON.parse(readFileSync(join(extensionRoot, 'package.json'), 'utf8')) as { bioSteward: { testedWithCli: string } };
const version = bioSteward.testedWithCli;

const install = (...args: string[]) => spawnSync(process.execPath, [script, '--dry-run', ...args], { cwd: extensionRoot, encoding: 'utf8' });
// The pure choice, as the script makes it.
function choose(requested: string, hasLocal: boolean): { sources?: string[]; error?: string } {
  const code = `import { chooseSources } from ${JSON.stringify(join(extensionRoot, 'scripts', 'release-source.mjs'))};
try { console.log(JSON.stringify({ sources: chooseSources(${JSON.stringify(requested)}, ${hasLocal}) })); }
catch (error) { console.log(JSON.stringify({ error: error.message })); }`;
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', code], { encoding: 'utf8' });
  return JSON.parse(r.stdout) as { sources?: string[]; error?: string };
}
// Whether the repository holding this extension has the pinned release tag (a shallow CI clone may not).
const localTag = spawnSync('git', ['rev-parse', '--verify', '--quiet', `refs/tags/v${version}^{commit}`], { cwd: extensionRoot, encoding: 'utf8' }).status === 0;

describe('cli:install, the choice of source (E01)', () => {
  it('chooses the local tag alone when the enclosing repository has it; otherwise PyPI, then the public tag', () => {
    assert.deepEqual(choose('auto', true).sources, ['local']);
    assert.deepEqual(choose('auto', false).sources, ['pypi', 'tag']);
    for (const source of ['local', 'pypi', 'tag']) assert.deepEqual(choose(source, true).sources, [source]);
    assert.deepEqual(choose('pypi', false).sources, ['pypi']);
    assert.match(choose('local', false).error ?? '', /no tag/);
    assert.match(choose('github', true).error ?? '', /--source must be local, pypi, tag or auto/);
  });

  it('outside a repository with the tag, falls back to PyPI, then the public tag, and names them', () => {
    const elsewhere = mkdtempSync(join(tmpdir(), 'steward-cli-install-'));
    try {
      const r = install('--repo', elsewhere);
      assert.equal(r.status, 0, r.stderr);
      assert.match(r.stdout, new RegExp(`from PyPI \\(bio-steward==${version.replaceAll('.', '\\.')}\\), then https://github\\.com/\\S+ tag v${version}`));
      assert.match(r.stdout, /source pypi \(no local tag/);
      const local = install('--repo', elsewhere, '--source', 'local');
      assert.equal(local.status, 1);
      assert.match(local.stderr, new RegExp(`no tag v${version.replaceAll('.', '\\.')}`));
      assert.match(install('--source', 'tag', '--repo', elsewhere).stdout, /source tag/);
    } finally {
      rmSync(elsewhere, { recursive: true, force: true });
    }
  });

  it('in this repository, installs from the local tag and names no github.com source', function () {
    if (!localTag) this.skip();
    const r = install();
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, new RegExp(`from the local release tag v${version.replaceAll('.', '\\.')} \\([0-9a-f]{40}, git archive`));
    assert.match(r.stdout, /^cli:install: source local /m);
    assert.doesNotMatch(r.stdout, /github\.com|git\+https|pypi/i, 'no request to github.com or PyPI is planned');
    console.log(`    ${r.stdout.trim().split('\n')[1]}`);
  });

  it('refuses an unknown --source', () => {
    const r = install('--source', 'github');
    assert.equal(r.status, 1);
    assert.match(r.stderr, /--source must be local, pypi, tag or auto, not github/);
  });
});
