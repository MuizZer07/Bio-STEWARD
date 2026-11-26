"""0.19.0 release review (b142183): AF1 – AF19 regression tests."""

import subprocess
from types import SimpleNamespace

import pytest

from conftest import codes, results
from test_v0120_features import gsh, xproj  # noqa: F401
from test_v0190_licence import MIT, _lock, _pkg, _setup
from test_v0190_publish import AUTHOR, _dev


def _snapshot(x):
    files = sorted(str(p.relative_to(x)) for p in x.rglob("*") if ".git" not in p.parts)
    refs = subprocess.run(["git", "show-ref"], cwd=x, capture_output=True, text=True).stdout
    remotes = subprocess.run(["git", "remote", "-v"], cwd=x, capture_output=True, text=True).stdout
    return files, refs, remotes


@pytest.mark.parametrize("staging", [".", "..", "src", ".steward", ".steward/../src"])
def test_AF1_the_staging_folder_is_never_the_checkout_or_outside(cli, xproj, tmp_path, staging):
    _dev(xproj, tmp_path, f'staging = "{staging}"\n')
    before = _snapshot(xproj)
    code, _, err = cli("release", "publish", "v1.0.0")
    assert code == 65 and "staging" in err
    assert _snapshot(xproj) == before


def test_AF1_a_linked_staging_folder_is_refused(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    (xproj / ".steward").mkdir(exist_ok=True)
    (xproj / ".steward/publish").symlink_to(xproj)
    code, _, err = cli("release", "publish", "v1.0.0")
    assert code == 65 and "link" in err


def test_AF2_AF3_the_staged_tree_is_the_scanned_export_and_a_tampered_stage_is_refused(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    from steward import publish as pb
    from steward.models import load_config
    files, _, _ = pb.build(xproj, load_config(xproj), "v1.0.0")
    assert pb._tree_matches(stage, "v1.0.0", files)
    (stage / "src/tool.py").write_text("tampered\n")  # change and retag the staged release
    gsh(stage, "git", "add", "-A")
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-qm", "x"], cwd=stage, check=True)
    gsh(stage, "git", "tag", "-f", "-a", "v1.0.0", "-m", "x")
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and ("differs" in err or "did not build" in err)  # refused before anything is sent
    assert subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout.strip() == ""
    gsh(stage, "git", "remote", "set-url", "origin", str(tmp_path / "elsewhere.git"))
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and "origin" in err


def test_AF4_private_records_ids_names_and_binaries_are_refused(cli, xproj, tmp_path):
    t = (xproj / "steward.toml").read_text().replace('code = "AAA"', 'code = "AAA"\nconsumers = ["RRR"]')
    (xproj / "steward.toml").write_text(t)
    _dev(xproj, tmp_path)
    (xproj / "src/notes.py").write_text("# fixed for RRR-REQ-012\n")
    (xproj / "src/RRR-FB-001.py").write_text("x = 1\n")
    (xproj / "src/blob.bin").write_bytes(b"\x00\x01private")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-a", "v1.3.0", "-m", "v1.3.0")
    code, out, _ = cli("release", "publish", "v1.3.0", "--dry-run")
    assert code == 65
    assert "src/notes.py:1: a private item ID" in out and "(a file whose path holds a private term or item ID)" in out
    assert "RRR-FB-001" not in out
    assert "src/blob.bin: a binary file cannot be scanned" in out
    assert "RRR-REQ-012" not in out  # the refusal never prints the private value


def test_AF5_the_licence_gate_judges_the_tag_at_public_strictness(cli, xproj, tmp_path):
    _setup(xproj, distribution="internal")
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-only")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    cli("licence", "notices", "--write")
    _dev(xproj, tmp_path)
    code, out, _ = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code == 65 and "R-80: copyleft 2.0: FAIL" in out  # internal passes; the public mirror does not
    _lock(xproj, [("goodlib", "1.0")])  # fixed after the tag: the tag is still judged
    code, out, _ = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code == 65 and "copyleft" in out


def test_AF6_status_and_publish_without_push_never_use_the_network(cli, xproj, tmp_path, monkeypatch):
    _dev(xproj, tmp_path)
    from steward import publish as pb
    calls = []
    real = pb._git
    monkeypatch.setattr(pb, "_git", lambda *a, **k: (calls.append(k.get("network", False)), real(*a, **k))[1])
    assert cli("release", "publish", "v1.0.0")[0] == 0
    assert cli("release", "status")[0] == 0
    assert not any(calls)
    cli("release", "publish", "v1.0.0", "--push")
    assert any(calls)


def test_AF7_an_invalid_lock_and_a_version_mismatch_are_unknown(cli, xproj):
    _setup(xproj)
    (xproj / "uv.lock").write_text("not [valid")
    _, rep = cli.check(xproj, "licence")
    r = results(rep, "R-80")[0]
    assert r["status"] != "PASS" and "R-80.inventory" in codes(r)  # never an empty, passing inventory
    _lock(xproj, [("goodlib", "2.0")])  # installed 1.0
    _, rep = cli.check(xproj, "licence")
    r = results(rep, "R-80")[0]
    assert "R-80.unknown" in codes(r) and "locked 2.0" in str(r["details"])


def test_AF9_an_exception_covers_only_its_licence(cli, xproj):
    import datetime as dt
    future = dt.date.today() + dt.timedelta(days=30)
    _setup(xproj, extra='exceptions = "development/exc.toml"\n')
    _pkg(xproj, "copyleft", "2.0", "AGPL-3.0-only")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/exc.toml").write_text(f'schema = "steward.licence-exceptions/1"\n[[exception]]\ntarget = "copyleft"\n'
                                                f'licence = "GPL-3.0-only"\nreason = "r"\napprover = "a"\ndate = 2026-11-25\nexpires = {future}\n')
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    assert results(rep, "R-80")[0]["status"] == "FAIL"  # the exception named GPL; the package is now AGPL


def test_AF10_a_declaration_never_hides_a_conflicting_header(cli, xproj):
    _setup(xproj, extra='third_party = "development/tp.toml"\n')
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/tp.toml").write_text('schema = "steward.third-party/1"\n[[item]]\npath = "src/a.py"\n'
                                               'licence = "MIT"\nsource = "x"\n')
    (xproj / "src").mkdir()
    (xproj / "src/a.py").write_text("# SPDX-License-Identifier: GPL-3.0-only\n")
    gsh(xproj, "git", "add", "-A")
    _, rep = cli.check(xproj, "licence")
    assert results(rep, "R-81")[0]["status"] == "FAIL"


def test_AF11_with_needs_an_exception_and_and_keeps_its_copyleft():
    from steward import licence as li
    with pytest.raises(ValueError):
        li.parse_expr("MIT WITH OR GPL-3.0-only")
    assert li.expr_family(li.parse_expr("MIT AND GPL-3.0-only")) == "strong"
    assert li.expr_family(li.parse_expr("MIT OR GPL-3.0-only")) == "permissive"
    rows = [{"name": "lib", "version": "2.0", "licence": "MIT"}]
    assert li.notices_current("- lib 1.0: MIT\n", rows)  # an older version's line is not current


def test_AF12_linked_metadata_is_a_problem_not_a_smaller_inventory(cli, xproj, tmp_path):
    _setup(xproj)
    outside = tmp_path / "out.dist-info"
    outside.mkdir()
    (outside / "METADATA").write_text("Name: evil\nVersion: 1\nLicense-Expression: MIT\n")
    (xproj / ".venv/lib/python3.11/site-packages/evil-1.dist-info").symlink_to(outside)
    from steward import licence as li
    env, problems = li.installed(xproj, [".venv/lib/python3*/site-packages"])
    assert "evil" not in env and problems


def test_AF13_a_valid_ledger_from_another_repository_is_not_a_receipt(tmp_path):
    from steward import exchange as xc
    from steward.ledger import Ledger
    r = tmp_path / "peer"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "steward.toml").write_text('[steward]\nschema = "steward.toml/0.2"\nrepo_id = "11111111-1111-4111-8111-111111111111"\nproject = "p"\n')
    (r / "exchange").mkdir()
    Ledger(r / "exchange/log.jsonl", "exchange", "22222222-2222-4222-8222-222222222222").append("state", {"item": "AAA-REQ-001", "state": "acknowledged"})
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-qm", "x"], cwd=r, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    assert xc.peer_history(r, sha) is None


def test_AF15_a_linked_pending_queue_is_refused_before_writing(tmp_path):
    from steward import authorize as az
    from steward.fsutil import LinkRefused, safe_write
    (tmp_path / ".steward").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".steward/pending").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(LinkRefused):
        safe_write(tmp_path, ".steward/pending/x.txt", b"x", exclusive=True)
    assert not list((tmp_path / "elsewhere").iterdir())
    assert "safe_write" in az.prepare.__code__.co_names  # prepare writes the queue only that way


def test_AF16_the_plan_reads_message_bodies_and_states_its_coverage(cli, xproj):
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n') if "[exchange]" not in (xproj / "steward.toml").read_text() else None
    gsh(xproj, "git", "commit", "-q", "--allow-empty", "-m", "subject\n\nbody names BBB-REQ-004")
    from steward import publish as pb
    from steward.models import load_config
    plan = pb.open_plan(xproj, load_config(xproj))
    assert plan["commits_with_private_content"] >= 1 and "file contents" in plan["coverage"]


def test_AF18_goal_init_never_appends_through_a_linked_config(cli, tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    real = tmp_path / "real.toml"
    real.write_text((d / "steward.toml").read_text())
    (d / "steward.toml").unlink()
    (d / "steward.toml").symlink_to(real)
    before = real.read_text()
    cli("init", "--repo", d, "--for", "reanalysis")
    assert real.read_text() == before


def test_AF19_quiet_never_hides_delivery_advice(cli, xproj, monkeypatch):
    from steward import cli as c
    rep = {"verdict": {"gates": [{"eligible": True, "name": "default"}], "results": [
        {"rule": "R-53", "status": "PASS", "details": [{"code": "R-53.undelivered"}]}]}}
    assert any(d.get("code") in c.QUIET_BREAKERS for r in rep["verdict"]["results"] for d in r["details"])


# ================================================================ the re-verification (b544d17): AF partials, AG1 – AG5
def _full_snapshot(x):
    files = {str(p.relative_to(x)): (p.read_bytes() if p.is_file() and not p.is_symlink() else b"")
             for p in x.rglob("*") if ".git" not in p.parts}
    git = lambda *a: subprocess.run(["git", *a], cwd=x, capture_output=True, text=True).stdout
    return files, git("show-ref"), git("remote", "-v"), git("rev-parse", "HEAD"), git("ls-files", "-s")


@pytest.mark.parametrize("staging", [".steward", ".steward/.", ".steward/sub/.."])
def test_AF1_staging_is_never_steward_itself(cli, xproj, tmp_path, staging):
    _dev(xproj, tmp_path, f'staging = "{staging}"\n')
    before = _full_snapshot(xproj)
    assert cli("release", "publish", "v1.0.0")[0] == 65
    assert _full_snapshot(xproj) == before


def test_AF1_a_linked_git_folder_in_staging_is_refused(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    (xproj / ".steward/publish").mkdir(parents=True)
    (xproj / ".steward/publish/.git").symlink_to(xproj / ".git")
    before = _full_snapshot(xproj)
    code, _, err = cli("release", "publish", "v1.0.0")
    assert code == 65 and ".git" in err and _full_snapshot(xproj) == before


def test_AF2_a_planted_filter_in_the_staging_config_refuses_and_runs_nothing(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    gsh(xproj, "git", "tag", "-a", "v1.0.1", "-m", "v1.0.1")
    marker = tmp_path / "ran"
    stage = xproj / ".steward/publish"
    subprocess.run(["git", "config", "filter.x.clean", f"touch {marker}; cat"], cwd=stage, check=True)
    (stage / ".gitattributes").write_text("* filter=x\n")
    code, _, err = cli("release", "publish", "v1.0.1")
    assert code == 65 and "filter.x.clean" in err and not marker.exists()


def test_AF3_a_changed_staging_branch_and_a_rewritten_push_url_are_refused(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=stage, check=True)
    gsh(xproj, "git", "tag", "-a", "v1.0.1", "-m", "v1.0.1")
    code, _, err = cli("release", "publish", "v1.0.1")
    assert code == 65 and "did not build" in err
    subprocess.run(["git", "reset", "-q", "--hard", "v1.0.0"], cwd=stage, check=True)
    subprocess.run(["git", "config", "remote.origin.pushurl", str(tmp_path / "other.git")], cwd=stage, check=True)
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and ("push" in err or "did not write" in err)
    assert subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout.strip() == ""


def test_AG1_an_older_release_never_moves_the_public_branch_back(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    assert cli("release", "publish", "v2.0.0", "--push")[0] == 0
    tip = subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout == tip


def test_AG2_status_counts_only_what_was_sent(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    cli("release", "publish", "v1.0.0")
    _, out, _ = cli("release", "status")
    assert "(not pushed yet)" in out and "not yet published: v1.0.0" in out
    cli("release", "publish", "v1.0.0", "--push")
    _, out, _ = cli("release", "status")
    assert "(pushed)" in out and "not yet published: nothing" in out


def test_AF4_records_root_term_lists_excluded_and_binaries_allowed_by_policy(cli, xproj, tmp_path):
    (xproj / "private").mkdir()
    (xproj / "private/notes.md").write_text("internal\n")
    t = (xproj / "steward.toml").read_text().replace("[paths]", '[paths]\nrecords = "private"', 1)
    (xproj / "steward.toml").write_text(t)
    (xproj / "lists").mkdir()
    (xproj / "lists/terms.txt").write_text("Zebrafinch\n")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "p"\nfile = "lists/terms.txt"\n')
    _dev(xproj, tmp_path, 'binary = ["**/*.png"]\n')
    (xproj / "src/logo.png").write_bytes(b"\x89PNG\x00\x01")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-a", "v1.4.0", "-m", "v1.4.0")
    from steward import publish as pb
    from steward.models import load_config
    files, _, findings = pb.build(xproj, load_config(xproj), "v1.4.0")
    assert "private/notes.md" not in files and "lists/terms.txt" not in files and "src/logo.png" in files
    assert not [f for f in findings if "logo" in f]


def test_AF5_missing_notices_in_the_export_refuse_and_a_clean_tag_passes(cli, xproj, tmp_path):
    _setup(xproj)
    _dev(xproj, tmp_path)
    code, out, _ = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code == 65 and "THIRD_PARTY_NOTICES.md is not among the published files" in out
    cli("licence", "notices", "--write")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "notices")
    gsh(xproj, "git", "tag", "-a", "v1.0.1", "-m", "v1.0.1")
    _pkg(xproj, "copyleft", "2.0", "AGPL-3.0-only")  # a later problem in the working tree only
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    code, out, err = cli("release", "publish", "v1.0.1", "--dry-run")
    assert code == 0, out + err


def test_AF6_session_start_check_and_numbering_never_fetch(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    calls = []
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: (calls.append(a), (_ for _ in ()).throw(AssertionError("fetched")))[1])
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\nconsumers = ["BBB"]\npeers = { BBB = { url = "https://example.org/b.git" } }\n')
    cli("exchange", "init", "--repo", d)
    xc.record_peer_ids(d, "BBB", set())  # as a pull would have (AH2)
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "x", "--repo", d)[0] == 0
    code, out, err = cli("session", "start", "--repo", d)
    assert code == 0, err
    code, out, err = cli("check", "--repo", d, "--summary")
    assert out.startswith("Summary:"), err
    assert not calls


def test_AF7_malformed_package_and_missing_version_are_unknown_and_an_empty_lock_passes(cli, xproj):
    _setup(xproj)
    (xproj / "uv.lock").write_text('version = 1\n[[package]]\nversion = "1.0"\n')
    _, rep = cli.check(xproj, "licence")
    assert "R-80.inventory" in codes(results(rep, "R-80")[0])
    d = xproj / ".venv/lib/python3.11/site-packages/nover-1.0.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text("Name: nover\nLicense-Expression: MIT\n")
    _lock(xproj, [("goodlib", "1.0"), ("nover", "1.0")])
    _, rep = cli.check(xproj, "licence")
    assert "R-80.unknown" in codes(results(rep, "R-80")[0])
    (xproj / "uv.lock").write_text("version = 1\n")
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    assert results(rep, "R-80")[0]["status"] == "PASS"


def test_AF8_each_release_section_carries_its_known_issues():
    import re
    from pathlib import Path

    from steward import exchange as xc
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text()
    assert re.search(r"^### Known issues", xc.changelog_section(text, "0.19.0"), re.M)


def test_AF9_scope_and_with_clauses_decide_an_exception():
    from steward import licence as li
    assert not li.same_licence("GPL-2.0-only WITH Classpath-exception-2.0", "GPL-2.0-only")
    import datetime as dt
    e = li.Exception_(target="lib", licence="GPL-3.0-only", reason="r", scope="other", approver="a",
                      date=dt.date(2026, 11, 25), expires=dt.date(2099, 1, 1))
    assert li.match_exception([e], "lib", "GPL-3.0-only") is None
    e2 = e.model_copy(update={"scope": "project"})
    assert li.match_exception([e2], "lib", "GPL-3.0-only") is e2


def test_AF11_a_near_version_or_near_licence_is_not_current():
    from steward import licence as li
    rows = [{"name": "lib", "version": "2.0", "licence": "MIT"}]
    assert li.notices_current("- lib 2.0.1: MIT\n", rows)
    assert li.notices_current("- lib 2.0: MIT-0\n", rows)
    assert not li.notices_current("- lib 2.0: MIT\n", rows)


def test_AF12_a_linked_environment_or_term_list_is_never_a_clean_result(cli, xproj, tmp_path):
    from steward import docsite
    from steward import licence as li
    from steward.models import load_config
    (tmp_path / "env").mkdir()
    (xproj / ".venv/lib/python3.11").mkdir(parents=True)
    (xproj / ".venv/lib/python3.11/site-packages").symlink_to(tmp_path / "env")
    _, problems = li.installed(xproj, [".venv/lib/python3*/site-packages"])
    assert problems
    (tmp_path / "terms.txt").write_text("x\n")
    (xproj / "terms.txt").symlink_to(tmp_path / "terms.txt")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "p"\nfile = "terms.txt"\n')
    assert docsite.scan(xproj, load_config(xproj), "text")  # an unusable list refuses


def test_AF14_private_terms_in_paths_and_models_are_withheld(tmp_path):
    from steward import tokens
    (tmp_path / "steward.toml").write_text('[steward]\nschema = "steward.toml/0.2"\nrepo_id = "5eed5eed-0000-4000-8000-000000000002"\nproject = "p"\n\n[[terms]]\nname = "p"\nfile = "t.txt"\n')
    (tmp_path / "t.txt").write_text("Zebrafinch\n")
    rows = [{"files_read": [{"path": str(tmp_path / "Zebrafinch/a.py"), "reads": 2}], "tool_outputs": [],
             "models": [{"model": "zebrafinch-tuned", "tokens": 5}]}]
    out, _ = tokens._redact(tmp_path, rows, {})
    assert "Zebrafinch" not in str(out).replace("withheld", "") and out[0]["models"][0]["tokens"] == 5


def test_AF15_AG5_policy_inputs_missing_or_linked(tmp_path):
    from types import SimpleNamespace

    from steward import authorize as az
    cfg = SimpleNamespace(policy=SimpleNamespace(allowed_signers="keys/allowed", revoked="keys/revoked"), terms=[])
    (tmp_path / "steward.toml").write_text("x\n")
    obj, parts = az.policy_bundle(tmp_path, cfg)  # AG5: an absent folder is absent evidence
    assert parts["keys/allowed"] is None
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "keys").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(az.AuthError):
        az.policy_bundle(tmp_path, cfg)  # AF15: a linked folder is refused, never "absent"


def test_AF16_a_history_hit_only_in_a_changed_path_is_counted(cli, xproj):
    (xproj / "BBB-REQ-077.md").write_text("x\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "an ordinary message")
    from steward import publish as pb
    from steward.models import load_config
    plan = pb.open_plan(xproj, load_config(xproj))
    assert plan["commits_with_private_content"] >= 1 and "paths each commit changed" in plan["coverage"]


def test_AF18_linked_config_is_refused_with_an_error(cli, tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    real = tmp_path / "real.toml"
    real.write_text((d / "steward.toml").read_text())
    (d / "steward.toml").unlink()
    (d / "steward.toml").symlink_to(real)
    assert cli("init", "--repo", d, "--for", "reanalysis")[0] == 65
    assert cli("release", "setup", "--repo", d, "--mode", "mirror")[0] == 65
    import tomllib
    assert not {"publish", "studies"} & set(tomllib.loads(real.read_text()))


def test_AF19_quiet_prints_the_summary_when_delivery_advice_exists(cli, tmp_path, monkeypatch):
    from steward import cli as c
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    real = c.run_check

    def fake(*a, **k):
        rep = real(*a, **k)
        rep["verdict"]["results"][0]["details"].append({"code": "R-53.undelivered", "message": "overdue"})
        return rep
    monkeypatch.setattr(c, "run_check", fake)
    code, out, err = cli("check", "--repo", d, "--quiet")
    assert out.startswith("Summary:"), (code, out, err)


def test_AG3_a_repaired_lock_after_an_unreadable_committed_one_is_judged(cli, xproj):
    _setup(xproj)
    (xproj / "uv.lock").write_text("not [valid")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "bad lock")
    _lock(xproj, [("goodlib", "1.0")])
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = results(rep, "R-80")[0]
    assert r["status"] == "PASS" and "R-80.baseline_unavailable" in codes(r)


def test_AG4_a_malformed_receiver_config_is_unchecked(tmp_path):
    from steward import exchange as xc
    from steward.ledger import Ledger
    r = tmp_path / "peer"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "steward.toml").write_text('steward = "not a table"\n')
    (r / "exchange").mkdir()
    Ledger(r / "exchange/log.jsonl", "exchange", "x").append("state", {"item": "AAA-REQ-001", "state": "acknowledged"})
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-qm", "x"], cwd=r, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    assert xc.peer_history(r, sha) is None


# ================================================================ the second re-verification (ebcf843): partials, AH1 – AH3
def test_AF1_an_absolute_staging_spelling_is_refused(cli, xproj, tmp_path):
    _dev(xproj, tmp_path, 'staging = "/.steward/publish"\n')
    assert cli("release", "publish", "v1.0.0")[0] == 65


def test_AF4_non_text_is_opaque_and_no_part_of_a_private_path_is_printed(cli, xproj, tmp_path):
    t = (xproj / "steward.toml").read_text().replace('code = "AAA"', 'code = "AAA"\nconsumers = ["RRR"]')
    (xproj / "steward.toml").write_text(t)
    _dev(xproj, tmp_path)
    (xproj / "RRR-REQ-009").mkdir()
    (xproj / "RRR-REQ-009/x.md").write_text("x\n")
    (xproj / "src/latin.txt").write_bytes("caf\xe9".encode("latin-1"))
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-a", "v1.5.0", "-m", "v1.5.0")
    code, out, _ = cli("release", "publish", "v1.5.0", "--dry-run")
    assert code == 65 and "RRR-REQ-009" not in out and "src/latin.txt: a binary file" in out


def test_AF5_the_tags_own_licence_table_runs_the_gate(cli, xproj, tmp_path):
    _setup(xproj)
    _dev(xproj, tmp_path)
    t = (xproj / "steward.toml").read_text()
    (xproj / "steward.toml").write_text(t[:t.index("\n[licence]")] + t[t.index("\n[publish]"):])  # removed after the tag
    code, out, _ = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code == 65 and "licence:" in out


def test_AF7_a_locked_package_without_a_version_is_unknown(cli, xproj):
    _setup(xproj)
    (xproj / "uv.lock").write_text('version = 1\n[[package]]\nname = "goodlib"\n')
    _, rep = cli.check(xproj, "licence")
    assert "R-80.unknown" in codes(results(rep, "R-80")[0])


def test_AF9_only_and_or_later_are_different_for_an_exception():
    import datetime as dt

    from steward import licence as li
    e = li.Exception_(target="lib", licence="GPL-3.0-only", reason="r", approver="a",
                      date=dt.date(2026, 11, 25), expires=dt.date(2099, 1, 1))
    assert li.match_exception([e], "lib", "GPL-3.0-or-later") is None


def test_AF12_a_linked_dist_info_without_metadata_is_named(tmp_path):
    from steward import licence as li
    sp = tmp_path / ".venv/lib/python3.11/site-packages"
    sp.mkdir(parents=True)
    (tmp_path / "empty").mkdir()
    (sp / "ghost-1.0.dist-info").symlink_to(tmp_path / "empty")
    _, problems = li.installed(tmp_path, [".venv/lib/python3*/site-packages"])
    assert any("ghost" in p for p in problems)


def test_AF14_a_lowercase_private_model_name_is_withheld(tmp_path):
    from steward import tokens
    (tmp_path / "steward.toml").write_text('[steward]\nschema = "steward.toml/0.2"\nrepo_id = "5eed5eed-0000-4000-8000-000000000003"\nproject = "p"\n\n[[terms]]\nname = "p"\nfile = "t.txt"\n')
    (tmp_path / "t.txt").write_text("Zebrafinch\n")
    rows = [{"files_read": [], "tool_outputs": [], "models": [{"model": "zebrafinch-tuned", "tokens": 5}]}]
    out, _ = tokens._redact(tmp_path, rows, {})
    assert "zebrafinch" not in out[0]["models"][0]["model"].lower() and out[0]["models"][0]["tokens"] == 5


def test_AF18_goal_init_on_a_linked_config_writes_nothing(cli, tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    real = tmp_path / "real.toml"
    real.write_text("x = 1\n")
    (d / "steward.toml").symlink_to(real)
    assert cli("init", "--repo", d, "--for", "reanalysis")[0] == 65
    assert real.read_text() == "x = 1\n" and not (d / "development").exists()


def test_AH1_a_public_branch_at_the_release_gets_its_missing_tag(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    subprocess.run(["git", "push", "-q", "origin", "v1.0.0^{commit}:refs/heads/main"], cwd=stage, check=True)  # branch only
    tip = subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout
    code, out, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 0, err
    assert "v1.0.0" in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout
    assert subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout == tip


def test_AH2_numbering_with_a_url_peer_needs_its_recorded_ids(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\npeers = { BBB = { url = "https://example.org/b.git" } }\n')
    cli("exchange", "init", "--repo", d)
    code, _, err = cli("exchange", "new", "request", "--to", "BBB", "--title", "x", "--repo", d)
    assert code == 64 and "exchange pull BBB" in err
    xc.record_peer_ids(d, "BBB", {"AAA-REQ-007"})
    code, out, _ = cli("exchange", "new", "request", "--to", "BBB", "--title", "x", "--repo", d)
    assert code == 0 and "AAA-REQ-008" in out


def test_AH3_a_merge_with_a_private_changed_path_is_counted(cli, xproj):
    gsh(xproj, "git", "commit", "-q", "--allow-empty", "-m", "base")
    gsh(xproj, "git", "checkout", "-q", "-b", "side")
    (xproj / "BBB-REQ-088.md").write_text("x\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "ordinary")
    gsh(xproj, "git", "checkout", "-q", "-")
    gsh(xproj, "git", "merge", "-q", "--no-ff", "-m", "merge", "side")
    from steward import publish as pb
    from steward.models import load_config
    assert pb.open_plan(xproj, load_config(xproj))["commits_with_private_content"] >= 2  # the commit and its merge


# ---------------------------------------------------------------- STW-027 (f9beeac): AI1 – AI4 and partial verdicts
def _failing(pb, monkeypatch, *match):
    real = pb._git

    def fake(cwd, *args, **kw):
        if args[:len(match)] == match:
            if kw.get("check", True):
                raise pb.PublishError(f"git {args[0]} failed")
            return subprocess.CompletedProcess(args, 128, "", "fatal: unreachable")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(pb, "_git", fake)


@pytest.mark.parametrize("match", [("ls-remote", "--tags"), ("ls-remote", "--heads"), ("fetch",)])
def test_AI1_no_evidence_of_the_public_releases_refuses_the_push(cli, xproj, tmp_path, monkeypatch, match):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    tip = subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout
    from steward import publish as pb
    _failing(pb, monkeypatch, *match)
    code, _, err = cli("release", "publish", "v2.0.0", "--push")
    assert code == 65 and "nothing pushed" in err, err
    assert subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout == tip
    assert "v2.0.0" not in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout


def test_AF3_the_first_publication_sends_one_parentless_commit(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    assert cli("release", "publish", "v2.0.0", "--push")[0] == 0  # v1.0.0 was staged, never sent
    log = subprocess.run(["git", "rev-list", "main"], cwd=pub, capture_output=True, text=True).stdout.split()
    assert len(log) == 1


def test_AF3_every_local_staging_branch_is_checked(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    gsh(stage, "git", "checkout", "-q", "-b", "other")
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-q", "--allow-empty",
                    "-m", "x"], cwd=stage, check=True)
    gsh(stage, "git", "checkout", "-q", "main")
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and "did not build" in err


def test_AI2_a_malformed_peer_id_record_refuses_and_a_record_keeps_valid_ids(cli, tmp_path, monkeypatch):
    import json

    from steward import exchange as xc
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\npeers = { BBB = { url = "https://example.org/b.git" } }\n')
    cli("exchange", "init", "--repo", d)
    (d / ".steward").mkdir(exist_ok=True)
    (d / xc.SEEN).write_text(json.dumps({"BBB": ["AAA-REQ-004", {"x": 1}], "CCC": ["AAA-REQ-009"]}))
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    code, _, err = cli("exchange", "new", "request", "--to", "BBB", "--title", "x", "--repo", d)
    assert code != 0 and "exchange pull BBB" in err and "Traceback" not in err
    xc.record_peer_ids(d, "BBB", {"AAA-REQ-005"})
    doc = json.loads((d / xc.SEEN).read_text())
    assert doc["BBB"] == ["AAA-REQ-004", "AAA-REQ-005"] and doc["CCC"] == ["AAA-REQ-009"]


def test_AI3_each_export_keeps_its_own_file_modes(tmp_path):
    from steward import publish as pb
    r = tmp_path / "s"
    r.mkdir()
    gsh(r, "git", "init", "-q")
    (r / "run.sh").write_text("x\n")
    (r / "run.sh").chmod(0o755)
    gsh(r, "git", "add", "-A")
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-qm", "x"], cwd=r, check=True)
    exe, plain = pb.Export({"run.sh": b"x\n"}), pb.Export({"run.sh": b"x\n"})
    exe.executable.add("run.sh")
    assert not pb._tree_matches(r, "HEAD", plain) and pb._tree_matches(r, "HEAD", exe)  # in either order


def test_AI4_announce_refuses_before_shipping_when_a_notice_cannot_be_numbered(cli, xproj, monkeypatch):
    from test_v0120_features import _receiver

    from steward import exchange as xc
    _receiver(cli, xproj)
    with open(xproj / "steward.toml", "a") as f:
        f.write('peers = { BBB = { url = "https://example.org/b.git" } }\n')
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    before = (xproj / "exchange/log.jsonl").read_bytes()
    code, _, err = cli("exchange", "announce", "v1.0.0")
    assert code == 64 and "nothing announced" in err, err
    assert (xproj / "exchange/log.jsonl").read_bytes() == before
    assert not list((xproj / "exchange").glob("*/AAA-REL-*.md"))


def test_AH2_a_pull_with_an_unverifiable_ledger_records_no_ids(cli, tmp_path, monkeypatch):
    import contextlib

    from steward import exchange as xc
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\npeers = { BBB = { url = "https://example.org/b.git" } }\n')
    cli("exchange", "init", "--repo", d)
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: contextlib.nullcontext((d, "0" * 40)))
    monkeypatch.setattr(xc, "peer_outbox", lambda *a, **k: [])
    monkeypatch.setattr(xc, "peer_history", lambda *a, **k: None)
    code, _, err = cli("exchange", "pull", "BBB", "--repo", d)
    assert code != 0 and "cannot be verified" in err
    assert xc.peer_ids_seen(d, "BBB") is None


def test_AF4_the_licence_gate_never_names_a_private_path(cli, xproj, tmp_path):
    _dev(xproj, tmp_path, 'private_codes = ["BBB"]\n')
    (xproj / "LICENSE").write_text(MIT)
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\n')
    (xproj / "src/BBB-REQ-031.py").write_text("# SPDX-License-Identifier: GPL-3.0-only\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "-f", "-a", "v1.0.0", "-m", "v1.0.0")
    code, out, err = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code != 0 and "a private term or item ID" in out + err, out + err
    assert "BBB-REQ-031" not in out + err


def test_AF5_the_tags_licence_table_decides_even_when_steward_toml_is_not_published(cli, xproj, tmp_path):
    _dev(xproj, tmp_path, 'exclude = ["steward.toml"]\n')
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\n')
    gsh(xproj, "git", "commit", "-qam", "licence")
    gsh(xproj, "git", "tag", "-f", "-a", "v1.0.0", "-m", "v1.0.0")
    t = (xproj / "steward.toml").read_text()
    (xproj / "steward.toml").write_text(t[:t.index("\n[licence]")] + "\n")  # the working checkout drops [licence]
    code, out, err = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code != 0 and "LICENSE" in out + err  # the tag's table still requires a LICENSE among the published files


def test_AF7_a_locked_version_that_is_not_text_is_not_evidence():
    from steward import licence as li
    with pytest.raises(ValueError):
        li.lock_packages('[[package]]\nname = "a"\nversion = 1.0\n', "uv.lock")


def test_AF12_a_linked_environment_prefix_is_a_problem_even_when_nothing_matches(tmp_path):
    from steward import licence as li
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".venv").symlink_to(tmp_path / "elsewhere")
    _, problems = li.installed(tmp_path, [".venv/lib/python*/site-packages"])
    assert problems and "link" in problems[0]


def test_AG1_a_prerelease_sorts_before_its_release():
    from steward import publish as pb
    k = pb.semver_key
    assert k("v1.2.0-rc1") < k("v1.2.0") == k("v1.2.0+build.5") < k("v1.2.1")


def test_AG2_status_lists_every_unsent_development_tag(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    gsh(xproj, "git", "tag", "-a", "v0.9.0", "-m", "older, never staged", "HEAD")
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    from steward import publish as pb
    from steward.models import load_config
    assert pb.status(xproj, load_config(xproj))["unpublished"] == ["v0.9.0"]


# ---------------------------------------------------------------- STW-028 (e3e2847): AJ1 – AJ3 and partial verdicts
def test_AJ1_a_failed_read_of_the_tags_configuration_refuses(cli, xproj, tmp_path, monkeypatch):
    _dev(xproj, tmp_path)
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\n')
    gsh(xproj, "git", "commit", "-qam", "licence")
    gsh(xproj, "git", "tag", "-f", "-a", "v1.0.0", "-m", "v1.0.0")
    t = (xproj / "steward.toml").read_text()
    (xproj / "steward.toml").write_text(t[:t.index("\n[licence]")] + "\n")
    from steward import publish as pb
    for match in (("ls-tree",), ("show",)):
        monkeypatch.undo()
        monkeypatch.chdir(xproj)
        _failing(pb, monkeypatch, *match)
        code, out, err = cli("release", "publish", "v1.0.0", "--dry-run")
        assert code != 0 and "cannot be" in out + err, (match, out, err)


def test_AJ2_a_private_path_from_the_tags_configuration_is_withheld(cli, xproj, tmp_path):
    _dev(xproj, tmp_path, 'private_codes = ["BBB"]\nexclude = ["steward.toml"]\n')
    (xproj / "LICENSE").write_text(MIT)
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\nnotices = "notices/BBB-REQ-044.md"\n')
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "licence")
    gsh(xproj, "git", "tag", "-f", "-a", "v1.0.0", "-m", "v1.0.0")
    code, out, err = cli("release", "publish", "v1.0.0", "--dry-run")
    assert code != 0 and "withheld" in out + err
    assert "BBB-REQ-044" not in out + err


def test_AJ3_the_reported_commit_is_the_one_sent(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    code, out, err = cli("release", "publish", "v2.0.0", "--push")
    assert code == 0, err
    tip = subprocess.run(["git", "rev-parse", "--short", "main"], cwd=pub, capture_output=True, text=True).stdout.strip()
    tagged = subprocess.run(["git", "rev-parse", "--short", "v2.0.0^{commit}"], cwd=pub, capture_output=True, text=True).stdout.strip()
    assert tip == tagged and tip in out


def test_AI1_no_local_ref_changes_before_the_remote_is_known(cli, xproj, tmp_path, monkeypatch):
    _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    stage = xproj / ".steward/publish"
    refs = lambda: subprocess.run(["git", "for-each-ref", "refs/heads", "refs/tags"], cwd=stage,  # noqa: E731
                                  capture_output=True, text=True).stdout
    before = refs()
    from steward import publish as pb
    _failing(pb, monkeypatch, "ls-remote", "--tags")
    assert cli("release", "publish", "v2.0.0", "--push")[0] == 65
    assert refs() == before


def test_AI4_announce_numbers_every_notice_once_before_shipping(cli, xproj, monkeypatch):
    from test_v0120_features import _receiver

    from steward import exchange as xc
    _receiver(cli, xproj)
    calls = []
    real = xc.next_id
    monkeypatch.setattr(xc, "next_id", lambda *a, **k: calls.append(a) or real(*a, **k))
    code, out, err = cli("exchange", "announce", "v1.0.0")
    assert code == 0, err
    assert [a[2] for a in calls] == ["release"]  # once, before any state was written


def test_AF3_an_unborn_head_still_has_its_branches_checked(cli, xproj, tmp_path):
    _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-q", "--allow-empty",
                    "-m", "x"], cwd=stage, check=True)
    gsh(stage, "git", "branch", "-q", "stray")
    gsh(stage, "git", "reset", "-q", "--hard", "v1.0.0")
    gsh(stage, "git", "checkout", "-q", "--orphan", "unborn")
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and "did not build" in err


def test_AF7_an_unpinned_requirement_is_not_evidence():
    from steward import licence as li
    with pytest.raises(ValueError):
        li.lock_packages("numpy==2.1.0\npandas>=2\n", "requirements.txt")
    assert li.lock_packages("# a comment\n--index-url https://example.org/simple\nnumpy==2.1.0\n", "requirements.txt") == [("numpy", "2.1.0")]
    for line in ("-r other.txt", "-e .", "./pkg", "git+https://example.org/x.git"):  # AF7 (STW-029)
        with pytest.raises(ValueError):
            li.lock_packages(f"numpy==2.1.0\n{line}\n", "requirements.txt")


def test_AF12_a_link_after_the_first_wildcard_is_a_problem_even_when_nothing_matches(tmp_path):
    from steward import licence as li
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/python3.12").symlink_to(tmp_path / "elsewhere")
    _, problems = li.installed(tmp_path, [".venv/lib/python*/site-packages"])
    assert problems == [".venv/lib/python3.12: reached through a link"]


def test_AG1_pre_releases_are_ordered_among_themselves():
    from steward import publish as pb
    assert pb._vkey("v1.2.0-rc.1") < pb._vkey("v1.2.0-rc.2") < pb._vkey("v1.2.0-rc.10") < pb._vkey("v1.2.0")


def test_AH2_an_unverifiable_pull_drops_an_older_record(cli, tmp_path, monkeypatch):
    import contextlib

    from steward import exchange as xc
    d = tmp_path / "p"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\npeers = { BBB = { url = "https://example.org/b.git" } }\n')
    cli("exchange", "init", "--repo", d)
    xc.record_peer_ids(d, "BBB", {"AAA-REQ-002"})
    monkeypatch.setattr(xc, "peer_revision", lambda *a, **k: contextlib.nullcontext((d, "0" * 40)))
    monkeypatch.setattr(xc, "peer_outbox", lambda *a, **k: [])
    monkeypatch.setattr(xc, "peer_history", lambda *a, **k: None)
    assert cli("exchange", "pull", "BBB", "--repo", d)[0] != 0
    assert xc.peer_ids_seen(d, "BBB") is None
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "x", "--repo", d)[0] != 0


# ---------------------------------------------------------------- STW-029 (c268cd2): AK1 – AK6 and partial verdicts
def test_AK1_a_failed_push_leaves_the_staging_refs_as_they_were(cli, xproj, tmp_path, monkeypatch):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    stage = xproj / ".steward/publish"
    refs = lambda: subprocess.run(["git", "for-each-ref"], cwd=stage, capture_output=True, text=True).stdout  # noqa: E731
    before = refs()
    from steward import publish as pb
    _failing(pb, monkeypatch, "push")
    assert cli("release", "publish", "v2.0.0", "--push")[0] != 0
    assert refs() == before
    assert "v2.0.0" not in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout


def test_AK2_semantic_versions_are_ordered_and_other_tags_refuse(cli, xproj, tmp_path):
    from steward import publish as pb
    k = pb.semver_key
    assert k("v1.0.0-alpha") < k("v1.0.0-alpha.1") < k("v1.0.0-alpha.beta") < k("v1.0.0-beta.2") < k("v1.0.0-beta.11") \
        < k("v1.0.0-rc.1") < k("v1.0.0")
    for bad in ("v1.2", "v1.2.3.1", "v01.2.3", "release"):
        with pytest.raises(ValueError):
            k(bad)
    assert sorted(["v1.2.3.1", "v1.2.3", "v1.2.4"], key=pb._vkey) == ["v1.2.3.1", "v1.2.3", "v1.2.4"]  # never raises
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    subprocess.run(["git", "tag", "v2.0.0+build.1", "main"], cwd=pub, check=True)  # a newer public release
    (xproj / "src/tool.py").write_text("print('rc')\n")
    gsh(xproj, "git", "commit", "-qam", "rc")
    gsh(xproj, "git", "tag", "-a", "v2.0.0-rc.1", "-m", "rc")
    code, _, err = cli("release", "publish", "v2.0.0-rc.1", "--push")
    assert code == 65 and "newer release" in err
    subprocess.run(["git", "tag", "-d", "v2.0.0+build.1"], cwd=pub, check=True, capture_output=True)
    subprocess.run(["git", "tag", "nightly", "main"], cwd=pub, check=True)
    code, _, err = cli("release", "publish", "v2.0.0-rc.1", "--push")
    assert code == 65 and "not a semantic version" in err


def test_AK3_an_unusable_term_list_withholds_every_licence_finding():
    from steward import publish as pb
    from steward.models import PublishSection as PublicSection
    broken = [SimpleNamespace(state="unreadable", errors=[], terms=[], name="list")]
    pub = PublicSection.model_validate({})
    out = pb._screen(broken, SimpleNamespace(exchange=None), pub, ["licence: R-80: a private-name/notices.md"])
    assert out == ["licence: findings withheld: a term list cannot be used to screen them"]


def test_AK4_an_unverifiable_pull_keeps_earlier_reservations_for_recovery(tmp_path):
    from steward import exchange as xc
    (tmp_path / ".steward").mkdir()
    xc.record_peer_ids(tmp_path, "BBB", {"AAA-REQ-009"})
    xc.forget_peer_ids(tmp_path, "BBB")
    assert xc.peer_ids_seen(tmp_path, "BBB") is None  # numbering refuses meanwhile
    xc.record_peer_ids(tmp_path, "BBB", set())  # a verified pull whose ledger omits it
    assert xc.peer_ids_seen(tmp_path, "BBB") == {"AAA-REQ-009"}


def test_AK5_a_repeated_consumer_gets_one_notice(cli, xproj):
    from test_v0120_features import _receiver
    _receiver(cli, xproj)
    t = (xproj / "steward.toml").read_text().replace('consumers = ["BBB"]', 'consumers = ["BBB", "BBB"]')
    (xproj / "steward.toml").write_text(t)
    code, _, err = cli("exchange", "announce", "v1.0.0")
    assert code == 0, err
    assert len(list((xproj / "exchange").glob("*/AAA-REL-*.md"))) == 1


def test_AK6_nothing_is_enumerated_beneath_a_linked_ancestor(tmp_path, monkeypatch):
    import pathlib

    from steward import licence as li
    (tmp_path / "elsewhere/lib/python3.12/site-packages").mkdir(parents=True)
    (tmp_path / ".venv").symlink_to(tmp_path / "elsewhere")
    seen = []
    real = pathlib.Path.glob
    monkeypatch.setattr(pathlib.Path, "glob", lambda self, pat, *a, **k: seen.append(pat) or real(self, pat, *a, **k))
    _, problems = li.installed(tmp_path, [".venv/lib/python*/site-packages"])
    assert problems == [".venv: reached through a link"] and seen == [".venv"]


def test_AF3_unlistable_staging_branches_refuse(cli, xproj, tmp_path, monkeypatch):
    _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    from steward import publish as pb
    _failing(pb, monkeypatch, "for-each-ref", "--format=%(refname)")
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and "cannot be listed" in err


# ---------------------------------------------------------------- STW-030 (87063e2): AL1 – AL4 and partial verdicts
def _two_releases(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    return pub


def test_AL1_a_published_release_keeps_its_local_commit_and_tag(cli, xproj, tmp_path, monkeypatch):
    pub = _two_releases(cli, xproj, tmp_path)
    from steward import publish as pb
    _failing(pb, monkeypatch, "update-ref", "refs/steward/pushed/v2.0.0")
    code, _, err = cli("release", "publish", "v2.0.0", "--push")
    assert code == 65 and "is public, but its local record" in err, err
    assert "v2.0.0" in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout
    stage = xproj / ".steward/publish"
    assert "v2.0.0" in subprocess.run(["git", "tag", "--list"], cwd=stage, capture_output=True, text=True).stdout


def test_AL2_a_branch_that_moves_while_it_is_checked_refuses(cli, xproj, tmp_path, monkeypatch):
    pub = _two_releases(cli, xproj, tmp_path)
    tip = subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout
    from steward import publish as pb
    real, calls = pb._git, []

    def fake(cwd, *args, **kw):
        r = real(cwd, *args, **kw)
        if args[:2] == ("ls-remote", "--heads"):
            calls.append(1)
            if len(calls) == 2:  # the second reading sees another tip: a release arrived meanwhile
                return subprocess.CompletedProcess(args, 0, "0" * 40 + "\trefs/heads/main\n", "")
        return r
    monkeypatch.setattr(pb, "_git", fake)
    code, _, err = cli("release", "publish", "v2.0.0", "--push")
    assert code == 65 and "moved while it was checked" in err, err
    assert subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout == tip


def test_AL3_malformed_semantic_versions_are_refused_and_still_listed():
    from steward import publish as pb
    for bad in ("v1.2.3-01", "v1.2.3-rc.01", "v1.٢.3"):
        with pytest.raises(ValueError):
            pb.semver_key(bad)
    assert pb.semver_key("v1.2.3-0") < pb.semver_key("v1.2.3")
    assert sorted(["v1.2.3-01", "v1.2.3"], key=pb._vkey) == ["v1.2.3-01", "v1.2.3"]


def test_AL4_a_notice_never_counts_an_inventory_with_problems(cli, xproj):
    from test_v0120_features import _receiver
    _receiver(cli, xproj)
    (xproj / "requirements.txt").write_text("numpy==2.1.0\n-rother.txt\n")
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[licence]\ndeclared = "MIT"\nlockfile = "requirements.txt"\n')
    code, _, err = cli("exchange", "announce", "v1.0.0")
    assert code == 0, err
    notice = next((xproj / "exchange").glob("*/AAA-REL-*.md")).read_text()
    assert "inventory unavailable" in notice and "Dependencies: 0" not in notice


def test_AF7_a_compact_include_is_not_an_empty_lock():
    from steward import licence as li
    for line in ("-rrequirements.in", "-cconstraints.txt", "-e."):
        with pytest.raises(ValueError):
            li.lock_packages(f"{line}\n", "requirements.txt")
    assert li.lock_packages("# nothing pinned\n", "requirements.txt") == []
