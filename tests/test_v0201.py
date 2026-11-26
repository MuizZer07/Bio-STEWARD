"""0.20.1: onboarding fixes from the Gemini stranger test (STW-033) and the waived 0.19.0 findings AM1 – AM4 (STW-037)."""

import io
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from conftest import results
from test_v0120_features import gsh, xproj  # noqa: F401
from test_v0190_publish import _dev

REPO = Path(__file__).parents[1]


def _fresh(tmp_path, name="p"):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


# ---------------------------------------------------------------- STW-033
def test_the_readme_states_the_current_version_and_rule_count():
    from steward import __version__
    from steward.rules import RULES
    text = (REPO / "README.md").read_text()
    assert f"deterministic%20rules-{len(RULES)}-" in text and f"Rules ({len(RULES)})" in text
    assert f"pre--release%20{__version__}" in text and f"latest tag `v{__version__}`" in text
    for r in ("R-83", "R-84", "R-85", "R-86", "R-79"):
        assert r in text.split("📐 Rules")[1].split("</details>")[0], r


def test_the_generated_values_file_names_the_real_command():
    from steward import values as v
    assert "--write" in v.emit({"a": "1"}, "tex") and "--emit" not in v.emit({"a": "1"}, "tex")


def test_json_with_output_prints_only_where_it_went(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, _ = cli("check", "--repo", d, "--format", "json", "--output", d / ".steward/r.json")
    assert out.startswith("wrote ") and out.count("\n") == 1 and "{" not in out
    assert json.loads((d / ".steward/r.json").read_text())["verdict"]


def test_init_for_paper_extends_an_existing_project(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, err = cli("init", "--repo", d, "--for", "paper")
    assert code == 0 and "append         steward.toml  [paper.main]" in out, err
    assert tomllib.loads((d / "steward.toml").read_text())["paper"]["main"]["dir"] == "paper"
    assert tomllib.loads((d / "paper/values.toml").read_text())["schema"] == "steward.values/0.1"
    assert "\\input{values}" in (d / "paper/main.tex").read_text()
    assert cli("paper", "values", "--write", "--repo", d)[0] == 0
    _, rep = cli.check(d, "paper")
    assert results(rep, "R-10")[0]["status"] != "NOT_APPLICABLE"
    cli("init", "--repo", d, "--paper")  # again: never a second table
    assert (d / "steward.toml").read_text().count("[paper.main]") == 1


def test_the_example_has_a_first_commit_so_its_undo_works(cli, tmp_path):
    x = tmp_path / "ex"
    assert cli("example", "biology", x)[0] == 0
    (x / "results/top_genes.tsv").write_text("broken\n")
    subprocess.run(["git", "checkout", "--", "."], cwd=x, check=True)
    assert (x / "results/top_genes.tsv").read_text() != "broken\n"


def _mangled(cli, tmp_path):
    x = tmp_path / "ex"
    cli("example", "biology", x)
    t = (x / "results/top_genes.tsv").read_text().split("\n")
    cols = t[1].split("\t")
    cols[1] = "7-Sep"
    t[1] = "\t".join(cols)
    (x / "results/top_genes.tsv").write_text("\n".join(t))
    return x


def test_the_summary_shows_where_and_what_under_each_failure(cli, tmp_path):
    x = _mangled(cli, tmp_path)
    _, out, _ = cli("check", "--repo", x, "--summary")
    lines = out.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith("FAIL R-83"))
    assert lines[i + 1].startswith("  - results/top_genes.tsv:2:2 '7-Sep' looks like a spreadsheet date"), lines[i + 1]


def test_check_rule_shows_one_rule_with_every_detail(cli, tmp_path):
    x = _mangled(cli, tmp_path)
    code, out, _ = cli("check", "--repo", x, "--rule", "r-83")
    assert code != 0 and out.splitlines()[0].startswith("FAIL R-83") and "7-Sep" in out
    assert "R-75" not in out and out.rstrip().endswith("steward explain R-83")
    assert cli("check", "--repo", x, "--rule", "R-999")[0] == 64


def test_report_rule_is_focused_by_default(cli, tmp_path):
    x = _mangled(cli, tmp_path)
    cli("check", "--repo", x, "--format", "json", "--output", x / ".steward/r.json")
    _, out, _ = cli("report", x / ".steward/r.json", "--rule", "R-83")
    assert out.startswith("FAIL R-83") and "not configured" not in out
    _, md, _ = cli("report", x / ".steward/r.json", "--rule", "R-83", "--format", "md")
    assert md.startswith("#")  # an explicit format still gives the full rendering


def test_no_study_yet_suggests_creating_one(cli, xproj):
    with open(xproj / "steward.toml", "a") as f:
        f.write("\n[studies]\n")
    _, out, _ = cli("check", "studies", "--summary")
    assert "next: steward study new ID" in out


def test_the_benchmark_template_shows_how_to_declare_leakage():
    text = (REPO / "templates/benchmark.contract.toml").read_text()
    assert "# [leakage]" in text and all(k in text for k in ("near_duplicate", "test_tuning", "undeclared_groups"))


# ---------------------------------------------------------------- STW-037: AM1 – AM4
@pytest.mark.parametrize("text", ["﻿-rrequirements.in\n", "--find-links . -r requirements.in\n",
                                  "numpy==2.1.0 --hash=sha256:00\n--index-url https://example.org -c c.txt\n"])
def test_AM1_an_include_anywhere_is_never_an_empty_inventory(text):
    from steward import licence as li
    with pytest.raises(ValueError):
        li.lock_packages(text, "requirements.txt")
    assert li.lock_packages("﻿numpy==2.1.0  # pinned\n", "requirements.txt") == [("numpy", "2.1.0")]


def test_AM2_the_missing_tag_is_not_sent_when_the_branch_moved(cli, xproj, tmp_path, monkeypatch):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0")[0] == 0
    stage = xproj / ".steward/publish"
    subprocess.run(["git", "push", "-q", "origin", "v1.0.0^{commit}:refs/heads/main"], cwd=stage, check=True)
    from steward import publish as pb
    real = pb._git

    def fake(cwd, *args, **kw):  # a newer release lands on the public branch just before the push
        if args[:3] == ("push", "-q", "--atomic"):
            other = tmp_path / "other"
            subprocess.run(["git", "clone", "-q", str(pub), str(other)], check=True)
            subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-q",
                            "--allow-empty", "-m", "v3"], cwd=other, check=True)
            subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=other, check=True)
        return real(cwd, *args, **kw)
    monkeypatch.setattr(pb, "_git", fake)
    code, _, _ = cli("release", "publish", "v1.0.0", "--push")
    assert code != 0
    assert "v1.0.0" not in subprocess.run(["git", "tag", "--list"], cwd=pub, capture_output=True, text=True).stdout


def test_AM3_a_public_tag_is_judged_by_its_whole_name(cli, xproj, tmp_path):
    pub = _dev(xproj, tmp_path)
    subprocess.run(["git", "init", "-q", "--bare", str(pub)], check=True)
    other = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@example.org", "commit", "-q", "--allow-empty",
                    "-m", "seed"], cwd=other, check=True)
    subprocess.run(["git", "tag", "varchive/refs/tags/v0.1.0"], cwd=other, check=True)
    subprocess.run(["git", "push", "-q", str(pub), "refs/tags/varchive/refs/tags/v0.1.0"], cwd=other, check=True)
    code, _, err = cli("release", "publish", "v1.0.0", "--push")
    assert code == 65 and "not a semantic version" in err and "varchive" in err


def test_AM4_the_recovery_command_quotes_the_staging_path():
    import shlex
    stage = "/tmp/Release Stage"
    assert shlex.split(f"git -C {shlex.quote(stage)} update-ref x y")[2] == stage
    src = (REPO / "src/steward/publish.py").read_text()
    assert re.search(r"shlex\.quote\(str\(stage\)\)", src)


# ---------------------------------------------------------------- STW-032 (Gemini review of 0.20.0): AN1 – AN11
from test_v0200_biology import MATRIX, SHEET, _archive, _samples, _study, _study_cfg  # noqa: E402


def _r75(cli, x):
    _, rep = cli.check(x, "studies")
    return results(rep, "R-75")[0]


def test_AN1_a_hard_linked_part_or_target_is_never_written_through(cli, xproj, monkeypatch, tmp_path):
    import os
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    d = xproj / "data/raw/1234567"
    d.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("precious\n")
    os.link(outside, d / ".m.txt.part")
    _archive(monkeypatch, {"m.txt": MATRIX})
    code, _, err = cli("data", "fetch", "Zenodo:1234567", "--study", "s1")
    assert code == 65 and "not a plain file" in err and outside.read_text() == "precious\n"
    (d / ".m.txt.part").unlink()
    (d / "m.txt").mkdir()
    code, _, err = cli("data", "fetch", "Zenodo:1234567", "--study", "s1")
    assert code == 65 and "Traceback" not in err


def test_AN2_every_sample_finding_is_listed(cli, xproj):
    rows = "".join(f"S{i}\tHomo sapiens\tbrain\tbad\tb1\n" for i in range(60))
    _samples(xproj, sheet="sample\torganism\ttissue\tcondition\tbatch\n" + rows,
             matrix=b"ID_REF\t" + "\t".join(f"S{i}" for i in range(60)).encode() + b"\n")
    r = _r75(cli, xproj)
    assert sum(d["code"] == "R-75.sample_value_not_allowed" for d in r["details"]) == 60
    assert not any(d["code"] == "R-75.samples_more" for d in r["details"])


def test_AN3_an_unreadable_matrix_keeps_the_sheet_findings(cli, xproj, tmp_path):
    _samples(xproj, sheet=SHEET.replace("\tcase\t", "\tCase\t"))
    (xproj / "data/m.txt").unlink()
    r = _r75(cli, xproj)
    codes_ = [d["code"] for d in r["details"]]
    assert "R-75.sample_value_not_allowed" in codes_ and "R-75.matrix_missing" in codes_
    (tmp_path / "real.txt").write_bytes(MATRIX)
    (xproj / "data/m.txt").symlink_to(tmp_path / "real.txt")
    r = _r75(cli, xproj)
    hit = [d for d in r["details"] if d["code"] == "R-75.matrix_refused"]
    assert hit and hit[0]["path"] == "data/m.txt" and "R-75.sample_value_not_allowed" in [d["code"] for d in r["details"]]


def test_AN4_a_new_input_never_takes_another_inputs_references(cli, xproj):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/peaks.bed").write_text("chr1\t1\t2\n")
    (xproj / "data/m.txt").write_text("x\n")
    _study(xproj, '[references]\ngenome = "GRCh38"\n', '[inputs.references]\ngenome = "GRCh37"\n')
    assert cli("study", "add-input", "s1", "--source", "GEO", "--accession", "GSE9", "--file", "data/m.txt")[0] == 0
    st = tomllib.loads((xproj / "development/studies/s1.toml").read_text())
    by = {i["id"]: i for i in st["inputs"]}
    assert by["peaks"]["references"]["genome"] == "GRCh37" and "references" not in by["GSE9"]


def test_AN5_a_foreign_or_other_ledger_is_refused(tmp_path):
    from types import SimpleNamespace

    from steward import compare as cm
    from steward.ledger import Ledger
    for name, rid in (("runs", "someone-else"), ("exchange", "mine")):
        path = tmp_path / f"{name}-{rid}.jsonl"
        Ledger(path, name, rid).append("note", {"text": "x"})
        cfg = SimpleNamespace(run=SimpleNamespace(ledger=path.name), steward=SimpleNamespace(repo_id="mine"))
        with pytest.raises(cm.CompareError):
            cm._runs(tmp_path, cfg, lambda rel, p=path: p.read_bytes())


def test_AN6_one_stale_comparison_of_the_latest_pair_is_not_current():
    src = (REPO / "src/steward/compare.py").read_text()
    assert "current = current and not details" in src


def test_AN7_sam_bgzf_and_late_names_are_read():
    import gzip

    from steward import biodata as bd
    sam = b"@HD\tVN:1.6\nread1\t0\t1\t100\t60\t10M\t*\t0\t0\tACGT\t*\n"
    assert bd.chromosome_naming(sam, column=2)[0] == "ensembl"
    bgz = gzip.compress(b"##fileformat=VCFv4.2\n#CHROM\tPOS\n") + gzip.compress(b"1\t100\t.\tA\tG\n")
    assert bd.chromosome_naming(bgz)[0] == "ensembl"
    late = ("chr1\t1\t2\n" * 2001 + "2\t1\t2\n").encode()
    assert bd.chromosome_naming(late)[0] == "mixed"


def test_AN8_archive_checksums_are_normalised_and_short_transfers_refused(cli, xproj, monkeypatch):
    from steward import biodata as bd
    from test_v0200_biology import _Resp
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: _Resp(json.dumps([
        {"fastq_ftp": ";ftp.sra.ebi.ac.uk/a_1.fq.gz", "fastq_md5": ";" + "A" * 32, "fastq_bytes": ";10"}]).encode()))
    f = bd.resolve("ENA", "SRR1234567", []).files
    assert [(x.name, x.md5, x.size) for x in f] == [("a_1.fq.gz", "a" * 32, 10)]
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")

    class Short(io.BytesIO):
        status = 200
        headers = {"Content-Length": str(len(MATRIX) + 50)}

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: Short(MATRIX))
    code, _, err = cli("data", "fetch", "https://example.org/m.tsv", "--study", "s1")
    assert code == 65 and "arrived" in err
    assert "inputs" not in tomllib.loads((xproj / "development/studies/s1.toml").read_text())


def test_AN9_a_tsv_row_count_leaves_out_its_header(tmp_path):
    x = tmp_path / "ex"
    from steward.cli import main
    assert main(["example", "biology", str(x)]) == 0
    assert 'n_samples: "25"' in (x / "paper/_variables.yml").read_text()


def test_AN10_bold_text_in_the_statement_and_fenced_headings():
    from steward import records as rc
    assert "GSE7621" in rc.availability_text("## Data availability\n\n**Expression data:** GSE7621.\n\n## References\n")
    assert rc.availability_text("```\n## Data availability\nGSE1\n```\n") is None


def test_AN11_front_matter_and_mismatched_fences_are_not_headings(cli, tmp_path):
    from steward import records as rc
    text = "---\ntitle: x\n# Limitations\n---\n```\n~~~\n## Competing interests\n```\n## Methods\n"
    spans = rc.fenced_spans(text)
    heads = [m.group(0) for m in re.finditer(r"^#{1,6}\s+.+$", text, re.M) if not rc._in_fence(text, m.start(), spans)]
    assert heads == ["## Methods"]


# ---------------------------------------------------------------- STW-038 (Gemini re-verification of 0.20.1): AO1 – AO3
def test_AO1_check_rule_exits_by_its_own_rule_and_always_checks_it(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    cli("init", "--repo", d, "--for", "paper")
    cli("paper", "values", "--write", "--repo", d)
    code, out, _ = cli("check", "--repo", d, "--rule", "R-10")
    assert out.startswith("PASS R-10") and code == 0, (code, out)
    code, out, err = cli("check", "config", "--repo", d, "--rule", "R-83")
    assert code == 0 and "R-83" in out.splitlines()[0] and "internal error" not in err, (code, err)  # AP1: N/A is fine
    for r in ("R-07", "R-49", "R-86"):  # rules that are not configured here
        code, _, err = cli("check", "--repo", d, "--rule", r)
        assert code == 0 and "internal error" not in err, (r, code, err)


@pytest.mark.parametrize("text,heads", [
    ("```code```\n\n## Methods\n\n## Data availability\n\nGSE7621.\n", ["## Methods", "## Data availability"]),
    ("````markdown\n```\n## Fake\n````\n## Real\n", ["## Real"]),
    ("~~~\n```\n## Fake\n~~~\n## Real\n", ["## Real"]),
])
def test_AO2_fences_follow_commonmark(text, heads):
    from steward import records as rc
    spans = rc.fenced_spans(text)
    got = [m.group(0) for m in re.finditer(r"^#{1,6}\s+.+$", text, re.M) if not rc._in_fence(text, m.start(), spans)]
    assert got == heads
    if "Data availability" in text:
        assert "GSE7621" in rc.availability_text(text)


def test_AO3_init_paper_refuses_a_linked_steward_toml_before_writing(cli, tmp_path):
    d = _fresh(tmp_path)
    real = tmp_path / "real.toml"
    real.write_text("x = 1\n")
    (d / "steward.toml").symlink_to(real)
    code, _, _ = cli("init", "--repo", d, "--paper")
    assert code == 65 and real.read_text() == "x = 1\n" and not (d / "paper").exists()


@pytest.mark.parametrize("inp", [
    'files = [{ path = "data/peaks.bed" }]\n[ inputs.references ]\ngenome = "GRCh37"\n',
    '[inputs.references]\ngenome = "GRCh37"\n\n[[inputs.files]]\npath = "data/x.bed"\n',
])
def test_AN4_no_spelling_of_an_inputs_subtable_changes_owner(cli, xproj, inp):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    for f in ("peaks.bed", "x.bed", "m.txt"):
        (xproj / "data" / f).write_text("chr1\t1\t2\n")
    (xproj / "development/studies").mkdir(parents=True, exist_ok=True)
    (xproj / "development/studies/s1.toml").write_text(
        'schema = "steward.study/1"\nid = "s1"\ntitle = "S"\n\n[[inputs]]\nid = "peaks"\nsource = "local"\n' + inp)
    code, _, err = cli("study", "add-input", "s1", "--source", "GEO", "--accession", "GSE9", "--file", "data/m.txt")
    assert code == 0, err
    by = {i["id"]: i for i in tomllib.loads((xproj / "development/studies/s1.toml").read_text())["inputs"]}
    assert by["peaks"]["references"]["genome"] == "GRCh37" and "references" not in by["GSE9"]


def test_AN7_a_bgzf_sam_reads_its_rname_column(cli, xproj):
    import gzip
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/reads.sam.bgz").write_bytes(gzip.compress(b"@HD\tVN:1.6\n") +
                                               gzip.compress(b"read1\t0\t1\t100\t60\t4M\t*\t0\t0\tACGT\t*\n"))
    (xproj / "data/peaks.bed").write_text("chr1\t1\t2\n")
    _study(xproj, '[references]\nchromosome_naming = "ucsc"\n',
           '[[inputs]]\nid = "reads"\nfiles = [{ path = "data/reads.sam.bgz" }]\n')
    cli("study", "fingerprint", "s1", "--write")
    assert "R-75.chromosome_naming" in [d["code"] for d in _r75(cli, xproj)["details"]]


def test_AM2_a_branch_rewound_after_the_check_is_refused(cli, xproj, tmp_path, monkeypatch):
    pub = _dev(xproj, tmp_path)
    assert cli("release", "publish", "v1.0.0", "--push")[0] == 0
    first = subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout.strip()
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    gsh(xproj, "git", "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    assert cli("release", "publish", "v2.0.0", "--push")[0] == 0
    (xproj / "src/tool.py").write_text("print('v3')\n")
    gsh(xproj, "git", "commit", "-qam", "v3")
    gsh(xproj, "git", "tag", "-a", "v3.0.0", "-m", "v3.0.0")
    from steward import publish as pb
    real = pb._git

    def fake(cwd, *args, **kw):  # the public branch is rewound to v1.0.0 just before the push
        if args[:3] == ("push", "-q", "--atomic"):
            subprocess.run(["git", "update-ref", "refs/heads/main", first], cwd=pub, check=True)
        return real(cwd, *args, **kw)
    monkeypatch.setattr(pb, "_git", fake)
    assert cli("release", "publish", "v3.0.0", "--push")[0] != 0
    assert subprocess.run(["git", "rev-parse", "main"], cwd=pub, capture_output=True, text=True).stdout.strip() == first
