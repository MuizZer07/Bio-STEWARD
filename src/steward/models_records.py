"""Model cards checked against study records and recorded evaluations."""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from . import evidence, licence
from .fsutil import escapes_root, sha256_bytes
from .ledger import verify_bytes
from .models import SENTINELS, Contract, ModelRecord, RunSection, StewardConfig
from .records import Study, _md, _sha_file, read_rel
from .rules import Ctx, _wrote, result
from .status import Result, Status


def ledger_path(cfg: StewardConfig) -> str:
    return (cfg.run or RunSection()).ledger


def study_path(cfg: StewardConfig, sid: str) -> str:
    return (Path(cfg.studies.dir) / f"{sid}.toml").as_posix()


def _file_path(path: str) -> bool:
    return bool(Path(path).parts) and "\x00" not in path and not escapes_root(path)


def _run_events(data: bytes, repo_id: str) -> dict[str, list[dict]]:
    chain = verify_bytes(data)
    header = chain.entries[0] if chain.entries else {}
    if (chain.errors or chain.torn_tail or header.get("kind") != "genesis"
            or header.get("ledger") != "runs" or header.get("repo_id") != repo_id):
        raise ValueError("invalid run ledger")
    runs = defaultdict(list)
    for entry in chain.entries[1:]:
        run_id = entry.get("run")
        if isinstance(run_id, str) and entry.get("kind") in ("started", "outcome", "interrupted"):
            runs[run_id].append(entry)
    return runs


def _mapping(entry: dict, key: str) -> dict:
    value = entry.get(key)
    return value if isinstance(value, dict) else {}


def _recorded_metrics(start: dict, outcome: dict) -> dict:
    """Use the captured JSON only when the run recorded writing that output."""
    text, path, cwd = (outcome.get("metrics_text"), outcome.get("metrics_file"), start.get("cwd"))
    if not isinstance(text, str) or not isinstance(path, str) or not isinstance(cwd, str) or not _file_path(path):
        raise ValueError("missing metrics capture")
    path = (Path(cwd) / path).as_posix()
    if not _file_path(path):
        raise ValueError("metrics path escapes the project")
    digest = _mapping(outcome, "outputs").get(path)
    # Path.read_text in the runner normalizes line endings.
    encodings = (text, text.replace("\n", "\r\n"), text.replace("\n", "\r"))
    if not any(sha256_bytes(raw.encode("utf-8")) == digest for raw in encodings):
        raise ValueError("recorded metrics differ from the output digest")
    run = {**start, "outcome": {**outcome, "outputs_mtime_ns": _mapping(outcome, "outputs_mtime_ns")},
           "outputs_before": _mapping(start, "outputs_before")}
    if not _wrote(run, path, digest):
        raise ValueError("run did not write the metrics")
    return evidence.flatten(evidence.loads_exact(text, strict_keys=True))


def check_models(ctx: Ctx) -> list[Result]:
    cfg = ctx.config
    assert cfg is not None
    if not cfg.model:
        return [result("R-86", ".", Status.NOT_APPLICABLE, "no model records configured")]

    @cache
    def read(path: str) -> bytes | None:
        if not _file_path(path):
            return None
        try:
            raw = read_rel(ctx.root, path)
        except OSError:
            return None
        ctx.inputs[path] = sha256_bytes(raw)
        return raw

    @cache
    def digest(path: str) -> str | None:
        if not _file_path(path):
            return None
        try:
            current = _sha_file(ctx.root, path)
        except OSError:
            return None
        if current is not None:
            ctx.inputs[path] = current
        return current

    @cache
    def load(path: str, schema):
        raw = read(path)
        if raw is not None:
            try:
                return schema.model_validate(tomllib.loads(raw.decode("utf-8")))
            except (ValueError, RecursionError):
                pass
        return None

    ledger = ledger_path(cfg)
    try:
        runs = _run_events(read(ledger) or b"", cfg.steward.repo_id)
    except (ValueError, RecursionError):
        runs = None
    config_bytes = read("steward.toml")
    versions = Counter((model.name, model.version) for model in cfg.model)
    out = []
    for model in cfg.model:
        paths = {"steward.toml", ledger, model.weights.path, model.contract}
        details = []
        if config_bytes is None or config_bytes != ctx.snapshot.get("steward.toml", config_bytes):
            details.append({"code": "R-86.config_refused", "message": "Keep the model configuration in a regular file"})
        if versions[model.name, model.version] > 1:
            details.append({"code": "R-86.duplicate", "message": "Keep one record per model name and version"})
        try:
            licence.parse_expr(model.licence)
        except (ValueError, RecursionError):
            details.append({"code": "R-86.licence", "message": "Use an SPDX licence expression for the weights"})

        weight_sha = digest(model.weights.path)
        if weight_sha != model.weights.sha256:
            details.append({"code": "R-86.weights_changed", "path": model.weights.path,
                            "message": "Restore the recorded weights or record and evaluate the new weights"})
        for sid in sorted(set(model.training_studies)):
            path = study_path(cfg, sid) if cfg.studies else None
            if path:
                paths.add(path)
            study = load(path, Study) if path else None
            if study is None or study.id != sid or not study.inputs or any(not i.files for i in study.inputs):
                details.append({"code": "R-86.training_study", "value": sid,
                                "message": "Record the study and its training inputs under the configured studies directory"})
                continue
            for item in study.inputs:
                for file in item.files:
                    paths.add(file.path)
                    current = digest(file.path)
                    if current is None or current != file.sha256:
                        details.append({"code": "R-86.training_input", "path": file.path, "value": sid,
                                        "message": "Check the training file against the study fingerprint"})

        contract = load(model.contract, Contract)
        splits = [s for s in contract.splits.sets if s.name == model.split] if contract else []
        expected_inputs = {model.weights.path: weight_sha}
        if contract is None or len(splits) != 1:
            details.append({"code": "R-86.contract_split", "path": model.contract, "value": model.split,
                            "message": "Name a valid benchmark contract and a split it defines once"})
        else:
            expected_inputs[model.contract] = ctx.inputs[model.contract]
            for path in sorted({s.ids_file for s in contract.splits.sets}):
                paths.add(path)
                expected_inputs[path] = None if path in SENTINELS else digest(path)
                if expected_inputs[path] is None:
                    details.append({"code": "R-86.split_file", "path": path,
                                    "message": "Restore the split file named by the benchmark contract"})
            for name in sorted(model.metrics.keys() - {metric.name for metric in contract.metrics.defs}):
                details.append({"code": "R-86.metric_undefined", "value": name,
                                "message": "Use a metric name defined in the benchmark contract"})
        details.extend(_check_run(model, contract, expected_inputs, runs))
        subject = f"{model.name} ({model.version})"
        status = Status.FAIL if details else Status.PASS
        message = ("model record is missing evidence or does not match it" if details
                   else "model weights, training inputs and evaluation metrics match their records")
        out.append(result("R-86", subject, status, message, details,
                          [item for path in sorted(paths) for item in ctx.evidence(path)]))
    return out


def _check_run(model: ModelRecord, contract: Contract | None, expected_inputs: dict, runs: dict | None) -> list[dict]:
    if runs is None:
        return [{"code": "R-86.run_ledger", "message": "Keep an intact run ledger for this project"}]
    entries = runs.get(model.run, [])
    if (len(entries) != 2 or entries[0]["kind"] != "started" or entries[1]["kind"] != "outcome"
            or entries[1].get("status") != "finished" or entries[1].get("exit_code") != 0):
        return [{"code": "R-86.run_missing", "value": model.run, "message": "Use a run with one successful outcome"}]

    start, outcome = entries
    details = []
    if contract and (start.get("contract") != contract.id or _mapping(start, "params").get("split") != model.split):
        details.append({"code": "R-86.run_context", "value": model.run,
                        "message": "Record the contract ID and split on the evaluation run"})
    inputs = _mapping(start, "inputs")
    for path, current in expected_inputs.items():
        if current is not None and inputs.get(path) != current:
            details.append({"code": "R-86.input_changed", "path": path,
                            "message": "Record an evaluation that uses this file with its current contents"})
    try:
        recorded = _recorded_metrics(start, outcome)
    except (ValueError, RecursionError):
        return details + [{"code": "R-86.metrics_unrecorded",
                           "message": "Record the JSON this run writes with both --metrics and --output"}]
    for name, metric in sorted(model.metrics.items()):
        try:
            matches = evidence.compare(recorded.get(metric.pointer), Decimal(metric.value), None) == "equal"
        except InvalidOperation:
            matches = False
        if not matches:
            details.append({"code": "R-86.metric_mismatch", "value": name,
                            "message": "Use an exact numeric value captured at the pointer in the evaluation run"})
    return details


def card(model: ModelRecord) -> str:
    """Render a verified record as Markdown."""
    lines = [f"## {_md(model.name)} · {_md(model.version)}", "",
             f"- **Intended use** — {_md(model.intended_use)}",
             f"- **Known limits** — {', '.join(_md(limit) for limit in model.known_limits)}",
             f"- **Weights** — {_md(model.weights.path)} (SHA-256 `{model.weights.sha256}`)",
             f"- **Weights licence** — {_md(model.licence)}",
             f"- **Training studies** — {', '.join(_md(sid) for sid in model.training_studies)}",
             f"- **Evaluation** — {_md(model.contract)}, split {_md(model.split)}, run {_md(model.run)}",
             "", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {_md(name)} | {metric.value} |" for name, metric in sorted(model.metrics.items()))
    return "\n".join(lines) + "\n"
