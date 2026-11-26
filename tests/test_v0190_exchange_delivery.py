"""STW-008: follow the exchange ref and check the receiver's receipt."""

import json
import os
import tomllib
from datetime import date, timedelta

import pytest

from conftest import codes, one
from test_v090_exchange import _repo, git_needed, sh

pytestmark = git_needed


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_NO_REGISTRY")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


def _file(cli, repo, to, *, age=0, oneway=False):
    extra = ["--oneway", "--channel", "email"] if oneway else []
    rc, out, err = cli("exchange", "new", "request", "--repo", repo, "--to", to, "--title", "A request", *extra)
    assert rc == 0, err
    iid = out.split(":", 1)[0]
    path = repo / "exchange" / ("oneway" if oneway else "outbox") / f"{iid}.md"
    if age:
        path.write_text(path.read_text().replace(str(date.today()), str(date.today() - timedelta(days=age))))
    return iid, path


def _commit(repo):
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "exchange records")


@pytest.mark.parametrize("remote", [False, True])
def test_status_and_pull_follow_the_peer_ref(cli, tmp_path, remote):
    peer = _repo(cli, tmp_path / "peer", "DEF")
    source = 'path = "../peer"' if not remote else f'url = "{peer.as_uri()}"'
    receiver = _repo(cli, tmp_path / "receiver", "ABC", f'peers = {{ DEF = {{ {source}, ref = "dev" }} }}\n')
    sh(peer, "git", "switch", "-qc", "dev")
    iid, path = _file(cli, peer, "ABC")
    other, _ = _file(cli, peer, "XYZ")
    expected = path.read_bytes()
    _commit(peer)
    dev = sh(peer, "git", "rev-parse", "HEAD")
    sh(peer, "git", "switch", "-qc", "feature", "main")
    assert not path.exists()

    rc, out, err = cli("exchange", "status", "--repo", receiver, "--json", *(["--fetch"] if remote else []))
    assert rc == 0 and not err
    pending = json.loads(out)
    assert [row["id"] for row in pending] == [iid]
    assert pending[0]["delivery"] == {"peer": "DEF", "state": "waiting"}
    _, out, _ = cli("session", "start", "--repo", receiver)
    if remote:  # AF6: session start never fetches; a URL peer is reported as not checked
        assert iid not in out and "DEF" in out
    else:
        assert f"{iid} from DEF: waiting to be received" in out and other not in out
    rc, _, err = cli("exchange", "pull", "DEF", "--repo", receiver)
    assert rc == 0, err
    assert (receiver / f"exchange/inbox/{iid}.md").read_bytes() == expected
    entries = map(json.loads, (receiver / "exchange/log.jsonl").read_text().splitlines())
    receipt = next(entry for entry in entries if entry.get("item") == iid)
    assert receipt["received"]["commit"] == dev
    assert sh(peer, "git", "branch", "--show-current") == "feature"
    assert sh(peer, "git", "status", "--porcelain") == ""
    _, out, _ = cli("session", "start", "--repo", receiver)
    assert iid not in out


def test_registry_discovers_a_sender_and_then_its_receiver(cli, tmp_path):
    sender = _repo(cli, tmp_path / "sender", "ABC")
    receiver = _repo(cli, tmp_path / "receiver", "DEF")
    iid, _ = _file(cli, sender, "DEF")
    _commit(sender)
    _, out, _ = cli("exchange", "status", "--repo", receiver)
    assert f"{iid} from ABC: waiting to be received" in out
    rc, _, err = cli("exchange", "pull", "--repo", receiver)
    assert rc == 0, err
    _commit(receiver)
    _, out, _ = cli("exchange", "status", "--repo", sender, "--json")
    assert json.loads(out)[0]["delivery"] == {"peer": "DEF", "state": "received"}
    assert "peers" not in tomllib.loads((receiver / "steward.toml").read_text())["exchange"]


def test_declared_ref_takes_precedence_over_a_registered_head(cli, tmp_path):
    peer = _repo(cli, tmp_path / "peer", "DEF")
    receiver = _repo(cli, tmp_path / "receiver", "ABC",
                     'peers = { DEF = { path = "../peer", ref = "missing" } }\n')
    iid, _ = _file(cli, peer, "ABC")
    _commit(peer)
    rc, out, err = cli("exchange", "status", "--repo", receiver, "--json")
    assert rc == 0 and json.loads(out) == [] and "could not check peer DEF" in err
    rc, _, err = cli("exchange", "pull", "DEF", "--repo", receiver)
    assert rc != 0 and "no commit at the selected ref" in err
    assert not (receiver / f"exchange/inbox/{iid}.md").exists()


def test_path_peers_still_work_in_local_checkout_commands(cli, tmp_path, monkeypatch):
    from steward import authorize, cleanup

    peer = _repo(cli, tmp_path / "peer", "DEF")
    receiver = _repo(cli, tmp_path / "receiver", "ABC",
                     'peers = { DEF = { path = "../peer", ref = "dev" }, XYZ = { url = "https://example.org/peer" } }\n')
    assert cleanup._peers(receiver) == [peer]
    checked = []

    def pending(project):
        checked.append(project)
        return []

    monkeypatch.setattr(authorize, "pending", pending)
    rc, out, err = cli("authorize", "pending", "--all-projects", "--repo", receiver)
    assert rc == 0 and not err
    assert checked == [receiver, peer] and "XYZ: no local checkout" in out


def test_only_old_outbox_items_get_the_advisory_until_the_receipt_is_committed(cli, tmp_path):
    sender = _repo(cli, tmp_path / "sender", "ABC",
                   'delivery_days = 3\npeers = { DEF = { path = "../receiver", ref = "dev" } }\n')
    receiver = _repo(cli, tmp_path / "receiver", "DEF")
    sh(receiver, "git", "switch", "-qc", "dev")
    overdue, _ = _file(cli, sender, "DEF", age=4)
    boundary, _ = _file(cli, sender, "DEF", age=3)
    oneway, _ = _file(cli, sender, "DEF", age=10, oneway=True)
    _commit(sender)

    def warnings():
        _, out, _ = cli("session", "start", "--repo", sender)
        return [line for line in out.splitlines() if line.startswith("R-53 (advisory)")]

    assert warnings() == [f"R-53 (advisory): {overdue} to DEF has no delivery receipt after more than 3 days."]
    _, report = cli.check(sender, "governance")
    rule = one(report, "R-53")
    assert rule["status"] == "PASS"
    assert [d["value"] for d in rule["details"] if d["code"] == "R-53.undelivered"] == [overdue]
    assert not any(iid in line for line in warnings() for iid in (boundary, oneway))
    _, text, _ = cli("check", "--repo", sender, "governance")
    assert f"R-53 (advisory): {overdue}" in text
    assert cli("exchange", "pull", "ABC", "--repo", receiver)[0] == 0
    assert warnings()
    _commit(receiver)
    sh(receiver, "git", "switch", "-qc", "feature", "main")
    assert not warnings()
    _, report = cli.check(sender, "governance")
    assert "R-53.undelivered" not in codes(one(report, "R-53"))


def test_receipt_must_match_item_bytes_and_come_from_an_intact_ledger(cli, tmp_path):
    sender = _repo(cli, tmp_path / "sender", "ABC", 'peers = { DEF = "../receiver" }\n')
    receiver = _repo(cli, tmp_path / "receiver", "DEF")
    iid, path = _file(cli, sender, "DEF", age=20)
    _commit(sender)
    assert cli("exchange", "pull", "--repo", receiver)[0] == 0
    _commit(receiver)

    def state():
        _, out, _ = cli("exchange", "status", "--repo", sender, "--json")
        return next(row["delivery"]["state"] for row in json.loads(out) if row["id"] == iid)

    assert state() == "received"
    path.write_bytes(path.read_bytes() + b"\nNew text.\n")
    assert state() == "changed"
    log = receiver / "exchange/log.jsonl"
    log.write_bytes(log.read_bytes() + b'{"broken":')
    _commit(receiver)
    assert state() == "unchecked"
    _, out, _ = cli("session", "start", "--repo", sender)
    assert f"R-53 (advisory): {iid}" in out and "ledger could not be checked" in out


def test_unchecked_deliveries_are_one_line_per_peer(cli, tmp_path, monkeypatch):
    """Token cost (STW-009): items whose receiver cannot be checked are counted per peer, never listed one by one."""
    from steward import cli as c
    from types import SimpleNamespace
    item = lambda i: SimpleNamespace(id=f"AAA-REQ-00{i}", from_="AAA", to="BBB")
    st = SimpleNamespace(unavailable=[], incoming=[],
                         outgoing=[SimpleNamespace(state="unchecked", item=item(i)) for i in range(1, 6)])
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(map(str, a))))
    cfg = SimpleNamespace(exchange=SimpleNamespace(delivery_days=14))
    monkeypatch.setattr(c, "_exchange_name", lambda root, cfg, x: x)
    c._print_exchange_delivery(tmp_path, cfg, st)
    assert [l for l in lines if "BBB" in l] == ["Exchange: 5 item(s) with BBB: delivery not checked (declare BBB under [exchange] peers to check it)."]
