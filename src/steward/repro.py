"""The reproduction gate, lean (0.9.0 B2, REQ-008; RELEASE_v0.9.0_SPEC §2.2).

A contract (`steward.repro/0.1`) names a manifest of reference outputs, `{relative path: sha256}`, hashed in a
canonical form this module owns: the file's bytes, or for `json-sorted` the JSON with the volatile pointers removed
and the keys sorted. `steward repro check ID --work DIR` compares re-derived files with it and appends one entry to an
append-only ledger. It does not run the replay (that stays with `steward run`). R-52 asks for a passing entry on the
current tree.

A file that differs is compared value by value against the reference copy (the contract's `reference` folder), with
the 0.6.2 tolerance grammar, only when a tolerance is declared; otherwise it is a mismatch.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import Strict, Text

MAX_LISTED = 50


class Compare(Strict):
    default: str = "exact"                                   # exact | abs:X | rel:X
    pointers: dict[str, str] = Field(default_factory=dict)   # JSON pointer -> abs:X | rel:X (every JSON file)


class ReproContract(Strict):
    schema_: Literal["steward.repro/0.1"] = Field(alias="schema")
    id: Text = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    manifest: str
    reference: str | None = None
    canonical: Literal["bytes", "json-sorted"] = "bytes"
    volatile: list[str] = Field(default_factory=list)
    compare: Compare = Field(default_factory=Compare)


class ReproError(ValueError):
    pass


def load(root: Path, rel: str) -> ReproContract:
    from .fsutil import escapes_root

    c = ReproContract.model_validate(tomllib.loads((root / rel).read_text(encoding="utf-8")))
    for p in (c.manifest, c.reference):
        if p is not None and escapes_root(p):
            raise ReproError(f"{rel}: {p} must stay inside the repository")
    return c


def contracts(root: Path, cfg: Any) -> dict[str, tuple[str, ReproContract | None, str | None]]:
    """id (or the file, when it does not parse) -> (file, contract or None, error)."""
    from .fsutil import matching_files

    out: dict[str, tuple[str, ReproContract | None, str | None]] = {}
    for rel in matching_files(root, cfg.repro.contracts):
        try:
            c = load(root, rel)
        except (OSError, ValueError, ValueError, RecursionError) as e:
            out[rel] = (rel, None, str(e).splitlines()[0][:200])
            continue
        if c.id in out:  # Q13: a second contract with the same id is an error, never a silent replacement
            out[rel] = (rel, None, f"duplicate contract id {c.id!r} (also in {out[c.id][0]})")
            continue
        out[c.id] = (rel, c, None)
    return out


def _drop(doc: Any, pointer: str) -> None:
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.lstrip("/").split("/")] if pointer else []
    cur = doc
    for p in parts[:-1]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return
    if parts and isinstance(cur, dict):
        cur.pop(parts[-1], None)


def _json(data: bytes, volatile: list[str]) -> Any:
    from .evidence import loads_exact

    doc = loads_exact(data.decode("utf-8"))
    for p in volatile:
        _drop(doc, p)
    return doc


def _canon(v: Any) -> str:
    """Sorted, compact JSON in which an exact decimal stays a number token, so 0.5 and "0.5" differ (review Q13)."""
    if isinstance(v, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + _canon(v[k]) for k in sorted(v)) + "}"
    if isinstance(v, list):
        return "[" + ",".join(_canon(x) for x in v) + "]"
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, str) and type(v) is not str:  # OutOfRange tokens keep their text, as numbers
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def canonical(rel: str, data: bytes, c: ReproContract) -> bytes:
    if c.canonical == "json-sorted" and rel.endswith(".json"):
        return _canon(_json(data, c.volatile)).encode("utf-8")
    return data


def digest(rel: str, data: bytes, c: ReproContract) -> str:
    return hashlib.sha256(canonical(rel, data, c)).hexdigest()


def files_under(d: Path) -> list[str]:
    from .fsutil import iter_repo_files

    return list(iter_repo_files(d))


def write_manifest(root: Path, c: ReproContract, source: Path) -> dict[str, str]:
    files = {rel: digest(rel, (source / rel).read_bytes(), c) for rel in files_under(source)}
    if not files:
        raise ReproError(f"{source} holds no files")
    from .fsutil import safe_write

    safe_write(root, c.manifest, (json.dumps({"schema": "steward.repro_manifest/0.1", "contract": c.id, "files": files},
                                             indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return files


def read_manifest(root: Path, c: ReproContract, raw: bytes | None = None) -> dict[str, str]:
    doc = json.loads((raw if raw is not None else (root / c.manifest).read_bytes()).decode("utf-8"))
    files = doc.get("files") if isinstance(doc, dict) and "files" in doc else doc
    if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
        raise ReproError(f"{c.manifest} is not a {{path: sha256}} manifest")
    if not files:  # Q13: nothing to compare is never a reproduction
        raise ReproError(f"{c.manifest} lists no files")
    return files


def _values(root: Path, c: ReproContract, rel: str, work_bytes: bytes, manifest: dict[str, str]) -> list[dict[str, Any]] | None:
    """Per-pointer differences beyond tolerance, or None when no value comparison is possible."""
    from .evidence import Container, compare, flatten, parse_tol

    if c.reference is None or not rel.endswith(".json"):
        return None
    ref_path = root / c.reference / rel
    if not ref_path.is_file() or ref_path.is_symlink():
        return None
    try:  # Q13, R9: the reference bytes compared are the bytes hashed against the manifest
        ref_bytes = ref_path.read_bytes()
        want = manifest.get(rel)
        if want is None or digest(rel, ref_bytes, c) != want:
            return [{"path": rel, "pointer": "(reference)", "state": "reference changed since the manifest"}]
    except (OSError, ValueError, ReproError):
        return None
    try:
        a = flatten(_json(ref_bytes, c.volatile))
        b = flatten(_json(work_bytes, c.volatile))
    except (ValueError, UnicodeDecodeError):
        return None
    default = None if c.compare.default == "exact" else parse_tol(c.compare.default)
    tols = {p: parse_tol(t) for p, t in c.compare.pointers.items()}
    out = []
    for ptr in sorted(set(a) | set(b)):
        if isinstance(a.get(ptr), Container) and isinstance(b.get(ptr), Container):
            continue
        state = compare(a[ptr], b[ptr], tols.get(ptr, default)) if ptr in a and ptr in b else "different"
        if state not in ("equal", "within"):
            out.append({"path": rel, "pointer": ptr or "(root)", "state": state})
    return out


def check(root: Path, c: ReproContract, work: Path) -> dict[str, Any]:
    """{result: pass | fail, files, mismatches[]} for the work folder against the contract's manifest."""
    raw_manifest = (root / c.manifest).read_bytes()  # R9: one read, hashed and used
    manifest = read_manifest(root, c, raw_manifest)
    mismatches: list[dict[str, Any]] = []
    within = 0
    for rel, want in sorted(manifest.items()):
        p = work / rel
        if p.is_symlink() or not p.is_file():
            mismatches.append({"path": rel, "state": "missing"})
            continue
        try:
            data = p.read_bytes()
            got = digest(rel, data, c)
        except (ValueError, UnicodeDecodeError):
            mismatches.append({"path": rel, "state": "unreadable"})
            continue
        if got == want:
            continue
        values = _values(root, c, rel, data, manifest)
        exact = c.compare.default == "exact" and not c.compare.pointers
        if values == [] and not exact:
            within += 1
            continue
        # exact: the canonical hash decides; equal values in another notation still differ
        mismatches += values if values else [{"path": rel, "state": "different"}]
    return {"result": "fail" if mismatches else "pass", "files": len(manifest), "within_tolerance": within,
            "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "mismatches": mismatches[:MAX_LISTED], "mismatch_count": len(mismatches)}


def ledger(root: Path, cfg: Any):
    from .ledger import Ledger

    return Ledger(root / cfg.repro.ledger, "repro", cfg.steward.repo_id, base=root)


def git_ids(root: Path) -> tuple[str | None, str | None]:
    from .fsutil import git_run

    c = git_run(root, "rev-parse", "HEAD", "HEAD^{tree}", text=True, timeout=10)
    if c.returncode != 0:
        return None, None
    lines = c.stdout.split()
    return (lines[0], lines[1]) if len(lines) == 2 else (None, None)


def sha_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
