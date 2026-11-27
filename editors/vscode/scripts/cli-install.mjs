#!/usr/bin/env node
// `npm run cli:install`: install the pinned CLI release, bio-steward==<testedWithCli>, into editors/vscode/.cli/,
// an environment of its own (rule G2). The tests use this program and never the checkout's src/.
//
// Source, in order: PyPI; until bio-steward is on PyPI, the public repository's release tag v<testedWithCli>.
// Uses `uv` when it is on PATH, otherwise `python3 -m venv` and pip. No shell is involved.
//
//   node scripts/cli-install.mjs              install unless .cli/ already holds the pinned version
//   node scripts/cli-install.mjs --force      remove .cli/ and install again
//   node scripts/cli-install.mjs --source pypi|tag    use one source only
//   node scripts/cli-install.mjs --print-path         print the path of the installed steward and exit
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPOSITORY = 'https://github.com/MuizZer07/Bio-STEWARD';
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
const force = args.includes('--force');
const sourceArg = args.includes('--source') ? args[args.indexOf('--source') + 1] : 'auto';
if (!['auto', 'pypi', 'tag'].includes(sourceArg)) fail(`--source must be pypi, tag or auto, not ${sourceArg}`);

if (args.includes('--print-path')) {
  console.log(stewardPath);
  process.exit(0);
}

const requirements = {
  pypi: `bio-steward==${version}`,
  tag: `bio-steward @ git+${REPOSITORY}@v${version}`,
};

function fail(message) {
  console.error(`cli:install: ${message}`);
  process.exit(1);
}

function run(file, argv, { quiet = false } = {}) {
  return execFileSync(file, argv, {
    cwd: extensionRoot,
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

function install(requirement) {
  try {
    if (useUv) {
      run('uv', ['pip', 'install', '--quiet', '--python', pythonPath, requirement]);
    } else {
      run(pythonPath, ['-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', requirement]);
    }
    return true;
  } catch {
    return false;
  }
}

const sources = sourceArg === 'auto' ? ['pypi', 'tag'] : [sourceArg];
let installedFrom;
for (const source of sources) {
  console.log(`cli:install: installing ${requirements[source]}`);
  if (install(requirements[source])) {
    installedFrom = source;
    break;
  }
  console.log(`cli:install: ${source === 'pypi' ? 'PyPI' : 'the release tag'} did not provide it`);
}
if (!installedFrom) fail(`could not install bio-steward ${version} from ${sources.join(' or ')}`);

const got = installedVersion();
if (got !== expected) fail(`installed program reports ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
console.log(`cli:install: ${got} installed from ${installedFrom === 'pypi' ? 'PyPI' : `${REPOSITORY} tag v${version}`}`);
console.log(`cli:install: program ${stewardPath}`);
