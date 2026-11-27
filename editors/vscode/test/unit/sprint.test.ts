// Unit suite, T13: the live sprint view, minimal (S9; design v0.4 §1, §2, §4; AC-S9).
// - the sprint-file reader against the recorded sprint file (its done-commands must equal the commands the CLI
//   itself read from that file, as recorded in the ledger's checks);
// - every displayed state, time and exit code against the recorded ledger (test/recorded/sprint/), and against
//   `steward sprint status` when the pinned CLI is installed;
// - a broken ledger line shows "unreadable"; the hash chain is not re-verified;
// - the status bar text and the three notifications;
// - T12: no git at all (D1); the plan validated as the pinned CLI validates it, ledger entries validated before the
//   fold, incomplete states marked on every surface, derived states labelled, work bounded (T11-03, T11-04, T11-09);
// - a scratch sprint on the pinned CLI with a shell task that commits twice: the commit the ledger records, and
//   nothing written by the read.
import { strict as assert } from 'node:assert';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as git from '../../src/cli/git';
import {
  foldStates, MAX_LEDGER_EVENTS, MAX_TASKS, notices, parseLedger, parsePlan, snapshotOf, sprintNodes, sprintStatus, taskOrder,
} from '../../src/model/sprint';
import { isFloat, MAX_TOML_DEPTH, parseToml, TomlDateTime, TomlError } from '../../src/model/toml';
import type { ViewNode } from '../../src/model/views';
import { MAX_SPRINTS, readBounded, SprintReader } from '../../src/sprints';

const extensionRoot = join(__dirname, '..', '..', '..');
const recorded = join(extensionRoot, 'test', 'recorded', 'sprint');
const SID = '2026-11-27-vscode-0.1';
const planText = readFileSync(join(recorded, `${SID}.toml`), 'utf8');
const ledgerText = readFileSync(join(recorded, `${SID}.jsonl`), 'utf8');
const ledgerLines = ledgerText.split('\n').filter(Boolean).map((l) => JSON.parse(l) as Record<string, unknown>);
// The pinned CLI from `npm run cli:install`, or BIO_STEWARD_TEST_CLI (a path; "off" skips), as in cli.test.ts.
const pinnedCli = join(extensionRoot, '.cli', 'bin', 'steward');
const override = process.env.BIO_STEWARD_TEST_CLI;
const steward = override === 'off' ? '' : override || (existsSync(pinnedCli) ? pinnedCli : '');
const haveCli = steward !== '';
const haveGit = spawnSync('/bin/sh', ['-c', 'command -v git'], { encoding: 'utf8' }).stdout.trim() !== '';

const firstLines = (n: number) => ledgerText.split('\n').slice(0, n).join('\n') + '\n';
const snap = (text = ledgerText) => snapshotOf(SID, planText, text);
const walk = (nodes: readonly ViewNode[]): ViewNode[] => nodes.flatMap((n) => [n, ...walk(n.children ?? [])]);
const byId = (nodes: readonly ViewNode[], id: string) => walk(nodes).find((n) => n.id === id);
const at = (iso: string) => Date.parse(iso);

describe('live sprint view (T13, S9)', () => {
  describe('the sprint-file reader', () => {
    it('reads the recorded sprint file: id, window, dispatch, twelve tasks in order, limits', () => {
      const plan = parsePlan(planText);
      assert.equal(plan.id, SID);
      assert.equal(plan.dispatch, 'order');
      assert.equal(plan.maxParallel, 1);
      assert.equal(plan.windowStart, at('2026-11-26T15:15:00-05:00'));
      assert.deepEqual(taskOrder(plan), ['T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'T08', 'T09', 'T10', 'T11', 'T12']);
      assert.deepEqual(plan.tasks.map((t) => t.wallMinutes), [120, 150, 120, 180, 150, 150, 150, 150, 180, 120, 120, 180]);
      assert.ok(plan.tasks.every((t) => t.idleMinutes === 30));
      assert.deepEqual(plan.tasks.find((t) => t.id === 'T09')?.after, ['T06', 'T07', 'T08']);
    });

    it('reads every done-command exactly as the CLI read it (the ledger records the commands it ran)', () => {
      const plan = parsePlan(planText);
      let compared = 0;
      for (const line of ledgerLines) {
        if (!Array.isArray(line.checks)) continue;
        const task = plan.tasks.find((t) => t.id === line.task)!;
        assert.deepEqual(task.done, (line.checks as { command: string }[]).map((c) => c.command), `${String(line.task)}`);
        compared++;
      }
      assert.equal(compared, 8);
    });

    it('reads the TOML forms a sprint file can use', () => {
      const doc = parseToml([
        'a = "tab\\tq\\"\\u00e9"', "b = 'C:\\path'", 'c = """\nline one\\\n   joined"""', "d = '''\nx ''y'''''",
        'e = [1, 2_000, -3.5e2, true, [ "n" ], ]', 'f = { g = 1, h.i = "j" }', 'k.l = 2026-11-26T15:15:00-05:00',
        '"q k" = 0x1F # comment', '[t]', 'x = 1', '[[arr]]', 'v = 1', '[[arr]]', 'v = 2', '',
      ].join('\n'));
      assert.equal(doc.a, 'tab\tq"é');
      assert.equal(doc.b, 'C:\\path');
      assert.equal(doc.c, 'line onejoined');
      assert.equal(doc.d, "x ''y''");
      assert.deepEqual(doc.e, [1, 2000, -350, true, ['n']]);
      assert.deepEqual(JSON.parse(JSON.stringify(doc.f)), { g: 1, h: { i: 'j' } });
      const when = (doc.k as Record<string, unknown>).l;
      assert.ok(when instanceof TomlDateTime && when.epochMs === at('2026-11-26T20:15:00Z'));
      assert.equal(doc['q k'], 31);
      assert.deepEqual(JSON.parse(JSON.stringify(doc.arr)), [{ v: 1 }, { v: 2 }]);
    });

    for (const [what, bad] of [
      ['a duplicate key', 'a = 1\na = 2'], ['a table defined twice', '[t]\n[t]'], ['an unterminated string', 'a = "x'],
      ['a bare value', 'a = yes'], ['two values on a line', 'a = 1 b = 2'], ['an inline table extended', 'a = {}\n[a]'],
      ['a leading zero', 'a = 012'],
      // T11-04
      ['a trailing comma in an inline table', 'a = { b = 1, }'], ['a table made by a dotted key, then its header', 'a.b = 1\n[a]'],
      ['a sub-table made by a dotted key, then its header', '[f]\napple.color = "red"\n[f.apple]'],
      ['February 30', 'a = 2026-02-30T00:00:00Z'], ['February 29 of a common year', 'a = 2025-02-29'], ['month 13', 'a = 2026-13-01'],
      ['hour 24', 'a = 2026-01-01T24:00:00Z'], ['second 60', 'a = 2026-01-01T23:59:60Z'], ['an offset of 24 h', 'a = 2026-01-01T00:00:00+24:00'],
      ['a local time 25:00', 'a = 25:00:00'],
      // T11-03
      [`arrays nested more than ${MAX_TOML_DEPTH} deep`, `a = ${'['.repeat(MAX_TOML_DEPTH + 1)}${']'.repeat(MAX_TOML_DEPTH + 1)}`],
      ['inline tables nested too deep', `a = ${'{ b = '.repeat(MAX_TOML_DEPTH + 1)}1${' }'.repeat(MAX_TOML_DEPTH + 1)}`],
      ['a key of too many parts', `${Array(40).fill('k').join('.')} = 1`],
    ] as const) {
      it(`refuses ${what}`, () => assert.throws(() => parseToml(bad), TomlError));
    }

    it('reads what TOML 1.0 allows near those limits: leap days, sub-tables of dotted tables, long tokens', () => {
      const doc = parseToml([
        'a = 2024-02-29T23:59:59.999+05:30', 'b = 2000-02-29', '[f]', 'apple.color = "red"', '[f.apple.texture]', 'smooth = true',
        '[g]', `${'k'.repeat(300)} = ${'1'.repeat(15)}`, `n = ${'['.repeat(MAX_TOML_DEPTH)}${']'.repeat(MAX_TOML_DEPTH)}`, '',
      ].join('\n'));
      assert.ok(doc.a instanceof TomlDateTime && doc.a.epochMs === at('2024-02-29T18:29:59.999Z'));
      const f = doc.f as Record<string, Record<string, Record<string, unknown>>>;
      assert.equal(f.apple.texture.smooth, true);
      assert.equal((doc.g as Record<string, unknown>)['k'.repeat(300)], 111111111111111);
    });

    it('tells floats from integers (max_parallel must be a whole number in the CLI)', () => {
      const doc = parseToml('a = 2\nb = 2.0\nc = 1e3\nd = 0x10\ne = inf\n');
      assert.deepEqual(['a', 'b', 'c', 'd', 'e'].map((k) => isFloat(doc, k)), [false, true, true, false, true]);
    });

    it('a deeply nested file within the byte cap is unreadable, not a crash (T11-03)', () => {
      const deep = planText.replace('max_parallel = 1', `max_parallel = 1\nx = ${'['.repeat(100000)}`);
      const s = snapshotOf(SID, deep, ledgerText);
      assert.equal(s.plan, undefined);
      assert.match(s.planError ?? '', /nested more than/);
    });

    it('refuses a sprint file that is not steward.sprint/0.1, or a window without its time zone', () => {
      assert.throws(() => parsePlan(planText.replace('steward.sprint/0.1', 'steward.sprint/9')), /schema/);
      assert.throws(() => parsePlan(planText.replace('start = 2026-11-26T15:15:00-05:00', 'start = 2026-11-26T15:15:00')), /time zone/);
    });

    // T11-04: the checks of the pinned CLI's SprintFile (sprint.py), each refused here too.
    const task = (fields: string, id = 'A') => `[[task]]\nid = "${id}"\ntitle = "A task"\ncommand = "true"\ndone = ["true"]\n${fields}\n`;
    const plan = (sprint: string, tasks = task('')) =>
      `schema = "steward.sprint/0.1"\n[sprint]\nid = "s"\nwindow = { start = 2026-01-01T00:00:00Z, end = 2026-01-02T00:00:00Z }\n${sprint}\n${tasks}`;
    for (const [what, text, error] of [
      ['a reversed window', plan('').replace('end = 2026-01-02', 'end = 2025-12-31'), /ends before it starts/],
      ['max_parallel 0', plan('max_parallel = 0'), /max_parallel/], ['max_parallel 17', plan('max_parallel = 17'), /max_parallel/],
      ['max_parallel 1.5', plan('max_parallel = 1.5'), /max_parallel/], ['max_parallel 2.0', plan('max_parallel = 2.0'), /max_parallel/],
      ['a cycle', plan('', task('after = ["B"]') + task('after = ["A"]', 'B')), /cycle: A, B/],
      ['a task waiting for itself', plan('', task('after = ["A"]')), /cycle/],
      ['an unknown field', plan('', task('colour = "red"')), /unknown field/], ['an unknown [sprint] field', plan('owner = "x"'), /unknown field/],
      ['an unknown adapter', plan('', task('agent = "gpt"')), /agent/],
      ['a shell task without a command', plan('', task('').replace('command = "true"\n', '')), /needs a command/],
      ['a task without done-commands', plan('', task('').replace('done = ["true"]', 'done = []')), /done needs/],
      ['a sentinel title', plan('', task('').replace('"A task"', '"TBD"')), /sentinel/],
      ['worktree as text', plan('', task('worktree = "no"')), /worktree/],
      ['an unknown signature kind', plan('', task('needs = ["root"]')), /signature/],
    ] as const) {
      it(`refuses ${what}, as the pinned CLI does`, () => assert.throws(() => parsePlan(text), error));
    }

    it('accepts what the CLI accepts: max_parallel 16, whole or fractional minutes, worktree false', () => {
      const p = parsePlan(plan('max_parallel = 16', task('worktree = false\nlimits = { wall_minutes = 5, idle_minutes = 0.5 }')));
      assert.equal(p.maxParallel, 16);
      assert.equal(p.tasks[0].worktree, false);
      assert.equal(p.tasks[0].idleMinutes, 0.5);
    });

    it(`bounds the work: more than ${MAX_TASKS} tasks is unreadable; a long chain is ordered and blocked in linear time (T11-03)`, () => {
      const many = (n: number, chain: boolean) => plan('', Array.from({ length: n }, (_, i) =>
        task(chain && i ? `after = ["T${i - 1}"]` : '', `T${i}`)).join(''));
      assert.throws(() => parsePlan(many(MAX_TASKS + 1, false)), /more than 500 tasks/);
      const started = Date.now();
      const text = many(MAX_TASKS, true);
      const chain = parsePlan(text);
      const s = snapshotOf('s', text, `${JSON.stringify({ kind: 'state', state: 'failed', task: 'T0', time: '2026-01-01T00:00:00Z' })}\n`);
      sprintNodes([s], { now: at('2026-01-01T01:00:00Z') });
      assert.equal(chain.order.length, MAX_TASKS);
      assert.equal(chain.order.at(-1), `T${MAX_TASKS - 1}`);
      assert.equal(s.states.get(`T${MAX_TASKS - 1}`)?.state, 'blocked', 'blocked transitively along the whole chain');
      assert.ok(Date.now() - started < 2000, `${Date.now() - started} ms`);
    });

    it('keeps the dispatcher\'s round order: file order within each round', () => {
      const p = parsePlan(plan('', [task(''), task('after = ["C"]', 'B'), task('', 'C'), task('after = ["A"]', 'D')].join('')));
      assert.deepEqual(taskOrder(p), ['A', 'C', 'B', 'D']);
    });
  });

  describe('the recorded ledger (AC-S9)', () => {
    const now = at('2026-11-26T22:30:00Z');
    const s = snap();
    const nodes = sprintNodes([s], { now, clock: (ms) => new Date(ms).toISOString().slice(11, 16) });

    // An independent fold, straight from the ledger lines: the last state line, or a later skip order.
    const expected = new Map<string, { state: string; running?: string; ended?: string; checks?: { command: string; exit: number | null }[] }>();
    for (const line of ledgerLines) {
      const task = String(line.task ?? '');
      if (line.kind === 'state') {
        const e: { state: string; running?: string; ended?: string; checks?: { command: string; exit: number | null }[] } =
          { ...expected.get(task), state: String(line.state) };
        if (line.state === 'running') {
          e.running = String(line.time);
          e.ended = undefined;
        }
        if (['done', 'failed'].includes(String(line.state))) e.ended = String(line.time);
        if (Array.isArray(line.checks)) e.checks = line.checks as { command: string; exit: number | null }[];
        expected.set(task, e);
      } else if (line.kind === 'order' && line.order === 'skip') {
        expected.set(task, { ...expected.get(task)!, state: 'skipped', ended: String(line.time) });
      }
    }

    it('shows the state the ledger records for every task, in the CLI\'s words', () => {
      const states = foldStates(parsePlan(planText), parseLedger(ledgerText).entries);
      assert.deepEqual([...states.values()].map((t) => t.state), [
        'done', 'skipped', 'done', 'done', 'skipped', 'done', 'done', 'done', 'ready', 'planned', 'planned', 'planned']);
      for (const [task, e] of expected) {
        const node = byId(nodes, `sprint/${SID}/task/${task}`)!;
        assert.ok(node.description?.startsWith(e.state.toUpperCase()), `${task}: ${node.description}`);
      }
      assert.equal(byId(nodes, `sprint/${SID}/task/T09`)?.description, 'READY · ORDER NEEDED');
      assert.equal(byId(nodes, `sprint/${SID}/task/T09`)?.kind, 'sprint-task-waiting');
      assert.equal(byId(nodes, `sprint/${SID}/task/T10`)?.description, 'PLANNED (waits for T09)');
    });

    it('shows the running and end times of the ledger, and the minutes used of each limit', () => {
      for (const [task, e] of expected) {
        if (!e.running) continue;
        const limits = byId(nodes, `sprint/${SID}/task/${task}/limits`)!;
        assert.ok(limits.tooltip?.startsWith(`running since ${e.running} (ledger)`), `${task}: ${limits.tooltip}`);
        if (e.ended) assert.ok(limits.tooltip?.endsWith(`ended ${e.ended}`), `${task}: ${limits.tooltip}`);
        const minutes = Math.floor((at(e.ended!) - at(e.running)) / 60_000);
        const wall = parsePlan(planText).tasks.find((t) => t.id === task)!.wallMinutes;
        assert.equal(limits.label, `limits: ${minutes} of ${wall} min · idle watchdog 30 min`);
      }
      assert.equal(byId(nodes, `sprint/${SID}/task/T01/limits`)?.label, 'limits: 5 of 120 min · idle watchdog 30 min');
    });

    it('shows every done-command with the exit code the ledger records, in order', () => {
      let shown = 0;
      for (const [task, e] of expected) {
        for (const [i, c] of (e.checks ?? []).entries()) {
          const node = byId(nodes, `sprint/${SID}/task/${task}/check/${i}`)!;
          assert.equal(node.label, c.exit === null ? 'exit —' : `exit ${c.exit}`);
          assert.equal(node.tooltip, c.command);
          shown++;
        }
      }
      assert.equal(shown, 24);
      assert.equal(byId(nodes, `sprint/${SID}/task/T05/check/2`)?.label, 'exit 1');
      assert.equal(byId(nodes, `sprint/${SID}/task/T05/check/2`)?.icon?.tone, 'failed');
    });

    it('lists the last ten ledger events, newest first, each with the ledger\'s own time', () => {
      const events = byId(nodes, `sprint/${SID}/events`)!.children!;
      const timed = ledgerLines.filter((l) => l.kind !== 'genesis').reverse().slice(0, 10);
      assert.deepEqual(events.map((e) => e.tooltip), timed.map((l) => `${String(l.time)} (sprint ledger)`));
      assert.equal(events[0].label, '22:19 T08 done (3 of 3 checks passed)');
      assert.equal(events[3].label, '22:00 T08 ordered by the human');
    });

    it('heads the sprint with its window, the done count and the parallelism', () => {
      assert.equal(nodes.length, 1);
      assert.equal(nodes[0].label, `SPRINT ${SID}`);
      assert.equal(nodes[0].description, 'window ends in 15 d 0 h · 6 of 12 done · one at a time');
    });

    it('agrees with `steward sprint status` on every task (pinned CLI)', function () {
      if (!haveCli || !haveGit) this.skip();
      this.timeout(60000);
      const repo = scratchRepo();
      try {
        mkdirSync(join(repo.root, 'development', 'sprints'), { recursive: true });
        writeFileSync(join(repo.root, 'development', 'sprints', `${SID}.toml`), planText);
        writeFileSync(join(repo.root, 'development', 'sprints', `${SID}.jsonl`), ledgerText);
        const out = repo.steward(['sprint', 'status', SID]);
        const cli = new Map(out.split('\n').filter(Boolean).map((l) => l.trim().split(/\s+/) as [string, string]));
        const ours = foldStates(parsePlan(planText), parseLedger(ledgerText).entries);
        assert.deepEqual([...ours.values()].map((t) => [t.id, t.state]), [...cli].map(([id, state]) => [id, state]));
        console.log(`    steward sprint status agrees on ${cli.size} tasks`);
      } finally {
        repo.remove();
      }
    });
  });

  describe('a broken ledger line', () => {
    it('shows "unreadable" and the states as of the line before; the hash chain is not re-verified', () => {
      const lines = ledgerText.split('\n');
      lines[19] = '{"hash": "torn';
      const s = snap(lines.join('\n'));
      assert.equal(s.ledger?.unreadableLine, 20);
      const nodes = sprintNodes([s], { now: at('2026-11-26T22:30:00Z') });
      assert.equal(byId(nodes, `sprint/${SID}/unreadable`)?.label, 'ledger line 20: unreadable');
      assert.equal(s.states.get('T04')?.state, 'done');
      assert.equal(s.states.get('T05')?.state, 'ready');
      assert.equal(s.states.get('T05')?.go, false);
    });

    it('accepts a ledger whose hashes do not chain (that is the CLI\'s check)', () => {
      const s = snap(ledgerText.replace(/"hash":"[0-9a-f]{64}"/g, '"hash":"x"'));
      assert.equal(s.ledger?.unreadableLine, undefined);
      assert.equal(s.states.get('T08')?.state, 'done');
    });

    it('waits for a last line still being written instead of calling it unreadable', () => {
      const s = snap(`${ledgerText}{"by":"human","kind":"or`);
      assert.equal(s.ledger?.unreadableLine, undefined);
      assert.equal(s.ledger?.partialTail, true);
      assert.equal(s.ledger?.entries.length, ledgerLines.length);
    });

    for (const [what, line] of [['a JSON array', '[1]'], ['a line without kind', '{"seq": 3}'], ['an empty line', '']] as const) {
      it(`calls ${what} unreadable`, () => {
        assert.equal(snap(`${firstLines(3)}${line}\n${ledgerText.split('\n').slice(3).join('\n')}`).ledger?.unreadableLine, 4);
      });
    }
  });

  describe('the status bar', () => {
    it('shows `▶ T01 12 min · 0/12` while T01 runs', () => {
      const s = snap(firstLines(4));
      assert.deepEqual(sprintStatus([s], at('2026-11-26T20:27:30Z')).text, '▶ T01 12 min · 0/12');
    });

    it('counts done tasks only (a skip is not done) and marks the checking step', () => {
      assert.equal(sprintStatus([snap(firstLines(21))], at('2026-11-26T21:18:49Z')).text, '▶ T05 3 min · 3/12');
      assert.equal(sprintStatus([snap(firstLines(22))], at('2026-11-26T21:25:00Z')).text, '▶ T05 checking 9 min · 3/12');
    });

    it('is hidden when nothing runs', () => {
      assert.equal(sprintStatus([snap()], at('2026-11-26T22:30:00Z')).visible, false);
    });
  });

  describe('the three notifications', () => {
    const at4 = snap(firstLines(4));

    it('none on the first read', () => {
      assert.deepEqual(notices(undefined, at4), []);
    });

    it('a task finished, and the next one waits for an order', () => {
      const got = notices(at4, snap(firstLines(6)));
      assert.deepEqual(got.map((n) => [n.kind, n.task, n.level]), [['finished', 'T01', 'info'], ['waiting', 'T02', 'info']]);
      assert.equal(got[0].message, `Sprint ${SID}: T01 done (2 of 2 checks passed); sprint/${SID}/T01 waits for your merge.`);
      assert.equal(got[1].message, `Sprint ${SID}: T02 is waiting for an order: steward sprint go ${SID} T02`);
    });

    it('a failed task is a warning with its note', () => {
      const got = notices(snap(firstLines(22)), snap(firstLines(23)));
      assert.deepEqual(got.map((n) => [n.kind, n.task, n.level]), [['finished', 'T05', 'warning']]);
      assert.match(got[0].message, /T05 failed \(3 of 4 checks passed\): an acceptance command did not pass/);
    });

    it('the watchdog stopped a task (steward run exited 124), instead of "finished"', () => {
      const running = `${ledgerText}{"kind":"order","order":"go","task":"T09","by":"human","time":"2026-11-26T23:00:00Z"}\n` +
        '{"kind":"state","state":"running","task":"T09","branch":"sprint/x/T09","time":"2026-11-26T23:00:01Z"}\n';
      const stopped = `${running}{"kind":"state","state":"failed","task":"T09","branch":"sprint/x/T09","note":"steward run exited 124","time":"2026-11-26T23:30:01Z"}\n`;
      const got = notices(snap(running), snap(stopped));
      assert.deepEqual(got.map((n) => [n.kind, n.task, n.level]), [['watchdog', 'T09', 'warning']]);
      assert.match(got[0].message, /the watchdog stopped T09/);
    });

    it('nothing when nothing changed', () => {
      assert.deepEqual(notices(snap(), snap()), []);
    });
  });

  describe('no git (T12, D1)', () => {
    it('check-ignore is the only git command; the sprint reads are gone', () => {
      assert.deepEqual(Object.keys(git.gitCommands), ['checkIgnoreReport']);
      for (const gone of ['sprintGitCommands', 'sprintGitRunner', 'SPRINT_BASES', 'LOG_FORMAT']) assert.equal(gone in git, false, gone);
    });

    it('the reader takes no git runner and reads only development/sprints/', async () => {
      const root = realpathSync(mkdtempSync(join(tmpdir(), 'steward-sprint-nogit-')));
      try {
        mkdirSync(join(root, 'development', 'sprints'), { recursive: true });
        writeFileSync(join(root, 'development', 'sprints', `${SID}.toml`), planText);
        writeFileSync(join(root, 'development', 'sprints', `${SID}.jsonl`), ledgerText);
        // A .git that points nowhere: a reader that ran git here would get errors, not states.
        writeFileSync(join(root, '.git'), 'gitdir: /nonexistent\n');
        const [snapshot] = await new SprintReader(root).read();
        assert.equal(snapshot.states.get('T08')?.state, 'done');
        assert.equal(snapshot.states.get('T08')?.commit, ledgerLines.filter((l) => l.task === 'T08' && l.commit).at(-1)?.commit);
        assert.equal('git' in snapshot, false);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    });

    it('shows the commit the ledger records when a task ends, and says commits mid-task are not shown', () => {
      const nodes = sprintNodes([snap()], { now: at('2026-11-26T22:30:00Z') });
      const t01 = ledgerLines.find((l) => l.task === 'T01' && l.state === 'done')!;
      assert.equal(byId(nodes, `sprint/${SID}/task/T01/commit`)?.label, `commit: ${String(t01.commit).slice(0, 12)}`);
      assert.match(byId(nodes, `sprint/${SID}/task/T01/commit`)?.tooltip ?? '', /the commit the sprint ledger records when T01 ended/);
      const running = sprintNodes([snap(firstLines(4))], { now: at('2026-11-26T20:27:30Z') });
      assert.equal(byId(running, `sprint/${SID}/task/T01/commit`), undefined);
      assert.match(byId(running, `sprint/${SID}/task/T01`)?.tooltip ?? '', /reads no git/);
      assert.equal(walk(nodes).some((n) => n.id.endsWith('/git') || n.id.endsWith('/last-commit')), false);
    });
  });

  describe('derived states (T11-09)', () => {
    it('labels ready, blocked and planned as derived, and ledger states as the ledger\'s', () => {
      const nodes = sprintNodes([snap()], { now: at('2026-11-26T22:30:00Z') });
      const tip = (id: string, from = nodes) => byId(from, `sprint/${SID}/task/${id}`)?.tooltip?.split('\n')[1];
      assert.equal(tip('T08'), 'state: done (sprint ledger)');
      assert.equal(tip('T02'), 'state: skipped (sprint ledger)');
      assert.equal(tip('T09'), 'state: ready (derived from the sprint file and ledger, as steward sprint status derives it)');
      assert.equal(tip('T10'), 'state: planned (derived: no ledger state yet)');
      const failed = `${ledgerText}${JSON.stringify({ kind: 'state', state: 'failed', task: 'T09', time: '2026-11-26T23:00:00Z' })}\n`;
      const blocked = sprintNodes([snap(failed)], { now: at('2026-11-26T23:30:00Z') });
      assert.equal(tip('T10', blocked), 'state: blocked (derived from the sprint file and ledger, as steward sprint status derives it)');
    });
  });

  describe('ledger entries validated before the fold; incomplete on every surface (T11-04)', () => {
    const running = firstLines(4);
    for (const [what, entry] of [
      ['an unknown state', { kind: 'state', state: 'finished', task: 'T01', time: '2026-11-26T20:30:00Z' }],
      ['a state without its task', { kind: 'state', state: 'done', time: '2026-11-26T20:30:00Z' }],
      ['an invalid calendar time', { kind: 'state', state: 'done', task: 'T01', time: '2026-02-30T20:30:00Z' }],
      ['a time without its zone', { kind: 'state', state: 'done', task: 'T01', time: '2026-11-26T20:30:00' }],
      ['checks that are not a list', { kind: 'state', state: 'done', task: 'T01', checks: 'all passed', time: '2026-11-26T20:30:00Z' }],
      ['a check exit that is text', { kind: 'state', state: 'done', task: 'T01', checks: [{ command: 'x', exit: '0' }], time: '2026-11-26T20:30:00Z' }],
      ['a note that is a number', { kind: 'state', state: 'failed', task: 'T01', note: 3, time: '2026-11-26T20:30:00Z' }],
      ['an unknown order', { kind: 'order', order: 'cancel', task: 'T01', time: '2026-11-26T20:30:00Z' }],
      ['an empty kind', { kind: '', time: '2026-11-26T20:30:00Z' }],
    ] as const) {
      it(`stops at ${what}: unreadable, the states as of the line before`, () => {
        const s = snap(`${running}${JSON.stringify(entry)}\n`);
        assert.equal(s.ledger?.unreadableLine, 5);
        assert.equal(s.states.get('T01')?.state, 'running');
        assert.match(s.incomplete ?? '', /line 5 is unreadable/);
      });
    }

    it('marks the tree, the task tooltips and the status bar incomplete, and sends no notification', () => {
      const lines = ledgerText.split('\n');
      const before = snap(running);
      const broken = `${running}${lines[4]}\nnot a ledger line\n`;
      const after = snap(broken);
      assert.equal(after.states.get('T01')?.state, 'checking');
      const now = at('2026-11-26T20:27:30Z');
      const nodes = sprintNodes([after], { now });
      assert.match(nodes[0].description ?? '', / · ledger incomplete$/);
      assert.match(byId(nodes, `sprint/${SID}/task/T01`)?.tooltip ?? '', /incomplete: ledger line 6 is unreadable; states as of line 5/);
      assert.match(sprintStatus([after], now).text, / · incomplete$/);
      assert.match(sprintStatus([after], now).tooltip, /Incomplete: ledger line 6/);
      // A done line after the broken one is never folded, so no "finished" can come from it.
      const done = snap(`${broken}${lines[5]}\n`);
      assert.equal(done.states.get('T01')?.state, 'checking');
      assert.deepEqual(notices(before, after), []);
      assert.deepEqual(notices(before, done), []);
    });

    it('a ledger past the event limit is incomplete, folded up to the limit', () => {
      const line = JSON.stringify({ kind: 'note', time: '2026-11-26T20:30:00Z' });
      const s = snap(`${running}${`${line}\n`.repeat(MAX_LEDGER_EVENTS)}`);
      assert.equal(s.ledger?.truncated, true);
      assert.equal(s.ledger?.entries.length, MAX_LEDGER_EVENTS);
      assert.match(s.incomplete ?? '', /more than 50000 entries/);
      assert.deepEqual(notices(snap(running), s), []);
    });

    it('a ledger the reader could not read is incomplete and named in the tree', () => {
      const s = snapshotOf(SID, planText, undefined, { ledger: 'not valid UTF-8' });
      assert.match(s.incomplete ?? '', /not valid UTF-8/);
      const nodes = sprintNodes([s], { now: at('2026-11-26T22:30:00Z') });
      assert.equal(byId(nodes, `sprint/${SID}/ledger-error`)?.label, 'ledger: not valid UTF-8');
    });

    it('shows a last line still being written, without calling it unreadable', () => {
      const nodes = sprintNodes([snap(`${running}{"kind":"st`)], { now: at('2026-11-26T20:27:30Z') });
      assert.equal(byId(nodes, `sprint/${SID}/partial`)?.label, 'ledger line 5: still being written');
      assert.equal(byId(nodes, `sprint/${SID}/unreadable`), undefined);
    });
  });

  describe('the bounded reader (T11-03, T11-04)', () => {
    let dir: string;
    beforeEach(() => {
      dir = realpathSync(mkdtempSync(join(tmpdir(), 'steward-sprint-read-')));
    });
    afterEach(() => rmSync(dir, { recursive: true, force: true }));

    it('rejects invalid UTF-8 instead of replacing it', async () => {
      writeFileSync(join(dir, 'a.toml'), Buffer.from([0x61, 0x20, 0x3d, 0x20, 0x22, 0xff, 0x22, 0x0a]));
      assert.deepEqual(await readBounded(dir, 'a.toml', 1024), { error: 'not valid UTF-8' });
      // A growing ledger: only the complete lines must be valid; the line being written may end mid-character.
      writeFileSync(join(dir, 'b.jsonl'), Buffer.concat([Buffer.from('{"kind":"x"}\n{"note":"'), Buffer.from('é').subarray(0, 1)]));
      assert.ok('text' in await readBounded(dir, 'b.jsonl', 1024, true));
      writeFileSync(join(dir, 'c.jsonl'), Buffer.concat([Buffer.from('{"note":"'), Buffer.from([0xff]), Buffer.from('"}\n{"kind":"x"}\n')]));
      assert.deepEqual(await readBounded(dir, 'c.jsonl', 1024, true), { error: 'not valid UTF-8' });
    });

    it('never follows a link, never blocks on a FIFO, and never reads past the size limit', async function () {
      writeFileSync(join(dir, 'target'), 'x');
      symlinkSync(join(dir, 'target'), join(dir, 'link.toml'));
      assert.deepEqual(await readBounded(dir, 'link.toml', 1024), { error: 'a link, not a regular file' });
      writeFileSync(join(dir, 'big.toml'), 'x'.repeat(2048));
      assert.deepEqual(await readBounded(dir, 'big.toml', 1024), { error: 'larger than 1 KB' });
      assert.deepEqual(await readBounded(dir, 'missing.toml', 1024), { missing: true });
      if (spawnSync('mkfifo', [join(dir, 'fifo.toml')]).status !== 0) return;
      this.timeout(3000);
      assert.deepEqual(await readBounded(dir, 'fifo.toml', 1024), { error: 'not a regular file' });
    });

    it(`reads at most the ${MAX_SPRINTS} newest sprints`, async () => {
      const sprints = join(dir, 'development', 'sprints');
      mkdirSync(sprints, { recursive: true });
      for (let i = 0; i < MAX_SPRINTS + 5; i++) writeFileSync(join(sprints, `2026-01-${String(i).padStart(2, '0')}-s.jsonl`), '');
      const read = await new SprintReader(dir).read();
      assert.equal(read.length, MAX_SPRINTS);
      assert.equal(read[0].id, '2026-01-05-s');
    });
  });

  describe('a scratch sprint on the pinned CLI: a shell task that commits twice', function () {
    let repo: ScratchRepo | undefined;

    before(function () {
      if (!haveCli || !haveGit) this.skip();
    });

    after(() => repo?.remove());

    it('shows the CLI\'s states, times, exit codes and recorded commit, and writes nothing', async function () {
      this.timeout(120000);
      repo = scratchRepo();
      const sprints = join(repo.root, 'development', 'sprints');
      mkdirSync(sprints, { recursive: true });
      const start = new Date(Date.now() - 5 * 60_000).toISOString().replace(/\.\d+Z$/, 'Z');
      const end = new Date(Date.now() + 3 * 3600_000).toISOString().replace(/\.\d+Z$/, 'Z');
      writeFileSync(join(sprints, 'scratch.toml'), [
        'schema = "steward.sprint/0.1"', '', '[sprint]', 'id = "scratch"', `window = { start = ${start}, end = ${end} }`,
        'max_parallel = 1', 'dispatch = "order"', '', '[[task]]', 'id = "T1"', 'title = "Commit twice"', 'agent = "shell"',
        'limits = { wall_minutes = 10, idle_minutes = 5 }',
        "command = '''printf a > a.txt && git add a.txt && git commit -qm 'first change' && printf b > b.txt && git add b.txt && git commit -qm 'second change''''",
        'done = ["test -f a.txt", "test -f b.txt"]', '',
        '[[task]]', 'id = "T2"', 'title = "Waits for T1"', 'agent = "shell"', 'after = ["T1"]', 'command = "true"', 'done = ["true"]', '',
      ].join('\n'));
      repo.steward(['sprint', 'go', 'scratch', 'T1']);
      repo.steward(['sprint', 'start', 'scratch'], 90000);

      const ledger = readFileSync(join(sprints, 'scratch.jsonl'), 'utf8');
      const lines = ledger.split('\n').filter(Boolean).map((l) => JSON.parse(l) as Record<string, unknown>);
      const running = lines.find((l) => l.kind === 'state' && l.state === 'running')!;
      const done = lines.find((l) => l.kind === 'state' && l.state === 'done')!;
      assert.ok(running && done, `the scratch sprint did not finish: ${ledger}`);

      const before = treeDigest(repo.root);
      const reader = new SprintReader(repo.root);
      const [snapshot] = await reader.read();
      await reader.read();
      assert.deepEqual(treeDigest(repo.root), before, 'reading the sprint changed a file (worktree, .git or ledger)');

      const t1 = snapshot.states.get('T1')!;
      assert.equal(t1.state, 'done');
      assert.equal(t1.runningTime, running.time);
      assert.equal(t1.endedTime, done.time);
      assert.deepEqual(t1.checks, done.checks);
      assert.equal(t1.worktree, '.steward/sprints/scratch/T1');
      // The commit the CLI recorded when T1 ended is the head of the task's branch: the second of its two commits.
      // (git runs here in the test only, to check the fixture; the view reads no git.)
      const head = spawnSync('git', ['-C', join(repo.root, '.steward', 'sprints', 'scratch', 'T1'), 'log', '--format=%H %s', '-2'],
        { env: repo.env, encoding: 'utf8' }).stdout.trim().split('\n');
      assert.deepEqual(head.map((l) => l.slice(41)), ['second change', 'first change']);
      assert.equal(t1.commit, head[0].slice(0, 40));
      assert.equal(t1.commit, done.commit);

      const now = Date.now();
      const nodes = sprintNodes([snapshot], { now });
      assert.equal(byId(nodes, 'sprint/scratch/task/T1')?.description, 'DONE');
      assert.equal(byId(nodes, 'sprint/scratch/task/T1/commit')?.label, `commit: ${String(done.commit).slice(0, 12)}`);
      assert.deepEqual([0, 1].map((i) => byId(nodes, `sprint/scratch/task/T1/check/${i}`)?.label), ['exit 0', 'exit 0']);
      assert.equal(byId(nodes, 'sprint/scratch/task/T2')?.description, 'READY · ORDER NEEDED');
      const cli = new Map(repo.steward(['sprint', 'status', 'scratch']).split('\n').filter(Boolean).map((l) => l.trim().split(/\s+/) as [string, string]));
      assert.deepEqual([...snapshot.states.values()].map((t) => [t.id, t.state]), [...cli].map(([id, state]) => [id, state]));
      console.log(`    scratch sprint: T1 ${t1.state} at commit ${String(t1.commit).slice(0, 12)} (two commits on its branch); steward sprint status agrees`);
    });
  });
});

interface ScratchRepo {
  readonly root: string;
  readonly env: NodeJS.ProcessEnv;
  steward(args: string[], timeout?: number): string;
  remove(): void;
}

// A new git repository with `steward init` and one commit on main. Git runs with no global or system
// configuration, so the user's hooks, signing or templates never apply.
function scratchRepo(): ScratchRepo {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'steward-sprint-')));
  const empty = join(root, '..', `${root.split('/').pop()}-gitconfig`);
  writeFileSync(empty, '');
  const env = {
    ...process.env, STEWARD_NO_REGISTRY: '1', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: empty,
    GIT_AUTHOR_NAME: 'Scratch', GIT_AUTHOR_EMAIL: 'scratch@example.invalid', GIT_COMMITTER_NAME: 'Scratch',
    GIT_COMMITTER_EMAIL: 'scratch@example.invalid',
  };
  const run = (program: string, args: string[], timeout = 60000) => {
    const out = spawnSync(program, args, { cwd: root, env, encoding: 'utf8', timeout });
    if (out.status !== 0) throw new Error(`${program} ${args.join(' ')} exited ${out.status}: ${out.stderr}${out.stdout}`);
    return out.stdout;
  };
  run('git', ['init', '-q', '-b', 'main']);
  run(steward, ['init', '--repo', root]);
  run('git', ['add', '-A']);
  run('git', ['commit', '-qm', 'init']);
  return {
    root, env,
    steward: (args, timeout) => run(steward, [...args, '--repo', root], timeout),
    remove: () => {
      rmSync(root, { recursive: true, force: true });
      rmSync(empty, { force: true });
    },
  };
}

// Every entry under `root` (the .git folder and the worktrees included) with its type, size, mtime and content hash.
function treeDigest(root: string): Record<string, string> {
  const out: Record<string, string> = {};
  const visit = (dir: string, rel: string) => {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name);
      const key = rel ? `${rel}/${name}` : name;
      const st = lstatSync(path);
      if (st.isSymbolicLink()) out[key] = `link ${readlinkSync(path)}`;
      else if (st.isDirectory()) {
        out[key] = 'dir';
        visit(path, key);
      } else {
        out[key] = `${st.size} ${st.mtimeMs} ${createHash('sha256').update(readFileSync(path)).digest('hex')}`;
      }
    }
  };
  visit(root, '');
  return out;
}
