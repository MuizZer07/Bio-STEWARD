"""0.12.0: the 0.9.0 fixes the 0.10.0 review rated partially verified (R1, R3, R4, R6, R7, R10, R12, R14, R17, R18,
R20), one regression test per remaining edge case (RELEASE_v0.12.0_SPEC §2)."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import codes, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    return r


# ---------------------------------------------------------------- R1: an overlay never repairs an invalid base gate
@pytest.mark.parametrize("base", ['require = ["R-01", {x = 1}]', 'require = ["R-01"]\nmin_evaluated = "two"',
                                  'require = ["R-01"]\nadded = [3]'])
def test_R1_an_invalid_base_gate_is_not_reshaped_by_an_overlay(cli, proj, base):
    with open(proj / "steward.toml", "a") as f:
        f.write(f"\n[gates.push]\n{base}\n")
    (proj / "steward.local.toml").write_text('[gates.push]\nrequire = ["R-07"]\nmin_evaluated = 2\n')
    code, rep = cli.check(proj)
    assert code != 70 and one(rep, "R-01")["status"] == "FAIL", one(rep, "R-01")


# ---------------------------------------------------------------- R3: stop only the process that holds its lock
@git_needed
def test_R3_a_matching_record_whose_process_does_not_hold_the_lock_is_not_stopped(cli, proj, tmp_path):
    import time
    sh(proj, "git", "init", "-q", "-b", "main")
    holder = ("import sys, time\nfrom pathlib import Path\nfrom steward.fsutil import owner_lock\n"
              "fd = owner_lock(Path(sys.argv[1]), 'mcp-test')\nprint('held', flush=True)\ntime.sleep(60)\n")
    bystander = subprocess.Popen([sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)",
                                  "steward", "mcp"], stdout=subprocess.PIPE, text=True)
    lock_holder = subprocess.Popen([sys.executable, "-c", holder, str(proj), "x"], stdout=subprocess.PIPE, text=True)
    try:
        assert bystander.stdout.readline().strip() == "up" and lock_holder.stdout.readline().strip() == "held"
        import psutil
        lock = proj / ".steward/owners/mcp-test.lock"
        # the record names the bystander (steward's command line, exact start time), which never opened the lock
        lock.write_text(json.dumps({"pid": bystander.pid, "created": psutil.Process(bystander.pid).create_time()}))
        from steward import session as ss
        from steward.models import load_config
        report = ss.end(proj, load_config(proj))
        time.sleep(0.3)
        assert bystander.poll() is None, report
        assert any("does not hold its ownership lock" in line for line in report), report
    finally:
        for p in (bystander, lock_holder):
            p.kill()
            p.wait()


# ---------------------------------------------------------------- R4: sidecars and staged worktrees
@git_needed
def test_R4_a_staged_worktree_of_another_repository_or_a_live_push_is_left(cli, proj):
    import tempfile
    from pathlib import Path
    sh(proj, "git", "init", "-q", "-b", "main")
    sh(proj, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "x")
    from steward import session as ss
    from steward.models import load_config
    for owner in ({"root": "/elsewhere", "pid": 1}, {"root": str(proj.resolve()), "pid": os.getpid()}, None):
        wt = Path(tempfile.mkdtemp(prefix="steward-push-")) / "wt"
        sh(proj, "git", "worktree", "add", "--detach", "-q", str(wt))
        if owner is not None:
            (wt.parent / "owner.json").write_text(json.dumps(owner))
        report = ss.end(proj, load_config(proj))
        assert wt.is_dir() and any("left the staged worktree" in line for line in report), report
        sh(proj, "git", "worktree", "remove", "--force", str(wt))


def test_R4_a_bundle_sidecar_is_never_written_through_a_link(cli, proj, tmp_path):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[release]\nbundles = "bundles"\n')
    (proj / "data").mkdir()
    (proj / "data/a.txt").write_text("a\n")
    (proj / "bundles").mkdir()
    target = tmp_path / "outside.json"
    target.write_text("keep\n")
    (proj / "bundles/b.bundle.json").symlink_to(target)
    code, _, err = cli("release", "bundle", "b", "--paths", "data")
    assert code == 0, err
    assert target.read_text() == "keep\n" and not (proj / "bundles/b.bundle.json").is_symlink()


# ---------------------------------------------------------------- R7: an identical orphan gets its receipt
def test_R7_an_inbox_file_without_any_state_gets_its_receipt_on_receive(cli, proj):
    import datetime
    from steward import exchange as xc
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    cli("exchange", "init")
    text = xc.render({"schema": "steward.exchange/1", "id": "BBB-REQ-001", "kind": "request", "from": "BBB", "to": "AAA",
                      "title": "t", "filed": datetime.date(2026, 11, 24)}, "## Need\nx\n")
    (proj / "exchange/inbox/BBB-REQ-001.md").write_text(text)  # left by an interrupted receive: no state
    src = proj / "drop.md"
    src.write_text(text)
    assert cli("exchange", "receive", src)[0] == 65  # still "already received" for the command
    st = xc.states(proj).get("BBB-REQ-001", [])
    assert st and st[-1]["state"] == "acknowledged" and st[-1]["received"]["sha256"]
    _, rep = cli.check(proj, "governance")
    assert "R-53.unknown_item" not in codes(one(rep, "R-53")) and one(rep, "R-54")["status"] == "PASS"


# ---------------------------------------------------------------- R10: one verified read; a future date
def _ack_item(cli, proj):
    from steward import exchange as xc
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    cli("exchange", "init")
    item = ('+++\nschema = "steward.exchange/1"\nid = "BBB-REQ-001"\nkind = "request"\nfrom = "BBB"\nto = "AAA"\n'
            'title = "t"\nfiled = 2026-11-01\n+++\n')
    xc.receive(proj, "r", "AAA", item.encode(), {"from": "file"})


def test_R10_an_acknowledgement_dated_in_the_future_is_no_clock(cli, proj, monkeypatch):
    import datetime as dt
    from steward import process
    _ack_item(cli, proj)
    monkeypatch.setattr(process, "_today", lambda: dt.date.today() - dt.timedelta(days=3))
    _, rep = cli.check(proj, "governance")
    res = one(rep, "R-54")
    assert res["status"] == "INCOMPLETE" and "R-54.future_date" in codes(res), res


def test_R10_the_verdict_never_comes_from_a_second_unchecked_read(cli, proj, monkeypatch):
    import datetime as dt
    from steward import exchange as xc
    from steward import process
    _ack_item(cli, proj)
    monkeypatch.setattr(process, "_today", lambda: dt.date.today() + dt.timedelta(days=30))
    monkeypatch.setattr(xc, "states", lambda root: {})  # a second read that would see nothing waiting
    _, rep = cli.check(proj, "governance")
    assert "R-54.no_decision" in codes(one(rep, "R-54"))


# ---------------------------------------------------------------- R12: R-58 reads and headings
@pytest.mark.parametrize("heading, found", [("## Unreleased", True), ("## [Unreleased]", True),
                                            ("## Unreleased (next)", True), ("## Unreleased features of 0.3", False)])
def test_R12_only_the_unreleased_heading_starts_the_section(heading, found):
    from steward.process import unreleased_entries
    assert (unreleased_entries(f"# Changelog\n\n{heading}\n- an entry\n") is not None) is found


@git_needed
def test_R12_a_git_failure_reading_head_is_unknown_never_absent(cli, proj, monkeypatch):
    from steward import process as pr
    sh(proj, "git", "init", "-q", "-b", "main")
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[changelog]\nfile = "CHANGELOG.md"\n')
    (proj / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    sh(proj, "git", "tag", "v0.1")
    (proj / "a.py").write_text("x = 1\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "y")
    real = pr.git_run

    def failing(root, *args, **kw):
        if args[:1] in (("ls-tree",), ("show",), ("cat-file",)):
            return subprocess.CompletedProcess(args, 128, b"", b"fatal")
        return real(root, *args, **kw)
    monkeypatch.setattr(pr, "git_run", failing)
    _, rep = cli.check(proj, "changelog")
    assert one(rep, "R-58")["status"] == "UNKNOWN", one(rep, "R-58")


# ---------------------------------------------------------------- R14: R-63 and an unreadable HEAD
@git_needed
def test_R14_an_unreadable_head_is_unknown_never_no_history(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[frozen]]\nname = "agent-v1"\nfiles = ["agents/v1/**"]\n')
    (proj / "agents/v1").mkdir(parents=True)
    (proj / "agents/v1/prompt.md").write_text("careful\n")
    sh(proj, "git", "init", "-q", "-b", "main")
    assert cli("frozen", "record", "agent-v1")[0] == 0
    _, rep = cli.check(proj, "frozen")
    assert one(rep, "R-63")["status"] == "PASS"  # unborn: no history, judged by hashes
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    head = sh(proj, "git", "rev-parse", "HEAD")
    obj = proj / ".git/objects" / head[:2] / head[2:]
    obj.chmod(0o644)
    obj.write_bytes(b"corrupt")  # HEAD names a commit git can no longer read
    _, rep = cli.check(proj, "frozen")
    res = one(rep, "R-63")
    assert res["status"] == "UNKNOWN" and "R-63.history_unavailable" in codes(res), res


# ---------------------------------------------------------------- R17: R-67 checks every power row
from test_v090_third_intake import _set_minimum, write  # noqa: E402
from test_v090_third_intake import contract  # noqa: E402,F401


@pytest.mark.parametrize("mutate", [lambda t: t.append("not a row"), lambda t: t.append({"n": 99, "shrink": 1}),
                                    lambda t: t.append({"n": True, "shrink": 1, "power": 0.5})])
def test_R17_a_malformed_row_at_any_size_fails_and_never_crashes(cli, contract, mutate):
    write(contract, "dev/effects.json", json.dumps([0.9, 1.1, 0.7, 1.3, 0.8, 1.0, 1.2, 0.6, 0.95, 1.05]))
    _set_minimum(contract, 15)
    cli("benchmark", "power", "benchmarks/expr-clf.contract.toml", "--effects", "dev/effects.json",
        "--test", "sign-flip", "--alpha", "0.05", "--shrink", "1,0.5", "--n", "5,15", "--reps", "200")
    p = contract / "benchmarks/expr-clf.power.json"
    rec = json.loads(p.read_text())
    mutate(rec["table"])
    p.write_text(json.dumps(rec))
    code, rep = cli.check(contract, "benchmark")
    res = one(rep, "R-67")
    assert code != 70 and res["status"] == "FAIL" and "R-67.invalid_row" in codes(res), res


# ---------------------------------------------------------------- R18: image tags and legacy bundle entries
@pytest.mark.parametrize("tags", ['""', "false", "0", "{}"])
def test_R18_a_falsy_non_list_repotags_is_unreadable_not_empty(tmp_path, tags):
    import io
    import tarfile
    from steward.containers import archive_tags
    data = f'[{{"Config": "c.json", "RepoTags": {tags}, "Layers": []}}]'.encode()
    p = tmp_path / "img.tar"
    with tarfile.open(p, "w") as t:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    assert archive_tags(p) is None


def test_R18_control_null_repotags_is_an_untagged_image(tmp_path):
    import io
    import tarfile
    from steward.containers import archive_tags
    data = b'[{"Config": "c.json", "RepoTags": null, "Layers": []}]'
    p = tmp_path / "img.tar"
    with tarfile.open(p, "w") as t:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    assert archive_tags(p) == []


# ---------------------------------------------------------------- R20: a supervision error still records an outcome
def test_R20_an_error_during_supervision_records_a_failed_outcome(cli, proj, monkeypatch):
    from steward import issues, runner
    from steward.ledger import verify

    def broken(*a, **k):
        raise RuntimeError("process table unavailable")
    monkeypatch.setattr(runner, "_watch", broken)
    code, _, err = cli("run", "--", "sleep", "30")
    assert code != 0
    fault = issues.read_last_error(proj)
    assert fault.command == "run" and fault.exit_code == code and issues.HINT in err
    assert not fault.flags and fault.error_type == "RuntimeError"
    out = [e for e in verify(proj / "development/runs.jsonl").entries if e.get("kind") == "outcome"]
    assert len(out) == 1 and out[0]["status"] == "failed" and out[0]["cleanup"] == "incomplete", out


def test_R20_terminate_signals_the_group_when_the_tree_cannot_be_listed(monkeypatch):
    import signal
    import subprocess
    import sys
    import psutil
    from steward import runner
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    monkeypatch.setattr(runner, "_tree", lambda ps: (_ for _ in ()).throw(psutil.AccessDenied(ps.pid)))
    runner._terminate(p, grace=2)
    assert p.wait(timeout=10) in (-signal.SIGTERM, -signal.SIGKILL)


# ---------------------------------------------------------------- R6: rollback never removes a swapped-in entry
def test_R6_rollback_puts_back_an_entry_swapped_in_under_the_item_name(cli, proj):
    from steward import exchange as xc
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    cli("exchange", "init")
    dest = xc.write_new(proj, "outbox", "AAA-REQ-009.md", b"mine\n")
    dest.unlink()
    dest.write_text("someone else's\n")  # a different file under the same name
    xc.rollback(proj, dest)
    assert dest.read_text() == "someone else's\n"
    assert not [p for p in dest.parent.iterdir() if p.name.endswith(".rollback")]
    d2 = xc.write_new(proj, "outbox", "AAA-REQ-010.md", b"mine\n")
    xc.rollback(proj, d2)  # control: the created file itself is removed
    assert not d2.exists()


# ---------------------------------------------------------------- U13 (review of 0.12.0): blind cleanup
def test_U13_a_term_resistant_job_is_killed_when_its_tree_cannot_be_listed(monkeypatch):
    import signal
    import subprocess
    import sys
    import time
    import psutil
    from steward import runner
    p = subprocess.Popen([sys.executable, "-c", "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                          "print('up', flush=True)\ntime.sleep(60)"], start_new_session=True, stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "up"
    monkeypatch.setattr(runner, "_tree", lambda ps: (_ for _ in ()).throw(psutil.AccessDenied(ps.pid)))
    t0 = time.monotonic()
    runner._terminate(p, grace=0.5)
    assert p.wait(timeout=10) == -signal.SIGKILL and time.monotonic() - t0 < 8


def test_U13_cleanup_is_incomplete_when_the_process_table_cannot_be_read(monkeypatch):
    import psutil
    from steward import runner

    def denied():
        raise psutil.AccessDenied()
    monkeypatch.setattr(runner.psutil, "process_iter", denied)
    assert runner._kill_group(999999, "tok", set()) is False
