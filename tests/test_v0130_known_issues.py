"""0.13.0: the known issues of 0.12.0 (review 1eb02cd: U5, U6, U7, U9, U14, U15 and the partially verified notes)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, one
from test_v0120_features import CHANGELOG, _item, _receiver, xproj  # noqa: F401
from test_v0120_features import gsh


# ---------------------------------------------------------------- U7
def test_U7_an_id_in_a_code_block_is_not_delivered():
    from steward.exchange import delivered_ids
    sec = "### Fixed\n- AAA-REQ-001 done\n```\nexample: AAA-REQ-002\n```\n"
    assert delivered_ids(sec, {"AAA-REQ-001", "AAA-REQ-002"}) == ["AAA-REQ-001"]


def test_U7_announce_reads_the_changelog_at_the_tag(cli, xproj):
    _receiver(cli, xproj)
    (xproj / "CHANGELOG.md").write_text(CHANGELOG.replace("BBB-REQ-001", "nothing"))  # uncommitted edit
    code, out, err = cli("exchange", "announce", "v1.0.0")
    assert code == 0 and "BBB-REQ-001: shipped" in out, err


def test_U7_a_notice_from_another_project_never_marks_this_item_shipped(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "mine")[0] == 0
    notice = xc.render({"schema": "steward.exchange/1", "id": "CCC-REL-001", "kind": "release", "from": "CCC", "to": "AAA",
                        "title": "Release v2.0.0", "filed": __import__("datetime").date(2026, 11, 24), "version": "2.0.0",
                        "tag": "v2.0.0", "breaking": False}, "\n## Shipped items\n- AAA-REQ-001\n")
    p = xproj / "drop/CCC-REL-001.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(notice)
    assert cli("exchange", "receive", p)[0] == 0
    _, st, _ = cli("exchange", "status")
    assert "shipped" not in [l for l in st.splitlines() if l.startswith("AAA-REQ-001")][0]


# ---------------------------------------------------------------- U15
def test_U15_the_manifest_output_never_overwrites_an_artifact_or_goes_through_a_link(cli, tmp_path, monkeypatch):
    import zipfile
    repo, rel = tmp_path / "repo", tmp_path / "rel"
    repo.mkdir()
    rel.mkdir()
    cli("init", "--repo", repo)
    whl = rel / "pkg-1.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
    before = whl.read_bytes()
    monkeypatch.chdir(repo)
    code, _, err = cli("release", "manifest", "--dist", rel, "--output", whl)
    assert code == 64 and whl.read_bytes() == before
    (tmp_path / "linkdir").symlink_to(rel)
    code, _, _ = cli("release", "manifest", "--dist", rel, "--output", tmp_path / "linkdir" / "m.json")
    assert code == 64 and not (rel / "m.json").exists()
    assert cli("release", "manifest", "--dist", rel, "--output", rel / "m.json")[0] == 0  # control


# ---------------------------------------------------------------- U9, U14
def test_U9_pull_imports_nothing_the_peer_does_not_record_as_received(cli, tmp_path, monkeypatch):
    import datetime
    from steward import exchange as xc
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    a, b = tmp_path / "a", tmp_path / "b"
    for r, c in ((a, "AAA"), (b, "BBB")):
        r.mkdir()
        gsh(r, "git", "init", "-q", "-b", "main")
        cli("init", "--repo", r)
        with open(r / "steward.toml", "a") as f:
            f.write(f'\n[exchange]\ncode = "{c}"\n' + ('peers = { BBB = "../b" }\n' if c == "AAA" else ""))
        cli("exchange", "init", "--repo", r)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA", "to": "BBB",
                      "title": "planted", "filed": datetime.date(2026, 11, 1)}, "## Need\nx\n")
    (b / "exchange/inbox/AAA-REQ-001.md").write_text(orig)  # no record of receiving it in B's ledger
    rsp = xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB", "to": "AAA",
                     "title": "Re", "filed": datetime.date(2026, 11, 2), "responds_to": "AAA-REQ-001"}, "\n## Decision\naccepted: x\n")
    (b / "exchange/responses/BBB-RSP-001.md").write_text(rsp)
    for r in (a, b):
        gsh(r, "git", "add", "-A")
        gsh(r, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    monkeypatch.chdir(a)
    cli("exchange", "pull", "BBB")
    assert not (a / "exchange/outbox/AAA-REQ-001.md").exists()


def test_U14_allowed_and_refused_occurrences_count_the_same_in_any_order():
    import re
    from types import SimpleNamespace
    from steward.privacy import Term, scan_text
    rule = SimpleNamespace(path="a.css", term=1, context="x{term}y", max=1, sha256=None)
    t = Term("p", 1, "video", re.compile(r"video"), True, [rule])
    one_line = scan_text("xvideoy video\n", [t], False, rel="a.css")[0]
    swapped = scan_text("video xvideoy\n", [t], False, rel="a.css")[0]
    assert len(one_line) == len(swapped) == 1
    then = scan_text("video xvideoy\nxvideoy\n", [t], False, rel="a.css")[0]
    assert [h["line"] for h in then] == [1, 2]  # max = 1 was used on line 1 in both orders


# ---------------------------------------------------------------- U6: hook recovery
@pytest.fixture
def hrepo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    r = tmp_path / "h"
    r.mkdir()
    cli("init", "--repo", r)
    gsh(r, "git", "init", "-q", "-b", "main")
    for f in (r / ".git/hooks").glob("*.sample"):
        f.unlink()
    monkeypatch.chdir(r)
    return r


MINE = b"#!/bin/sh\necho the user's own\n"


def test_U6_a_failed_forced_replacement_never_lets_remove_delete_the_user_hook(hrepo, monkeypatch):
    from steward import hooks as hk
    hooks = hrepo / ".git/hooks"
    (hooks / "pre-commit").write_bytes(MINE)
    real = hk._HooksDir.write

    def failing(self, name, data, mode):
        if name == "pre-commit":
            raise OSError("disk full")
        return real(self, name, data, mode)
    monkeypatch.setattr(hk._HooksDir, "write", failing)
    with pytest.raises(OSError):
        hk.install(hrepo, [], "default", force=True)
    monkeypatch.setattr(hk._HooksDir, "write", real)
    hk.remove(hrepo)
    assert (hooks / "pre-commit").read_bytes() == MINE


@pytest.mark.parametrize("rec", ['{"pre-commit": {"sha256": "x"}}', '{"pre-commit": {"sha256": "' + "a" * 64 + '", "chained": "yes"}}',
                                 '{"other": {"sha256": "' + "a" * 64 + '"}}'])
def test_U6_a_manifest_record_with_a_wrong_field_is_refused(cli, hrepo, rec):
    (hrepo / ".git/hooks/.steward-hooks.json").write_text(rec)
    code, out, err = cli("hooks", "remove")
    assert code != 0 and "not a valid steward hooks manifest" in out + err


def test_U6_a_substituted_link_is_not_restored(cli, hrepo, tmp_path):
    hooks = hrepo / ".git/hooks"
    (tmp_path / "a.sh").write_bytes(MINE)
    (tmp_path / "b.sh").write_bytes(b"#!/bin/sh\necho swapped\n")
    (hooks / "pre-commit").symlink_to(tmp_path / "a.sh")
    assert cli("hooks", "install", "--chain")[0] == 0
    (hooks / "pre-commit.local").unlink()
    (hooks / "pre-commit.local").symlink_to(tmp_path / "b.sh")
    _, out, _ = cli("hooks", "remove")
    assert "changed since it was chained" in out and (hooks / "pre-commit.local").is_symlink()


def test_U6_chained_removal_restores_in_one_rename(cli, hrepo, monkeypatch):
    from steward import hooks as hk
    hooks = hrepo / ".git/hooks"
    (hooks / "pre-commit").write_bytes(MINE)
    assert cli("hooks", "install", "--chain")[0] == 0
    calls = []
    real_unlink = hk._HooksDir.unlink
    monkeypatch.setattr(hk._HooksDir, "unlink", lambda self, n: (calls.append(n), real_unlink(self, n)))
    hk.remove(hrepo)
    assert "pre-commit" not in calls and (hooks / "pre-commit").read_bytes() == MINE


# ---------------------------------------------------------------- R18: a record flag without its hash
def test_R18_record_bound_true_without_a_hash_is_stale(cli, tmp_path, monkeypatch):
    import zipfile
    cli("init", "--repo", tmp_path)
    for name, text in (("CITATION.cff", "cff-version: 1.2.0\ntitle: x\nmessage: x\nauthors: []\n"), ("LICENSE", "MIT\n"),
                       ("README.md", "# x\n")):
        (tmp_path / name).write_text(text)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\nbundles = "bundles"\n')
    (tmp_path / "dist").mkdir()
    with zipfile.ZipFile(tmp_path / "dist/pkg-1.0-py3-none-any.whl", "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/a.txt").write_text("a\n")
    monkeypatch.chdir(tmp_path)
    assert cli("release", "bundle", "b", "--paths", "data")[0] == 0
    assert cli("release", "manifest")[0] == 0
    m = json.loads((tmp_path / "release-manifest.json").read_text())
    m["bundles"]["b"]["record_sha256"] = None
    m["bundles"]["b"]["record_bound"] = True
    (tmp_path / "release-manifest.json").write_text(json.dumps(m))
    _, rep = cli.check(tmp_path, "release")
    assert "R-42.bundle_record_stale" in codes(one(rep, "R-42"))


# ---------------------------------------------------------------- U5: rollback and a recorded receipt
def test_U5_a_restored_entry_never_replaces_one_that_appeared_meanwhile(cli, xproj):
    from steward import exchange as xc
    dest = xc.write_new(xproj, "outbox", "AAA-REQ-009.md", b"mine\n")
    dest.unlink()
    dest.write_text("swapped in\n")
    real_rename = os.rename

    def rename_then_race(src, dst, **kw):
        real_rename(src, dst, **kw)
        if str(src).endswith("AAA-REQ-009.md") and ".rollback" in str(dst):
            (xproj / "exchange/outbox/AAA-REQ-009.md").write_text("appeared meanwhile\n")
    import pytest as _p
    with _p.MonkeyPatch.context() as m:
        m.setattr(os, "rename", rename_then_race)
        xc.rollback(xproj, dest)
    assert dest.read_text() == "appeared meanwhile\n"
    left = [p for p in dest.parent.iterdir() if p.name.endswith(".rollback")]
    assert len(left) == 1 and left[0].read_text() == "swapped in\n"  # kept aside, never deleted


def test_U5_an_item_whose_receipt_was_written_is_kept_when_the_write_reports_an_error(cli, xproj, monkeypatch):
    from steward import exchange as xc
    real = xc.set_state

    def wrote_then_failed(*a, **k):
        real(*a, **k)
        raise OSError("fsync failed after the append")
    monkeypatch.setattr(xc, "set_state", wrote_then_failed)
    with pytest.raises(OSError):
        xc.receive(xproj, "r", "AAA", _item(xproj, "BBB-REQ-005").read_bytes(), {"from": "file"})
    monkeypatch.setattr(xc, "set_state", real)
    assert (xproj / "exchange/inbox/BBB-REQ-005.md").is_file() and xc.states(xproj).get("BBB-REQ-005")


# ---------------------------------------------------------------- S9: remedies of helper-built and f-string codes
def test_S9_a_code_built_through_a_helper_or_beside_an_fstring_has_its_remedy():
    from steward.cli import code_fixes
    f = code_fixes("R-53")
    assert f["R-53.missing_entry"] == "run: steward exchange init"
    assert f["R-53.oneway_channel"] == "a one-way item names its channel"


# ---------------------------------------------------------------- R4: lock release without a name window
def test_R4_releasing_a_lock_never_removes_a_file_that_replaced_it(cli, tmp_path):
    from steward.fsutil import owner_lock, release_owner_lock
    cli("init", "--repo", tmp_path)
    fd = owner_lock(tmp_path, "run-x")
    lock = tmp_path / ".steward/owners/run-x.lock"
    lock.unlink()
    lock.write_text("someone else's\n")
    release_owner_lock(tmp_path, "run-x", fd)
    assert lock.read_text() == "someone else's\n"
    assert not [p for p in lock.parent.iterdir() if p.name.endswith(".aside")]
    fd = owner_lock(tmp_path, "run-y")
    release_owner_lock(tmp_path, "run-y", fd)  # control
    assert not (tmp_path / ".steward/owners/run-y.lock").exists()
