"""Compare the current timeline with the plan and its local Git history."""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from itertools import chain
from pathlib import Path
from subprocess import TimeoutExpired

from . import decisions
from .cockpit import board_tasks
from .fsutil import escapes_root, git_run
from .milestones import FILE, MilestonesFile

ROADMAP = re.compile(r"^\W*(?:\d+\.\s+)?roadmap\b", re.I)
SCOPE_FIELDS = ("title", "kind", "gate", "tasks", "items", "needs", "buffer_days", "final")
NOT_STARTED = {"proposed", "planned", "todo", "to do", "not started", "(none)"}
DROPPED = {"dropped", "cancelled", "canceled", "withdrawn", "abandoned"}


def roadmap(text: str) -> dict:
    rows = {}
    section = None
    table = []
    for number, line in decisions.markdown_lines(text):
        heading = decisions.HEADING.match(line)
        if heading:
            depth = len(heading[1])
            if ROADMAP.match(heading[2]):
                section = depth
            elif section is not None and depth <= section:
                section = None
            table = []
        elif ROADMAP.match(line.strip()) and line.strip().endswith((":", "**")):
            section = 6
            table = []
        elif section is not None and line.lstrip().startswith("|"):
            row = decisions.cells(line)
            if not table:
                table = row
            elif len(row) == len(table) and row[0] and not decisions.table_separator(row):
                key = row[0].strip("`* ")
                rows[key] = (number, dict(zip(table, row)))
        elif line.strip():
            table = []
    return rows


def _milestones(text: str) -> dict:
    parsed = MilestonesFile.model_validate(tomllib.loads(text))
    return {m.id: m.model_dump() for m in parsed.milestone}


def _history(root: Path, path: str):
    """Yield each first-parent snapshot of this project path, oldest first, including deletions."""
    log = git_run(root, "log", "--no-show-signature", "--first-parent", "--full-history", "--reverse",
                  "--format=%H%x09%cI", "HEAD", "--", f":(top,literal){path}")
    if log.returncode:
        raise ValueError("could not list commits")
    for line in log.stdout.decode().splitlines():
        oid, when = line.split("\t", 1)
        blob = git_run(root, "show", "--no-textconv", f"{oid}:{path}")
        if blob.returncode:
            tree = git_run(root, "ls-tree", "-z", oid, "--", f":(top,literal){path}")
            if tree.returncode or tree.stdout:
                yield oid, when, False  # the path exists but its content could not be read
                continue
            yield oid, when, None
        else:
            yield oid, when, blob.stdout.decode("utf-8", errors="replace")


def _mentions(text: str, subject: str) -> bool:
    return bool(subject and re.search(rf"(?<![\w.-]){re.escape(subject)}(?![\w.-])", text, re.I))


def _decision(records, subject, title, reference, when):
    if reference and decisions.DATED.fullmatch(reference):
        for entry in records:
            if reference == entry["heading"]:
                return {key: entry[key] for key in ("path", "line", "heading")}
    if when:
        day = dt.date.fromisoformat(when[:10])
        nearby = sorted(records, key=lambda e: abs((dt.date.fromisoformat(e["date"]) - day).days))
        for entry in nearby:
            if abs((dt.date.fromisoformat(entry["date"]) - day).days) > 1:
                break
            if any(
                _mentions(entry["heading"] + "\n" + entry["body"], term) for term in (subject, title)
            ):
                return {key: entry[key] for key in ("path", "line", "heading")}
    return None


def _changes(root, path, kind, current, parse, records):
    changes = []
    baseline = {}
    notes = []
    previous = None
    for oid, when, text in chain(_history(root, path), [(None, None, current)]):
        try:
            if text is False:
                raise ValueError("unavailable blob")
            snapshot = parse(text) if text is not None else {}
        except ValueError:
            notes.append(f"{path}: could not read the plan at {oid or 'the working tree'}")
            previous = None  # there is no evidence for a transition across an unreadable snapshot
            continue
        if kind == "milestone" and oid:
            for mid, milestone in snapshot.items():
                baseline.setdefault(mid, milestone["due"])
        if previous is not None:
            for subject in sorted(previous.keys() | snapshot.keys()):
                before, after = previous.get(subject), snapshot.get(subject)
                if before == after:
                    continue
                reference = None
                title = ""
                due = None
                if before is None or after is None:
                    fields = ["added" if before is None else "removed"]
                elif kind == "roadmap":
                    fields = ["row"] if before[1] != after[1] else []
                else:
                    fields = [key for key in ("due", *SCOPE_FIELDS, "outcome") if before[key] != after[key]]
                    if "due" in fields:
                        due = {"before": before["due"].isoformat(), "after": after["due"].isoformat()}
                if not fields:
                    continue
                if kind == "milestone":
                    title = (after or before)["title"]
                    outcome = after["outcome"] if after else None
                    if outcome and any(key in fields for key in ("outcome", "added")):
                        reference = outcome["decision"]
                changes.append({"kind": kind, "id": subject, "path": path, "commit": oid, "time": when,
                                "fields": fields, "due": due, "decision": _decision(records, subject, title, reference, when)})
        if text is not None or previous is not None:
            previous = snapshot
    return changes, baseline, notes


def _local_history(root: Path) -> str:
    repo = git_run(root, "rev-parse", "--show-prefix")
    if repo.returncode or repo.stdout.strip():
        return "unavailable"
    if git_run(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode:
        return "unavailable"
    shallow = git_run(root, "rev-parse", "--is-shallow-repository")
    return "shallow" if shallow.stdout.strip() == b"true" else "available"


def _scope_and_order(root, cfg, plan, rows, index, roadmap_rows):
    tasks = {task["id"]: task for task in board_tasks(root, cfg)}
    assigned = {task for m in plan.values() for task in m["tasks"]}
    scope = [{"reason": "unassigned_task", "id": tid, "milestone": None, "path": task["path"], "line": None}
             for tid, task in sorted(tasks.items()) if tid not in assigned
             and task["status"].casefold() not in DROPPED and (task["closed"] or not task["archived"])]
    for mid, m in plan.items():
        for tid in sorted(set(m["tasks"])):
            task = tasks.get(tid)
            if task is None:
                if cfg.tasks is None:
                    continue
                reason = "missing_task"
            else:
                status = task["status"].casefold()
                if status in DROPPED:
                    reason = "dropped_task"
                elif status in NOT_STARTED and not task["closed"]:
                    reason = "unstarted_task"
                else:
                    continue
            scope.append({"reason": reason, "id": tid, "milestone": mid, "path": task["path"] if task else FILE,
                          "line": None})
    for key, (line, row) in roadmap_rows.items():
        task_cells = [value for name, value in row.items() if name.casefold() in ("task", "tasks", "task id", "task ids")]
        linked = any(_mentions(" ".join(row.values()), tid) for tid in tasks)
        if not task_cells and not tasks:
            continue  # no task references to compare
        if not linked and all(value.casefold().strip(" -*`") in decisions.EMPTY for value in task_cells):
            scope.append({"reason": "roadmap_without_task", "id": key, "milestone": None, "path": index, "line": line})
    order = []
    for row in rows:
        mid = row["id"]
        m = plan.get(mid)
        if m is None:
            continue
        started = sorted({tid for tid in m["tasks"] if tid in tasks and
                          tasks[tid]["status"].casefold() not in DROPPED and
                          (tasks[tid]["closed"] or tasks[tid]["status"].casefold() in {"in progress", "in review", "done"})})
        if not started:
            continue
        for earlier in rows:
            if earlier["open_work"] and earlier["id"] in plan and plan[earlier["id"]]["due"] < m["due"]:
                distinct = sorted(set(started) - set(plan[earlier["id"]]["tasks"]))
                if distinct:
                    order.append({"earlier": earlier["id"], "later": mid, "started_tasks": distinct})
    return scope, order


def document(root: Path, cfg, rows: list[dict]) -> dict:
    index = decisions.index_path(cfg)
    text = decisions.read_record(root, index)
    milestones = decisions.read_record(root, FILE)
    plan = _milestones(milestones) if milestones is not None else {}
    records = decisions.recorded(root, cfg)
    changes, baseline, notes = [], {}, []
    try:
        history = _local_history(root)
    except (OSError, TimeoutExpired):
        history = "unavailable"
    if history != "unavailable":
        for path, kind, current, parser in ((FILE, "milestone", milestones, _milestones), (index, "roadmap", text, roadmap)):
            if escapes_root(path) or ".git" in Path(path).parts:
                continue
            try:
                found, first, problems = _changes(root, path, kind, current, parser, records)
            except (OSError, TimeoutExpired, ValueError):
                notes.append(f"{path}: could not read local history")
                continue
            changes.extend(found)
            baseline.update(first)
            notes.extend(problems)
    dates = []
    for mid, m in plan.items():
        first = baseline.get(mid)
        moved = bool(m["outcome"] and m["outcome"]["state"] == "moved")
        count = sum(c["kind"] == "milestone" and c["id"] == mid and c["due"] is not None for c in changes)
        if count or moved or (first is not None and first != m["due"]):
            dates.append({"id": mid, "first_due": first.isoformat() if first is not None else None,
                          "current_due": m["due"].isoformat(),
                          "days": round((m["due"] - first).total_seconds() / 86400, 3) if first is not None else None,
                          "moves": count, "recorded_move": moved})
    scope, order = _scope_and_order(root, cfg, plan, rows, index, roadmap(text or ""))
    return {"history": "partial" if notes else history, "notes": notes, "date": dates, "scope": scope,
            "order": order, "changes": changes}
