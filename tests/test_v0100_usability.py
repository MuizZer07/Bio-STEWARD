"""0.10.0 U1 - U3: steward explain, a quiet start, the user guide (RELEASE_v0.10.0_SPEC)."""

import re

import pytest

from conftest import REPO


def test_U1_every_rule_is_documented():
    from steward.rule_docs import RULE_DOCS
    from steward.rules import RULES
    assert set(RULE_DOCS) == set(RULES)
    for r, d in RULE_DOCS.items():
        assert {"checks", "why", "not", "scope"} <= set(d) and d["scope"] in ("project", "multi-project"), r


def test_U1_explain_prints_purpose_codes_fix_and_limits(cli):
    code, out, _ = cli("explain", "R-42")
    assert code == 0
    for part in ("R-42 release.integrity", "Checks:", "Why:", "A PASS does not mean:", "Fix:", "R-42.no_manifest"):
        assert part in out, part
    assert cli("explain", "R-999")[0] == 64


def test_U2_the_summary_folds_not_applicable_results_but_names_each(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, out, _ = cli("check", "--repo", tmp_path, "--summary")
    na = [l for l in out.splitlines() if l.startswith("NOT_APPLICABLE")]
    assert len(na) == 1 and "R-42" in na[0], out
    _, full, _ = cli("check", "--repo", tmp_path, "--summary", "--all")
    assert len([l for l in full.splitlines() if l.startswith("NOT_APPLICABLE")]) > 10


# ---------------------------------------------------------------- H6: the scrub check
def test_H6_published_files_are_scrubbed():
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import scrub_check
    assert scrub_check.findings() == []


def test_H6_a_seeded_name_email_and_home_path_are_found(tmp_path):
    import subprocess
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import scrub_check
    (tmp_path / "development").mkdir()
    (tmp_path / "development/ADOPTION.md").write_text("- **Acme-Lab (AL):** an adopter\n")
    (tmp_path / "README.md").write_text("Made for acme lab.\nWrite to ann@acmelab.edu\nsee /" "Users/ann/x\n")  # scrub: allow; steward: allow R-07 (example)
    for c in (["git", "init", "-q"], ["git", "add", "-f", "README.md"]):
        subprocess.run(c, cwd=tmp_path, check=True, capture_output=True)
    found = scrub_check.findings(tmp_path)
    assert {f.split(": ", 1)[1] for f in found} == {"adopter name", "e-mail address", "home path"}, found


# ---------------------------------------------------------------- U3, H5: the guide and the quick starts
def test_U3_the_reference_pages_are_current():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(REPO / "tools/build_rule_reference.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_U3_every_page_in_the_navigation_exists_and_links_resolve():
    nav = re.findall(r":\s*([\w/.-]+\.md)\s*$", (REPO / "mkdocs.yml").read_text(), re.M)
    assert len(nav) >= 15
    for page in nav:
        p = REPO / "docs" / page
        assert p.is_file(), page
        for link in re.findall(r"\]\(([^)#:]+\.md)", p.read_text()):
            assert (p.parent / link).resolve().is_file(), (page, link)


def test_U3_both_governance_layers_are_first_class_and_the_start_page_leads_with_the_agent():
    start = (REPO / "docs/index.md").read_text()
    assert "Run the using-steward skill" in start
    assert (REPO / "docs/guides/single-project.md").is_file() and (REPO / "docs/guides/multi-project.md").is_file()


@pytest.mark.parametrize("page", ["quickstart.md", "quickstart-paper.md", "quickstart-talk.md"])
def test_H5_quick_start_commands_run_as_written(cli, tmp_path, monkeypatch, page):
    """S10: each quick start, in a fresh folder, every command as written, ends at the gate outcome it documents."""
    import shlex
    text = (REPO / "docs" / page).read_text()
    block = re.search(r"```bash\n(.*?)```", text, re.S).group(1)
    expected = re.search(r"Expected gate: `(Gate default: [A-Z ]+)`", text).group(1)
    monkeypatch.chdir(tmp_path)
    gate_lines = []
    for line in [l for l in block.splitlines() if l.startswith("steward ")]:
        code, out, err = cli(*shlex.split(line)[1:])
        assert code in (0, 1, 2, 3), (line, code, err)  # a gate verdict, never a usage or internal error
        gate_lines += [l for l in out.splitlines() if l.startswith("Gate default:") and "not evaluated" not in l]
    assert gate_lines and gate_lines[-1].startswith(expected), (page, gate_lines)


def test_S10_the_install_line_pins_the_version_these_pages_describe():
    from steward import __version__
    start = (REPO / "docs/index.md").read_text()
    pinned = re.search(r"Bio-STEWARD\.git@v([0-9.]+)", start).group(1)
    if ".dev" in __version__:  # during development the pages pin the latest release, before this version
        assert tuple(map(int, pinned.split("."))) < tuple(map(int, __version__.split(".dev")[0].split("."))), pinned
    else:
        assert pinned == __version__, (pinned, __version__)
