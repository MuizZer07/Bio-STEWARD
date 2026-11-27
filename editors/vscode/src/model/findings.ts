import { realpath, stat } from 'node:fs/promises';
import { isAbsolute, relative, sep } from 'node:path';
import { confinedPath } from '../cli/paths';
import type { ResultItem, Status } from './report';

type FileLookup = (path: string) => Promise<string | undefined>;
export type UnknownSeverity = 'information' | 'warning';
export type Severity = 'error' | 'warning' | 'information';

export function severityFor(status: Status, unknown: UnknownSeverity): Severity | undefined {
  switch (status) {
    case 'FAIL': return 'error';
    case 'INCOMPLETE': return 'warning';
    case 'UNKNOWN': return unknown;
    default: return undefined;
  }
}

export function resultCode(rule: string, value: unknown): string | undefined {
  return typeof value === 'string' && /^R-\d{2}\.[A-Za-z0-9_]+$/.test(value) && value.startsWith(rule + '.')
    ? value : undefined;
}

export interface Anchor {
  path: string;
  line: number;
  code?: string;
}

// Cache only for one refresh. Use canonical paths for confinement and root-relative paths for editor URIs.
export function projectFiles(root: string): FileLookup {
  const canonicalRoot = realpath(root).catch(() => undefined);
  const cache = new Map<string, Promise<string | undefined>>();
  async function lookup(value: string): Promise<string | undefined> {
    const canonical = await canonicalRoot;
    if (!canonical) return undefined;
    const path = await confinedPath(root, value)
      ?? (isAbsolute(value) && canonical !== root ? await confinedPath(canonical, value) : undefined);
    if (!path || !(await stat(path).catch(() => undefined))?.isFile()) return undefined;
    return relative(canonical, path).split(sep).join('/');
  }
  return (value) => {
    const cached = cache.get(value);
    if (cached) return cached;
    const resolved = lookup(value);
    cache.set(value, resolved);
    return resolved;
  };
}

export async function resultAnchors(result: ResultItem, file: FileLookup): Promise<Anchor[]> {
  const anchors: Anchor[] = [];
  const seen = new Set<string>();
  for (const detail of result.details) {
    if (typeof detail.path !== 'string') continue;
    const path = await file(detail.path);
    if (!path) continue;
    const line = typeof detail.line === 'number' && Number.isSafeInteger(detail.line) && detail.line > 0
      ? detail.line : 1;
    const code = resultCode(result.rule, detail.code);
    const key = JSON.stringify([path, line, code]);
    if (seen.has(key)) continue;
    seen.add(key);
    anchors.push({ path, line, code });
  }
  if (anchors.length) return anchors;
  const path = await file(result.subject);
  return path ? [{ path, line: 1, code: resultCode(result.rule, result.details[0]?.code) }] : [];
}
