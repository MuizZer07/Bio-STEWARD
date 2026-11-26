"""0.18.0 research records: study records (R-75), research-direction records (R-76), citation verification (R-77),
LLM-evaluation hygiene (R-78), dispatch briefs, runs compared and charted, and the project-site pages."""

import json

import pytest

from conftest import codes, results
from test_v0120_features import gsh, xproj  # noqa: F401


def _cfg(x, text):
    with open(x / "steward.toml", "a") as f:
        f.write(text)


def _commit(x, msg="x"):
    gsh(x, "git", "add", "-A")
    gsh(x, "git", "commit", "-qm", msg)


def _by(rep, rule):
    return {r["subject"]: r for r in results(rep, rule)}


# ---------------------------------------------------------------- study records (R-75)
def _study(x, sid, inputs, extra=""):
    files = ", ".join(f'{{ path = "{p}" }}' for p in inputs)
    (x / "development/studies").mkdir(parents=True, exist_ok=True)
    (x / f"development/studies/{sid}.toml").write_text(f'''schema = "steward.study/1"
id = "{sid}"
title = "Study {sid}"
kind = "reanalysis"
{extra}
[[inputs]]
id = "GSE1"
source = "GEO"
accession = "GSE1"
retrieved = 2026-11-20
files = [{files}]

[references]
genome = "GRCh38"
annotation = "GENCODE 44"
''')


def test_a_study_is_fingerprinted_then_checked_and_a_change_makes_it_and_its_dependants_stale(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("gene\tlogfc\nA\t1.0\n")
    code, out, err = cli("study", "new", "s1", "--title", "First")
    assert code == 0 and (xproj / "development/studies/s1.toml").is_file(), err
    _study(xproj, "s1", ["data/a.tsv"])
    _study(xproj, "s2", ["data/a.tsv"], 'depends_on = ["s1"]\n')
    _, rep = cli.check(xproj)
    r = _by(rep, "R-75")
    assert r["development/studies/s1.toml"]["status"] == "INCOMPLETE" and "R-75.unfingerprinted" in codes(r["development/studies/s1.toml"])
    for s in ("s1", "s2"):
        code, out, _ = cli("study", "fingerprint", s, "--write")
        assert code == 0 and "unrecorded" in out
    _, rep = cli.check(xproj)
    r = _by(rep, "R-75")
    assert r["development/studies/s1.toml"]["status"] == "PASS"
    assert "R-75.duplicate_input" in codes(r["development/studies/s1.toml"])  # the same input in two studies
    (xproj / "data/a.tsv").write_text("gene\tlogfc\nA\t2.0\n")
    _, rep = cli.check(xproj)
    r = _by(rep, "R-75")
    assert r["development/studies/s1.toml"]["status"] == "FAIL" and "R-75.file_changed" in codes(r["development/studies/s1.toml"])
    assert "R-75.file_changed" in codes(r["development/studies/s2.toml"])
    code, out, _ = cli("study", "fingerprint", "s1", "--write")  # a changed digest is never overwritten
    assert code == 65 and "CHANGED" in out


def test_a_dependency_change_is_stale_and_names_the_citing_papers(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    (xproj / "data/b.tsv").write_text("b\n")
    _study(xproj, "base", ["data/a.tsv"])
    _study(xproj, "derived", ["data/b.tsv"], 'depends_on = ["base"]\n')
    for s in ("base", "derived"):
        cli("study", "fingerprint", s, "--write")
    (xproj / "data/a.tsv").write_text("changed\n")
    _, rep = cli.check(xproj)
    d = _by(rep, "R-75")["development/studies/derived.toml"]
    assert d["status"] == "INCOMPLETE" and "R-75.stale_dependency" in codes(d)


def test_unknown_papers_dependencies_and_inconsistent_references(cli, xproj):
    _cfg(xproj, '\n[studies]\nconsistent = ["genome"]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    _study(xproj, "s1", ["data/a.tsv"], 'papers = ["nope"]\ndepends_on = ["ghost"]\n')
    _study(xproj, "s2", ["data/a.tsv"])
    t = (xproj / "development/studies/s2.toml").read_text().replace('genome = "GRCh38"', 'genome = "GRCh37"')
    (xproj / "development/studies/s2.toml").write_text(t)
    _, rep = cli.check(xproj)
    r = _by(rep, "R-75")
    c1 = codes(r["development/studies/s1.toml"])
    assert {"R-75.unknown_paper", "R-75.unknown_dependency", "R-75.inconsistent_references"} <= c1


def test_a_frozen_study_must_be_fingerprinted_and_an_invalid_record_fails(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    _study(xproj, "s1", ["data/a.tsv"], 'status = "frozen"\n')
    (xproj / "development/studies/bad.toml").write_text('schema = "steward.study/1"\nid = "other"\ntitle = "x"\n')
    _, rep = cli.check(xproj)
    r = _by(rep, "R-75")
    assert r["development/studies/s1.toml"]["status"] == "FAIL"
    assert r["development/studies/bad.toml"]["status"] == "FAIL"


def test_study_list_show_and_the_site_page(cli, xproj):
    _cfg(xproj, '\n[studies]\n\n[docs]\npublish = ["overview", "studies"]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    _study(xproj, "s1", ["data/a.tsv"])
    cli("study", "fingerprint", "s1", "--write")
    _, out, _ = cli("study", "list", "--json")
    assert json.loads(out)["studies"][0] == {"id": "s1", "title": "Study s1", "kind": "reanalysis", "status": "active",
                                             "check": "PASS", "inputs": 1, "papers": []}
    _, out, _ = cli("study", "show", "s1")
    assert "### Study s1" in out and "GRCh38" in out and "✅" in out
    from steward import docsite
    from steward.models import load_config
    pages = docsite.build_pages(xproj, load_config(xproj))
    assert "### Study s1" in pages["studies.md"]


# ---------------------------------------------------------------- research-direction records (R-76)
@pytest.mark.parametrize("kind", ["review", "novelty", "gaps", "dead-end"])
def test_every_research_template_is_a_valid_record(cli, xproj, kind):
    _cfg(xproj, '\n[research]\n')
    code, _, err = cli("research", "new", kind, f"r-{kind}", "--title", f"A {kind}")
    assert code == 0, err
    _, rep = cli.check(xproj)
    r = _by(rep, "R-76")[f"development/research/r-{kind}.toml"]
    assert r["status"] in ("PASS", "INCOMPLETE") and "R-76.invalid" not in codes(r)


def test_research_records_report_what_needs_attention(cli, xproj):
    _cfg(xproj, '\n[research]\nstale_days = 30\n')
    d = xproj / "development/research"
    d.mkdir(parents=True)
    (d / "old.toml").write_text('''schema = "steward.research/1"
id = "old"
title = "An old review"
kind = "review"
date = 2026-01-01
[review]
question = "q"
searched = 2026-01-01
[[review.sources]]
id = "doi:10.1/x"
title = "t"
''')
    (d / "nov.toml").write_text('''schema = "steward.research/1"
id = "nov"
title = "Novelty"
kind = "novelty"
date = 2026-11-24
[[contributions]]
claim = "c"
''')
    (d / "dead.toml").write_text('''schema = "steward.research/1"
id = "dead"
title = "Dead end"
kind = "dead-end"
date = 2026-11-24
[dead_end]
results = ["run-1"]
''')
    (d / "bad.toml").write_text('schema = "steward.research/1"\nid = "bad"\ntitle = "x"\nkind = "gaps"\ndate = 2026-11-24\n')
    _, rep = cli.check(xproj)
    r = _by(rep, "R-76")
    assert "R-76.stale_review" in codes(r["development/research/old.toml"])
    assert {"R-76.no_nearest", "R-76.no_difference"} <= codes(r["development/research/nov.toml"])
    assert "R-76.undecided_dead_end" in codes(r["development/research/dead.toml"])
    assert r["development/research/bad.toml"]["status"] == "FAIL"
    from steward.models import ADVISORY
    assert "R-76" in ADVISORY  # it never blocks the default gate
    _, out, _ = cli("research", "list")
    assert "dead-end" in out and "no decision yet" in out


# ---------------------------------------------------------------- citation verification (R-77)
def _cite_setup(example):
    t = (example / "paper/main.tex").read_text().replace("\\citep{exampleA2025}", "\\citep{exampleA2025,realA2020}", 1)
    (example / "paper/main.tex").write_text(t)
    with open(example / "paper/refs.bib", "a") as f:
        f.write("\n@article{realA2020,\n  title = {A Study of Things},\n  journal = {J},\n  year = {2020},\n"
                "  doi = {10.1234/abc.5}\n}\n")
    t = (example / "steward.toml").read_text().replace('main = "main.tex"', 'main = "main.tex"\ncitations = "citations.toml"', 1)
    (example / "steward.toml").write_text(t)


def test_R77_citations_need_a_record_and_the_recorded_title_must_match(cli, example):
    _cite_setup(example)
    _, rep = cli.check(example, "paper")
    r = results(rep, "R-77")[0]
    assert r["status"] == "INCOMPLETE" and "R-77.no_record" in codes(r)
    (example / "paper/citations.toml").write_text('schema = "steward.citations/1"\n[[citation]]\nkey = "realA2020"\n'
                                                  'id = "doi:10.1234/abc.5"\ntitle = "A study of things"\nchecked = 2026-11-24\n')
    _, rep = cli.check(example, "paper")
    assert results(rep, "R-77")[0]["status"] == "PASS"
    (example / "paper/citations.toml").write_text('schema = "steward.citations/1"\n[[citation]]\nkey = "realA2020"\n'
                                                  'id = "doi:10.1234/abc.5"\ntitle = "Something else entirely"\nchecked = 2026-11-24\n')
    _, rep = cli.check(example, "paper")
    r = results(rep, "R-77")[0]
    assert r["status"] == "FAIL" and "R-77.title_mismatch" in codes(r)


def test_R77_fetch_records_resolved_titles(cli, example, monkeypatch):
    from steward import records as rc
    _cite_setup(example)
    monkeypatch.setattr(rc, "fetch_title", lambda cid, timeout=20: ("A Study of Things.", "crossref"))
    code, out, err = cli("paper", "citations", "main", "--repo", example, "--fetch")
    assert code == 0 and "1 recorded" in out, err
    _, rep = cli.check(example, "paper")
    assert results(rep, "R-77")[0]["status"] == "PASS"


def test_R77_is_not_applicable_without_a_citations_record(cli, example):
    _, rep = cli.check(example, "paper")
    assert results(rep, "R-77")[0]["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- LLM-evaluation hygiene (R-78)
def _llm(example, rows, models, prompts='prompts = "prompts"'):
    (example / "benchmarks/cases.csv").write_text("id,published,group,split\n" + "\n".join(rows) + "\n")
    with open(example / "benchmarks/expr-clf.contract.toml", "a") as f:
        f.write(f'\n[llm_eval]\ncases = "benchmarks/cases.csv"\n{prompts}\n' + "".join(
            f'[[llm_eval.models]]\nname = "{n}"\n' + (f"training_cutoff = {c}\n" if c else "") + f'role = "{r}"\n'
            for n, c, r in models))
    with open(example / "steward.toml", "a") as f:
        f.write('\n[[frozen]]\nname = "prompts"\nfiles = ["benchmarks/cases.csv"]\n')


def test_R78_a_clean_evaluation_passes_only_with_its_prompt_set_recorded(cli, example):
    _llm(example, ["c1,2026-03-01,GSE1,test", "c2,2026-04-01,GSE2,tune"], [("m", "2025-12-31", "candidate"),
                                                                           ("j", None, "judge")])
    _, rep = cli.check(example, "benchmark")
    r = results(rep, "R-78")[0]
    assert r["status"] == "INCOMPLETE" and "R-78.prompts_not_intact" in codes(r)  # AE11: a set name alone is not enough
    code, _, err = cli("frozen", "record", "prompts", "--repo", example)
    assert code == 0, err
    _, rep = cli.check(example, "benchmark")
    assert results(rep, "R-78")[0]["status"] == "PASS"


def test_R78_leakage_self_judging_contamination_and_prompts(cli, example):
    _llm(example, ["c1,2024-03-01,GSE1,test", "c2,2026-04-01,GSE1,tune", "c3,2026-05-01,GSE3,test"],
         [("m", "2025-12-31", "candidate"), ("m", None, "judge"), ("n", None, "candidate")], prompts='prompts = "nope"')
    _, rep = cli.check(example, "benchmark")
    r = results(rep, "R-78")[0]
    assert r["status"] == "FAIL"
    assert {"R-78.group_leak", "R-78.self_judging", "R-78.contamination_risk", "R-78.cutoff_unknown",
            "R-78.prompts_unknown"} <= codes(r)


def test_R78_not_applicable_without_llm_eval(cli, example):
    _, rep = cli.check(example, "benchmark")
    assert results(rep, "R-78")[0]["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- dispatch briefs
def test_a_task_becomes_a_brief_for_each_agent(cli, xproj):
    code, out, _ = cli("task", "template")
    assert code == 0 and "literature-review" in out
    code, tmpl, _ = cli("task", "template", "review")
    assert code == 0 and "## Acceptance criteria" in tmpl
    p = xproj / "development/tasks/T-1.md"
    p.parent.mkdir(parents=True)
    p.write_text(tmpl.replace("VERSION", "1.2.0").replace("- **ID:** … (unique, e.g. `ABC-042`)", "- **ID:** T-1"))
    for agent in ("codex", "gemini", "claude", "generic"):
        code, out, err = cli("task", "brief", p, "--for", agent)
        assert code == 0, err
        assert "## Goal" in out and "## Acceptance criteria" in out and "How to run:" in out and "(T-1)" in out
    _, out, _ = cli("task", "brief", p, "--for", "codex")
    assert "codex exec -s read-only" in out


def test_a_brief_with_a_private_term_is_refused(cli, xproj):
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/terms.txt").write_text("Zebrafinch\n")
    _cfg(xproj, '\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\n')
    p = xproj / "T.md"
    p.write_text("# Task: check the Zebrafinch pipeline\n\n## Goal\nx\n")
    code, _, err = cli("task", "brief", p)
    assert code == 65 and "reword" in err and "Zebrafinch" not in err


# ---------------------------------------------------------------- runs compared and charted
def test_runs_are_compared_and_charted(cli, xproj, tmp_path):
    import sys
    _cfg(xproj, '\n[run]\n\n[docs]\npublish = ["overview", "runs"]\n')
    for lab in ("model-a", "model-b"):
        code, _, err = cli("run", "--label", lab, "--", sys.executable, "-c", "print(1)")
        assert code == 0, err
    code, out, _ = cli("diff", "runs", "--json")
    rows = json.loads(out)["runs"]
    assert code == 0 and [r["label"] for r in rows] == ["model-a", "model-b"] and all(r["status"] == "finished" for r in rows)
    svg = tmp_path / "runs.svg"
    code, out, _ = cli("diff", "runs", "--label", "model-*", "--svg", svg)
    assert code == 0 and svg.read_text().startswith("<svg") and "model-a" in svg.read_text()
    from steward import docsite
    from steward.models import load_config
    page = docsite.build_pages(xproj, load_config(xproj))["runs.md"]
    assert "<svg" in page and "| Run |" in page


# ---------------------------------------------------------------- the implementer's own review
def test_a_study_title_is_text_on_the_site_never_markup(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    _study(xproj, "s1", ["data/a.tsv"])
    t = (xproj / "development/studies/s1.toml").read_text().replace('title = "Study s1"', 'title = "<img src=x onerror=1> | [x](javascript:1)"')
    (xproj / "development/studies/s1.toml").write_text(t)
    _, out, _ = cli("study", "show", "s1")
    assert "<img" not in out and "&lt;img" in out and "](javascript" not in out


def test_R78_a_cases_file_outside_the_repository_is_refused_by_the_contract(cli, example):
    with open(example / "benchmarks/expr-clf.contract.toml", "a") as f:
        f.write('\n[llm_eval]\ncases = "../outside.csv"\n[[llm_eval.models]]\nname = "m"\n')
    _, rep = cli.check(example, "benchmark")
    assert results(rep, "R-78")[0]["status"] == "NOT_APPLICABLE"  # an invalid contract is R-02's, never read here
    assert any(r["status"] == "FAIL" for r in results(rep, "R-02"))


# ================================================================ the final review (72ed51c): AE1 – AE15
def _studies_with_site(x, publish='["overview", "studies", "research"]'):
    _cfg(x, f'\n[studies]\n\n[research]\n\n[docs]\npublish = {publish}\n')
    (x / "data").mkdir(exist_ok=True)
    (x / "data/a.tsv").write_text("a\n")


def test_AE1_a_record_folder_behind_a_link_is_never_published_or_read(cli, xproj, tmp_path):
    from steward import docsite
    from steward.models import load_config
    _studies_with_site(xproj)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/studies").symlink_to(real)
    (real / "s1.toml").write_text('schema = "steward.study/1"\nid = "s1"\ntitle = "outside"\n')
    with pytest.raises(docsite.DocsError):
        docsite.build_pages(xproj, load_config(xproj))
    _, rep = cli.check(xproj)
    assert all("outside" not in json.dumps(r) for r in results(rep, "R-75"))


def test_AE2_a_protected_term_with_markup_characters_is_refused_before_rendering(cli, xproj):
    from steward import docsite
    from steward.models import load_config
    _studies_with_site(xproj)
    (xproj / "development/terms.txt").write_text("secret_cohort\nA&B\n")
    _cfg(xproj, '\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\n')
    _study(xproj, "s1", ["data/a.tsv"])
    t = (xproj / "development/studies/s1.toml").read_text().replace('title = "Study s1"', 'title = "the secret_cohort study"')
    (xproj / "development/studies/s1.toml").write_text(t)
    with pytest.raises(docsite.DocsError) as e:
        docsite.build_pages(xproj, load_config(xproj))
    assert "secret_cohort" not in str(e.value) and "products" in str(e.value)


@pytest.mark.parametrize("rows,code", [
    (["c1,2026-03-01,GSE1,tune"], "R-78.no_test_cases"),
    (["c1,2026-03-01,,test", "c2,2026-03-01,,tune"], "R-78.blank_group"),
    (["c1,2026-03-01,GSE1,test", "c1,2026-03-01,GSE2,tune"], "R-78.id_conflict"),
    (["c1,2026-03-01junk,GSE1,test"], "R-78.undated_cases"),
])
def test_AE3_unusable_llm_evidence_is_never_a_pass(cli, example, rows, code):
    _llm(example, rows, [("m", "2025-12-31", "candidate")])
    cli("frozen", "record", "prompts", "--repo", example)
    _, rep = cli.check(example, "benchmark")
    r = results(rep, "R-78")[0]
    assert r["status"] != "PASS" and code in codes(r), r


def test_AE3_no_candidates_and_duplicate_rows_count_once(cli, example):
    _llm(example, ["c1,2024-01-01,GSE1,test", "c1,2024-01-01,GSE1,test"], [("m", "2025-12-31", "candidate")])
    cli("frozen", "record", "prompts", "--repo", example)
    _, rep = cli.check(example, "benchmark")
    d = next(x for x in results(rep, "R-78")[0]["details"] if x["code"] == "R-78.contamination_risk")
    assert d["value"] == 1
    from steward import records as rc
    from steward.models import LlmEval
    ev = LlmEval(cases="c.csv", models=[{"name": "j", "role": "judge"}], prompts=None)
    st, _, det = rc.check_llm_eval(example, None, ev, lambda r: b"id,published,group,split\nc1,2026-01-01,G,test\n")
    assert st != "PASS" and "R-78.no_candidates" in {x["code"] for x in det}


def test_AE4_non_latin_titles_compare_by_their_words_and_empty_never_matches():
    from steward import records as rc
    assert rc.norm_title("细胞类型去卷积方法") != rc.norm_title("单细胞测序综述")
    assert rc.norm_title("Café {RNA}-seq") == rc.norm_title("cafe rna seq")
    assert rc.norm_title("") == "" and rc.norm_title("!!!") == ""


def test_AE4_a_mismatched_non_latin_title_fails(cli, example):
    _cite_setup(example)
    t = (example / "paper/refs.bib").read_text().replace("title = {A Study of Things}", "title = {细胞类型去卷积方法}")
    (example / "paper/refs.bib").write_text(t)
    (example / "paper/citations.toml").write_text('schema = "steward.citations/1"\n[[citation]]\nkey = "realA2020"\n'
                                                  'id = "doi:10.1234/abc.5"\ntitle = "单细胞测序综述"\nchecked = 2026-11-24\n')
    _, rep = cli.check(example, "paper")
    assert "R-77.title_mismatch" in codes(results(rep, "R-77")[0])


def test_AE5_record_paths_through_links_or_outside_are_refused(cli, xproj, tmp_path):
    from steward import records as rc
    (tmp_path / "out.txt").write_text("secret\n")
    (xproj / "linkdir").symlink_to(tmp_path)
    for rel in ("linkdir/out.txt", "../out.txt"):
        with pytest.raises(rc.RecordRefused):
            rc.read_rel(xproj, rel)
        assert rc._sha_file(xproj, rel) is None


def test_AE6_a_missing_plan_makes_dependants_and_papers_stale(cli, example):
    _cfg(example, '\n[studies]\n')
    (example / "development/plan.md").write_text("plan\n")
    d = example / "development/studies"
    d.mkdir(parents=True)
    for sid, extra in (("a", 'plan = "development/plan.md"\n'), ("b", 'depends_on = ["a"]\n'),
                       ("c", 'depends_on = ["b"]\npapers = ["main"]\n')):
        (d / f"{sid}.toml").write_text(f'schema = "steward.study/1"\nid = "{sid}"\ntitle = "{sid}"\n{extra}'
                                       '[[inputs]]\nid = "x"\nfiles = [{ path = "paper/refs.bib" }]\n')
        cli("study", "fingerprint", sid, "--write", "--repo", example)
    _, rep = cli.check(example, "studies")
    assert all(r["status"] == "PASS" for r in results(rep, "R-75"))
    (example / "development/plan.md").write_text("changed\n")
    _, rep = cli.check(example, "studies")
    r = _by(rep, "R-75")
    assert "R-75.file_changed" in codes(r["development/studies/a.toml"])
    assert "R-75.stale_paper" in codes(r["development/studies/c.toml"]) and r["development/studies/c.toml"]["status"] != "PASS"
    (example / "development/plan.md").unlink()
    _, rep = cli.check(example, "studies")
    assert "R-75.stale_dependency" in codes(_by(rep, "R-75")["development/studies/c.toml"])


def test_AE7_fingerprint_never_writes_into_a_comment_and_reports_what_it_could_not_write(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    for n in ("a", "b"):
        (xproj / f"data/{n}.tsv").write_text(n)
    d = xproj / "development/studies"
    d.mkdir(parents=True)
    (d / "s1.toml").write_text('schema = "steward.study/1"\nid = "s1"\ntitle = "s"\n'
                               '# files = [{ path = "data/a.tsv" }]\n'
                               '[[inputs]]\nid = "x"\nfiles = [{ path = "data/a.tsv" }]\n'
                               '[[inputs]]\nid = "y"\n[[inputs.files]]\npath = "data/b.tsv"\n')
    code, out, err = cli("study", "fingerprint", "s1", "--write")
    assert code == 65 and "data/b.tsv: not written" in err
    text = (d / "s1.toml").read_text()
    assert '# files = [{ path = "data/a.tsv" }]' in text  # the comment is untouched
    import tomllib
    doc = tomllib.loads(text)
    assert len(doc["inputs"][0]["files"][0]["sha256"]) == 64


def test_AE8_a_new_research_record_is_a_draft_until_filled(cli, xproj):
    _cfg(xproj, '\n[research]\n')
    for kind in ("review", "novelty", "gaps", "dead-end"):
        assert cli("research", "new", kind, f"r-{kind}", "--title", "t")[0] == 0
    _, rep = cli.check(xproj)
    for r in results(rep, "R-76"):
        assert r["status"] == "INCOMPLETE" and "R-76.draft" in codes(r)
    import tomllib
    doc = tomllib.loads((xproj / "development/research/r-dead-end.toml").read_text())
    assert "decision" not in doc["dead_end"]


def test_AE9_only_cited_entries_count_and_a_doi_url_is_an_identifier(cli, example):
    _cite_setup(example)
    with open(example / "paper/refs.bib", "a") as f:
        f.write("\n@article{unused1,\n  title = {Never cited},\n  doi = {10.9/unused}\n}\n"
                "\n@article{urlDoi,\n  title = {By URL},\n  url = {https://doi.org/10.5555/byurl}\n}\n")
    t = (example / "paper/main.tex").read_text().replace("realA2020}", "realA2020,urlDoi}", 1)
    (example / "paper/main.tex").write_text(t)
    (example / "paper/citations.toml").write_text('schema = "steward.citations/1"\n[[citation]]\nkey = "realA2020"\n'
                                                  'id = "doi:10.1234/abc.5"\ntitle = "A study of things"\nchecked = 2026-11-24\n')
    _, rep = cli.check(example, "paper")
    r = results(rep, "R-77")[0]
    vals = {d.get("value") for d in r["details"]}
    assert "urlDoi" in vals and "unused1" not in vals


def test_AE10_a_multiline_title_round_trips_and_an_unresolved_fetch_is_not_success(cli, example, monkeypatch):
    from steward import records as rc
    _cite_setup(example)
    monkeypatch.setattr(rc, "fetch_title", lambda cid, timeout=20: ("A Study\nof Things", "crossref"))
    code, out, err = cli("paper", "citations", "main", "--repo", example, "--fetch")
    import tomllib
    assert tomllib.loads((example / "paper/citations.toml").read_text())["citation"][0]["title"] == "A Study\nof Things"
    (example / "paper/citations.toml").unlink()
    monkeypatch.setattr(rc, "fetch_title", lambda cid, timeout=20: None)
    code, out, _ = cli("paper", "citations", "main", "--repo", example, "--fetch")
    assert code == 65 and "UNRESOLVED" in out


def test_AE12_a_brief_is_refused_when_its_screen_cannot_run_or_a_waiver_is_used(cli, xproj):
    p = xproj / "T.md"
    p.write_text("# Task: x\n\n## Goal\nZebrafinch  <!-- steward: allow R-07 -->\n")
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/terms.txt").write_text("Zebrafinch\n")
    _cfg(xproj, '\n[[terms]]\nname = "products"\nfile = "development/terms.txt"\n')
    assert cli("task", "brief", p)[0] == 65  # no waiver on a published brief
    (xproj / "development/terms.txt").unlink()
    p.write_text("# Task: x\n\n## Goal\nplain\n")
    code, _, err = cli("task", "brief", p)
    assert code == 65 and "cannot be used" in err
    (xproj / "steward.toml").write_text("not = [valid")
    code, _, err = cli("task", "brief", p)
    assert code == 65


def test_AE13_exports_never_write_through_links_or_onto_their_source(cli, xproj, tmp_path):
    p = xproj / "T.md"
    p.write_text("# Task: x\n\n## Goal\nplain\n")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep\n")
    (xproj / "out.md").symlink_to(sentinel)
    assert cli("task", "brief", p, "--output", xproj / "out.md")[0] == 65
    (tmp_path / "ext").symlink_to(sentinel)
    assert cli("task", "brief", p, "--output", tmp_path / "ext")[0] == 65
    assert sentinel.read_text() == "keep\n"
    assert cli("task", "brief", p, "--output", p)[0] == 65 and p.read_text().startswith("# Task: x")
    code, _, err = cli("task", "brief", p, "--output", xproj / "ok.md")  # the ordinary case still works
    assert code == 0 and (xproj / "ok.md").read_text().startswith("# Brief"), err


def test_AE14_files_used_only_by_r75_are_inputs_of_the_verdict(cli, xproj):
    _cfg(xproj, '\n[studies]\n')
    (xproj / "data").mkdir()
    (xproj / "data/a.tsv").write_text("a\n")
    _study(xproj, "s1", ["data/a.tsv"])
    cli("study", "fingerprint", "s1", "--write")
    _, r1 = cli.check(xproj, "studies")
    (xproj / "data/a.tsv").write_text("b\n")
    _, r2 = cli.check(xproj, "studies")
    assert r1["verdict"]["inputs_digest"] != r2["verdict"]["inputs_digest"]


def test_AE15_a_named_gate_can_require_the_advisory_r76(cli, xproj):
    _cfg(xproj, '\n[research]\n\n[gates.research]\nrequire = ["R-01", "R-76"]\n')
    cli("research", "new", "review", "r1", "--title", "t")
    code, _ = cli.check(xproj, gate="research")
    assert code != 0
    text = (__import__("pathlib").Path(__file__).parents[1] / "docs/guides/research-records.md").read_text()
    assert "the default gate never requires it (a gate you name can)" in text
