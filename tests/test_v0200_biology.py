"""0.20.0 biology: B1 fetch with provenance (STW-011), B3/B4 conventions and sample metadata (STW-013), B5 data
availability (STW-014). The network is never used: the archive is a fake."""

import hashlib
import io
import json
import tomllib

import pytest

from conftest import codes, results
from test_v0120_features import gsh, xproj  # noqa: F401

MATRIX = b"ID_REF\tGSM1\tGSM2\n1007_s_at\t5.1\t6.2\n"


class _Resp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _archive(monkeypatch, files, md5=None, ranged=True):
    """A fake Zenodo record serving `files` {name: bytes}; returns the list of requests."""
    from steward import biodata as bd
    seen = []

    def fake(req, timeout=None):
        url = req.full_url
        seen.append((url, dict(req.header_items())))
        if url.startswith("https://zenodo.org/api/records/"):
            return _Resp(json.dumps({"files": [
                {"key": n, "size": len(d), "checksum": f"md5:{(md5 or {}).get(n) or hashlib.md5(d).hexdigest()}",
                 "links": {"self": f"https://zenodo.org/files/{n}"}} for n, d in files.items()]}).encode())
        name = url.rsplit("/", 1)[1]
        data = files[name]
        rng = req.get_header("Range")
        if rng and ranged:
            return _Resp(data[int(rng.split("=")[1].rstrip("-")):], 206)
        return _Resp(data)
    monkeypatch.setattr(bd, "_urlopen", fake)
    return seen


def _study_cfg(x):
    with open(x / "steward.toml", "a") as f:
        f.write("\n[studies]\n")


# ---------------------------------------------------------------- B1: fetch with provenance
def test_B1_a_fetch_records_the_input_with_its_checksums(cli, xproj, monkeypatch):
    _study_cfg(xproj)
    assert cli("study", "new", "s1", "--title", "S")[0] == 0
    _archive(monkeypatch, {"m.txt": MATRIX})
    code, out, err = cli("data", "fetch", "Zenodo:1234567", "--study", "s1")
    assert code == 0, err
    assert "checked against the archive's md5" in out
    st = tomllib.loads((xproj / "development/studies/s1.toml").read_text())
    inp = st["inputs"][0]
    assert inp["accession"] == "1234567" and inp["source"] == "Zenodo" and inp["retrieved"]
    f = inp["files"][0]
    assert f["path"] == "data/raw/1234567/m.txt" and f["size"] == len(MATRIX)
    assert f["sha256"] == hashlib.sha256(MATRIX).hexdigest() and f["md5"] == hashlib.md5(MATRIX).hexdigest()
    assert f["url"] == "https://zenodo.org/files/m.txt"
    _, rep = cli.check(xproj, "studies")
    assert results(rep, "R-75")[0]["status"] == "PASS"
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1")[0] == 64  # once per input


def test_B1_a_checksum_mismatch_refuses_and_records_nothing(cli, xproj, monkeypatch):
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    before = (xproj / "development/studies/s1.toml").read_text()
    _archive(monkeypatch, {"m.txt": MATRIX}, md5={"m.txt": "0" * 32})
    code, _, err = cli("data", "fetch", "Zenodo:1234567", "--study", "s1")
    assert code == 65 and "md5" in err and "nothing recorded" in err
    assert (xproj / "development/studies/s1.toml").read_text() == before
    assert not list((xproj / "data/raw/1234567").iterdir())  # no file, no partial file


def test_B1_an_expected_sha256_is_checked_for_a_url(cli, xproj, monkeypatch):
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    from steward import biodata as bd
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: _Resp(MATRIX))
    code, _, err = cli("data", "fetch", "https://example.org/d/m.tsv", "--study", "s1", "--sha256", "a" * 64)
    assert code == 65 and "sha256" in err
    code, out, err = cli("data", "fetch", "https://example.org/d/m.tsv", "--study", "s1",
                         "--sha256", hashlib.sha256(MATRIX).hexdigest())
    assert code == 0, err
    inp = tomllib.loads((xproj / "development/studies/s1.toml").read_text())["inputs"][0]
    assert inp["url"] == "https://example.org/d/m.tsv" and "accession" not in inp


def test_B1_a_partial_download_resumes(cli, xproj, monkeypatch):
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    d = xproj / "data/raw/1234567"
    d.mkdir(parents=True)
    (d / ".m.txt.part").write_bytes(MATRIX[:10])
    seen = _archive(monkeypatch, {"m.txt": MATRIX})
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1")[0] == 0
    assert (d / "m.txt").read_bytes() == MATRIX and not (d / ".m.txt.part").exists()
    assert any(h.get("Range") == "bytes=10-" for _, h in seen)


def test_B1_a_server_that_ignores_the_range_restarts_cleanly(cli, xproj, monkeypatch):
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    d = xproj / "data/raw/1234567"
    d.mkdir(parents=True)
    (d / ".m.txt.part").write_bytes(b"garbage!!")
    _archive(monkeypatch, {"m.txt": MATRIX}, ranged=False)
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1")[0] == 0
    assert (d / "m.txt").read_bytes() == MATRIX


def test_B1_sources_resolve_to_their_archives_and_a_dry_run_downloads_nothing(cli, xproj, monkeypatch):
    from steward import biodata as bd
    assert bd.resolve("GEO", "GSE5281", []).files[0].url == \
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE5nnn/GSE5281/matrix/GSE5281_series_matrix.txt.gz"
    assert bd.resolve("GEO", "GSE123", ["GSE123_RAW.tar"]).files[0].url.endswith("/geo/series/GSEnnn/GSE123/suppl/GSE123_RAW.tar")
    assert bd.parse_spec("SRA:SRR1234567") == ("ENA", "SRR1234567")
    for bad in ("GEO:12", "nothing", "ArrayExpress:../x", "ftp:/x"):
        with pytest.raises(bd.FetchError):
            bd.parse_spec(bad)
    with pytest.raises(bd.FetchError):
        bd.resolve("GEO", "GSE1", ["../../etc/passwd"])
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: _Resp(json.dumps([
        {"run_accession": "SRR1", "fastq_ftp": "ftp.sra.ebi.ac.uk/vol1/SRR1_1.fastq.gz;ftp.sra.ebi.ac.uk/vol1/SRR1_2.fastq.gz",
         "fastq_md5": "a" * 32 + ";" + "b" * 32, "fastq_bytes": "10;20"}]).encode()))
    files = bd.resolve("ENA", "SRR1234567", []).files
    assert [(f.name, f.md5, f.size) for f in files] == [("SRR1_1.fastq.gz", "a" * 32, 10), ("SRR1_2.fastq.gz", "b" * 32, 20)]
    assert files[0].url == "https://ftp.sra.ebi.ac.uk/vol1/SRR1_1.fastq.gz"
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    code, out, _ = cli("data", "fetch", "ENA:SRR1234567", "--study", "s1", "--dry-run")
    assert code == 0 and "nothing was downloaded" in out and not (xproj / "data").exists()


def test_B1_the_destination_stays_in_the_repository_and_off_links(cli, xproj, monkeypatch, tmp_path):
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    _archive(monkeypatch, {"m.txt": MATRIX})
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1", "--dest", "../out")[0] == 65
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1", "--dest", ".git/x")[0] == 65
    (tmp_path / "elsewhere").mkdir()
    (xproj / "linked").symlink_to(tmp_path / "elsewhere")
    assert cli("data", "fetch", "Zenodo:1234567", "--study", "s1", "--dest", "linked")[0] == 65
    assert not list((tmp_path / "elsewhere").iterdir())


# ---------------------------------------------------------------- B3: conventions
def _study(x, body, inputs_extra=""):
    (x / "development/studies").mkdir(parents=True, exist_ok=True)
    (x / "development/studies/s1.toml").write_text(f'''schema = "steward.study/1"
id = "s1"
title = "S"

[[inputs]]
id = "peaks"
source = "local"
files = [{{ path = "data/peaks.bed" }}]
{inputs_extra}
{body}''')


def _r75(cli, x):
    _, rep = cli.check(x, "studies")
    return results(rep, "R-75")[0]


@pytest.mark.parametrize("first,ok", [("chr1", True), ("1", False), ("NC_000001.11", False)])
def test_B3_chromosome_names_are_checked_against_the_declared_naming(cli, xproj, first, ok):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/peaks.bed").write_text(f"track name=x\n{first}\t100\t200\n")
    _study(xproj, '[references]\nchromosome_naming = "ucsc"\n')
    cli("study", "fingerprint", "s1", "--write")
    r = _r75(cli, xproj)
    assert (r["status"] == "PASS") is ok and ("R-75.chromosome_naming" in codes(r)) is not ok, r


def test_B3_an_input_that_declares_other_conventions_than_its_study_fails(cli, xproj):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/peaks.bed").write_text("chr1\t1\t2\n")
    _study(xproj, '[references]\ngenome = "GRCh38"\ntaxon = 9606\n',
           '[inputs.references]\ngenome = "GRCh37"\ntaxon = 9606\n')
    cli("study", "fingerprint", "s1", "--write")
    r = _r75(cli, xproj)
    d = [x for x in r["details"] if x["code"] == "R-75.convention_mismatch"]
    assert r["status"] == "FAIL" and [x["value"] for x in d] == ["genome"] and d[0]["path"] == "data/peaks.bed"


def test_B3_the_mapping_table_is_fingerprinted_with_its_version(cli, xproj):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/peaks.bed").write_text("chr1\t1\t2\n")
    (xproj / "data/map.tsv").write_text("probe\tgene\n")
    _study(xproj, '[references.mapping]\npath = "data/map.tsv"\nversion = "GPL570, 2026-01-10"\n')
    assert cli("study", "fingerprint", "s1", "--write")[0] == 0
    assert _r75(cli, xproj)["status"] == "PASS"
    (xproj / "data/map.tsv").write_text("probe\tgene\nx\ty\n")
    r = _r75(cli, xproj)
    assert r["status"] == "FAIL" and "R-75.file_changed" in codes(r)


# ---------------------------------------------------------------- B4: sample metadata
SHEET = "sample\torganism\ttissue\tcondition\tbatch\nGSM1\tHomo sapiens\tbrain\tcontrol\tb1\nGSM2\tHomo sapiens\tbrain\tcase\tb1\n"


def _samples(x, sheet=SHEET, matrix=MATRIX, allowed='{ condition = ["control", "case"] }'):
    _study_cfg(x)
    (x / "data").mkdir(exist_ok=True)
    (x / "data/peaks.bed").write_text("chr1\t1\t2\n")
    (x / "data/samples.tsv").write_text(sheet)
    (x / "data/m.txt").write_bytes(matrix)
    _study(x, f'[samples]\npath = "data/samples.tsv"\nallowed = {allowed}\nmatrix = [{{ path = "data/m.txt" }}]\n',
           '[[inputs]]\nid = "GSE1"\nsource = "GEO"\naccession = "GSE1"\nfiles = [{ path = "data/m.txt" }]\n')
    assert cli_fp(x)


def cli_fp(x):
    from steward.cli import main
    return main(["study", "fingerprint", "s1", "--write", "--repo", str(x)]) == 0


def test_B4_a_sample_sheet_that_matches_its_matrix_passes(cli, xproj):
    _samples(xproj)
    r = _r75(cli, xproj)
    assert r["status"] == "PASS", r


@pytest.mark.parametrize("sheet,code", [
    (SHEET.replace("\tcase\t", "\tCase\t"), "R-75.sample_value_not_allowed"),
    (SHEET.replace("\tb1\nGSM2", "\tNA\nGSM2"), "R-75.sample_value_missing"),
    (SHEET.replace("\tbatch", "\tbatch_id"), "R-75.sample_field_missing"),
    (SHEET.replace("GSM2", "GSM9"), "R-75.sample_not_in_metadata"),
    (SHEET + "GSM3\tHomo sapiens\tbrain\tcase\tb2\n", "R-75.sample_not_in_matrix"),
    (SHEET + "GSM2\tHomo sapiens\tbrain\tcase\tb2\n", "R-75.sample_duplicate"),
])
def test_B4_each_sample_finding_names_the_file_and_row(cli, xproj, sheet, code):
    _samples(xproj, sheet=sheet)
    r = _r75(cli, xproj)
    hit = [d for d in r["details"] if d["code"] == code]
    assert r["status"] == "FAIL" and hit and hit[0]["path"], r


def test_B4_a_geo_series_matrix_header_is_read_after_its_metadata(cli, xproj):
    import gzip
    m = gzip.compress(b'!Series_title\t"x"\n!series_matrix_table_begin\n"ID_REF"\t"GSM1"\t"GSM2"\n"a"\t1\t2\n')
    from steward import biodata as bd
    assert bd.matrix_samples(m, "GSE1_series_matrix.txt.gz") == ["GSM1", "GSM2"]


def test_B4_a_matrix_that_is_not_a_recorded_input_is_incomplete(cli, xproj):
    _samples(xproj)
    t = (xproj / "development/studies/s1.toml").read_text().replace('files = [{ path = "data/m.txt"', 'files = [{ path = "data/peaks.bed"', 1)
    t = t.replace('id = "GSE1"\nsource = "GEO"\naccession = "GSE1"\nfiles = [{ path = "data/m.txt"', 'id = "GSE1"\nsource = "GEO"\naccession = "GSE1"\nfiles = [{ path = "data/samples.tsv"')
    (xproj / "development/studies/s1.toml").write_text(t)
    assert "R-75.matrix_unrecorded" in codes(_r75(cli, xproj))


# ---------------------------------------------------------------- B5: data availability
def _paper(x, statement, spec_file=None):
    (x / "paper").mkdir(exist_ok=True)
    (x / "paper/main.tex").write_text("\\section{Methods}\nWe used GSE1 and GSE2.\n"
                                      + ("" if spec_file else f"\\section{{Data availability}}\n{statement}\n")
                                      + "\\section{References}\n")
    if spec_file:
        (x / "paper" / spec_file).write_text(statement)
        (x / "paper/spec.toml").write_text(f'data_availability = "{spec_file}"\n')
    with open(x / "steward.toml", "a") as f:
        f.write('\n[paper.main]\ndir = "paper"\nmain = "main.tex"\n')


def _cited(x):
    _study_cfg(x)
    (x / "development/studies").mkdir(parents=True, exist_ok=True)
    (x / "development/studies/s1.toml").write_text('''schema = "steward.study/1"
id = "s1"
title = "S"
papers = ["main"]

[[inputs]]
id = "GSE1"
source = "GEO"
accession = "GSE1"

[[inputs]]
id = "GSE2"
source = "GEO"
accession = "GSE2"
''')


def _r85(cli, x):
    _, rep = cli.check(x, "studies")
    return results(rep, "R-85")


def test_B5_a_paper_naming_one_of_two_accessions_is_incomplete(cli, xproj):
    _cited(xproj)
    _paper(xproj, "Data are in GEO under GSE1.")
    r = _r85(cli, xproj)[0]
    assert r["status"] == "INCOMPLETE" and [d["value"] for d in r["details"]] == ["GSE2"], r


def test_B5_naming_both_passes_and_gse1_never_matches_gse10(cli, xproj):
    _cited(xproj)
    _paper(xproj, "Data: GSE1 and GSE2 (GEO).")
    assert _r85(cli, xproj)[0]["status"] == "PASS"
    from steward import records as rc
    assert not rc.accession_named("GSE1", "GSE10 only") and rc.accession_named("GSE1", "series~GSE1.")


def test_B5_the_statement_file_the_spec_names_is_read(cli, xproj):
    _cited(xproj)
    _paper(xproj, "GSE1, GSE2", spec_file="data.tex")
    assert _r85(cli, xproj)[0]["status"] == "PASS"


def test_B5_no_statement_and_no_cited_study(cli, xproj):
    _cited(xproj)
    _paper(xproj, "")
    (xproj / "paper/main.tex").write_text("\\section{Methods}\nGSE1 GSE2\n")
    r = _r85(cli, xproj)[0]
    assert r["status"] == "INCOMPLETE" and "R-85.no_statement" in codes(r)
    t = (xproj / "development/studies/s1.toml").read_text().replace('papers = ["main"]\n', "")
    (xproj / "development/studies/s1.toml").write_text(t)
    assert _r85(cli, xproj)[0]["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- B6: the worked example
def test_B6_the_biology_example_passes_and_its_breakages_fail_as_documented(cli, tmp_path):
    x = tmp_path / "ex"
    code, out, err = cli("example", "biology", x)
    assert code == 0 and "steward check --summary" in out, err
    assert 'repo_id = "c77f22b4' not in (x / "steward.toml").read_text()  # an ID of its own
    code, out, _ = cli("check", "--repo", x, "--summary")
    assert code == 0 and "Gate default: ELIGIBLE" in out and "FAIL 0" in out and "UNKNOWN 0" in out, out
    t = (x / "results/top_genes.tsv").read_text().split("\n")
    cols = t[1].split("\t")
    cols[1] = "7-Sep"  # what a spreadsheet does to SEPTIN7's old symbol
    t[1] = "\t".join(cols)
    (x / "results/top_genes.tsv").write_text("\n".join(t))
    _, out, _ = cli("check", "--repo", x, "--summary")
    assert "FAIL R-83" in out and "results/top_genes.tsv" in out
    da = (x / "paper/data-availability.md").read_text()
    (x / "paper/data-availability.md").write_text(da.replace(" under accession GSE7621", "").replace(
        "(https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE7621)", ""))
    _, out, _ = cli("check", "--repo", x, "--summary")
    assert "INCOMPLETE R-85" in out
    assert cli("example", "biology", x)[0] == 64  # never over an existing folder


def test_B6_the_example_analysis_reproduces_its_results(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    src = Path(__file__).parents[1] / "examples/biology-geo"
    x = tmp_path / "ex"
    shutil.copytree(src, x)
    before = {p: (x / p).read_bytes() for p in ("results/de.tsv", "results/top_genes.tsv", "results/summary.toml")}
    subprocess.run([sys.executable, "analysis/de.py"], cwd=x, check=True, capture_output=True)
    assert {p: (x / p).read_bytes() for p in before} == before
