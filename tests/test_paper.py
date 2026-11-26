"""PaperKit v0.2.0: R-08 spec and venue, R-09 placeholders, R-12 build log, R-07 PDF scan, final mode, init --paper
(RELEASE_v0.2_SPEC §6)."""

import shutil

import json

import pytest

from steward import rules

from conftest import REPO, append, codes, edit, gate, one, results

SPEC = "paper/spec.toml"
VENUE = "paper/venue.toml"
TEX = "paper/main.tex"
LOG = "paper/main.log"


def r(rep, rule, subject):
    return next(x for x in results(rep, rule) if x["subject"] == subject)


# ---------------------------------------------------------------- example and N/A
def test_example_paper_passes_in_draft_and_final(cli, example):
    code, rep = cli.check(example)
    assert code == 0 and gate(rep)["eligible"]
    for rule in ("R-08", "R-09", "R-12"):
        assert all(x["status"] == "PASS" for x in results(rep, rule)), rule
    code, rep = cli("check", "--repo", example, "--final", "--summary")[:2]
    assert code == 0


def test_no_paper_configured_is_not_applicable(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    for rule in ("R-08", "R-09", "R-10", "R-11", "R-12", "R-13", "R-14", "R-15"):
        res = one(rep, rule)
        assert res["status"] == "NOT_APPLICABLE" and res["reason"] == "no paper configured"


def test_paper_table_requires_schema_02(cli, example):
    edit(example, "steward.toml", 'schema  = "steward.toml/0.2"', 'schema  = "steward.toml/0.1"')
    _, rep = cli.check(example)
    res = one(rep, "R-01")
    assert res["status"] == "FAIL" and any("requires schema steward.toml/0.2" in d.get("message", "") for d in res["details"])


def test_invalid_placeholder_regex_fails_config(cli, example):
    edit(example, "steward.toml", 'dir  = "paper"', "dir  = \"paper\"\nplaceholders = ['(unclosed']")
    _, rep = cli.check(example)
    assert one(rep, "R-01")["status"] == "FAIL"


def test_paper_path_outside_repository_fails_config(cli, example):
    edit(example, "steward.toml", 'dir  = "paper"', 'dir  = "../elsewhere"')
    _, rep = cli.check(example)
    assert "path_escapes_root" in codes(one(rep, "R-01"))


# ---------------------------------------------------------------- R-08
def test_R08_tbd_story_is_incomplete(cli, example):
    text = (example / SPEC).read_text()
    story = text.split("story  = ")[1].split("\n")[0]
    edit(example, SPEC, story, '"TBD"')
    code, rep = cli.check(example)
    assert r(rep, "R-08", SPEC)["status"] == "INCOMPLETE" and code == 2


def test_R08_bad_strength_fails(cli, example):
    edit(example, SPEC, 'strength = "explores"', 'strength = "proves"')
    _, rep = cli.check(example)
    assert r(rep, "R-08", SPEC)["status"] == "FAIL"


def test_R08_missing_spec_is_incomplete_and_missing_venue_not_applicable(cli, example):
    (example / SPEC).unlink()
    (example / VENUE).unlink()
    _, rep = cli.check(example)
    assert r(rep, "R-08", SPEC)["status"] == "INCOMPLETE"
    assert r(rep, "R-08", VENUE)["status"] == "NOT_APPLICABLE"


def test_R08_venue_without_source_is_unknown_and_bad_url_fails(cli, example):
    edit(example, VENUE, 'source_url = "url:https://example.org/fictional/preprint-guidelines"', 'source_url = "unknown"')
    _, rep = cli.check(example)
    assert r(rep, "R-08", VENUE)["status"] == "UNKNOWN"
    edit(example, VENUE, 'source_url = "unknown"', 'source_url = "example.org"')
    _, rep = cli.check(example)
    assert r(rep, "R-08", VENUE)["status"] == "FAIL"


def test_R08_malformed_toml(cli, example):
    append(example, SPEC, "\n[[broken\n")
    _, rep = cli.check(example)
    assert r(rep, "R-08", SPEC)["status"] == "FAIL"


# ---------------------------------------------------------------- R-09
def test_R09_marker_in_text_is_incomplete_in_draft_fail_in_final(cli, example):
    edit(example, TEX, "No results are reported at this stage.", "No results are reported at this stage. TODO: expand.")
    code, rep = cli.check(example)
    res = one(rep, "R-09")
    assert res["status"] == "INCOMPLETE" and code == 2
    assert {"code": "R-09.marker", "path": TEX, "value": "pattern #1"} == {k: v for k, v in res["details"][1].items() if k != "line"}
    code, _, _ = cli("check", "--repo", example, "--final", "--format", "json")
    assert code == 1


def test_R09_comment_ignored_in_draft_scanned_in_final(cli, example):
    edit(example, TEX, "\\section{Limitations}", "% TODO: reviewer asked for more here\n\\section{Limitations}")
    _, rep = cli.check(example)
    assert one(rep, "R-09")["status"] == "PASS"
    code, _, _ = cli("check", "--repo", example, "--final")
    assert code == 1
    edit(example, "steward.toml", 'mode = "draft"', 'mode = "final"')  # config mode, same effect
    _, rep = cli.check(example)
    assert one(rep, "R-09")["status"] == "FAIL"


def test_R09_escaped_percent_is_not_a_comment(cli, example):
    edit(example, TEX, "No results are reported at this stage.", "Coverage is 50\\% TODO.")
    _, rep = cli.check(example)
    assert one(rep, "R-09")["status"] == "INCOMPLETE"


def test_R09_custom_pattern(cli, example):
    edit(example, "steward.toml", 'dir  = "paper"', "dir  = \"paper\"\nplaceholders = ['\\\\pending\\{']")
    edit(example, TEX, "No results are reported at this stage.", "\\pending{results}")
    _, rep = cli.check(example)
    assert one(rep, "R-09")["status"] == "INCOMPLETE"


def test_R09_docx_unreadable_without_pandoc_is_unknown(cli, example, monkeypatch):
    edit(example, "steward.toml", 'main = "main.tex"', 'main = "draft.docx"')
    (example / "paper/draft.docx").write_bytes(b"PK\x03\x04 not really a docx")
    monkeypatch.setattr(rules, "_docx_text", lambda path: None)
    _, rep = cli.check(example)
    res = one(rep, "R-09")
    assert res["status"] == "UNKNOWN" and "R-09.docx_unreadable" in codes(res)
    assert one(rep, "R-12")["status"] == "NOT_APPLICABLE"  # build-log checks are LaTeX-only


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_R09_docx_scanned_with_pandoc(cli, example, tmp_path):
    import subprocess

    md = tmp_path / "d.md"
    md.write_text("# Draft\n\nResults: TODO\n")
    subprocess.run(["pandoc", str(md), "-o", str(example / "paper/draft.docx")], check=True)
    edit(example, "steward.toml", 'main = "main.tex"', 'main = "draft.docx"')
    _, rep = cli.check(example)
    assert one(rep, "R-09")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- R-12
def test_R12_undefined_citation_fails(cli, example):
    append(example, LOG, "\nLaTeX Warning: Citation `missing2025' on page 1 undefined on input line 30.\n")
    code, rep = cli.check(example)
    res = one(rep, "R-12")
    assert res["status"] == "FAIL" and "R-12.undefined_citation" in codes(res) and code == 1
    assert any(d.get("value") == "missing2025" for d in res["details"])


def test_R12_undefined_reference_and_error_fail(cli, example):
    append(example, LOG, "\nLaTeX Warning: Reference `fig:x' on page 2 undefined on input line 9.\n! Undefined control sequence.\n")
    _, rep = cli.check(example)
    assert {"R-12.undefined_reference", "R-12.latex_error"} <= codes(one(rep, "R-12"))


def test_R12_rerun_is_incomplete(cli, example):
    append(example, LOG, "\nLaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.\n")
    _, rep = cli.check(example)
    assert one(rep, "R-12")["status"] == "INCOMPLETE"


def test_R12_overfull_listed_in_draft_blocks_in_final(cli, example):
    append(example, LOG, "\nOverfull \\hbox (12.3pt too wide) in paragraph at lines 20--22\n")
    _, rep = cli.check(example)
    res = one(rep, "R-12")
    assert res["status"] == "PASS" and "R-12.overfull" in codes(res)
    code, _, _ = cli("check", "--repo", example, "--final")
    assert code == 2


def test_R12_missing_log_is_unknown(cli, example):
    (example / LOG).unlink()
    code, rep = cli.check(example)
    assert one(rep, "R-12")["status"] == "UNKNOWN" and code == 3


def test_R12_markdown_main_not_applicable(cli, example):
    edit(example, "steward.toml", 'main = "main.tex"', 'main = "main.md"')
    (example / "paper/main.md").write_text("# Paper\n")
    _, rep = cli.check(example)
    assert one(rep, "R-12")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- R-07 v2: PDFs
PRIVACY = '\n[privacy]\ndenylist_file = ".steward/private/denylist.txt"\n'


def test_R07_term_inside_figure_pdf_fails_without_leaking(cli, example):
    import json

    append(example, "steward.toml", PRIVACY)
    append(example, ".steward/private/denylist.txt", "projectnightjar\n")
    shutil.copy(REPO / "tests/fixtures/figure_with_term.pdf", example / "paper/fig1.pdf")
    _, rep = cli.check(example)
    res = one(rep, "R-07")
    assert res["status"] == "FAIL"
    assert {"code": "R-07.hit", "path": "paper/fig1.pdf", "page": 1, "term": "denylist:1"} in res["details"]  # FB-2
    assert "nightjar" not in json.dumps(rep).lower()


def test_R07_unreadable_pdf_is_unknown(cli, example, monkeypatch):
    append(example, "steward.toml", PRIVACY)
    append(example, ".steward/private/denylist.txt", "projectnightjar\n")
    monkeypatch.setattr(rules, "pdf_text", lambda path: None)
    code, rep = cli.check(example)
    res = one(rep, "R-07")
    assert res["status"] == "UNKNOWN" and {"code": "R-07.pdf_unreadable", "path": "paper/main.pdf"} in res["details"]
    assert code == 3


# ---------------------------------------------------------------- init --paper and areas
def test_init_paper_creates_kit_and_config(cli, tmp_path):
    code, _, _ = cli("init", "--repo", tmp_path, "--paper")
    assert code == 0
    for f in ("paper/spec.toml", "paper/venue.toml", "paper/main.tex", "paper/refs.bib"):
        assert (tmp_path / f).is_file(), f
    cfg = (tmp_path / "steward.toml").read_text()
    assert 'schema  = "steward.toml/0.2"' in cfg and "[paper.main]" in cfg
    _, rep = cli.check(tmp_path)
    assert r(rep, "R-08", "paper/spec.toml")["status"] == "INCOMPLETE"  # template TBDs, not schema failures
    assert one(rep, "R-09")["status"] == "INCOMPLETE"                   # skeleton TODOs
    assert one(rep, "R-12")["status"] == "UNKNOWN"                      # not built yet
    assert rep["verdict"]["summary"]["counts"]["FAIL"] == 0


def test_init_paper_on_existing_config_appends_its_table(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    before = (tmp_path / "steward.toml").read_text()
    code, out, _ = cli("init", "--repo", tmp_path, "--paper", "review")  # 0.20.1 (STW-033): appended, not printed
    after = (tmp_path / "steward.toml").read_text()
    assert code == 0 and "append         steward.toml  [paper.review]" in out
    assert after.startswith(before.rstrip("\n")) and after.count("[paper.review]") == 1
    assert (tmp_path / "papers/review/main.tex").is_file()
    assert cli("init", "--repo", tmp_path, "--paper", "Bad Name")[0] == 64


def test_paper_area_is_partial(cli, example):
    code, rep = cli.check(example, "paper")
    assert not gate(rep)["evaluated"] and {x["rule"] for x in rep["verdict"]["results"]} == {"R-01", "R-08", "R-09", "R-10", "R-11", "R-12", "R-13", "R-14", "R-15", "R-77", "R-85"}


# ---------------------------------------------------------------- red-team round 4: E4
def test_E4_an_empty_display_manifest_earns_no_integrity_coverage(cli, tmp_path):
    cli("init", "--repo", tmp_path, "--paper")
    (tmp_path / "paper/displays.toml").write_text('schema = "steward.displays/0.1"\n[displays]\n')
    _, rep = cli.check(tmp_path, "paper")
    res = one(rep, "R-11")
    assert res["status"] == "PASS" and "R-11.nothing_to_check" in codes(res)
    assert "R-11" not in rep["verdict"]["coverage"]["statement"]


def test_E4_a_checked_display_keeps_its_coverage(cli, example):
    _, rep = cli.check(example, "paper")
    assert "R-11.nothing_to_check" not in codes(one(rep, "R-11"))
    assert "R-11" in rep["verdict"]["coverage"]["statement"]


# ---------------------------------------------------------------- red-team round 5: F2
def test_F2_r11_earns_coverage_only_when_fingerprints_were_compared(cli, example):
    (example / "paper/displays.lock").unlink()
    _, rep = cli.check(example, "paper")
    assert "R-11.no_lock" in codes(one(rep, "R-11"))
    assert "R-11" not in rep["verdict"]["coverage"]["statement"]


def test_F2_a_stale_lock_was_compared_and_keeps_its_coverage(cli, example):
    append(example, "benchmarks/splits/test.txt", "S041_1\n")
    _, rep = cli.check(example, "paper")
    assert one(rep, "R-11")["status"] == "FAIL" and "R-11" in rep["verdict"]["coverage"]["statement"]


# ---------------------------------------------------------------- red-team round 6: G4
@pytest.mark.parametrize("entry", [{}, [], {"script": {}, "inputs": {}, "params": {}, "output": {}}])
def test_G4_a_lock_entry_without_fingerprints_is_invalid_and_earns_no_coverage(cli, example, entry):
    lock = example / "paper/displays.lock"
    doc = json.loads(lock.read_text())
    doc["displays"] = {name: entry for name in doc["displays"]}
    lock.write_text(json.dumps(doc))
    _, rep = cli.check(example, "paper")
    res = one(rep, "R-11")
    assert res["status"] == "FAIL" and "R-11.lock_entry_invalid" in codes(res)
    assert "R-11.fingerprints_compared" not in codes(res) and "R-11" not in rep["verdict"]["coverage"]["statement"]


# ---------------------------------------------------------------- 0.6.3: known issue H5
@pytest.mark.parametrize("digest", ["x", " ", "abc", "g" * 64, "A" * 64])
def test_H5_lock_digests_must_be_sha256(cli, example, digest):
    lock = example / "paper/displays.lock"
    doc = json.loads(lock.read_text())
    for entry in doc["displays"].values():
        for part in ("script", "inputs", "output"):
            entry[part] = {k: digest for k in entry[part]}
    lock.write_text(json.dumps(doc))
    _, rep = cli.check(example, "paper")
    res = one(rep, "R-11")
    assert "R-11.lock_entry_invalid" in codes(res) and "R-11.fingerprints_compared" not in codes(res)
    assert "R-11" not in rep["verdict"]["coverage"]["statement"]
