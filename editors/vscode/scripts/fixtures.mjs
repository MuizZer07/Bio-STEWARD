#!/usr/bin/env node
// `npm run fixtures`: generate test/fixtures/ and src/schemas/ from the pinned CLI (RELEASE_vscode_0.1.0_SPEC §4,
// task T03). Nothing in test/fixtures/ is written by hand: every report is what `steward check` printed, with only
// the run-specific envelope fields replaced (see NORMALISED below), and every derived file (invalid JSON, oversized
// report) is computed here from such a report.
//
// Sources (rule G2, findings F3 and F4):
//   - the program installed by `npm run cli:install` (.cli/), which must report `steward <testedWithCli>`;
//   - the public repository at tag v<testedWithCli>, cloned once into .cli/release-v<version>/: the report schema
//     (schemas/steward.report-0.1.schema.json, copied byte for byte) and examples/toy-expression-benchmark
//     (`git archive`), which the wheel does not contain;
//   - `steward example biology` for the GEO example.
// The checkout's own src/, schemas/ and examples/ are never read.
//
// The reduced panels of 0.2.0 (RELEASE_vscode_0.2.0_SPEC §3, task U01) add test/fixtures/cockpit/: what 0.20.6 prints
// for `audit progress --json`, `timeline --json`, `tokens report --json` (no source, an empty source, a log with
// records) and `authorize pending` (with and without --all-projects), run on the plain GEO example and on two
// workspaces made for them (geo-cockpit and its peer: exchange items, a signing queue, a task board whose Status
// lines vary, milestones in five states, a sprint plan). Every workspace change is made with the CLI's own commands
// where one exists; only the task files, the board, the milestones file and the configuration tables are written
// here, as a user would write them. See COCKPIT_NORMALISED for the two values that are replaced.
//
//   node scripts/fixtures.mjs                    write test/fixtures/ and src/schemas/
//   node scripts/fixtures.mjs --verify           regenerate in a scratch folder; exit 1 if anything committed differs
//   node scripts/fixtures.mjs --workspaces DIR   build the fixture workspaces (example copies, seeded faults) in DIR
//   node scripts/fixtures.mjs --keep             keep the scratch folder and print its path
import { Buffer } from 'node:buffer';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const REPOSITORY = 'https://github.com/MuizZer07/Bio-STEWARD';
const SCHEMA_PATH = 'schemas/steward.report-0.1.schema.json';
const TOY_PATH = 'examples/toy-expression-benchmark';
// The bounded reader's limit (src/cli/output.ts, design §5 "default limit 20 MB").
const OUTPUT_LIMIT = 20 * 1024 * 1024;

// Fields of the envelope that differ from run to run and machine to machine. They are replaced by these constants,
// which still satisfy the schema; everything else is the CLI's output unchanged.
const NORMALISED = {
  created: '2000-01-01T00:00:00Z',
  git: { dirty: 'not checked', head: '0000000000000000000000000000000000000000' },
  platform: { os: 'fixture', python: 'fixture' },
};
// The repo_id given to every copy of the GEO example (see baseGeo).
const FIXED_REPO_ID = '00000000-0000-4000-8000-000000000000';
// Fixed identity and dates for the commits this script makes, so a workspace is the same on every machine.
const GIT_ENV = {
  GIT_AUTHOR_NAME: 'fixtures', GIT_AUTHOR_EMAIL: 'fixtures@example.invalid', GIT_AUTHOR_DATE: '2000-01-01T00:00:00Z',
  GIT_COMMITTER_NAME: 'fixtures', GIT_COMMITTER_EMAIL: 'fixtures@example.invalid',
  GIT_COMMITTER_DATE: '2000-01-01T00:00:00Z', GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1',
};

// The cockpit outputs (U01). A milestone's days_left is measured from the moment the CLI runs, so it is recomputed
// from its due time as of COCKPIT_NOW; a prepared payload's nonce is random, so each queued payload is renamed to a
// fixed nonce (its file name and its nonce line, the two places the CLI reads it from) before anything lists it.
const COCKPIT_NOW = '2026-11-27T00:00:00Z';
const COCKPIT_NORMALISED = {
  days_left: `each milestones[].days_left (timeline) and pending.milestones[].days_left (audit progress) is ` +
    `(due - ${COCKPIT_NOW}) in days, rounded to 0.1 as the CLI rounds it; the CLI measures it from its own clock. ` +
    'The states are not changed: every due date is in 2000 - 2001 or in 2099, so they hold until 2099-05-18.',
  nonce: 'each payload `steward authorize prepare` queued in .steward/pending/ is renamed to the nonce ' +
    'sha256("fixture-nonce:<workspace>:<label>")[:32] (file name and nonce line) before it is listed',
  paths: 'the scratch folder is replaced by <workspace> or <inputs> in argv; no output names it',
};
// The peer gets its own repo_id, so the two projects of --all-projects are two repositories.
const PEER_REPO_ID = '00000000-0000-4000-8000-000000000001';

const extensionRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const fixturesDir = join(extensionRoot, 'test', 'fixtures');
const schemaCopy = join(extensionRoot, 'src', ...SCHEMA_PATH.split('/'));
const windows = process.platform === 'win32';
const steward = join(extensionRoot, '.cli', windows ? 'Scripts' : 'bin', windows ? 'steward.exe' : 'steward');

const manifest = JSON.parse(readFileSync(join(extensionRoot, 'package.json'), 'utf8'));
const version = manifest.bioSteward?.testedWithCli;
const releaseDir = join(extensionRoot, '.cli', `release-v${version}`);

const args = process.argv.slice(2);
const verify = args.includes('--verify');
const keep = args.includes('--keep');
const workspacesArg = args.includes('--workspaces') ? args[args.indexOf('--workspaces') + 1] : undefined;
if (args.includes('--workspaces') && !workspacesArg) fail('--workspaces needs a folder');

function fail(message) {
  console.error(`fixtures: ${message}`);
  process.exit(1);
}

function run(file, argv, options = {}) {
  return execFileSync(file, argv, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...options });
}

function git(cwd, argv, options = {}) {
  return run('git', argv, { cwd, env: { ...process.env, ...GIT_ENV }, ...options });
}

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

// ---------------------------------------------------------------------------------------------------------------
// Sources

function checkCli() {
  if (!/^\d+\.\d+\.\d+$/.test(version ?? '')) fail(`package.json bioSteward.testedWithCli is not a version: ${version}`);
  if (!existsSync(steward)) fail(`no CLI in ${dirname(steward)}; run \`npm run cli:install\` first`);
  const got = run(steward, ['--version']).trim();
  if (got !== `steward ${version}`) fail(`${steward} reports ${JSON.stringify(got)}, expected "steward ${version}"`);
  console.log(`fixtures: using ${got} (${steward})`);
}

function releaseSource() {
  const tag = `v${version}`;
  if (!existsSync(join(releaseDir, '.git'))) {
    rmSync(releaseDir, { recursive: true, force: true });
    console.log(`fixtures: cloning ${REPOSITORY} at ${tag} into ${releaseDir}`);
    run('git', ['clone', '--quiet', '--depth', '1', '--branch', tag, '--', `${REPOSITORY}.git`, releaseDir]);
  }
  const commit = git(releaseDir, ['rev-parse', 'HEAD']).trim();
  const tagged = git(releaseDir, ['rev-parse', `refs/tags/${tag}^{commit}`]).trim();
  if (commit !== tagged) fail(`${releaseDir} is not at ${tag}; remove it and run again`);
  return { tag, commit };
}

function releaseFile(path) {
  return execFileSync('git', ['show', `HEAD:${path}`], { cwd: releaseDir, maxBuffer: 64 * 1024 * 1024 });
}

// ---------------------------------------------------------------------------------------------------------------
// Workspaces: the two worked examples and their seeded faults

function commitAll(dir, message) {
  git(dir, ['add', '--all']);
  git(dir, ['commit', '--quiet', '--allow-empty', '--no-gpg-sign', '-m', message]);
}

function baseGeo(dest) {
  const result = spawnSync(steward, ['example', 'biology', dest], {
    encoding: 'utf8', env: { ...process.env, ...GIT_ENV, STEWARD_NO_REGISTRY: '1' },
  });
  if (result.status !== 0) fail(`steward example biology failed (${result.status}): ${result.stderr}`);
  // `steward example` writes a new repo_id into each copy; a fixed one makes steward.toml, and so every digest,
  // the same on every run. Committed like a user's own first change would be.
  edit(dest, 'steward.toml', (text) => text.replace(/^repo_id = "[0-9a-f-]{36}"/m, `repo_id = "${FIXED_REPO_ID}"`));
  commitAll(dest, 'fixtures: fixed repo_id');
}

function baseToy(dest) {
  mkdirSync(dest, { recursive: true });
  const tar = execFileSync('git', ['archive', '--format=tar', `HEAD:${TOY_PATH}`],
    { cwd: releaseDir, maxBuffer: 64 * 1024 * 1024 });
  execFileSync('tar', ['-x', '-f', '-', '-C', dest], { input: tar });
  git(dest, ['init', '--quiet', '--initial-branch=main']);
  commitAll(dest, 'toy-expression-benchmark from the release tag');
}

function edit(dir, path, change) {
  const file = join(dir, path);
  const before = readFileSync(file, 'utf8');
  const after = change(before);
  if (after === before) fail(`seeding ${path} changed nothing; the example differs from what this script expects`);
  writeFileSync(file, after);
}

function replaceOnce(text, from, to) {
  if (!text.includes(from)) return text;
  return text.replace(from, to);
}

// ---------------------------------------------------------------------------------------------------------------
// The cockpit workspaces (U01)

// A per-user folder of the CLI's own (trust pins, the project registry), empty and private to this run, so nothing
// of the machine running the script reaches a fixture.
let configHomeDir;
function configHome() {
  if (!configHomeDir) {
    configHomeDir = realpathSync(mkdtempSync(join(tmpdir(), 'steward-fixtures-home-')));
    process.on('exit', () => rmSync(configHomeDir, { recursive: true, force: true }));
  }
  return configHomeDir;
}

const cockpitEnv = () => ({ ...process.env, ...GIT_ENV, STEWARD_NO_REGISTRY: '1', STEWARD_CONFIG_HOME: configHome() });

function stewardIn(dir, argv) {
  const result = spawnSync(steward, argv, { cwd: dir, encoding: 'utf8', env: cockpitEnv(), maxBuffer: 64 * 1024 * 1024 });
  if (result.error) fail(`steward ${argv.join(' ')}: ${result.error.message}`);
  return result;
}

function stewardOk(dir, argv) {
  const result = stewardIn(dir, argv);
  if (result.status !== 0) fail(`steward ${argv.join(' ')} failed (${result.status}): ${result.stderr || result.stdout}`);
  return result;
}

const append = (dir, path, text) => edit(dir, path, (before) => `${before.replace(/\n*$/, '\n')}${text}`);

function write(dir, path, text) {
  mkdirSync(dirname(join(dir, path)), { recursive: true });
  writeFileSync(join(dir, path), text);
}

const fixedNonce = (workspace, label) => sha256(`fixture-nonce:${workspace}:${label}`).slice(0, 32);

// `steward authorize prepare`, then the queued payload renamed to its fixed nonce (COCKPIT_NORMALISED.nonce).
function prepare(dir, workspace, label, { expires, summary }) {
  const queue = join(dir, '.steward', 'pending');
  const before = new Set(existsSync(queue) ? readdirSync(queue) : []);
  stewardOk(dir, ['authorize', 'prepare', 'spend', '--object', 'README.md', '--expires', expires, '--summary', summary]);
  const added = readdirSync(queue).filter((name) => !before.has(name));
  if (added.length !== 1 || !/^[0-9a-f]{32}\.txt$/.test(added[0])) fail(`authorize prepare queued ${added.join(', ')}`);
  const random = added[0].slice(0, 32);
  const nonce = fixedNonce(workspace, label);
  const text = readFileSync(join(queue, added[0]), 'utf8');
  if (!text.includes(`\nnonce: ${random}\n`)) fail('a prepared payload has no nonce line; the payload format changed');
  writeFileSync(join(queue, `${nonce}.txt`), text.replace(`\nnonce: ${random}\n`, `\nnonce: ${nonce}\n`));
  rmSync(join(queue, added[0]));
}

// The task files of geo-cockpit: Status lines as a user writes them, a configured status, a status with a qualifier
// after a dash or in brackets, one the board does not configure, and a file without a Status line (AC-P3).
const TASK_FILES = [
  { path: 'development/tasks/GEO-001-load-series.md', id: 'GEO-001', title: 'Load the series', status: 'in progress' },
  { path: 'development/tasks/GEO-002-normalise.md', id: 'GEO-002', title: 'Normalise the arrays', status: 'done' },
  { path: 'development/tasks/GEO-003-annotate.md', id: 'GEO-003', title: 'Annotate the probes',
    status: 'blocked — waiting on the annotation release' },
  { path: 'development/tasks/GEO-004-figures.md', id: 'GEO-004', title: 'Draw the figures', status: 'in review (left: CI)' },
  { path: 'development/tasks/GEO-005-methods.md', id: 'GEO-005', title: 'Write the methods', status: 'GO recorded' },
  { path: 'development/tasks/GEO-006-notes.md', id: 'GEO-006', title: 'Collect notes', status: null },
];

const taskFile = ({ id, title, status }) => [
  `# ${id}: ${title}`, '', `- **ID:** ${id}`, ...(status === null ? [] : [`- **Status:** ${status}`]),
  '- **Owner:** fixtures', '', '## Work', '', 'Written by scripts/fixtures.mjs for the reduced Tasks panel.', '',
].join('\n');

const BOARD = [
  '# Task board', '', 'Next unused ID: GEO-007', '', '| ID | Title |', '|---|---|',
  ...TASK_FILES.map(({ id, title }) => `| ${id} | ${title} |`), '',
].join('\n');

// One milestone per state 0.20.6 can be fixed in (met, due without an outcome, late, on track, ready); "at risk"
// depends on the day the CLI runs, so it is not among them (see not_generated).
const MILESTONES = `schema = "steward.milestones/0.1"

[[milestone]]
id = "kickoff"
title = "Kick-off"
due = 2000-03-01T00:00:00Z
outcome = { state = "met", decision = "development/DECISIONS.md, 2000-03-01", on = 2000-03-01 }

[[milestone]]
id = "abstract"
title = "Conference abstract"
kind = "submission"
due = 2000-06-01T00:00:00Z
tasks = ["GEO-002"]

[[milestone]]
id = "preprint"
title = "Preprint"
kind = "preprint"
due = 2001-01-01T00:00:00Z
tasks = ["GEO-001", "GEO-003"]

[[milestone]]
id = "review"
title = "Internal review"
kind = "review"
due = 2099-06-01T00:00:00Z
buffer_days = 14
tasks = ["GEO-001", "GEO-004", "GEO-005"]
needs = ["spend"]

[[milestone]]
id = "release"
title = "Data release"
kind = "release"
due = 2099-12-31T23:59:00-12:00
tasks = ["GEO-002"]
`;

function seedCockpitPeer(dir) {
  edit(dir, 'steward.toml', (text) => text.replace(`repo_id = "${FIXED_REPO_ID}"`, `repo_id = "${PEER_REPO_ID}"`));
  append(dir, 'steward.toml', '\n[exchange]\ncode = "PEER"\npeers = { GEO = "../geo-cockpit" }\n\n' +
    '[policy]\nbaseline = "HEAD"\n');
  commitAll(dir, 'fixtures: exchange and policy tables');
  stewardOk(dir, ['exchange', 'init']);
  stewardOk(dir, ['exchange', 'new', 'request', '--to', 'GEO', '--title', 'Add a gene-set enrichment table']);
  commitAll(dir, 'fixtures: a request to GEO');
  prepare(dir, 'geo-cockpit-peer', 'waiting', { expires: '2099-01-01T00:00:00Z', summary: 'Spend for the peer rerun' });
}

function seedCockpit(dir) {
  const peer = join(dirname(dir), 'geo-cockpit-peer');
  if (!existsSync(join(peer, 'exchange', 'outbox', 'PEER-REQ-001.md'))) fail('geo-cockpit needs geo-cockpit-peer first');
  append(dir, 'steward.toml', '\n[exchange]\ncode = "GEO"\n' +
    'peers = { PEER = "../geo-cockpit-peer", GONE = "../no-such-project" }\n\n' +
    '[policy]\nbaseline = "HEAD"\n\n' +
    '[tasks]\nspecs = ["development/tasks/*.md"]\nboard = "development/BOARD.md"\n');
  for (const task of TASK_FILES) write(dir, task.path, taskFile(task));
  write(dir, 'development/BOARD.md', BOARD);
  write(dir, 'development/milestones.toml', MILESTONES);
  commitAll(dir, 'fixtures: exchange, policy and task tables; task files; milestones');
  stewardOk(dir, ['exchange', 'init']);
  stewardOk(dir, ['exchange', 'new', 'question', '--to', 'PEER', '--title', 'Which annotation release do you use?']);
  stewardOk(dir, ['exchange', 'receive', join(peer, 'exchange', 'outbox', 'PEER-REQ-001.md')]);
  prepare(dir, 'geo-cockpit', 'waiting', { expires: '2099-01-01T00:00:00Z', summary: 'Spend for the model comparison' });
  prepare(dir, 'geo-cockpit', 'expired', { expires: '2000-01-02T00:00:00Z', summary: 'Spend for the first rerun' });
  stewardOk(dir, ['sprint', 'plan', 'fixture-sprint', '--from', 'board', '--start', '2099-01-05T09:00:00+00:00']);
}

// Files that hold the day or the time the CLI ran (the exchange ledger and item dates), or a commit made after
// such a file (a payload's baseline): their names are recorded, their bytes are not compared.
const VOLATILE = (rel) => /^exchange\/(log\.jsonl|(inbox|outbox|oneway|responses)\/[^/]+\.md)$/.test(rel) ||
  rel.startsWith('.steward/pending/');
const VOLATILE_MARK = 'not compared: written with the date or time of the run';

// Each workspace: a base example and the seeded change, applied and committed like a real mistake would be.
const WORKSPACES = {
  'geo': { base: 'geo', about: '`steward example biology`, unchanged' },
  'toy': { base: 'toy', about: 'examples/toy-expression-benchmark from the release tag, unchanged' },
  'geo-fail-date-symbol': {
    base: 'geo',
    about: 'FAIL at a file: a gene symbol in results/top_genes.tsv turned into a date (README "Break it on purpose")',
    seed: (dir) => edit(dir, 'results/top_genes.tsv', (text) => {
      const lines = text.split('\n');
      const header = lines[0].split('\t');
      const column = header.indexOf('gene_symbol');
      if (column < 0) return text;
      const row = lines[1].split('\t');
      row[column] = '7-Sep';
      lines[1] = row.join('\t');
      return lines.join('\n');
    }),
  },
  'geo-incomplete-accession': {
    base: 'geo',
    about: 'INCOMPLETE: both mentions of GSE7621 removed from paper/data-availability.md (README "Break it on purpose")',
    seed: (dir) => edit(dir, 'paper/data-availability.md', (text) => text.replaceAll('GSE7621', 'GSE-REMOVED')),
  },
  'toy-unknown-contract': {
    base: 'toy',
    about: 'UNKNOWN: the benchmark contract made invalid, so the rules that need it report "not evaluated"',
    seed: (dir) => {
      const contract = findFiles(dir, (rel) => rel.endsWith('.contract.toml'))[0];
      if (!contract) fail('the toy benchmark has no *.contract.toml');
      edit(dir, contract, (text) => `${text}\nnot_a_contract_key = true\n`);
    },
  },
  'geo-broken-config': {
    base: 'geo',
    about: 'a broken steward.toml: an unknown key in [steward]',
    seed: (dir) => edit(dir, 'steward.toml', (text) => replaceOnce(text, '[steward]\n', '[steward]\nnot_a_key = 1\n')),
  },
  // U01. The peer comes first: geo-cockpit receives its request and lists its signing queue.
  'geo-cockpit-peer': {
    base: 'geo',
    about: 'the peer PEER of geo-cockpit: its own repo_id, a request filed to GEO, one payload waiting for a signature',
    seed: seedCockpitPeer,
    commit: 'fixtures: the peer records',
    volatile: VOLATILE,
  },
  'geo-cockpit': {
    base: 'geo',
    about: 'the reduced panels\' workspace (code GEO): an open question to PEER, a request received from PEER, ' +
      'a waiting and an expired payload, a peer without a checkout (GONE), a task board whose Status lines vary ' +
      '(one file has none), milestones met / due / late / on track / ready, and a planned sprint',
    seed: seedCockpit,
    commit: 'fixtures: the cockpit records',
    volatile: VOLATILE,
  },
};

function findFiles(dir, accept, base = dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '.git') continue;
    const full = join(dir, entry.name);
    const rel = relative(base, full).split(sep).join('/');
    if (entry.isDirectory()) out.push(...findFiles(full, accept, base));
    else if (accept(rel)) out.push(rel);
  }
  return out.sort();
}

const bases = new Map();
function buildWorkspace(root, name) {
  const spec = WORKSPACES[name];
  const dest = join(root, name);
  rmSync(dest, { recursive: true, force: true });
  const cached = bases.get(spec.base);
  if (cached) {
    cpSync(cached, dest, { recursive: true, verbatimSymlinks: true });
  } else {
    (spec.base === 'geo' ? baseGeo : baseToy)(dest);
    const pristine = join(root, `.base-${spec.base}`);
    cpSync(dest, pristine, { recursive: true, verbatimSymlinks: true });
    bases.set(spec.base, pristine);
  }
  if (spec.seed) {
    spec.seed(dest);
    commitAll(dest, spec.commit ?? `seeded fault: ${name}`);
  }
  return dest;
}

// The files of a workspace other than .git, with their sha256: recorded so a test can tell which bytes a report
// describes, and so --verify notices when the example itself changes. A volatile file is named without its digest.
function digestTree(dir, volatile = () => false) {
  return Object.fromEntries(findFiles(dir, () => true).map((rel) =>
    [rel, volatile(rel) ? VOLATILE_MARK : sha256(readFileSync(join(dir, rel)))]));
}

// ---------------------------------------------------------------------------------------------------------------
// Reports

// `check` runs on each workspace; `scoped` adds a partial run, which never evaluates a gate.
const REPORTS = {
  'geo': { workspace: 'geo', args: [] },
  'toy': { workspace: 'toy', args: [] },
  'geo-fail-date-symbol': { workspace: 'geo-fail-date-symbol', args: [] },
  'geo-incomplete-accession': { workspace: 'geo-incomplete-accession', args: [] },
  'toy-unknown-contract': { workspace: 'toy-unknown-contract', args: [] },
  'geo-scoped-data': { workspace: 'geo-fail-date-symbol', args: ['data'], about: 'a scoped run (AREA data)' },
  'geo-scoped-rule': { workspace: 'geo-fail-date-symbol', args: ['--rule', 'R-83'], about: 'a scoped run (--rule R-83)' },
  'geo-broken-config': { workspace: 'geo-broken-config', args: [] },
};

function normalise(report, workspace) {
  const text = JSON.stringify(report);
  if (text.includes(workspace) || text.includes(realpathSync(workspace))) {
    fail(`a report names the scratch folder ${workspace}; it would not be reproducible`);
  }
  const envelope = report.envelope ?? {};
  for (const key of Object.keys(NORMALISED)) {
    if (!(key in envelope)) fail(`report envelope has no ${key}; the report format changed`);
  }
  return { ...report, envelope: { ...envelope, ...JSON.parse(JSON.stringify(NORMALISED)) } };
}

const canonical = (value) => `${JSON.stringify(value, null, 2)}\n`;

function runCheck(root, name, out) {
  const spec = REPORTS[name];
  const workspace = join(root, spec.workspace);
  const output = join(out, `${name}.raw.json`);
  const argv = ['check', '--repo', workspace, '--format', 'json', '--output', output, ...spec.args];
  const result = spawnSync(steward, argv, {
    encoding: 'utf8', env: { ...process.env, STEWARD_NO_REGISTRY: '1' }, maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) fail(`steward check on ${name}: ${result.error.message}`);
  const entry = {
    workspace: spec.workspace,
    argv: ['check', '--repo', '<workspace>', '--format', 'json', '--output', '<report>', ...spec.args],
    exit_code: result.status,
  };
  if (spec.about) entry.about = spec.about;
  if (existsSync(output)) {
    const report = normalise(JSON.parse(readFileSync(output, 'utf8')), workspace);
    entry.report = `reports/${name}.json`;
    entry.counts = report.verdict.summary.counts;
    entry.gates = report.verdict.gates.map((g) => ({ name: g.name, evaluated: g.evaluated, eligible: g.eligible,
      reason: g.reason }));
    return { entry, report };
  }
  // No report (for example a configuration error): the CLI's messages are the fixture, with the scratch folder
  // replaced by a placeholder.
  const scrub = (text) => text.replaceAll(realpathSync(workspace), '<workspace>').replaceAll(workspace, '<workspace>');
  entry.stdout = scrub(result.stdout);
  entry.stderr = scrub(result.stderr);
  return { entry };
}

// Derived from a real report: its bytes cut in half (invalid JSON), and its bytes followed by whitespace until the
// file exceeds the reader's limit (a document that would parse, but is too large), gzipped to keep the repository
// small (whitespace compresses to almost nothing).
function derived(report) {
  const text = canonical(report);
  const invalid = text.slice(0, Math.floor(text.length / 2));
  const padding = OUTPUT_LIMIT + 1 - Buffer.byteLength(text);
  const oversized = Buffer.concat([Buffer.from(text), Buffer.alloc(Math.max(padding, 1), ' ')]);
  return { invalid, oversized: gzipSync(oversized, { level: 9 }), oversizedBytes: oversized.length };
}

// ---------------------------------------------------------------------------------------------------------------
// The cockpit outputs (U01): what the reduced panels read, as 0.20.6 prints it

// Agent logs given to `tokens report` with --claude: inputs, kept next to the outputs so a test can read them.
// The session log is the smallest a Claude Code session writes for one answer and one Read: one assistant message
// with its usage and a Read call, and the tool result. Its times are in 2000, before every run of the CLI.
const COCKPIT_INPUTS = {
  'empty.jsonl': '',
  'claude-session.jsonl': [
    { type: 'assistant', sessionId: 'fixture-session', timestamp: '2000-01-01T10:00:00Z',
      message: { id: 'msg_fixture_1', model: 'claude-fixture', role: 'assistant',
        usage: { input_tokens: 100, output_tokens: 20, cache_read_input_tokens: 1000, cache_creation_input_tokens: 50 },
        content: [{ type: 'tool_use', id: 'toolu_fixture_1', name: 'Read', input: { file_path: 'README.md' } }] } },
    { type: 'user', sessionId: 'fixture-session', timestamp: '2000-01-01T10:00:01Z',
      message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'toolu_fixture_1', content: 'x'.repeat(300) }] } },
  ].map((row) => `${JSON.stringify(row)}\n`).join(''),
};

// Each output: the workspace, the arguments after `steward` (an { input } is a file of COCKPIT_INPUTS), and whether
// stdout is JSON or text. Every command runs with --repo <workspace>, from the workspace.
const COCKPIT = {
  'audit-progress/geo': { workspace: 'geo', argv: ['audit', 'progress', '--json'], format: 'json',
    about: 'P1 / P2 reduced, nothing pending: no exchange, no queue, no milestones, no sprints' },
  'audit-progress/geo-cockpit': { workspace: 'geo-cockpit', argv: ['audit', 'progress', '--json'], format: 'json',
    about: 'P1 / P2 reduced: open exchange items, own open requests, a signature waiting, milestones, a sprint ' +
      'with open tasks' },
  'timeline/geo': { workspace: 'geo', argv: ['timeline', '--json'], format: 'json', about: 'P7 reduced, no milestones' },
  'timeline/geo-cockpit': { workspace: 'geo-cockpit', argv: ['timeline', '--json'], format: 'json',
    about: 'P2 / P7 reduced: one milestone per state (met, due (record its outcome), late, on track, ready)' },
  'tokens-report/no-source': { workspace: 'geo-cockpit', argv: ['tokens', 'report', '--json'], format: 'json',
    about: 'P4, no source given: every agent unavailable with no files' },
  'tokens-report/empty-source': { workspace: 'geo-cockpit', format: 'json',
    argv: ['tokens', 'report', '--json', '--claude', { input: 'empty.jsonl' }],
    about: 'P4, a configured but empty source: an empty Claude log' },
  'tokens-report/claude-session': { workspace: 'geo-cockpit', format: 'json',
    argv: ['tokens', 'report', '--json', '--claude', { input: 'claude-session.jsonl' }],
    about: 'P4, a log with records: one model, a cache read and write, one Read and its output size' },
  'authorize-pending/geo': { workspace: 'geo', argv: ['authorize', 'pending'], format: 'text',
    about: 'P5 reduced, an empty queue' },
  'authorize-pending/geo-cockpit': { workspace: 'geo-cockpit', argv: ['authorize', 'pending'], format: 'text',
    about: 'P5 reduced: a waiting and an expired payload' },
  'authorize-pending/geo-cockpit-all-projects': { workspace: 'geo-cockpit', format: 'text',
    argv: ['authorize', 'pending', '--all-projects'],
    about: 'P5 reduced across projects: this queue, a peer without a checkout (skipped), the peer\'s waiting payload' },
};

const roundDays = (due) => Math.round(((Date.parse(due) - Date.parse(COCKPIT_NOW)) / 86400000) * 10) / 10;

// COCKPIT_NORMALISED.days_left, applied to the CLI's own text so that every other byte stays as it printed it.
function normaliseDays(text, values) {
  const pattern = /"days_left": -?\d+(\.\d+)?(e[+-]?\d+)?/g;
  const found = text.match(pattern) ?? [];
  if (found.length !== values.length) fail(`days_left: ${found.length} in the output, ${values.length} milestones`);
  let index = 0;
  return text.replace(pattern, () => `"days_left": ${values[index++].toFixed(1)}`);
}

function runCockpit(root, inputsDir, name, dues) {
  const spec = COCKPIT[name];
  const workspace = join(root, spec.workspace);
  const argv = spec.argv.map((a) => (typeof a === 'string' ? a : join(inputsDir, a.input)));
  const result = stewardIn(workspace, [...argv, '--repo', workspace]);
  const entry = {
    workspace: spec.workspace,
    argv: [...spec.argv.map((a) => (typeof a === 'string' ? a : `<inputs>/${a.input}`)), '--repo', '<workspace>'],
    exit_code: result.status, format: spec.format, about: spec.about,
  };
  if (result.status !== 0) fail(`${name}: steward ${entry.argv.join(' ')} exited ${result.status}: ${result.stderr}`);
  if (result.stderr) entry.stderr = result.stderr;
  let text = result.stdout;
  for (const scratch of [root, inputsDir, configHome()]) {
    if (text.includes(scratch) || (entry.stderr ?? '').includes(scratch)) fail(`${name} names the scratch folder ${scratch}`);
  }
  if (spec.format === 'json') {
    const doc = JSON.parse(text);
    const rows = name.startsWith('timeline/') ? doc.milestones : name.startsWith('audit-progress/') ?
      doc.pending?.milestones ?? [] : [];
    if (name.startsWith('timeline/')) for (const row of rows) dues.set(`${spec.workspace}:${row.id}`, row.due);
    const values = rows.map((row) => {
      const due = dues.get(`${spec.workspace}:${row.id}`);
      if (!due) fail(`${name}: no due time for milestone ${row.id}; the timeline runs first`);
      return roundDays(due);
    });
    if (rows.length > 0) {
      text = normaliseDays(text, values);
      entry.normalised = ['days_left'];
    }
    JSON.parse(text);
  }
  entry.file = `cockpit/${name}.${spec.format === 'json' ? 'json' : 'txt'}`;
  return { entry, text };
}

// What the reduced Tasks panel must show for each task file of geo-cockpit (AC-P3): the Status line's value as the
// file holds it, or null without one. These are this script's own inputs (TASK_FILES), listed for the tests.
function taskFilesEntry() {
  return {
    workspace: 'geo-cockpit',
    about: 'written by this script (inputs, not CLI output); status is the text after "**Status:**" as written, ' +
      'null when the file has no Status line',
    specs: 'development/tasks/*.md', board: 'development/BOARD.md',
    files: TASK_FILES.map(({ path, id, status }) => ({ path, id, status })),
  };
}

// ---------------------------------------------------------------------------------------------------------------
// Generation

function generate(target) {
  checkCli();
  const source = releaseSource();
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'steward-fixtures-')));
  const work = join(scratch, 'ws');
  const out = join(scratch, 'out');
  mkdirSync(work);
  mkdirSync(out);
  try {
    const files = new Map();
    const schema = releaseFile(SCHEMA_PATH);
    files.set('schema', schema);

    const workspaces = {};
    for (const name of Object.keys(WORKSPACES)) {
      const dir = buildWorkspace(work, name);
      workspaces[name] = { base: WORKSPACES[name].base, about: WORKSPACES[name].about,
        files: digestTree(dir, WORKSPACES[name].volatile) };
    }
    const reports = {};
    for (const name of Object.keys(REPORTS)) {
      const { entry, report } = runCheck(work, name, out);
      reports[name] = entry;
      if (report) files.set(entry.report, canonical(report));
      console.log(`fixtures: ${name}: exit ${entry.exit_code}${entry.counts ? ' ' + JSON.stringify(entry.counts) : ''}`);
    }
    const geo = JSON.parse(files.get('reports/geo.json'));
    const { invalid, oversized, oversizedBytes } = derived(geo);
    files.set('derived/invalid-json.json', invalid);
    files.set('derived/oversized.json.gz', oversized);

    const inputsDir = join(scratch, 'inputs');
    mkdirSync(inputsDir);
    for (const [file, text] of Object.entries(COCKPIT_INPUTS)) {
      writeFileSync(join(inputsDir, file), text);
      files.set(`cockpit/inputs/${file}`, text);
    }
    const outputs = {};
    const dues = new Map();
    const order = Object.keys(COCKPIT).sort((a, b) => Number(b.startsWith('timeline/')) - Number(a.startsWith('timeline/')));
    for (const name of order) {
      const { entry, text } = runCockpit(work, inputsDir, name, dues);
      files.set(entry.file, text);
      console.log(`fixtures: cockpit ${name}: exit ${entry.exit_code}`);
      outputs[name] = entry;
    }
    const cockpit = {
      about: 'What the reduced panels of extension 0.2.0 read (RELEASE_vscode_0.2.0_SPEC §3), as CLI ' +
        `${version} prints it: stdout byte for byte, except as "normalised" says.`,
      now: COCKPIT_NOW,
      normalised: COCKPIT_NORMALISED,
      outputs: Object.fromEntries(Object.keys(COCKPIT).map((name) => [name, outputs[name]])),
      inputs: Object.fromEntries(Object.keys(COCKPIT_INPUTS).map((file) => [file, {
        file: `cockpit/inputs/${file}`, sha256: sha256(COCKPIT_INPUTS[file]),
      }])),
      task_files: taskFilesEntry(),
      queue: {
        'geo-cockpit': { waiting: fixedNonce('geo-cockpit', 'waiting'), expired: fixedNonce('geo-cockpit', 'expired') },
        'geo-cockpit-peer': { waiting: fixedNonce('geo-cockpit-peer', 'waiting') },
      },
      not_generated: {
        'at risk': 'a milestone is at risk only between its internal deadline and its due time, measured from the ' +
          'moment the CLI runs; no fixed due date stays in that window, so no output with "at risk" is reproducible',
        signed: 'a signed payload needs a signing key and `git tag -s`; this script never signs, so the queue has ' +
          'waiting and expired payloads only',
        'no local checkout': 'a peer given by a remote URL ("no local checkout for signing; skipped") is not made: ' +
          'the script makes no network source; GONE shows the other skip line',
      },
    };

    const index = {
      about: 'Generated by scripts/fixtures.mjs from the pinned CLI. Do not edit; run `npm run fixtures`.',
      cli: { version, program: 'steward', source: `${REPOSITORY} tag ${source.tag}`, commit: source.commit },
      schema: { path: `src/${SCHEMA_PATH}`, source: `${source.tag}:${SCHEMA_PATH}`, sha256: sha256(schema) },
      normalised: {
        envelope: NORMALISED,
        geo_repo_id: `steward.toml repo_id of every GEO copy set to ${FIXED_REPO_ID} (steward example writes a new one each time)`,
      },
      workspaces,
      reports,
      derived: {
        'invalid-json': { file: 'derived/invalid-json.json', from: 'reports/geo.json', how: 'the first half of its bytes' },
        'oversized': {
          file: 'derived/oversized.json.gz', from: 'reports/geo.json', limit_bytes: OUTPUT_LIMIT,
          bytes_uncompressed: oversizedBytes, how: 'its bytes followed by spaces until the file exceeds limit_bytes; gzipped',
        },
      },
      not_generated: {
        waiver: 'CLI 0.20.6 never lists a gate waiver (gates[].waived is always empty; a waived UNKNOWN is planned ' +
          'for a later CLI), so no report with a waiver can be produced by the pinned CLI. Raised in the T03 report.',
      },
      cockpit,
    };
    files.set('manifest.json', canonical(index));
    return target(files, scratch);
  } finally {
    if (keep) console.log(`fixtures: scratch kept in ${scratch}`);
    else rmSync(scratch, { recursive: true, force: true });
  }
}

function destination(name) {
  return name === 'schema' ? schemaCopy : join(fixturesDir, ...name.split('/'));
}

function listCommitted() {
  if (!existsSync(fixturesDir)) return [];
  return findFiles(fixturesDir, () => true);
}

if (workspacesArg) {
  checkCli();
  releaseSource();
  mkdirSync(workspacesArg, { recursive: true });
  const root = realpathSync(workspacesArg);
  for (const name of Object.keys(WORKSPACES)) console.log(`fixtures: workspace ${buildWorkspace(root, name)}`);
  for (const spec of new Set(bases.values())) rmSync(spec, { recursive: true, force: true });
} else if (verify) {
  const problems = generate((files) => {
    const found = [];
    for (const [name, bytes] of files) {
      const path = destination(name);
      const want = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
      if (!existsSync(path)) found.push(`missing: ${relative(extensionRoot, path)}`);
      else if (!readFileSync(path).equals(want)) found.push(`differs: ${relative(extensionRoot, path)}`);
    }
    const expected = new Set([...files.keys()].filter((name) => name !== 'schema'));
    for (const rel of listCommitted()) {
      if (!expected.has(rel)) found.push(`not generated: test/fixtures/${rel}`);
    }
    return found;
  });
  if (problems.length > 0) {
    for (const line of problems) console.error(`fixtures: ${line}`);
    fail('the committed fixtures differ from what the pinned CLI produces; run `npm run fixtures`');
  }
  console.log('fixtures: verified: the committed fixtures and the schema copy equal what the pinned CLI produces');
} else {
  generate((files) => {
    rmSync(fixturesDir, { recursive: true, force: true });
    for (const [name, bytes] of files) {
      const path = destination(name);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, bytes);
    }
    console.log(`fixtures: wrote ${files.size - 1} files in test/fixtures/ and ${relative(extensionRoot, schemaCopy)}`);
  });
}
