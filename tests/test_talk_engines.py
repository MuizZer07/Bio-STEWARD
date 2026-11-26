"""PresentationKit slices: PDF layout checks (any PDF), Quarto / reveal.js, PPTX, Keynote (exported PDF)."""

import shutil
import subprocess
import sys

import pytest

from steward import talk_sources as ts

from conftest import codes, edit, one

TALK = "talks/progress-update"
PLAN = f"{TALK}/talk.toml"


@pytest.fixture(autouse=True)
def isolated_prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config-home"))


# ---------------------------------------------------------------- PDF layout (Beamer)
def test_beamer_layout_measured(cli, example):
    _, rep = cli.check(example, "talk")
    res = one(rep, "R-28")
    mf = next(d for d in res["details"] if d["code"] == "R-28.min_font")
    assert res["status"] == "PASS" and mf["value"] >= 14


def test_small_font_detected(cli, example):
    with open(example / PLAN, "a") as f:
        f.write("\n[overrides]\ntypography.min_font_pt = 40\n")
    _, rep = cli.check(example)
    res = one(rep, "R-28")
    assert res["status"] == "INCOMPLETE" and "R-28.font_too_small" in codes(res)
    assert cli("check", "--repo", example, "--final")[0] == 1


# ---------------------------------------------------------------- Quarto / reveal.js
QMD = """---
title: "Progress update"
format: revealjs
---

## Why donor-level splits

- {{< var n_donors >}} donors, {{< var samples_per_donor >}} samples each.

## What exists

![](../../paper/figures/unregistered.png)

## Decisions we need

- Bootstrap resamples: keep 2000 or raise to 5000? <!-- literal-ok -->

## Next steps

- Train the baselines.
"""


@pytest.fixture
def quarto(example):
    edit(example, "steward.toml", 'main  = "slides.tex"', 'main  = "slides.qmd"')
    (example / TALK / "slides.tex").unlink()
    (example / TALK / "slides.pdf").unlink()  # the Beamer build; a Quarto deck has no PDF unless exported
    (example / TALK / "slides.qmd").write_text(QMD)
    return example


def test_quarto_values_variables_and_slide_count(cli, quarto):
    _, rep = cli.check(quarto, "talk")
    assert "R-24.variables_missing" in codes(one(rep, "R-24"))
    code, out, _ = cli("talk", "values", "--repo", quarto, "--write")
    assert code == 0 and (quarto / TALK / "_variables.yml").is_file()
    _, rep = cli.check(quarto, "talk")
    assert one(rep, "R-24")["status"] == "PASS"
    slides = next(d for d in one(rep, "R-28")["details"] if d["code"] == "R-28.slides")
    assert slides["value"] == 4
    assert "R-27.unregistered" in codes(one(rep, "R-27"))
    assert one(rep, "R-26")["status"] == "PASS"  # the decision appears in the Quarto text


def test_quarto_unknown_key_and_stale_variables(cli, quarto):
    cli("talk", "values", "--repo", quarto, "--write")
    with open(quarto / "benchmarks/splits/test.txt", "a") as f:
        f.write("S041_1\n")
    _, rep = cli.check(quarto, "talk")
    assert "R-24.variables_stale" in codes(one(rep, "R-24"))
    (quarto / TALK / "slides.qmd").write_text(QMD.replace("{{< var n_donors >}}", "{{< var n_donor >}}"))
    _, rep = cli.check(quarto, "talk")
    assert "R-24.unknown_key" in codes(one(rep, "R-24"))


# ---------------------------------------------------------------- PPTX
pptx_mod = pytest.importorskip("pptx")


def make_pptx(path, *, tiny=False, offslide=False, image=None):
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for title, body in (("Why donor-level splits", "Every donor in one split"),
                        ("Decisions we need", "Bootstrap resamples: keep 2000 or raise to 5000?"),
                        ("Next steps", "This proves everything")):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        tf = s.placeholders[1].text_frame
        tf.text = body
        tf.paragraphs[0].runs[0].font.size = Pt(8 if tiny else 24)
    if offslide:
        prs.slides[0].shapes.add_textbox(Inches(12.5), Inches(1), Inches(3), Inches(1)).text_frame.text = "cut off"
    if image:
        prs.slides[0].shapes.add_picture(str(image), Inches(1), Inches(4), Inches(2))
        prs.slides[0].notes_slide.notes_text_frame.text = "speaker note: preliminary"
    prs.save(path)


@pytest.fixture
def pptx(example):
    edit(example, "steward.toml", 'main  = "slides.tex"', 'main  = "slides.pptx"')
    (example / TALK / "slides.tex").unlink()
    return example


def test_pptx_facts_and_rules(cli, pptx):
    make_pptx(pptx / TALK / "slides.pptx")
    edit(pptx, PLAN, "Bootstrap resamples: keep 2000 or raise to 5000?", "Bootstrap resamples: keep 2000 or raise to 5000?")
    _, rep = cli.check(pptx, "talk")
    assert one(rep, "R-26")["status"] == "PASS"
    assert next(d for d in one(rep, "R-28")["details"] if d["code"] == "R-28.slides")["value"] == 3
    assert any(d["value"].lower() == "proves" for d in one(rep, "R-29")["details"])
    # "2000" looks like a year and is ignored by the heuristic; "5000" is listed
    assert {d["value"] for d in one(rep, "R-24")["details"] if d["code"] == "R-24.literal"} == {"5000"}


def test_pptx_small_font_and_offslide_shape(cli, pptx):
    make_pptx(pptx / TALK / "slides.pptx", tiny=True, offslide=True)
    _, rep = cli.check(pptx, "talk")
    c = codes(one(rep, "R-28"))
    assert {"R-28.font_too_small", "R-28.outside_slide"} <= c


def test_pptx_image_traced_by_hash(cli, pptx, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    png = tmp_path / "fig.png"
    Image.new("RGB", (40, 30), "white").save(png)
    make_pptx(pptx / TALK / "slides.pptx", image=png)
    _, rep = cli.check(pptx, "talk")
    assert "R-27.unregistered" in codes(one(rep, "R-27"))  # an image with no display behind it


# ---------------------------------------------------------------- Keynote (via exported PDF)
@pytest.fixture
def keynote(example):
    edit(example, "steward.toml", 'main  = "slides.tex"', 'main  = "slides.key"')
    (example / TALK / "slides.key").write_bytes(b"not a real keynote file")
    (example / TALK / "slides.tex").unlink()
    return example


def test_keynote_checked_through_exported_pdf(cli, keynote):
    _, rep = cli.check(keynote, "talk")  # the Beamer PDF from the example stands in for an export
    assert next(d for d in one(rep, "R-28")["details"] if d["code"] == "R-28.slides")["value"] == 6
    assert one(rep, "R-27")["status"] == "UNKNOWN"  # images in Keynote cannot be traced
    assert one(rep, "R-26")["status"] == "PASS"


def test_keynote_without_export_is_unknown(cli, keynote):
    (keynote / TALK / "slides.pdf").unlink()
    _, rep = cli.check(keynote, "talk")
    assert one(rep, "R-28")["status"] == "UNKNOWN"


def test_keynote_export_command(cli, keynote, monkeypatch):
    calls = []
    monkeypatch.setattr(ts, "export_keynote", lambda src, out: calls.append((src, out)))
    code, out, _ = cli("talk", "export", "--repo", keynote)
    assert code == 0 and calls and str(calls[0][1]).endswith("slides.pdf")


def test_export_refused_for_other_engines(cli, example):
    assert cli("talk", "export", "--repo", example)[0] == 64


def test_engine_detection():
    assert [ts.engine_of(x) for x in ("a.tex", "a.qmd", "a.md", "a.pptx", "a.key", "a.odp")] == \
        ["beamer", "quarto", "quarto", "pptx", "keynote", "unknown"]


# ---------------------------------------------------------------- red-team B6, B7
def _no_pdf_readers(monkeypatch):
    import builtins
    from steward import rules
    real_import = builtins.__import__
    monkeypatch.setattr(rules.shutil, "which", lambda name: None)
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **k: (_ for _ in ()).throw(ImportError(name)) if name == "pypdf" else real_import(name, *a, **k))


def test_B6_missing_pdf_reader_is_named_not_a_missing_pdf(cli, example, monkeypatch):
    _no_pdf_readers(monkeypatch)
    _, rep = cli.check(example, "talk")
    res = one(rep, "R-28")
    assert res["status"] == "UNKNOWN" and "R-28.pdf_reader_missing" in codes(res) and "R-28.no_pdf" not in codes(res)
    _, text, _ = cli("check", "--repo", example, "talk", "--summary")
    assert "install a PDF reader" in text


def test_B7_r28_reason_names_skipped_layout_checks(cli, example, monkeypatch):
    from steward import talk_sources
    monkeypatch.setattr(talk_sources, "pdf_layout", lambda path, min_font: None)
    _, rep = cli.check(example, "talk")
    res = one(rep, "R-28")
    assert res["status"] == "PASS" and "fonts and bounds not assessed" in res["reason"]


def test_B7_coverage_statement_reports_what_was_checked(cli, example):
    _, rep = cli.check(example)
    stmt = rep["verdict"]["coverage"]["statement"]
    assert "Artifact integrity: checked by" in stmt and "R-11" in stmt
    assert "Scientific validity" in stmt and "not assessed" in stmt


# ---------------------------------------------------------------- red-team round 3: D5
def _reader_installed():
    import importlib.util
    return bool(shutil.which("pdfinfo")) or importlib.util.find_spec("pypdf") is not None


@pytest.mark.skipif(not _reader_installed(), reason="needs a PDF reader (poppler or pypdf)")
def test_D5_damaged_pdf_is_not_reported_as_a_missing_reader(cli, example):
    (example / "talks/progress-update/slides.pdf").write_text("not a pdf\n")
    _, rep = cli.check(example, "talk")
    res = one(rep, "R-28")
    assert "R-28.pdf_unreadable" in codes(res) and "R-28.pdf_reader_missing" not in codes(res)
    assert res["status"] != "PASS"
