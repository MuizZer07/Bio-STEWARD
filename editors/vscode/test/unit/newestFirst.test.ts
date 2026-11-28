// E01 (RELEASE_vscode_0.3.0_SPEC; roadmap §2 item 9): newest first in every panel's list. The order rule itself
// (dates newest first, then IDs highest first, as people read them; undated last), then one block per panel.
// Today, Tasks, Milestones and Drift and Sprint have further order checks in their own suites (today, tasks, drift,
// sprint), the Sprint one against the pinned CLI's `steward sprint status`.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { approvalsHtml, parsePendingText, type ApprovalsState } from '../../src/model/approvals';
import { decisionsNodes, type DecisionsState } from '../../src/model/decisions';
import { driftNodes, milestonesLatestFirst } from '../../src/model/drift';
import { compareIds, highestFirst, newestFirst, whenMs } from '../../src/model/order';
import { snapshotOf, sprintNodes, sprintsNewestFirst, tasksNewestFirst } from '../../src/model/sprint';
import { orderTasks, tasksNodes, type TaskFile, type TaskSettings } from '../../src/model/tasks';
import { countdownView, parseTimeline, type MilestoneRow } from '../../src/model/timeline';
import { parseAuditProgress, pendingLists, todayNodes } from '../../src/model/today';
import { markNotificationsRead, parseNotifications } from '../../src/model/notifications';
import { parseTokensReport, tokensNodes, type TokenTask } from '../../src/model/tokens';

const extensionRoot = join(__dirname, '..', '..', '..');
const fixtures = join(extensionRoot, 'test', 'fixtures');
const cockpit = (name: string) => readFileSync(join(fixtures, 'cockpit', name), 'utf8');
const recorded = join(extensionRoot, 'test', 'recorded', 'sprint');
const SID = '2026-11-27-vscode-0.1';

describe('newest first (E01)', () => {
  describe('the rule', () => {
    it('compares IDs as people read them: T10 after T9, GEO-010 after GEO-9', () => {
      assert.ok(compareIds('T10', 'T9') > 0);
      assert.ok(compareIds('GEO-010', 'GEO-9') > 0);
      assert.ok(compareIds('S1-E01', 'S1-E01b') < 0);
      assert.equal(compareIds('X02', 'X02'), 0);
      assert.deepEqual(highestFirst(['T1', 'T10', 'T9', 'T2'], (id) => id), ['T10', 'T9', 'T2', 'T1']);
    });

    it('puts the latest date first, then the highest ID, and undated entries last', () => {
      const rows = [
        { id: 'A1', when: '2026-11-01' }, { id: 'A3', when: undefined }, { id: 'A2', when: '2026-11-27T10:00:00Z' },
        { id: 'A10', when: '2026-11-01T00:00:00Z' }, { id: 'A4', when: 'not a date' },
      ];
      assert.deepEqual(newestFirst(rows, (r) => r.when, (r) => r.id).map((r) => r.id), ['A2', 'A10', 'A1', 'A4', 'A3']);
      assert.equal(whenMs('2026-11-01'), Date.parse('2026-11-01T00:00:00Z'));
      assert.equal(whenMs(''), undefined);
      assert.deepEqual(rows.map((r) => r.id), ['A1', 'A3', 'A2', 'A10', 'A4'], 'the input is not changed');
    });
  });

  describe('Now · Today', () => {
    it('lists items with IDs highest first, milestones latest due first, and signatures as the CLI gives them', () => {
      const audit = parseAuditProgress(JSON.stringify({
        schema: 'steward.progress_audit/0.1',
        pending: {
          signatures_waiting: ['spend (bbbbbbbbbbbb)', 'spend (aaaaaaaaaaaa)', 'unseal (cccccccccccc)'],
          exchange_open: ['PEER-REQ-2', 'PEER-REQ-10', 'PEER-FB-3'], own_open: ['GEO-Q-1', 'GEO-Q-12'],
          sprints: [{ sprint: '2026-11-27-s1', open: ['T2', 'T10', 'T1'] }, { sprint: '2026-11-28-s1', open: [] }],
          milestones: [{ id: 'soon', state: 'on track', days_left: 3 }, { id: 'late', state: 'late', days_left: -2 },
            { id: 'later', state: 'on track', days_left: 30 }],
        },
      }));
      assert.ok(audit);
      const lists = new Map(pendingLists(audit).map((list) => [list.key, list.items]));
      assert.deepEqual(lists.get('signatures')?.map((i) => i.label), ['spend (bbbbbbbbbbbb)', 'spend (aaaaaaaaaaaa)', 'unseal (cccccccccccc)']);
      assert.deepEqual(lists.get('exchange')?.map((i) => i.label), ['PEER-REQ-10', 'PEER-REQ-2', 'PEER-FB-3']);
      assert.deepEqual(lists.get('own')?.map((i) => i.label), ['GEO-Q-12', 'GEO-Q-1']);
      assert.deepEqual(lists.get('sprints')?.map((i) => [i.label, i.description]), [['2026-11-28-s1', ''], ['2026-11-27-s1', 'T10, T2, T1']]);
      assert.deepEqual(lists.get('milestones')?.map((i) => i.label), ['later', 'soon', 'late']);
      // The tree shows the lists in that order.
      const nodes = todayNodes([{ root: '/p', name: 'p', trusted: true, audit: { kind: 'ready', audit } }]);
      assert.deepEqual(nodes.find((n) => n.id.endsWith('/exchange'))?.children?.map((n) => n.label), ['PEER-REQ-10', 'PEER-REQ-2', 'PEER-FB-3']);
    });

    it('lists Notifications at the top of Today: unread newest first, then read dimmed newest first (E03)', () => {
      const document = parseNotifications(JSON.stringify({
        schema: 'steward.notifications/0.1',
        tool_version: '0.22.0',
        now: '2026-11-27T12:00:00Z',
        days: 14,
        notes: [],
        items: [
          { id: 'exchange:EX-2', kind: 'exchange', time: '2026-11-25T10:00:00Z', source: 'exchange/inbox/EX-2.md', title: 'older unread', command: 'steward exchange status', urgent: false },
          { id: 'exchange:EX-10', kind: 'exchange', time: '2026-11-25T10:00:00Z', source: 'exchange/inbox/EX-10.md', title: 'same time higher ID unread', command: 'steward exchange status', urgent: false },
          { id: 'approval:aaa', kind: 'approval', time: '2026-11-27T09:00:00Z', source: '.steward/pending/aaa.txt', title: 'newest read', command: 'steward authorize sign-pending', urgent: true },
          { id: 'milestone:m1:late', kind: 'milestone', time: '2026-11-26T08:00:00Z', source: 'development/milestones.toml', title: 'older read', command: 'steward next', urgent: false },
        ],
      }));
      assert.ok(document);
      const { state: readNotifications } = markNotificationsRead({}, [
        { root: '/p', item: document.items[2] },
        { root: '/p', item: document.items[3] },
      ]);
      const nodes = todayNodes([{
        root: '/p', name: 'p', trusted: true,
        notifications: { kind: 'ready', document },
        readNotifications,
      }]);
      assert.equal(nodes[1].kind, 'today-notifications', 'Notifications sits at the top of Today');
      assert.deepEqual(
        nodes[1].children?.map((n) => [n.notificationId, n.kind]),
        [
          ['exchange:EX-10', 'notification-unread'],
          ['exchange:EX-2', 'notification-unread'],
          ['approval:aaa', 'notification-read'],
          ['milestone:m1:late', 'notification-read'],
        ],
      );
    });
  });

  describe('Now · Approvals', () => {
    it('keeps the CLI\'s line order, which CLI 0.22.0 prints newest prepared first', () => {
      const state = parsePendingText(cockpit('authorize-pending/geo-cockpit-all-projects.txt'));
      assert.equal(state.kind, 'ready');
      const page = approvalsHtml({ kind: 'ready', blocks: [{ root: '/p', name: 'geo-cockpit', index: 0, approvals: state as ApprovalsState, payloads: new Map() }] });
      const shown = [...page.matchAll(/As printed: <code>([^<]*)<\/code>/g)].map((m) => m[1]);
      const printed = (state.kind === 'ready' ? state.lines : []).filter((l) => l.kind === 'payload').map((l) => l.text);
      assert.deepEqual(shown, printed);
      // The fixture queues the waiting payload, then the expired one: the later-prepared (expired) one is printed first.
      assert.match(shown[0], /06e95f82fc4a {2}expired/);
    });
  });

  describe('Work · Tasks', () => {
    const settings: TaskSettings = { configured: true, specs: ['t/*.md'], archive: [], statuses: ['in progress', 'done'], closed: ['done'] };
    const file = (id: string, changed?: string, value = 'in progress'): TaskFile => ({ path: `t/${id}.md`, id, changed, value, status: `- **Status:** ${value}` });

    it('orders open and closed tasks each by the latest change, then the highest ID', () => {
      const { open, closed } = orderTasks([file('T9', '2026-11-20T00:00:00Z'), file('T10', '2026-11-20T00:00:00Z'),
        file('T2', '2026-11-27T00:00:00Z'), file('T1'), file('T3', '2026-11-25T00:00:00Z', 'done'), file('T4', '2026-11-26T00:00:00Z', 'done')],
      settings);
      assert.deepEqual(open.map((f) => f.id), ['T2', 'T10', 'T9', 'T1']);
      assert.deepEqual(closed.map((f) => f.id), ['T4', 'T3']);
      const nodes = tasksNodes([{ root: '/p', name: 'p', tasks: { kind: 'ready', settings, files: [...open, ...closed].reverse(), more: 0 } }]);
      assert.deepEqual(nodes.filter((n) => n.kind === 'task-file').map((n) => n.label), ['T2.md', 'T10.md', 'T9.md', 'T1.md']);
    });
  });

  describe('Work · Sprint', () => {
    const plan = readFileSync(join(recorded, `${SID}.toml`), 'utf8');
    const ledger = readFileSync(join(recorded, `${SID}.jsonl`), 'utf8');

    it('lists the tasks by their latest ledger entry, then the highest ID; tasks without one last', () => {
      const s = snapshotOf(SID, plan, ledger);
      const order = tasksNewestFirst(s);
      const last = new Map<string, number>();
      for (const line of ledger.split('\n').filter(Boolean)) {
        const entry = JSON.parse(line) as { task?: string; time?: string };
        if (entry.task && entry.time) last.set(entry.task, Date.parse(entry.time));
      }
      const expected = [...s.states.keys()].sort((a, b) =>
        (last.get(b) ?? -Infinity) - (last.get(a) ?? -Infinity) || compareIds(b, a));
      assert.deepEqual(order, expected);
      assert.deepEqual(order.slice(-4), ['T12', 'T11', 'T10', 'T09'], 'no ledger entry: the highest ID first');
      const nodes = sprintNodes([s], { now: Date.parse('2026-11-26T22:30:00Z') });
      assert.deepEqual(nodes[0].children?.filter((n) => n.kind.startsWith('sprint-task')).map((n) => n.code), order);
    });

    it('puts the sprint with the latest ledger entry first', () => {
      const older = snapshotOf(SID, plan, ledger);
      const newer = snapshotOf(SID.replace('0.1', '0.2'), plan.replace(SID, SID.replace('0.1', '0.2')),
        `${ledger}${JSON.stringify({ kind: 'note', time: '2026-11-27T09:00:00Z' })}\n`);
      assert.deepEqual(sprintsNewestFirst([older, newer]).map((s) => s.id), [newer.id, older.id]);
    });
  });

  describe('Work · Tokens', () => {
    it('lists the task rows by task ID, highest first (the report gives a row no time)', () => {
      const report = parseTokensReport(cockpit('tokens-report/claude-session.json'));
      assert.ok(report);
      const task = report.tasks[0];
      const rows: TokenTask[] = ['T2', 'T10', 'T1'].map((id) => ({ ...task, task: id }));
      const nodes = tokensNodes([{ root: '/p', name: 'p', tokens: { kind: 'ready', report: { ...report, tasks: rows } },
        logs: { files: { claude: ['claude log 1'], codex: [], gemini: [] }, problems: [], capped: {} } }]);
      assert.deepEqual(nodes.filter((n) => n.kind === 'tokens-task').map((n) => n.label), ['T10', 'T2', 'T1']);
    });
  });

  describe('Direction · Milestones and Drift', () => {
    it('lists the latest due first, while the countdown still names the nearest milestone', () => {
      const parsed = parseTimeline(cockpit('timeline/geo-cockpit.json'));
      assert.ok(parsed);
      const rows: readonly MilestoneRow[] = parsed.milestones;
      assert.deepEqual(milestonesLatestFirst(rows).map((r) => r.id), ['release', 'review', 'preprint', 'abstract', 'kickoff']);
      const nodes = driftNodes([{ root: '/p', name: 'p', timeline: { kind: 'ready', rows } }]);
      assert.deepEqual(nodes.slice(1).map((n) => n.label.split(':')[0]), ['release', 'review', 'preprint', 'abstract', 'kickoff']);
      const countdown = countdownView({ kind: 'ready', rows });
      assert.ok(countdown.visible);
      assert.match(countdown.text, /abstract/, 'the nearest milestone without an outcome');
    });
  });

  describe('Direction · Decisions', () => {
    it('keeps the configured order of the logs (the first that exists is the one Open DECISIONS.md opens)', () => {
      const state: DecisionsState = {
        kind: 'ready', settings: { source: 'integrity.decisions', patterns: ['b/DECISIONS.md', 'a/DECISIONS.md'] },
        logs: [{ path: 'b/DECISIONS.md', exists: true }, { path: 'a/DECISIONS.md', exists: true }], unmatched: [], more: 0,
      };
      const nodes = decisionsNodes([{ root: '/p', name: 'p', decisions: state }]);
      assert.deepEqual(nodes.filter((n) => n.kind === 'decisions-log').map((n) => n.label), ['b/DECISIONS.md', 'a/DECISIONS.md']);
    });
  });
});
