// Host suite for E01 (RELEASE_vscode_0.3.0_SPEC): the refresh button in every panel's title bar, on the U01 cockpit
// workspace (geo-cockpit). Each refresh must run that panel's CLI commands (or re-read its files) at once, past the
// debounce timers and the sprint view's pacing, with the panel's progress shown while it runs. The commands a
// project ran are read from Project.recentRuns; the progress from the refresh records (TestApi.refreshes), which
// the extension writes around VS Code's `withProgress` in the panel.
import { strict as assert } from 'node:assert';
import { utimesSync } from 'node:fs';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import { PANELS, type PanelId } from '../../src/model/panels';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;

async function until(condition: () => boolean, what: string, ms = 30000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

describe('a refresh button on every panel (E01)', () => {
  let api: TestApi | undefined;

  before(async function () {
    if (example !== 'cockpit') this.skip();
    this.timeout(90000);
    api = await vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID)?.activate();
    assert.ok(api);
    await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready' && p.state.audit?.kind === 'ready'
      && p.state.tasks?.kind === 'ready' && p.state.decisions?.kind === 'ready' && p.state.approvals?.kind === 'ready') ?? false,
    'CLI detection and the first reads', 60000);
  });

  // Run a panel's refresh command; return the CLI commands the project queued while it ran, and its record.
  async function refresh(panel: PanelId): Promise<{ runs: string[]; ms: number }> {
    assert.ok(api);
    const project = api.projects[0];
    const since = project.recentRuns.length;
    const records = api.refreshes.length;
    const started = Date.now();
    await vscode.commands.executeCommand(PANELS[panel].refresh);
    const ms = Date.now() - started;
    const record = api.refreshes[records];
    assert.ok(record, `${panel}: a refresh record (the progress shown in the panel)`);
    assert.equal(record.panel, panel);
    assert.ok(record.ended !== undefined && record.ended >= record.started, `${panel}: the progress ended when the refresh did`);
    assert.equal(api.refreshes.length, records + 1, `${panel}: one refresh`);
    return { runs: project.recentRuns.slice(since).map((r) => r.args), ms };
  }
  const ran = (runs: string[], prefix: string) => runs.some((args) => args.startsWith(prefix));

  it('Now · Today runs steward notifications, steward audit progress and steward timeline at once', async function () {
    this.timeout(60000);
    const { runs } = await refresh('today');
    assert.ok(ran(runs, 'notifications'), runs.join(' | '));
    assert.ok(ran(runs, 'audit progress'), runs.join(' | '));
    assert.ok(ran(runs, 'timeline'), runs.join(' | '));
    assert.equal(api?.today.tree.nodes[0].label, 'Sources');
  });

  it('Now · Approvals runs steward authorize pending', async function () {
    this.timeout(60000);
    const { runs } = await refresh('approvals');
    assert.ok(runs.some((args) => args.startsWith('authorize pending') && args.includes('--all-projects')), runs.join(' | '));
    assert.equal(api?.projects[0].state.approvals?.kind, 'ready');
  });

  it('Quality · Overview runs steward check, steward timeline and steward upgrade --check', async function () {
    this.timeout(120000);
    const { runs } = await refresh('overview');
    assert.ok(ran(runs, 'check '), runs.join(' | '));
    assert.ok(ran(runs, 'timeline'), runs.join(' | '));
    assert.ok(ran(runs, 'upgrade --check'), runs.join(' | '));
    assert.ok(api?.projects[0].state.full, 'a report is shown');
  });

  it('Quality · Results runs steward check', async function () {
    this.timeout(120000);
    const { runs } = await refresh('results');
    assert.ok(ran(runs, 'check '), runs.join(' | '));
    assert.ok((api?.results.tree.nodes.length ?? 0) > 0, 'the results are shown');
  });

  it('Work · Tasks reads the task files again at once, past the 500 ms debounce of a file change', async function () {
    this.timeout(60000);
    assert.ok(api);
    const project = api.projects[0];
    const file = join(project.root, 'development', 'tasks', 'GEO-004-figures.md');
    const before = project.state.tasks;
    // Later than every file's own time (the workspace was copied just now), so this file is the latest change.
    const when = new Date(Math.floor(Date.now() / 1000) * 1000 + 3_600_000);
    utimesSync(file, when, when);
    const { ms } = await refresh('tasks');
    assert.notEqual(project.state.tasks, before, 'a new read');
    assert.ok(ms < 500, `the refresh did not wait for the debounce (${ms} ms)`);
    // Newest first: the file changed last is the first open task.
    const first = api.tasks.tree.nodes.find((n) => n.kind === 'task-file');
    assert.equal(first?.label, 'GEO-004 · GEO-004-figures.md', 'the board row of the file changed last');
    const state = project.state.tasks;
    assert.equal(state?.kind === 'ready' ? state.files.find((f) => f.id === 'GEO-004')?.changed : undefined, when.toISOString());
  });

  it('Work · Sprint reads the sprint files at once, twice in a row, past the one-read-a-second pacing', async function () {
    this.timeout(60000);
    assert.ok(api);
    const live = api.sprint.live;
    assert.ok(live);
    await refresh('sprint');
    const reads = live.reads;
    const { ms } = await refresh('sprint');
    assert.equal(live.reads, reads + 1, 'one more read');
    assert.ok(ms < 900, `no wait for the pacing (${ms} ms)`);
  });

  it('Work · Tokens runs steward tokens report', async function () {
    this.timeout(60000);
    const { runs } = await refresh('tokens');
    assert.ok(ran(runs, 'tokens report'), runs.join(' | '));
    assert.equal(api?.projects[0].state.tokens?.kind, 'ready');
  });

  it('Direction · Milestones and Drift runs steward timeline', async function () {
    this.timeout(60000);
    const { runs } = await refresh('drift');
    assert.ok(ran(runs, 'timeline'), runs.join(' | '));
    assert.equal(api?.drift.tree.nodes[0].label, 'Milestones and drift');
  });

  it('Direction · Decisions finds the decisions log again and runs steward decisions (E04)', async function () {
    this.timeout(60000);
    assert.ok(api);
    const before = api.projects[0].state.decisions;
    const { runs } = await refresh('decisions');
    assert.notEqual(api.projects[0].state.decisions, before, 'a new read');
    assert.deepEqual(runs, ['decisions --format json'], 'the full form\'s one command');
  });

  it('Agents · Agent Skills lists the skill folders again', async function () {
    this.timeout(60000);
    assert.ok(api);
    const renders = api.skills.renders;
    await refresh('skills');
    assert.ok(api.skills.renders > renders, 'the tree was drawn again');
  });

  it('covered every panel', () => {
    assert.ok(api);
    const refreshed = new Set(api.refreshes.map((r) => r.panel));
    assert.deepEqual([...refreshed].sort(), Object.keys(PANELS).sort());
  });
});
