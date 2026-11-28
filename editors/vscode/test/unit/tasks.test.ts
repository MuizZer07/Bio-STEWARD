import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { mkdir, mkdtemp, realpath, rm, symlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import {
  configuredStatus, DEFAULT_SPECS, globBase, globMatch, idLine, isClosed, READ_FROM_FILE, selectTaskFiles, statusLine, statusValue,
  taskSettings, tasksNodes, TASKS_SOURCE_NOTE, windowCandidates, type TaskSettings,
} from '../../src/model/tasks';
import type { ViewNode } from '../../src/model/views';
import { listTaskFiles } from '../../src/taskFiles';

// P3 Tasks (task U03, AC-P3): the task files listed by name, each Status line shown exactly as written
// and labelled "read from the file", nothing for a file without one, open first.

const fixtures = join(__dirname, '..', '..', '..', 'test', 'fixtures');
interface TaskFixture { path: string; id: string; status: string | null }
const manifest = JSON.parse(readFileSync(join(fixtures, 'manifest.json'), 'utf8')) as {
  cockpit: { task_files: { specs: string; board: string; files: TaskFixture[] } };
};
const recorded = manifest.cockpit.task_files;

// A task file in the form the U01 fixture script writes (scripts/fixtures.mjs `taskFile`).
const taskText = ({ id, status }: { id: string; status: string | null }) => [
  `# ${id}: a task`, '', `- **ID:** ${id}`, ...(status === null ? [] : [`- **Status:** ${status}`]), '- **Owner:** fixtures', '',
  '## Work', '', 'Text.', '',
].join('\n');

const FIXED_TIME = new Date('2026-01-01T00:00:00Z');
const walk = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(walk)];
const defaults: TaskSettings = { configured: false, specs: DEFAULT_SPECS, archive: [], statuses: ['proposed', 'on hold', 'GO recorded', 'in progress', 'in review', 'done'], closed: ['done'] };

describe('Tasks (U03)', () => {
  let scratch: string;

  beforeEach(async () => {
    scratch = await realpath(await mkdtemp(join(tmpdir(), 'steward-tasks-test-')));
  });
  afterEach(async () => rm(scratch, { recursive: true, force: true }));

  async function write(root: string, path: string, text: string | Buffer): Promise<void> {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), text);
    // One fixed time for every file, so the newest-first order falls back to the IDs unless a test changes it.
    await utimes(join(root, path), FIXED_TIME, FIXED_TIME);
  }

  async function cockpitLike(): Promise<string> {
    const root = join(scratch, 'geo-cockpit');
    await write(root, 'steward.toml', `[tasks]\nspecs = ["${recorded.specs}"]\nboard = "${recorded.board}"\n`);
    for (const file of recorded.files) await write(root, file.path, taskText(file));
    await write(root, recorded.board, '# Board\n\n- **Status:** not a task\n');
    return root;
  }

  describe('the Status line', () => {
    it('is the physical line, as written, for every recorded fixture value, and the CLI\'s value beside it; none without a line', () => {
      for (const file of recorded.files) {
        assert.equal(statusLine(taskText(file)), file.status === null ? undefined : `- **Status:** ${file.status}`, file.path);
        assert.equal(statusValue(taskText(file)), file.status ?? undefined, file.path);
      }
      assert.equal(statusLine('* **Status:**   in review (left: CI)   \n'), '* **Status:**   in review (left: CI)   ');
      assert.equal(statusValue('* **Status:**   in review (left: CI)   \n'), 'in review (left: CI)');
      assert.equal(statusLine('- **Status:** first\n- **Status:** second\n'), '- **Status:** first');
      assert.equal(statusLine('Status: done\n**Status:** done\n'), undefined, 'only a list item is a Status line');
      assert.equal(statusLine('- **Status:** done\r\n'), '- **Status:** done', 'without its CRLF line break');
    });

    it('takes the value as CLI 0.20.6 process.STATUS_LINE does: blank, whitespace-only, multiline and missing cases (U09)', () => {
      // A bare label: the CLI reads the value from the next line; the panel shows the label's own line.
      assert.equal(statusValue('- **Status:**\ndone\n'), 'done');
      assert.equal(statusLine('- **Status:**\ndone\n'), '- **Status:**');
      assert.equal(statusValue('- **Status:**\n\n- **Owner:** x\n'), '- **Owner:** x');
      // Whitespace only: the CLI captures one space.
      assert.equal(statusValue('- **Status:**   \n'), ' ');
      assert.equal(statusLine('- **Status:**   \n'), '- **Status:**   ');
      // A label at the very end: no value, so no Status line at all (as the CLI finds none).
      assert.equal(statusValue('- **Status:**\n'), undefined);
      assert.equal(statusLine('- **Status:**\n'), undefined);
      assert.equal(statusLine('# Task\n\n- **Owner:** x\n'), undefined);
      // The leading whitespace of the pattern can start on an earlier line.
      assert.equal(statusValue('x\n\n  - **Status:** in review\n'), 'in review');
      assert.equal(statusLine('x\n\n  - **Status:** in review\n'), '  - **Status:** in review');
      assert.equal(idLine(taskText({ id: 'GEO-001', status: null })), 'GEO-001');
      assert.equal(idLine('- **ID:** `PRJ-071`\n'), 'PRJ-071');
    });

    it('decides closed only by the configured statuses, also with a qualifier (the CLI\'s rule)', () => {
      for (const value of ['done', 'done (merged)', 'done — see the notes', 'done - late']) assert.equal(isClosed(value, defaults), true, value);
      for (const value of ['in progress', 'blocked — waiting on the annotation release', 'in review (left: CI)', 'GO recorded', 'done?', 'not done', undefined]) {
        assert.equal(isClosed(value, defaults), false, String(value));
      }
      assert.equal(configuredStatus('in review (left: CI)', defaults.statuses), 'in review');
      assert.equal(configuredStatus('blocked — x', defaults.statuses), undefined);
      assert.equal(isClosed('dropped', { statuses: ['proposed', 'dropped'], closed: ['done', 'dropped'] }), true);
      // R-57 normalises against `statuses` first, then checks `closed` (U09): a closed status that is not one of
      // `statuses` counts only as the whole value.
      const odd = { statuses: ['proposed'], closed: ['done'] };
      assert.equal(isClosed('done', odd), true);
      assert.equal(isClosed('done (merged)', odd), false);
    });
  });

  describe('steward.toml [tasks]', () => {
    it('uses the CLI defaults without a [tasks] table, and reads specs, archive, board and closed when there is one', () => {
      const none = taskSettings('[steward]\nprofile = "exploratory"\n');
      assert.equal(none.kind, 'ok');
      assert.deepEqual(none.kind === 'ok' && none.settings, defaults);
      const some = taskSettings('[tasks]\nspecs = ["work/*.md"]\narchive = ["work/old/**"]\nboard = "BOARD.md"\nclosed = ["done", "dropped"]\n');
      assert.equal(some.kind, 'ok');
      if (some.kind !== 'ok') return;
      assert.deepEqual([some.settings.specs, some.settings.archive, some.settings.board, some.settings.closed],
        [['work/*.md'], ['work/old/**'], 'BOARD.md', ['done', 'dropped']]);
    });

    it('is unreadable, never guessed, for a wrong type, a path outside the project, or broken TOML', () => {
      for (const toml of ['[tasks]\nspecs = "x/*.md"\n', '[tasks]\nspecs = ["../other/*.md"]\n', '[tasks]\nspecs = ["/abs/*.md"]\n',
        'tasks = 3\n', '[tasks\n']) {
        assert.equal(taskSettings(toml).kind, 'unreadable', toml);
      }
    });

    it('matches globs as the CLI does: **/ any folders, * and ? within one segment', () => {
      assert.ok(globMatch('development/tasks/a.md', 'development/tasks/**/*.md'));
      assert.ok(globMatch('development/tasks/x/y/a.md', 'development/tasks/**/*.md'));
      assert.ok(!globMatch('development/tasks/x/a.md', 'development/tasks/*.md'));
      assert.ok(globMatch('development/tasks/a1.md', 'development/tasks/a?.md'));
      assert.ok(!globMatch('development/tasksXa.md', 'development/tasks/*.md'));
      assert.ok(!globMatch('development/tasks/a.mdx', 'development/tasks/*.md'));
      // As Python's re without DOTALL (U09): ** stops at a line break in a name; ? is one code point; - is literal.
      assert.ok(!globMatch('notes/a\nb.md', 'notes/**.md'));
      assert.ok(!globMatch('notes/x\ny/a.md', 'notes/**/*.md'));
      assert.ok(globMatch('notes/a\nb.md', 'notes/*.md'), '* is [^/]*, which takes a line break, as in Python');
      assert.ok(globMatch('notes/😀.md', 'notes/?.md'));
      assert.ok(globMatch('a-b/c.md', 'a-b/*.md'));
      assert.ok(globMatch('[x].md', '[x].md'), '[ is literal, as the CLI translates it');
      assert.equal(globBase('development/tasks/**/*.md'), 'development/tasks');
      assert.equal(globBase('*.md'), '');
      assert.deepEqual(selectTaskFiles(['t/a.md', 't/old/b.md', 't/BOARD.md', 'u/c.md'],
        { ...defaults, specs: ['t/**/*.md'], archive: ['t/old/**'], board: 't/BOARD.md' }), ['t/a.md']);
    });
  });

  describe('the list on disk and its tree', () => {
    it('shows every task file of the fixture with its Status line unchanged, labelled, and nothing without one (AC-P3)', async () => {
      const root = await cockpitLike();
      const tasks = await listTaskFiles(root);
      assert.equal(tasks.kind, 'ready');
      const nodes = tasksNodes([{ root, name: 'geo-cockpit', tasks }]);
      assert.equal(nodes[0].label, 'Task files');
      assert.equal(nodes[0].tooltip, TASKS_SOURCE_NOTE);
      const files = nodes.flatMap(walk).filter((n) => n.kind === 'task-file');
      assert.deepEqual(files.map((n) => n.label).sort(), recorded.files.map((f) => f.path.split('/').pop()).sort(),
        'every task file, the board excluded');
      for (const file of recorded.files) {
        const node = files.find((n) => n.path === `${root}/${file.path}`);
        assert.ok(node, file.path);
        assert.equal(node.description, file.status === null ? undefined : `- **Status:** ${file.status} · ${READ_FROM_FILE}`, file.path);
        if (file.status === null) assert.doesNotMatch(node.tooltip ?? '', /Status/, 'nothing about a status it does not have');
        assert.equal(node.command, 'openTaskFile');
        assert.equal(node.root, root);
      }
      console.log(`      tasks: ${files.map((n) => `${n.label}${n.description ? ` [${n.description}]` : ''}`).join(' | ')}`);
    });

    it('lists open tasks first, and closed ones in their own group after them, each newest first (E01)', async () => {
      const root = await cockpitLike();
      const nodes = tasksNodes([{ root, name: 'geo-cockpit', tasks: await listTaskFiles(root) }]);
      const top = nodes.slice(1);
      const closed = top.findIndex((n) => n.kind === 'task-group');
      assert.equal(closed, top.length - 1, 'the closed group is last');
      assert.deepEqual(top[closed].children?.map((n) => n.label), ['GEO-002-normalise.md']);
      // Every file has the same time: the highest ID first.
      assert.deepEqual(top.slice(0, closed).map((n) => n.label), ['GEO-006-notes.md', 'GEO-005-methods.md',
        'GEO-004-figures.md', 'GEO-003-annotate.md', 'GEO-001-load-series.md']);
      assert.equal(top[closed].expanded, false);
    });

    it('puts the task changed last first, then the highest ID (E01, newest first)', async () => {
      const root = await cockpitLike();
      const at = (path: string, iso: string) => utimes(join(root, path), new Date(iso), new Date(iso));
      await at('development/tasks/GEO-003-annotate.md', '2026-11-27T10:00:00Z');
      await at('development/tasks/GEO-001-load-series.md', '2026-11-26T10:00:00Z');
      await at('development/tasks/GEO-002-normalise.md', '2026-11-25T10:00:00Z');
      const tasks = await listTaskFiles(root);
      const top = tasksNodes([{ root, name: 'geo-cockpit', tasks }]).slice(1);
      assert.deepEqual(top.filter((n) => n.kind === 'task-file').map((n) => n.label), ['GEO-003-annotate.md',
        'GEO-001-load-series.md', 'GEO-006-notes.md', 'GEO-005-methods.md', 'GEO-004-figures.md']);
      assert.equal(tasks.kind === 'ready' ? tasks.files.find((f) => f.id === 'GEO-003')?.changed : undefined, '2026-11-27T10:00:00.000Z');
      // The window picker offers the same order, open tasks first.
      assert.deepEqual(windowCandidates(tasks).map((c) => c.id), ['GEO-003', 'GEO-001', 'GEO-006', 'GEO-005', 'GEO-004', 'GEO-002']);
    });

    it('uses the default glob without [tasks], walks no links, skips .git, and names a file it cannot read', async () => {
      const root = join(scratch, 'plain');
      await write(root, 'steward.toml', '');
      await write(root, 'development/tasks/A-001.md', '- **Status:** proposed\n');
      await write(root, 'development/tasks/deep/A-002.md', '- **Status:** done\n');
      await write(root, 'development/tasks/A-003.md', Buffer.from([0x2d, 0x20, 0xff, 0xfe]));
      await write(root, 'development/notes.md', '- **Status:** not a task\n');
      await write(scratch, 'outside/X-001.md', '- **Status:** secret\n');
      await symlink(join(scratch, 'outside'), join(root, 'development', 'tasks', 'linked'));
      await symlink(join(scratch, 'outside', 'X-001.md'), join(root, 'development', 'tasks', 'X-001.md'));
      const tasks = await listTaskFiles(root);
      assert.equal(tasks.kind, 'ready');
      if (tasks.kind !== 'ready') return;
      assert.deepEqual(tasks.files.map((f) => f.path), ['development/tasks/A-001.md', 'development/tasks/A-003.md', 'development/tasks/deep/A-002.md']);
      assert.match(tasks.files[1].unreadable ?? '', /./, 'not UTF-8');
      const node = tasksNodes([{ root, name: 'plain', tasks }]).flatMap(walk).find((n) => n.label === 'A-003.md');
      assert.equal(node?.description, 'unreadable');
    });

    it('says when steward.toml cannot be read or its [tasks] is unreadable, and when there are no task files', async () => {
      const missing = await listTaskFiles(join(scratch, 'none'));
      assert.equal(missing.kind, 'unreadable');
      const root = join(scratch, 'bad');
      await write(root, 'steward.toml', '[tasks]\nspecs = ["../x/*.md"]\n');
      const bad = await listTaskFiles(root);
      assert.deepEqual(bad, { kind: 'unreadable', reason: 'steward.toml: [tasks] names a path outside the project' });
      const nodes = tasksNodes([{ root, name: 'bad', tasks: bad }]);
      assert.equal(nodes[1].description, 'not listed');
      const empty = join(scratch, 'empty');
      await write(empty, 'steward.toml', '');
      const none = tasksNodes([{ root: empty, name: 'empty', tasks: await listTaskFiles(empty) }]);
      assert.equal(none[1].label, 'No task files');
      assert.match(none[1].description ?? '', /development\/tasks\/\*\*\/\*\.md/);
    });

    it('with several projects: one block each, in the order given, rows never mixed', async () => {
      const a = await cockpitLike();
      const b = join(scratch, 'other');
      await write(b, 'steward.toml', '');
      await write(b, 'development/tasks/B-001.md', '- **Status:** done\n');
      const nodes = tasksNodes([
        { root: b, name: 'other', tasks: await listTaskFiles(b) },
        { root: a, name: 'geo-cockpit', tasks: await listTaskFiles(a) },
      ]);
      assert.deepEqual(nodes.slice(1).map((n) => [n.label, n.description]), [['other', '0 open · 1 closed'], ['geo-cockpit', '5 open · 1 closed']]);
      for (const block of nodes.slice(1)) {
        for (const node of walk(block).slice(1)) assert.ok(node.id.startsWith(`${block.id}/`), node.id);
      }
      assert.equal(tasksNodes([{ root: a, name: 'x', tasks: { kind: 'loading' } }])[1].description, 'not read yet');
    });

    it('offers each file\'s ID line for a task window, open tasks first', async () => {
      const root = await cockpitLike();
      const ids = windowCandidates(await listTaskFiles(root)).map((c) => c.id);
      assert.deepEqual(ids, ['GEO-006', 'GEO-005', 'GEO-004', 'GEO-003', 'GEO-001', 'GEO-002']);
    });
  });
});
