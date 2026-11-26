"""T-ST: the result model, summaries and gate eligibility (DESIGN_v0.4 §1; RELEASE_v0.1_SPEC §8.2)."""

from steward import rules
from steward.status import Result, Status, evaluate_gate, gate_exit_code, summarize, worst

from conftest import CONTRACT, edit, gate, one


def r(rule: str, status: Status, subject: str = ".") -> Result:
    return Result(rule, "x", 1, subject, status, "reason")


def test_worst_ignores_not_applicable_and_empty_is_unknown():
    assert worst([Status.PASS, Status.NOT_APPLICABLE]) is Status.PASS
    assert worst([Status.NOT_APPLICABLE]) is Status.UNKNOWN
    assert worst([]) is Status.UNKNOWN
    assert worst([Status.UNKNOWN, Status.INCOMPLETE, Status.PASS]) is Status.INCOMPLETE
    assert worst([Status.INCOMPLETE, Status.FAIL]) is Status.FAIL


def test_T_ST_01_counts_always_present_for_all_five_statuses():
    s = summarize([r("R-01", Status.PASS)])
    assert s["counts"] == {"PASS": 1, "FAIL": 0, "INCOMPLETE": 0, "UNKNOWN": 0, "NOT_APPLICABLE": 0}


def test_T_ST_02_single_unknown_blocks_but_pass_count_is_kept():
    res = [r("R-01", Status.PASS), r("R-02", Status.UNKNOWN)]
    g = evaluate_gate("default", ["R-01", "R-02"], res, partial=False)
    assert not g["eligible"] and gate_exit_code(g) == 3
    assert summarize(res)["counts"]["PASS"] == 1


def test_T_ST_03_vacuous_gate_is_not_eligible():
    g = evaluate_gate("default", ["R-02"], [r("R-02", Status.NOT_APPLICABLE)], partial=False)
    assert not g["eligible"] and g["reason"] == "gate.vacuous" and gate_exit_code(g) == 3
    g = evaluate_gate("default", ["R-02"], [], partial=False)
    assert not g["eligible"] and gate_exit_code(g) == 3


def test_T_ST_04_fail_and_incomplete_both_listed_exit_1():
    res = [r("R-01", Status.PASS), r("R-02", Status.FAIL), r("R-03", Status.INCOMPLETE)]
    g = evaluate_gate("default", ["R-01", "R-02", "R-03"], res, partial=False)
    assert {b["status"] for b in g["blocking"]} == {"FAIL", "INCOMPLETE"}
    assert gate_exit_code(g) == 1


def test_results_outside_a_gate_still_counted(cli, example):
    edit(example, "steward.toml", "# [gates.default]\n# require = [", "[gates.default]\nrequire = [\"R-01\"]\n# x = [")
    edit(example, CONTRACT, "alpha     = 0.05", 'alpha     = "unknown"')
    code, rep = cli.check(example)
    assert code == 0 and gate(rep)["eligible"]
    # R-02, R-03 and R-10 (the paper reports alpha from the contract): visible though no gate requires them
    assert rep["verdict"]["summary"]["counts"]["UNKNOWN"] == 3


def test_T_ST_05_partial_check_never_evaluates_a_gate(cli, example):
    code, rep = cli.check(example, "contract")
    g = gate(rep)
    assert g["evaluated"] is False and g["reason"] == "partial_check" and not g["eligible"]
    assert code == 0  # from summary.worst (PASS), not from a gate
    edit(example, CONTRACT, "value      = 0.05", 'value      = "TBD"')
    code, rep = cli.check(example, "contract")
    assert code == 2 and not gate(rep)["evaluated"]


def test_T_ST_06_rule_exception_is_unknown_and_other_rules_run(cli, example, monkeypatch):
    def boom(ctx):
        raise RuntimeError("bug")

    monkeypatch.setitem(rules.RULE_FUNCS, "R-05", boom)
    code, rep = cli.check(example)
    res = one(rep, "R-05")
    assert res["status"] == "UNKNOWN" and res["reason"] == "internal_error"
    assert one(rep, "R-06")["status"] == "INCOMPLETE"  # R-05 stored nothing, so R-06 finds no record
    assert one(rep, "R-02")["status"] == "PASS"
    assert code == 2
