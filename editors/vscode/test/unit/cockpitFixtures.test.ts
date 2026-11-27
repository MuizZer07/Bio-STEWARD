import { strict as assert } from 'node:assert';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

// The cockpit corpus of test/fixtures/cockpit/ (task U01): the 0.20.6 outputs the reduced panels of 0.2.0 read
// (RELEASE_vscode_0.2.0_SPEC §3). These tests check that it holds the cases U02 – U05 need; `npm run fixtures --
// --verify` checks that it is what the pinned CLI prints.

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');

interface Output { workspace: string; argv: string[]; exit_code: number; format: 'json' | 'text'; file: string;
  normalised?: string[] }
interface Cockpit {
  now: string;
  outputs: Record<string, Output>;
  inputs: Record<string, { file: string; sha256: string }>;
  task_files: { workspace: string; files: { path: string; id: string; status: string | null }[] };
  queue: Record<string, Record<string, string>>;
  not_generated: Record<string, string>;
}
interface Manifest { cli: { version: string }; workspaces: Record<string, { files: Record<string, string> }>;
  cockpit: Cockpit }

const manifest = JSON.parse(readFileSync(join(fixtures, 'manifest.json'), 'utf8')) as Manifest;
const { cockpit } = manifest;
const text = (name: string) => readFileSync(join(fixtures, cockpit.outputs[name].file), 'utf8');
const json = <T>(name: string) => JSON.parse(text(name)) as T;

interface Milestone { id: string; state: string; days_left: number; due?: string }
interface Audit {
  schema: string;
  pending: { exchange_open?: string[]; own_open?: string[]; signatures_waiting: string[]; milestones: Milestone[];
    sprints: { sprint: string; open?: string[] }[] };
}
interface Tokens {
  sources: Record<string, { status: string; files: { path: string; status: string; issues: string[] }[] }>;
  tasks: { task: string; tokens: number | null; status: string; models: { model: string; tokens: number }[] }[];
}

describe('cockpit fixture corpus (U01)', () => {
  it('names every output it holds, each run with exit 0 on a recorded workspace', () => {
    for (const [name, entry] of Object.entries(cockpit.outputs)) {
      assert.equal(entry.exit_code, 0, name);
      assert.ok(entry.workspace in manifest.workspaces, name);
      assert.deepEqual(entry.argv.slice(-2), ['--repo', '<workspace>'], name);
      assert.ok(entry.file.endsWith(entry.format === 'json' ? '.json' : '.txt'), name);
      const body = text(name);
      if (entry.format === 'json') assert.doesNotThrow(() => JSON.parse(body), name);
      assert.ok(!/\/(tmp|var|private|Users|home)\//.test(body), `${name} names a local folder`);
    }
    for (const input of Object.values(cockpit.inputs)) {
      assert.equal(createHash('sha256').update(readFileSync(join(fixtures, input.file))).digest('hex'), input.sha256);
    }
  });

  it('has audit progress with nothing pending and with every pending kind P1 shows', () => {
    const empty = json<Audit>('audit-progress/geo');
    assert.equal(empty.schema, 'steward.progress_audit/0.1');
    assert.deepEqual(empty.pending, { milestones: [], signatures_waiting: [], sprints: [] });
    const full = json<Audit>('audit-progress/geo-cockpit').pending;
    assert.deepEqual(full.exchange_open, ['PEER-REQ-001']);
    assert.deepEqual(full.own_open, ['GEO-Q-001']);
    assert.deepEqual(full.signatures_waiting, [`spend (${cockpit.queue['geo-cockpit'].waiting.slice(0, 12)})`]);
    assert.ok(full.sprints.some((s) => s.sprint === 'fixture-sprint' && (s.open ?? []).length > 0));
    assert.deepEqual(full.milestones.map((m) => m.state),
      json<{ milestones: Milestone[] }>('timeline/geo-cockpit').milestones.map((m) => m.state));
  });

  it('has a timeline with no milestones and one per reproducible state, days_left measured from "now"', () => {
    assert.deepEqual(json<{ milestones: Milestone[] }>('timeline/geo').milestones, []);
    const rows = json<{ milestones: Milestone[] }>('timeline/geo-cockpit').milestones;
    assert.deepEqual(rows.map((m) => m.state), ['met', 'due (record its outcome)', 'late', 'on track', 'ready']);
    for (const m of rows) {
      const days = Math.round(((Date.parse(m.due ?? '') - Date.parse(cockpit.now)) / 86400000) * 10) / 10;
      assert.equal(m.days_left, days, m.id);
    }
    assert.deepEqual(cockpit.outputs['timeline/geo-cockpit'].normalised, ['days_left']);
    assert.ok('at risk' in cockpit.not_generated);
  });

  it('has tokens reports with no source, an empty source and a log with records (P4)', () => {
    const none = json<Tokens>('tokens-report/no-source');
    for (const source of Object.values(none.sources)) assert.deepEqual(source, { files: [], status: 'unavailable' });
    const empty = json<Tokens>('tokens-report/empty-source');
    assert.equal(empty.sources.claude.files.length, 1);
    assert.equal(empty.sources.claude.status, 'unavailable');
    assert.equal(empty.tasks[0].tokens, null);
    const session = json<Tokens>('tokens-report/claude-session');
    assert.equal(session.sources.claude.status, 'available');
    assert.deepEqual(session.tasks.map((t) => [t.task, t.tokens, t.status]), [['all activity', 1170, 'available']]);
    assert.deepEqual(session.tasks[0].models.map((m) => m.model), ['claude-fixture']);
  });

  it('has the authorize pending text for an empty queue, one project and all projects (P5)', () => {
    assert.equal(text('authorize-pending/geo'), '0 waiting\n');
    const { waiting, expired } = cockpit.queue['geo-cockpit'];
    const one = text('authorize-pending/geo-cockpit');
    assert.match(one, new RegExp(`^GEO {2}${waiting.slice(0, 12)} {2}waiting `, 'm'));
    assert.match(one, new RegExp(`^GEO {2}${expired.slice(0, 12)} {2}expired `, 'm'));
    assert.match(one, /^1 waiting; sign them with: steward authorize sign-pending\n$/m);
    const all = text('authorize-pending/geo-cockpit-all-projects');
    assert.ok(all.startsWith(one.split('\n').slice(0, 2).join('\n')));
    assert.match(all, /^GONE: no-such-project: not a steward project here; skipped$/m);
    assert.match(all, new RegExp(`^PEER {2}${cockpit.queue['geo-cockpit-peer'].waiting.slice(0, 12)} {2}waiting `, 'm'));
    assert.match(all, /^2 waiting; sign them with: steward authorize sign-pending --all-projects\n$/m);
  });

  it('has task files whose Status lines vary, and one without (AC-P3)', () => {
    const { workspace, files } = cockpit.task_files;
    const recorded = manifest.workspaces[workspace].files;
    for (const file of files) assert.ok(file.path in recorded, file.path);
    const statuses = files.map((f) => f.status);
    assert.ok(statuses.includes(null), 'a file without a Status line');
    assert.ok(statuses.some((s) => s !== null && /[—(]/.test(s)), 'a status with a qualifier');
    assert.ok(new Set(statuses).size === statuses.length, 'every status differs');
  });
});
