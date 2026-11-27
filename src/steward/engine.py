"""Run the rule catalogue and assemble a C10 report (RELEASE_v0.1_SPEC §5).

``verdict`` is a pure function of the repository bytes; everything that may vary lives in ``envelope``.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .fsutil import compact_json, git_run, sha256_bytes
from .rules import AREAS, RULE_FUNCS, RULES, Ctx, not_evaluated, result, rule_area
from .status import Result, Status, evaluate_gate, sort_key, summarize

INTEGRITY_RULES = ("R-11", "R-27", "R-31", "R-35", "R-36", "R-42")
SUBJECT_EVIDENCE = {"R-42": "R-42.audited", "R-11": "R-11.fingerprints_compared"}  # the detail that shows the rule inspected artifacts, not only metadata
NO_SUBJECT = {"R-27.nothing_to_trace", "R-11.nothing_to_check"}  # details that show a rule passed with nothing to inspect

# These codes describe an implementation limit, independent of the project's records or installed dependencies.
TOOLKIT_LIMITATIONS = {"R-13.pages_unsupported", "R-13.words_unsupported"}


def coverage_statement(results: list[Result]) -> str:
    """What this check covered (red-team B7): built from the rules that actually evaluated something."""
    def inspected(r: Result) -> bool:  # red-team D6: a rule is credited only if it had artifacts to inspect
        need = SUBJECT_EVIDENCE.get(r.rule)
        got = {d.get("code") for d in r.details}
        return (need is None or need in got) and not (got & NO_SUBJECT)

    checked = sorted({r.rule for r in results if r.rule in INTEGRITY_RULES
                      and r.status not in (Status.NOT_APPLICABLE, Status.UNKNOWN) and inspected(r)})
    integrity = f"checked by {', '.join(checked)}" if checked else "not assessed by this check"
    return ("Checked against declared rules only. Artifact integrity: " + integrity + ". Computational repeatability: "
            "not assessed by `steward check` (use `steward diff run`). Scientific validity, and the correctness or "
            "acceptance of a manuscript, are not assessed by this tool.")


def configured_areas(ctx: Any, results: list[Result]) -> dict[str, list[str]]:
    """Which areas the configuration turns on (FB-4, FB-9). An area whose table is present is configured, even when
    every one of its rules is NOT_APPLICABLE ("nothing recorded")."""
    from .rules import AREAS

    cfg = ctx.config
    if cfg is None:
        return {"configured": [], "nothing_recorded": [], "not_configured": sorted(AREAS)}
    present = {
        "config": True, "contract": bool(ctx.contract_files), "benchmark": bool(ctx.contract_files),
        "prior-work": bool(getattr(ctx, "prior_files", [])), "privacy": cfg.privacy is not None,
        "paper": bool(cfg.paper), "talk": bool(cfg.talk), "run": cfg.run is not None, "policy": cfg.policy is not None,
        "spend": cfg.spend is not None, "integrity": cfg.integrity is not None, "evidence": cfg.evidence is not None,
        "release": cfg.release is not None, "storage": getattr(cfg, "storage", None) is not None,
        "governance": cfg.steward.constitution is not None or getattr(cfg, "governance", None) is not None,
        "boundary": cfg.boundary is not None, "tasks": cfg.tasks is not None, "changelog": cfg.changelog is not None,
        "branches": cfg.branches is not None, "skills": cfg.skills is not None, "repro": cfg.repro is not None,
        "session": cfg.session is not None, "files": True, "agents": cfg.agents is not None,
        "stages": bool(cfg.stages), "frozen": bool(cfg.frozen), "dependencies": cfg.dependencies is not None,
        "containers": cfg.containers is not None, "docs": cfg.docs is not None,
        "data": cfg.data is not None,
        "models": bool(cfg.model),
    }
    conf, empty, missing = [], [], []
    for area, rules in AREAS.items():
        rs = [r for r in results if r.rule in rules]
        on = present.get(area, False) or any(r.status is not Status.NOT_APPLICABLE for r in rs)
        if on:
            conf.append(area)
            if rs and all(r.status is Status.NOT_APPLICABLE for r in rs):
                empty.append(area)
        else:
            missing.append(area)
    return {"configured": conf, "nothing_recorded": empty, "not_configured": missing}


class UnknownGate(Exception):
    pass


def input_list(inputs: dict[str, str]) -> list[list[str]]:
    """The check's inputs as the digest sees them: sorted [path, sha256] pairs."""
    return sorted([p, h] for p, h in inputs.items())


def inputs_digest(inputs: dict[str, str]) -> str:
    """The verdict's `inputs_digest`: one function for `check` and `check --digest-only` (C5)."""
    return "sha256:" + sha256_bytes(compact_json(input_list(inputs)).encode("utf-8"))


def tree_digest(root: Path, exclude: tuple[str, ...] = ()) -> str:
    """A digest of the repository's file list (names only, never contents), without `.git` folders, the process
    locks in `.steward/owners`, and the given paths. A file added or removed anywhere changes it, so `check --digest-only` can tell when a check could read a
    file the earlier one never saw (C5)."""
    import os

    names: list[str] = []
    skip = set(exclude)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = Path(dirpath).relative_to(root)
        # `.steward/owners` holds the locks of running steward processes (an MCP server's), not project content
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and (rel / d).as_posix() != ".steward/owners")
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():  # a linked folder is listed, never walked
                names.append((rel / d).as_posix())
        for f in filenames:
            if f == ".git":
                continue
            p = (rel / f).as_posix()
            if p not in skip:
                names.append(p)
    return "sha256:" + sha256_bytes("\n".join(sorted(names)).encode("utf-8"))


def scope_of(areas: list[str] | None, rule: str | None) -> dict[str, Any]:
    """What a run covered: every area, the named areas, or one rule's areas (STW-047, sprint task T04)."""
    return {"full": not areas, "areas": sorted(set(areas or [])), "rule": rule}


def run_check(root: Path, areas: list[str] | None = None, gate: str = "default", final: bool = False,
              rule: str | None = None, exclude: tuple[str, ...] = (), *,
              on_fault: Callable[[Exception | str], None] | None = None) -> dict[str, Any]:
    """`rule`: the rule a `check --rule` run asked for (its areas are in `areas`). `exclude`: repository paths left
    out of the tree digest (the report file this check writes)."""
    scope = scope_of(areas, rule)
    ctx = Ctx(root=root, final=final)
    selected = list(RULES) if not areas else sorted({"R-01", *[r for a in areas for r in AREAS[a]]})
    results: list[Result] = []
    for rule in selected:
        if rule != "R-01" and ctx.config is None:
            results.append(not_evaluated(rule, "config is not valid (R-01)"))
            continue
        try:
            results.extend(RULE_FUNCS[rule](ctx))
        except Exception as e:  # a rule bug must never pass silently or hide other rules
            if on_fault is not None:
                on_fault(e)
            results.append(result(rule, ".", Status.UNKNOWN, "internal_error", [{"code": "internal_error", "message": repr(e)}]))
    results.sort(key=sort_key)
    if on_fault is not None:
        limitations = {d.get("code") for r in results if scope["rule"] in (None, r.rule)
                       for d in r.details if d.get("code") in TOOLKIT_LIMITATIONS}
        for code in sorted(limitations):
            on_fault(code)

    partial = bool(areas)
    if ctx.config is not None:
        require = ctx.config.gate_require(gate)
        gate_names = sorted({"default", *ctx.config.gates})
    else:
        # an invalid configuration cannot name its gates: every gate asked for requires every rule, so R-01's FAIL
        # blocks it (a pre-commit hook on a named gate must not let a broken steward.toml through; AR-17)
        require = list(RULES)
        gate_names = sorted({"default", gate})
    if require is None:
        raise UnknownGate(gate)
    from . import authorize as az

    # review N3: with a trust root pinned, policy enforcement is part of every gate; a gate an unsigned edit defines
    # cannot leave R-33 out
    enforce = ctx.config is not None and az.pinned_trust_exists(ctx.config, root) is not None
    gates = []
    for name in gate_names:
        req = (ctx.config.gate_require(name) if ctx.config else list(RULES))
        if enforce and req is not None and "R-33" not in req:
            req = [*req, "R-33"]
        g = evaluate_gate(name, req or [], results, partial=partial,
                          min_evaluated=ctx.config.gate_min(name) if ctx.config else 0)
        added = ctx.config.gate_added(name) if ctx.config else []
        if added:  # Q1: the overlay's rules must also pass, and never count toward the base minimum
            g_all = evaluate_gate(name, [*(req or []), *added], results, partial=partial, min_evaluated=0)
            g = g_all if g["eligible"] else {**g, "required_count": g_all["required_count"], "waived": g_all["waived"]}
        gates.append(g)

    verdict = {
        "repo_id": ctx.config.steward.repo_id if ctx.config else "unknown",
        "project": ctx.config.steward.project if ctx.config else "unknown",
        "config_profile": ctx.config.steward.profile if ctx.config else "unknown",
        "inputs_digest": inputs_digest(ctx.inputs),
        "inputs": [{"path": p, "sha256": h} for p, h in input_list(ctx.inputs)],
        "tree_digest": tree_digest(root, exclude),
        "scope": scope,
        "results": [{**r.to_json(), "area": rule_area(r.rule)} for r in results],
        "summary": summarize(results),
        "gates": gates,
        "coverage": {
            "not_evaluated": sorted(ctx.not_evaluated, key=lambda d: (d["path"], d["reason"])),
            "statement": coverage_statement(results),
            "areas": configured_areas(ctx, results),
        },
    }
    return {"schema": "steward.report/0.1", "envelope": envelope(root), "verdict": verdict, "_gate": gate}


def envelope(root: Path) -> dict[str, Any]:
    return {
        "tool": "steward",
        "tool_version": __version__,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": {"os": sys.platform, "python": platform.python_version()},
        "git": _git_state(root),
    }


def _git_state(root: Path) -> dict[str, Any] | str:
    try:
        head = git_run(root, "rev-parse", "HEAD", text=True, timeout=10)
        if head.returncode != 0:
            return "unknown"
        # The working-tree state is not checked: `git status` refreshes the index, and that can run filters the
        # repository's .gitattributes and configuration select (red-team L1). The envelope is informational only.
        return {"head": head.stdout.strip(), "dirty": "not checked"}
    except (OSError, subprocess.SubprocessError):
        return "unknown"
