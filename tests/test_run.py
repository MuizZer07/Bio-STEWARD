"""v0.4.0: `steward run` (watchdog, slots, records), ledgers (R-31) and run records (R-32). RELEASE_v0.4_SPEC §6."""

import json
import os
import subprocess
import sys
import threading
import time

import psutil
import pytest

from steward.ledger import Ledger, LedgerError, verify

from conftest import codes, one

PY = sys.executable


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[run]\nslots = { heavy = 1 }\nwall_s = 30\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def entries(repo):
    return verify(repo / "development/runs.jsonl").entries


def test_finished_run_records_everything(cli, repo):
    (repo / "in.txt").write_text("x")
    code, _, err = cli("run", "--input", "in.txt", "--output", "out.txt", "--param", "k=3", "--seed", "7",
                       "--estimate-min", "0.1", "--", PY, "-c", "open('out.txt','w').write('y'); print('ok')")
    assert code == 0 and "finished" in err
    started, outcome = [e for e in entries(repo) if e["kind"] in ("started", "outcome")]
    assert started["inputs"]["in.txt"] and started["params"] == {"k": "3"} and started["seed"] == "7"
    assert started["limits"]["wall_s"] == 30 and "python" in started["environment"]
    assert outcome["status"] == "finished" and outcome["outputs"]["out.txt"] and outcome["log_sha256"]
    assert (repo / outcome["log"]).read_text().strip() == "ok"


def test_failed_run_keeps_exit_code(cli, repo):
    code, _, _ = cli("run", "--", PY, "-c", "raise SystemExit(5)")
    assert code == 5 and entries(repo)[-1]["status"] == "failed"


@pytest.mark.parametrize("flags,code_expected,needle", [
    (["--wall", "1"], 124, "wall time"),
    (["--hang", "1"], 124, "no output"),
    (["--mem", "60"], 124, "memory"),
])
def test_limits_kill_the_tree(cli, repo, flags, code_expected, needle):
    prog = "import time\nx = bytearray(250*1024*1024) if %r else 0\nprint('go', flush=True)\ntime.sleep(10)" % ("--mem" in flags)
    t0 = time.monotonic()
    code, _, err = cli("run", *flags, "--", PY, "-c", prog)
    assert code == code_expected and needle in err and time.monotonic() - t0 < 9
    assert entries(repo)[-1]["status"] == "killed"


def test_cli_cannot_loosen_configured_limits(cli, repo):
    cli("run", "--wall", "999", "--", PY, "-c", "pass")
    assert [e for e in entries(repo) if e["kind"] == "started"][-1]["limits"]["wall_s"] == 30


def test_child_processes_are_killed_with_the_parent(cli, repo):
    prog = "import subprocess, sys, time\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\nopen('child.pid','w').write(str(p.pid))\ntime.sleep(30)"
    code, _, _ = cli("run", "--wall", "1.5", "--", PY, "-c", prog)
    pid = int((repo / "child.pid").read_text())
    time.sleep(0.5)
    assert code == 124 and not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
def test_limitation_escaped_process_is_not_supervised(cli, repo):
    """Documented limit: a double-forked, setsid process leaves the tree and survives (RELEASE_v0.4_SPEC §2)."""
    prog = ("import os, sys, time\n"
            "if os.fork() == 0:\n    os.setsid()\n    if os.fork() == 0:\n        open('escaped.pid','w').write(str(os.getpid())); time.sleep(20); os._exit(0)\n    os._exit(0)\n"
            "time.sleep(30)")
    cli("run", "--wall", "1.5", "--", PY, "-c", prog)
    pid = int((repo / "escaped.pid").read_text())
    try:
        assert psutil.pid_exists(pid), "expected the escaped process to survive (out of coverage)"
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def test_slot_busy_refuses_75_and_wait_succeeds(cli, repo):
    holder = subprocess.Popen([sys.executable, "-m", "steward.cli", "run", "--slot", "heavy", "--", PY, "-c",
                               "import time; time.sleep(3)"], cwd=repo)
    time.sleep(1.0)
    code, _, err = cli("run", "--slot", "heavy", "--", PY, "-c", "pass")
    assert code == 75 and "no free 'heavy' slot" in err
    code, _, _ = cli("run", "--slot", "heavy", "--wait", "--", PY, "-c", "pass")
    holder.wait()
    assert code == 0
    assert cli("run", "--slot", "gpu", "--", PY, "-c", "pass")[0] == 64


def test_unfinished_run_incomplete_then_recover(cli, repo):
    led = Ledger(repo / "development/runs.jsonl", "runs")
    led.append("started", {"run": "r-dead", "pid": 999999, "pid_created": 0})
    code, rep = cli.check(repo)
    assert one(rep, "R-32")["status"] == "INCOMPLETE" and code == 2
    code, out, _ = cli("run", "--recover")
    assert "r-dead" in out
    _, rep = cli.check(repo)
    res = one(rep, "R-32")
    assert res["status"] == "PASS" and "R-32.interrupted" in codes(res)


def test_failed_and_killed_runs_are_retained_not_failing(cli, repo):
    cli("run", "--", PY, "-c", "raise SystemExit(2)")
    cli("run", "--wall", "1", "--", PY, "-c", "import time; time.sleep(5)")
    _, rep = cli.check(repo)
    res = one(rep, "R-32")
    assert res["status"] == "PASS" and {"R-32.failed", "R-32.killed"} <= codes(res)


def test_output_changed_after_run_is_listed(cli, repo):
    cli("run", "--output", "o.txt", "--", PY, "-c", "open('o.txt','w').write('1')")
    (repo / "o.txt").write_text("2")
    _, rep = cli.check(repo)
    assert "R-32.output_changed" in codes(one(rep, "R-32"))


# ---------------------------------------------------------------- ledger integrity
def test_edited_entry_fails_and_gap_fails(cli, repo):
    cli("run", "--", PY, "-c", "pass")
    p = repo / "development/runs.jsonl"
    lines = p.read_text().splitlines()
    e = json.loads(lines[1])
    e["command"] = ["something", "else"]
    lines[1] = json.dumps(e)
    p.write_text("\n".join(lines) + "\n")
    _, rep = cli.check(repo)
    assert one(rep, "R-31")["status"] == "FAIL"


def test_deleted_middle_entry_fails(cli, repo):
    cli("run", "--", PY, "-c", "raise SystemExit(1)")
    cli("run", "--", PY, "-c", "pass")
    p = repo / "development/runs.jsonl"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:2] + lines[3:]) + "\n")  # a failed run's outcome "disappears"
    _, rep = cli.check(repo)
    res = one(rep, "R-31")
    assert res["status"] == "FAIL" and {"ledger.sequence", "ledger.chain_broken"} & codes(res)


def test_truncated_tail_is_undetectable_without_anchor(cli, repo):
    cli("run", "--", PY, "-c", "pass")
    p = repo / "development/runs.jsonl"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:-1]) + "\n")
    _, rep = cli.check(repo)
    res = one(rep, "R-31")
    assert res["status"] == "PASS" and "R-31.anchor_none" in codes(res)  # stated limit, not hidden


def test_torn_tail_incomplete_then_recover_never_deletes(cli, repo):
    cli("run", "--", PY, "-c", "pass")
    p = repo / "development/runs.jsonl"
    with open(p, "ab") as f:
        f.write(b'{"seq": 3, "partial')
    _, rep = cli.check(repo)
    assert one(rep, "R-31")["status"] == "INCOMPLETE"
    with pytest.raises(LedgerError):
        Ledger(p, "runs").append("x", {})
    code, out, _ = cli("ledger", "recover", p)
    assert code == 0 and "quarantined" in out
    assert any(q.read_bytes().startswith(b'{"seq": 3') for q in (repo / "development/runs.jsonl.quarantine").iterdir())
    _, rep = cli.check(repo)
    assert one(rep, "R-31")["status"] == "PASS"


def test_concurrent_writers_lose_nothing(tmp_path):
    led = Ledger(tmp_path / "l.jsonl", "t")

    def write(k):
        for i in range(25):
            led.append("x", {"w": k, "i": i})

    threads = [threading.Thread(target=write, args=(k,)) for k in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    v = verify(tmp_path / "l.jsonl")
    assert not v.errors and len(v.entries) == 101
