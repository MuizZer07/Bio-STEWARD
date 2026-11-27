// View models (src/model/views.ts) over the fixture corpus of the pinned CLI.
//
// AC-3.1: for every fixture report, every number and list the Overview, the Results tree and the status bar show
// equals the JSON. The parity walk visits every node and fails on a node it has no rule for, so a new row cannot
// be added without saying where its numbers come from.
// AC-3.2: a scoped run never changes a gate badge.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Gate, GateRef, Report, Status } from '../../src/model/report';
import {
  COUNT_ORDER, GROUP_BY, GROUP_ORDER, STATUS_LOOK, emptyState, initialState, isPartialReport, literal,
  overviewNodes, resultsNodes, statusBarView, treeAccessibilityLabel, withReport, withRunFailure, withRunning,
  type GroupBy, type ProjectState, type ViewNode,
} from '../../src/model/views';

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
const manifest = JSON.parse(readFileSync(join(fixtures, 'manifest.json'), 'utf8')) as {
  reports: Record<string, { report?: string; argv: string[] }>;
};
const corpus = Object.entries(manifest.reports).flatMap(([name, entry]) => entry.report
  ? [{ name, report: JSON.parse(readFileSync(join(fixtures, entry.report), 'utf8')) as Report }]
  : []);
const fullReports = corpus.filter(({ report }) => !isPartialReport(report));
const partialReports = corpus.filter(({ report }) => isPartialReport(report));

const ready: ProjectState = {
  ...initialState(true),
  cli: { kind: 'ready', version: '0.20.6', mode: 'limited', newerThanTested: false },
};

const numbers = (text: string | undefined) => (text?.match(/\d+/g) ?? []).map(Number);
const sameRef = (a: GateRef) => (b: GateRef) => a.rule === b.rule && a.subject === b.subject && a.status === b.status;

function walk(nodes: readonly ViewNode[], visit: (node: ViewNode) => void): number {
  let count = 0;
  for (const node of nodes) {
    visit(node);
    count += 1 + walk(node.children ?? [], visit);
  }
  return count;
}

function allIds(nodes: readonly ViewNode[]): string[] {
  const ids: string[] = [];
  walk(nodes, (node) => ids.push(node.id));
  return ids;
}

// Checks one verdict subtree (verdictNodes) against its report; returns the nodes it checked.
function checkVerdict(nodes: readonly ViewNode[], report: Report, partialRun: boolean, freshness: string, where: string): Set<ViewNode> {
  const checked = new Set<ViewNode>();
  const { verdict, envelope } = report;
  const mark = (node: ViewNode) => checked.add(node);

  const refs = (list: ViewNode, expected: readonly GateRef[], title: string) => {
    assert.equal(list.label, `${title} (${expected.length})`, `${where} ${list.id}`);
    assert.deepEqual(numbers(list.label), [expected.length]);
    assert.equal(list.children?.length ?? 0, expected.length, `${where} ${list.id} children`);
    list.children?.forEach((child, i) => {
      assert.equal(child.kind, 'ref');
      assert.deepEqual({ rule: child.ref?.rule, subject: child.ref?.subject, status: child.ref?.status },
        { ...expected[i] }, `${where} ${child.id}`);
      const result = child.ref?.index === undefined ? undefined : verdict.results[child.ref.index];
      if (result) {
        assert.ok(sameRef(expected[i])(result));
        assert.equal(child.label, `${result.rule} ${result.name}`);
      }
      assert.equal(child.description, `${STATUS_LOOK[expected[i].status].text} · ${expected[i].subject}`);
      mark(child);
    });
    mark(list);
  };

  for (const node of nodes) {
    switch (node.kind) {
      case 'report': {
        assert.equal(node.description,
          `${freshness} · ${verdict.project} · profile ${verdict.config_profile} · ${envelope.created}`, where);
        for (const part of [verdict.inputs_digest, envelope.tool_version, verdict.project]) {
          assert.ok(node.tooltip?.includes(part), `${where} report tooltip has ${part}`);
        }
        mark(node);
        break;
      }
      case 'gate': {
        const gate = verdict.gates.find((g) => node.id.endsWith(`/gate:${g.name}`)) as Gate;
        assert.ok(gate, `${where} ${node.id}`);
        assert.equal(node.label, `Gate ${gate.name}`);
        const badge = partialRun ? '– NOT EVALUATED BY THIS RUN'
          : !gate.evaluated ? '– NOT EVALUATED' : gate.eligible ? '✓ ELIGIBLE' : '✗ NOT ELIGIBLE';
        assert.ok(node.description?.startsWith(`${badge} · `), `${where} ${node.id}: ${node.description}`);
        assert.deepEqual(numbers(node.description), [gate.blocking.length, gate.required_count], `${where} ${node.id}`);
        const [reason, counted, blocking, waived, ...rest] = node.children ?? [];
        assert.equal(rest.length, 0);
        assert.equal(reason.kind, 'gate-reason');
        assert.equal(reason.description, gate.reason);
        assert.equal(counted.kind, 'gate-counts');
        assert.deepEqual(numbers(counted.description), [gate.evaluated_count,
          ...(gate.pass_count === undefined ? [] : [gate.pass_count]),
          ...(gate.not_applicable_count === undefined ? [] : [gate.not_applicable_count]), gate.required_count]);
        refs(blocking, gate.blocking, 'Blocking');
        refs(waived, gate.waived, 'Waived');
        [node, reason, counted].forEach(mark);
        break;
      }
      case 'counts': {
        const { counts } = verdict.summary;
        assert.deepEqual(numbers(node.description), COUNT_ORDER.map((s) => counts[s]), where);
        for (const s of COUNT_ORDER) assert.ok(node.description?.includes(`${counts[s]} ${STATUS_LOOK[s].text}`));
        mark(node);
        break;
      }
      case 'worst': {
        assert.equal(node.description, `${STATUS_LOOK[verdict.summary.worst].glyph} ${STATUS_LOOK[verdict.summary.worst].text}`);
        mark(node);
        break;
      }
      case 'coverage': {
        const { coverage } = verdict;
        const lists: [string, readonly string[]][] = [
          ['Configured', coverage.areas?.configured ?? []],
          ['Not configured', coverage.areas?.not_configured ?? []],
          ['Nothing recorded', coverage.areas?.nothing_recorded ?? []],
        ];
        const total = lists.reduce((sum, [, list]) => sum + list.length, 0);
        assert.deepEqual(numbers(node.description),
          [lists[0][1].length, total, lists[2][1].length, coverage.not_evaluated.length], where);
        const incomplete = coverage.not_evaluated.length > 0 || lists[2][1].length > 0;
        assert.equal(node.description?.includes('coverage incomplete'), incomplete);
        const [statement, ...rest] = node.children ?? [];
        assert.equal(statement.kind, 'statement');
        assert.equal(statement.label, coverage.statement);
        lists.forEach(([title, list], i) => {
          const areas = rest[i];
          assert.equal(areas.label, `${title} (${list.length})`);
          assert.deepEqual(areas.children?.map((a) => a.label) ?? [], [...list]);
          walk([areas], mark);
        });
        const notEvaluated = rest[3];
        assert.equal(rest.length, 4);
        assert.deepEqual(numbers(notEvaluated.label), [coverage.not_evaluated.length]);
        assert.deepEqual(notEvaluated.children?.map((c) => ({ path: c.label, reason: c.description })) ?? [],
          coverage.not_evaluated.map((item) => ({ ...item })));
        walk([notEvaluated], mark);
        [node, statement].forEach(mark);
        break;
      }
      default:
        break;
    }
  }
  // Every gate of the report has its row, in report order.
  assert.deepEqual(nodes.filter((n) => n.kind === 'gate').map((n) => n.label), verdict.gates.map((g) => `Gate ${g.name}`));
  return checked;
}

function checkOverview(state: ProjectState, where: string): void {
  const nodes = overviewNodes(state);
  const checked = new Set<ViewNode>();
  const top = (kind: string) => nodes.filter((n) => n.kind === kind);
  for (const node of top('cli')) {
    assert.equal(node.label, 'steward 0.20.6');
    checked.add(node);
  }
  for (const node of top('run')) checked.add(node);
  for (const node of top('no-full')) {
    assert.equal(state.full, undefined);
    checked.add(node);
  }
  if (state.full) {
    const verdict = nodes.filter((n) => n.id.startsWith('full/'));
    checkVerdict(verdict, state.full.report, false, state.full.freshness, `${where} full`).forEach((n) => checked.add(n));
  }
  for (const node of top('partial')) {
    assert.ok(state.partial);
    checkVerdict(node.children ?? [], state.partial.report, true, state.partial.freshness, `${where} partial`)
      .forEach((n) => checked.add(n));
    checked.add(node);
  }
  const total = walk(nodes, () => undefined);
  const missed: string[] = [];
  walk(nodes, (n) => { if (!checked.has(n)) missed.push(n.id); });
  assert.deepEqual(missed, [], `${where}: nodes without a parity rule`);
  assert.equal(checked.size, total);
  const ids = allIds(nodes);
  assert.equal(new Set(ids).size, ids.length, `${where}: node ids are unique`);
}

function checkResults(state: ProjectState, groupBy: GroupBy, where: string): void {
  const loaded = state.partial ?? state.full;
  assert.ok(loaded);
  const { report } = loaded;
  const { results, gates, summary } = report.verdict;
  const nodes = resultsNodes(state, groupBy);
  const groups = loaded.partial ? nodes.slice(1) : nodes;
  if (loaded.partial) assert.equal(nodes[0].kind, 'partial');

  const seen: number[] = [];
  const leaf = (node: ViewNode, groupSubject?: string) => {
    assert.equal(node.kind, 'result', `${where} ${node.id}`);
    const index = node.ref?.index;
    assert.ok(index !== undefined);
    const result = results[index];
    seen.push(index);
    assert.equal(node.label, `${result.rule} ${result.name}`);
    assert.ok(node.description?.startsWith(STATUS_LOOK[result.status].text));
    if (groupSubject === undefined) assert.ok(node.description?.includes(` · ${result.subject}`));
    else assert.equal(result.subject === '.' || result.subject === '' ? '' : result.subject, groupSubject);
    for (const gate of gates) {
      const blocks: boolean = !loaded.partial && gate.blocking.some(sameRef(result));
      assert.equal(node.description?.includes(`blocks gate ${gate.name}`), blocks, `${where} ${node.id}`);
    }
    assert.equal(node.children?.length ?? 0, result.details.length);
    assert.ok(node.tooltip?.includes(result.reason));
  };

  if (groupBy === 'status') {
    assert.deepEqual(groups.map((g) => g.label), GROUP_ORDER.map((s) => `${STATUS_LOOK[s].glyph} ${STATUS_LOOK[s].text}`));
    groups.forEach((g, i) => {
      const status = GROUP_ORDER[i] as Status;
      assert.deepEqual(numbers(g.description), [summary.counts[status]], `${where} ${status}`);
      assert.equal(g.children?.length ?? 0, summary.counts[status]);
      for (const child of g.children ?? []) {
        leaf(child);
        assert.equal(child.ref?.status, status);
      }
    });
    assert.deepEqual([...seen].sort((a, b) => a - b), results.map((_, i) => i), `${where}: every result once`);
  } else if (groupBy === 'gate') {
    const referenced = new Set<number>();
    gates.forEach((gate, i) => {
      const node = groups[i];
      assert.equal(node.label, `Gate ${gate.name}`);
      const [blocking, waived] = node.children ?? [];
      for (const [list, expected] of [[blocking, gate.blocking], [waived, gate.waived]] as const) {
        assert.deepEqual(numbers(list.description), [expected.length]);
        assert.equal(list.children?.length ?? 0, expected.length);
        list.children?.forEach((child, j) => {
          assert.ok(child.ref && sameRef(expected[j])(child.ref));
          if (child.kind === 'result') {
            leaf(child);
            referenced.add(child.ref.index as number);
          }
        });
      }
    });
    const other = groups[gates.length];
    assert.equal(groups.length, gates.length + 1);
    assert.deepEqual(numbers(other.description), [results.length - referenced.size]);
    for (const child of other.children ?? []) leaf(child);
    assert.deepEqual([...new Set(seen)].sort((a, b) => a - b), results.map((_, i) => i));
  } else {
    let sum = 0;
    for (const g of groups) {
      const subject = g.label === 'Repository level' ? '' : g.label;
      assert.deepEqual(numbers(g.description), [g.children?.length ?? 0]);
      sum += g.children?.length ?? 0;
      for (const child of g.children ?? []) leaf(child, subject);
    }
    assert.equal(sum, results.length);
    assert.deepEqual([...seen].sort((a, b) => a - b), results.map((_, i) => i));
  }
  const ids = allIds(nodes);
  assert.equal(new Set(ids).size, ids.length, `${where}: node ids are unique`);
}

function checkStatusBar(state: ProjectState, gateName: string, where: string): void {
  const view = statusBarView(state, gateName);
  const full = state.full;
  assert.ok(full);
  const { gates, summary } = full.report.verdict;
  const gate = gates.find((g) => g.name === gateName);
  assert.ok(gate);
  const badge = !gate.evaluated ? '– NOT EVALUATED' : gate.eligible ? '✓ ELIGIBLE' : '✗ NOT ELIGIBLE';
  assert.equal(view.badge, badge, where);
  const blocking = gate.evaluated && !gate.eligible && gate.blocking.length ? [gate.blocking.length] : [];
  assert.equal(view.text, [`$(shield) ${gateName} ${badge}`, ...blocking.map((n) => `${n} blocking`), full.freshness].join(' · '));
  assert.deepEqual(numbers(view.text.replace(gateName, '')), blocking, where);
  for (const g of gates) {
    const line = view.tooltip.find((l) => l.startsWith(`Gate ${g.name}: `));
    assert.ok(line, `${where}: tooltip line for gate ${g.name}`);
    assert.ok(line.endsWith(` · ${g.reason}`));
    assert.deepEqual(numbers(line.slice(0, -g.reason.length - 3).replace(g.name, '')), [g.blocking.length, g.required_count]);
  }
  const counts = view.tooltip.find((l) => l.startsWith('Counts: '));
  assert.deepEqual(numbers(counts), COUNT_ORDER.map((s) => summary.counts[s]));
  assert.ok(view.tooltip.includes(`Worst status: ${STATUS_LOOK[summary.worst].text}`));
  assert.ok(view.tooltip.includes(
    `Report: ${full.freshness} · created ${full.report.envelope.created} · steward ${full.report.envelope.tool_version}`));
  assert.ok(view.tooltip.includes(`Coverage: ${full.report.verdict.coverage.statement}`));
}

describe('view models', () => {
  it('has a corpus with full and scoped reports', () => {
    assert.ok(fullReports.length >= 6, 'full reports');
    assert.deepEqual(partialReports.map(({ name }) => name).sort(), ['geo-scoped-data', 'geo-scoped-rule']);
    for (const { name } of partialReports) {
      assert.ok(manifest.reports[name].argv.some((arg) => arg === '--rule' || arg === 'data'), name);
    }
  });

  describe('parity with the report JSON over every fixture (AC-3.1)', () => {
    for (const { name, report } of corpus) {
      it(name, () => {
        const state = withReport(ready, report);
        checkOverview(state, name);
        for (const groupBy of GROUP_BY) checkResults(state, groupBy, `${name} by ${groupBy}`);
        if (!isPartialReport(report)) {
          for (const gate of report.verdict.gates) checkStatusBar(state, gate.name, name);
        }
        // Stale and with a newer partial run, the same numbers.
        const later = partialReports.length ? withReport(state, partialReports[0].report) : state;
        checkOverview(later, `${name} then a partial run`);
        if (!isPartialReport(report)) checkStatusBar(later, 'default', `${name} then a partial run`);
      });
    }
  });

  describe('a scoped run never changes a gate badge (AC-3.2)', () => {
    const badges = (state: ProjectState) => overviewNodes(state)
      .filter((n) => n.kind === 'gate').map((n) => [n.id, n.description?.split(' · ')[0]]);

    for (const { name: fullName, report: full } of fullReports) {
      for (const { name: partialName, report: partial } of partialReports) {
        it(`${partialName} after ${fullName}`, () => {
          const before = withReport(ready, full);
          const after = withReport(before, partial);
          for (const gate of full.verdict.gates) {
            const a = statusBarView(before, gate.name);
            const b = statusBarView(after, gate.name);
            assert.equal(b.badge, a.badge);
            assert.equal(b.text, a.text.replace(/ · fresh$/, ' · stale'));
          }
          assert.deepEqual(badges(after), badges(before));
          assert.equal(after.full?.report, full);
          assert.equal(after.full?.freshness, 'stale');
          // The partial run's own gates never read as a verdict.
          const own = overviewNodes(after).find((n) => n.kind === 'partial')?.children?.filter((n) => n.kind === 'gate') ?? [];
          assert.equal(own.length, partial.verdict.gates.length);
          for (const node of own) assert.ok(node.description?.startsWith('– NOT EVALUATED BY THIS RUN'));
        });
      }
    }

    it('a run the extension started as scoped is partial even when its report looks full', () => {
      const [first, second] = fullReports.map(({ report }) => report);
      const before = withReport(ready, first);
      const after = withReport(before, second, { scope: 'check data' });
      assert.equal(after.full?.report, first);
      assert.equal(statusBarView(after, 'default').badge, statusBarView(before, 'default').badge);
      const partial = overviewNodes(after).find((n) => n.kind === 'partial');
      assert.ok(partial?.description?.startsWith('check data · fresh'));
    });

    it('a scoped run with no full report shows no badge', () => {
      for (const { report } of partialReports) {
        const view = statusBarView(withReport(ready, report), 'default');
        assert.equal(view.badge, undefined);
        assert.equal(view.text, '$(shield) default ? · no full report');
      }
    });

    it('the next full run replaces the verdict and clears the partial run', () => {
      const failing = fullReports.find(({ name }) => name === 'geo-fail-date-symbol')?.report as Report;
      const passing = fullReports.find(({ name }) => name === 'geo')?.report as Report;
      const state = withReport(withReport(withReport(ready, failing), partialReports[0].report), passing);
      assert.equal(state.partial, undefined);
      assert.equal(statusBarView(state, 'default').text, '$(shield) default ✓ ELIGIBLE · fresh');
    });
  });

  describe('status bar states (design v0.1 §5.4)', () => {
    const geo = corpus.find(({ name }) => name === 'geo')?.report as Report;
    const failing = corpus.find(({ name }) => name === 'geo-fail-date-symbol')?.report as Report;

    it('names what is missing before there is a verdict', () => {
      const cases: [ProjectState, string][] = [
        [initialState(false), '$(shield) Bio-STEWARD: Restricted Mode'],
        [initialState(true), '$(sync~spin) Bio-STEWARD: starting'],
        [{ ...initialState(true), cli: { kind: 'missing' } }, '$(shield) Bio-STEWARD: CLI not found'],
        [{ ...initialState(true), cli: { kind: 'invalid-setting' } }, '$(shield) Bio-STEWARD: CLI path invalid'],
        [{ ...initialState(true), cli: { kind: 'too-old', version: '0.19.0', minimum: '0.20.6' } },
          '$(shield) Bio-STEWARD: CLI 0.19.0 too old'],
        [{ ...initialState(true), cli: { kind: 'failed' } }, '$(shield) Bio-STEWARD: CLI not working'],
        [ready, '$(shield) default ? · no report'],
        [withRunning(ready), '$(sync~spin) default ? · no report'],
        [withRunFailure(ready, 'unreadable'), '$(shield) default ? · output unreadable'],
        [withRunFailure(ready, 'not-configured'), '$(shield) default ? · not set up'],
      ];
      for (const [state, text] of cases) assert.equal(statusBarView(state, 'default').text, text);
      // Restricted Mode wins over everything else.
      assert.equal(statusBarView({ ...withReport(ready, geo), trusted: false }, 'default').text,
        '$(shield) Bio-STEWARD: Restricted Mode');
    });

    it('shows the gate, ELIGIBLE or not, the blocking count and freshness', () => {
      assert.equal(statusBarView(withReport(ready, geo), 'default').text, '$(shield) default ✓ ELIGIBLE · fresh');
      const blocking = failing.verdict.gates[0].blocking.length;
      assert.equal(statusBarView(withReport(ready, failing), 'default').text,
        `$(shield) default ✗ NOT ELIGIBLE · ${blocking} blocking · fresh`);
      assert.equal(statusBarView(withReport(ready, failing), 'default').tone, 'error');
      assert.equal(statusBarView(withReport(ready, failing), 'default').accessibility,
        `Bio-STEWARD: gate default NOT ELIGIBLE, ${blocking} blocking, fresh`);
    });

    it('keeps the verdict, marked stale, when a run fails or is unreadable', () => {
      for (const failure of ['unreadable', 'not-configured', 'failed'] as const) {
        const state = withRunFailure(withReport(ready, failing), failure);
        assert.match(statusBarView(state, 'default').text, /✗ NOT ELIGIBLE · \d+ blocking · stale$/);
      }
      assert.match(statusBarView(withRunning(withReport(ready, geo)), 'default').text, /^\$\(sync~spin\) default ✓ ELIGIBLE/);
    });

    it('says when the chosen gate is not in the report', () => {
      const view = statusBarView(withReport(ready, geo), 'submission');
      assert.equal(view.text, '$(shield) submission ? · not in report · fresh');
      assert.equal(view.badge, undefined);
    });

    it('never lets a gate name add an icon', () => {
      assert.equal(literal('$(alert) x'), '$​(alert) x');
      assert.ok(!statusBarView(withReport(ready, geo), '$(alert)').text.includes(' $(alert)'));
    });

    it('supplies words for status glyphs and preserves punctuation in result text (AC-X.3)', () => {
      for (const status of GROUP_ORDER) {
        const { glyph, text } = STATUS_LOOK[status];
        assert.equal(treeAccessibilityLabel(`${glyph} ${text}`, '2'), `${text}, 2`);
      }
      assert.equal(treeAccessibilityLabel('Gate default', '✗ NOT ELIGIBLE · 2 blocking'),
        'Gate default, NOT ELIGIBLE, 2 blocking');
      assert.equal(treeAccessibilityLabel('Counts', '✓ 1 PASS · ? 2 UNKNOWN'), 'Counts, 1 PASS, 2 UNKNOWN');
      assert.equal(treeAccessibilityLabel('Note – an interval', '1–2; check? yes'), 'Note – an interval, 1–2; check? yes');
    });

    it('never says current (no digest on CLI 0.20.6)', () => {
      for (const { report } of corpus) {
        for (const state of [withReport(ready, report), withRunFailure(withReport(ready, report), 'failed')]) {
          assert.ok(!/current/i.test(statusBarView(state, 'default').text));
          // The extension adds its own freshness words; rule names and reasons are shown as the CLI reports them.
          walk(overviewNodes(state), (n) => {
            if (n.kind === 'report' || n.kind === 'partial' || n.kind === 'run') {
              assert.ok(!/\bcurrent\b/i.test(`${n.label} ${n.description ?? ''}`), n.id);
            }
          });
        }
      }
    });
  });

  describe('empty states', () => {
    it('names why a tree is empty, and is empty only then', () => {
      assert.equal(emptyState(initialState(false)), 'untrusted');
      assert.equal(emptyState({ ...initialState(true), cli: { kind: 'missing' } }), 'no-cli');
      assert.equal(emptyState(ready), 'no-report');
      assert.equal(emptyState(withRunning(ready)), 'running');
      assert.equal(emptyState(withRunFailure(ready, 'unreadable')), 'unreadable');
      assert.equal(overviewNodes(ready).length, 0);
      assert.equal(resultsNodes(ready, 'status').length, 0);
      const state = withReport(ready, corpus[0].report);
      assert.equal(emptyState(state), undefined);
      assert.ok(overviewNodes(state).length > 0);
      assert.equal(overviewNodes({ ...state, trusted: false }).length, 0);
    });

    it('shows that the last run was unreadable above the previous verdict', () => {
      const state = withRunFailure(withReport(ready, corpus[0].report), 'unreadable');
      const [cli, run] = overviewNodes(state);
      assert.equal(cli.kind, 'cli');
      assert.equal(run.label, 'Last run: output unreadable');
      assert.equal(run.command, 'showLog');
    });
  });

  it('marks results from a stale report', () => {
    const state = withRunFailure(withReport(ready, corpus[0].report), 'failed');
    walk(resultsNodes(state, 'status'), (n) => {
      if (n.kind === 'result') assert.ok(n.tooltip?.includes('From a stale report'));
    });
  });
});
