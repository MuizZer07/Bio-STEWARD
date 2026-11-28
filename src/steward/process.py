"""Process rules of 0.9.0 (RELEASE_v0.9.0_SPEC §2.3 – §2.7): R-56 dependency boundary, R-57 task board, R-58
changelog, R-59 branch model, R-60 skills copies.

Each is NOT_APPLICABLE without its table. Git is read through the safe helper and only tree-to-tree or ref queries
are made, so no repository-configured filter or hook runs (red-team L1). Uncommitted changes are not considered by
R-58 and R-59: they judge history.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from .fsutil import git_run, glob_match, iter_repo_files
from .rules import Ctx, result
from .status import Result, Status, combine

def _why(status: Status, ok: str, fail: str, incomplete: str = "", unknown: str = "") -> str:
    return {Status.FAIL: fail, Status.INCOMPLETE: incomplete or fail, Status.UNKNOWN: unknown or fail}.get(status, ok)


LIST_MAX = 20  # details listed per code; the count is always given


def _cap(details: list[dict[str, Any]], code: str) -> list[dict[str, Any]]:
    same = [d for d in details if d["code"] == code]
    if len(same) <= LIST_MAX:
        return details
    keep = [d for d in details if d["code"] != code] + same[:LIST_MAX]
    return keep + [{"code": code + "_more", "value": len(same) - LIST_MAX, "message": "further occurrences not listed"}]


# ---------------------------------------------------------------- R-56 boundary.imports (B3, REQ-005)
def _norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(req: str) -> str | None:
    m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    return _norm_dist(m.group(1)) if m else None


def _forbidden(mod: str, prefixes: list[str]) -> str | None:
    return next((p for p in prefixes if mod == p or mod.startswith(p + ".")), None)


def _imports(tree: ast.AST) -> tuple[list[tuple[str, int]], list[int]]:
    """(module, line) for every absolute import and literal dynamic import; lines of computed dynamic imports."""
    found, computed = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # a relative import stays inside its package
                found.append((node.module, node.lineno))
                found += [(f"{node.module}.{a.name}", node.lineno) for a in node.names if a.name != "*"]  # Q16
        elif isinstance(node, ast.Call):
            f = node.func
            dyn = (isinstance(f, ast.Name) and f.id in ("__import__", "import_module")) or (
                isinstance(f, ast.Attribute) and f.attr == "import_module")
            if not dyn:
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if not arg.value.startswith("."):
                    found.append((arg.value, node.lineno))
            else:
                computed.append(node.lineno)
    return found, computed


def r56(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    bc = ctx.config.boundary
    if bc is None:
        return [result("R-56", ".", Status.NOT_APPLICABLE, "[boundary] is not configured")]
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    files = [rel for rel in iter_repo_files(ctx.root) if rel.endswith(".py") and any(
        glob_match(rel, p) or rel.startswith(p.rstrip("/") + "/") for p in bc.packages)]
    for rel in files:
        try:
            tree = ast.parse(ctx.read(rel), filename=rel)
        except (SyntaxError, ValueError, OSError) as e:
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-56.unparsable", "path": rel, "message": str(e)[:200]})
            continue
        found, computed = _imports(tree)
        for mod, line in found:
            hit = _forbidden(mod, bc.forbidden_imports)
            if hit:
                causes.append(Status.FAIL)
                details.append({"code": "R-56.forbidden_import", "path": rel, "line": line, "value": mod})
        for line in computed:
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-56.computed_import", "path": rel, "line": line,
                            "message": "a computed module name cannot be checked statically"})
    banned = {_norm_dist(d) for d in bc.forbidden_distributions}
    if banned and not (ctx.root / bc.pyproject).is_file():  # Q16: declared, and nothing to check them in
        causes.append(Status.INCOMPLETE)
        details.append({"code": "R-56.no_pyproject", "path": bc.pyproject})
    if banned and (ctx.root / bc.pyproject).is_file():
        try:
            py = tomllib.loads(ctx.read(bc.pyproject).decode("utf-8"))
        except (ValueError, RecursionError, UnicodeDecodeError) as e:
            py = None
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-56.pyproject_invalid", "path": bc.pyproject, "message": str(e)[:200]})
        if py is not None:
            project = py.get("project", {}) if isinstance(py.get("project"), dict) else {}
            where: list[tuple[str, Any]] = [("dependencies", project.get("dependencies", []))]
            where += [(f"optional-dependencies.{g}", v) for g, v in (project.get("optional-dependencies") or {}).items()
                      if g not in bc.allow_groups]
            groups = py.get("dependency-groups") or {}

            def expand(g: str, seen: set[str]) -> list[Any]:  # Q16: included groups are part of the group
                out: list[Any] = []
                for r in groups.get(g, []) if isinstance(groups.get(g), list) else []:
                    if isinstance(r, dict) and isinstance(r.get("include-group"), str) and r["include-group"] not in seen:
                        out += expand(r["include-group"], seen | {r["include-group"]})
                    else:
                        out.append(r)
                return out
            where += [(f"dependency-groups.{g}", expand(g, {g})) for g in groups if g not in bc.allow_groups]
            for label, reqs in where:
                for req in reqs if isinstance(reqs, list) else []:
                    name = _req_name(req) if isinstance(req, str) else None  # {include-group = …} entries are skipped
                    if name in banned:
                        causes.append(Status.FAIL)
                        details.append({"code": "R-56.forbidden_distribution", "path": bc.pyproject, "value": name,
                                        "message": f"in {label}"})
    details.append({"code": "R-56.scanned", "value": len(files), "message": f"{len(files)} Python file(s) parsed"})
    details = _cap(_cap(details, "R-56.forbidden_import"), "R-56.computed_import")
    status = combine(causes)
    return [result("R-56", ".", status, _why(status, "no forbidden import or dependency found" if files
                   else "no Python files under the declared packages", "a forbidden import or dependency is present",
                   unknown="an import or the pyproject file could not be checked"), details)]


# ---------------------------------------------------------------- R-57 tasks.board (B4, REQ-007)
ID_LINE = re.compile(r"^\s*[-*]\s*\*\*ID:\*\*\s*`?([^`\s]+)`?", re.M)
STATUS_LINE = re.compile(r"^\s*[-*]\s*\*\*Status:\*\*\s*(.+?)\s*$", re.M)
NEXT_LINE = re.compile(r"Next unused ID:\**\s*`?([A-Za-z0-9._-]*[A-Za-z0-9])`?", re.I)  # DEF-030: not a full stop


def _status(value: str | None, statuses: list[str]) -> str | None:
    """The configured status a **Status:** line holds: the whole value, or the longest status followed by a
    qualifier in brackets or after a dash (`in progress (left: CI)`, `blocked — waiting on X`) (DEF-030)."""
    if value is None:
        return None
    if value in statuses:
        return value
    for st in sorted(statuses, key=len, reverse=True):
        if re.match(rf"^{re.escape(st)}(?:\s+\(.*\)|\s+[—–-]\s+.+)$", value):
            return st
    return value


def _num(tid: str) -> tuple[str, int] | None:
    m = re.match(r"^(.*?)(\d+)$", tid)
    return (m.group(1), int(m.group(2))) if m else None


def r57(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    tc = ctx.config.tasks
    if tc is None:
        return [result("R-57", ".", Status.NOT_APPLICABLE, "[tasks] is not configured")]
    pat = re.compile(rf"^(?:{tc.id_pattern})$")
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    all_files = list(iter_repo_files(ctx.root))
    archive = [f for f in all_files if any(glob_match(f, g) for g in tc.archive)]
    specs = [f for f in all_files if any(glob_match(f, g) for g in tc.specs) and f not in archive and f != tc.board]
    seen: dict[str, str] = {}
    open_ids: list[tuple[str, str, int]] = []
    for rel in specs + archive:
        text = ctx.read(rel).decode("utf-8", errors="replace")
        m = ID_LINE.search(text)
        if not m or not pat.match(m.group(1)):
            causes.append(Status.FAIL)
            details.append({"code": "R-57.no_id", "path": rel, "message": f"no **ID:** line matching {tc.id_pattern}"})
            continue
        tid = m.group(1)
        id_line = text.count("\n", 0, m.start(1)) + 1  # C4 (0.21.0): the location of the ID line
        if tid in seen:
            causes.append(Status.FAIL)
            details.append({"code": "R-57.duplicate_id", "path": rel, "line": id_line, "value": tid,
                            "message": f"also in {seen[tid]}"})
        else:
            seen[tid] = rel
        s = STATUS_LINE.search(text)
        status = _status(s.group(1) if s else None, tc.statuses)
        if status is None or status not in tc.statuses:
            causes.append(Status.FAIL)
            details.append({"code": "R-57.unknown_status", "path": rel,
                            "line": text.count("\n", 0, s.start()) + 1 if s else id_line, "value": status or "(none)",
                            "message": f"use one of: {' | '.join(tc.statuses)}"})
        if rel in specs and status not in tc.closed:
            open_ids.append((tid, rel, id_line))
    if not (ctx.root / tc.board).is_file():
        causes.append(Status.FAIL)
        details.append({"code": "R-57.no_board", "path": tc.board})
    else:
        btext = ctx.read(tc.board).decode("utf-8", errors="replace")
        # Q17: an entry is a list item or a table row, not a mention in prose (the Next line lists nothing)
        listed = "\n".join(l for l in NEXT_LINE.sub("", btext).splitlines()
                           if re.match(r"^\s*([-*+]|\d+[.)]|\|)\s*", l))
        for tid, rel, id_line in open_ids:
            if not re.search(rf"(?<![\w-]){re.escape(tid)}(?![\w-])", listed):
                causes.append(Status.FAIL)
                details.append({"code": "R-57.not_on_board", "path": rel, "line": id_line, "value": tid})
        nm = NEXT_LINE.search(btext)
        used = [n for n in (_num(t) for t in seen) if n]
        if nm is None:
            causes.append(Status.FAIL)
            details.append({"code": "R-57.no_next_id", "path": tc.board, "message": "add a line: Next unused ID: …"})
        elif not pat.match(nm.group(1)):  # Q17: the counter itself follows the pattern
            causes.append(Status.FAIL)
            details.append({"code": "R-57.next_id_invalid", "path": tc.board, "message": f"does not match {tc.id_pattern}"})
        elif used:
            nxt = _num(nm.group(1))
            top = max(n for _, n in used)
            if nxt is None or nxt[1] <= top:
                causes.append(Status.FAIL)
                details.append({"code": "R-57.next_id_stale", "path": tc.board, "value": nm.group(1),
                                "message": f"an ID up to number {top} is in use"})
    status = combine(causes)
    return [result("R-57", tc.board, status, _why(status, f"{len(seen)} task ID(s) unique; {len(open_ids)} open "
                   "task(s) on the board", "the task specs and the board disagree"), details)]


# ---------------------------------------------------------------- R-58 changelog.unreleased (B5, REQ-008)
def _last_tag(root: Path, pattern: str, ref: str = "HEAD") -> str | None:
    out = git_run(root, "describe", "--tags", "--abbrev=0", "--match", pattern, ref, text=True, timeout=30)
    return out.stdout.strip() or None if out.returncode == 0 else None


def _head_state(root: Path) -> str:
    """"commit" (HEAD names a commit), "unborn" (a repository with no commit yet), or "unknown" (git failed)."""
    if git_run(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0:
        return "commit"
    if not (root / ".git").exists():  # not a git checkout: there is no history to read
        return "unborn"
    refs = git_run(root, "for-each-ref", "--count=1", text=True)
    sym = git_run(root, "symbolic-ref", "-q", "HEAD", text=True)
    if refs.returncode == 0 and not refs.stdout.strip() and sym.returncode == 0:
        return "unborn"
    return "unknown"


def _blob_state(root: Path, ref: str, rel: str) -> str:
    """"present", "absent" or "unknown" for `rel` at `ref`: `ls-tree` answers absent with success and no output, so a
    failure of git itself is never taken for an absent file (R12)."""
    out = git_run(root, "ls-tree", "-z", ref, "--", rel)
    if out.returncode != 0:
        return "unknown"
    return "present" if out.stdout.strip(b"\0") else "absent"


def unreleased_entries(text: str) -> list[str] | None:
    """The non-blank, non-heading lines of the `Unreleased` section, or None when there is no such section."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^##\s+\[?Unreleased\]?\s*(?:$|[(:—–-])", l, re.I)), None)
    if start is None:
        return None
    body = []
    for l in lines[start + 1:]:
        if re.match(r"^##\s", l):
            break
        if l.strip() and not l.lstrip().startswith("#"):
            body.append(l)
    return body


def entry_format(entries: list[str], cc: Any, final: bool) -> list[dict[str, Any]]:
    """Problems of the Unreleased entry lines, by line number in the section; the entry text is never copied into a
    report (review Q18)."""
    out = []
    for n, line in enumerate(entries, start=1):
        if not line.lstrip().startswith(("- ", "* ")) or line.startswith((" ", "\t")):
            continue  # continuation lines and nested items belong to the entry above
        if cc.entry_pattern and not re.search(cc.entry_pattern, line):
            out.append({"code": "R-58.entry_malformed", "value": n, "message": "entry line does not match entry_pattern"})
        elif final and cc.ready:
            m = re.search(r"Status:\s*([A-Za-z-]+)", line)
            if not m or m.group(1) != cc.ready:
                out.append({"code": "R-58.not_ready", "value": n, "message": f"entry line is not Status: {cc.ready}"})
    return out


def _bullets(entries: list[str] | None) -> list[str]:
    return [l for l in entries or [] if l.lstrip().startswith(("- ", "* ")) and not l.startswith((" ", "\t"))]


def r58(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    cc = ctx.config.changelog
    if cc is None:
        return [result("R-58", ".", Status.NOT_APPLICABLE, "[changelog] is not configured")]
    tag = _last_tag(ctx.root, cc.tag_pattern)
    if tag is None:
        return [result("R-58", cc.file, Status.UNKNOWN, f"no release tag matching {cc.tag_pattern!r} before HEAD",
                       [{"code": "R-58.no_tag"}])]
    diff = git_run(ctx.root, "diff", "--name-only", "-z", "--no-renames", tag, "HEAD", timeout=60)
    if diff.returncode != 0:
        return [result("R-58", cc.file, Status.UNKNOWN, "cannot list the changes since the release tag",
                       [{"code": "R-58.git_error", "value": tag}])]
    changed = [p.decode("utf-8", errors="surrogateescape") for p in diff.stdout.split(b"\0") if p]
    relevant = [p for p in changed if p != cc.file and not any(glob_match(p, e) for e in cc.exclude)]
    base = [{"code": "R-58.range", "value": f"{tag}..HEAD", "message": f"{len(relevant)} relevant file(s) changed"}]
    show = git_run(ctx.root, "show", f"HEAD:{cc.file}", timeout=30)
    committed = _blob_state(ctx.root, "HEAD", cc.file)
    if committed == "unknown":  # R12 (0.12.0): git could not say whether it exists: never read as absent
        return [result("R-58", cc.file, Status.UNKNOWN, "git could not read HEAD's tree", [{"code": "R-58.unreadable"}])]
    committed = committed == "present"
    if show.returncode != 0 and committed:  # R12: present but unreadable is UNKNOWN, never an empty section
        return [result("R-58", cc.file, Status.UNKNOWN, "the committed changelog could not be read",
                       base + [{"code": "R-58.git_error"}])]
    entries = unreleased_entries(show.stdout.decode("utf-8", errors="replace")) if show.returncode == 0 else None
    problems = entry_format(entries or [], cc, ctx.final)  # Q18: always validated, also with nothing relevant
    if not relevant:
        if problems:
            return [result("R-58", cc.file, Status.FAIL, "Unreleased entries lack their fields, or are not ready", base + problems)]
        return [result("R-58", cc.file, Status.PASS, f"only excluded files changed since {tag}", base)]
    if show.returncode != 0:
        return [result("R-58", cc.file, Status.FAIL, "the changelog is not committed", base + [{"code": "R-58.no_changelog"}])]
    if not _bullets(entries):  # Q18: an entry is a bullet; other text does not count
        return [result("R-58", cc.file, Status.FAIL, f"files changed since {tag}, and the Unreleased section has "
                       + ("no section" if entries is None else "no entries"), base + [{"code": "R-58.no_entry"}])]
    old = git_run(ctx.root, "show", f"{tag}:{cc.file}", timeout=30)
    if old.returncode != 0 and _blob_state(ctx.root, tag, cc.file) != "absent":
        return [result("R-58", cc.file, Status.UNKNOWN, f"the changelog at {tag} could not be read",
                       base + [{"code": "R-58.git_error"}])]  # R12
    before = unreleased_entries(old.stdout.decode("utf-8", errors="replace")) if old.returncode == 0 else None
    if before is not None and _bullets(before) == _bullets(entries):  # Q18: the section itself must have changed
        return [result("R-58", cc.file, Status.FAIL, f"the Unreleased entries are unchanged since {tag}",
                       base + [{"code": "R-58.not_updated"}])]
    if problems:
        return [result("R-58", cc.file, Status.FAIL, "Unreleased entries lack their fields, or are not ready", base + problems)]
    return [result("R-58", cc.file, Status.PASS, f"the Unreleased section has {len(_bullets(entries))} entr(ies) for the "
                   f"changes since {tag}", base)]


# ---------------------------------------------------------------- R-59 branches.model (B6, REQ-009)
def tagged_commits(root: Path, pattern: str) -> set[str]:
    out = git_run(root, "for-each-ref", "refs/tags", "--format=%(objectname) %(*objectname) %(refname:short)",
                  text=True, timeout=30)
    commits: set[str] = set()
    for line in out.stdout.splitlines() if out.returncode == 0 else []:
        f = line.split()
        if len(f) == 3 and glob_match(f[2], pattern):
            commits.add(f[1])          # annotated: the commit it points at
        elif len(f) == 2 and glob_match(f[1], pattern):
            commits.add(f[0])          # lightweight
    return commits


def _branch_exists(root: Path, name: str) -> bool:
    return git_run(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}").returncode == 0


def r59(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    bc = ctx.config.branches
    if bc is None:
        return [result("R-59", ".", Status.NOT_APPLICABLE, "[branches] is not configured")]
    if git_run(ctx.root, "rev-parse", "--git-dir").returncode != 0:
        return [result("R-59", ".", Status.UNKNOWN, "not a git repository", [{"code": "R-59.no_git"}])]
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    tagged = tagged_commits(ctx.root, bc.tag_pattern)
    since = [f"^{bc.since}"] if bc.since else []
    if bc.since and git_run(ctx.root, "rev-parse", "--verify", "--quiet", f"{bc.since}^{{commit}}").returncode != 0:
        return [result("R-59", ".", Status.UNKNOWN, f"[branches] since = {bc.since!r} does not name a commit",
                       [{"code": "R-59.since_unknown"}])]
    if bc.release:
        if not _branch_exists(ctx.root, bc.release):
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-59.no_release_branch", "value": bc.release})
        else:
            out = git_run(ctx.root, "rev-list", "--first-parent", f"refs/heads/{bc.release}", *since, text=True, timeout=60)
            if out.returncode != 0:  # Q19
                causes.append(Status.UNKNOWN)
                details.append({"code": "R-59.history_unavailable", "value": bc.release})
            for c in out.stdout.split() if out.returncode == 0 else []:
                if c not in tagged and bc.release_tag_on == "merged-parent":  # REQ-018
                    par = git_run(ctx.root, "rev-list", "--parents", "-n", "1", c, text=True, timeout=30)
                    ps = par.stdout.split()[1:] if par.returncode == 0 else []
                    if len(ps) >= 2 and ps[1] in tagged:
                        continue
                if c not in tagged:
                    causes.append(Status.FAIL)
                    details.append({"code": "R-59.untagged_release_commit", "value": c[:12],
                                    "message": f"on {bc.release} without a tag matching {bc.tag_pattern}"
                                               + (" (on it or on its merged parent)" if bc.release_tag_on == "merged-parent" else "")})
    if bc.integration and bc.merge == "no-ff":
        if not _branch_exists(ctx.root, bc.integration):
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-59.no_integration_branch", "value": bc.integration})
        else:
            tag = _last_tag(ctx.root, bc.tag_pattern, f"refs/heads/{bc.integration}")
            if tag is None and not bc.since:
                causes.append(Status.UNKNOWN)
                details.append({"code": "R-59.no_tag", "message": f"no release tag on {bc.integration}: its merges are not checked"})
            else:
                lower = ([f"^{tag}"] if tag else []) + since  # DEF-029: both bounds; the later one applies
                out = git_run(ctx.root, "rev-list", "--first-parent", "--parents", f"refs/heads/{bc.integration}",
                              *lower, text=True, timeout=60)
                if out.returncode != 0:  # Q19
                    causes.append(Status.UNKNOWN)
                    details.append({"code": "R-59.history_unavailable", "value": bc.integration})
                for line in out.stdout.splitlines() if out.returncode == 0 else []:
                    f = line.split()
                    if len(f) == 2:  # one parent: a direct commit or a fast-forward, not a --no-ff merge
                        causes.append(Status.FAIL)
                        details.append({"code": "R-59.not_no_ff", "value": f[0][:12],
                                        "message": f"on {bc.integration} without a merge commit (merge task branches with --no-ff)"})
    if bc.task_patterns:
        out = git_run(ctx.root, "for-each-ref", "refs/heads", "--format=%(refname:short)", text=True, timeout=30)
        if out.returncode != 0:  # Q19
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-59.refs_unavailable"})
        fixed = {b for b in (bc.release, bc.integration) if b}
        if ctx.config.release is not None:
            fixed |= set(ctx.config.release.protected)
        for name in out.stdout.split():
            if name not in fixed and not any(glob_match(name, p) for p in bc.task_patterns):
                causes.append(Status.FAIL)
                details.append({"code": "R-59.branch_name", "value": name,
                                "message": f"matches none of {', '.join(bc.task_patterns)}"})
    for code in ("R-59.untagged_release_commit", "R-59.not_no_ff", "R-59.branch_name"):
        details = _cap(details, code)
    status = combine(causes)
    return [result("R-59", ".", status, _why(status, "the history follows the declared branch model",
                   "the history departs from the declared branch model", "the release or integration branch is missing",
                   "part of the history could not be checked"), details)]


def release_tip_tagged(root: Path, sha: str, pattern: str, on: str = "commit") -> bool:
    tagged = tagged_commits(root, pattern)
    if sha in tagged:
        return True
    if on == "merged-parent":  # REQ-018
        par = git_run(root, "rev-list", "--parents", "-n", "1", sha, text=True, timeout=30)
        ps = par.stdout.split()[1:] if par.returncode == 0 else []
        return len(ps) >= 2 and ps[1] in tagged
    return False


# ---------------------------------------------------------------- R-60 skills.copies (B7, REQ-014)
POINTER = "STEWARD_SKILLS"


def _tree(d: Path) -> dict[str, str]:
    """Regular files by content hash, and links by their target text (review Q20: a link is part of a copy)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        here = Path(dirpath)
        for name in sorted(dirnames + filenames):
            p = here / name
            rel = p.relative_to(d).as_posix()
            if p.is_symlink():
                out[rel] = "link:" + hashlib.sha256(os.readlink(p).encode()).hexdigest()
            elif p.is_file():
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def skills_copies(root: Path, sc: Any) -> tuple[bool, list[tuple[bool, dict[str, Any]]]]:
    """R-60's view of a [skills] table, shared with `steward skills list` (C8): whether the canonical directory is
    usable, and for each copy location (failed, detail)."""
    canon = root / sc.canonical
    if canon.is_symlink() or not canon.is_dir():
        return False, []
    out: list[tuple[bool, dict[str, Any]]] = []
    ref = _tree(canon)
    for c in sc.copies:
        p = root / c
        if p.is_symlink():
            if not p.exists():
                out.append((True, {"code": "R-60.dangling", "path": c}))
            elif p.resolve() != canon.resolve():
                out.append((True, {"code": "R-60.wrong_target", "path": c, "message": "links somewhere else"}))  # Q20
            else:
                out.append((False, {"code": "R-60.linked", "path": c}))
        elif (p / POINTER).is_file():
            target = (p / (p / POINTER).read_text(encoding="utf-8").strip()).resolve()
            if target != canon.resolve():
                out.append((True, {"code": "R-60.pointer_wrong", "path": f"{c}/{POINTER}"}))
            else:
                out.append((False, {"code": "R-60.pointer", "path": c}))
        elif p.is_dir():
            mine = _tree(p)
            differ = sorted(k for k in set(ref) | set(mine) if ref.get(k) != mine.get(k))
            if differ:
                out.append((True, {"code": "R-60.drift", "path": c, "value": len(differ),
                                   "message": "differs from the canonical copy: " + ", ".join(differ[:10])}))
            else:
                out.append((False, {"code": "R-60.copy", "path": c, "message": "an identical copy; a link avoids drift"}))
        else:
            out.append((True, {"code": "R-60.missing", "path": c}))
    return True, out


def r60(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    sc = ctx.config.skills
    if sc is None:
        return [result("R-60", ".", Status.NOT_APPLICABLE, "[skills] is not configured")]
    usable, copies = skills_copies(ctx.root, sc)
    if not usable:
        return [result("R-60", sc.canonical, Status.FAIL, "the canonical skills directory is missing or a link",
                       [{"code": "R-60.no_canonical", "path": sc.canonical}])]
    causes = [Status.FAIL for failed, _ in copies if failed]
    details = [d for _, d in copies]
    status = combine(causes)
    return [result("R-60", sc.canonical, status, _why(status, f"{len(sc.copies)} copy location(s) match the canonical "
                   "directory", "a skills copy is missing, dangling or has drifted"), details)]


# ---------------------------------------------------------------- R-52 repro.current (B2, REQ-008)
def r52(ctx: Ctx) -> list[Result]:
    from . import ledger as lg
    from . import repro as rp

    assert ctx.config is not None
    rc = ctx.config.repro
    if rc is None:
        return [result("R-52", ".", Status.NOT_APPLICABLE, "[repro] is not configured")]
    found = rp.contracts(ctx.root, ctx.config)
    if not found:
        return [result("R-52", ".", Status.NOT_APPLICABLE, "no reproduction contracts match [repro] contracts")]
    v = lg.verify(ctx.root / rc.ledger)
    if v.errors or v.torn_tail:  # Q13: a torn last record is not a clean prefix to trust
        return [result("R-52", rc.ledger, Status.FAIL, "the reproduction ledger is not intact",
                       [{"code": "R-52.ledger", **e} for e in v.errors] + ([{"code": "R-52.torn_tail"}] if v.torn_tail else []))]
    commit, tree = rp.git_ids(ctx.root)
    out: list[Result] = []
    for key, (rel, c, err) in sorted(found.items()):
        if c is None:
            out.append(result("R-52", rel, Status.FAIL, "the reproduction contract is invalid",
                              [{"code": "R-52.contract_invalid", "message": err}]))
            continue
        cur = {"contract_sha256": rp.sha_file(ctx.root / rel), "manifest_sha256": rp.sha_file(ctx.root / c.manifest)}
        if cur["manifest_sha256"] is None:
            out.append(result("R-52", rel, Status.INCOMPLETE, "the reference manifest is missing",
                              [{"code": "R-52.no_manifest", "path": c.manifest}]))
            continue
        mine = [e for e in v.entries if e.get("kind") == "repro" and e.get("id") == c.id]
        if tree is None:
            out.append(result("R-52", rel, Status.UNKNOWN, "no git commit: the current tree cannot be named",
                              [{"code": "R-52.no_git"}]))
            continue
        current = [e for e in mine if e.get("tree") == tree and all(e.get(k) == h for k, h in cur.items())]
        if not current:
            out.append(result("R-52", rel, Status.INCOMPLETE, f"{c.id}: no reproduction check on the current tree",
                              [{"code": "R-52.not_current", "value": tree[:12],
                                "message": f"run: steward repro check {c.id} --work DIR"}]))
            continue
        last = current[-1]
        try:
            n_files = len(rp.read_manifest(ctx.root, c))
        except (OSError, ValueError, rp.ReproError):
            n_files = 0
        if n_files == 0 or not isinstance(last.get("files"), int) or last["files"] < 1 or last.get("mismatch_count"):
            out.append(result("R-52", rel, Status.FAIL, f"{c.id}: the manifest or the recorded check compared no file",
                              [{"code": "R-52.no_files"}]))  # R9: zero-file evidence never certifies
            continue
        if last.get("result") != "pass":
            out.append(result("R-52", rel, Status.FAIL, f"{c.id}: the latest check on this tree failed",
                              [{"code": "R-52.failed", "value": last.get("mismatch_count"), "message": "seq "
                                + str(last.get("seq"))}]))
        else:
            out.append(result("R-52", rel, Status.PASS, f"{c.id}: re-derived outputs match the reference on this tree",
                              [{"code": "R-52.passed", "value": last.get("seq")}]))
    return out


# ---------------------------------------------------------------- R-54 exchange.inbox (C2)
def _today():
    """Today in UTC: the ledger's times are UTC, so a receipt made this evening (local) is never "in the future"."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


def r54(ctx: Ctx) -> list[Result]:
    """Received items stay as received, and get a decision within `[exchange] ack_days`. (Unacknowledged items and
    orphan responses are R-53's.)"""
    from datetime import date

    from . import exchange as xc

    assert ctx.config is not None
    xcfg = ctx.config.exchange
    if xcfg is None:
        return [result("R-54", ".", Status.NOT_APPLICABLE, "[exchange] is not configured")]
    inbox = xc.folder(ctx.root) / "inbox"
    if inbox.is_symlink() or not inbox.is_dir():
        return [result("R-54", xc.FOLDER, Status.NOT_APPLICABLE, "no exchange/inbox/ folder (R-53 reports the layout)")]
    from . import ledger as lg

    lp = xc.folder(ctx.root) / "log.jsonl"
    hist: dict[str, list[dict[str, Any]]] = {}
    if lp.is_file():
        v = lg.verify(lp)
        if v.errors or v.torn_tail:  # R10: a receipt verdict needs an intact ledger
            return [result("R-54", f"{xc.FOLDER}/inbox", Status.UNKNOWN, "the exchange ledger is not intact (R-53)",
                           [{"code": "R-54.ledger"}])]
        for e in v.entries:  # R10 (0.12.0): the verdict comes from this verified read, never from a second one
            if e.get("kind") == "state":
                hist.setdefault(e["item"], []).append(e)
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    entries = xc.items(ctx.root).get("inbox", [])
    verified, unverified = 0, []
    for rel, text in entries:
        iid = Path(rel).stem
        mine = hist.get(iid, [])
        try:
            is_response = xc.parse(text)[0].get("kind") == "response"
        except (ValueError, RecursionError):
            is_response = False
        rec = next((e["received"] for e in mine if isinstance(e.get("received"), dict)), None)
        if not rec or not isinstance(rec.get("sha256"), str):
            unverified.append(iid)  # Q14: received before receipts were recorded; said, never claimed
        elif rec["sha256"] != hashlib.sha256(ctx.read(rel)).hexdigest():
            causes.append(Status.FAIL)
            details.append({"code": "R-54.inbox_edited", "path": rel,
                            "message": "differs from the bytes received" + (f" from {rec['from']}" if rec.get("from") else "")})
        else:
            verified += 1
        # Q14: still awaiting a disposition; a received response is a decision already, with no clock (FB-017)
        if not is_response and xc.current(mine) in ("acknowledged", "verified", "not-reproduced"):
            ack = next((e for e in mine if e.get("state") == "acknowledged"), mine[-1])  # R10: the clock starts there
            when = (ack.get("time") or "")[:10]
            try:
                age = (_today() - date.fromisoformat(when)).days
            except ValueError:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-54.no_date", "value": iid, "message": "its last state has no readable date"})
                continue
            if age < 0:  # R10: a date in the future is not a clock
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-54.future_date", "value": iid})
                continue
            if age > xcfg.ack_days:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-54.no_decision", "value": iid,
                                "message": f"{xc.current(mine)} {age} days ago; decide it with steward exchange respond"})
    if unverified:
        details.append({"code": "R-54.receipt_unverified", "value": len(unverified),
                        "message": "no receipt hash recorded (received before 0.9.0): " + ", ".join(unverified[:LIST_MAX])})
    status = combine(causes)
    return [result("R-54", f"{xc.FOLDER}/inbox", status, _why(status, f"{verified} of {len(entries)} inbox item(s) match "
                   f"their receipts; decisions within {xcfg.ack_days} days", "an inbox item was edited after it was received",
                   "inbox items wait for a decision"), details)]


# ---------------------------------------------------------------- R-55 session.handoff (G3, advisory)
def r55(ctx: Ctx) -> list[Result]:
    from . import session as ss

    assert ctx.config is not None
    sc = ctx.config.session
    if sc is None:
        return [result("R-55", ".", Status.NOT_APPLICABLE, "[session] is not configured")]
    rel = sc.handoff
    if not (ctx.root / rel).is_file():
        return [result("R-55", rel, Status.INCOMPLETE, "no handoff yet; run steward session close",
                       [{"code": "R-55.missing", "path": rel}])]
    text = ctx.read(rel).decode("utf-8", errors="replace")
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    have = ss.sections(text)
    missing = [h for h in ss.HEADINGS if h not in have]
    if missing:
        causes.append(Status.FAIL)
        details.append({"code": "R-55.shape", "path": rel, "message": "missing: " + ", ".join(missing)})
    n = ss.words(text)
    if n > sc.budget_words:
        causes.append(Status.FAIL)
        details.append({"code": "R-55.over_budget", "path": rel, "value": n, "message": f"over {sc.budget_words} words"})
    hits = ss.privacy_hits(ctx.root, ctx.config, text, rel)
    if hits:
        causes.append(Status.FAIL)
        details.append({"code": "R-55.private", "path": rel, "message": ", ".join(hits)})
    log = ss.decisions_log(ctx.config)
    h = git_run(ctx.root, "log", "-1", "--format=%H", "--", rel, text=True)
    hc = h.stdout.strip() if h.returncode == 0 else ""
    if not hc:
        causes.append(Status.INCOMPLETE)
        details.append({"code": "R-55.uncommitted", "path": rel})
    else:
        if ss.uncommitted(ctx.root, [rel], set()):
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-55.uncommitted", "path": rel, "message": "changed since its last commit"})
        from . import integrity as ig

        for dlog in ig.decision_logs(ctx.root, ctx.config):  # R11: every decisions log, not only the first
            d = git_run(ctx.root, "log", "-1", "--format=%H", "--", dlog, text=True)
            dc = d.stdout.strip() if d.returncode == 0 else ""
            if dc and git_run(ctx.root, "merge-base", "--is-ancestor", dc, hc).returncode != 0:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-55.stale", "path": rel, "message": f"{dlog} changed after the handoff was committed"})
    details.append({"code": "R-55.words", "value": n, "message": f"{n} of {sc.budget_words} words"})
    status = combine(causes)
    return [result("R-55", rel, status, _why(status, "the handoff is current, within budget and well formed",
                   "the handoff is malformed, over budget or holds private text",
                   "the handoff is missing, uncommitted or older than the last decision"), details)]


# ---------------------------------------------------------------- R-61 files.conflict_markers (REQ-015)
CONFLICT_ALLOW = "steward: allow conflict-markers"


def conflict_lines(text: str) -> list[int]:
    """Line numbers of `<<<<<<<` that open a complete conflict (a lone `=======`, then `>>>>>>>`)."""
    found, start, middle = [], None, False
    for n, line in enumerate(text.splitlines(), start=1):
        if line == "<<<<<<<" or line.startswith("<<<<<<< "):
            start, middle = n, False
        elif start is not None and line == "=======":
            middle = True
        elif start is not None and middle and (line == ">>>>>>>" or line.startswith(">>>>>>> ")):
            found.append(start)
            start, middle = None, False
    return found


def r61(ctx: Ctx) -> list[Result]:
    """Every text file is scanned, streamed (no size limit; review Q21); a file is exempt only with the marker in its
    first five lines; an unreadable file is listed as not evaluated."""
    details: list[dict[str, Any]] = []
    scanned, unreadable = 0, []
    for rel in iter_repo_files(ctx.root):
        if rel.startswith(".steward/"):
            continue
        try:
            with open(ctx.root / rel, "rb") as f:
                head = f.read(8192)
                if b"\x00" in head:
                    continue
                f.seek(0)
                found, start, middle, exempt = [], None, False, False
                for n, raw in enumerate(f, start=1):
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if n <= 5 and CONFLICT_ALLOW in line:
                        exempt = True
                        break
                    if line == "<<<<<<<" or line.startswith("<<<<<<< "):
                        start, middle = n, False
                    elif start is not None and line == "=======":
                        middle = True
                    elif start is not None and middle and (line == ">>>>>>>" or line.startswith(">>>>>>> ")):
                        found.append(start)
                        start, middle = None, False
        except OSError:
            unreadable.append(rel)
            ctx.not_evaluated.append({"path": rel, "reason": "unreadable"})
            continue
        scanned += 1
        if not exempt:
            details += [{"code": "R-61.conflict_marker", "path": rel, "line": n} for n in found]
    extra = [{"code": "R-61.not_scanned", "value": len(unreadable), "message": "unreadable: " + ", ".join(unreadable[:LIST_MAX])}] \
        if unreadable else []
    if details:
        return [result("R-61", ".", Status.FAIL, f"unresolved merge-conflict markers in {len({d['path'] for d in details})} "
                       "file(s)", _cap(details, "R-61.conflict_marker") + extra)]
    if unreadable:
        return [result("R-61", ".", Status.UNKNOWN, f"{len(unreadable)} file(s) could not be read for conflict markers", extra)]
    return [result("R-61", ".", Status.PASS, f"no merge-conflict markers in {scanned} text file(s)")]


# ---------------------------------------------------------------- R-62 agents.ledger (REQ-016)
def agent_entries(entries: list[dict[str, Any]],
                  may_score: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Problems in an attribution ledger's entries: self-scores, scores of unknown attempts, silent overrides, and
    (X03, when `may_score` is set) a score by an agent the table does not let score that attempt's author."""
    attempts: dict[tuple[str, int], dict[str, Any]] = {}
    scored: set[tuple[str, int]] = set()
    out = []
    for e in entries:
        if e.get("kind") == "attempt":
            attempts[(e.get("task"), e.get("attempt"))] = e
        elif e.get("kind") == "score":
            key = (e.get("task"), e.get("attempt"))
            a = attempts.get(key)
            if a is None:
                out.append({"code": "R-62.unknown_attempt", "value": f"{key[0]}#{key[1]}", "seq": e.get("seq")})
            elif e.get("scorer") == a.get("agent"):
                out.append({"code": "R-62.self_scored", "value": f"{key[0]}#{key[1]}", "seq": e.get("seq"),
                            "message": f"scored by its author {a.get('agent')}"})
            elif may_score is not None and a.get("agent") not in may_score.get(str(e.get("scorer")), []):
                out.append({"code": "R-62.not_permitted", "value": f"{key[0]}#{key[1]}", "seq": e.get("seq"),
                            "message": f"{e.get('scorer')} may not score work by {a.get('agent')} "
                                       "([agents] may_score)"})
            if key in scored and not str(e.get("override") or "").strip():  # Q22: a blank reason is no reason
                out.append({"code": "R-62.silent_override", "value": f"{key[0]}#{key[1]}", "seq": e.get("seq"),
                            "message": "a later score needs an override reason"})
            scored.add(key)
    return out


def r62(ctx: Ctx) -> list[Result]:
    from . import ledger as lg

    assert ctx.config is not None
    ac = ctx.config.agents
    if ac is None:
        return [result("R-62", ".", Status.NOT_APPLICABLE, "[agents] is not configured")]
    p = ctx.root / ac.ledger
    if not p.is_file():
        return [result("R-62", ac.ledger, Status.NOT_APPLICABLE, "no attempts recorded yet")]
    v = lg.verify(p)
    if v.errors or v.torn_tail:  # Q22
        return [result("R-62", ac.ledger, Status.FAIL, "the attribution ledger was edited, or its last record is torn",
                       [{"code": "R-62.ledger", **e} for e in v.errors] + ([{"code": "R-62.torn_tail"}] if v.torn_tail else []))]
    problems = agent_entries(v.entries, ac.may_score)
    n = sum(1 for e in v.entries if e.get("kind") == "attempt")
    if problems:
        return [result("R-62", ac.ledger, Status.FAIL, "a score breaks the attribution rules", problems)]
    return [result("R-62", ac.ledger, Status.PASS, f"{n} attempt(s); every score by another agent"
                   + (" that [agents] may_score allows" if ac.may_score is not None else ""))]


# ---------------------------------------------------------------- staged gates (REQ-008): checks and R-68
def accrual_count(root: Path, rel: str) -> int | None:
    import json as _json

    p = root / rel
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8").strip()
    try:
        doc = _json.loads(text)
        n = doc.get("count") if isinstance(doc, dict) else doc
        return int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else None
    except ValueError:
        return int(text) if text.isdigit() else None


def stage_evidence(root: Path, cfg: Any, name: str) -> tuple[str | None, dict[str, Any]]:
    """(why the stage may not run, or None; the evidence read once: GO log and count). The launch record is made
    from this same evidence, so it can never be weaker than the check (review R13)."""
    from . import integrity as ig

    st = next((s for s in cfg.stages if s.name == name), None)
    ev: dict[str, Any] = {"go_log": None, "count": None}
    if st is not None and st.go:
        ev["go_log"] = ig.decision_heading(root, cfg, st.go)
    acc = cfg.accrual
    if st is not None and acc is not None and acc.stage == name:
        ev["count"] = accrual_count(root, acc.count_file)
    return _stage_why(root, cfg, name, ev), ev


def _stage_why(root: Path, cfg: Any, name: str, ev: dict[str, Any]) -> str | None:
    st = next((s for s in cfg.stages if s.name == name), None)
    if st is None:
        return f"no stage {name!r} in [[stages]]"
    if st.reads == "outcomes":
        if not st.go:
            return f"stage {name} reads outcomes and declares no `go` decision"
        if not ev["go_log"]:
            return f"stage {name} reads outcomes: its GO ({st.go!r}) is not a decisions-log entry heading"
    acc = cfg.accrual
    if acc is not None and acc.stage == name and (ev["count"] is None or ev["count"] < acc.minimum):
        return f"accrual: {ev['count'] if ev['count'] is not None else 'no'} unit(s) counted in {acc.count_file}, minimum {acc.minimum}"
    return None


def stage_refusal(root: Path, cfg: Any, name: str) -> str | None:
    """Why a stage may not run now, or None."""
    return stage_evidence(root, cfg, name)[0]


def _old_stage_refusal(root: Path, cfg: Any, name: str) -> str | None:
    from . import integrity as ig

    st = next((s for s in cfg.stages if s.name == name), None)
    if st is None:
        return f"no stage {name!r} in [[stages]]"
    if st.reads == "outcomes":
        if not st.go:
            return f"stage {name} reads outcomes and declares no `go` decision"
        if not ig.decision_heading(root, cfg, st.go):  # Q23: an entry heading, not a mention
            return f"stage {name} reads outcomes: its GO ({st.go!r}) is not a decisions-log entry heading"
    acc = cfg.accrual
    if acc is not None and acc.stage == name:
        n = accrual_count(root, acc.count_file)
        if n is None or n < acc.minimum:
            return f"accrual: {n if n is not None else 'no'} unit(s) counted in {acc.count_file}, minimum {acc.minimum}"
    return None


def r68(ctx: Ctx) -> list[Result]:
    from . import integrity as ig
    from . import ledger as lg

    assert ctx.config is not None
    cfg = ctx.config
    if not cfg.stages:
        return [result("R-68", ".", Status.NOT_APPLICABLE, "no [[stages]] declared")]
    p = ctx.root / cfg.stages_ledger
    if not p.is_file():
        return [result("R-68", cfg.stages_ledger, Status.NOT_APPLICABLE, "no stage has run yet")]
    v = lg.verify(p)
    if v.errors or v.torn_tail:  # Q22: a torn last record is not a valid record
        return [result("R-68", cfg.stages_ledger, Status.FAIL, "the stage ledger is not intact",
                       [{"code": "R-68.ledger", **e} for e in v.errors] + ([{"code": "R-68.torn_tail"}] if v.torn_tail else []))]
    launches = {e["seq"]: e for e in v.entries if e.get("kind") == "launch"}
    details = []
    runs = [e for e in v.entries if e.get("kind") == "stage"]
    declared = {s.name: s for s in cfg.stages}
    finished = {e.get("launch") for e in runs}
    for seq, start in launches.items():  # R13: a launch with no outcome is reported, unless it is the last record
        if seq not in finished and seq != v.entries[-1]["seq"]:
            details.append({"code": "R-68.unfinished", "value": seq, "message": f"stage {start.get('stage')} has no outcome"})
    for e in runs:
        start = launches.get(e.get("launch"))
        decl = declared.get(e.get("stage"))
        if start is None or start.get("stage") != e.get("stage") or start["seq"] >= e["seq"] or decl is None \
                or start.get("reads") != decl.reads or e.get("reads") != decl.reads:  # Q23, R13
            details.append({"code": "R-68.no_launch", "value": e.get("seq"),
                            "message": f"stage {e.get('stage')} has no launch record made before it ran"})
            continue
        if start.get("reads") == "outcomes" and not (start.get("go_log") and start.get("go")
                                                     and ig.decision_heading(ctx.root, cfg, start["go"])):
            details.append({"code": "R-68.no_go", "value": e.get("seq"), "message": f"stage {e.get('stage')} ran without its GO"})
        acc = cfg.accrual
        if acc is not None and acc.stage == e.get("stage") and (start.get("count") or 0) < acc.minimum:
            details.append({"code": "R-68.below_minimum", "value": e.get("seq"),
                            "message": f"{start.get('count')} < {acc.minimum} at launch"})
    if details:
        return [result("R-68", cfg.stages_ledger, Status.FAIL, "a stage ran without its GO, its launch record or the accrual minimum", details)]
    return [result("R-68", cfg.stages_ledger, Status.PASS, f"{len(runs)} stage run(s), each launched with its GO and accrual")]


# ---------------------------------------------------------------- R-63 frozen.sets (REQ-011)
def frozen_record_path(fs: Any) -> str:
    return fs.record or f"development/frozen/{fs.name}.json"


def frozen_hashes(root: Path, fs: Any) -> dict[str, str]:
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in iter_repo_files(root) if any(glob_match(rel, g) for g in fs.files)}


def r63(ctx: Ctx) -> list[Result]:
    import json as _json

    assert ctx.config is not None
    if not ctx.config.frozen:
        return [result("R-63", ".", Status.NOT_APPLICABLE, "no [[frozen]] sets declared")]
    out = []
    for fs in ctx.config.frozen:
        rel = frozen_record_path(fs)
        if not (ctx.root / rel).is_file():
            out.append(result("R-63", rel, Status.INCOMPLETE, f"{fs.name}: not recorded; run steward frozen record {fs.name}",
                              [{"code": "R-63.not_recorded"}]))
            continue
        try:
            doc = _json.loads(ctx.read(rel).decode("utf-8"))
        except (ValueError, RecursionError):
            doc = None
        rec = doc.get("files") if isinstance(doc, dict) else None
        if not isinstance(doc, dict) or doc.get("schema") != "steward.frozen/0.1" or doc.get("name") != fs.name \
                or not isinstance(rec, dict) or not rec:  # Q24
            out.append(result("R-63", rel, Status.FAIL, f"{fs.name}: the record is not a valid frozen record",
                              [{"code": "R-63.invalid"}]))
            continue
        now = frozen_hashes(ctx.root, fs)
        if not now:
            out.append(result("R-63", rel, Status.FAIL, f"{fs.name}: no file matches the set", [{"code": "R-63.no_files"}]))
            continue
        from . import integrity as ig

        recorded_again = False
        head = _head_state(ctx.root)
        if head == "unknown":  # R14 (0.12.0): git could not read HEAD; never "no history"
            out.append(result("R-63", rel, Status.UNKNOWN, f"{fs.name}: the repository's HEAD could not be read",
                              [{"code": "R-63.history_unavailable"}]))
            continue
        if head == "commit":  # history only when there is some
            n = git_run(ctx.root, "rev-list", "--count", "HEAD", "--", rel, text=True, timeout=30)
            d = git_run(ctx.root, "diff", "--quiet", "HEAD", "--", rel)
            if n.returncode != 0 or not n.stdout.strip().isdigit() or d.returncode not in (0, 1):  # R14
                out.append(result("R-63", rel, Status.UNKNOWN, f"{fs.name}: the record's history could not be read",
                                  [{"code": "R-63.history_unavailable"}]))
                continue
            count = int(n.stdout.strip())
            recorded_again = count > 1 or (count > 0 and d.returncode == 1)
        if recorded_again and not ig.decision_heading(ctx.root, ctx.config, doc.get("decision")):
            out.append(result("R-63", rel, Status.FAIL, f"{fs.name}: a new version without its decision heading",
                              [{"code": "R-63.no_decision"}]))
            continue
        differ = sorted(k for k in set(rec) | set(now) if rec.get(k) != now.get(k))
        if differ:
            out.append(result("R-63", rel, Status.FAIL, f"{fs.name}: {len(differ)} frozen file(s) changed, added or removed",
                              [{"code": "R-63.changed", "path": d} for d in differ[:LIST_MAX]]))
        else:
            out.append(result("R-63", rel, Status.PASS, f"{fs.name}: {len(now)} file(s) match the frozen record"))
    return out


# ---------------------------------------------------------------- R-66 dependencies.parity (REQ-012)
PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:==|===)\s*([^\s;#]+)")
PIN_GIT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*\S+@([^\s;#]+)")


def pins(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = PIN.match(line) or PIN_GIT.match(line)
        if m:
            out[_norm_dist(m.group(1))] = m.group(2)
    return out


def r66(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    dc = ctx.config.dependencies
    if dc is None:
        return [result("R-66", ".", Status.NOT_APPLICABLE, "[dependencies] is not configured")]
    tag = _last_tag(ctx.root, dc.tag_pattern)
    if tag is None:
        return [result("R-66", ".", Status.UNKNOWN, f"no release tag matching {dc.tag_pattern!r}: pin changes cannot be dated",
                       [{"code": "R-66.no_tag"}])]
    changes: list[tuple[str, str, str | None, str | None]] = []
    at_tag = git_run(ctx.root, "ls-tree", "-r", "--name-only", "-z", tag, timeout=30)
    if at_tag.returncode != 0:  # R16
        return [result("R-66", ".", Status.UNKNOWN, f"the tree at {tag} could not be listed", [{"code": "R-66.git_error"}])]
    tagged = [n for n in at_tag.stdout.decode("utf-8", errors="replace").split("\0") if n]
    candidates = sorted(set(iter_repo_files(ctx.root)) | set(tagged))  # Q27: a pin file removed since the tag counts
    for rel in candidates:
        if not any(glob_match(rel, g) for g in dc.pins):
            continue
        old = git_run(ctx.root, "show", f"{tag}:{rel}", timeout=30)
        if old.returncode != 0 and rel in tagged:  # R16: present at the tag but unreadable
            return [result("R-66", ".", Status.UNKNOWN, f"{rel} at {tag} could not be read", [{"code": "R-66.git_error"}])]
        before = pins(old.stdout.decode("utf-8", errors="replace")) if old.returncode == 0 else {}
        after = pins(ctx.read(rel).decode("utf-8", errors="replace")) if (ctx.root / rel).is_file() else {}
        for pkg in sorted(set(before) | set(after)):
            if before.get(pkg) != after.get(pkg):
                changes.append((rel, pkg, before.get(pkg), after.get(pkg) or "removed"))
    if not changes:
        return [result("R-66", ".", Status.PASS, f"no pinned version changed since {tag}")]
    recs = []
    for rel in iter_repo_files(ctx.root):
        if any(glob_match(rel, g) for g in dc.records):
            try:
                recs.append((rel, tomllib.loads(ctx.read(rel).decode("utf-8"))))
            except (ValueError, RecursionError, UnicodeDecodeError):
                recs.append((rel, {}))
    details, causes = [], []
    for pin_file, pkg, old_v, new_v in changes:
        rec = next((r for p, r in recs if r.get("schema") == "steward.upgrade/0.1"  # Q27: only real records
                    and _norm_dist(str(r.get("package", ""))) == pkg and r.get("new") == new_v
                    and r.get("old") == old_v), None)  # R16: the whole transition
        if rec is None:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-66.no_record", "path": pin_file, "value": pkg, "message": f"{old_v} -> {new_v}"})
            continue
        hs = rec.get("harnesses") or []
        bad = [h.get("name") or "(unnamed)" for h in hs if h.get("verdict") not in ("pass", "accepted")
               or not str(h.get("name") or "").strip()]
        missing = [k for k in ("old", "approval") if not rec.get(k)]
        if not hs or bad or missing or rec.get("old") != old_v:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-66.incomplete", "value": pkg, "message": "; ".join(filter(None, [
                "no harnesses" if not hs else "", f"not passed: {', '.join(map(str, bad))}" if bad else "",
                f"missing: {', '.join(missing)}" if missing else "",
                f"old {rec.get('old')} != {old_v}" if rec.get("old") != old_v and "old" not in missing else ""]))})
        else:
            details.append({"code": "R-66.record", "value": pkg, "message": f"{old_v} -> {new_v}: {len(hs)} harness(es)"})
    status = combine(causes)
    return [result("R-66", ".", status, _why(status, f"{len(changes)} pin change(s) since {tag}, each with a complete record",
                   "", incomplete="a pin changed without a complete parity record"), details)]


# ---------------------------------------------------------------- R-67 benchmark.power (REQ-010)
def r67(ctx: Ctx) -> list[Result]:
    import json as _json

    from . import power as pw

    out = []
    for rel in ctx.contract_files:
        c = ctx.contracts.get(rel)
        if c is None or c.minimum_units is None:
            continue
        prel = pw.record_path(rel)
        if not (ctx.root / prel).is_file():
            out.append(result("R-67", rel, Status.INCOMPLETE, f"minimum_units = {c.minimum_units}, and no power table",
                              [{"code": "R-67.no_power", "message": f"run: steward benchmark power {rel} --effects FILE"}]))
            continue
        try:
            rec = _json.loads(ctx.read(prel).decode("utf-8"))
        except (ValueError, RecursionError):
            out.append(result("R-67", prel, Status.FAIL, "the power table is not valid", [{"code": "R-67.invalid"}]))
            continue
        from .fsutil import escapes_root, inside

        if not isinstance(rec, dict) or rec.get("schema") != "steward.power/0.1":
            out.append(result("R-67", prel, Status.FAIL, "the power table is not valid", [{"code": "R-67.invalid"}]))
            continue
        eff = rec.get("effects") if isinstance(rec.get("effects"), str) else ""
        ok_path = bool(eff) and not escapes_root(eff) and inside(ctx.root, eff)  # R17: checked before it is read
        effects_now = pw.effects_sha(ctx.root / eff) if ok_path and (ctx.root / eff).is_file() else None
        if effects_now is None or effects_now != rec.get("effects_sha256"):
            out.append(result("R-67", prel, Status.INCOMPLETE, "the development effects changed since the power table",
                              [{"code": "R-67.stale"}]))  # R17: no path in the report
            continue
        import math

        shrinks = rec.get("shrinks")
        if rec.get("contract") != c.id or not isinstance(shrinks, list) or not shrinks or not all(
                isinstance(s, (int, float)) and not isinstance(s, bool) for s in shrinks):  # R17
            out.append(result("R-67", prel, Status.FAIL, "the power table is not this contract's (schema, contract or shrinks)",
                              [{"code": "R-67.invalid"}]))
            continue
        def _num(v: Any) -> bool:
            try:
                return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            except OverflowError:  # R17 (review of 0.12.0): a huge JSON integer is invalid, never an internal error
                return False

        table = rec.get("table")
        # R17 (0.12.0): every row is checked, at any size: an object with an integer n, a shrink and a probability
        if not isinstance(table, list) or any(
                not isinstance(r, dict) or not isinstance(r.get("n"), int) or isinstance(r.get("n"), bool)
                or not _num(r.get("shrink")) or not _num(r.get("power")) or not 0 <= r["power"] <= 1 for r in table):
            out.append(result("R-67", prel, Status.FAIL, "the power table has invalid rows", [{"code": "R-67.invalid_row"}]))
            continue
        rows = [r for r in table if r["n"] == c.minimum_units]
        bad: list[Any] = []
        missing = [s for s in rec["shrinks"] if not any(r.get("shrink") == s for r in rows)]
        if bad or (rows and missing):  # Q28: every declared shrink has a row with a probability
            out.append(result("R-67", prel, Status.FAIL, "the power table has invalid or missing rows",
                              [{"code": "R-67.invalid_row"}] * bool(bad) + [{"code": "R-67.missing_row", "value": s} for s in missing]))
            continue
        if not rows:
            out.append(result("R-67", prel, Status.INCOMPLETE, f"the table has no row for n = {c.minimum_units}",
                              [{"code": "R-67.no_row"}]))
            continue
        low = [r for r in rows if r["power"] < c.power_target]
        if low:
            out.append(result("R-67", prel, Status.INCOMPLETE, f"n = {c.minimum_units} is below the target power {c.power_target}",
                              [{"code": "R-67.underpowered", "message": f"shrink {r['shrink']}: power {r['power']}"} for r in low]))
        else:
            out.append(result("R-67", prel, Status.PASS, f"n = {c.minimum_units} reaches power {c.power_target} at every "
                              f"declared shrink ({rec.get('test')}, alpha {rec.get('alpha')})"))
    return out or [result("R-67", ".", Status.NOT_APPLICABLE, "no contract declares minimum_units")]


# ---------------------------------------------------------------- R-64, R-65 containers (REQ-003, 005)
def r64(ctx: Ctx) -> list[Result]:
    from . import containers as ct

    assert ctx.config is not None
    cc = ctx.config.containers
    if cc is None or not cc.contexts:
        return [result("R-64", ".", Status.NOT_APPLICABLE, "no [containers] contexts declared")]
    out = []
    for rel in cc.contexts:
        if not (ctx.root / rel).is_dir():
            out.append(result("R-64", rel, Status.INCOMPLETE, "the build context does not exist", [{"code": "R-64.missing"}]))
            continue
        f = ct.audit_context(ctx.root, rel, cc.dev_only, cc.max_unignored_mb)
        out.append(result("R-64", rel, Status.FAIL if f else Status.PASS,
                          f"{len(f)} hazard(s) in the build context" if f else "nothing dev-only, secret or oversized reaches the build",
                          f))
    return out


def r65(ctx: Ctx) -> list[Result]:
    from . import containers as ct

    assert ctx.config is not None
    cc = ctx.config.containers
    if cc is None or not (cc.compose or cc.ship_with_image):
        return [result("R-65", ".", Status.NOT_APPLICABLE, "no [containers] compose files or shipped paths declared")]
    try:
        import yaml  # noqa: F401
    except ImportError:
        return [result("R-65", ".", Status.UNKNOWN, "compose files need PyYAML: install the [containers] extra",
                       [{"code": "R-65.no_yaml"}])]
    try:
        f = ct.audit_compose(ctx.root, cc)
    except (OSError, ValueError, AttributeError) as e:
        return [result("R-65", ".", Status.UNKNOWN, f"a compose file cannot be read: {e}", [{"code": "R-65.unreadable"}])]
    except Exception as e:  # yaml.YAMLError
        return [result("R-65", ".", Status.UNKNOWN, f"a compose file is not valid YAML: {str(e)[:120]}", [{"code": "R-65.invalid"}])]
    if f:
        return [result("R-65", ".", Status.FAIL, f"{len(f)} compose / image parity problem(s)", f)]
    return [result("R-65", ".", Status.PASS, "every declared key, user-data volume and shipped path is in place")]


# ---------------------------------------------------------------- R-69 docs.current (0.11.0)
def r69(ctx: Ctx) -> list[Result]:
    from . import docreadme, docsite as ds

    assert ctx.config is not None
    dc = ctx.config.docs
    readme = docreadme.check(ctx.root, ctx.config)
    if readme and (dc is None or readme[0] is Status.FAIL):
        status, details = readme
        reason = {Status.PASS: "the generated README matches its records",
                  Status.INCOMPLETE: "the generated README is missing or stale",
                  Status.FAIL: "the generated README cannot be published"}[status]
        return [result("R-69", docreadme.README, status, reason, details)]
    if dc is None:
        return [result("R-69", ".", Status.NOT_APPLICABLE, "[docs] is not configured")]
    try:
        want = ds.build_pages(ctx.root, ctx.config)
    except ds.DocsError as e:
        return [result("R-69", dc.generated, Status.FAIL, "a page would publish a private term or a local path",
                       [{"code": "R-69.private", "message": str(e)[:300]}])]
    details = list(readme[1]) if readme else []
    from .fsutil import LinkRefused, open_dir_beneath

    try:  # T7: the generated folder is reached without links
        os.close(open_dir_beneath(ctx.root, tuple(Path(dc.generated).parts)))
    except LinkRefused:
        if (ctx.root / dc.generated).exists() or (ctx.root / dc.generated).is_symlink():
            return [result("R-69", dc.generated, Status.FAIL, "the generated folder is reached through a link",
                           [{"code": "R-69.link"}])]
    for rel in ds.retired(ctx.root, ctx.config, set(want)):  # T1
        details.append({"code": "R-69.retired", "path": rel, "message": "no longer published: steward docs build removes it"})
    for name, text in sorted(want.items()):
        rel = f"{dc.generated.rstrip('/')}/{name}"
        p = ctx.root / rel
        if p.is_symlink() or not p.is_file():
            details.append({"code": "R-69.missing", "path": rel})
            continue
        raw = ctx.read(rel)
        have = raw.decode("utf-8", errors="replace")
        if ds.scan(ctx.root, ctx.config, have):
            return [result("R-69", rel, Status.FAIL, "a generated page holds a private term or a local path",
                           [{"code": "R-69.private", "path": rel}])]
        if raw != text.encode("utf-8"):  # T12: byte-for-byte, never after lossy decoding
            details.append({"code": "R-69.stale", "path": rel, "message": "older than its records"})
    if details:
        reason = "the generated documentation is missing or stale" if readme else "the documentation site lags its records"
        return [result("R-69", dc.generated, Status.INCOMPLETE, reason, details)]
    suffix = ", including the README check" if readme else ""
    return [result("R-69", dc.generated, Status.PASS, f"{len(want)} generated page(s) match the records{suffix}")]


# ---------------------------------------------------------------- R-70 milestones.valid (0.13.0; advisory)
def r70(ctx: Ctx) -> list[Result]:
    from . import milestones as ms

    assert ctx.config is not None
    st, details = ms.check(ctx.root, ctx.config)
    status = Status[st]
    if status is Status.NOT_APPLICABLE:
        return [result("R-70", ms.FILE, status, "no milestones file")]
    return [result("R-70", ms.FILE, status, _why(status, "the milestones are valid and each past one has an outcome",
                   "the milestones file is invalid or names what does not exist", "a milestone is past due without an outcome"),
                   details)]


# ---------------------------------------------------------------- R-71 sprint.valid, R-72 sprint.closed (0.13.0)
def _sprint_files(ctx: Ctx) -> list[str]:
    from . import sprint as sp

    d = ctx.root / sp.DIR
    return sorted(p.relative_to(ctx.root).as_posix() for p in d.glob("*.toml")) if d.is_dir() else []


def r71(ctx: Ctx) -> list[Result]:
    from . import sprint as sp

    files = _sprint_files(ctx)
    if not files:
        return [result("R-71", sp.DIR, Status.NOT_APPLICABLE, "no sprints")]
    out = []
    for rel in files:
        sf, err = sp.validate_file(ctx.root / rel)
        if sf is None:
            out.append(result("R-71", rel, Status.FAIL, "the sprint file is not valid", [{"code": "R-71.invalid", "message": err}]))
            continue
        if sf.sprint.id != Path(rel).stem:
            out.append(result("R-71", rel, Status.FAIL, "the file name and the sprint id differ", [{"code": "R-71.id"}]))
            continue
        main = sp.main_checkout_ledger(ctx.root, sf.sprint.id)  # X05: in a task's worktree, the dispatcher's ledger
        where = " (the main checkout's ledger)" if main is not None else ""
        try:
            evs = sp.events(ctx.root, sf.sprint.id, at=main)
        except ValueError:
            out.append(result("R-71", rel, Status.FAIL, f"the sprint ledger is not intact{where}",
                              [{"code": "R-71.ledger"}]))
            continue
        bad = sp.ledger_findings(sf, evs)  # V15 (0.14.0)
        if bad:
            out.append(result("R-71", rel, Status.FAIL, f"the sprint ledger does not match its plan{where}", bad))
            continue
        out.append(result("R-71", rel, Status.PASS,
                          f"{len(sf.task)} task(s), ledger intact and bound to the plan{where}"))
    return out


def r72(ctx: Ctx) -> list[Result]:
    import datetime as _d

    from . import sprint as sp

    files = _sprint_files(ctx)
    out = []
    now = _d.datetime.now(_d.timezone.utc)
    for rel in files:
        sf, _ = sp.validate_file(ctx.root / rel)
        if sf is None or sf.sprint.window.end > now:
            continue
        details: list[dict[str, Any]] = []
        rp = ctx.root / sp.DIR / f"{sf.sprint.id}-report.md"
        try:
            st = sp.states(sf, sp.events(ctx.root, sf.sprint.id))
        except ValueError:
            continue  # R-71 reports the ledger
        if not rp.is_file() or rp.is_symlink():
            details.append({"code": "R-72.no_report", "message": f"run: steward sprint report {sf.sprint.id}"})
        elif rp.read_text(encoding="utf-8", errors="replace") != sp.report(ctx.root, sf):  # V15: the current report
            details.append({"code": "R-72.stale_report", "message": f"run: steward sprint report {sf.sprint.id}"})
        declared = {t.id: list(t.done) for t in sf.task}
        for tid, s in st.items():
            ran = {c.get("command"): c.get("exit") for c in (s.get("checks") or [])}
            if s["state"] == "done" and not (declared.get(tid) and all(ran.get(c) == 0 for c in declared[tid])):
                details.append({"code": "R-72.unchecked_done", "value": tid,
                                "message": "done without every declared done command recorded with exit 0"})
        status = Status.INCOMPLETE if details else Status.PASS
        out.append(result("R-72", rel, status, "the ended sprint is reported and its done tasks are checked"
                          if not details else "the ended sprint is not closed", details))
    return out or [result("R-72", sp.DIR, Status.NOT_APPLICABLE, "no ended sprint")]


# ---------------------------------------------------------------- R-73 pins.records, R-74 pins.retirement (0.17.0)
def r73(ctx: Ctx) -> list[Result]:
    from . import pins as pn

    assert ctx.config is not None
    if not ctx.config.pin:
        return [result("R-73", ".", Status.NOT_APPLICABLE, "no [[pin]] declared")]
    try:
        rows = pn.records(ctx.root, ctx.config)
    except pn.PinError as e:
        return [result("R-73", pn.settings(ctx.config).ledger, Status.UNKNOWN, str(e), [{"code": "R-73.ledger"}])]
    return [result("R-73", name, Status[st], why, [d] if d else []) for name, st, why, d in rows]


def r74(ctx: Ctx) -> list[Result]:
    from . import pins as pn

    assert ctx.config is not None
    if not ctx.config.pin:
        return [result("R-74", ".", Status.NOT_APPLICABLE, "no [[pin]] declared")]
    try:
        rows = pn.status(ctx.root, ctx.config)
    except pn.PinError as e:
        return [result("R-74", pn.settings(ctx.config).ledger, Status.UNKNOWN, str(e))]
    out = []
    for r in rows:
        if r["state"] in ("deprecated", "retire-eligible") and r.get("callers") is None:  # AA6 (0.17.0)
            out.append(result("R-74", r["name"], Status.UNKNOWN, "who uses it cannot be told",
                              [{"code": "R-74.callers_unavailable",
                                "message": "declare `module` or `references`; git and every file readable"}]))
        elif r["state"] in ("deprecated", "retire-eligible") and r.get("callers"):
            out.append(result("R-74", r["name"], Status.INCOMPLETE, "deprecated, and still used",
                              [{"code": "R-74.deprecated_in_use", "value": ", ".join(r["callers"][:5]),
                                "message": r["deprecated"]["reason"]}]))
        elif r["state"] == "retire-eligible":
            out.append(result("R-74", r["name"], Status.PASS, "eligible for retirement (a signed pin.retire approval retires it)",
                              [{"code": "R-74.eligible", "message": "; ".join(r["reasons"])}]))
        else:
            out.append(result("R-74", r["name"], Status.PASS, f"{r['state']}: {'; '.join(r['reasons'])[:160]}"))
    return out


# ---------------------------------------------------------------- 0.18.0 research records: R-75 – R-78
def r75(ctx: Ctx) -> list[Result]:
    """Study records: every recorded file present and unchanged; stale studies and papers; duplicates; consistency."""
    from . import records as rc

    assert ctx.config is not None
    if ctx.config.studies is None:
        return [result("R-75", ".", Status.NOT_APPLICABLE, "[studies] is not configured")]
    def observe(rel: str, sha: str) -> None:  # AE14: every file R-75 relied on is an input of the verdict
        ctx.inputs[rel] = sha
    def safe(rel: str) -> bytes:  # AE1, AE5: records read without links; their bytes are verdict inputs
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    rows = rc.check_studies(ctx.root, ctx.config, safe, observe)
    if not rows:
        return [result("R-75", ctx.config.studies.dir, Status.INCOMPLETE, "no study records yet (steward study new ID)",
                        [{"code": "R-75.none"}])]
    return [result("R-75", subj, Status[st], why, d) for subj, st, why, d in rows]


def r85(ctx: Ctx) -> list[Result]:
    """Data availability (0.20.0, B5): a paper's data-availability statement names every accession of the studies
    that list the paper."""
    from . import records as rc
    from .fsutil import matching_files

    assert ctx.config is not None
    if ctx.config.studies is None:
        return [result("R-85", ".", Status.NOT_APPLICABLE, "[studies] is not configured")]

    def safe(rel: str) -> bytes:
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    studies, _ = rc.load_studies(ctx.root, ctx.config, safe)
    need: dict[str, dict[str, list[str]]] = {}
    for sid, (_, st) in sorted(studies.items()):
        if st.status == "retired":
            continue
        for p in st.papers:
            for inp in st.inputs:
                if inp.accession:
                    need.setdefault(p, {}).setdefault(inp.accession, []).append(sid)
    need = {p: a for p, a in need.items() if p in ctx.config.paper}  # an unknown paper is R-75's finding
    if not need:
        return [result("R-85", ".", Status.NOT_APPLICABLE, "no study that a paper cites records an accession")]
    out = []
    for name, accs in sorted(need.items()):
        pp = ctx.config.paper[name]
        declared = None
        try:
            declared = tomllib.loads(safe(pp.rel(pp.spec)).decode("utf-8")).get("data_availability")
        except (rc.RecordRefused, ValueError, UnicodeDecodeError):
            pass
        text, where = None, None
        try:
            if isinstance(declared, str):
                where = pp.rel(declared)
                text = safe(where).decode("utf-8", "replace")
            else:
                for rel in matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]):
                    if rel.endswith((".tex", ".md", ".qmd", ".txt")):
                        found = rc.availability_text(safe(rel).decode("utf-8", "replace"))
                        if found is not None:
                            text, where = found, rel
                            break
        except rc.RecordRefused as e:
            out.append(result("R-85", where or pp.dir, Status.FAIL if e.reason != "missing" else Status.INCOMPLETE,
                              f"paper '{name}': the data-availability statement cannot be read ({e})",
                              [{"code": "R-85.refused", "path": where}]))
            continue
        if text is None:
            out.append(result("R-85", pp.rel(pp.main), Status.INCOMPLETE,
                              f"paper '{name}': no data-availability section (a 'Data availability' heading, or "
                              "data_availability = FILE in its spec)", [{"code": "R-85.no_statement",
                                                                         "value": ", ".join(sorted(accs))}]))
            continue
        missing = [a for a in sorted(accs) if not rc.accession_named(a, text)]
        if missing:
            out.append(result("R-85", where, Status.INCOMPLETE,
                              f"paper '{name}': the data-availability statement does not name {len(missing)} accession(s)",
                              [{"code": "R-85.accession_missing", "value": a, "path": where,
                                "message": f"used by {', '.join(accs[a])}"} for a in missing]))
        else:
            out.append(result("R-85", where, Status.PASS, f"paper '{name}': names all {len(accs)} accession(s)"))
    return out


def r76(ctx: Ctx) -> list[Result]:
    """Research-direction records (advisory): stale reviews, contributions without their nearest work, undecided
    gaps and dead ends."""
    from . import records as rc

    assert ctx.config is not None
    if ctx.config.research is None:
        return [result("R-76", ".", Status.NOT_APPLICABLE, "[research] is not configured")]
    def safe(rel: str) -> bytes:
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    rows = rc.check_research(ctx.root, ctx.config, rc.today_utc(), safe)
    if not rows:
        return [result("R-76", ctx.config.research.dir, Status.PASS, "no research records yet")]
    return [result("R-76", subj, Status[st], why, d) for subj, st, why, d in rows]


def r77(ctx: Ctx) -> list[Result]:
    """Citation verification (optional, per paper): every DOI or PMID the manuscript cites has a recorded title, and
    it is the cited title (AE4, AE9). LaTeX/BibTeX papers only, as R-14."""
    from . import records as rc
    from .fsutil import escapes_root

    assert ctx.config is not None
    papers = [(n, pp) for n, pp in sorted(ctx.config.paper.items()) if pp.citations]
    if not papers:
        return [result("R-77", ".", Status.NOT_APPLICABLE, "no paper declares a citations record")]

    def safe(rel: str) -> bytes:  # AE5: never outside, never through a link; recorded as a verdict input
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    out = []
    for name, pp in papers:
        rel = pp.rel(pp.citations)
        if pp.ext != ".tex":
            out.append(result("R-77", rel, Status.NOT_APPLICABLE, f"paper '{name}': citation records are LaTeX/BibTeX-only"))
            continue
        if escapes_root(rel):
            out.append(result("R-77", rel, Status.FAIL, f"paper '{name}': the citations record is outside the repository",
                              [{"code": "R-77.outside", "path": rel}]))
            continue
        try:
            cited, details, nkeys = rc.cited_entries(ctx.root, pp, safe)
        except rc.RecordRefused as e:
            out.append(result("R-77", rel, Status.FAIL, f"paper '{name}': a source cannot be read safely ({e})",
                              [{"code": "R-77.refused"}]))
            continue
        causes = [Status.INCOMPLETE if d["code"] == "R-77.no_bibliography" else Status.FAIL for d in details]
        recs: dict[str, Any] = {}
        try:
            cf = rc.CitationsFile.model_validate(tomllib.loads(safe(rel).decode("utf-8")))
            recs = {r.key: r for r in cf.citation}
        except rc.RecordRefused as e:
            missing = e.reason == "missing"
            causes.append(Status.INCOMPLETE if missing else Status.FAIL)
            details.append({"code": "R-77.no_record" if missing else "R-77.refused", "path": rel,
                            "message": f"no citations record yet (steward paper citations {name} --fetch)" if missing else str(e)})
        except Exception as e:  # noqa: BLE001
            causes.append(Status.FAIL)
            details.append({"code": "R-77.invalid", "path": rel, "message": str(e).splitlines()[0][:200]})
        checked = 0
        for brel, e, cid in cited:
            r = recs.get(e.key)
            if r is None or r.id.lower() != cid:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-77.unverified", "value": e.key, "path": brel, "line": e.line,
                                "message": f"{cid} has no verification record"})
                continue
            cited_t, rec_t = rc.norm_title(e.fields.get("title", "")), rc.norm_title(r.title)
            if not cited_t or not rec_t:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-77.no_title", "value": e.key, "path": brel, "line": e.line,
                                "message": "no title to compare (the entry's or the record's is empty)"})
                continue
            if cited_t != rec_t:
                causes.append(Status.FAIL)
                details.append({"code": "R-77.title_mismatch", "value": e.key, "path": brel, "line": e.line,
                                "message": f"{cid} resolves to {r.title!r}, not the cited title"})
                continue
            checked += 1
        status = combine(causes)
        out.append(result("R-77", rel, status, _why(status, f"paper '{name}': {checked} cited identifier(s) verified "
                                                  f"({nkeys} key(s) cited)",
                                                  f"paper '{name}': a cited identifier resolves to another title",
                                                  f"paper '{name}': citations without a usable verification record"), details))
    return out


def r78(ctx: Ctx) -> list[Result]:
    """Evaluating language models: groups apart, no self-judging, contamination by date, frozen prompts."""
    from . import records as rc
    from .models import Contract

    assert ctx.config is not None
    out = []
    for rel in sorted(__import__("steward.fsutil", fromlist=["matching_files"]).matching_files(ctx.root, ctx.config.paths.contracts)):
        try:
            c = Contract.model_validate(tomllib.loads(ctx.read(rel).decode("utf-8")))
        except Exception:  # noqa: BLE001 - an invalid contract is R-02's
            continue
        if c.llm_eval is None:
            continue

        def safe(rel: str) -> bytes:  # AE5: the cases file is read without links, and is a verdict input
            if rel not in ctx.snapshot:
                ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
            ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
            return ctx.snapshot[rel]
        state = None
        fs = next((f for f in ctx.config.frozen if f.name == c.llm_eval.prompts), None)
        if fs is not None:  # AE11: R-63's verdict on that set
            r = next((x for x in r63(ctx) if x.subject == frozen_record_path(fs)), None)
            state = (r.status.name, r.reason) if r is not None else None
        st, why, details = rc.check_llm_eval(ctx.root, ctx.config, c.llm_eval, safe, state)
        out.append(result("R-78", rel, Status[st], why, details))
    return out or [result("R-78", ".", Status.NOT_APPLICABLE, "no benchmark contract declares [llm_eval]")]


# ---------------------------------------------------------------- 0.19.0 licence governance: R-79 – R-82
def _licence_read(ctx: Ctx):
    from . import records as rc

    def safe(rel: str) -> bytes:  # never outside, never through a link; recorded as a verdict input
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = rc.read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    return safe


def r79(ctx: Ctx) -> list[Result]:
    """The declared licence is the one every declaration file states."""
    from . import licence as li

    assert ctx.config is not None
    lc = ctx.config.licence
    if lc is None:
        return [result("R-79", ".", Status.NOT_APPLICABLE, "[licence] is not configured")]
    try:
        li.parse_expr(lc.declared)
    except ValueError as e:
        return [result("R-79", "steward.toml", Status.FAIL, f"the declared licence is not an SPDX expression ({e})",
                       [{"code": "R-79.declared_invalid", "value": lc.declared}])]
    decl = li.declarations(ctx.root, _licence_read(ctx))
    details: list[dict[str, Any]] = []
    causes: list[Status] = []
    if not any(src.startswith(("LICENSE", "LICENCE", "COPYING")) for src, _ in decl):
        causes.append(Status.FAIL)
        details.append({"code": "R-79.no_licence_file", "message": "no LICENSE file"})
    for src, stated in decl:
        if stated is None:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-79.unreadable", "path": src, "message": "states no licence that can be identified"})
        elif not li.same_licence(stated, lc.declared):
            causes.append(Status.FAIL)
            details.append({"code": "R-79.mismatch", "path": src, "value": stated,
                            "message": f"states {stated}, not the declared {lc.declared}"})
    status = combine(causes)
    return [result("R-79", ".", status, _why(status, f"{lc.declared}, stated consistently in {len(decl)} file(s)",
                                              "a declaration file states another licence",
                                              "a declaration file states no identifiable licence"), details)]


def r80(ctx: Ctx) -> list[Result]:
    """Every dependency's licence is compatible with the policy for the distribution state; a public project keeps
    its third-party notices current."""
    from . import licence as li

    assert ctx.config is not None
    lc = ctx.config.licence
    if lc is None:
        return [result("R-80", ".", Status.NOT_APPLICABLE, "[licence] is not configured")]
    read = _licence_read(ctx)
    rows, problems = li.inventory(ctx.root, ctx.config, read)
    causes: list[Status] = [Status.UNKNOWN] * len(problems)
    details: list[dict[str, Any]] = [{"code": "R-80.inventory", "message": p} for p in problems]
    for r in rows:
        if r["status"] == "FAIL":
            causes.append(Status.FAIL)
            details.append({"code": "R-80.incompatible", "value": f"{r['name']} {r['version']}", "message": r["why"]})
        elif r["status"] == "UNKNOWN":
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-80.unknown", "value": f"{r['name']} {r['version']}", "message": r["why"]})
        elif r["status"] == "PASS_OBLIGATION":
            details.append({"code": "R-80.obligation", "value": f"{r['name']} {r['version']}", "message": r["why"]})
        elif r.get("exception"):
            details.append({"code": "R-80.exception", "value": r["name"], "message": r["why"]})
    for name in li.unmatched_use(ctx.config, rows):  # 0.22.0: a note, not a cause: nothing is judged by it
        details.append({"code": "R-80.use_unmatched", "value": name,
                        "message": "[licence] use names a package that is not in the inventory"})
    if lc.lockfile:  # name what a change to the lockfile added or upgraded (the pre-commit view)
        from .fsutil import git_run

        old = git_run(ctx.root, "show", f"HEAD:{lc.lockfile}", timeout=30)
        before = None
        if old.returncode == 0:
            try:  # AG3: an unreadable committed lock is a separate note, never an internal error
                before = dict(li.lock_packages(old.stdout.decode("utf-8", "replace"), lc.lockfile))
            except ValueError:
                details.append({"code": "R-80.baseline_unavailable", "message": "the committed lockfile cannot be read"})
        if before is not None:
            for r in rows:
                if before.get(r["name"]) != r["version"]:
                    details.append({"code": "R-80.changed", "value": f"{r['name']} {before.get(r['name'], '(new)')} → "
                                    f"{r['version']}", "message": f"licence {r['licence'] or 'UNKNOWN'}: {r['status']}"})
    if lc.distribution == "public":
        try:
            text = read(lc.notices).decode("utf-8", errors="replace")
            stale = li.notices_current(text, rows)
            if stale:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-80.notices_stale", "path": lc.notices, "value": len(stale),
                                "message": "not named in the notices: " + ", ".join(stale[:8]) + " (steward licence notices --write)"})
        except OSError:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-80.notices_missing", "path": lc.notices,
                            "message": "a public project keeps third-party notices (steward licence notices --write)"})
    details.append({"code": "R-80.scope", "message": li.LEGAL})
    status = combine(causes)
    return [result("R-80", lc.lockfile or "site-packages", status, _why(
        status, f"{len(rows)} dependency licence(s) compatible with the {lc.policy} policy ({lc.distribution})",
        "a dependency's licence is incompatible with the policy", "third-party notices are missing or stale",
        "a dependency's licence is unknown"), details)]


def _code_files(ctx: Ctx) -> list[str]:
    out = git_run(ctx.root, "ls-files", "-z")
    if out.returncode == 0:
        return sorted(f.decode("utf-8", "surrogateescape") for f in out.stdout.split(b"\0") if f)
    return list(iter_repo_files(ctx.root))


def r81(ctx: Ctx) -> list[Result]:
    """Copied, ported or translated code and bundled assets: declared, and compatible with the policy."""
    from . import licence as li

    assert ctx.config is not None
    lc = ctx.config.licence
    if lc is None:
        return [result("R-81", ".", Status.NOT_APPLICABLE, "[licence] is not configured")]
    def read(rel: str) -> bytes:
        try:
            return _licence_read(ctx)(rel)
        except OSError:
            raise
    findings, _ = li.code_findings(ctx.root, ctx.config, _code_files(ctx), read)
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    for f in findings:
        code = {"FAIL": "R-81.incompatible", "UNKNOWN": "R-81.unknown", "PASS_OBLIGATION": "R-81.obligation",
                "PASS": "R-81.declared"}[f["status"]]
        if f["status"] in ("FAIL", "UNKNOWN"):
            causes.append(Status[f["status"]])
        details.append({"code": code, "path": f["path"], "value": f["licence"], "message": f["why"]})
    status = combine(causes)
    return [result("R-81", lc.third_party or ".", status, _why(
        status, f"{len(findings)} declared third-party item(s) and licence header(s) compatible",
        "copied or ported code is under an incompatible licence", unknown="a declared licence is not one the policy knows"),
        details)]


def r82(ctx: Ctx) -> list[Result]:
    """Advisory: comments that suggest a port or copy nobody declared."""
    from . import licence as li

    assert ctx.config is not None
    lc = ctx.config.licence
    if lc is None:
        return [result("R-82", ".", Status.NOT_APPLICABLE, "[licence] is not configured")]
    _, hints = li.code_findings(ctx.root, ctx.config, _code_files(ctx), _licence_read(ctx))
    if not hints:
        return [result("R-82", ".", Status.PASS, "no undeclared port or copy markers in code comments")]
    return [result("R-82", ".", Status.INCOMPLETE, f"{len(hints)} comment(s) suggest copied or ported code: declare its "
                   "source in third_party, or confirm it is original", _cap([{"code": "R-82.hint", "path": h["path"],
                   "line": h["line"], "value": h["text"]} for h in hints], "R-82.hint"))]
