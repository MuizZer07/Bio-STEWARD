"""Where the project stands and what is next (0.21.0; STW-048 C10, C12; C21).

- `steward next`: the resume pointer (the session handoff), the nearest milestone with what blocks it, what waits on
  the human, what waits on agents, and what needs tidying. Each item names its source record and one command.
- `steward tidy`: stale open tasks, statuses that contradict the records, stale state pages, exchange items not
  delivered or not received, merged sprint branches and worktrees, and memory entries in the folders a project
  declares under `[tidy] memory`. Read-only; `--archive ID…` moves the named task files, only when asked.
- `steward notifications`: one feed of what changed or waits: a newer CLI named by a release notice, new exchange
  items, sprint tasks finished, failed or waiting for an order, approvals waiting, a gate turned not eligible (against
  an earlier report), a milestone at risk or late. Each with an ID, a time, a kind, a source and its next command.
- R-88 (advisory): the counts of `steward tidy` in `steward check`, from the repository's records only.

Everything here is read from the project's own records (git, ledgers, the exchange folder, the signing queue). No
command here opens a network connection, and nothing is deleted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .fsutil import git_run

TOOLKIT_CODE = "STW"  # the exchange code of Bio-STEWARD itself: its release notices name a newer CLI
SETTLED = {"shipped", "adopted", "closed", "merged", "declined", "noted", "superseded", "withdrawn"}
UNDECIDED = {None, "filed", "acknowledged"}
VERSION = re.compile(r"(?<![\w.])v?(\d+)\.(\d+)\.(\d+)(?![\w.]*\d)")
MEMORY_MAX = 500  # entries read per memory folder


# ---------------------------------------------------------------- time
def parse_now(text: str | None) -> dt.datetime:
    """`--now`: an ISO 8601 time with its zone (`Z` accepted); without it, the current time."""
    if text is None:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("--now needs its time zone, e.g. 2027-01-20T12:00:00Z")
    return value.astimezone(dt.timezone.utc)


def iso(t: dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _day(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)


def _age(now: dt.datetime, t: dt.datetime | None) -> float | None:
    return None if t is None else round((now - t).total_seconds() / 86400, 1)


def _mtime(p: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).replace(microsecond=0)
    except OSError:
        return None


def thresholds(cfg: Any):
    from .models import TidySection

    return cfg.tidy if getattr(cfg, "tidy", None) is not None else TidySection()


# ---------------------------------------------------------------- git, read-only
class _Git:
    """The few git facts the cockpit reads, each asked once."""

    def __init__(self, root: Path):
        self.root = root
        r = git_run(root, "rev-parse", "--show-toplevel", text=True)
        self.ok = r.returncode == 0
        self._dirty: set[str] | None = None

    def commit_time(self, rel: str) -> dt.datetime | None:
        if not self.ok:
            return None
        r = git_run(self.root, "log", "-1", "--format=%ct", "--", rel, text=True)
        out = r.stdout.strip() if r.returncode == 0 else ""
        return dt.datetime.fromtimestamp(int(out), dt.timezone.utc) if out.isdigit() else None

    def dirty(self) -> set[str]:
        if self._dirty is None:
            self._dirty = set()
            if self.ok:
                r = git_run(self.root, "status", "--porcelain", "-z", "--untracked-files=all", "--", ".")
                for rec in r.stdout.decode("utf-8", errors="replace").split("\0") if r.returncode == 0 else []:
                    if len(rec) > 3:
                        self._dirty.add(rec[3:])
        return self._dirty

    def last_activity(self, rel: str) -> dt.datetime | None:
        """The last commit that touched the file; its modification time when it has uncommitted changes, is not
        committed, or the folder is not a git repository."""
        committed = self.commit_time(rel)
        if committed is None or rel in self.dirty():
            return _mtime(self.root / rel) or committed
        return committed

    def latest_tag(self) -> str | None:
        if not self.ok:
            return None
        r = git_run(self.root, "describe", "--tags", "--abbrev=0", "--match", "v*", text=True)
        return (r.stdout.strip() or None) if r.returncode == 0 else None

    def main_branch(self, cfg: Any) -> str | None:
        if not self.ok:
            return None
        br = getattr(cfg, "branches", None)
        for name in [b for b in (getattr(br, "integration", None), getattr(br, "release", None)) if b] + ["main", "master"]:
            if git_run(self.root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0:
                return name
        return None

    def merged(self, branch: str, into: str) -> bool:
        return self.ok and git_run(self.root, "merge-base", "--is-ancestor", f"refs/heads/{branch}",
                                   f"refs/heads/{into}").returncode == 0


def _version_key(text: str) -> tuple[int, int, int] | None:
    m = VERSION.fullmatch(text.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------- records
def board_tasks(root: Path, cfg: Any, *, use_default: bool = False) -> list[dict[str, Any]]:
    """The board's task files (R-57's reading): ID, path, status, closed or not, archived or not."""
    from .fsutil import glob_match, iter_repo_files
    from .process import ID_LINE, STATUS_LINE, _status

    tc = getattr(cfg, "tasks", None)
    if tc is None:
        if not use_default:
            return []
        from .models import TasksSection

        tc = TasksSection(specs=["development/tasks/**/*.md"], board="development/TASKS.md")
    out = []
    for rel in iter_repo_files(root):
        if rel == tc.board:
            continue
        archived = any(glob_match(rel, g) for g in tc.archive)
        if not (archived or any(glob_match(rel, g) for g in tc.specs)):
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        m, s = ID_LINE.search(text), STATUS_LINE.search(text)
        if not m:
            continue
        status = _status(s.group(1) if s else None, tc.statuses) or "(none)"
        out.append({"id": m.group(1), "path": rel, "status": status, "closed": status in tc.closed,
                    "archived": archived})
    return out


def last_changed(root: Path, paths: list[str]) -> dict[str, float]:
    """X05: each path's latest change: the time of the last commit that touched it, or now when it has changes git
    has not committed (or git is unavailable). One `git log` for all of them."""
    import subprocess
    import time

    from .fsutil import git_run

    now = time.time()
    if not paths:
        return {}
    out: dict[str, float] = {}
    folders = sorted({p.rsplit("/", 1)[0] if "/" in p else p for p in paths})
    try:
        dirty = git_run(root, "status", "--porcelain", "-z", "--", *folders, timeout=30)
        log = git_run(root, "log", "--format=%x01%ct", "--name-only", "--no-renames", "-z", "--", *folders,
                      timeout=60)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {p: now for p in paths}
    if log.returncode == 0:
        stamp = None
        for part in log.stdout.decode("utf-8", "replace").replace("\n", "\0").split("\0"):
            if part.startswith("\x01"):
                try:
                    stamp = float(part[1:])
                except ValueError:
                    stamp = None
            elif part and stamp is not None:
                out.setdefault(part, stamp)
    changed = set()
    if dirty.returncode == 0:
        changed = {entry[3:] for entry in dirty.stdout.decode("utf-8", "replace").split("\0") if len(entry) > 3}
    return {p: now if p in changed or p not in out else out[p] for p in paths}


def sprints(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Each valid sprint with its tasks' states and the time of each task's latest ledger event."""
    from . import sprint as sp

    out, notes = [], []
    d = root / sp.DIR
    for f in sorted(d.glob("*.toml")) if d.is_dir() else []:
        sf, _ = sp.validate_file(f)
        if sf is None:
            notes.append(f"sprint {f.stem}: its plan is not valid (steward sprint check {f.stem})")
            continue
        try:
            evs = sp.events(root, sf.sprint.id)
        except (ValueError, OSError):
            notes.append(f"sprint {sf.sprint.id}: its ledger is not intact or cannot be read")
            continue
        states = sp.states(sf, evs)
        times: dict[str, dt.datetime] = {}
        for e in evs:
            t = _parse_time(e.get("time"))
            if e.get("task") in states and t is not None:
                times[e["task"]] = t
        out.append({"sf": sf, "states": states, "times": times,
                    "ledger": sp.ledger_path(root, sf.sprint.id).relative_to(root).as_posix()})
    return out, notes


def _run_labels(root: Path, cfg: Any) -> dict[str, dt.datetime]:
    """Run label -> the time of its latest run ledger entry."""
    from .ledger import verify
    from .models import RunSection

    rel = (cfg.run or RunSection()).ledger
    p = root / rel
    if not p.is_file():
        return {}
    labels: dict[str, str] = {}
    out: dict[str, dt.datetime] = {}
    for e in verify(p).entries:
        if e.get("kind") == "started" and isinstance(e.get("label"), str):
            labels[str(e.get("run"))] = e["label"]
        label = labels.get(str(e.get("run")))
        t = _parse_time(e.get("time"))
        if label and t:
            out[label] = max(out.get(label, t), t)
    return out


def _inbox(root: Path, cfg: Any) -> tuple[list[tuple[str, Any, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]:
    """Valid inbox items: (rel, item, its ledger entries); and the whole state history."""
    from . import exchange as xc

    if cfg.exchange is None or not xc.folder(root).is_dir():
        return [], {}
    hist = xc.states(root)
    out = []
    for rel, text in xc.items(root).get("inbox", []):
        try:
            it = xc.Item.model_validate(xc.parse(text)[0])
        except Exception:  # noqa: BLE001 - an invalid item is R-53's to report
            continue
        if it.id == Path(rel).stem:
            out.append((rel, it, hist.get(it.id, [])))
    return out, hist


def _received_at(it: Any, entries: list[dict[str, Any]]) -> dt.datetime:
    for e in entries:
        if "received" in e and _parse_time(e.get("time")):
            return _parse_time(e["time"])  # type: ignore[return-value]
    return _day(it.filed)


def _handoff_rel(root: Path, cfg: Any) -> str | None:
    rel = cfg.session.handoff if cfg.session else f"{cfg.paths.records.rstrip('/')}/HANDOFF.md"
    return rel if (root / rel).is_file() else None


# ---------------------------------------------------------------- tidy (C12)
def _item(kind: str, iid: str, subject: str, message: str, age: float | None = None,
          command: str | None = None) -> dict[str, Any]:
    return {"id": f"{kind}:{iid}", "kind": kind, "subject": subject, "message": message, "age_days": age,
            "command": command}


KINDS = ("stale_task", "contradiction", "stale_page", "exchange", "leftover", "memory")


def tidy(root: Path, cfg: Any, now: dt.datetime, *, memory: bool = True, peers: bool = True) -> dict[str, Any]:
    """What looks stale, read-only. R-88 passes `memory=False` and `peers=False`: the memory folders and the peers'
    checkouts are outside the repository (R-53 already reports items not delivered)."""
    th = thresholds(cfg)
    git = _Git(root)
    items: list[dict[str, Any]] = []
    notes: list[str] = []
    tasks = board_tasks(root, cfg)
    sps, sp_notes = sprints(root)
    notes += sp_notes
    try:
        runs = _run_labels(root, cfg)
    except Exception:  # noqa: BLE001 - an unreadable run ledger is named, never a crash
        runs = {}
        notes.append("the run ledger cannot be read: runs are not counted as activity")
    by_ref: dict[str, list[tuple[str, str, dict[str, Any], dt.datetime | None]]] = {}
    for s in sps:
        for t in s["sf"].task:
            if t.ref:
                by_ref.setdefault(t.ref, []).append((s["sf"].sprint.id, t.id, s["states"][t.id], s["times"].get(t.id)))

    # stale open tasks, and board statuses the sprint ledger contradicts
    for t in tasks:
        if t["closed"] or t["archived"]:
            continue
        times = [git.last_activity(t["path"])] + [when for *_, when in by_ref.get(t["id"], [])]
        times += [when for label, when in runs.items() if re.search(rf"(?<![\w-]){re.escape(t['id'])}(?![\w-])", label)]
        last = max((x for x in times if x is not None), default=None)
        age = _age(now, last)
        if age is not None and age > th.stale_days:
            items.append(_item("stale_task", t["id"], t["path"], f"{t['status']}; untouched for {age:g} days",
                               age, f"steward tidy --archive {t['id']}"))
        for sid, tid, st, _ in by_ref.get(t["id"], []):
            if st["state"] == "done":
                items.append(_item("contradiction", t["id"], t["path"],
                                   f"the board says {t['status']}; sprint {sid} task {tid} is done",
                                   None, f"steward sprint report {sid}"))

    # stale state pages: the handoff's age, and a page naming no version as recent as the latest tag
    tag = git.latest_tag()
    pages = [(rel, name) for rel, name in ((_handoff_rel(root, cfg), "handoff"), (th.index, "index")) if rel]
    for rel, name in pages:
        if not (root / rel).is_file():
            continue
        age = _age(now, git.last_activity(rel))
        if name == "handoff" and age is not None and age > th.handoff_days:
            items.append(_item("stale_page", rel, rel, f"the handoff is {age:g} days old", age, "steward session close"))
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        named = [(int(a), int(b), int(c)) for a, b, c in VERSION.findall(text)]
        latest = _version_key(tag) if tag else None
        if latest and named and max(named) < latest:
            items.append(_item("stale_page", f"{rel}@{tag}", rel,
                               f"names {'.'.join(map(str, max(named)))} at most; the latest tag is {tag}", age,
                               "steward session close" if name == "handoff" else None))

    # exchange: own items answered but still open, unacknowledged, undelivered and unreceived items
    if cfg.exchange is not None:
        from . import exchange as xc

        inbox, hist = _inbox(root, cfg)
        answered = {it.responds_to for _, it, _ in inbox if it.kind == "response" and it.responds_to}
        for rel, text in xc.items(root).get("outbox", []):
            iid = Path(rel).stem
            try:
                kind = xc.parse(text)[0].get("kind")
            except (ValueError, RecursionError):
                continue
            if kind != "release" and iid in answered and xc.current(hist.get(iid, [])) not in SETTLED:
                items.append(_item("contradiction", iid, rel,
                                   f"open here ({xc.current(hist.get(iid, [])) or 'no state'}); its response is filed",
                                   None, f"steward exchange state {iid} closed"))
        for rel, it, entries in inbox:
            if not entries and (now.date() - it.filed).days > cfg.exchange.ack_days:
                items.append(_item("exchange", it.id, rel, f"received and not acknowledged for over "
                                   f"{cfg.exchange.ack_days} days", None, f"steward exchange state {it.id} acknowledged"))
        ds = None
        try:
            if peers:  # local peers only: a peer declared by URL stays unchecked
                ds = xc.delivery_status(root, cfg.exchange)
        except Exception:  # noqa: BLE001 - the exchange rules report a broken exchange; tidy names it
            notes.append("the exchange delivery could not be read (steward check governance)")
        for d in (ds.outgoing if ds else []):
            late = (now.date() - d.item.filed).days > cfg.exchange.delivery_days
            if late and d.state != "received" and d.item.kind != "response":
                items.append(_item("exchange", d.item.id, f"exchange/outbox/{d.item.id}.md",
                                   f"not received by {d.item.to} after {(now.date() - d.item.filed).days} days"
                                   + (" (its ledger could not be checked)" if d.state == "unchecked" else ""),
                                   None, "steward exchange status"))
        for d in (ds.incoming if ds else []):
            if d.state == "waiting":
                items.append(_item("exchange", d.item.id, f"{d.item.from_} outbox",
                                   f"in {d.item.from_}'s committed outbox, not received here", None,
                                   f"steward exchange pull {d.item.from_}"))
        for peer in sorted(ds.unavailable if ds else []):
            notes.append(f"exchange peer {peer}: not checked (a peer declared by URL is read only with "
                         "`steward exchange status --fetch`)")

    # leftovers: sprint branches already merged, and their worktrees
    main = git.main_branch(cfg)
    if main:
        r = git_run(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/sprint/", text=True)
        head = git_run(root, "symbolic-ref", "--quiet", "--short", "HEAD", text=True).stdout.strip()
        tip = git_run(root, "rev-parse", f"refs/heads/{main}", text=True).stdout.strip()
        # a branch still at main's tip has no work of its own yet (a task about to start), and the branch checked out
        # here is in use: neither is a leftover
        merged = [b for b in r.stdout.split() if b not in (main, head) and git.merged(b, main)
                  and git_run(root, "rev-parse", f"refs/heads/{b}", text=True).stdout.strip() != tip] \
            if r.returncode == 0 else []
        wt = git_run(root, "worktree", "list", "--porcelain", text=True)
        trees: dict[str, str] = {}
        cur = None
        for line in wt.stdout.splitlines() if wt.returncode == 0 else []:
            if line.startswith("worktree "):
                cur = line[len("worktree "):]
            elif line.startswith("branch refs/heads/") and cur:
                trees[line[len("branch refs/heads/"):]] = cur
        for b in merged:
            if b in trees:
                shown = _shown_path(root, Path(trees[b]))
                items.append(_item("leftover", f"worktree:{b}", shown, f"worktree of {b}, merged into {main}", None,
                                   f"git worktree remove {shown}"))
            items.append(_item("leftover", f"branch:{b}", b, f"merged into {main}", None, f"git branch -d {b}"))

    # memory folders a harness keeps for this project (outside the repository; read, never changed)
    folders = [_expand(root, f) for f in th.memory]
    if memory:
        for folder in folders:
            items += _memory(root, folder, now, th.memory_days, notes)
    items.sort(key=lambda i: (KINDS.index(i["kind"]), not i["id"].startswith("leftover:worktree:"), i["id"]))  # a
    # worktree is removed before its branch can be deleted
    counts = {k: sum(1 for i in items if i["kind"] == k) for k in KINDS}
    return {"now": iso(now), "thresholds": {"stale_days": th.stale_days, "handoff_days": th.handoff_days,
                                            "memory_days": th.memory_days, "archive": th.archive,
                                            "memory_folders": len(folders)},
            "items": items, "counts": counts, "total": len(items), "notes": notes}


def _expand(root: Path, folder: str) -> Path:
    p = Path(os.path.expanduser(folder))
    return p if p.is_absolute() else root / p


def _shown_path(root: Path, p: Path) -> str:
    from .cleanup import tilde

    try:
        return p.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return tilde(str(p))


BACKTICK = re.compile(r"`([^`\s]+)`")


def _memory(root: Path, folder: Path, now: dt.datetime, days: int, notes: list[str]) -> list[dict[str, Any]]:
    shown = _shown_path(root, folder)
    if not folder.is_dir() or folder.is_symlink():
        notes.append(f"memory folder {shown}: not found")
        return []
    out: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    tops = {p.name for p in root.iterdir()}
    files = sorted(p for p in folder.rglob("*.md") if p.is_file() and not p.is_symlink())
    if len(files) > MEMORY_MAX:
        notes.append(f"memory folder {shown}: {len(files)} entries; the first {MEMORY_MAX} were read")
    for p in files[:MEMORY_MAX]:
        name = _shown_path(root, p)
        age = _age(now, _mtime(p))
        if age is not None and age > days:
            out.append(_item("memory", f"{name}:old", name, f"not changed for {age:g} days", age))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        missing = sorted({t for t in BACKTICK.findall(text) if "/" in t and not t.startswith(("/", "~", "http"))
                          and t.split("/")[0] in tops and not (root / t.rstrip("/")).exists()})
        if missing:
            out.append(_item("memory", f"{name}:paths", name, "names paths that no longer exist here: "
                             + ", ".join(missing[:5]) + (f", and {len(missing) - 5} more" if len(missing) > 5 else "")))
        body = text.split("---", 2)[2] if text.startswith("---") and text.count("---") >= 2 else text
        digest = hashlib.sha256(" ".join(body.split()).encode()).hexdigest()
        if digest in seen:
            out.append(_item("memory", f"{name}:duplicate", name, f"the same text as {seen[digest]}"))
        else:
            seen[digest] = name
    return out


def render_tidy(doc: dict[str, Any]) -> str:
    if not doc["items"]:
        lines = ["Nothing to tidy."]
    else:
        lines = [f"Needs tidying ({doc['total']}): " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in
                                                                 doc["counts"].items() if n)]
        for i in doc["items"]:
            lines.append(f"  {i['kind']:<13} {i['subject']}: {i['message']}" + (f"  -> {i['command']}" if i["command"] else ""))
        lines.append("Nothing was changed. Archive a task only when its owner agrees (steward tidy --archive ID); "
                     "memory folders belong to the harness: clean them there.")
    lines += [f"note: {n}" for n in doc["notes"]]
    return "\n".join(lines)


class ArchiveError(ValueError):
    pass


def archive(root: Path, cfg: Any, ids: list[str]) -> list[tuple[str, str]]:
    """Move the named open task files into `[tidy] archive` (one change, ready to commit). Nothing else."""
    from .fsutil import glob_match

    th = thresholds(cfg)
    if getattr(cfg, "tasks", None) is None:
        raise ArchiveError("no [tasks] board is configured")
    dest_dir = root / th.archive
    for parent in [dest_dir, *dest_dir.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ArchiveError(f"{th.archive} is reached through a link; nothing was moved")
    tasks = {t["id"]: t for t in board_tasks(root, cfg)}
    moves = []
    if len(set(ids)) != len(ids):  # W12 F13: checked before any move, so a repeated ID never moves half the set
        raise ArchiveError(f"an ID is named twice ({next(i for i in ids if ids.count(i) > 1)}); nothing was moved")
    for iid in ids:
        t = tasks.get(iid)
        if t is None:
            raise ArchiveError(f"no task file has ID {iid}; nothing was moved")
        if t["archived"]:
            raise ArchiveError(f"{iid} is already archived ({t['path']}); nothing was moved")
        dest = f"{th.archive.rstrip('/')}/{Path(t['path']).name}"
        if (root / dest).exists() or (root / t["path"]).is_symlink():
            raise ArchiveError(f"{dest} exists, or {t['path']} is a link; nothing was moved")
        if any(d == dest for _, d in moves):  # W12 F13: two files of the same name in different folders
            raise ArchiveError(f"two of the named tasks would both move to {dest}; nothing was moved")
        moves.append((t["path"], dest))
    git = _Git(root)
    for src, dest in moves:
        (root / dest).parent.mkdir(parents=True, exist_ok=True)
        tracked = git.ok and git_run(root, "ls-files", "--error-unmatch", "--", src).returncode == 0
        if tracked:
            r = git_run(root, "mv", "--", src, dest, text=True)
            if r.returncode != 0:
                raise ArchiveError(f"git mv {src} failed: {r.stderr.strip()[:200]}")
        else:
            os.rename(root / src, root / dest)
    unseen = [d for _, d in moves if not any(glob_match(d, g) for g in cfg.tasks.archive)]
    if unseen:
        raise ArchiveError(f"moved, but [tasks] archive does not match {unseen[0]}: add \"{th.archive}/**\" to it")
    return moves


# ---------------------------------------------------------------- R-88 (advisory)
def r88(ctx: Any) -> list:
    from .rules import result
    from .status import Status

    cfg = ctx.config
    if cfg is None or cfg.tidy is None:
        return [result("R-88", ".", Status.NOT_APPLICABLE, "[tidy] is not configured")]
    doc = tidy(ctx.root, cfg, parse_now(None), memory=False, peers=False)
    from . import sprint as sp

    read = [t["path"] for t in board_tasks(ctx.root, cfg)] + [r for r in (_handoff_rel(ctx.root, cfg), cfg.tidy.index) if r]
    read += [p.relative_to(ctx.root).as_posix() for d in (sp.DIR, "exchange") if (ctx.root / d).is_dir()
             for p in sorted((ctx.root / d).rglob("*")) if p.is_file() and not p.is_symlink() and not p.name.endswith(".lock")]
    for rel in read:  # recorded, so `check --digest-only` sees a change to what this rule read
        if (ctx.root / rel).is_file():
            ctx.read(rel)
    if not doc["items"]:
        return [result("R-88", ".", Status.PASS, "nothing to tidy in the records")]
    details = [{"code": f"R-88.{i['kind']}", "value": i["id"].split(":", 1)[1], "message": i["message"],
                **({"path": i["subject"]} if (ctx.root / i["subject"]).is_file() else {})} for i in doc["items"]]
    counts = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in doc["counts"].items() if n)
    return [result("R-88", ".", Status.INCOMPLETE, f"needs tidying: {counts} (steward tidy)", details)]


# ---------------------------------------------------------------- next (C10)
def _entry(kind: str, iid: str, title: str, source: str, command: str, time: dt.datetime | None = None) -> dict[str, Any]:
    return {"kind": kind, "id": iid, "title": title, "source": source, "command": command, "time": iso(time)}


def _resume(root: Path, cfg: Any, now: dt.datetime, git: _Git) -> dict[str, Any] | None:
    from . import session as ss

    rel = _handoff_rel(root, cfg)
    if rel is None:
        return None
    sec = ss.sections((root / rel).read_text(encoding="utf-8", errors="replace"))

    def bullets(name: str) -> list[str]:
        out = []
        for line in sec.get(name, "").splitlines():
            m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*\S)", line)
            if m and m.group(1).lower() not in ("none", "(none given)"):
                out.append(m.group(1))
        return out
    return {"path": rel, "age_days": _age(now, git.last_activity(rel)), "committed": git.commit_time(rel) is not None,
            "next": bullets("Next"), "open_decisions": bullets("Open decisions"), "command": "steward session start"}


def _milestone(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    row = next((r for r in rows if "outcome" not in r), None)
    if row is None:
        return None
    p, blockers = row["progress"], []
    g = p.get("gate") or {}
    if g and not g.get("eligible", False):
        for b in g.get("blocking", []) or ([g["error"]] if "error" in g else []):
            blockers.append({"kind": "rule", "id": str(b), "command": f"steward explain {b}" if str(b).startswith("R-")
                             else f"steward check --summary --gate {g['name']}"})
    t = p.get("tasks") or {}
    blockers += [{"kind": "task", "id": i, "command": "steward timeline"} for i in t.get("open", [])]
    i = p.get("items") or {}
    blockers += [{"kind": "exchange", "id": x, "command": "steward exchange status"} for x in i.get("waiting", [])]
    s = p.get("signatures") or {}
    blockers += [{"kind": "signature", "id": x, "command": "steward authorize sign-pending"} for x in s.get("waiting", [])]
    return {"id": row["id"], "title": row["title"], "kind": row["kind"], "due": row["due"], "days_left": row["days_left"],
            "state": row["state"], "open_work": row["open_work"], "blockers": blockers, "command": "steward timeline"}


def _waiting_since(s: dict[str, Any], t: Any) -> dt.datetime:
    """When a task became ready: its last dependency's latest event, else the sprint window's start."""
    deps = [s["times"][a] for a in t.after if a in s["times"]]
    return max(deps) if deps else s["sf"].sprint.window.start


def _exchange_command(it: Any) -> str:
    if it.kind == "release":
        return f"steward exchange state {it.id} adopted --note {it.version or 'VERSION'}"
    if it.kind == "response":
        return f"steward exchange state {it.id} noted"
    return f"steward exchange respond {it.id} STATE --note \"…\""


def next_doc(root: Path, cfg: Any, now: dt.datetime) -> dict[str, Any]:
    from . import authorize as az
    from . import milestones as ms

    git = _Git(root)
    notes: list[str] = []
    resume = _resume(root, cfg, now, git)
    milestone = _milestone(ms.timeline(root, cfg, now=now))
    human: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    for q in az.pending(root, now=now, repo_id=cfg.steward.repo_id):  # W12 F1: a foreign payload is not waiting
        if q["state"] == "waiting":
            human.append(_entry("signature", q["nonce"], f"{q['action']} (scope {q.get('scope', '-')}, expires "
                                f"{q['expires']})", q["path"], "steward authorize sign-pending", _mtime(root / q["path"])))
    for d in (resume or {}).get("open_decisions", []):
        human.append(_entry("decision", hashlib.sha256(d.encode()).hexdigest()[:12], d, resume["path"],
                            "steward session start"))
    inbox, _ = _inbox(root, cfg)
    for rel, it, entries in inbox:
        st = entries[-1]["state"] if entries else None
        if st in UNDECIDED:
            human.append(_entry("exchange", it.id, f"{it.kind} from {it.from_}: {it.title}", rel, _exchange_command(it),
                                _received_at(it, entries)))
    sps, notes_ = sprints(root)
    notes += notes_
    main = git.main_branch(cfg)
    for s in sps:
        sf, sid = s["sf"], s["sf"].sprint.id
        for t in sf.task:
            st, when = s["states"][t.id], s["times"].get(t.id)
            label = f"sprint {sid} task {t.id}: {t.title}"
            if st["state"] in ("running", "checking"):
                agents.append(_entry("task_running", f"{sid}/{t.id}", f"{label} ({st['state']}, agent {t.agent})",
                                     s["ledger"], f"steward sprint status {sid}", when))
            elif st["state"] == "ready" and st["go"]:
                agents.append(_entry("task_ordered", f"{sid}/{t.id}", f"{label} (ordered, not started)", s["ledger"],
                                     f"steward sprint start {sid}", when))
            elif st["state"] == "ready" and sf.sprint.dispatch == "order" and not st["hold"] and sf.sprint.window.end >= now:
                human.append(_entry("task_waiting", f"{sid}/{t.id}", f"{label} waits for an order", s["ledger"],
                                    f"steward sprint go {sid} {t.id}", when or _waiting_since(s, t)))
            elif st["state"] == "failed":
                human.append(_entry("task_failed", f"{sid}/{t.id}", f"{label} failed" + (f": {st['note']}" if st.get("note") else ""),
                                    s["ledger"], f"steward sprint go {sid} {t.id} --retry", when))
            elif st["state"] == "done" and st.get("branch") and main and not git.merged(st["branch"], main):
                human.append(_entry("task_done", f"{sid}/{t.id}", f"{label} is done; branch {st['branch']} waits for "
                                    "your review", s["ledger"], f"steward sprint report {sid}", when))
    td = tidy(root, cfg, now)
    return {"now": iso(now), "project": cfg.steward.project, "resume": resume, "milestone": milestone,
            "waiting_on_human": human, "waiting_on_agents": agents,
            "tidy": {"counts": td["counts"], "total": td["total"], "command": "steward tidy"},
            "notes": notes + td["notes"]}


def render_next(doc: dict[str, Any], brief: bool = False) -> str:
    cap = 3 if brief else 30
    out: list[str] = []
    r = doc["resume"]
    if r is None:
        out.append("Where you left off: no session handoff (steward session close writes one)")
    else:
        age = f"{r['age_days']:g} days old" if r["age_days"] is not None else "age unknown"
        out.append(f"Where you left off: {r['path']} ({age}{'' if r['committed'] else ', not committed'})")
        out += [f"  {n}. {line}" for n, line in enumerate(r["next"][:cap], start=1)] or ["  (no next steps recorded)"]
    m = doc["milestone"]
    if m is None:
        out.append("Next milestone: none open (development/milestones.toml)")
    else:
        out.append(f"Next milestone: {m['id']} \"{m['title']}\" · {m['days_left']:g} days · {m['state'].upper()}")
        if m["blockers"]:
            shown = ", ".join(f"{b['kind']} {b['id']}" for b in m["blockers"][:cap * 2])
            out.append(f"  blocking: {shown}" + (f", and {len(m['blockers']) - cap * 2} more" if len(m["blockers"]) > cap * 2 else ""))
    from .newest import newest_first

    for title, key in (("Waiting on you", "waiting_on_human"), ("Waiting on agents", "waiting_on_agents")):
        rows = newest_first(doc[key], lambda r: r["time"], lambda r: r["id"])  # X05: newest first
        out.append(f"{title} ({len(rows)})" + ("" if rows else ": nothing"))
        for row in rows[:cap]:
            out.append(f"  {row['kind']:<12} {row['title']}" + ("" if brief else f"\n               -> {row['command']}"))
        if len(rows) > cap:
            out.append(f"  and {len(rows) - cap} more")
    t = doc["tidy"]
    out.append(f"Needs tidying ({t['total']})" + (": " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in t["counts"].items() if n)
                                                 + " -> steward tidy" if t["total"] else ": nothing"))
    if brief:
        out.append("Ask before archiving or deleting anything listed; the commands above are suggestions, not orders.")
    else:
        out += [f"note: {n}" for n in doc["notes"]]
    return "\n".join(out)


# ---------------------------------------------------------------- notifications (C21)
URGENT = {"gate", "approval", "task_failed"}


def _note(kind: str, iid: str, time: dt.datetime | None, source: str, title: str, command: str) -> dict[str, Any]:
    return {"id": f"{kind}:{iid}", "kind": kind, "time": iso(time), "source": source, "title": title,
            "command": command, "urgent": kind in URGENT}


def notifications(root: Path, cfg: Any, now: dt.datetime, days: int = 14,
                  against: dict[str, Any] | None = None, against_name: str | None = None) -> dict[str, Any]:
    from . import __version__
    from . import authorize as az
    from . import milestones as ms

    items: list[dict[str, Any]] = []
    notes: list[str] = []
    from .upgrade import parse_version, release_version

    since = now - dt.timedelta(days=days)
    try:  # W12 F13: the same version order and notice test as `steward upgrade --check` (prereleases included)
        installed = parse_version(__version__.split("+")[0])
    except ValueError:
        installed = None
    inbox, _ = _inbox(root, cfg)
    for rel, it, entries in inbox:
        st = entries[-1]["state"] if entries else None
        when = _received_at(it, entries)
        announced = release_version(root, cfg, rel, it, entries) if installed is not None else None
        newer = announced is not None and announced.key > installed.key
        if newer and st not in ("declined", "closed"):
            items.append(_note("upgrade", it.id, when, rel, f"Bio-STEWARD {it.version} is released, newer than this "
                               "CLI (steward --version)", "steward exchange status"))
        elif st in UNDECIDED:
            items.append(_note("exchange", it.id, when, rel, f"{it.kind} from {it.from_}: {it.title}",
                               _exchange_command(it)))
    sps, sp_notes = sprints(root)
    notes += sp_notes
    for s in sps:
        sf, sid = s["sf"], s["sf"].sprint.id
        for t in sf.task:
            st, when = s["states"][t.id], s["times"].get(t.id)
            label = f"sprint {sid} task {t.id}: {t.title}"
            if st["state"] in ("done", "failed") and when is not None and when >= since:
                kind = "task_finished" if st["state"] == "done" else "task_failed"
                items.append(_note(kind, f"{sid}/{t.id}", when, s["ledger"], f"{label} {st['state']}",
                                   f"steward sprint report {sid}" if kind == "task_finished"
                                   else f"steward sprint go {sid} {t.id} --retry"))
            elif st["state"] == "ready" and not st["go"] and not st["hold"] and sf.sprint.dispatch == "order" \
                    and sf.sprint.window.end >= now:
                items.append(_note("task_waiting", f"{sid}/{t.id}", _waiting_since(s, t),
                                   s["ledger"], f"{label} waits for an order", f"steward sprint go {sid} {t.id}"))
    for q in az.pending(root, now=now, repo_id=cfg.steward.repo_id):  # W12 F1: a foreign payload is not waiting
        if q["state"] == "waiting":
            items.append(_note("approval", q["nonce"], _mtime(root / q["path"]), q["path"],
                               f"{q['action']} waits for a signature (expires {q['expires']})",
                               "steward authorize sign-pending"))
    for row in ms.timeline(root, cfg, now=now):
        if row["state"] in ("at risk", "late"):
            due = _parse_time(row["due"])
            internal = _parse_time(row["internal"])
            when = due if row["state"] == "late" else internal if internal and internal <= now else now
            items.append(_note("milestone", f"{row['id']}:{row['state'].replace(' ', '-')}", when, ms.FILE,
                               f"{row['id']} \"{row['title']}\" is {row['state']} ({row['open_work']} open)",
                               "steward next"))
    if against is None:
        notes.append("gates: not compared (pass --against REPORT, an earlier `steward check --format json` output)")
    else:
        from .engine import run_check

        before = {g.get("name"): g.get("eligible") for g in against.get("verdict", {}).get("gates", [])
                  if isinstance(g, dict)}
        rep = run_check(root)
        digest = str(rep["verdict"].get("inputs_digest") or "")[:12]
        for g in rep["verdict"]["gates"]:
            if before.get(g["name"]) is True and not g["eligible"]:
                blocking = [b.get("rule") if isinstance(b, dict) else b for b in g["blocking"]]
                items.append(_note("gate", f"{g['name']}:{digest}", now, against_name or "report",
                                   f"gate {g['name']} turned not eligible (blocking {', '.join(map(str, blocking[:6]))})",
                                   f"steward check --summary --gate {g['name']}"))
    items.sort(key=lambda i: (i["time"] or "", i["id"]), reverse=True)
    return {"now": iso(now), "days": days, "items": items, "notes": notes}


def render_notifications(doc: dict[str, Any]) -> str:
    if not doc["items"]:
        out = ["No notifications."]
    else:
        out = [f"Notifications ({len(doc['items'])}, newest first)"]
        for i in doc["items"]:
            out.append(f"  {(i['time'] or '')[:16].replace('T', ' '):<16} {'!' if i['urgent'] else ' '} {i['kind']:<13} "
                       f"{i['title']}\n{'':<35}-> {i['command']}")
    return "\n".join(out + [f"note: {n}" for n in doc["notes"]])
