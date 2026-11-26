"""Power and feasibility planning from development effects (0.9.0, REQ-010).

Per-unit effects measured on development data are resampled (with replacement) at each declared size `n` and each
shrink factor, and a one-sample test of "mean effect = 0" is run on every resample:

- `sign-flip`: the sign-flip permutation test of the mean (two-sided, Monte Carlo flips);
- `bootstrap`: the percentile bootstrap interval of the mean excludes 0.

Power is the share of resamples where the test rejects at `alpha`. Everything is seeded, so the table is repeatable.
The estimate is only as good as the development effects: it plans a design; it does not establish one.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

FLIPS = 200
BOOT = 200


def read_effects(path: Path) -> list[float]:
    text = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
        vals = doc if isinstance(doc, list) else doc.get("effects", [])
    except ValueError:
        vals = [l.split(",")[-1] for l in text.splitlines() if l.strip()]
    out = [float(v) for v in vals]
    if len(out) < 2:
        raise ValueError("need at least two development effects")
    return out


def _sign_flip(xs: list[float], alpha: float, rng: random.Random) -> bool:
    obs = abs(sum(xs))
    hits = 1
    for _ in range(FLIPS):
        if abs(sum(x if rng.random() < 0.5 else -x for x in xs)) >= obs - 1e-12:
            hits += 1
    return hits / (FLIPS + 1) <= alpha


def _bootstrap(xs: list[float], alpha: float, rng: random.Random) -> bool:
    n = len(xs)
    means = sorted(sum(rng.choice(xs) for _ in range(n)) / n for _ in range(BOOT))
    lo, hi = means[int(BOOT * alpha / 2)], means[min(BOOT - 1, int(BOOT * (1 - alpha / 2)))]
    return lo > 0 or hi < 0


def table(effects: list[float], test: str, alpha: float, shrinks: list[float], sizes: list[int], reps: int,
          seed: int) -> list[dict[str, Any]]:
    fn = _sign_flip if test == "sign-flip" else _bootstrap
    rows = []
    for n in sizes:
        for s in shrinks:
            rng = random.Random(f"{seed}:{n}:{s}")
            scaled = [e * s for e in effects]
            hits = sum(fn([rng.choice(scaled) for _ in range(n)], alpha, rng) for _ in range(reps))
            rows.append({"n": n, "shrink": s, "power": round(hits / reps, 4)})
    return rows


def record_path(contract_rel: str) -> str:
    stem = contract_rel[: -len(".contract.toml")] if contract_rel.endswith(".contract.toml") else contract_rel.rsplit(".", 1)[0]
    return stem + ".power.json"


def effects_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
