"""0.22.0 X01: the exchange folder (X01)."""

import hashlib
import json
import os

import pytest

from conftest import codes, one
from test_v090_exchange import _repo, git_needed, sh

pytestmark = git_needed


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_NO_REGISTRY", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


def _commit(repo, message="exchange records"):
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", message)


def _r53(cli, repo):
    _, report = cli.check(repo, "governance")
    return one(report, "R-53")


def _unknown(res):
    return sorted(d["path"] for d in res["details"] if d["code"] == "R-53.unknown_entry")


# ---------------------------------------------------------------- X01, ignored files
PLACES = ("exchange", "exchange/inbox", "exchange/outbox")


def test_X01_ignored_verify_1_ignored_ds_store_in_each_folder_passes(cli, tmp_path):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / ".gitignore").write_text(".DS_Store\n")
    _commit(repo, "ignore OS files")
    for place in PLACES:
        (repo / place / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    res = _r53(cli, repo)
    assert res["status"] == "PASS", res
    assert _unknown(res) == []


def test_X01_ignored_verify_2_a_tracked_ds_store_still_fails(cli, tmp_path):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / ".gitignore").write_text(".DS_Store\n")
    for place in PLACES:
        (repo / place / ".DS_Store").write_bytes(b"Bud1")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "add", "-f", *[f"{p}/.DS_Store" for p in PLACES])
    sh(repo, "git", "commit", "-qm", "commit OS files")
    res = _r53(cli, repo)
    assert res["status"] == "FAIL"
    assert _unknown(res) == sorted(f"{p}/.DS_Store" for p in PLACES)


def test_X01_ignored_verify_3_an_unknown_unignored_file_still_fails(cli, tmp_path):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / ".gitignore").write_text(".DS_Store\n")
    _commit(repo, "ignore OS files")
    (repo / "exchange/notes.txt").write_text("x")
    (repo / "exchange/.DS_Store").write_bytes(b"Bud1")
    res = _r53(cli, repo)
    assert res["status"] == "FAIL"
    assert _unknown(res) == ["exchange/notes.txt"]


def test_an_ignored_unknown_file_is_skipped_by_git_check_ignore(cli, tmp_path):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / ".gitignore").write_text("*.swp\nscratch/\n")
    _commit(repo, "ignore editor files")
    (repo / "exchange/inbox/x.swp").write_text("x")
    (repo / "exchange/scratch").mkdir()
    (repo / "exchange/scratch/a.txt").write_text("x")
    assert _r53(cli, repo)["status"] == "PASS"
    sh(repo, "git", "add", "-f", "exchange/scratch/a.txt")
    sh(repo, "git", "commit", "-qm", "track one file")
    assert _unknown(_r53(cli, repo)) == ["exchange/scratch"]  # a folder holding a tracked file is checked


@pytest.mark.parametrize("name", [".DS_Store", "Thumbs.db", "desktop.ini", "._outbox"])
def test_X01_os_metadata_an_untracked_os_metadata_file_passes_without_a_gitignore(cli, tmp_path, name):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / "exchange" / name).write_bytes(b"\x00meta")
    res = _r53(cli, repo)
    assert res["status"] == "PASS", res
    _, out, _ = cli("check", "--repo", repo, "--summary")
    assert "FAIL 0 " in out and "unknown_entry" not in out


def test_X01_os_metadata_an_untracked_appledouble_item_file_is_not_read_as_an_item(cli, tmp_path):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / "exchange/outbox/._ABC-REQ-001.md").write_bytes(b"\x00\x05\x16\x07Mac OS X")
    assert _r53(cli, repo)["status"] == "PASS"
    sh(repo, "git", "add", "-f", "exchange/outbox/._ABC-REQ-001.md")
    sh(repo, "git", "commit", "-qm", "commit it")
    assert "R-53.invalid" in codes(_r53(cli, repo))  # tracked: checked as an item, as before


def test_X01_os_metadata_verify_the_commit_hook_passes_with_an_untracked_ds_store(cli, tmp_path, monkeypatch):
    repo = _repo(cli, tmp_path / "p", "ABC")
    (repo / "exchange/.DS_Store").write_bytes(b"Bud1")
    _, out, _ = cli("check", "--repo", repo, "--summary")
    assert "FAIL 0 " in out and "unknown_entry" not in out
    monkeypatch.chdir(repo)
    rc, _, err = cli("hooks", "run", "pre-commit")
    assert rc == 0, err
    sh(repo, "git", "add", "-f", "exchange/.DS_Store")  # staged, so tracked: the hook blocks it
    assert cli("hooks", "run", "pre-commit")[0] != 0
    sh(repo, "git", "rm", "-q", "--cached", "exchange/.DS_Store")
    (repo / "exchange/stray.md.txt").write_text("x")
    sh(repo, "git", "add", "-f", "exchange/stray.md.txt")
    sh(repo, "git", "commit", "-qm", "a tracked unknown file")
    assert _unknown(_r53(cli, repo)) == ["exchange/stray.md.txt"]


def test_outside_git_only_os_metadata_names_are_skipped(cli, tmp_path, monkeypatch):
    r = tmp_path / "plain"
    r.mkdir()
    cli("init", "--repo", r)
    (r / "steward.toml").write_text((r / "steward.toml").read_text() + '\n[exchange]\ncode = "ABC"\n')
    monkeypatch.chdir(r)
    assert cli("exchange", "init")[0] == 0
    (r / "exchange/.DS_Store").write_bytes(b"Bud1")
    (r / "exchange/notes.txt").write_text("x")
    _, report = cli.check(r)
    assert _unknown(one(report, "R-53")) == ["exchange/notes.txt"]


# ---------------------------------------------------------------- X01, edited received items
def _pair(cli, tmp_path):
    sender = _repo(cli, tmp_path / "sender", "ABC", 'peers = { DEF = "../receiver" }\n')
    receiver = _repo(cli, tmp_path / "receiver", "DEF")
    rc, out, err = cli("exchange", "new", "request", "--repo", sender, "--to", "DEF", "--title", "A request")
    assert rc == 0, err
    iid = out.split(":", 1)[0]
    _commit(sender)
    commit = sh(sender, "git", "rev-parse", "HEAD")
    assert cli("exchange", "pull", "--repo", receiver)[0] == 0
    _commit(receiver)
    return sender, receiver, iid, commit


def _mismatch(res):
    return [d for d in res["details"] if d["code"] == "R-53.receipt_mismatch"]


def test_X01_edited_received_verify_an_edited_received_item_is_named_before_any_response(cli, tmp_path):
    sender, receiver, iid, commit = _pair(cli, tmp_path)
    path = sender / f"exchange/outbox/{iid}.md"
    received = path.read_bytes()
    assert _mismatch(_r53(cli, sender)) == []
    path.write_bytes(received + b"\nA reviewer's fix.\n")
    assert not list((receiver / "exchange/responses").glob("*.md"))  # no response yet
    res = _r53(cli, sender)
    found = _mismatch(res)
    assert res["status"] == "INCOMPLETE" and [d["value"] for d in found] == [iid]
    message = found[0]["message"]
    assert hashlib.sha256(received).hexdigest() in message
    assert hashlib.sha256(path.read_bytes()).hexdigest() in message
    assert commit in message and f"git show {commit}:exchange/outbox/{iid}.md" in message
    assert "re-file the revision under a new ID" in message
    _commit(sender, "the edit, committed")
    assert _mismatch(_r53(cli, sender))  # committing the edit does not clear it

    path.write_bytes(received)  # restore the received bytes
    res = _r53(cli, sender)
    assert _mismatch(res) == [] and res["status"] == "PASS", res


def test_X01_edited_received_an_unreceived_item_may_be_edited_freely(cli, tmp_path):
    sender = _repo(cli, tmp_path / "sender", "ABC", 'peers = { DEF = "../receiver" }\n')
    _repo(cli, tmp_path / "receiver", "DEF")
    rc, out, _ = cli("exchange", "new", "request", "--repo", sender, "--to", "DEF", "--title", "A request")
    iid = out.split(":", 1)[0]
    path = sender / f"exchange/outbox/{iid}.md"
    path.write_bytes(path.read_bytes() + b"\nMore.\n")
    assert _mismatch(_r53(cli, sender)) == []


def test_X01_edited_received_exchange_status_json_is_unchanged(cli, tmp_path):
    sender, _, iid, _ = _pair(cli, tmp_path)
    path = sender / f"exchange/outbox/{iid}.md"
    path.write_bytes(path.read_bytes() + b"\nEdited.\n")
    _, out, _ = cli("exchange", "status", "--repo", sender, "--json")
    row = next(r for r in json.loads(out) if r["id"] == iid)
    assert row["delivery"] == {"peer": "DEF", "state": "changed"}
