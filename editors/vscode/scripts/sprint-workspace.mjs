// `node scripts/sprint-workspace.mjs DIR`: the host-test workspace of the live sprint view (T13). Needs git, not the
// CLI: a git repository with a stand-in steward.toml (for activation only), the recorded sprint file and the first
// four lines of its recorded ledger (test/recorded/sprint/: T01 running), and T01's worktree on its own branch
// with two commits, laid out as `steward sprint start` lays it out (`.steward/sprints/<id>/<task>`). The host test
// then appends the recorded ledger's next lines and checks the view, the status bar and the notifications.
//
// Git runs with no global or system configuration, so the user's hooks, signing or templates never apply.
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const SPRINT_ID = '2026-11-27-vscode-0.1';
const here = dirname(fileURLToPath(import.meta.url));
const recorded = resolve(here, '..', 'test', 'recorded', 'sprint');

export function buildSprintWorkspace(dir) {
  mkdirSync(dir, { recursive: true });
  const root = realpathSync(dir);
  const gitconfig = join(root, '..', 'sprint-gitconfig');
  writeFileSync(gitconfig, '');
  const env = {
    ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: gitconfig,
    GIT_AUTHOR_NAME: 'Scratch', GIT_AUTHOR_EMAIL: 'scratch@example.invalid',
    GIT_COMMITTER_NAME: 'Scratch', GIT_COMMITTER_EMAIL: 'scratch@example.invalid',
  };
  const git = (cwd, ...args) => {
    const out = spawnSync('git', args, { cwd, env, encoding: 'utf8' });
    if (out.status !== 0) throw new Error(`git ${args.join(' ')}: ${out.stderr}`);
  };
  git(root, 'init', '-q', '-b', 'main');
  writeFileSync(join(root, 'steward.toml'), '# stand-in for the live sprint host test; the view does not read it\n');
  writeFileSync(join(root, '.gitignore'), '.steward/\n');
  const sprints = join(root, 'development', 'sprints');
  mkdirSync(sprints, { recursive: true });
  writeFileSync(join(sprints, `${SPRINT_ID}.toml`), readFileSync(join(recorded, `${SPRINT_ID}.toml`)));
  const lines = readFileSync(join(recorded, `${SPRINT_ID}.jsonl`), 'utf8').split('\n');
  writeFileSync(join(sprints, `${SPRINT_ID}.jsonl`), `${lines.slice(0, 4).join('\n')}\n`);
  git(root, 'add', '-A');
  git(root, 'commit', '-qm', 'init');
  const worktree = join(root, '.steward', 'sprints', SPRINT_ID, 'T01');
  mkdirSync(dirname(worktree), { recursive: true });
  git(root, 'worktree', 'add', '-q', '-b', `sprint/${SPRINT_ID}/T01`, worktree);
  for (const [file, subject] of [['a.txt', 'first change'], ['b.txt', 'second change']]) {
    writeFileSync(join(worktree, file), `${file}\n`);
    git(worktree, 'add', file);
    git(worktree, 'commit', '-qm', subject);
  }
  return root;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dir = process.argv[2];
  if (!dir) throw new Error('usage: node scripts/sprint-workspace.mjs DIR');
  console.log(`sprint workspace: ${buildSprintWorkspace(dir)}`);
}
