"""0.23.0 D02b (delegation): with [delegation], a task that names a worker (agent = "codex" or "antigravity") and ends
in "cannot run" is re-delegated as an auto task is; the Codex commit step also commits a run stopped by a limit.

The stand-in agents are those of the D02 tests, with two more modes: `partial-limit` writes a file and then ends as
`limit` does, and `partial-fail` writes a file and then fails as `fail` does.
"""

import datetime as dt
import json

from steward import sprint as sp
from test_v0230_redelegation import (  # noqa: F401 - the fixtures are used by name
    STANDIN, UTC, _hermetic, agent_task, calls, delegate, events, iso, kinds, ledger_ok, limited, repo, sh, status,
    write_sprint,
)

PARTIAL = '''if mode in ("partial-limit", "partial-fail"):
    pathlib.Path(exe + "-partial.txt").write_text("partial\\n")
    mode = mode.split("-")[1]
if mode == "limit":'''
STANDIN_B = STANDIN.replace('if mode == "limit":', PARTIAL, 1)
assert STANDIN_B != STANDIN


def install(tmp_path, *exes):
    import sys

    for exe in exes:
        f = tmp_path / "bin" / exe
        f.write_text(f"#!{sys.executable}\n{STANDIN_B}")
        f.chmod(0o755)


def subjects(repo, branch="sprint/day1/T1"):
    return sh(repo, "git", "log", "--format=%s", f"main..{branch}").splitlines()


def files_in(repo, ref):
    return sh(repo, "git", "show", "--name-only", "--format=", ref).splitlines()


# ---------------------------------------------------------------- item 1: a named worker that cannot run moves
def test_D02b_a_named_codex_that_is_limited_moves_to_the_next_worker_with_its_partial_work(cli, repo, tmp_path,
                                                                                         monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex", "antigravity"))
    monkeypatch.setenv("STANDIN_CODEX", "partial-limit")
    write_sprint(repo, agent_task("T1", "codex", done='["test -f agy.txt", "test -f codex-partial.txt"]',
                                  extra='model = "codex-model-x"'))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    assert "T1: redelegated (codex cannot run: usage limit, resets " in out
    assert "; moved from the named agent codex)" in out
    assert kinds(repo, "T1") == ["running", "redelegated", "running", "checking", "review"]
    first, red, second = (e for e in events(repo, "T1") if e.get("state") in ("running", "redelegated"))
    assert (first["agent"], first["model"], "moved_from" in first) == ("codex", "codex-model-x", False)
    assert red["agent"] == "codex" and red["reason"] == "limited" and red["moved_from"] == "codex"
    assert "the task names codex and moves from it" in red["note"] and "partial work is committed" in red["note"]
    # the next worker of [delegation] workers takes it, with its own model (none here), on the same branch
    assert (second["agent"], second["model"], second["moved_from"], second["role"]) == (
        "antigravity", None, "codex", "worker")
    assert first["branch"] == second["branch"] == "sprint/day1/T1"
    assert [c["exe"] for c in calls(tmp_path)] == ["codex", "agy"]
    # item 2: Codex's partial work is committed, below the next agent's commit, with a message that says why
    subj = subjects(repo)
    assert subj[0] == "work by agy"
    assert subj[-1].startswith("task T1 (sprint day1, T1; written by Codex, committed by the sprint task; the run "
                               "was stopped by a limit (usage limit, resets ")
    assert subj[-1].endswith("); partial work)")
    assert red["commit"] == sh(repo, "git", "rev-parse", "sprint/day1/T1~1")
    assert "codex-partial.txt" in files_in(repo, red["commit"])
    ledger_ok(repo)
    # the agents ledger and sprint status show both attempts, newest first
    att = [json.loads(ln) for ln in (repo / "development/agents.jsonl").read_text().splitlines()]
    assert [(a["agent"], a["status"]) for a in att if a.get("kind") == "attempt"] == [
        ("codex", "redelegated"), ("antigravity", "review")]
    s = status(cli)["T1"]
    assert s["agent"] == "codex" and s["delegation"]["agent"] == "antigravity"
    assert [(a["agent"], a["outcome"]) for a in s["delegation"]["attempts"]] == [
        ("antigravity", "review"), ("codex", "redelegated")]
    # the watch and report lines say where it moved from
    lines: list[str] = []
    sp.watch(repo, "day1", out=lines.append, once=True)
    out = "\n".join(lines)
    assert "redelegated: codex cannot run (limited, resets " in out and "; moved from the named agent codex" in out
    code, out, err = cli("sprint", "report", "day1")
    assert code == 0, err
    assert "| T1 | codex (antigravity) | review |" in out


def test_D02b_a_named_worker_with_every_worker_limited_goes_to_the_master(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("antigravity", "codex"))
    limited(repo, "codex", iso(dt.datetime.now(UTC) + dt.timedelta(hours=3)))
    monkeypatch.setenv("STANDIN_AGY", "limit")
    write_sprint(repo, agent_task("T1", "antigravity"))
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "redelegated", "running", "checking", "done"]
    ran = [e for e in events(repo, "T1") if e.get("state") == "running"]
    assert [(e["agent"], e.get("role"), e.get("moved_from")) for e in ran] == [
        ("antigravity", "worker", None), ("claude-code", "master", "antigravity")]
    assert [c["exe"] for c in calls(tmp_path)] == ["agy", "claude"]  # the limited codex is skipped
    ledger_ok(repo)


def test_D02b_a_named_worker_waits_with_on_limit_wait(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex",), on_limit="wait")
    monkeypatch.setenv("STANDIN_CODEX", "limit")
    write_sprint(repo, agent_task("T1", "codex"))
    f = repo / "development/sprints/day1.toml"  # the window ends before Codex's reset (2 hours), so nobody sleeps
    end = (dt.datetime.now(UTC) + dt.timedelta(hours=1)).replace(microsecond=0).isoformat()
    f.write_text("\n".join(ln if not ln.startswith("window = ") else ln[: ln.index("end = ") + 6] + end + " }"
                           for ln in f.read_text().splitlines()) + "\n")
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "redelegated", "waiting"]
    s = status(cli)["T1"]
    assert s["state"] == "waiting" and s["delegation"]["until"]


# ---------------------------------------------------------------- what stays as it was
def test_D02b_without_delegation_a_named_codex_that_is_limited_fails_and_keeps_its_partial_work(cli, repo, tmp_path,
                                                                                              monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    monkeypatch.setenv("STANDIN_CODEX", "partial-limit")
    write_sprint(repo, agent_task("T1", "codex"))
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "failed"]  # no [delegation]: it fails, as before
    failed = events(repo, "T1")[-1]
    assert "moved_from" not in failed and "codex cannot run (usage limit" in failed["note"]
    assert "Codex's partial work is committed" in failed["note"]
    assert [c["exe"] for c in calls(tmp_path)] == ["codex"]
    subj = subjects(repo)
    assert len(subj) == 1 and "the run was stopped by a limit" in subj[0]
    assert failed["commit"] == sh(repo, "git", "rev-parse", "sprint/day1/T1")
    assert not (repo / "development/agents.jsonl").exists()
    ledger_ok(repo)


def test_D02b_a_codex_run_that_fails_otherwise_is_not_committed(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    monkeypatch.setenv("STANDIN_CODEX", "partial-fail")
    write_sprint(repo, agent_task("T1", "codex"))
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "failed"]  # a task failure is not re-delegated
    failed = events(repo, "T1")[-1]
    assert "commit" not in failed and "partial work" not in failed["note"]
    assert subjects(repo) == []
    wt = repo / failed["branch"].replace("sprint/", ".steward/sprints/", 1)
    wt = wt if wt.is_dir() else next(p for p in (repo / ".steward/sprints").rglob("T1") if p.is_dir())
    assert "codex-partial.txt" in sh(wt, "git", "status", "--porcelain")  # left in the worktree, as before
    assert [c["exe"] for c in calls(tmp_path)] == ["codex"]


def test_D02b_a_task_that_names_the_master_fails_as_before(cli, repo, tmp_path, monkeypatch):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo)
    monkeypatch.setenv("STANDIN_CLAUDE", "limit")
    write_sprint(repo, agent_task("T1", "claude-code"))
    assert cli("sprint", "start", "day1")[0] == 0
    assert kinds(repo, "T1") == ["running", "failed"]
    assert [c["exe"] for c in calls(tmp_path)] == ["claude"]


# ---------------------------------------------------------------- who runs it (unit)
def _cfg(repo):
    from steward.models import load_config

    return load_config(repo)


def test_D02b_assign_moves_a_named_worker_and_asks_for_it_again_in_a_later_round(repo, tmp_path):
    install(tmp_path, "claude", "codex", "agy")
    delegate(repo, workers=("codex", "antigravity"), on_limit="wait")
    write_sprint(repo, agent_task("T1", "codex", extra='model = "m1"'))
    cfg, t = _cfg(repo), sp.load(repo, "day1").task[0]
    now = dt.datetime.now(UTC)
    run = {"kind": "state", "task": "T1", "state": "running", "agent": "codex"}
    red = {"kind": "state", "task": "T1", "state": "redelegated", "agent": "codex", "moved_from": "codex"}
    assert sp.assign(repo, cfg, t, {"state": "ready"}, [], now)[1]["agent"] == "codex"
    assert not sp.moved([run], "T1") and sp.moved([run, red], "T1")
    what, a = sp.assign(repo, cfg, t, {"state": "redelegated"}, [run, red], now)
    assert (what, a["agent"], a["model"]) == ("run", "antigravity", None)
    # after a wait (a new round), the named agent is asked for first, with the task's model, when it is available
    wait = {"kind": "state", "task": "T1", "state": "waiting", "until": "2000-01-01T00:00:00Z"}
    what, a = sp.assign(repo, cfg, t, {"state": "waiting"}, [run, red, wait], now)
    assert (what, a["agent"], a["model"], a["role"]) == ("run", "codex", "m1", "worker")
    # a new go order, or a result, ends the move
    go = {"kind": "order", "task": "T1", "order": "go"}
    assert not sp.moved([run, red, go], "T1")
    assert not sp.moved([run, red, {"kind": "state", "task": "T1", "state": "failed"}], "T1")
