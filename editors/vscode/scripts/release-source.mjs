// Where the pinned CLI release (tag v<testedWithCli>) comes from, for `npm run cli:install` and `npm run fixtures`.
//
// - local: the release tag in the git repository that holds this extension (this project's own checkout, or any
//   of its worktrees). Its tree is read with `git archive`, which gives the released files byte for byte, and
//   nothing is fetched from the public repository.
// - pypi: `bio-steward==<version>` from PyPI.
// - tag:  the public repository's release tag (`git+https://…@v<version>`).
//
// With no choice given (`auto`), the order is local when the enclosing repository has the tag, then PyPI, then the
// public tag. So runs inside the development repository (sprints, tests) never clone the public repository, and
// its clone counts stay those of real users.
import { execFileSync } from 'node:child_process';

export const REPOSITORY = 'https://github.com/MuizZer07/Bio-STEWARD';
export const SOURCES = Object.freeze(['local', 'pypi', 'tag']);

// The commit the tag `v<version>` names in the repository that holds `dir`, or undefined (no git, no repository,
// or no such tag). Only local git commands; no remote is contacted.
export function localTag(dir, version) {
  const ref = `refs/tags/v${version}`;
  try {
    const top = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const commit = execFileSync('git', ['rev-parse', '--verify', '--quiet', `${ref}^{commit}`],
      { cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    return /^[0-9a-f]{40,64}$/.test(commit) ? { repository: top, ref, commit } : undefined;
  } catch {
    return undefined;
  }
}

// The sources to try, in order. `requested` is 'auto' or one of SOURCES; `hasLocal` says whether localTag found
// the tag. A requested source is the only one tried; `local` without the tag is an error the caller reports.
export function chooseSources(requested, hasLocal) {
  if (requested === 'auto') return hasLocal ? ['local'] : ['pypi', 'tag'];
  if (!SOURCES.includes(requested)) throw new Error(`--source must be local, pypi, tag or auto, not ${requested}`);
  if (requested === 'local' && !hasLocal) throw new Error('--source local: the enclosing git repository has no tag v<version>');
  return [requested];
}

// How each source is named in the output.
export function sourceName(source, version, local) {
  switch (source) {
    case 'local': return `the local release tag v${version} (${local?.commit ?? 'not found'}, git archive; nothing fetched from the public repository)`;
    case 'pypi': return `PyPI (bio-steward==${version})`;
    case 'tag': return `${REPOSITORY} tag v${version}`;
    default: return source;
  }
}
