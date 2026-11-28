"""0.23.0 D01 (delegation): [delegation] in steward.toml, `steward agents setup`, the "cannot run" endings of each
agent, the availability ledger, `steward agents status`, the init offer and the advisory rule R-89.

The agents here are stand-ins: small shell scripts on a PATH of the test's own, and a HOME of its own, so no real
agent CLI is found or run. Regenerate the goldens after an intended change:
STEWARD_UPDATE_GOLDENS=1 pytest tests/test_v0230_delegation.py
"""

import datetime as dt
import json
import os
import socket
import stat
from pathlib import Path

import pytest

from conftest import codes, one
from test_interface import GOLDEN, _golden_bytes, machine_example  # noqa: F401
from test_interface_w02 import _valid

FIXTURES = Path(__file__).parent / "fixtures" / "agent_endings"
NOW = dt.datetime(2026, 11, 18, 15, 0, tzinfo=dt.timezone.utc)
UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}/usr/bin{os.pathsep}/bin")


@pytest.fixture
def no_network(monkeypatch):
    def refused(*_args, **_kwargs):
        raise AssertionError("steward opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


def fake_agent(folder: Path, exe: str, version: str, status: tuple[str, str] | None = None, *, signed_in=True) -> Path:
    """A stand-in agent CLI: `--version`, `--help` (listing the status subcommand when it has one) and the status
    subcommand. Any other call (a prompt) is written to calls.log as well and fails."""
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "calls.log"
    sub = f"  {status[0]}   Manage sign-in\\n" if status else ""
    said = ("Logged in using ChatGPT" if exe == "codex" else '{"loggedIn": true}') if signed_in else "Not logged in"
    body = f"""#!/bin/sh
echo "{exe} $*" >> "{log}"
case "$*" in
  --version) echo "{version}" ;;
  --help) printf 'Usage: {exe} [options]\\n\\nCommands:\\n{sub}' ;;
  "{' '.join(status) if status else '-'}") echo '{said}'; exit {0 if signed_in else 1} ;;
  *) echo "a prompt was passed" >&2; exit 9 ;;
esac
"""
    p = folder / exe
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return log


def install(which: str = "codex agy"):
    """codex on PATH; agy only in ~/.gemini/bin; claude on PATH when asked."""
    bin_ = Path(os.environ["PATH"].split(os.pathsep)[0])
    logs = []
    if "claude" in which.split():
        logs.append(fake_agent(bin_, "claude", "2.1.50 (Claude Code)", ("auth", "status")))
    if "codex" in which.split():
        logs.append(fake_agent(bin_, "codex", "codex-cli 0.125.0", ("login", "status"), signed_in=False))
    if "agy" in which.split():
        logs.append(fake_agent(Path(os.environ["HOME"]) / ".gemini" / "bin", "agy", "1.5.18"))
    return logs


def calls(logs) -> list[str]:
    return [line for log in logs if log.is_file() for line in log.read_text().splitlines()]


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    return r


def toml(root) -> str:
    return (root / "steward.toml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the endings
@pytest.mark.parametrize("agent,fixture,kind,reset", [
    ("claude-code", "claude-limit-5h.jsonl", "limited", "2026-11-18T19:40:00Z"),
    ("claude-code", "claude-limit-weekly.txt", "limited", "2026-11-19T21:00:00Z"),
    ("claude-code", "claude-signed-out.txt", "signed_out", None),
    ("codex", "codex-limit-at.jsonl", "limited", "2026-11-18T15:04:00Z"),
    ("codex", "codex-limit-in.jsonl", "limited", "2026-11-20T18:04:00Z"),
    ("codex", "codex-signed-out.jsonl", "signed_out", None),
    ("codex", "codex-sandbox.txt", "sandbox", None),
    ("codex", "codex-missing.txt", "missing", None),
    ("antigravity", "antigravity-limit.txt", "limited", "2026-11-18T17:13:05Z"),
    ("antigravity", "antigravity-exhausted.json", "limited", None),
    ("antigravity", "antigravity-signed-out.txt", "signed_out", None),
    ("antigravity", "antigravity-sandbox.txt", "sandbox", None),
    ("antigravity", "antigravity-missing.txt", "missing", None),
])
def test_D01_each_ending_is_recognised_with_its_reset_time(agent, fixture, kind, reset):
    from steward import delegation as dg

    e = dg.read_ending(agent, FIXTURES / fixture, NOW, UTC)
    assert e is not None and (e.kind, e.reset) == (kind, reset), e
    assert e.agent == agent and e.message and "\n" not in e.message and len(e.message) <= 200


@pytest.mark.parametrize("agent,fixture", [
    ("claude-code", "claude-task-failure.jsonl"),  # an error result that is not a limit, after a quoted limit
    ("codex", "codex-tool-output.jsonl"),  # a command's output quotes a limit message; then a failed test
    ("codex", "codex-not-limited.jsonl"),  # the real rate-limit status record: 93% used, no limit reached
])
def test_D01_a_task_failure_is_not_a_cannot_run_ending(agent, fixture):
    from steward import delegation as dg

    assert dg.read_ending(agent, FIXTURES / fixture, NOW, UTC) is None


def test_D01_every_agent_has_its_own_table_and_every_fixture_is_listed():
    from steward import delegation as dg

    assert set(dg.ENDINGS) == set(dg.AGENTS) == {"claude-code", "codex", "antigravity"}
    for name in dg.AGENTS:
        kinds = {k for k, _ in dg._COMPILED[name]}
        assert kinds == set(dg.KINDS), name
    listed = (FIXTURES / "SOURCES.txt").read_text(encoding="utf-8")
    for f in FIXTURES.iterdir():
        assert f.name == "SOURCES.txt" or f.name in listed, f.name
    with pytest.raises(ValueError):
        dg.ending("shell", "anything")


def test_D01_only_the_end_of_a_log_is_read(tmp_path):
    from steward import delegation as dg

    log = tmp_path / "task.log"
    early = "You've hit your usage limit. Try again in 5 minutes.\n"
    log.write_text(early + "".join(f"line {i}\n" for i in range(dg.TEXT_TAIL + 5)), encoding="utf-8")
    assert dg.read_ending("codex", log, NOW, UTC) is None  # the limit line is above the last lines
    log.write_text("x" * (dg.LOG_TAIL + 10) + "\n" + early, encoding="utf-8")
    assert dg.read_ending("codex", log, NOW, UTC).kind == "limited"
    link = tmp_path / "link.log"
    link.symlink_to(log)
    assert dg.read_ending("codex", link, NOW, UTC) is None
    assert dg.read_ending("codex", tmp_path / "none.log", NOW, UTC) is None


@pytest.mark.parametrize("line,expected", [
    ("You've hit your 5-hour limit · resets 2:40pm (Europe/Berlin)", "2026-11-19T13:40:00Z"),  # 15:00Z is past it
    ("You've hit your 5-hour limit · resets 4pm (UTC)", "2026-11-18T16:00:00Z"),
    ("You've hit your weekly limit · resets Nov 17 at 4pm (UTC)", "2026-11-17T16:00:00Z"),  # already past: as stated
    ("You've hit your weekly limit · resets Jan 2 at 4pm (UTC)", "2027-01-02T16:00:00Z"),  # next year's
    ("try again at Nov 30th, 2026 3:04 PM", "2026-11-30T15:04:00Z"),
    ("try again in 1 hour", "2026-11-18T16:00:00Z"),
    ("Your quota will reset after 45m", "2026-11-18T15:45:00Z"),
    ("resets 13pm (UTC)", None),
    ("resets 4pm (Nowhere/Zone)", None),
    ("You've hit your limit", None),
])
def test_D01_reset_times(line, expected):
    from steward import delegation as dg

    assert dg.reset_time(line, NOW, UTC) == expected


# ---------------------------------------------------------------- [delegation]
def test_D01_delegation_section_validates(proj, cli):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[delegation]\nmaster = "claude-code"\nworkers = ["codex", "claude-code"]\n')
    code, rep = cli.check(proj, "config")
    assert one(rep, "R-01")["status"] == "FAIL" and "master is also a worker" in json.dumps(rep)
    (proj / "steward.toml").write_text(toml(proj).replace('["codex", "claude-code"]', '["codex"]\non_limit = "soon"'))
    code, rep = cli.check(proj, "config")
    assert one(rep, "R-01")["status"] == "FAIL"
    (proj / "steward.toml").write_text(toml(proj).replace('on_limit = "soon"', 'on_limit = "wait"\n'
                                                          '[delegation.models]\ncodex = "gpt-5.5"'))
    code, rep = cli.check(proj, "config")
    assert one(rep, "R-01")["status"] == "PASS"


def test_D01_replace_table_keeps_every_other_line():
    from steward import delegation as dg

    block = dg.render({"master": "claude-code", "workers": ["codex"], "on_limit": "next", "models": {}})
    text = ('[steward]\nrepo_id = "x"\n\n[delegation]\nmaster = "codex"\n\n[delegation.models]\ncodex = "m"\n\n'
            '# the run limits\n[run]\nwall = 1\n')
    out = dg.replace_table(text, block)
    assert out == '[steward]\nrepo_id = "x"\n\n' + block + "\n# the run limits\n[run]\nwall = 1\n"
    assert dg.replace_table('[steward]\nrepo_id = "x"', block) == '[steward]\nrepo_id = "x"\n\n' + block
    assert dg.replace_table(out, block) == out


# ---------------------------------------------------------------- steward agents setup
def test_D01_setup_with_codex_and_agy_in_its_install_folder(proj, cli, no_network):
    """The acceptance case: codex on PATH and agy only in ~/.gemini/bin; no model is called, no network is used."""
    logs = install("claude codex agy")
    before = toml(proj)
    code, out, err = cli("agents", "setup", "--yes")
    assert code == 0, err
    assert "codex-cli" not in out and "0.125.0 · signed out · PATH" in out and "1.5.18 · sign-in not known · known folder" in out
    expected = ('[delegation]\nmaster = "claude-code"\nworkers = ["codex", "antigravity"]\non_limit = "next"\n\n'
                '[delegation.models]\nantigravity = "gemini-4-neon-high"\n')
    assert toml(proj) == before + "\n" + expected
    assert "+workers = [\"codex\", \"antigravity\"]" in out and "wrote [delegation]" in out
    made = calls(logs)
    assert made and all(c.split(" ", 1)[1] in ("--version", "--help", "auth status", "login status") for c in made), made
    # agy has no status subcommand: it was never asked one
    assert [c for c in made if c.startswith("agy")] == ["agy --version"]
    code, out, _ = cli("agents", "setup", "--yes")
    assert code == 0 and "[delegation] is up to date" in out
    entries = [json.loads(line) for line in (proj / ".steward/agents/availability.jsonl").read_text().splitlines()]
    observed = [e for e in entries if e["kind"] == "observed"]
    assert [(e["agent"], e["state"]) for e in observed[:3]] == [
        ("claude-code", "available"), ("codex", "signed_out"), ("antigravity", "available")]


def test_D01_setup_without_claude_takes_the_first_installed_agent_as_master(proj, cli):
    install("codex agy")
    code, out, _ = cli("agents", "setup", "--yes")
    assert code == 0 and 'master = "codex"' in toml(proj) and 'workers = ["antigravity"]' in toml(proj)
    code, out, _ = cli("agents", "setup", "--yes", "--master", "claude-code")
    # the configured workers keep their order; the former master joins after them
    assert code == 0 and 'master = "claude-code"' in toml(proj) and 'workers = ["antigravity", "codex"]' in toml(proj)
    assert toml(proj).count("[delegation]") == 1


def test_D01_setup_asks_before_writing(proj, cli, monkeypatch):
    install("codex")
    before = toml(proj)
    code, out, _ = cli("agents", "setup")  # not a terminal, no --yes: the diff only
    assert code == 0 and "+[delegation]" in out and "not written" in out and toml(proj) == before
    assert not (proj / ".steward/agents/availability.jsonl").exists()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    code, out, _ = cli("agents", "setup")
    assert code == 0 and "not written" in out and toml(proj) == before
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    code, out, _ = cli("agents", "setup")
    assert code == 0 and "wrote [delegation]" in out and 'master = "codex"' in toml(proj)


def test_D01_setup_with_no_agent_writes_nothing(proj, cli):
    before = toml(proj)
    code, out, _ = cli("agents", "setup", "--yes")
    assert code == 0 and "no agent CLI is installed" in out and toml(proj) == before


def test_D01_setup_keeps_the_configured_order_and_models(proj, cli):
    install("claude codex agy")
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[delegation]\nmaster = "claude-code"\nworkers = ["antigravity", "codex"]\non_limit = "wait"\n'
                '\n[delegation.models]\nantigravity = "a-model"\n')
    code, out, _ = cli("agents", "setup", "--yes")
    assert code == 0 and "[delegation] is up to date" in out, out


# ---------------------------------------------------------------- the ledger and steward agents status
def test_D01_status_from_the_ledger(proj, cli):
    from steward import delegation as dg
    from steward.models import load_config

    install("claude codex")
    cli("agents", "setup", "--yes")
    rid = load_config(proj).steward.repo_id
    e = dg.read_ending("codex", FIXTURES / "codex-limit-in.jsonl", NOW, UTC)
    dg.record_ending(proj, rid, e, ".steward/sprints/s/T.log")
    dg.record_ending(proj, rid, dg.ending("claude-code", "Invalid API key · Please run /login"), "dispatch")

    def status(now):
        code, out, err = cli("agents", "status", "--format", "json", "--now", now)
        assert code == 0, err
        return {a["agent"]: a for a in _valid(json.loads(out))["agents"]}

    s = status("2026-11-18T16:00:00Z")
    assert (s["codex"]["state"], s["codex"]["until"], s["codex"]["reset_known"]) == ("limited", "2026-11-20T18:04:00Z", True)
    assert s["claude-code"]["state"] == "signed_out" and s["claude-code"]["role"] == "master"
    assert s["antigravity"]["state"] == "missing" and s["antigravity"]["role"] == "unassigned"
    assert s["codex"]["version"] == "0.125.0" and s["codex"]["last"]["source"] == ".steward/sprints/s/T.log"
    assert list(s) == ["claude-code", "codex", "antigravity"]
    assert status("2026-11-21T00:00:00Z")["codex"]["state"] == "available"  # the reset time has passed
    code, out, _ = cli("agents", "status", "--now", "2026-11-18T16:00:00Z")
    assert code == 0 and "master claude-code · workers codex" in out
    assert "limited until 2026-11-20T18:04:00Z" in out and "signed out" in out and "missing" in out
    cli("agents", "setup", "--yes")  # a new observation: claude is signed in again
    assert status("2026-11-18T16:00:00Z")["claude-code"]["state"] == "available"


def test_D01_a_limit_without_a_reset_time_counts_for_an_hour(proj, cli, monkeypatch):
    from steward import delegation as dg
    from steward import ledger

    install("codex")
    monkeypatch.setattr(ledger, "_now", lambda: "2026-11-18T15:00:00Z")
    dg.record_ending(proj, "x", dg.Ending("codex", "limited", None, "usage_limit_reached"), "dispatch")
    code, out, _ = cli("agents", "status", "--format", "json", "--now", "2026-11-18T15:30:00Z")
    a = {x["agent"]: x for x in json.loads(out)["agents"]}["codex"]
    assert (a["state"], a["until"], a["reset_known"]) == ("limited", "2026-11-18T16:00:00Z", False)
    code, out, _ = cli("agents", "status", "--format", "json", "--now", "2026-11-18T16:30:00Z")
    assert {x["agent"]: x for x in json.loads(out)["agents"]}["codex"]["state"] == "available"


def test_D01_status_refuses_an_edited_ledger_and_a_bad_time(proj, cli):
    from steward import delegation as dg

    dg.record_ending(proj, "x", dg.Ending("codex", "signed_out", None, "Not logged in"), "dispatch")
    assert cli("agents", "status", "--now", "soon")[0] == 64
    p = proj / dg.LEDGER
    p.write_text(p.read_text().replace("Not logged in", "Logged in"))
    code, out, err = cli("agents", "status")
    assert code == 65 and not out and "edited" in err


def test_D01_status_without_delegation(proj, cli):
    code, out, _ = cli("agents", "status", "--format", "json")
    doc = _valid(json.loads(out))
    assert code == 0 and doc["configured"] is False and doc["master"] is None
    assert [a["state"] for a in doc["agents"]] == ["missing"] * 3


# ---------------------------------------------------------------- R-89 and the init offer
def test_D01_R89_names_a_configured_agent_that_is_not_installed(proj, cli):
    code, rep = cli.check(proj, "agents")
    assert one(rep, "R-89")["status"] == "NOT_APPLICABLE"
    install("claude codex")
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[delegation]\nmaster = "claude-code"\nworkers = ["codex", "antigravity"]\n')
    code, rep = cli.check(proj, "agents")
    r = one(rep, "R-89")
    assert r["status"] == "INCOMPLETE" and codes(r) == {"R-89.missing"} and "antigravity (worker)" in r["reason"]
    from steward.models import ADVISORY

    assert "R-89" in ADVISORY and r["area"] == "agents"  # advisory: the default gate does not require it
    assert "R-89" not in [b["rule"] for g in rep["verdict"]["gates"] if g["name"] == "default" for b in g["blocking"]]
    install("agy")
    code, rep = cli.check(proj, "agents")
    assert one(rep, "R-89")["status"] == "PASS"


def test_D01_init_offers_setup(cli, tmp_path):
    r = tmp_path / "q"
    r.mkdir()
    code, out, _ = cli("init", "--repo", r)
    assert code == 0 and "steward agents setup" not in out  # no agent installed: nothing to offer
    install("codex")
    r2 = tmp_path / "q2"
    r2.mkdir()
    code, out, _ = cli("init", "--repo", r2)
    assert code == 0 and "Delegation: `steward agents setup`" in out and "[delegation]" not in toml(r2)


# ---------------------------------------------------------------- goldens on both worked examples
def test_D01_agents_status_goldens(cli, machine_example, monkeypatch):  # noqa: F811
    from steward import delegation as dg
    from steward.models import load_config

    name, root = machine_example
    install("codex agy")
    assert cli("agents", "setup", "--yes", "--master", "claude-code", "--repo", root)[0] == 0
    e = dg.read_ending("codex", FIXTURES / "codex-limit-at.jsonl", dt.datetime(2026, 11, 27, 12, 0, tzinfo=UTC), UTC)
    dg.record_ending(root, load_config(root).steward.repo_id, e, ".steward/sprints/example/T1.log")
    code, out, err = cli("agents", "status", "--repo", root, "--format", "json", "--now", "2026-11-27T13:00:00Z")
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    path = GOLDEN / f"{name}.agents-status.json"
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.write_text(out, encoding="utf-8", newline="\n")
    assert out == path.read_text(encoding="utf-8") == _golden_bytes(doc), f"output differs from {path}"
    code, interface, _ = cli("interface", "--format", "json")
    assert json.loads(interface)["commands"]["agents status"]["schema"] == doc["schema"] == "steward.agents_status/0.1"
