"""Sprint B02 (STW-035): result-code descriptions in explain (B4), analysis-review template and
placeholder warnings (B5), and first-contact wording + confirmatory-only red-team recommendation (B7)."""

from __future__ import annotations

import json
import subprocess

import pytest

from conftest import codes, one


def _fresh(tmp_path, name="proj"):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


# ---------------------------------------------------------------- B4: result-code descriptions
def test_B4_every_emitted_result_code_has_a_one_line_description():
    from steward.cli import code_fixes, explain_entry
    from steward.code_docs import CODE_DOCS
    from steward.rules import RULES

    seen: set[str] = set()
    for rule in sorted(RULES):
        fixes = code_fixes(rule)
        entry = explain_entry(rule)
        assert [c["code"] for c in entry["codes"]] == list(fixes), rule
        for item in entry["codes"]:
            code, fix = item["code"], item["fix"]
            seen.add(code)
            assert isinstance(fix, str) and fix, (rule, code)
            assert "\n" not in fix, (rule, code, fix)
            assert len(fix.split()) >= 3 and fix[0].isalpha(), (rule, code, fix)
    # No stale entries in CODE_DOCS for codes that no rule emits
    assert sorted(set(CODE_DOCS) - seen) == []
    # Previously missed helper and digit-suffixed codes are now covered
    assert "R-40.derived_binary64" in seen
    assert "R-53.deferred_stale" in seen
    for code in ("R-78.contamination_risk", "R-78.id_conflict", "R-78.prompts_not_intact", "R-78.undated_cases"):
        assert code in seen


def test_B4_explain_text_and_json_show_code_descriptions(cli):
    code, text, err = cli("explain", "R-45")
    assert code == 0 and not err
    code, raw, err = cli("explain", "R-45", "--format", "json")
    assert code == 0 and not err
    doc = json.loads(raw)["rules"][0]
    assert len(doc["codes"]) >= 15
    for item in doc["codes"]:
        assert item["fix"], item
        assert f"  {item['code']}: {item['fix']}" in text.splitlines()

    code, all_raw, err = cli("explain", "--all", "--format", "json")
    assert code == 0 and not err
    all_doc = json.loads(all_raw)
    missing = [(r["rule"], c["code"]) for r in all_doc["rules"] for c in r["codes"] if not c["fix"]]
    assert missing == []


# ---------------------------------------------------------------- B5: analysis-review template & placeholders
def test_B5_analysis_review_template_exists_first_and_covers_analyses(cli, tmp_path):
    code, listing, err = cli("task", "template")
    assert code == 0 and not err
    first_line = listing.splitlines()[0]
    assert first_line.startswith("Brief templates: analysis-review, "), first_line

    out_path = tmp_path / "development/tasks/AR-001.md"
    code, out, err = cli("task", "template", "analysis-review", "--output", out_path)
    assert code == 0 and not err and out_path.is_file()
    text = out_path.read_text(encoding="utf-8")
    assert "\r" not in text
    for term in ("scripts", "notebooks", "figures", "sample sheets", "GO reference", "ANALYSIS"):
        assert term in text, term


def test_B5_task_brief_warns_on_unfilled_placeholders_and_clears_when_filled(cli, tmp_path):
    from steward import briefs as br

    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    task_file = d / "development/tasks/AR-001.md"
    assert cli("task", "template", "analysis-review", "--repo", d, "--output", task_file)[0] == 0

    code, out, err = cli("task", "brief", task_file, "--repo", d, "--for", "codex")
    assert code == 0 and "warning:" in err and "placeholders" in err
    for slot in ("title", "ID", "GO reference", "Branch", "Owner", "Goal", "Scope", "Acceptance criteria"):
        assert slot in err, (slot, err)
    assert "# Brief for Codex:" in out

    # Filling only the header still warns if ANALYSIS or DATE remains in the body
    partial = (
        task_file.read_text(encoding="utf-8")
        .replace("# Task: independent review of ANALYSIS", "# Task: independent review of differential expression")
        .replace("… (unique, e.g. `AR-001`)", "`AR-001`")
        .replace("… (the `development/DECISIONS.md` entry giving the human go-ahead for this task)",
                 "DECISIONS.md 2026-11-28: approve DE review")
        .replace("… (and the base commit or tag, if comparing changes)", "main")
        .replace("… · **Approver:** …", "Lead · **Approver:** Lead")
    )
    task_file.write_text(partial, encoding="utf-8")
    code, _, err = cli("task", "brief", task_file, "--repo", d, "--for", "codex")
    assert code == 0 and "warning:" in err and "Goal" in err and "Scope" in err and "Acceptance criteria" in err

    # Filling every placeholder removes the warning completely
    filled = partial.replace("ANALYSIS", "DE reanalysis").replace("DATE", "2026-11-28")
    task_file.write_text(filled, encoding="utf-8")
    code, out, err = cli("task", "brief", task_file, "--repo", d, "--for", "codex")
    assert code == 0 and "warning:" not in err and "DE reanalysis" in out

    # Every built-in brief template is detected as having unfilled placeholders before editing
    for name in br.TEMPLATES:
        assert br.unfilled(br.template(name)), name


# ---------------------------------------------------------------- B7: first-contact wording & red-team scope
@pytest.mark.parametrize("with_release", [False, True])
def test_B7_red_team_recommendation_only_for_confirmatory(cli, tmp_path, with_release):
    exp = _fresh(tmp_path, "exp")
    conf = _fresh(tmp_path, "conf")
    cli("init", "--repo", exp, "--profile", "exploratory")
    cli("init", "--repo", conf, "--profile", "confirmatory")
    if with_release:
        for d in (exp, conf):
            with open(d / "steward.toml", "a", encoding="utf-8") as f:
                f.write("\n[release]\nreview_required = false\n")

    _, exp_rep = cli.check(exp)
    _, exp_sum, _ = cli("check", "--repo", exp, "--summary")
    assert "R-43.recommended" not in codes(one(exp_rep, "R-43"))
    assert "red-team" not in exp_sum

    _, conf_rep = cli.check(conf)
    _, conf_sum, _ = cli("check", "--repo", conf, "--summary")
    assert "R-43.recommended" in codes(one(conf_rep, "R-43"))
    assert "Recommended:" in conf_sum and "red-team" in conf_sum


def test_B7_profiles_explained_on_first_contact(cli, tmp_path):
    exp = _fresh(tmp_path, "exp")
    code, out, err = cli("init", "--repo", exp)
    assert code == 0 and not err
    assert "profile exploratory: rules report, few demand" in out
    assert "confirmatory" in out
    assert "rules report, few demand" in (exp / "steward.toml").read_text(encoding="utf-8")

    conf = _fresh(tmp_path, "conf")
    code, out, err = cli("init", "--repo", conf, "--profile", "confirmatory")
    assert code == 0 and not err
    assert "profile confirmatory: requires a benchmark contract and prior-work record" in out

    code, help_out, _ = cli("init", "--help")
    assert code == 0 and "rules report, few demand" in help_out and "benchmark contract" in help_out


def test_B7_go_reference_explained_in_templates(cli, tmp_path):
    from steward import briefs as br

    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    task_tmpl = (d / "development/templates/task.md").read_text(encoding="utf-8")
    assert "GO reference" in task_tmpl and "DECISIONS.md" in task_tmpl and "go-ahead" in task_tmpl

    for name in br.TEMPLATES:
        code, text, err = cli("task", "template", name)
        assert code == 0 and not err
        assert "GO reference" in text and "DECISIONS.md" in text and "go-ahead" in text, name
