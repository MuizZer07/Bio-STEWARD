"""0.17.0: pinned-dependency retirement (REQ-019; a deprecated stage first, Muiz 2026-11-24)."""

import json
import shutil

import pytest

from conftest import codes, one, results
from test_authorize import approve, repo, sh  # noqa: F401  (signed-authorization fixture)

signing = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")

PINS = '''
[[pin]]
name = "lib-1-0"
package = "lib"
version = "1.0"
artifact = "vendor/wheels/lib-1.0-py3-none-any.whl"
module = "lib_1_0"
install = ["vendor/lib_1_0", "scripts/install_lib_1_0.sh"]
retire_when = ["no_callers"]
deprecated = { reason = "replaced by 2.0", target = "2.0" }
install_command = "mkdir -p vendor/lib_1_0 && cp {artifact} vendor/lib_1_0/"
check_command = "test -f vendor/lib_1_0/lib-1.0-py3-none-any.whl"

[[pin]]
name = "lib-1-5"
package = "lib"
version = "1.5"
artifact = "vendor/wheels/lib-1.5-py3-none-any.whl"
module = "lib_1_5"
install = ["vendor/lib_1_5"]
retire_when = ["no_callers", "after:audits/lib-1-5-audit.md"]
deprecated = { reason = "used only by a finished audit" }

[[pin]]
name = "lib-1-8"
package = "lib"
version = "1.8"
artifact = "vendor/wheels/lib-1.8-py3-none-any.whl"
module = "lib_1_8"
protects = ["locks/analysis.lock"]
retire_when = ["after:milestone:paper-2"]
deprecated = { reason = "the lock of a running analysis depends on it" }

[[pin]]
name = "lib-2-0"
package = "lib"
version = "2.0"
artifact = "vendor/wheels/lib-2.0-py3-none-any.whl"
module = "lib_2_0"
retire_when = ["never"]
'''


def _pins(r):
    for v in ("1.0", "1.5", "1.8", "2.0"):
        w = r / f"vendor/wheels/lib-{v}-py3-none-any.whl"
        w.parent.mkdir(parents=True, exist_ok=True)
        w.write_bytes(f"wheel {v}".encode())
    for d in ("vendor/lib_1_0", "vendor/lib_1_5"):
        (r / d).mkdir(parents=True, exist_ok=True)
        (r / d / "__init__.py").write_text("x = 1\n")
    (r / "scripts").mkdir(exist_ok=True)
    (r / "scripts/install_lib_1_0.sh").write_text("echo install\n")
    (r / "locks").mkdir(exist_ok=True)
    (r / "locks/analysis.lock").write_text("lib==1.8\n")
    (r / "audits").mkdir(exist_ok=True)
    (r / "audits/lib-1-5-audit.md").write_text("finished\n")
    (r / "analysis.py").write_text("import lib_1_8\nimport lib_2_0\n")
    with open(r / "steward.toml", "a") as f:
        f.write(PINS)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "pins")
    from steward.cli import main
    assert main(["authorize", "pin", "--repo", str(r)]) == 0  # the reviewed change becomes the trusted baseline


def _status(cli):
    code, out, err = cli("pins", "status", "--json")
    assert code == 0, err
    return {p["name"]: p for p in json.loads(out)["pins"]}


@signing
def test_eligibility_is_computed_with_its_reasons(cli, repo):
    _pins(repo)
    st = _status(cli)
    assert st["lib-1-0"]["state"] == "retire-eligible" and st["lib-1-5"]["state"] == "retire-eligible"
    assert st["lib-1-8"]["state"] == "deprecated" and "paper-2" in " ".join(st["lib-1-8"]["reasons"])
    assert st["lib-2-0"]["state"] == "active" and "object" not in st["lib-2-0"]


@signing
def test_a_deprecated_pin_still_imported_is_reported_and_not_eligible(cli, repo):
    _pins(repo)
    (repo / "uses_old.py").write_text("from lib_1_0 import thing\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "a caller")
    st = _status(cli)
    assert st["lib-1-0"]["state"] == "deprecated" and st["lib-1-0"]["callers"] == ["uses_old.py"]
    _, rep = cli.check(repo, "pins")
    r = next(x for x in results(rep, "R-74") if x["subject"] == "lib-1-0")
    assert r["status"] == "INCOMPLETE" and "R-74.deprecated_in_use" in codes(r)


@signing
def test_retire_is_refused_without_its_approval_and_keeps_the_artifact_with_it(cli, repo):
    _pins(repo)
    code, _, err = cli("pins", "retire", "lib-1-0", "--authorization", "steward/auth/" + "0" * 32)
    assert code == 1 and "NOT AUTHORIZED" in err and (repo / "vendor/lib_1_0").is_dir()
    obj = _status(cli)["lib-1-5"]["object"]  # an approval for another pin
    wrong = approve(cli, repo, action="pin.retire", obj=obj)
    code, _, err = cli("pins", "retire", "lib-1-0", "--authorization", wrong)
    assert code == 65 and "not for this plan" in err and (repo / "vendor/lib_1_0").is_dir()
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)["lib-1-0"]["object"])
    code, out, err = cli("pins", "retire", "lib-1-0", "--authorization", tag)
    assert code == 0, err
    assert not (repo / "vendor/lib_1_0").exists() and not (repo / "scripts/install_lib_1_0.sh").exists()
    assert not (repo / "vendor/wheels/lib-1.0-py3-none-any.whl").exists()
    keep = repo / "pins/retired/lib-1-0"
    assert (keep / "lib-1.0-py3-none-any.whl").read_bytes() == b"wheel 1.0" and (keep / "manifest.json").is_file()
    led = [json.loads(l) for l in (repo / "development/pins.jsonl").read_text().splitlines()]
    rec = next(e for e in led if e.get("kind") == "retire")
    assert {r["path"] for r in rec["removed"]} == {"vendor/lib_1_0", "vendor/lib_1_0/__init__.py",  # Z10: every entry
                                                   "scripts/install_lib_1_0.sh", "vendor/wheels/lib-1.0-py3-none-any.whl"}
    assert _status(cli)["lib-1-0"]["state"] == "retired"
    code, _, err = cli("pins", "retire", "lib-1-5", "--authorization", tag)  # single use
    assert code != 0


@signing
def test_restore_reinstalls_from_the_kept_artifact_and_runs_its_check(cli, repo):
    _pins(repo)
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)["lib-1-0"]["object"])
    assert cli("pins", "retire", "lib-1-0", "--authorization", tag)[0] == 0
    code, out, err = cli("pins", "restore", "lib-1-0")
    assert code == 0, err
    assert "check exit 0" in out and (repo / "vendor/lib_1_0/lib-1.0-py3-none-any.whl").is_file()
    assert "git checkout" in out  # version-specific code comes back from git, said explicitly
    assert _status(cli)["lib-1-0"]["state"] != "retired"


@signing
def test_a_retired_pin_whose_kept_artifact_is_gone_fails_r73(cli, repo):
    _pins(repo)
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)["lib-1-0"]["object"])
    assert cli("pins", "retire", "lib-1-0", "--authorization", tag)[0] == 0
    _, rep = cli.check(repo, "pins")
    assert next(x for x in results(rep, "R-73") if x["subject"] == "lib-1-0")["status"] == "PASS"
    (repo / "pins/retired/lib-1-0/lib-1.0-py3-none-any.whl").unlink()
    _, rep = cli.check(repo, "pins")
    r = next(x for x in results(rep, "R-73") if x["subject"] == "lib-1-0")
    assert r["status"] == "FAIL" and "R-73.artifact_missing" in codes(r)


@signing
def test_an_active_pin_cannot_be_retired_and_retire_when_is_validated(cli, repo):
    _pins(repo)
    tag = approve(cli, repo, action="pin.retire", obj="sha256:" + "a" * 64)
    code, _, err = cli("pins", "retire", "lib-2-0", "--authorization", tag)
    assert code != 0
    t = (repo / "steward.toml").read_text().replace('retire_when = ["never"]', 'retire_when = ["whenever"]')
    (repo / "steward.toml").write_text(t)
    code, _, _ = cli("pins", "status")
    assert code != 0



# ---------------------------------------------------------------- review of 0.17.0: Z1 - Z3, Z5 - Z9
def _retire(cli, repo, name="lib-1-0"):
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)[name]["object"])
    return tag, cli("pins", "retire", name, "--authorization", tag)


@signing
def test_Z1_an_install_path_overlapping_git_or_another_pin_is_refused(cli, repo):
    _pins(repo)
    t = (repo / "steward.toml").read_text().replace('install = ["vendor/lib_1_0", "scripts/install_lib_1_0.sh"]',
                                                     'install = ["vendor/lib_1_0", "vendor/lib_1_5"]')
    (repo / "steward.toml").write_text(t)
    sh(repo, "git", "commit", "-qam", "x")
    from steward.cli import main
    main(["authorize", "pin", "--repo", str(repo)])
    st = _status(cli)["lib-1-0"]
    assert st["state"] == "deprecated" and "overlaps the pin lib-1-5" in " ".join(st["reasons"])


@signing
def test_Z3_an_approval_does_not_survive_a_changed_install_list(cli, repo):
    _pins(repo)
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)["lib-1-0"]["object"])
    (repo / "extra.txt").write_text("keep me\n")
    t = (repo / "steward.toml").read_text().replace('"scripts/install_lib_1_0.sh"]', '"scripts/install_lib_1_0.sh", "extra.txt"]')
    (repo / "steward.toml").write_text(t)
    sh(repo, "git", "commit", "-qam", "x")
    from steward.cli import main
    main(["authorize", "pin", "--repo", str(repo)])
    code, _, err = cli("pins", "retire", "lib-1-0", "--authorization", tag)
    assert code == 65 and "not for this plan" in err and (repo / "extra.txt").exists()


@signing
def test_Z2_an_interrupted_retirement_is_recorded_and_resumed(cli, repo, monkeypatch):
    from steward import pins as pn
    _pins(repo)
    real = pn._remove
    calls = []

    def fail_second(root, entry):
        calls.append(entry["path"])
        if len(calls) == 2:
            raise OSError("disk error")
        return real(root, entry)
    monkeypatch.setattr(pn, "_remove", fail_second)
    tag, (code, _, _) = _retire(cli, repo)
    assert code != 0
    monkeypatch.setattr(pn, "_remove", real)
    assert _status(cli)["lib-1-0"]["state"] == "retiring"
    _, rep = cli.check(repo, "pins")
    r = next(x for x in results(rep, "R-73") if x["subject"] == "lib-1-0")
    assert "R-73.retirement_incomplete" in codes(r)
    code, _, err = cli("pins", "retire", "lib-1-0", "--resume")  # AA1: never without the plan's signed approval
    assert code == 64
    code, out, err = cli("pins", "retire", "lib-1-0", "--resume", "--authorization", tag)
    assert code == 0, err
    assert _status(cli)["lib-1-0"]["state"] == "retired" and not (repo / "vendor/lib_1_0").exists()


@signing
def test_Z5_the_pins_ledger_records_the_approval_it_used(cli, repo):
    _pins(repo)
    tag, (code, _, err) = _retire(cli, repo)
    assert code == 0, err
    led = [json.loads(l) for l in (repo / "development/pins.jsonl").read_text().splitlines()]
    assert any(e.get("kind") == "retiring" and e.get("nonce") for e in led)


@signing
def test_Z6_Z7_a_caller_always_blocks_and_a_pin_without_module_is_never_eligible(cli, repo):
    _pins(repo)
    t = (repo / "steward.toml").read_text().replace('module = "lib_1_5"\n', "")
    (repo / "steward.toml").write_text(t)
    st = _status(cli)["lib-1-5"]
    assert st["state"] == "deprecated" and "cannot be told" in " ".join(st["reasons"])
    (repo / "multi.py").write_text("import os, lib_1_0 as old\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "x")
    assert _status(cli)["lib-1-0"]["callers"] == ["multi.py"]


@signing
def test_Z8_a_failed_check_keeps_the_pin_retired(cli, repo):
    _pins(repo)
    tag, (code, _, err) = _retire(cli, repo)
    assert code == 0, err
    t = (repo / "steward.toml").read_text().replace('check_command = "test -f vendor/lib_1_0/lib-1.0-py3-none-any.whl"',
                                                     'check_command = "false"')
    (repo / "steward.toml").write_text(t)
    code, out, _ = cli("pins", "restore", "lib-1-0")
    assert code == 65 and "NOT restored" in out and _status(cli)["lib-1-0"]["state"] == "retired"


@signing
def test_Z9_a_retired_pin_whose_declaration_was_removed_is_still_checked(cli, repo):
    _pins(repo)
    tag, (code, _, err) = _retire(cli, repo)
    assert code == 0, err
    (repo / "pins/retired/lib-1-0/lib-1.0-py3-none-any.whl").unlink()
    t = (repo / "steward.toml").read_text()
    a = t.index("[[pin]]\nname = \"lib-1-0\"")
    b = t.index("[[pin]]\nname = \"lib-1-5\"")
    (repo / "steward.toml").write_text(t[:a] + t[b:])
    _, rep = cli.check(repo, "pins")
    r = next(x for x in results(rep, "R-73") if x["subject"] == "lib-1-0")
    assert r["status"] == "FAIL" and "R-73.artifact_missing" in codes(r)



# ---------------------------------------------------------------- follow-up review: AA1 - AA9
@signing
def test_AA2_resume_never_removes_the_original_when_the_kept_copy_is_gone(cli, repo, monkeypatch):
    from steward import pins as pn
    _pins(repo)
    real = pn._remove
    monkeypatch.setattr(pn, "_remove", lambda root, entry: (_ for _ in ()).throw(OSError("stop")))
    tag, (code, _, _) = _retire(cli, repo)
    monkeypatch.setattr(pn, "_remove", real)
    (repo / "pins/retired/lib-1-0/lib-1.0-py3-none-any.whl").unlink()
    code, _, err = cli("pins", "retire", "lib-1-0", "--resume", "--authorization", tag)
    assert code == 65 and "kept artifact" in err and (repo / "vendor/wheels/lib-1.0-py3-none-any.whl").exists()


@signing
def test_AA4_an_alias_spelling_of_another_pin_is_refused(cli, repo):
    _pins(repo)
    t = (repo / "steward.toml").read_text().replace('install = ["vendor/lib_1_0", "scripts/install_lib_1_0.sh"]',
                                                     'install = ["vendor/lib_1_0", "vendor/./lib_1_5"]')
    (repo / "steward.toml").write_text(t)
    sh(repo, "git", "commit", "-qam", "x")
    from steward.cli import main
    main(["authorize", "pin", "--repo", str(repo)])
    assert "overlaps the pin lib-1-5" in " ".join(_status(cli)["lib-1-0"]["reasons"])


@signing
def test_AA5_a_folder_changed_after_the_plan_is_left_in_place(cli, repo, monkeypatch):
    from steward import pins as pn
    _pins(repo)
    tag = approve(cli, repo, action="pin.retire", obj=_status(cli)["lib-1-0"]["object"])
    real = pn._write_kept

    def plant(*a, **k):
        real(*a, **k)
        (repo / "vendor/lib_1_0/new.py").write_text("planted after the plan\n")
    monkeypatch.setattr(pn, "_write_kept", plant)
    code, _, err = cli("pins", "retire", "lib-1-0", "--authorization", tag)
    assert code == 65 and "not the planned folder" in err
    left = [p for p in (repo / "vendor").iterdir() if "steward-retire" in p.name]
    assert left and (left[0] / "new.py").exists()  # nothing unplanned was deleted


@signing
def test_AA6_r74_is_unknown_when_callers_cannot_be_told(cli, repo):
    _pins(repo)
    t = (repo / "steward.toml").read_text().replace('module = "lib_1_5"\n', "")
    (repo / "steward.toml").write_text(t)
    _, rep = cli.check(repo, "pins")
    r = next(x for x in results(rep, "R-74") if x["subject"] == "lib-1-5")
    assert r["status"] == "UNKNOWN" and "R-74.callers_unavailable" in codes(r)
