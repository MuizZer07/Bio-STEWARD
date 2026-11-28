// Unit suite for E03 notifications (RELEASE_vscode_0.3.0_SPEC E03; design v0.9 §4):
// schema validation, local per-machine read state keyed by ID + content hash, read-once-seen,
// Mark read / Mark unread / Mark all read, unread above dimmed read newest first, urgent toasts with
// off setting, status-bar bell view, and details Markdown generation.
import { strict as assert } from 'node:assert';
import {
  bellStatusView, collectNotifications, isNotificationRead, isUrgentKind, markNotificationsRead,
  markNotificationUnread, MAX_READ_ENTRIES, notificationContentHash, notificationDetailsMarkdown,
  notificationsSectionNode, orderNotifications, parseNotifications, projectNotifications, sanitizeReadState,
  URGENT_KINDS, urgentToToast, type NotificationItem, type NotificationKind, type NotificationsDocument,
} from '../../src/model/notifications';
import { todayNodes } from '../../src/model/today';

function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 'exchange:EX-001',
    kind: 'exchange',
    time: '2026-11-27T10:00:00Z',
    source: 'exchange/inbox/EX-001.md',
    title: 'request from PEER: add feature',
    command: 'steward exchange respond EX-001 STATE --note "…"',
    urgent: false,
    ...overrides,
  };
}

function doc(items: readonly NotificationItem[], notes: readonly string[] = []): NotificationsDocument {
  return {
    schema: 'steward.notifications/0.1',
    tool_version: '0.22.0',
    now: '2026-11-27T12:00:00Z',
    days: 14,
    items,
    notes,
  };
}

describe('notifications model (E03)', () => {
  describe('schema validation', () => {
    it('accepts a valid steward.notifications/0.1 document with all eight kinds and null time', () => {
      const kinds: NotificationKind[] = [
        'upgrade', 'exchange', 'task_finished', 'task_failed', 'task_waiting', 'approval', 'gate', 'milestone',
      ];
      const raw = doc(kinds.map((kind, i) => item({
        id: `${kind}:id-${i}`,
        kind,
        time: i === 0 ? null : `2026-11-2${i}T00:00:00Z`,
        urgent: isUrgentKind(kind),
      })), ['gates: not compared']);
      const parsed = parseNotifications(JSON.stringify(raw));
      assert.deepEqual(parsed, raw);
    });

    it('rejects wrong schema, unknown kind, missing fields, or invalid JSON', () => {
      const valid = doc([item()]);
      for (const bad of [
        { ...valid, schema: 'steward.notifications/0.2' },
        { ...valid, items: [{ ...item(), kind: 'unknown_kind' }] },
        { ...valid, items: [{ ...item(), urgent: 'yes' }] },
        { ...valid, days: '14' },
        { ...valid, notes: undefined },
      ]) {
        assert.equal(parseNotifications(JSON.stringify(bad)), undefined);
      }
      assert.equal(parseNotifications('{not json'), undefined);
    });
  });

  describe('read state by ID and content hash (Read once seen)', () => {
    it('marks items read per machine/project, keeps them read on identical repeats, and marks unread when content changes', () => {
      const a = item({ id: 'approval:abc123', kind: 'approval', title: 'spend waits (expires 2099)', urgent: true });
      const b = item({ id: 'exchange:EX-002', kind: 'exchange', title: 'question from PEER' });

      let state = sanitizeReadState(undefined);
      assert.equal(isNotificationRead(state, '/proj/one', a), false);
      assert.equal(isNotificationRead(state, '/proj/one', b), false);

      // Mark read: changes state, scoped to /proj/one.
      const first = markNotificationsRead(state, [{ root: '/proj/one', item: a }]);
      assert.equal(first.changed, true);
      state = first.state;
      assert.equal(isNotificationRead(state, '/proj/one', a), true);
      assert.equal(isNotificationRead(state, '/proj/two', a), false, 'read state is scoped per project root');
      assert.equal(isNotificationRead(state, '/proj/one', b), false);

      // Repeating the exact same item is not news twice (idempotent).
      const again = markNotificationsRead(state, [{ root: '/proj/one', item: { ...a } }]);
      assert.equal(again.changed, false);
      assert.equal(isNotificationRead(state, '/proj/one', { ...a }), true);

      // When the CLI reports any change to the item, its content hash changes and it returns as unread.
      const changedVariants: NotificationItem[] = [
        { ...a, title: 'spend waits (expires 2100)' },
        { ...a, time: '2026-11-28T00:00:00Z' },
        { ...a, command: 'steward authorize sign-pending --all-projects' },
        { ...a, source: '.steward/pending/abc123-v2.txt' },
        { ...a, urgent: false },
      ];
      for (const variant of changedVariants) {
        assert.notEqual(notificationContentHash(variant), notificationContentHash(a));
        assert.equal(isNotificationRead(state, '/proj/one', variant), false, `changed item returns as unread: ${variant.title}`);
      }

      // Mark unread returns the item to unread; calling markUnread again reports no change.
      const unread = markNotificationUnread(state, '/proj/one', a.id);
      assert.equal(unread.changed, true);
      state = unread.state;
      assert.equal(isNotificationRead(state, '/proj/one', a), false);
      assert.equal(markNotificationUnread(state, '/proj/one', a.id).changed, false);
    });

    it('sanitizes malformed stored entries and caps read-state size', () => {
      const validHash = 'a'.repeat(64);
      const cleaned = sanitizeReadState({ good: validHash, bad: 'not-a-hash', num: 42 });
      assert.deepEqual(cleaned, { good: validHash });
      assert.deepEqual(sanitizeReadState(null), {});
      assert.deepEqual(sanitizeReadState([]), {});

      const big: Record<string, string> = {};
      for (let i = 0; i < MAX_READ_ENTRIES + 50; i++) big[`k${i}`] = validHash;
      const capped = sanitizeReadState(big);
      assert.equal(Object.keys(capped).length, MAX_READ_ENTRIES);
      assert.equal('k0' in capped, false, 'oldest entries evicted');
      assert.equal(`k${MAX_READ_ENTRIES + 49}` in capped, true, 'newest entries kept');
    });
  });

  describe('ordering, dimming, Today section and status-bar bell', () => {
    it('places unread newest first above read dimmed newest first, and drops unread count once read', () => {
      const oldUnread = item({ id: 'exchange:EX-2', time: '2026-11-25T10:00:00Z', title: 'older unread' });
      const newUnread = item({ id: 'exchange:EX-10', time: '2026-11-27T10:00:00Z', title: 'newer unread' });
      const undatedUnread = item({ id: 'milestone:m1:late', kind: 'milestone', time: null, title: 'undated unread' });
      const oldRead = item({ id: 'task_finished:s1/T1', kind: 'task_finished', time: '2026-11-24T10:00:00Z', title: 'older read' });
      const newRead = item({ id: 'approval:aaa', kind: 'approval', time: '2026-11-28T10:00:00Z', title: 'newer read', urgent: true });

      const document = doc([oldUnread, oldRead, undatedUnread, newRead, newUnread]);
      const { state: read } = markNotificationsRead({}, [
        { root: '/p', item: oldRead },
        { root: '/p', item: newRead },
      ]);
      const entries = orderNotifications(projectNotifications({
        root: '/p', name: 'proj', trusted: true, state: { kind: 'ready', document },
      }, read));
      assert.deepEqual(entries.map((e) => [e.item.id, e.read]), [
        ['exchange:EX-10', false],
        ['exchange:EX-2', false],
        ['milestone:m1:late', false],
        ['approval:aaa', true],
        ['task_finished:s1/T1', true],
      ]);

      // Today panel: Notifications sits right after Sources (above Resume), collapsed by default, read rows dimmed.
      const nodes = todayNodes([{
        root: '/p', name: 'proj', trusted: true,
        notifications: { kind: 'ready', document },
        readNotifications: read,
      }]);
      assert.equal(nodes[0].label, 'Sources');
      assert.equal(nodes[1].kind, 'today-notifications');
      assert.equal(nodes[1].label, 'Notifications (3 unread · 2 read)');
      assert.equal(nodes[1].expanded, false);
      const children = nodes[1].children ?? [];
      assert.deepEqual(children.map((c) => [c.notificationId, c.kind, c.dimmed]), [
        ['exchange:EX-10', 'notification-unread', false],
        ['exchange:EX-2', 'notification-unread', false],
        ['milestone:m1:late', 'notification-unread', false],
        ['approval:aaa', 'notification-read', true],
        ['task_finished:s1/T1', 'notification-read', true],
      ]);
      assert.equal(children[3].icon?.tone, 'disabled');
      assert.match(children[3].description ?? '', /^read · /);

      // Bell counts only unread items; read urgent item does not count or trigger warning tone.
      const bell = bellStatusView(entries, { trusted: true, hasProjects: true, hasReady: true });
      assert.equal(bell.visible, true);
      assert.equal(bell.unread, 3);
      assert.equal(bell.urgentUnread, 0);
      assert.equal(bell.text, '$(bell-dot) 3');
      assert.equal(bell.tone, undefined);

      // Marking all read drops unread count to 0; bell shows $(bell) with no count.
      const allRead = markNotificationsRead(read, document.items.map((it) => ({ root: '/p', item: it }))).state;
      const entriesAfter = collectNotifications([{ root: '/p', name: 'proj', trusted: true, state: { kind: 'ready', document } }], allRead);
      const bellAfter = bellStatusView(entriesAfter, { trusted: true, hasProjects: true, hasReady: true });
      assert.equal(bellAfter.unread, 0);
      assert.equal(bellAfter.text, '$(bell)');
    });

    it('hides the bell in Restricted Mode or when no CLI is ready, and explains unsupported CLIs', () => {
      assert.equal(bellStatusView([], { trusted: false, hasProjects: true, hasReady: true }).visible, false);
      assert.equal(bellStatusView([], { trusted: true, hasProjects: true, hasReady: false }).visible, false);
      const unsupported = notificationsSectionNode({
        root: '/p', name: 'proj', state: { kind: 'unsupported', minimum: '0.21.0' }, read: {},
      }, 'today/p');
      assert.equal(unsupported.description, 'needs steward 0.21.0 or newer');
    });
  });

  describe('urgent toasts and off setting', () => {
    it('toasts only for the three urgent kinds, respects the off setting, and never re-toasts read or unchanged items', () => {
      assert.deepEqual([...URGENT_KINDS].sort(), ['approval', 'gate', 'task_failed']);
      const all = [
        item({ id: 'gate:default:1', kind: 'gate', urgent: true, title: 'gate failed' }),
        item({ id: 'approval:aaa', kind: 'approval', urgent: true, title: 'approval waits' }),
        item({ id: 'task_failed:s1/T1', kind: 'task_failed', urgent: true, title: 'task failed' }),
        // Non-urgent kinds must NEVER toast even if urgent is set to true.
        item({ id: 'upgrade:U1', kind: 'upgrade', urgent: true, title: 'CLI 0.23.0 available' }),
        item({ id: 'exchange:EX-1', kind: 'exchange', urgent: false, title: 'exchange item' }),
        item({ id: 'task_finished:s1/T2', kind: 'task_finished', urgent: false, title: 'task done' }),
        item({ id: 'task_waiting:s1/T3', kind: 'task_waiting', urgent: false, title: 'task waits' }),
        item({ id: 'milestone:m1:late', kind: 'milestone', urgent: true, title: 'milestone late' }),
      ];
      const document = doc(all);
      const entries = collectNotifications([{ root: '/p', name: 'proj', trusted: true, state: { kind: 'ready', document } }], {});

      // With toasts enabled: only the three urgent kinds toast.
      const first = urgentToToast(entries, {}, true);
      assert.deepEqual(first.map((e) => e.item.kind).sort(), ['approval', 'gate', 'task_failed']);

      // With toasts turned off: zero toasts.
      assert.deepEqual(urgentToToast(entries, {}, false), []);

      // Once toasted with the same content hash: never toasts again.
      const toasted = Object.fromEntries(first.map((e) => [e.key, e.hash]));
      assert.deepEqual(urgentToToast(entries, toasted, true), []);

      // Once read: never toasts again even with an empty session toast map (e.g. after restart).
      const readState = markNotificationsRead({}, all.slice(0, 3).map((it) => ({ root: '/p', item: it }))).state;
      const readEntries = collectNotifications([{ root: '/p', name: 'proj', trusted: true, state: { kind: 'ready', document } }], readState);
      assert.deepEqual(urgentToToast(readEntries, {}, true), []);

      // If the CLI reports a change to an urgent item, its hash changes and it toasts again.
      const changedDoc = doc([item({ id: 'approval:aaa', kind: 'approval', urgent: true, title: 'approval updated' })]);
      const changedEntries = collectNotifications([{ root: '/p', name: 'proj', trusted: true, state: { kind: 'ready', document: changedDoc } }], readState);
      assert.deepEqual(urgentToToast(changedEntries, toasted, true).map((e) => e.item.id), ['approval:aaa']);
    });
  });

  describe('details page markdown', () => {
    it('shows what the item is, where it comes from, what it means, and the next command while escaping hostile text', () => {
      const hostile = item({
        id: 'upgrade:U1',
        kind: 'upgrade',
        title: 'CLI 0.23.0 <script>alert(1)</script>',
        command: 'steward exchange status',
      });
      const [entry] = projectNotifications({
        root: '/p', name: 'geo', trusted: true, state: { kind: 'ready', document: doc([hostile]) },
      }, {});
      const md = notificationDetailsMarkdown(entry);
      assert.ok(md.includes('# CLI upgrade · geo'));
      assert.ok(md.includes('## What it is'));
      assert.ok(md.includes('## Where it comes from'));
      assert.ok(md.includes('## What it means'));
      assert.ok(md.includes('## Next step'));
      assert.ok(md.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
      assert.doesNotMatch(md, /<script>/);
      assert.ok(md.includes('Bio-STEWARD: Upgrade CLI…'));
    });
  });
});
