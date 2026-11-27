// Host suite, T13: the live sprint view (S9) in the test host, on the `sprint` workspace of
// scripts/sprint-workspace.mjs (no CLI needed; git only builds the fixture, the view never runs it). The recorded ledger's lines are appended one step at a
// time, as `steward sprint` would write them, and the view, the status bar and the three notifications follow.
// Nothing the view does may change a file of the workspace (AC-S9).
import { strict as assert } from 'node:assert';
import { createHash } from 'node:crypto';
import { appendFileSync, lstatSync, readdirSync, readFileSync, readlinkSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import type { ViewNode } from '../../src/model/views';

const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const SID = '2026-11-27-vscode-0.1';

async function until(condition: () => boolean, what: string, ms = 15000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const walk = (nodes: readonly ViewNode[]): ViewNode[] => nodes.flatMap((n) => [n, ...walk(n.children ?? [])]);

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
      } else out[key] = `${st.size} ${st.mtimeMs} ${createHash('sha256').update(readFileSync(path)).digest('hex')}`;
    }
  };
  visit(root, '');
  return out;
}

describe('live sprint view in the test host (T13, S9)', function () {
  let api: TestApi;
  let root: string;
  let recorded: string[];
  let ledger: string;
  const node = (id: string) => walk(api.sprint.view.tree.nodes).find((n) => n.id === `sprint/${SID}/${id}`);

  before(async function () {
    if (example !== 'sprint') this.skip();
    const extension = vscode.extensions.getExtension<TestApi>('MuizZer07.bio-steward');
    assert.ok(extension);
    api = await extension.activate();
    root = realpathSync(vscode.workspace.workspaceFolders![0].uri.fsPath);
    ledger = join(root, 'development', 'sprints', `${SID}.jsonl`);
    recorded = readFileSync(join(__dirname, '..', '..', '..', 'test', 'recorded', 'sprint', `${SID}.jsonl`), 'utf8').split('\n');
    await until(() => node('task/T01') !== undefined, 'the first read of the sprint');
  });

  it('registers the sprint commands and contributes the Sprint view', async () => {
    const all = await vscode.commands.getCommands(true);
    for (const command of ['bioSteward.sprint.refresh', 'bioSteward.sprint.copyOrderCommand', 'bioSteward.sprint.show']) {
      assert.ok(all.includes(command), command);
    }
    await vscode.commands.executeCommand('bioSteward.sprint.show');
  });

  it('shows the running task from the ledger (no git), and the status bar `▶ T01 … · 0/12`', () => {
    assert.equal(api.sprint.view.tree.nodes[0]?.label, `SPRINT ${SID}`);
    assert.match(node('task/T01')?.description ?? '', /^RUNNING .+ · shell$/);
    assert.equal(node('task/T01/git'), undefined, 'no git facts: the view reads no git (D1)');
    assert.match(node('task/T01')?.tooltip ?? '', /reads no git/);
    assert.equal(node('task/T02')?.description, 'PLANNED (waits for T01)');
    assert.match(api.sprint.statusBar.text ?? '', /^▶ T01 \d.* · 0\/12$/);
    assert.deepEqual(api.sprint.notices, []);
  });

  it('follows the ledger: T01 finished, T02 waits for an order; the status bar hides', async function () {
    this.timeout(20000);
    appendFileSync(ledger, `${recorded[4]}\n${recorded[5]}\n`);
    await until(() => api.sprint.notices.length >= 2, 'the notifications');
    assert.deepEqual(api.sprint.notices.map((n) => [n.kind, n.task]), [['finished', 'T01'], ['waiting', 'T02']]);
    await until(() => node('task/T01')?.description === 'DONE', 'T01 done in the view');
    assert.deepEqual([0, 1].map((i) => node(`task/T01/check/${i}`)?.label), ['exit 0', 'exit 0']);
    assert.match(node('task/T01/commit')?.label ?? '', /^commit: [0-9a-f]{12}$/);
    assert.equal(node('task/T02')?.description, 'READY · ORDER NEEDED');
    assert.equal(node('task/T02')?.kind, 'sprint-task-waiting');
    assert.equal(api.sprint.statusBar.text, undefined);
  });

  it('copies the order command for a waiting task, and never runs it', async () => {
    const copied = await vscode.commands.executeCommand<string>('bioSteward.sprint.copyOrderCommand', node('task/T02'));
    assert.equal(copied, `steward sprint go ${SID} T02`);
    assert.equal(api.clipboard.text, copied, 'what the extension copied, not the shared system clipboard');
  });

  it('tells when the watchdog stopped a task', async function () {
    this.timeout(20000);
    appendFileSync(ledger, `${recorded[6]}\n${recorded[7]}\n`);
    await until(() => (node('task/T02')?.description ?? '').startsWith('RUNNING'), 'T02 running');
    assert.match(api.sprint.statusBar.text ?? '', /^▶ T02 \d.* · 1\/12$/);
    appendFileSync(ledger, `${JSON.stringify({ branch: `sprint/${SID}/T02`, kind: 'state', note: 'steward run exited 124', state: 'failed', task: 'T02', time: '2026-11-26T20:40:00Z' })}\n`);
    await until(() => api.sprint.notices.length >= 3, 'the watchdog notification');
    assert.deepEqual(api.sprint.notices.slice(2).map((n) => [n.kind, n.task, n.level]), [['watchdog', 'T02', 'warning']]);
    assert.equal(node('task/T02/note')?.label, 'note: steward run exited 124');
  });

  it('shows a broken ledger line as unreadable', async function () {
    this.timeout(20000);
    appendFileSync(ledger, 'not a ledger line\n');
    await until(() => node('unreadable') !== undefined, 'the unreadable line');
    assert.equal(node('unreadable')?.label, 'ledger line 10: unreadable');
    assert.match(api.sprint.view.tree.nodes[0]?.description ?? '', / · ledger incomplete$/);
  });

  it('reads at most once a second, however often the files change', async function () {
    this.timeout(20000);
    const live = api.sprint.live!;
    const start = Date.now();
    const reads = live.reads;
    for (let i = 0; i < 20; i++) {
      live.schedule();
      await new Promise((done) => setTimeout(done, 100));
    }
    await live.refresh();
    const elapsed = Date.now() - start;
    assert.ok(live.reads - reads <= Math.ceil(elapsed / 1000) + 1, `${live.reads - reads} reads in ${elapsed} ms`);
  });

  it('writes nothing: every view command and read leaves the workspace (and .git) unchanged', async function () {
    this.timeout(20000);
    await api.sprint.live!.refresh();
    const before = treeDigest(root);
    await vscode.commands.executeCommand('bioSteward.sprint.refresh');
    await vscode.commands.executeCommand('bioSteward.sprint.copyOrderCommand', node('task/T03'));
    await vscode.commands.executeCommand('bioSteward.sprint.show');
    api.sprint.live!.schedule();
    await api.sprint.live!.refresh();
    assert.deepEqual(treeDigest(root), before);
  });
});
