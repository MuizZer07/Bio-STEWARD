// `npm run package`: build the .vsix with `vsce package --no-dependencies` (it never publishes), byte for byte the
// same for the same commit (design v0.1 §10.5: same commit, same hash).
//
// vsce stamps every zip entry with the file's modification time unless SOURCE_DATE_EPOCH is set; then it uses that
// time for every entry and sorts the entries. This script sets it to the commit time of HEAD (git log -1 %ct), so a
// fresh checkout, a rebuild or another worktree of the same commit gives the same bytes. Without git it uses
// SOURCE_DATE_EPOCH from the environment, or refuses.
//
//   npm run package                  build bio-steward-<version>.vsix and print its SHA-256
//   npm run package -- --twice       build it twice and exit 1 if the two differ
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const { version } = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'));
const target = `bio-steward-${version}.vsix`;

function epoch() {
  if (process.env.SOURCE_DATE_EPOCH) return process.env.SOURCE_DATE_EPOCH;
  try {
    return execFileSync('git', ['-c', 'core.fsmonitor=false', 'log', '-1', '--format=%ct', 'HEAD'],
      { cwd: here, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    console.error('No git commit to take the time from: set SOURCE_DATE_EPOCH.');
    process.exit(2);
  }
}

const sde = epoch();
if (!/^\d+$/.test(sde)) {
  console.error(`SOURCE_DATE_EPOCH is not a number of seconds: ${sde}`);
  process.exit(2);
}

function build(out) {
  const vsce = join(here, 'node_modules', '@vscode', 'vsce', 'vsce');
  const r = spawnSync(process.execPath, [vsce, 'package', '--no-dependencies', '--out', out],
    { cwd: here, stdio: 'inherit', env: { ...process.env, SOURCE_DATE_EPOCH: sde } });
  if (r.status !== 0) process.exit(r.status ?? 1);
  return createHash('sha256').update(readFileSync(join(here, out))).digest('hex');
}

const first = build(target);
console.log(`SOURCE_DATE_EPOCH=${sde} (${new Date(Number(sde) * 1000).toISOString()})`);
console.log(`sha256 ${first}  ${target}`);
if (process.argv.includes('--twice')) {
  const again = `bio-steward-${version}.second-build.vsix`;
  const second = build(again);
  rmSync(join(here, again));
  console.log(`sha256 ${second}  (second build)`);
  if (first !== second) {
    console.error('The two builds differ.');
    process.exit(1);
  }
  console.log('The two builds are byte-identical.');
}
