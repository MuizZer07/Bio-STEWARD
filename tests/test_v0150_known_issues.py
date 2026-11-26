"""0.15.0: the known issues of 0.14.0 (review 1ea76b2: W4, W8, W9 and the partially verified notes)."""

import json
import os
import subprocess

import pytest

from conftest import codes, one
from test_v0140_known_issues import home, sh  # noqa: F401
from test_v0140_audit import _two


# ---------------------------------------------------------------- W4
def test_W4_a_malformed_peer_table_and_an_invalid_sprint_do_not_stop_the_audit(cli, home, monkeypatch):
    me, them = _two(cli, home, monkeypatch)
    with open(them / "steward.toml", "a") as f:
        f.write('peers = ["not", "a", "table"]\nuses = 3\n')  # appended to its [exchange]
    (me / "development/sprints").mkdir(parents=True)
    (me / "development/sprints/bad.toml").write_text("not a sprint\n")
    code, out, err = cli("audit", "progress", "--json")
    assert code == 0, err
    doc = json.loads(out)
    assert {"sprint": "bad", "unavailable": "its plan is not valid (steward sprint check)"} in doc["pending"]["sprints"]


def test_W4_a_section_that_fails_is_named_and_the_others_shown(cli, home, monkeypatch):
    from steward import audit as au
    me, _ = _two(cli, home, monkeypatch)
    monkeypatch.setattr(au, "reach", lambda root: 1 / 0)
    code, out, _ = cli("audit", "progress")
    reach = out.split("## 4. Reach")[1]
    assert code == 0 and "- unavailable: could not be gathered" in reach
    assert "## 1. Where we are" in out


# ---------------------------------------------------------------- W8
def test_W8_the_timeline_page_rows_and_digest_come_from_one_read(cli, home, monkeypatch):
    import hashlib
    d = home / "site"
    d.mkdir()
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[docs]\npublish = ["overview", "timeline"]\n')
    data = b'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "a"\ntitle = "One"\ndue = 2027-01-20T23:59:00-12:00\n'
    (d / "development/milestones.toml").write_bytes(data)
    monkeypatch.chdir(d)
    assert cli("docs", "build")[0] == 0
    page = (d / "docs/project/timeline.md").read_text()
    assert hashlib.sha256(data).hexdigest()[:12] in page and "| One |" in page


# ---------------------------------------------------------------- W9
def test_W9_a_linked_config_home_parent_is_never_written_through(cli, home, monkeypatch, tmp_path):
    from steward import cleanup as cu
    from steward.models import load_config
    real = tmp_path / "realhome"
    real.mkdir()
    (tmp_path / "linkhome").symlink_to(real)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "linkhome"))
    p = home / "proj"
    p.mkdir()
    cli("init", "--repo", p)
    cu.register(p, load_config(p))  # resolved once, then walked without links: the real folder receives it
    assert (real / "projects.toml").is_file()
    assert not [x for x in real.iterdir() if x.name.endswith(".tmp")]


# ---------------------------------------------------------------- the partially verified notes
def test_U7_a_fence_closes_only_with_one_at_least_as_long_and_nothing_after_it():
    from steward.exchange import delivered_ids
    sec = "### Fixed\n````\n```\nAAA-REQ-002 inside\n``` not a close\n````\n- AAA-REQ-001\n"
    assert delivered_ids(sec, {"AAA-REQ-001", "AAA-REQ-002"}) == ["AAA-REQ-001"]


def test_U5_a_different_later_entry_is_not_taken_for_the_intended_one(cli, home, monkeypatch):
    from steward import exchange as xc
    me, _ = _two(cli, home, monkeypatch)
    dest = xc.write_new(me, "outbox", "AAA-REQ-001.md", b"x\n")
    before = xc.entries_of(me, "AAA-REQ-001")
    xc.set_state(me, "r", "AAA-REQ-001", "filed", None, "AAA", False)
    assert not xc.keep_if_appended(me, dest, "AAA-REQ-001", before, "closed")
    assert xc.keep_if_appended(me, dest, "AAA-REQ-001", before, "filed")


def test_V15_task_states_without_an_opened_record_are_reported(cli, home, monkeypatch):
    from test_v0130_sprint import _sprint
    from steward import sprint as sp
    from steward.models import load_config
    r = home / "s"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    _sprint(r)
    sp.led(r, "day1", load_config(r).steward.repo_id).append("state", {"task": "T1", "state": "running"})
    _, rep = cli.check(r, "sprints")
    assert "R-71.not_opened" in codes(one(rep, "R-71"))


def test_S9_a_fragment_is_never_shown_as_a_remedy():
    from steward.cli import code_fixes
    from steward.rules import RULES
    for r in RULES:
        for code, fix in code_fixes(r).items():
            assert not fix or (len(fix.split()) >= 3 and fix[:1].isalpha()), (code, fix)


def test_U15_a_lock_behind_a_linked_folder_is_not_read(cli, home, monkeypatch):
    from steward import release as rl
    r = home / "rel"
    (r / "real").mkdir(parents=True)
    (r / "real/req.lock").write_text("x\n")
    (r / "linked").symlink_to(r / "real")
    assert rl._in_repo(r, "real/req.lock") and not rl._in_repo(r, "linked/req.lock")


def test_V7_an_unwritable_ledger_refuses_before_deleting(cli, home, monkeypatch):
    from test_v0130_storage import _plan, _tty
    import shutil as _sh
    p = home / "c"
    p.mkdir()
    cli("init", "--repo", p)
    sh(p, "git", "init", "-q", "-b", "main")
    sh(p, "git", "add", "-A")
    sh(p, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    (p / "pkg/__pycache__").mkdir(parents=True)
    (p / "pkg/__pycache__/m.pyc").write_bytes(b"x")
    monkeypatch.chdir(p)
    plan = _plan(cli, p, "python")
    (p / "development/storage-cleanup.jsonl").write_text("")
    os.chmod(p / "development/storage-cleanup.jsonl", 0o444)
    _tty(monkeypatch, ["y"] * 3)
    try:
        code, _, err = cli("storage", "clean", "--apply", plan)
    finally:
        os.chmod(p / "development/storage-cleanup.jsonl", 0o644)
    assert code == 65 and (p / "pkg/__pycache__/m.pyc").exists()



# ---------------------------------------------------------------- review of 0.15.0: X1 - X4, X6, X7
def test_X1_a_declared_lock_the_manifest_could_not_hash_is_not_a_pass(cli, tmp_path, monkeypatch):
    import zipfile
    cli("init", "--repo", tmp_path)
    for name, text in (("CITATION.cff", "cff-version: 1.2.0\ntitle: x\nmessage: x\nauthors: []\n"), ("LICENSE", "MIT\n"),
                       ("README.md", "# x\n")):
        (tmp_path / name).write_text(text)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\nlocks = ["requirements.lock"]\n')
    (tmp_path / "dist").mkdir()
    with zipfile.ZipFile(tmp_path / "dist/pkg-1.0-py3-none-any.whl", "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
    monkeypatch.chdir(tmp_path)
    assert cli("release", "manifest")[0] == 0  # the lock is missing: recorded as null
    _, rep = cli.check(tmp_path, "release")
    res = one(rep, "R-42")
    assert res["status"] != "PASS" and "R-42.lock_unavailable" in codes(res), res


def test_X2_a_dry_run_is_scanned_exactly(cli, home, monkeypatch):
    from steward import session as ss
    seen = []
    real = ss.privacy_hits
    monkeypatch.setattr(ss, "privacy_hits", lambda *a, **k: (seen.append(k.get("preview")), real(*a, **k))[1])
    r = home / "d"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "add", "-A")
    sh(r, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    monkeypatch.chdir(r)
    cli("session", "close", "--decisions-logged", "--next", "x", "--end", "--dry-run", "--allow-dirty")
    assert seen and seen[0] is False


def test_X4_an_unavailable_section_is_shown_as_unavailable_and_the_report_unchanged():
    import copy
    from steward import audit as au
    doc = {"where": {"unavailable": "w"}, "usage": {"note": "n"}, "pending": {"unavailable": "p"},
           "reach": {"present": [], "missing": [], "note": "r"}}
    before = copy.deepcopy(doc)
    a, b = au.render(doc), au.render(doc)
    assert a == b and doc == before and "exchange items open here" not in a and "- unavailable: p" in a


def test_X6_an_id_in_indented_code_is_not_delivered():
    from steward.exchange import delivered_ids
    sec = "### Fixed\n    AAA-REQ-002 in an example\n- AAA-REQ-001\n"
    assert delivered_ids(sec, {"AAA-REQ-001", "AAA-REQ-002"}) == ["AAA-REQ-001"]


def test_X7_one_unresolvable_peer_does_not_hide_the_others(cli, home, monkeypatch):
    from steward import cleanup as cu
    r = home / "pp"
    r.mkdir()
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\npeers = { BAD = "~nouser_xyz_/x", GOOD = "../good" }\n')
    names = [p.name for p in cu._peers(r)]
    assert "good" in names


def test_X3_an_old_plan_is_refused_and_records_nothing(cli, home, monkeypatch):
    from test_v0130_storage import _plan, _tty
    p = home / "op"
    p.mkdir()
    cli("init", "--repo", p)
    sh(p, "git", "init", "-q", "-b", "main")
    sh(p, "git", "add", "-A")
    sh(p, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    (p / "pkg/__pycache__").mkdir(parents=True)
    (p / "pkg/__pycache__/m.pyc").write_bytes(b"x")
    monkeypatch.chdir(p)
    plan = _plan(cli, p, "python")
    doc = json.loads(plan.read_text())
    for e in doc["entries"]:
        e.pop("entries")
    plan.write_text(json.dumps(doc))
    _tty(monkeypatch, ["y"] * 3)
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "older version" in out and (p / "pkg/__pycache__/m.pyc").exists()
    assert not (p / "development/storage-cleanup.jsonl").exists() or "partial" not in (p / "development/storage-cleanup.jsonl").read_text()
