"""STW-023: compare the recorded outputs of two fixture runs."""

import json
import re
import sys
from pathlib import Path

import pytest

from conftest import append, codes, gate, one
from steward.fsutil import canonical_json, sha256_bytes
from steward.ledger import Ledger
from steward.models import ADVISORY, load_config


@pytest.fixture
def comparison_project(example, monkeypatch):
    monkeypatch.chdir(example)
    append(example, "steward.toml", """
[[stages]]
name = "classify"
reads = "metadata"
shadow = true

[gates.promotion]
require = ["R-01", "R-84"]

[docs]
publish = ["comparisons"]
""")
    return example


def recorded_run(root, run, path, csv, time, status="finished"):
    cfg = load_config(root)
    ledger = Ledger(root / "development/runs.jsonl", "runs", cfg.steward.repo_id, base=root)
    (root / path).write_text(csv, encoding="utf-8")
    ledger.append("started", {"run": run})
    ledger.append("outcome", {"run": run, "time": time, "status": status,
                              "exit_code": 0 if status == "finished" else 1,
                              "outputs": {path: sha256_bytes(csv.encode())}})


def fixture_runs(root):
    recorded_run(root, "old", "old.csv", "item,class\nz,yes\nb,no\na,yes\nd,\n", "2026-11-24T12:00:00Z")
    recorded_run(root, "new", "new.tsv", "item\tclass\nc\tno\nb\tyes\na\tyes\nd\t\n", "2026-11-25T12:00:00Z")


def record(cli, *options):
    return cli("compare", "record", "classify", "--a", "old", "--b", "new", "--key", "item", *options)


def files(root):
    return sorted((root / "development/comparisons/classify").glob("*.json"))


def test_record_is_byte_stable_and_lists_every_disagreement(cli, comparison_project):
    root = comparison_project
    fixture_runs(root)
    assert record(cli)[0] == 0
    [path] = files(root)
    first = path.read_bytes()
    assert record(cli)[0] == 0
    assert files(root) == [path] and path.read_bytes() == first
    doc = json.loads(first)
    assert doc["a"]["run"] == "old" and doc["b"]["run"] == "new"
    assert doc["agreement"] == {
        "equal": 2, "different": 1, "only_a": 1, "only_b": 1,
    }
    assert doc["disagreements"] == [
        {"key": "b", "a": "no", "b": "yes"},
        {"key": "c", "a": None, "b": "no"},
        {"key": "z", "a": "yes", "b": None},
    ]
    assert doc["classes"] == {"": {"a": 1, "b": 1, "equal": 1},
                              "no": {"a": 1, "b": 1, "equal": 0},
                              "yes": {"a": 2, "b": 2, "equal": 1}}
    assert first == canonical_json(doc).encode()


def test_shadow_advice_reports_missing_current_and_stale(cli, comparison_project):
    root = comparison_project
    fixture_runs(root)
    _, report = cli.check(root)
    assert "R-84.missing" in codes(one(report, "R-84"))
    assert "R-84" in ADVISORY
    assert all(item["rule"] != "R-84" for item in gate(report)["blocking"])
    assert record(cli)[0] == 0
    _, report = cli.check(root, gate="promotion")
    current = one(report, "R-84")
    assert current["status"] == "PASS"
    assert gate(report, "promotion")["eligible"]
    assert {e["path"] for e in current["evidence"]} >= {"development/runs.jsonl", "old.csv", "new.tsv"}
    append(root, "new.tsv", "q\tno\n")
    _, report = cli.check(root, gate="promotion")
    stale = one(report, "R-84")
    assert stale["status"] == "INCOMPLETE" and "R-84.stale" in codes(stale)
    assert not gate(report, "promotion")["eligible"]
    assert "digest changed" in stale["details"][0]["message"]
    assert record(cli)[0] == 65


def test_site_charts_historical_agreement_without_row_values(cli, comparison_project):
    root = comparison_project
    fixture_runs(root)
    assert record(cli)[0] == 0
    recorded_run(root, "next", "next.csv", "item,class\na,private-label\n", "2026-11-26T12:00:00Z")
    assert cli("compare", "record", "classify", "--a", "old", "--b", "next", "--key", "item")[0] == 0
    assert len(files(root)) == 2
    earlier = root / "new.tsv"
    earlier_bytes = earlier.read_bytes()
    earlier.unlink()
    assert one(cli.check(root, "compare")[1], "R-84")["status"] == "PASS"
    assert cli("docs", "build")[0] == 0
    page = root / "docs/project/comparisons.md"
    generated = page.read_text()
    assert "<svg" in generated and "Agreement over time" in generated
    assert "| 2026-11-25T12:00:00Z | 2 | 5 | 40.00%" in generated
    assert "| 2026-11-26T12:00:00Z | 0 | 4 | 0.00%" in generated
    assert generated.index("2026-11-25") < generated.index("2026-11-26")
    assert "private-label" not in generated and "next.csv" not in generated
    assert cli("docs", "build")[0] == 0 and page.read_text() == generated
    earlier.write_bytes(earlier_bytes)
    (root / "next.csv").unlink()
    assert "R-84.stale" in codes(one(cli.check(root, "compare")[1], "R-84"))


@pytest.mark.parametrize(("contents", "error"), [
    ("item,class\nx,yes\nx,no\n", "duplicate key"),
    ("item,class\n,no\n", "empty key"),
    ("item,item\nx,no\n", "duplicate column"),
    ("item,class\nx\n", "wrong number of columns"),
    ("item,class,label\nx,yes,no\n", "--value"),
])
def test_invalid_tables_leave_no_record(cli, comparison_project, contents, error):
    root = comparison_project
    recorded_run(root, "old", "old.csv", contents, "2026-11-24T12:00:00Z")
    recorded_run(root, "new", "new.csv", "item,class\nx,yes\n", "2026-11-25T12:00:00Z")
    code, _, err = record(cli)
    assert code == 65 and error in err
    assert not files(root)


def test_refuses_linked_output_and_changed_record(cli, comparison_project):
    root = comparison_project
    fixture_runs(root)
    assert record(cli)[0] == 0
    [path] = files(root)
    path.write_bytes(path.read_bytes() + b" ")
    _, report = cli.check(root, "compare")
    assert "R-84.invalid" in codes(one(report, "R-84"))
    assert cli("docs", "build")[0] == 65

    output = root / "new.tsv"
    output.rename(root / "copy.tsv")
    output.symlink_to(Path("copy.tsv"))
    code, _, err = record(cli)
    assert code == 65 and "link" in err


def test_uses_outputs_from_steward_run_and_explicit_columns(cli, comparison_project):
    runs = []
    for name in ("old", "new"):
        path = name + ".csv"
        command = f"from pathlib import Path; Path({path!r}).write_text('item,class,note\\nx,yes,ok\\n')"
        if name == "old":
            command += "; Path('extra.csv').write_text('item,class\\nx,no\\n')"
        options = ["--output", "extra.csv"] if name == "old" else []
        code, _, err = cli("run", "--output", path, *options, "--", sys.executable, "-c", command)
        assert code == 0, err
        runs.append(re.search(r"steward: run (\S+) finished", err)[1])

    args = ("compare", "record", "classify", "--a", runs[0], "--b", runs[1], "--key", "item")
    assert cli(*args, "--value", "class")[0] == 65
    assert cli(*args, "--value", "class", "--output-a", "old.csv")[0] == 0
    [path] = files(comparison_project)
    assert json.loads(path.read_bytes())["agreement"]["equal"] == 1


def test_refuses_sealed_or_failed_run_outputs(cli, comparison_project):
    root = comparison_project
    append(root, "steward.toml", "\n[integrity]\n")
    append(root, "development/datasets.toml", """
schema = "steward.datasets/0.1"

[datasets.holdout]
role = "sealed"
identifier = "unknown"
paths = ["held.csv"]
""")
    recorded_run(root, "sealed", "held.csv", "item,class\nx,yes\n", "2026-11-24T12:00:00Z")
    recorded_run(root, "alias", "alias.csv", "item,class\nx,yes\n", "2026-11-24T12:00:01Z")
    recorded_run(root, "failed", "failed.csv", "item,class\nx,no\n", "2026-11-24T12:00:02Z", status="failed")
    recorded_run(root, "new", "new.csv", "item,class\nx,no\n", "2026-11-25T12:00:00Z")
    for run, reason in (("sealed", "sealed dataset"), ("alias", "sealed dataset"), ("failed", "successful outcome")):
        code, _, err = cli("compare", "record", "classify", "--a", run, "--b", "new", "--key", "item")
        assert code == 65 and reason in err
    assert not files(root)
