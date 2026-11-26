"""0.20.4: the public documentation is accurate and the capabilities page is current."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parents[1]


def test_the_capabilities_page_is_current():
    r = subprocess.run([sys.executable, "tools/build_capabilities.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_every_public_doc_links_commands_and_rules_are_real():
    sys.path.insert(0, str(REPO / "tools"))
    import check_docs
    assert check_docs.problems() == []


def test_the_readme_badges_state_the_current_facts():
    from steward import __version__
    from steward.rules import RULES
    text = (REPO / "README.md").read_text()
    skills = len(list((REPO / "skills").glob("*/SKILL.md")))
    assert f"badge/version-{__version__}%20beta" in text and f"Agent%20Skills-{skills}-" in text
    assert f"deterministic%20rules-{len(RULES)}-" in text and f"latest release `v{__version__}`" in text


def test_the_lint_accepts_the_toolkits_name_but_not_a_claim():
    sys.path.insert(0, str(REPO / "tools"))
    import lint_language as ll
    assert ll.lint_text("Scientific Toolkit for Engineering, Workflow Assurance, Reproducibility, and Development") == []
    assert ll.lint_text("Workflow\n> Assurance, Reproducibility, and Development)") == []
    assert ll.lint_text("This guarantees reproducibility.")  # still a claim the lint rejects


def test_the_citation_names_the_toolkit_and_its_doi():
    import yaml
    from steward import __version__
    c = yaml.safe_load((REPO / "CITATION.cff").read_text())
    assert c["title"].startswith("Bio-STEWARD: Scientific Toolkit for Engineering") and c["version"] == __version__
    assert c["doi"].startswith("10.5281/zenodo.") and c["doi"] in (REPO / "README.md").read_text()
    assert c["authors"][0]["orcid"].startswith("https://orcid.org/")
