"""0.9.0 B9 (REQ-006, overlay part): a configuration overlay that can only add (RELEASE_v0.9.0_SPEC §2.9)."""

import pytest

from conftest import codes, gate, one


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_CONFIG_OVERLAY", raising=False)
    cli("init", "--repo", tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def overlay(root, text, name="steward.local.toml"):
    (root / name).write_text(text)


def test_B9_an_overlay_adds_a_gate_and_its_hash_is_reported(cli, proj):
    overlay(proj, '[gates.private]\nrequire = ["R-01", "R-38"]\n')
    code, rep = cli.check(proj, gate="private")
    assert "private" in {g["name"] for g in rep["verdict"]["gates"]}
    r01 = one(rep, "R-01")
    assert r01["status"] == "PASS" and "R-01.overlay" in codes(r01)
    assert any(d.get("path") == "steward.local.toml" and len(d.get("value", "")) == 64 for d in r01["details"])


def test_B9_records_required_from_the_overlay_makes_missing_records_incomplete(cli, proj):
    import shutil
    shutil.rmtree(proj / "development")
    _, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "PASS"
    overlay(proj, "[paths]\nrecords_required = true\n")
    _, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "INCOMPLETE"


@pytest.mark.parametrize("text", [
    '[policy]\nbaseline = "x"\n',                          # never the trust settings
    "[paths]\nrecords_required = false\n",                  # never relaxes
    '[gates.default]\nmin_evaluated = 0\nunknown = 1\n',    # unknown gate key
    '[[terms]]\nname = "x"\nfile = "y"\n',                  # never the term lists
    '[steward]\nprofile = "exploratory"\n',                  # never replaces
])
def test_B9_anything_but_an_addition_fails_r01(cli, proj, text):
    overlay(proj, text)
    _, rep = cli.check(proj)
    res = one(rep, "R-01")
    assert res["status"] == "FAIL" and "R-01.overlay_refused" in codes(res), res


def test_B9_an_overlay_default_gate_cannot_shrink_the_default(cli, proj):
    from steward.models import ADVISORY, RULE_IDS
    overlay(proj, '[gates.default]\nrequire = ["R-01"]\nmin_evaluated = 1\n')
    _, rep = cli.check(proj)
    g = gate(rep)
    assert g["required_count"] == len([r for r in RULE_IDS if r not in ADVISORY]), g


def test_B9_an_overlay_only_adds_rules_to_an_existing_gate(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[gates.push]\nrequire = ["R-01", "R-07"]\nmin_evaluated = 3\n')
    overlay(proj, '[gates.push]\nrequire = ["R-38"]\nmin_evaluated = 1\n')
    from steward.models import load_config
    cfg = load_config(proj)
    g = cfg.gates["push"]  # review Q1: added rules are kept apart, so they never count toward the base minimum
    assert set(g.require) == {"R-01", "R-07"} and g.added == ["R-38"] and g.min_evaluated == 3


def test_B9_the_overlay_can_be_named_by_the_environment_and_the_commands_see_it(cli, proj, monkeypatch):
    overlay(proj, '[gates.private]\nrequire = ["R-01"]\n', name="private.toml")
    monkeypatch.setenv("STEWARD_CONFIG_OVERLAY", "private.toml")
    code, rep = cli.check(proj, gate="private")
    assert gate(rep, "private")["eligible"]
    monkeypatch.setenv("STEWARD_CONFIG_OVERLAY", "missing.toml")
    _, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "FAIL"
