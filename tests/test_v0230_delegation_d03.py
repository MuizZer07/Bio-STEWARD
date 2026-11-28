"""0.23.0 D03 (delegation): the AGENTS block names the project's master from [delegation], the using-steward and
task-lifecycle skills cover delegation within each kit's word budget, and docs/guides/delegation.md has the SVG flow
figure linked from mkdocs.yml and docs/index.md.
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from conftest import REPO
from test_v0230_delegation import fake_agent

sys.path.insert(0, str(REPO / "tools"))
import build_plugin  # noqa: E402
import measure_footprint  # noqa: E402


def _setup_env(monkeypatch, tmp_path, agents: str = "claude codex agy"):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config"))
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}/usr/bin{os.pathsep}/bin")
    if "claude" in agents.split():
        fake_agent(bin_, "claude", "2.1.50 (Claude Code)", ("auth", "status"))
    if "codex" in agents.split():
        fake_agent(bin_, "codex", "codex-cli 0.125.0", ("login", "status"), signed_in=True)
    if "agy" in agents.split():
        fake_agent(home / ".gemini" / "bin", "agy", "1.5.18")


# ---------------------------------------------------------------- AGENTS block from [delegation]
def test_D03_init_agents_block_names_master_and_workers(cli, tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    assert cli("init", "--repo", r)[0] == 0
    ag = r / "AGENTS.md"
    assert "Delegation:" not in ag.read_text(encoding="utf-8")

    with open(r / "steward.toml", "a", encoding="utf-8") as fh:
        fh.write('\n[delegation]\nmaster = "claude-code"\nworkers = ["codex", "antigravity"]\non_limit = "next"\n')

    code, out, err = cli("init", "--repo", r)
    assert code == 0, err
    text = ag.read_text(encoding="utf-8")
    assert "Delegation: master is `claude-code`" in text
    assert "workers: `codex`, `antigravity`" in text
    assert text.count("<!-- >>> steward -->") == 1

    # Idempotent on a second run
    code, out, _ = cli("init", "--repo", r)
    assert code == 0 and ag.read_text(encoding="utf-8") == text
    assert "unchanged" in out and "AGENTS.md" in out


def test_D03_init_agents_block_with_master_only_and_preserves_skills_note(cli, tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    assert cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")[0] == 0
    with open(r / "steward.toml", "a", encoding="utf-8") as fh:
        fh.write('\n[delegation]\nmaster = "codex"\nworkers = []\non_limit = "master"\n')

    assert cli("init", "--repo", r)[0] == 0
    text = (r / "AGENTS.md").read_text(encoding="utf-8")
    assert "Delegation: master is `codex`" in text and "workers:" not in text
    assert ".agents/skills" in text and ".claude/skills" in text


def test_D03_init_leaves_unmarked_agents_md_untouched_and_prints_master(cli, tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    assert cli("init", "--repo", r)[0] == 0
    (r / "AGENTS.md").write_text("# Custom instructions\n", encoding="utf-8")
    with open(r / "steward.toml", "a", encoding="utf-8") as fh:
        fh.write('\n[delegation]\nmaster = "claude-code"\nworkers = ["codex"]\n')

    code, out, _ = cli("init", "--repo", r)
    assert code == 0
    assert (r / "AGENTS.md").read_text(encoding="utf-8") == "# Custom instructions\n"
    assert "Delegation: master is `claude-code`" in out

    assert cli("init", "--repo", r, "--agents-md")[0] == 0
    text = (r / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Custom instructions\n") and "Delegation: master is `claude-code`" in text


def test_D03_agents_setup_syncs_agents_block_and_respects_confirmation(cli, tmp_path, monkeypatch):
    _setup_env(monkeypatch, tmp_path)
    r = tmp_path / "repo"
    r.mkdir()
    assert cli("init", "--repo", r)[0] == 0
    monkeypatch.chdir(r)
    before = (r / "AGENTS.md").read_text(encoding="utf-8")

    # Without --yes and not a terminal: nothing written to steward.toml or AGENTS.md
    code, out, _ = cli("agents", "setup")
    assert code == 0 and "not written" in out
    assert (r / "AGENTS.md").read_text(encoding="utf-8") == before

    # With --yes: writes [delegation] and updates the steward block in AGENTS.md
    code, out, err = cli("agents", "setup", "--yes")
    assert code == 0, err
    assert "updated AGENTS.md (steward block)" in out
    text = (r / "AGENTS.md").read_text(encoding="utf-8")
    assert "Delegation: master is `claude-code`" in text
    assert "workers: `codex`, `antigravity`" in text

    # Changing master updates AGENTS.md again
    code, out, err = cli("agents", "setup", "--yes", "--master", "codex")
    assert code == 0, err
    text = (r / "AGENTS.md").read_text(encoding="utf-8")
    assert "Delegation: master is `codex`" in text


def test_D03_sync_agents_block_skips_unmarked_and_symlink(cli, tmp_path, monkeypatch):
    from steward.init import sync_agents_block

    _setup_env(monkeypatch, tmp_path)
    r = tmp_path / "repo"
    r.mkdir()
    assert cli("init", "--repo", r)[0] == 0
    (r / "AGENTS.md").write_text("# Hand-written\n", encoding="utf-8")
    monkeypatch.chdir(r)
    assert cli("agents", "setup", "--yes")[0] == 0
    assert (r / "AGENTS.md").read_text(encoding="utf-8") == "# Hand-written\n"

    outside = tmp_path / "outside.md"
    outside.write_text("<!-- >>> steward -->\nold\n<!-- <<< steward -->\n", encoding="utf-8")
    (r / "AGENTS.md").unlink()
    (r / "AGENTS.md").symlink_to(outside)
    assert sync_agents_block(r) is False
    assert outside.read_text(encoding="utf-8") == "<!-- >>> steward -->\nold\n<!-- <<< steward -->\n"


# ---------------------------------------------------------------- skills and budgets
def test_D03_skills_cover_delegation_and_hold_budgets():
    us = (REPO / "skills/using-steward/SKILL.md").read_text(encoding="utf-8")
    tl = (REPO / "skills/task-lifecycle/SKILL.md").read_text(encoding="utf-8")
    dl = (REPO / "skills/task-lifecycle/delegation.md").read_text(encoding="utf-8")

    for text in (us, tl):
        assert "self-contained" in text
        assert "acceptance commands" in text
        assert "steward task dispatch TASK --to auto" in text
        assert 'agent = "auto"' in text
        assert "steward sprint accept" in text
        assert "merging" in text
        assert "signature" in text
    assert "steward agents setup" in dl and "git apply --check" in dl

    assert measure_footprint.violations(measure_footprint.measure()) == []
    assert build_plugin.main(check=True) == 0


# ---------------------------------------------------------------- guide, SVG and navigation
def test_D03_delegation_guide_svg_and_links():
    guide = REPO / "docs/guides/delegation.md"
    svg = REPO / "docs/assets/delegation-flow.svg"
    assert guide.is_file() and svg.is_file()

    gtext = guide.read_text(encoding="utf-8")
    assert gtext.startswith("# Delegate to other agents\n")
    assert "../assets/delegation-flow.svg" in gtext
    for needle in ("steward agents setup", "steward agents status", "--to auto", 'agent = "auto"',
                   "steward sprint accept", "steward sprint rework", "on_limit"):
        assert needle in gtext, needle

    stext = svg.read_text(encoding="utf-8")
    root = ET.fromstring(stext)
    assert root.tag.endswith("svg") and root.attrib.get("role") == "img" and root.attrib.get("aria-label")
    assert "prefers-color-scheme: dark" in stext
    for label in ("worker", "limited", "next worker", "master", "review", "accept", "done"):
        assert label in stext, label

    assert "Delegate to other agents: guides/delegation.md" in (REPO / "mkdocs.yml").read_text(encoding="utf-8")
    assert "guides/delegation.md" in (REPO / "docs/index.md").read_text(encoding="utf-8")
