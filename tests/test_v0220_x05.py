"""0.22.0 X05: token windows from the records, newest first in the text views, and two supervisor fixes."""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

import pytest

from steward import ledger as ledger_module
from steward.cli import main
from steward.ledger import Ledger

REPO_ID = "123e4567-e89b-42d3-a456-426614174000"
CONFIG = f"""[steward]
schema = "steward.toml/0.2"
repo_id = "{REPO_ID}"
project = "Token windows fixture"
"""
SPRINT_FILE = '''schema = "steward.sprint/0.1"
[sprint]
id = "s1"
window = { start = 2026-11-25T09:00:00Z, end = 2026-11-25T18:00:00Z }
dispatch = "order"

[[task]]
id = "T1"
title = "one"
agent = "claude-code"
prompt = "one"
done = ["true"]

[[task]]
id = "T2"
title = "two"
agent = "codex"
prompt = "two"
done = ["true"]

[[task]]
id = "T3"
title = "three"
agent = "shell"
command = "true"
done = ["true"]
'''


def jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def claude(at, ident, inputs, outputs, session="session-claude"):
    """A stand-in Claude Code log record: one assistant message with its usage."""
    return {"type": "assistant", "sessionId": session, "timestamp": at,
            "message": {"id": ident, "model": "claude-test", "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": inputs, "output_tokens": outputs, "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


def codex(at, inputs, outputs):
    """A stand-in Codex log: one session with one token count."""
    usage = {"input_tokens": inputs, "cached_input_tokens": 0, "output_tokens": outputs,
             "reasoning_output_tokens": 0, "total_tokens": inputs + outputs}
    return [{"type": "session_meta", "payload": {"id": "session-codex"}},
            {"type": "turn_context", "payload": {"model": "codex-test"}},
            {"type": "event_msg", "timestamp": at, "payload": {"type": "token_count", "info": {
                "last_token_usage": usage, "total_token_usage": usage}}}]


def stamped(monkeypatch, led, when, kind, body):
    monkeypatch.setattr(ledger_module, "_now", lambda: when)
    led.append(kind, body)


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """A recorded sprint (T1 by Claude Code done, T2 by Codex failed, T3 by shell skipped while it ran), the run each
    task ran through, one plain `steward run`, and stand-in agent logs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "steward.toml").write_text(CONFIG)
    (tmp_path / "development/sprints").mkdir(parents=True)
    (tmp_path / "development/sprints/s1.toml").write_text(SPRINT_FILE)
    sprint = Ledger(tmp_path / "development/sprints/s1.jsonl", "sprint", REPO_ID)
    runs = Ledger(tmp_path / "development/runs.jsonl", "runs", REPO_ID)
    stamped(monkeypatch, sprint, "2026-11-25T09:00:00Z", "opened", {"sprint": "s1", "tasks": ["T1", "T2", "T3"],
                                                                   "dispatch": "order"})
    for task, agent, run, start, state, end in (
            ("T1", "claude-code", "r-t1", "2026-11-25T10:00:00Z", "done", "2026-11-25T10:30:00Z"),
            ("T2", "codex", "r-t2", "2026-11-25T11:00:00Z", "failed", "2026-11-25T11:30:00Z"),
            ("T3", "shell", "r-t3", "2026-11-25T12:00:00Z", None, "2026-11-25T12:30:00Z")):
        stamped(monkeypatch, sprint, start, "order", {"task": task, "order": "go", "by": "human"})
        stamped(monkeypatch, runs, start, "started", {"run": run, "label": f"sprint:s1:{task}"})
        stamped(monkeypatch, sprint, start, "state", {"task": task, "state": "running", "agent": agent, "run": run})
        stamped(monkeypatch, runs, end, "outcome", {"run": run, "status": "finished"})
        if state:
            stamped(monkeypatch, sprint, end, "state", {"task": task, "state": state})
        else:
            stamped(monkeypatch, sprint, end, "order", {"task": task, "order": "skip", "by": "human", "reason": "x"})
    stamped(monkeypatch, runs, "2026-11-25T13:00:00Z", "started", {"run": "r-plain", "label": "pipeline"})
    stamped(monkeypatch, runs, "2026-11-25T13:30:00Z", "outcome", {"run": "r-plain", "status": "finished"})
    stamped(monkeypatch, runs, "2026-11-25T14:00:00Z", "started", {"run": "r-quiet", "label": "no agent"})
    stamped(monkeypatch, runs, "2026-11-25T14:10:00Z", "outcome", {"run": "r-quiet", "status": "finished"})
    logs = tmp_path / "logs"
    logs.mkdir()
    jsonl(logs / "claude.jsonl", [
        claude("2026-11-25T10:10:00+00:00", "m1", 100, 10),    # T1
        claude("2026-11-25T10:20:00+00:00", "m2", 40, 5),      # T1
        claude("2026-11-25T11:10:00+00:00", "m3", 7, 3),       # in T2's window, but T2 ran Codex: no task
        claude("2026-11-25T12:10:00+00:00", "m4", 20, 2),      # T3 ran by shell: any agent's usage counts
        claude("2026-11-25T13:10:00+00:00", "m5", 9, 1),       # the plain run
        claude("2026-11-25T15:00:00+00:00", "m6", 50, 50),     # outside every window
    ])
    jsonl(logs / "codex.jsonl", codex("2026-11-25T11:05:00+00:00", 30, 6))  # T2
    monkeypatch.setattr(ledger_module, "_now", lambda: "2026-11-25T16:00:00Z")
    return tmp_path, ["--claude", str(logs / "claude.jsonl"), "--codex", str(logs / "codex.jsonl")]


def report(capsys, *args):
    capsys.readouterr()
    code = main(["tokens", "report", *args])
    out, err = capsys.readouterr()
    assert code == 0, err
    return out


def test_X05_sprint_and_run_windows_count_each_task(recorded, capsys):
    root, logs = recorded
    doc = json.loads(report(capsys, "--format", "json", *logs))
    rows = {row["task"]: row for row in doc["tasks"]}
    assert set(rows) == {"sprint s1 T1", "sprint s1 T2", "sprint s1 T3", "run r-plain"}  # r-quiet logged nothing
    assert rows["sprint s1 T1"]["tokens"] == 155
    assert rows["sprint s1 T1"]["agents"] == [{"agent": "claude", "tokens": 155}]
    assert rows["sprint s1 T2"]["tokens"] == 36
    assert rows["sprint s1 T2"]["agents"] == [{"agent": "codex", "tokens": 36}]
    assert rows["sprint s1 T3"]["tokens"] == 22
    assert rows["run r-plain"]["tokens"] == 10
    assert rows["sprint s1 T1"]["windows"] == [{"source": "sprint", "ledger": "development/sprints/s1.jsonl",
                                               "start": "2026-11-25T10:00:00+00:00",
                                               "end": "2026-11-25T10:30:00+00:00"}]
    assert rows["sprint s1 T3"]["windows"][0]["end"] == "2026-11-25T12:30:00+00:00"  # ended by the skip order
    assert rows["run r-plain"]["windows"] == [{"source": "run", "ledger": "development/runs.jsonl",
                                              "start": "2026-11-25T13:00:00+00:00",
                                              "end": "2026-11-25T13:30:00+00:00"}]
    assert not any(task.startswith("run r-t") for task in rows)  # a sprint task's own run is its sprint window
    assert doc["schema"] == "steward.tokens_report/0.1" and doc["issues"] == []
    one = json.loads(report(capsys, "--format", "json", "--task", "sprint s1 T2", *logs))
    assert [row["task"] for row in one["tasks"]] == ["sprint s1 T2"]


def test_X05_legacy_json_is_unchanged_by_the_records(recorded, capsys):
    root, logs = recorded
    with_records = report(capsys, "--json", *logs)
    for rel in ("development/sprints/s1.jsonl", "development/runs.jsonl"):
        (root / rel).unlink()
    assert with_records == report(capsys, "--json", *logs)
    assert [row["task"] for row in json.loads(with_records)["tasks"]] == ["all activity"]
    assert "windows" not in json.loads(with_records)["tasks"][0]


def test_X05_a_hand_made_window_keeps_its_task_and_its_usage(recorded, monkeypatch, capsys):
    from steward import tokens

    monkeypatch.setattr(tokens, "now", lambda: datetime(2026, 11, 25, 10, 5, tzinfo=timezone.utc))
    assert main(["task", "start", "T1"]) == 0
    monkeypatch.setattr(tokens, "now", lambda: datetime(2026, 11, 25, 10, 15, tzinfo=timezone.utc))
    assert main(["task", "done", "T1"]) == 0
    monkeypatch.setattr(tokens, "now", lambda: datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc))
    doc = json.loads(report(capsys, "--format", "json", *recorded[1]))
    rows = {row["task"]: row for row in doc["tasks"]}
    assert "sprint s1 T1" not in rows  # the task has a window by hand: that one is used
    assert rows["T1"]["tokens"] == 110 and rows["T1"]["windows"][0]["source"] == "task-tokens"


def test_X05_text_lists_the_newest_window_first_and_names_its_source(recorded, capsys):
    out = report(capsys, *recorded[1])
    heads = [line.split("  ")[0] for line in out.splitlines() if "estimated cost" in line and not line.startswith(" ")]
    assert heads == ["run r-plain", "sprint s1 T3", "sprint s1 T2", "sprint s1 T1"]
    assert "(window: sprint)" in out and "(window: run)" in out


def test_X05_an_unfinished_sprint_task_ends_with_the_window_and_a_dead_run_is_left_out(recorded, monkeypatch, capsys):
    root, logs = recorded
    sprint = Ledger(root / "development/sprints/s1.jsonl", "sprint", REPO_ID)
    runs = Ledger(root / "development/runs.jsonl", "runs", REPO_ID)
    stamped(monkeypatch, sprint, "2026-11-25T15:00:00Z", "order", {"task": "T2", "order": "go", "by": "human",
                                                                  "retry": True})
    stamped(monkeypatch, sprint, "2026-11-25T15:00:00Z", "state", {"task": "T2", "state": "running",
                                                                  "agent": "claude-code"})
    stamped(monkeypatch, runs, "2026-11-25T16:00:00Z", "started", {"run": "r-dead", "label": "x", "pid": 0,
                                                                  "pid_created": 0})
    doc = json.loads(report(capsys, "--format", "json", *logs))
    t2 = next(row for row in doc["tasks"] if row["task"] == "sprint s1 T2")
    assert [w["end"] for w in t2["windows"]] == ["2026-11-25T11:30:00+00:00", "2026-11-25T18:00:00+00:00"]
    assert t2["tokens"] == 36 + 100  # the retry, by Claude Code, took m6
    assert "1 run(s) have no recorded end and no live process; their windows are left out" in doc["issues"]


def test_X05_check_keeps_the_hand_made_windows_only(recorded, capsys):
    capsys.readouterr()
    assert main(["tokens", "check", *recorded[1]]) == 0
    assert capsys.readouterr().out.strip() == "No active token window"


# ---------------------------------------------------------------- newest first
def test_X05_newest_first_orders_by_date_then_id_highest_first():
    from steward.newest import id_key, newest_first

    assert sorted(["T9", "T10", "T1"], key=id_key) == ["T1", "T9", "T10"]
    rows = [{"id": "A-2", "at": "2026-11-01"}, {"id": "A-10", "at": "2026-11-01"}, {"id": "A-3", "at": None},
            {"id": "A-1", "at": "2026-11-20T10:00:00Z"}]
    assert [r["id"] for r in newest_first(rows, lambda r: r["at"], lambda r: r["id"])] == ["A-1", "A-10", "A-2", "A-3"]


def test_X05_timeline_text_lists_the_latest_due_first(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "steward.toml").write_text(CONFIG)
    (tmp_path / "development").mkdir()
    (tmp_path / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n'
        '[[milestone]]\nid = "early"\ntitle = "Early"\ndue = 2026-12-01T00:00:00Z\n'
        '[[milestone]]\nid = "late"\ntitle = "Late"\ndue = 2027-01-01T00:00:00Z\n')
    capsys.readouterr()
    assert main(["timeline"]) == 0
    out = capsys.readouterr().out
    assert out.index("late: Late") < out.index("early: Early")
    capsys.readouterr()
    assert main(["timeline", "--format", "json"]) == 0
    assert [m["id"] for m in json.loads(capsys.readouterr().out)["milestones"]] == ["early", "late"]  # JSON as before


def test_X05_decisions_text_lists_the_newest_first(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "steward.toml").write_text(CONFIG)
    (tmp_path / "development").mkdir()
    (tmp_path / "development/DECISIONS.md").write_text(
        "# Decisions\n\n## 2026-11-01: First\n- **Muiz:** \"one\"\n\n## 2026-11-20: Second\n- **Muiz:** \"two\"\n\n"
        "## 2026-11-20: Third\n- **Muiz:** \"three\"\n")
    capsys.readouterr()
    assert main(["decisions"]) == 0
    out = capsys.readouterr().out
    assert out.index("Third") < out.index("Second") < out.index("First")


def test_X05_every_document_schema_says_its_order():
    from steward.interface_schemas import SCHEMAS

    for name, model in SCHEMAS.items():
        assert "Order" in (model.model_json_schema().get("description") or ""), name


# ---------------------------------------------------------------- the supervisor
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "T")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@example.org")
    root = tmp_path / "r"
    root.mkdir()
    cli("init", "--repo", root)
    sh(root, "git", "init", "-q", "-b", "main")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "init")
    monkeypatch.chdir(root)
    return root


def _iso(hours):
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _day(root, tasks=("T1",)):
    (root / "development/sprints").mkdir(parents=True, exist_ok=True)
    body = "".join(f'\n[[task]]\nid = "{t}"\ntitle = "{t}"\nagent = "shell"\ncommand = "true"\n'
                   f'limits = {{ wall_minutes = 5 }}\ndone = ["true"]\n' for t in tasks)
    (root / "development/sprints/day1.toml").write_text(
        f'schema = "steward.sprint/0.1"\n[sprint]\nid = "day1"\nwindow = {{ start = {_iso(-1)}, end = {_iso(8)} }}\n'
        f'dispatch = "order"\n{body}')


@needs_git
def test_X05_start_with_no_task_ordered_waits_until_stop(cli, repo):
    from steward import sprint as sp
    from steward.models import load_config

    _day(repo)
    said: list[str] = []
    result: list[int] = []
    worker = threading.Thread(target=lambda: result.append(
        sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), poll=0.05, out=said.append)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 30
    while not said and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    assert worker.is_alive(), said
    assert said == ["waiting for orders: steward sprint go day1 T1 (until the window ends, or steward sprint stop day1)"]
    assert cli("sprint", "stop", "day1")[0] == 0
    worker.join(30)
    assert not worker.is_alive() and result == [0]


@needs_git
def test_X05_start_with_no_task_ordered_ends_with_the_window(cli, repo):
    from datetime import timedelta

    from steward import sprint as sp
    from steward.models import load_config

    _day(repo)
    sf = sp.load(repo, "day1")
    clock = iter([datetime.now(timezone.utc)] * 3)
    said: list[str] = []

    def now():  # the window ends after the first look
        return next(clock, sf.sprint.window.end + timedelta(seconds=1))

    assert sp.dispatch(repo, load_config(repo), sf, poll=0.01, now=now, out=said.append) == 0
    assert said and said[0].startswith("waiting for orders")


@needs_git
def test_X05_R71_in_a_task_worktree_reads_the_main_checkouts_ledger(cli, repo):
    _day(repo, ("T1", "T2"))
    (repo / "development/sprints/day1.toml").write_text(
        (repo / "development/sprints/day1.toml").read_text().split("\n[[task]]\nid = \"T2\"")[0])
    from steward import sprint as sp
    from steward.models import load_config

    cfg = load_config(repo)
    sp.led(repo, "day1", cfg.steward.repo_id).append("opened", {"sprint": "day1", "tasks": ["T1"], "dispatch": "order"})
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "sprint opened")
    _day(repo, ("T1", "T2"))  # a task written into the file after the sprint opened, then added
    assert cli("sprint", "add", "day1", "T2")[0] == 0
    sh(repo, "git", "add", "development/sprints/day1.toml")
    sh(repo, "git", "commit", "-qm", "T2 in the file")  # the ledger's `added` is not committed (it is on main)
    wt = repo / ".steward/sprints/day1/T2"
    sh(repo, "git", "worktree", "add", "-q", "-b", "sprint/day1/T2", str(wt))

    def r71(root):
        from conftest import one

        _, rep = cli.check(root, "sprints")
        return [one(rep, "R-71")]

    assert [r["status"] for r in r71(repo)] == ["PASS"]
    found, = r71(wt)
    assert found["status"] == "PASS" and "main checkout" in found["reason"], found
    sh(wt, "git", "switch", "-q", "-c", "elsewhere")  # not a task branch: the worktree's own copy, which lacks the add
    found, = r71(wt)
    assert found["status"] == "FAIL", found
