"""Reference preflight through the study CLI and the report schemas."""

import gzip
import hashlib
import json
import socket

import pytest

from conftest import append, codes, results
from steward import reference_preflight
from test_interface import machine_example  # noqa: F401
from test_interface_w02 import _check_golden, _valid


REFERENCE = "fixture.chrom.sizes"
SIZES = "chr1\t248956422\nchr2\t242193529\n"
VCF = "##fileformat=VCFv4.3\n##contig=<ID=chr1,length={length}>\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
SAM = "@HD\tVN:1.6\n@SQ\tLN:{length}\tSN:chr1\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("reference preflight must stay offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _study(root, files, *, declaration=f'genome = "GRCh38"\nchromosome_sizes = "{REFERENCE}"'):
    inputs = []
    for path, content in files.items():
        data = content.encode("utf-8") if isinstance(content, str) else content
        (root / path).write_bytes(data)
        inputs.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    inline = ", ".join(f'{{ path = "{f["path"]}", sha256 = "{f["sha256"]}" }}' for f in inputs)
    path = root / "development/studies/reference-fixture.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'schema = "steward.study/1"\nid = "reference-fixture"\ntitle = "Reference fixture"\n'
        f'[[inputs]]\nid = "fixture"\nfiles = [{inline}]\n[references]\n{declaration}\n',
        encoding="utf-8",
    )
    (root / REFERENCE).write_text(SIZES, encoding="utf-8")


def _result(report):
    return next(row for row in results(report, "R-75") if row["subject"].endswith("/reference-fixture.toml"))


@pytest.mark.parametrize(("path", "data", "status", "message"), [
    ("input.vcf", VCF.format(length=249250621), "FAIL", "contig 'chr1' has header length 249250621, reference length 248956422"),
    ("input.sam", SAM.format(length=249250621), "FAIL", "contig 'chr1' has header length 249250621, reference length 248956422"),
    ("input.bed", "chr1\t0\t248956423\n", "FAIL", "interval end 248956423 exceeds reference length 248956422"),
    ("input.bed", "chr1\t5\t4\n", "FAIL", "BED start exceeds end"),
    ("input.bed", "chr1\t-1\t4\n", "FAIL", "expected a nonnegative decimal integer"),
    ("input.bed", "chr01\t0\t1\n", "FAIL", "contig 'chr01' is absent"),
    ("input.sam", "@SQ\tSN:chr1\n", "FAIL", "@SQ needs one SN and one LN field"),
    ("input.vcf", '##contig=<ID=chr1,Description="quoted, value",length=248956422>\n', "PASS", None),
    ("input.vcf", "##contig=<ID=chr2>\n", "INCOMPLETE", "contig 'chr2' has no length"),
    ("input.vcf", "##contig=<ID=chr2>\n" + VCF.format(length=249250621), "FAIL", "header length 249250621"),
    ("input.sam", "@HD\tVN:1.6\n", "INCOMPLETE", "no contigs found in the SAM header"),
    ("input.bed", "# empty\ntrack name=test\n", "INCOMPLETE", "no contigs found in the BED rows"),
    ("input.bed", "browser position chr1:1-100\nchr1\t0\t248956422\r\nchr2\t0\t1", "PASS", None),
])
def test_reference_findings(cli, example, path, data, status, message):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, {path: data})
    code, report = cli.check(example, "studies")
    row = _result(report)
    assert row["status"] == status
    if message:
        [detail] = row["details"]
        assert message in detail["message"]
        assert detail["path"] == path
        assert "GRCh38" in detail["message"]
    if status == "FAIL":
        assert code != 0
        text = cli("check", "--repo", example, "studies")[1]
        assert message in text


@pytest.mark.parametrize("invalid", [None, "", "chr1 0\n", "chr1 10\nchr1 11\n", "chr1 wrong\n"])
def test_bad_reference_file(cli, example, invalid):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, {"input.vcf": VCF.format(length=248956422)})
    path = example / REFERENCE
    if invalid is None:
        path.unlink()
    else:
        path.write_text(invalid, encoding="utf-8")
    result = _result(cli.check(example, "studies")[1])
    assert result["status"] == "FAIL"
    assert codes(result) == {"R-75.reference_sizes"}
    assert result["details"][0]["path"] == REFERENCE


@pytest.mark.parametrize("declaration", [
    f'chromosome_sizes = "{REFERENCE}"',
    'genome = "GRCh38"\nchromosome_sizes = "../sizes"',
    'genome = "GRCh38"\nchromosome_sizes = "."',
])
def test_invalid_reference_declaration(cli, example, declaration):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, {"input.sam": SAM.format(length=248956422)}, declaration=declaration)
    assert codes(_result(cli.check(example, "studies")[1])) == {"R-75.invalid"}


def test_symlink_sizes_file_is_refused(cli, example, tmp_path):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, {"input.sam": SAM.format(length=248956422)})
    outside = tmp_path / "outside.sizes"
    (example / REFERENCE).rename(outside)
    (example / REFERENCE).symlink_to(outside)
    assert codes(_result(cli.check(example, "studies")[1])) == {"R-75.reference_sizes"}


def test_each_study_uses_its_declared_genome(cli, example):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, {"input.vcf": VCF.format(length=249250621)})
    first = example / "development/studies/reference-fixture.toml"
    second = first.with_name("other-build.toml")
    second.write_text(first.read_text().replace("reference-fixture", "other-build")
                      .replace("GRCh38", "GRCh37").replace(REFERENCE, "other.chrom.sizes"))
    sizes = example / "other.chrom.sizes"
    sizes.write_text("chr1 249250621\n")
    _, before = cli.check(example, "studies")
    assert _result(before)["status"] == "FAIL"
    assert next(row for row in results(before, "R-75") if row["subject"].endswith("other-build.toml"))["status"] == "PASS"
    sizes.write_text("chr1 249250620\n")
    _, after = cli.check(example, "studies")
    assert before["verdict"]["inputs_digest"] != after["verdict"]["inputs_digest"]
    assert next(row for row in results(after, "R-75") if row["subject"].endswith("other-build.toml"))["status"] == "FAIL"


def test_streaming_header_and_bed_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_preflight, "MAX_LINE", 150)
    for kind, header in {".vcf": VCF.format(length=248956422), ".sam": SAM.format(length=248956422)}.items():
        path = f"input{kind}.bgz"
        # A contig declaration crosses compressed member boundaries. The body exceeds the line limit.
        (tmp_path / path).write_bytes(gzip.compress(header[:30].encode()) +
                                      gzip.compress(header[30:].encode() + b"chr1\t" + b"A" * 400))
        assert reference_preflight.check_input(tmp_path, path, kind, {"chr1": 248956422}) is None

    path = "input.bed.gz"
    (tmp_path / path).write_bytes(gzip.compress(b"chr1\t0\t1\n" * 20))
    monkeypatch.setattr(reference_preflight, "MAX_SCAN", 100)
    with pytest.raises(reference_preflight.PreflightError, match="scan exceeds 100 bytes"):
        reference_preflight.check_input(tmp_path, path, ".bed", {"chr1": 1})
    (tmp_path / path).write_bytes(gzip.compress(b"") * 10)
    with pytest.raises(reference_preflight.PreflightError, match="raw byte limit exceeded"):
        reference_preflight.check_input(tmp_path, path, ".bed", {"chr1": 1})
    (tmp_path / path).write_bytes(gzip.compress(b"chr1\t0\t1\n")[:-4])
    with pytest.raises(reference_preflight.PreflightError, match="cannot read compressed genomic text"):
        reference_preflight.check_input(tmp_path, path, ".bed", {"chr1": 1})


def test_line_and_sizes_limits(tmp_path, monkeypatch):
    path = tmp_path / REFERENCE
    path.write_text(SIZES, encoding="utf-8")
    monkeypatch.setattr(reference_preflight, "MAX_SIZES", 20)
    with pytest.raises(reference_preflight.PreflightError, match="scan exceeds 20 bytes"):
        reference_preflight.chromosome_sizes(tmp_path, REFERENCE)
    monkeypatch.setattr(reference_preflight, "MAX_LINE", 10)
    with pytest.raises(reference_preflight.PreflightError, match="line exceeds 10 bytes"):
        reference_preflight.chromosome_sizes(tmp_path, REFERENCE)


def test_b03_goldens(cli, machine_example):
    name, root = machine_example
    _study(root, {"fixture.vcf": VCF.format(length=249250621),
                  "fixture.sam": SAM.format(length=248956422),
                  "fixture.bed": "chr2\t0\t242193530\n"})
    _, report = cli.check(root, "studies")
    row = _result(_valid(report))
    assert {"path": REFERENCE, "sha256": hashlib.sha256(SIZES.encode()).hexdigest()} in row["evidence"]
    code, out, err = cli("study", "show", "reference-fixture", "--repo", root, "--format", "json")
    assert code == 0 and not err
    _check_golden(f"{name}.b03.json", {
        "study show": _valid(json.loads(out)),
        "check": {"schema": report["schema"], "results": [row]},
    })
