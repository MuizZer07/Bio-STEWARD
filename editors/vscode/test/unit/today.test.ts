import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseTimeline, type TimelineState } from '../../src/model/timeline';
import {
  BRIEF_HANDOFF_LINES, orderProjects, parseAuditProgress, pendingSummary, reopenDue, SOURCES_NOTE, todayNodes,
  whereAmIText, type AuditProgress, type AuditState, type TodayInput, type WhereAmIInput,
} from '../../src/model/today';
import type { Report } from '../../src/model/report';
import type { ViewNode } from '../../src/model/views';

// P1 Today and P2 "Where am I?" (task U02): parity against the U01 corpus of test/fixtures/cockpit/, the
// 0.20.6 outputs these panels read. Every pending item must appear exactly as the CLI wrote it, under a part that
// names its source.

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
const cockpit = (name: string) => readFileSync(join(fixtures, 'cockpit', name), 'utf8');
const auditOf = (name: string): AuditProgress => {
  const audit = parseAuditProgress(cockpit(`audit-progress/${name}.json`));
  assert.ok(audit, name);
  return audit;
};
const timelineOf = (name: string): TimelineState => {
  const parsed = parseTimeline(cockpit(`timeline/${name}.json`));
  assert.ok(parsed, name);
  return parsed.milestones.length ? { kind: 'ready', rows: parsed.milestones } : { kind: 'none' };
};
const ready = (audit: AuditProgress): AuditState => ({ kind: 'ready', audit });
const raw = (name: string) => JSON.parse(cockpit(`audit-progress/${name}.json`)) as {
  pending: { signatures_waiting: string[]; exchange_open?: string[]; own_open?: string[];
    sprints: { sprint: string; open?: string[] }[]; milestones: { id: string; state: string; days_left: number }[] };
  where: { branch: string; toolkit_version: string };
};

const input = (name: string, root = `/w/${name}`): TodayInput => ({
  root, name, trusted: true, audit: ready(auditOf(name)), timeline: timelineOf(name),
  handoff: { kind: 'missing', path: 'development/HANDOFF.md' },
});
const byId = (nodes: readonly ViewNode[], suffix: string) => nodes.find((n) => n.id.endsWith(suffix));

describe('Today and Where am I? (U02)', () => {
  describe('steward audit progress --json', () => {
    it('reads both U01 fixtures and refuses other documents', () => {
      assert.equal(auditOf('geo').pending.signatures_waiting.length, 0);
      assert.equal(auditOf('geo-cockpit').pending.signatures_waiting.length, 1);
      const good = JSON.parse(cockpit('audit-progress/geo-cockpit.json'));
      for (const bad of [
        { ...good, schema: 'steward.progress_audit/0.2' },
        { ...good, pending: undefined },
        { ...good, pending: { ...good.pending, signatures_waiting: 'spend' } },
        { ...good, pending: { ...good.pending, sprints: [{ open: [] }] } },
        { ...good, pending: { ...good.pending, milestones: [{ id: 'x', state: 'late' }] } },
      ]) assert.equal(parseAuditProgress(JSON.stringify(bad)), undefined);
      assert.equal(parseAuditProgress('not json'), undefined);
    });
  });

  describe('P1 Today', () => {
    it('shows every pending item of geo-cockpit as written, each part labelled with its source (parity)', () => {
      const nodes = todayNodes([input('geo-cockpit')]);
      const fixture = raw('geo-cockpit').pending;
      assert.equal(nodes[0].label, 'Sources');
      assert.equal(nodes[0].tooltip, SOURCES_NOTE);
      const section = (key: string) => {
        const node = byId(nodes, `/${key}`);
        assert.ok(node, key);
        assert.match(node.description ?? '', /steward audit progress$/, key);
        return node;
      };
      const labels = (key: string) => (section(key).children ?? []).map((c) => c.label);
      assert.deepEqual(labels('signatures'), fixture.signatures_waiting);
      assert.deepEqual(labels('exchange'), fixture.exchange_open);
      assert.deepEqual(labels('own'), fixture.own_open);
      assert.deepEqual(labels('sprints'), fixture.sprints.map((s) => s.sprint));
      // E01, newest first: a sprint's open tasks highest ID first; milestones the latest due (most days left) first.
      assert.deepEqual(section('sprints').children?.map((c) => c.description), ['T5, T4, T3, T2, T1']);
      const latest = [...fixture.milestones].sort((a, b) => b.days_left - a.days_left);
      assert.deepEqual(labels('milestones'), latest.map((m) => m.id));
      assert.deepEqual(labels('milestones'), ['release', 'review', 'preprint', 'abstract', 'kickoff']);
      assert.deepEqual(section('milestones').children?.map((c) => c.description?.split(' · ')[0]), latest.map((m) => m.state));
      assert.equal(section('signatures').label, `Signatures waiting (${fixture.signatures_waiting.length})`);
      assert.equal(section('milestones').label, `Milestones (${fixture.milestones.length})`);
    });

    it('labels the resume and countdown rows with their sources; the countdown is the timeline\'s next milestone', () => {
      const nodes = todayNodes([input('geo-cockpit')]);
      const resume = byId(nodes, '/resume');
      assert.equal(resume?.description, 'no handoff yet (development/HANDOFF.md) · the session handoff');
      assert.equal(resume?.command, 'resume');
      assert.equal(resume?.root, '/w/geo-cockpit');
      // The first milestone without an outcome in timeline/geo-cockpit.json is "abstract" (kickoff is met).
      assert.equal(byId(nodes, '/milestone')?.description, 'abstract · 9675.0 days ago · DUE (RECORD ITS OUTCOME) · steward timeline');
      const found = todayNodes([{ ...input('geo-cockpit'), handoff: { kind: 'found', path: 'notes/HANDOFF.md', text: 'x' } }]);
      assert.equal(byId(found, '/resume')?.description, 'notes/HANDOFF.md · the session handoff');
    });

    it('shows nothing pending for geo, with every part still present and labelled', () => {
      const nodes = todayNodes([input('geo')]);
      for (const key of ['signatures', 'exchange', 'own', 'sprints', 'milestones']) {
        const node = byId(nodes, `/${key}`);
        assert.equal(node?.description, 'none · steward audit progress', key);
        assert.equal(node?.children?.length, 0, key);
      }
      assert.equal(byId(nodes, '/milestone')?.description, 'no milestones · steward timeline');
      assert.equal(pendingSummary(ready(auditOf('geo'))), 'nothing pending');
    });

    it('says when audit progress is not set up, unreadable or did not finish, never inventing rows', () => {
      for (const kind of ['not-configured', 'unreadable', 'failed'] as const) {
        const nodes = todayNodes([{ ...input('geo'), audit: { kind } }]);
        assert.deepEqual(nodes.map((n) => n.id.split('/').pop()), ['source', 'resume', 'milestone', 'audit'], kind);
        assert.match(byId(nodes, '/audit')?.description ?? '', /steward audit progress/);
      }
      assert.deepEqual(todayNodes([{ ...input('geo'), trusted: false }]), []);
    });

    it('with several projects: one block each, ordered by the audit counts, rows never mixed (AC-multi)', () => {
      const geo = input('geo');
      const full = input('geo-cockpit');
      const nodes = todayNodes([geo, full]);
      assert.deepEqual(nodes.map((n) => n.label), ['Sources', 'geo-cockpit', 'geo']);
      assert.match(nodes[0].tooltip ?? '', /ordered by the counts steward audit progress reports/);
      assert.equal(nodes[1].description, '1 signature waiting · 1 exchange item open · 1 own request open · 1 sprint with open tasks');
      assert.equal(nodes[2].description, 'nothing pending');
      const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
      for (const block of nodes.slice(1)) {
        for (const node of walk(block)) assert.ok(node.id.startsWith(block.id), `${node.id} inside ${block.id}`);
      }
      assert.equal(byId(nodes[2].children ?? [], '/signatures')?.children?.length, 0, 'geo shows none of geo-cockpit\'s items');
    });

    it('orders by signatures, then exchange, then own requests, then sprints; ties and unreadable keep workspace order', () => {
      const audit = (s: number, e: number, o: number, p: number): AuditState => ready({
        schema: 'steward.progress_audit/0.1',
        pending: {
          signatures_waiting: Array(s).fill('x'), exchange_open: Array(e).fill('x'), own_open: Array(o).fill('x'),
          sprints: Array(p).fill({ sprint: 's' }), milestones: [],
        },
      });
      const projects: [string, AuditState][] = [
        ['broken', { kind: 'unreadable' }], ['a', audit(0, 0, 0, 1)], ['b', audit(0, 1, 0, 0)], ['c', audit(1, 0, 0, 0)],
        ['d', audit(0, 1, 0, 0)], ['e', audit(0, 0, 1, 0)], ['loading', { kind: 'loading' }],
      ];
      assert.deepEqual(orderProjects(projects, ([, a]) => a).map(([name]) => name), ['c', 'b', 'd', 'e', 'a', 'broken', 'loading']);
    });
  });

  describe('P2 Where am I?', () => {
    const report = JSON.parse(readFileSync(join(fixtures, 'reports', 'geo.json'), 'utf8')) as Report;
    const page = (extra: Partial<WhereAmIInput> = {}, options = {}) => whereAmIText({
      ...input('geo-cockpit'), gate: 'default', now: new Date('2026-11-27T00:00:00Z'), ...extra,
    }, options);

    it('composes every part with its source, from the fixtures (parity)', () => {
      const text = page({ report: { report, freshness: 'fresh', partial: false } });
      const fixture = raw('geo-cockpit');
      assert.ok(text.startsWith('# Where am I? · geo-cockpit\n\nComposed from steward audit progress'));
      for (const heading of ['## Where it stands · from steward audit progress', '## Gate · from the last steward check report',
        '## You left off · from the session handoff', '## Next target · from steward timeline',
        '## Waiting on you · from steward audit progress', '## Waiting on others · from steward audit progress',
        '## Sprints · from steward audit progress', '## Milestones · from steward audit progress', '## Not on this page yet']) {
        assert.ok(text.includes(`\n${heading}`), heading);
      }
      assert.ok(text.includes(`- branch ${fixture.where.branch} · project version none · latest tag none · toolkit ${fixture.where.toolkit_version}`));
      for (const item of [...fixture.pending.signatures_waiting, ...fixture.pending.exchange_open ?? [], ...fixture.pending.own_open ?? []]) {
        assert.ok(text.includes(`  - ${item}\n`), item);
      }
      for (const s of fixture.pending.sprints) assert.ok(text.includes(`  - ${s.sprint}: ${[...(s.open ?? [])].reverse().join(', ')}\n`));
      for (const m of fixture.pending.milestones) assert.ok(text.includes(`  - ${m.id}: ${m.state} · `), m.id);
      const gate = report.verdict.gates.find((g) => g.name === 'default');
      assert.ok(gate);
      assert.ok(text.includes(`- default: ${gate.eligible ? '✓ ELIGIBLE' : '✗ NOT ELIGIBLE'} · ${gate.blocking.length} blocking of ${gate.required_count} required · report fresh`));
      assert.ok(text.includes('- abstract: Conference abstract (submission) · due 2000-06-01T00:00:00+00:00 · 9675.0 days ago · DUE (RECORD ITS OUTCOME)'));
      assert.ok(text.includes('  - Tasks: 1 of 1 done'));
    });

    it('quotes the handoff as written; the agent brief cuts it to its first lines and says so', () => {
      const lines = Array.from({ length: BRIEF_HANDOFF_LINES + 5 }, (_, i) => `line ${i + 1} <b>$(bug)</b>`);
      const handoff = { kind: 'found' as const, path: 'development/HANDOFF.md', text: `${lines.join('\n')}\n` };
      const full = page({ handoff });
      for (const line of lines) assert.ok(full.includes(`\n> ${line}\n`), line);
      const brief = page({ handoff }, { brief: true, handoffLines: BRIEF_HANDOFF_LINES });
      assert.ok(brief.startsWith('# Bio-STEWARD agent brief · geo-cockpit\n'));
      assert.ok(brief.includes(`> line ${BRIEF_HANDOFF_LINES} `));
      assert.ok(!brief.includes(`> line ${BRIEF_HANDOFF_LINES + 1} `));
      assert.ok(brief.includes(`(The first ${BRIEF_HANDOFF_LINES} of ${lines.length} lines; read development/HANDOFF.md for the rest.)`));
      assert.ok(brief.length < 6000, 'a brief stays short');
    });

    it('says what is missing instead of guessing (no report, no handoff, no audit)', () => {
      const text = page({ audit: { kind: 'failed' }, handoff: { kind: 'missing', path: 'development/HANDOFF.md' }, timeline: { kind: 'none' } });
      assert.ok(text.includes('No check report in this session.'));
      assert.ok(text.includes('No handoff yet (development/HANDOFF.md).'));
      assert.ok(text.includes('steward audit progress did not finish; see the log.'));
      assert.ok(text.includes('\n## Next target · from steward timeline\n\nno milestones\n'));
      assert.ok(!text.includes('## Sprints'), 'no audit, no audit lists');
    });

    it('names the last open as kept by the extension', () => {
      const text = page({ lastSeen: '2026-11-17T00:00:00.000Z' });
      assert.ok(text.includes('Last open in VS Code: 2026-11-17 (10.0 days ago; kept by the extension, not the repository).'));
    });
  });

  describe('P2 shown once on reopening', () => {
    const now = new Date('2026-11-27T00:00:00Z');
    const on = { showOnReopen: true, afterDays: 3 };
    it('is due after more than N days, never on a first open, and never with the setting off', () => {
      assert.equal(reopenDue('2026-11-20T00:00:00Z', now, on), true);
      assert.equal(reopenDue('2026-11-24T00:00:00Z', now, on), false, 'exactly 3 days is not more than 3');
      assert.equal(reopenDue('2026-11-26T00:00:00Z', now, on), false);
      assert.equal(reopenDue(undefined, now, on), false, 'first open');
      assert.equal(reopenDue('2026-11-01T00:00:00Z', now, { ...on, showOnReopen: false }), false, 'off switch');
      assert.equal(reopenDue('2026-11-25T00:00:00Z', now, { ...on, afterDays: 1 }), true);
      assert.equal(reopenDue('garbage', now, on), false);
      assert.equal(reopenDue('2027-01-01T00:00:00Z', now, on), false, 'a time in the future');
      assert.equal(reopenDue('2026-11-25T00:00:00Z', now, { ...on, afterDays: 0 }), true, 'below 1 day counts as 1');
    });
  });
});
