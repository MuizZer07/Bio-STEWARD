"""Token efficiency without loss of accuracy: invariants A1–A6 and footprint budgets (DESIGN_v0.5 §3–§4)."""

import json
import re
import sys

import pytest

from steward.cli import build_parser

from conftest import CONTRACT, REPO, edit
from test_determinism import mixed

sys.path.insert(0, str(REPO / "tools"))
import measure_footprint  # noqa: E402

LINE = re.compile(r"^(FAIL|INCOMPLETE|UNKNOWN|NOT_APPLICABLE|PASS) (R-\d\d) \S+ (\S+) — ")


def non_pass(report: dict) -> set[tuple[str, str, str]]:
    return {(r["rule"], r["subject"], r["status"]) for r in report["verdict"]["results"] if r["status"] != "PASS"}


def parse_summary(text: str) -> tuple[dict[str, int], set[tuple[str, str, str]]]:
    counts_line = next(l for l in text.splitlines() if l.startswith("Summary: "))
    counts = {k: int(v) for k, v in re.findall(r"([A-Z_]+) (\d+)", counts_line)}
    rows = {(m.group(2), m.group(3), m.group(1)) for m in map(LINE.match, text.splitlines()) if m}
    return counts, rows


@pytest.mark.parametrize("state", ["example", "mixed", "many"])
def test_A1_A3_summary_matches_full_run(cli, example, state):
    if state == "mixed":
        mixed(example)
    if state == "many":
        many(example, 50)
    code_full, full = cli.check(example)
    code_sum, text, _ = cli("check", "--repo", example, "--summary")
    counts, rows = parse_summary(text)
    assert counts == full["verdict"]["summary"]["counts"]                 # A1: counts unchanged
    # A1/A2 (0.10.0 U2): every result that is neither PASS nor NOT_APPLICABLE has its row; the not-applicable rules
    # are folded onto one line that names each of them (--all restores one row each)
    folded = next((l for l in text.splitlines() if l.startswith("NOT_APPLICABLE (")), "")
    na_only = {r for r, s, st in non_pass(full) if st == "NOT_APPLICABLE"} - {r for r, s, st in non_pass(full) if st != "NOT_APPLICABLE"}
    assert rows == {x for x in non_pass(full) if not (x[2] == "NOT_APPLICABLE" and x[0] in na_only)}
    assert all(r in folded.split() for r in na_only)
    _, all_text, _ = cli("check", "--repo", example, "--summary", "--all")
    assert parse_summary(all_text)[1] == non_pass(full)                  # --all: every non-PASS row
    assert code_sum == code_full                                          # A3: same exit code
    for g in full["verdict"]["gates"]:                                    # A3: same gate decision
        assert (f"Gate {g['name']}: ELIGIBLE (" in text) == g["eligible"]
        assert (f"Gate {g['name']}: NOT ELIGIBLE (" in text) == (not g["eligible"])


def many(root, n):
    text = (root / CONTRACT).read_text()
    for i in range(n):
        (root / f"benchmarks/c{i:02d}.contract.toml").write_text(
            text.replace('id       = "expr-clf"', f'id       = "c{i:02d}"').replace("value      = 0.05", 'value      = "TBD"'))


def test_A2_never_truncates(cli, example):
    many(example, 50)
    _, text, _ = cli("check", "--repo", example, "--summary")
    assert sum(1 for l in text.splitlines() if l.startswith("INCOMPLETE R-02")) == 50
    assert "more" not in text.lower()


def test_A5_summary_with_output_keeps_full_evidence(cli, example, tmp_path):
    mixed(example)
    out = tmp_path / "r.json"
    cli("check", "--repo", example, "--summary", "--output", out)
    _, full = cli.check(example)
    assert json.loads(out.read_text())["verdict"] == full["verdict"]


def test_A5_one_result_can_be_fetched_with_its_details(cli, example, tmp_path):
    mixed(example)
    out = tmp_path / "r.json"
    _, text, _ = cli("check", "--repo", example, "--summary", "--output", out)
    assert f"steward report {out}" in text
    code, detail, _ = cli("report", out, "--format", "text", "--rule", "R-03")
    assert code == 0 and "R-03.primary_undefined" in detail
    assert "Summary: PASS" in detail                                      # summary and gates are never filtered
    assert "R-05" not in detail.split("Summary:")[0]
    assert cli("report", out, "--rule", "R-99")[0] == 64


def test_A6_unknown_and_incomplete_never_rendered_as_pass(cli, example, tmp_path):
    edit(example, CONTRACT, "alpha     = 0.05", 'alpha     = "unknown"')
    out = tmp_path / "r.json"
    cli("check", "--repo", example, "--output", out)
    for fmt in ("summary", "text", "md"):
        _, text, _ = cli("report", out, "--format", fmt)
        assert "UNKNOWN" in text and "NOT ELIGIBLE" in text, fmt


def test_A4_no_option_selects_rules_by_budget():
    names = []
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices  # noqa: SLF001 (introspection in a test)
    for command, action in commands.items():
        if command == "tokens":  # DESIGN_v0.5 A4 allows these names for usage reporting.
            assert set(action._subparsers._group_actions[0].choices) == {"check", "report"}  # noqa: SLF001
            continue
        for a in action._actions:  # noqa: SLF001
            names += list(a.option_strings) + [a.dest]
    assert not [n for n in names if re.search(r"budget|token|context|fast|quick|lite", n)]


def test_summary_and_json_are_exclusive(cli, example):
    assert cli("check", "--repo", example, "--summary", "--format", "json")[0] == 64


def test_summary_is_compact(cli, example):
    mixed(example)
    _, text, _ = cli("check", "--repo", example)
    _, summ, _ = cli("check", "--repo", example, "--summary")
    assert len(summ.encode()) <= 0.4 * len(text.encode()) or len(summ.encode()) < len(text.encode())
    _, full, _ = cli("check", "--repo", example, "--format", "json")
    assert len(summ.encode()) < 0.25 * len(full.encode())


def test_F2_footprint_budgets_hold():
    assert measure_footprint.violations(measure_footprint.measure()) == []


def test_budget_guard_requires_recorded_decisions():
    m = measure_footprint.measure()
    m["always_loaded"]["bundles"]["core"]["decision"] = "2099-01-01 — a decision nobody recorded"
    assert any("not found in development/DECISIONS.md" in v for v in measure_footprint.violations(m))
    m["always_loaded"]["bundles"]["core"]["decision"] = None
    assert any("no decision reference" in v for v in measure_footprint.violations(m))
    m = measure_footprint.measure()
    m["skills"]["using-steward"]["description"]["words"] = 36  # per-skill cap (35)
    assert any("using-steward: description" in v for v in measure_footprint.violations(m))


def test_A6_every_rule_has_a_next_action_and_kits_are_shown(cli, example):
    from steward.report import NEXT
    from steward.rules import AREAS, RULES

    assert set(RULES) == set(NEXT)
    _, text, _ = cli("check", "--repo", example, "--summary")
    # FB-4 / FB-9 (0.8.1): the configured areas, counted, from the configuration and the results
    assert f"Configured: 9 of {len(AREAS)} areas: config, contract, prior-work, paper, talk, evidence, benchmark, governance, files" in text
    assert "not configured:" in text
    mixed(example)
    _, text, _ = cli("check", "--repo", example, "--summary")
    assert "  next: make the contract's cross-references consistent" in text
