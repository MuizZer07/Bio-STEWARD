// The countdown (S3). AC-S3: the countdown equals `timeline --json`: here for hand-made rows and, when the pinned
// CLI is installed, for its own output on a scratch project.
import { strict as assert } from 'node:assert';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { commands } from '../../src/cli/commands';
import { CliRunner } from '../../src/cli/runner';
import {
  countdownView, daysText, nextMilestone, parseTimeline, progressLines, type MilestoneRow,
} from '../../src/model/timeline';

const row = (fields: Partial<MilestoneRow>): MilestoneRow => ({
  id: 'preprint', title: 'Preprint on bioRxiv', kind: 'preprint', due: '2027-01-20T23:59:00-12:00',
  internal: '2027-01-13T23:59:00-12:00', days_left: 12.3, state: 'on track', open_work: 0, progress: {}, ...fields,
});

describe('countdown (S3)', () => {
  it('reads the CLI 0.20.6 shape and rejects anything else', () => {
    assert.deepEqual(parseTimeline('{"milestones": []}'), { milestones: [] });
    const doc = parseTimeline(JSON.stringify({ milestones: [row({})] }));
    assert.equal(doc?.milestones[0].id, 'preprint');
    for (const bad of ['', '[]', '{}', '{"milestones": {}}', '{"milestones": [{"id": "x"}]}',
      JSON.stringify({ milestones: [{ ...row({}), days_left: '12' }] })]) {
      assert.equal(parseTimeline(bad), undefined, bad);
    }
  });

  it('counts down to the soonest milestone without an outcome, in the CLI\'s words', () => {
    const rows = [
      row({ id: 'kickoff', state: 'met', days_left: -30, outcome: { state: 'met', decision: 'DECISIONS.md' } }),
      row({ id: 'preprint', state: 'at risk', days_left: 12.3, open_work: 2 }),
      row({ id: 'release', state: 'on track', days_left: 40 }),
    ];
    assert.equal(nextMilestone(rows)?.id, 'preprint');
    const view = countdownView({ kind: 'ready', rows });
    assert.equal(view.visible, true);
    assert.equal(view.text, '$(watch) preprint · 12.3 days left · AT RISK');
    assert.equal(view.tone, 'warning');
    assert.equal(view.milestone, 'preprint');
    assert.ok(view.tooltip.includes('State: at risk · open work: 2'));
    assert.ok(view.tooltip.some((line) => line.startsWith('Later: release (on track, 40.0 days left)')));
    assert.ok(!view.tooltip.join('\n').includes('kickoff'), 'a milestone with an outcome is not counted');

    assert.equal(countdownView({ kind: 'ready', rows: [row({ state: 'late', days_left: -2 })] }).text,
      '$(watch) preprint · 2.0 days ago · LATE');
    assert.equal(countdownView({ kind: 'ready', rows: [row({ state: 'late', days_left: -2 })] }).tone, 'error');
    assert.equal(countdownView({ kind: 'ready', rows: [row({ id: 'x$(bug)' })] }).text.includes('$(bug)'), false);
  });

  it('is hidden with nothing to count down to, and says so when the CLI answer is unusable', () => {
    for (const state of [undefined, { kind: 'none' } as const, { kind: 'loading' } as const, { kind: 'not-configured' } as const,
      { kind: 'ready', rows: [row({ outcome: { state: 'dropped', decision: 'x' } })] } as const]) {
      assert.equal(countdownView(state).visible, false, JSON.stringify(state));
    }
    assert.equal(countdownView({ kind: 'invalid' }).text, '$(watch) milestones invalid');
    assert.equal(countdownView({ kind: 'unreadable' }).text, '$(watch) milestones unreadable');
  });

  it('lists what blocks a milestone as the CLI prints it', () => {
    assert.deepEqual(progressLines(row({ progress: {
      gate: { name: 'submission', final: true, eligible: false, passed: 60, required: 71, not_applicable: 9, blocking: ['R-11', 'R-27'] },
      tasks: { done: 1, total: 3, open: ['T-2', 'T-3'], unknown: [] },
      items: { done: 0, total: 1, waiting: ['X-1'] },
      signatures: { needed: ['policy.change'], waiting: ['policy.change'] },
    } })), [
      'Gate submission (final checks): NOT ELIGIBLE, 60 of 71 required passed (9 not applicable); blocking R-11, R-27',
      'Tasks: 1 of 3 done; open T-2, T-3',
      'Items: 0 of 1 settled; waiting X-1',
      'Signatures: needs policy.change; waiting to be signed: policy.change',
    ]);
    assert.deepEqual(progressLines(row({ progress: { tasks: { error: 'no [tasks] board configured' } } })),
      ['Tasks: no [tasks] board configured']);
  });

  it('shows a malformed or missing gate verdict as unavailable, never as NOT ELIGIBLE (T11-09)', () => {
    const unavailable = 'Gate submission: unavailable (steward timeline gave no readable gate progress)';
    for (const gate of [
      { name: 'submission' },
      { name: 'submission', passed: 1, required: 2, not_applicable: 0 },
      { name: 'submission', eligible: 'yes', passed: 1, required: 2, not_applicable: 0 },
      { name: 'submission', eligible: true, passed: 1.5, required: 2, not_applicable: 0 },
      { name: 'submission', eligible: true, required: 2, not_applicable: 0 },
      { name: 'submission', eligible: false, passed: 1, required: 2, not_applicable: 0, blocking: 'R-11' },
    ]) {
      assert.deepEqual(progressLines(row({ progress: { gate } })), [unavailable], JSON.stringify(gate));
    }
    assert.deepEqual(progressLines(row({ progress: { gate: 'x' } })), ['Gate ?: unavailable (steward timeline gave no readable gate progress)']);
    assert.deepEqual(progressLines(row({ progress: { gate: { name: 'g', error: "unknown gate 'g'" } } })), ["Gate g: unknown gate 'g'"]);
    assert.deepEqual(progressLines(row({ progress: { gate: { name: 'g', eligible: true, passed: 3, required: 3, not_applicable: 0, blocking: [] } } })),
      ['Gate g: ELIGIBLE, 3 of 3 required passed (0 not applicable)']);
  });

  it('formats days like `steward timeline`', () => {
    assert.equal(daysText(12.3), '12.3 days left');
    assert.equal(daysText(0), '0.0 days left');
    assert.equal(daysText(-0.5), '0.5 days ago');
    assert.equal(daysText(1), '1.0 days left');
  });

  const pinned = join(__dirname, '..', '..', '..', '.cli', 'bin', 'steward');
  const cli = process.env.BIO_STEWARD_TEST_CLI === 'off' ? undefined : process.env.BIO_STEWARD_TEST_CLI || (existsSync(pinned) ? pinned : undefined);
  if (!cli) {
    it('equals the pinned CLI\'s timeline --json (skipped: no .cli/)');
  } else {
    it('equals the pinned CLI\'s timeline --json on a scratch project (AC-S3)', async function () {
      this.timeout(20000);
      const scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-timeline-test-')));
      try {
        const runner = new CliRunner({ cli, root: scratch, isTrusted: () => true, registry: 'disable' });
        const init = await runner.run(commands.init(), { confirm: async () => true });
        assert.equal(init.kind === 'completed' && init.exitCode, 0);
        await mkdir(join(scratch, 'development'), { recursive: true });
        const day = 86_400_000;
        const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
        await writeFile(join(scratch, 'development', 'milestones.toml'), [
          'schema = "steward.milestones/0.1"', '',
          '[[milestone]]', 'id = "kickoff"', 'title = "Kick-off"', `due = ${iso(Date.now() - 3 * day)}`,
          'outcome = { state = "met", decision = "DECISIONS.md 2026-11-26" }', '',
          '[[milestone]]', 'id = "preprint"', 'title = "Preprint"', 'kind = "preprint"', `due = ${iso(Date.now() + 12 * day)}`,
          'buffer_days = 3', '',
          '[[milestone]]', 'id = "release"', 'title = "Release"', 'kind = "release"', `due = ${iso(Date.now() + 40 * day)}`, '',
        ].join('\n'));
        const result = await runner.run(commands.timeline());
        assert.equal(result.kind, 'completed');
        assert.equal(result.kind === 'completed' && result.exitCode, 0, result.kind === 'completed' ? result.stderr : '');
        const doc = parseTimeline(result.kind === 'completed' ? result.stdout : '');
        assert.ok(doc, 'the CLI output passes the extension\'s validation');
        const raw = JSON.parse(result.kind === 'completed' ? result.stdout : '{}') as { milestones: MilestoneRow[] };
        const next = raw.milestones.find((m) => !m.outcome);
        assert.ok(next);
        assert.equal(next.id, 'preprint');
        const view = countdownView({ kind: 'ready', rows: doc.milestones });
        assert.equal(view.text, `$(watch) ${next.id} · ${Math.abs(next.days_left).toFixed(1)} days ${next.days_left >= 0 ? 'left' : 'ago'} · ${next.state.toUpperCase()}`);
        assert.ok(view.tooltip.includes(`State: ${next.state} · open work: ${next.open_work}`));
        console.log(`    countdown: ${view.text}`);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});
