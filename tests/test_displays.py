"""PaperKit v0.2.2: display manifest, lock and R-11 (stale, missing, uncited, not included, unregistered)."""

import shutil

from conftest import REPO, append, codes, edit, one

MANIFEST = "paper/displays.toml"
LOCK = "paper/displays.lock"
TEX = "paper/main.tex"


def test_example_displays_pass(cli, example):
    _, rep = cli.check(example, "paper")
    assert one(rep, "R-11")["status"] == "PASS"


def test_input_changed_after_build_is_stale(cli, example):
    append(example, "benchmarks/splits/test.txt", "S041_1\n")
    code, rep = cli.check(example)
    res = one(rep, "R-11")
    assert res["status"] == "FAIL" and code == 1
    stale = [d for d in res["details"] if d["code"] == "R-11.stale"]
    assert {d["field"] for d in stale} == {"displays.splits_table", "displays.donors_figure"}
    assert all(d["value"] == "inputs" for d in stale)


def test_script_change_is_stale_and_record_clears_it(cli, example):
    append(example, "analysis/make_displays.py", "\n# changed\n")
    _, rep = cli.check(example)
    assert "R-11.stale" in codes(one(rep, "R-11"))
    code, out, _ = cli("paper", "displays", "--repo", example, "--record")
    assert code == 0 and "wrote paper/displays.lock" in out
    _, rep = cli.check(example)
    assert one(rep, "R-11")["status"] == "PASS"  # the author declared the rebuild; the lock cannot prove it


def test_hand_edited_output_is_stale(cli, example):
    append(example, "paper/tables/splits.tex", "% edited by hand\n")
    _, rep = cli.check(example)
    assert any(d.get("value") == "output" for d in one(rep, "R-11")["details"])


def test_missing_output_incomplete_missing_script_fails(cli, example):
    (example / "paper/figures/donors.tex").unlink()
    _, rep = cli.check(example)
    assert one(rep, "R-11")["status"] == "INCOMPLETE"
    (example / "analysis/make_displays.py").unlink()
    _, rep = cli.check(example)
    assert "R-11.missing_script" in codes(one(rep, "R-11"))
    code, _, err = cli("paper", "displays", "--repo", example, "--record")
    assert code == 1 and "nothing recorded" in err


def test_uncited_display_is_incomplete(cli, example):
    edit(example, TEX, "Table~\\ref{tab:splits}, Figure~\\ref{fig:donors}", "Table~\\ref{tab:splits}")
    _, rep = cli.check(example)
    res = one(rep, "R-11")
    assert res["status"] == "INCOMPLETE" and {"code": "R-11.not_cited", "field": "displays.donors_figure",
                                              "value": "fig:donors"} in res["details"]


def test_unregistered_figure_incomplete_in_draft_fail_in_final(cli, example):
    shutil.copy(REPO / "tests/fixtures/figure_with_term.pdf", example / "paper/figures/extra.pdf")
    edit(example, TEX, "\\section{Limitations}", "\\includegraphics{figures/extra}\n\\section{Limitations}")
    _, rep = cli.check(example)
    res = one(rep, "R-11")
    assert res["status"] == "INCOMPLETE" and "R-11.unregistered" in codes(res)
    code, _, _ = cli("check", "--repo", example, "--final")
    assert code == 1


def test_no_lock_is_incomplete_and_invalid_manifest_fails(cli, example):
    (example / LOCK).unlink()
    _, rep = cli.check(example)
    assert "R-11.no_lock" in codes(one(rep, "R-11"))
    append(example, MANIFEST, '\n[displays.dup]\nkind = "table"\noutput = "paper/tables/splits.tex"\nscript = "x.py"\nlabel = "tab:x"\n')
    _, rep = cli.check(example)
    assert one(rep, "R-11")["status"] == "FAIL"


def test_no_manifest_not_applicable(cli, example):
    (example / MANIFEST).unlink()
    _, rep = cli.check(example)
    assert one(rep, "R-11")["status"] == "NOT_APPLICABLE"  # no \includegraphics in the example
