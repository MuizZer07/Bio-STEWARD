"""0.14.0: the known issues of 0.13.0 (review 1677b00: V5, V7, V9, V14, V15, the partially verified 0.12.0 notes)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, one


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_NO_REGISTRY", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return tmp_path


# ---------------------------------------------------------------- V5: the machine registry
def test_V5_init_registers_and_concurrent_registrations_all_survive(cli, home):
    from steward import cleanup as cu
    (home / "a").mkdir()
    cli("init", "--repo", home / "a")
    assert [p.name for p in cu.registered()] == ["a"]
    import sys
    procs = []
    for i in range(6):
        d = home / f"p{i}"
        d.mkdir()
        cli("init", "--repo", d)
    (home / "home/projects.toml").unlink()
    code = ("import sys\nfrom pathlib import Path\nfrom steward import cleanup as cu\nfrom steward.models import load_config\n"
            "cu.register(Path(sys.argv[1]), load_config(Path(sys.argv[1])))\n")
    env = {**os.environ}
    for i in range(6):
        procs.append(subprocess.Popen([sys.executable, "-c", code, str(home / f"p{i}")], env=env))
    for p in procs:
        assert p.wait(timeout=60) == 0
    assert sorted(p.name for p in cu.registered()) == [f"p{i}" for i in range(6)]


@pytest.mark.parametrize("text", ["projects = 3\n", "projects = [1, 2]\n", "nonsense [[\n"])
def test_V5_a_malformed_registry_is_an_empty_one(home, text):
    from steward import cleanup as cu
    (home / "home").mkdir()
    (home / "home/projects.toml").write_text(text)
    assert cu.registered() == []


def test_V5_a_peer_and_a_relative_cache_setting_are_found_as_users(cli, home, monkeypatch):
    from steward import cleanup as cu
    monkeypatch.setattr(cu, "SHARED_DEFAULTS", ())
    me, peer = home / "me", home / "peer"
    for d in (me, peer):
        d.mkdir()
        cli("init", "--repo", d)
    (home / "home/projects.toml").unlink()  # not registered: found as an [exchange] peer
    (peer / ".env").write_text("HF_HOME=../shared-scratch\n")
    (home / "shared-scratch").mkdir()
    with open(me / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "MEE"\npeers = {{ PER = "../peer" }}\n\n[storage]\n[storage.clean]\n'
                f'paths = ["{home / "shared-scratch"}"]\nregistry = false\n')
    monkeypatch.chdir(me)
    code, out, _ = cli("storage", "scan", "--json")
    c = next(v for v in json.loads(out)["candidates"] if v["cls"] == "declared")
    assert "project peer" in c["users"], c


# ---------------------------------------------------------------- V7: partial deletions are recorded; no links
from test_v0130_storage import _plan, _tty, proj  # noqa: E402,F401


def test_V7_a_partial_deletion_is_recorded(cli, proj, monkeypatch):
    from steward import cleanup as cu
    from steward.ledger import verify
    (proj / "src/pkg/__pycache__/b.pyc").write_bytes(b"y" * 500)
    plan = _plan(cli, proj, "python")
    real_delete = cu.delete

    def half(e):
        (proj / "src/pkg/__pycache__/m.pyc").unlink()
        raise OSError("permission denied on b.pyc")
    monkeypatch.setattr(cu, "delete", half)
    _tty(monkeypatch, ["y"] * 3)
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "partly deleted" in out
    led = verify(proj / "development/storage-cleanup.jsonl")
    rec = [e for e in led.entries if e["kind"] != "genesis"]
    assert [e["kind"] for e in rec] == ["partial"] and rec[0]["bytes"] == 1000


def test_V7_the_plan_folder_is_never_a_link(cli, proj, tmp_path):
    (proj / ".steward").mkdir(exist_ok=True)
    (tmp_path / "elsewhere").mkdir()
    (proj / ".steward/cleanup").symlink_to(tmp_path / "elsewhere")
    try:
        code = cli("storage", "clean", "--plan")[0]
    except Exception:  # noqa: BLE001 - a refusal either way
        code = 1
    assert code != 0 and list((tmp_path / "elsewhere").iterdir()) == []


# ---------------------------------------------------------------- V9: final checks; a broken exchange ledger
def test_V9_a_submission_milestone_uses_final_checks(cli, proj, monkeypatch):
    import datetime as dt
    from steward import engine
    seen = []
    real = engine.run_check
    monkeypatch.setattr("steward.engine.run_check", lambda *a, **k: (seen.append(k.get("final")), real(*a, **k))[1])
    due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).replace(microsecond=0).isoformat()
    (proj / "development/milestones.toml").write_text(
        f'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "s"\ntitle = "s"\ndue = {due}\nkind = "submission"\n'
        'gate = "default"\n')
    _, out, _ = cli("timeline")
    assert seen == [True] and "(final checks)" in out


def test_V9_a_broken_exchange_ledger_is_unavailable_evidence(cli, proj):
    import datetime as dt
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    cli("exchange", "init")
    cli("exchange", "new", "request", "--to", "BBB", "--title", "x")
    with open(proj / "exchange/log.jsonl", "a") as f:
        f.write("{broken\n")
    due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).replace(microsecond=0).isoformat()
    (proj / "development/milestones.toml").write_text(
        f'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "s"\ntitle = "s"\ndue = {due}\nitems = ["AAA-REQ-001"]\n')
    _, out, _ = cli("timeline", "--json")
    row = json.loads(out)["milestones"][0]
    assert row["progress"]["items"].get("error") and row["state"] != "ready"


# ---------------------------------------------------------------- V14: watch waits; non-watch returns
from test_v0130_sprint import _sprint, _status  # noqa: E402
from test_v0130_sprint import repo as srepo  # noqa: E402,F401


def test_V14_watch_waits_for_a_future_window_then_runs(cli, srepo, monkeypatch):
    import datetime as dt
    from steward import sprint as sp
    from steward.models import load_config
    _sprint(srepo, dispatch="auto", start=1, end=8)
    sf = sp.load(srepo, "day1")
    clock = {"t": sf.sprint.window.start - dt.timedelta(seconds=1)}
    sleeps = []

    def fake_sleep(x):
        sleeps.append(x)
        clock["t"] += dt.timedelta(seconds=max(x, 1))
        if len(sleeps) > 200:
            sp.led(srepo, "day1", load_config(srepo).steward.repo_id).append("stop", {"now": False})
    monkeypatch.setattr(sp.time, "sleep", fake_sleep)
    sp.dispatch(srepo, load_config(srepo), sf, watch=True, poll=1, now=lambda: clock["t"], out=lambda *_: None)
    assert sleeps and _status(cli)["T1"] in ("done", "failed")


def test_V14_without_watch_a_held_task_returns_at_once(cli, srepo):
    import time as _t
    _sprint(srepo, dispatch="auto")
    cli("sprint", "hold", "day1", "T1")
    t0 = _t.monotonic()
    _, out, _ = cli("sprint", "start", "day1")
    assert _t.monotonic() - t0 < 5 and "held" in out


# ---------------------------------------------------------------- V15: sprint rules bind ledger, plan and report
def test_V15_a_foreign_ledger_a_bad_transition_and_a_stale_report_are_found(cli, srepo):
    from steward import sprint as sp
    from steward.models import load_config
    _sprint(srepo, dispatch="auto", start=-3, end=8)
    cli("sprint", "start", "day1")
    _, rep = cli.check(srepo, "sprints")
    assert one(rep, "R-71")["status"] == "PASS", one(rep, "R-71")
    led = sp.led(srepo, "day1", load_config(srepo).steward.repo_id)
    led.append("state", {"task": "T3", "state": "done"})  # done without running or checking
    _, rep = cli.check(srepo, "sprints")
    assert "R-71.bad_transition" in codes(one(rep, "R-71"))


def test_V15_an_old_report_is_stale(cli, srepo):
    _sprint(srepo, dispatch="auto", start=-3, end=8)
    cli("sprint", "start", "day1")
    cli("sprint", "report", "day1")
    t = (srepo / "development/sprints/day1.toml").read_text()
    end = t.split("end = ")[1].split(" }")[0]
    import datetime as dt
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).replace(microsecond=0).isoformat()
    (srepo / "development/sprints/day1.toml").write_text(t.replace(end, past))
    _, rep = cli.check(srepo, "sprints")
    assert "R-72.stale_report" in codes(one(rep, "R-72"))  # the window in the report changed
    cli("sprint", "report", "day1")
    _, rep = cli.check(srepo, "sprints")
    assert one(rep, "R-72")["status"] == "PASS"


# ---------------------------------------------------------------- the partially verified 0.12.0 notes
def test_U7_a_fence_closes_only_with_its_own_marker():
    from steward.exchange import delivered_ids
    sec = "### Fixed\n```\n~~~\nAAA-REQ-002 inside\n```\n- AAA-REQ-001\n"
    assert delivered_ids(sec, {"AAA-REQ-001", "AAA-REQ-002"}) == ["AAA-REQ-001"]


def test_U6_a_link_chained_by_0_12_is_restored(cli, home, monkeypatch):
    r = home / "h"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    hooks = r / ".git/hooks"
    for f in hooks.glob("*.sample"):
        f.unlink()
    (home / "orig.sh").write_text("#!/bin/sh\necho mine\n")
    (hooks / "pre-commit").symlink_to(home / "orig.sh")
    monkeypatch.chdir(r)
    assert cli("hooks", "install", "--chain")[0] == 0
    man = json.loads((hooks / ".steward-hooks.json").read_text())
    man["pre-commit"]["local_sha256"] = None  # as 0.12.0 recorded a linked original
    (hooks / ".steward-hooks.json").write_text(json.dumps(man))
    cli("hooks", "remove")
    assert (hooks / "pre-commit").is_symlink() and not (hooks / "pre-commit.local").exists()


def test_U15_the_manifest_output_never_overwrites_the_citation(cli, tmp_path, monkeypatch):
    import zipfile
    repo, rel = tmp_path / "repo", tmp_path / "rel"
    repo.mkdir()
    rel.mkdir()
    cli("init", "--repo", repo)
    (repo / "CITATION.cff").write_text("cff-version: 1.2.0\n")
    with zipfile.ZipFile(rel / "pkg-1.0-py3-none-any.whl", "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
    monkeypatch.chdir(repo)
    assert cli("release", "manifest", "--dist", rel, "--output", repo / "CITATION.cff")[0] == 64
    assert (repo / "CITATION.cff").read_text() == "cff-version: 1.2.0\n"


def test_S9_the_reference_lists_each_code_with_its_remedy():
    from conftest import REPO
    text = (REPO / "docs/reference/rules.md").read_text()
    assert "`R-53.missing_entry`: run: steward exchange init" in text


def test_R4_session_end_removes_only_the_cache_it_checked(cli, home):
    from steward import session as ss
    from steward.models import load_config
    r = home / "c"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    (r / ".steward/cache").mkdir(parents=True)
    (r / ".steward/cache/x").write_text("x")
    report = ss.end(r, load_config(r))
    assert "removed .steward/cache/" in report and not (r / ".steward/cache").exists()
    assert not [p for p in (r / ".steward").iterdir() if p.name.endswith(".removing")]


def test_U5_a_response_kept_when_its_state_reached_the_ledger(cli, home, monkeypatch):
    from steward import exchange as xc
    from test_v0120_features import _item
    r = home / "x"
    r.mkdir()
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    monkeypatch.chdir(r)
    cli("exchange", "init")
    assert cli("exchange", "receive", _item(r, "BBB-REQ-001"))[0] == 0
    real = xc.set_state

    def wrote_then_failed(*a, **k):
        real(*a, **k)
        raise OSError("fsync failed")
    monkeypatch.setattr(xc, "set_state", wrote_then_failed)
    try:
        code = cli("exchange", "respond", "BBB-REQ-001", "verified", "--note", "seen")[0]
    except OSError:
        code = 1
    assert code != 0 and list((r / "exchange/responses").glob("AAA-RSP-*.md"))
