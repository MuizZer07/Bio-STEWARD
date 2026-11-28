// Host suite (VS Code test host, `npm run test:host`).
// T01: the extension loads, activates and registers its commands.
// T04: verdict views on the GEO example. T05: Problems and Explain on workspaces from the pinned release.
import { strict as assert } from 'node:assert';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as vscode from 'vscode';
import type { TestApi } from '../../src/extension';
import type { Report } from '../../src/model/report';
import type { ViewNode } from '../../src/model/views';
import { explainHtml } from '../../src/ui/explain';
import { previewHtml as initPreviewHtml } from '../../src/ui/init';
import { skillsPreviewHtml } from '../../src/ui/skills';

const EXTENSION_ID = 'MuizZer07.bio-steward';
const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'reports');
const example = process.env.BIO_STEWARD_TEST_EXAMPLE;
const diagnostics = (uri: vscode.Uri) => vscode.languages.getDiagnostics(uri).filter((d) => d.source === 'Bio-STEWARD');
const diagnosticCode = (d: vscode.Diagnostic) => typeof d.code === 'object' ? d.code.value : d.code;

async function until(condition: () => boolean, what: string, ms = 15000): Promise<void> {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((done) => setTimeout(done, 50));
  }
}

const find = (nodes: readonly ViewNode[], id: string) => nodes.find((n) => n.id === id);

describe('extension in the test host', () => {
  let api: TestApi | undefined;

  before(async () => {
    const ext = vscode.extensions.getExtension<TestApi | undefined>(EXTENSION_ID);
    assert.ok(ext, `${EXTENSION_ID} not found`);
    api = await ext.activate();
  });

  it('is installed and activates', () => {
    assert.equal(vscode.extensions.getExtension(EXTENSION_ID)?.isActive, true);
  });

  it('registers its commands', async () => {
    const all = await vscode.commands.getCommands(true);
    for (const command of ['bioSteward.showLog', 'bioSteward.runCheck', 'bioSteward.showOverview',
      'bioSteward.results.groupBy', 'bioSteward.redetect', 'bioSteward.explainRule',
      'bioSteward.initialize', 'bioSteward.openInitWalkthrough', 'bioSteward.applyInit']) {
      assert.ok(all.includes(command), command);
    }
  });

  describe('verdict views on the GEO example (T04)', function () {
    before(function () {
      if (example !== 'geo') this.skip();
    });

    it('finds the pinned CLI and shows "no report" before a run', async () => {
      assert.ok(api);
      await until(() => api?.project.state.cli.kind === 'ready', 'CLI detection');
      const { cli } = api.project.state;
      // The CLI the tests run on: the manifest's testedWithCli (rule G2).
      assert.equal(cli.kind === 'ready' && cli.version, vscode.extensions.getExtension(EXTENSION_ID)?.packageJSON.bioSteward.testedWithCli);
      console.log(`    Host tests use steward ${cli.kind === 'ready' ? cli.version : '?'} (${cli.kind === 'ready' ? cli.mode : ''} mode)`);
      assert.equal(api.statusBar.text, '$(shield) default ? · no report');
      assert.equal(api.overview.tree.nodes.length, 0);
    });

    it('Run Check fills the Overview, the Results tree and the status bar from the report', async function () {
      this.timeout(60000);
      assert.ok(api);
      await vscode.commands.executeCommand('bioSteward.runCheck');
      assert.equal(api.project.state.run, 'completed');
      const full = api.project.state.full;
      assert.ok(full, 'a full report');
      const { verdict } = full.report;
      // The same example and CLI as the committed fixture, so the same counts and gate.
      const fixture = JSON.parse(readFileSync(join(fixtures, 'geo.json'), 'utf8')) as Report;
      assert.deepEqual(verdict.summary.counts, fixture.verdict.summary.counts);
      assert.deepEqual(verdict.gates.map(({ name, evaluated, eligible }) => ({ name, evaluated, eligible })),
        fixture.verdict.gates.map(({ name, evaluated, eligible }) => ({ name, evaluated, eligible })));

      assert.equal(api.statusBar.text, '$(shield) default ✓ ELIGIBLE · fresh');
      const gate = find(api.overview.tree.nodes, 'full/gate:default');
      assert.ok(gate);
      const required = verdict.gates[0].required_count;
      assert.equal(gate.description, `✓ ELIGIBLE · 0 blocking of ${required} required`);
      const counts = find(api.overview.tree.nodes, 'full/counts');
      assert.equal(counts?.description, `✓ ${verdict.summary.counts.PASS} PASS · ✗ 0 FAIL · ◐ 0 INCOMPLETE · ? 0 UNKNOWN · – ${verdict.summary.counts.NOT_APPLICABLE} NOT APPLICABLE`);

      const groups = api.results.tree.nodes;
      assert.deepEqual(groups.map((g) => [g.label, g.children?.length ?? 0]), [
        ['✗ FAIL', 0], ['◐ INCOMPLETE', 0], ['? UNKNOWN', 0],
        ['✓ PASS', verdict.summary.counts.PASS], ['– NOT APPLICABLE', verdict.summary.counts.NOT_APPLICABLE],
      ]);
      // The provider hands VS Code what the model built.
      const item = api.overview.tree.getTreeItem(gate);
      assert.equal(item.id, gate.id);
      assert.equal(item.description, gate.description);
      assert.equal(item.collapsibleState, vscode.TreeItemCollapsibleState.Collapsed);
    });

    it('groups the results by gate and by file on request', async () => {
      assert.ok(api);
      await vscode.commands.executeCommand('bioSteward.results.groupBy', 'file');
      assert.equal(api.results.groupBy, 'file');
      assert.equal(api.results.tree.nodes[0].label, 'Repository level');
      await vscode.commands.executeCommand('bioSteward.results.groupBy', 'gate');
      assert.deepEqual(api.results.tree.nodes.map((n) => n.label), ['Gate default', 'Not in a gate\'s lists']);
      await vscode.commands.executeCommand('bioSteward.results.groupBy', 'status');
      assert.equal(api.results.groupBy, 'status');
    });

    it('a scoped report never changes the gate badge; the verdict is kept, marked stale', async () => {
      assert.ok(api);
      const before = api.statusBar.view?.badge;
      assert.equal(before, '✓ ELIGIBLE');
      assert.equal(await api.project.showReportFile(join(fixtures, 'geo-scoped-data.json')), true);
      assert.equal(api.statusBar.view?.badge, before);
      assert.equal(api.statusBar.text, '$(shield) default ✓ ELIGIBLE · stale');
      const partial = find(api.overview.tree.nodes, 'partial');
      assert.ok(partial?.children?.some((n) => n.kind === 'gate' && n.description?.startsWith('– NOT EVALUATED BY THIS RUN')));
      assert.equal(find(api.overview.tree.nodes, 'full/gate:default')?.description?.split(' · ')[0], '✓ ELIGIBLE');
      assert.equal(api.results.tree.nodes[0].kind, 'partial');
    });

    it('follows bioSteward.gate', async () => {
      assert.ok(api);
      const config = vscode.workspace.getConfiguration('bioSteward');
      await config.update('gate', 'submission', vscode.ConfigurationTarget.Workspace);
      try {
        await until(() => api?.statusBar.text.startsWith('$(shield) submission') ?? false, 'the gate setting');
        assert.equal(api.statusBar.text, '$(shield) submission ? · not in report · stale');
      } finally {
        await config.update('gate', undefined, vscode.ConfigurationTarget.Workspace);
      }
    });

    it('an unreadable report keeps the previous verdict, marked stale', async () => {
      assert.ok(api);
      const derived = join(__dirname, '..', '..', '..', 'test', 'fixtures', 'derived', 'invalid-json.json');
      assert.equal(await api.project.showReportFile(derived), false);
      assert.equal(api.project.state.run, 'unreadable');
      assert.equal(find(api.overview.tree.nodes, 'run')?.label, 'Last run: output unreadable');
      assert.match(api.statusBar.text, /✓ ELIGIBLE · stale$/);
    });
  });

  // T05's tests run after T04's suite: Mocha runs a suite's own tests before its nested suites, and T04's
  // first test needs a workspace where no check has run yet.
  describe('Problems and Explain (T05)', () => {
    it('keeps CLI explanations and markdown syntax as plain text (T6)', () => {
      const plain = '[check](command:other) <b>bold</b> & "quoted"\n';
      const html = explainHtml('R-85', plain);
      assert.match(html, /default-src 'none'/);
      assert.ok(html.includes('[check](command:other) &lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot;\n'));
      assert.doesNotMatch(html, /<b>|href="command:other|<script/);
    });

    // D2 (T11-08): each of the three webviews links exactly its one named command and escapes CLI and repository
    // text. The live panels' options (one enabled command, no scripts, no local resources) are asserted where each
    // panel opens: Explain below (geo), Skills Preview in skills.test.ts (toy), Init Preview in init.test.ts (init).
    it('the three webview pages link only their own command and escape hostile CLI and repository text (D2)', () => {
      const hostile = '<script>alert(1)</script> <a href="command:bioSteward.applyInit">x</a> [y](command:bioSteward.runCheck) " & \'\n' +
        'would create   <img src=x onerror=alert(2)>\n';
      const pages: [string, string, string][] = [
        ['explain', explainHtml('R-85', hostile), 'bioSteward.copyExplainCommand'],
        ['init', initPreviewHtml(hostile, undefined), 'bioSteward.applyInit'],
        ['skills', skillsPreviewHtml(hostile, undefined), 'bioSteward.applySkillsInstall'],
        ['init blocked', initPreviewHtml(hostile, '<b>blocked</b>'), ''],
        ['skills blocked', skillsPreviewHtml(hostile, '<b>blocked</b>'), ''],
      ];
      for (const [name, html, command] of pages) {
        const links = [...html.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);
        assert.deepEqual(links.map((l) => l.replace(/\?.*$/, '')), command ? [`command:${command}`] : [], `${name}: ${links.join(' ')}`);
        assert.match(html, /<meta http-equiv="Content-Security-Policy" content="default-src 'none'">/, name);
        assert.doesNotMatch(html, /<script|<img|<a href="command:bioSteward\.applyInit">x|<b>/, name);
        assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), `${name}: the text is escaped, not dropped`);
      }
    });

    if (example === 'geo' || example === 'toy') {
      it(`publishes and clears the seeded ${example} finding through Run Check (AC-4.3)`, async function () {
        this.timeout(60000);
        assert.ok(api);
        await until(() => api?.project.state.cli.kind === 'ready', 'CLI detection');
        const root = vscode.workspace.workspaceFolders![0].uri;
        const uri = vscode.Uri.joinPath(root, example === 'geo' ? 'paper/data-availability.md' : 'benchmarks/expr-clf.contract.toml');
        const original = readFileSync(uri.fsPath, 'utf8');
        const fault = example === 'geo'
          ? original.replaceAll('GSE7621', 'GSE-REMOVED')
          : original.replace(/(sha256\s*=\s*)"[^"]+"/, '$1"invalid-hash"');
        const code = example === 'geo' ? 'R-85.accession_missing' : 'R-02';
        const findDiagnostic = () => diagnostics(uri).find((d) => diagnosticCode(d) === code);
        assert.notEqual(fault, original);
        try {
          writeFileSync(uri.fsPath, fault);
          await vscode.commands.executeCommand('bioSteward.runCheck');
          await until(() => !!findDiagnostic(), code);
          const diagnostic = findDiagnostic();
          assert.ok(diagnostic);
          assert.equal(diagnostic.range.start.line, 0);
          assert.equal(diagnostic.severity, example === 'geo' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error);
          if (example === 'geo') {
            assert.ok(typeof diagnostic.code === 'object');
            assert.equal(diagnostic.code.target.scheme, 'command');
            assert.equal(diagnostic.code.target.path, 'bioSteward.explainRule');
            await vscode.commands.executeCommand(diagnostic.code.target.path, ...JSON.parse(diagnostic.code.target.query));
            const cli = vscode.workspace.getConfiguration('bioSteward', root).get<string>('cliPath');
            assert.ok(cli);
            const stdout = execFileSync(cli, ['explain', '--repo', root.fsPath, 'R-85'], { encoding: 'utf8' });
            const expected = stdout.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
              .replace('  R-85.accession_missing\n', '  <mark>R-85.accession_missing</mark>\n');
            const html = api.explain.html;
            assert.ok(html);
            assert.ok(html.includes(`<pre><span>${expected}</span></pre>`), 'the Explain view preserves CLI text (AC-4.4)');
            assert.match(html, /href="command:bioSteward\.copyExplainCommand\?/);
            // D2: the live panel enables exactly its one command, no scripts and no local resources.
            const options = api.explain.webviewOptions;
            assert.deepEqual(options?.enableCommandUris, ['bioSteward.copyExplainCommand']);
            assert.equal(options?.enableScripts, false);
            assert.deepEqual(options?.localResourceRoots, []);
          }
        } finally {
          writeFileSync(uri.fsPath, original);
          await vscode.commands.executeCommand('bioSteward.runCheck');
        }
        await until(() => !findDiagnostic(), `${code} to disappear after the fix`);
      });
    }

    if (example === 'geo') {
      it('sets ranges, tags and confined evidence, retaining the full Problems batch after partial and unreadable reports', async function () {
        this.timeout(60000);
        assert.ok(api);
        const root = vscode.workspace.workspaceFolders![0].uri;
        const file = vscode.Uri.joinPath(root, 'paper/data-availability.md');
        const scratch = vscode.Uri.joinPath(root, 'test-problems-report.json').fsPath;
        const report = JSON.parse(readFileSync(join(fixtures, 'geo-incomplete-accession.json'), 'utf8')) as Report;
        const result = report.verdict.results.find((item) => item.rule === 'R-85' && item.status === 'INCOMPLETE');
        assert.ok(result);
        const reason = '<img src="https://example.invalid/image"> [Run](command:bioSteward.runCheck) – literal';
        result.reason = reason;
        result.details[0].message = reason;
        result.details[0].line = 2;
        result.evidence = [
          { path: 'steward.toml', sha256: '0'.repeat(64) },
          { path: '../outside', sha256: '0'.repeat(64) },
        ];
        const gate = report.verdict.gates[0];
        const ref = { rule: result.rule, subject: result.subject, status: result.status };
        // CLI 0.21 and later name the authorization that waived a result (WaivedGateRef).
        gate.waived = [{ ...ref, authorization: `steward/auth/${'0'.repeat(32)}` }];
        report.verdict.gates.push({ ...gate, name: 'submission', eligible: false, blocking: [ref], waived: [] });
        const findDiagnostic = () => diagnostics(file).find((item) => diagnosticCode(item) === 'R-85.accession_missing');
        try {
          writeFileSync(scratch, JSON.stringify(report));
          assert.equal(await api.project.showReportFile(scratch), true);
          await until(() => !!findDiagnostic(), 'an anchored finding');
          const item = findDiagnostic();
          assert.ok(item);
          assert.equal(item.range.start.line, 1);
          assert.ok(item.message.startsWith(reason));
          assert.ok(typeof item.code === 'object');
          assert.equal(item.code.target.path, 'bioSteward.explainRule');
          const resultRow = api.results.tree.nodes.find((node) => node.id === 'status:INCOMPLETE')?.children
            ?.find((node) => node.ref?.rule === 'R-85');
          assert.ok(resultRow);
          const treeItem = api.results.tree.getTreeItem(resultRow);
          assert.ok(typeof treeItem.tooltip === 'string');
          assert.ok(treeItem.tooltip.includes(reason));
          const detail = resultRow.children?.[0];
          assert.ok(detail);
          const detailItem = api.results.tree.getTreeItem(detail);
          assert.equal(detailItem.label, reason);
          assert.ok(detailItem.accessibilityInformation?.label.startsWith(reason));
          assert.equal(detailItem.command?.command, 'bioSteward.row.open');
          const details = await vscode.commands.executeCommand<vscode.Uri>(detailItem.command.command, ...detailItem.command.arguments ?? []);
          assert.equal(details.scheme, 'bio-steward-details');
          const markdown = (await vscode.workspace.openTextDocument(details)).getText();
          assert.ok(markdown.includes(`    ${reason}`), 'CLI text is in a literal Markdown block');
          assert.match(markdown, /## Source\n\n {4}steward check/);
          assert.match(item.message, /waived in gate default/);
          assert.match(item.message, /blocks gate submission/);
          assert.deepEqual(item.relatedInformation?.map((info) => info.location.uri.fsPath), [join(root.fsPath, 'steward.toml')]);
          assert.equal(await api.project.showReportFile(join(fixtures, 'geo-scoped-data.json')), true);
          await until(() => !!findDiagnostic()?.message.includes('from a stale report'), 'the stale tag');
          assert.ok(!diagnostics(vscode.Uri.joinPath(root, 'results/top_genes.tsv')).some((d) => diagnosticCode(d) === 'R-83.excel_date'));
          writeFileSync(scratch, '{');
          assert.equal(await api.project.showReportFile(scratch), false);
          assert.ok(findDiagnostic()?.message.includes('from a stale report'));
        } finally {
          rmSync(scratch, { force: true });
          await vscode.commands.executeCommand('bioSteward.runCheck');
        }
        await until(() => !findDiagnostic(), 'the full diagnostic batch to be replaced');
      });
    }
  });

  // T06: freshness, the report location, resume and the countdown, on one project (after T04 and T05's suites).
  describe('freshness, report location, resume, countdown (T06)', function () {
    before(function () {
      if (example !== 'geo' && example !== 'toy') this.skip();
    });
    const root = () => vscode.workspace.workspaceFolders![0].uri.fsPath;
    const cli = () => vscode.workspace.getConfiguration('bioSteward').get<string>('cliPath') ?? '';

    it('auto writes .steward/report.json when git ignores it, else the extension storage (S10)', async function () {
      this.timeout(90000);
      assert.ok(api);
      await until(() => api?.project.state.cli.kind === 'ready', 'CLI detection');
      await vscode.commands.executeCommand('bioSteward.runCheck');
      assert.equal(api.project.lastReportLocation?.where, 'repository', api.project.lastReportLocation?.why);
      assert.equal(api.project.lastReportLocation?.path, join(realpathSync(root()), '.steward', 'report.json'));
      assert.ok(existsSync(join(root(), '.steward', 'report.json')));

      const gitignore = join(root(), '.gitignore');
      const original = readFileSync(gitignore, 'utf8');
      try {
        writeFileSync(gitignore, original.replace(/^\.steward\/$/m, '# .steward/ not ignored'));
        await vscode.commands.executeCommand('bioSteward.runCheck');
        assert.equal(api.project.lastReportLocation?.where, 'extension', api.project.lastReportLocation?.why);
        assert.equal(api.project.lastReportLocation?.why, 'auto · git: not ignored');
        assert.ok(!api.project.lastReportLocation?.path.startsWith(realpathSync(root())));
      } finally {
        writeFileSync(gitignore, original);
      }
    });

    it('confines report preparation before it can touch a symlinked parent (T09)', async () => {
      assert.ok(api);
      const outside = mkdtempSync(join(tmpdir(), 'bsv-outside-'));
      const sentinel = join(outside, 'report.json');
      const reportDir = join(root(), '.steward');
      const backup = join(outside, 'original-directory');
      const existing = existsSync(reportDir);
      const config = vscode.workspace.getConfiguration('bioSteward');
      const setting = config.inspect<string>('report.location')?.workspaceValue;
      try {
        await config.update('report.location', 'repository', vscode.ConfigurationTarget.Workspace);
        writeFileSync(sentinel, 'outside the project');
        if (existing) renameSync(reportDir, backup);
        symlinkSync(outside, reportDir);
        await vscode.commands.executeCommand('bioSteward.runCheck');
        assert.equal(api.project.lastReportLocation?.where, 'repository');
        assert.equal(api.project.state.run, 'failed');
        assert.equal(readFileSync(sentinel, 'utf8'), 'outside the project');
      } finally {
        if (existsSync(backup)) {
          rmSync(reportDir, { force: true });
          renameSync(backup, reportDir);
        } else if (!existing) {
          rmSync(reportDir, { force: true });
        }
        rmSync(outside, { recursive: true, force: true });
        await config.update('report.location', setting, vscode.ConfigurationTarget.Workspace);
      }
    });

    it('a report the extension did not just make is "unknown"', async () => {
      assert.ok(api);
      assert.equal(await api.project.showReportFile(join(fixtures, `${example}.json`)), true);
      assert.equal(api.project.state.full?.freshness, 'unknown');
      assert.match(api.statusBar.text, / · unknown$/);
    });

    it('Resume shows the handoff file\'s text unchanged, read-only (S4, AC-S4)', async () => {
      assert.ok(api);
      const handoff = join(root(), 'development', 'HANDOFF.md');
      assert.equal(existsSync(handoff), false);
      const text = '# Session handoff\n\n## Next\n1. <b>not HTML</b> [link](command:bioSteward.runCheck) `$(bug)` é\n\ttab  \n';
      try {
        writeFileSync(handoff, text);
        await vscode.commands.executeCommand('bioSteward.resume');
        const document = api.resume.document;
        assert.ok(document);
        assert.equal(document.getText(), text);
        assert.equal(document.uri.scheme, 'bio-steward-handoff');
        assert.equal(document.languageId, 'markdown');
        assert.equal(readFileSync(handoff, 'utf8'), text, 'nothing written');
      } finally {
        rmSync(handoff, { force: true });
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      }
    });

    it('the countdown equals `steward timeline --json` (S3, AC-S3)', async function () {
      this.timeout(60000);
      assert.ok(api);
      const file = join(root(), 'development', 'milestones.toml');
      assert.equal(existsSync(file), false);
      const day = 86_400_000;
      const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
      try {
        writeFileSync(file, ['schema = "steward.milestones/0.1"', '',
          '[[milestone]]', 'id = "preprint"', 'title = "Preprint"', 'kind = "preprint"', `due = ${iso(Date.now() + 9 * day)}`,
          'buffer_days = 2', '',
          '[[milestone]]', 'id = "release"', 'title = "Release"', 'kind = "release"', `due = ${iso(Date.now() + 30 * day)}`, ''].join('\n'));
        await until(() => api?.project.state.timeline?.kind === 'ready', 'the timeline after the milestones file changed', 15000);
        const stdout = execFileSync(cli(), ['timeline', '--repo', root(), '--json'], { encoding: 'utf8',
          env: { ...process.env, STEWARD_NO_REGISTRY: '1' } });
        const next = (JSON.parse(stdout) as { milestones: { id: string; days_left: number; state: string; outcome?: unknown }[] })
          .milestones.find((m) => !m.outcome);
        assert.ok(next);
        await api.project.refreshTimeline();
        const days = `${Math.abs(next.days_left).toFixed(1)} days ${next.days_left >= 0 ? 'left' : 'ago'}`;
        assert.equal(api.countdown.text, `$(watch) ${next.id} · ${days} · ${next.state.toUpperCase()}`);
        console.log(`    countdown: ${api.countdown.text}`);
      } finally {
        rmSync(file, { force: true });
      }
      await api.project.refreshTimeline();
      assert.equal(api.project.state.timeline?.kind, 'none');
      assert.equal(api.countdown.text, undefined, 'hidden without milestones');
    });
  });

  // T06 freshness (S1, AC-6.2) and D3 on-save, on the `fresh` profile: a clean copy of the GEO example that no
  // other test writes to (T12, T11-07). No sleeps: each test awaits the watcher event of the file it wrote.
  describe('freshness and check on save, on a clean workspace (S1, AC-6.2; D3)', function () {
    before(async function () {
      if (example !== 'fresh') this.skip();
      await until(() => api?.project.state.cli.kind === 'ready', 'CLI detection');
    });
    const root = () => vscode.workspace.workspaceFolders![0].uri.fsPath;
    const events = (path: string) => api!.project.recentWatchEvents.filter((e) => e.path === path).length;

    it('fresh after a run; a .steward/ change is seen and ignored; stale within 2 s of an edit, with no check run', async function () {
      this.timeout(90000);
      assert.ok(api);
      await vscode.commands.executeCommand('bioSteward.runCheck');
      assert.equal(api.project.state.run, 'completed');
      assert.equal(api.project.state.full?.freshness, 'fresh');
      assert.match(api.statusBar.text, / · fresh$/);
      const report = api.project.state.full?.report;

      // Not a project input: the test waits until the watcher has delivered this very file's event.
      const inputs = api.project.recentInputChanges.length;
      writeFileSync(join(root(), '.steward', 'scratch.txt'), 'not an input');
      await until(() => events('.steward/scratch.txt') > 0, 'the watcher event of .steward/scratch.txt');
      assert.ok(api.project.recentWatchEvents.filter((e) => e.path === '.steward/scratch.txt').every((e) => !e.input));
      assert.deepEqual(api.project.recentInputChanges.slice(inputs), [], 'no input changed');
      assert.equal(api.project.state.full?.freshness, 'fresh', 'a .steward/ change leaves the report fresh');

      const note = join(root(), 'freshness-note.txt');
      try {
        const started = Date.now();
        writeFileSync(note, 'an edit');
        // AC-6.2's 2 s threshold, on this edit only.
        await until(() => api?.project.state.full?.freshness === 'stale' &&
          api.project.recentInputChanges.includes('freshness-note.txt'), 'stale from the edited file', 2000);
        console.log(`    stale after ${Date.now() - started} ms`);
        assert.match(api.statusBar.text, / · stale$/);
        assert.equal(api.project.state.run, 'completed', 'no check ran');
        assert.equal(api.project.state.full?.report, report, 'the verdict is kept, only marked stale');
      } finally {
        const seen = events('freshness-note.txt');
        rmSync(note, { force: true });
        rmSync(join(root(), '.steward', 'scratch.txt'), { force: true });
        await until(() => events('freshness-note.txt') > seen, 'the watcher event of the removal');
      }
      // Only a new run clears "stale". It is "fresh" exactly when no input changed during it, else "unknown"
      // (a late event of the removal above can land during the run): the rule itself, not a quiet window.
      const before = api.project.recentInputChanges.length;
      await vscode.commands.executeCommand('bioSteward.runCheck');
      const during = api.project.recentInputChanges.slice(before);
      assert.equal(api.project.state.full?.freshness, during.length ? 'unknown' : 'fresh', `inputs during the run: ${during.join(', ') || 'none'}`);
      assert.notEqual(api.project.state.full?.report, report, 'a new report');
      if (during.length) console.log(`    the re-run saw ${during.join(', ')} change during it: unknown, as specified`);
    });

    it('bioSteward.check.onSave: a save runs one check 2 s later; a save under .steward/ runs none (D3)', async function () {
      this.timeout(90000);
      assert.ok(api);
      const config = vscode.workspace.getConfiguration('bioSteward');
      const save = async (path: string, text: string) => {
        writeFileSync(path, '');
        const editor = await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(path));
        await editor.edit((edit) => edit.insert(new vscode.Position(0, 0), text));
        assert.ok(await editor.document.save());
        await until(() => api!.saves.some((s) => s.path === path), `the save event of ${path}`);
        return api!.saves.filter((s) => s.path === path).at(-1)!;
      };
      const ignored = join(root(), '.steward', 'onsave.txt');
      const off = join(root(), 'onsave-off.md');
      const note = join(root(), 'onsave-note.md');
      try {
        // Off by default: a save runs nothing.
        assert.equal(config.get('check.onSave'), false);
        assert.equal((await save(off, 'off')).triggered, false);
        await config.update('check.onSave', true, vscode.ConfigurationTarget.Workspace);
        await until(() => vscode.workspace.getConfiguration('bioSteward').get('check.onSave') === true, 'the setting');

        const ignoredSave = await save(ignored, 'state');
        assert.equal(ignoredSave.triggered, false, 'a save under .steward/ never triggers a check');
        assert.equal(api.onSave.busy(api.project), false);

        const before = api.project.state.full?.report;
        const savedAt = Date.now();
        assert.equal((await save(note, 'on')).triggered, true);
        assert.equal(api.onSave.busy(api.project), true, 'a check is waiting for the debounce');
        await until(() => api?.project.state.full?.report !== before && api?.project.state.run === 'completed', 'the check after the save', 60000);
        const after = Date.now() - savedAt;
        console.log(`    check on save: report after ${after} ms`);
        assert.ok(after >= 1900, `ran ${after} ms after the save: the debounce is 2 s`);
        await until(() => !api?.onSave.busy(api.project), 'the on-save run to end');
      } finally {
        await config.update('check.onSave', undefined, vscode.ConfigurationTarget.Workspace);
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
        for (const file of [ignored, off, note]) rmSync(file, { force: true });
      }
    });
  });

  // T06, S2: two projects in one window (AC-1.4).
  describe('several projects in one window (T06, S2)', function () {
    before(function () {
      if (example !== 'multi') this.skip();
    });

    it('has two independent projects; the status bar and views follow the active editor\'s project', async function () {
      this.timeout(120000);
      assert.ok(api);
      assert.deepEqual(api.projects.map((p) => p.name), ['geo', 'toy']);
      await until(() => api?.projects.every((p) => p.state.cli.kind === 'ready') ?? false, 'CLI detection in both');
      const [geo, toy] = api.projects;
      assert.equal(api.project, geo, 'the first project is active at first');
      assert.match(api.statusBar.text, /^\$\(shield\) geo · default \? · no report$/);

      await vscode.commands.executeCommand('bioSteward.runCheck');
      assert.ok(geo.state.full, 'geo has a report');
      assert.ok(!toy.state.full, 'toy has none: runs are per project');
      const geoReport = geo.state.full.report;

      await vscode.window.showTextDocument(vscode.Uri.file(join(toy.root, 'steward.toml')));
      await until(() => api?.project === toy, 'the active editor\'s project');
      assert.match(api.statusBar.text, /^\$\(shield\) toy · default \? · no report$/);
      await vscode.commands.executeCommand('bioSteward.runCheck');
      // Read through a call: the state changes behind awaits, which TypeScript's narrowing does not see.
      const toyFull = ((p: typeof toy) => p.state.full)(toy);
      assert.ok(toyFull);
      assert.notEqual(toyFull.report.verdict.project, geoReport.verdict.project);
      assert.equal(geo.state.full?.report, geoReport, 'running toy left geo\'s report alone');
      assert.match(api.statusBar.text, /^\$\(shield\) toy · default /);
      assert.notEqual(toy.lastReportLocation?.path, geo.lastReportLocation?.path, 'each project has its own report');

      // A change in one project leaves the other fresh.
      const note = join(toy.root, 'freshness-note.txt');
      try {
        writeFileSync(note, 'edit');
        await until(() => toy.state.full?.freshness === 'stale', 'toy stale', 2000);
        assert.equal(geo.state.full.freshness, 'fresh');
      } finally {
        rmSync(note, { force: true });
      }

      await vscode.window.showTextDocument(vscode.Uri.file(join(geo.root, 'steward.toml')));
      await until(() => api?.project === geo, 'back to geo');
      assert.match(api.statusBar.text, /^\$\(shield\) geo · default ✓ ELIGIBLE · fresh$/);
      const results = api.results.tree.nodes;
      assert.equal(results.find((n) => n.label === '✓ PASS')?.children?.length, geo.state.full.report.verdict.summary.counts.PASS);

      await vscode.commands.executeCommand('bioSteward.selectProject', toy.root);
      assert.equal(api.project, toy);
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    });
  });
});
