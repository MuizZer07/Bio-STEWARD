"""Model cards and their recorded evidence (STW-022)."""

import json
import sys

import pytest

from steward.fsutil import safe_write, sha256_bytes
from steward.records import read_rel

from conftest import CONTRACT, append, codes, edit, gate, one


WEIGHTS = "results/weights.bin"
SPLITS = [f"benchmarks/splits/{name}.txt" for name in ("train", "validation", "test")]
LEDGER = ".steward/evaluation/runs.jsonl"
STUDY = "development/studies/training.toml"
METRICS = "results/evaluation.json"
DATA = "data/expression.csv"


def _evaluate(cli, script):
    return cli("run", "--contract", "expr-clf", "--param", "split=test",
               "--input", WEIGHTS, "--input", CONTRACT, *[arg for p in SPLITS for arg in ("--input", p)],
               "--metrics", METRICS, "--output", METRICS, "--", sys.executable, "-c", script)


@pytest.fixture
def project(cli, example, monkeypatch):
    monkeypatch.chdir(example)
    weight_sha = sha256_bytes(b"test weights")
    safe_write(example, WEIGHTS, b"test weights")
    safe_write(example, STUDY, f"""schema = "steward.study/1"
id = "training"
title = "Training data"

[[inputs]]
id = "toy"
files = [{{ path = "{DATA}", sha256 = "{sha256_bytes(read_rel(example, DATA))}" }}]
""".encode())
    append(example, "steward.toml", f"""
[run]
ledger = "{LEDGER}"
logs = ".steward/evaluation"

[studies]

[docs]
publish = ["models"]
""")
    calc = f"from pathlib import Path; Path({METRICS!r}).write_text('{{\"auroc\": 0.912345678901234567}}')"
    code, _, err = _evaluate(cli, calc)
    assert code == 0, err
    run = json.loads(read_rel(example, LEDGER).splitlines()[-1])["run"]
    append(example, "steward.toml", f"""
[[model]]
name = "Toy classifier"
version = "1"
weights = {{ path = "{WEIGHTS}", sha256 = "{weight_sha}" }}
training_studies = ["training"]
contract = "{CONTRACT}"
split = "test"
run = "{run}"
metrics = {{ auroc = {{ pointer = "/auroc", value = "0.912345678901234567" }} }}
intended_use = "Compare models on synthetic data"
known_limits = ["Synthetic data only"]
licence = "Apache-2.0"
""")
    return example


def test_no_models(cli, example):
    _, report = cli.check(example, "models")
    assert one(report, "R-86")["status"] == "NOT_APPLICABLE"
    assert "models" in report["verdict"]["coverage"]["areas"]["not_configured"]


def test_card_uses_run_and_builds_site(cli, project):
    safe_write(project, METRICS, b'{"auroc": 0.2}')
    _, report = cli.check(project)
    check = one(report, "R-86")
    assert check["status"] == "PASS", check
    assert "models" in report["verdict"]["coverage"]["areas"]["configured"]
    assert {WEIGHTS, CONTRACT, LEDGER, STUDY, *SPLITS} <= {x["path"] for x in check["evidence"]}
    assert cli("docs", "init")[0] == 0
    assert cli("docs", "build")[0] == 0
    card = read_rel(project, "docs/project/models.md").decode()
    assert "Toy classifier" in card and "0.912345678901234567" in card
    assert "Apache-2.0" in card and "Synthetic data only" in card and "training" in card
    assert "models.md" in read_rel(project, "docs/project/index.md").decode()
    assert "project/models.md" in read_rel(project, "mkdocs.yml").decode()
    assert one(cli.check(project, "docs")[1], "R-69")["status"] == "PASS"


@pytest.mark.parametrize(("path", "content", "expected"), [
    (WEIGHTS, b"changed", "weights_changed"),
    (SPLITS[0], b"changed\n", "input_changed"),
    (CONTRACT, None, "input_changed"),
    (LEDGER, b"broken", "run_ledger"),
    (STUDY, b"broken", "training_study"),
    (DATA, b"changed", "training_input"),
])
def test_changed_evidence_fails(cli, project, path, content, expected):
    safe_write(project, path, content if content is not None else read_rel(project, path) + b"\n")
    check = one(cli.check(project, "models")[1], "R-86")
    assert check["status"] == "FAIL" and f"R-86.{expected}" in codes(check), check


@pytest.mark.parametrize(("old", "new", "expected"), [
    ('value = "0.912345678901234567"', 'value = "0.912345678901234568"', "metric_mismatch"),
    ('pointer = "/auroc"', 'pointer = "/missing"', "metric_mismatch"),
    ('split = "test"', 'split = "validation"', "run_context"),
    ('licence = "Apache-2.0"', 'licence = "MIT OR"', "licence"),
])
def test_unbacked_card_blocks_default_gate_and_site(cli, project, old, new, expected):
    edit(project, "steward.toml", old, new)
    code, report = cli.check(project)
    check = one(report, "R-86")
    assert check["status"] == "FAIL" and f"R-86.{expected}" in codes(check), check
    assert code == 1 and any(item["rule"] == "R-86" for item in gate(report)["blocking"])
    assert cli("docs", "build")[0] == 65
    assert not (project / "docs/project").exists()


def test_model_check_refuses_linked_weights_and_run_ledger(cli, project):
    for path in (WEIGHTS, LEDGER):
        original = project / path
        moved = original.with_suffix(".copy")
        original.rename(moved)
        original.symlink_to(moved.name)
    check = one(cli.check(project, "models")[1], "R-86")
    assert check["status"] == "FAIL" and {"R-86.weights_changed", "R-86.run_ledger"} <= codes(check)


@pytest.mark.parametrize(("script", "expected"), [
    ("pass", "metrics_unrecorded"),
    ("raise SystemExit(1)", "run_missing"),
])
def test_cannot_reuse_metrics_left_by_a_previous_run(cli, project, script, expected):
    old_run = json.loads(read_rel(project, LEDGER).splitlines()[-1])["run"]
    _evaluate(cli, script)
    new_run = json.loads(read_rel(project, LEDGER).splitlines()[-1])["run"]
    assert new_run != old_run
    edit(project, "steward.toml", f'run = "{old_run}"', f'run = "{new_run}"')
    check = one(cli.check(project, "models")[1], "R-86")
    assert check["status"] == "FAIL" and f"R-86.{expected}" in codes(check), check


def test_site_scans_card_text_before_markdown_escaping(cli, project):
    append(project, "steward.toml", '\n[[terms]]\nname = "private"\nfile = "development/private.txt"\n')
    safe_write(project, "development/private.txt", b"trial_marker\n")
    edit(project, "steward.toml", "Synthetic data only", "trial_marker")
    code, _, err = cli("docs", "build")
    assert code == 65 and "private" in err and "trial_marker" not in err


@pytest.mark.parametrize("match_path", [True, False])
def test_site_refuses_card_for_sealed_weights(cli, project, match_path):
    append(project, "steward.toml", '\n[integrity]\n')
    sealed = WEIGHTS if match_path else "results/sealed-copy.bin"
    if not match_path:
        safe_write(project, sealed, read_rel(project, WEIGHTS))
    safe_write(project, "development/datasets.toml", f"""schema = "steward.datasets/0.1"
[datasets.weights]
role = "sealed"
identifier = "TBD"
paths = ["{sealed}"]
""".encode())
    code, _, err = cli("docs", "build")
    assert code == 65 and "sealed dataset" in err
