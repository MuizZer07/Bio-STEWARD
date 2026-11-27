// Freshness on CLI 0.20.6 (S1; design v0.1 §5.3, specification §3): a report is *fresh* right after the run that
// produced it, *stale* once a project file changes, and *unknown* when the extension cannot tell (a report it did
// not just produce, a file change while the run was going, no file watcher). File changes only ever downgrade:
// nothing here can make a report fresh again except a new run, and "current" is never used (it needs C5).
import type { Freshness, LoadedReport, ProjectState } from './views';

// Paths under these folders are not inputs of `steward check`, or change without the project changing:
// `.steward/` holds the CLI's own state and the shared report (VX5); `.git/` changes on every `git status`.
// Inside `.git/`, a moved HEAD or branch is a change (the report records the commit it was made at).
const GIT_INPUTS = /^\.git\/(HEAD|packed-refs|refs\/.+)$/;

// `relative` is the path from the project root, with `/` or the platform separator.
export function isWatchedInput(relative: string): boolean {
  const path = relative.replaceAll('\\', '/');
  if (!path || path === '.' || path === '..' || path.startsWith('../') || path.startsWith('/')) return false;
  if (path === '.steward' || path.startsWith('.steward/')) return false;
  if (path === '.git' || path.startsWith('.git/')) return GIT_INPUTS.test(path);
  return true;
}

const RANK: Readonly<Record<Freshness, number>> = Object.freeze({ fresh: 0, unknown: 1, stale: 2 });

// The worse of two freshness states: stale over unknown over fresh. Used for every downgrade.
export function worse(a: Freshness, b: Freshness): Freshness {
  return RANK[a] >= RANK[b] ? a : b;
}

function downgradeReport(loaded: LoadedReport | undefined, to: Freshness): LoadedReport | undefined {
  if (!loaded) return loaded;
  const freshness = worse(loaded.freshness, to);
  return freshness === loaded.freshness ? loaded : { ...loaded, freshness };
}

// Every report held is downgraded to at least `to`; the same object comes back when nothing changed.
export function downgrade(state: ProjectState, to: Freshness): ProjectState {
  const full = downgradeReport(state.full, to);
  const partial = downgradeReport(state.partial, to);
  return full === state.full && partial === state.partial ? state : { ...state, full, partial };
}

// A watched project file was created, changed or deleted.
export function withInputChanged(state: ProjectState): ProjectState {
  return downgrade(state, 'stale');
}

// The freshness a report gets when it lands: fresh only from the extension's own run, with a watcher that saw no
// input change while the run was going.
export function freshnessOfRun(options: { watching: boolean; changedDuringRun: boolean }): Freshness {
  return options.watching && !options.changedDuringRun ? 'fresh' : 'unknown';
}
