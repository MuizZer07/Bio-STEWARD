#!/usr/bin/env node
// `npm run cli:install`: install the pinned CLI release, bio-steward==<testedWithCli>, into editors/vscode/.cli/,
// an environment of its own (rule G2). The tests use this program and never the checkout's src/.
//
// Source (scripts/release-source.mjs): the release tag v<testedWithCli> of the enclosing git repository when it has
// it (its tree from `git archive` into a temporary folder, then installed from there: nothing is fetched from the
// public repository); otherwise PyPI, then the public repository's release tag. The output names the source used.
// Uses `uv` when it is on PATH, otherwise `python3 -m venv` and pip. No shell is involved.
//
//   node scripts/cli-install.mjs                           install unless .cli/ already holds the pinned version
//   node scripts/cli-install.mjs --force                   remove .cli/ and install again
//   node scripts/cli-install.mjs --source local|pypi|tag   use one source only
//   node scripts/cli-install.mjs --dry-run                 print the source that would be used, install nothing
//   node scripts/cli-install.mjs --repo DIR                look for the tag in the git repository holding DIR
//   node scripts/cli-install.mjs --print-path              print the path of the installed steward and exit
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chooseSources, localTag, REPOSITORY, sourceName } from './release-source.mjs';

const PYTHON_VERSION = '>=3.11';

const extensionRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const envDir = join(extensionRoot, '.cli');
const windows = process.platform === 'win32';
const binDir = join(envDir, windows ? 'Scripts' : 'bin');
const stewardPath = join(binDir, windows ? 'steward.exe' : 'steward');
const pythonPath = join(binDir, windows ? 'python.exe' : 'python');

const manifest = JSON.parse(readFileSync(join(extensionRoot, 'package.json'), 'utf8'));
const version = manifest.bioSteward?.testedWithCli;
if (!/^\d+\.\d+\.\d+$/.test(version ?? '')) {
  fail(`package.json bioSteward.testedWithCli is not a version: ${JSON.stringify(version)}`);
}

const args = process.argv.slice(2);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const force = args.includes('--force');
const dryRun = args.includes('--dry-run');
const sourceArg = option('--source') ?? 'auto';
const repoDir = resolve(option('--repo') ?? extensionRoot);

if (args.includes('--print-path')) {
  console.log(stewardPath);
  process.exit(0);
}

function fail(message) {
  console.error(`cli:install: ${message}`);
  process.exit(1);
}

const local = localTag(repoDir, version);
let sources;
try {
  sources = chooseSources(sourceArg, Boolean(local));
} catch (error) {
  fail(error.message.replace('<version>', version));
}

if (dryRun) {
  console.log(`cli:install: steward ${version} would be installed from ${sources.map((s) => sourceName(s, version, local)).join(', then ')}`);
  console.log(`cli:install: source ${sources[0]}${local ? ` (tag found in ${local.repository})` : ' (no local tag v' + version + ')'}`);
  process.exit(0);
}

function run(file, argv, { quiet = false, cwd = extensionRoot } = {}) {
  return execFileSync(file, argv, {
    cwd,
    encoding: 'utf8',
    stdio: quiet ? ['ignore', 'pipe', 'pipe'] : ['ignore', 'pipe', 'inherit'],
  });
}

function onPath(program) {
  try {
    run(program, ['--version'], { quiet: true });
    return true;
  } catch {
    return false;
  }
}

function installedVersion() {
  if (!existsSync(stewardPath)) return undefined;
  try {
    return run(stewardPath, ['--version'], { quiet: true }).trim();
  } catch {
    return undefined;
  }
}

const expected = `steward ${version}`;
if (!force && installedVersion() === expected) {
  console.log(`cli:install: ${expected} already in ${envDir}`);
  process.exit(0);
}

rmSync(envDir, { recursive: true, force: true });
const useUv = onPath('uv');
console.log(`cli:install: creating ${envDir} with ${useUv ? 'uv' : 'python3 -m venv'}`);
if (useUv) {
  run('uv', ['venv', '--quiet', '--python', PYTHON_VERSION, envDir]);
} else {
  run(windows ? 'python' : 'python3', ['-m', 'venv', envDir]);
}

function pipInstall(requirement) {
  if (useUv) {
    run('uv', ['pip', 'install', '--quiet', '--python', pythonPath, requirement]);
  } else {
    run(pythonPath, ['-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', requirement]);
  }
}

// The tag's tree, written by `git archive` into a temporary folder and installed from there (a plain folder, not a
// git URL: pip and uv never look for a remote).
function installLocal() {
  const scratch = mkdtempSync(join(tmpdir(), 'steward-cli-release-'));
  try {
    const tree = join(scratch, `bio-steward-${version}`);
    mkdirSync(tree);
    const tar = execFileSync('git', ['archive', '--format=tar', local.ref], { cwd: local.repository, maxBuffer: 512 * 1024 * 1024 });
    execFileSync('tar', ['-x', '-f', '-', '-C', tree], { input: tar });
    pipInstall(tree);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

const requirements = {
  pypi: `bio-steward==${version}`,
  tag: `bio-steward @ git+${REPOSITORY}@v${version}`,
};

let installedFrom;
for (const source of sources) {
  console.log(`cli:install: installing from ${sourceName(source, version, local)}`);
  try {
    if (source === 'local') installLocal();
    else pipInstall(requirements[source]);
    installedFrom = source;
    break;
  } catch {
    console.log(`cli:install: ${sourceName(source, version, local)} did not provide it`);
  }
}
if (!installedFrom) fail(`could not install bio-steward ${version} from ${sources.join(' or ')}`);

const got = installedVersion();
if (got !== expected) fail(`installed program reports ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
console.log(`cli:install: ${got} installed from ${sourceName(installedFrom, version, local)}`);
console.log(`cli:install: source ${installedFrom}`);
console.log(`cli:install: program ${stewardPath}`);
