// Host suite for E03 notifications bell, Notifications at the top of Today, read-once-seen, Mark read / Mark unread /
// Mark all read, content-hash change detection, details page, and urgent toasts setting on `cockpit` and `multi-cockpit`.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { readdirSync, utimesSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { parseNotifications, type NotificationsDocument } from '../../src/model/notifications';
import type { ViewNode } from '../../src/model/views';
import { DIMMED_NODE_SCHEME } from '../../src/ui/tree';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const cli = () => vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';
function cliNotifications(root: string): NotificationsDocument {
  const stdout = execFileSync(cli(), ['notifications', '--repo', root, '--format', 'json'], {
    encoding: 'utf8',
    env: { ...process.env, STEWARD_NO_REGISTRY: '1' },
  });
  const parsed = parseNotifications(stdout);
  assert.ok(parsed, 'the CLI notifications JSON is readable');
  return parsed;
}

describe('Notifications bell and Read once seen (E03)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit' && example !== 'multi-cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) =>
      p.state.cli.kind === 'ready' && p.state.notifications?.kind === 'ready' && p.state.audit?.kind === 'ready') ?? false,
    'CLI detection, notifications and audit progress in every project', 60000);
  });

  describe('one project (geo-cockpit)', () => {
    before(function () {
      if (example !== 'cockpit') this.skip();
    });

    const root = () => api!.project.root;
    const notificationsNode = (): ViewNode => {
      const node = api!.today.tree.nodes.find((n) => n.kind === 'today-notifications');
      assert.ok(node, 'Notifications section present in Today');
      return node;
    };

    beforeEach(async () => {
      assert.ok(api);
      await api.notifications.readStore.clear();
      api.notifications.bell.resetToasts();
      await vscode.commands.executeCommand('bioSteward.today.refresh');
    });

    afterEach(async () => {
      api?.notifications.closeBell();
      await vscode.workspace.getConfiguration('bioSteward').update('notifications.toasts', undefined, vscode.ConfigurationTarget.Global);
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });

    it('shows Notifications at the top of Today and the unread count in the status-bar bell (parity)', () => {
      assert.ok(api);
      const expected = cliNotifications(root());
      assert.ok(expected.items.length >= 2, 'geo-cockpit has notifications (exchange, approval, milestone)');
      const nodes = api.today.tree.nodes;
      assert.equal(nodes[0].label, 'Sources');
      assert.equal(nodes[1].kind, 'today-notifications', 'Notifications sits at the top of Today');
      assert.equal(nodes[1].expanded, false, 'collapsed by default so opening marks them seen');
      assert.deepEqual(
        (nodes[1].children ?? []).map((n) => n.notificationId),
        expected.items.map((i) => i.id),
      );
      assert.equal(api.notifications.bell.view.visible, true);
      assert.equal(api.notifications.bell.view.unread, expected.items.length);
      assert.equal(api.notifications.bell.text, `$(bell-dot) ${expected.items.length}`);
    });

    it('opening the bell marks every item it showed as read, drops the count, and dims read items', async () => {
      assert.ok(api);
      const before = api.notifications.bell.view.unread;
      assert.ok(before >= 2);

      const shown = await api.notifications.openBell();
      assert.equal(shown.length, before);
      assert.equal(api.notifications.bell.view.unread, 0);
      assert.equal(api.notifications.bell.text, '$(bell)');

      await until(() => (notificationsNode().children ?? []).every((c) => c.kind === 'notification-read'),
        'Today tree updated to read');
      const section = notificationsNode();
      assert.equal(section.label, `Notifications (0 unread · ${before} read)`);
      for (const child of section.children ?? []) {
        assert.equal(child.kind, 'notification-read');
        assert.equal(child.dimmed, true);
        const treeItem = api.today.tree.getTreeItem(child);
        assert.equal(treeItem.resourceUri?.scheme, DIMMED_NODE_SCHEME);
        assert.match(child.description ?? '', /^read · /);
      }

      // Refreshing with unchanged CLI output keeps every item read (same item is not news twice).
      await vscode.commands.executeCommand('bioSteward.today.refresh');
      assert.equal(api.notifications.bell.view.unread, 0);
      assert.equal(api.notifications.bell.text, '$(bell)');
    });

    it('supports Mark unread, Mark read, opening the Notifications list in Today, and Mark all read', async () => {
      assert.ok(api);
      // Start with all read via the bell.
      await api.notifications.openBell();
      api.notifications.closeBell();
      assert.equal(api.notifications.bell.view.unread, 0);
      const children = notificationsNode().children ?? [];
      assert.ok(children.length >= 2);
      const target = children[children.length - 1];

      // Mark unread moves the item above read items and increments the bell count.
      assert.equal(await api.notifications.markUnread(target), true);
      assert.equal(api.notifications.bell.view.unread, 1);
      assert.equal(api.notifications.bell.text, '$(bell-dot) 1');
      await until(() => notificationsNode().children?.[0]?.notificationId === target.notificationId,
        'unread item placed above read items');
      assert.equal(notificationsNode().children?.[0]?.kind, 'notification-unread');
      assert.equal(notificationsNode().children?.[1]?.kind, 'notification-read');

      // Mark read on that item drops the count back to 0 and dims it.
      const unreadNode = notificationsNode().children![0];
      assert.equal(await api.notifications.markRead(unreadNode), true);
      assert.equal(api.notifications.bell.view.unread, 0);
      assert.equal(api.notifications.bell.text, '$(bell)');

      // Mark two items unread, then open the Notifications list in Today -> marks shown items read.
      assert.equal(await api.notifications.markUnread(children[0]), true);
      assert.equal(await api.notifications.markUnread(children[1]), true);
      assert.equal(api.notifications.bell.view.unread, 2);
      assert.equal(await api.today.openNotificationsList(root()), true);
      assert.equal(api.notifications.bell.view.unread, 0);
      assert.equal(api.notifications.bell.text, '$(bell)');

      // Mark two items unread, then Mark all read -> drops count to 0.
      assert.equal(await api.notifications.markUnread(children[0]), true);
      assert.equal(await api.notifications.markUnread(children[1]), true);
      assert.equal(api.notifications.bell.view.unread, 2);
      assert.equal(await api.notifications.markAllRead(), true);
      assert.equal(api.notifications.bell.view.unread, 0);
    });

    it('marks an item unread again when the CLI reports a change (new content hash), while unchanged items stay read', async function () {
      this.timeout(60000);
      assert.ok(api);
      await api.notifications.openBell();
      api.notifications.closeBell();
      assert.equal(api.notifications.bell.view.unread, 0);

      // Touch the waiting pending payload file so `steward notifications` reports a changed timestamp (new content hash).
      const pendingDir = join(root(), '.steward', 'pending');
      const waitingFile = readdirSync(pendingDir).find((name) => name.startsWith('d3e83e998137'));
      assert.ok(waitingFile, 'waiting payload exists');
      const fullPath = join(pendingDir, waitingFile);
      const later = new Date(Date.now() + 120_000);
      utimesSync(fullPath, later, later);

      await vscode.commands.executeCommand('bioSteward.today.refresh');
      assert.equal(api.notifications.bell.view.unread, 1, 'only the changed approval came back as unread');
      const first = notificationsNode().children?.[0];
      assert.equal(first?.kind, 'notification-unread');
      assert.match(first?.notificationId ?? '', /^approval:d3e83e998137/);
      const rest = (notificationsNode().children ?? []).slice(1);
      assert.ok(rest.length >= 1 && rest.every((n) => n.kind === 'notification-read'), 'unchanged items stay read');
    });

    it('opens a read-only Markdown details page when clicking a notification', async () => {
      assert.ok(api);
      const first = notificationsNode().children?.[0];
      assert.ok(first);
      const document = await api.notifications.openDetails(first);
      assert.ok(document);
      assert.equal(document.uri.scheme, 'bio-steward-notification');
      assert.equal(document.languageId, 'markdown');
      const text = document.getText();
      assert.ok(text.includes('## What it is'));
      assert.ok(text.includes('## Where it comes from'));
      assert.ok(text.includes('## Next step'));
      assert.ok(text.includes('steward notifications --format json'));
    });

    it('toasts only for the three urgent kinds, respects the off setting, and never toasts read items again', async () => {
      assert.ok(api);
      // In geo-cockpit: approval is urgent; exchange and milestone are not urgent.
      const toasts = api.notifications.bell.shownToasts;
      assert.ok(toasts.length >= 1, 'at least one urgent notification toasted');
      assert.ok(toasts.every((t) => t.kind === 'approval' || t.kind === 'gate' || t.kind === 'task_failed'),
        `only urgent kinds toasted: ${toasts.map((t) => t.kind).join(', ')}`);

      // Mark all read, reset session toast memory, and refresh: read items never toast again.
      await api.notifications.markAllRead();
      api.notifications.bell.resetToasts();
      await vscode.commands.executeCommand('bioSteward.today.refresh');
      assert.equal(api.notifications.bell.shownToasts.length, 0, 'read items never toast again');

      // Turn toasts off, clear read state, refresh: zero toasts even though urgent items are unread.
      await vscode.workspace.getConfiguration('bioSteward').update('notifications.toasts', false, vscode.ConfigurationTarget.Global);
      await api.notifications.readStore.clear();
      api.notifications.bell.resetToasts();
      await vscode.commands.executeCommand('bioSteward.today.refresh');
      assert.ok(api.notifications.bell.view.unread >= 1, 'items are unread');
      assert.equal(api.notifications.bell.shownToasts.length, 0, 'toasts setting turned them off');
    });
  });

  describe('three projects in one window (multi-cockpit)', () => {
    before(function () {
      if (example !== 'multi-cockpit') this.skip();
    });

    it('aggregates unread count across projects in the bell and keeps each project\'s Notifications at the top of its block', async () => {
      assert.ok(api);
      await api.notifications.readStore.clear();
      await vscode.commands.executeCommand('bioSteward.today.refresh');
      const totalExpected = api.projects.reduce((sum, project) => sum + cliNotifications(project.root).items.length, 0);
      assert.equal(api.notifications.bell.view.unread, totalExpected);
      for (const block of api.today.tree.nodes.slice(1)) {
        assert.equal(block.children?.[0]?.kind, 'today-notifications', `${block.label} has Notifications at top`);
      }
      await api.notifications.markAllRead();
      assert.equal(api.notifications.bell.view.unread, 0);
    });
  });
});
