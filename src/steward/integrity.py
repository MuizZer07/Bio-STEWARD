"""Research integrity (v0.5.0, RELEASE_v0.5_SPEC): frozen snapshots, amendments, dataset roles and seals.

Everything is recorded in a hash-chained ledger. Freezing a confirmatory design, applying an amendment and unsealing
held-out data require a verified, single-use signed authorization naming the exact object; anyone may propose an
amendment. `steward run` refuses sealed inputs. Reads outside `steward run` are out of coverage and are detected later
only where inputs are declared (run records, values registries).
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .fsutil import glob_match, iter_repo_files
from .ledger import Ledger, verify as lverify, verify_bytes
from .models import Identifier, Sentinel, Strict, Text

ROLES = ("development", "sealed", "spent", "census-only")


Role = Literal["development", "sealed", "spent", "census-only", "reserved"]


class DatasetDef(Strict):
    role: Role
    identifier: Union[Identifier, Sentinel]
    paths: list[Text] = Field(default_factory=list)
    sha256: Union[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], Sentinel] = "TBD"
    consumers: dict[str, Role] = Field(default_factory=dict)  # REQ-007: the role for each study or paper


class DatasetsFile(Strict):
    schema_: Literal["steward.datasets/0.1"] = Field(alias="schema")
    datasets: dict[str, DatasetDef] = Field(default_factory=dict)


class IntegrityError(Exception):
    pass


def _canon_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha(root: Path, rel: str) -> str | None:
    p = root / rel
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def cohort(root: Path, rel: str) -> dict[str, Any]:
    """An ID list as a set: sorted, unique, hashed. The IDs themselves are not stored in the ledger."""
    p = root / rel
    if not p.is_file():
        return {"sha256": None, "count": 0}
    ids = sorted({l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()})
    return {"sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(), "count": len(ids), "ids_sha": [
        hashlib.sha256(i.encode()).hexdigest()[:16] for i in ids]}


def params(root: Path, rel: str) -> dict[str, Any]:
    p = root / rel
    if not p.is_file():
        raise IntegrityError(f"parameter file {rel} not found")
    text = p.read_text(encoding="utf-8")
    data = tomllib.loads(text) if rel.endswith(".toml") else json.loads(text)
    flat: dict[str, Any] = {}

    def walk(prefix: str, v: Any) -> None:
        if isinstance(v, dict):
            for k in sorted(v):
                walk(f"{prefix}.{k}" if prefix else k, v[k])
        else:
            flat[prefix] = v
    walk("", data)
    return flat


def snapshot(root: Path, files: list[str], cohorts: list[str], params_file: str | None, contract: str | None) -> dict[str, Any]:
    snap = {
        "files": {f: file_sha(root, f) for f in sorted(files)},
        "cohorts": {c: cohort(root, c) for c in sorted(cohorts)},
        "params": {"file": params_file, "values": params(root, params_file) if params_file else {}},
        "contract": contract,
    }
    missing = [f for f, h in snap["files"].items() if h is None] + [c for c, v in snap["cohorts"].items() if v["sha256"] is None]
    if missing:
        raise IntegrityError(f"missing files: {missing}")
    snap["hash"] = _canon_hash({k: v for k, v in snap.items()})
    return snap


def recompute(root: Path, snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "files": {f: file_sha(root, f) for f in snap["files"]},
        "cohorts": {c: cohort(root, c) for c in snap["cohorts"]},
        "params": {"file": snap["params"]["file"],
                   "values": params(root, snap["params"]["file"]) if snap["params"]["file"] and (root / snap["params"]["file"]).is_file() else {}},
        "contract": snap["contract"],
    }


def differences(frozen: dict[str, Any], now: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f, h in frozen["files"].items():
        if now["files"].get(f) != h:
            out.append({"code": "protocol.drift", "path": f})
    for c, v in frozen["cohorts"].items():
        cur = now["cohorts"].get(c, {})
        if cur.get("sha256") != v["sha256"]:
            before, after = set(v.get("ids_sha", [])), set(cur.get("ids_sha", []))
            out.append({"code": "cohort.changed", "path": c,
                        "message": f"{len(after - before)} added, {len(before - after)} removed (IDs not shown)"})
    fv, nv = frozen["params"]["values"], now["params"]["values"]
    for k in sorted(set(fv) | set(nv)):
        if fv.get(k) != nv.get(k):
            out.append({"code": "params.changed", "field": k, "message": f"{fv.get(k)!r} -> {nv.get(k)!r}"})
    return out


# ---------------------------------------------------------------- ledger state
@dataclass
class State:
    frozen: dict[str, dict[str, Any]]  # name -> latest snapshot entry (freeze or amend)
    proposals: dict[str, dict[str, Any]]  # name -> latest unapplied proposal
    roles: dict[str, tuple[str, dict[str, Any]]]  # dataset -> (role, entry)
    entries: list[dict[str, Any]]
    intact: bool = True  # R21: the read these roles came from had no error and no torn tail


def state(root: Path, cfg: Any, *, read=None) -> State:
    v = (lverify(root / cfg.integrity.ledger) if read is None
         else verify_bytes(read(cfg.integrity.ledger) or b""))
    st = State({}, {}, {}, v.entries, not (v.errors or v.torn_tail))
    for e in v.entries:
        k = e.get("kind")
        if k in ("freeze", "amend"):
            st.frozen[e["name"]] = e
            st.proposals.pop(e["name"], None)
        elif k == "proposal":
            st.proposals[e["name"]] = e
        elif k == "seal":
            st.roles[e["dataset"]] = ("sealed", e)
        elif k == "unseal":
            st.roles[e["dataset"]] = ("spent", e)
    return st


def ledger(root: Path, cfg: Any) -> Ledger:
    return Ledger(root / cfg.integrity.ledger, "integrity", cfg.steward.repo_id)


def load_datasets(root: Path, cfg: Any) -> DatasetsFile | None:
    p = root / cfg.integrity.datasets
    if not p.is_file():
        return None
    return DatasetsFile.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))


def dataset_files(root: Path, d: DatasetDef) -> list[str]:
    return [r for r in iter_repo_files(root) if any(glob_match(r, p) for p in d.paths)]


def dataset_hash(root: Path, d: DatasetDef) -> str | None:
    files = dataset_files(root, d)
    if not files:
        return None
    return _canon_hash([[f, file_sha(root, f)] for f in files])


def sealed_owner(root: Path, cfg: Any, rel: str, *, read=None, hash_file=None) -> str | None:
    """The sealed dataset a path belongs to (by path pattern or by content hash), or None."""
    if getattr(cfg, "integrity", None) is None:
        return None
    if read is None:
        try:
            ds = load_datasets(root, cfg)
        except Exception:
            return None
    else:
        data = read(cfg.integrity.datasets)
        ds = DatasetsFile.model_validate(tomllib.loads(data.decode("utf-8"))) if data is not None else None
    if ds is None:
        return None
    st = state(root, cfg, read=read)
    # R21: the same resolution as `access`: the ledger's latest role wins; the declared role counts without one
    sealed = {n for n, (role, _) in st.roles.items() if role == "sealed"}
    sealed |= {n for n, d in ds.datasets.items() if d.role == "sealed" and n not in st.roles}
    if not st.intact:
        sealed |= set(ds.datasets)  # an unusable ledger: every dataset is treated as sealed
    def digest(path: str) -> str | None:
        if hash_file is not None:
            return hash_file(path)
        if read is None:
            return file_sha(root, path)
        data = read(path)
        return hashlib.sha256(data).hexdigest() if data is not None else None

    h = digest(rel)
    for n in sorted(sealed):
        d = ds.datasets.get(n)
        if d is None:
            continue
        if any(glob_match(rel, p) for p in d.paths):
            return n
        if h and any(h == digest(f) for f in dataset_files(root, d)):
            return n
    return None


def access(root: Path, cfg: Any, name: str, consumer: str, use: str) -> tuple[bool, str]:
    """May `consumer` use dataset `name` for `use` (develop | confirm | metadata)? (REQ-007)
    Spent anywhere is never confirmatory again; sealed and reserved deny develop and confirm; census-only allows
    metadata only; development data never confirms."""
    ds = load_datasets(root, cfg)
    if ds is None or name not in ds.datasets:
        raise IntegrityError(f"no dataset {name!r} in {cfg.integrity.datasets}")
    st = state(root, cfg)  # R21: one read, verified, is the source of the roles
    if not st.intact:  # Q33: an unusable ledger gives no answer, never an "allow"
        raise IntegrityError(f"{cfg.integrity.ledger} is not intact: access cannot be decided")
    d = ds.datasets[name]
    ledger_role = st.roles.get(name, (None, None))[0]
    role = d.consumers.get(consumer, ledger_role or d.role)
    # Q33: an active seal (the ledger's, or the declared role) holds for every consumer, as the run input check does
    if ledger_role == "sealed" or (ledger_role is None and d.role == "sealed"):
        role = "sealed"
    spent = "spent" in (d.role, ledger_role, *d.consumers.values())
    if use == "metadata":
        return True, f"{role}: metadata may be read"
    if role == "census-only":
        return False, "census-only: metadata only, never the data"
    if role in ("sealed", "reserved"):
        return False, f"{role} for {consumer}" + (": unseal it with a signed authorization first" if role == "sealed"
                                                   else ": kept for a later design")
    if use == "confirm":
        if spent:
            who = [c for c, r in d.consumers.items() if r == "spent"]
            return False, "spent" + (f" for {', '.join(who)}" if who else "") + ": never confirmatory again"
        if role == "development":
            return False, "development data cannot confirm"
    return True, f"{role}: {use} allowed"


def decision_logs(root: Path, cfg: Any) -> list[str]:
    return cfg.integrity.decision_logs(root) if getattr(cfg, "integrity", None) else \
        [f"{cfg.paths.records.rstrip('/')}/DECISIONS.md"]


def decision_heading(root: Path, cfg: Any, text: str | None) -> str | None:
    """The decisions log that holds an entry whose heading is exactly `## <text>`, or None. A mention in a body, a
    proposal or a quote does not count (review of 0.9.0, Q23, Q24, Q30)."""
    if not text or not text.strip():
        return None
    want = "## " + text.strip()
    for rel in decision_logs(root, cfg):
        p = root / rel
        if not p.is_file() or p.is_symlink():
            continue
        fenced = False
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith(("```", "~~~")):  # R13: a heading in a code example is not an entry
                fenced = not fenced
            elif not fenced and line.rstrip() == want:
                return rel
    return None


def decision_present(root: Path, cfg: Any, ref: str | None) -> bool:
    if not ref:
        return False
    return any((root / p).is_file() and ref in (root / p).read_text(encoding="utf-8")
               for p in cfg.integrity.decision_logs(root))



# ---------------------------------------------------------------- decisions log format (0.8.1, AR-06)
_HEADING = __import__("re").compile(r"^## (\d{4}-\d{2}-\d{2}): \S")


def decision_entries(text: str) -> list[tuple[int, str, list[str]]]:
    """(line, heading, body lines) for each `## YYYY-MM-DD: title` entry. The template's own placeholder heading
    (`## YYYY-MM-DD: …`) is the example, not an entry."""
    out: list[tuple[int, str, list[str]]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            if line.startswith("## YYYY-MM-DD"):
                out.append((n, "", []))  # the template's example: skipped below
                continue
            out.append((n, line, []))
        elif out:
            out[-1][2].append(line)
    return [e for e in out if e[1]]


def entry_fields(body: list[str]) -> dict[str, str]:
    """Each `- **Field:**` with its text: the rest of its line plus the indented continuation lines and nested list
    items below it, up to the next field (DEF-021). The first occurrence of a field counts."""
    import re

    fields: dict[str, str] = {}
    cur: str | None = None
    for line in body:
        m = re.match(r"^- \*\*([A-Za-z][\w ]*):\*\*\s?(.*)$", line)
        if m:
            cur = m.group(1)
            fields.setdefault(cur, m.group(2).strip())
            continue
        if cur is not None and (line.startswith((" ", "\t")) or not line.strip()):
            if line.strip() and fields.get(cur) is not None:
                fields[cur] = (fields[cur] + " " + line.strip()).strip()
            continue
        cur = None  # a line at the left margin that is not a field ends the block
    return fields


def entry_problems(heading: str, body: list[str]) -> list[str]:
    import re

    problems = []
    if not _HEADING.match(heading):
        problems.append("the heading is not `## YYYY-MM-DD: title`")
    fields = entry_fields(body)
    quote = fields.get("Quote", "")
    if not re.match(r'^("|“|not recorded verbatim \(source: .+\))', quote, re.S):
        problems.append('no quote (`- **Quote:** "…"`, or `not recorded verbatim (source: …)`)')
    for part in ("Decision", "Consequences"):
        if not fields.get(part, "").strip():
            problems.append(f"no `- **{part}:**` line")
    return problems
