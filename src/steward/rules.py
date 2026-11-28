"""Rule catalogue v0.1, R-01 … R-07 (RELEASE_v0.1_SPEC §4).

Every rule is deterministic: the same repository bytes give the same results. A rule never decides
NOT_APPLICABLE on its own judgment; only the config or a deterministic precondition does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import hashlib
import tomllib
from decimal import Decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from . import models as m
from .fsutil import escapes_root, glob_match, inside, iter_repo_files, matching_files, sha256_bytes
from .status import Result, Status, combine

RULES: dict[str, tuple[str, int]] = {
    "R-01": ("config.valid", 1),
    "R-02": ("contract.valid", 1),
    "R-03": ("contract.consistent", 1),
    "R-04": ("contract.required", 1),
    "R-05": ("prior_work.valid", 1),
    "R-06": ("prior_work.required", 1),
    "R-07": ("privacy.denylist", 2),
    "R-08": ("paper.spec_valid", 1),
    "R-09": ("paper.placeholders", 1),
    "R-10": ("paper.values", 1),
    "R-11": ("paper.displays", 1),
    "R-12": ("paper.build", 1),
    "R-13": ("paper.venue", 1),
    "R-14": ("paper.citations", 1),
    "R-15": ("paper.consistency", 1),
    "R-21": ("talk.plan_valid", 1),
    "R-22": ("talk.stage_confirmed", 1),
    "R-23": ("talk.claim_ceiling", 1),
    "R-24": ("talk.values", 1),
    "R-25": ("talk.limitations", 1),
    "R-26": ("talk.structure", 1),
    "R-27": ("talk.figures", 1),
    "R-28": ("talk.visual", 1),
    "R-29": ("talk.language", 1),
    "R-31": ("ledger.integrity", 1),
    "R-32": ("run.records", 1),
    "R-33": ("policy.baseline", 1),
    "R-34": ("spend.ledger", 1),
    "R-35": ("integrity.frozen", 1),
    "R-36": ("integrity.datasets", 1),
    "R-37": ("integrity.sealed_use", 1),
    "R-38": ("integrity.decisions", 1),
    "R-39": ("integrity.contract_frozen", 1),
    "R-40": ("evidence.claims", 1),
    "R-41": ("prior_work.links", 1),
    "R-42": ("release.integrity", 1),
    "R-43": ("release.review", 1),
    "R-44": ("release.fingerprint", 1),
    "R-45": ("benchmark.splits", 1),
    "R-46": ("benchmark.datasets", 1),
    "R-47": ("benchmark.results", 1),
    "R-48": ("benchmark.comparison", 1),
    "R-49": ("benchmark.leakage", 1),
    "R-50": ("storage.artifacts", 1),
    "R-51": ("governance.constitution", 1),
    "R-52": ("repro.current", 1),
    "R-53": ("exchange.items", 1),
    "R-54": ("exchange.inbox", 1),
    "R-55": ("session.handoff", 1),
    "R-56": ("boundary.imports", 1),
    "R-57": ("tasks.board", 1),
    "R-58": ("changelog.unreleased", 1),
    "R-59": ("branches.model", 1),
    "R-60": ("skills.copies", 1),
    "R-61": ("files.conflict_markers", 1),
    "R-62": ("agents.ledger", 1),
    "R-63": ("frozen.sets", 1),
    "R-64": ("containers.context", 1),
    "R-65": ("containers.compose", 1),
    "R-66": ("dependencies.parity", 1),
    "R-67": ("benchmark.power", 1),
    "R-68": ("stages.records", 1),
    "R-69": ("docs.current", 1),
    "R-70": ("milestones.valid", 1),
    "R-71": ("sprint.valid", 1),
    "R-72": ("sprint.closed", 1),
    "R-73": ("pins.records", 1),
    "R-74": ("pins.retirement", 1),
    "R-75": ("studies.records", 1),
    "R-76": ("research.records", 1),
    "R-77": ("paper.citations_verified", 1),
    "R-78": ("benchmark.llm_eval", 1),
    "R-79": ("licence.declared", 1),
    "R-80": ("licence.dependencies", 1),
    "R-81": ("licence.code", 1),
    "R-82": ("licence.provenance", 1),
    "R-83": ("data.contracts", 1),
    "R-85": ("paper.data_availability", 1),
    "R-84": ("compare.shadow", 1),
    "R-87": ("release.stranger_test", 1),
    "R-86": ("model.records", 1),
    "R-88": ("tidy.stale", 1),
}

AREAS: dict[str, tuple[str, ...]] = {
    "config": ("R-01",),
    "contract": ("R-02", "R-03", "R-04"),
    "prior-work": ("R-05", "R-06"),
    "privacy": ("R-07",),
    "paper": ("R-08", "R-09", "R-10", "R-11", "R-12", "R-13", "R-14", "R-15", "R-77", "R-85"),
    "talk": ("R-21", "R-22", "R-23", "R-24", "R-25", "R-26", "R-27", "R-28", "R-29"),
    "run": ("R-31", "R-32"),
    "policy": ("R-33",),
    "spend": ("R-34",),
    "integrity": ("R-35", "R-36", "R-37", "R-38", "R-39"),
    "evidence": ("R-40", "R-41"),
    "release": ("R-42", "R-43", "R-44", "R-87"),
    "benchmark": ("R-02", "R-03", "R-45", "R-46", "R-47", "R-48", "R-49", "R-67", "R-78"),
    "storage": ("R-50",),
    "governance": ("R-51", "R-53", "R-54"),
    "boundary": ("R-56",),
    "tasks": ("R-57",),
    "changelog": ("R-58",),
    "branches": ("R-59",),
    "skills": ("R-60",),
    "repro": ("R-52",),
    "session": ("R-55",),
    "files": ("R-61",),
    "agents": ("R-62",),
    "stages": ("R-68",),
    "frozen": ("R-63",),
    "dependencies": ("R-66",),
    "containers": ("R-64", "R-65"),
    "docs": ("R-69",),
    "milestones": ("R-70",),
    "sprints": ("R-71", "R-72"),
    "pins": ("R-73", "R-74"),
    "studies": ("R-75", "R-85"),
    "research": ("R-76",),
    "licence": ("R-79", "R-80", "R-81", "R-82"),
    "data": ("R-83",),
    "compare": ("R-84",),
    "models": ("R-86",),
    "tidy": ("R-88",),
}


def rule_area(rule: str) -> str:
    """The area a rule belongs to: the first area that lists it (0.21.0, STW-047). A rule that several areas share
    (R-02 and R-03 in contract and benchmark, R-85 in paper and studies) is named by its first area, as `explain`
    and the using-steward catalogue name it."""
    return next((a for a, rs in AREAS.items() if rule in rs), "unassigned")


@dataclass
class Ctx:
    """State shared by the rules of one check run: what was read, and what the earlier rules parsed."""

    root: Path
    final: bool = False  # `steward check --final`: final mode for every paper
    overlay: list[dict[str, Any]] = field(default_factory=list)  # 0.9.0 B9: the overlay's R-01 detail
    config: m.StewardConfig | None = None
    inputs: dict[str, str] = field(default_factory=dict)  # rel path -> sha256 of every file read
    not_evaluated: list[dict[str, str]] = field(default_factory=list)
    contracts: dict[str, m.Contract] = field(default_factory=dict)  # rel path -> parsed contract (R-02 not FAIL)
    contract_files: list[str] = field(default_factory=list)
    contract_r02: dict[str, Status] = field(default_factory=dict)
    prior: dict[str, m.PriorWork] = field(default_factory=dict)
    prior_files: list[str] = field(default_factory=list)
    snapshot: dict[str, bytes] = field(default_factory=dict)  # rel path -> bytes, read once per check (I2)
    values_cache: dict[str, Any] = field(default_factory=dict)  # paper name -> (ValuesFile | None, Computed | None, errors)

    def read(self, rel: str) -> bytes:
        """The file's bytes, read once per check: every rule, and the verdict's input digest, see the same snapshot
        (red-team G7, H2, I2)."""
        if rel not in self.snapshot:
            self.snapshot[rel] = (self.root / rel).read_bytes()
        data = self.snapshot[rel]
        self.inputs[rel] = sha256_bytes(data)
        return data

    def evidence(self, rel: str) -> list[dict[str, str]]:
        return [{"path": rel, "sha256": self.inputs[rel]}] if rel in self.inputs else []


def result(rule: str, subject: str, status: Status, reason: str, details=None, evidence=None) -> Result:
    name, version = RULES[rule]
    return Result(rule, name, version, subject, status, reason, details or [], evidence or [])


def not_evaluated(rule: str, why: str) -> Result:
    return result(rule, ".", Status.UNKNOWN, f"not evaluated: {why}")


# ---------------------------------------------------------------- helpers
def _load_toml(ctx: Ctx, rel: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        raw = ctx.read(rel)
    except OSError as e:
        return None, [{"code": "read", "message": f"cannot read file: {e.strerror}"}]
    try:
        return tomllib.loads(raw.decode("utf-8")), []
    except UnicodeDecodeError:
        return None, [{"code": "parse", "message": "file is not valid UTF-8"}]
    except (ValueError, RecursionError) as e:
        return None, [{"code": "parse", "message": f"invalid TOML: {e}"}]


def _sentinel_status(found: list[tuple[str, str]]) -> tuple[list[Status], list[dict[str, Any]]]:
    causes, details = [], []
    for path, value in found:
        causes.append(Status.INCOMPLETE if value == m.TBD else Status.UNKNOWN)
        details.append({"code": "sentinel", "field": path, "value": value})
    return causes, details


def _reason(status: Status, fail: str, incomplete: str, unknown: str, ok: str) -> str:
    return {Status.FAIL: fail, Status.INCOMPLETE: incomplete, Status.UNKNOWN: unknown}.get(status, ok)


# ---------------------------------------------------------------- R-01 config.valid
def r01(ctx: Ctx) -> list[Result]:
    rel = "steward.toml"
    data, errors = _load_toml(ctx, rel)
    if data is None:
        return [result("R-01", rel, Status.FAIL, "config cannot be parsed", errors, ctx.evidence(rel))]
    overlay_detail: list[dict[str, Any]] = []
    overlay_adds: dict[str, list[str]] = {}
    op = m.overlay_path(ctx.root)
    if op is not None:  # 0.9.0 B9: additions only, hashed into the report
        import hashlib

        label = m.overlay_label(ctx.root, op)
        try:
            raw = op.read_bytes()
            over = tomllib.loads(raw.decode("utf-8"))
        except OSError as e:  # Q3: the label only, never the raw path of an outside overlay
            return [result("R-01", rel, Status.FAIL, "the configuration overlay cannot be read",
                           [{"code": "R-01.overlay_unreadable", "path": label, "message": e.strerror or "unreadable"}],
                           ctx.evidence(rel))]
        except (UnicodeDecodeError, ValueError, RecursionError):
            return [result("R-01", rel, Status.FAIL, "the configuration overlay is not valid TOML",
                           [{"code": "R-01.overlay_unreadable", "path": label}], ctx.evidence(rel))]
        digest = hashlib.sha256(raw).hexdigest()
        ctx.inputs[label] = digest
        data, refused, overlay_adds = m.merge_overlay(data, over)
        if refused:
            return [result("R-01", rel, Status.FAIL, "the configuration overlay may only add",
                           [{"code": "R-01.overlay_refused", "path": label, "value": k} for k in refused], ctx.evidence(rel))]
        overlay_detail = [{"code": "R-01.overlay", "path": label, "value": digest,
                           "message": "additions only: gates, gate rules, records_required, record globs"}]
    schema = data.get("steward", {}).get("schema") if isinstance(data.get("steward"), dict) else None
    if schema is not None and schema not in m.CONFIG_SCHEMAS:
        msg = f"unsupported config schema {schema}; this steward supports {', '.join(m.CONFIG_SCHEMAS)}"
        return [result("R-01", rel, Status.FAIL, msg, [{"code": "schema_version", "message": msg}], ctx.evidence(rel))]
    try:
        cfg = m.StewardConfig.model_validate(data)
    except ValidationError as e:
        return [result("R-01", rel, Status.FAIL, "config violates schema steward.toml/0.1", m.format_errors(e), ctx.evidence(rel))]
    m.apply_adds(cfg, overlay_adds)  # Q2: after the records root has moved the defaults
    details = []
    globs = [("paths.contracts", p) for p in cfg.paths.contracts] + [("paths.prior_work", p) for p in cfg.paths.prior_work]
    globs += [("paths.records", cfg.paths.records)]
    if cfg.privacy:
        globs += [("privacy.denylist_file", cfg.privacy.denylist_file)] if cfg.privacy.denylist_file else []
        globs += [("privacy.include", p) for p in cfg.privacy.include] + [("privacy.exclude", p) for p in cfg.privacy.exclude]
    for name, pp in sorted(cfg.paper.items()):
        globs += [(f"paper.{name}.dir", pp.dir)]
        globs += [(f"paper.{name}.{k}", pp.rel(v)) for k, v in
                  (("main", pp.main), ("spec", pp.spec), ("venue", pp.venue), ("build_log", pp.resolved_log() or "x"))]
        globs += [(f"paper.{name}.sources", pp.rel(g)) for g in pp.resolved_sources()]
    for name, tt in sorted(cfg.talk.items()):
        globs += [(f"talk.{name}.dir", tt.dir)]
        globs += [(f"talk.{name}.{k}", tt.rel(v)) for k, v in
                  (("main", tt.main), ("plan", tt.plan), ("pdf", tt.resolved_pdf()), ("build_log", tt.resolved_log()))]
    for fld, pat in globs:
        if escapes_root(pat):
            details.append({"code": "path_escapes_root", "field": fld, "message": f"'{pat}' is outside the repository root"})
    if details:
        return [result("R-01", rel, Status.FAIL, "config path outside the repository", details, ctx.evidence(rel))]
    ctx.config = cfg
    ctx.overlay = overlay_detail
    if cfg.paths.records_required:  # SR-006: a records root that went missing is not silently NOT_APPLICABLE
        decisions = cfg.integrity.primary_decisions if cfg.integrity else f"{cfg.paths.records.rstrip('/')}/DECISIONS.md"
        missing = [p for p, kind in ((cfg.paths.records, "dir"), (decisions, "file"))  # review N13: the right kind
                   if not ((ctx.root / p).is_dir() if kind == "dir" else (ctx.root / p).is_file())]
        if missing:
            return [result("R-01", rel, Status.INCOMPLETE, "required process records are missing",
                           [{"code": "R-01.records_missing", "path": p} for p in missing] + overlay_detail, ctx.evidence(rel))]
    return [result("R-01", rel, Status.PASS, f"config is consistent with {cfg.steward.schema_}", overlay_detail,
                   ctx.evidence(rel))]


# ---------------------------------------------------------------- R-02 contract.valid
def r02(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    ctx.contract_files = matching_files(ctx.root, ctx.config.paths.contracts)
    if not ctx.contract_files:
        return [result("R-02", ".", Status.NOT_APPLICABLE, f"no files matched {', '.join(ctx.config.paths.contracts)}")]
    out = []
    for rel in ctx.contract_files:
        data, errors = _load_toml(ctx, rel)
        if data is None:
            ctx.contract_r02[rel] = Status.FAIL
            out.append(result("R-02", rel, Status.FAIL, "contract cannot be parsed", errors, ctx.evidence(rel)))
            continue
        try:
            c = m.Contract.model_validate(data)
        except ValidationError as e:
            ctx.contract_r02[rel] = Status.FAIL
            out.append(result("R-02", rel, Status.FAIL, "contract violates schema steward.contract/0.1", m.format_errors(e), ctx.evidence(rel)))
            continue
        # leakage declarations are R-49's: an advisory "unknown" must not block through R-02 (red-team J8)
        causes, details = _sentinel_status([f for f in m.find_sentinels(c) if not f[0].startswith("leakage")])
        status = combine(causes)
        ctx.contracts[rel] = c
        ctx.contract_r02[rel] = status
        reason = _reason(status, "", "contract has fields marked TBD", "contract has fields marked unknown",
                         "contract is consistent with steward.contract/0.1")
        out.append(result("R-02", rel, status, reason, details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- R-03 contract.consistent
def _ref_file(ctx: Ctx, value: Any, field_path: str, causes: list[Status], details: list[dict[str, Any]]) -> None:
    if value is None or value in m.SENTINELS:
        return
    if escapes_root(value) or not inside(ctx.root, value):
        causes.append(Status.FAIL)
        details.append({"code": "R-03.path_outside", "field": field_path, "path": value})
    elif not (ctx.root / value).is_file():
        causes.append(Status.INCOMPLETE)
        details.append({"code": "R-03.missing_file", "field": field_path, "path": value})


def r03(ctx: Ctx) -> list[Result]:
    if not ctx.contract_files:
        return [result("R-03", ".", Status.NOT_APPLICABLE, "no contract files matched")]
    ids: dict[str, list[str]] = {}
    for rel, c in ctx.contracts.items():
        ids.setdefault(c.id, []).append(rel)
    out = []
    for rel in ctx.contract_files:
        if rel not in ctx.contracts:
            out.append(result("R-03", rel, Status.UNKNOWN, "not evaluated: contract failed R-02", [], ctx.evidence(rel)))
            continue
        c = ctx.contracts[rel]
        causes: list[Status] = []
        details: list[dict[str, Any]] = []

        def fail(code: str, **kw: Any) -> None:
            causes.append(Status.FAIL)
            details.append({"code": f"R-03.{code}", **kw})

        if len(ids[c.id]) > 1:
            fail("duplicate_id", id=c.id, files=sorted(ids[c.id]))
        metric_names = [d.name for d in c.metrics.defs]
        if c.metrics.primary not in metric_names:
            fail("primary_undefined", field="metrics.primary", value=c.metrics.primary)
        baseline_names = {b.name for b in c.baselines}
        for i, t in enumerate(c.thresholds):
            if t.metric not in metric_names:
                fail("threshold_metric_undefined", field=f"thresholds[{i}].metric", value=t.metric)
            if t.against.startswith("baseline:") and t.against[len("baseline:"):] not in baseline_names:
                fail("threshold_baseline_undefined", field=f"thresholds[{i}].against", value=t.against)
        names = [s.name for s in c.splits.sets]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            fail("duplicate_split", value=dup)
        if not any(s.role == "test" for s in c.splits.sets):
            fail("no_test_role", field="splits.sets")
        if c.analysis == "confirmatory":
            if c.comparison is None:
                fail("confirmatory_without_comparison", field="comparison")
            if not c.thresholds:
                fail("confirmatory_without_thresholds", field="thresholds")
            found = m.find_sentinels(c.comparison, "comparison") if c.comparison else []
            found += [(f"thresholds[{i}].value", t.value) for i, t in enumerate(c.thresholds) if t.value in m.SENTINELS]
            s_causes, s_details = _sentinel_status(found)
            causes += s_causes
            details += [{**d, "code": "R-03.confirmatory_unspecified"} for d in s_details]
        for i, s in enumerate(c.splits.sets):
            _ref_file(ctx, s.ids_file, f"splits.sets[{i}].ids_file", causes, details)
        for i, d in enumerate(c.metrics.defs):
            _ref_file(ctx, d.implementation, f"metrics.defs[{i}].implementation", causes, details)
        if c.exclusions:
            _ref_file(ctx, c.exclusions.excluded_ids_file, "exclusions.excluded_ids_file", causes, details)
        status = combine(causes)
        reason = _reason(status, "contract cross-references are inconsistent", "referenced evidence is missing or not yet specified",
                         "confirmatory settings are marked unknown", "contract cross-references are consistent")
        out.append(result("R-03", rel, status, reason, details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- R-04 contract.required
def r04(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    if ctx.config.steward.profile != "confirmatory":
        return [result("R-04", ".", Status.NOT_APPLICABLE, "profile is exploratory; confirmatory contracts are not required")]
    confirmatory = sorted(rel for rel, c in ctx.contracts.items() if c.analysis == "confirmatory")
    if confirmatory:
        return [result("R-04", ".", Status.PASS, f"{len(confirmatory)} confirmatory contract(s) present",
                       [{"code": "R-04.found", "files": confirmatory}])]
    return [result("R-04", ".", Status.INCOMPLETE, "confirmatory profile requires a contract with analysis = \"confirmatory\"")]


# ---------------------------------------------------------------- R-05 prior_work.valid
def r05(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    ctx.prior_files = matching_files(ctx.root, ctx.config.paths.prior_work)
    if not ctx.prior_files:
        return [result("R-05", ".", Status.NOT_APPLICABLE, f"no files matched {', '.join(ctx.config.paths.prior_work)}")]
    out = []
    for rel in ctx.prior_files:
        data, errors = _load_toml(ctx, rel)
        if data is None:
            out.append(result("R-05", rel, Status.FAIL, "prior-work record cannot be parsed", errors, ctx.evidence(rel)))
            continue
        try:
            p = m.PriorWork.model_validate(data)
        except ValidationError as e:
            out.append(result("R-05", rel, Status.FAIL, "record violates schema steward.prior_work/0.1", m.format_errors(e), ctx.evidence(rel)))
            continue
        causes, details = _sentinel_status(m.find_sentinels(p))
        work_ids = [w.id for w in p.works]
        for dup in sorted({w for w in work_ids if work_ids.count(w) > 1}):
            causes.append(Status.FAIL)
            details.append({"code": "R-05.duplicate_work_id", "value": dup})
        for i, row in enumerate(p.comparisons):
            for key in sorted(row.theirs):
                if key not in work_ids:
                    causes.append(Status.FAIL)
                    details.append({"code": "R-05.unknown_work", "field": f"comparisons[{i}].theirs.{key}", "value": key})
        # The novelty judgment is a human field: reported, never assessed (spec §3.3).
        details.append({"code": "R-05.human_judgment", "field": "judgment.novelty",
                        "note": "human judgment; recorded, not verified; not assessed by this rule"})
        status = combine(causes)
        ctx.prior[rel] = p
        reason = _reason(status, "prior-work record is inconsistent", "record has fields marked TBD",
                         "record has fields marked unknown", "record is consistent with steward.prior_work/0.1")
        out.append(result("R-05", rel, status, reason, details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- R-06 prior_work.required
def r06(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    if ctx.config.steward.profile != "confirmatory":
        return [result("R-06", ".", Status.NOT_APPLICABLE, "profile is exploratory; a prior-work record is not required")]
    with_closest = sorted(rel for rel, p in ctx.prior.items() if any(w.relation == "closest_method" for w in p.works))
    if with_closest:
        return [result("R-06", ".", Status.PASS, "prior-work record with a closest_method work present",
                       [{"code": "R-06.found", "files": with_closest}])]
    return [result("R-06", ".", Status.INCOMPLETE, "confirmatory profile requires a prior-work record with a closest_method work")]


# ---------------------------------------------------------------- R-07 privacy.denylist
def _load_terms(raw: bytes) -> list[str]:
    terms = []
    for line in raw.decode("utf-8").splitlines():  # UnicodeDecodeError handled by caller
        s = line.strip()
        if s and not s.startswith("#"):
            terms.append(s)
    return terms


def r07(ctx: Ctx) -> list[Result]:
    """Term lists and local paths (0.8.1: SR-004, AR-04, SR-005, FB-2, FB-3, FB-11)."""
    from . import privacy as pv

    assert ctx.config is not None
    priv = ctx.config.privacy
    lists = pv.load(ctx.root, ctx.config, read=ctx.read)
    if priv is None and not lists:
        return [result("R-07", ".", Status.NOT_APPLICABLE, "[privacy] and [[terms]] are not configured")]
    local_paths = priv is None or priv.local_paths  # the audit's default too (DEF-024)
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    for src in lists:
        details += src.errors
        causes += [Status.FAIL] * len(src.errors)
        if src.state == "missing":
            details.append({"code": "R-07.list_missing", "value": src.name, "path": src.file})
            if src.public:  # a committed list must be in the checkout
                causes.append(Status.INCOMPLETE)
        elif src.state in ("unreadable", "empty"):
            details.append({"code": f"R-07.list_{src.state}", "value": src.name, "path": src.file})
    readable = [s for s in lists if s.state == "ok"]
    if lists and not readable and not any(x is Status.INCOMPLETE for x in causes):
        # no declared list could be read: never PASS on what was meant to be checked (local paths are still scanned)
        causes.append(Status.UNKNOWN)
    scope_inc = priv.include if priv else ["**/*"]
    scope_exc = (priv.exclude if priv else [".git/**", ".steward/**"]) + (pv.BINARY_GLOBS if (priv is None or priv.binary_excludes) else [])
    allow = priv.allow if priv else []
    hits: list[dict[str, Any]] = []
    allowed = 0
    unextractable: list[str] = []
    for rel in iter_repo_files(ctx.root):
        if pv.exempt(rel, lists, []) or any(glob_match(rel, p) for p in pv.BINARY_GLOBS if priv is None or priv.binary_excludes):
            continue
        own = [t for s in readable if s.applies(rel) for t in s.terms]
        lp = local_paths and any(glob_match(rel, p) for p in scope_inc) and not any(glob_match(rel, p) for p in scope_exc) \
            and not any(glob_match(rel, p) for p in allow)
        if not own and not lp:
            continue
        try:
            raw = ctx.read(rel)
        except OSError:
            ctx.not_evaluated.append({"path": rel, "reason": "unreadable"})
            continue
        if rel.lower().endswith(".pdf"):
            pages = pdf_text(ctx.root / rel)
            if pages is None:
                unextractable.append(rel)
                ctx.not_evaluated.append({"path": rel, "reason": "pdf text extraction unavailable (install poppler or the [paper] extra)"})
                continue
            for page_no, page in enumerate(pages, start=1):
                found, n = pv.scan_text(page, own, lp)
                allowed += n
                hits += [{**h, "path": rel, "page": page_no} for h in found]
            continue
        if b"\x00" in raw[:8192]:
            ctx.not_evaluated.append({"path": rel, "reason": "binary"})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            ctx.not_evaluated.append({"path": rel, "reason": "not UTF-8"})
            continue
        found, n = pv.scan_text(text, own, lp, rel=rel, sha=hashlib.sha256(raw).hexdigest())
        allowed += n
        for h in found:
            h["path"] = rel
        hits += found
    out_hits = []
    for h in hits:
        where = {"path": h["path"], **({"page": h["page"]} if h.get("page") else
                                       {"line": h["line"], **({"column": h["column"]} if "column" in h else {})})}
        if h["kind"] == "local_path":
            out_hits.append({"code": "R-07.local_path", **where, "message": "an absolute home path with a user name"})
        elif h["term"].public:
            out_hits.append({"code": "R-07.policy_hit", **where, "term": h["term"].label, "value": h["term"].text})
        else:  # never the term itself: the report must not leak what it protects
            out_hits.append({"code": "R-07.hit", **where, "term": h["term"].label})
    if allowed:
        details.append({"code": "R-07.allowed_lines", "value": allowed, "message": f"lines marked '{pv.MARKER}'"})
    if out_hits:
        return [result("R-07", ".", Status.FAIL, f"{len(out_hits)} term or local-path occurrence(s) found", out_hits + details)]
    if unextractable:
        causes.append(Status.UNKNOWN)
        details += [{"code": "R-07.pdf_unreadable", "path": p} for p in unextractable]
    status = combine(causes)
    n_terms = sum(len(s.terms) for s in readable)
    return [result("R-07", ".", status, _reason(status, "a term list is invalid", "a committed term list is missing",
                   "no declared term list could be read, or a PDF could not be read",
                   f"no listed terms found ({n_terms} term(s) in {len(readable)} list(s))" + ("; local paths checked" if local_paths else "")),
                   details)]


def pdf_text(path: Path) -> list[str] | None:
    """Text of each PDF page: pdftotext (Poppler) first, then pypdf ([paper] extra). None when neither is available."""
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120)
            if out.returncode == 0:
                return out.stdout.decode("utf-8", errors="replace").split("\f")
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return None
    try:
        return [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    except Exception:  # a malformed PDF is unreadable, not a crash
        return None


# ---------------------------------------------------------------- paper kit (C16, RELEASE_v0.2_SPEC §3)
def _papers(ctx: Ctx, rule: str) -> list[tuple[str, m.PaperSection]] | list[Result]:
    assert ctx.config is not None
    if not ctx.config.paper:
        return [result(rule, ".", Status.NOT_APPLICABLE, "no paper configured")]
    return sorted(ctx.config.paper.items())


def _mode(ctx: Ctx, pp: m.PaperSection) -> str:
    return "final" if ctx.final or pp.mode == "final" else "draft"


def _validated(ctx: Ctx, rule: str, rel: str, model: Any, label: str) -> Result:
    data, errors = _load_toml(ctx, rel)
    if data is None:
        return result(rule, rel, Status.FAIL, f"{label} cannot be parsed", errors, ctx.evidence(rel))
    try:
        obj = model.model_validate(data)
    except ValidationError as e:
        return result(rule, rel, Status.FAIL, f"{label} violates its schema", m.format_errors(e), ctx.evidence(rel))
    causes, details = _sentinel_status(m.find_sentinels(obj))
    status = combine(causes)
    reason = _reason(status, "", f"{label} has fields marked TBD", f"{label} has fields marked unknown",
                     f"{label} is consistent with its schema")
    return result(rule, rel, status, reason, details, ctx.evidence(rel))


def r08(ctx: Ctx) -> list[Result]:
    papers = _papers(ctx, "R-08")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        spec = pp.rel(pp.spec)
        if not (ctx.root / spec).is_file():
            out.append(result("R-08", spec, Status.INCOMPLETE, f"paper '{name}': spec file is missing"))
        else:
            out.append(_validated(ctx, "R-08", spec, m.PaperSpec, f"paper '{name}' spec"))
        venue = pp.rel(pp.venue)
        if not (ctx.root / venue).is_file():
            out.append(result("R-08", venue, Status.NOT_APPLICABLE, f"paper '{name}': no venue profile (optional in v0.2.0)"))
        else:
            out.append(_validated(ctx, "R-08", venue, m.Venue, f"paper '{name}' venue profile"))
    return out


_TEX_COMMENT = re.compile(r"(?<!\\)%.*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->")


def _docx_text(path: Path) -> str | None:
    if not shutil.which("pandoc"):
        return None
    try:
        out = subprocess.run(["pandoc", "-t", "plain", "--wrap=none", str(path)], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None


def r09(ctx: Ctx) -> list[Result]:
    papers = _papers(ctx, "R-09")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        mode = _mode(ctx, pp)
        patterns = [re.compile(p) for p in pp.placeholders]
        files = matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()])
        causes: list[Status] = []
        details: list[dict[str, Any]] = [{"code": "R-09.mode", "value": mode}]
        for rel in files:
            if rel.lower().endswith(".docx"):
                ctx.read(rel)
                text = _docx_text(ctx.root / rel)
                if text is None:
                    causes.append(Status.UNKNOWN)
                    details.append({"code": "R-09.docx_unreadable", "path": rel, "message": "pandoc not available"})
                    continue
            else:
                try:
                    text = ctx.read(rel).decode("utf-8")
                except UnicodeDecodeError:
                    ctx.not_evaluated.append({"path": rel, "reason": "not UTF-8"})
                    continue
            is_tex = rel.endswith((".tex", ".bib", ".cls", ".sty"))
            for lineno, line in enumerate(text.splitlines(), start=1):
                raw_line = line
                if mode == "draft":
                    line = _TEX_COMMENT.sub("", line) if is_tex else _HTML_COMMENT.sub("", line)
                for k, pat in enumerate(patterns, start=1):
                    hit = pat.search(line)
                    if hit:
                        causes.append(Status.FAIL if mode == "final" else Status.INCOMPLETE)
                        # C4: the column only where removing comments left the line unchanged up to the marker
                        col = {"column": hit.start() + 1} if raw_line[:hit.end()] == line[:hit.end()] else {}
                        details.append({"code": "R-09.marker", "path": rel, "line": lineno, **col,
                                        "value": f"pattern #{k}"})
        status = combine(causes)
        n = sum(1 for d in details if d["code"] == "R-09.marker")
        reason = {Status.FAIL: f"{n} placeholder marker(s) in final mode",
                  Status.INCOMPLETE: f"{n} placeholder marker(s) remain (draft mode)",
                  Status.UNKNOWN: "some sources could not be read"}.get(status, f"no placeholder markers ({len(files)} file(s), {mode} mode)")
        out.append(result("R-09", pp.dir, status, reason, details))
    return out


_LOG_RULES = [
    (re.compile(r"Reference [`'\"]([^'\"]+)['\"] on page \d+ undefined"), "R-12.undefined_reference", Status.FAIL),
    (re.compile(r"Citation [`'\"]([^'\"]+)['\"](?: on page \d+)? undefined"), "R-12.undefined_citation", Status.FAIL),
    (re.compile(r"There were undefined (references|citations)"), "R-12.undefined_summary", Status.FAIL),
    (re.compile(r"Label [`'\"]([^'\"]+)['\"] multiply defined|There were multiply-defined labels"), "R-12.multiply_defined", Status.FAIL),
    (re.compile(r"^! "), "R-12.latex_error", Status.FAIL),
    (re.compile(r"Rerun to get|may have changed\. Rerun|Please \(?re\)?run (Biber|BibTeX|LaTeX)|Please rerun LaTeX"), "R-12.rerun", Status.INCOMPLETE),
]
_OVERFULL = re.compile(r"^Overfull \\[hv]box")


def r12(ctx: Ctx) -> list[Result]:
    papers = _papers(ctx, "R-12")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        if pp.ext != ".tex":
            out.append(result("R-12", pp.dir, Status.NOT_APPLICABLE, f"paper '{name}': main is {pp.ext or 'not .tex'}; build-log checks are LaTeX-only in v0.2"))
            continue
        log = pp.rel(pp.resolved_log() or "")
        if not (ctx.root / log).is_file():
            out.append(result("R-12", log, Status.UNKNOWN, f"paper '{name}': build log not found; build the paper first"))
            continue
        text = ctx.read(log).decode("utf-8", errors="replace")
        mode = _mode(ctx, pp)
        causes: list[Status] = []
        details: list[dict[str, Any]] = [{"code": "R-12.mode", "value": mode}]
        overfull = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat, code, status in _LOG_RULES:
                mt = pat.search(line)
                if mt:
                    causes.append(status)
                    d: dict[str, Any] = {"code": code, "path": log, "line": lineno}
                    if mt.groups() and mt.group(1):
                        d["value"] = mt.group(1)
                    details.append(d)
            if _OVERFULL.search(line):
                overfull += 1
                details.append({"code": "R-12.overfull", "path": log, "line": lineno})
                if mode == "final":
                    causes.append(Status.INCOMPLETE)
        status = combine(causes)
        reason = {Status.FAIL: "build log reports undefined references, citations, duplicate labels or errors",
                  Status.INCOMPLETE: "build needs a rerun or has overfull boxes (final mode)"}.get(
            status, f"build log clean ({overfull} overfull box(es) listed)" if overfull else "build log clean")
        out.append(result("R-12", log, status, reason, details, ctx.evidence(log)))
    return out


# ---------------------------------------------------------------- values registry (v0.2.1): R-10, R-15
_LITERAL = re.compile(r"(?<![\w.\\{])[-+]?\d+(?:[.,]\d+)*(?:\.\d+)?\s?%?(?![\w}])")
_STRIP_CMDS = re.compile(r"\\(?:val|ref|eqref|cref|Cref|autoref|cite[a-z]*|label|begin|end|usepackage|documentclass|"
                         r"includegraphics|input|include|bibliography|bibliographystyle|url|href|hspace|vspace|"
                         r"setlength|addtolength)\*?(?:\[[^\]]*\])*(?:\{[^}]*\})+")
_YEAR = re.compile(r"^(19|20)\d\d$")


def _load_values(ctx: Ctx, name: str, pp: m.PaperSection) -> tuple[Any, Any, list[dict[str, Any]]]:
    from . import values as v

    if name in ctx.values_cache:
        return ctx.values_cache[name]
    rel = pp.rel(pp.values)
    out: tuple[Any, Any, list[dict[str, Any]]]
    if not (ctx.root / rel).is_file():
        out = (None, None, [])
    else:
        data, errors = _load_toml(ctx, rel)
        if data is None:
            out = (None, None, errors or [{"code": "parse"}])
        else:
            try:
                vf = v.ValuesFile.model_validate(data)
            except ValidationError as e:
                out = (None, None, m.format_errors(e))
            else:
                comp = v.compute(ctx.root, vf, read=ctx.snapshot)
                for src, raw in comp.read.items():
                    ctx.inputs[src] = sha256_bytes(raw)
                out = (vf, comp, [])
    ctx.values_cache[name] = out
    return out


def _value_refs(ctx: Ctx, pp: m.PaperSection) -> list[tuple[str, int, str]]:
    from . import values as v

    gen = pp.rel(pp.resolved_values_out())
    refs = []
    for rel in matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]):
        if rel == gen or rel.endswith(".docx"):
            continue
        try:
            text = ctx.read(rel).decode("utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            line = _TEX_COMMENT.sub("", line) if rel.endswith(".tex") else line
            refs += [(rel, n, k) for k in v.VAL_REF.findall(line) + v.QUARTO_REF.findall(line)]
    return refs


def _display_outputs(ctx: Ctx, pp: m.PaperSection) -> set[str]:
    """Outputs declared in the display manifest (built by scripts; their provenance is R-11's job)."""
    p = ctx.root / pp.rel(pp.displays)
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (ValueError, RecursionError, UnicodeDecodeError):
        return set()
    disp = data.get("displays", {})
    return {d["output"] for d in disp.values() if isinstance(d, dict) and isinstance(d.get("output"), str)} if isinstance(disp, dict) else set()


def _literals(ctx: Ctx, pp: m.PaperSection) -> list[dict[str, Any]]:
    """Bare numbers in the body of LaTeX sources: a heuristic listing, never a certificate.
    Generated files (the values file, display outputs) are excluded: scripts produced their numbers."""
    found = []
    skip = {pp.rel(pp.resolved_values_out())} | _display_outputs(ctx, pp)
    for rel in matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]):
        if rel in skip or not rel.endswith(".tex"):
            continue
        text = (ctx.root / rel).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines) if "\\begin{document}" in l), -1) + 1
        for n in range(start, len(lines)):
            raw = lines[n]
            if "literal-ok" in raw:
                continue
            line = _STRIP_CMDS.sub(" ", _TEX_COMMENT.sub("", raw))
            for mt in _LITERAL.finditer(line):
                num = mt.group(0).strip()
                if _YEAR.match(num):
                    continue
                found.append({"code": "R-10.literal", "path": rel, "line": n + 1, "value": num})
    return found


def r10(ctx: Ctx) -> list[Result]:
    from . import values as v

    papers = _papers(ctx, "R-10")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        rel = pp.rel(pp.values)
        refs = _value_refs(ctx, pp)
        vf, comp, errors = _load_values(ctx, name, pp)
        if vf is None and not errors:
            if refs:
                out.append(result("R-10", rel, Status.FAIL, f"paper '{name}': the text uses value keys but there is no values registry",
                                  [{"code": "R-10.no_registry", "path": p, "line": n, "value": k} for p, n, k in refs]))
            else:
                out.append(result("R-10", rel, Status.NOT_APPLICABLE, f"paper '{name}': no values registry"))
            continue
        if vf is None:
            out.append(result("R-10", rel, Status.FAIL, f"paper '{name}': values registry is invalid", errors, ctx.evidence(rel)))
            continue
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        for key, (kind, msg) in sorted(comp.errors.items()):
            causes.append({"missing": Status.INCOMPLETE, "unknown": Status.UNKNOWN}.get(kind, Status.FAIL))
            details.append({"code": f"R-10.source_{kind}", "field": f"values.{key}", "message": msg})
        for p, n, k in refs:
            if k not in vf.values:
                causes.append(Status.FAIL)
                details.append({"code": "R-10.unknown_key", "path": p, "line": n, "value": k})
        used = {k for _, _, k in refs}
        details += [{"code": "R-10.unused", "field": f"values.{k}"} for k in sorted(vf.values) if k not in used]
        gen = pp.rel(pp.resolved_values_out())
        if not comp.errors:
            expected = v.emit(comp.text, v.emit_format_for(gen))
            if not (ctx.root / gen).is_file():
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-10.generated_missing", "path": gen,
                                "message": f"run: steward paper values {name} --write"})
            elif ctx.read(gen).decode("utf-8", errors="replace") != expected:
                causes.append(Status.FAIL)
                details.append({"code": "R-10.generated_stale", "path": gen,
                                "message": f"values changed since generation; run: steward paper values {name} --write"})
        lits = _literals(ctx, pp)
        if lits and _mode(ctx, pp) == "final":
            causes.append(Status.INCOMPLETE)
        details += lits
        status = combine(causes)
        reason = {Status.FAIL: "values do not match their sources, the generated file, or the text's keys",
                  Status.INCOMPLETE: "value sources, the generated file, or unregistered numbers need attention"}.get(
            status, f"{len(vf.values)} value(s) match their sources; {len(refs)} reference(s) resolve"
            + (f"; {len(lits)} unregistered number(s) listed (heuristic)" if lits else ""))
        out.append(result("R-10", rel, status, reason, details, ctx.evidence(rel)))
    return out


def r15(ctx: Ctx) -> list[Result]:
    from . import values as v

    papers = _papers(ctx, "R-15")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        rel = pp.rel(pp.values)
        vf, comp, errors = _load_values(ctx, name, pp)
        if vf is None:
            why = "values registry is invalid (see R-10)" if errors else "no values registry"
            out.append(result("R-15", rel, Status.UNKNOWN if errors else Status.NOT_APPLICABLE, f"paper '{name}': {why}"))
            continue
        if not vf.assert_:
            out.append(result("R-15", rel, Status.NOT_APPLICABLE, f"paper '{name}': no assertions declared"))
            continue
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        for i, a in enumerate(vf.assert_):
            keys = v.REF.findall(a.expr)
            missing = [k for k in keys if k not in comp.raw]
            if missing:
                causes.append(Status.UNKNOWN)
                details.append({"code": "R-15.unavailable", "field": f"assert[{i}]", "value": a.expr, "message": f"values unavailable: {missing}"})
                continue
            try:
                ok = v.check_assertion(a, {k: float(comp.raw[k]) for k in keys})
            except (ValueError, TypeError, SyntaxError, ZeroDivisionError) as e:
                causes.append(Status.FAIL)
                details.append({"code": "R-15.invalid", "field": f"assert[{i}]", "value": a.expr, "message": str(e)})
                continue
            if not ok:
                causes.append(Status.FAIL)
                shown = ", ".join(f"{k}={comp.raw[k]}" for k in keys)
                details.append({"code": "R-15.violated", "field": f"assert[{i}]", "value": a.expr, "message": shown})
        status = combine(causes)
        reason = {Status.FAIL: "a declared relation between values does not hold",
                  Status.UNKNOWN: "some assertions could not be evaluated"}.get(status, f"{len(vf.assert_)} assertion(s) hold")
        out.append(result("R-15", rel, status, reason, details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- displays (v0.2.2): R-11
_REF_LABEL = re.compile(r"\\(?:ref|cref|Cref|autoref|eqref|pageref|nameref)\*?\{([^}]*)\}")
_INCLUDE = re.compile(r"\\(includegraphics(?:\[[^\]]*\])?|input|include)\{([^}]*)\}")
_GRAPHIC_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def _tex_body(ctx: Ctx, pp: m.PaperSection) -> list[tuple[str, int, str]]:
    out = []
    for rel in matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]):
        if not rel.endswith(".tex") or rel == pp.rel(pp.resolved_values_out()):
            continue
        text = ctx.read(rel).decode("utf-8", errors="replace")
        out += [(rel, n, _TEX_COMMENT.sub("", line)) for n, line in enumerate(text.splitlines(), start=1)]
    return out


def _resolve_include(pp: m.PaperSection, arg: str, graphic: bool) -> list[str]:
    """Repository-relative candidates for an \\includegraphics or \\input argument (relative to the paper dir)."""
    base = pp.rel(arg.strip())
    if Path(arg).suffix:
        return [base]
    return [base + e for e in _GRAPHIC_EXT] if graphic else [base + ".tex"]


def r11(ctx: Ctx) -> list[Result]:
    from . import displays as dsp

    papers = _papers(ctx, "R-11")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        rel = pp.rel(pp.displays)
        body = _tex_body(ctx, pp) if pp.ext == ".tex" else []
        graphics = [(p, n, a) for p, n, line in body for kind, a in _INCLUDE.findall(line) if kind.startswith("includegraphics")]
        inputs = [(p, n, a) for p, n, line in body for kind, a in _INCLUDE.findall(line) if not kind.startswith("includegraphics")]
        if not (ctx.root / rel).is_file():
            if graphics:
                st = Status.FAIL if _mode(ctx, pp) == "final" else Status.INCOMPLETE
                out.append(result("R-11", rel, st, f"paper '{name}': figures are included but there is no display manifest",
                                  [{"code": "R-11.unregistered", "path": p, "line": n, "value": a} for p, n, a in graphics]))
            else:
                out.append(result("R-11", rel, Status.NOT_APPLICABLE, f"paper '{name}': no display manifest"))
            continue
        data, errors = _load_toml(ctx, rel)
        try:
            df = dsp.DisplaysFile.model_validate(data) if data is not None else None
        except ValidationError as e:
            df, errors = None, m.format_errors(e)
        if df is None:
            out.append(result("R-11", rel, Status.FAIL, f"paper '{name}': display manifest is invalid", errors, ctx.evidence(rel)))
            continue
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        lock_rel = str(Path(rel).with_name("displays.lock"))
        lock = None
        if (ctx.root / lock_rel).is_file():
            try:
                doc = json.loads(ctx.read(lock_rel).decode("utf-8"))
                lock = doc.get("displays", {}) if isinstance(doc, dict) else None
                if not isinstance(lock, dict):
                    raise ValueError("displays is not a table")
            except (ValueError, UnicodeDecodeError):
                lock = None
                causes.append(Status.FAIL)
                details.append({"code": "R-11.lock_invalid", "path": lock_rel})
        cited = {lab.strip() for _, _, line in body for grp in _REF_LABEL.findall(line) for lab in grp.split(",")}
        included = set()
        for p, n, a in graphics:
            included.update(_resolve_include(pp, a, True))
        for p, n, a in inputs:
            included.update(_resolve_include(pp, a, False))
        outputs = {d.output for d in df.displays.values()}
        compared = 0
        for dname, d in sorted(df.displays.items()):
            for path in [d.script, *d.inputs, d.output]:
                if escapes_root(path):
                    causes.append(Status.FAIL)
                    details.append({"code": "R-11.path_outside", "field": f"displays.{dname}", "path": path})
            missing = dsp.missing_files(ctx.root, d)
            for path in missing:
                causes.append(Status.FAIL if path == d.script else Status.INCOMPLETE)
                details.append({"code": "R-11.missing_script" if path == d.script else "R-11.missing_file",
                                "field": f"displays.{dname}", "path": path})
            if pp.ext == ".tex":
                if d.label not in cited:
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-11.not_cited", "field": f"displays.{dname}", "value": d.label})
                if d.output not in included:
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-11.not_included", "field": f"displays.{dname}", "path": d.output})
            if lock is not None and not missing:
                if dname not in lock:
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-11.not_recorded", "field": f"displays.{dname}",
                                    "message": f"run: steward paper displays {name} --record"})
                elif not _lock_entry_ok(lock[dname]):  # red-team G4: no fingerprints, nothing to compare
                    causes.append(Status.FAIL)
                    details.append({"code": "R-11.lock_entry_invalid", "field": f"displays.{dname}", "path": lock_rel,
                                    "message": f"the lock entry has no recorded fingerprints; run: steward paper displays {name} --record"})
                else:
                    compared += 1
                    parts = dsp.stale_parts(lock[dname], dsp.fingerprint(ctx.root, d))
                    if parts:
                        causes.append(Status.FAIL)
                        details.append({"code": "R-11.stale", "field": f"displays.{dname}", "value": ",".join(parts),
                                        "message": "changed since the output was recorded; rebuild, then --record"})
        if lock is None and df.displays and not any(c == Status.FAIL for c in causes):
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-11.no_lock", "path": lock_rel, "message": f"run: steward paper displays {name} --record"})
        for p, n, a in graphics:
            if not set(_resolve_include(pp, a, True)) & outputs:
                causes.append(Status.FAIL if _mode(ctx, pp) == "final" else Status.INCOMPLETE)
                details.append({"code": "R-11.unregistered", "path": p, "line": n, "value": a})
        if compared:  # red-team F2: integrity coverage needs a fingerprint actually compared with the lock
            details.append({"code": "R-11.fingerprints_compared", "value": compared})
        if not df.displays:  # red-team E4: a valid but empty manifest inspected nothing
            details.append({"code": "R-11.nothing_to_check", "message": "the display manifest declares no displays"})
        status = combine(causes)
        reason = {Status.FAIL: "displays are stale, lack a script, or the manifest is invalid",
                  Status.INCOMPLETE: "displays are missing, uncited, not included, unrecorded or unregistered"}.get(
            status, f"{len(df.displays)} display(s) built from declared scripts and inputs, cited and current")
        out.append(result("R-11", rel, status, reason, details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- venue rules (v0.2.3): R-13
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff")


def pdf_reader_available() -> bool:
    """Whether any PDF reader is installed: poppler's pdfinfo or pypdf (red-team D5: absence vs a failed read)."""
    if shutil.which("pdfinfo"):
        return True
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def pdf_page_count(path: Path) -> int | None:
    if shutil.which("pdfinfo"):
        try:
            out = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60)
            mt = re.search(rb"^Pages:\s+(\d+)", out.stdout, re.M)
            if out.returncode == 0 and mt:
                return int(mt.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def pdf_author(path: Path) -> str | None:
    if shutil.which("pdfinfo"):
        try:
            out = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60)
            mt = re.search(rb"^Author:\s*(.*)$", out.stdout, re.M)
            return mt.group(1).decode("utf-8", errors="replace").strip() if mt else ""
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        from pypdf import PdfReader
        return str((PdfReader(str(path)).metadata or {}).get("/Author", "") or "")
    except Exception:
        return None


def _latex_words(fragment: str, vals: dict[str, str]) -> int:
    t = re.sub(r"\\val\{([^}]*)\}", lambda mt: vals.get(mt.group(1), "X"), fragment)
    t = _TEX_COMMENT.sub("", t) if "\n" not in t else "\n".join(_TEX_COMMENT.sub("", l) for l in t.splitlines())
    t = re.sub(r"\\(cite[a-z]*|ref|label|eqref)\*?(\[[^\]]*\])*\{[^}]*\}", " X ", t)
    t = re.sub(r"\\[A-Za-z]+\*?", " ", t)
    t = re.sub(r"[{}~]", " ", t)
    return sum(1 for w in t.split() if re.search(r"\w", w))


def _between(text: str, begin: str, end: str) -> str | None:
    i = text.find(begin)
    j = text.find(end, i + len(begin)) if i != -1 else -1
    return text[i + len(begin):j] if i != -1 and j != -1 else None


def _braced_arg(text: str, command: str) -> str | None:
    i = text.find(command + "{")
    if i == -1:
        return None
    depth, j = 1, i + len(command) + 1
    while j < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        j += 1
    return text[i + len(command) + 1:j - 1]


def r13(ctx: Ctx) -> list[Result]:
    from . import values as vmod

    papers = _papers(ctx, "R-13")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        vrel = pp.rel(pp.venue)
        if not (ctx.root / vrel).is_file():
            out.append(result("R-13", vrel, Status.NOT_APPLICABLE, f"paper '{name}': no venue profile"))
            continue
        data, _ = _load_toml(ctx, vrel)
        try:
            venue = m.Venue.model_validate(data) if data is not None else None
        except ValidationError:
            venue = None
        if venue is None:
            out.append(result("R-13", vrel, Status.UNKNOWN, f"paper '{name}': venue profile is invalid (see R-08)"))
            continue
        final = _mode(ctx, pp) == "final"
        viol = Status.FAIL if final else Status.INCOMPLETE
        causes: list[Status] = []
        details: list[dict[str, Any]] = [{"code": "R-13.mode", "value": _mode(ctx, pp)}]

        def unknown(code: str, msg: str) -> None:
            causes.append(Status.UNKNOWN)
            details.append({"code": code, "message": msg})

        def violated(code: str, **kw: Any) -> None:
            causes.append(viol)
            details.append({"code": code, **kw})

        if venue.source_url in m.SENTINELS or venue.retrieved in m.SENTINELS:
            unknown("R-13.no_source", "venue rules have no recorded source and date")
        lim = venue.limits
        pdf_rel = pp.rel(pp.resolved_pdf())
        pdf = ctx.root / pdf_rel
        page_limits = {k: getattr(lim, k) for k in ("pages_total", "pages_main")}
        for k, val in page_limits.items():
            if val in m.SENTINELS:
                unknown("R-13.limit_unspecified", f"limits.{k} is {val}")
        wanted = {k: val for k, val in page_limits.items() if isinstance(val, int)}
        if wanted:
            if pp.ext == ".docx":
                unknown("R-13.pages_unsupported", "page limits are not checked for .docx in this version")
            elif not pdf.is_file():
                unknown("R-13.no_pdf", f"{pdf_rel} not found; build the paper")
            else:
                ctx.read(pdf_rel)
                pages = pdf_page_count(pdf)
                if pages is None:
                    unknown("R-13.pdf_unreadable", "page count unavailable (install poppler or the [paper] extra)")
                else:
                    details.append({"code": "R-13.pages", "path": pdf_rel, "value": pages})
                    if "pages_total" in wanted and pages > wanted["pages_total"]:
                        violated("R-13.pages_total", value=pages, message=f"limit {wanted['pages_total']}")
                    if "pages_main" in wanted:
                        texts = pdf_text(pdf)
                        idx = next((i for i, t in enumerate(texts or []) if pp.main_ends_at in t), None)
                        if idx is None:
                            unknown("R-13.main_end_not_found", f"'{pp.main_ends_at}' not found in the PDF text")
                        elif idx + 1 > wanted["pages_main"]:
                            violated("R-13.pages_main", value=idx + 1, message=f"limit {wanted['pages_main']}")
        main_rel = pp.rel(pp.main)
        src = ""
        if (ctx.root / main_rel).is_file():
            if pp.ext == ".docx":
                src = _docx_text(ctx.root / main_rel) or ""
            else:
                src = ctx.read(main_rel).decode("utf-8", errors="replace")
        vals: dict[str, str] = {}
        if (ctx.root / pp.rel(pp.values)).is_file():
            vf, comp, _ = _load_values(ctx, name, pp)
            vals = comp.text if comp else {}
        for k, begin_end in (("abstract_words", ("\\begin{abstract}", "\\end{abstract}")), ("title_words", None)):
            limit = getattr(lim, k)
            if limit in m.SENTINELS:
                unknown("R-13.limit_unspecified", f"limits.{k} is {limit}")
            if not isinstance(limit, int):
                continue
            if pp.ext != ".tex":
                unknown("R-13.words_unsupported", f"{k} is checked for LaTeX sources only in this version")
                continue
            frag = _between(src, *begin_end) if begin_end else _braced_arg(src, "\\title")
            if frag is None:
                unknown("R-13.not_found", f"{'abstract' if begin_end else 'title'} not found in {main_rel}")
                continue
            words = _latex_words(frag, vals)
            details.append({"code": f"R-13.{k}", "value": words})
            if words > limit:
                violated(f"R-13.{k}_over", value=words, message=f"limit {limit}")
        # required sections and declarations: headings in the sources (or in the DOCX text)
        heads: set[str] = set()
        if pp.ext == ".docx":
            heads = {l.strip().lower() for l in src.splitlines() if l.strip()}
        else:
            for rel in matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]):
                if rel.endswith(".tex"):
                    t = ctx.read(rel).decode("utf-8", errors="replace")
                    heads |= {h.strip().lower() for h in re.findall(r"\\(?:section|subsection|subsubsection|paragraph)\*?\{([^}]*)\}", t)}
                elif rel.endswith((".md", ".qmd")):  # 0.20.0: Markdown headings, outside fenced code and front matter
                    from .records import _in_fence, fenced_spans

                    t = ctx.read(rel).decode("utf-8", errors="replace")
                    spans = fenced_spans(t)  # AN11: a fence closes only on its own marker; YAML front matter skipped
                    for mh in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", t, re.M):
                        if not _in_fence(t, mh.start(), spans):
                            heads.add(re.sub(r"\s*\{[^}]*\}$", "", mh.group(1)).strip().lower())
        for k in ("sections", "declarations"):
            req = getattr(venue.required, k)
            if req in m.SENTINELS:
                unknown("R-13.required_unspecified", f"required.{k} is {req}")
                continue
            for item in req:
                if item.strip().lower() not in heads:
                    violated(f"R-13.missing_{k[:-1]}", value=item)
        # double-blind anonymity
        if venue.anonymity.double_blind in m.SENTINELS:
            unknown("R-13.anonymity_unspecified", "anonymity.double_blind is not specified")
        elif venue.anonymity.double_blind is True:
            if not pp.anonymity_file or not (ctx.root / pp.anonymity_file).is_file():
                unknown("R-13.anonymity_no_list", "double-blind venue: set paper.anonymity_file (a gitignored list of names, affiliations, links)")
            else:
                try:
                    terms = _load_terms(ctx.read(pp.anonymity_file))
                except (OSError, UnicodeDecodeError):
                    terms = []
                    unknown("R-13.anonymity_unreadable", "anonymity file unreadable")
                pats = [re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in terms]
                scan = [(rel, ctx.read(rel).decode("utf-8", errors="replace")) for rel in
                        matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()]) if not rel.endswith(".docx")]
                if pdf.is_file():
                    texts = pdf_text(pdf)
                    if texts is None:
                        unknown("R-13.pdf_unreadable", "PDF text unavailable for the anonymity scan")
                    else:
                        scan.append((pdf_rel, "\f".join(texts)))
                    author = pdf_author(pdf)
                    if author:
                        violated("R-13.pdf_author_metadata", path=pdf_rel, message="the PDF metadata names an author")
                for rel, text in scan:
                    for k, pat in enumerate(pats, start=1):
                        if pat.search(text):
                            violated("R-13.anonymity", path=rel, term=f"#{k}")
        # figure formats and resolution
        fig = venue.figures
        files = sorted(_display_outputs(ctx, pp))
        if fig.formats not in m.SENTINELS:
            allowed = {f.lower().lstrip(".") for f in fig.formats}
            for rel in files:
                ext = Path(rel).suffix.lower().lstrip(".")
                if ext in ("tex",):  # TikZ/pgfplots or table sources are drawn by LaTeX, not image files
                    continue
                if ext not in allowed:
                    violated("R-13.figure_format", path=rel, value=ext)
        if isinstance(fig.min_dpi, int):
            for rel in files:
                if not rel.lower().endswith(_IMAGE_EXT) or not (ctx.root / rel).is_file():
                    continue
                try:
                    from PIL import Image
                except ImportError:
                    unknown("R-13.dpi_unavailable", "install the [paper] extra (Pillow) to check raster resolution")
                    break
                with Image.open(ctx.root / rel) as im:
                    dpi = im.info.get("dpi")
                if not dpi:
                    unknown("R-13.dpi_unknown", f"{rel} has no resolution metadata")
                elif min(float(dpi[0]), float(dpi[1])) < fig.min_dpi:
                    violated("R-13.figure_dpi", path=rel, value=round(min(float(dpi[0]), float(dpi[1]))))
        status = combine(causes)
        reason = {Status.FAIL: "the paper breaks venue rules (final mode)",
                  Status.INCOMPLETE: "the paper does not yet meet venue rules (draft mode)",
                  Status.UNKNOWN: "some venue rules could not be checked"}.get(status, "machine-checkable venue rules are met")
        out.append(result("R-13", vrel, status, reason, details, ctx.evidence(vrel)))
    return out


# ---------------------------------------------------------------- citations (v0.2.3): R-14
def r14(ctx: Ctx) -> list[Result]:
    from . import bib

    papers = _papers(ctx, "R-14")
    if papers and isinstance(papers[0], Result):
        return papers  # type: ignore[return-value]
    out = []
    for name, pp in papers:  # type: ignore[misc]
        if pp.ext != ".tex":
            out.append(result("R-14", pp.dir, Status.NOT_APPLICABLE, f"paper '{name}': citation checks are LaTeX/BibTeX-only in this version"))
            continue
        files = matching_files(ctx.root, [pp.rel(g) for g in pp.resolved_sources()])
        bibs = [f for f in files if f.endswith(".bib")]
        cites: dict[str, tuple[str, int]] = {}
        nocite_all = False
        for rel in files:
            if not rel.endswith(".tex"):
                continue
            for n, line in enumerate(ctx.read(rel).decode("utf-8", errors="replace").splitlines(), start=1):
                for grp in bib.CITE.findall(_TEX_COMMENT.sub("", line)):
                    for k in (x.strip() for x in grp.split(",")):
                        if k == "*":
                            nocite_all = True
                        elif k:
                            cites.setdefault(k, (rel, n))
        if not bibs and not cites:
            out.append(result("R-14", pp.dir, Status.NOT_APPLICABLE, f"paper '{name}': no bibliography and no citations"))
            continue
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        entries: list[tuple[str, Any]] = []
        for rel in bibs:
            try:
                entries += [(rel, e) for e in bib.parse(ctx.read(rel).decode("utf-8", errors="replace"))]
            except bib.BibError as e:
                causes.append(Status.FAIL)
                details.append({"code": "R-14.parse", "path": rel, "message": str(e)})
        keys: dict[str, list[str]] = {}
        dois: dict[str, list[str]] = {}
        verified = unverified = unavailable = 0
        for rel, e in entries:
            keys.setdefault(e.key, []).append(f"{rel}:{e.line}")
            ids = bib.identifiers(e)
            for bad in bib.malformed(ids):
                causes.append(Status.FAIL)
                details.append({"code": "R-14.malformed_identifier", "path": rel, "line": e.line, "value": e.key, "message": bad})
            if "doi" in ids and bib.DOI.match(ids["doi"]):
                dois.setdefault(ids["doi"].lower(), []).append(e.key)
            if any(k in ids for k in ("doi", "pmid", "arxiv", "url")):
                unverified += 1  # well-formed but not resolved: verification needs the online extra (not in this version)
            else:
                unavailable += 1
                details.append({"code": "R-14.no_identifier", "path": rel, "line": e.line, "value": e.key})
        for k, where in sorted(keys.items()):
            if len(where) > 1:
                causes.append(Status.FAIL)
                details.append({"code": "R-14.duplicate_key", "value": k, "message": ", ".join(where)})
        for d, ks in sorted(dois.items()):
            if len(set(ks)) > 1:
                causes.append(Status.FAIL)
                details.append({"code": "R-14.duplicate_doi", "value": d, "message": ", ".join(sorted(set(ks)))})
        for k, (rel, n) in sorted(cites.items()):
            if k not in keys:
                causes.append(Status.FAIL)
                details.append({"code": "R-14.missing_entry", "path": rel, "line": n, "value": k})
        if not nocite_all:
            details += [{"code": "R-14.unused", "value": k} for k in sorted(keys) if k not in cites]
        details.append({"code": "R-14.verification", "message": f"verified {verified}, unverified {unverified}, "
                        f"unavailable {unavailable}; online verification is not part of this version"})
        status = combine(causes)
        reason = {Status.FAIL: "citations or bibliography entries are missing, duplicated or malformed"}.get(
            status, f"{len(cites)} cited key(s) resolve; {len(entries)} entr(ies) well-formed (existence not verified)")
        out.append(result("R-14", pp.dir, status, reason, details, [e for rel in bibs for e in ctx.evidence(rel)]))
    return out


# ---------------------------------------------------------------- PresentationKit (v0.3): R-21 … R-29
_OVERSTATEMENT = re.compile(r"\b(validated|demonstrates?|proves?|proven|state[- ]of[- ]the[- ]art|solves?|outperforms?|"
                            r"breakthrough|definitive(ly)?|guarantees?)\b", re.I)
_FRAME_TITLE = re.compile(r"\\begin\{frame\}(?:<[^>]*>)?(?:\[[^\]]*\])?\{([^}]*)\}|\\frametitle\{([^}]*)\}|\\(?:sub)?section\*?\{([^}]*)\}")


def _talks(ctx: Ctx, rule: str) -> list[tuple[str, Any]] | list[Result]:
    assert ctx.config is not None
    if not ctx.config.talk:
        return [result(rule, ".", Status.NOT_APPLICABLE, "no talk configured")]
    return sorted(ctx.config.talk.items())


def _talk_plan(ctx: Ctx, name: str, tt: Any) -> tuple[Any, list[dict[str, Any]]]:
    from . import talk as tk

    key = f"talkplan:{name}"
    if key in ctx.values_cache:
        return ctx.values_cache[key]
    rel = tt.rel(tt.plan)
    out: tuple[Any, list[dict[str, Any]]]
    if not (ctx.root / rel).is_file():
        out = (None, [{"code": "missing", "path": rel}])
    else:
        data, errors = _load_toml(ctx, rel)
        if data is None:
            out = (None, errors)
        else:
            try:
                out = (tk.TalkPlan.model_validate(data), [])
            except ValidationError as e:
                out = (None, m.format_errors(e))
    ctx.values_cache[key] = out
    return out


def _talk_text(ctx: Ctx, tt: Any) -> list[tuple[str, int, str]]:
    out = []
    for rel in matching_files(ctx.root, [tt.rel("**/*.tex")]):
        text = ctx.read(rel).decode("utf-8", errors="replace")
        out += [(rel, n, _TEX_COMMENT.sub("", line)) for n, line in enumerate(text.splitlines(), start=1)]
    return out


def _talk_mode(ctx: Ctx, tt: Any) -> str:
    return "final" if ctx.final or tt.mode == "final" else "draft"


def _each_talk(ctx: Ctx, rule: str, fn: Callable[[str, Any, Any], Result]) -> list[Result]:
    talks = _talks(ctx, rule)
    if talks and isinstance(talks[0], Result):
        return talks  # type: ignore[return-value]
    out = []
    for name, tt in talks:  # type: ignore[misc]
        plan, errors = _talk_plan(ctx, name, tt)
        if plan is None and rule != "R-21":
            out.append(result(rule, tt.rel(tt.plan), Status.UNKNOWN, f"talk '{name}': plan missing or invalid (see R-21)"))
            continue
        out.append(fn(name, tt, plan))
    return out


def r21(ctx: Ctx) -> list[Result]:
    def one(name: str, tt: Any, plan: Any) -> Result:
        rel = tt.rel(tt.plan)
        p, errors = _talk_plan(ctx, name, tt)
        if p is None:
            missing = errors and errors[0].get("code") == "missing"
            return result("R-21", rel, Status.INCOMPLETE if missing else Status.FAIL,
                          f"talk '{name}': plan {'is missing' if missing else 'violates schema steward.talk/0.1'}",
                          [] if missing else errors, ctx.evidence(rel))
        from . import talk as tk

        causes, details = _sentinel_status(m.find_sentinels(p))
        if p.stage not in m.SENTINELS and tk.ceiling(p.stage) is None:
            causes.append(Status.FAIL)
            details.append({"code": "R-21.unknown_stage", "value": p.stage})
        if p.purpose not in m.SENTINELS and p.purpose not in tk.taxonomy()["purposes"]:
            details.append({"code": "R-21.custom_purpose", "value": p.purpose})
        if p.feedback == "targeted" and not p.unresolved_decisions:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-21.no_decisions", "message": "feedback = targeted needs unresolved_decisions"})
        if (ctx.root / tt.rel(tt.main)).is_file() and not p.outline:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-21.no_outline", "message": f"run: steward talk plan {name} --write-outline"})
        try:
            from . import talk as tk2
            tk2.Prefs.model_validate({k: v for k, v in p.overrides.items() if k not in tk2.TALK_ONLY})
        except ValidationError as e:
            causes.append(Status.FAIL)
            details += [{**d, "code": "R-21.overrides"} for d in m.format_errors(e)]
        status = combine(causes)
        return result("R-21", rel, status, _reason(status, f"talk '{name}': plan is inconsistent",
                      f"talk '{name}': plan is incomplete", f"talk '{name}': plan has unknown fields",
                      f"talk '{name}': plan is consistent with steward.talk/0.1"), details, ctx.evidence(rel))
    talks = _talks(ctx, "R-21")
    if talks and isinstance(talks[0], Result):
        return talks  # type: ignore[return-value]
    return [one(n, t, None) for n, t in talks]  # type: ignore[misc]


def r22(ctx: Ctx) -> list[Result]:
    from . import talk as tk

    def one(name: str, tt: Any, p: Any) -> Result:
        rel = tt.rel(tt.plan)
        details = []
        if p.stage not in m.SENTINELS and p.purpose not in m.SENTINELS and tk.unusual(p.stage, p.purpose):
            details.append({"code": "R-22.unusual", "message": f"{p.stage} x {p.purpose}: confirm this combination"})
        if p.stage_source != "confirmed" or p.stage in m.SENTINELS:
            return result("R-22", rel, Status.UNKNOWN, f"talk '{name}': research stage not confirmed by a human", details)
        return result("R-22", rel, Status.PASS, f"talk '{name}': stage '{p.stage}' confirmed", details)
    return _each_talk(ctx, "R-22", one)


def _talk_registry(ctx: Ctx, tt: Any) -> tuple[Any, Any]:
    if tt.paper and ctx.config and tt.paper in ctx.config.paper:
        vf, comp, _ = _load_values(ctx, tt.paper, ctx.config.paper[tt.paper])
        return vf, comp
    return None, None


def r23(ctx: Ctx) -> list[Result]:
    from . import bib
    from . import talk as tk

    def one(name: str, tt: Any, p: Any) -> Result:
        rel = tt.rel(tt.plan)
        if p.stage in m.SENTINELS or tk.ceiling(p.stage) is None:
            return result("R-23", rel, Status.UNKNOWN, f"talk '{name}': stage unknown; ceiling cannot be applied")
        ceil = tk.ceiling(p.stage)
        vf, comp = _talk_registry(ctx, tt)
        causes: list[Status] = []
        details: list[dict[str, Any]] = [{"code": "R-23.ceiling", "value": ceil}]
        for c in p.claims:
            if c.status == "unknown":
                causes.append(Status.UNKNOWN)
                details.append({"code": "R-23.unknown_status", "value": c.id})
                continue
            if tk.rank(c.status) <= tk.rank(ceil):
                continue
            if not c.evidence:
                causes.append(Status.FAIL)
                details.append({"code": "R-23.overstatement", "value": c.id, "message": f"{c.status} exceeds the {p.stage} ceiling ({ceil}) with no evidence"})
                continue
            ok = False
            if c.status == "validated":
                contracts = [e[len("contract:"):] for e in c.evidence if e.startswith("contract:")]
                confirm = any(x.id == cid and x.analysis == "confirmatory" for cid in contracts for x in ctx.contracts.values())
                vals = [e[len("value:"):] for e in c.evidence if e.startswith("value:")]
                ok = confirm and bool(vals) and comp is not None and all(v in comp.raw for v in vals)
            elif c.status == "published":
                ok = any((e.startswith("doi:") and bib.DOI.match(e[4:])) or (e.startswith("pmid:") and bib.PMID.match(e[5:]))
                         or (e.startswith("arxiv:") and bib.ARXIV.match(e[6:])) for e in c.evidence)
            else:
                ok = True  # implemented/preliminary above a concept ceiling: evidence listed is accepted as declared
            if not ok:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-23.evidence_insufficient", "value": c.id,
                                "message": f"{c.status} needs " + ("a confirmatory contract and computed value(s)" if c.status == "validated" else "a doi:/pmid:/arxiv: reference")})
        status = combine(causes)
        return result("R-23", rel, status, _reason(status, f"talk '{name}': a claim exceeds the stage ceiling without evidence",
                      f"talk '{name}': claims above the ceiling lack sufficient evidence", f"talk '{name}': some claims have unknown status",
                      f"talk '{name}': {len(p.claims)} claim(s) within the {p.stage} ceiling or supported"), details, ctx.evidence(rel))
    return _each_talk(ctx, "R-23", one)


def _tfacts(ctx: Ctx, name: str, tt: Any, p: Any) -> Any:
    from . import talk as tk
    from . import talk_sources as ts

    key = f"tfacts:{name}"
    if key not in ctx.values_cache:
        try:
            prefs = tk.resolve(ctx.root, p.overrides, p.context_profile)
            min_font = float(prefs["typography.min_font_pt"][0])
        except (ValidationError, ValueError, RecursionError):
            min_font = 14.0
        ctx.values_cache[key] = (ts.facts(ctx.root, tt, ctx.read, min_font), min_font)
    return ctx.values_cache[key]


def r24(ctx: Ctx) -> list[Result]:
    from . import talk_sources as ts
    from . import values as v

    def one(name: str, tt: Any, p: Any) -> Result:
        f, _ = _tfacts(ctx, name, tt, p)
        refs = f.value_refs
        vf, comp = _talk_registry(ctx, tt)
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        if refs and vf is None:
            return result("R-24", tt.dir, Status.FAIL, f"talk '{name}': slides use value keys but no linked paper registry",
                          [{"code": "R-24.no_registry", "path": r, "line": n, "value": k} for r, n, k in refs])
        for r, n, k in refs:
            if k not in vf.values:
                causes.append(Status.FAIL)
                details.append({"code": "R-24.unknown_key", "path": r, "line": n, "value": k})
        if f.engine == "quarto" and refs and comp is not None and not comp.errors:
            gen = tt.rel("_variables.yml")
            expected = v.emit(comp.text, "quarto")
            if not (ctx.root / gen).is_file():
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-24.variables_missing", "path": gen, "message": f"run: steward talk values {name} --write"})
            elif ctx.read(gen).decode("utf-8", errors="replace") != expected:
                causes.append(Status.FAIL)
                details.append({"code": "R-24.variables_stale", "path": gen, "message": f"run: steward talk values {name} --write"})
        skip = set()
        if tt.paper and ctx.config:
            skip |= _display_outputs(ctx, ctx.config.paper[tt.paper])
        skip.add(tt.rel("_variables.yml"))
        started: dict[str, bool] = {}
        for r, n, line in f.text:
            if r in skip or "literal-ok" in f.raw_lines.get((r, n), ""):
                continue
            if f.engine == "beamer":
                if "\\begin{document}" in line:
                    started[r] = True
                    continue
                if not started.get(r):
                    continue
                line = _STRIP_CMDS.sub(" ", line)
            else:
                line = ts._QVAR.sub(" ", line)
            for mt in _LITERAL.finditer(line):
                num = mt.group(0).strip()
                if not _YEAR.match(num):
                    details.append({"code": "R-24.literal", "path": r, "line": n, "value": num})
        if any(d["code"] == "R-24.literal" for d in details) and _talk_mode(ctx, tt) == "final":
            causes.append(Status.INCOMPLETE)
        status = combine(causes)
        if not refs and not details:
            return result("R-24", tt.dir, Status.PASS, f"talk '{name}': no numbers on slides")
        return result("R-24", tt.dir, status, {Status.FAIL: f"talk '{name}': value keys do not resolve or variables are stale",
                      Status.INCOMPLETE: f"talk '{name}': generated variables missing, or unregistered numbers (final mode)"}.get(
                      status, f"talk '{name}': {len(refs)} value reference(s) resolve"), details)
    return _each_talk(ctx, "R-24", one)


def r25(ctx: Ctx) -> list[Result]:
    def one(name: str, tt: Any, p: Any) -> Result:
        if p.stage in m.SENTINELS:
            return result("R-25", tt.rel(tt.plan), Status.INCOMPLETE if p.stage == "TBD" else Status.UNKNOWN,
                          f"talk '{name}': stage not set; whether limitations are required cannot be decided")
        need = (p.stage in ("evaluation", "completed", "published")) or any(c.status == "validated" for c in p.claims)
        if not need:
            return result("R-25", tt.rel(tt.plan), Status.NOT_APPLICABLE, f"talk '{name}': stage '{p.stage}' with no validated claims")
        f, _ = _tfacts(ctx, name, tt, p)
        has_role = any(o.role == "limitations" for o in p.outline)
        has_frame = any(re.search(r"limitation", t, re.I) for t in f.titles)
        if has_role and has_frame:
            return result("R-25", tt.rel(tt.plan), Status.PASS, f"talk '{name}': limitations are presented")
        return result("R-25", tt.rel(tt.plan), Status.INCOMPLETE, f"talk '{name}': limitations are required at this stage",
                      [{"code": "R-25.missing_role"}] * (not has_role) + [{"code": "R-25.missing_frame"}] * (not has_frame))
    return _each_talk(ctx, "R-25", one)


def r26(ctx: Ctx) -> list[Result]:
    def one(name: str, tt: Any, p: Any) -> Result:
        rel = tt.rel(tt.plan)
        roles = {o.role for o in p.outline}
        f, _ = _tfacts(ctx, name, tt, p)
        text = " ".join(line for _, _, line in f.text).lower()
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        if p.feedback == "targeted":
            if "decisions-needed" not in roles:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-26.no_decisions_section"})
            for d in p.unresolved_decisions:
                if d.lower() not in text:
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-26.decision_not_shown", "value": d})
        elif p.feedback == "informational":
            bad = roles & {"feedback-requested", "open-questions", "input-needed"}
            if bad and not p.overrides.get("allow_feedback_slides"):
                causes.append(Status.FAIL)
                details += [{"code": "R-26.feedback_slide_in_informational", "value": r} for r in sorted(bad)]
        elif p.feedback == "defense" and "qa-backup" not in roles:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-26.no_qa_backup"})
        if p.feedback in m.SENTINELS:
            causes.append(Status.INCOMPLETE if p.feedback == "TBD" else Status.UNKNOWN)
        for sec in p.required_sections:
            if sec.lower() not in text:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-26.required_section", "value": sec})
        if not f.text and f.engine != "beamer":
            causes.append(Status.UNKNOWN)
            details += [{"code": "R-26.no_text", "message": n} for n in f.notes]
        status = combine(causes)
        return result("R-26", rel, status, _reason(status, f"talk '{name}': structure contradicts the feedback mode",
                      f"talk '{name}': structure misses what the feedback mode needs", f"talk '{name}': feedback mode or slide text unknown",
                      f"talk '{name}': structure matches feedback mode '{p.feedback}'"), details, ctx.evidence(rel))
    return _each_talk(ctx, "R-26", one)


def r27(ctx: Ctx) -> list[Result]:
    from . import displays as dsp

    def one(name: str, tt: Any, p: Any) -> Result:
        f, _ = _tfacts(ctx, name, tt, p)
        if f.engine == "keynote":
            return result("R-27", tt.dir, Status.UNKNOWN, f"talk '{name}': Keynote images cannot be traced to displays; "
                          "export to PPTX or Beamer for figure checks", [{"code": "R-27.not_traceable"}])
        manifests = []
        if tt.paper and ctx.config:
            pp = ctx.config.paper[tt.paper]
            manifests.append(pp.rel(pp.displays))
        manifests.append(tt.rel(tt.displays))
        declared: dict[str, tuple[str, Any, Any]] = {}
        for mrel in manifests:
            if not (ctx.root / mrel).is_file():
                continue
            data, _ = _load_toml(ctx, mrel)
            try:
                df = dsp.DisplaysFile.model_validate(data) if data else None
            except ValidationError:
                df = None
            if df is None:
                continue
            lock_rel = str(Path(mrel).with_name("displays.lock"))
            lock = json.loads((ctx.root / lock_rel).read_text()).get("displays", {}) if (ctx.root / lock_rel).is_file() else None
            for dname, d in df.displays.items():
                declared[d.output] = (dname, d, (lock or {}).get(dname))
        by_hash = {}
        for out_rel, entry in declared.items():
            h = sha256_bytes((ctx.root / out_rel).read_bytes()) if (ctx.root / out_rel).is_file() else None
            if h:
                by_hash[h] = out_rel
        causes: list[Status] = []
        details: list[dict[str, Any]] = []
        used = 0
        hits: list[tuple[str, int, str | None, str]] = []
        for r, n, arg, graphic in f.includes:
            base = os.path.normpath(str(Path(r).parent / arg.strip())).replace(os.sep, "/")
            cands = [base] if Path(arg).suffix else ([base + e for e in _GRAPHIC_EXT] if graphic else [base + ".tex"])
            hits.append((r, n, next((c for c in cands if c in declared), None), arg if graphic else ""))
        for r, n, h in f.image_hashes:
            hits.append((r, n, by_hash.get(h), f"image on slide {n}"))
        for r, n, hit, label in hits:
            if hit is None:
                if label:
                    causes.append(Status.FAIL if _talk_mode(ctx, tt) == "final" else Status.INCOMPLETE)
                    details.append({"code": "R-27.unregistered", "path": r, "line": n, "value": label})
                continue
            used += 1
            dname, d, recorded = declared[hit]
            missing = dsp.missing_files(ctx.root, d)
            if missing:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-27.missing_file", "value": dname, "message": ", ".join(missing)})
            elif recorded is None:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-27.not_recorded", "value": dname})
            elif dsp.stale_parts(recorded, dsp.fingerprint(ctx.root, d)):
                causes.append(Status.FAIL)
                details.append({"code": "R-27.stale", "value": dname})
        status = combine(causes)
        if used == 0 and not details:
            return result("R-27", tt.dir, Status.PASS, f"talk '{name}': no figures or generated tables on slides",
                          [{"code": "R-27.nothing_to_trace"}])
        return result("R-27", tt.dir, status, {Status.FAIL: f"talk '{name}': slides use stale or unregistered displays",
                      Status.INCOMPLETE: f"talk '{name}': displays unregistered or unrecorded"}.get(
                      status, f"talk '{name}': {used} display(s) from declared, current builds"), details)
    return _each_talk(ctx, "R-27", one)


def r28(ctx: Ctx) -> list[Result]:
    from . import talk as tk
    from . import talk_sources as ts

    def one(name: str, tt: Any, p: Any) -> Result:
        final = _talk_mode(ctx, tt) == "final"
        viol = Status.FAIL if final else Status.INCOMPLETE
        f, min_font = _tfacts(ctx, name, tt, p)
        causes: list[Status] = []
        details: list[dict[str, Any]] = [{"code": "R-28.engine", "value": f.engine}] + [{"code": "R-28.note", "message": n} for n in f.notes]
        try:
            prefs = tk.resolve(ctx.root, p.overrides, p.context_profile)
        except (ValidationError, ValueError, RecursionError) as e:
            return result("R-28", tt.dir, Status.FAIL, f"talk '{name}': a preference layer is invalid", [{"code": "R-28.prefs", "message": str(e).splitlines()[0]}])
        ratio = tk.contrast(prefs["palette.text"][0], prefs["palette.background"][0])
        need = float(prefs["accessibility.min_contrast"][0])
        details.append({"code": "R-28.contrast", "value": round(ratio, 2), "message": f"minimum {need}"})
        if ratio < need:
            causes.append(Status.FAIL)
        pdf_rel = tt.rel(tt.resolved_pdf())
        pdf = ctx.root / pdf_rel
        layout = None
        pages = None
        if pdf.is_file() and f.engine in ("beamer", "quarto", "keynote"):
            ctx.read(pdf_rel)
            pages = pdf_page_count(pdf)
            layout = ts.pdf_layout(pdf, min_font)
        elif f.engine == "pptx":
            pages, layout = f.slide_count, f.layout
        elif f.engine == "quarto":
            pages = f.slide_count
        if p.duration_min in m.SENTINELS:
            causes.append(Status.INCOMPLETE if p.duration_min == "TBD" else Status.UNKNOWN)
        elif pages is None:
            causes.append(Status.UNKNOWN)
            if pdf.is_file() and pdf_reader_available():  # red-team D5: a reader is there and could not read it
                details.append({"code": "R-28.pdf_unreadable", "path": pdf_rel,
                                "message": "the installed PDF reader could not read this file; rebuild the PDF"})
            elif pdf.is_file():  # red-team B6: the PDF is there; the tool to read it is not
                details.append({"code": "R-28.pdf_reader_missing", "path": pdf_rel,
                                "message": "install a PDF reader: poppler (pdfinfo, pdftotext) or the [talk] extra (pypdf)"})
            else:
                details.append({"code": "R-28.no_pdf", "path": pdf_rel})
        else:
            limit = p.max_slides if isinstance(p.max_slides, int) else tk.auto_max_slides(float(p.duration_min), prefs["style.density"][0])
            details.append({"code": "R-28.slides", "value": pages, "message": f"maximum {limit}"})
            if pages > limit:
                causes.append(viol)
                details.append({"code": "R-28.too_many_slides", "value": pages})
        if layout is None:
            details.append({"code": "R-28.not_assessed", "message": "font size and slide bounds: no PDF layout or PPTX shapes available"})
        else:
            details.append({"code": "R-28.min_font", "value": layout["min_font"], "message": f"minimum {min_font} pt (960 pt wide slide)"})
            for s in layout["small"]:
                causes.append(viol)
                details.append({"code": "R-28.font_too_small", "line": s["page"], "value": s["value"]})
            for o in layout["outside"]:
                causes.append(viol)
                details.append({"code": "R-28.outside_slide", "line": o["page"]})
        if f.engine == "beamer":
            log_rel = tt.rel(tt.resolved_log())
            if (ctx.root / log_rel).is_file():
                for n, line in enumerate(ctx.read(log_rel).decode("utf-8", errors="replace").splitlines(), start=1):
                    if re.match(r"^Overfull \\vbox", line):
                        causes.append(viol)
                        details.append({"code": "R-28.frame_overflow", "path": log_rel, "line": n})
                    elif re.search(r"(Reference|Citation) [`'\"][^'\"]+['\"] on page \d+ undefined|^! ", line):
                        causes.append(Status.FAIL)
                        details.append({"code": "R-28.build_error", "path": log_rel, "line": n})
            else:
                causes.append(Status.UNKNOWN)
                details.append({"code": "R-28.no_log", "path": log_rel})
        status = combine(causes)
        return result("R-28", tt.dir, status, {Status.FAIL: f"talk '{name}': visual or build rules are broken",
                      Status.INCOMPLETE: f"talk '{name}': duration not set, too many slides, small fonts, or overflow (draft)",
                      Status.UNKNOWN: f"talk '{name}': PDF, log or duration unavailable"}.get(
                      status, f"talk '{name}': slide count, fonts, bounds and contrast within limits" if layout is not None
                      else f"talk '{name}': slide count and contrast within limits; fonts and bounds not assessed (no PDF layout reader)"),
                      details)
    return _each_talk(ctx, "R-28", one)


def r29(ctx: Ctx) -> list[Result]:
    from . import talk as tk

    def one(name: str, tt: Any, p: Any) -> Result:
        top = max((tk.rank(c.status) for c in p.claims if c.status != "unknown"), default=-1)
        if top >= tk.rank("validated"):
            return result("R-29", tt.dir, Status.PASS, f"talk '{name}': validated claims declared; wording not listed")
        f, _ = _tfacts(ctx, name, tt, p)
        hits = [{"code": "R-29.strong_wording", "path": r, "line": n, "value": mt.group(0)}
                for r, n, line in f.text for mt in _OVERSTATEMENT.finditer(line)]
        return result("R-29", tt.dir, Status.PASS,
                      f"talk '{name}': {len(hits)} strong wording(s) listed for human review (advisory)" if hits
                      else f"talk '{name}': no strong wording found", hits)
    return _each_talk(ctx, "R-29", one)


# ---------------------------------------------------------------- run safety (v0.4): R-31, R-32
def configured_ledgers(cfg: m.StewardConfig) -> list[tuple[str, str]]:
    out = []
    if cfg.run is not None:
        out.append(("runs", cfg.run.ledger))
    for attr, name in (("policy", "authorizations"), ("spend", "spend"), ("integrity", "integrity")):
        sec = getattr(cfg, attr, None)
        if sec is not None and getattr(sec, "ledger", None):
            out.append((name, sec.ledger))
    return out


def r31(ctx: Ctx) -> list[Result]:
    from . import ledger as lg

    assert ctx.config is not None
    ledgers = configured_ledgers(ctx.config)
    if not ledgers:
        return [result("R-31", ".", Status.NOT_APPLICABLE, "no ledger configured")]
    out = []
    for name, rel in ledgers:
        if escapes_root(rel):
            out.append(result("R-31", rel, Status.FAIL, f"{name} ledger path is outside the repository"))
            continue
        path = ctx.root / rel
        if not path.is_file():
            out.append(result("R-31", rel, Status.NOT_APPLICABLE, f"{name} ledger does not exist yet"))
            continue
        ctx.read(rel)
        v = lg.verify(path)
        details = list(v.errors)
        anchors = _anchor_details(ctx, name, v)
        details += anchors
        details.append({"code": "R-31.coverage", "message": "tamper evidence: edits, gaps and broken chains are detected; "
                        "a truncated tail or consistent rewrite only against a signed anchor"})
        if v.errors or any(d["code"] == "R-31.anchor_mismatch" for d in anchors):
            st, why = Status.FAIL, f"{name} ledger chain or anchor is broken; restore from version control"
        elif any(d["code"] == "R-31.anchor_unavailable" for d in anchors):
            st, why = Status.UNKNOWN, f"{name} ledger: chain intact; its signed anchors cannot be verified here"
        elif v.torn_tail:
            st, why = Status.INCOMPLETE, f"{name} ledger has a torn tail; run: steward ledger recover {rel}"
            details.append({"code": "R-31.torn_tail", "value": len(v.torn_tail)})
        else:
            st, why = Status.PASS, f"{name} ledger: {len(v.entries)} entries, chain intact"
        out.append(result("R-31", rel, st, why, details, ctx.evidence(rel)))
    return out


def _anchor_details(ctx: Ctx, name: str, v: Any) -> list[dict[str, Any]]:
    """Anchors (signed tags `steward/anchor/<ledger>/<seq>`, v0.4.1) are compared when present."""
    from . import authorize as az
    from .authorize import ledger_anchors

    if az.READ_ONLY and az.list_tags(ctx.root, f"steward/anchor/{name}/"):  # review N12: not verifiable here
        return [{"code": "R-31.anchor_unavailable", "message": "signed anchors exist but are not verified through the MCP server"}]
    anchors, unverified = ledger_anchors(ctx.root, ctx.config, name)
    out: list[dict[str, Any]] = [{"code": "R-31.anchor_unverified", "value": t} for t in unverified]
    if not anchors:
        return out + [{"code": "R-31.anchor_none", "message": "no signed anchor: tail truncation is undetectable"}]
    by_seq = {e["seq"]: e["hash"] for e in v.entries}
    for seq, h in anchors:
        if by_seq.get(seq) != h:
            out.append({"code": "R-31.anchor_mismatch", "value": seq})
        else:
            out.append({"code": "R-31.anchor_ok", "value": seq})
    return out


def r32(ctx: Ctx) -> list[Result]:
    from . import ledger as lg

    assert ctx.config is not None
    if ctx.config.run is None:
        return [result("R-32", ".", Status.NOT_APPLICABLE, "[run] is not configured")]
    rel = ctx.config.run.ledger
    if not (ctx.root / rel).is_file():
        return [result("R-32", rel, Status.NOT_APPLICABLE, "no runs recorded yet")]
    v = lg.verify(ctx.root / rel)
    if v.errors:
        return [result("R-32", rel, Status.UNKNOWN, "run ledger is not intact (see R-31)")]
    started = {e["run"]: e for e in v.entries if e.get("kind") == "started"}
    ended = {e["run"]: e for e in v.entries if e.get("kind") in ("outcome", "interrupted")}
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    shared = bool(ctx.config.run.slots_dir or __import__("os").environ.get("STEWARD_SLOTS_DIR"))  # review N11
    for run_id in sorted(started):
        if shared and started[run_id].get("slot") and started[run_id].get("slot_scope", "repository") == "repository":
            details.append({"code": "R-32.local_slot", "value": run_id,  # SR-001: it did not share permits
                            "message": "this run used a repository-local slot while a shared slots_dir is configured"})
        if run_id not in ended:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-32.unfinished", "value": run_id, "message": "running or interrupted; steward run --recover"})
            continue
        end = ended[run_id]
        if end.get("kind") == "interrupted" or end.get("status") in ("failed", "killed"):
            details.append({"code": f"R-32.{end.get('status', 'interrupted')}", "value": run_id,
                            "message": end.get("breached") or f"exit {end.get('exit_code')}"})
        for out_rel, recorded in sorted((end.get("outputs") or {}).items()):
            p = ctx.root / out_rel
            current = sha256_bytes(p.read_bytes()) if p.is_file() else None
            if current != recorded:
                details.append({"code": "R-32.output_changed", "value": run_id, "path": out_rel})
    status = combine(causes)
    n_fail = sum(1 for d in details if d["code"] in ("R-32.failed", "R-32.killed", "R-32.interrupted"))
    return [result("R-32", rel, status, "unfinished runs need recovery" if status is Status.INCOMPLETE else
                   f"{len(started)} run(s) recorded, {n_fail} failed, killed or interrupted (retained)", details, ctx.evidence(rel))]


# ---------------------------------------------------------------- policy baseline (v0.4.1): R-33
def r33(ctx: Ctx) -> list[Result]:
    from . import authorize as az

    assert ctx.config is not None
    pinned_rid = az.pin_for_checkout(ctx.root)
    if pinned_rid and pinned_rid != ctx.config.steward.repo_id:  # review N3: an unsigned repo_id edit
        return [result("R-33", ".", Status.FAIL, "repo_id differs from the one pinned for this checkout",
                       [{"code": "R-33.repo_id_changed", "message": "restore repo_id, or re-pin yourself (steward authorize pin)"}])]
    if ctx.config.policy is None:
        pinned = az.pinned_trust_exists(ctx.config, ctx.root)
        if pinned:  # adopter review: one unsigned edit must not switch signed policy off
            return [result("R-33", ".", Status.FAIL, "[policy] was removed while a trust root is pinned for this repository",
                           [{"code": "R-33.policy_removed", "value": pinned,
                             "message": "restore [policy], or remove the pin yourself (it lives outside the repository)"}])]
        return [result("R-33", ".", Status.NOT_APPLICABLE, "[policy] is not configured")]
    pol = ctx.config.policy
    if not az.policy_active(ctx.config, ctx.root):  # REQ-016: decided, not yet set up
        return [result("R-33", ".", Status.INCOMPLETE, "[policy] is pending: the trust root is not set up yet",
                       [{"code": "R-33.pending", "message": f"1. create an approval key; 2. add its public key to "
                         f"{pol.allowed_signers} and commit it on {pol.baseline}; 3. run `steward authorize pin`; "
                         "4. set [policy] state = \"active\""}])]
    trust = az.resolve_trust(ctx.root, ctx.config)
    if trust.source == "unreadable":  # S2
        return [result("R-33", ".", Status.UNKNOWN, "the per-user trust pin cannot be read; repair it or re-pin "
                       "(steward authorize pin)", [{"code": "R-33.pin_unreadable"}])]
    try:
        base = az.resolve_baseline(ctx.root, trust.baseline_ref)
    except (az.AuthError, OSError, subprocess.SubprocessError) as e:
        return [result("R-33", ".", Status.UNKNOWN, f"policy baseline unavailable: {e}")]
    wt, changed = az.policy_change(ctx.root, ctx.config, base)
    details: list[dict[str, Any]] = [{"code": "R-33.overlay", "path": d["path"], "value": d["value"],
                                      "message": "a configuration overlay adds to this policy (it cannot relax it)"}
                                     for d in ctx.overlay]
    details += [{"code": "R-33.trust_root", "value": trust.source,
                                      "message": f"baseline {trust.baseline_ref} = {base[:12]}"}]
    if not re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", trust.baseline_ref):  # a branch or tag can move under the pin
        details.append({"code": "R-33.baseline_moving", "value": trust.baseline_ref,
                        "message": "the baseline is a ref name; pin a reviewed commit (steward authorize pin) so a later "
                                   "unsigned edit on that ref is not absorbed"})
    signers = trust.signers if trust.source != "working-tree" else az.baseline_file(ctx.root, base, pol.allowed_signers)
    if signers is None:
        return [result("R-33", ".", Status.UNKNOWN, f"{pol.allowed_signers} is not on the baseline; signing is not set up", details)]
    details += [{"code": "R-33.signer", "value": k["principal"], "message": f"{k['type']}; hardware-backed: {k['hardware']}"}
                for k in az.signer_keys(signers.decode("utf-8", errors="replace"))]
    details += [{"code": "R-33.fingerprint", "message": f} for f in az.fingerprints(signers)]
    if trust.source == "working-tree":
        unpinned = result("R-33", ".", Status.UNKNOWN, "trust root not pinned: the baseline and signers come from the "
                          "working tree, which an agent can edit; run `steward authorize pin` (or set STEWARD_TRUST_* in CI)", details)
    else:
        unpinned = None
    if wt is None:
        return [unpinned or result("R-33", ".", Status.PASS, f"policy files match the pinned baseline ({trust.source} trust root)", details)]
    unavailable = False
    for tag in az.list_tags(ctx.root):
        try:
            v = az.verify(ctx.root, ctx.config, tag, action="policy.change", expected_object=wt)
        except az.AuthError as err:
            unavailable = unavailable or err.step == "unavailable"
            continue
        return [unpinned or result("R-33", ".", Status.PASS, f"policy change authorized by {v.principal} ({tag})",
                       details + [{"code": "R-33.changed", "path": p} for p in changed])]
    if unavailable:  # red-team M1: verification was not possible here, which is not a failed authorization
        return [result("R-33", ".", Status.UNKNOWN, "policy files differ from the baseline; signatures cannot be verified here",
                       details + [{"code": "R-33.verification_unavailable", "message": "run `steward check` in a terminal"}]
                       + [{"code": "R-33.changed", "path": p} for p in changed])]
    queued = [q for q in az.pending(ctx.root) if q["state"] == "waiting" and q.get("action") == "policy.change"
              and q.get("object") == wt and q.get("repo_id") == ctx.config.steward.repo_id
              and q.get("baseline") == base]  # U1 (0.12.0): this repository's request, against the trusted baseline
    if queued:  # 0.12.0 deferred signing: exactly this change is prepared and waits for the human's signature
        return [result("R-33", ".", Status.INCOMPLETE, "policy change prepared and awaiting your signature",
                       details + [{"code": "R-33.changed", "path": p} for p in changed]
                       + [{"code": "R-33.awaiting_signature", "value": q["nonce"],
                           "message": f"sign with: steward authorize sign {q['nonce']} (or steward authorize sign-pending); "
                                      f"expires {q['expires']}"} for q in queued])]
    return [result("R-33", ".", Status.FAIL, "policy files differ from the baseline without a verified policy.change authorization",
                   details + [{"code": "R-33.changed", "path": p} for p in changed]
                   + [{"code": "R-33.object", "value": wt, "message": "authorize with: steward authorize prepare policy.change "
                       "--expires YYYY-MM-DDTHH:MM:SSZ"}])]


# ---------------------------------------------------------------- spend guard (v0.4.2): R-34
def r34(ctx: Ctx) -> list[Result]:
    from . import authorize as az
    from . import ledger as lg
    from . import spend as sp

    assert ctx.config is not None
    if ctx.config.spend is None:
        return [result("R-34", ".", Status.NOT_APPLICABLE, "[spend] is not configured")]
    rel = ctx.config.spend.ledger
    if not (ctx.root / rel).is_file():
        return [result("R-34", rel, Status.NOT_APPLICABLE, "no spend recorded yet")]
    v = lg.verify(ctx.root / rel)
    if v.errors:
        return [result("R-34", rel, Status.UNKNOWN, "spend ledger is not intact (see R-31)")]
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    estimates = [e for e in v.entries if e.get("kind") == "estimate"]
    est_calls = {e["call"] for e in estimates}
    checked: dict[str, bool] = {}
    for e in estimates:
        tag = e.get("tag", "")
        if tag not in checked:
            try:  # judged at the time of the call: an authorization that expired later was valid then
                az.verify(ctx.root, ctx.config, tag, action="spend", now=sp.entry_time(e), consumed=set(),
                          require_pinned=True) if ctx.config.policy else None
                checked[tag] = "ok" if ctx.config.policy is not None else "no policy"
            except az.AuthError as err:
                checked[tag] = {"trust_root": "unpinned", "unavailable": "unavailable"}.get(err.step, "bad")
            except (KeyError, ValueError):
                checked[tag] = "bad"
        if checked[tag] == "unpinned":
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-34.trust_unpinned", "value": e["call"]})
        elif checked[tag] == "unavailable":  # M1
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-34.verification_unavailable", "value": e["call"]})
        elif checked[tag] != "ok":
            causes.append(Status.FAIL)
            details.append({"code": "R-34.unauthorized", "value": e["call"], "message": f"authorization {tag!r} does not verify"})
    for e in v.entries:
        if e.get("kind") == "actual" and e.get("call") not in est_calls:
            details.append({"code": "R-34.actual_without_estimate", "value": e.get("call")})
    t = sp.totals(ctx.root, ctx.config)
    details.append({"code": "R-34.totals", "message": f"{t['calls']} call(s); committed {t['committed']} {ctx.config.spend.currency} "
                    f"(cap {ctx.config.spend.cap}); actual {t['actual']}; unknown-cost calls {t['unknown_cost_calls']}; "
                    "the provider's bill is authoritative"})
    if t["committed"] > ctx.config.spend.cap:
        causes.append(Status.FAIL)
        details.append({"code": "R-34.over_cap", "value": t["committed"]})
    status = combine(causes)
    return [result("R-34", rel, status, "spend is over the cap or not authorized" if status is Status.FAIL else
                   f"spend within cap; every call authorized ({t['calls']} call(s))", details, ctx.evidence(rel))]


# ---------------------------------------------------------------- research integrity (v0.5.0): R-35 … R-39
def _integrity(ctx: Ctx, rule: str) -> Any:
    assert ctx.config is not None
    if ctx.config.integrity is None:
        return result(rule, ".", Status.NOT_APPLICABLE, "[integrity] is not configured")
    return None


def r35(ctx: Ctx) -> list[Result]:
    from . import integrity as ig
    from . import ledger as lg

    na = _integrity(ctx, "R-35")
    if na:
        return [na]
    rel = ctx.config.integrity.ledger
    if not (ctx.root / rel).is_file():
        return [result("R-35", rel, Status.NOT_APPLICABLE, "nothing frozen yet")]
    if lg.verify(ctx.root / rel).errors:
        return [result("R-35", rel, Status.UNKNOWN, "integrity ledger is not intact (see R-31)")]
    st = ig.state(ctx.root, ctx.config)
    out = []
    for name, e in sorted(st.frozen.items()):
        snap = e["snapshot"]
        try:
            diffs = ig.differences(snap, ig.recompute(ctx.root, snap))
        except (ig.IntegrityError, ValueError, ValueError, RecursionError) as err:
            out.append(result("R-35", name, Status.FAIL, f"frozen set '{name}': cannot recompute ({err})"))
            continue
        causes = [Status.FAIL] * len(diffs)
        details = list(diffs)
        if name in st.proposals:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-35.proposal_pending", "value": st.proposals[name]["proposal"],
                            "message": "proposed, not authorised: steward amend apply NAME --authorization TAG"})
        status = combine(causes)
        out.append(result("R-35", name, status, {Status.FAIL: f"frozen set '{name}' changed since it was frozen",
                          Status.INCOMPLETE: f"frozen set '{name}': an amendment is proposed, not authorised"}.get(
                          status, f"frozen set '{name}' unchanged ({len(snap['files'])} file(s), {len(snap['cohorts'])} cohort(s))"),
                          details))
    return out or [result("R-35", rel, Status.NOT_APPLICABLE, "nothing frozen yet")]


def r36(ctx: Ctx) -> list[Result]:
    from . import integrity as ig

    na = _integrity(ctx, "R-36")
    if na:
        return [na]
    rel = ctx.config.integrity.datasets
    if not (ctx.root / rel).is_file():
        return [result("R-36", rel, Status.NOT_APPLICABLE, "no datasets declared")]
    data, errors = _load_toml(ctx, rel)
    try:
        ds = ig.DatasetsFile.model_validate(data) if data is not None else None
    except ValidationError as e:
        ds, errors = None, m.format_errors(e)
    if ds is None:
        return [result("R-36", rel, Status.FAIL, "datasets file is invalid", errors, ctx.evidence(rel))]
    causes, details = _sentinel_status(m.find_sentinels(ds))
    st = ig.state(ctx.root, ctx.config) if (ctx.root / ctx.config.integrity.ledger).is_file() else None
    for name, d in sorted(ds.datasets.items()):
        for link in d.links:  # X02: a link must name a declared dataset
            if link not in ds.datasets:
                causes.append(Status.FAIL)
                details.append({"code": "R-36.unknown_link", "value": name, "message": f"links to {link}, which is not declared"})
        recorded = st.roles.get(name) if st else None
        if recorded and recorded[0] != d.role:
            causes.append(Status.FAIL)
            details.append({"code": "R-36.role_mismatch", "value": name, "message": f"declared {d.role}, recorded {recorded[0]}"})
        if d.role in ("sealed", "spent") and not recorded:
            causes.append(Status.FAIL)
            details.append({"code": "R-36.role_unrecorded", "value": name, "message": f"declared {d.role} but never sealed with steward seal"})
        if recorded and recorded[0] == "sealed":
            now = ig.dataset_hash(ctx.root, d)
            if now != recorded[1]["content"]:
                causes.append(Status.FAIL)
                details.append({"code": "R-36.sealed_changed", "value": name})
    status = combine(causes)
    return [result("R-36", rel, status, _reason(status, "dataset roles or sealed contents are inconsistent",
                   "datasets have fields marked TBD", "datasets have fields marked unknown",
                   f"{len(ds.datasets)} dataset(s); roles match the record"), details, ctx.evidence(rel))]


def r37(ctx: Ctx) -> list[Result]:
    from . import integrity as ig
    from . import ledger as lg

    na = _integrity(ctx, "R-37")
    if na:
        return [na]
    try:
        ds = ig.load_datasets(ctx.root, ctx.config)
    except (ValidationError, ValueError, RecursionError):
        return [result("R-37", ".", Status.UNKNOWN, "datasets file invalid (see R-36)")]
    if ds is None or not (ctx.root / ctx.config.integrity.ledger).is_file():
        return [result("R-37", ".", Status.NOT_APPLICABLE, "no sealed datasets recorded")]
    st = ig.state(ctx.root, ctx.config)
    windows = {}
    for e in st.entries:
        if e.get("kind") == "seal":
            windows[e["dataset"]] = [e["time"], None]
        elif e.get("kind") == "unseal" and e["dataset"] in windows:
            windows[e["dataset"]][1] = e["time"]
    if not windows:
        return [result("R-37", ".", Status.NOT_APPLICABLE, "no sealed datasets recorded")]
    causes, details = [], []

    def owner(path: str, h: str | None) -> str | None:
        for n in windows:
            d = ds.datasets.get(n)
            if d and (any(glob_match(path, p) for p in d.paths) or (h and h in {ig.file_sha(ctx.root, f) for f in ig.dataset_files(ctx.root, d)})):
                return n
        return None

    if ctx.config.run and (ctx.root / ctx.config.run.ledger).is_file():
        for e in lg.verify(ctx.root / ctx.config.run.ledger).entries:
            if e.get("kind") != "started":
                continue
            for path, h in (e.get("inputs") or {}).items():
                n = owner(path, h)
                if n and windows[n][0] <= e["time"] and (windows[n][1] is None or e["time"] < windows[n][1]):
                    causes.append(Status.FAIL)
                    details.append({"code": "R-37.run_read_sealed", "value": e["run"], "path": path, "message": f"dataset {n}"})
    for pname, pp in sorted(ctx.config.paper.items()):
        vf, comp, _ = _load_values(ctx, pname, pp)
        for key, d in sorted((vf.values if vf else {}).items()):
            if d.source:
                n = owner(d.source, None)
                if n and windows[n][1] is None:
                    causes.append(Status.FAIL)
                    details.append({"code": "R-37.paper_reports_sealed", "value": key, "path": d.source, "message": f"dataset {n}"})
    status = combine(causes)
    return [result("R-37", ".", status, "sealed data was used before an authorised unseal" if causes else
                   f"no use of sealed data found in declared inputs ({len(windows)} sealed dataset(s)); undeclared reads are out of coverage", details)]


def _logs_in_history(ctx: Ctx, cfg: Any, causes: list[Status], details: list[dict[str, Any]]) -> list[str]:
    """Every path matching the configured decisions globs that HEAD's history ever held (created, kept or deleted in
    any commit); a history that cannot be read is UNKNOWN, never empty (review R8)."""
    from .fsutil import git_run

    pats = [cfg.integrity.decisions] if isinstance(cfg.integrity.decisions, str) else list(cfg.integrity.decisions)
    if not any(any(c in p for c in "*?[") for p in pats):
        return []
    if git_run(ctx.root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        return []  # nothing committed yet (or no git): the working tree holds every log there is
    log = git_run(ctx.root, "log", "--format=", "--name-only", "-z", "--no-renames", "HEAD", timeout=120)
    if log.returncode != 0:
        causes.append(Status.UNKNOWN)
        details.append({"code": "R-38.history_unavailable", "message": "git could not list the decisions logs in history"})
        return []
    out: list[str] = []
    for name in log.stdout.decode("utf-8", errors="replace").replace("\n", "\0").split("\0"):
        if name and any(glob_match(name, p) for p in pats) and name not in out:
            out.append(name)
    return sorted(out)


def _log_history(ctx: Ctx, rel: str, causes: list[Status], details: list[dict[str, Any]]) -> None:
    """Append-only across the log's own committed history, then the working tree against HEAD's version, for when no
    base holds the log (DEF-022). Every committed version must extend the one before it; a deletion followed by
    a re-creation is not a fresh start; unavailable or capped history is UNKNOWN (review Q12)."""
    from . import authorize as az
    from . import fsutil

    cap = 2000
    revs = fsutil.git_run(ctx.root, "rev-list", "--reverse", f"--max-count={cap + 1}", "HEAD", "--", rel, text=True, timeout=60)
    if revs.returncode != 0:
        gitdir = fsutil.git_run(ctx.root, "rev-parse", "--git-dir", text=True, timeout=10)
        any_ref = fsutil.git_run(ctx.root, "rev-list", "-n", "1", "--all", text=True, timeout=10)
        if gitdir.returncode == 0 and any_ref.returncode == 0 and not any_ref.stdout.strip():  # R8: truly unborn
            details.append({"code": "R-38.append_only_new", "path": rel, "message": "no commit yet: nothing to compare"})
            return
        causes.append(Status.UNKNOWN)
        details.append({"code": "R-38.history_unavailable", "path": rel, "message": "git could not list the log's history"})
        return
    commits = revs.stdout.split()
    if len(commits) > cap:
        causes.append(Status.UNKNOWN)
        details.append({"code": "R-38.history_partial", "path": rel, "value": cap,
                        "message": f"more than {cap} commits touch the log: only the newest {cap} were compared"})
        commits = commits[-cap:]
    now = ctx.read(rel) if (ctx.root / rel).is_file() else None
    if not commits:
        details.append({"code": "R-38.append_only_new", "path": rel,
                        "message": "the log is not committed yet: there is no earlier version to compare"})
        return
    prev = None
    for c in commits:
        blob = az.baseline_file(ctx.root, c, rel)
        if blob is None:
            if prev is not None:  # Q12: removal is a rewrite; a later re-creation does not start a new history
                causes.append(Status.FAIL)
                details.append({"code": "R-38.log_removed", "path": rel, "value": c[:12],
                                "message": "the log was deleted in this commit; it is append-only"})
            continue
        if prev is not None and not blob.startswith(prev):
            causes.append(Status.FAIL)
            details.append({"code": "R-38.decisions_rewritten", "path": rel, "value": c[:12],
                            "message": "earlier entries changed in this commit; the log is append-only"})
        prev = blob
    if prev is not None and now is None:
        causes.append(Status.FAIL)
        details.append({"code": "R-38.log_removed", "path": rel, "message": "the committed log is missing from the working tree"})
    elif prev is not None and not now.startswith(prev):
        causes.append(Status.FAIL)
        details.append({"code": "R-38.decisions_rewritten", "path": rel,
                        "message": "earlier entries changed in the working tree; the log is append-only"})
    details.append({"code": "R-38.append_only_history", "path": rel, "value": len(commits),
                    "message": f"no base holds the log: checked across its {len(commits)} commit(s) and the working tree"})

def _r38_log(ctx: Ctx, cfg: Any, dpath: str, pol_on: bool, causes: list[Status], details: list[dict[str, Any]]) -> None:
    """Format and append-only checks of one decisions log (REQ-013: each listed log)."""
    from . import authorize as az
    from . import integrity as ig

    has_log = (ctx.root / dpath).is_file()
    if has_log and cfg.integrity.decisions_format == "template":  # AR-06: the template's entry format
        text = ctx.read(dpath).decode("utf-8", errors="replace")
        body_text = "\n".join(l for l in text.splitlines() if l.strip() and not l.startswith("# "))
        if body_text and not ig.decision_entries(text) and "## YYYY-MM-DD" not in text:  # review N9
            causes.append(Status.FAIL)
            details.append({"code": "R-38.entry_malformed", "path": dpath, "message": "the log has text but no `## YYYY-MM-DD: title` entries"})
        for line, heading, body in ig.decision_entries(text):
            for problem in ig.entry_problems(heading, body):
                causes.append(Status.FAIL)
                details.append({"code": "R-38.entry_malformed", "path": dpath, "line": line, "message": problem})
    if not pol_on and has_log:  # AR-06: append-only without a signing policy, against a git base
        from .fsutil import git_run

        ref = cfg.integrity.decisions_base
        try:
            if ref is None:
                head_ref = git_run(ctx.root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", text=True, timeout=10)
                default = head_ref.stdout.strip() if head_ref.returncode == 0 and head_ref.stdout.strip() else "main"
                mb = git_run(ctx.root, "merge-base", "HEAD", default, text=True, timeout=10)
                base_commit = mb.stdout.strip() if mb.returncode == 0 else None
            else:
                rv = git_run(ctx.root, "rev-parse", "--verify", f"{ref}^{{commit}}", text=True, timeout=10)
                base_commit = rv.stdout.strip() if rv.returncode == 0 else None
                if base_commit is None:
                    causes.append(Status.UNKNOWN)
                    details.append({"code": "R-38.decisions_base_unknown", "value": ref})
        except (OSError, subprocess.SubprocessError):
            base_commit = None
        if base_commit:
            before = az.baseline_file(ctx.root, base_commit, dpath)
            now = ctx.read(dpath)
            if before is None:  # DEF-022: never a pass on a comparison that did not run
                _log_history(ctx, dpath, causes, details)
            elif not now.startswith(before):
                causes.append(Status.FAIL)
                details.append({"code": "R-38.decisions_rewritten", "path": dpath, "message": "earlier entries changed; the log is append-only"})
            details.append({"code": "R-38.append_only_weak", "value": base_commit[:12],
                            "message": "checked against a git base without a pinned trust root (weaker than [policy])"})
        elif ref is None:
            _log_history(ctx, dpath, causes, details)
    if pol_on:
        try:
            base = az.resolve_baseline(ctx.root, az.resolve_trust(ctx.root, cfg).baseline_ref)  # the trusted baseline
            before = az.baseline_file(ctx.root, base, dpath)
            now = (ctx.root / dpath).read_bytes() if (ctx.root / dpath).is_file() else b""
            if before is None:  # DEF-022
                _log_history(ctx, dpath, causes, details)
                details.append({"code": "R-38.append_only_weak", "message": "the log is not on the policy baseline: "
                                "checked against its own git history (weaker than the baseline)"})
            elif not now.startswith(before):
                causes.append(Status.FAIL)
                details.append({"code": "R-38.decisions_rewritten", "path": dpath,
                                "message": "earlier entries changed; the log is append-only"})
        except az.AuthError:  # S2: unavailable pinned evidence blocks; it never falls back to the working tree
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-38.append_only_unchecked", "message": "policy baseline unavailable"})


def r38(ctx: Ctx) -> list[Result]:
    from . import authorize as az
    from . import integrity as ig
    from . import spend as sp

    na = _integrity(ctx, "R-38")
    if na:
        return [na]
    cfg = ctx.config
    pol_on = az.policy_active(cfg, ctx.root)  # REQ-016: a pending policy without a pin is not enforced yet
    causes, details = [], []
    gated = []
    if (ctx.root / cfg.integrity.ledger).is_file():
        st = ig.state(ctx.root, cfg)
        gated = [e for e in st.entries if e.get("kind") in ("amend", "unseal") or (e.get("kind") == "freeze" and e.get("confirmatory"))]
    for e in gated:
        action = {"amend": "amend", "unseal": "unseal", "freeze": "freeze.confirmatory"}[e["kind"]]
        if not pol_on:
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-38.no_policy", "value": e["seq"]})
            continue
        try:
            az.verify(ctx.root, cfg, e.get("authorization", ""), action=action, expected_object=e.get("object"),
                      now=sp.entry_time(e), consumed=set(), require_pinned=True)
        except az.AuthError as err:
            causes.append(Status.UNKNOWN if err.step in ("trust_root", "unavailable") else Status.FAIL)
            details.append({"code": {"trust_root": "R-38.trust_unpinned", "unavailable": "R-38.verification_unavailable"}.get(err.step, "R-38.unauthorized"),
                            "value": e["seq"], "message": f"{err.step}: {err.message}"})
        if not ig.decision_present(ctx.root, cfg, e.get("decision")):
            causes.append(Status.FAIL)
            details.append({"code": "R-38.no_decision", "value": e["seq"], "message": e.get("decision") or "no decision reference"})
    from .fsutil import git_run as _git

    logs = cfg.integrity.decision_logs(ctx.root)
    in_history = _logs_in_history(ctx, cfg, causes, details)
    logs += [l for l in in_history if l not in logs]  # Q12, R8
    has_log = any((ctx.root / d).is_file() for d in logs)
    for dpath in logs:
        if not (ctx.root / dpath).is_file():
            if dpath not in in_history and _git(ctx.root, "cat-file", "-e", f"HEAD:{dpath}").returncode != 0:
                continue  # configured, never committed: nothing recorded yet (FB-9), not a removal
            causes.append(Status.FAIL)
            details.append({"code": "R-38.log_removed", "path": dpath, "message": "a decisions log in history is gone; logs are append-only"})
            continue
        _r38_log(ctx, cfg, dpath, pol_on, causes, details)
    if not gated and not pol_on and not has_log and not causes:  # R8: collected failures are never discarded
        return [result("R-38", ".", Status.NOT_APPLICABLE, "no gated integrity actions, no policy baseline and no decisions log", details)]
    status = combine(causes)
    return [result("R-38", ".", status, _reason(status, "an integrity action lacks a verified authorization or decision, or the decisions log was rewritten",
                   "", "integrity actions cannot be verified without [policy]",
                   f"{len(gated)} gated action(s) authorized and recorded; decisions log checked"), details)]


def r39(ctx: Ctx) -> list[Result]:
    from . import integrity as ig
    from . import ledger as lg

    na = _integrity(ctx, "R-39")
    if na:
        return [na]
    confirmatory = sorted(c.id for c in ctx.contracts.values() if c.analysis == "confirmatory")
    if not confirmatory:
        return [result("R-39", ".", Status.NOT_APPLICABLE, "no confirmatory contract")]
    freezes: dict[str, str] = {}
    if (ctx.root / ctx.config.integrity.ledger).is_file():
        for e in ig.state(ctx.root, ctx.config).entries:
            if e.get("kind") == "freeze" and e.get("snapshot", {}).get("contract"):
                freezes.setdefault(e["snapshot"]["contract"], e["time"])
    first_run: dict[str, str] = {}
    if ctx.config.run and (ctx.root / ctx.config.run.ledger).is_file():
        for e in lg.verify(ctx.root / ctx.config.run.ledger).entries:
            if e.get("kind") == "started" and e.get("contract"):
                first_run.setdefault(e["contract"], e["time"])
    causes, details = [], []
    for cid in confirmatory:
        if cid not in freezes:
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-39.not_frozen", "value": cid, "message": "freeze it before the first run"})
        elif cid in first_run and first_run[cid] < freezes[cid]:
            causes.append(Status.FAIL)
            details.append({"code": "R-39.frozen_after_run", "value": cid, "message": "frozen after outcomes may have been seen"})
    status = combine(causes)
    return [result("R-39", ".", status, {Status.FAIL: "a confirmatory contract was frozen after its first run",
                   Status.INCOMPLETE: "confirmatory contracts are not frozen"}.get(status, f"{len(confirmatory)} confirmatory contract(s) frozen before their runs"),
                   details)]


# ---------------------------------------------------------------- evidence (v0.6.0): R-40, R-41
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _plain(v: Any) -> str:
    """A number as a person writes it: plain decimal notation, exponent form only beyond 30 digits of scale."""
    if isinstance(v, Decimal) and v.is_finite() and abs(v.adjusted()) <= 30:
        return f"{v:f}"
    return str(v)


def _lock_entry_ok(e: Any) -> bool:
    """A display-lock entry with recorded fingerprints (red-team G4): four tables, a script and an output hash."""
    if not isinstance(e, dict) or any(not isinstance(e.get(k), dict) for k in ("script", "inputs", "params", "output")):
        return False
    return bool(e["script"]) and bool(e["output"]) and all(
        isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for part in ("script", "inputs", "output") for h in e[part].values())  # SHA-256 (H5)


def r40(ctx: Ctx) -> list[Result]:
    from . import evidence as ev
    from . import integrity as ig

    assert ctx.config is not None
    if ctx.config.evidence is None:
        return [result("R-40", ".", Status.NOT_APPLICABLE, "[evidence] is not configured")]
    rel = ctx.config.evidence.claims
    if not (ctx.root / rel).is_file():
        return [result("R-40", rel, Status.NOT_APPLICABLE, "no claim map yet")]
    # one read: validation, exact numbers and the evidence hash all come from the same bytes (red-team G7)
    raw = ctx.read(rel)
    errors: list[dict[str, Any]] = []
    try:
        text = raw.decode("utf-8")
        data: dict[str, Any] | None = tomllib.loads(text)
        exact_claims = tomllib.loads(text, parse_float=ev._exact_float).get("claims") or []  # as written (F1, H4)
    except UnicodeDecodeError:
        data, exact_claims, errors = None, [], [{"code": "parse", "message": "file is not valid UTF-8"}]
    except (ValueError, RecursionError) as e:
        data, exact_claims, errors = None, [], [{"code": "parse", "message": f"invalid TOML: {e}"}]
    try:
        cf = ev.ClaimsFile.model_validate(data) if data is not None else None
    except ValidationError as e:
        cf, errors = None, m.format_errors(e)
    if cf is None:
        return [result("R-40", rel, Status.FAIL, "claim map is invalid", errors, ctx.evidence(rel))]
    recs = ev.runs(ctx.root, ctx.config)
    frozen_contracts = set()
    if ctx.config.integrity and (ctx.root / ctx.config.integrity.ledger).is_file():
        frozen_contracts = {e["snapshot"]["contract"] for e in ig.state(ctx.root, ctx.config).frozen.values() if e["snapshot"].get("contract")}
    causes, details = _sentinel_status(m.find_sentinels(cf))
    snapshot = ctx.snapshot  # each source is read once per check, shared with every rule (H2, I2)

    def source_bytes(path: str) -> bytes:
        return ctx.read(path)
    for ci, c in enumerate(cf.claims):
        def bad(code: str, status: Status = Status.FAIL, **kw: Any) -> None:
            causes.append(status)
            details.append({"code": f"R-40.{code}", "value": c.id, **kw})
        if not c.runs:
            bad("no_run", message="claimed without a run record")
            continue
        listed = [recs.get(r) for r in c.runs]
        if any(r is None for r in listed):
            bad("run_missing", message=", ".join(r for r in c.runs if r not in recs))
            continue
        if any(r["outcome"] is None for r in listed):
            bad("run_unfinished", Status.INCOMPLETE)
            continue
        if any(r["outcome"].get("status") != "finished" for r in listed):
            bad("run_failed", message="a listed run failed or was killed")
            continue
        actual, provenance = None, []  # provenance: (source path, current hash) that a listed run must have recorded
        if c.value_key is not None:
            from . import values as vals

            hit = None
            for pname, pp in sorted(ctx.config.paper.items()):
                vf, _, _ = _load_values(ctx, pname, pp)
                if vf and c.value_key in vf.values:
                    hit = vf
                    break
            if hit is None:
                bad("unknown_value_key", message=c.value_key)
                continue
            # registry pointers read exactly (G1), from the check's one snapshot of each source (G7, H2)
            comp = vals.compute(ctx.root, hit, exact=True, read=snapshot)
            for src_, raw_ in comp.read.items():  # every byte a rule used is in the verdict's input digest (I2)
                ctx.inputs[src_] = sha256_bytes(raw_)
            actual = comp.raw.get(c.value_key)
            # a derived value depends on every source behind it (H3)
            seen, todo, paths = set(), [c.value_key], set()
            while todo:
                k = todo.pop()
                if k in seen or k not in hit.values:
                    continue
                seen.add(k)
                d = hit.values[k]
                if d.derive is not None:
                    todo += vals.REF.findall(d.derive)
                elif d.source:
                    paths.add(d.source)
            for path in sorted(paths):
                data = snapshot.get(path)
                provenance.append((path, hashlib.sha256(data).hexdigest() if data is not None else None))
            if hit.values[c.value_key].derive is not None:
                details.append({"code": "R-40.derived_binary64", "value": c.id,
                                "message": "a derived value is computed in binary floating point"})
        else:
            try:
                data_bytes = source_bytes(c.source)
                provenance.append((c.source, hashlib.sha256(data_bytes).hexdigest()))
                actual = ev.pointer_value(data_bytes, c.source, c.pointer)
            except (OSError, KeyError, IndexError, ValueError, ValueError, RecursionError) as e:
                bad("source_unreadable", message=f"{c.source} {c.pointer}: {e}")
                continue
        for path, current in provenance:
            if not any((r["outcome"].get("outputs") or {}).get(path) == current for r in listed):
                bad("not_from_runs", path=path, message="no listed run recorded this source with its current hash")
        if c.value not in m.SENTINELS:
            exact = exact_claims[ci] if ci < len(exact_claims) and isinstance(exact_claims[ci], dict) else {}
            ev_ = exact.get("value")
            stated = ev_ if _is_num(ev_) or isinstance(ev_, ev.OutOfRange) else c.value  # as written (F1, H4)
            et = exact.get("tolerance")
            tol = et if _is_num(et) or isinstance(et, ev.OutOfRange) else c.tolerance
            numeric = _is_num(actual) or isinstance(actual, ev.OutOfRange)
            if isinstance(tol, ev.OutOfRange) or isinstance(stated, ev.OutOfRange):
                state = "out of range"
            else:
                state = ev.compare(actual, stated, ("abs", tol)) if numeric else None
            dtol = None if isinstance(tol, ev.OutOfRange) else (tol if isinstance(tol, Decimal) else ev._dec(tol))
            if dtol is not None and (not dtol.is_finite() or dtol < 0):
                bad("invalid_tolerance", message=f"tolerance {_plain(tol)} must be finite and non-negative")  # G6, H6
            elif state is None:
                bad("not_numeric", message=repr(actual))
            elif state == "out of range":
                bad("out_of_range", Status.UNKNOWN, message=f"stated {_plain(stated)}, evidence {_plain(actual)}: beyond the exactly comparable range")
            elif state not in ("equal", "within"):  # exact (red-team D3, F1)
                bad("value_mismatch", message=f"stated {_plain(stated)}, evidence {_plain(actual)}, tolerance {_plain(tol)}")
        if c.contract and c.contract not in frozen_contracts:
            bad("contract_not_frozen", Status.INCOMPLETE, message=c.contract)
    status = combine(causes)
    return [result("R-40", rel, status, _reason(status, "a claim does not match recorded, current evidence",
                   "claims are incomplete", "claims have unknown fields",
                   f"{len(cf.claims)} claim(s) match recorded, current evidence (truth of the claims not assessed)"), details, ctx.evidence(rel))]


def r41(ctx: Ctx) -> list[Result]:
    assert ctx.config is not None
    if not ctx.prior:
        return [result("R-41", ".", Status.NOT_APPLICABLE, "no prior-work record")]
    ids = {c.id for c in ctx.contracts.values()}
    out = []
    for rel, p in sorted(ctx.prior.items()):
        causes, details = [], []
        for d in p.claimed_differences:
            if d.evidence in m.SENTINELS:
                continue  # reported by R-05
            if not d.evidence:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-41.no_evidence", "value": d.id, "message": "a difference with no distinguishing experiment is a hypothesis"})
            for ref in d.evidence:
                if ref.startswith("contract:") and ref[9:] not in ids:
                    causes.append(Status.FAIL)
                    details.append({"code": "R-41.unknown_contract", "value": d.id, "message": ref})
        status = combine(causes)
        out.append(result("R-41", rel, status, {Status.FAIL: "claimed differences cite unknown contracts",
                          Status.INCOMPLETE: "some claimed differences have no distinguishing experiment"}.get(
                          status, f"{len(p.claimed_differences)} claimed difference(s) link to existing contracts"), details))
    return out


# ---------------------------------------------------------------- release integrity (v0.6.1): R-42
def r42(ctx: Ctx) -> list[Result]:
    from . import release as rl

    assert ctx.config is not None
    rc = ctx.config.release
    if rc is None:
        return [result("R-42", ".", Status.NOT_APPLICABLE, "[release] is not configured")]
    causes: list[Status] = []
    details: list[dict[str, Any]] = []
    # REQ-001: the required files and the citation are a release's; before anything is built, and outside a
    # final check, they are reported without failing (a repository that never distributes has no LICENSE)
    building = bool(rl.artifacts(ctx.root / rc.dist)) or ctx.final
    pending: list[Status] = []
    for req in rc.required:
        if not (ctx.root / req).is_file():
            pending.append(Status.FAIL)
            details.append({"code": "R-42.missing_required", "path": req})
    for p in rl.cff_problems(ctx.root / "CITATION.cff"):
        pending.append(Status.FAIL)
        details.append({"code": "R-42.citation", "message": p})
    if building:
        causes += pending
    validator = shutil.which("cffconvert")
    if validator is None:
        details.append({"code": "R-42.citation_not_validated", "message": "cffconvert not installed; structure checked only"})
    elif (ctx.root / "CITATION.cff").is_file():  # red-team B5: run it, not only detect it
        try:
            out = subprocess.run([validator, "--validate", "-i", str(ctx.root / "CITATION.cff")], capture_output=True, timeout=120)
            if out.returncode != 0:
                (causes if building else pending).append(Status.FAIL)
                details.append({"code": "R-42.citation_invalid", "message": (out.stderr or out.stdout).decode("utf-8", errors="replace").strip()[:300]})
            else:
                details.append({"code": "R-42.citation_validated", "message": "cffconvert --validate passed"})
        except (OSError, subprocess.SubprocessError) as e:
            causes.append(Status.UNKNOWN)
            details.append({"code": "R-42.citation_validator_error", "message": str(e)})
    dist = ctx.root / rc.dist
    arts = rl.artifacts(dist)
    if not arts:
        details.append({"code": "R-42.no_dist", "message": f"no distributions in {rc.dist}/; build them to check the release"})
    else:
        mpath = ctx.root / rc.manifest
        if not mpath.is_file():
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-42.no_manifest", "message": "run: steward release manifest"})
        else:
            try:
                man = json.loads(ctx.read(rc.manifest).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                man = None
            if not isinstance(man, dict) or man.get("schema") != "steward.release_manifest/0.1":
                causes.append(Status.FAIL)
                details.append({"code": "R-42.manifest_invalid"})
            else:
                for key in ctx.config.release.identities:  # SR-003: recorded, never verified (they are external)
                    val = (man.get("identities") or {}).get(key)
                    if val is None:
                        details.append({"code": "R-42.identity_missing", "value": key})
                        if ctx.final:
                            causes.append(Status.INCOMPLETE)
                    else:
                        details.append({"code": "R-42.identity_recorded", "value": key, "message": "recorded, not verified"})
                now = {a.name: rl.sha(a) for a in arts}
                recorded = {k: v.get("sha256") for k, v in (man.get("artifacts") or {}).items()}
                if man.get("dist") not in (None, rc.dist):  # FB-10; review N8: never a PASS on another folder's hashes
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-42.manifest_other_dist", "value": man.get("dist"),
                                    "message": f"the manifest describes another folder; {rc.dist}/ is not confirmed by it"})
                    now = recorded
                for name in sorted(set(now) | set(recorded)):
                    if now.get(name) != recorded.get(name):
                        causes.append(Status.FAIL)
                        details.append({"code": "R-42.artifact_mismatch", "path": f"{rc.dist}/{name}"})
                if "bundles" in man or rl.bundles(ctx.root / rc.bundles):  # 0.9.0 B8: recorded bundles still match
                    cur_b = {k: (v["sha256"], v.get("record_sha256")) for k, v in rl.bundles(ctx.root / rc.bundles).items()}
                    rec_b = {k: ((v or {}).get("sha256"), (v or {}).get("record_sha256")) for k, v in (man.get("bundles") or {}).items()}
                    for name, v in (man.get("bundles") or {}).items():  # R18: a recorded but unbound record is explicit
                        # R18 (0.12.0): a legacy entry with no binding flag and no record hash is unbound too
                        if isinstance(v, dict) and (v.get("record_bound") is False or v.get("record_sha256") is None):
                            # R18 (0.13.0): bound only with a record hash, whatever the flag says
                            causes.append(Status.FAIL)
                            details.append({"code": "R-42.bundle_record_stale", "path": f"{rc.bundles}/{name}.bundle.json"})
                    for name in sorted(set(cur_b) | set(rec_b)):
                        if cur_b.get(name) != rec_b.get(name):
                            causes.append(Status.FAIL)
                            details.append({"code": "R-42.bundle_mismatch", "path": f"{rc.bundles}/{name}.zip",
                                            "message": "differs from the manifest; run: steward release manifest"})
                in_dist = set(man.get("locks_in_dist") or [])
                for lock, h in sorted((man.get("locks") or {}).items()):
                    if h is None:  # X1 (0.15.0): a declared lock the manifest could not hash is never a match
                        causes.append(Status.INCOMPLETE)
                        details.append({"code": "R-42.lock_unavailable", "path": lock,
                                        "message": "declared in [release] locks, but not hashed (missing, or reached "
                                                   "through a link); fix it and run: steward release manifest"})
                        continue
                    if lock in in_dist:  # REQ-010: read from the release folder, judged there (U15: never via links)
                        cur = rl.sha(dist / lock) if rl._in_dist(dist, lock) else None
                    else:  # U15 (0.14.0): a repository lock is read only inside the repository, never via a link
                        cur = rl.sha(ctx.root / lock) if rl._in_repo(ctx.root, lock) else None  # U15 (0.15.0)
                    if cur != h:
                        causes.append(Status.FAIL)
                        details.append({"code": "R-42.lock_changed", "path": lock})
                # red-team D4: every hash the manifest records is evidence, so each must still match
                recorded_files = [("CITATION.cff", "citation_sha256", "R-42.citation_changed")]
                if ctx.config.evidence is not None:
                    recorded_files.append((ctx.config.evidence.claims, "claims_sha256", "R-42.claims_changed"))
                for path, key, code in recorded_files:
                    cur = rl.sha(ctx.root / path) if (ctx.root / path).is_file() else None
                    if key not in man or man.get(key) != cur:
                        causes.append(Status.FAIL)
                        details.append({"code": code, "path": path, "message": "changed since the manifest was written; run: steward release manifest"})
        aud = rl.audit_for(ctx.root, ctx.config, dist, read=ctx.read)  # the same function as the command (SR-007)
        for f in aud["findings"]:
            causes.append(Status.FAIL)
            details.append({"code": f"R-42.{f['code']}", "path": f"{f['artifact']}:{f['member']}",
                            **{k: f[k] for k in ("term", "line", "value") if k in f}})
        for f in aud.get("declared", []):  # REQ-006
            details.append({"code": "R-42.shipped_secret", "path": f"{f['artifact']}:{f['member']}",
                            "message": f"declared: {f['reason']} (decision {f['decision']})"})
        details.append({"code": "R-42.audited", "message": ", ".join(f"{k} ({v} members)" for k, v in aud["artifacts"].items())})
        if aud.get("unscanned"):  # review N7: say what the content scan did not read
            details.append({"code": "R-42.members_unscanned", "value": len(aud["unscanned"]), "message": "large or binary members: names checked, content not scanned"})
    if ctx.config.evidence is not None:  # red-team B5, D4: the claim map is checked with or without distributions
        if not (ctx.root / ctx.config.evidence.claims).is_file():
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-42.no_claim_map", "path": ctx.config.evidence.claims,
                            "message": "[evidence] is configured but the claim map is missing; create it (it may list no claims)"})
        else:
            claims = r40(ctx)[0]
            if claims.status in (Status.FAIL, Status.INCOMPLETE, Status.UNKNOWN):
                causes.append(claims.status)
                details.append({"code": "R-42.claims_not_passing", "value": claims.status.value, "message": claims.reason})
    if not arts:  # AR-16 / SR-007: nothing built never passes a release check
        if ctx.final:
            causes.append(Status.INCOMPLETE)
        elif not causes:
            return [result("R-42", ".", Status.NOT_APPLICABLE, f"nothing built in {rc.dist}/ yet; a final check requires distributions",
                           details)]
    status = combine(causes)
    return [result("R-42", ".", status, {Status.FAIL: "release contents, manifest, locks or citation metadata are inconsistent",
                   Status.INCOMPLETE: "the manifest or the claim map is missing, or claims are incomplete"}.get(
                   status, "required release files present" + ("; artifacts match the manifest and pass the audit" if arts else "")),
                   details)]


# ---------------------------------------------------------------- release review (0.6.2): R-43
RECOMMEND = ("before any public release, an independent red-team review recorded in development/assessment/findings.toml "
             "(red-team-review skill); set [release] review_required = true to enforce it")


def r43(ctx: Ctx) -> list[Result]:
    from . import review as rv

    assert ctx.config is not None
    rc = ctx.config.release
    rec = ([{"code": "R-43.recommended", "message": RECOMMEND}]
           if ctx.config.steward.profile == "confirmatory" else [])  # 0.20.2: not in an exploratory project's summary
    if rc is None:
        return [result("R-43", ".", Status.NOT_APPLICABLE, "[release] is not configured", rec)]
    rel = rc.findings
    ff, causes, details = None, [], []
    waivers: list[tuple[str, str]] = []
    if (ctx.root / rel).is_file():
        data, errors = _load_toml(ctx, rel)
        try:
            ff = rv.FindingsFile.model_validate(data) if data is not None else None
        except ValidationError as e:
            ff, errors = None, m.format_errors(e)
        if ff is None:
            causes, details = [Status.FAIL], [{"code": "R-43.invalid", "message": "findings register is invalid"}] + errors
        else:
            names, details = rv.evaluate(ctx.root, ctx.config, ff, waivers=waivers)
            causes = [Status(n) for n in names]
    else:
        causes, details = [Status.INCOMPLETE], [{"code": "R-43.no_register", "path": rel}]
    status = combine(causes)
    if not rc.review_required:
        state = "no open blockers" if status is Status.PASS else f"review state: {status.value.lower()}"
        return [result("R-43", rel, Status.NOT_APPLICABLE, f"release review is optional here ({state})",
                       rec + details)]
    review_result = result("R-43", rel, status, {Status.FAIL: "open, unwaived or non-independent review findings block the release",
                   Status.INCOMPLETE: "the release review is missing, stale, or awaiting re-verification",
                   Status.UNKNOWN: "review coverage cannot be determined (git unavailable)"}.get(
                   status, "an independent review covers this release; blocking findings are verified or waived"), details, ctx.evidence(rel))
    review_result.waivers = tuple(sorted(set(waivers)))
    return [review_result]


# ---------------------------------------------------------------- runtime fingerprint (0.6.2): R-44
def r44(ctx: Ctx) -> list[Result]:
    from . import fingerprint as fpm
    from . import ledger as lg

    assert ctx.config is not None
    rc = ctx.config.release
    if rc is None or not rc.fingerprint:
        return [result("R-44", ".", Status.NOT_APPLICABLE, "no runtime fingerprint configured ([release] fingerprint)")]
    rel = rc.fingerprint_file
    if not (ctx.root / rel).is_file():
        return [result("R-44", rel, Status.INCOMPLETE, "no recorded fingerprint; run: steward release fingerprint --record")]
    try:
        recorded = json.loads(ctx.read(rel).decode("utf-8")).get("modules", {})
    except (ValueError, UnicodeDecodeError):
        return [result("R-44", rel, Status.FAIL, "fingerprint file is invalid")]
    current, errors = fpm.fingerprints(ctx.root, rc.fingerprint)
    acks: dict[str, set[str]] = {}
    if (ctx.root / rc.acks).is_file():
        v = lg.verify(ctx.root / rc.acks)
        if v.errors:
            return [result("R-44", rel, Status.FAIL, "acknowledgement ledger is not intact (see R-31)")]
        for e in v.entries:
            if e.get("kind") == "ack":
                acks.setdefault(e["module"], set()).add(e["fingerprint"])
    causes, details = [], []
    for mod, err in sorted(errors.items()):
        causes.append(Status.FAIL)
        details.append({"code": "R-44.unparsable", "path": mod, "message": err})
    for mod in sorted(set(current) | set(recorded)):
        cur, rec = current.get(mod), recorded.get(mod)
        if cur == rec:
            continue
        if cur is not None and cur in acks.get(mod, set()):
            details.append({"code": "R-44.acknowledged", "path": mod})
            continue
        if cur is None and mod in errors:
            continue
        causes.append(Status.FAIL)
        details.append({"code": "R-44.changed" if cur and rec else ("R-44.added" if cur else "R-44.removed"), "path": mod,
                        "message": "acknowledge a neutral change: steward release ack MODULE --reason TEXT, or re-record after review"})
    status = combine(causes)
    return [result("R-44", rel, status, "runtime code changed since the recorded fingerprint without acknowledgement"
                   if status is Status.FAIL else f"{len(current)} module(s) match the recorded fingerprint or acknowledged changes",
                   details, ctx.evidence(rel))]


# ---------------------------------------------------------------- benchmark (v0.7): R-45, R-46
def r45(ctx: Ctx) -> list[Result]:
    from . import benchmark as bm

    if not ctx.contract_files:
        return [result("R-45", ".", Status.NOT_APPLICABLE, "no contract files matched")]
    out = []
    for rel in ctx.contract_files:
        if rel not in ctx.contracts:
            out.append(result("R-45", rel, Status.UNKNOWN, "not evaluated: contract failed R-02", [], ctx.evidence(rel)))
            continue
        c = ctx.contracts[rel]
        a = bm.analyze(ctx.root, c, read=ctx.read)  # one snapshot for the decision and the evidence (J1)
        causes = [Status(st) for st, _, _ in a["problems"]]
        details = [{"code": code, **d} for _, code, d in a["problems"]]
        what = {"ids": "sample IDs", "groups": "groups", "time": "time order"}
        details.append({"code": "R-45.checked", "value": sum(a["counts"].values()),  # 0.20.2: in words
                        "message": f"checked {', '.join(what.get(c, c) for c in a['checked'])} across "
                                   f"{sum(a['counts'].values())} sample(s)"})
        status = combine(causes)
        reason = _reason(status, "splits overlap or are out of order, as declared",
                         "split metadata or files are incomplete", "split checks could not run",
                         "splits checked for ID, group and temporal overlap as declared ("
                         + ", ".join(a["checked"]) + "); undeclared leakage types are not checked")
        out.append(result("R-45", rel, status, reason, details,
                          [e for f in [rel, *[s_.ids_file for s_ in c.splits.sets if isinstance(s_.ids_file, str)], c.splits.metadata or ""]
                           for e in ctx.evidence(f)]))
    return out


def r46(ctx: Ctx) -> list[Result]:
    if not ctx.contract_files:
        return [result("R-46", ".", Status.NOT_APPLICABLE, "no contract files matched")]
    out = []
    for rel, c in sorted(ctx.contracts.items()):
        causes, details, hashed = [], [], 0
        for d in c.datasets:
            src = d.source if isinstance(d.source, str) and d.source not in ("TBD", "unknown") else None
            if src is None or escapes_root(src) or not inside(ctx.root, src) or not (ctx.root / src).is_file():
                details.append({"code": "R-46.not_a_repository_file", "value": d.id, "message": "the source is not a file in this repository; its hash is not checked"})
                continue
            if not isinstance(d.sha256, str) or d.sha256 in ("TBD", "unknown"):
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-46.no_hash", "value": d.id})
                continue
            hashed += 1
            if hashlib.sha256(ctx.read(src)).hexdigest() != d.sha256:
                causes.append(Status.FAIL)
                details.append({"code": "R-46.hash_mismatch", "value": d.id, "path": src})
        if not hashed and not causes:
            out.append(result("R-46", rel, Status.NOT_APPLICABLE, "no dataset source is a repository file", details))
            continue
        status = combine(causes)
        out.append(result("R-46", rel, status, _reason(status, "a dataset file does not match its recorded hash",
                          "a dataset hash is not recorded", "dataset hashes unknown",
                          f"{hashed} dataset file(s) match their recorded hashes"), details, ctx.evidence(rel)))
    return out


def _results_doc(ctx: Ctx, rel: str) -> Any:
    from . import evidence as ev

    data = ctx.read(rel)
    text = data.decode("utf-8-sig")
    return tomllib.loads(text, parse_float=ev._exact_float) if rel.endswith(".toml") else ev.loads_exact(text, strict_keys=True)


def _exact_thresholds(ctx: Ctx, rel: str) -> list[Any]:
    from . import evidence as ev

    try:
        raw = tomllib.loads(ctx.read(rel).decode("utf-8"), parse_float=ev._exact_float)
    except (ValueError, RecursionError, UnicodeDecodeError):
        return []
    return [t.get("value") if isinstance(t, dict) else None for t in raw.get("thresholds") or []]


def r47(ctx: Ctx) -> list[Result]:
    from . import benchmark as bm

    out = []
    for rel, c in sorted(ctx.contracts.items()):
        if c.results is None:
            continue
        rf = c.results.file
        if escapes_root(rf) or not inside(ctx.root, rf):
            out.append(result("R-47", rel, Status.FAIL, "the results file resolves outside the repository",
                              [{"code": "R-47.path_outside", "path": rf}], ctx.evidence(rel)))
            continue
        if not (ctx.root / rf).is_file():
            out.append(result("R-47", rel, Status.INCOMPLETE, "the results file does not exist yet",
                              [{"code": "R-47.no_results", "path": rf}], ctx.evidence(rel)))
            continue
        try:
            doc = _results_doc(ctx, rf)
        except (ValueError, UnicodeDecodeError, ValueError, RecursionError) as e:
            out.append(result("R-47", rel, Status.FAIL, "the results file cannot be read", [{"code": "R-47.invalid", "path": rf, "message": str(e)}]))
            continue
        a = bm.analyze_results(doc, c, _exact_thresholds(ctx, rel))
        causes = [Status(st) for st, _, _ in a["problems"] if st != "INFO"]
        details = [{"code": code, **d} for _, code, d in a["problems"]]
        details += [{"code": "R-47.threshold_met" if t["state"] == "met" else ("R-47.threshold_not_met" if t["state"] == "not met" else "R-47.threshold_not_evaluable"),
                     "value": t["metric"], "message": t.get("message", f"{t['split']}: {t['against']}")} for t in a["thresholds"]]
        status = combine(causes)
        out.append(result("R-47", rel, status, _reason(status, "results are malformed or name undefined splits",
                          "results are missing for some metric, method or split", "some results are unknown",
                          f"results present for every metric, method and required split; thresholds reported, not gating "
                          f"({sum(t['state'] == 'met' for t in a['thresholds'])} met, {sum(t['state'] == 'not met' for t in a['thresholds'])} not met)"),
                          details, ctx.evidence(rel) + ctx.evidence(rf)))
    return out or [result("R-47", ".", Status.NOT_APPLICABLE, "no contract declares [results]")]


def _wrote(run: dict[str, Any], path: str, current: str) -> bool:
    """The run wrote `path` (red-team J6): the file was absent before it, or its bytes or modification time changed.
    Records without the before-state (made before 0.7) do not qualify."""
    before = (run.get("outputs_before") or {}).get(path)
    after_mtime = (run["outcome"].get("outputs_mtime_ns") or {}).get(path)
    if not isinstance(before, dict):
        return False
    return before.get("sha256") is None or before.get("sha256") != current or before.get("mtime_ns") != after_mtime


def r48(ctx: Ctx) -> list[Result]:
    from . import evidence as ev

    out = []
    recs = None
    for rel, c in sorted(ctx.contracts.items()):
        if c.comparison is None or not c.comparison.output:
            continue
        path = c.comparison.output
        if escapes_root(path) or not inside(ctx.root, path):
            out.append(result("R-48", rel, Status.FAIL, "the comparison output resolves outside the repository",
                              [{"code": "R-48.path_outside", "path": path}], ctx.evidence(rel)))
            continue
        if not (ctx.root / path).is_file():
            out.append(result("R-48", rel, Status.INCOMPLETE, "the comparison output does not exist yet",
                              [{"code": "R-48.no_output", "path": path}], ctx.evidence(rel)))
            continue
        current = hashlib.sha256(ctx.read(path)).hexdigest()
        if recs is None:
            recs = ev.runs(ctx.root, ctx.config)
        made = [r for r in recs.values() if r["outcome"] and r["outcome"].get("status") == "finished"
                and (r["outcome"].get("outputs") or {}).get(path) == current and _wrote(r, path, current)
                and r.get("contract") in (None, c.id)]  # a run labelled for another contract does not count
        if not made:
            out.append(result("R-48", rel, Status.FAIL, "no finished run wrote the comparison output with its current hash",
                              [{"code": "R-48.not_from_run", "path": path}], ctx.evidence(rel)))
            continue
        split_hash: dict[str, str | None] = {}
        missing_splits = []
        for s_ in c.splits.sets:
            if not isinstance(s_.ids_file, str) or s_.ids_file in m.SENTINELS:
                continue
            if escapes_root(s_.ids_file) or not inside(ctx.root, s_.ids_file) or not (ctx.root / s_.ids_file).is_file():
                missing_splits.append(s_.ids_file)
                continue
            split_hash[s_.ids_file] = hashlib.sha256(ctx.read(s_.ids_file)).hexdigest()

        def judge(run: dict[str, Any]) -> tuple[list[Status], list[dict[str, Any]]]:
            causes, details = [], [{"code": "R-48.run", "value": run["run"]}]
            for split_file in missing_splits:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "R-48.split_missing", "path": split_file})
            for split_file, now in split_hash.items():
                if (run.get("inputs") or {}).get(split_file) != now:
                    causes.append(Status.FAIL)
                    details.append({"code": "R-48.inputs_changed", "path": split_file,
                                    "message": "the comparison was not produced from the current split file"})
            if c.analysis == "confirmatory":
                want = []
                if isinstance(c.comparison.seed, int) and str(run.get("seed")) != str(c.comparison.seed):
                    want.append(f"seed {c.comparison.seed}")
                if isinstance(c.comparison.resamples, int) and str((run.get("params") or {}).get("resamples")) != str(c.comparison.resamples):
                    want.append(f"resamples={c.comparison.resamples}")
                if want:
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-48.procedure_unrecorded", "message": "the run did not record " + ", ".join(want)
                                    + " (steward run --seed ... --param resamples=...)"})
            return causes, details
        rank = {Status.PASS: 0, Status.NOT_APPLICABLE: 0, Status.INCOMPLETE: 1, Status.UNKNOWN: 2, Status.FAIL: 3}
        judged = [(rank[combine(cs)], -i, r, cs, ds) for i, r in enumerate(made) for cs, ds in [judge(r)]]
        _, _, run, causes, details = min(judged, key=lambda j: (j[0], j[1]))  # the best qualifying run; the latest on ties
        status = combine(causes)
        out.append(result("R-48", rel, status, _reason(status, "the comparison was not produced from the current splits",
                          "the comparison procedure's settings or a split file are missing", "comparison provenance unknown",
                          f"the comparison output was written by run {run['run']} from the current split files"), details, ctx.evidence(rel)))
    return out or [result("R-48", ".", Status.NOT_APPLICABLE, "no contract declares [comparison] output")]


def r49(ctx: Ctx) -> list[Result]:
    """Declarations about leakage that identifiers cannot reveal. A declaration is recorded, never verified."""
    assert ctx.config is not None
    if not ctx.contract_files:
        return [result("R-49", ".", Status.NOT_APPLICABLE, "no contract files matched")]
    required_all = bool(ctx.config.benchmark and ctx.config.benchmark.require_leakage)
    out = []
    for rel, c in sorted(ctx.contracts.items()):
        decl = c.leakage or {}
        causes, details = [], []
        for key in sorted(set(decl) - set(m.LEAKAGE_TYPES)):
            causes.append(Status.FAIL)
            details.append({"code": "R-49.unknown_type", "value": key, "message": "known types: " + ", ".join(m.LEAKAGE_TYPES)})
        undeclared = [t for t in m.LEAKAGE_TYPES if t not in decl or decl[t] == m.UNKNOWN]
        for t in m.LEAKAGE_TYPES:
            d = decl.get(t)
            if d == m.TBD:
                causes.append(Status.INCOMPLETE)
                details.append({"code": "sentinel", "field": f"leakage.{t}", "value": d})
            elif isinstance(d, m.LeakageDecl):
                if d.status == "checked":
                    ev_path = (d.evidence or "").split("#", 1)[0]
                    if not ev_path or escapes_root(ev_path) or not inside(ctx.root, ev_path) or not (ctx.root / ev_path).is_file():
                        causes.append(Status.INCOMPLETE)
                        details.append({"code": "R-49.evidence_missing", "field": f"leakage.{t}", "path": d.evidence or ""})
                    else:
                        details.append({"code": "R-49.declared_checked", "field": f"leakage.{t}", "path": ev_path})
                elif not (d.reason or "").strip():
                    causes.append(Status.INCOMPLETE)
                    details.append({"code": "R-49.reason_missing", "field": f"leakage.{t}"})
                else:
                    details.append({"code": "R-49.declared_not_applicable", "field": f"leakage.{t}", "message": d.reason})
        applies = c.analysis == "confirmatory" or required_all
        if undeclared:
            details.append({"code": "R-49.undeclared", "value": len(undeclared), "message": "not checked: " + ", ".join(undeclared)})
            if applies:
                causes.append(Status.UNKNOWN)
        if not applies and not any(x is Status.FAIL for x in causes):
            out.append(result("R-49", rel, Status.NOT_APPLICABLE, "exploratory contract: leakage declarations are advisory "
                              "(set [benchmark] require_leakage = true to enforce)", details, ctx.evidence(rel)))
            continue
        status = combine(causes)
        out.append(result("R-49", rel, status, _reason(status, "the leakage table names an unknown type",
                          "a leakage declaration is incomplete", "leakage types are not declared (not checked)",
                          f"{len(m.LEAKAGE_TYPES)} undetectable leakage types declared, not verified"), details, ctx.evidence(rel)))
    return out


# ---------------------------------------------------------------- storage (v0.8): R-50
def r50(ctx: Ctx) -> list[Result]:
    from . import storage as stg

    assert ctx.config is not None
    sc = ctx.config.storage
    if sc is None:
        return [result("R-50", ".", Status.NOT_APPLICABLE, "[storage] is not configured")]
    rel = sc.artifacts
    reg = None
    if not stg.located(ctx.root, rel):  # red-team K2: the registry itself must be in the repository
        return [result("R-50", rel, Status.FAIL, "the artifact registry resolves outside the repository",
                       [{"code": "R-50.registry_outside", "path": rel}])]
    if (ctx.root / rel).is_file():
        try:
            reg = stg.load(ctx.read(rel).decode("utf-8"))
        except (ValidationError, ValueError, RecursionError, UnicodeDecodeError) as e:
            errs = m.format_errors(e) if isinstance(e, ValidationError) else [{"code": "parse", "message": str(e)}]
            return [result("R-50", rel, Status.FAIL, "the artifact registry is invalid", errs, ctx.evidence(rel))]
    a = stg.evaluate(ctx.root, reg, sc, ctx.final)
    for st in a["artifacts"]:  # streamed hashes enter the verdict's inputs without loading large files into memory
        if st.get("sha256"):
            ctx.inputs[st["path"]] = st["sha256"]
    ctx.inputs.update(a["pointers"])  # DVC pointers decide verdicts, so they are inputs too (K4)
    causes = [Status(x) for x, _, _ in a["problems"] if x != "INFO"]
    details = [{"code": code, **d} for _, code, d in a["problems"]]
    n = len(a["artifacts"])
    if not n and not causes:
        return [result("R-50", rel, Status.NOT_APPLICABLE, "no artifacts registered and no large files in git", details)]
    status = combine(causes)
    present = sum(1 for x in a["artifacts"] if x["state"] == "present")
    return [result("R-50", rel, status, _reason(status, "an artifact differs from its recorded hash",
                   "artifacts are unregistered, absent, or lack a retrieval note", "artifact state unknown",
                   f"{n} artifact(s) registered; {present} present and matching, {n - present} absent locally (hash recorded)"),
                   details, ctx.evidence(rel))]


# ---------------------------------------------------------------- governance (0.8.1): R-51
def r51(ctx: Ctx) -> list[Result]:
    """The constitution (C-1): declared, the installed version, and its records present when required."""
    from .resources import CONSTITUTION_VERSION

    assert ctx.config is not None
    declared = ctx.config.steward.constitution
    required = bool(ctx.config.governance and ctx.config.governance.required)
    hint = {"code": "R-51.recommended", "message": 'declare it: constitution = "' + CONSTITUTION_VERSION
            + '" under [steward] (steward constitution prints it)'}
    if declared is None:
        if required:
            return [result("R-51", "steward.toml", Status.INCOMPLETE, "the constitution is required but not declared", [hint])]
        return [result("R-51", "steward.toml", Status.NOT_APPLICABLE, "no constitution declared", [hint])]
    causes, details = [], []
    if declared != CONSTITUTION_VERSION:
        causes.append(Status.INCOMPLETE)
        details.append({"code": "R-51.version_differs", "value": declared,
                        "message": f"the installed toolkit has version {CONSTITUTION_VERSION}; read `steward constitution --changes`, then update"})
    if required:
        log = ctx.config.integrity.primary_decisions if ctx.config.integrity else f"{ctx.config.paths.records.rstrip('/')}/DECISIONS.md"
        if not (ctx.root / log).is_file():
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-51.no_decisions_log", "path": log, "message": "Article IV needs a decisions log"})
    status = combine(causes)
    return [result("R-51", "steward.toml", status, _reason(status, "", "the declared constitution or its records are incomplete",
                   "", f"constitution version {declared} declared and installed"), details, ctx.evidence("steward.toml"))]


def r53(ctx: Ctx) -> list[Result]:
    """The exchange folder, items and state ledger (constitution Article V; protocol step 1)."""
    from datetime import date as _date

    from . import exchange as xc
    from . import ledger as lg
    from .fsutil import git_run

    assert ctx.config is not None
    xcfg = ctx.config.exchange
    if xcfg is None:
        return [result("R-53", ".", Status.NOT_APPLICABLE, "[exchange] is not configured")]
    f = xc.folder(ctx.root)
    if f.is_symlink():  # review N4
        return [result("R-53", xc.FOLDER, Status.FAIL, "exchange/ is a symbolic link", [{"code": "R-53.symlink", "path": xc.FOLDER}])]
    if not f.is_dir():
        return [result("R-53", xc.FOLDER, Status.INCOMPLETE, "no exchange/ folder; run: steward exchange init")]
    causes, details = [], []
    for p in sorted(f.rglob("*")):
        if p.is_symlink():
            causes.append(Status.FAIL)
            details.append({"code": "R-53.symlink", "path": p.relative_to(ctx.root).as_posix()})
    for name in (*xc.SUBDIRS, "README.md"):  # review N6: the layout is checked for what is missing, too
        if not (f / name).exists():
            causes.append(Status.INCOMPLETE)
            details.append({"code": "R-53.missing_entry", "path": f"{xc.FOLDER}/{name}", "message": "run: steward exchange init"})

    def bad(code: str, status: Status = Status.FAIL, **kw: Any) -> None:
        causes.append(status)
        details.append({"code": f"R-53.{code}", **kw})
    unknown: list[str] = []  # the fixed layout (P6)
    metadata_md: list[str] = []  # a `._ID.md` AppleDouble file would otherwise be read as an item
    for p in sorted(f.iterdir()):
        if p.is_dir() and p.name in xc.SUBDIRS:
            for q in sorted(p.iterdir()):
                if q.name != ".keep" and (q.suffix != ".md" or not q.is_file()):
                    unknown.append(q.relative_to(ctx.root).as_posix())
                elif q.suffix == ".md" and xc.os_metadata(q.name):
                    metadata_md.append(q.relative_to(ctx.root).as_posix())
        elif p.name not in xc.FILES:
            unknown.append(p.relative_to(ctx.root).as_posix())
    # X01, ignored files (0.22.0): an untracked entry that git ignores, or an untracked OS metadata file
    # (.DS_Store, Thumbs.db, desktop.ini, `._*`), is not part of the exchange; a tracked one is checked as before
    skipped = xc.skippable(ctx.root, unknown + metadata_md)
    for rel in unknown:
        if rel not in skipped:
            bad("unknown_entry", path=rel)
    parsed: dict[str, tuple[str, Any]] = {}
    rel_of: dict[str, str] = {}
    seen: dict[str, str] = {}
    alias_of: dict[str, set[str]] = {}
    early = xc.states(ctx.root) if (f / "log.jsonl").is_file() else {}

    def _refiled(old_id: str, new_id: str, old_rel: str) -> bool:
        """DEF-010: a re-filed item may alias the item it replaces when that item is this project's own, in the
        same folder, and its last state is `merged` (or `closed`) with a note naming the new ID: they point at each
        other."""
        hist = early.get(old_id) or [{}]
        last = hist[-1]
        merged = [e for e in hist if e.get("state") == "merged"]  # U10 (0.12.0): a merge into the new ID, not only a close
        return Path(old_rel).stem == old_id and old_rel.startswith(f"{xc.FOLDER}/outbox/") \
            and new_id.split("-")[0] == old_id.split("-")[0] and last.get("state") in ("merged", "closed") and merged \
            and re.search(rf"(?<![\w-]){re.escape(new_id)}(?![\w-])", merged[-1].get("note") or "") is not None \
            and re.search(rf"(?<![\w-]){re.escape(new_id)}(?![\w-])", last.get("note") or "") is not None
    for place, entries in xc.items(ctx.root).items():
        for rel, text in entries:
            if rel in skipped:
                continue
            try:  # S5: the whole file must be UTF-8, the body too (the reader replaces bad bytes to list it at all)
                (ctx.root / rel).read_bytes().decode("utf-8")
            except UnicodeDecodeError as e:
                bad("invalid", path=rel, message=f"not UTF-8 at byte {e.start}")
                continue
            except OSError:
                bad("invalid", path=rel, message="cannot be read")
                continue
            try:
                head, _ = xc.parse(text)
                it = xc.Item.model_validate(head)
            except (ValueError, ValidationError, ValueError, RecursionError) as e:
                bad("invalid", path=rel, message=str(e).splitlines()[0][:200])
                continue
            if Path(rel).stem != it.id:
                bad("name_mismatch", path=rel, value=it.id)
            own = it.from_ == xcfg.code
            if (place in ("outbox", "oneway", "responses")) != own:
                bad("misplaced", path=rel, message=f"{place}/ holds {'this' if place != 'inbox' else 'a peer'} project's items")
            for key in [it.id, *it.aliases]:
                if key in seen and not (key != it.id and _refiled(key, it.id, seen[key])) \
                        and not (key == it.id and any(_refiled(key, n, rel) for n in alias_of.get(key, ()))):
                    bad("duplicate_id", path=rel, value=key, message=f"also {seen[key]}")
                seen.setdefault(key, rel)
            for a in it.aliases:
                alias_of.setdefault(a, set()).add(it.id)
            parsed[it.id] = (place, it)
            rel_of[it.id] = rel
    def _retired_receipt(iid: str) -> bool:
        """FB-018 (AB6, AC4, AC5): a received item whose file may be gone, by the one test (exchange.removable),
        with this check's own view of inbox/ and of this project's responses."""
        if iid in parsed:
            return False
        inbox = {i for i, (pl, _) in parsed.items() if pl == "inbox" and Path(rel_of[i]).stem == i}  # AD3
        answers: dict[str, list[Any]] = {}
        for i, (pl, it_) in parsed.items():
            if pl == "responses" and it_.kind == "response" and it_.responds_to:
                answers.setdefault(it_.responds_to, []).append(
                    xc.answered((ctx.root / rel_of[i]).read_text("utf-8", "replace")))
        return xc.removable(iid, early, inbox, answers)
    for iid, (place, it) in parsed.items():
        # a response answers an item the responder received (inbox), or, received here, this project's own item
        # (outbox); DEF-026
        target = parsed.get(it.responds_to or "")
        if it.kind == "response" and target is None and place == "responses" and it.responds_to not in parsed and \
                xc.retired_receipt(it.responds_to or "", early.get(it.responds_to or "", [])):
            # it answers a received item that was superseded or withdrawn and then removed: its binding must name
            # exactly the bytes the receipt recorded (AB7)
            ans = xc.answered((ctx.root / rel_of[iid]).read_text("utf-8", "replace"))  # AC7: the file parsed
            if ans is None or ans[0] != it.responds_to or ans[1] != xc.receipt_sha(early.get(it.responds_to or "", [])):
                bad("response_target_mismatch", value=iid,
                    message=f"answers {it.responds_to}, removed; its Answers binding does not name the bytes received")
            continue
        if it.kind == "response" and (target is None or target[0] not in ("inbox", "outbox")
                                      or (target[0] == "outbox") != (place == "inbox")):
            bad("orphan_response", value=iid, message=f"responds to {it.responds_to}, which is not in inbox/ or outbox/")
        elif it.kind == "response" and target[0] == "outbox" and target[1].to != it.from_:  # Q11
            bad("wrong_counterparty", value=iid, message=f"answers {it.responds_to}, addressed to {target[1].to}")
        elif it.kind == "response" and place == "inbox" and \
                xc.target_mismatch(ctx.root, (ctx.root / f"{xc.FOLDER}/inbox/{iid}.md").read_text("utf-8", "replace"),
                                   it.responds_to or ""):
            bad("response_target_mismatch", Status.INCOMPLETE, value=iid,
                message=f"answers other bytes than this project's {it.responds_to} (an ID collision); re-file under a new ID")
        if place == "oneway" and not it.channel:
            bad("oneway_channel", Status.INCOMPLETE, value=iid, message="a one-way item names its channel")
    log = f / "log.jsonl"
    history: dict[str, list[dict[str, Any]]] = {}
    if log.is_file():
        v = lg.verify(log)
        if v.errors or v.torn_tail:
            bad("ledger_broken", path=f"{xc.FOLDER}/log.jsonl")
        history = xc.states(ctx.root)
    for iid, entries in history.items():
        if iid not in parsed:
            # FB-018 (0.18.0): a received item that was superseded or withdrawn may lose its file; the ledger keeps
            # the receipt (with the file's hash) and the decision as the record
            done = [e["state"] for e in entries]
            if _retired_receipt(iid):
                prev = None
                for s in done:
                    if s not in xc.TWO_WAY.get(prev, set()):
                        bad("bad_transition", value=iid, message=f"{prev or '(new)'} → {s}")
                    prev = s
                st = next(s for s in reversed(done) if s in xc.RETIRED_STATES)
                details.append({"code": "R-53.removed_after_retirement", "value": iid,
                                "message": f"{st}; its file was removed, the receipt stays in the ledger"})
                continue
            bad("unknown_item", value=iid, message="the ledger names an item with no file")
            continue
        machine = xc.machine_for(parsed[iid][0], parsed[iid][1].kind)
        prev = None
        for e in entries:
            if e["state"] not in machine.get(prev, set()):
                bad("bad_transition", value=iid, message=f"{prev or '(new)'} → {e['state']}")
            prev = e["state"]
        shipped = [e for e in entries if e["state"] == "shipped"]  # review N6: also when a later state follows
        if shipped and parsed[iid][0] == "outbox":  # DEF-027: the receiver's tag, in another repository
            details.append({"code": "R-53.tag_not_verified", "value": iid,
                            "message": f"shipped by the receiver ({shipped[-1].get('note') or 'no note'}); stated, not verified here"})
        elif parsed[iid][0] == "inbox" and xc.current(entries) == "deferred" and \
                xc.released_since(ctx.root, entries[-1].get("note")):  # DEF-028: its target version has passed
            bad("deferred_stale", Status.INCOMPLETE, value=iid,
                message=f"deferred ({entries[-1].get('note')}); {xc.released_since(ctx.root, entries[-1].get('note'))} "
                        "is released: ship, re-defer or decline it")
        elif shipped:
            tag = xc.note_tag(shipped[-1].get("note"))
            out = git_run(ctx.root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", text=True, timeout=10) if tag else None
            if out is None or out.returncode != 0:
                bad("tag_missing", Status.INCOMPLETE, value=iid, message=f"shipped names tag {tag or '(none)'}, which does not exist here")
    from . import privacy as pv  # 0.9.0 C3: what this project sends passes its public term lists (R-07's lists)

    publics = [t for s in pv.load(ctx.root, ctx.config, read=ctx.read) if s.public and s.state == "ok" for t in s.terms]
    if publics:
        for place, entries in xc.items(ctx.root).items():
            if place == "inbox":
                continue
            for rel, text in entries:
                if rel in skipped:
                    continue
                hits, _ = pv.scan_text(text, publics, False)
                labels = sorted({h["term"].label for h in hits if h["kind"] == "term"})
                if labels:
                    bad("public_term", path=rel, value=", ".join(labels), message="reword before it is sent")
    today = _date.today()
    for iid, (place, it) in parsed.items():
        st = xc.current(history.get(iid, []))
        if place == "inbox" and it.kind == "release" and st not in ("adopted", "declined", "closed"):  # 0.9.0 D2
            used = xcfg.uses.get(it.from_)
            newer = used is None or (xc.version_key(it.version or "") or ()) > (xc.version_key(used) or ())
            if newer:
                details.append({"code": "R-53.upgrade_available", "value": iid,
                                "message": f"{it.from_} {it.version} released" + (f"; this project uses {used}" if used else "")
                                + "; adopt (with a parity record) or decline it"})
        if place == "inbox" and st is None and (today - it.filed).days > xcfg.ack_days:
            bad("unacknowledged", Status.INCOMPLETE, value=iid, message=f"received over {xcfg.ack_days} days ago")
        if place == "oneway" and st == "sent" and it.sent and (today - it.sent).days > xcfg.oneway_days:
            details.append({"code": "R-53.awaiting_reply", "value": iid, "message": "one-way: the other project owes no reply"})
    for delivery in xc.delivery_status(ctx.root, xcfg, overdue_only=True, any_age=True).outgoing:
        iid = delivery.item.id
        shown = "(withheld)" if pv.private_match(ctx.root, ctx.config, iid) else iid
        peer = delivery.item.to
        peer = "(withheld)" if pv.private_match(ctx.root, ctx.config, peer) else peer
        # X01, edited received items (0.22.0): an own item edited after the peer received it is reported at once, not only once the
        # peer's response arrives
        changed = xc.receipt_mismatch_advice(delivery, shown, peer)
        if changed:
            bad("receipt_mismatch", Status.INCOMPLETE, value=shown, message=changed)
        message = xc.delivery_advice(delivery, xcfg.delivery_days, shown, peer)  # overdue items only, as before
        if message:
            details.append({"code": "R-53.undelivered", "value": shown, "message": message})
    status = combine(causes)
    return [result("R-53", xc.FOLDER, status, _reason(status, "the exchange folder, an item or its state ledger is invalid",
                   "exchange items need attention", "", f"{len(parsed)} exchange item(s) valid, states recorded in the ledger"),
                   details)]


def _process(name: str, ctx: Ctx) -> list[Result]:
    from . import process  # the 0.9.0 process rules (R-56 – R-60) live in their own module

    return getattr(process, name)(ctx)


def r83(ctx: Ctx) -> list[Result]:
    from .datacontract import check_contracts

    return check_contracts(ctx)
def r84(ctx: Ctx) -> list[Result]:
    from .compare import r84 as check_shadow

    return check_shadow(ctx)


def r86(ctx: Ctx) -> list[Result]:
    from .models_records import check_models

    return check_models(ctx)


RULE_FUNCS: dict[str, Callable[[Ctx], list[Result]]] = {
    "R-83": r83,
    "R-01": r01, "R-02": r02, "R-03": r03, "R-04": r04, "R-05": r05, "R-06": r06, "R-07": r07,
    "R-08": r08, "R-09": r09, "R-10": r10, "R-11": r11, "R-12": r12, "R-13": r13, "R-14": r14, "R-15": r15,
    "R-21": r21, "R-22": r22, "R-23": r23, "R-24": r24, "R-25": r25, "R-26": r26, "R-27": r27, "R-28": r28,
    "R-29": r29, "R-31": r31, "R-32": r32, "R-33": r33, "R-34": r34, "R-35": r35, "R-36": r36, "R-37": r37,
    "R-38": r38, "R-39": r39, "R-40": r40, "R-41": r41, "R-42": r42, "R-43": r43, "R-44": r44,
    "R-45": r45, "R-46": r46, "R-47": r47, "R-48": r48, "R-49": r49, "R-50": r50, "R-51": r51, "R-53": r53,
    "R-52": lambda c: _process("r52", c), "R-54": lambda c: _process("r54", c), "R-55": lambda c: _process("r55", c), "R-56": lambda c: _process("r56", c), "R-57": lambda c: _process("r57", c), "R-58": lambda c: _process("r58", c),
    "R-59": lambda c: _process("r59", c), "R-60": lambda c: _process("r60", c),
    "R-61": lambda c: _process("r61", c), "R-62": lambda c: _process("r62", c),
    "R-68": lambda c: _process("r68", c), "R-69": lambda c: _process("r69", c), "R-70": lambda c: _process("r70", c),
    "R-71": lambda c: _process("r71", c), "R-72": lambda c: _process("r72", c),
    "R-73": lambda c: _process("r73", c), "R-74": lambda c: _process("r74", c),
    "R-75": lambda c: _process("r75", c), "R-76": lambda c: _process("r76", c),
    "R-77": lambda c: _process("r77", c), "R-78": lambda c: _process("r78", c),
    "R-79": lambda c: _process("r79", c), "R-80": lambda c: _process("r80", c),
    "R-81": lambda c: _process("r81", c), "R-82": lambda c: _process("r82", c),
    "R-85": lambda c: _process("r85", c), "R-63": lambda c: _process("r63", c),
    "R-84": r84,
    "R-87": lambda c: __import__("steward.stranger", fromlist=["r87"]).r87(c),
    "R-88": lambda c: __import__("steward.cockpit", fromlist=["r88"]).r88(c),
    "R-86": r86,
    "R-66": lambda c: _process("r66", c), "R-64": lambda c: _process("r64", c), "R-65": lambda c: _process("r65", c), "R-67": lambda c: _process("r67", c),
}
