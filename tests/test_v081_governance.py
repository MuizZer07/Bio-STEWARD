"""0.8.1 governance: the decisions log without a signing policy (AR-06), review classes and the stopping rule
(AR-13)."""

import shutil
import subprocess

import pytest

from conftest import codes, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


ENTRY = '\n## 2026-11-20: adopt the toolkit\n- **Quote:** "adopt it"\n- **Decision:** adopted\n- **Consequences:** none\n'


@pytest.fixture
def decisions(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[integrity]\ndecisions_format = "template"\n')
    (r / "development/DECISIONS.md").write_text("# Decisions (append-only)\n" + ENTRY)
    sh(r, "git", "add", "-A")
    sh(r, "git", "add", "-f", "development/DECISIONS.md")  # a global gitignore may cover *.md
    sh(r, "git", "commit", "-qm", "base")
    sh(r, "git", "checkout", "-q", "-b", "task")
    monkeypatch.chdir(r)
    return r


def r38(cli, root):
    _, rep = cli.check(root)
    return one(rep, "R-38")


@git_needed
def test_AR06_a_well_formed_log_passes_without_a_policy(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write(ENTRY.replace("2026-11-20", "2026-11-21"))
    res = r38(cli, decisions)
    assert res["status"] == "PASS", res
    assert "R-38.append_only_weak" in codes(res)  # the report says the git base is weaker than a pinned baseline


@git_needed
def test_AR06_a_malformed_entry_fails(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-22: missing parts\n- **Decision:** something\n")
    res = r38(cli, decisions)
    assert res["status"] == "FAIL" and "R-38.entry_malformed" in codes(res)


@git_needed
def test_AR06_a_backfilled_entry_may_say_not_recorded_verbatim(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-22: earlier\n- **Quote:** not recorded verbatim (source: a meeting note)\n"
                "- **Decision:** kept\n- **Consequences:** none\n")
    assert r38(cli, decisions)["status"] == "PASS"


@git_needed
def test_AR06_an_edited_earlier_entry_fails_against_the_git_base(cli, decisions):
    p = decisions / "development/DECISIONS.md"
    p.write_text(p.read_text().replace("adopted", "rejected"))
    res = r38(cli, decisions)
    assert res["status"] == "FAIL" and "R-38.decisions_rewritten" in codes(res)


@git_needed
def test_AR06_an_unresolvable_configured_base_is_unknown(cli, decisions):
    text = (decisions / "steward.toml").read_text().replace('decisions_format = "template"', 'decisions_format = "template"\ndecisions_base = "no-such-ref"')
    (decisions / "steward.toml").write_text(text)
    assert r38(cli, decisions)["status"] == "UNKNOWN"


# ---------------------------------------------------------------- AR-13: classes, stopping rule, accepted on tests
REG = '''schema = "steward.findings/0.1"
[[reviews]]
id = "r1"
reviewer = "Independent reviewer"
implementer = "Implementer"
revision = "{rev}"
{findings}
'''


def finding(fid, severity, status, extra=""):
    return f'[[findings]]\nid = "{fid}"\nreview = "r1"\nseverity = "{severity}"\ntitle = "t"\nstatus = "{status}"\n{extra}\n'


@pytest.fixture
def review(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    r = tmp_path / "rv"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[release]\nrequired = []\nreview_required = true\nstopping_rule = "no-blocking-no-wrong-result"\n'
                'known_issues = "CHANGELOG.md"\n')
    (r / "tests").mkdir()
    (r / "tests/test_a.py").write_text("def test_a(): pass\n")
    (r / "CHANGELOG.md").write_text("# Changelog\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "v1")
    monkeypatch.chdir(r)
    return r


def register(root, *findings):
    (root / "development/assessment").mkdir(parents=True, exist_ok=True)
    (root / "development/assessment/findings.toml").write_text(
        REG.format(rev=sh(root, "git", "rev-parse", "HEAD"), findings="".join(findings)))


def r43(cli, root):
    _, rep = cli.check(root)
    return one(rep, "R-43")


@git_needed
def test_AR13_an_open_limitation_must_be_listed_as_a_known_issue(cli, review):
    register(review, finding("F1", "medium", "open", 'class = "limitation"'))
    res = r43(cli, review)
    assert res["status"] == "INCOMPLETE" and "R-43.unlisted_limitation" in codes(res)
    (review / "CHANGELOG.md").write_text("# Changelog\n## Known issues\n- F1: a limitation\n")
    assert r43(cli, review)["status"] == "PASS"


@git_needed
@pytest.mark.parametrize("cls", ["blocking", "wrong_result"])
def test_AR13_an_open_blocking_or_wrong_result_finding_fails_at_any_severity(cli, review, cls):
    register(review, finding("F2", "low", "open", f'class = "{cls}"'))
    assert r43(cli, review)["status"] == "FAIL"


@git_needed
def test_AR13_accepted_on_tests_needs_a_recorded_decision(cli, review):
    register(review, finding("F3", "medium", "accepted_on_tests", 'test = "tests/test_a.py::test_a"'))
    res = r43(cli, review)
    assert res["status"] == "FAIL" and "R-43.accepted_on_tests_unrecorded" in codes(res)
    (review / "development/DECISIONS.md").write_text("# Decisions\n\n## 2026-11-23: accept F3 on its test\n")
    register(review, finding("F3", "medium", "accepted_on_tests", 'test = "tests/test_a.py::test_a"\ndecision = "accept F3 on its test"'))
    assert r43(cli, review)["status"] == "PASS"


@git_needed
def test_AR13_a_high_finding_accepted_on_tests_still_needs_reverification(cli, review):
    (review / "development/DECISIONS.md").write_text("# Decisions\n\n## 2026-11-23: accept F4\n")
    register(review, finding("F4", "high", "accepted_on_tests", 'test = "tests/test_a.py::test_a"\ndecision = "accept F4"'))
    res = r43(cli, review)
    assert res["status"] == "INCOMPLETE" and "R-43.not_reverified" in codes(res)
