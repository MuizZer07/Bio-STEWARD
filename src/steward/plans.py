"""Index the project's plans and the progress recorded against them."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from subprocess import TimeoutExpired

from . import decisions, drift, milestones, sprint
from .cockpit import board_tasks
from .fsutil import escapes_root, git_run
from .models import StewardConfig
from .newest import newest_first, when_key

_RELEASE = re.compile(r"RELEASE_(?:(?P<series>[\w.-]+)_)?v?(?P<version>\d+\.\d+(?:\.\d+)?(?:-[\w.-]+)?)_SPEC\.md")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SIGNATURE = re.compile(r"^\s*\*?Signature:\s*(\d{4}-\d{2}-\d{2})\b", re.I)
_MILESTONE_TABLE = re.compile(r"""^\s*\[\[\s*(?:milestone|"milestone"|'milestone')\s*\]\]\s*(?:#.*)?$""")
_MILESTONE_ARRAY = re.compile(r"""^\s*(?:milestone|"milestone"|'milestone')\s*=""")
_SPRINT_TABLE = re.compile(r"""^\s*(?:\[\s*(?:sprint|"sprint"|'sprint')\s*\]|(?:sprint|"sprint"|'sprint')\s*[.=])""")


def _row(kind, ident, title, state, date, path, line, progress, findings):
    return {"kind": kind, "id": ident, "title": title, "state": state, "date": date,
            "path": path, "line": line, "progress": progress, "drift": findings}


def _counts(tasks: list[dict], done: int) -> dict:
    return {"done": done, "total": len(tasks), "tasks": tasks}


def _findings(kind, ident, report, due_dates):
    return {
        "date": next((row for row in report["date"] if kind == "milestone" and row["id"] == ident), None),
        "scope": newest_first(
            (row for row in report["scope"] if
             (row["milestone"] == ident if kind == "milestone" else
              row["reason"] == "roadmap_without_task" and row["id"] == ident)),
            lambda _: None, lambda row: row["id"],
        ),
        "order": newest_first(
            (row for row in report["order"] if kind == "milestone" and ident in (row["earlier"], row["later"])),
            lambda row: due_dates[row["later"]], lambda row: (row["later"], row["earlier"]),
        ),
        "changes": newest_first(
            (row for row in report["changes"] if row["kind"] == kind and row["id"] == ident),
            lambda row: row["time"] or float("inf"), lambda row: row["commit"],
        ),
    }


def _roadmap(root, cfg, path, report):
    records = drift.roadmap(decisions.read_record(root, path) or "")
    if not records:
        return
    tasks = board_tasks(root, cfg)
    for ident, (line, row) in records.items():
        cells = {name.casefold(): value for name, value in row.items()}
        title = next((cells[k] for k in ("title", "theme", "plan", "description", "contents") if cells.get(k)), ident)
        state = cells.get("state") or cells.get("status") or "unrecorded"
        found = _DATE.search(cells.get("date") or state)
        date = found[0] if found and when_key(found[0])[0] else None
        linked = newest_first(
            (task for task in tasks if drift._mentions(" ".join(row.values()), task["id"])),
            lambda _: None, lambda task: task["id"],
        )
        progress = _counts([{"id": t["id"], "state": t["status"]} for t in linked],
                           sum(t["closed"] for t in linked)) if linked else None
        yield _row("roadmap", ident, title, state, date, path, line, progress,
                   _findings("roadmap", ident, report, {}))


def _tags(root: Path) -> dict[str, str]:
    try:
        prefix = git_run(root, "rev-parse", "--show-prefix", text=True)
        if prefix.returncode or prefix.stdout.strip():
            return {}
        tags = git_run(root, "for-each-ref", "--format=%(refname:lstrip=2)%09%(creatordate:iso-strict)",
                       "refs/tags", text=True)
    except (OSError, TimeoutExpired):
        return {}
    return dict(line.split("\t", 1) for line in tags.stdout.splitlines()) if tags.returncode == 0 else {}


def _release_drift(root: Path, tag: str, path: str, text: str) -> dict | None:
    try:
        baseline = git_run(root, "show", "--no-textconv", f"refs/tags/{tag}:{path}")
    except (OSError, TimeoutExpired):
        return None
    if baseline.returncode:
        return None
    recorded = baseline.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return {"changed_since_tag": text != recorded}


def _releases(root: Path, cfg: StewardConfig):
    relative = Path(cfg.paths.records) / "design"
    folder = root / relative
    if escapes_root(relative.as_posix()) or folder.resolve() != root.resolve() / relative:
        return
    specs = [(file, match) for file in folder.glob("RELEASE_*_SPEC.md") if (match := _RELEASE.fullmatch(file.name))]
    tags = _tags(root) if specs else {}
    for file, match in specs:
        path = file.relative_to(root).as_posix()
        text = decisions.read_record(root, path)
        if not text:
            continue
        ident = file.stem.removeprefix("RELEASE_").removesuffix("_SPEC")
        series, version = match.group("series", "version")
        prefix = f"{series}-v" if series else "v"
        parts = version.split("-", 1)
        if parts[0].count(".") == 1:
            parts[0] += ".0"
        tag = next((t for t in (prefix + version, prefix + "-".join(parts)) if tags.get(t)), None)
        title, line, date = None, 1, None
        for number, content in decisions.markdown_lines(text):
            if title is None and (heading := decisions.HEADING.match(content)):
                title, line = heading[2], number
            if (signature := _SIGNATURE.match(content)) and when_key(signature[1])[0]:
                date = signature[1]
        yield _row("release", ident, title or ident, "tagged" if tag else "specified",
                   tags[tag] if tag else date, path, line, {"tag": tag},
                   _release_drift(root, tag, path, text) if tag else None)


def _sprints(root: Path):
    for file in (root / sprint.DIR).glob("*.toml"):
        path = file.relative_to(root).as_posix()
        text = decisions.read_record(root, path)
        if text is None:
            continue
        try:
            sf = sprint.SprintFile.model_validate(tomllib.loads(text))
            ident = sf.sprint.id
            if ident != file.stem:
                raise ValueError("the file name and sprint id must agree")
            events = sprint.events(root, ident)
        except ValueError as e:
            raise ValueError(f"{path}: {str(e).splitlines()[0][:160]}") from e
        states = sprint.states(sf, events)
        latest = {e["task"]: e.get("time") for e in events if e.get("task") in states}
        ids = newest_first(states, latest.get, str)
        progress = _counts([{"id": tid, "state": states[tid]["state"]} for tid in ids],
                           sum(s["state"] == "done" for s in states.values()))
        recorded = sprint.plan(events)
        findings = None if recorded is None else {
            "unplanned_tasks": [tid for tid in ids if tid not in recorded],
            "missing_tasks": newest_first(set(recorded) - states.keys(), lambda _: None, str),
        }
        line = next((n for n, content in enumerate(text.splitlines(), 1) if _SPRINT_TABLE.match(content)), 1)
        yield _row("sprint", ident, ident, sprint.window_state(sf), sf.sprint.window.start.isoformat(), path, line,
                   progress, findings)


def _milestone_lines(text: str) -> list[int]:
    """Find table declarations, excluding lookalikes in multiline strings."""
    lines = text.splitlines(keepends=True)
    found = []
    for index, line in enumerate(lines):
        if not (_MILESTONE_TABLE.match(line) or _MILESTONE_ARRAY.match(line)):
            continue
        try:
            tomllib.loads("".join(lines[:index]))
        except tomllib.TOMLDecodeError:
            continue  # a complete prefix ends before a real declaration
        if _MILESTONE_ARRAY.match(line):
            count = len(tomllib.loads(text)["milestone"])
            return [index + 1] * count
        found.append(index + 1)
    return found


def document(root: Path, cfg: StewardConfig) -> dict:
    index = decisions.index_path(cfg)
    text = decisions.read_record(root, milestones.FILE)
    timeline = milestones.timeline(root, cfg) if text is not None else []
    report = drift.document(root, cfg, timeline)
    due_dates = {m["id"]: m["due"] for m in timeline}
    rows = [*_roadmap(root, cfg, index, report), *_releases(root, cfg), *_sprints(root)]
    if timeline:
        # Apply the timeline's stable due-date sort to the declaration lines.
        mf = milestones.MilestonesFile.model_validate(tomllib.loads(text))
        sources = sorted(zip(mf.milestone, _milestone_lines(text), strict=True), key=lambda pair: pair[0].due)
        for m, (_, line) in zip(timeline, sources, strict=True):
            rows.append(_row("milestone", m["id"], m["title"], m["state"], m["due"], milestones.FILE, line,
                             m["progress"], _findings("milestone", m["id"], report, due_dates)))
    return {"plans": newest_first(rows, lambda row: row["date"], lambda row: (row["id"], row["path"], row["line"])),
            "history": report["history"], "notes": report["notes"]}


def render(doc: dict) -> str:
    lines = []
    for row in doc["plans"]:
        when = f" · {row['date']}" if row["date"] else ""
        lines.append(f"{row['state'].upper()}  {row['kind']} {row['id']} · {row['title']}{when}"
                     f"  ({row['path']}:{row['line']})")
        progress = row["progress"]
        if row["kind"] == "milestone":
            for name, record in progress.items():
                if "error" in record:
                    detail = record["error"]
                elif name == "gate":
                    detail = f"{record['passed']} of {record['required']} required rules passed"
                elif name == "signatures":
                    detail = f"{len(record['waiting'])} waiting"
                else:
                    unit = "settled" if name == "items" else "done"
                    detail = f"{record['done']} of {record['total']} {unit}"
                lines.append(f"  {name} · {detail}")
        elif row["kind"] == "release" and progress["tag"]:
            lines.append(f"  tag {progress['tag']}")
        elif progress and "done" in progress:
            lines.append(f"  {progress['done']} of {progress['total']} tasks done")
        findings = row["drift"]
        if findings and "changed_since_tag" in findings:
            if findings["changed_since_tag"]:
                lines.append("  drift · specification changed since the tag")
        elif findings and "unplanned_tasks" in findings:
            for name in ("unplanned_tasks", "missing_tasks"):
                if findings[name]:
                    lines.append(f"  drift · {name.replace('_', ' ')} · {', '.join(findings[name])}")
        elif findings:
            if findings["date"]:
                date = findings["date"]
                change = f", {date['days']:+g} days" if date["days"] is not None else ""
                lines.append(f"  drift · {date['moves']} deadline changes{change}"
                             + (", move recorded" if date["recorded_move"] else ""))
            for name in ("scope", "order", "changes"):
                if findings[name]:
                    lines.append(f"  drift · {name} · {len(findings[name])}")
    return "\n".join(lines) or "No plans recorded."
