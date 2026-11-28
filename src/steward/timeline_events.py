"""The research timeline (0.24.0, P02): every dated record of the project on one time axis.

`steward timeline --events` reads milestones (with their moves and outcomes), decisions, releases (the local `v*`
tags), papers (the date their venue requirements were retrieved) and the independent reviews, research records, and
sprint windows with their tasks. Each event names its source file and line. Nothing is estimated and nothing is
fetched: a record without a date is left out, and `--all-projects` reads only the projects the exchange names that
are present on disk.
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from .cockpit import _day, _parse_time, iso
from .fsutil import git_run

KINDS = ("milestone", "milestone_moved", "milestone_outcome", "decision", "release", "paper", "review", "research",
         "sprint", "task")


def _event(kind: str, key: str, time: dt.datetime, title: str, path: str | None, line: int | None, *,
           project: str | None = None, day: bool = False, end: dt.datetime | None = None,
           internal: dt.datetime | None = None, moved_from: dt.datetime | None = None,
           moved_to: dt.datetime | None = None, state: str | None = None, ref: str | None = None) -> dict[str, Any]:
    return {"id": f"{project + '/' if project else ''}{kind}:{key}", "kind": kind, "project": project,
            "time": iso(time), "day": day, "end": iso(end), "internal": iso(internal), "moved_from": iso(moved_from),
            "moved_to": iso(moved_to), "state": state, "title": title, "path": path, "line": line, "ref": ref}


def _read(root: Path, rel: str) -> str | None:
    from .decisions import read_record

    try:
        return read_record(root, rel)
    except OSError:
        return None


def line_of(text: str | None, key: str, value: str | None = None, after: str | None = None) -> int | None:
    """The line of `key = …` (or `key = "value"`) in a TOML text, from the first line that matches `after`."""
    if text is None:
        return None
    start = 0
    lines = text.splitlines()
    if after is not None:
        start = next((i for i, ln in enumerate(lines) if re.match(after, ln.strip())), 0)
    want = re.compile(rf"^\s*{re.escape(key)}\s*=\s*" + (rf"[\"']{re.escape(value)}[\"']" if value is not None else ""))
    return next((i + 1 for i, ln in enumerate(lines[start:], start) if want.match(ln)), None)


def _repo_top(root: Path) -> bool:
    """The project is the root of its own Git repository (not a folder inside another one)."""
    try:
        r = git_run(root, "rev-parse", "--show-prefix", timeout=30)
        return r.returncode == 0 and not r.stdout.strip()
    except (OSError, TimeoutExpired):
        return False


def _milestones(root, cfg, now, project, progress, notes) -> list[dict[str, Any]]:
    from . import drift
    from . import milestones as ms

    try:
        mf = ms.load(root)
    except ValueError as e:  # pydantic's ValidationError is a ValueError
        notes.append(f"{ms.FILE}: not valid ({str(e).splitlines()[0][:120]})")
        return []
    if mf is None:
        return []
    text = _read(root, ms.FILE)
    rows = []
    if progress:
        rows = ms.timeline(root, cfg) if now is None else ms.timeline(root, cfg, now=now)
    states = {r["id"]: r["state"] for r in rows}
    try:
        moves = drift.document(root, cfg, rows)
    except (OSError, ValueError, TimeoutExpired):
        moves = {"date": [], "changes": [], "notes": [f"{ms.FILE}: could not read local history"]}
    notes.extend(n for n in moves["notes"] if n.startswith(ms.FILE))
    first = {d["id"]: _parse_time(d["first_due"]) for d in moves["date"]}
    out = []
    for m in mf.milestone:
        line = line_of(text, "id", m.id)
        internal = m.due - dt.timedelta(days=m.buffer_days)
        old = first.get(m.id)
        state = states.get(m.id) or (m.outcome.state if m.outcome else None)
        out.append(_event("milestone", m.id, m.due, m.title, ms.FILE, line, project=project,
                          internal=internal if m.buffer_days else None,
                          moved_from=old if old is not None and old != m.due else None, state=state))
        if m.outcome is not None and m.outcome.on is not None:
            out.append(_event("milestone_outcome", m.id, _day(m.outcome.on), f"{m.id}: {m.outcome.state} "
                              f"({m.outcome.decision})", ms.FILE, line, project=project, day=True,
                              state=m.outcome.state))
    titles = {m.id: (m.title, line_of(text, "id", m.id)) for m in mf.milestone}
    for c in moves["changes"]:
        if c["kind"] != "milestone" or c["due"] is None:
            continue
        when = _parse_time(c["time"])
        if when is None:  # a change in the working tree has no commit time
            notes.append(f"{ms.FILE}: an uncommitted move of {c['id']} is not dated")
            continue
        title, line = titles.get(c["id"], (c["id"], None))
        out.append(_event("milestone_moved", f"{c['id']}:{c['commit'][:12]}", when,
                          f"{c['id']} moved: {c['due']['before'][:10]} → {c['due']['after'][:10]} ({title})",
                          ms.FILE, line, project=project, moved_from=_parse_time(c["due"]["before"]),
                          moved_to=_parse_time(c["due"]["after"]), ref=c["commit"]))
    return out


def _decisions(root, cfg, project) -> list[dict[str, Any]]:
    from . import decisions

    return [_event("decision", f"{e['path']}:{e['line']}", _day(dt.date.fromisoformat(e["date"])), e["title"] or
                   e["heading"], e["path"], e["line"], project=project, day=True)
            for e in decisions.recorded(root, cfg)]


def _releases(root, project, git_ok) -> list[dict[str, Any]]:
    if not git_ok:
        return []
    r = git_run(root, "for-each-ref", "--format=%(refname:short)%09%(creatordate:iso-strict)", "refs/tags/v*",
                text=True, timeout=30)
    out = []
    for ln in r.stdout.splitlines() if r.returncode == 0 else []:
        tag, _, when = ln.partition("\t")
        t = _parse_time(when)
        if t is not None and re.fullmatch(r"v\d+(?:\.\d+)*\S*", tag):
            out.append(_event("release", tag, t, f"release {tag}", None, None, project=project, ref=f"refs/tags/{tag}"))
    return out


def _papers(root, cfg, project, notes) -> list[dict[str, Any]]:
    out = []
    for name, pp in sorted((getattr(cfg, "paper", None) or {}).items()):
        rel = f"{pp.dir.rstrip('/')}/{pp.venue}"
        text = _read(root, rel)
        if text is None:
            continue
        try:
            venue = tomllib.loads(text)
            day = dt.date.fromisoformat(str(venue.get("retrieved")))
        except (tomllib.TOMLDecodeError, ValueError):
            continue  # no venue date yet (a sentinel) or not valid: R-checks report it
        out.append(_event("paper", f"{name}:venue", _day(day), f"paper {name}: venue requirements retrieved "
                          f"({venue.get('name', 'venue')})", rel, line_of(text, "retrieved"), project=project, day=True))
    return out


def _reviews(root, cfg, project, git_ok, notes) -> list[dict[str, Any]]:
    from .models import ReleaseSection
    from .review import FindingsFile

    rel = (getattr(cfg, "release", None) or ReleaseSection()).findings
    text = _read(root, rel)
    if text is None:
        return []
    try:
        ff = FindingsFile.model_validate(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValueError):
        notes.append(f"{rel}: not valid; its reviews are not dated")
        return []
    out = []
    for rv in ff.reviews:
        when = None
        if git_ok:
            r = git_run(root, "show", "-s", "--no-show-signature", "--format=%cI", f"{rv.revision}^{{commit}}", "--",
                        text=True, timeout=30)
            when = _parse_time(r.stdout.strip()) if r.returncode == 0 else None
        if when is None:
            notes.append(f"{rel}: review {rv.id} is not dated (its revision is not a local commit)")
            continue
        out.append(_event("review", rv.id, when, f"review {rv.id} by {rv.reviewer}", rel, line_of(text, "id", rv.id),
                          project=project, ref=rv.revision))
    return out


def _research(root, cfg, project, notes) -> list[dict[str, Any]]:
    from .records import load_research

    if getattr(cfg, "research", None) is None:
        return []
    try:
        ok, bad = load_research(root, cfg)
    except OSError:
        notes.append("research records could not be read")
        return []
    notes.extend(f"{rel}: not valid; left out" for rel, _ in bad)
    out = []
    for rid, (rel, r) in sorted(ok.items()):
        text = _read(root, rel)
        out.append(_event("research", rid, _day(r.date), f"{r.kind} {rid}: {r.title}", rel, line_of(text, "date"),
                          project=project, day=True, state=r.status))
        if r.review is not None and r.review.searched != r.date:
            out.append(_event("research", f"{rid}:searched", _day(r.review.searched), f"{rid}: literature searched",
                              rel, line_of(text, "searched"), project=project, day=True))
        if r.dead_end is not None and r.dead_end.decided is not None:
            out.append(_event("research", f"{rid}:decided", _day(r.dead_end.decided),
                              f"{rid}: dead-end decision ({r.dead_end.decision or 'recorded'})", rel,
                              line_of(text, "decided"), project=project, day=True, state=r.dead_end.decision))
    return out


def _sprints(root, now, project, notes) -> list[dict[str, Any]]:
    from . import sprint as sp
    from .cockpit import sprints

    found, problems = sprints(root)
    notes.extend(problems)
    out = []
    for s in found:
        sf = s["sf"]
        sid = sf.sprint.id
        rel = f"{sp.DIR}/{sid}.toml"
        text = _read(root, rel)
        if text is None:
            rel, text = s["ledger"], None
        out.append(_event("sprint", sid, sf.sprint.window.start, f"sprint {sid}", rel, line_of(text, "window"),
                          project=project, end=sf.sprint.window.end, state=sp.window_state(sf, now)))
        for t in sf.task:
            st = s["states"][t.id]
            started = _parse_time(st.get("started"))
            if started is None:
                continue  # never started: the ledger dates nothing for it
            ended = _parse_time(st.get("ended")) if st["state"] in ("done", "failed", "review") else None
            out.append(_event("task", f"{sid}/{t.id}", started, f"{sid} {t.id}: {t.title}", rel,
                              line_of(text, "id", t.id, after=r"\[\[task\]\]"), project=project, end=ended,
                              state=st["state"]))
    return out


def events(root: Path, cfg: Any, now: dt.datetime | None, *, project: str | None = None,
           progress: bool = True) -> tuple[list[dict[str, Any]], list[str]]:
    """Every dated event of one project, in no particular order, and the notes on what could not be dated."""
    notes: list[str] = []
    git_ok = _repo_top(root)
    found = [*_milestones(root, cfg, now, project, progress, notes), *_decisions(root, cfg, project),
             *_releases(root, project, git_ok), *_papers(root, cfg, project, notes),
             *_reviews(root, cfg, project, git_ok, notes), *_research(root, cfg, project, notes),
             *_sprints(root, now, project, notes)]
    return found, [f"{project}: {n}" if project else n for n in notes]


def _named_projects(root: Path, cfg: Any) -> tuple[dict[str, Any], set[str]]:
    """The projects the exchange names: its peers (declared, or found in the local registry), its consumers, and
    the codes its items come from or go to. Code -> its peer source (None when only named)."""
    from . import exchange as xc

    ex = getattr(cfg, "exchange", None)
    if ex is None:
        return {}, set()
    peers, ambiguous = xc.discover_peers(root, ex)
    named: dict[str, Any] = {code: None for code in ex.consumers}
    if xc.folder(root).is_dir():
        for entries in xc.items(root).values():
            for _, text in entries:
                try:
                    it = xc.Item.model_validate(xc.parse(text)[0])
                except Exception:  # noqa: BLE001  # an invalid item names nothing
                    continue
                for code in (it.from_, it.to):
                    named.setdefault(code, None)
    named.update(peers)
    named.pop(ex.code, None)
    return named, ambiguous


def document(root: Path, cfg: Any, now: dt.datetime, *, all_projects: bool = False,
             explicit_now: bool = True) -> dict[str, Any]:
    from .models import load_config
    from .newest import newest_first

    own = getattr(getattr(cfg, "exchange", None), "code", None)
    found, notes = events(root, cfg, now if explicit_now else None)
    projects = [{"code": own, "path": ".", "reachable": True, "note": None}]
    if all_projects:
        from . import exchange as xc

        named, ambiguous = _named_projects(root, cfg)
        if getattr(cfg, "exchange", None) is None:
            notes.append("--all-projects: no [exchange] table, so no other project is named")
        for code in sorted(named):
            source = named[code]
            where = xc.local_peer_path(root, source) if source is not None else None
            entry = {"code": code, "path": None, "reachable": False, "note": None}
            projects.append(entry)
            if code in ambiguous:
                entry["note"] = "more than one checkout on disk declares this code"
            elif source is None:
                entry["note"] = "named by the exchange, with no location"
            elif where is None:
                entry["note"] = "a remote URL: not fetched"
            elif not (where / "steward.toml").is_file():
                entry["note"] = "not on disk"
            else:
                entry["path"] = str(where)
                try:
                    pcfg = load_config(where)
                    more, more_notes = events(where, pcfg, now, project=code, progress=False)
                except (ValueError, OSError) as e:
                    entry["note"] = f"its records could not be read ({str(e).splitlines()[0][:120]})"
                    continue
                entry["reachable"] = True
                found += more
                notes += more_notes
    return {"now": iso(now), "projects": projects,
            "events": newest_first(found, lambda e: e["time"], lambda e: e["id"]), "notes": notes}


def render(doc: dict[str, Any]) -> str:
    if not doc["events"]:
        out = ["No dated records. Milestones, decisions, releases, papers, reviews, research records and sprints "
               "appear here once they are recorded."]
    else:
        out = [f"Research timeline ({len(doc['events'])} events, newest first; now {doc['now']})"]
        for e in doc["events"]:
            when = e["time"][:10] if e["day"] else e["time"][:16].replace("T", " ")
            where = f"{e['path']}:{e['line']}" if e["path"] and e["line"] else e["path"] or e["ref"] or ""
            extra = [f"until {e['end'][:16].replace('T', ' ')}"] if e["end"] else []
            extra += [f"internal {e['internal'][:10]}"] if e["internal"] else []
            extra += [f"first due {e['moved_from'][:10]}"] if e["moved_from"] and e["kind"] == "milestone" else []
            extra += [e["state"]] if e["state"] and e["kind"] != "milestone_outcome" else []
            who = f"[{e['project']}] " if e["project"] else ""
            out.append(f"  {when:<16} {e['kind']:<17} {who}{e['title']}"
                       + (f" ({'; '.join(extra)})" if extra else "") + (f"  {where}" if where else ""))
    for p in doc["projects"][1:]:
        out.append(f"project {p['code']}: " + ("read from " + p["path"] if p["reachable"] else p["note"] or "not read"))
    return "\n".join(out + [f"note: {n}" for n in doc["notes"]])
