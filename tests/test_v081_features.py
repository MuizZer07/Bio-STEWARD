"""0.8.1 features: shared run slots (SR-001), release identities and --dist (SR-003, FB-10), records root (SR-006)."""

import json
import sys
import threading
import time
import zipfile

import pytest

from conftest import append, codes, one

PY = sys.executable


# ---------------------------------------------------------------- SR-001: shared slots, bounded wait
@pytest.fixture
def two_checkouts(cli, tmp_path, monkeypatch):
    shared = tmp_path / "shared-slots"
    roots = []
    for name in ("a", "b"):
        r = tmp_path / name
        r.mkdir()
        cli("init", "--repo", r)
        append(r, "steward.toml", "\n[run]\n[run.slots]\nheavy = 1\n")
        roots.append(r)
    monkeypatch.setenv("STEWARD_SLOTS_DIR", str(shared))
    return roots


def test_SR001_checkouts_sharing_a_slot_directory_share_permits(cli, two_checkouts, monkeypatch):
    a, b = two_checkouts
    monkeypatch.chdir(a)
    holder = threading.Thread(target=lambda: cli("run", "--slot", "heavy", "--", PY, "-c", "import time; time.sleep(3)"))
    holder.start()
    time.sleep(1.0)
    monkeypatch.chdir(b)
    t0 = time.time()
    code, _, err = cli("run", "--slot", "heavy", "--wait-timeout", "1", "--", PY, "-c", "pass")
    assert code == 75 and 0.8 <= time.time() - t0 < 2.5, err
    holder.join()
    code, _, _ = cli("run", "--slot", "heavy", "--wait-timeout", "1", "--", PY, "-c", "pass")
    assert code == 0


def test_SR001_the_record_names_the_slot_scope_without_a_local_path(cli, two_checkouts, monkeypatch):
    a, _ = two_checkouts
    monkeypatch.chdir(a)
    cli("run", "--slot", "heavy", "--", PY, "-c", "pass")
    started = [json.loads(l) for l in (a / "development/runs.jsonl").read_text().splitlines() if '"started"' in l][-1]
    assert started["slot_scope"] == "shared" and started["slot_dir"] == "$STEWARD_SLOTS_DIR"
    assert "/Users/" not in json.dumps(started) and "/home/" not in json.dumps(started)


def test_SR001_a_local_slot_while_a_shared_one_is_configured_is_reported(cli, two_checkouts, monkeypatch):
    a, _ = two_checkouts
    monkeypatch.chdir(a)
    monkeypatch.delenv("STEWARD_SLOTS_DIR")
    cli("run", "--slot", "heavy", "--", PY, "-c", "pass")
    append(a, "steward.toml", "")
    text = (a / "steward.toml").read_text().replace("[run]\n", '[run]\nslots_dir = "~/.steward/slots"\n', 1)
    (a / "steward.toml").write_text(text)
    _, rep = cli.check(a, "run")
    assert "R-32.local_slot" in codes(one(rep, "R-32"))


# ---------------------------------------------------------------- SR-003, FB-10: identities and --dist
CFF = 'cff-version: 1.2.0\nmessage: "c"\ntitle: "x"\nauthors:\n  - name: "A"\n'


@pytest.fixture
def rel(cli, tmp_path, monkeypatch):
    r = tmp_path / "r"
    r.mkdir()
    cli("init", "--repo", r)
    append(r, "steward.toml", '\n[release]\nidentities = ["image", "doi"]\n')
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        (r / name).write_text(text)
    (r / "dist").mkdir()
    with zipfile.ZipFile(r / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
    monkeypatch.chdir(r)
    return r


def test_SR003_identities_are_recorded_and_a_missing_one_is_null(cli, rel):
    assert cli("release", "manifest", "--identity", "image=sha256:" + "a" * 64)[0] == 0
    man = json.loads((rel / "release-manifest.json").read_text())
    assert man["identities"] == {"image": "sha256:" + "a" * 64, "doi": None}
    _, rep = cli.check(rel, "release")
    assert one(rep, "R-42")["status"] == "PASS"
    _, out, _ = cli("check", "--repo", rel, "--format", "json", "--final", "release")
    res = one(json.loads(out), "R-42")
    assert res["status"] == "INCOMPLETE" and "R-42.identity_missing" in codes(res)


def test_SR003_an_undeclared_identity_is_refused(cli, rel):
    code, _, err = cli("release", "manifest", "--identity", "colour=blue")
    assert code == 64 and "colour" in err


def test_FB10_manifest_for_a_folder_outside_the_repository(cli, rel, tmp_path):
    ext = tmp_path / "builds"
    ext.mkdir()
    with zipfile.ZipFile(ext / "q-2.0-py3-none-any.whl", "w") as z:
        z.writestr("q/__init__.py", "y = 2\n")
    code, out, _ = cli("release", "manifest", "--dist", ext)
    man = json.loads((rel / "release-manifest.json").read_text())
    assert code == 0 and "q-2.0-py3-none-any.whl" in man["artifacts"]
    assert man["dist"] == "(outside the repository)" and str(tmp_path) not in json.dumps(man)


# ---------------------------------------------------------------- SR-006: one records root
def test_SR006_every_default_record_path_follows_the_records_root(tmp_path):
    import tomllib
    from steward.models import StewardConfig
    from steward.cli import main
    main(["init", "--repo", str(tmp_path)])
    text = (tmp_path / "steward.toml").read_text().replace("[paths]", '[paths]\nrecords = "process"', 1)
    if "[paths]" not in text:
        text += '\n[paths]\nrecords = "process"\n'
    text += '\n[run]\n[integrity]\n[evidence]\n[storage]\n[run.slots]\n'
    cfg = StewardConfig.model_validate(tomllib.loads(text))
    assert cfg.run.ledger == "process/runs.jsonl" and cfg.integrity.decisions == "process/DECISIONS.md"
    assert cfg.evidence.claims == "process/claims.toml" and cfg.storage.artifacts == "process/artifacts.toml"
    assert cfg.paths.prior_work == ["process/prior_work/**/*.prior.toml"]


def test_SR006_an_explicit_path_wins(tmp_path):
    import tomllib
    from steward.models import StewardConfig
    from steward.cli import main
    main(["init", "--repo", str(tmp_path)])
    text = (tmp_path / "steward.toml").read_text() + '\n[run]\nledger = "logs/runs.jsonl"\n'
    text = text.replace("[paths]", '[paths]\nrecords = "process"', 1) if "[paths]" in text else text + '\n[paths]\nrecords = "process"\n'
    cfg = StewardConfig.model_validate(tomllib.loads(text))
    assert cfg.run.ledger == "logs/runs.jsonl"


def test_SR006_required_records_that_are_missing_are_incomplete(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    text = (tmp_path / "steward.toml").read_text()
    text = text.replace("[paths]", '[paths]\nrecords = "process"\nrecords_required = true', 1) if "[paths]" in text \
        else text + '\n[paths]\nrecords = "process"\nrecords_required = true\n'
    (tmp_path / "steward.toml").write_text(text)
    _, rep = cli.check(tmp_path)
    res = one(rep, "R-01")
    assert res["status"] == "INCOMPLETE" and "R-01.records_missing" in codes(res)
    (tmp_path / "process").mkdir()
    (tmp_path / "process/DECISIONS.md").write_text("# Decisions\n")
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-01")["status"] == "PASS"
