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
