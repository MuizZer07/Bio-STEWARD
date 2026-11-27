// Agent Skills (S7): the skill folders on disk and the R-60 `skills.copies` result, as tree nodes. Pure: no
// `vscode` import, no file access (src/ui/skills.ts lists the folders).
//
// On CLI 0.20.6 there is no inventory command (C8). The view therefore shows two things side by side:
// - the folder listing: the folders R-60 names (its subject is the canonical folder, its details name the copies)
//   and the known harness folders that exist, each with the folders it holds, exactly as they are on disk
//   (AC-5.3 read for 0.20.6);
// - drift: the R-60 result of the newest report that holds one, with its status, reason and detail codes shown as
//   the CLI reports them. The view never compares skill files itself (no rule semantics here).
import type { ResultItem, Status } from './report';
import { STATUS_LOOK, type Freshness, type ProjectState, type ViewNode } from './views';

// The harness folders the extension looks for (design v0.1 §1.3 J1; PERF-7: known skill folders only).
export const HARNESS_FOLDERS = Object.freeze(['.agents/skills', '.claude/skills'] as const);

// The file a copy holds instead of a link where links are not possible (CLI 0.20.6, R-60).
export const SKILLS_POINTER = 'STEWARD_SKILLS';

// Most skill folders one folder may show; anything beyond is counted, not listed.
export const MAX_LISTED_SKILLS = 500;

export interface SkillsResult {
  readonly result: ResultItem;
  readonly freshness: Freshness;
  readonly partial: boolean;
  readonly scope?: string;
}

// The newest report's R-60 result: a scoped run's when it holds one, else the full report's.
export function skillsResult(state: ProjectState): SkillsResult | undefined {
  for (const loaded of [state.partial, state.full]) {
    const result = loaded?.report.verdict.results.find((item) => item.rule === 'R-60');
    if (loaded && result) return { result, freshness: loaded.freshness, partial: loaded.partial, scope: loaded.scope };
  }
  return undefined;
}

export interface SkillDetail {
  readonly code: string;
  readonly message?: string;
}

export interface FolderRef {
  // Relative to the project root, with forward slashes.
  readonly path: string;
  readonly role: 'canonical' | 'copy' | 'found';
  readonly details: readonly SkillDetail[];
}

export function normalisePath(path: string): string {
  let out = path.replaceAll('\\', '/');
  while (out.startsWith('./')) out = out.slice(2);
  while (out.length > 1 && out.endsWith('/')) out = out.slice(0, -1);
  return out;
}

function detailOf(detail: Readonly<Record<string, unknown>>): SkillDetail {
  const message = typeof detail.message === 'string' ? detail.message : undefined;
  return { code: String(detail.code), message };
}

// The folders to list: those R-60 names, then the known harness folders it does not name.
export function skillFolders(r60: ResultItem | undefined): FolderRef[] {
  const folders = new Map<string, { role: FolderRef['role']; details: SkillDetail[] }>();
  const add = (path: string, role: FolderRef['role'], detail?: SkillDetail) => {
    const key = normalisePath(path);
    if (!key || key === '.') return;
    const entry = folders.get(key) ?? { role, details: [] };
    if (!folders.has(key)) folders.set(key, entry);
    if (detail) entry.details.push(detail);
  };
  if (r60 && r60.status !== 'NOT_APPLICABLE') {
    add(r60.subject, 'canonical');
    for (const raw of r60.details) {
      if (typeof raw.path !== 'string') continue;
      // `R-60.pointer_wrong` names the pointer file inside the copy.
      const path = raw.code === 'R-60.pointer_wrong' && raw.path.endsWith(`/${SKILLS_POINTER}`)
        ? raw.path.slice(0, -SKILLS_POINTER.length - 1)
        : raw.path;
      add(path, normalisePath(path) === normalisePath(r60.subject) ? 'canonical' : 'copy', detailOf(raw));
    }
  }
  for (const path of HARNESS_FOLDERS) add(path, 'found');
  return [...folders].map(([path, { role, details }]) => ({ path, role, details }));
}

export type FolderEntry =
  | { readonly kind: 'directory'; readonly skills: readonly string[]; readonly more: number }
  | { readonly kind: 'link'; readonly target: string; readonly skills?: readonly string[]; readonly more?: number }
  | { readonly kind: 'pointer' }
  | { readonly kind: 'missing' }
  | { readonly kind: 'outside' }
  | { readonly kind: 'not-a-folder' }
  | { readonly kind: 'unreadable' };

export interface FolderListing extends FolderRef {
  readonly entry: FolderEntry;
}

// A known harness folder that does not exist is not shown: the listing is the folders on disk.
export function shownFolders(listings: readonly FolderListing[]): FolderListing[] {
  return listings.filter((folder) => folder.role !== 'found' || folder.entry.kind !== 'missing');
}

const ROLE_TEXT: Readonly<Record<FolderRef['role'], string>> = Object.freeze({
  canonical: 'canonical',
  copy: 'copy',
  found: 'not in [skills]',
});

function count(skills: readonly string[], more = 0): string {
  const total = skills.length + more;
  return `${total} skill folder${total === 1 ? '' : 's'}`;
}

function entryText(entry: FolderEntry): string {
  switch (entry.kind) {
    case 'directory': return count(entry.skills, entry.more);
    case 'link': return `link → ${entry.target}${entry.skills ? ` · ${count(entry.skills, entry.more)}` : ''}`;
    case 'pointer': return `pointer file ${SKILLS_POINTER}`;
    case 'missing': return 'missing';
    case 'outside': return 'outside the project · not listed';
    case 'not-a-folder': return 'not a folder';
    case 'unreadable': return 'unreadable';
  }
}

function entryIcon(entry: FolderEntry): ViewNode['icon'] {
  switch (entry.kind) {
    case 'directory': return { codicon: 'folder' };
    case 'link': return { codicon: 'file-symlink-directory' };
    case 'pointer': return { codicon: 'file-symlink-file' };
    default: return { codicon: 'warning', tone: 'warning' };
  }
}

function folderNode(folder: FolderListing, status: Status | undefined): ViewNode {
  const { entry } = folder;
  const skills = entry.kind === 'directory' || entry.kind === 'link' ? entry.skills ?? [] : [];
  const more = entry.kind === 'directory' || entry.kind === 'link' ? entry.more ?? 0 : 0;
  const children: ViewNode[] = [
    ...folder.details.map((detail, index): ViewNode => ({
      id: `folder:${folder.path}/detail:${index}`,
      kind: 'skills-detail',
      label: detail.code,
      description: detail.message,
      tooltip: [detail.code, detail.message].filter(Boolean).join(': '),
      icon: { codicon: 'info' },
      code: detail.code,
      ...(status ? { ref: { rule: 'R-60', subject: folder.path, status } } : {}),
    })),
    ...skills.map((name): ViewNode => ({
      id: `folder:${folder.path}/skill:${name}`, kind: 'skill', label: name, icon: { codicon: 'book' },
    })),
    ...(more ? [{ id: `folder:${folder.path}/more`, kind: 'skill' as const, label: `… and ${more} more` }] : []),
  ];
  const codes = folder.details.map((detail) => detail.code);
  const description = [ROLE_TEXT[folder.role], entryText(entry), ...codes].join(' · ');
  return {
    id: `folder:${folder.path}`,
    kind: 'skills-folder',
    label: folder.path,
    description,
    tooltip: [folder.path, description, ...folder.details.map((d) => d.message ? `${d.code}: ${d.message}` : d.code)].join('\n'),
    icon: entryIcon(entry),
    children,
    expanded: folder.details.length > 0 && folder.role !== 'canonical',
  };
}

const NOT_CONFIGURED_TIP = 'R-60 checks skill copies once steward.toml has a [skills] table (canonical = "…", copies = […]). ' +
  '`steward init --skills` prints that table; it never edits steward.toml.';

function driftNode(found: SkillsResult | undefined): ViewNode {
  if (!found) {
    return {
      id: 'drift', kind: 'skills-drift', label: 'Drift (R-60)', description: 'no report yet · Check Skills',
      tooltip: 'Run Check Skills (steward check skills) to read R-60 skills.copies.',
      icon: { codicon: 'question', tone: 'info' }, command: 'checkSkills',
    };
  }
  const { result } = found;
  const look = STATUS_LOOK[result.status];
  const from = found.partial ? found.scope ?? 'scoped check' : 'full check';
  return {
    id: 'drift',
    kind: 'result',
    label: 'Drift (R-60 skills.copies)',
    description: `${look.glyph} ${look.text} · ${result.reason} · ${from} · ${found.freshness}`,
    tooltip: [`R-60 ${result.name}: ${look.text}`, result.reason, `From the ${from} (${found.freshness}).`,
      ...(result.status === 'NOT_APPLICABLE' ? [NOT_CONFIGURED_TIP] : [])].join('\n'),
    icon: { codicon: look.codicon, tone: look.tone },
    ref: { rule: result.rule, subject: result.subject, status: result.status },
  };
}

// The Agent Skills tree: drift first, then every folder of the listing.
export function skillsNodes(state: ProjectState, listings: readonly FolderListing[]): ViewNode[] {
  if (!state.trusted) return [];
  const found = skillsResult(state);
  const folders = shownFolders(listings).map((folder) => folderNode(folder, found?.result.status));
  return [
    driftNode(found),
    ...(folders.length ? folders : [{
      id: 'no-folders', kind: 'skills-folder' as const, label: 'No skill folders',
      description: 'Install Agent Skills…', tooltip: `None of ${HARNESS_FOLDERS.join(', ')} exists, and R-60 names none.`,
      icon: { codicon: 'circle-slash', tone: 'disabled' as const }, command: 'installSkills' as const,
    }]),
  ];
}

// The `[skills]` table `steward init --skills` prints when steward.toml has none (it never edits steward.toml).
export function printedSkillsTable(stdout: string): string | undefined {
  const lines = stdout.split(/\r?\n/);
  const start = lines.findIndex((line) => /^\[skills\]/.test(line));
  if (start < 0) return undefined;
  let end = start + 1;
  while (end < lines.length && lines[end].trim() !== '') end++;
  return lines.slice(start, end).join('\n');
}

// The plan lines of `steward init … --dry-run`: action and path (CLI 0.20.6 text, read as printed).
export function planLines(stdout: string): { action: string; path: string }[] {
  return [...stdout.matchAll(/^(would create|would update|create|update|skip|unchanged|print) {2,}(.+?)(?: {2}\(.*\))?$/gm)]
    .map((match) => ({ action: match[1], path: match[2] }));
}
