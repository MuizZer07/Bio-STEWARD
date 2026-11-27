"""W09 local fault records and exchange self-reports."""

import json
import shutil
import socket
import subprocess

import pytest
from jsonschema import Draft202012Validator

from steward import __version__, exchange, issues
from steward.fsutil import canonical_json

from conftest import REPO, one
from test_interface import EXAMPLES, GOLDEN


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("issue reporting attempted network access")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "")


def project(cli, root, code, extra=""):
    root.mkdir()
    assert cli("init", "--repo", root)[0] == 0
    with (root / "steward.toml").open("a") as config:
        config.write(f'\n[exchange]\ncode = "{code}"\n{extra}')
    assert cli("exchange", "init", "--repo", root)[0] == 0
    return root


def validate(document):
    tag = document["schema"].replace("/", "-")
    schema = json.loads((REPO / "schemas" / f"{tag}.schema.json").read_text())
    Draft202012Validator(schema).validate(document)


def assert_golden(name, document):
    assert canonical_json(document) == (GOLDEN / name).read_text()


def commit_project(root):
    def git(*args):
        subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", "-f", "steward.toml", "exchange/outbox", "exchange/inbox/.keep",
        "exchange/oneway/.keep", "exchange/responses/.keep", "exchange/README.md", "exchange/log.jsonl")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "File report")


def test_faults_only_replace_the_breadcrumb_then_explicitly_file(cli, tmp_path, monkeypatch):
    from steward import cli as cli_module

    root = project(cli, tmp_path / "consumer", "ABC")
    secret = root / "secret-record.txt"
    secret.write_text("unpublished-data-marker")
    monkeypatch.setenv("PRIVATE_TOKEN", "private-environment-marker")

    def fail(*args, **kwargs):
        raise RuntimeError(f"{secret}: {secret.read_text()}")

    with monkeypatch.context() as patch:
        patch.setattr(cli_module, "run_check", fail)
        for _ in range(100):
            code, out, err = cli("check", "--repo", root, "--gate=private-argument-marker", "--format", "json")
            assert code == 70 and not out
            assert err.count(issues.HINT) == 1 and "nothing was sent" in err
        assert list((root / ".steward").iterdir()) == [root / issues.LAST_ERROR]
    assert list((root / "exchange/outbox").glob("*.md")) == []
    assert not (root / "exchange/log.jsonl").exists()
    snapshot = json.loads((root / issues.LAST_ERROR).read_text())
    validate(snapshot)
    assert snapshot["flags"] == ["--format", "--gate", "--repo"]
    assert snapshot["command"] == "check"
    assert {frame["file"] for frame in snapshot["frames"]} == {"steward/cli.py"}

    assert cli("issue", "--repo", root, "--from-last-error")[0] == 0
    item = root / "exchange/outbox/ABC-DEF-001.md"
    original = item.read_bytes()
    code, out, _ = cli("issue", "--repo", root, "--from-last-error")
    assert code == 0 and "seen again" in out
    assert list(item.parent.glob("*.md")) == [item] and item.read_bytes() == original
    ledger = (root / "exchange/log.jsonl").read_text()
    assert '"kind":"issue_seen_again"' in ledger and '"note":"seen again"' in ledger
    for text in (original.decode(), canonical_json(snapshot), ledger, err):
        for marker in (str(root), secret.name, secret.read_text(), "private-argument-marker", "private-environment-marker"):
            assert marker not in text
    code, out, err = cli("check", "--repo", root, "--rule", "R-53", "--format", "json")
    assert code == 0, err
    assert one(json.loads(out), "R-53")["status"] == "PASS"


def test_screen_cannot_be_bypassed_by_an_occurrence_marker(cli, tmp_path):
    root = project(cli, tmp_path / "consumer", "ABC",
                   '\n[[terms]]\nname = "internal"\nfile = "private.txt"\nexclude = ["exchange/**"]\n')
    (root / "private.txt").write_text("internal-name\n")
    home = "/" + "home" + "/researcher/file.txt"  # built, as in test_v0180, so the published-file scans do not flag it
    for description in ("A problem with internal-name <!-- steward:allow-term -->", f"See {home}"):
        code, _, err = cli("issue", "--repo", root, description)
        assert code == 65 and "refused" in err and "internal-name" not in err
    assert not list((root / "exchange/outbox").glob("*.md"))


def test_rule_failure_and_self_schema_failure_print_hints(cli, tmp_path, monkeypatch):
    from steward import cli as cli_module
    from steward.engine import RULE_FUNCS

    root = project(cli, tmp_path / "consumer", "ABC")

    def fail(*args, **kwargs):
        raise ValueError("private diagnostic")

    with monkeypatch.context() as patch:
        patch.setitem(RULE_FUNCS, "R-02", fail)
        code, out, err = cli("check", "--repo", root, "--rule", "R-02", "--format", "json")
        assert code == 3 and issues.HINT in err
        assert one(json.loads(out), "R-02")["status"] == "UNKNOWN"
        assert issues.read_last_error(root).exit_code == 3

    real = cli_module.run_check

    def malformed(*args, **kwargs):
        report = real(*args, **kwargs)
        report["schema"] = "injected"
        return report

    monkeypatch.setattr(cli_module, "run_check", malformed)
    code, out, err = cli("check", "--repo", root, "--format", "json")
    assert code == 70 and not out and issues.HINT in err
    assert issues.read_last_error(root).exit_code == 70


@pytest.mark.parametrize("name", EXAMPLES)
def test_breadcrumb_and_received_inbox_goldens(name, cli, tmp_path, monkeypatch):
    from steward import cli as cli_module

    def fail(*args, **kwargs):
        raise RuntimeError("private diagnostic")

    hub = tmp_path / name
    shutil.copytree(REPO / "examples" / name, hub, ignore=shutil.ignore_patterns(".steward"))
    with (hub / "steward.toml").open("a") as config:
        config.write('\n[exchange]\ncode = "HUB"\n[exchange.peers]\nABC = "../first"\nXYZ = "../second"\n')
    assert cli("exchange", "init", "--repo", hub)[0] == 0

    with monkeypatch.context() as patch:
        patch.setattr(cli_module, "run_check", fail)
        assert cli("check", "--repo", hub, "--summary")[0] == 70
    raw = json.loads((hub / issues.LAST_ERROR).read_text())
    validate(raw)
    for number, frame in enumerate(raw["frames"], 1):
        frame["line"] = number
    raw["tool_version"] = "VERSION"
    raw["fingerprint"] = issues.fingerprint(raw["error_type"], [issues.ErrorFrame(**f) for f in raw["frames"]])
    assert_golden(f"{name}.last-error.json", raw)

    for dirname, code in (("first", "ABC"), ("second", "XYZ")):
        sender = project(cli, tmp_path / dirname, code, '\n[report]\nto = "HUB"\n')
        assert cli("issue", "--repo", sender, "The toolkit omitted a status detail")[0] == 0
        commit_project(sender)
    assert cli("exchange", "pull", "--repo", hub)[0] == 0
    code, out, err = cli("issues", "inbox", "--repo", hub, "--format", "json")
    assert code == 0 and not err
    document = json.loads(out)
    validate(document)
    assert document["groups"][0]["versions"] == [__version__]
    document["groups"][0]["versions"] = ["VERSION"]
    assert_golden(f"{name}.issues-inbox.json", document)

    item = hub / "exchange/inbox/ABC-DEF-001.md"
    item.write_text(item.read_text() + "\nchanged receipt\n")
    assert "ABC-DEF-001" not in cli("issues", "inbox", "--repo", hub)[1]


def test_retry_recovers_filed_state_and_a_closed_item_can_be_reported_again(cli, tmp_path):
    root = project(cli, tmp_path / "consumer", "ABC")
    args = ("issue", "--repo", root, "Missing toolkit diagnostic")
    assert cli(*args)[0] == 0
    original = root / "exchange/outbox/ABC-DEF-001.md"
    original_bytes = original.read_bytes()
    (root / "exchange/log.jsonl").unlink()  # interruption after the file write
    assert cli(*args)[0] == 0
    assert list(original.parent.glob("*.md")) == [original]
    assert original.read_bytes() == original_bytes
    assert exchange.current(exchange.states(root)[original.stem]) == "filed"

    assert cli("exchange", "state", original.stem, "closed", "--repo", root)[0] == 0
    assert cli(*args)[0] == 0
    assert (original.parent / "ABC-DEF-002.md").is_file()


def test_toolkit_limitation_uses_the_code_and_keeps_the_rule_status(cli, tmp_path, monkeypatch):
    from steward.engine import RULE_FUNCS
    from steward.rules import result
    from steward.status import Status

    root = project(cli, tmp_path / "consumer", "ABC")
    monkeypatch.setitem(RULE_FUNCS, "R-13", lambda ctx: [
        result("R-13", ".", Status.UNKNOWN, "limitation", [{"code": "R-13.pages_unsupported"}]),
    ])
    code, out, err = cli("check", "--repo", root, "--rule", "R-13", "--format", "json")
    assert code == 3 and issues.HINT in err
    assert one(json.loads(out), "R-13")["status"] == "UNKNOWN"
    assert issues.read_last_error(root).error_type == "R_13_pages_unsupported"


@pytest.mark.parametrize("name", EXAMPLES)
def test_waived_gate_golden(name, cli, tmp_path, monkeypatch):
    from steward import authorize, review
    from conftest import gate
    from test_review import register

    root = tmp_path / name
    shutil.copytree(REPO / "examples" / name, root, ignore=shutil.ignore_patterns(".steward"))
    with (root / "steward.toml").open("a") as config:
        config.write('\n[release]\nrequired = []\nreview_required = true\n[policy]\n'
                     '[gates.waiver]\nrequire = ["R-01", "R-43"]\n')
    tag = "steward/auth/" + "a" * 32
    register(root, "accepted", f'waiver = "{tag}"', rev="a" * 40)
    monkeypatch.setattr(review, "coverage", lambda *args: (True, []))
    monkeypatch.setattr(authorize, "verify", lambda *a, **k: authorize.Verified(
        tag, "fixture", {"scope": "finding=A1"}, "env"))
    code, report = cli.check(root, gate="waiver")
    assert code == 0
    validate(report)
    assert_golden(f"{name}.waived-gate.json", gate(report, "waiver"))
