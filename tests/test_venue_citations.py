"""PaperKit v0.2.3: R-13 venue rules, R-14 citations, the submission manifest."""

import json
from conftest import append, codes, edit, one

VENUE = "paper/venue.toml"
TEX = "paper/main.tex"
BIB = "paper/refs.bib"


def test_example_venue_and_citations_pass(cli, example):
    _, rep = cli.check(example, "paper")
    assert one(rep, "R-13")["status"] == "PASS" and one(rep, "R-14")["status"] == "PASS"
    details = {d["code"]: d.get("value") for d in one(rep, "R-13")["details"]}
    assert details["R-13.abstract_words"] > 30


# ---------------------------------------------------------------- R-13
def test_abstract_over_limit_incomplete_in_draft_fail_in_final(cli, example):
    edit(example, VENUE, "abstract_words = 250", "abstract_words = 20")
    _, rep = cli.check(example)
    res = one(rep, "R-13")
    assert res["status"] == "INCOMPLETE" and "R-13.abstract_words_over" in codes(res)
    assert cli("check", "--repo", example, "--final")[0] == 1


def test_page_limits(cli, example):
    edit(example, VENUE, 'pages_total    = "none"', "pages_total    = 1")
    _, rep = cli.check(example)
    assert "R-13.pages_total" in codes(one(rep, "R-13"))
    edit(example, VENUE, "pages_total    = 1", 'pages_total    = "none"')
    edit(example, VENUE, 'pages_main     = "none"', "pages_main     = 1")
    _, rep = cli.check(example)
    res = one(rep, "R-13")
    assert "R-13.pages_main" in codes(res) or "R-13.main_end_not_found" in codes(res)


def test_missing_required_section(cli, example):
    edit(example, VENUE, 'sections     = ["Limitations"]', 'sections     = ["Limitations", "Data availability"]')
    _, rep = cli.check(example)
    res = one(rep, "R-13")
    assert {"code": "R-13.missing_section", "value": "Data availability"} in res["details"]


def test_unspecified_rules_and_missing_source_are_unknown(cli, example):
    edit(example, VENUE, 'source_url = "url:https://example.org/fictional/preprint-guidelines"', 'source_url = "TBD"')
    _, rep = cli.check(example)
    assert one(rep, "R-13")["status"] == "UNKNOWN"


def test_missing_pdf_is_unknown_when_page_limit_set(cli, example):
    edit(example, VENUE, 'pages_total    = "none"', "pages_total    = 10")
    (example / "paper/main.pdf").unlink()
    _, rep = cli.check(example)
    assert "R-13.no_pdf" in codes(one(rep, "R-13"))


def test_double_blind_needs_list_and_finds_names(cli, example):
    edit(example, VENUE, "double_blind = false", "double_blind = true")
    _, rep = cli.check(example)
    assert "R-13.anonymity_no_list" in codes(one(rep, "R-13"))
    edit(example, "steward.toml", 'dir  = "paper"', 'dir  = "paper"\nanonymity_file = ".steward/private/authors.txt"')
    append(example, ".steward/private/authors.txt", "Example Author\n")
    code, rep = cli.check(example)
    res = one(rep, "R-13")
    hits = [d for d in res["details"] if d["code"] == "R-13.anonymity"]
    assert {d["path"] for d in hits} >= {"paper/main.tex", "paper/main.pdf"} and all(d["term"] == "#1" for d in hits)
    assert "Example Author" not in json.dumps(rep)


def test_figure_format(cli, example):
    edit(example, VENUE, 'formats = ["pdf"]', 'formats = ["png"]')
    edit(example, "paper/displays.toml", 'output = "paper/figures/donors.tex"', 'output = "paper/figures/donors.pdf"')
    _, rep = cli.check(example)
    assert "R-13.figure_format" in codes(one(rep, "R-13"))


# ---------------------------------------------------------------- R-14
def test_missing_entry_fails(cli, example):
    edit(example, TEX, "\\citep{exampleC2024}", "\\citep{exampleC2024,ghost2023}")
    code, rep = cli.check(example)
    res = one(rep, "R-14")
    assert res["status"] == "FAIL" and {"code": "R-14.missing_entry", "path": TEX, "value": "ghost2023"} == {
        k: v for k, v in next(d for d in res["details"] if d["code"] == "R-14.missing_entry").items() if k != "line"}


def test_duplicate_key_and_doi_and_malformed(cli, example):
    append(example, BIB, "\n@misc{exampleA2025, title={dup}}\n@misc{d1, doi={10.5555/abc}}\n@misc{d2, doi={https://doi.org/10.5555/ABC}}\n"
                         "@misc{bad, doi={11.x/y}}\n")
    _, rep = cli.check(example)
    c = codes(one(rep, "R-14"))
    assert {"R-14.duplicate_key", "R-14.duplicate_doi", "R-14.malformed_identifier"} <= c


def test_unused_and_no_identifier_listed_not_failing(cli, example):
    append(example, BIB, "\n@book{lonely, title={Uncited book}}\n")
    _, rep = cli.check(example)
    res = one(rep, "R-14")
    assert res["status"] == "PASS" and {"code": "R-14.unused", "value": "lonely"} in res["details"]
    assert any(d["code"] == "R-14.no_identifier" and d["value"] == "lonely" for d in res["details"])
    assert "existence not verified" in res["reason"]


def test_unbalanced_bib_fails(cli, example):
    append(example, BIB, "\n@article{broken, title={no end}\n")
    _, rep = cli.check(example)
    assert "R-14.parse" in codes(one(rep, "R-14"))


# ---------------------------------------------------------------- manifest
def test_submission_manifest_lists_files_with_hashes(cli, example, tmp_path):
    out = tmp_path / "m.json"
    code, msg, _ = cli("paper", "manifest", "--repo", example, "--output", out)
    doc = json.loads(out.read_text())
    paths = {f["path"] for f in doc["files"]}
    assert code == 0 and {"paper/main.tex", "paper/main.pdf", "paper/refs.bib", "paper/values.tex",
                          "paper/displays.lock", "paper/tables/splits.tex"} <= paths
    assert all(len(f["sha256"]) == 64 for f in doc["files"])
