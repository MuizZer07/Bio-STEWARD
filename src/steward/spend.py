"""Spend guard (v0.4.2, RELEASE_v0.4_SPEC §4): paid calls routed through `guard()` are refused past the cap, without a
verified `spend` authorization, after its expiry, at an unknown price (unless the authorization allows unknown prices
with a call ceiling), and always when STEWARD_NO_PAID_CALLS=1.

Coverage: only calls routed through this guard. Direct SDK calls are not seen. Costs are estimates from the configured
price table; the provider's bill is authoritative, and the ledger keeps estimates and actual usage apart.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import authorize as az
from .ledger import Ledger, verify as lverify


class SpendRefused(Exception):
    pass


@dataclass
class Budget:
    currency: str | None
    amount: float | None
    calls: int | None
    unknown_price_ok: bool


def parse_budget(text: str) -> Budget:
    """'USD 50', 'USD 50 calls=200', 'unknown-price calls=20' (the authorization's budget field)."""
    m = re.match(r"^\s*(?:(?P<cur>[A-Z]{3})\s+(?P<amt>\d+(?:\.\d+)?))?\s*(?P<unk>unknown-price)?\s*(?:calls=(?P<calls>\d+))?\s*$", text or "")
    if not m or not (m.group("amt") or m.group("unk")):
        raise SpendRefused(f"authorization budget {text!r} is not '<CUR> <amount> [calls=N]' or 'unknown-price calls=N'")
    if m.group("unk") and not (m.group("calls") and int(m.group("calls")) > 0):
        # red-team B2: an unpriced call has no currency bound, so a finite call ceiling is the only limit
        raise SpendRefused("an unknown-price budget needs a finite call ceiling: 'unknown-price calls=N' with N > 0")
    return Budget(m.group("cur"), float(m.group("amt")) if m.group("amt") else None,
                  int(m.group("calls")) if m.group("calls") else None, bool(m.group("unk")))


def _ledger(root: Path, cfg: Any) -> Ledger:
    return Ledger(root / cfg.spend.ledger, "spend", cfg.steward.repo_id)


def price(cfg: Any, model: str, tokens_in: int, tokens_out: int, *,
          cache_read: int = 0, cache_write: int = 0) -> float | None:
    """Estimate cost with uncached input and optional, separately priced cache tokens."""
    if cfg.spend is None:
        return None
    p = cfg.spend.prices.get(model)
    if p is None:
        return None
    if (cache_read and p.cache_read_per_1k is None) or (cache_write and p.cache_write_per_1k is None):
        return None
    return (tokens_in / 1000 * p.input_per_1k + tokens_out / 1000 * p.output_per_1k
            + cache_read / 1000 * (p.cache_read_per_1k or 0) + cache_write / 1000 * (p.cache_write_per_1k or 0))


def totals(root: Path, cfg: Any, nonce: str | None = None, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if entries is None:
        entries = lverify(root / cfg.spend.ledger).entries
    est = {e["call"]: e for e in entries if e.get("kind") == "estimate" and (nonce is None or e.get("nonce") == nonce)}
    act = {e["call"]: e for e in entries if e.get("kind") == "actual" and e.get("call") in est}
    committed = 0.0
    for call, e in est.items():
        cost = act[call]["cost"] if call in act else e["est_cost"]
        committed += cost or 0.0
    return {"calls": len(est), "committed": round(committed, 6),
            "actual": round(sum((a["cost"] or 0.0) for a in act.values()), 6),
            "unknown_cost_calls": sum(1 for c, e in est.items() if (act.get(c, e).get("cost", e.get("est_cost"))) is None)}


def parse_scope(scope: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tok in (scope or "").split():
        k, sep, v = tok.partition("=")
        if sep:
            out[k] = [x for x in v.split(",") if x]
    return out


def guard(root: Path, cfg: Any, model: str, est_in: int, est_out: int, authorization: str,
          now: datetime | None = None, task: str | None = None) -> str:
    """Check before a paid call; record the estimate and return a call id. Raises SpendRefused."""
    if os.environ.get("STEWARD_NO_PAID_CALLS") == "1":
        raise SpendRefused("STEWARD_NO_PAID_CALLS=1: paid calls are refused (tests and verification scripts)")
    if getattr(cfg, "spend", None) is None:
        raise SpendRefused("no [spend] table in steward.toml")
    if getattr(cfg, "policy", None) is None:
        raise SpendRefused("spend needs [policy] for signed authorizations")
    try:
        v = az.verify(root, cfg, authorization, action="spend", now=now, require_pinned=True)
    except az.AuthError as e:
        raise SpendRefused(f"authorization {authorization}: {e.step}: {e.message}") from e
    budget = parse_budget(v.payload["budget"])
    nonce = v.payload["nonce"]
    scope = parse_scope(v.payload["scope"])
    if "models" not in scope:  # red-team A2: a spend authorization names what it covers
        raise SpendRefused("the authorization's scope names no models (use --scope models=a,b [task=X])")
    if model not in scope["models"]:
        raise SpendRefused(f"model {model!r} is outside the authorized scope {scope['models']}")
    if "task" in scope and task not in scope["task"]:
        raise SpendRefused(f"task {task!r} is outside the authorized scope {scope['task']}")
    if budget.currency and budget.currency != cfg.spend.currency:
        raise SpendRefused(f"authorization is in {budget.currency}, ledger in {cfg.spend.currency}")
    cost = price(cfg, model, est_in, est_out)
    if cost is None and not budget.unknown_price_ok:
        raise SpendRefused(f"no price for model {model!r} in [spend.prices]; unknown cost is refused")
    limit_auth = budget.amount if budget.amount is not None else float("inf")
    call = uuid.uuid4().hex[:12]

    def decide(entries: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        # Decided and reserved under the ledger lock: concurrent workers cannot spend the same remainder twice.
        t = totals(root, cfg, nonce, entries)
        if budget.calls is not None and t["calls"] >= budget.calls:
            raise SpendRefused(f"call ceiling reached ({budget.calls})")
        overall = totals(root, cfg, None, entries)
        if cost is not None and t["committed"] + cost > limit_auth:
            raise SpendRefused(f"authorized budget exceeded: {t['committed'] + cost:.4f} > {limit_auth:g} {cfg.spend.currency}")
        if cost is not None and overall["committed"] + cost > cfg.spend.cap:
            raise SpendRefused(f"repository cap exceeded: {overall['committed'] + cost:.4f} > {cfg.spend.cap:g} {cfg.spend.currency}")
        return "estimate", {"call": call, "model": model, "task": task, "est_in": est_in, "est_out": est_out,
                            "est_cost": None if cost is None else round(cost, 6), "tag": authorization,
                            "nonce": nonce, "principal": v.principal, "trust_source": v.trust_source}

    _ledger(root, cfg).transaction(decide)
    return call


def record(root: Path, cfg: Any, call: str, tokens_in: int, tokens_out: int, request_id: str | None = None) -> dict[str, Any]:
    v = lverify(root / cfg.spend.ledger)
    est = next((e for e in v.entries if e.get("kind") == "estimate" and e["call"] == call), None)
    if est is None:
        raise SpendRefused(f"unknown call id {call}")
    cost = price(cfg, est["model"], tokens_in, tokens_out)
    return _ledger(root, cfg).append("actual", {"call": call, "model": est["model"], "tokens_in": tokens_in,
                                                "tokens_out": tokens_out, "cost": None if cost is None else round(cost, 6),
                                                "request_id": request_id})


def entry_time(e: dict[str, Any]) -> datetime:
    return datetime.strptime(e["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
