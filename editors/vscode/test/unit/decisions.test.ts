import { strict as assert } from 'node:assert';
import { mkdir, mkdtemp, realpath, rename, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { unlinkedFile } from '../../src/cli/paths';
import { findDecisionLogs } from '../../src/decisionsFiles';
import {
  DECISIONS_REDUCED_NOTE, decisionsNodes, decisionsSettings, DEFAULT_DECISIONS, expandLogs, firstLog, type DecisionsState,
} from '../../src/model/decisions';
import type { ViewNode } from '../../src/model/views';

// P6 Decisions, reduced form (task U05; RELEASE_vscode_0.2.0_SPEC §3): Open DECISIONS.md only. The log is the one
// steward.toml names, or the CLI 0.20.6 default; its entries are never read.

const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];

describe('Decisions (U05, reduced form)', () => {
  describe('which file is the decisions log (CLI 0.20.6: IntegritySection.decisions, session.decisions_log)', () => {
    const patterns = (toml: string) => {
      const read = decisionsSettings(toml);
      return read.kind === 'ok' ? [read.settings.source, ...read.settings.patterns] : read.reason;
    };

    it('is development/DECISIONS.md without [integrity] and without [paths] records', () => {
      assert.deepEqual(patterns(''), ['default', DEFAULT_DECISIONS]);
      assert.deepEqual(patterns('[project]\nname = "x"\n[paths]\nruns = "runs"\n'), ['default', DEFAULT_DECISIONS]);
    });

    it('is DECISIONS.md in [paths] records when there is no [integrity] table', () => {
      assert.deepEqual(patterns('[paths]\nrecords = "records/"\n'), ['paths.records', 'records/DECISIONS.md']);
      assert.deepEqual(patterns('paths.records = "docs"\n'), ['paths.records', 'docs/DECISIONS.md']);
    });

    it('is [integrity] decisions when the table exists (its default when the key does not), whatever [paths] says', () => {
      assert.deepEqual(patterns('[paths]\nrecords = "docs"\n[integrity]\nledger = "x.jsonl"\n'), ['integrity-default', DEFAULT_DECISIONS]);
      assert.deepEqual(patterns('[integrity]\ndecisions = "notes/LOG.md"\n'), ['integrity.decisions', 'notes/LOG.md']);
      assert.deepEqual(patterns('[integrity]\ndecisions = ["a/DECISIONS.md", "teams/*/DECISIONS.md"]\n'),
        ['integrity.decisions', 'a/DECISIONS.md', 'teams/*/DECISIONS.md']);
      assert.deepEqual(patterns('[integrity]\ndecisions = []\n'), ['integrity.decisions']);
    });

    it('is unreadable, never guessed, for a value of the wrong type, a path outside the project, or bad TOML', () => {
      for (const toml of ['[integrity]\ndecisions = 3\n', '[integrity]\ndecisions = ["a", 1]\n', 'integrity = 1\n',
        '[paths]\nrecords = 1\n', 'paths = "x"\n', '[integrity]\ndecisions = "../elsewhere.md"\n',
        '[integrity]\ndecisions = "/abs/DECISIONS.md"\n', '[paths]\nrecords = "../up"\n', '[integrity\n']) {
        assert.equal(decisionsSettings(toml).kind, 'unreadable', toml);
      }
    });

    it('expands a glob with the CLI\'s glob rules, keeps the order of the patterns, and drops repeats', () => {
      const files = ['b/DECISIONS.md', 'a/DECISIONS.md', 'a/deep/DECISIONS.md', 'a/other.md'];
      assert.deepEqual(expandLogs(['a/DECISIONS.md', '*/DECISIONS.md', '**/DECISIONS.md'], files), [
        { path: 'a/DECISIONS.md' },
        { path: 'b/DECISIONS.md', pattern: '*/DECISIONS.md' },
        { path: 'a/deep/DECISIONS.md', pattern: '**/DECISIONS.md' },
      ]);
    });
  });

  describe('on disk', () => {
    let scratch: string;
    beforeEach(async () => {
      scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-decisions-test-')));
    });
    afterEach(async () => rm(scratch, { recursive: true, force: true }));

    async function write(path: string, text: string): Promise<void> {
      await mkdir(dirname(join(scratch, path)), { recursive: true });
      await writeFile(join(scratch, path), text);
    }

    it('finds the default log, and says "not found" for a missing one without creating it', async () => {
      await write('steward.toml', '');
      let state = await findDecisionLogs(scratch);
      assert.equal(state.kind, 'ready');
      assert.deepEqual(state.kind === 'ready' && state.logs, [{ path: DEFAULT_DECISIONS, exists: false }]);
      assert.equal(firstLog(state), undefined);
      await write(DEFAULT_DECISIONS, '# Decisions\n');
      state = await findDecisionLogs(scratch);
      assert.deepEqual(firstLog(state), { path: DEFAULT_DECISIONS, exists: true });
    });

    it('expands globs over the project files only, never through a link or into .git, and names an unmatched glob', async () => {
      await write('steward.toml', '[integrity]\ndecisions = ["DECISIONS.md", "teams/*/DECISIONS.md", "none/*.md"]\n');
      await write('teams/a/DECISIONS.md', 'a\n');
      await write('teams/b/DECISIONS.md', 'b\n');
      await write('.git/teams/c/DECISIONS.md', 'git\n');
      const outside = await realpath(await mkdtemp(join(tmpdir(), 'steward-decisions-outside-')));
      try {
        await mkdir(join(outside, 'z'));
        await writeFile(join(outside, 'z', 'DECISIONS.md'), 'outside\n');
        await symlink(join(outside, 'z'), join(scratch, 'teams', 'z'));
        const state = await findDecisionLogs(scratch);
        assert.equal(state.kind, 'ready');
        if (state.kind !== 'ready') return;
        assert.deepEqual(state.logs, [
          { path: 'DECISIONS.md', exists: false },
          { path: 'teams/a/DECISIONS.md', pattern: 'teams/*/DECISIONS.md', exists: true },
          { path: 'teams/b/DECISIONS.md', pattern: 'teams/*/DECISIONS.md', exists: true },
        ]);
        assert.deepEqual(state.unmatched, ['none/*.md']);
        assert.equal(firstLog(state)?.path, 'teams/a/DECISIONS.md');
      } finally {
        await rm(outside, { recursive: true, force: true });
      }
    });

    it('never counts a named log that links out of the project as found', async () => {
      const outside = await realpath(await mkdtemp(join(tmpdir(), 'steward-decisions-outside-')));
      try {
        await writeFile(join(outside, 'DECISIONS.md'), 'outside\n');
        await write('steward.toml', '[integrity]\ndecisions = "LOG.md"\n');
        await symlink(join(outside, 'DECISIONS.md'), join(scratch, 'LOG.md'));
        assert.equal(firstLog(await findDecisionLogs(scratch)), undefined);
      } finally {
        await rm(outside, { recursive: true, force: true });
      }
    });

    it('as the CLI lists files (U09): never from a fixed prefix reached through a link, never from an explicit .git prefix', async () => {
      const outside = await realpath(await mkdtemp(join(tmpdir(), 'steward-decisions-outside-')));
      try {
        await write('steward.toml', '[integrity]\ndecisions = ["linked/*/DECISIONS.md", ".git/*/DECISIONS.md", "real/*/DECISIONS.md"]\n');
        await mkdir(join(outside, 'a'), { recursive: true });
        await writeFile(join(outside, 'a', 'DECISIONS.md'), 'outside\n');
        await symlink(outside, join(scratch, 'linked'));
        await write('.git/a/DECISIONS.md', 'git\n');
        await write('real/a/DECISIONS.md', 'real\n');
        const state = await findDecisionLogs(scratch);
        assert.equal(state.kind, 'ready');
        if (state.kind !== 'ready') return;
        assert.deepEqual(state.logs, [{ path: 'real/a/DECISIONS.md', pattern: 'real/*/DECISIONS.md', exists: true }]);
        assert.deepEqual(state.unmatched, ['linked/*/DECISIONS.md', '.git/*/DECISIONS.md']);
      } finally {
        await rm(outside, { recursive: true, force: true });
      }
    });

    it('names a glob unmatched only when it matches no file, even if an earlier pattern listed its files (U09)', async () => {
      await write('steward.toml', '[integrity]\ndecisions = ["teams/*/DECISIONS.md", "teams/a/*.md"]\n');
      await write('teams/a/DECISIONS.md', 'a\n');
      const state = await findDecisionLogs(scratch);
      assert.equal(state.kind === 'ready' && state.logs.length, 1);
      assert.deepEqual(state.kind === 'ready' && state.unmatched, [], 'the second glob matches the file the first one listed');
    });

    it('labels the first-existing-log policy against the CLI\'s first configured value, and checks a log again at open time (U09)', async () => {
      await write('steward.toml', '[integrity]\ndecisions = ["MISSING.md", "teams/*/DECISIONS.md"]\n');
      await write('teams/a/DECISIONS.md', 'a\n');
      const state = await findDecisionLogs(scratch);
      const nodes = decisionsNodes([{ root: scratch, name: 'p', decisions: state }]).flatMap(walk);
      const policy = nodes.find((node) => node.id.endsWith('/policy'));
      assert.equal(policy?.label, 'Open DECISIONS.md opens teams/a/DECISIONS.md');
      assert.match(policy?.tooltip ?? '', /The CLI's single-path commands use the first configured value, MISSING\.md/);
      assert.equal(await unlinkedFile(scratch, 'teams/a/DECISIONS.md'), join(scratch, 'teams', 'a', 'DECISIONS.md'));
      // The folder replaced by a link after the listing: the open-time check refuses it.
      const outside = await realpath(await mkdtemp(join(tmpdir(), 'steward-decisions-outside-')));
      try {
        await mkdir(join(outside, 'a'));
        await writeFile(join(outside, 'a', 'DECISIONS.md'), 'outside\n');
        await rename(join(scratch, 'teams'), join(scratch, 'teams-real'));
        await symlink(outside, join(scratch, 'teams'));
        assert.equal(await unlinkedFile(scratch, 'teams/a/DECISIONS.md'), undefined);
        for (const bad of ['../x', '.git/config', 'a//b', '/etc/passwd', 'a\\b']) assert.equal(await unlinkedFile(scratch, bad), undefined, bad);
      } finally {
        await rm(outside, { recursive: true, force: true });
      }
    });

    it('is unreadable without a steward.toml', async () => {
      assert.equal((await findDecisionLogs(scratch)).kind, 'unreadable');
    });
  });

  describe('the panel', () => {
    const ready = (logs: { path: string; exists: boolean; pattern?: string }[], source: 'default' | 'integrity.decisions' = 'default'): DecisionsState => ({
      kind: 'ready', settings: { source, patterns: logs.map((log) => log.pattern ?? log.path) }, logs, unmatched: [], more: 0,
    });

    it('is labelled reduced, and each log row opens that file as it is (Open DECISIONS.md only)', () => {
      const nodes = decisionsNodes([{ root: '/p', name: 'p', decisions: ready([{ path: DEFAULT_DECISIONS, exists: true }]) }]);
      assert.equal(nodes[0].label, 'Reduced form');
      assert.equal(nodes[0].description, 'Open DECISIONS.md only');
      assert.equal(nodes[0].tooltip, DECISIONS_REDUCED_NOTE);
      assert.match(DECISIONS_REDUCED_NOTE, /never writes a decision/);
      const [, log] = nodes;
      assert.equal(log.kind, 'decisions-log');
      assert.equal(log.label, DEFAULT_DECISIONS);
      assert.equal(log.description, 'the CLI\'s default development/DECISIONS.md');
      assert.equal(log.command, 'openDecisionLog');
      assert.equal(log.path, `/p/${DEFAULT_DECISIONS}`);
      assert.equal(nodes.length, 2, 'no entry of the log is listed');
    });

    it('shows a missing log as not found, with no open command', () => {
      const [, missing] = decisionsNodes([{ root: '/p', name: 'p', decisions: ready([{ path: 'LOG.md', exists: false }], 'integrity.decisions') }]);
      assert.equal(missing.kind, 'decisions-missing');
      assert.equal(missing.description, 'not found');
      assert.equal(missing.command, undefined);
      assert.match(missing.tooltip ?? '', /does not create it/);
    });

    it('says when the log is not read yet or not found', () => {
      assert.equal(decisionsNodes([{ root: '/p', name: 'p' }])[1].description, 'not read yet');
      const unreadable = decisionsNodes([{ root: '/p', name: 'p', decisions: { kind: 'unreadable', reason: 'steward.toml: bad' } }])[1];
      assert.equal(unreadable.description, 'not found');
      assert.equal(unreadable.tooltip, 'steward.toml: bad');
    });

    it('with several projects: one block each, in the order given, rows never mixed (AC-multi)', () => {
      const nodes = decisionsNodes([
        { root: '/b', name: 'b', decisions: ready([{ path: 'B.md', exists: true }], 'integrity.decisions') },
        { root: '/a', name: 'a', decisions: ready([{ path: DEFAULT_DECISIONS, exists: false }]) },
      ]);
      assert.deepEqual(nodes.slice(1).map((node) => [node.label, node.kind, node.root]), [['b', 'decisions-project', '/b'], ['a', 'decisions-project', '/a']]);
      for (const block of nodes.slice(1)) {
        for (const node of walk(block).slice(1)) {
          if (node.path) assert.ok(node.path.startsWith(`${block.root}/`), node.id);
          assert.ok(node.id.startsWith(`decisions/${block.root}/`), node.id);
        }
      }
      assert.equal(nodes[1].description, 'B.md');
      assert.equal(nodes[2].description, '0 of 1 logs found');
    });
  });
});
