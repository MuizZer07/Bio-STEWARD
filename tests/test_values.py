"""PaperKit v0.2.1: the values registry (R-10), assertions (R-15), `steward paper values`; skill bundles (H2)."""

import pytest

from steward import values as v

from conftest import append, codes, edit, one

VALUES = "paper/values.toml"
GEN = "paper/values.tex"
TEX = "paper/main.tex"


# ---------------------------------------------------------------- example
def test_example_values_pass_and_text_uses_keys(cli, example):
    code, rep = cli.check(example, "paper")
    assert one(rep, "R-10")["status"] == "PASS" and one(rep, "R-15")["status"] == "PASS"
    assert code == 0


def test_paper_values_prints_and_writes(cli, example):
    code, out, _ = cli("paper", "values", "--repo", example)
    assert code == 0 and "n_donors = 40" in out and "samples_per_donor = 3" in out and "alpha = 0.05" in out
    before = (example / GEN).read_text()
    (example / GEN).unlink()
    code, out, _ = cli("paper", "values", "--repo", example, "--write")
    assert code == 0 and (example / GEN).read_text() == before  # generation is deterministic


# ---------------------------------------------------------------- R-10
def test_R10_source_changed_makes_generated_file_stale(cli, example):
    append(example, "benchmarks/splits/test.txt", "S999_1\n")  # results changed after generation
    code, rep = cli.check(example)
    res = one(rep, "R-10")
    assert res["status"] == "FAIL" and "R-10.generated_stale" in codes(res) and code == 1


def test_R10_hand_edited_generated_value_fails(cli, example):
    edit(example, GEN, "{stewardval@n_donors}{40}", "{stewardval@n_donors}{41}")
    _, rep = cli.check(example)
    assert "R-10.generated_stale" in codes(one(rep, "R-10"))


def test_R10_unknown_key_in_text_fails(cli, example):
    edit(example, TEX, "\\val{n_donors} donors", "\\val{n_donor} donors")
    _, rep = cli.check(example)
    res = one(rep, "R-10")
    assert res["status"] == "FAIL" and any(d.get("value") == "n_donor" for d in res["details"] if d["code"] == "R-10.unknown_key")


def test_R10_missing_source_is_incomplete_bad_pointer_fails(cli, example):
    append(example, VALUES, '\n[values.auroc]\nsource = "results/metrics.json"\npointer = "/test/auroc"\n')
    _, rep = cli.check(example)
    assert one(rep, "R-10")["status"] == "INCOMPLETE"  # the run has not happened yet
    (example / "results").mkdir()
    (example / "results/metrics.json").write_text('{"test": {"auprc": 0.5}}')
    _, rep = cli.check(example)
    assert "R-10.source_error" in codes(one(rep, "R-10"))


def test_R10_invalid_registry_fails(cli, example):
    append(example, VALUES, '\n[values.bad]\nsource = "x.json"\npointer = "/a"\ncount = "rows"\n')  # two kinds
    _, rep = cli.check(example)
    assert one(rep, "R-10")["status"] == "FAIL"
    assert one(rep, "R-15")["status"] == "UNKNOWN"


def test_R10_registry_absent(cli, example):
    (example / VALUES).unlink()
    _, rep = cli.check(example)
    assert one(rep, "R-10")["status"] == "FAIL"  # the text still uses \val keys
    edit(example, TEX, "\\input{values}", "")
    text = (example / TEX).read_text()
    import re
    (example / TEX).write_text(re.sub(r"\\val\{[^}]+\}", "N", text))
    _, rep = cli.check(example)
    assert one(rep, "R-10")["status"] == "NOT_APPLICABLE"


def test_R10_literal_listed_in_draft_blocks_in_final(cli, example):
    edit(example, TEX, "No results are reported at this stage.", "No results are reported at this stage; 37 checks ran.")
    _, rep = cli.check(example)
    res = one(rep, "R-10")
    assert res["status"] == "PASS" and {"code": "R-10.literal", "path": TEX, "value": "37"} in [
        {k: d[k] for k in ("code", "path", "value")} for d in res["details"] if d["code"] == "R-10.literal"]
    code, _, _ = cli("check", "--repo", example, "--final")
    assert code == 2
    edit(example, TEX, "37 checks ran.", "37 checks ran. % literal-ok: design constant")
    code, _, _ = cli("check", "--repo", example, "--final")
    assert code == 0


def test_R10_years_refs_and_cites_are_not_literals(cli, example):
    edit(example, TEX, "No results are reported at this stage.", "Since 2024 (Section~\\ref{sec:intro}) \\citep{exampleA2025}.")
    _, rep = cli.check(example)
    assert not [d for d in one(rep, "R-10")["details"] if d["code"] == "R-10.literal"]


# ---------------------------------------------------------------- R-15
def test_R15_violated_assertion_fails_with_values(cli, example):
    append(example, VALUES, '\n[[assert]]\nexpr = "{n_test_samples} > {n_train_samples}"\n')
    code, rep = cli.check(example)
    res = one(rep, "R-15")
    assert res["status"] == "FAIL" and "R-15.violated" in codes(res) and code == 1
    assert any("n_test_samples=24" in d.get("message", "") for d in res["details"])


def test_R15_tolerance_and_unavailable(cli, example):
    append(example, VALUES, '\n[[assert]]\nexpr = "{alpha} * 2 == 0.1001"\ntol = 0.001\n')
    _, rep = cli.check(example)
    assert one(rep, "R-15")["status"] == "PASS"
    append(example, VALUES, '\n[values.later]\nsource = "results/none.json"\npointer = "/x"\n\n[[assert]]\nexpr = "{later} > 0"\n')
    _, rep = cli.check(example)
    assert one(rep, "R-15")["status"] == "UNKNOWN"


def test_R15_no_assertions_not_applicable(cli, example):
    text = (example / VALUES).read_text()
    (example / VALUES).write_text(text[: text.index("[[assert]]")])
    _, rep = cli.check(example)
    assert one(rep, "R-15")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- evaluator safety and emitters
@pytest.mark.parametrize("expr", ["__import__('os')", "{a}.real", "[1][0]", "{a} ** 2", "open('x')"])
def test_derive_rejects_anything_but_arithmetic(expr):
    with pytest.raises((ValueError, SyntaxError, KeyError)):
        v.derive(expr, {"a": 1.0})


def test_derive_cycle_is_an_error(tmp_path):
    vf = v.ValuesFile.model_validate({"schema": "steward.values/0.1", "values": {
        "a": {"derive": "{b} + 1"}, "b": {"derive": "{a} + 1"}}})
    comp = v.compute(tmp_path, vf)
    assert set(comp.errors) == {"a", "b"}


def test_emitters_escape_and_sort():
    text = {"b_pct": "12.5%", "a": "x_y"}
    tex = v.emit(text, "tex")
    assert tex.index("stewardval@a}") < tex.index("stewardval@b_pct}") and "12.5\\%" in tex and "x\\_y" in tex
    assert v.emit(text, "quarto").splitlines()[1] == 'a: "x_y"'


# ---------------------------------------------------------------- H2 bundles
def test_init_kits_select_bundles(cli, tmp_path):
    from test_language_and_skills import CORE_SKILLS

    cli("init", "--repo", tmp_path, "--skills", "s", "--kits", "paper")
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["figures-and-tables", "manuscript-drafting", "manuscript-review", "number-crosscheck", "paper-kit",
                                                                "submission-readiness"]
    cli("init", "--repo", tmp_path / "x", "--skills", "s", "--paper") if (tmp_path / "x").mkdir() is None else None
    names = sorted(p.name for p in (tmp_path / "x/s").iterdir())
    assert set(CORE_SKILLS) <= set(names) and "paper-kit" in names
    assert cli("init", "--repo", tmp_path, "--skills", "s", "--kits", "slides")[0] == 64
