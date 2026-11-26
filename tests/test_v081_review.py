"""0.8.1 pre-release review (a615ec5): medium and low findings N5 - N13 not covered elsewhere."""

import json
import math
import zipfile

import pytest

from conftest import append, codes, one


# ---------------------------------------------------------------- N7: the release audit discloses what it could not scan
@pytest.fixture
def rel(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", '\n[release]\nrequired = []\n\n[[terms]]\nname = "policy"\nfile = "policy.txt"\npublic = true\n')
    (tmp_path / "policy.txt").write_text("AcmeHost\n")
    (tmp_path / "dist").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def wheel(root, members):
    with zipfile.ZipFile(root / "dist/p-1.0-py3-none-any.whl", "w") as z:
        for k, v in members.items():
            z.writestr(k, v)


def test_N7_an_unreadable_public_list_refuses_the_audit(cli, rel):
    (rel / "policy.txt").unlink()
    wheel(rel, {"p/a.py": "x = 1\n"})
    code, out, _ = cli("release", "audit")
    assert code == 1 and "terms_unavailable" in out


def test_N7_the_packaged_list_is_exempt_from_its_own_terms(cli, rel):
    wheel(rel, {"policy.txt": "AcmeHost\n", "p/a.py": "x = 1\n"})
    assert cli("release", "audit")[0] == 0


@pytest.mark.parametrize("text,hit", [("/" "Users/Jane Doe/project", True), ("/" "home/runner/work", True)])  # steward: allow R-07 (examples)
def test_N7_more_home_paths_are_found(text, hit):
    from steward import privacy as pv
    found, _ = pv.scan_text(text, [], True)
    assert bool(found) is hit


# ---------------------------------------------------------------- N8: a manifest for another folder never passes
def test_N8_a_manifest_for_another_folder_is_incomplete(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", "\n[release]\nrequired = []\n")
    for d in ("dist", "built"):
        (tmp_path / d).mkdir()
        with zipfile.ZipFile(tmp_path / d / "p-1.0-py3-none-any.whl", "w") as z:
            z.writestr("p/a.py", f"# {d}\n")
    monkeypatch.chdir(tmp_path)
    assert cli("release", "manifest", "--dist", "built")[0] == 0
    _, out, _ = cli("check", "--repo", tmp_path, "--format", "json", "--final", "release")
    res = one(json.loads(out), "R-42")
    assert res["status"] in ("INCOMPLETE", "FAIL") and "R-42.manifest_other_dist" in codes(res)


# ---------------------------------------------------------------- N9: a template log with no entries
def test_N9_a_prose_only_template_log_fails(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", '\n[integrity]\ndecisions_format = "template"\n')
    (tmp_path / "development/DECISIONS.md").write_text("# Decisions\n\nWe decided to adopt it.\n")
    _, rep = cli.check(tmp_path)
    res = one(rep, "R-38")
    assert res["status"] == "FAIL" and "R-38.entry_malformed" in codes(res)


# ---------------------------------------------------------------- N10: weaker evidence than described
def test_N10_bindings_count_loop_and_with_targets(tmp_path):
    from steward import review as rv
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("class Base:\n    pass\n\n\nfor Base in [dict]:\n    pass\n\n\n"
                                              "class TestX(Base):\n    def test_x(self):\n        pass\n")
    assert rv.test_exists(tmp_path, "tests/test_x.py::TestX::test_x") is False


def test_N10_a_test_path_must_stay_inside_the_tree(tmp_path):
    from steward import review as rv
    outside = tmp_path / "out"
    outside.mkdir()
    (outside / "test_o.py").write_text("def test_o():\n    pass\n")
    inside = tmp_path / "repo"
    inside.mkdir()
    (inside / "tests").mkdir()
    (inside / "tests/linked.py").symlink_to(outside / "test_o.py")
    assert rv.test_exists(inside, "../out/test_o.py::test_o") is False
    assert rv.test_exists(inside, "tests/linked.py::test_o") is False


def test_N10_known_issues_and_decisions_need_their_sections(tmp_path):
    from steward import review as rv
    assert rv.known_issue_listed("# Changelog\n## 0.8.1\n- fixed F1 elsewhere\n", "F1") is False
    assert rv.known_issue_listed("# Changelog\n## Known issues in 0.8.1\n- F1: a limitation\n## 0.8.0\n", "F1") is True
    assert rv.decision_heading("# Decisions\n\nWe will accept F3 on its test.\n", "accept F3 on its test") is False
    assert rv.decision_heading("## 2026-11-23: accept F3 on its test\n", "accept F3 on its test") is True


# ---------------------------------------------------------------- N11: slot waits and records
@pytest.mark.parametrize("bad", ["nan", "inf", "-1"])
def test_N11_the_wait_timeout_must_be_finite_and_non_negative(cli, tmp_path, monkeypatch, bad):
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", "\n[run]\n[run.slots]\nheavy = 1\n")
    monkeypatch.chdir(tmp_path)
    code, _, err = cli("run", "--slot", "heavy", "--wait-timeout", bad, "--", "true")
    assert code == 64 and "wait-timeout" in err


def test_N11_a_short_timeout_returns_promptly(tmp_path):
    import time
    from steward import runner
    a = runner.Slot(tmp_path, "heavy", 1, str(tmp_path / "s"))
    b = runner.Slot(tmp_path, "heavy", 1, str(tmp_path / "s"))
    assert a.acquire(False)
    t0 = time.monotonic()
    assert not b.acquire(False, 0.02) and time.monotonic() - t0 < 0.15
    a.release()


def test_N11_the_slot_directory_is_recorded_without_the_home_path(tmp_path, monkeypatch):
    from pathlib import Path
    from steward import runner
    monkeypatch.delenv("STEWARD_SLOTS_DIR", raising=False)
    s = runner.Slot(tmp_path, "heavy", 1, str(Path.home() / ".steward-test-slots"))
    assert s.spec.startswith("~/") and str(Path.home()) not in s.spec


# ---------------------------------------------------------------- N13: records types
def test_N13_records_root_must_be_a_directory_and_the_log_a_file(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    text = (tmp_path / "steward.toml").read_text().replace("[paths]", '[paths]\nrecords = "process"\nrecords_required = true', 1)
    (tmp_path / "steward.toml").write_text(text)
    (tmp_path / "process").write_text("a file, not a folder\n")
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-01")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- N12: anchors MCP cannot verify are not a PASS
def test_N12_unverifiable_anchors_are_unknown_under_the_mcp_server(cli, tmp_path, monkeypatch):
    import sys
    from steward import authorize as az
    cli("init", "--repo", tmp_path)
    append(tmp_path, "steward.toml", "\n[run]\n")
    monkeypatch.chdir(tmp_path)
    cli("run", "--", sys.executable, "-c", "pass")
    monkeypatch.setattr(az, "list_tags", lambda root, prefix="steward/auth/": ["steward/anchor/runs/1"] if "anchor" in prefix else [])
    monkeypatch.setattr(az, "READ_ONLY", True)
    _, rep = cli.check(tmp_path, "run")
    res = [r for r in rep["verdict"]["results"] if r["rule"] == "R-31"][0]
    assert res["status"] == "UNKNOWN" and "R-31.anchor_unavailable" in codes(res)
