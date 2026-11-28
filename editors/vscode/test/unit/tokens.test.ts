import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { mkdir, mkdtemp, realpath, rename, rm, symlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  isWindowId, NO_LOGS, parseTokensReport, SETTING_KEYS, tokensNodes, totals, type LogSelection, type TokensReport,
} from '../../src/model/tokens';
import type { ViewNode } from '../../src/model/views';
import { MAX_LOG_FILES, selectLogs } from '../../src/tokenLogs';
import { boundedLog } from '../../src/cli/paths';
import { commands } from '../../src/cli/commands';

// P4 Tokens (task U03): `steward tokens report --json` of CLI 0.20.6, against the U01 corpus (no source, an empty
// source, a log with records). Every number shown is the CLI's; the totals are the sum of its rows.

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
const raw = (name: string) => readFileSync(join(fixtures, 'cockpit', 'tokens-report', `${name}.json`), 'utf8');
const reportOf = (name: string): TokensReport => {
  const report = parseTokensReport(raw(name));
  assert.ok(report, name);
  return report;
};
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
const withClaude: LogSelection = { files: { claude: ['/logs/a.jsonl'], codex: [], gemini: [] }, problems: [], capped: {} };
const one = (name: string, logs: LogSelection) =>
  tokensNodes([{ root: '/w/geo-cockpit', name: 'geo-cockpit', tokens: { kind: 'ready', report: reportOf(name) }, logs }]);

describe('Tokens (U03)', () => {
  describe('steward tokens report --json', () => {
    it('reads all three U01 fixtures and refuses other documents', () => {
      for (const name of ['no-source', 'empty-source', 'claude-session']) assert.ok(parseTokensReport(raw(name)), name);
      assert.equal(parseTokensReport(readFileSync(join(fixtures, 'cockpit', 'audit-progress', 'geo.json'), 'utf8')), undefined);
      assert.equal(parseTokensReport('{"tasks": [{"task": "x"}], "sources": {}, "issues": [], "currency": null}'), undefined);
      assert.equal(parseTokensReport('not json'), undefined);
      assert.equal(parseTokensReport('{"tasks": [], "sources": {}, "issues": [], "currency": null, "x": 1}')?.tasks.length, 0);
    });
  });

  describe('the panel', () => {
    it('shows each task window and model exactly as the CLI counted them, with the total (parity, a log with records)', () => {
      const json = JSON.parse(raw('claude-session')) as { tasks: { task: string; tokens: number; status: string;
        models: { agent: string; model: string; tokens: number; input: number; output: number; cache_read: number; cache_write: number }[] }[] };
      const nodes = one('claude-session', withClaude);
      assert.equal(nodes[0].label, 'Per task');
      assert.equal(nodes.some((n) => n.kind === 'tokens-setup'), false, 'no setup hint once a log is selected');
      const rows = nodes.filter((n) => n.kind === 'tokens-task');
      assert.deepEqual(rows.map((n) => n.label), json.tasks.map((t) => t.task));
      for (const [i, task] of json.tasks.entries()) {
        assert.equal(rows[i].description, `${task.tokens.toLocaleString('en-US')} tokens · ${task.status}` +
          (task.task === 'all activity' ? ' · shared, not this project\'s alone' : ''));
        const models = rows[i].children?.filter((n) => n.kind === 'tokens-model') ?? [];
        assert.deepEqual(models.map((n) => [n.label, n.description]), task.models.map((m) => [`${m.agent} / ${m.model}`,
          `${m.tokens.toLocaleString('en-US')} tokens · input ${m.input.toLocaleString('en-US')} · output ${m.output} · ` +
          `cache read ${m.cache_read.toLocaleString('en-US')} · cache write ${m.cache_write}`]));
        for (const [j, m] of task.models.entries()) {
          assert.ok(models[j].tooltip?.includes(`input ${m.input}, output ${m.output}, cache read ${m.cache_read}, cache write ${m.cache_write}`));
        }
      }
      const total = nodes.find((n) => n.kind === 'tokens-total');
      assert.equal(total?.description, '1,170 tokens · 1 task');
      assert.deepEqual(total?.children?.map((n) => [n.label, n.description]), [['claude / claude-fixture', '1,170 tokens']]);
      const files = nodes.flatMap(walk).filter((n) => n.id.includes('/files/'));
      assert.deepEqual(files.map((n) => [n.label, n.description]), [['README.md', '1 read']]);
      const sources = nodes.find((n) => n.label === 'Sources');
      assert.equal(sources?.description, 'claude available · codex unavailable · gemini unavailable');
      console.log(`      tokens: ${nodes.slice(1).map((n) => `${n.label} [${n.description ?? ''}]`).join(' | ')}`);
    });

    it('explains how to point it at the agents\' logs when none is selected, and still shows the CLI\'s rows', () => {
      const nodes = one('no-source', NO_LOGS);
      const setup = nodes.find((n) => n.kind === 'tokens-setup');
      assert.ok(setup);
      assert.equal(setup.label, 'Agent log settings');
      assert.equal(setup.command, 'openTokenSettings');
      assert.deepEqual(setup.children?.map((n) => n.description), Object.values(SETTING_KEYS));
      assert.match(setup.tooltip ?? '', /Nothing leaves this machine/);
      const row = nodes.find((n) => n.kind === 'tokens-task');
      assert.equal(row?.label, 'all activity');
      assert.equal(row?.description, 'no counts · unavailable · shared, not this project\'s alone');
      assert.match(row?.tooltip ?? '', /Shared activity: the agent logs are this machine's/);
      assert.deepEqual(row?.children?.map((n) => n.label), ['no usable counts matched the task window']);
      assert.equal(nodes.find((n) => n.kind === 'tokens-total')?.description, '0 tokens · 1 task (1 without counts)');
    });

    it('shows a selected log the CLI could not use, with the CLI\'s own words', () => {
      const nodes = one('empty-source', withClaude);
      const claude = nodes.find((n) => n.label === 'Sources')?.children?.find((n) => n.label === 'claude');
      assert.equal(claude?.description, 'unavailable · 1 file');
      assert.deepEqual(claude?.children?.map((n) => [n.label, n.description]), [['claude log 1', 'unavailable · no supported usage records']]);
      const row = nodes.find((n) => n.kind === 'tokens-task');
      assert.deepEqual(row?.children?.map((n) => n.label), ['a selected log has missing or unreadable records',
        'no usable counts matched the task window']);
    });

    it('adds up the rows and the models for the totals, and counts the rows without counts', () => {
      const model = (agent: string, name: string | null, tokens: number) => ({ agent, model: name, tokens, input: tokens, output: 0,
        cache_read: 0, cache_write: 0, cost: null });
      const report: TokensReport = {
        currency: 'USD', issues: ['agents ledger has attempts without a supported agent or usable dates'], sources: {},
        tasks: [
          { task: 'A-1', tokens: 1500, cost: 0.25, status: 'available', issues: [], agents: [], files_read: [],
            models: [model('claude', 'm1', 1000), model('codex', null, 500)] },
          { task: 'A-2', tokens: 2000, cost: null, status: 'partial', issues: ['some usage matched multiple tasks'], agents: [], files_read: [],
            models: [model('claude', 'm1', 2000)] },
          { task: 'A-3', tokens: null, cost: null, status: 'unavailable', issues: [], agents: [], files_read: [], models: [] },
        ],
      };
      assert.deepEqual(totals(report), { tokens: 3500, rows: 3, withoutCounts: 1, partial: 1,
        models: [{ agent: 'claude', model: 'm1', tokens: 3000 }, { agent: 'codex', model: null, tokens: 500 }] });
      const nodes = tokensNodes([{ root: '/w/p', name: 'p', tokens: { kind: 'ready', report }, logs: withClaude }]);
      assert.equal(nodes.find((n) => n.kind === 'tokens-total')?.description, '3,500 tokens · 3 tasks (1 without counts, 1 partial) · estimated cost 0.25 USD (1 of 3 tasks priced)');
      assert.match(nodes.find((n) => n.label === 'A-1')?.tooltip ?? '', /estimated cost 0\.25 USD/);
      assert.ok(nodes.find((n) => n.label === 'A-1')?.children?.some((n) => n.label === 'codex / unknown model'));
      assert.ok(nodes.some((n) => n.kind === 'tokens-issue' && n.label.startsWith('agents ledger')), 'a report issue is shown');
    });

    it('says when the report is not set up, unreadable, failed or refused, and with several projects keeps one block each', () => {
      for (const [kind, text] of [['not-configured', /not set up/], ['unreadable', /no readable answer/], ['failed', /did not finish/]] as const) {
        const nodes = tokensNodes([{ root: '/w/p', name: 'p', tokens: { kind }, logs: withClaude }]);
        assert.match(nodes[1].description ?? '', text, kind);
      }
      const refused = tokensNodes([{ root: '/w/p', name: 'p', tokens: { kind: 'refused', message: 'An agent log is not …' }, logs: withClaude }]);
      assert.equal(refused[1].description, 'An agent log is not …');
      const several = tokensNodes([
        { root: '/w/b', name: 'b', tokens: { kind: 'ready', report: reportOf('claude-session') }, logs: withClaude },
        { root: '/w/a', name: 'a', tokens: { kind: 'ready', report: reportOf('no-source') }, logs: withClaude },
      ]);
      assert.deepEqual(several.slice(1).map((n) => [n.label, n.description]), [['b', '1,170 tokens'], ['a', '0 tokens']]);
      for (const block of several.slice(1)) for (const node of walk(block).slice(1)) assert.ok(node.id.startsWith(`${block.id}/`), node.id);
    });

    it('accepts only the CLI\'s task window IDs', () => {
      for (const id of ['GEO-001', 'U03', 'a.b:c/d+e-f_g']) assert.ok(isWindowId(id), id);
      for (const id of ['', '-x', 'all activity', 'a;b', 'x'.repeat(161), '--yes', undefined]) assert.ok(!isWindowId(id), String(id));
    });
  });

  describe('the agent logs of the settings', () => {
    let scratch: string;
    beforeEach(async () => {
      scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-tokens-test-')));
    });
    afterEach(async () => rm(scratch, { recursive: true, force: true }));

    it('takes files and the .jsonl / .json files of folders, newest first, and names every entry it cannot use', async () => {
      const file = join(scratch, 'one.jsonl');
      await writeFile(file, '');
      const sessions = join(scratch, 'sessions', '2026', '11', '26');
      await mkdir(sessions, { recursive: true });
      await writeFile(join(sessions, 'old.jsonl'), '');
      await writeFile(join(sessions, 'new.jsonl'), '');
      await writeFile(join(sessions, 'notes.txt'), '');
      await utimes(join(sessions, 'old.jsonl'), new Date('2026-01-01'), new Date('2026-01-01'));
      const empty = join(scratch, 'empty');
      await mkdir(empty);
      await symlink(file, join(empty, 'linked.jsonl'));
      const selected = await selectLogs({
        claude: [file, file, 'relative/log.jsonl', join(scratch, 'missing.jsonl')],
        codex: [join(scratch, 'sessions')],
        gemini: [empty, 42],
      });
      assert.deepEqual(selected.files.claude, [file], 'a repeated entry is passed once');
      assert.deepEqual(selected.files.codex, [join(sessions, 'new.jsonl'), join(sessions, 'old.jsonl')]);
      assert.deepEqual(selected.files.gemini, [], 'links inside a folder are not followed');
      assert.deepEqual(selected.problems, [
        'claude: not an absolute path: relative/log.jsonl', `claude: not found: ${join(scratch, 'missing.jsonl')}`,
        `gemini: no .jsonl or .json files in ${empty}`,
      ]);
    });

    it('keeps each file\'s selected boundary to the CLI\'s start: a walked file or folder replaced by a link is refused (U09)', async () => {
      const sessions = join(scratch, 'sessions');
      const day = join(sessions, '2026');
      await mkdir(day, { recursive: true });
      const log = join(day, 's.jsonl');
      await writeFile(log, '');
      const single = join(scratch, 'single.jsonl');
      await writeFile(single, '');
      const selected = await selectLogs({ claude: [sessions], codex: [single], gemini: undefined });
      assert.deepEqual(selected.boundaries, { [log]: sessions, [single]: single });
      const built = commands.tokensReport({ ...selected.files, boundaries: selected.boundaries });
      assert.deepEqual(built.paths.map((p) => p.boundary), [sessions, single]);
      assert.equal(await boundedLog(log, sessions), log);
      assert.equal(await boundedLog(single, single), single);
      // Another selected source's file is not inside this boundary.
      assert.equal(await boundedLog(single, sessions), undefined);
      const outside = await realpath(await mkdtemp(join(tmpdir(), 'steward-tokens-outside-')));
      try {
        await writeFile(join(outside, 's.jsonl'), '{"secret": 1}');
        // The walked file replaced by a link.
        await rm(log);
        await symlink(join(outside, 's.jsonl'), log);
        assert.equal(await boundedLog(log, sessions), undefined, 'a file replaced by a link');
        await rm(log);
        await writeFile(log, '');
        // A folder below the boundary replaced by a link to a folder holding a file of the same name.
        await rename(day, join(sessions, '2026-real'));
        await symlink(outside, day);
        assert.equal(await boundedLog(log, sessions), undefined, 'an ancestor replaced by a link');
      } finally {
        await rm(outside, { recursive: true, force: true });
      }
    });

    it(`passes at most ${MAX_LOG_FILES} files per agent, and says how many older ones it left out`, async () => {
      const folder = join(scratch, 'many');
      await mkdir(folder);
      for (let i = 0; i < MAX_LOG_FILES + 3; i++) await writeFile(join(folder, `s${String(i).padStart(3, '0')}.jsonl`), '');
      const selected = await selectLogs({ claude: [folder], codex: undefined, gemini: undefined });
      assert.equal(selected.files.claude.length, MAX_LOG_FILES);
      assert.deepEqual(selected.capped, { claude: 3 });
    });
  });
});
