"""W01 machine interface and byte compatibility on both worked examples."""

import argparse
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from conftest import CONTRACT, REPO
from test_tokens import claude_messages, jsonl

GOLDEN = REPO / "tests" / "golden" / "interface"
READ_COMMANDS = {
    "audit progress": (),
    "benchmark results": (CONTRACT,),
    "benchmark splits": (CONTRACT,),
    "diff impact": (),
    "diff run": ("first", "second"),
    "diff runs": (),
    "exchange status": (),
    "licence inventory": (),
    "pins status": (),
    "research list": (),
    "storage audit": ("--top", "0"),
    "storage scan": (),
    "storage verify": (),
    "study list": (),
    "timeline": (),
    "tokens report": ("--claude", Path("fixture-usage.jsonl")),
}
EXAMPLES = ("biology-geo", "toy-expression-benchmark")


@pytest.fixture(params=EXAMPLES)
def machine_example(request, tmp_path, monkeypatch):
    from steward import cleanup, exchange, ledger, milestones, records, tokens
    from steward.models import RunSection

    import psutil

    # The process list is the machine's, not the project's: an agent's sandbox sees none and a desktop sees some it
    # may not read, which changes `storage scan`'s note. Pin it so the goldens hold on any machine.
    def _no_process_list(*_args, **_kwargs):
        raise psutil.Error("process list pinned by the test")

    monkeypatch.setattr(psutil, "process_iter", _no_process_list)
    name = request.param
    root = tmp_path / name
    shutil.copytree(REPO / "examples" / name, root, ignore=shutil.ignore_patterns(
        ".steward", "__pycache__", ".DS_Store", "*.aux", "*.bbl", "*.blg", "*.fdb_latexmk", "*.fls",
        "*.out", "*.nav", "*.snm", "*.toc",
    ))
    # Some features need records beyond those in the worked examples.
    extra = """
[run]
[exchange]
code = "DEMO"
[exchange.peers.PEER]
url = "https://example.invalid/peer.git"
[storage.caps]
results = 1
[storage.clean]
registry = false
paths = ["fixture-output"]
[licence]
declared = "MIT"
site_packages = []
lockfile = "fixture-requirements.txt"
[[pin]]
name = "fixture"
package = "fixture"
version = "1"
artifact = "fixture.whl"
"""
    if name == "toy-expression-benchmark":
        extra += "\n[studies]\n[research]\n"
    with (root / "steward.toml").open("a", encoding="utf-8") as f:
        f.write(extra)
    (root / "fixture-requirements.txt").write_text("fixture==1\n", encoding="utf-8")
    contract = root / CONTRACT
    if not contract.exists():
        toy = REPO / "examples" / "toy-expression-benchmark"
        shutil.copytree(toy / "benchmarks", root / "benchmarks")
        shutil.copyfile(toy / "data" / "samples.csv", root / "data" / "samples.csv")
    with contract.open("a", encoding="utf-8") as f:
        f.write('\n[results]\nfile = "fixture-results.json"\n')
    (root / "fixture-results.json").write_text(
        '{"test":{"candidate":{"auroc":0.8},"majority-class":{"auroc":0.5},"logistic-regression":{"auroc":0.7}}}\n',
        encoding="utf-8",
    )
    (root / "fixture-output").write_bytes(b"fixture")
    (root / "development/artifacts.toml").write_text(
        'schema = "steward.artifacts/0.1"\n[[artifacts]]\npath = "fixture-output"\nsize = 7\n'
        'sha256 = "' + "a" * 64 + '"\nretrieval = "fixture"\n', encoding="utf-8",
    )
    outbox = root / "exchange/outbox"
    outbox.mkdir(parents=True)
    item = {"schema": "steward.exchange/1", "id": "DEMO-REQ-001", "kind": "request", "from": "DEMO", "to": "PEER",
            "filed": "2026-11-27", "title": "Example request", "against": "0.20.7"}
    (outbox / "DEMO-REQ-001.md").write_text(exchange.render(item, "Example request.\n"), encoding="utf-8")

    def unexpected_peer_access(*args, **kwargs):
        pytest.fail("exchange status attempted to reach the remote peer")

    monkeypatch.setattr(exchange, "peer_revision", unexpected_peer_access)
    monkeypatch.setattr(cleanup, "registered", lambda: [])
    monkeypatch.setattr(cleanup, "SHARED_ENV", ())
    monkeypatch.setattr(cleanup, "SHARED_DEFAULTS", ())
    monkeypatch.setattr(cleanup, "SHARED_DEFAULTS_ALL", ())
    monkeypatch.setattr(cleanup, "mount_point", lambda path: Path("/"))
    # Resolve the explicit local log argument in the example directory.
    monkeypatch.chdir(root)
    jsonl(root / "fixture-usage.jsonl", claude_messages())
    monkeypatch.setattr(records, "today_utc", lambda: date(2026, 11, 27))
    instant = datetime(2026, 11, 27, tzinfo=timezone.utc)
    monkeypatch.setattr(tokens, "now", lambda: instant)
    original_timeline = milestones.timeline
    monkeypatch.setattr(milestones, "timeline", lambda root, cfg: original_timeline(root, cfg, now=instant))
    (root / milestones.FILE).write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "review"\n'
        'title = "Review the example"\ndue = 2026-12-01T00:00:00Z\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ledger, "_now", lambda: "2026-11-27T00:00:00Z")
    runs = ledger.Ledger(root / RunSection().ledger, "runs", "fixture")
    for run in ("first", "second"):
        runs.append("started", {"run": run, "label": "fixture"})
        runs.append("outcome", {"run": run, "status": "finished", "exit_code": 0, "duration_s": 1.0,
                                "peak_rss_mb": 2.0, "outputs": {"fixture-results.json": "a" * 64}})
    return name, root


def _golden_bytes(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_legacy_json_goldens(cli, machine_example):
    from steward import __version__

    name, root = machine_example
    expected = json.loads((GOLDEN / f"{name}.legacy.json").read_text(encoding="utf-8"))
    expected["audit progress"]["stdout"]["where"]["toolkit_version"] = __version__
    assert expected.keys() == READ_COMMANDS.keys()
    for command, arguments in READ_COMMANDS.items():
        code, out, err = cli(*command.split(), *arguments, "--repo", root, "--json")
        assert code == expected[command]["exit"], (command, err)
        assert out == _golden_bytes(expected[command]["stdout"]), command


def test_tagged_json_goldens(cli, machine_example):
    from jsonschema import Draft202012Validator

    from steward import __version__
    from steward.resources import schemas_dir

    name, root = machine_example
    expected = json.loads((GOLDEN / f"{name}.tagged.json").read_text(encoding="utf-8"))
    expected["audit progress"]["stdout"]["where"]["toolkit_version"] = __version__
    expected["interface"]["stdout"]["tool_version"] = __version__
    code, out, err = cli("interface", "--format", "json")
    interface = json.loads(out)
    assert code == expected["interface"]["exit"] and not err
    assert out == _golden_bytes(expected["interface"]["stdout"])
    assert {cmd for cmd, info in interface["commands"].items() if "legacy_argv" in info} == READ_COMMANDS.keys()
    for command, arguments in {"interface": (), **READ_COMMANDS}.items():
        if command != "interface":
            code, out, err = cli(*command.split(), *arguments, "--repo", root, "--format", "json")
        assert code == expected[command]["exit"], (command, err)
        assert out == _golden_bytes(expected[command]["stdout"]), command
        doc = json.loads(out)
        schema_id = interface["commands"][command]["schema"]
        assert doc["schema"] == schema_id
        file = schemas_dir() / interface["schema_files"][schema_id]
        schema = json.loads(file.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(doc)


def test_interface_without_project(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli("interface", "--format", "json")
    assert (code, err) == (0, "")
    assert json.loads(out)["schema"] == "steward.interface/1"


def test_json_format_conflicts(cli):
    for flags in (("--json", "--format", "json"), ("--svg", "--format", "json")):
        code, out, err = cli("tokens", "report", *flags)
        assert code == 64 and not out and "not allowed" in err


def test_every_legacy_json_command_is_advertised():
    from steward.cli import build_parser
    from steward.interface import describe

    def legacy_commands(parser, prefix=()):
        for action in parser._actions:
            if "--json" in action.option_strings:
                yield " ".join(prefix)
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    yield from legacy_commands(child, (*prefix, name))

    advertised = describe()["commands"]
    assert set(legacy_commands(build_parser())) == {cmd for cmd, spec in advertised.items() if "legacy_argv" in spec}


def test_tagged_progress_audit_preserves_privacy_redactions(cli, example):
    from jsonschema import Draft202012Validator

    from steward.audit import WITHHELD
    from steward.resources import schemas_dir

    (example / "private-terms.txt").write_text("where\nschema\n", encoding="utf-8")
    with (example / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[privacy]\ndenylist_file = "private-terms.txt"\n')
    code, out, err = cli("audit", "progress", "--repo", example, "--format", "json")
    assert code == 0, err
    doc = json.loads(out)
    assert doc["schema"] == "steward.progress_audit/0.1"
    assert "where" not in doc and WITHHELD in doc
    schema = schemas_dir() / "steward.progress_audit-0.1.schema.json"
    Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).validate(doc)


def test_not_configured_under_python_dash_m(tmp_path):
    """`python -m steward.cli` loads cli.py twice; a research command in a folder without steward.toml must still exit
    78 with the error document, never an internal error (found in W02's verification)."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "steward.cli", "study", "list", "--repo", str(tmp_path), "--format", "json"],
                       capture_output=True, text=True, env={**__import__("os").environ, "STEWARD_NO_REGISTRY": "1"})
    assert r.returncode == 78, r.stderr
    assert json.loads(r.stdout)["code"] == "not_configured"
    assert "internal error" not in r.stderr
