"""0.13.0: supervised sprints (RELEASE_v0.13.0_SPEC §4; DESIGN_BRIEF_sprint §2, §3)."""

import datetime as dt
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.org")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.org")
    r = tmp_path / "r"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


def _iso(hours):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _sprint(repo, dispatch="order", start=-1, end=8, extra=""):
    (repo / "development/sprints").mkdir(parents=True, exist_ok=True)
    (repo / "development/sprints/day1.toml").write_text(f'''schema = "steward.sprint/0.1"
[sprint]
id = "day1"
window = {{ start = {_iso(start)}, end = {_iso(end)} }}
dispatch = "{dispatch}"

[[task]]
id = "T1"
title = "write a"
agent = "shell"
command = "echo a > a.txt && git add a.txt && git commit -qm a"
limits = {{ wall_minutes = 5 }}
done = ["test -f a.txt"]

[[task]]
id = "T2"
title = "fails"
agent = "shell"
command = "exit 3"
after = ["T1"]
limits = {{ wall_minutes = 5 }}
done = ["true"]

[[task]]
id = "T3"
title = "after the failure"
agent = "shell"
command = "true"
after = ["T2"]
limits = {{ wall_minutes = 5 }}
done = ["true"]
needs = ["policy.change", "spend"]
{extra}''')


def _status(cli):
    _, out, _ = cli("sprint", "status", "day1")
    return {l.split()[0]: l.split()[1] for l in out.splitlines()}


def test_P2_order_dispatch_waits_for_go_then_runs_in_a_worktree(cli, repo):
    import threading
    import time

    from steward import sprint as sp
    from steward.models import load_config

    _sprint(repo)
    said: list[str] = []
    result: list[int] = []
    # X05: started with no task ordered, the dispatcher waits for the order instead of exiting
    worker = threading.Thread(target=lambda: result.append(
        sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), poll=0.05, out=said.append)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 30
    while not any("waiting for orders" in line for line in said) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert any("waiting for orders" in line for line in said) and worker.is_alive()
    assert _status(cli)["T1"] == "ready"
    assert cli("sprint", "go", "day1", "T1")[0] == 0
    worker.join(120)
    assert not worker.is_alive() and result == [0], said  # it ran T1; T2 has no order, so it returns as before
    st = _status(cli)
    assert st["T1"] == "done" and st["T2"] == "ready"
    assert not (repo / "a.txt").exists()  # the work is on the task's branch, not in the main checkout
    assert sh(repo, "git", "show", "sprint/day1/T1:a.txt") == "a"
    runs = (repo / "development/runs.jsonl").read_text()
    assert "sprint:day1:T1" in runs  # through steward run: limits, watchdog and the run ledger


def test_P2_auto_dispatch_fails_a_task_whose_run_fails_and_blocks_its_dependants(cli, repo):
    _sprint(repo, dispatch="auto")
    assert cli("sprint", "start", "day1")[0] == 0
    st = _status(cli)
    assert st == {"T1": "done", "T2": "failed", "T3": "blocked"}, st
    _, out, _ = cli("sprint", "report", "day1")
    assert "| T1 | shell | done | 1/1 | sprint/day1/T1 |" in out and "waiting for your merge" in out
    assert (repo / "development/sprints/day1-report.md").is_file()


def test_P2_the_agent_never_decides_done_a_failing_check_fails_the_task(cli, repo):
    _sprint(repo, dispatch="auto")
    t = (repo / "development/sprints/day1.toml").read_text().replace('done = ["test -f a.txt"]', 'done = ["test -f b.txt"]')
    (repo / "development/sprints/day1.toml").write_text(t)
    cli("sprint", "start", "day1")
    assert _status(cli)["T1"] == "failed"


def test_P2_nothing_starts_outside_the_window_or_after_stop(cli, repo):
    _sprint(repo, dispatch="auto", start=2, end=8)
    cli("sprint", "start", "day1")
    assert _status(cli)["T1"] == "ready" and not (repo / ".steward/sprints").exists()
    _sprint(repo, dispatch="auto")
    cli("sprint", "stop", "day1")
    cli("sprint", "start", "day1")
    assert _status(cli)["T1"] == "ready"


def test_P2_skip_and_retry_are_human_orders(cli, repo):
    _sprint(repo, dispatch="auto")
    cli("sprint", "start", "day1")
    assert cli("sprint", "skip", "day1", "T3", "--reason", "not needed today")[0] == 0
    assert _status(cli)["T3"] == "skipped"
    assert cli("sprint", "go", "day1", "T2", "--retry")[0] == 0
    assert _status(cli)["T2"] == "ready"


@pytest.mark.parametrize("bad, msg", [('after = ["T3"]', "cycle"), ('done = []', "done"), ('needs = ["root"]', "signature")])
def test_P1_check_refuses_a_cycle_no_done_command_and_unknown_signatures(cli, repo, bad, msg):
    _sprint(repo)
    t = (repo / "development/sprints/day1.toml").read_text()
    if bad.startswith("after"):
        t = t.replace('id = "T1"\n', 'id = "T1"\n' + bad + "\n", 1)
    elif bad.startswith("done"):
        t = t.replace('done = ["test -f a.txt"]', bad, 1)
    else:
        t = t.replace('needs = ["policy.change", "spend"]', bad, 1)
    (repo / "development/sprints/day1.toml").write_text(t)
    code, _, err = cli("sprint", "check", "day1")
    assert code == 65 and msg in err, err


def test_P4_signatures_are_offered_as_sign_ahead_or_sign_later(cli, repo):
    _sprint(repo)
    _, out, _ = cli("sprint", "check", "day1")
    assert "policy.change (T3): sign later" in out and "spend (T3): sign ahead now" in out


def test_P2_plan_drafts_from_the_board_in_order_mode(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[tasks]\nspecs = ["development/tasks/*.md"]\nboard = "development/BOARD.md"\nid_pattern = "TSK-\\\\d{3}"\n')
    (repo / "development/tasks").mkdir(parents=True)
    (repo / "development/tasks/a.md").write_text("# Task\n- **ID:** `TSK-001`\n- **Status:** proposed\n")
    code, out, err = cli("sprint", "plan", "day2", "--hours", "6")
    assert code == 0, err
    text = (repo / "development/sprints/day2.toml").read_text()
    assert 'ref = "TSK-001"' in text and 'dispatch = "order"' in text
    assert cli("sprint", "check", "day2")[0] == 0


# ---------------------------------------------------------------- P5: R-71, R-72
def test_P5_r71_reports_an_invalid_sprint_and_r72_an_ended_sprint_without_its_report(cli, repo):
    from conftest import codes, one
    _sprint(repo, dispatch="auto", start=-3, end=8)
    cli("sprint", "start", "day1")
    _, rep = cli.check(repo, "sprints")
    assert one(rep, "R-71")["status"] == "PASS" and one(rep, "R-72")["status"] == "NOT_APPLICABLE"
    t = (repo / "development/sprints/day1.toml").read_text()
    end = t.split("end = ")[1].split(" }")[0]
    (repo / "development/sprints/day1.toml").write_text(t.replace(end, _iso(-1)))  # the window has ended
    _, rep = cli.check(repo, "sprints")
    assert "R-72.no_report" in codes(one(rep, "R-72"))
    cli("sprint", "report", "day1")
    _, rep = cli.check(repo, "sprints")
    assert one(rep, "R-72")["status"] == "PASS"
    (repo / "development/sprints/day1.toml").write_text(t.replace('done = ["true"]', "done = []", 1))
    _, rep = cli.check(repo, "sprints")
    assert one(rep, "R-71")["status"] == "FAIL"


# ---------------------------------------------------------------- review of 0.13.0: V10 - V13
def test_V10_a_sprint_id_is_never_a_path_and_must_match_its_file(cli, repo):
    _sprint(repo)
    assert cli("sprint", "start", "../../etc/x")[0] == 64
    t = (repo / "development/sprints/day1.toml").read_text()
    (repo / "development/sprints/other.toml").write_text(t)  # declares id "day1"
    code, _, err = cli("sprint", "status", "other")
    assert code == 65 and "must agree" in err


def test_V11_a_foreign_directory_at_the_worktree_path_is_refused(cli, repo):
    _sprint(repo, dispatch="auto")
    (repo / ".steward/sprints/day1/T1").mkdir(parents=True)
    (repo / ".steward/sprints/day1/T1/plain.txt").write_text("not a worktree\n")
    cli("sprint", "start", "day1")
    st = _status(cli)
    assert st["T1"] == "failed" and (repo / ".steward/sprints/day1/T1/plain.txt").exists()


def test_V11_uncommitted_work_is_never_done_and_done_names_its_commit(cli, repo):
    _sprint(repo, dispatch="auto")
    t = (repo / "development/sprints/day1.toml").read_text()
    (repo / "development/sprints/day1.toml").write_text(t.replace("echo a > a.txt && git add a.txt && git commit -qm a",
                                                                  "echo a > a.txt"))
    cli("sprint", "start", "day1")
    assert _status(cli)["T1"] == "failed"
    _sprint(repo, dispatch="auto")
    (repo / "development/sprints/day1.jsonl").unlink()
    shutil.rmtree(repo / ".steward/sprints")
    sh(repo, "git", "worktree", "prune")
    sh(repo, "git", "branch", "-D", "sprint/day1/T1")
    cli("sprint", "start", "day1")
    _, out, _ = cli("sprint", "report", "day1")
    commit = sh(repo, "git", "rev-parse", "sprint/day1/T1")
    assert commit[:12] in out


def test_V12_one_dispatcher_per_sprint_and_unfinished_work_is_reconciled(cli, repo):
    from steward.fsutil import owner_lock, release_owner_lock
    _sprint(repo, dispatch="auto")
    fd = owner_lock(repo, "sprint-day1")  # another dispatcher holds the sprint
    try:
        code, out, _ = cli("sprint", "start", "day1")
        assert code == 75 and "another dispatcher" in out and _status(cli)["T1"] == "ready"
    finally:
        release_owner_lock(repo, "sprint-day1", fd)
    from steward import sprint as sp
    from steward.models import load_config
    sp.led(repo, "day1", load_config(repo).steward.repo_id).append("state", {"task": "T1", "state": "running"})
    _sprint(repo, dispatch="order")
    _, out, _ = cli("sprint", "start", "day1")
    assert "left unfinished" in out and _status(cli)["T1"] == "failed"


def test_V13_no_acceptance_check_runs_after_a_stop(cli, repo):
    _sprint(repo, dispatch="auto")
    t = (repo / "development/sprints/day1.toml").read_text()
    t = t.replace('done = ["test -f a.txt"]', 'done = ["sleep 20"]')
    (repo / "development/sprints/day1.toml").write_text(t)
    import threading
    import time as _t

    def stop_soon():
        _t.sleep(2.5)
        cli("sprint", "stop", "day1", "--now")
    th = threading.Thread(target=stop_soon)
    th.start()
    t0 = _t.monotonic()
    cli("sprint", "start", "day1")
    th.join()
    assert _t.monotonic() - t0 < 15 and _status(cli)["T1"] == "failed"
