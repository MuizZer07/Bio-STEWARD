"""0.19.0: onboarding from the stranger test (STW-006) and token cost (STW-009)."""

import subprocess
import tomllib

import pytest

from conftest import results
from test_v0120_features import gsh, xproj  # noqa: F401


def _fresh(tmp_path, name="p"):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


def test_an_unconfigured_project_is_told_where_to_start(cli, tmp_path):
    d = _fresh(tmp_path)
    code, out, _ = cli("init", "--repo", d)
    assert code == 0 and "Next:" in out and "steward init --for" in out and "development/templates/ copies" not in out
    _, out, _ = cli("check", "--repo", d, "--summary")
    assert "Start here: nothing project-specific is checked yet" in out
    first = out.splitlines()
    assert first[0].startswith("Summary:") and first[1].startswith("Gate default:")


@pytest.mark.parametrize("goal,tables,skill", [
    ("reanalysis", {"studies", "research"}, "research-review"),
    ("agents", {"run", "agents"}, None),
    ("benchmark", set(), None),
    ("paper", {"paper"}, "paper-kit"),
])
def test_init_for_a_goal_writes_what_it_needs_and_says_what_next(cli, tmp_path, goal, tables, skill):
    d = _fresh(tmp_path)
    code, out, err = cli("init", "--repo", d, "--for", goal, "--skills", d / ".agents/skills")
    assert code == 0, err
    cfg = tomllib.loads((d / "steward.toml").read_text())
    assert tables <= set(cfg)
    if skill:
        assert (d / f".agents/skills/{skill}/SKILL.md").is_file()
    assert "Next:" in out and "  1. " in out
    if goal == "benchmark":
        assert (d / "development/templates/benchmark.contract.toml").is_file()
    code, _, err = cli("init", "--repo", d, "--for", goal)  # again: never a duplicate table
    assert code == 0 and tomllib.loads((d / "steward.toml").read_text())


def test_init_for_licence_declares_the_licence_file(cli, tmp_path):
    d = _fresh(tmp_path)
    (d / "LICENSE").write_text("Permission is hereby granted, free of charge, to any person\n")
    cli("init", "--repo", d, "--for", "licence")
    assert tomllib.loads((d / "steward.toml").read_text())["licence"]["declared"] == "MIT"


def test_a_broken_configuration_is_said_once_and_first(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write("\n[studies]\n\n[studies]\n")
    _, out, _ = cli("check", "--repo", d, "--summary")
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Start here: steward.toml is not valid"))
    assert start < next(i for i, ln in enumerate(lines) if ln.startswith(("FAIL", "UNKNOWN")))


def test_study_add_input_records_and_fingerprints(cli, xproj):
    with open(xproj / "steward.toml", "a") as f:
        f.write("\n[studies]\n")
    (xproj / "data").mkdir()
    (xproj / "data/m.txt").write_text("ID_REF\tGSM1\n")
    assert cli("study", "new", "s1", "--title", "S")[0] == 0
    code, out, err = cli("study", "add-input", "s1", "--source", "GEO", "--accession", "GSE5281", "--file", "data/m.txt")
    assert code == 0 and "1 fingerprinted file" in out, err
    st = tomllib.loads((xproj / "development/studies/s1.toml").read_text())
    assert st["inputs"][0]["accession"] == "GSE5281" and len(st["inputs"][0]["files"][0]["sha256"]) == 64
    _, rep = cli.check(xproj, "studies")
    assert results(rep, "R-75")[0]["status"] == "PASS"
    assert cli("study", "add-input", "s1", "--source", "GEO", "--accession", "GSE5281")[0] == 64  # once
    assert cli("study", "add-input", "s1", "--source", "x", "--file", "../outside.txt")[0] == 64


def test_quiet_is_one_line_when_nothing_needs_attention(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, _ = cli("check", "--repo", d, "--quiet")
    assert code == 0 and out.count("\n") == 1 and out.startswith("OK:")
    with open(d / "steward.toml", "a") as f:
        f.write("\n[studies]\n")
    code, out, _ = cli("check", "--repo", d, "--quiet")
    assert out.startswith("Summary:")  # something needs attention: the full summary


def test_help_groups_the_commands(cli):
    code, out, _ = cli("--help")
    assert "Commands by what you do" in out and "Start            init" in out


def test_a_task_may_name_how_its_brief_is_run(cli, tmp_path):
    t = tmp_path / "T.md"
    t.write_text("# Task: x\n\n- **ID:** T-1\n- **Run:** in an empty folder\n\n## Goal\ny\n")
    code, out, _ = cli("task", "brief", t, "--for", "codex")
    assert code == 0 and out.rstrip().endswith("How to run: in an empty folder")


def test_token_budget_the_first_check_of_a_new_project_is_short(cli, tmp_path):
    """STW-009: the first summary an agent reads stays small (words, a proxy for tokens)."""
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    _, out, _ = cli("check", "--repo", d, "--summary")
    assert len(out.split()) <= 320, len(out.split())
    _, out, _ = cli("check", "--repo", d, "--quiet")
    assert len(out.split()) <= 20


def test_the_changelog_has_one_section_per_version_each_with_upgrade_notes():
    """AF8: `exchange announce` reads one section per version, which must carry its upgrade notes."""
    import re
    from pathlib import Path

    from steward import exchange as xc
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text()
    versions = re.findall(r"^## (\d+\.\d+\.\d+)\b", text, re.M)
    assert len(versions) == len(set(versions)), versions
    for v in versions[:3]:
        assert re.search(r"^#{2,4}\s+Upgrade notes", xc.changelog_section(text, v), re.M | re.I), v
