"""Benchmark checks (v0.7, RELEASE_v0.7_SPEC): split integrity from declared identifiers, groups and times.

The checks find violations of what the contract declares. They do not show a benchmark is fair or free of leakage:
types that cannot be detected from identifiers and metadata are declared separately (R-49).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RANK = {"train": 0, "dev": 1, "validation": 1, "test": 2}
SHOW = 10  # IDs listed per finding


SENT = ("TBD", "unknown")
NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
DATE_HINT = "write dates as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (digits-only values are read as numbers)"


def _text(data: bytes) -> str:
    return data.decode("utf-8-sig")  # a UTF-8 byte-order mark is not part of the first ID


def parse_ids(text: str) -> list[str]:
    """One ID per line; surrounding whitespace, blank lines and `#` comments ignored."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def parse_metadata(text: str, id_column: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    """(rows by ID, problems). Ambiguous metadata is refused, never resolved by the last value (red-team J2)."""
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return {}, ["the metadata file is empty"]
    header = [h.strip() for h in rows[0]]
    problems = [f"duplicate column {h!r}" for h in sorted({h for h in header if header.count(h) > 1})]
    if id_column not in header:
        problems.append(f"column {id_column!r} not found")
    if problems:
        return {}, problems
    out: dict[str, dict[str, str]] = {}
    for n, r in enumerate(rows[1:], start=2):
        if len(r) != len(header):
            problems.append(f"row {n} has {len(r)} fields, the header has {len(header)}")
            continue
        row = {h: v.strip() for h, v in zip(header, r)}
        sid = row[id_column]
        if sid in out:
            problems.append(f"sample {sid!r} appears in more than one row")
        out[sid] = row
    return out, problems


def parse_time(text: str) -> tuple[str, Any] | None:
    """('number', exact Decimal) or ('time', aware datetime); None if neither, or not finite (red-team J3).
    Digits-only tokens are numbers; naive date-times are taken as UTC."""
    from decimal import Decimal

    t = text.strip()
    if NUMBER.fullmatch(t):
        return "number", Decimal(t)
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return "time", d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)


def analyze(root: Path, contract: Any, read: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """Counts, overlaps, time ranges and problems for one contract's splits. Problems: (status, code, details).
    Every file is read through `read`: in a check, the check's one snapshot (red-team J1)."""
    from .fsutil import escapes_root, inside

    read = read or (lambda rel: (root / rel).read_bytes())
    sp = contract.splits
    problems: list[tuple[str, str, dict[str, Any]]] = []

    def located(rel: str, code_missing: str) -> bool:
        if escapes_root(rel) or not inside(root, rel):
            problems.append(("FAIL", "R-45.path_outside", {"path": rel, "message": "resolves outside the repository"}))
            return False
        if not (root / rel).is_file():
            problems.append(("INCOMPLETE", code_missing, {"path": rel}))
            return False
        return True
    ids: dict[str, list[str]] = {}
    roles = {s.name: s.role for s in sp.sets}
    for s in sp.sets:
        if not isinstance(s.ids_file, str) or s.ids_file in SENT:
            continue  # R-03 reports unspecified split files
        if not located(s.ids_file, "R-45.split_missing"):
            continue
        try:
            ids[s.name] = parse_ids(_text(read(s.ids_file)))
        except UnicodeDecodeError:
            problems.append(("INCOMPLETE", "R-45.split_unreadable", {"path": s.ids_file, "message": "not UTF-8 text"}))
            continue
        except OSError as e:  # red-team K10: a read error names the file
            problems.append(("INCOMPLETE", "R-45.split_unreadable", {"path": s.ids_file, "message": e.strerror or str(e)}))
            continue
        if not ids[s.name]:
            problems.append(("INCOMPLETE", "R-45.empty_split", {"value": s.name, "path": s.ids_file}))
        seen: set[str] = set()
        dup: list[str] = []
        for i in ids[s.name]:
            if i in seen:
                dup.append(i)
            seen.add(i)
        if dup:
            problems.append(("FAIL", "R-45.duplicate_id", {"value": s.name, "message": ", ".join(sorted(set(dup))[:SHOW])}))
    names = sorted(ids)
    id_overlap = []
    for a_i, a in enumerate(names):
        for b in names[a_i + 1:]:
            common = sorted(set(ids[a]) & set(ids[b]))
            if common:
                id_overlap.append({"splits": [a, b], "count": len(common), "ids": common[:SHOW]})
                problems.append(("FAIL", "R-45.id_overlap", {"field": f"{a}/{b}", "value": len(common),
                                                            "message": ", ".join(common[:SHOW])}))
    checked = ["ids"]
    group_key = sp.group_key if isinstance(sp.group_key, str) and sp.group_key not in ("none", *SENT) else None
    time_key = sp.time_key if isinstance(sp.time_key, str) and sp.time_key not in ("none", *SENT) else None
    if sp.temporal and not time_key:
        problems.append(("INCOMPLETE", "R-45.time_unchecked", {"message": "temporal = true needs a time_key (and metadata)"}))
    meta = None
    if sp.metadata:
        if located(sp.metadata, "R-45.metadata_missing"):
            try:
                meta, bad = parse_metadata(_text(read(sp.metadata)), sp.id_column)
            except (UnicodeDecodeError, csv.Error, OSError) as e:
                meta, bad = None, [str(e)]
            for b in bad:
                problems.append(("FAIL", "R-45.metadata_invalid", {"path": sp.metadata, "message": b}))
            if bad:
                meta = None
    elif group_key or (time_key and sp.temporal):
        problems.append(("INCOMPLETE", "R-45.group_unchecked" if group_key else "R-45.time_unchecked",
                         {"message": "declare [splits] metadata (a CSV with one row per sample) to check groups and times"}))
    group_overlap = []
    time_range: dict[str, list[str]] = {}
    if meta is not None:
        columns = set(next(iter(meta.values()))) if meta else set()
        missing = sorted({i for n in names for i in ids[n] if i not in meta})
        if missing:
            problems.append(("INCOMPLETE", "R-45.no_metadata", {"value": len(missing), "message": ", ".join(missing[:SHOW])}))
        for key, label in ((group_key, "group"), (time_key, "time")):
            if key and meta and key not in columns:
                problems.append(("FAIL", "R-45.metadata_invalid", {"path": sp.metadata, "message": f"{label} column {key!r} not found"}))
        if group_key and group_key in columns:
            checked.append("groups")
            blank = sorted(i for n in names for i in ids[n] if i in meta and not meta[i][group_key])
            if blank:
                problems.append(("INCOMPLETE", "R-45.blank_group", {"value": len(blank), "message": ", ".join(blank[:SHOW])}))
            groups = {n: {meta[i][group_key] for i in ids[n] if i in meta and meta[i][group_key]} for n in names}
            for a_i, a in enumerate(names):
                for b in names[a_i + 1:]:
                    common = sorted(groups[a] & groups[b])
                    if common:
                        group_overlap.append({"splits": [a, b], "count": len(common), "groups": common[:SHOW]})
                        problems.append(("FAIL", "R-45.group_overlap", {"field": f"{a}/{b}", "value": len(common),
                                                                       "message": f"{group_key}: " + ", ".join(common[:SHOW])}))
        if time_key and time_key in columns:
            times: dict[str, list[tuple[Any, str]]] = {}
            bad, kinds = [], set()
            for n in names:
                for i in ids[n]:
                    if i not in meta:
                        continue
                    t = parse_time(meta[i][time_key])
                    if t is None:
                        bad.append(i)
                    else:
                        kinds.add(t[0])
                        times.setdefault(n, []).append((t[1], meta[i][time_key]))
            for n, vals in times.items():
                if len(kinds) == 1:
                    lo, hi = min(vals, key=lambda v: v[0]), max(vals, key=lambda v: v[0])
                    time_range[n] = [lo[1], hi[1]]
            if sp.temporal:
                if bad or len(kinds) > 1:
                    problems.append(("INCOMPLETE", "R-45.time_unparsed", {"value": len(bad), "message": (
                        (", ".join(bad[:SHOW]) + ": not a finite number or an ISO 8601 date; ") if bad else
                        "times mix numbers and dates; ") + DATE_HINT}))
                else:
                    checked.append("temporal order")
                    for a in names:
                        for b in names:
                            if RANK[roles[a]] < RANK[roles[b]] and times.get(a) and times.get(b):
                                if max(v for v, _ in times[a]) > min(v for v, _ in times[b]):
                                    problems.append(("FAIL", "R-45.temporal_order", {"field": f"{a}/{b}",
                                                     "message": f"a {a} sample is later than a {b} sample ({time_key})"}))
    return {"counts": {n: len(ids[n]) for n in names}, "id_overlap": id_overlap, "group_overlap": group_overlap,
            "time_range": time_range, "checked": checked, "problems": problems}


# ---------------------------------------------------------------- results matrix (slice 2)
def required_splits(contract: Any) -> list[str]:
    r = contract.results
    return list(r.splits) if r and r.splits is not None else [s.name for s in contract.splits.sets if s.role == "test"]


def methods(contract: Any) -> list[str]:
    return [b.name for b in contract.baselines] + ["candidate"]


def _finite_number(v: Any) -> bool:
    from decimal import Decimal

    from .evidence import _number

    if not _number(v):
        return False
    if isinstance(v, float):
        return v == v and v not in (float("inf"), float("-inf"))
    return not isinstance(v, Decimal) or v.is_finite()


def analyze_results(doc: Any, contract: Any, exact_thresholds: list[Any] | None = None) -> dict[str, Any]:
    """Missing cells, invalid values, undeclared entries and threshold evaluations. Values are read exactly, and
    threshold values are the literals written in the contract when given (red-team J5)."""
    from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext

    from .evidence import OutOfRange, _dec

    problems: list[tuple[str, str, dict[str, Any]]] = []
    names = {s.name for s in contract.splits.sets}
    req = required_splits(contract)
    if not req:  # red-team K9: an empty required set is never a complete matrix
        problems.append(("FAIL", "R-47.no_required_splits", {"message": "no test split, and [results] splits is not set"}))
    for sp in req:
        if sp not in names:
            problems.append(("FAIL", "R-47.unknown_split", {"value": sp, "message": "a required split the contract does not define"}))
    base_names = [b.name for b in contract.baselines]
    if "candidate" in base_names:  # red-team J4: one cell must never fill two roles
        problems.append(("FAIL", "R-47.reserved_name", {"value": "candidate", "message": "a baseline may not be named \"candidate\""}))
    for dup in sorted({b for b in base_names if base_names.count(b) > 1}):
        problems.append(("FAIL", "R-47.duplicate_method", {"value": dup}))
    mets = [d.name for d in contract.metrics.defs]
    meths = methods(contract)
    if not isinstance(doc, dict):
        return {"missing": [], "cells": {}, "thresholds": [],
                "problems": [("FAIL", "R-47.invalid", {"message": "the results file is not a table of splits"})]}

    def cell_of(sp: str, me: str, mt: str) -> Any:
        row = doc.get(sp)
        mrow = row.get(me) if isinstance(row, dict) else None
        return mrow.get(mt) if isinstance(mrow, dict) else None
    missing: list[str] = []
    cells: dict[str, str] = {}
    for sp in req:
        for me in meths:
            for mt in mets:
                v, cell = cell_of(sp, me, mt), f"{sp}/{me}/{mt}"
                if v is None:
                    missing.append(cell)
                    continue
                cells[cell] = str(v)
                if v in SENT:
                    problems.append(("INCOMPLETE" if v == "TBD" else "UNKNOWN", "sentinel", {"field": cell, "value": v}))
                elif isinstance(v, OutOfRange):
                    problems.append(("UNKNOWN", "R-47.out_of_range", {"field": cell, "message": str(v)}))
                elif not _finite_number(v):
                    problems.append(("FAIL", "R-47.not_numeric", {"field": cell, "message": f"{v!r}: not a finite number"}))
    if missing:
        problems.append(("INCOMPLETE", "R-47.missing_result", {"value": len(missing), "message": ", ".join(missing[:SHOW])}))
    extra = sorted(f"{sp}/{me}/{mt}" for sp, row in doc.items() if isinstance(row, dict) for me, mrow in row.items()
                   if isinstance(mrow, dict) for mt in mrow if sp not in names or me not in meths or mt not in mets)
    if extra:
        problems.append(("INFO", "R-47.undeclared", {"value": len(extra), "message": ", ".join(extra[:SHOW])}))
    thresholds = []
    ops = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}

    def num(v: Any) -> Decimal | None:
        return _dec(v) if _finite_number(v) else None
    for ti, t in enumerate(contract.thresholds):
        if t.value in SENT:
            continue
        literal = exact_thresholds[ti] if exact_thresholds and ti < len(exact_thresholds) and num(exact_thresholds[ti]) is not None else t.value
        for sp in req:
            label = "absolute" if t.against == "absolute" else t.against[len("baseline:"):]
            try:
                cand = num(cell_of(sp, "candidate", t.metric))
                ref = Decimal(0) if label == "absolute" else num(cell_of(sp, label, t.metric))
                if cand is None or ref is None:
                    raise ValueError("a value is missing or not a finite number")
                with localcontext(Context(prec=10000, Emax=MAX_EMAX, Emin=MIN_EMIN)):
                    diff = cand - ref
                bound = _dec(literal)
                ok = ops[t.comparator](diff, bound)
            except (ValueError, ArithmeticError) as e:  # reported, never changes the matrix verdict
                thresholds.append({"split": sp, "metric": t.metric, "against": label, "state": "not evaluable", "message": f"{sp}: {e}"})
                continue
            shown = f"candidate - {label}" if label != "absolute" else "candidate"
            thresholds.append({"split": sp, "metric": t.metric, "against": label, "state": "met" if ok else "not met",
                               "message": f"{sp}: {t.metric} {shown} = {diff:f} {t.comparator} {bound:f}"})
    return {"missing": missing, "cells": cells, "problems": problems, "thresholds": thresholds}
