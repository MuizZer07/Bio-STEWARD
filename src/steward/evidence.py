"""Evidence (v0.6.0, RELEASE_v0.6_SPEC §1): run comparison (repeatability within tolerance), change impact from run
records, and the claim-to-evidence map.

Reports keep three things apart: artifact integrity (bytes match a record), computational repeatability (a rerun
matches within declared tolerances) and scientific reproducibility (not assessed by this tool).
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, Inexact, InvalidOperation, Overflow, Underflow, localcontext
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import Field, model_validator

from .ledger import verify as lverify
from .models import Sentinel, Strict, Text

METRICS_MAX = 64 * 1024


def file_sha(root: Path, rel: str) -> str | None:
    p = root / rel
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def runs(root: Path, cfg: Any) -> dict[str, dict[str, Any]]:
    """Run id -> merged record {started fields..., outcome: {...} | None, interrupted: bool}, in ledger order."""
    out: dict[str, dict[str, Any]] = {}
    if cfg.run is None or not (root / cfg.run.ledger).is_file():
        return out
    for e in lverify(root / cfg.run.ledger).entries:
        k = e.get("kind")
        if k == "started":
            out[e["run"]] = {**e, "outcome": None, "interrupted": False}
        elif k == "outcome" and e.get("run") in out:
            out[e["run"]]["outcome"] = e
        elif k == "interrupted" and e.get("run") in out:
            out[e["run"]]["interrupted"] = True
    return out


# ---------------------------------------------------------------- repeatability
class Container(str):
    """A structural node (red-team B1, D1). Kept apart from leaf values by type, never by a key suffix, so no metric
    name can impersonate it: each JSON node has exactly one pointer."""


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """JSON pointer (RFC 6901; "" is the root) -> leaf value, or a Container naming the node's type."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {prefix: Container("object")}
        for k in sorted(obj):
            out.update(flatten(obj[k], f"{prefix}/{str(k).replace('~', '~0').replace('/', '~1')}"))
        return out
    if isinstance(obj, list):
        out = {prefix: Container("array")}
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}/{i}"))
        return out
    return {prefix: obj}


def parse_tol(spec: str) -> tuple[str, Decimal]:
    """Kept as the exact decimal the user wrote (red-team D3): no float conversion, no range limit beyond finiteness."""
    kind, _, val = spec.partition(":")
    if kind not in ("abs", "rel") or not val:
        raise ValueError(f"tolerance {spec!r} must be abs:X or rel:X")
    try:
        x = Decimal(val.strip())
    except InvalidOperation:
        raise ValueError(f"tolerance {spec!r} is not a number") from None
    if not x.is_finite() or x < 0:
        raise ValueError(f"tolerance {spec!r} must be finite and non-negative")
    return kind, x


def _number(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _dec(v: Any) -> Decimal:
    # exact for int and Decimal (fractional JSON tokens are read as Decimal, red-team F1); a float, from a record
    # written before 0.6.2, compares as its shortest round-trip decimal
    if isinstance(v, Decimal):
        return v
    return Decimal(repr(v)) if isinstance(v, float) else Decimal(v)


class OutOfRange(str):
    """A JSON number this tool cannot represent exactly (its exponent is beyond the decimal limits). It is reported,
    never guessed at (red-team G3)."""


MAX_SPAN = 10 ** 6  # the largest digit span an exact difference may need; beyond it a tolerance is not decided


def _exact_float(token: str) -> Decimal | OutOfRange:
    try:
        return Decimal(token)
    except (InvalidOperation, ValueError):
        return OutOfRange(token)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ValueError(f"duplicate key(s) {dup}")
    return dict(pairs)


def loads_exact(text: str, strict_keys: bool = False) -> Any:
    """JSON with fractional numbers kept as the exact decimal written (red-team F1). With `strict_keys`, a repeated
    key is an error, not the last value (red-team J4)."""
    if strict_keys:
        return json.loads(text, parse_float=_exact_float, object_pairs_hook=_no_duplicates)
    return json.loads(text, parse_float=_exact_float)


def pointer_value(data: bytes, source: str, pointer: str) -> Any:
    """The value at `pointer` in these bytes (JSON or TOML), read exactly. The caller hashes the same bytes, so the
    value and its evidence hash cannot come from different versions of the file (red-team G7)."""
    from .values import json_pointer

    text = data.decode("utf-8")
    doc = tomllib.loads(text, parse_float=_exact_float) if source.endswith(".toml") else loads_exact(text)
    return json_pointer(doc, pointer)


def recorded_metrics(outcome: dict[str, Any]) -> tuple[Any, str]:
    """(metrics, precision: exact | binary64 | none). Since 0.6.2 a run keeps the metrics file's text and it is read exactly; older records
    hold only JSON values, so their fractional numbers are binary floats ("binary64")."""
    text = outcome.get("metrics_text")
    if isinstance(text, str):
        try:
            return loads_exact(text), "exact"
        except ValueError:
            pass
    if outcome.get("metrics") is None:
        return None, "none"  # no metrics recorded (0.6.3, H7)
    return outcome.get("metrics"), "binary64"


def _digits(d: Decimal) -> int:
    return len(d.as_tuple().digits)


def exceeds(diff_of: tuple[Decimal, Decimal], bound_terms: tuple[Decimal, Decimal | None]) -> bool:
    """|a - b| > x (or > x * m), decided without rounding (red-team D3, E1) and without materialising a product
    outside the decimal exponent range (E2). Inputs are context-free (`copy_abs`), so the caller's Decimal context
    plays no part."""
    a, b = diff_of
    x, m = bound_terms
    lo = min(a.as_tuple().exponent, b.as_tuple().exponent)
    hi = max(a.adjusted(), b.adjusted())
    prec = max(hi - int(lo) + 2, _digits(a), _digits(b)) + 1
    ctx = Context(prec=prec, Emax=MAX_EMAX, Emin=MIN_EMIN, traps=[Inexact, InvalidOperation, Overflow, Underflow])
    with localcontext(ctx):
        diff = (a - b).copy_abs()
    if diff.is_zero():
        return False
    if m is None:
        return diff > x  # comparison is exact in any context
    if x.is_zero() or m.is_zero():
        return True
    # orders of magnitude: 10**e <= v < 10**(e+1) for e = v.adjusted(), so x*m lies in [10**(ex+em), 10**(ex+em+2))
    em = x.adjusted() + m.adjusted()
    if em >= diff.adjusted() + 1:
        return False  # bound >= 10**(ed+1) > diff
    if em + 2 <= diff.adjusted():
        return True   # bound < 10**(em+2) <= 10**ed <= diff
    # here the product's exponent is within a few orders of diff, so it is representable; compute it exactly
    ctx = Context(prec=_digits(x) + _digits(m) + 1, Emax=MAX_EMAX, Emin=MIN_EMIN,
                  traps=[Inexact, InvalidOperation, Overflow, Underflow])
    with localcontext(ctx):
        return diff > x * m


def compare(a: Any, b: Any, tol: tuple[str, Any] | None) -> str:
    """'equal', 'within', 'different' or 'not comparable'. Types are preserved and NaN/inf refused (red-team A1);
    structure is compared as structure (B1, D1); arithmetic is exact at the tolerance boundary (B1, D3)."""
    if isinstance(a, Container) or isinstance(b, Container):
        return "equal" if isinstance(a, Container) and isinstance(b, Container) and a == b else "different"
    if isinstance(a, OutOfRange) or isinstance(b, OutOfRange):  # red-team G3: reported, not guessed
        return "out of range"  # never evidence, even when the two tokens are identical (0.6.3, H4)
    if a is None or b is None:
        return "not comparable"
    if _number(a) and _number(b):
        if any((isinstance(v, float) and not math.isfinite(v)) or (isinstance(v, Decimal) and not v.is_finite()) for v in (a, b)):
            return "not comparable"
        x = None
        if tol is not None:  # red-team G6: an invalid tolerance is refused even when the values are equal
            x = tol[1] if isinstance(tol[1], Decimal) else _dec(tol[1])
            if not x.is_finite() or x < 0:
                return "not comparable"
        da, db = _dec(a), _dec(b)
        if da == db:
            return "equal"
        if tol is None or x.is_zero():
            return "different"
        span = max(da.adjusted(), db.adjusted()) - min(da.as_tuple().exponent, db.as_tuple().exponent)
        if span > MAX_SPAN:  # the exact difference would need more than MAX_SPAN digits (red-team G3)
            return "out of range"
        scale = max(da.copy_abs(), db.copy_abs())  # context-free: no rounding of the scale (red-team E1)
        try:
            return "different" if exceeds((da, db), (x, None if tol[0] == "abs" else scale)) else "within"
        except (Overflow, Underflow, InvalidOperation):  # the difference itself is beyond the decimal range (H4)
            return "out of range"
    if type(a) is not type(b):
        return "different"  # True vs 1, "1" vs 1
    return "equal" if a == b else "different"


def _show(v: Any) -> Any:
    if isinstance(v, Container):
        return f"({v})"
    if isinstance(v, OutOfRange):
        return str(v)
    if isinstance(v, Decimal):  # JSON output: a number when a float states it exactly, otherwise the exact text
        return float(v) if Decimal(repr(float(v))) == v else str(v)
    return v


def within(a: Any, b: Any, tol: tuple[str, float] | None) -> bool:
    return compare(a, b, tol) in ("equal", "within")


def diff_runs(a: dict[str, Any], b: dict[str, Any], tols: dict[str, tuple[str, float]],
              default: tuple[str, float] | None) -> dict[str, Any]:
    env: list[dict[str, Any]] = []
    for key in ("command", "code", "params", "seed", "inputs"):
        if a.get(key) != b.get(key):
            env.append({"field": key, "a": a.get(key), "b": b.get(key)})
    for key in ("head", "dirty", "diff_sha256"):
        if (a.get("git") or {}).get(key) != (b.get("git") or {}).get(key):
            env.append({"field": f"git.{key}", "a": (a.get("git") or {}).get(key), "b": (b.get("git") or {}).get(key)})
    ea, eb = a.get("environment") or {}, b.get("environment") or {}
    for key in sorted(set(ea) | set(eb)):
        if ea.get(key) != eb.get(key):
            env.append({"field": f"environment.{key}", "a": ea.get(key), "b": eb.get(key)})
    oa, ob = a["outcome"] or {}, b["outcome"] or {}
    results: list[dict[str, Any]] = []
    (ra, pa), (rb, pb) = recorded_metrics(oa), recorded_metrics(ob)
    ma = flatten(ra) if ra is not None else {}
    mb = flatten(rb) if rb is not None else {}
    if (ra is None) != (rb is None):  # metrics recorded for one run only: not comparable, never silently skipped
        results.append({"pointer": "(metrics)", "a": "recorded" if ra is not None else None, "b": "recorded" if rb is not None else None,
                        "tolerance": None, "state": "not comparable", "within": False})
    for ptr in (sorted(set(ma) | set(mb)) if ra is not None and rb is not None else []):
        tol = tols.get(ptr, default)
        # both runs recorded metrics: a key present on one side only is a structural difference (red-team B1)
        state = compare(ma[ptr], mb[ptr], tol) if ptr in ma and ptr in mb else "different"
        leaf = not isinstance(ma.get(ptr), Container) and not isinstance(mb.get(ptr), Container)
        results.append({"pointer": ptr or "(root)", "a": _show(ma.get(ptr)), "b": _show(mb.get(ptr)),
                        "tolerance": None if tol is None else f"{tol[0]}:{tol[1]}", "state": state,
                        "within": state in ("equal", "within"), "leaf": leaf})
    outs_a, outs_b = oa.get("outputs") or {}, ob.get("outputs") or {}
    for path in sorted(set(outs_a) | set(outs_b)):
        if path in (oa.get("metrics_file"), ob.get("metrics_file")) and (ra is not None or rb is not None):
            continue  # compared numerically above
        state = compare(outs_a.get(path), outs_b.get(path), None)  # a missing hash on either side is not evidence
        results.append({"output": path, "a": outs_a.get(path), "b": outs_b.get(path), "state": state, "within": state == "equal", "leaf": True})
    finished = (oa.get("status") == "finished") and (ob.get("status") == "finished")
    comparable = [r for r in results if r["state"] not in ("not comparable", "out of range")]
    evidence = [r for r in comparable if r.get("leaf")]  # red-team D2: structure alone is not evidence
    if not finished or not evidence or len(comparable) < len(results):
        verdict = "incomplete" if all(r["within"] for r in comparable) else "not repeatable"
    else:
        verdict = "repeatable" if all(r["within"] for r in results) else "not repeatable"
    return {"verdict": verdict, "repeatable": verdict == "repeatable", "compared": len(comparable), "evidence": len(evidence),
            "metrics_precision": {"a": pa, "b": pb},
            "not_comparable": len(results) - len(comparable), "finished": finished,
            "results": results, "environment_differences": env}


# ---------------------------------------------------------------- change impact
def impact(root: Path, cfg: Any) -> dict[str, Any]:
    recs = runs(root, cfg)
    latest: dict[str, dict[str, Any]] = {}
    for r in recs.values():
        o = r["outcome"]
        if o and o.get("status") == "finished":
            for path in (o.get("outputs") or {}):
                latest[path] = r
    items = []
    stale_outputs = set()
    for path, r in sorted(latest.items()):
        changed_inputs = [p for p, h in (r.get("inputs") or {}).items() if file_sha(root, p) != h]
        changed_code = [p for p, h in (r.get("code") or {}).items() if file_sha(root, p) != h]
        own = file_sha(root, path) != r["outcome"]["outputs"][path]
        state = "stale" if (changed_inputs or changed_code) else ("changed since run" if own else "current")
        if state != "current":
            stale_outputs.add(path)
        items.append({"output": path, "run": r["run"], "state": state, "inputs_changed": changed_inputs, "code_changed": changed_code})
    downstream = []
    for pname, pp in sorted(getattr(cfg, "paper", {}).items()):
        vpath = root / pp.rel(pp.values)
        if vpath.is_file():
            try:
                data = tomllib.loads(vpath.read_text(encoding="utf-8"))
            except (ValueError, RecursionError):
                data = {}
            for key, d in sorted((data.get("values") or {}).items()):
                if isinstance(d, dict) and d.get("source") in stale_outputs:
                    downstream.append({"paper": pname, "value": key, "source": d["source"]})
        dpath = root / pp.rel(pp.displays)
        if dpath.is_file():
            try:
                ddata = tomllib.loads(dpath.read_text(encoding="utf-8"))
            except (ValueError, RecursionError):
                ddata = {}
            for dname, d in sorted((ddata.get("displays") or {}).items()):
                hit = [i for i in (d.get("inputs") or []) if i in stale_outputs] if isinstance(d, dict) else []
                if hit:
                    downstream.append({"paper": pname, "display": dname, "inputs": hit})
    from .fsutil import iter_repo_files

    result_like = [p for p in iter_repo_files(root) if p.startswith(("results/", "outputs/"))]
    covered = sum(1 for p in result_like if p in latest)
    return {"outputs": items, "downstream": downstream,
            "coverage": f"{covered} of {len(result_like)} files under results/ and outputs/ have run records; "
                        "impact through undeclared dependencies is not traced"}


# ---------------------------------------------------------------- claim map
class Claim(Strict):
    id: Text
    text: Text
    where: Union[Text, Sentinel] = "TBD"
    value: Union[int, float, Sentinel]  # an integer stays an integer (red-team E3)
    tolerance: Union[int, float] = 0  # R-40 refuses negative and non-finite values with one diagnostic (I3)
    source: str | None = None
    pointer: str | None = None
    value_key: str | None = None
    runs: list[str] = Field(default_factory=list)
    contract: str | None = None

    @model_validator(mode="after")
    def _where_value(self) -> "Claim":
        if (self.source is None) == (self.value_key is None):
            raise ValueError("give exactly one of source (+ pointer) or value_key")
        if self.source is not None and self.pointer is None:
            raise ValueError("source needs a JSON pointer")
        return self


class ClaimsFile(Strict):
    schema_: Literal["steward.claims/0.1"] = Field(alias="schema")
    claims: list[Claim] = Field(default_factory=list)


def read_pointer(root: Path, source: str, pointer: str) -> Any:
    return pointer_value((root / source).read_bytes(), source, pointer)
