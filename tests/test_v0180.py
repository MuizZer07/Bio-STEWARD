"""0.18.0: FB-018 (superseded / withdrawn received items; term lists checked before receiving), FB-019 (status
shows the furthest observation; the registry opt-out in check --help) and REQ-020 (pin callers by reference)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, one, results
from test_authorize import repo, sh  # noqa: F401  (the pins fixture repository)
from test_v0120_features import _item, gsh, xproj  # noqa: F401
from test_v0140_known_issues import home  # noqa: F401

signing = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")


def _commit(r, msg="x"):
    gsh(r, "git", "add", "-A")
    gsh(r, "git", "commit", "-qm", msg)


def _terms(r, words, public=False):
    (r / "development").mkdir(exist_ok=True)
    (r / "development/terms.txt").write_text("\n".join(words) + "\n")
    with open(r / "steward.toml", "a") as f:
        f.write(f'\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\npublic = {"true" if public else "false"}\n'
                'include = ["exchange/**"]\n')


# ---------------------------------------------------------------- FB-018: superseded and withdrawn
def test_FB_018_superseded_by_a_received_item_lets_the_file_go(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-002"))[0] == 0
    code, out, err = cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "BBB-REQ-002")
    assert code == 0 and "git rm exchange/inbox/BBB-REQ-001.md" in out, err
    from steward import exchange as xc
    last = xc.states(xproj)["BBB-REQ-001"][-1]
    assert last["state"] == "superseded" and last["superseded_by"] == "BBB-REQ-002" and "BBB-REQ-002" in last["note"]
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    r = one(rep, "R-53")
    assert r["status"] == "PASS" and "R-53.removed_after_retirement" in codes(r), r
    _, out, _ = cli("exchange", "status")
    assert "BBB-REQ-001" in out and "(file removed)" in out
    code, out, _ = cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))  # the sender's copy is still there
    assert code == 0 and "superseded here" in out and not (xproj / "exchange/inbox/BBB-REQ-001.md").exists()
    assert cli("exchange", "state", "BBB-REQ-001", "closed")[0] == 0  # the record stays, and can be closed later
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"


def test_FB_018_superseded_needs_a_received_replacement_from_the_same_sender(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    assert cli("exchange", "receive", _item(xproj, "CCC-REQ-001", frm="CCC"))[0] == 0
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "superseded")
    assert code == 64 and "--by" in err
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "BBB-REQ-009")
    assert code == 64 and "inbox" in err
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "CCC-REQ-001")
    assert code == 64 and "not from BBB" in err
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "withdrawn", "--by", "CCC-REQ-001")
    assert code == 64 and "superseded state only" in err
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "withdrawn")
    assert code == 64 and "needs --note" in err
    from steward import exchange as xc
    assert xc.current(xc.states(xproj)["BBB-REQ-001"]) == "acknowledged"  # nothing was recorded


def test_FB_018_withdrawn_with_a_response_and_a_removed_file_passes_r53(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    code, out, err = cli("exchange", "respond", "BBB-REQ-001", "withdrawn", "--note", "closed by its sender")
    assert code == 0 and "response" in out, err
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"


def test_FB_018_control_a_removed_file_without_a_retirement_still_fails(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    r = one(rep, "R-53")
    assert r["status"] == "FAIL" and "R-53.unknown_item" in codes(r)


# ---------------------------------------------------------------- FB-018: term lists before receiving
def test_FB_018_receive_refuses_a_term_hit_names_the_line_and_leaves_the_ledger(cli, xproj):
    _terms(xproj, ["Zebrafinch"])
    p = _item(xproj, "BBB-REQ-001", body="## Need\nplain\nour Zebrafinch pipeline\n")
    before = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    code, _, err = cli("exchange", "receive", p)
    assert code == 65 and "line" in err and "products:1" in err and "--allow-terms" in err
    assert "Zebrafinch" not in err  # a private list's term is never printed
    assert not (xproj / "exchange/inbox/BBB-REQ-001.md").exists()
    after = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    assert after == before
    code, _, err = cli("exchange", "receive", p, "--allow-terms")
    assert code == 0, err
    from steward import exchange as xc
    assert xc.states(xproj)["BBB-REQ-001"][0]["received"]["terms_allowed"] is True


def test_FB_018_a_public_term_and_a_local_path_are_named(cli, xproj):
    _terms(xproj, ["Zebrafinch"], public=True)
    home_path = "/" + "Users" + "/alice/data.csv"
    p = _item(xproj, "BBB-REQ-001", body=f"## Need\nZebrafinch at {home_path}\n")
    code, _, err = cli("exchange", "receive", p)
    assert code == 65 and "(Zebrafinch)" in err and "local path" in err


def test_FB_018_control_a_clean_item_and_an_excluded_path_are_received(cli, xproj):
    _terms(xproj, ["Zebrafinch"])
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001", body="## Need\nplain words\n"))[0] == 0
    t = (xproj / "steward.toml").read_text().replace('include = ["exchange/**"]', 'include = ["docs/**"]')
    (xproj / "steward.toml").write_text(t)
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-002", body="## Need\nZebrafinch\n"))[0] == 0


def test_FB_018_pull_refuses_only_the_item_that_hits(cli, xproj, tmp_path):
    from steward import exchange as xc
    peer = tmp_path / "peer"
    peer.mkdir()
    gsh(peer, "git", "init", "-q", "-b", "main")
    gsh(peer, "git", "config", "user.name", "T")
    gsh(peer, "git", "config", "user.email", "t@example.org")
    (peer / "steward.toml").write_text('[exchange]\ncode = "BBB"\n')
    (peer / "exchange/outbox").mkdir(parents=True)
    for iid, body in (("BBB-REQ-001", "## Need\nZebrafinch\n"), ("BBB-REQ-002", "## Need\nplain\n")):
        (peer / f"exchange/outbox/{iid}.md").write_text(xc.render(
            {"schema": "steward.exchange/1", "id": iid, "kind": "request", "from": "BBB", "to": "AAA",
             "title": f"item {iid}", "filed": __import__("datetime").date(2026, 11, 24)}, body))
    _commit(peer)
    _terms(xproj, ["Zebrafinch"])
    t = (xproj / "steward.toml").read_text().replace('code = "AAA"', f'code = "AAA"\npeers = {{ BBB = "{peer}" }}')
    (xproj / "steward.toml").write_text(t)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "BBB-REQ-001 is not received" in err and "BBB-REQ-002: received" in out
    assert not (xproj / "exchange/inbox/BBB-REQ-001.md").exists()
    code, out, err = cli("exchange", "pull", "BBB", "--allow-terms")
    assert code == 0 and "BBB-REQ-001: received" in out, err
    assert cli("exchange", "state", "BBB-REQ-001", "withdrawn", "--note", "re-filed by the sender")[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    code, out, err = cli("exchange", "pull", "BBB")  # still in the sender's outbox: never received again, never refused
    assert code == 0 and "BBB-REQ-001: already received; withdrawn here" in out, err
    assert not (xproj / "exchange/inbox/BBB-REQ-001.md").exists()


# ---------------------------------------------------------------- FB-019: the furthest observation
def test_FB_019_status_shows_shipped_over_a_later_accepted(cli, xproj):
    from steward import exchange as xc
    code, out, _ = cli("exchange", "new", "request", "--to", "BBB", "--title", "a need")
    iid = out.split(":")[0]
    xc.observe(xproj, "r", iid, "shipped", "BBB", "BBB-REL-011")
    xc.observe(xproj, "r", iid, "accepted", "BBB", "BBB-RSP-077")
    _, out, _ = cli("exchange", "status")
    line = next(x for x in out.splitlines() if x.startswith(iid))
    assert "[BBB: shipped (BBB-REL-011); latest: accepted (BBB-RSP-077)]" in line
    _, out, _ = cli("exchange", "status", "--json")
    row = next(r for r in json.loads(out) if r["id"] == iid)
    assert row["observed"]["state"] == "shipped" and row["observed_latest"]["state"] == "accepted"


def test_FB_019_control_the_latest_wins_a_tie_and_a_later_stage(cli, xproj):
    from steward import exchange as xc
    _, out, _ = cli("exchange", "new", "request", "--to", "BBB", "--title", "a need")
    iid = out.split(":")[0]
    xc.observe(xproj, "r", iid, "accepted", "BBB", "BBB-RSP-001")
    xc.observe(xproj, "r", iid, "deferred", "BBB", "BBB-RSP-002")
    _, out, _ = cli("exchange", "status", "--json")
    row = next(r for r in json.loads(out) if r["id"] == iid)
    assert row["observed"]["state"] == "deferred" and "observed_latest" not in row
    xc.observe(xproj, "r", iid, "shipped", "BBB", "BBB-REL-003")
    _, out, _ = cli("exchange", "status", "--json")
    row = next(r for r in json.loads(out) if r["id"] == iid)
    assert row["observed"]["state"] == "shipped" and "observed_latest" not in row


def test_FB_019_check_help_names_the_registry_opt_out(cli):
    _, out, _ = cli("check", "--help")
    assert "STEWARD_NO_REGISTRY" in out and "[storage.clean]" in out and "registry = false" in out


# ---------------------------------------------------------------- the audit: items not received yet
def test_the_audit_lists_peer_items_not_received_here(cli, home, monkeypatch):
    from steward import exchange as xc
    me, them = home / "me", home / "them"
    for d in (me, them):
        d.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
        cli("init", "--repo", d)
    with open(me / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "AAA"\nconsumers = ["BBB"]\npeers = {{ BBB = "{them}" }}\n')
    with open(them / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "BBB"\n')
    (them / "exchange/outbox").mkdir(parents=True)
    (them / "exchange/outbox/BBB-FB-001.md").write_text(xc.render(
        {"schema": "steward.exchange/1", "id": "BBB-FB-001", "kind": "feedback", "from": "BBB", "to": "AAA",
         "title": "waiting", "filed": __import__("datetime").date(2026, 11, 24)}, "## Need\nx\n"))
    for a in (["add", "-A"], ["-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x"]):
        subprocess.run(["git", *a], cwd=them, check=True)
    monkeypatch.chdir(me)
    cli("exchange", "init")
    code, out, err = cli("audit", "progress", "--json")
    assert code == 0, err
    assert json.loads(out)["usage"]["consumers"]["BBB"]["checkout"]["not_received"] == ["BBB-FB-001"]
    _, text, _ = cli("audit", "progress")
    assert "not received here: BBB-FB-001" in text


# ---------------------------------------------------------------- REQ-020: callers by reference
SHARED = '''
[[pin]]
name = "lib-1"
package = "lib"
version = "1"
artifact = "vendor/wheels/lib-1.whl"
module = "lib"
references = ["vendor/lib_1/"]
install = ["vendor/lib_1"]
deprecated = { reason = "replaced by 2" }

[[pin]]
name = "lib-2"
package = "lib"
version = "2"
artifact = "vendor/wheels/lib-2.whl"
module = "lib"
references = ["vendor/lib_2/"]
install = ["vendor/lib_2"]
deprecated = { reason = "replaced by 3" }
'''


def _shared(r, extra=""):
    for v in ("1", "2"):
        (r / f"vendor/lib_{v}").mkdir(parents=True, exist_ok=True)
        (r / f"vendor/lib_{v}/lib.py").write_text("x = 1\n")
        (r / "vendor/wheels").mkdir(parents=True, exist_ok=True)
        (r / f"vendor/wheels/lib-{v}.whl").write_bytes(f"wheel {v}".encode())
    (r / "a.py").write_text('import sys\nsys.path.insert(0, "vendor/lib_1/")\nimport lib\n')
    (r / "b.py").write_text('import sys\nsys.path.insert(0, "vendor/lib_2/")\nimport lib\n')
    with open(r / "steward.toml", "a") as f:
        f.write(SHARED.replace('deprecated = { reason = "replaced by 2" }', 'deprecated = { reason = "replaced by 2" }' + extra))
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "pins")


def _status(cli):
    code, out, err = cli("pins", "status", "--json")
    assert code == 0, err
    return {p["name"]: p for p in json.loads(out)["pins"]}


@signing
def test_REQ_020_references_tell_callers_of_one_import_name_apart(cli, repo):
    _shared(repo)
    st = _status(cli)
    assert st["lib-1"]["callers"] == ["a.py"] and st["lib-2"]["callers"] == ["b.py"]
    assert st["lib-1"]["caller_rule"] == "references"
    assert st["lib-1"]["caller_detail"] == [{"path": "a.py", "via": "reference"}]
    _, out, _ = cli("pins", "status")
    assert "caller a.py (reference)" in out


@signing
def test_REQ_020_both_rules_and_the_module_rule_alone(cli, repo):
    _shared(repo, '\ncallers = "both"')
    st = _status(cli)
    assert st["lib-1"]["callers"] == ["a.py", "b.py"]  # the module scan finds every `import lib`
    assert {d["path"]: d["via"] for d in st["lib-1"]["caller_detail"]} == {"a.py": "module+reference", "b.py": "module"}
    t = (repo / "steward.toml").read_text().replace('callers = "both"', 'callers = "module"')
    (repo / "steward.toml").write_text(t)
    assert _status(cli)["lib-1"]["callers"] == ["a.py", "b.py"]  # 0.17.0 behaviour


@signing
def test_REQ_020_ignored_callers_are_listed_and_do_not_block(cli, repo):
    _shared(repo, '\nignore_callers = ["audits/**"]')
    (repo / "a.py").unlink()
    (repo / "audits").mkdir()
    (repo / "audits/finished.py").write_text('LOAD = "vendor/lib_1/"\n')
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "an audit kept as evidence")
    st = _status(cli)["lib-1"]
    assert st["callers"] == [] and st["state"] == "retire-eligible"
    assert st["caller_detail"] == [{"path": "audits/finished.py", "via": "reference", "ignored": True}]
    _, rep = cli.check(repo, "pins")
    assert next(x for x in results(rep, "R-74") if x["subject"] == "lib-1")["status"] == "PASS"


@signing
@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_REQ_020_an_unreadable_file_still_blocks_even_when_ignored(cli, repo):
    _shared(repo, '\nignore_callers = ["audits/**"]')
    (repo / "audits").mkdir()
    f = repo / "audits/finished.py"
    f.write_text("x\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "x")
    f.chmod(0)
    try:
        st = _status(cli)["lib-1"]
        assert st["callers"] is None and st["state"] == "deprecated" and "cannot be told" in " ".join(st["reasons"])
    finally:
        f.chmod(0o644)


@signing
def test_REQ_020_the_pins_own_records_are_not_callers(cli, repo):
    _shared(repo)
    (repo / "a.py").unlink()
    (repo / "vendor/lib_1/notes.txt").write_text("vendor/lib_1/ is this pin\n")  # its own install path
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "x")
    assert _status(cli)["lib-1"]["callers"] == []  # steward.toml names the reference too, and is not a caller


@signing
def test_REQ_020_a_submodule_gitlink_is_not_unreadable_evidence(cli, repo, tmp_path):
    _shared(repo)
    (repo / "a.py").unlink()
    sub = tmp_path / "sub"
    sub.mkdir()
    sh(sub, "git", "init", "-q")
    (sub / "f").write_text("x\n")
    sh(sub, "git", "add", "-A")
    sh(sub, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    sh(repo, "git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "ext")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "a submodule")
    assert _status(cli)["lib-1"]["callers"] == []


def test_REQ_020_callers_references_needs_a_references_list():
    from pydantic import ValidationError

    from steward.models import PinSpec
    with pytest.raises(ValidationError, match="references list"):
        PinSpec(name="x", package="x", version="1", artifact="x.whl", callers="references")
    assert PinSpec(name="x", package="x", version="1", artifact="x.whl", module="x").caller_rule == "module"


# ================================================================ the 0.18.0 review (02a6f80): AB1 – AB11
@signing
@pytest.mark.parametrize("swap", ["dir", "link", "linked_parent"])
def test_AB1_a_tracked_caller_that_is_no_longer_its_file_blocks(cli, repo, tmp_path, swap):
    _shared(repo)
    (repo / "sub").mkdir()
    (repo / "sub/c.py").write_text('P = "vendor/lib_1/"\n')
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "a caller in a folder")
    (repo / "a.py").unlink()
    target = repo / ("sub/c.py" if swap != "linked_parent" else "sub")
    shutil.rmtree(target) if target.is_dir() else target.unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "c.py").write_text("nothing here\n")
    if swap == "dir":
        target.mkdir()
    elif swap == "link":
        target.symlink_to(outside / "c.py")
    else:
        target.symlink_to(outside)
    st = _status(cli)["lib-1"]
    assert st["callers"] is None and st["state"] == "deprecated" and "object" not in st
    _, rep = cli.check(repo, "pins")
    assert next(x for x in results(rep, "R-74") if x["subject"] == "lib-1")["status"] == "UNKNOWN"


@signing
def test_AB1_an_unpopulated_gitlink_is_left_out_by_its_index_mode(cli, repo, tmp_path):
    _shared(repo)
    (repo / "a.py").unlink()
    sub = tmp_path / "sub"
    sub.mkdir()
    sh(sub, "git", "init", "-q")
    (sub / "f").write_text("x\n")
    sh(sub, "git", "add", "-A")
    sh(sub, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    sh(repo, "git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "ext")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "a submodule")
    shutil.rmtree(repo / "ext")  # not populated: no folder at all
    assert _status(cli)["lib-1"]["callers"] == []


PEER_RID = "5eed5eed-0000-4000-8000-000000000001"


def _peer(tmp_path, items, inbox=None, ledger=None):
    """A peer repository BBB with committed outbox (and inbox) items."""
    from steward import exchange as xc
    peer = tmp_path / "peer"
    peer.mkdir()
    gsh(peer, "git", "init", "-q", "-b", "main")
    gsh(peer, "git", "config", "user.name", "T")
    gsh(peer, "git", "config", "user.email", "t@example.org")
    (peer / "steward.toml").write_text(f'[steward]\nschema = "steward.toml/0.2"\nrepo_id = "{PEER_RID}"\nproject = "peer"\n\n'
                                       '[exchange]\ncode = "BBB"\n')  # AF13 (0.19.0): the ledger names this repo_id
    for sub, d in (("outbox", items), ("inbox", inbox or {})):
        (peer / f"exchange/{sub}").mkdir(parents=True, exist_ok=True)
        (peer / f"exchange/{sub}/.keep").write_text("")  # git keeps no empty folder
        for iid, text in d.items():
            (peer / f"exchange/{sub}/{iid}.md").write_text(text)
    if ledger is not None:
        (peer / "exchange/log.jsonl").write_bytes(ledger)
    _commit(peer)
    return peer, xc


def _with_peer(xproj, peer):
    t = (xproj / "steward.toml").read_text().replace('code = "AAA"', f'code = "AAA"\npeers = {{ BBB = "{peer}" }}', 1)
    (xproj / "steward.toml").write_text(t)


def test_AB2_a_refused_response_imports_no_original(cli, xproj, tmp_path):
    import hashlib

    from steward import exchange as xc
    from steward.ledger import Ledger
    d = __import__("datetime").date(2026, 11, 24)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA",
                      "to": "BBB", "title": "ours", "filed": d}, "## Need\nplain\n")
    sha = hashlib.sha256(orig.encode()).hexdigest()

    def response(body):
        return xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB",
                          "to": "AAA", "title": "re", "filed": d, "responds_to": "AAA-REQ-001"},
                         f"## Decision\naccepted: {body}\n\n## Answers\nAAA-REQ-001 sha256:{sha}\n")
    scratch = tmp_path / "ledger"
    scratch.mkdir()
    lg = Ledger(scratch / "log.jsonl", "exchange", PEER_RID)
    lg.transaction(lambda _: ("state", {"item": "AAA-REQ-001", "state": "acknowledged", "from_state": None, "note": "",
                                        "by": "BBB", "received": {"from": "file", "sha256": sha}}))
    peer, _ = _peer(tmp_path, {}, inbox={"AAA-REQ-001": orig}, ledger=(scratch / "log.jsonl").read_bytes())
    (peer / "exchange/responses").mkdir()
    (peer / "exchange/responses/BBB-RSP-001.md").write_text(response("Zebrafinch"))
    _commit(peer)
    _terms(xproj, ["Zebrafinch"])
    _with_peer(xproj, peer)
    before = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "is not received" in err
    assert not (xproj / "exchange/outbox/AAA-REQ-001.md").exists()
    after = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    assert after == before
    # control: a clean response imports the original and is received
    (peer / "exchange/responses/BBB-RSP-001.md").write_text(response("planned"))
    _commit(peer)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 0 and (xproj / "exchange/outbox/AAA-REQ-001.md").is_file() and "BBB-RSP-001: received" in out, err


def test_AB2_an_original_that_hits_at_its_outbox_path_is_not_imported(cli, xproj, tmp_path):
    import hashlib

    from steward import exchange as xc
    from steward.ledger import Ledger
    d = __import__("datetime").date(2026, 11, 24)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA",
                      "to": "BBB", "title": "ours", "filed": d}, "## Need\nZebrafinch\n")
    sha = hashlib.sha256(orig.encode()).hexdigest()
    rsp = xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB",
                     "to": "AAA", "title": "re", "filed": d, "responds_to": "AAA-REQ-001"},
                    f"## Decision\naccepted: ok\n\n## Answers\nAAA-REQ-001 sha256:{sha}\n")
    scratch = tmp_path / "ledger"
    scratch.mkdir()
    Ledger(scratch / "log.jsonl", "exchange", PEER_RID).transaction(lambda _: ("state", {
        "item": "AAA-REQ-001", "state": "acknowledged", "from_state": None, "note": "", "by": "BBB",
        "received": {"from": "file", "sha256": sha}}))
    peer, _ = _peer(tmp_path, {}, inbox={"AAA-REQ-001": orig}, ledger=(scratch / "log.jsonl").read_bytes())
    (peer / "exchange/responses").mkdir()
    (peer / "exchange/responses/BBB-RSP-001.md").write_text(rsp)
    _commit(peer)
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/terms.txt").write_text("Zebrafinch\n")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\ninclude = ["exchange/outbox/**"]\n')
    _with_peer(xproj, peer)
    code, _, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "outbox path" in err and "Zebrafinch" not in err
    assert not (xproj / "exchange/outbox/AAA-REQ-001.md").exists() and not (xproj / "exchange/inbox/BBB-RSP-001.md").exists()


def test_AB3_a_recovered_receipt_passes_the_screen(cli, xproj):
    _terms(xproj, ["Zebrafinch"])
    p = _item(xproj, "BBB-REQ-001", body="## Need\nZebrafinch\n")
    (xproj / "exchange/inbox/BBB-REQ-001.md").write_bytes(p.read_bytes())  # left behind, with no state
    before = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    code, _, err = cli("exchange", "receive", p)
    assert code == 65 and "is not received" in err and "Zebrafinch" not in err
    after = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    assert after == before
    code, out, err = cli("exchange", "receive", p, "--allow-terms")
    from steward import exchange as xc
    assert xc.states(xproj)["BBB-REQ-001"][0]["received"]["terms_allowed"] is True


def test_AB4_an_id_matching_a_private_term_is_withheld(cli, xproj, tmp_path):
    _terms(xproj, ["BBB-REQ-007"])
    code, out, err = cli("exchange", "receive", _item(xproj, "BBB-REQ-007"))
    assert code == 65 and "BBB-REQ-007" not in err + out and "withheld" not in err and "its ID matches" in err
    peer, xc = _peer(tmp_path, {"BBB-REQ-007": _item(xproj, "BBB-REQ-007").read_text()})
    _with_peer(xproj, peer)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "BBB-REQ-007" not in err + out


def _legacy_ack(xproj, iid):
    """An inbox item with a pre-0.9.0 acknowledgement: no receipt hash."""
    from steward import exchange as xc
    p = _item(xproj, iid)
    (xproj / f"exchange/inbox/{iid}.md").write_bytes(p.read_bytes())
    xc.set_state(xproj, "r", iid, "acknowledged", "migrated", "AAA", False, "request", place="inbox")
    return p


def test_AB5_a_legacy_receipt_is_not_advised_for_removal_and_r53_agrees(cli, xproj):
    p = _legacy_ack(xproj, "BBB-REQ-001")
    code, out, _ = cli("exchange", "state", "BBB-REQ-001", "withdrawn", "--note", "the sender closed it")
    assert code == 0 and "Keep exchange/inbox/BBB-REQ-001.md" in out and "git rm" not in out
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    assert "R-53.unknown_item" in codes(one(rep, "R-53"))
    code, _, err = cli("exchange", "receive", p)  # never "already received" while its file is missing
    assert code == 65 and "restore it from git" in err
    _, out, _ = cli("exchange", "status")
    assert "(file removed)" not in out


def test_AB6_r53_needs_a_hashed_receipt_and_a_received_replacement(cli, xproj):
    from steward import exchange as xc
    from steward.ledger import Ledger
    lg = Ledger(xproj / "exchange/log.jsonl", "exchange", "r", base=xproj)
    for e in ({"item": "BBB-REQ-001", "state": "acknowledged", "from_state": None, "note": "", "by": "AAA",
               "received": {}},
              {"item": "BBB-REQ-001", "state": "superseded", "from_state": "acknowledged", "note": "x", "by": "AAA"}):
        lg.transaction(lambda _, e=e: ("state", e))
    _, rep = cli.check(xproj)
    assert "R-53.unknown_item" in codes(one(rep, "R-53"))
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-002"))[0] == 0  # a valid one, for the control below
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-003"))[0] == 0
    assert cli("exchange", "state", "BBB-REQ-002", "superseded", "--by", "BBB-REQ-003")[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-002.md").unlink()
    _, rep = cli.check(xproj)
    assert "R-53.removed_after_retirement" in codes(one(rep, "R-53"))
    (xproj / "exchange/inbox/BBB-REQ-003.md").unlink()  # the replacement gone too: no longer accepted
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "FAIL"
    assert xc.retired_receipt("BBB-REQ-001", xc.states(xproj)["BBB-REQ-001"]) is False


def test_AB6_the_cli_needs_a_hashed_receipt_for_the_replacement(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    _legacy_ack(xproj, "BBB-REQ-002")
    code, _, err = cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "BBB-REQ-002")
    assert code == 64 and "receipt with a hash" in err


def test_AB7_a_response_to_a_removed_item_must_bind_the_received_bytes(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    _, out, _ = cli("exchange", "respond", "BBB-REQ-001", "withdrawn", "--note", "closed by its sender")
    rid = out.split("response ")[1].split()[0]
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"
    rp = xproj / f"exchange/responses/{rid}.md"
    t = rp.read_text()
    import re
    rp.write_text(re.sub(r"sha256:[0-9a-f]{64}", "sha256:" + "0" * 64, t))
    _, rep = cli.check(xproj)
    r = one(rep, "R-53")
    assert r["status"] == "FAIL" and "R-53.response_target_mismatch" in codes(r)


def test_AB8_an_item_with_a_nul_byte_is_refused_as_a_format(cli, xproj):
    _terms(xproj, ["Zebrafinch"])
    p = _item(xproj, "BBB-REQ-001", body="## Need\nx\x00y\n")
    code, _, err = cli("exchange", "receive", p)
    assert code == 65 and "NUL byte" in err


def test_AB9_retirement_is_for_received_requests_only_and_close_after_removal_works(cli, xproj):
    from steward import exchange as xc
    assert "superseded" not in xc.RESPONSE["acknowledged"] and "withdrawn" not in xc.REQUESTER["acknowledged"]
    assert "withdrawn" not in xc.RELEASE["acknowledged"]
    assert cli("exchange", "receive", _item(xproj, "BBB-RSP-001", kind="response",
                                            extra='responds_to = "AAA-REQ-009"\n'))[0] == 0
    code, _, err = cli("exchange", "state", "BBB-RSP-001", "withdrawn", "--note", "x")
    assert code == 64 and "not a valid transition" in err
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    assert cli("exchange", "state", "BBB-REQ-001", "withdrawn", "--note", "closed by its sender")[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    code, out, err = cli("exchange", "state", "BBB-REQ-001", "closed")
    assert code == 0 and "closed" in out, err
    assert xc.current(xc.states(xproj)["BBB-REQ-001"]) == "closed"
    _, rep = cli.check(xproj)
    assert "R-53.unknown_item" not in codes(one(rep, "R-53"))
    _, out, _ = cli("exchange", "status")
    assert "BBB-REQ-001" in out and "(file removed)" in out


def test_AB10_a_configured_peer_appears_before_anything_is_received(cli, home, monkeypatch):
    from steward import exchange as xc
    me, them = home / "me", home / "them"
    for d in (me, them):
        d.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
        cli("init", "--repo", d)
    with open(me / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "AAA"\npeers = {{ BBB = "{them}" }}\n')  # not a consumer
    with open(them / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "BBB"\n')
    (them / "exchange/outbox").mkdir(parents=True)
    (them / "exchange/outbox/BBB-FB-001.md").write_text(xc.render(
        {"schema": "steward.exchange/1", "id": "BBB-FB-001", "kind": "feedback", "from": "BBB", "to": "AAA",
         "title": "waiting", "filed": __import__("datetime").date(2026, 11, 24)}, "## Need\nx\n"))
    for a in (["add", "-A"], ["-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x"]):
        subprocess.run(["git", *a], cwd=them, check=True)
    monkeypatch.chdir(me)
    cli("exchange", "init")
    _, out, _ = cli("audit", "progress", "--json")
    assert json.loads(out)["usage"]["consumers"]["BBB"]["checkout"]["not_received"] == ["BBB-FB-001"]
    assert cli("exchange", "pull", "BBB")[0] == 0
    _, out, _ = cli("audit", "progress", "--json")
    assert json.loads(out)["usage"]["consumers"]["BBB"]["checkout"]["not_received"] == []


@signing
def test_AB11_a_reference_only_pin_can_become_eligible_and_module_pins_list_ignored_importers(cli, repo):
    _shared(repo)
    t = (repo / "steward.toml").read_text().replace('module = "lib"\nreferences = ["vendor/lib_1/"]',
                                                     'references = ["vendor/lib_1/"]', 1)
    (repo / "steward.toml").write_text(t)
    (repo / "a.py").unlink()
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "x")
    assert _status(cli)["lib-1"]["state"] == "retire-eligible"
    t = (repo / "steward.toml").read_text().replace('references = ["vendor/lib_2/"]',
                                                     'references = ["vendor/lib_2/"]\ncallers = "module"\n'
                                                     'ignore_callers = ["b.py"]', 1)
    (repo / "steward.toml").write_text(t)
    st = _status(cli)["lib-2"]
    assert st["callers"] == [] and {"path": "b.py", "via": "module", "ignored": True} in st["caller_detail"]


# ================================================================ the re-verification (6430a12): AC1 – AC7
@signing
def test_AC1_a_tracked_link_replaced_by_a_regular_caller_is_scanned(cli, repo, tmp_path):
    _shared(repo)
    (repo / "a.py").unlink()
    (repo / "loader.txt").symlink_to("vendor/lib_1/lib.py")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "a tracked link")
    assert _status(cli)["lib-1"]["callers"] == []  # control: a genuine link is not followed
    (repo / "loader.txt").unlink()
    (repo / "loader.txt").write_text('P = "vendor/lib_1/"\n')
    st = _status(cli)["lib-1"]
    assert st["callers"] == ["loader.txt"] and "object" not in st


@signing
@pytest.mark.parametrize("nl", ["\n", "\r\n", "\r"])
def test_AC1_module_callers_are_found_with_any_line_ending(cli, repo, nl):
    _shared(repo)
    t = (repo / "steward.toml").read_text().replace('references = ["vendor/lib_1/"]\n', "", 1)
    (repo / "steward.toml").write_text(t)
    (repo / "a.py").write_bytes(f"x = 1{nl}import lib{nl}".encode())
    (repo / "b.py").unlink()
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "line endings")
    assert _status(cli)["lib-1"]["callers"] == ["a.py"]


@signing
def test_AC2_a_fifo_in_place_of_a_caller_is_unavailable_and_never_stalls(cli, repo):
    import time
    _shared(repo)
    (repo / "a.py").unlink()
    (repo / "c.py").write_text("x = 1\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "x")
    (repo / "c.py").unlink()
    os.mkfifo(repo / "c.py")
    t0 = time.monotonic()
    st = _status(cli)["lib-1"]
    assert time.monotonic() - t0 < 20 and st["callers"] is None and "object" not in st


def test_AC3_a_response_left_without_a_receipt_imports_no_original(cli, xproj, tmp_path):
    import hashlib

    from steward import exchange as xc
    from steward.ledger import Ledger
    d = __import__("datetime").date(2026, 11, 24)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA",
                      "to": "BBB", "title": "ours", "filed": d}, "## Need\nplain\n")
    sha = hashlib.sha256(orig.encode()).hexdigest()
    rsp = xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB",
                     "to": "AAA", "title": "re", "filed": d, "responds_to": "AAA-REQ-001"},
                    f"## Decision\naccepted: Zebrafinch\n\n## Answers\nAAA-REQ-001 sha256:{sha}\n")
    scratch = tmp_path / "ledger"
    scratch.mkdir()
    Ledger(scratch / "log.jsonl", "exchange", PEER_RID).transaction(lambda _: ("state", {
        "item": "AAA-REQ-001", "state": "acknowledged", "from_state": None, "note": "", "by": "BBB",
        "received": {"from": "file", "sha256": sha}}))
    peer, _ = _peer(tmp_path, {}, inbox={"AAA-REQ-001": orig}, ledger=(scratch / "log.jsonl").read_bytes())
    (peer / "exchange/responses").mkdir()
    (peer / "exchange/responses/BBB-RSP-001.md").write_text(rsp)
    _commit(peer)
    _terms(xproj, ["Zebrafinch"])
    _with_peer(xproj, peer)
    (xproj / "exchange/inbox/BBB-RSP-001.md").write_text(rsp)  # left behind by an interrupted receive
    before = (xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b""
    code, _, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "is not received" in err
    assert not (xproj / "exchange/outbox/AAA-REQ-001.md").exists()
    assert ((xproj / "exchange/log.jsonl").read_bytes() if (xproj / "exchange/log.jsonl").exists() else b"") == before


def test_AC4_a_chain_of_replacements_stays_valid_when_each_is_removed(cli, xproj):
    for i in ("001", "002", "003"):
        assert cli("exchange", "receive", _item(xproj, f"BBB-REQ-{i}"))[0] == 0
    assert cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "BBB-REQ-002")[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, out, _ = cli("exchange", "state", "BBB-REQ-002", "superseded", "--by", "BBB-REQ-003")
    assert "may now be removed" in out
    (xproj / "exchange/inbox/BBB-REQ-002.md").unlink()
    _, rep = cli.check(xproj)
    r = one(rep, "R-53")
    assert r["status"] == "PASS" and "R-53.unknown_item" not in codes(r)
    _, out, _ = cli("exchange", "status")
    assert out.count("(file removed)") == 2
    # the end of the chain withdrawn and removed: the whole chain still rests on retained receipts
    _, out, _ = cli("exchange", "state", "BBB-REQ-003", "withdrawn", "--note", "closed by its sender")
    assert "may now be removed" in out
    (xproj / "exchange/inbox/BBB-REQ-003.md").unlink()
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"
    assert cli("exchange", "state", "BBB-REQ-001", "closed")[0] == 0


def test_AC5_an_unbound_response_blocks_the_advice_and_r53_agrees(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    legacy = xc.render({"schema": "steward.exchange/1", "id": "AAA-RSP-001", "kind": "response", "from": "AAA",
                        "to": "BBB", "title": "re", "filed": __import__("datetime").date(2026, 11, 24),
                        "responds_to": "BBB-REQ-001"}, "## Decision\nverified: seen\n")  # no Answers section
    (xproj / "exchange/responses/AAA-RSP-001.md").write_text(legacy)
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"
    code, out, _ = cli("exchange", "state", "BBB-REQ-001", "withdrawn", "--note", "closed by its sender")
    assert code == 0 and "Keep exchange/inbox/BBB-REQ-001.md" in out and "git rm" not in out
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"  # nothing changed while the file is kept


def test_AC6_a_received_response_cannot_be_retired_by_respond_either(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "receive", _item(xproj, "BBB-RSP-001", kind="response",
                                            extra='responds_to = "AAA-REQ-009"\n'))[0] == 0
    before = xc.states(xproj)["BBB-RSP-001"]
    code, _, err = cli("exchange", "respond", "BBB-RSP-001", "withdrawn", "--note", "x")
    assert code == 64 and "not a valid transition" in err
    assert xc.states(xproj)["BBB-RSP-001"] == before
    assert not list((xproj / "exchange/responses").glob("*.md"))  # no response file left behind
    assert xc.retired_receipt("BBB-REL-001", [{"state": "acknowledged", "received": {"sha256": "a" * 64}},
                                              {"state": "withdrawn"}]) is False


def test_AC7_a_renamed_response_is_a_name_mismatch_not_unknown(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    _, out, _ = cli("exchange", "respond", "BBB-REQ-001", "withdrawn", "--note", "closed by its sender")
    rid = out.split("response ")[1].split()[0]
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    (xproj / f"exchange/responses/{rid}.md").rename(xproj / "exchange/responses/AAA-RSP-777.md")
    _, rep = cli.check(xproj)
    r = one(rep, "R-53")
    assert r["status"] == "FAIL" and "R-53.name_mismatch" in codes(r)


# ---------------------------------------------------------------- the partial verdicts
def test_AB4_an_id_on_a_list_for_other_paths_is_still_withheld(cli, xproj):
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/terms.txt").write_text("BBB-REQ-007\n")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "ids"\nfile = "development/terms.txt"\ninclude = ["exchange/inbox/BBB-REQ-007.md"]\n')
    code, out, err = cli("exchange", "receive", _item(xproj, "BBB-REQ-007"))
    assert code == 65 and "BBB-REQ-007" not in out + err


@pytest.mark.parametrize("digest", ["a" * 64 + "\n", "A" * 64, "a" * 63, ""])
def test_AB6_a_malformed_digest_is_no_receipt(digest):
    from steward import exchange as xc
    assert xc.receipt_sha([{"state": "acknowledged", "received": {"sha256": digest}}]) is None


def test_AB6_each_bad_replacement_keeps_the_item_from_removal(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    hist = {"BBB-REQ-001": [{"state": "acknowledged", "received": {"sha256": "a" * 64}},
                            {"state": "superseded", "superseded_by": None}]}
    for by in (None, "CCC-REQ-001", "BBB-REQ-001", "BBB-REQ-404"):
        hist["BBB-REQ-001"][1]["superseded_by"] = by
        assert xc.removable("BBB-REQ-001", hist, set(), {}) is False, by


def test_AB8_a_nul_byte_is_refused_without_any_privacy_policy(cli, xproj):
    code, _, err = cli("exchange", "receive", _item(xproj, "BBB-REQ-001", body="## Need\nx\x00y\n"))
    assert code == 65 and "NUL byte" in err


# ================================================================ the second re-verification (80fd6af): AD1 – AD4
def _bound_pair(tmp_path, rsp_body="## Decision\naccepted: ok\n", orig_body="## Need\nplain\n"):
    """A peer holding this project's own item AAA-REQ-001 in its inbox (with a hashed receipt) and a bound response."""
    import hashlib

    from steward import exchange as xc
    from steward.ledger import Ledger
    d = __import__("datetime").date(2026, 11, 24)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA",
                      "to": "BBB", "title": "ours", "filed": d}, orig_body)
    sha = hashlib.sha256(orig.encode()).hexdigest()
    rsp = xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB",
                     "to": "AAA", "title": "re", "filed": d, "responds_to": "AAA-REQ-001"},
                    f"{rsp_body}\n## Answers\nAAA-REQ-001 sha256:{sha}\n")
    scratch = tmp_path / "ledger"
    scratch.mkdir()
    Ledger(scratch / "log.jsonl", "exchange", PEER_RID).transaction(lambda _: ("state", {
        "item": "AAA-REQ-001", "state": "acknowledged", "from_state": None, "note": "", "by": "BBB",
        "received": {"from": "file", "sha256": sha}}))
    peer, _ = _peer(tmp_path, {}, inbox={"AAA-REQ-001": orig}, ledger=(scratch / "log.jsonl").read_bytes())
    (peer / "exchange/responses").mkdir()
    (peer / "exchange/responses/BBB-RSP-001.md").write_text(rsp)
    (peer / "exchange/outbox/BBB-REQ-050.md").write_text(_plain("BBB-REQ-050"))  # an independent later item
    _commit(peer)
    return peer, rsp


def _plain(iid):
    from steward import exchange as xc
    return xc.render({"schema": "steward.exchange/1", "id": iid, "kind": "request", "from": "BBB", "to": "AAA",
                      "title": f"item {iid}", "filed": __import__("datetime").date(2026, 11, 24)}, "## Need\nx\n")


def _ledger_bytes(x):
    return (x / "exchange/log.jsonl").read_bytes() if (x / "exchange/log.jsonl").exists() else b""


@pytest.mark.parametrize("where", ["response", "response_left", "original"])
@pytest.mark.parametrize("allow", [False, True])
def test_AD1_a_nul_byte_refuses_the_pair_before_any_write(cli, xproj, tmp_path, where, allow):
    peer, rsp = _bound_pair(tmp_path, rsp_body="## Decision\naccepted: a\x00b\n" if where != "original" else
                            "## Decision\naccepted: ok\n", orig_body="## Need\nx\x00y\n" if where == "original" else
                            "## Need\nplain\n")
    _with_peer(xproj, peer)
    if where == "response_left":
        (xproj / "exchange/inbox/BBB-RSP-001.md").write_text(rsp)
    before = _ledger_bytes(xproj)
    code, out, err = cli("exchange", "pull", "BBB", *(["--allow-terms"] if allow else []))
    assert code == 65 and "NUL byte" in err
    assert not (xproj / "exchange/outbox/AAA-REQ-001.md").exists()
    from steward import exchange as xc
    assert "AAA-REQ-001" not in xc.states(xproj) and "BBB-RSP-001" not in xc.states(xproj)
    assert "BBB-REQ-050: received" in out  # the later, independent item still arrives
    assert _ledger_bytes(xproj) != before  # (only that later item's receipt)


def test_AD1_control_a_clean_pair_imports_and_is_received(cli, xproj, tmp_path):
    peer, _ = _bound_pair(tmp_path)
    _with_peer(xproj, peer)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 0 and (xproj / "exchange/outbox/AAA-REQ-001.md").is_file() and "BBB-RSP-001: received" in out, err


def test_AD2_a_peer_code_on_a_private_list_is_never_printed(cli, xproj, tmp_path):
    peer, _ = _peer(tmp_path, {"BBB-REQ-001": _plain("BBB-REQ-001")})
    _terms(xproj, ["BBB"])
    _with_peer(xproj, peer)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 65 and "BBB" not in out + err
    assert "line" in err and "products:1" in err and "new item(s)" in out


def test_AD3_an_invalid_replacement_file_gives_one_decision_everywhere(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    p2 = _item(xproj, "BBB-REQ-002")
    assert cli("exchange", "receive", p2)[0] == 0
    assert cli("exchange", "state", "BBB-REQ-001", "superseded", "--by", "BBB-REQ-002")[0] == 0
    (xproj / "exchange/inbox/BBB-REQ-001.md").unlink()
    _, rep = cli.check(xproj)
    assert one(rep, "R-53")["status"] == "PASS"
    (xproj / "exchange/inbox/BBB-REQ-002.md").write_text("+++\nincomplete")  # name and receipt kept, content not
    _, rep = cli.check(xproj)
    assert "R-53.unknown_item" in codes(one(rep, "R-53"))
    assert xc.may_be_gone(xproj, "BBB-REQ-001") is False
    _, out, _ = cli("exchange", "status")
    assert "(file removed)" not in out
    code, _, err = cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))
    assert code == 65 and "restore it from git" in err
    before = xc.states(xproj)["BBB-REQ-001"]
    assert cli("exchange", "state", "BBB-REQ-001", "closed")[0] == 64
    assert xc.states(xproj)["BBB-REQ-001"] == before
    (xproj / "exchange/inbox/BBB-REQ-002.md").write_bytes(p2.read_bytes())  # control: intact again
    assert xc.may_be_gone(xproj, "BBB-REQ-001") is True


def test_AD4_a_chain_longer_than_the_recursion_limit_is_decided(monkeypatch):
    import sys

    from steward import exchange as xc
    n = sys.getrecursionlimit() + 50
    ids = [f"BBB-REQ-{i:05d}" for i in range(n)]
    hist = {}
    for i, iid in enumerate(ids):
        hist[iid] = [{"state": "acknowledged", "received": {"sha256": "a" * 64}}]
        hist[iid].append({"state": "superseded", "superseded_by": ids[i + 1]} if i + 1 < n else {"state": "withdrawn"})
    assert xc.removable(ids[0], hist, set(), {}) is True
    hist[ids[-1]] = hist[ids[-1]][:1]  # the tail no longer retired: the chain is invalid
    assert xc.removable(ids[0], hist, set(), {}) is False
    hist[ids[-1]].append({"state": "superseded", "superseded_by": ids[0]})  # a cycle
    assert xc.removable(ids[0], hist, set(), {}) is False
