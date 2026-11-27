// Agent Skills on disk (S7), without `vscode`, so the unit tests run it on real folders.
//
// - The folder listing: CLI 0.20.6 has no skills inventory (C8), so the folders R-60 names and the known harness
//   folders are read from disk (PERF-7: nothing else is scanned), each confined to the project (T5): a folder, or
//   a link's target, outside the project is named but never listed.
// - The check that a `steward init --skills … --dry-run` plan only creates new paths inside the project.
// Read-only: nothing here writes.
import { lstat, readdir, readlink, realpath } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { confinedPath, isWithin } from './cli/paths';
import {
  MAX_LISTED_SKILLS, SKILLS_POINTER, planLines, type FolderEntry, type FolderListing, type FolderRef,
} from './model/skills';

async function folderNames(path: string): Promise<{ skills: string[]; more: number }> {
  const entries = await readdir(path, { withFileTypes: true });
  const names = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
  return { skills: names.slice(0, MAX_LISTED_SKILLS), more: Math.max(0, names.length - MAX_LISTED_SKILLS) };
}

export async function entryFor(root: string, path: string): Promise<FolderEntry> {
  const candidate = resolve(root, path);
  if (!isWithin(root, candidate) || candidate === root) return { kind: 'outside' };
  // Every folder above it must stay inside the project, even when the folder itself does not exist.
  const parent = dirname(candidate);
  if (parent !== root && !await confinedPath(root, relative(root, parent), true)) return { kind: 'outside' };
  const status = await lstat(candidate).catch((error: NodeJS.ErrnoException) => error.code === 'ENOENT' ? 'missing' as const : undefined);
  if (status === 'missing') return { kind: 'missing' };
  if (!status) return { kind: 'unreadable' };
  // The folder itself, resolved: it, and every folder above it, must stay inside the project.
  const inside = await confinedPath(root, path);
  try {
    if (status.isSymbolicLink()) {
      const target = await readlink(candidate);
      if (!inside || !(await lstat(inside)).isDirectory()) return { kind: 'link', target };
      return { kind: 'link', target, ...await folderNames(inside) };
    }
    if (!inside) return { kind: 'outside' };
    if (!status.isDirectory()) return { kind: 'not-a-folder' };
    const pointer = await lstat(resolve(inside, SKILLS_POINTER)).then((entry) => entry.isFile(), () => false);
    if (pointer) return { kind: 'pointer' };
    return { kind: 'directory', ...await folderNames(inside) };
  } catch {
    return { kind: 'unreadable' };
  }
}

// The folders on disk for these references (AC-5.3 read for 0.20.6). Read-only.
export async function listSkillFolders(root: string, refs: readonly FolderRef[]): Promise<FolderListing[]> {
  const canonical = await realpath(root);
  return Promise.all(refs.map(async (ref) => ({ ...ref, entry: await entryFor(canonical, ref.path) })));
}

// Why a plan cannot be applied, or undefined. Every path the plan would create must be new and inside the project
// (not reached through a link); a plan to create steward.toml means the folder is not a project yet.
export async function skillsPlanBlock(root: string, stdout: string): Promise<string | undefined> {
  const plan = planLines(stdout);
  const created = plan.filter((line) => line.action === 'would create').map((line) => line.path);
  if (created.includes('steward.toml')) return 'This folder has no steward.toml. Run Initialize Project… first.';
  if (!created.length) return 'Nothing to install: every skill in this plan already exists. The CLI never overwrites a skill.';
  for (const path of created) {
    const target = resolve(root, path);
    if (await confinedPath(root, path, true) !== target) {
      return 'A planned destination is outside the project, inaccessible, or redirected through a link.';
    }
    const missing = await lstat(target).then(() => false, (error: NodeJS.ErrnoException) => error.code === 'ENOENT');
    if (!missing) return 'A planned destination already exists or is inaccessible.';
  }
  return undefined;
}

