// Host-test configuration for @vscode/test-cli (`npm run test:host`).
//
// Feasibility finding F2:
// - the test host fails with `listen EINVAL` when its user-data folder path is longer than about 103 characters,
//   which a sprint worktree easily is, so every run gets a short temporary `--user-data-dir`;
// - VS Code (about 370 MB) is downloaded once into a folder shared by all worktrees, not once per worktree.
//   Set BIOSTEWARD_VSCODE_TEST_CACHE to choose that folder.
//
// The example workspaces come from the fixture generator and the pinned CLI (G2).
// Without .cli/, the suites that do not require the pinned CLI still run.
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, platform, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig } from '@vscode/test-cli';
import { downloadAndUnzipVSCode } from '@vscode/test-electron';
import { buildSprintWorkspace } from './scripts/sprint-workspace.mjs';

// The VS Code release the host tests run in (stable on 2026-11-26, as in the feasibility record).
const VSCODE_VERSION = '1.148.0';

const cachePath = process.env.BIOSTEWARD_VSCODE_TEST_CACHE || join(homedir(), '.cache', 'bio-steward-vscode-test');
const shortTmp = platform() === 'win32' ? tmpdir() : '/tmp';
const scratch = mkdtempSync(join(shortTmp, 'bsvw-'));
process.on('exit', () => rmSync(scratch, { recursive: true, force: true }));

const windows = platform() === 'win32';
const steward = resolve('.cli', windows ? 'Scripts' : 'bin', windows ? 'steward.exe' : 'steward');
const cli = existsSync(steward) ? steward : '';
const examples = cli ? ['geo', 'toy', 'fresh', 'multi', 'init', 'offline-geo', 'offline-toy', 'cockpit', 'multi-cockpit'] : ['empty'];
if (cli) {
  const made = spawnSync(process.execPath, ['scripts/fixtures.mjs', '--workspaces', scratch], { stdio: 'inherit' });
  if (made.status !== 0) throw new Error(`could not prepare the CLI fixture workspaces (${made.status})`);
  // T12 (T11-07): a clean copy of the GEO example for the freshness watcher and on-save tests only, so no other
  // test's late file events reach the project they measure.
  cpSync(join(scratch, 'geo'), join(scratch, 'fresh'), { recursive: true });
  // S2 (T06): a multi-root workspace with copies of both examples, so its runs never touch the other suites' folders.
  const multi = join(scratch, 'multi');
  mkdirSync(multi);
  for (const name of ['geo', 'toy']) cpSync(join(scratch, name), join(multi, name), { recursive: true });
  writeFileSync(join(multi, 'multi.code-workspace'), JSON.stringify({ folders: [{ path: 'geo' }, { path: 'toy' }] }, null, 2));
  // U02: Today and Where am I? on the U01 cockpit workspace (its peer stays beside it, as its [exchange] names
  // it), and three projects in one window: geo (nothing pending), geo-cockpit-peer and geo-cockpit, in that order.
  cpSync(join(scratch, 'geo-cockpit'), join(scratch, 'cockpit', 'geo-cockpit'), { recursive: true });
  cpSync(join(scratch, 'geo-cockpit-peer'), join(scratch, 'cockpit', 'geo-cockpit-peer'), { recursive: true });
  const multiCockpit = join(scratch, 'multi-cockpit');
  for (const name of ['geo', 'geo-cockpit-peer', 'geo-cockpit']) cpSync(join(scratch, name), join(multiCockpit, name), { recursive: true });
  writeFileSync(join(multiCockpit, 'multi.code-workspace'), JSON.stringify({
    folders: [{ path: 'geo' }, { path: 'geo-cockpit-peer' }, { path: 'geo-cockpit' }] }, null, 2));
  mkdirSync(join(scratch, 'init'));
  for (const name of ['geo', 'toy']) {
    const offline = join(scratch, `offline-${name}`);
    cpSync(join(scratch, name), offline, { recursive: true });
    // Restore this config in the test, after the network guard is installed and before activation.
    renameSync(join(offline, 'steward.toml'), join(offline, 'fixture.toml'));
  }
} else {
  mkdirSync(join(scratch, 'empty'));
  console.log('test:host: no .cli/bin/steward (run `npm run cli:install`); the tests that need the CLI are pending');
}
// S9 (T13): the live sprint view needs git, not the CLI, so its workspace is made in both cases.
if (spawnSync('git', ['--version']).status === 0) {
  buildSprintWorkspace(join(scratch, 'sprint'));
  examples.push('sprint');
} else {
  console.log('test:host: no git on PATH; the live sprint view tests are not run');
}
const restricted = join(scratch, 'restricted');
mkdirSync(restricted);
writeFileSync(join(restricted, 'steward.toml'), '');
const spy = join(scratch, 'steward-spy');
const calls = join(scratch, 'steward-calls');
writeFileSync(spy, '#!/bin/sh\nprintf "%s\\n" "$*" >> "$BIO_STEWARD_TEST_CLI_CALLS"\n', { mode: 0o700 });
examples.push('restricted');
const vscodeExecutable = await downloadAndUnzipVSCode({ version: VSCODE_VERSION, cachePath });
// @vscode/test-electron adds --disable-workspace-trust to every launch. Drop it for this profile only.
const trustLauncher = join(scratch, 'vscode-with-trust');
writeFileSync(trustLauncher, `#!/bin/bash
args=()
for arg in "$@"; do
  if [[ "$arg" != --disable-workspace-trust ]]; then args+=("$arg"); fi
done
exec "$BIO_STEWARD_TEST_VSCODE" "\${args[@]}"
`, { mode: 0o700 });
export default defineConfig(examples.map((example) => {
  const userDataDir = mkdtempSync(join(shortTmp, 'bsvt-'));
  process.on('exit', () => rmSync(userDataDir, { recursive: true, force: true }));
  mkdirSync(join(userDataDir, 'User'), { recursive: true });
  const isRestricted = example === 'restricted';
  const offline = example.startsWith('offline-');
  const hardening = isRestricted || offline;
  let workspaceFolder = example === 'multi' || example === 'multi-cockpit' ? join(scratch, example, 'multi.code-workspace')
    : example === 'cockpit' ? join(scratch, 'cockpit', 'geo-cockpit') : join(scratch, example);
  if (offline) {
    // Workspace settings must never override the machine's executable, even in trusted workspaces.
    workspaceFolder = join(scratch, `${example}.code-workspace`);
    writeFileSync(workspaceFolder, JSON.stringify({
      folders: [{ path: example }],
      settings: { 'bioSteward.cliPath': spy },
    }));
  }
  writeFileSync(join(userDataDir, 'User', 'settings.json'), JSON.stringify({
    'security.workspace.trust.enabled': isRestricted,
    'security.workspace.trust.startupPrompt': 'never',
    'security.workspace.trust.banner': 'always',
    'bioSteward.cliPath': isRestricted ? spy : cli,
    'bioSteward.registry': 'disable',
  }, null, 2));
  return {
    label: hardening ? example : `trusted-${example}`,
    files: hardening ? 'out/test/host/hardening.test.js' : 'out/test/host/**/*.test.js',
    version: VSCODE_VERSION,
    useInstallation: { fromPath: isRestricted ? trustLauncher : vscodeExecutable },
    workspaceFolder,
    launchArgs: ['--user-data-dir', userDataDir, '--disable-extensions'],
    env: { BIO_STEWARD_TEST_EXAMPLE: example, BIO_STEWARD_TEST_CLI_CALLS: `${calls}-${example}`,
      BIO_STEWARD_TEST_VSCODE: vscodeExecutable },
    mocha: { ui: 'bdd', timeout: 20000 },
  };
}));
