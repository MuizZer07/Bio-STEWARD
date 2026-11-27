import { lstat, realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

export function isWithin(root: string, candidate: string): boolean {
  const remainder = relative(root, candidate);
  return !isAbsolute(remainder) && remainder !== '..' && !remainder.startsWith('..' + sep);
}

// Resolve existing ancestors as well as the destination, so a new output file
// cannot be redirected through a symlink. A dangling link is never a new file.
async function resolveDestination(candidate: string, allowMissing: boolean): Promise<string> {
  try {
    return await realpath(candidate);
  } catch (error) {
    if (!allowMissing || (error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  const entry = await lstat(candidate).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== 'ENOENT') throw error;
    return undefined;
  });
  if (entry) throw new Error('Unresolvable path');
  const parent = dirname(candidate);
  const resolvedParent = await resolveDestination(parent, true);
  return resolve(resolvedParent, relative(parent, candidate));
}

export async function confinedPath(root: string, value: string, allowMissing = false): Promise<string | undefined> {
  if (!value || value.includes('\0')) return undefined;
  const candidate = resolve(root, value);
  if (!isWithin(root, candidate)) return undefined;
  try {
    const canonicalRoot = await realpath(root);
    const canonicalPath = await resolveDestination(candidate, allowMissing);
    if (canonicalPath !== canonicalRoot && isWithin(canonicalRoot, canonicalPath)) return canonicalPath;
  } catch {
    // Unreadable paths and broken links cannot be used.
  }
  return undefined;
}

// A project file named by a POSIX path relative to the root (P3 task files, P6 decisions logs), as CLI 0.20.6
// `fsutil.iter_repo_files` would list it (U09): every folder on the way is a real folder (not a link) and none is
// `.git`, and the file itself is a regular file, not a link. Returns its path under the canonical root.
export async function unlinkedFile(root: string, relativePath: string): Promise<string | undefined> {
  if (typeof relativePath !== 'string' || !relativePath || relativePath.includes('\0') || relativePath.includes('\\')) return undefined;
  const parts = relativePath.split('/');
  if (parts.some((part) => !part || part === '.' || part === '..' || part === '.git')) return undefined;
  try {
    let path = await realpath(root);
    for (const [i, part] of parts.entries()) {
      path = `${path}/${part}`;
      const entry = await lstat(path);
      if (entry.isSymbolicLink()) return undefined;
      if (i < parts.length - 1 ? !entry.isDirectory() : !entry.isFile()) return undefined;
    }
    return path;
  } catch {
    return undefined;
  }
}

// The folder a walk starts from (a glob's fixed prefix), as `unlinkedFile` but a folder; '' is the root itself.
export async function unlinkedFolder(root: string, relativePath: string): Promise<string | undefined> {
  try {
    let path = await realpath(root);
    if (!relativePath) return path;
    const parts = relativePath.split('/');
    if (parts.some((part) => !part || part === '.' || part === '..' || part === '.git')) return undefined;
    for (const part of parts) {
      path = `${path}/${part}`;
      const entry = await lstat(path);
      if (entry.isSymbolicLink() || !entry.isDirectory()) return undefined;
    }
    return path;
  } catch {
    return undefined;
  }
}

// An agent log (P4) selected from a setting's file or folder (U09): still a regular file, reached without any link
// (its path is its own canonical path), and still the selected file or inside the selected folder.
export async function boundedLog(value: string, boundary: string): Promise<string | undefined> {
  if (typeof value !== 'string' || !isAbsolute(value) || value.includes('\0') || !isAbsolute(boundary)) return undefined;
  try {
    if (await realpath(boundary) !== boundary || await realpath(value) !== value) return undefined;
    const entry = await lstat(value);
    if (entry.isSymbolicLink() || !entry.isFile()) return undefined;
    return value === boundary || isWithin(boundary, value) ? value : undefined;
  } catch {
    return undefined;
  }
}

// An agent log (P4): an absolute path whose target is an existing regular file, resolved through links.
export async function existingFile(value: string): Promise<string | undefined> {
  if (typeof value !== 'string' || !isAbsolute(value) || value.includes('\0')) return undefined;
  try {
    const canonical = await realpath(value);
    return (await stat(canonical)).isFile() ? canonical : undefined;
  } catch {
    return undefined;
  }
}
