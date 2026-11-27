// The one git command the extension may run (S10; Muiz, 2026-11-26, option (a) in DECISIONS.md): is
// `.steward/report.json` git-ignored? It decides where `bioSteward.report.location = auto` writes the report (VX5).
//
// The live sprint view runs no git (T12, decision D1 on T11-01 and T11-02: `git status` could run a filter program
// the repository's own config defines, and object reads could fetch). Its commits and changed files come later from
// the CLI (`sprint status --format json`, request STW-052).
//
// - The builder is on its own allow-list: the steward runner refuses it, and a git runner refuses everything else.
// - `core.fsmonitor`, `core.hooksPath` and `core.untrackedCache` are forced off on the command line, because a
//   repository's own `.git/config` could otherwise make git start a program (the fsmonitor hook).
// - git runs with a cleaned environment (`gitEnvironment`): only PATH and HOME are kept, every `GIT_*` variable of
//   the host is dropped (so nothing redirects the repository, its config or its object store), and
//   GIT_CONFIG_NOSYSTEM=1 leaves the machine-wide config out.
// - The same runner rules as the CLI: no shell, trusted workspaces only, the project root as working directory,
//   the timeout. git is found on PATH, never inside a workspace folder or a `.venv` (like the CLI, T2).
// - Exit 0: ignored. Exit 1: not ignored. Anything else, or no git: treated as not ignored, so the report goes to
//   the extension's storage and nothing is written to the repository.
import type { Invocation } from './commands';
import { findOnPath } from './locator';
import { CliRunner } from './runner';

export const CHECK_IGNORE_ARGS = Object.freeze([
  '-c', 'core.fsmonitor=false',
  '-c', 'core.hooksPath=/dev/null',
  '-c', 'core.untrackedCache=false',
  'check-ignore', '-q', '--', '.steward/report.json',
]);

const built = new WeakSet<Invocation>();

export function isGitAllowed(invocation: Invocation): boolean {
  return built.has(invocation);
}

export const gitCommands = Object.freeze({
  checkIgnoreReport(): Invocation {
    const invocation: Invocation = Object.freeze({
      args: CHECK_IGNORE_ARGS,
      repoIndex: undefined,
      paths: Object.freeze([]),
      confirmation: false,
    });
    built.add(invocation);
    return invocation;
  },
});

// The environment git runs with: PATH and HOME of the host, GIT_CONFIG_NOSYSTEM=1, and nothing else (no GIT_DIR,
// GIT_WORK_TREE, GIT_CONFIG_*, GIT_EXEC_PATH, GIT_ALTERNATE_OBJECT_DIRECTORIES or any other variable).
export function gitEnvironment(host: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { GIT_CONFIG_NOSYSTEM: '1' };
  for (const name of ['PATH', 'HOME'] as const) {
    if (typeof host[name] === 'string') env[name] = host[name];
  }
  return env;
}

export type IgnoreAnswer =
  | { readonly ignored: true; readonly why: 'git: ignored' }
  | { readonly ignored: false; readonly why: string };

export interface CheckIgnoreOptions {
  root: string;
  workspaceRoots: readonly string[];
  // For finding git on PATH only; the child always gets `gitEnvironment(process.env)`.
  env: NodeJS.ProcessEnv;
  isTrusted: () => boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
}

// Whether `.steward/report.json` is git-ignored in `root`. Never throws.
export async function reportIgnored(options: CheckIgnoreOptions): Promise<IgnoreAnswer> {
  try {
    if (!options.isTrusted()) return { ignored: false, why: 'untrusted' };
    const git = await findOnPath('git', options.workspaceRoots, options.env);
    if (!git) return { ignored: false, why: 'git not found' };
    const runner = new CliRunner({
      program: 'git',
      cli: git,
      root: options.root,
      flight: 'check-ignore',
      isTrusted: options.isTrusted,
      timeoutMs: options.timeoutMs ?? 10_000,
      maxOutputBytes: 64 * 1024,
    });
    const result = await runner.run(gitCommands.checkIgnoreReport(), { signal: options.signal });
    if (result.kind !== 'completed') return { ignored: false, why: `git: ${result.kind}` };
    if (result.exitCode === 0) return { ignored: true, why: 'git: ignored' };
    return { ignored: false, why: result.exitCode === 1 ? 'git: not ignored' : `git: exit ${result.exitCode}` };
  } catch (error) {
    return { ignored: false, why: `git: ${error instanceof Error ? error.message : String(error)}` };
  }
}
