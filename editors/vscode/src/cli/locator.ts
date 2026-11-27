import { constants } from 'node:fs';
import { access, lstat, realpath, stat } from 'node:fs/promises';
import { delimiter, isAbsolute, join, resolve, sep } from 'node:path';
import { isWithin } from './paths';

export type Location =
  | { kind: 'found'; path: string; source: 'setting' | 'path' | 'tools' }
  | { kind: 'missing' | 'invalid-setting' };

interface LocateOptions {
  // Pass VS Code's inspected setting. Workspace and workspace-folder values are ignored.
  setting?: { globalValue?: string };
  workspaceRoots: readonly string[];
  env: NodeJS.ProcessEnv;
  home: string;
}

async function executable(path: string): Promise<string | undefined> {
  if (!isAbsolute(path) || path.includes('\0')) return undefined;
  try {
    const target = await realpath(path);
    if (!(await stat(target)).isFile()) return undefined;
    await access(target, constants.X_OK);
    return target;
  } catch {
    return undefined;
  }
}

// A program on one of these folders' lists, never one inside a workspace folder or a `.venv` (T2).
async function findIn(
  name: string,
  lists: readonly (readonly [string, readonly (string | undefined)[]])[],
  workspaceRoots: readonly string[],
): Promise<{ path: string; source: string } | undefined> {
  const roots = await Promise.all(workspaceRoots.map(async (root) => {
    const absolute = resolve(root);
    return [absolute, await realpath(absolute).catch(() => absolute)];
  }));
  const isLocal = (path: string) =>
    path.split(sep).includes('.venv') || roots.some((aliases) => aliases.some((root) => isWithin(root, path)));
  for (const [source, directories] of lists) {
    for (const directory of directories) {
      if (!directory || !isAbsolute(directory)) continue;
      const candidate = resolve(directory, name);
      if (isLocal(candidate)) continue;
      const path = await executable(candidate);
      if (path && !isLocal(path)) return { path, source };
    }
  }
  return undefined;
}

// A program found on PATH under the same rules as the CLI: absolute PATH entries only, nothing inside a
// workspace folder (also through a symlink) or a `.venv`. Used for `git` (src/cli/git.ts).
export async function findOnPath(name: string, workspaceRoots: readonly string[], env: NodeJS.ProcessEnv): Promise<string | undefined> {
  return (await findIn(name, [['path', (env.PATH ?? '').split(delimiter)]], workspaceRoots))?.path;
}

export async function locateCli({ setting, workspaceRoots, env, home }: LocateOptions): Promise<Location> {
  if (setting?.globalValue) {
    const path = await executable(setting.globalValue);
    return path ? { kind: 'found', path, source: 'setting' } : { kind: 'invalid-setting' };
  }

  const pathDirectories = (env.PATH ?? '').split(delimiter);
  const toolDirectories = [env.PIPX_BIN_DIR, env.UV_TOOL_BIN_DIR, env.XDG_BIN_HOME, join(home, '.local', 'bin'),
    env.UV_TOOL_DIR && join(env.UV_TOOL_DIR, 'bio-steward', 'bin'),
    env.PIPX_HOME && join(env.PIPX_HOME, 'venvs', 'bio-steward', 'bin'),
    join(env.XDG_DATA_HOME || join(home, '.local', 'share'), 'uv', 'tools', 'bio-steward', 'bin'),
    join(env.XDG_DATA_HOME || join(home, '.local', 'share'), 'pipx', 'venvs', 'bio-steward', 'bin'),
    join(home, '.local', 'pipx', 'venvs', 'bio-steward', 'bin')];

  const found = await findIn('steward', [['path', pathDirectories], ['tools', toolDirectories]], workspaceRoots);
  return found ? { kind: 'found', path: found.path, source: found.source as 'path' | 'tools' } : { kind: 'missing' };
}

export async function findProjectRoot(directory: string, workspaceRoot: string): Promise<string | undefined> {
  const boundary = await realpath(workspaceRoot);
  let current = await realpath(directory);
  while (isWithin(boundary, current)) {
    try {
      if ((await lstat(join(current, 'steward.toml'))).isFile()) return current;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
    if (current === boundary) break;
    current = resolve(current, '..');
  }
  return undefined;
}
