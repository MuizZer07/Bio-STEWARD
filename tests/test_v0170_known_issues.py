"""0.17.0: the open known issues fixed before the tag (Muiz: "Try fixing those first")."""

import json
import os

import pytest

from conftest import codes, one
from test_v0140_known_issues import home, sh  # noqa: F401


def test_V5_a_registry_with_any_non_string_entry_is_empty(home):
    from steward import cleanup as cu
    (home / "home").mkdir()
    (home / "home/projects.toml").write_text('projects = ["/a", 3]\n')
    assert cu.registered() == []


def test_X5_W9_registration_reads_and_writes_inside_the_held_folder(cli, home, monkeypatch):
    from steward import cleanup as cu
    from steward.models import load_config
    p = home / "p"
    p.mkdir()
    cli("init", "--repo", p)
    monkeypatch.setattr(cu, "registered", lambda: (_ for _ in ()).throw(AssertionError("read by path")))
    cu.register(p, load_config(p))  # the existing list is read through the held folder, not registered()
    assert '"' + str(p.resolve()) + '"' in (home / "home/projects.toml").read_text()


def test_V15_a_state_before_a_later_opened_record_is_reported(cli, home, monkeypatch):
    from test_v0130_sprint import _sprint
    from steward import sprint as sp
    from steward.models import load_config
    r = home / "s"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    _sprint(r)
    led = sp.led(r, "day1", load_config(r).steward.repo_id)
    led.append("state", {"task": "T1", "state": "running"})
    led.append("opened", {"sprint": "day1", "tasks": ["T1", "T2", "T3"], "dispatch": "order"})
    _, rep = cli.check(r, "sprints")
    assert "R-71.not_opened" in codes(one(rep, "R-71"))


def test_U7_a_backtick_opener_with_a_backtick_in_its_info_is_not_a_fence():
    from steward.exchange import delivered_ids
    sec = "### Fixed\n``` x`y\n- AAA-REQ-001\n"
    assert delivered_ids(sec, {"AAA-REQ-001"}) == ["AAA-REQ-001"]


def test_U15_a_dist_lock_behind_a_linked_folder_is_not_read(tmp_path):
    from steward import release as rl
    d = tmp_path / "dist"
    (d / "real").mkdir(parents=True)
    (d / "real/req.lock").write_text("x\n")
    (d / "linked").symlink_to(d / "real")
    assert rl._in_dist(d, "real/req.lock") and not rl._in_dist(d, "linked/req.lock")


def test_R4_a_cache_replaced_meanwhile_is_left_aside_never_renamed_back(cli, home, monkeypatch):
    from steward import session as ss
    from steward.models import load_config
    r = home / "c"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    (r / ".steward/cache").mkdir(parents=True)
    real_rename = os.rename

    def swap(src, dst, **kw):
        if src == "cache" and str(dst).endswith(".removing"):
            os.rmdir(r / ".steward/cache")
            (r / ".steward/cache").mkdir()  # another folder appears under the name just before the move
        return real_rename(src, dst, **kw)
    monkeypatch.setattr(os, "rename", swap)
    report = ss.end(r, load_config(r))
    assert any("not the cache that was checked" in line for line in report)


def test_AA8_a_malformed_registry_keeps_the_shared_confirmation(cli, home, monkeypatch):
    from steward import cleanup as cu
    (home / "home").mkdir()
    (home / "home/projects.toml").write_text('projects = ["/a", 3]\n')
    c = cu.Candidate("declared", "x", str(home), "dir", 1, "/", False)
    cu.users(home, [c])
    assert any(u.startswith("project use:") for u in c.users)


def test_AA9_a_linked_payload_entry_is_never_current(tmp_path, monkeypatch):
    import sys
    from conftest import REPO
    sys.path.insert(0, str(REPO / "tools"))
    import build_plugin as bp
    out = tmp_path / "plugin"
    monkeypatch.setattr(bp, "OUT", out)
    assert bp.main(False) == 0 and bp.main(True) == 0
    target = tmp_path / "copy.md"
    f = out / "skills/using-steward/SKILL.md"
    target.write_bytes(f.read_bytes())
    f.unlink()
    f.symlink_to(target)  # identical bytes, through a link
    assert bp.main(True) == 1
