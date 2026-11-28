import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DRIFT_SOURCE_NOTE, driftNodes, MILESTONES_FILE, NO_MILESTONES, stateCounts, stateLook } from '../../src/model/drift';
import { daysText, parseTimeline, type MilestoneRow, type TimelineState } from '../../src/model/timeline';
import type { ViewNode } from '../../src/model/views';

// P7 Drift (task U05; RELEASE_vscode_0.2.0_SPEC §3): the timeline states only, in the CLI's own
// words, from `steward timeline --json` (the U01 fixtures of CLI 0.20.6).

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
const timeline = (name: string): TimelineState => {
  const doc = parseTimeline(readFileSync(join(fixtures, 'cockpit', 'timeline', `${name}.json`), 'utf8'));
  assert.ok(doc, name);
  // As src/project.ts stores it: an empty list is "none".
  return doc.milestones.length ? { kind: 'ready', rows: doc.milestones } : { kind: 'none' };
};
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
const row = (fields: Partial<MilestoneRow>): MilestoneRow => ({
  id: 'preprint', title: 'Preprint', kind: 'preprint', due: '2027-01-20T00:00:00+00:00', internal: '2027-01-13T00:00:00+00:00',
  days_left: 3.2, state: 'at risk', open_work: 2, progress: {}, ...fields,
});

describe('Drift (U05)', () => {
  it('shows each milestone of steward timeline --json with its state as the CLI wrote it, the latest due first (parity, E01)', () => {
    const state = timeline('geo-cockpit');
    assert.equal(state.kind, 'ready');
    if (state.kind !== 'ready') return;
    const nodes = driftNodes([{ root: '/p', name: 'geo-cockpit', timeline: state }]);
    assert.equal(nodes[0].label, 'Milestones');
    assert.equal(nodes[0].description, 'steward timeline · latest due first');
    assert.equal(nodes[0].tooltip, DRIFT_SOURCE_NOTE);
    const rows = nodes.slice(1);
    assert.equal(rows.length, state.rows.length);
    // E01: newest first, by the due date (the CLI's JSON keeps soonest first).
    const latestFirst = [...state.rows].sort((a, b) => Date.parse(b.due) - Date.parse(a.due));
    assert.deepEqual(rows.map((node) => node.label.split(':')[0]), latestFirst.map((r) => r.id));
    assert.deepEqual(rows.map((node) => node.label.split(':')[0]), ['release', 'review', 'preprint', 'abstract', 'kickoff']);
    rows.forEach((node, index) => {
      const milestone = latestFirst[index];
      assert.equal(node.kind, 'drift-milestone');
      assert.equal(node.label, `${milestone.id}: ${milestone.title}`);
      assert.equal(node.description, `${milestone.state} · ${daysText(milestone.days_left)}`);
      assert.ok(node.tooltip?.includes(`State: ${milestone.state} (steward timeline)`), milestone.id);
      assert.equal(node.command, undefined);
      assert.equal(node.code, milestone.id);
      assert.equal(node.path, `/p/${MILESTONES_FILE}`);
    });
    console.log(`      drift: ${rows.map((node) => `${node.label} [${node.description}]`).join(' | ')}`);
    assert.deepEqual(state.rows.map((r) => r.state), ['met', 'due (record its outcome)', 'late', 'on track', 'ready']);
    assert.ok(rows[4].tooltip?.includes('Outcome: met on 2000-03-01 · development/DECISIONS.md, 2000-03-01'));
    assert.ok(rows[2].tooltip?.includes('Tasks: 0 of 2 done; open GEO-001, GEO-003'));
  });

  it('shows "at risk", and a state it does not know, in the CLI\'s words; nothing is computed', () => {
    // The same due date: the higher ID first ('x' comes after 'preprint', so it is shown first).
    const nodes = driftNodes([{ root: '/p', name: 'p', timeline: { kind: 'ready', rows: [row({ id: 'x', state: 'some new state' }), row({})] } }]);
    assert.equal(nodes[1].description, 'some new state · 3.2 days left');
    assert.equal(nodes[2].description, 'at risk · 3.2 days left');
    assert.deepEqual(nodes[2].icon, { codicon: 'warning', tone: 'warning' });
    assert.deepEqual(stateLook('some new state'), { codicon: 'milestone' });
    assert.equal(stateLook('late').tone, 'failed');
    assert.equal(stateLook('due (record its outcome)').tone, 'warning');
    assert.match(DRIFT_SOURCE_NOTE, /Nothing is computed here/);
  });

  it('says so, in the CLI\'s own line, when there are no milestones, and when the timeline is not read', () => {
    const empty = driftNodes([{ root: '/p', name: 'geo', timeline: timeline('geo') }]);
    assert.equal(empty[1].label, NO_MILESTONES);
    assert.equal(NO_MILESTONES, 'No milestones. Add them to development/milestones.toml (see the guide "Plan to a deadline").');
    assert.equal(driftNodes([{ root: '/p', name: 'p' }])[1].label, 'not read yet');
    assert.match(driftNodes([{ root: '/p', name: 'p', timeline: { kind: 'invalid' } }])[1].label, /exited 65/);
  });

  it('with several projects: one block each, in the order given, with the count of each state, rows never mixed (AC-multi)', () => {
    const nodes = driftNodes([
      { root: '/c', name: 'geo-cockpit', timeline: timeline('geo-cockpit') },
      { root: '/g', name: 'geo', timeline: timeline('geo') },
    ]);
    assert.deepEqual(nodes.slice(1).map((node) => node.label), ['geo-cockpit', 'geo']);
    assert.equal(nodes[1].description, '1 met · 1 due (record its outcome) · 1 late · 1 on track · 1 ready');
    assert.equal(nodes[2].description, 'no milestones');
    assert.equal(stateCounts(undefined), 'not read yet');
    for (const block of nodes.slice(1)) {
      for (const node of walk(block).slice(1)) {
        assert.ok(node.id.startsWith(`drift/${block.root}/`), node.id);
        assert.equal(node.root, block.root, node.id);
      }
    }
  });
});
