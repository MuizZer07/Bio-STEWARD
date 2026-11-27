// T12, T11-05: each check request gets a private output file; only a run that exits 0 – 3 with a valid report is
// published; the saved full report is replaced atomically and only by a request that succeeded; overlapping
// requests never delete or replace each other's output and are published in request order; a scoped request keeps
// its own report. Driven with stand-in runs that write distinct reports, so no CLI is needed.
import { strict as assert } from 'node:assert';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { ValidateFunction } from 'ajv';
import type { RunResult } from '../../src/cli/runner';
import { PublishOrder, runReportRequest, type ReportRun } from '../../src/reportRun';

interface Doc {
  readonly name: string;
}

const validate = ((value: unknown) => typeof value === 'object' && value !== null && typeof (value as Doc).name === 'string') as ValidateFunction<Doc>;
const done = (exitCode: number): RunResult => ({ kind: 'completed', exitCode, stdout: '', stderr: '' });
const later = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe('check requests and their reports (T11-05)', () => {
  let root: string;
  let saved: string;
  let order: PublishOrder;
  let shown: string[];
  let outputs: string[];

  beforeEach(() => {
    root = realpathSync(mkdtempSync(join(tmpdir(), 'steward-report-run-')));
    mkdirSync(join(root, '.steward'));
    saved = join(root, '.steward', 'report.json');
    writeFileSync(saved, JSON.stringify({ name: 'previous' }));
    order = new PublishOrder();
    shown = [];
    outputs = [];
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  // A stand-in for `steward check --output FILE`: waits, writes `body` (none for null), exits with `exit`.
  const request = (name: string, { wait = 0, exit = 0, body = JSON.stringify({ name }), result }: {
    wait?: number; exit?: number; body?: string | null; result?: RunResult;
  } = {}, destination: { replace: string } | { folder: string } = { replace: saved }): Promise<ReportRun<Doc>> =>
    runReportRequest<Doc>({
      boundary: root, destination, order, validate,
      execute: async (output) => {
        outputs.push(output);
        assert.equal(existsSync(output), false, 'a private output does not exist before its run');
        await later(wait);
        if (body !== null) writeFileSync(output, body);
        return result ?? done(exit);
      },
      show: (doc) => shown.push(doc.name),
    });

  const savedName = () => (JSON.parse(readFileSync(saved, 'utf8')) as Doc).name;
  const leftovers = () => readdirSync(join(root, '.steward')).filter((n) => n.startsWith('.report-'));

  it('a successful request replaces the saved report and shows it; its private file is gone', async () => {
    const run = await request('new');
    assert.deepEqual(run, { kind: 'published', value: { name: 'new' }, exitCode: 0 });
    assert.equal(savedName(), 'new');
    assert.deepEqual(shown, ['new']);
    assert.equal(outputs.length, 1);
    assert.notEqual(outputs[0], saved, 'the run writes its own file, not the saved report');
    assert.deepEqual(leftovers(), []);
  });

  it('exits 1 – 3 carry a report too (FAIL, INCOMPLETE, UNKNOWN)', async () => {
    for (const exit of [1, 2, 3]) assert.equal((await request(`exit ${exit}`, { exit })).kind, 'published');
    assert.equal(savedName(), 'exit 3');
  });

  it('an overlap: two requests with distinct reports never touch each other\'s output, and the newer one wins', async () => {
    // The older request runs longer, so it finishes after the newer one has been published.
    const [older, newer] = await Promise.all([request('older', { wait: 150 }), request('newer', { wait: 10 })]);
    assert.equal(newer.kind, 'published');
    assert.equal(older.kind, 'outdated', 'an older request never replaces a newer report');
    assert.equal(savedName(), 'newer');
    assert.deepEqual(shown, ['newer']);
    assert.equal(new Set(outputs).size, 2, 'each request had its own output file');
    assert.deepEqual(leftovers(), []);
  });

  it('an overlap in order: both are published, the later last', async () => {
    const [first, second] = await Promise.all([request('first', { wait: 10 }), request('second', { wait: 100 })]);
    assert.deepEqual([first.kind, second.kind], ['published', 'published']);
    assert.deepEqual(shown, ['first', 'second']);
    assert.equal(savedName(), 'second');
  });

  it('a cancellation: the saved report is kept, nothing is shown, the private file is removed', async () => {
    for (const kind of ['cancelled', 'superseded', 'timeout'] as const) {
      const run = await request(kind, { result: { kind } });
      assert.equal(run.kind, 'run');
    }
    assert.equal(savedName(), 'previous');
    assert.deepEqual(shown, []);
    assert.deepEqual(leftovers(), []);
  });

  it('a failure: another exit, invalid JSON, a wrong document or no file leave the saved report alone', async () => {
    assert.deepEqual(await request('usage', { exit: 64 }), { kind: 'exit', exitCode: 64, stderr: '' });
    assert.deepEqual(await request('crash', { exit: 5 }), { kind: 'exit', exitCode: 5, stderr: '' });
    assert.deepEqual(await request('broken', { body: '{' }), { kind: 'unreadable', exitCode: 0 });
    assert.deepEqual(await request('wrong', { body: '[]', exit: 1 }), { kind: 'unreadable', exitCode: 1 });
    assert.deepEqual(await request('none', { body: null }), { kind: 'unreadable', exitCode: 0 });
    assert.equal((await request('error', { result: { kind: 'process-error', message: 'spawn failed' } })).kind, 'run');
    assert.equal(savedName(), 'previous');
    assert.deepEqual(shown, []);
    assert.deepEqual(leftovers(), []);
  });

  it('a scoped request keeps its own report and label, and never replaces the saved one', async () => {
    const storage = join(root, 'storage');
    const scoped = (name: string, wait: number) => request(name, { wait }, { folder: storage });
    const [skills, rule] = await Promise.all([scoped('check skills', 60), scoped('check --rule R-60', 5)]);
    assert.equal(rule.kind, 'published');
    assert.ok(rule.kind === 'published' && rule.value.name === 'check --rule R-60', 'each request reads its own file');
    assert.equal(skills.kind, 'outdated');
    assert.equal(savedName(), 'previous');
    assert.deepEqual(readdirSync(storage), []);
  });

  it('refuses a report folder that is a link out of the project, before anything runs', async () => {
    const outside = realpathSync(mkdtempSync(join(tmpdir(), 'steward-report-outside-')));
    try {
      rmSync(join(root, '.steward'), { recursive: true });
      symlinkSync(outside, join(root, '.steward'));
      assert.deepEqual(await request('x'), { kind: 'path' });
      assert.deepEqual(outputs, []);
      assert.deepEqual(readdirSync(outside), []);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});
