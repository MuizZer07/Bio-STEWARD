"""Session sign-off and resumption (0.9.0 G1 – G4; DESIGN_session_handoff, approved S1 – S5; constitution Article
VIII.2).

`steward session close` checks that the process records are committed, collects the open items by ID, and writes
one bounded handoff (`[session] handoff`, replaced at each close; history in git). It never copies a record and never
reads a transcript. `steward session start` prints the constitution version and that handoff, nothing else.
`--end` stops what the toolkit started for this repository and removes what it owns; ending or deleting the agent
session itself is the harness's, and the output says so.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from .fsutil import git_run

HEADINGS = ("State", "Next", "Open decisions", "Open items", "Working agreements", "Read first", "Signature")
OPEN_FINDING = ("open", "confirmed")
DONE_STATES = {"closed", "shipped", "adopted", "declined", "merged", "not-reproduced", "superseded", "withdrawn"}
LIST_MAX = 30


class SessionError(ValueError):
    pass


def decisions_log(cfg: Any) -> str:
    return cfg.integrity.primary_decisions if cfg.integrity else f"{cfg.paths.records.rstrip('/')}/DECISIONS.md"


def process_paths(root: Path, cfg: Any) -> list[str]:
    from .fsutil import glob_match, iter_repo_files

    sc = cfg.session
    paths = [cfg.paths.records.rstrip("/"), "exchange"]
    globs = [g for g in sc.process if any(c in g for c in "*?[")]
    paths += [g for g in sc.process if g not in globs]
    if globs:  # Q15, R11: globs expand over the working tree and HEAD's tree, so a deleted match still counts
        paths += [f for f in iter_repo_files(root) if any(glob_match(f, g) for g in globs)]
        ls = git_run(root, "ls-tree", "-r", "--name-only", "-z", "HEAD")
        if ls.returncode == 0:
            paths += [f for f in ls.stdout.decode("utf-8", errors="replace").split("\0") if f and any(glob_match(f, g) for g in globs)]
    tracked = git_run(root, "ls-files", "-z", "--", *paths) if paths else None
    known = set(tracked.stdout.decode("utf-8", errors="replace").split("\0")) if tracked and tracked.returncode == 0 else set()
    return [p for p in dict.fromkeys(paths) if (root / p).exists() or p in known or
            git_run(root, "cat-file", "-e", f"HEAD:{p}").returncode == 0]


def uncommitted(root: Path, paths: list[str], skip: set[str]) -> list[str]:
    """Tracked files under `paths` whose bytes differ from the index, and untracked ones. Hashes are compared with
    filters off (`hash-object --no-filters`), so no repository-configured program runs (red-team L1)."""
    if not paths:
        return []
    ls = git_run(root, "ls-files", "-s", "-z", "--", *paths)
    if ls.returncode != 0:
        raise SessionError("not a git repository: the process records cannot be checked")
    tracked: dict[str, str] = {}
    for rec in ls.stdout.split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            tracked[path.decode("utf-8", errors="surrogateescape")] = meta.split()[1].decode()
    changed = []
    present = [p for p in sorted(tracked) if (root / p).is_file() and not (root / p).is_symlink()]
    changed += [p for p in sorted(tracked) if p not in present]
    if present:
        h = git_run(root, "hash-object", "--no-filters", "--stdin-paths", input="\n".join(present).encode() + b"\n")
        shas = h.stdout.decode().split()
        if h.returncode != 0 or len(shas) != len(present):  # Q15: an incomplete answer is an error, never "clean"
            raise SessionError("git could not hash the process records")
        for p, sha in zip(present, shas):
            if tracked[p] != sha:
                changed.append(p)
    staged = git_run(root, "diff-index", "--cached", "--name-only", "-z", "HEAD", "--", *paths)  # index vs HEAD
    if staged.returncode == 0:
        changed += [p.decode("utf-8", errors="surrogateescape") for p in staged.stdout.split(b"\0") if p]
    elif git_run(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0:
        raise SessionError("git could not compare the index with HEAD")
    else:
        changed += sorted(tracked)  # no commit yet: nothing is committed
    others = git_run(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths)
    changed += [p.decode("utf-8", errors="surrogateescape") for p in others.stdout.split(b"\0") if p]
    # DEF-031: steward's own lock file beside a ledger is never a record. Repository ignore rules apply (through
    # --exclude-standard above); a user's personal global excludes do not, as they can hide real records (`*.md`).
    changed = [p for p in set(changed) if p in tracked or not (p.endswith(".jsonl.lock") or (  # U17: tracked always counts
        p.endswith(".lock") and (root / p[:-5]).is_file()))]
    return sorted(p for p in set(changed) if p not in skip)


def open_findings(root: Path, cfg: Any) -> list[str]:
    import tomllib

    rel = cfg.release.findings if cfg.release else f"{cfg.paths.records.rstrip('/')}/assessment/findings.toml"
    try:
        doc = tomllib.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return []
    return [f"{f.get('id')} ({f.get('severity')})" for f in doc.get("findings", []) if f.get("status") in OPEN_FINDING]


def open_exchange(root: Path, cfg: Any) -> list[str]:
    from . import exchange as xc

    if cfg.exchange is None or not xc.folder(root).is_dir():
        return []
    hist = xc.states(root)
    out = []
    for place, entries in xc.items(root).items():
        if place == "responses":
            continue
        for rel, _ in entries:
            iid = Path(rel).stem
            st = xc.current(hist.get(iid, []))
            if st not in DONE_STATES:
                out.append(f"{iid} ({st or 'no state'})")
    return sorted(out)


def _capped(items: list[str]) -> str:
    if not items:
        return "none"
    shown = ", ".join(items[:LIST_MAX])
    return shown + (f", and {len(items) - LIST_MAX} more" if len(items) > LIST_MAX else "")


def state_line(root: Path) -> tuple[str, str]:
    br = git_run(root, "rev-parse", "--abbrev-ref", "HEAD", text=True)
    head = git_run(root, "log", "-1", "--format=%h %s", text=True)
    return (br.stdout.strip() or "unknown") if br.returncode == 0 else "unknown", \
        (head.stdout.strip() or "none") if head.returncode == 0 else "none"


def project_version(root: Path, cfg: Any) -> str:
    import tomllib

    try:
        v = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("version")
    except (OSError, ValueError, RecursionError):
        v = None
    return v or "not declared"


def render(root: Path, cfg: Any, a: Any, dirty: list[str], end_report: list[str] | None) -> str:
    branch, head = state_line(root)
    log = decisions_log(cfg)
    sec: dict[str, list[str]] = {
        "State": [f"- {cfg.steward.project}, version {project_version(root, cfg)}, branch `{branch}`, last commit {head}.",
                  f"- Tests (as reported): {a.tests or 'not given'}.",
                  f"- Decisions: confirmed by the agent as recorded in `{log}`.",
                  f"- Uncommitted process records: {_capped(dirty)}."],
        "Next": [f"{i}. {n}" for i, n in enumerate(a.next, start=1)] or ["(none given)"],
        "Open decisions": [f"- {q}" for q in a.question] or ["- none"],
        "Open items": [f"- Findings: {_capped(open_findings(root, cfg))}.",
                       f"- Exchange: {_capped(open_exchange(root, cfg))}."],
        "Working agreements": [f"- {w}" for w in a.agreement] or ["- none recorded"],
        "Read first": [f"- `{p}`" for p in a.read_first] or ["- the links above"],
    }
    if end_report is not None:
        sec["Session end"] = [f"- {line}" for line in end_report]
    sec["Signature"] = [a.signature or f"{date.today().isoformat()} · session handoff · harness, provider and model "
                        "not given"]
    out = ["# Session handoff", "", "Written by `steward session close` (constitution Article VIII.2). It links to the "
           "records and copies none of them; earlier handoffs are in git history."]
    for h, lines in sec.items():
        out += ["", f"## {h}", *lines]
    return "\n".join(out) + "\n"


def sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = ""
        elif cur is not None:
            out[cur] += line + "\n"
    return out


def words(text: str) -> int:
    return len(text.split())


def privacy_hits(root: Path, cfg: Any, text: str, rel: str | None = None, preview: bool = False) -> list[str]:
    """Term-list and local-path hits in `text`. With `rel` (the file it is written to), each list applies as R-07
    applies it to that path: only where the path matches its `include` and neither its `exclude` nor its `allow`
    (DEF-032). Without `rel` (text printed to a terminal), every list applies. Local paths are always checked."""
    from . import privacy as pv
    from .fsutil import glob_match

    def scoped(src: Any) -> bool:
        return rel is None or (src.applies(rel) and not any(glob_match(rel, g) for g in src.allow))

    import hashlib

    terms = [t for s in pv.load(root, cfg) if s.state == "ok" and scoped(s) for t in s.terms]
    # U14 (0.13.0): the handoff's accepted occurrences apply as R-07 applies them to its path
    sha = "*" if preview else hashlib.sha256(text.encode("utf-8")).hexdigest() if rel else None  # U14 (0.15.0)
    found, _ = pv.scan_text(text, terms, True, rel=rel, sha=sha)
    return sorted({h["term"].label if h["kind"] == "term" else "local path" for h in found})


# ---------------------------------------------------------------- G4: ending the session for good
def _ours(pid: int, created: Any, words: tuple[str, ...]):
    """The process, when it is the one recorded (pid and exact start time) and its command line is steward's own
    (`words` all present); else None. A reused pid, or another program, is never returned (review of 0.9.0, Q4)."""
    import psutil

    if not isinstance(pid, int) or pid == os.getpid():
        return None
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - float(created)) > 0.01:
            return None
        argv = p.cmdline()
    except (psutil.Error, ValueError, TypeError):
        return None
    # R3 (0.12.0): whole arguments, not substrings: steward's module or executable, then the command word itself
    is_steward = any(a in ("steward.cli", "steward") or a.endswith(("/steward", "\\steward.exe")) for a in argv)
    return p if is_steward and all(w in argv for w in words if w != "steward") else None


def _holds(p: Any, lock: Any) -> bool | None:
    """True when the process has the lock file open (bound to the lock, not only to its record); None when the
    operating system does not say (R3)."""
    import psutil

    try:
        files = p.open_files()
    except (psutil.Error, OSError):
        return None
    for f in files:
        try:
            st = os.stat(f.path)
        except OSError:
            continue
        if (st.st_dev, st.st_ino) == tuple(lock):
            return True
    return False


def _stop(p: Any, grace: float = 5.0) -> bool:
    """TERM, then KILL, through psutil's handle: it refuses to signal a pid that now names another process. True only
    when the process is gone afterwards (R3: a failure is reported, never a success)."""
    import psutil

    try:
        p.terminate()
        p.wait(timeout=grace)
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        try:
            p.kill()
            p.wait(timeout=grace)
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.Error:
            return False
    except psutil.Error:
        return False


def end(root: Path, cfg: Any) -> list[str]:
    """Stop what the toolkit started for this repository and remove what it owns. A process is stopped only when
    its pid, exact start time and command line match the record; a ledger that is not intact stops nothing."""
    from .fsutil import LinkRefused, open_dir_beneath
    from .ledger import verify
    from .models import RunSection

    from .fsutil import held_owner_locks

    report: list[str] = []
    for name, rec in held_owner_locks(root):  # K1 (R3): a live ownership lock, then the identity, then the command line
        kind = "run" if name.startswith("run-") else "mcp" if name.startswith("mcp-") else None
        if kind is None:
            continue
        p = _ours(rec.get("pid"), rec.get("created"), ("steward", kind))
        what = f"{'run ' + name[4:] if kind == 'run' else 'the MCP server'} (pid {rec.get('pid')})"
        if p is None:
            continue
        held = _holds(p, rec.get("_lock", (-1, -1)))
        if held is not True:  # R3: the recorded process must hold the lock itself
            report.append(f"did not stop {what}: " + ("it does not hold its ownership lock" if held is False else
                          "the system does not show whether it holds its ownership lock; stop it yourself"))
            continue
        if _stop(p, grace=15.0 if kind == "run" else 5.0):  # steward run stops its job's tree first, then records it
            report.append(f"stopped {what}")
        else:
            report.append(f"could not stop {what}; stop it yourself")
    tmp = Path(tempfile.gettempdir()).resolve()
    wl = git_run(root, "worktree", "list", "--porcelain", text=True)
    for line in wl.stdout.splitlines() if wl.returncode == 0 else []:
        if not line.startswith("worktree "):
            continue
        p = Path(line[len("worktree "):])
        parent = p.parent
        # Q5: only a staged pre-push worktree in the system temporary folder, removed by git itself
        if p.name != "wt" or not parent.name.startswith("steward-push-") or parent.resolve().parent != tmp:
            continue
        try:  # R4 (0.12.0): owned by this repository, and the pre-push that staged it has ended
            own = json.loads((parent / "owner.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            own = {}
        if not isinstance(own, dict) or own.get("root") != str(root.resolve()) or _alive(own.get("pid")):
            report.append(f"left the staged worktree {parent.name}: " + (
                "its pre-push is still running" if isinstance(own, dict) and own.get("root") == str(root.resolve())
                else "it is not recorded as this repository's"))
            continue
        if git_run(root, "worktree", "remove", "--force", str(p)).returncode == 0:
            try:
                parent.rmdir()  # only when empty: nothing beside it is ever deleted
            except OSError:
                pass
            report.append(f"removed a staged pre-push worktree ({parent.name})")
        else:
            report.append(f"could not remove the staged worktree {parent.name}; run: git worktree prune")
    git_run(root, "worktree", "prune")
    try:  # K2 (R4): removed through the checked .steward descriptor; a link there is refused, never followed
        sfd = open_dir_beneath(root, (".steward",))
        try:
            cfd = open_dir_beneath(root, (".steward", "cache"))
            try:  # R4 (0.15.0): held while it is moved aside and compared
                ident = os.fstat(cfd)
                import secrets

                aside = f".cache.{secrets.token_hex(8)}.removing"
                os.rename("cache", aside, src_dir_fd=sfd, dst_dir_fd=sfd)
                st = os.stat(aside, dir_fd=sfd, follow_symlinks=False)
                if (st.st_dev, st.st_ino) == (ident.st_dev, ident.st_ino):
                    shutil.rmtree(aside, dir_fd=sfd)
                    report.append("removed .steward/cache/")
                else:  # R4 (0.17.0): never renamed back over a name another process may now use
                    report.append(f"left .steward/{aside} in place: it is not the cache that was checked")
            finally:
                os.close(cfd)
        except (LinkRefused, OSError):
            pass
        finally:
            os.close(sfd)
    except LinkRefused:
        pass  # absent, or reached through a link
    if not report:
        report.append("nothing of the toolkit's was running or cached")
    report.append("Bio-STEWARD cannot end or delete this agent session, its transcript or a provider's copy: "
                  + (getattr(cfg.session, "end_hint", None) or "use your agent harness's own session end and delete "
                     "command") + ".")
    return report


def _alive(pid: Any) -> bool:
    import psutil

    try:
        return isinstance(pid, int) and psutil.pid_exists(pid)
    except psutil.Error:
        return False


def hold_mcp_lock(root: Path) -> int | None:
    """This MCP server's ownership lock (K1): `--end` can stop it, and only it, while it runs."""
    from .fsutil import owner_lock

    return owner_lock(root, f"mcp-{os.getpid()}")


def handoff_commit(root: Path, rel: str) -> str | None:
    out = git_run(root, "log", "-1", "--format=%h %cs", "--", rel, text=True)
    return out.stdout.strip() or None if out.returncode == 0 else None

