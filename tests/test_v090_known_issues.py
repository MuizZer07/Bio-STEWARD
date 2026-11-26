"""0.9.0, section A: the known issues P1 - P5 of 0.8.1 and the directory-relative exchange writes (RELEASE_v0.9.0_SPEC §1).
Each test is named after its task and finding ID."""

import os
import shutil
import subprocess
import threading
import unicodedata
import uuid

import pytest

from conftest import append

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
ZERO = "0" * 40


def sh(cwd, *a, input=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True, input=input).stdout.strip()


@pytest.fixture
def gitrepo(cli, tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_TRUST_BASELINE", raising=False)
    monkeypatch.delenv("STEWARD_TRUST_SIGNERS", raising=False)
    (tmp_path / "home").mkdir()
    return r


def _unconfigured_tip(repo):
    sh(repo, "git", "checkout", "-q", "-b", "ungoverned")
    sh(repo, "git", "rm", "-q", "steward.toml")
    sh(repo, "git", "commit", "-qm", "no config", "--no-verify")
    sha = sh(repo, "git", "rev-parse", "HEAD")
    sh(repo, "git", "checkout", "-q", "main")
    return [f"refs/heads/ungoverned {sha} refs/heads/ungoverned {ZERO}"]


# ---------------------------------------------------------------- A1 / P1 (high)
@git_needed
def test_A1_P1_a_pinned_checkout_refuses_an_unconfigured_tip(gitrepo, capsys):
    from steward import authorize as az
    from steward import hooks as hk
    lines = _unconfigured_tip(gitrepo)
    az.trust_file().write_text(f'[repos."{uuid.uuid4()}"]\nbaseline = "{"0" * 40}"\nsigners = """x"""\n'
                               f'checkout = "{gitrepo.resolve()}"\n')
    assert hk.run_pre_push(gitrepo, "default", [], "skip", lines) == 1
    assert "pinned" in capsys.readouterr().err


@git_needed
def test_A1_P1_a_pin_for_the_checkouts_repo_id_refuses_an_unconfigured_tip(gitrepo, capsys):
    import tomllib
    from steward import authorize as az
    from steward import hooks as hk
    lines = _unconfigured_tip(gitrepo)
    rid = tomllib.loads((gitrepo / "steward.toml").read_text())["steward"]["repo_id"]
    az.trust_file().write_text(f'[repos."{rid}"]\nbaseline = "{"0" * 40}"\nsigners = """x"""\n')
    assert hk.run_pre_push(gitrepo, "default", [], "skip", lines) == 1


@git_needed
def test_A1_P1_an_env_trust_root_refuses_an_unconfigured_tip(gitrepo, monkeypatch):
    from steward import hooks as hk
    lines = _unconfigured_tip(gitrepo)
    monkeypatch.setenv("STEWARD_TRUST_BASELINE", "0" * 40)
    monkeypatch.setenv("STEWARD_TRUST_SIGNERS", "x ssh-ed25519 AAAA")
    assert hk.run_pre_push(gitrepo, "default", [], "skip", lines) == 1


@git_needed
def test_A1_P1_controls_unpinned_skips_with_a_notice_and_refuse_refuses(gitrepo, capsys):
    from steward import hooks as hk
    lines = _unconfigured_tip(gitrepo)
    assert hk.run_pre_push(gitrepo, "default", [], "skip", lines) == 0
    assert "no steward.toml" in capsys.readouterr().err
    assert hk.run_pre_push(gitrepo, "default", [], "refuse", lines) == 1


# ---------------------------------------------------------------- A2 / P2 (high)
def _torn(tmp_path, name="log.jsonl"):
    from steward.ledger import Ledger
    p = tmp_path / "led" / name
    led = Ledger(p, "t")
    led.append("x", {"a": 1})
    with open(p, "ab") as f:
        f.write(b'{"seq": 2, "torn')
    return led, p


def test_A2_P2_recover_refuses_a_hard_linked_ledger_before_any_write(tmp_path):
    from steward.ledger import Ledger, LedgerError
    _, p = _torn(tmp_path)
    external = tmp_path / "external.jsonl"
    shutil.copy(p, external)
    p.unlink()
    os.link(external, p)
    before = external.read_bytes()
    with pytest.raises(LedgerError):
        Ledger(p, "t").recover()
    assert external.read_bytes() == before
    assert not (p.parent / (p.name + ".quarantine")).exists()


def test_A2_P2_recover_refuses_a_symlinked_ledger_before_any_write(tmp_path):
    from steward.ledger import Ledger, LedgerError
    _, p = _torn(tmp_path)
    external = tmp_path / "external.jsonl"
    shutil.move(p, external)
    p.symlink_to(external)
    before = external.read_bytes()
    with pytest.raises(LedgerError):
        Ledger(p, "t").recover()
    assert external.read_bytes() == before
    assert not (p.parent / (p.name + ".quarantine")).exists()


def test_A2_P2_recover_refuses_a_linked_quarantine_directory(tmp_path):
    from steward.ledger import Ledger, LedgerError
    _, p = _torn(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (p.parent / (p.name + ".quarantine")).symlink_to(outside)
    before = p.read_bytes()
    with pytest.raises(LedgerError):
        Ledger(p, "t").recover()
    assert not any(outside.iterdir()) and p.read_bytes() == before


def test_A2_P2_control_an_ordinary_recovery_quarantines_and_continues(tmp_path):
    from steward.ledger import Ledger, verify
    led, p = _torn(tmp_path)
    e = led.recover()
    assert e is not None and e["kind"] == "recovery"
    v = verify(p)
    assert not v.errors and not v.torn_tail and len(list((p.parent / (p.name + ".quarantine")).iterdir())) == 1


# ---------------------------------------------------------------- A3 / P3
def _promptly(fn, fifo, seconds=5.0):
    """Run fn; a FIFO open that blocks is released (by opening the reader) and reported as a failure."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        t.join(5)
        os.close(fd)
        pytest.fail("the ledger open blocked on a FIFO")
    return box


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_A3_P3_a_fifo_ledger_is_refused_promptly(tmp_path):
    from steward.ledger import Ledger, LedgerError
    p = tmp_path / "led" / "log.jsonl"
    p.parent.mkdir()
    os.mkfifo(p)
    box = _promptly(lambda: Ledger(p, "t").append("x", {}), p)
    assert isinstance(box.get("error"), LedgerError), box


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_A3_P3_a_fifo_lock_is_refused_promptly(tmp_path):
    from steward.ledger import Ledger, LedgerError
    p = tmp_path / "led" / "log.jsonl"
    p.parent.mkdir()
    os.mkfifo(p.with_suffix(".jsonl.lock"))
    box = _promptly(lambda: Ledger(p, "t").append("x", {}), p.with_suffix(".jsonl.lock"))
    assert isinstance(box.get("error"), LedgerError), box


def test_A3_P3_a_hard_linked_lock_is_refused_and_not_locked(tmp_path, monkeypatch):
    import fcntl
    from steward.ledger import Ledger, LedgerError
    p = tmp_path / "led" / "log.jsonl"
    p.parent.mkdir()
    shared = tmp_path / "shared.lock"
    shared.write_text("")
    os.link(shared, p.with_suffix(".jsonl.lock"))
    locked = []
    real = fcntl.flock
    monkeypatch.setattr(fcntl, "flock", lambda f, op: (locked.append(op), real(f, op))[1])
    with pytest.raises(LedgerError):
        Ledger(p, "t").append("x", {})
    assert fcntl.LOCK_EX not in locked and not p.exists()


def test_A3_P3_control_ordinary_ledger_and_lock(tmp_path):
    from steward.ledger import Ledger, verify
    p = tmp_path / "led" / "log.jsonl"
    led = Ledger(p, "t")
    led.append("x", {})
    led.append("y", {})
    assert len(verify(p).entries) == 3


# ---------------------------------------------------------------- A4 / P4
@git_needed
def test_A4_P4_a_link_above_the_hooks_parent_is_refused(cli, gitrepo, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "via").symlink_to(real)
    sh(gitrepo, "git", "config", "core.hooksPath", str(tmp_path / "via" / "a" / "hooks"))
    code, out, err = cli("hooks", "install")
    assert code == 64 and "symlink" in (out + err)
    assert not any(real.iterdir())


@git_needed
def test_A4_P4_a_linked_directory_inside_the_repository_is_refused(cli, gitrepo, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (gitrepo / "tools").symlink_to(real)
    sh(gitrepo, "git", "config", "core.hooksPath", "tools/x/hooks")
    code, out, err = cli("hooks", "install")
    assert code == 64 and "symlink" in (out + err)
    assert not any(real.iterdir())


# ---------------------------------------------------------------- A5 / P5
def _blob(repo, data):
    return sh(repo, "git", "hash-object", "-w", "--stdin", input=data)


def _commit(repo, entries):
    """entries: [(mode, kind, sha, name)] at the top level; returns a commit sha."""
    tree = sh(repo, "git", "mktree", input="".join(f"{m} {k} {s}\t{n}\n" for m, k, s, n in entries))
    return sh(repo, "git", "commit-tree", tree, "-m", "t")


@git_needed
@pytest.mark.parametrize("names", [("A.txt", "a.txt"),
                                   (unicodedata.normalize("NFC", "café.txt"), unicodedata.normalize("NFD", "café.txt"))])
def test_A5_P5_colliding_paths_refuse_the_staged_tree(gitrepo, tmp_path, names):
    from steward import hooks as hk
    one, two = _blob(gitrepo, "one\n"), _blob(gitrepo, "two\n")
    sha = _commit(gitrepo, [("100644", "blob", one, names[0]), ("100644", "blob", two, names[1])])
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="collide"):
        hk.materialize(gitrepo, sha, dest)
    assert not any(dest.iterdir())


@git_needed
def test_A5_P5_a_link_under_a_case_variant_of_exchange_is_refused(gitrepo, tmp_path):
    from steward import hooks as hk
    target = _blob(gitrepo, "/etc")
    sub = sh(gitrepo, "git", "mktree", input=f"120000 blob {target}\tinbox\n")
    sha = _commit(gitrepo, [("040000", "tree", sub, "Exchange")])
    with pytest.raises(RuntimeError, match="exchange"):
        hk.materialize(gitrepo, sha, tmp_path)


@git_needed
def test_A5_P5_blob_reads_are_bounded_by_bytes(gitrepo, tmp_path, monkeypatch):
    from steward import fsutil
    from steward import hooks as hk
    blobs = [_blob(gitrepo, f"{i}\n" * 50) for i in range(6)]
    sha = _commit(gitrepo, [("100644", "blob", b, f"f{i}.txt") for i, b in enumerate(blobs)])
    calls = []
    real = fsutil.git_run

    def spy(root, *args, **kw):
        if args[:2] == ("cat-file", "--batch"):
            calls.append(kw.get("input", b"").count(b"\n"))
        return real(root, *args, **kw)
    monkeypatch.setattr(fsutil, "git_run", spy)
    monkeypatch.setattr(hk, "BATCH_BYTES", 250)  # each blob is 100 bytes: two per batch
    dest = tmp_path / "d1"
    dest.mkdir()
    hk.materialize(gitrepo, sha, dest)
    assert calls == [2, 2, 2] and (dest / "f5.txt").read_text() == "5\n" * 50
    monkeypatch.setattr(hk, "MAX_BLOB_BYTES", 99)
    dest = tmp_path / "d2"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="larger"):
        hk.materialize(gitrepo, sha, dest)


# ---------------------------------------------------------------- A6: directory-relative exchange writes
@pytest.fixture
def ex(cli, tmp_path, monkeypatch):
    r = tmp_path / "x"
    r.mkdir()
    cli("init", "--repo", r)
    append(r, "steward.toml", '\n[exchange]\ncode = "ABC"\n')
    monkeypatch.chdir(r)
    cli("exchange", "init")
    return r


def test_A6_a_replaced_ancestor_does_not_redirect_an_item_write(ex, tmp_path, monkeypatch):
    from steward import exchange as xc
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(ex / "exchange/outbox")
    (ex / "exchange/outbox").symlink_to(outside)
    # the lexical check ran before the swap: simulate it by letting the guard pass
    monkeypatch.setattr(xc, "guard", lambda root, *parts: root.joinpath(xc.FOLDER, *parts))
    with pytest.raises((xc.BoundaryError, OSError)):
        xc.write_new(ex, "outbox", "ABC-REQ-001.md", b"x")
    assert not any(outside.iterdir())


def test_A6_a_replaced_exchange_root_does_not_redirect_the_ledger(ex, tmp_path, monkeypatch):
    from steward import exchange as xc
    from steward.ledger import LedgerError
    outside = tmp_path / "outside"
    shutil.move(str(ex / "exchange"), str(outside))
    (ex / "exchange").symlink_to(outside)
    before = (outside / "log.jsonl").read_bytes() if (outside / "log.jsonl").exists() else None
    monkeypatch.setattr(xc, "ledger_ok", lambda root: None)
    with pytest.raises((xc.BoundaryError, LedgerError, OSError)):
        xc.set_state(ex, "r", "XYZ-REQ-001", "acknowledged", None, "t", False)
    after = (outside / "log.jsonl").read_bytes() if (outside / "log.jsonl").exists() else None
    assert after == before


def test_A6_control_ordinary_exchange_writes(cli, ex):
    code, out, _ = cli("exchange", "new", "request", "--to", "STW", "--title", "ok")
    assert code == 0 and (ex / "exchange/outbox/ABC-REQ-001.md").is_file()
