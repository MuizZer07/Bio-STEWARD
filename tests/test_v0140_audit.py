"""0.14.0: the Progress Audit's evidence (steward audit progress) and the progress-audit skill."""

import json
import os

from test_v0140_known_issues import home  # noqa: F401


def test_audit_progress_reports_use_pending_and_reach_and_changes_nothing(cli, home, monkeypatch):
    from test_v0120_features import _item
    me, them = home / "me", home / "them"
    for d in (me, them):
        d.mkdir()
        cli("init", "--repo", d)
    with open(me / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\nconsumers = ["BBB"]\n')
    with open(them / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "BBB"\nuses = { AAA = "v1.0.0" }\n\n[paper]\n')
    monkeypatch.chdir(me)
    cli("exchange", "init")
    assert cli("exchange", "receive", _item(me, "BBB-REQ-001"))[0] == 0
    before = sorted((p, p.stat().st_mtime_ns) for p in me.rglob("*") if p.is_file())
    code, out, err = cli("audit", "progress", "--json")
    assert code == 0, err
    doc = json.loads(out)
    c = doc["usage"]["consumers"]["BBB"]
    assert c["filed"] == 1 and c["open"] == ["BBB-REQ-001"]
    assert c["checkout"]["uses"] == "v1.0.0" and "paper" in c["checkout"]["areas_configured"]  # its claims, apart
    assert doc["pending"]["exchange_open"] == ["BBB-REQ-001"]
    assert "a licence" in doc["reach"]["missing"] or "a licence" in doc["reach"]["present"]
    assert sorted((p, p.stat().st_mtime_ns) for p in me.rglob("*") if p.is_file()) == before  # read-only
    _, text, _ = cli("audit", "progress")
    assert "## 2. Use by other projects" in text and "Read-only" in text


def test_the_progress_audit_skill_is_in_the_manage_bundle_and_names_its_steps():
    from conftest import REPO
    text = (REPO / "skills/progress-audit/SKILL.md").read_text()
    assert "Progress Audit" in text and "steward audit progress" in text and "sign ahead" in text
    assert '"progress-audit"' in (REPO / "skills/BUNDLES.toml").read_text()


def test_the_timeline_page_holds_titles_dates_and_outcomes_only(cli, home, monkeypatch):
    d = home / "site"
    d.mkdir()
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[docs]\npublish = ["overview", "timeline"]\n')
    (d / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "a"\ntitle = "Preprint"\ndue = 2027-01-20T23:59:00-12:00\n'
        'kind = "preprint"\n')
    monkeypatch.chdir(d)
    assert cli("docs", "build")[0] == 0
    page = (d / "docs/project/timeline.md").read_text()
    assert "| Preprint | preprint | 2027-01-20T23:59:00-12:00 | — |" in page and "days" not in page
    _, rep = cli.check(d, "docs")
    from conftest import one
    assert one(rep, "R-69")["status"] == "PASS"



# ---------------------------------------------------------------- review of 0.14.0: W1, W2, W3, W5, W7
def _two(cli, home, monkeypatch):
    me, them = home / "me", home / "them"
    for d in (me, them):
        d.mkdir()
        cli("init", "--repo", d)
    with open(me / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\nconsumers = ["BBB"]\n')
    with open(them / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "BBB"\n')
    monkeypatch.chdir(me)
    cli("exchange", "init")
    return me, them


def test_W1_the_audit_runs_signature_checks_read_only(cli, home, monkeypatch):
    from steward import authorize as az
    from steward import audit as au
    from steward.models import load_config
    me, _ = _two(cli, home, monkeypatch)
    seen = []
    real = au.where
    monkeypatch.setattr(au, "where", lambda root: (seen.append(az.READ_ONLY), real(root))[1])
    au.progress(me, load_config(me))
    assert seen == [True] and az.READ_ONLY is False


def test_W2_two_checkouts_claiming_one_code_are_not_believed(cli, home, monkeypatch):
    me, them = _two(cli, home, monkeypatch)
    twin = home / "twin"
    twin.mkdir()
    cli("init", "--repo", twin)
    with open(twin / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "BBB"\nuses = { AAA = "v9.9.9" }\n')
    from test_v0120_features import _item
    cli("exchange", "receive", _item(me, "BBB-REQ-001"))
    _, out, _ = cli("audit", "progress", "--json")
    c = json.loads(out)["usage"]["consumers"]["BBB"]
    assert c["checkout"]["status"].startswith("ambiguous") and "uses" not in c["checkout"]


def test_W3_a_local_path_in_the_evidence_is_withheld(cli, home, monkeypatch):
    me, _ = _two(cli, home, monkeypatch)
    (me / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    (me / "CHANGELOG.md").write_text("# C\n\n## 1.0.0\n\n### Known issues in 1.0.0\n| ID | S | I | U |\n|---|---|---|---|\n"
                                     "| /" "Users/alice/secret | x | y | z |\n\n## 0.9.0\n")  # scrub: allow; steward: allow R-07 (synthetic)
    _, out, _ = cli("audit", "progress", "--json")
    assert "alice" not in out and "withheld" in out


def test_W5_project_and_toolkit_versions_and_own_open_requests(cli, home, monkeypatch):
    me, _ = _two(cli, home, monkeypatch)
    (me / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "2.3.0"\n')
    cli("exchange", "new", "request", "--to", "BBB", "--title", "mine")
    _, out, _ = cli("audit", "progress", "--json")
    doc = json.loads(out)
    assert doc["where"]["project_version"] == "2.3.0" and doc["where"]["toolkit_version"]
    assert doc["pending"]["own_open"] == ["AAA-REQ-001"]


def test_W7_a_timeline_title_is_shown_as_text(cli, home, monkeypatch):
    d = home / "site"
    d.mkdir()
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write('\n[docs]\npublish = ["overview", "timeline"]\n')
    (d / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "a"\ntitle = "<b>bold</b> **x**"\n'
        'due = 2027-01-20T23:59:00-12:00\n')
    monkeypatch.chdir(d)
    assert cli("docs", "build")[0] == 0
    page = (d / "docs/project/timeline.md").read_text()
    assert "\\<b\\>bold\\</b\\> \\*\\*x\\*\\*" in page
