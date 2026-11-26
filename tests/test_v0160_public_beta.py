"""0.16.0: public-beta preparation (DESIGN_BRIEF_public_release §5 – §6). Nothing is published by these files."""

import json
import re

import pytest
import yaml

from conftest import REPO

# Y13 (0.16.0): these tests read the repository's public files; a source archive without them skips them
pytestmark = pytest.mark.skipif(not (REPO / "action.yml").is_file(), reason="checkout-only: the public files are absent")


def test_community_files_exist_and_name_their_promises():
    contributing = (REPO / "CONTRIBUTING.md").read_text()
    assert "7 days" in contributing and "false PASS" in contributing and "failing test" in contributing.lower()
    security = (REPO / "SECURITY.md").read_text()
    assert "private vulnerability reporting" in security and "3 days" in security
    assert "Contributor Covenant" in (REPO / "CODE_OF_CONDUCT.md").read_text()
    for f in ("bug.yml", "feature.yml", "config.yml"):
        doc = yaml.safe_load((REPO / ".github/ISSUE_TEMPLATE" / f).read_text())
        assert f == "config.yml" or len(doc["name"]) > 3  # Y12: GitHub needs more than three characters
    assert (REPO / ".github/pull_request_template.md").is_file()


def test_the_action_installs_its_own_version_and_fails_unless_eligible():
    act = yaml.safe_load((REPO / "action.yml").read_text())
    assert act["runs"]["using"] == "composite"
    steps = " ".join(s.get("run", "") for s in act["runs"]["steps"])
    assert "${{" not in steps  # Y1: no expression in shell source; values arrive through the environment
    assert 'cd "$RUNNER_TEMP"' in steps and "python -I -m venv" in steps  # Y1: installed away from the checkout
    assert 'mktemp -d "$RUNNER_TEMP' in steps and "report" not in act["inputs"]  # Y2: a fresh runner folder
    assert "true|false" in steps  # Y3: final validated
    assert '--gate "$GATE"' in steps and 'exit "$code"' in steps
    assert set(act["inputs"]) >= {"gate", "final", "python-version"} and {"eligible", "report"} <= set(act["outputs"])


def test_the_pre_commit_hook_runs_the_toolkit_hook():
    hooks = yaml.safe_load((REPO / ".pre-commit-hooks.yaml").read_text())
    h = next(x for x in hooks if x["id"] == "steward-check")
    assert h["entry"].startswith("steward hooks run pre-commit") and h["pass_filenames"] is False


def test_the_plugin_payload_is_curated_current_and_versioned():
    import subprocess
    import sys
    from steward import __version__
    plugin = json.loads((REPO / "plugin/.claude-plugin/plugin.json").read_text())
    assert plugin["version"] == __version__.split(".dev")[0] and plugin["name"] == "bio-steward"
    market = json.loads((REPO / ".claude-plugin/marketplace.json").read_text())
    assert market["plugins"][0]["source"] == "./plugin"  # Y7: never the repository root
    tops = {p.name for p in (REPO / "plugin").iterdir()}
    assert tops == {".claude-plugin", "skills", "LICENSE"}, tops
    r = subprocess.run([sys.executable, str(REPO / "tools/build_plugin.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_joss_draft_has_its_sections_and_cites_only_its_bibliography():
    text = (REPO / "paper/paper.md").read_text()
    for h in ("# Summary", "# Statement of need", "# References"):
        assert h in text
    keys = set(re.findall(r"@([a-z0-9]+)\]", text))
    bib = set(re.findall(r"@article\{([a-z0-9]+),", (REPO / "paper/paper.bib").read_text()))
    assert keys and keys <= bib
    assert "DRAFT, not ready for submission" in text  # Y14: JOSS asks 750 - 1,750 words and more sections


def test_the_principles_page_is_in_the_guide_and_the_readme_links_the_integrations():
    assert "principles.md" in (REPO / "mkdocs.yml").read_text()
    readme = (REPO / "README.md").read_text()
    for link in ("action.yml", ".pre-commit-hooks.yaml", "plugin/", "docs/principles.md", "CONTRIBUTING.md"):
        assert link in readme


def test_Y8_the_scrub_inventory_covers_every_public_surface():
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import scrub_check
    for f in ("action.yml", ".pre-commit-hooks.yaml", ".claude-plugin", ".github", "paper", "plugin", "CITATION.cff",
              "pyproject.toml", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"):
        assert f in scrub_check.PUBLISHED, f


def test_Y1_the_action_runs_a_real_check_from_a_runner_folder(tmp_path):
    """The two run steps, executed locally with a stand-in runner: install away from the checkout, gate, outputs."""
    import os
    import shutil
    import subprocess
    if not shutil.which("bash"):
        pytest.skip("needs bash")
    act = yaml.safe_load((REPO / "action.yml").read_text())
    check = act["runs"]["steps"][2]["run"]
    ws, runner = tmp_path / "ws", tmp_path / "runner"
    ws.mkdir()
    runner.mkdir()
    venv_bin = runner / "steward-venv" / "bin"
    venv_bin.mkdir(parents=True)
    import sys as _s
    (venv_bin / "steward").write_text(f"#!/bin/sh\nexec {_s.executable} -m steward.cli \"$@\"\n")
    (venv_bin / "steward").chmod(0o755)
    subprocess.run([_s.executable, "-m", "steward.cli", "init", "--repo", str(ws)], check=True, capture_output=True)
    out = tmp_path / "out.txt"
    env = {**os.environ, "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out), "GATE": "default", "FINAL": "false"}
    r = subprocess.run(["bash", "-c", check], cwd=ws, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    o = dict(l.split("=", 1) for l in out.read_text().splitlines())
    assert o["eligible"] == "true" and o["report"].startswith(str(runner)) and os.path.isfile(o["report"])
    env["FINAL"] = "yes"
    assert subprocess.run(["bash", "-c", check], cwd=ws, env=env, capture_output=True).returncode == 2
