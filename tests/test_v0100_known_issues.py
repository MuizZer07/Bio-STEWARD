"""0.10.0 K1 - K7: the known issues of 0.9.0 (RELEASE_v0.10.0_SPEC §1a; re-verification of f895128)."""

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


def git(root):
    sh(root, "git", "init", "-q", "-b", "main")
    sh(root, "git", "config", "user.name", "T")
    sh(root, "git", "config", "user.email", "t@example.org")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "init")


# ---------------------------------------------------------------- K1 (R3): ownership locks
def test_K1_a_held_lock_is_listed_and_a_released_one_is_not(proj):
    from steward import fsutil
    fd = fsutil.owner_lock(proj, "run-x")
    held = dict(fsutil.held_owner_locks(proj))
    assert held["run-x"]["pid"] == os.getpid()
    fsutil.release_owner_lock(proj, "run-x", fd)
    assert "run-x" not in dict(fsutil.held_owner_locks(proj))


def test_K1_a_stale_lock_file_is_removed_and_signals_nothing(proj):
    from steward import fsutil
    (proj / ".steward/owners").mkdir(parents=True)
    (proj / ".steward/owners/mcp-1.lock").write_text(json.dumps({"pid": os.getpid(), "created": 0}))
    assert fsutil.held_owner_locks(proj) == [] and not (proj / ".steward/owners/mcp-1.lock").exists()


# ---------------------------------------------------------------- K2 (R4): held descriptors
def test_K2_cache_removal_never_follows_a_linked_cache(cli, proj, tmp_path):
    from steward import session as ss
    from steward.models import load_config
    with open(proj / "steward.toml", "a") as f:
        f.write("\n[session]\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("x")
    (proj / ".steward").mkdir(exist_ok=True)
    (proj / ".steward/cache").symlink_to(outside)
    ss.end(proj, load_config(proj))
    assert (outside / "keep").is_file()


# ---------------------------------------------------------------- K3 (R5): hook ownership by manifest
@git_needed
def test_K3_a_hook_that_merely_contains_the_marks_is_not_steward_s(cli, proj):
    from steward import hooks as hk
    git(proj)
    hooks = proj / ".git/hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text(hk.render_chained("pre-commit", "default", []))  # look-alike, not installed
    (hooks / "pre-commit.local").write_text("#!/bin/sh\nexit 0\n")
    cli("hooks", "remove")
    assert (hooks / "pre-commit").exists() and (hooks / "pre-commit.local").exists()  # nothing restored or removed


@git_needed
def test_K3_install_then_remove_round_trips_through_the_manifest(cli, proj):
    git(proj)
    hooks = proj / ".git/hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    original = (hooks / "pre-commit").read_bytes()
    assert cli("hooks", "install", "--chain")[0] == 0
    assert json.loads((hooks / ".steward-hooks.json").read_text())["pre-commit"]["chained"] is True
    cli("hooks", "remove")
    assert (hooks / "pre-commit").read_bytes() == original and not (hooks / ".steward-hooks.json").exists()


# ---------------------------------------------------------------- K4 (R6): rollback in the held directory
def test_K4_rollback_works_through_the_descriptor_held_since_creation(cli, proj, tmp_path):
    from steward import exchange as xc
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "ABC"\n')
    cli("exchange", "init")
    dest = xc.write_new(proj, "outbox", "ABC-REQ-050.md", b"x")
    moved = tmp_path / "moved-outbox"
    shutil.move(str(proj / "exchange/outbox"), str(moved))  # the directory is replaced after creation
    (proj / "exchange/outbox").mkdir()
    (proj / "exchange/outbox/ABC-REQ-050.md").write_text("another file")
    xc.rollback(proj, dest)
    assert (proj / "exchange/outbox/ABC-REQ-050.md").read_text() == "another file"  # untouched
    assert not (moved / "ABC-REQ-050.md").exists()                                  # the created one is gone


# ---------------------------------------------------------------- K5 (R20): only the job's processes
def test_K5_a_process_in_a_reused_group_without_the_token_is_not_the_jobs():
    from steward import runner as rn
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
    try:
        assert rn._members(other.pid, "not-its-token", set()) == []
    finally:
        other.kill()


# ---------------------------------------------------------------- K6 (Q7): hooks through the held descriptor
@git_needed
def test_K6_install_writes_through_the_checked_directory(cli, proj, tmp_path, monkeypatch):
    from steward import hooks as hk
    git(proj)
    real_init = hk._HooksDir.__init__
    swapped = {}

    def init(self, root, create):  # replace the hooks directory right after it was checked and opened
        real_init(self, root, create)
        hooks = proj / ".git/hooks"
        shutil.move(str(hooks), str(tmp_path / "old-hooks"))
        (tmp_path / "decoy").mkdir()
        hooks.symlink_to(tmp_path / "decoy")
        swapped["done"] = True
    monkeypatch.setattr(hk._HooksDir, "__init__", init)
    cli("hooks", "install")
    assert swapped and not any((tmp_path / "decoy").iterdir())  # nothing written through the substituted path
    assert (tmp_path / "old-hooks" / "pre-commit").is_file()     # written in the directory that was checked


# ---------------------------------------------------------------- K7: the medium findings
def test_K7_R1_an_unknown_rule_in_an_overlay_gate_is_refused(cli, proj):
    (proj / "steward.local.toml").write_text('[gates.default]\nrequire = ["R-999"]\n')
    _, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "FAIL"


def test_K7_R1_a_malformed_base_gate_table_is_a_config_error_not_a_crash(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[gates]\npush = "not a table"\n')
    (proj / "steward.local.toml").write_text('[gates.push]\nrequire = ["R-01"]\n')
    code, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "FAIL" and code != 70


def test_K7_R10_an_old_acknowledgement_stays_overdue_after_a_fresh_verification(cli, proj, monkeypatch):
    import datetime as dt
    from steward import exchange as xc
    from steward import process
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    cli("exchange", "init")
    item = ('+++\nschema = "steward.exchange/1"\nid = "BBB-REQ-001"\nkind = "request"\nfrom = "BBB"\nto = "AAA"\n'
            'title = "t"\nfiled = 2026-11-01\n+++\n')
    xc.receive(proj, "r", "AAA", item.encode(), {"from": "file"})
    monkeypatch.setattr(process, "_today", lambda: dt.date.today() + dt.timedelta(days=30))
    xc.set_state(proj, "r", "BBB-REQ-001", "verified", "reproduced", "AAA", False)  # today's verification
    _, rep = cli.check(proj, "governance")
    assert "R-54.no_decision" in codes(one(rep, "R-54"))


def test_K7_R14_the_frozen_writer_needs_a_heading_not_a_mention(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[frozen]]\nname = "a"\nfiles = ["agents/**"]\n')
    (proj / "agents").mkdir()
    (proj / "agents/p.md").write_text("v1\n")
    cli("frozen", "record", "a")
    before = (proj / "development/frozen/a.json").read_bytes()
    (proj / "agents/p.md").write_text("v2\n")
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\nWe discussed 2026-11-24: new prompt but did not decide.\n")
    assert cli("frozen", "record", "a", "--decision", "2026-11-24: new prompt")[0] == 64
    assert (proj / "development/frozen/a.json").read_bytes() == before


def test_K7_R18_a_malformed_image_list_is_unreadable():
    import io
    import tarfile
    from steward import containers as ct
    buf = io.BytesIO()
    data = json.dumps([{"RepoTags": "app:1.0"}]).encode()  # a string, not a list
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "a.tar"
    p.write_bytes(buf.getvalue())
    assert ct.archive_tags(p) is None


# ---------------------------------------------------------------- review of d04235b: S1 - S3
def test_S1_denied_process_enumeration_never_hides_the_outcome(cli, proj, monkeypatch):
    import psutil
    from steward import runner as rn

    def denied(*a, **k):
        raise psutil.AccessDenied()
    monkeypatch.setattr(psutil, "process_iter", denied)
    assert rn._kill_group(999999, "t", set()) in (True, False)  # never raises
    code, _, err = cli("run", "--", sys.executable, "-c", "pass")
    assert code == 0, err
    log = [json.loads(l) for l in (proj / "development/runs.jsonl").read_text().splitlines()]
    assert any(e.get("kind") == "outcome" for e in log)


def test_S2_a_damaged_pin_never_falls_back_to_the_working_tree(cli, proj, tmp_path):
    from steward import authorize as az
    from steward.models import load_config
    with open(proj / "steward.toml", "a") as f:
        f.write("\n[policy]\n")
    az.trust_file().parent.mkdir(parents=True, exist_ok=True)
    az.trust_file().write_bytes(b"\xff\xfe not toml")
    cfg = load_config(proj)
    assert az.resolve_trust(proj, cfg).source == "unreadable"
    with pytest.raises(az.AuthError):
        az.verify(proj, cfg, "steward/auth/x", action="waive", consumed=set())
    _, rep = cli.check(proj, "policy")
    assert one(rep, "R-33")["status"] == "UNKNOWN"


def test_S3_a_hard_linked_or_foreign_lock_file_is_never_taken_over_or_deleted(proj, tmp_path):
    from steward import fsutil
    owners = proj / ".steward/owners"
    owners.mkdir(parents=True)
    precious = tmp_path / "precious.txt"
    precious.write_text("keep")
    os.link(precious, owners / "run-x.lock")
    assert fsutil.owner_lock(proj, "run-x") is None
    assert fsutil.held_owner_locks(proj) == [] and precious.read_text() == "keep" and (owners / "run-x.lock").exists()


def test_S3_release_leaves_a_replaced_entry_alone(proj):
    from steward import fsutil
    fd = fsutil.owner_lock(proj, "run-y")
    p = proj / ".steward/owners/run-y.lock"
    p.rename(proj / ".steward/owners/moved.lock")
    p.write_text("someone else")
    fsutil.release_owner_lock(proj, "run-y", fd)
    assert p.read_text() == "someone else"
