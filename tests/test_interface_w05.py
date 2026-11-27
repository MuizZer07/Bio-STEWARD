"""STW-050 status documents on both worked examples."""

import hashlib
import json
import shutil
import socket

import pytest
from jsonschema import Draft202012Validator

from conftest import REPO, append
from test_interface import GOLDEN, _golden_bytes, machine_example

NONCE = "a" * 32
OBJECT = "sha256:" + "b" * 64
SPRINT = """schema = "steward.sprint/0.1"
[sprint]
id = "fixture"
window = { start = 2026-11-27T00:00:00Z, end = 2026-11-27T08:00:00Z }
[[task]]
id = "T1"
title = "Check the example"
command = "true"
done = ["true"]
[[task]]
id = "T2"
title = "Review the example"
command = "true"
done = ["true"]
after = ["T1"]
"""


@pytest.fixture
def status_example(machine_example, monkeypatch):
    from steward import authorize, records, sprint, talk
    from steward.ledger import Ledger
    from steward.models import load_config

    name, root = machine_example
    config = root / "steward.toml"
    config.write_text(config.read_text().replace("[paper.main]", '[paper.main]\ncitations = "citations.toml"'))
    append(root, "steward.toml", """
[policy]
baseline = "fixture"
[spend]
cap = 5
[integrity]
[session]
handoff = "development/W05-HANDOFF.md"
[publish]
remote = "https://example.invalid/public.git"
[tasks]
specs = ["development/tasks/**/*.md"]
archive = ["development/archive/**/*.md"]
board = "development/TASKS.md"
[tokens]
claude = ["fixture-usage.jsonl"]
[[channel]]
name = "fixture-tool"
stable = "https://example.invalid/stable.git"
dev = "https://example.invalid/dev.git"
[[channel]]
name = "other-tool"
stable = "https://example.invalid/stable.git"
dev = "https://example.invalid/dev.git"
""")
    study_id = "pd-substantia-nigra"
    if name == "toy-expression-benchmark":
        study_id = "example-study"
        append(root, f"development/studies/{study_id}.toml",
               'schema = "steward.study/1"\nid = "example-study"\ntitle = "Example study"\n')
    else:
        append(root, "paper/displays.toml", 'schema = "steward.displays/0.1"\n[displays.example]\n'
               'kind = "figure"\noutput = "paper/example.pdf"\nscript = "paper/make-example.py"\nlabel = "fig:example"\n')
        append(root, "steward.toml", """
[talk.progress-update]
dir = "talks/progress-update"
main = "slides.tex"
paper = "main"
""")
        dest = root / "talks/progress-update"
        dest.mkdir(parents=True)
        source = REPO / "examples/toy-expression-benchmark/talks/progress-update/talk.toml"
        shutil.copyfile(source, dest / "talk.toml")
        plan = dest / "talk.toml"
        plan.write_text(plan.read_text().replace('purpose      = "progress-update"', 'purpose      = "TBD"'))

    cfg = load_config(root)
    append(root, "development/tasks/DEMO-001.md", "# Active task\n\n- **ID:** DEMO-001\n- **Status:** in progress (review)\n")
    append(root, "development/archive/DEMO-002.md", "# Archived task\n\n- **ID:** DEMO-002\n- **Status:** done\n")
    append(root, cfg.tasks.board, "# Board\n\n- **ID:** DEMO-999\n")
    append(root, cfg.session.handoff, "# Handoff\n\nResume from the example records.\n")
    append(root, f"{sprint.DIR}/fixture.toml", SPRINT)
    from steward import ledger as ledger_module

    with monkeypatch.context() as pinned:  # the sprint status reports each task's times from its ledger
        pinned.setattr(ledger_module, "_now", lambda: "2026-11-27T01:00:00Z")
        led = sprint.led(root, "fixture", cfg.steward.repo_id)
        led.append("state", {"task": "T1", "state": "done", "branch": "sprint/fixture/T1", "commit": "c" * 40,
                             "checks": [{"command": "true", "exit": 0}]})
        led.append("order", {"task": "T2", "order": "go"})
    spend = Ledger(root / cfg.spend.ledger, "spend", cfg.steward.repo_id)
    spend.append("estimate", {"call": "fixture", "est_cost": 1.5})
    spend.append("actual", {"call": "fixture", "cost": 1.0})
    integrity = Ledger(root / cfg.integrity.ledger, "integrity", cfg.steward.repo_id)
    integrity.append("freeze", {"name": "fixture", "snapshot": {"hash": OBJECT}})
    integrity.append("proposal", {"name": "fixture"})
    integrity.append("seal", {"dataset": "example"})
    append(root, ".steward/channels.json", json.dumps(
        {"fixture-tool": {"channel": "dev", "tag": "v0.1.0", "time": "2026-11-27T00:00:00Z"}}
    ))

    fields = {"repo_id": cfg.steward.repo_id, "action": "spend", "object": OBJECT,
              "scope": "task=DEMO-001", "budget": "2 USD", "expires": "2099-12-31T00:00:00Z",
              "baseline": "c" * 40, "nonce": NONCE}
    # CRLF matters to the digest even though it leaves the parsed fields unchanged.
    pending = root / ".steward/pending" / f"{NONCE}.txt"
    pending.parent.mkdir()
    pending.write_bytes(authorize.render(fields, "Example spending request.").replace("\n", "\r\n").encode())
    assert not (root / ".git").exists()
    # Pin read-only git results for example folders without their own history.
    monkeypatch.setattr(authorize, "resolve_baseline", lambda *_: fields["baseline"])
    monkeypatch.setattr(authorize, "baseline_file", lambda *_: b"demo sk-ssh-ed25519@openssh.com fixture-key\n")
    monkeypatch.setattr(authorize, "list_tags", lambda *_: [])
    from steward import publish
    from subprocess import CompletedProcess

    monkeypatch.setattr(publish, "_git", lambda *a, **k: CompletedProcess(a, 0, "v0.2.0\n", ""))
    monkeypatch.setattr(talk, "config_home", lambda: root / ".steward/test-user-settings")

    def network(*_args, **_kwargs):
        pytest.fail("status command attempted network access")

    monkeypatch.setattr(records, "fetch_title", network)
    monkeypatch.setattr(socket.socket, "connect", network)
    return name, root, study_id, pending


def test_status_goldens(cli, status_example, monkeypatch):
    from steward.interface import READ_COMMANDS
    from steward.resources import schemas_dir

    name, root, study_id, pending = status_example
    expected = json.loads((GOLDEN / f"{name}.w05.json").read_text())
    code, out, err = cli("interface", "--format", "json")
    assert code == 0, err
    interface = json.loads(out)
    assert expected.keys() == set(READ_COMMANDS) | {"tokens report"}
    # A different caller directory exercises root-relative configured log paths.
    monkeypatch.chdir(root / "development")
    operands = {"authorize pending": ["--all-projects"], "sprint status": ["fixture"], "study show": [study_id]}
    for command, want in expected.items():
        code, out, err = cli(*command.split(), *operands.get(command, []), "--repo", root, "--format", "json")
        assert code == want["exit"], (command, err)
        assert not err, (command, err)
        assert out == _golden_bytes(want["stdout"]), command
        doc = json.loads(out)
        entry = interface["commands"][command]
        assert doc["schema"] == entry["schema"]
        schema = json.loads((schemas_dir() / interface["schema_files"][entry["schema"]]).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(doc)
        if command == "authorize pending":
            item, = doc["items"]
            assert item["payload_sha256"] == hashlib.sha256(pending.read_bytes()).hexdigest()
            assert item["object"] == OBJECT and item["nonce"] == NONCE
    code, out, err = cli("tokens", "report", "--repo", root, "--format", "json", "--codex", "missing.jsonl")
    assert code == 0, err
    sources = json.loads(out)["sources"]
    assert not sources["claude"]["files"] and sources["codex"]["files"]


def test_status_does_not_run_write_options(cli, example):
    for command, operand in {
        "paper values": ("--write",),
        "paper displays": ("--record",),
        "paper citations": ("--fetch",),
        "talk plan": ("--write-outline",),
        "talk prefs": ("--set", "style.density", "sparse"),
    }.items():
        code, out, err = cli(*command.split(), "--repo", example, "--format", "json", *operand)
        assert code == 64 and not out and "cannot be used with" in err


def test_session_handoff_missing_and_link(cli, example, tmp_path):
    code, out, err = cli("session", "start", "--repo", example, "--format", "json")
    assert code == 0, err
    handoff = json.loads(out)["handoff"]
    target = example / handoff["path"]
    target.unlink(missing_ok=True)
    code, out, err = cli("session", "start", "--repo", example, "--format", "json")
    assert code == 0, err
    assert json.loads(out)["handoff"]["text"] is None

    outside = tmp_path / "outside.md"
    outside.write_text("not part of the project")
    target.symlink_to(outside)
    code, out, err = cli("session", "start", "--repo", example, "--format", "json")
    assert code == 65 and not out and "link" in err
