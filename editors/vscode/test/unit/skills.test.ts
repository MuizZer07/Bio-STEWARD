// T08, S7: the Agent Skills model (R-60 → folders and nodes), the folder listing on real folders, and the plan check
// of `steward init --skills … --dry-run`.
import { strict as assert } from 'node:assert';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Report, ResultItem } from '../../src/model/report';
import {
  HARNESS_FOLDERS, planLines, printedSkillsTable, shownFolders, skillFolders, skillsNodes, skillsResult,
  type FolderListing,
} from '../../src/model/skills';
import { initialState, withReport, type ProjectState } from '../../src/model/views';
import { listSkillFolders, skillsPlanBlock } from '../../src/skillFolders';

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports');
const geo = () => JSON.parse(readFileSync(join(fixtures, 'geo.json'), 'utf8')) as Report;

function r60(status: ResultItem['status'], reason: string, subject: string, details: Record<string, unknown>[]): ResultItem {
  return { rule: 'R-60', name: 'skills.copies', rule_version: 1, subject, status, reason, details, evidence: [] } as unknown as ResultItem;
}

function withR60(result: ResultItem, partial = false): Report {
  const report = geo();
  report.verdict.results = report.verdict.results.map((item) => item.rule === 'R-60' ? result : item);
  if (partial) {
    report.verdict.results = [result];
    for (const gate of report.verdict.gates) Object.assign(gate, { evaluated: false, eligible: false, reason: 'partial_check' });
  }
  return report;
}

const ready: ProjectState = { ...initialState(true), cli: { kind: 'ready', version: '0.20.6', mode: 'limited', newerThanTested: false } };

// The CLI 0.20.6 text of `steward init --skills .agents/skills --skills .claude/skills --kits core --dry-run` in a
// project whose steward.toml has no [skills] table (shown as the CLI prints it).
const PLAN = `print          steward.toml  (exists; steward.toml is never edited. Add this table)

[skills]                      # one canonical copy; the other harness directories link to it
canonical = ".agents/skills"
copies = [".claude/skills"]

skip           steward.toml  (exists; repo_id and profile kept)
skip           development/DECISIONS.md  (exists)
unchanged      .gitignore  (steward block current)
would update   AGENTS.md  (steward block)
would create   .agents/skills/benchmark-contract/  (skill)
would create   .agents/skills/using-steward/  (skill)
would create   .claude/skills  (skills link)
`;

describe('Agent Skills model (S7)', () => {
  it('lists only the known harness folders when R-60 is not configured', () => {
    const result = geo().verdict.results.find((item) => item.rule === 'R-60');
    assert.equal(result?.status, 'NOT_APPLICABLE');
    assert.deepEqual(skillFolders(result), HARNESS_FOLDERS.map((path) => ({ path, role: 'found', details: [] })));
    assert.deepEqual(skillFolders(undefined).map((f) => f.path), [...HARNESS_FOLDERS]);
  });

  it('takes the canonical folder and the copies from R-60, with their codes as the CLI reports them', () => {
    const folders = skillFolders(r60('FAIL', 'a skills copy is missing, dangling or has drifted', './.agents/skills/', [
      { code: 'R-60.linked', path: '.claude/skills' },
      { code: 'R-60.drift', path: '.codex/skills', value: 1, message: 'differs from the canonical copy: run-estimate/SKILL.md' },
      { code: 'R-60.pointer_wrong', path: '.gemini/skills/STEWARD_SKILLS' },
    ]));
    assert.deepEqual(folders, [
      { path: '.agents/skills', role: 'canonical', details: [] },
      { path: '.claude/skills', role: 'copy', details: [{ code: 'R-60.linked', message: undefined }] },
      { path: '.codex/skills', role: 'copy', details: [{ code: 'R-60.drift', message: 'differs from the canonical copy: run-estimate/SKILL.md' }] },
      { path: '.gemini/skills', role: 'copy', details: [{ code: 'R-60.pointer_wrong', message: undefined }] },
    ]);
    const canonicalMissing = skillFolders(r60('FAIL', 'the canonical skills directory is missing or a link', 'skills',
      [{ code: 'R-60.no_canonical', path: 'skills' }]));
    assert.deepEqual(canonicalMissing[0], { path: 'skills', role: 'canonical', details: [{ code: 'R-60.no_canonical', message: undefined }] });
  });

  it('reads R-60 from the newest report that holds it: a scoped run, else the full report', () => {
    const full = withR60(r60('PASS', '1 copy location(s) match the canonical directory', '.agents/skills', []));
    const drift = r60('FAIL', 'a skills copy is missing, dangling or has drifted', '.agents/skills', []);
    let state = withReport(ready, full);
    assert.equal(skillsResult(state)?.result.status, 'PASS');
    assert.equal(skillsResult(state)?.partial, false);
    state = withReport(state, withR60(drift, true), { scope: 'check skills' });
    assert.deepEqual(skillsResult(state), { result: drift, freshness: 'fresh', partial: true, scope: 'check skills' });
    // A scoped run without R-60 leaves the full report's result in place.
    const other = withR60(drift, true);
    other.verdict.results = [];
    state = withReport(withReport(ready, full), other, { scope: 'check data' });
    assert.equal(skillsResult(state)?.result.status, 'PASS');
    assert.equal(skillsResult(state)?.freshness, 'stale');
  });

  it('builds the drift row and folder rows from the result and the listing, nothing computed', () => {
    const result = r60('FAIL', 'a skills copy is missing, dangling or has drifted', '.agents/skills', [
      { code: 'R-60.drift', path: '.claude/skills', value: 2, message: 'differs from the canonical copy: a/SKILL.md, b/SKILL.md' },
    ]);
    const state = withReport(ready, withR60(result, true), { scope: 'check skills' });
    const listings: FolderListing[] = [
      { path: '.agents/skills', role: 'canonical', details: [], entry: { kind: 'directory', skills: ['a', 'b'], more: 0 } },
      { path: '.claude/skills', role: 'copy', details: [{ code: 'R-60.drift', message: 'differs from the canonical copy: a/SKILL.md, b/SKILL.md' }],
        entry: { kind: 'directory', skills: ['a', 'b'], more: 0 } },
    ];
    const [drift, canonical, copy] = skillsNodes(state, listings);
    assert.equal(drift.kind, 'result');
    assert.equal(drift.description, '✗ FAIL · a skills copy is missing, dangling or has drifted · check skills · fresh');
    assert.deepEqual(drift.ref, { rule: 'R-60', subject: '.agents/skills', status: 'FAIL' });
    assert.equal(canonical.description, 'canonical · 2 skill folders');
    assert.deepEqual(canonical.children?.map((n) => n.label), ['a', 'b']);
    assert.equal(copy.description, 'copy · 2 skill folders · R-60.drift');
    assert.equal(copy.children?.[0].label, 'R-60.drift');
    assert.equal(copy.children?.[0].description, 'differs from the canonical copy: a/SKILL.md, b/SKILL.md');
    assert.equal(copy.expanded, true);
  });

  it('says plainly when there is no report, when R-60 is not configured, and when there are no folders', () => {
    const none = skillsNodes(ready, []);
    assert.equal(none[0].description, 'no report yet · Check Skills');
    assert.equal(none[0].command, 'checkSkills');
    assert.equal(none[1].label, 'No skill folders');
    const notConfigured = skillsNodes(withReport(ready, geo()), []);
    assert.equal(notConfigured[0].description, '– NOT APPLICABLE · [skills] is not configured · full check · fresh');
    assert.match(notConfigured[0].tooltip ?? '', /never edits steward\.toml/);
    assert.deepEqual(skillsNodes({ ...ready, trusted: false }, []), [], 'nothing in Restricted Mode');
  });

  it('hides a known harness folder that does not exist, but keeps a missing configured copy', () => {
    const listings: FolderListing[] = [
      { path: '.claude/skills', role: 'copy', details: [{ code: 'R-60.missing' }], entry: { kind: 'missing' } },
      { path: '.agents/skills', role: 'found', details: [], entry: { kind: 'missing' } },
    ];
    assert.deepEqual(shownFolders(listings).map((f) => f.path), ['.claude/skills']);
  });

  it('reads the plan lines and the [skills] table the CLI prints', () => {
    assert.deepEqual(planLines(PLAN).filter((l) => l.action.startsWith('would')), [
      { action: 'would update', path: 'AGENTS.md' },
      { action: 'would create', path: '.agents/skills/benchmark-contract/' },
      { action: 'would create', path: '.agents/skills/using-steward/' },
      { action: 'would create', path: '.claude/skills' },
    ]);
    assert.equal(printedSkillsTable(PLAN),
      '[skills]                      # one canonical copy; the other harness directories link to it\n' +
      'canonical = ".agents/skills"\ncopies = [".claude/skills"]');
    assert.equal(printedSkillsTable('skip  steward.toml  (exists)\n'), undefined);
  });
});

describe('Agent Skills on disk (S7, AC-5.3 for 0.20.6)', () => {
  let root: string;
  let outside: string;

  beforeEach(() => {
    root = realpathSync(mkdtempSync(join(tmpdir(), 'bs-skills-')));
    outside = realpathSync(mkdtempSync(join(tmpdir(), 'bs-outside-')));
  });
  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  });

  it('lists the folders on disk: a directory, a link inside the project, a pointer copy, a missing copy', async () => {
    for (const name of ['using-steward', 'task-lifecycle', 'change-impact']) mkdirSync(join(root, '.agents', 'skills', name), { recursive: true });
    writeFileSync(join(root, '.agents', 'skills', 'README.md'), 'a file, not a skill folder');
    mkdirSync(join(root, '.claude'));
    symlinkSync('../.agents/skills', join(root, '.claude', 'skills'));
    mkdirSync(join(root, '.gemini', 'skills'), { recursive: true });
    writeFileSync(join(root, '.gemini', 'skills', 'STEWARD_SKILLS'), '../../.agents/skills\n');
    const refs = skillFolders(r60('FAIL', 'x', '.agents/skills', [
      { code: 'R-60.linked', path: '.claude/skills' }, { code: 'R-60.pointer', path: '.gemini/skills' },
      { code: 'R-60.missing', path: '.codex/skills' },
    ]));
    const listings = await listSkillFolders(root, refs);
    const onDisk = readdirSync(join(root, '.agents', 'skills'), { withFileTypes: true })
      .filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
    assert.deepEqual(listings.map((l) => [l.path, l.entry]), [
      ['.agents/skills', { kind: 'directory', skills: onDisk, more: 0 }],
      ['.claude/skills', { kind: 'link', target: '../.agents/skills', skills: onDisk, more: 0 }],
      ['.gemini/skills', { kind: 'pointer' }],
      ['.codex/skills', { kind: 'missing' }],
    ]);
  });

  it('never lists a folder outside the project, through a link or a parent link (T5)', async () => {
    mkdirSync(join(outside, 'secret-skill'));
    mkdirSync(join(root, '.claude'));
    symlinkSync(outside, join(root, '.claude', 'skills'));
    symlinkSync(outside, join(root, '.agents'));
    const listings = await listSkillFolders(root, skillFolders(r60('PASS', 'x', '../elsewhere', [])));
    assert.deepEqual(listings.map((l) => [l.path, l.entry]), [
      ['../elsewhere', { kind: 'outside' }],
      ['.agents/skills', { kind: 'outside' }],
      ['.claude/skills', { kind: 'link', target: outside }],
    ]);
  });

  it('accepts a plan that only creates new paths inside the project', async () => {
    writeFileSync(join(root, 'steward.toml'), '');
    assert.equal(await skillsPlanBlock(root, PLAN), undefined);
  });

  it('blocks a plan that creates nothing, creates steward.toml, or reaches an existing or outside path', async () => {
    assert.match(await skillsPlanBlock(root, 'skip           .agents/skills/a/  (exists)\n') ?? '', /Nothing to install/);
    assert.match(await skillsPlanBlock(root, 'would create   steward.toml  (profile exploratory)\n') ?? '', /no steward\.toml/);
    mkdirSync(join(root, '.claude', 'skills'), { recursive: true });
    assert.match(await skillsPlanBlock(root, PLAN) ?? '', /already exists/);
    rmSync(join(root, '.claude'), { recursive: true });
    symlinkSync(outside, join(root, '.agents'));
    assert.match(await skillsPlanBlock(root, PLAN) ?? '', /outside the project/);
  });
});
