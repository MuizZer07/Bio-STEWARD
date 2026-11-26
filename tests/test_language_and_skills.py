"""T-LANG-01, T-SKILL-01, committed schemas, and the generic-toolkit rule (spec §8.4; DESIGN_v0.2 §6)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import lint_language  # noqa: E402
import regenerate_schemas  # noqa: E402

SKILLS = sorted(p for p in (REPO / "skills").iterdir() if p.is_dir())
CORE_SKILLS = sorted([
    "benchmark-contract", "change-impact", "negative-results", "no-paid-tests", "prior-work-grounding",
    "run-estimate", "signature-and-attribution", "task-lifecycle", "using-steward", "red-team-review",
    "container-release", "dependency-upgrade",  # 0.9.0 (REQ-006, 012), with the core budget raised to 325
])
EXPECTED_SKILLS = [
    "benchmark-contract", "change-impact", "container-release", "dependency-upgrade", "negative-results", "no-paid-tests", "figures-and-tables", "licence-compliance", "manuscript-drafting", "manuscript-review", "number-crosscheck", "paper-kit",
    "presentation-building", "presentation-planning", "presentation-review", "prior-work-grounding", "progress-audit", "red-team-review", "research-review", "run-estimate", "signature-and-attribution", "submission-readiness", "task-lifecycle",
    "using-steward",
]


def test_T_LANG_01_lint_passes_on_toolkit_text():
    assert lint_language.main(REPO) == 0


def test_T_LANG_01_lint_catches_seeded_phrases():
    assert lint_language.lint_text("This proves the method works.")
    assert lint_language.lint_text("The benchmark is fair.")
    assert lint_language.lint_text("Results are reproducible.")
    assert not lint_language.lint_text("This proves nothing. (lint: allow)")
    assert not lint_language.lint_text("Artifact integrity verified; repeatable within tolerance 1e-6.")
    # A7: advice to skip verification for cost is flagged; a prohibition is not.
    assert lint_language.lint_text("Skip the check for small edits.")
    assert lint_language.lint_text("There is no need to run steward here.")
    assert lint_language.lint_text("Use the partial check to save tokens.")
    assert not lint_language.lint_text("Never skip the check before reporting.")
    assert not lint_language.lint_text("Do not skip the gate.")


def test_T_SKILL_01_skills_ref_validates_every_skill():
    if importlib.util.find_spec("skills_ref") is None:
        pytest.skip("skills-ref not installed (pip install -e '.[dev]')")
    from skills_ref import validate

    assert [p.name for p in SKILLS] == sorted(EXPECTED_SKILLS)
    for skill in SKILLS:
        assert validate(skill) == [], skill.name


def test_skills_are_short_and_name_their_rules():
    for skill in SKILLS:
        text = (skill / "SKILL.md").read_text()
        assert len(text.splitlines()) <= 200, skill.name
        assert "Start by saying in one line that you are using this skill and why." in text, skill.name  # DESIGN_v0.5 §3.3
    for name in ("using-steward", "benchmark-contract", "prior-work-grounding"):
        assert "R-0" in (REPO / "skills" / name / "SKILL.md").read_text(), name


def test_committed_schemas_are_current():
    assert regenerate_schemas.main(["--check"]) == 0


def test_A5_C2_nothing_the_example_or_tests_need_is_git_ignored():
    """Red-team A5 / C2: a clean checkout must contain every file the example check and the tests read."""
    import shutil
    import subprocess

    if not shutil.which("git") or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "examples", "tests/fixtures"],
                         cwd=REPO, capture_output=True, text=True).stdout.split()
    build_byproducts = (".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".out", ".nav", ".snm", ".toc", ".pyc")
    needed = [f for f in out if not f.endswith(build_byproducts) and "/.steward/" not in f and "__pycache__" not in f
              and not f.endswith(".DS_Store")]
    assert needed == [], f"git-ignored files the example or tests need: {needed}"


@pytest.mark.skipif(not (REPO / "development/DECISIONS.md").is_file(), reason="the development records are private (a public clone)")
def test_v090_the_core_budget_is_325_by_a_recorded_decision():
    import tomllib
    b = tomllib.loads((REPO / "skills/BUNDLES.toml").read_text())["core"]
    assert b["budget_words"] == 325 and b["decision"] in (REPO / "development/DECISIONS.md").read_text()
    assert {"container-release", "dependency-upgrade"} <= set(b["skills"])
