"""0.8.1: the exchange protocol, step 1 (DESIGN_exchange_protocol; constitution Article V)."""

import json

import pytest

from conftest import append, codes, one


@pytest.fixture
def ex(cli, tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    cli("init", "--repo", r)
    append(r, "steward.toml", '\n[exchange]\ncode = "ABC"\n')
    monkeypatch.chdir(r)
    assert cli("exchange", "init")[0] == 0
    return r


def r53(cli, root):
    _, rep = cli.check(root)
    return one(rep, "R-53")


def test_init_makes_the_fixed_layout(ex):
    for sub in ("outbox", "inbox", "responses", "oneway"):
        assert (ex / "exchange" / sub).is_dir()
    assert "ABC" in (ex / "exchange/README.md").read_text()


def test_new_item_is_filed_with_the_next_id_and_its_state_in_the_ledger(cli, ex):
    code, out, _ = cli("exchange", "new", "request", "--to", "STW", "--title", "Shared run slots", "--against", "v0.7.0")
    assert code == 0 and "ABC-REQ-001" in out
    assert (ex / "exchange/outbox/ABC-REQ-001.md").is_file()
    cli("exchange", "new", "request", "--to", "STW", "--title", "Second")
    assert (ex / "exchange/outbox/ABC-REQ-002.md").is_file()
    code, out, _ = cli("exchange", "status", "--json")
    rows = {r["id"]: r for r in json.loads(out)}
    assert rows["ABC-REQ-001"]["state"] == "filed"
    assert r53(cli, ex)["status"] == "PASS"


def test_states_follow_the_machine_and_decisions_need_a_note(cli, ex):
    cli("exchange", "new", "request", "--to", "STW", "--title", "x")
    # 0.9.0 (DEF-025): a requester may record the receiver's outcome (shipped, adopted) from filed; the receiver's
    # own steps (verified, accepted) are still not the requester's to record
    code, _, err = cli("exchange", "state", "ABC-REQ-001", "verified", "--note", "v9")
    assert code == 64 and "not a valid transition" in err
    code, _, err = cli("exchange", "state", "ABC-REQ-001", "acknowledged")
    assert code == 0
    code, _, err = cli("exchange", "state", "ABC-REQ-001", "verified")
    assert code == 64 and "--note" in err


def test_a_hand_edited_state_or_unknown_file_is_caught(cli, ex):
    cli("exchange", "new", "request", "--to", "STW", "--title", "x")
    (ex / "exchange/stray.txt").write_text("x")
    res = r53(cli, ex)
    assert res["status"] == "FAIL" and "R-53.unknown_entry" in codes(res)


def test_an_invalid_item_fails(cli, ex):
    (ex / "exchange/outbox/ABC-REQ-009.md").write_text('+++\nschema = "steward.exchange/1"\nid = "ABC-FB-009"\n+++\n')
    res = r53(cli, ex)
    assert res["status"] == "FAIL" and "R-53.invalid" in codes(res)


def test_receive_takes_a_peer_item_read_only_and_never_writes_to_the_peer(cli, ex, tmp_path):
    peer = tmp_path / "peer"
    (peer / "exchange/outbox").mkdir(parents=True)
    item = peer / "exchange/outbox/XYZ-DEF-004.md"
    item.write_text('+++\nschema = "steward.exchange/1"\nid = "XYZ-DEF-004"\nkind = "defect"\nfrom = "XYZ"\nto = "ABC"\n'
                    'title = "A defect"\nfiled = 2026-11-23\nagainst = "v0.7.0"\nreproduced = "yes: a test"\n+++\n## Need\nx\n')
    before = item.read_bytes()
    assert cli("exchange", "receive", item)[0] == 0
    assert (ex / "exchange/inbox/XYZ-DEF-004.md").read_bytes() == before and item.read_bytes() == before
    code, out, _ = cli("exchange", "status", "--json")
    assert {r["id"]: r["state"] for r in json.loads(out)}["XYZ-DEF-004"] == "acknowledged"
    code, _, err = cli("exchange", "receive", ex / "exchange/inbox/XYZ-DEF-004.md")
    assert code != 0  # already received: an inbox item is never replaced


def test_an_item_addressed_elsewhere_is_refused(cli, ex, tmp_path):
    item = tmp_path / "XYZ-REQ-001.md"
    item.write_text('+++\nschema = "steward.exchange/1"\nid = "XYZ-REQ-001"\nkind = "request"\nfrom = "XYZ"\nto = "QQQ"\n'
                    'title = "t"\nfiled = 2026-11-23\n+++\n')
    code, _, err = cli("exchange", "receive", item)
    assert code == 64 and "QQQ" in err


def test_a_response_must_answer_an_inbox_item(cli, ex):
    (ex / "exchange/responses/ABC-RSP-001.md").write_text(
        '+++\nschema = "steward.exchange/1"\nid = "ABC-RSP-001"\nkind = "response"\nfrom = "ABC"\nto = "XYZ"\n'
        'title = "re"\nfiled = 2026-11-23\nresponds_to = "XYZ-REQ-404"\n+++\n')
    res = r53(cli, ex)
    assert res["status"] == "FAIL" and "R-53.orphan_response" in codes(res)


def test_one_way_items_need_a_channel_and_export_plain_text(cli, ex):
    code, out, _ = cli("exchange", "new", "request", "--to", "EXT", "--title", "Upstream fix", "--oneway",
                       "--channel", "https://example.org/issues/1")
    assert code == 0 and (ex / "exchange/oneway/ABC-REQ-001.md").is_file()
    assert cli("exchange", "state", "ABC-REQ-001", "sent", "--note", "issue filed")[0] == 0
    code, out, _ = cli("exchange", "export", "ABC-REQ-001")
    assert code == 0 and "Upstream fix" in out and "+++" not in out and "steward" not in out.lower()
    assert r53(cli, ex)["status"] == "PASS"


def test_shipped_names_a_tag_that_exists(cli, ex):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=ex, check=True)
    item = ex / "XYZ-REQ-002.md"
    item.write_text('+++\nschema = "steward.exchange/1"\nid = "XYZ-REQ-002"\nkind = "request"\nfrom = "XYZ"\nto = "ABC"\n'
                    'title = "t"\nfiled = 2026-11-23\n+++\n')
    cli("exchange", "receive", item)
    for state, note in (("verified", "reproduced"), ("accepted", "v0.9.0")):
        assert cli("exchange", "state", "XYZ-REQ-002", state, "--note", note)[0] == 0
    # 0.12.0 (FB-016): shipped is refused while the tag does not exist
    assert cli("exchange", "state", "XYZ-REQ-002", "shipped", "--note", "v0.9.0")[0] == 64
    for c in (["git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "x"],
              ["git", "tag", "v0.9.0"]):
        subprocess.run(c, cwd=ex, check=True)
    assert cli("exchange", "state", "XYZ-REQ-002", "shipped", "--note", "v0.9.0")[0] == 0
    subprocess.run(["git", "tag", "-d", "v0.9.0"], cwd=ex, check=True, capture_output=True)  # removed later
    res = r53(cli, ex)
    assert res["status"] == "INCOMPLETE" and "R-53.tag_missing" in codes(res)


def test_not_configured_is_not_applicable(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-53")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- 0.8.1 review: N4 (high), N5, N6
def _item(path, iid="XYZ-REQ-005"):
    path.write_text(f'+++\nschema = "steward.exchange/1"\nid = "{iid}"\nkind = "request"\nfrom = "XYZ"\nto = "ABC"\n'
                    'title = "t"\nfiled = 2026-11-23\n+++\n')
    return path


@pytest.mark.parametrize("link", ["inbox", "exchange", "ledger"])
def test_N4_no_exchange_write_follows_a_link_out_of_the_repository(cli, ex, tmp_path, link):
    import shutil
    outside = tmp_path / "outside"
    outside.mkdir()
    if link == "inbox":
        shutil.rmtree(ex / "exchange/inbox")
        (ex / "exchange/inbox").symlink_to(outside)
    elif link == "exchange":
        shutil.move(str(ex / "exchange"), str(outside / "exchange"))
        (ex / "exchange").symlink_to(outside / "exchange")
    else:
        (outside / "log.jsonl").write_text("")
        (ex / "exchange/log.jsonl").symlink_to(outside / "log.jsonl")
    before = sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*"))
    sizes = {p: p.stat().st_size for p in outside.rglob("*") if p.is_file()}
    code, _, err = cli("exchange", "receive", _item(tmp_path / "XYZ-REQ-005.md"))
    assert code != 0 and ("link" in err or "outside" in err), err
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")) == before
    assert {p: p.stat().st_size for p in outside.rglob("*") if p.is_file()} == sizes
    _, rep = cli.check(ex)
    assert one(rep, "R-53")["status"] == "FAIL"


def test_N5_a_failed_ledger_append_leaves_no_item(cli, ex, tmp_path):
    (ex / "exchange/log.jsonl").write_text("{not json\n")
    code, _, _ = cli("exchange", "receive", _item(tmp_path / "XYZ-REQ-006.md", "XYZ-REQ-006"))
    assert code != 0 and not (ex / "exchange/inbox/XYZ-REQ-006.md").exists()


def test_N5_ids_are_never_reused_after_an_item_is_removed(cli, ex):
    cli("exchange", "new", "request", "--to", "STW", "--title", "one")
    (ex / "exchange/outbox/ABC-REQ-001.md").unlink()
    code, out, _ = cli("exchange", "new", "request", "--to", "STW", "--title", "two")
    assert "ABC-REQ-002" in out


def test_N6_missing_layout_entries_are_incomplete(cli, ex):
    import shutil
    shutil.rmtree(ex / "exchange/responses")
    res = r53(cli, ex)
    assert res["status"] == "INCOMPLETE" and "R-53.missing_entry" in codes(res)


def test_N6_export_refuses_a_public_term(cli, ex):
    append(ex, "steward.toml", '\n[[terms]]\nname = "policy"\nfile = "development/policy.txt"\npublic = true\n')
    (ex / "development/policy.txt").write_text("AcmeHost\n")
    cli("exchange", "new", "request", "--to", "EXT", "--title", "Ask AcmeHost upstream", "--oneway", "--channel", "issue")
    code, out, err = cli("exchange", "export", "ABC-REQ-001")
    assert code == 65 and "AcmeHost" not in out and "policy:1" in err


# ---------------------------------------------------------------- re-verification of 7fd0970: O5
def test_O5_init_refuses_a_linked_exchange_root(cli, tmp_path, monkeypatch):
    r = tmp_path / "p2"
    r.mkdir()
    cli("init", "--repo", r)
    append(r, "steward.toml", '\n[exchange]\ncode = "ABC"\n')
    outside = tmp_path / "out"
    outside.mkdir()
    (r / "exchange").symlink_to(outside)
    monkeypatch.chdir(r)
    code, _, err = cli("exchange", "init")
    assert code != 0 and "link" in err and not any(outside.iterdir())


def test_O5_the_ledger_refuses_a_hard_linked_file(cli, ex, tmp_path):
    import os
    other = tmp_path / "external.jsonl"
    other.write_text("")
    os.link(other, ex / "exchange/log.jsonl")
    code, _, err = cli("exchange", "new", "request", "--to", "STW", "--title", "x")
    assert code != 0 and other.read_text() == ""
