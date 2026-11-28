"""0.23.0 D02 (delegation): `agent = "auto"`, re-delegation when a worker cannot run, `on_limit`, the master's review
step (`sprint accept`, `sprint rework`), `task dispatch --to auto`, the agents ledger's attempts and their tokens.

The agents are stand-ins: one small Python script installed as `claude`, `codex` and `agy` on a PATH of the test's
own, with a HOME of its own, so no real agent CLI is found or run. Each one does what its environment variable says
(`STANDIN_CLAUDE`, `STANDIN_CODEX`, `STANDIN_AGY`): `work` (the default) writes a file and commits it (Codex leaves
the commit to the sprint, as its sandbox would), `limit` prints that agent's usage-limit message and exits 1, `fail`
exits 1 with an ordinary error. Every call is written to calls.jsonl.
"""

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys

import pytest

from steward import delegation as dg
from steward import sprint as sp

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
UTC = dt.timezone.utc

STANDIN = r'''
import json, os, pathlib, subprocess, sys
exe = os.path.basename(sys.argv[0])
mode = os.environ.get("STANDIN_" + exe.upper(), "work")
args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else args[-1]
with open(os.environ["STANDIN_LOG"], "a") as f:
    f.write(json.dumps({"exe": exe, "cwd": os.getcwd(), "prompt": prompt, "mode": mode}) + "\n")
if mode == "limit":
    if exe == "agy":  # some work first, committed, then the limit
        pathlib.Path("agy.txt").write_text("partial\n")
        subprocess.run(["git", "add", "agy.txt"], check=True)
        subprocess.run(["git", "commit", "-qm", "partial work by agy"], check=True)
        print("You have exhausted your capacity on this model. Your quota will reset after 1h30m0s.", flush=True)
    elif exe == "codex":
        print(json.dumps({"type": "error", "message": "You've hit your usage limit. Visit the usage page to "
                          "purchase more credits or try again in 2 hours."}), flush=True)
    else:
        print(json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached"}), flush=True)
    sys.exit(1)
if mode == "fail":
    print("Traceback: something in the task went wrong", flush=True)
    sys.exit(1)
pathlib.Path(exe + ".txt").write_text("done by " + exe + "\n")
rec = pathlib.Path("development/tasks/T1-record.md")
rec.parent.mkdir(parents=True, exist_ok=True)
rec.write_text("# Task record\n\n## What changed\nA file.\n\n## Deviations and open points\n"
               "1. The stand-in wrote " + exe + ".txt instead of the file the task named.\n\n## Signature\nnone\n")
if exe != "codex":
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "work by " + exe], check=True)
print(json.dumps({"type": "result", "result": "finished"}), flush=True)
'''


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    real = socket.socket.connect

    def guard(self, address, *a, **k):
        if isinstance(address, tuple):
            pytest.fail(f"network access to {address}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config"))
    for k, v in (("GIT_AUTHOR_NAME", "T"), ("GIT_AUTHOR_EMAIL", "t@example.org"),
                 ("GIT_COMMITTER_NAME", "T"), ("GIT_COMMITTER_EMAIL", "t@example.org")):
        monkeypatch.setenv(k, v)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setenv("STANDIN_LOG", str(tmp_path / "calls.jsonl"))


def install(tmp_path, *exes):
    for exe in exes:
        f = tmp_path / "bin" / exe
        f.write_text(f"#!{sys.executable}\n{STANDIN}")
        f.chmod(0o755)


def calls(tmp_path):
    p = tmp_path / "calls.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


DELEGATION = '\n[delegation]\nmaster = "claude-code"\nworkers = {workers}\non_limit = "{on_limit}"\n'


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    r = tmp_path / "r"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


def delegate(repo, workers=("antigravity", "codex"), on_limit="next"):
    p = repo / "steward.toml"
    p.write_text(p.read_text() + DELEGATION.format(workers=json.dumps(list(workers)), on_limit=on_limit))


def _iso(hours):
    return (dt.datetime.now(UTC) + dt.timedelta(hours=hours)).replace(microsecond=0).isoformat()


def write_sprint(repo, tasks, dispatch="auto"):
    (repo / "development/sprints").mkdir(parents=True, exist_ok=True)
    (repo / "development/sprints/day1.toml").write_text(
        f'schema = "steward.sprint/0.1"\n[sprint]\nid = "day1"\n'
        f"window = {{ start = {_iso(-1)}, end = {_iso(8)} }}\ndispatch = \"{dispatch}\"\n{tasks}")


def agent_task(tid, agent="auto", done='["test -f agy.txt -o -f codex.txt -o -f claude.txt"]', extra=""):
    return (f'\n[[task]]\nid = "{tid}"\ntitle = "task {tid}"\nagent = "{agent}"\nprompt = "Do it."\n'
            f'permissions = "edit-and-run"\nlimits = {{ wall_minutes = 5 }}\ndone = {done}\n{extra}\n')


def status(cli):
    code, out, err = cli("sprint", "status", "day1", "--format", "json")  # validated against its schema
    assert code == 0, err
    return {t["id"]: t for t in json.loads(out)["tasks"]}


def events(repo, tid=None):
    evs = [json.loads(ln) for ln in (repo / "development/sprints/day1.jsonl").read_text().splitlines()]
    return [e for e in evs if tid is None or e.get("task") == tid]


def kinds(repo, tid):
    return [e["state"] for e in events(repo, tid) if e.get("kind") == "state"]


def ledger_ok(repo):
    sf = sp.load(repo, "day1")
    assert sp.ledger_findings(sf, sp.events(repo, "day1")) == []


def limited(repo, agent, reset):
    """A limit the availability ledger already holds (as a run's ending would have written it)."""
    dg.record_ending(repo, "x", dg.Ending(agent, "limited", reset, "You've hit your usage limit"), "test")


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- re-delegation (STW-061 acceptance 1)
def test_D02_a_limited_worker_is_redelegated_on_the_same_branch_and_skipped_until_its_reset(cli, repo, tmp_path,
                                                                                            monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    monkeypatch.setenv("STANDIN_AGY", "limit")
    write_sprint(repo, agent_task("T1", done='["test -f agy.txt", "test -f codex.txt"]'))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert "T1: redelegated (antigravity cannot run: usage limit, resets " in out
    assert kinds(repo, "T1") == ["running", "redelegated", "running", "checking", "review"]
    first, red, second = (e for e in events(repo, "T1") if e.get("state") in ("running", "redelegated"))
    assert (first["agent"], first["role"], second["agent"], second["role"]) == ("antigravity", "worker", "codex",
                                                                                "worker")
    assert red["agent"] == "antigravity" and red["reason"] == "limited" and red["reset"]
    assert first["branch"] == second["branch"] == "sprint/day1/T1"
    subjects = sh(repo, "git", "log", "--format=%s", "main..sprint/day1/T1").splitlines()
    assert subjects[-1] == "partial work by agy" and "written by Codex" in subjects[0]  # the first commit stays
    ledger_ok(repo)
    # the availability ledger: antigravity limited until its reset
    _, raw, _ = cli("agents", "status", "--format", "json")
    agy = next(a for a in json.loads(raw)["agents"] if a["agent"] == "antigravity")
    assert agy["state"] == "limited" and agy["until"] == red["reset"]
    row = [json.loads(ln) for ln in (repo / dg.LEDGER).read_text().splitlines()][-1]
    assert (row["kind"], row["agent"], row["state"], row["redelegated"], row["task"]) == (
        "ending", "antigravity", "limited", True, "day1/T1")
    # the agents ledger: both attempts, with agent, model and outcome
    rows = [json.loads(ln) for ln in (repo / "development/agents.jsonl").read_text().splitlines()]
    att = [r for r in rows if r.get("kind") == "attempt"]
    assert [(a["task"], a["attempt"], a["agent"], a["model"], a["status"]) for a in att] == [
        ("day1/T1", 1, "antigravity", "unknown", "redelegated"), ("day1/T1", 2, "codex", "unknown", "review")]
    assert att[0]["reason"] == "limited" and att[0]["provider"] == "google"
    # sprint status shows each attempt, newest first
    s = status(cli)["T1"]
    assert s["state"] == "review" and s["agent"] == "auto"
    assert [(a["agent"], a["outcome"]) for a in s["delegation"]["attempts"]] == [("codex", "review"),
                                                                                ("antigravity", "redelegated")]
    # a second auto task: antigravity is skipped until its reset time, codex takes it at once
    monkeypatch.delenv("STANDIN_AGY")
    write_sprint(repo, agent_task("T1", done='["test -f agy.txt", "test -f codex.txt"]')
                 + agent_task("T2", done='["test -f codex.txt"]'))
    cli("sprint", "add", "day1", "T2")
    n = len(calls(tmp_path))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert [c["exe"] for c in calls(tmp_path)[n:]] == ["codex"]
    assert kinds(repo, "T2") == ["running", "checking", "review"]


def test_D02_a_task_failure_is_not_redelegated(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    monkeypatch.setenv("STANDIN_AGY", "fail")
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert kinds(repo, "T1") == ["running", "failed"]
    assert [c["exe"] for c in calls(tmp_path)] == ["agy"]
    assert not (repo / dg.LEDGER).exists() or "ending" not in (repo / dg.LEDGER).read_text()


# ---------------------------------------------------------------- on_limit (STW-061 acceptance 2)
def test_D02_every_worker_limited_and_on_limit_next_the_master_runs_it_and_it_ends_done(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    later = iso(dt.datetime.now(UTC) + dt.timedelta(hours=3))
    limited(repo, "antigravity", later)
    limited(repo, "codex", later)
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert [c["exe"] for c in calls(tmp_path)] == ["claude"]
    assert kinds(repo, "T1") == ["running", "checking", "done"]  # the master's task: done, as before
    running = next(e for e in events(repo, "T1") if e.get("state") == "running")
    assert running["agent"] == "claude-code" and running["role"] == "master"
    assert not (repo / sp.review_rel("day1", "T1")).exists()


def test_D02_on_limit_master_hands_it_to_the_master_as_soon_as_a_worker_cannot_run(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, on_limit="master")
    monkeypatch.setenv("STANDIN_AGY", "limit")
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert [c["exe"] for c in calls(tmp_path)] == ["agy", "claude"]  # codex, the next worker, is not asked
    assert kinds(repo, "T1") == ["running", "redelegated", "running", "checking", "done"]
    ledger_ok(repo)


def test_D02_on_limit_wait_shows_until_when_in_sprint_status_and_next(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, on_limit="wait")
    soon, later = (iso(dt.datetime.now(UTC) + dt.timedelta(hours=h)) for h in (10, 12))  # after the window ends
    limited(repo, "antigravity", later)
    limited(repo, "codex", soon)
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert f"T1: waiting until {soon}" in out
    assert calls(tmp_path) == []
    s = status(cli)["T1"]
    assert s["state"] == "waiting" and s["delegation"]["until"] == soon
    _, text, _ = cli("sprint", "status", "day1")
    assert "waiting" in text and soon in text
    _, raw, _ = cli("next", "--format", "json")  # validated against its schema
    entry = next(e for e in json.loads(raw)["waiting_on_agents"] if e["id"] == "day1/T1")
    assert entry["kind"] == "task_limited" and soon in entry["title"]
    ledger_ok(repo)


def test_D02_on_limit_wait_starts_the_task_once_the_reset_time_passes(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex",), on_limit="wait")
    reset = dt.datetime.now(UTC).replace(microsecond=0) + dt.timedelta(seconds=3)
    limited(repo, "codex", iso(reset))
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert dt.datetime.now(UTC) >= reset
    assert kinds(repo, "T1") == ["waiting", "running", "checking", "review"]
    assert [c["exe"] for c in calls(tmp_path)] == ["codex"]
    ledger_ok(repo)


# ---------------------------------------------------------------- the master's review (STW-061 acceptance 3)
def test_D02_a_workers_passing_task_ends_in_review_with_a_brief_and_accept_marks_it_done(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex",))
    write_sprint(repo, agent_task("T1", done='["test -f codex.txt", "echo checked-output-line"]'))
    main_before = sh(repo, "git", "rev-parse", "main")
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    s = status(cli)["T1"]
    assert s["state"] == "review" and s["delegation"]["review"] == sp.review_rel("day1", "T1")
    brief = (repo / sp.review_rel("day1", "T1")).read_text()
    assert "codex.txt" in brief and "## Diff summary" in brief  # the diff summary
    assert "`echo checked-output-line`: exit 0" in brief and "checked-output-line" in brief.split("## Checks")[1]
    assert "The stand-in wrote codex.txt instead" in brief  # the task record's deviations
    assert "steward sprint accept day1 T1" in brief
    assert '"output"' not in json.dumps(events(repo, "T1"))  # check output stays out of the ledger
    _, raw, _ = cli("next", "--format", "json")
    entry = next(e for e in json.loads(raw)["waiting_on_human"] if e["id"] == "day1/T1")
    assert entry["kind"] == "task_review" and entry["command"] == "steward sprint accept day1 T1"
    code, out, err = cli("sprint", "accept", "day1", "T1")
    assert code == 0, err
    assert "done (accepted by the master)" in out
    assert status(cli)["T1"]["state"] == "done"
    assert sh(repo, "git", "rev-parse", "main") == main_before  # nothing merges by itself
    code, _, err = cli("sprint", "accept", "day1", "T1")
    assert code == 64 and "accept is for a task in review" in err
    ledger_ok(repo)


def test_D02_rework_sends_it_back_to_the_same_worker_with_the_note(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex",))
    write_sprint(repo, agent_task("T1", done='["test -f codex.txt"]'))
    assert cli("sprint", "start", "day1")[0] == 0
    code, out, err = cli("sprint", "rework", "day1", "T1", "--note", "Name the file in the record.")
    assert code == 0, err
    assert status(cli)["T1"]["state"] == "rework"
    assert cli("sprint", "start", "day1")[0] == 0
    again = calls(tmp_path)[-1]
    assert again["exe"] == "codex" and "Name the file in the record." in again["prompt"]
    assert kinds(repo, "T1") == ["running", "checking", "review", "rework", "running", "checking", "review"]
    code, out, err = cli("sprint", "rework", "day1", "T1", "--note", "Do it yourself.", "--to", "master")
    assert code == 0, err
    assert cli("sprint", "start", "day1")[0] == 0
    assert calls(tmp_path)[-1]["exe"] == "claude"
    assert kinds(repo, "T1")[-3:] == ["running", "checking", "done"]  # the master's attempt ends in done
    ledger_ok(repo)


def test_D02_a_review_left_without_the_master_is_a_bad_transition():
    window = {"start": dt.datetime(2026, 11, 27, tzinfo=UTC), "end": dt.datetime(2026, 11, 28, tzinfo=UTC)}
    sf = sp.SprintFile.model_validate({"schema": "steward.sprint/0.1", "sprint": {"id": "s", "window": window},
        "task": [{"id": "T1", "title": "t", "agent": "auto", "prompt": "p", "done": ["true"]}]})
    evs = [{"kind": "opened", "sprint": "s", "tasks": ["T1"]}] + [
        {"kind": "state", "task": "T1", "state": s} for s in ("running", "checking", "review")]
    assert sp.ledger_findings(sf, evs + [{"kind": "state", "task": "T1", "state": "done", "by": "master"}]) == []
    bad = sp.ledger_findings(sf, evs + [{"kind": "state", "task": "T1", "state": "done"}])
    assert [f["code"] for f in bad] == ["R-71.bad_transition"]


# ---------------------------------------------------------------- named agents, no [delegation], sprint check
def test_D02_a_task_that_names_its_agent_keeps_it(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    write_sprint(repo, agent_task("T1", "codex", done='["test -f codex.txt"]'))
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "checking", "done"]  # no [delegation]: done, as before
    running = next(e for e in events(repo, "T1") if e.get("state") == "running")
    assert "role" not in running and "delegation" not in status(cli)["T1"]
    assert not (repo / "development/agents.jsonl").exists()


def test_D02_without_delegation_an_auto_task_fails_and_check_says_why(cli, repo, tmp_path):
    write_sprint(repo, agent_task("T1"))
    code, out, err = cli("sprint", "check", "day1")
    assert code == 0 and "warning: T1 cannot start: there is no [delegation]" in out
    assert cli("sprint", "start", "day1")[0] == 0
    s = status(cli)["T1"]
    assert s["state"] == "failed" and "needs [delegation]" in s["note"]


def test_D02_sprint_check_prints_the_order_it_will_try(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex")  # no agy
    delegate(repo)
    limited(repo, "codex", iso(dt.datetime.now(UTC) + dt.timedelta(hours=2)))
    write_sprint(repo, agent_task("T1", extra='model = "x"'))
    code, out, err = cli("sprint", "check", "day1")
    assert code == 0, err
    assert "delegation: T1: tries antigravity, codex; then the master claude-code (on_limit = next)" in out
    assert "delegation: now antigravity missing; codex limited until " in out and "claude-code available (master)" in out
    assert "permissions: T1: auto, edit-and-run" in out
    assert "warning: T1 is auto: its model comes from [delegation.models]" in out


def test_D02_choose_follows_the_order_requirements_and_on_limit(repo, tmp_path):
    from steward.models import load_config

    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    cfg = load_config(repo)
    now = dt.datetime.now(UTC)
    c = dg.choose(repo, cfg, [], now)
    assert (c.agent, c.role) == ("antigravity", "worker")
    c = dg.choose(repo, cfg, ["network"], now)  # Antigravity's sandbox offers no network
    assert c.agent == "codex" and "antigravity cannot offer network" in c.why
    c = dg.choose(repo, cfg, ["display"], now)
    assert (c.agent, c.role) == ("claude-code", "master")
    c = dg.choose(repo, cfg, [], now, tried=["antigravity", "codex"])
    assert c.agent == "claude-code"
    c = dg.choose(repo, cfg, [], now, tried=["antigravity", "codex", "claude-code"])
    assert c.agent is None and c.until is None and "no agent can run" in c.why
    c = dg.choose(repo, cfg, [], now, prefer="codex")
    assert c.agent == "codex"


def test_D02_the_running_task_keeps_the_definition_it_started_with(cli, repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex",))
    write_sprint(repo, agent_task("T1", done='["test -f codex.txt"]'))
    assert cli("sprint", "start", "day1")[0] == 0
    running = next(e for e in events(repo, "T1") if e.get("state") == "running")
    t = next(x for x in sp.load(repo, "day1").task if x.id == "T1")
    assert running["task_sha256"] == sp.task_sha(t)  # the file's definition (agent = "auto"), not the resolved one
    assert t.agent == "auto" and running["agent"] == "codex"


# ---------------------------------------------------------------- task dispatch --to auto
TASK = """# Task: review of the change

- **ID:** T-007
- **Status:** proposed
- **GO reference:** the owner's decision of today
- **Owner:** the owner · **Approver:** the owner

## Goal
Review the change.

## Scope
- In: the file `README.md`.

## Acceptance criteria
- [ ] A report.
"""


def test_D02_task_dispatch_to_auto_takes_the_next_worker_after_a_limit(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "codex", "agy")
    delegate(repo, workers=("codex", "antigravity"))
    (repo / "T-007.md").write_text(TASK)
    monkeypatch.setenv("STANDIN_CODEX", "limit")
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "auto")
    assert code == 0, err
    assert "delegation: codex takes it" in out and "redelegated: codex cannot run (limited, resets " in out
    assert "delegation: antigravity takes it" in out
    assert [c["exe"] for c in calls(tmp_path)] == ["codex", "agy"]
    _, raw, _ = cli("agents", "status", "--format", "json")
    assert next(a for a in json.loads(raw)["agents"] if a["agent"] == "codex")["state"] == "limited"
    # codex is now skipped until its reset; with antigravity limited too, the master is named and it exits 75
    monkeypatch.setenv("STANDIN_AGY", "limit")
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "auto")
    assert code == 75 and "the master claude-code does it itself" in err
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "auto")
    assert code == 75 and calls(tmp_path)[-1]["exe"] == "agy" and len(calls(tmp_path)) == 3


def test_D02_task_dispatch_to_auto_needs_delegation(cli, repo, tmp_path):
    (repo / "T-007.md").write_text(TASK)
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "auto")
    assert code == 64 and "needs [delegation]" in err


# ---------------------------------------------------------------- tokens per worker and attempt
def test_D02_tokens_report_shows_each_workers_attempts(cli, repo, tmp_path, monkeypatch, capsys):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex", "antigravity"))
    monkeypatch.setenv("STANDIN_CODEX", "limit")
    write_sprint(repo, agent_task("T1", done='["test -f agy.txt"]'))
    assert cli("sprint", "start", "day1")[0] == 0
    att = [json.loads(ln) for ln in (repo / "development/agents.jsonl").read_text().splitlines()]
    att = [a for a in att if a.get("kind") == "attempt"]
    start, end = (dt.datetime.fromisoformat(att[0][k]) for k in ("started", "ended"))
    at = (start + (end - start) / 2).isoformat()  # inside codex's (the first) attempt
    usage = {"input_tokens": 40, "cached_input_tokens": 0, "output_tokens": 2, "reasoning_output_tokens": 0,
             "total_tokens": 42}
    log = tmp_path / "codex.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [
        {"type": "session_meta", "payload": {"id": "session-codex"}},
        {"type": "turn_context", "payload": {"model": "codex-test"}},
        {"type": "event_msg", "timestamp": at, "payload": {"type": "token_count", "info": {
            "last_token_usage": usage, "total_token_usage": usage}}}]))
    code, out, err = cli("tokens", "report", "--codex", str(log), "--format", "json")  # validated by its schema
    assert code == 0, err
    row = next(r for r in json.loads(out)["tasks"] if r["task"] == "day1/T1")
    assert [(a["attempt"], a["agent"], a["outcome"], a["reason"], a["tokens"]) for a in row["attempts"]] == [
        (2, "antigravity", "review", None, None), (1, "codex", "redelegated", "limited", 42)]
    assert not any(r["task"] == "sprint day1 T1" for r in json.loads(out)["tasks"])  # not counted twice
    code, text, err = cli("tokens", "report", "--codex", str(log))
    assert code == 0, err
    assert "attempt 1  codex / unknown model  redelegated (limited)  42 tokens" in text
