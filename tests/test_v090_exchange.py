"""0.9.0, sections C and D: the exchange protocol step 2 and release notices (RELEASE_v0.9.0_SPEC §3, §4)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _repo(cli, path, code, extra=""):
    path.mkdir()
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.name", "T")
    sh(path, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", path)
    with open(path / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "{code}"\n{extra}')
    cwd = os.getcwd()
    os.chdir(path)
    try:
        cli("exchange", "init")
    finally:
        os.chdir(cwd)
    sh(path, "git", "add", "-A")
    sh(path, "git", "commit", "-qm", "init")
    return path


@pytest.fixture
def pair(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    peer = _repo(cli, tmp_path / "peer", "CCC")
    me = _repo(cli, tmp_path / "me", "STW", 'peers = { CCC = "../peer" }\n')
    monkeypatch.chdir(peer)
    cli("exchange", "new", "request", "--to", "STW", "--title", "A generic need")
    cli("exchange", "new", "request", "--to", "XYZ", "--title", "Not for STW")
    sh(peer, "git", "add", "-A")
    sh(peer, "git", "commit", "-qm", "items")
    monkeypatch.chdir(me)
    return me, peer


# ---------------------------------------------------------------- C1: pull
@git_needed
def test_C1_pull_takes_committed_items_addressed_here_and_writes_nothing_to_the_peer(cli, pair):
    me, peer = pair
    before = sh(peer, "git", "status", "--porcelain")
    code, out, err = cli("exchange", "pull", "CCC")
    assert code == 0, err
    assert (me / "exchange/inbox/CCC-REQ-001.md").is_file()
    assert not (me / "exchange/inbox/CCC-REQ-002.md").exists()   # addressed to another project
    assert sh(peer, "git", "status", "--porcelain") == before
    log = [json.loads(l) for l in (me / "exchange/log.jsonl").read_text().splitlines()]
    rec = next(e for e in log if e.get("item") == "CCC-REQ-001")
    assert rec["state"] == "acknowledged" and len(rec["received"]["commit"]) == 40 and len(rec["received"]["sha256"]) == 64
    code, out, _ = cli("exchange", "pull")  # again: nothing new
    assert code == 0 and "already received" in out


@git_needed
def test_C1_pull_reads_the_committed_revision_not_the_working_tree(cli, pair):
    me, peer = pair
    p = peer / "exchange/outbox/CCC-REQ-001.md"
    p.write_text(p.read_text().replace("A generic need", "Uncommitted edit"))
    cli("exchange", "pull", "CCC")
    assert "A generic need" in (me / "exchange/inbox/CCC-REQ-001.md").read_text()


@git_needed
def test_C1_an_ineligible_peer_is_refused_with_the_one_way_fallback(cli, pair, tmp_path):
    me, _ = pair
    plain = tmp_path / "plain"
    plain.mkdir()
    sh(plain, "git", "init", "-q", "-b", "main")
    (plain / "README.md").write_text("x\n")
    sh(plain, "git", "add", "-A")
    sh(plain, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    toml = (me / "steward.toml").read_text().replace('peers = { CCC = "../peer" }', 'peers = { CCC = "../peer", EXT = "../plain" }')
    (me / "steward.toml").write_text(toml)
    code, out, err = cli("exchange", "pull", "EXT")
    assert code != 0 and "not eligible" in err and "--oneway" in err


@git_needed
def test_C1_an_item_changed_at_the_peer_is_not_replaced(cli, pair):
    me, peer = pair
    cli("exchange", "pull", "CCC")
    p = peer / "exchange/outbox/CCC-REQ-001.md"
    p.write_text(p.read_text() + "\nmore\n")
    sh(peer, "git", "commit", "-qam", "edit")
    first = (me / "exchange/inbox/CCC-REQ-001.md").read_bytes()
    code, out, _ = cli("exchange", "pull", "CCC")
    assert "changed at the peer" in out and (me / "exchange/inbox/CCC-REQ-001.md").read_bytes() == first


# ---------------------------------------------------------------- C2: respond, R-54
@git_needed
def test_C2_respond_writes_a_response_and_the_state_together(cli, pair):
    me, _ = pair
    cli("exchange", "pull", "CCC")
    code, out, err = cli("exchange", "respond", "CCC-REQ-001", "verified", "--note", "reproduced on 0.9.0.dev0")
    assert code == 0, err
    rsp = me / "exchange/responses/STW-RSP-001.md"
    assert rsp.is_file() and 'responds_to = "CCC-REQ-001"' in rsp.read_text() and "reproduced on 0.9.0.dev0" in rsp.read_text()
    code, _, err = cli("exchange", "respond", "CCC-REQ-001", "shipped", "--note", "v9")  # verified -> shipped is invalid
    assert code != 0 and not (me / "exchange/responses/STW-RSP-002.md").exists()


@git_needed
def test_C2_R54_an_edited_inbox_item_fails(cli, pair):
    me, _ = pair
    cli("exchange", "pull", "CCC")
    _, rep = cli.check(me, "governance")
    assert one(rep, "R-54")["status"] == "PASS", one(rep, "R-54")
    p = me / "exchange/inbox/CCC-REQ-001.md"
    p.write_text(p.read_text() + "\nlocal edit\n")
    _, rep = cli.check(me, "governance")
    res = one(rep, "R-54")
    assert res["status"] == "FAIL" and "R-54.inbox_edited" in codes(res), res


@git_needed
def test_C2_R54_an_acknowledged_item_without_a_decision_is_incomplete_after_ack_days(cli, pair, monkeypatch):
    import datetime as dt
    me, _ = pair
    cli("exchange", "pull", "CCC")
    from steward import process

    class Later(dt.date):
        @classmethod
        def today(cls):
            return dt.date.today() + dt.timedelta(days=30)
    monkeypatch.setattr(process, "_today", Later.today)
    _, rep = cli.check(me, "governance")
    res = one(rep, "R-54")
    assert res["status"] == "INCOMPLETE" and "R-54.no_decision" in codes(res), res


def test_C2_R54_not_configured(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path, "governance")
    assert one(rep, "R-54")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- C3: outbox bodies against public term lists
@git_needed
def test_C3_R53_an_outbox_body_with_a_public_term_fails(cli, pair):
    me, _ = pair
    with open(me / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "policy"\nfile = "development/policy.txt"\npublic = true\n')
    (me / "development/policy.txt").write_text("AcmeHost\n")
    cli("exchange", "new", "request", "--to", "CCC", "--title", "Plain title")
    p = me / "exchange/outbox/STW-REQ-001.md"
    p.write_text(p.read_text() + "\nWe saw it on AcmeHost.\n")
    _, rep = cli.check(me, "governance")
    res = one(rep, "R-53")
    assert res["status"] == "FAIL" and "R-53.public_term" in codes(res), res


# ---------------------------------------------------------------- D1, D2: release notices
CHANGELOG = """# Changelog

## 1.2.0 (2026-11-23): things
### Added
- a thing
### Known issues
- K1 something
### Upgrade notes (from 1.1.0)
- rename X to Y

## 1.1.0
- older
"""


@pytest.fixture
def library(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    consumer = _repo(cli, tmp_path / "consumer", "CCC", 'uses = { STW = "1.1.0" }\npeers = { STW = "../lib" }\n')
    lib = _repo(cli, tmp_path / "lib", "STW", 'consumers = ["CCC", "EXT"]\npeers = { CCC = "../consumer" }\n')
    (lib / "CHANGELOG.md").write_text(CHANGELOG)
    sh(lib, "git", "add", "-A")
    sh(lib, "git", "commit", "-qm", "1.2.0")
    sh(lib, "git", "tag", "v1.2.0")
    monkeypatch.chdir(lib)
    return lib, consumer


@git_needed
def test_D1_announce_writes_one_notice_per_consumer_with_the_upgrade_notes(cli, library):
    lib, _ = library
    code, out, err = cli("exchange", "announce", "v1.2.0", "--previous", "v1.1.0")
    assert code == 0, err
    notice = (lib / "exchange/outbox/STW-REL-001.md").read_text()
    assert 'kind = "release"' in notice and 'to = "CCC"' in notice and 'version = "1.2.0"' in notice
    assert "rename X to Y" in notice and "K1 something" in notice and "1.1.0\n- older" not in notice
    oneway = (lib / "exchange/oneway/STW-REL-002.md").read_text()  # EXT is not a peer: one-way, to export
    assert 'to = "EXT"' in oneway and "channel" in oneway
    _, rep = cli.check(lib, "governance")
    assert one(rep, "R-53")["status"] == "PASS", one(rep, "R-53")


@git_needed
def test_D1_announce_refuses_without_upgrade_notes_or_tag(cli, library):
    lib, _ = library
    assert cli("exchange", "announce", "v9.9.9")[0] != 0
    (lib / "CHANGELOG.md").write_text(CHANGELOG.replace("### Upgrade notes (from 1.1.0)\n- rename X to Y\n", ""))
    sh(lib, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qam", "notes removed")
    sh(lib, "git", "tag", "-f", "v1.2.0")  # 0.13.0 (U7): announce reads the changelog at the tag
    code, _, err = cli("exchange", "announce", "v1.2.0")
    assert code != 0 and "Upgrade notes" in err


@git_needed
def test_D2_the_consumer_pulls_acknowledges_and_sees_upgrade_available(cli, library, monkeypatch):
    lib, consumer = library
    cli("exchange", "announce", "v1.2.0")
    sh(lib, "git", "add", "-A")
    sh(lib, "git", "commit", "-qm", "notices")
    monkeypatch.chdir(consumer)
    assert cli("exchange", "pull", "STW")[0] == 0
    _, rep = cli.check(consumer, "governance")
    res = one(rep, "R-53")
    assert "R-53.upgrade_available" in codes(res) and res["status"] == "PASS", res  # never blocks
    code, _, err = cli("exchange", "state", "STW-REL-001", "adopted", "--note", "parity: development/parity.md")
    assert code == 0, err
    _, rep = cli.check(consumer, "governance")
    assert "R-53.upgrade_available" not in codes(one(rep, "R-53"))


# ---------------------------------------------------------------- D3: constitution version 2 (Muiz, 2026-11-23)
def test_D3_constitution_version_2_has_article_vii_4_and_lists_its_change(cli, tmp_path):
    from conftest import REPO
    code, out, _ = cli("constitution", "--version")
    assert code == 0 and out.strip() == "2"
    text = (REPO / "CONSTITUTION.md").read_text()
    assert "4. A release notifies each consumer it declares" in text
    _, changes, _ = cli("constitution", "--changes")
    assert "2 (Bio-STEWARD 0.9.0" in changes and "Article VII.4" in changes
    cli("init", "--repo", tmp_path)
    assert 'constitution = "2"' in (tmp_path / "steward.toml").read_text()


def test_D3_a_project_on_version_1_is_told_to_read_the_changes(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    p = tmp_path / "steward.toml"
    p.write_text(p.read_text().replace('constitution = "2"', 'constitution = "1"'))
    _, rep = cli.check(tmp_path, "governance")
    res = one(rep, "R-51")
    assert res["status"] == "INCOMPLETE" and "R-51.version_differs" in codes(res)


# ---------------------------------------------------------------- re-filing: IDs a peer recorded are never reused
@git_needed
def test_new_ids_skip_those_a_peer_has_recorded_for_this_code(cli, pair, monkeypatch):
    me, peer = pair
    # the peer's ledger names CCC-REQ-001 and CCC-REQ-002 (pulled from CCC), so CCC's next ID skips past a migrated one
    monkeypatch.chdir(me)
    cli("exchange", "pull", "CCC")
    from steward import exchange as xc
    led = xc.ledger(me, "r")
    led.append("state", {"item": "CCC-REQ-007", "state": "acknowledged", "from_state": None, "note": "migrated", "by": "STW"})
    sh(me, "git", "add", "-A")
    sh(me, "git", "commit", "-qm", "migrated id")
    toml = (peer / "steward.toml").read_text().replace('code = "CCC"\n', 'code = "CCC"\npeers = { STW = "../me" }\n')
    (peer / "steward.toml").write_text(toml)
    monkeypatch.chdir(peer)
    code, out, err = cli("exchange", "new", "request", "--to", "STW", "--title", "next")
    assert code == 0, err
    assert "CCC-REQ-008" in out
