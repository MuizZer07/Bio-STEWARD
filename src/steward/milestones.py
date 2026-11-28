"""Milestones and the timeline (0.13.0; DESIGN_BRIEF_sprint §5; SP7).

`development/milestones.toml` lists dated goals (a preprint, a conference deadline, a release). `steward timeline`
shows each, soonest first, with the days left and its progress, measured only from the project's own records: the
required rules of its gate, its board tasks, the exchange items it waits on and the signatures it needs. A milestone is
**at risk** when work is open after its internal deadline (due minus the buffer), and **late** after its due time.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from .models import Strict, Text

FILE = "development/milestones.toml"
DONE_ITEM = {"shipped", "adopted", "closed", "merged", "declined", "superseded", "withdrawn"}


class Outcome(Strict):
    state: Literal["met", "moved", "dropped"]
    decision: Text  # the decisions-log entry or note that records it
    on: dt.date | None = None


class Milestone(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    title: Text
    due: dt.datetime
    kind: Literal["submission", "preprint", "release", "review", "other"] = "other"
    gate: str | None = None
    tasks: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)  # signatures: policy.change, spend, unseal, …
    buffer_days: int = Field(default=0, ge=0, le=365)
    final: bool | None = None  # V9 (0.14.0): final checks; default on for submissions, preprints and releases
    outcome: Outcome | None = None

    @field_validator("due")
    @classmethod
    def _zoned(cls, v: dt.datetime) -> dt.datetime:
        if v.tzinfo is None:
            raise ValueError("due needs its time zone, e.g. 2027-01-20T23:59:00-12:00 (anywhere on earth)")
        return v


class MilestonesFile(Strict):
    schema_: Literal["steward.milestones/0.1"] = Field(alias="schema")
    milestone: list[Milestone] = Field(default_factory=list)


def load(root: Path) -> MilestonesFile | None:
    p = root / FILE
    if not p.is_file():
        return None
    return MilestonesFile.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))


def _task_states(root: Path, cfg: Any) -> dict[str, str] | None:
    """Task ID -> status, from the board's specs (R-57's reading), or None without [tasks]."""
    from .fsutil import glob_match, iter_repo_files
    from .process import ID_LINE, STATUS_LINE, _status

    tc = getattr(cfg, "tasks", None)
    if tc is None:
        return None
    out: dict[str, str] = {}
    for rel in iter_repo_files(root):
        if any(glob_match(rel, g) for g in [*tc.specs, *tc.archive]):
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            m, s = ID_LINE.search(text), STATUS_LINE.search(text)
            if m:
                out[m.group(1)] = _status(s.group(1) if s else None, tc.statuses) or "(none)"
    return out


def progress(root: Path, cfg: Any, m: Milestone, gate_cache: dict[str, dict[str, Any]],
             now: dt.datetime | None = None) -> dict[str, Any]:
    from . import authorize as az
    from . import exchange as xc

    out: dict[str, Any] = {}
    if m.gate:
        final = m.final if m.final is not None else m.kind in ("submission", "preprint", "release")
        key = f"{m.gate}|{final}"
        if key not in gate_cache:
            from .engine import UnknownGate, run_check

            try:
                rep = run_check(root, gate=m.gate, final=final)
                g = next(x for x in rep["verdict"]["gates"] if x["name"] == rep["_gate"])
                gate_cache[key] = {"final": final, "eligible": g["eligible"], "passed": g["pass_count"], "required": g["required_count"],
                                      "not_applicable": g["not_applicable_count"],
                                      "blocking": [b.get("rule") if isinstance(b, dict) else b for b in g["blocking"]]}
            except UnknownGate:
                gate_cache[key] = {"error": f"unknown gate {m.gate!r}"}
        out["gate"] = {"name": m.gate, **gate_cache[key]}
    if m.tasks:
        states = _task_states(root, cfg)
        closed = set(getattr(getattr(cfg, "tasks", None), "closed", []) or [])
        if states is None:
            out["tasks"] = {"error": "no [tasks] board configured"}
        else:
            open_ = [t for t in m.tasks if states.get(t) not in closed]
            out["tasks"] = {"done": len(m.tasks) - len(open_), "total": len(m.tasks), "open": open_,
                            "unknown": [t for t in m.tasks if t not in states]}
    if m.items:
        from .ledger import verify

        lp = xc.folder(root) / "log.jsonl"
        v = verify(lp) if lp.is_file() else None
        if v is not None and (v.errors or v.torn_tail):  # V9 (0.14.0): a broken ledger is unavailable evidence
            out["items"] = {"error": "the exchange ledger is not intact", "total": len(m.items), "waiting": list(m.items),
                            "done": 0}
        else:
            hist: dict[str, list[dict[str, Any]]] = {}
            for e in (v.entries if v is not None else []):  # V9 (0.15.0): the verified read, not a second one
                if e.get("kind") == "state":
                    hist.setdefault(e["item"], []).append(e)
            waiting = [i for i in m.items if xc.current(hist.get(i, [])) not in DONE_ITEM]
            out["items"] = {"done": len(m.items) - len(waiting), "total": len(m.items), "waiting": waiting}
    if m.needs:
        # W12 F12: the same `now` as the rest of the timeline, so `--now` decides which payloads have expired
        pend = [q for q in az.pending(root, now=now, repo_id=cfg.steward.repo_id) if q["state"] == "waiting"]
        out["signatures"] = {"needed": list(m.needs),
                             "waiting": sorted({q["action"] for q in pend if q["action"] in m.needs})}
    return out


def _open_work(p: dict[str, Any]) -> int:
    n = 0
    g = p.get("gate") or {}
    if g and not g.get("eligible", False):
        n += max(1, len(g.get("blocking", [])))
    t = p.get("tasks") or {}
    n += len(t.get("open", [])) + (1 if "error" in t else 0) + len(t.get("unknown", []))  # V8: unknown is not done
    n += len((p.get("items") or {}).get("waiting", []))
    n += len((p.get("signatures") or {}).get("waiting", []))
    return n


def timeline(root: Path, cfg: Any, now: dt.datetime | None = None) -> list[dict[str, Any]]:
    mf = load(root)
    if mf is None:
        return []
    now = now or dt.datetime.now(dt.timezone.utc)
    cache: dict[str, dict[str, Any]] = {}
    rows = []
    for m in sorted(mf.milestone, key=lambda x: x.due):
        internal = m.due - dt.timedelta(days=m.buffer_days)
        p = progress(root, cfg, m, cache, now=now) if m.outcome is None else {}
        open_work = _open_work(p)
        days_left = (m.due - now).total_seconds() / 86400
        if m.outcome is not None:
            state = m.outcome.state
        elif now > m.due:
            state = "late" if open_work else "due (record its outcome)"
        elif now > internal and open_work:
            state = "at risk"
        elif open_work and days_left < 7 and open_work / max(days_left, 0.5) > 3:
            state = "at risk"  # more than three open pieces of work a day remain
        else:
            state = "on track" if open_work or not p else "ready"
        rows.append({"id": m.id, "title": m.title, "kind": m.kind, "due": m.due.isoformat(),
                     "internal": internal.isoformat(), "days_left": round(days_left, 1), "state": state,
                     "open_work": open_work, "progress": p,
                     **({"outcome": m.outcome.model_dump(mode="json")} if m.outcome else {})})
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"No milestones. Add them to {FILE} (see the guide \"Plan to a deadline\")."
    from .newest import newest_first

    out = []
    for r in newest_first(rows, lambda r: r["due"], lambda r: r["id"]):  # X05: the latest due first
        days = r["days_left"]
        when = f"{abs(days):.1f} days {'left' if days >= 0 else 'ago'}"
        out.append(f"{r['state'].upper():<9} {r['id']}: {r['title']} ({r['kind']}) — due {r['due']} ({when})")
        p = r["progress"]
        if "gate" in p:
            g = p["gate"]
            out.append(f"          gate {g['name']}{' (final checks)' if g.get('final') else ''}: " + (g["error"] if "error" in g else
                       f"{'ELIGIBLE' if g['eligible'] else 'NOT ELIGIBLE'}, {g['passed']} of {g['required']} required "
                       f"passed ({g['not_applicable']} not applicable)" + (f"; blocking {', '.join(map(str, g['blocking']))}"
                                                                           if g["blocking"] else "")))
        if "tasks" in p:
            t = p["tasks"]
            out.append("          tasks: " + (t["error"] if "error" in t else
                       f"{t['done']} of {t['total']} done" + (f"; open {', '.join(t['open'])}" if t["open"] else "")))
        if "items" in p:
            i = p["items"]
            out.append("          items: " + (i["error"] if "error" in i else f"{i['done']} of {i['total']} settled"
                                                  + (f"; waiting {', '.join(i['waiting'])}" if i["waiting"] else "")))
        if "signatures" in p:
            s = p["signatures"]
            out.append(f"          signatures: needs {', '.join(s['needed'])}" + (
                f"; waiting to be signed: {', '.join(s['waiting'])} (steward authorize sign-pending)" if s["waiting"] else ""))
    out.append("Progress is read from the project's records (gates, board, exchange, the signing queue), not estimated.")
    return "\n".join(out)


def check(root: Path, cfg: Any) -> tuple[str, list[dict[str, Any]]]:
    """R-70: (status name, details)."""
    try:
        mf = load(root)
    except ValidationError as e:
        err = e.errors()[0]
        return "FAIL", [{"code": "R-70.invalid", "path": FILE, "message": f"{'.'.join(map(str, err['loc']))}: {err['msg']}"[:200]}]
    except ValueError as e:
        return "FAIL", [{"code": "R-70.invalid", "path": FILE, "message": str(e).splitlines()[0][:200]}]
    if mf is None:
        return "NOT_APPLICABLE", []
    details: list[dict[str, Any]] = []
    status = "PASS"
    ids = [m.id for m in mf.milestone]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        details.append({"code": "R-70.duplicate_id", "value": dup})
        status = "FAIL"
    states = _task_states(root, cfg)
    from . import exchange as xc

    known_items: set[str] = set()
    for entries in (xc.items(root).values() if xc.folder(root).is_dir() else []):
        for rel, text in entries:
            try:  # V9: an item exists only as a valid item file of that ID
                it = xc.Item.model_validate(xc.parse(text)[0])
                if it.id == Path(rel).stem:
                    known_items.add(it.id)
            except Exception:  # noqa: BLE001
                continue
    now = dt.datetime.now(dt.timezone.utc)
    for m in mf.milestone:
        if m.tasks and states is None:  # V8 (0.13.0): tasks it cannot read are not done
            details.append({"code": "R-70.no_board", "value": m.id, "message": "names tasks, and [tasks] is not configured"})
            status = "FAIL"
        for t in m.tasks:
            if states is not None and t not in states:
                details.append({"code": "R-70.unknown_task", "value": t, "message": f"{m.id} names a task no spec has"})
                status = "FAIL"
        for i in m.items:
            if i not in known_items:
                details.append({"code": "R-70.unknown_item", "value": i, "message": f"{m.id} names an item not in exchange/"})
                status = "FAIL"
        if m.outcome is None and now > m.due:
            details.append({"code": "R-70.past_due", "value": m.id,
                            "message": "past due without an outcome: record met, moved (with a decision) or dropped"})
            status = status if status == "FAIL" else "INCOMPLETE"
    return status, details

