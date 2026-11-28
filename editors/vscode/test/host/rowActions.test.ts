import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { basename, relative } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { MAX_BRIEF_BYTES } from '../../src/model/agent';
import { APPROVAL_DETAILS_COMMAND, pageLinks } from '../../src/model/approvals';
import type { ViewNode } from '../../src/model/views';
import { DETAILS_SCHEME } from '../../src/ui/preview';
import type { NodeTree } from '../../src/ui/tree';

const profile = process.env.BIO_STEWARD_TEST_EXAMPLE;
const flatten = (nodes: readonly ViewNode[]): ViewNode[] => nodes.flatMap((node) => [node, ...flatten(node.children ?? [])]);
const hasPreview = () => vscode.window.tabGroups.all.some((group) => group.tabs.some((tab) =>
  tab.input instanceof vscode.TabInputWebview && tab.input.viewType.includes('markdown.preview')));

async function openRow(tree: NodeTree, node: ViewNode): Promise<vscode.Uri> {
  const item = tree.getTreeItem(node);
  assert.ok(item.command, node.kind);
  const uri = await vscode.commands.executeCommand<vscode.Uri>(item.command.command, ...item.command.arguments ?? []);
  assert.ok(uri, node.kind);
  return uri;
}

async function inspect(record: vscode.Uri): Promise<string> {
  assert.equal(record.scheme, DETAILS_SCHEME);
  const document = await vscode.workspace.openTextDocument(record);
  const text = document.getText();
  for (const heading of ['Item', 'Source', 'What it means', 'Next step']) assert.ok(text.includes(`## ${heading}\n`));
  assert.ok(hasPreview(), 'Markdown preview is open');
  return text;
}

describe('E02 row clicks and actions', function () {
  this.timeout(90_000);
  let api: TestApi;

  before(async function () {
    if (profile !== 'cockpit' && profile !== 'sprint') this.skip();
    const activated = await vscode.extensions.getExtension<TestApi>('MuizZer07.bio-steward')?.activate();
    assert.ok(activated);
    api = activated;
    const until = Date.now() + 60_000;
    while (api.project.state.cli.kind !== 'ready') {
      if (Date.now() > until) throw new Error('The pinned CLI is not ready');
      await new Promise((done) => setTimeout(done, 50));
    }
  });

  afterEach(async () => {
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
  });

  it('opens the available row kinds across the cockpit panels and every approval card', async function () {
    if (profile !== 'cockpit') this.skip();
    for (const panel of ['overview', 'results', 'today', 'approvals', 'tasks', 'tokens', 'decisions', 'drift']) {
      await vscode.commands.executeCommand(`bioSteward.${panel}.refresh`);
    }
    await vscode.commands.executeCommand('bioSteward.refreshSkills');
    await vscode.commands.executeCommand('bioSteward.results.groupBy', 'status');
    const trees = [api.overview.tree, api.results.tree, api.today.tree, api.tasks.tree, api.tokens.view.tree,
      api.decisions.view.tree, api.drift.tree, api.skills.tree];
    for (const tree of trees) {
      assert.ok(tree.nodes.length);
      const kinds = new Map(flatten(tree.nodes).map((node) => [node.kind === 'today-item' ? `${node.kind}/${node.code}` : node.kind, node.id]));
      for (const id of kinds.values()) {
        const node = flatten(tree.nodes).find((current) => current.id === id);
        assert.ok(node);
        // Action rows (a setting written, a window started, a terminal opened) have tests of their own.
        if (node.command === 'useTokenFolder' || node.command === 'startTokenWindow' || node.command === 'upgradeCli') continue;
        const uri = await openRow(tree, node);
        if (node.command === 'openNotification') {
          assert.ok(uri, 'a notification opens its details page');
        } else if (node.command === 'openTaskFile' || node.command === 'openDecisionLog') {
          assert.equal(uri.fsPath, node.path);
          assert.ok(hasPreview(), 'Markdown file preview is open');
        } else if (uri.scheme === 'bio-steward-handoff') {
          assert.ok(hasPreview(), 'handoff preview is open');
        } else {
          await inspect(uri);
        }
      }
    }
    const links = pageLinks(api.approvals.view.html).filter((link) => link.startsWith(`command:${APPROVAL_DETAILS_COMMAND}?`));
    assert.ok(links.length);
    for (const link of links) {
      const args = JSON.parse(decodeURIComponent(link.split('?')[1])) as number[];
      const uri = await vscode.commands.executeCommand<vscode.Uri>(APPROVAL_DETAILS_COMMAND, ...args);
      assert.match(await inspect(uri), /authorize pending/);
    }
    const milestone = api.drift.tree.nodes.find((node) => node.kind === 'drift-milestone');
    assert.ok(milestone);
    const config = await vscode.commands.executeCommand<vscode.Uri>('bioSteward.row.milestone', milestone);
    assert.equal(basename(config.fsPath), 'milestones.toml');
    assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, config.fsPath);
    const blockers = await vscode.commands.executeCommand<vscode.Uri>('bioSteward.row.blockers', milestone);
    assert.match(await inspect(blockers), /steward timeline/);
  });

  it('hands task and milestone briefs from the CLI to the clipboard', async function () {
    if (profile !== 'cockpit') this.skip();
    await vscode.commands.executeCommand('bioSteward.tasks.refresh');
    await vscode.commands.executeCommand('bioSteward.drift.refresh');
    const task = flatten(api.tasks.tree.nodes).find((node) => node.kind === 'task-file');
    assert.ok(task?.path);
    const before = Date.now();
    const text = await vscode.commands.executeCommand<string>('bioSteward.row.handToAgent', task);
    assert.ok(text);
    assert.equal(api.clipboard.text, text);
    assert.ok(Buffer.byteLength(text) <= MAX_BRIEF_BYTES);
    const command = api.project.recentRuns.find(({ args, at }) => at >= before && args.startsWith('task brief '));
    assert.ok(command?.args.includes(relative(api.project.root, task.path)));
    const cli = api.project.cliPath;
    assert.ok(cli);
    assert.equal(text, execFileSync(cli, ['task', 'brief', '--repo', api.project.root, task.path, '--for', 'codex'],
      { encoding: 'utf8', env: { ...process.env, STEWARD_NO_REGISTRY: '1' } }));
    const milestone = api.drift.tree.nodes.find((node) => node.kind === 'drift-milestone');
    assert.ok(milestone);
    const brief = await vscode.commands.executeCommand<string>('bioSteward.row.milestoneBrief', milestone);
    assert.ok(brief);
    assert.equal(api.clipboard.text, brief);
    assert.ok(Buffer.byteLength(brief) <= MAX_BRIEF_BYTES);
    assert.ok(api.project.recentRuns.some(({ args }) => args.startsWith('next ') && args.endsWith('--brief')));
  });

  it('opens sprint, task, ledger event and acceptance-check rows', async function () {
    if (profile !== 'sprint') this.skip();
    await vscode.commands.executeCommand('bioSteward.sprint.refresh');
    const tree = api.sprint.view.tree;
    const kinds = new Map(flatten(tree.nodes).map((node) => [node.kind, node.id]));
    for (const required of ['sprint', 'sprint-task', 'sprint-event', 'sprint-check'] as const) assert.ok(kinds.has(required), required);
    for (const id of kinds.values()) {
      const node = flatten(tree.nodes).find((current) => current.id === id);
      assert.ok(node);
      assert.match(await inspect(await openRow(tree, node)), /development\/sprints/);
    }
  });
});
