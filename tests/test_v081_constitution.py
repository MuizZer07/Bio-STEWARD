"""0.8.1: the constitution (C-1), R-51, and the process templates it governs (FB-6, FB-7, AR-07, AR-10, AR-12)."""

import pytest

from steward.resources import CONSTITUTION_VERSION

from conftest import REPO, codes, one


def test_C1_the_constitution_is_shipped_and_printed(cli):
    code, out, _ = cli("constitution")
    assert code == 0 and "Article II. Authority" in out and f"Version {CONSTITUTION_VERSION}" in out
    code, out, _ = cli("constitution", "--version")
    assert code == 0 and out.strip() == CONSTITUTION_VERSION


def test_C1_init_declares_it_and_r51_passes(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    assert f'constitution = "{CONSTITUTION_VERSION}"' in (tmp_path / "steward.toml").read_text()
    assert "CONSTITUTION" in (tmp_path / "AGENTS.md").read_text() or "constitution" in (tmp_path / "AGENTS.md").read_text()
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-51")["status"] == "PASS"


def _without_declaration(tmp_path, cli):
    cli("init", "--repo", tmp_path)
    p = tmp_path / "steward.toml"
    import re
    p.write_text(re.sub(rf'^constitution = "{CONSTITUTION_VERSION}".*\n', "", p.read_text(), flags=re.M))


def test_C1_not_declared_is_not_applicable_with_a_recommendation(cli, tmp_path):
    _without_declaration(tmp_path, cli)
    _, rep = cli.check(tmp_path)
    res = one(rep, "R-51")
    assert res["status"] == "NOT_APPLICABLE" and "R-51.recommended" in codes(res)


def test_C1_required_and_not_declared_is_incomplete(cli, tmp_path):
    _without_declaration(tmp_path, cli)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write("\n[governance]\nrequired = true\n")
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-51")["status"] == "INCOMPLETE"


def test_C1_another_version_is_incomplete(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    p = tmp_path / "steward.toml"
    p.write_text(p.read_text().replace(f'constitution = "{CONSTITUTION_VERSION}"', 'constitution = "0"'))
    _, rep = cli.check(tmp_path)
    res = one(rep, "R-51")
    assert res["status"] == "INCOMPLETE" and "R-51.version_differs" in codes(res)


def test_C1_required_without_a_decisions_log_is_incomplete(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    (tmp_path / "development/DECISIONS.md").unlink()
    with open(tmp_path / "steward.toml", "a") as f:
        f.write("\n[governance]\nrequired = true\n")
    _, rep = cli.check(tmp_path)
    res = one(rep, "R-51")
    assert res["status"] == "INCOMPLETE" and "R-51.no_decisions_log" in codes(res)


def test_C1_this_repository_declares_the_constitution():
    text = (REPO / "AGENTS.md").read_text()
    assert "CONSTITUTION.md" in text


@pytest.mark.parametrize("name,needles", [
    ("task.md", ["ID", "Branch", "Dependencies", "Owner", "Approver", "Work log", "Follow-ups"]),
    ("HANDOFF.md", ["State", "Next", "Open decisions", "Working agreements"]),
    ("parity.md", ["Local item", "Replaced by", "Parity", "Removed"]),
])
def test_templates_carry_the_standard_fields(name, needles):
    text = (REPO / "templates" / name).read_text()
    missing = [n for n in needles if n not in text]
    assert not missing, (name, missing)


def test_task_lifecycle_states_the_close_out_rule_handoff_and_patch_mode():
    text = (REPO / "skills/task-lifecycle/SKILL.md").read_text()
    companions = "".join(p.read_text() for p in (REPO / "skills/task-lifecycle").glob("*.md") if p.name != "SKILL.md")
    allt = text + companions
    for needle in ("every acceptance criterion ran and passed", "HANDOFF", "git apply --check", "never merged"):
        assert needle in allt, needle


def test_using_steward_guides_adoption_into_an_existing_repository():
    allt = "".join(p.read_text() for p in (REPO / "skills/using-steward").glob("*.md"))
    assert "existing repository" in allt and "parity" in allt
