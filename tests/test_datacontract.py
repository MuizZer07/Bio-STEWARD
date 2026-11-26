"""Synthetic tables for the data contract gate."""
import hashlib
import json
import os

import pytest

from conftest import gate, one
from steward.fsutil import safe_write


CONFIG = """
[[data.contract]]
path = "results.tsv"
id_column = "gene"
columns = { gene = "hgnc", label = "text", score = "number", rank = "integer" }
raw_counts = ["S1", "S2"]
p_value = "p"
adjusted_p_value = "q"
log_fold_change = "lfc"
"""

HEADER = "gene\tlabel\tscore\trank\tS1\tS2\tp\tq\tlfc\n"
ROW = ["SEPT2", "probe", "1.1", "2", "5", "0", "0.01", "0.02", "-3"]


def put(root, path, data):
    safe_write(root, path, data.encode() if isinstance(data, str) else data)


def config(root, addition=CONFIG):
    path = root / "steward.toml"
    put(root, path.name, path.read_text() + addition)


def table(root, *rows):
    put(root, "results.tsv", HEADER + "".join("\t".join(row) + "\n" for row in rows))


def check(cli, root):
    _, report = cli.check(root, "data")
    return one(report, "R-83")


@pytest.mark.parametrize(("column", "bad", "code"), [
    (1, "2-Sep", "excel_date"),
    (1, "1-Mar", "excel_date"),
    (1, "Sep-02", "excel_date"),
    (1, "BAD_ID", "identifier"),
    (1, "NA", "missing_id"),
    (3, "three", "type"),
    (4, "2.5", "type"),
    (5, "-1", "raw_count"),
    (6, "0.25", "raw_count"),
    (7, "-0.1", "p_value"),
    (8, "1.1", "p_value"),
    (8, "0.009999999999999999999", "p_order"),
    (9, "-Inf", "infinite_lfc"),
    (9, "+Infinity", "infinite_lfc"),
])
def test_cell_failure_and_control(cli, example, column, bad, code):
    config(example)
    table(example, ROW)
    assert check(cli, example)["status"] == "PASS"
    changed = ROW.copy()
    changed[column - 1] = bad
    table(example, changed)
    result = check(cli, example)
    assert result["status"] == "FAIL"
    [finding] = result["details"]
    assert (finding["code"], finding["row"], finding["column"]) == (f"R-83.{code}", 2, column)


@pytest.mark.parametrize(("kind", "good", "bad"), [
    ("ensembl", "ENSMUSG00000000001.12", "ENSMUST00000000001"),
    ("entrez", "123", "0"),
    ("hgnc", "C12orf57", "BAD ID"),
])
def test_identifier_patterns(cli, example, kind, good, bad):
    config(example, CONFIG.replace('"hgnc"', f'"{kind}"'))
    for status, identifier in [("PASS", good), ("FAIL", bad)]:
        table(example, [identifier, *ROW[1:]])
        assert check(cli, example)["status"] == status


def test_duplicate_and_missing_encodings(cli, example):
    config(example)
    row = ["MARCH1", "label", "NA", "NA", *ROW[4:]]
    table(example, ROW, row)
    assert check(cli, example)["status"] == "PASS"
    row[0] = ROW[0]
    row[3] = ""
    table(example, ROW, row)
    result = check(cli, example)
    assert [(d["code"], d["row"], d["column"]) for d in result["details"]] == [
        ("R-83.duplicate_id", 3, 1),
        ("R-83.mixed_na", 3, 4),
    ]


def test_series_matrix_and_sample_sheet(csv_project, cli):
    root = csv_project
    assert check(cli, root)["status"] == "PASS"
    put(root, "samples.csv", 'sample,note\n"S,1","two\nlines"\nS3,other\n')
    result = check(cli, root)
    assert [(d["code"], d["path"], d["row"], d["column"]) for d in result["details"]] == [
        ("R-83.sample_not_in_sheet", "series.txt", 3, 3),
        ("R-83.sample_not_in_matrix", "samples.csv", 4, 1),
    ]
    put(root, "samples.csv", 'sample,note\nS2,other\n"S,1",control\n')
    [finding] = check(cli, root)["details"]
    assert (finding["code"], finding["row"], finding["column"]) == ("R-83.sample_order", 2, 1)


@pytest.fixture
def csv_project(example):
    config(example, """
[[data.contract]]
path = "series.txt"
format = "series_matrix"
id_column = "gene"
columns = { gene = "entrez" }
[data.contract.sample_sheet]
path = "samples.csv"
format = "csv"
id_column = "sample"
""")
    put(example, "series.txt",
        '\ufeff!Series_title\t"Toy"\r\n!series_matrix_table_begin\r\n'
        '"gene"\t"S,1"\t"S2"\r\n123\t0\t1\r\n!series_matrix_table_end\r\n')
    put(example, "samples.csv", 'sample,note\n"S,1","two\nlines"\nS2,other\n')
    return example


def test_streams_through_end_and_hashes_original_bytes(cli, example, monkeypatch):
    from steward import datacontract
    from steward.rules import Ctx

    config(example, """
[[data.contract]]
path = "large.csv"
format = "csv"
raw_counts = ["S1"]
""")
    content = b"S1,label\r\n" + b"1,example\r\n" * 120_000 + b"-1,example\r\n"
    put(example, "large.csv", content)
    original = Ctx.read

    def read(ctx, path):
        assert path != "large.csv"
        return original(ctx, path)

    original_reader = datacontract._DigestReader.readinto
    chunks = []

    def readinto(reader, buffer):
        size = original_reader(reader, buffer)
        chunks.append(size)
        return size

    monkeypatch.setattr(Ctx, "read", read)
    monkeypatch.setattr(datacontract._DigestReader, "readinto", readinto)
    result = check(cli, example)
    [finding] = result["details"]
    assert (finding["code"], finding["row"], finding["column"]) == ("R-83.raw_count", 120_002, 1)
    assert 0 < max(chunks) < sum(chunks) == len(content)
    assert result["evidence"] == [{"path": "large.csv", "sha256": hashlib.sha256(content).hexdigest()}]


def test_default_gate_and_undeclared_control(cli, example):
    _, report = cli.check(example)
    assert one(report, "R-83")["status"] == "NOT_APPLICABLE"
    config(example)
    table(example, ROW)
    _, report = cli.check(example)
    assert gate(report)["eligible"]
    table(example, ["2-Sep", *ROW[1:]])
    _, report = cli.check(example)
    assert {"rule": "R-83", "status": "FAIL", "subject": "results.tsv"} in gate(report)["blocking"]


@pytest.mark.parametrize(("contents", "code", "row", "column"), [
    ("S1,S1\n1,2\n", "header", 1, 2),
    ("S2,label\n1,a\n", "missing_column", 1, None),
    ("S1,label\n1\n", "row_width", 2, 2),
    ('S1,label\n1,"unclosed', "format", 2, None),
    (b"S1,label\n1,\xff\n", "encoding", None, None),
])
def test_bad_table_structure_and_control(cli, example, contents, code, row, column):
    config(example, '\n[[data.contract]]\npath = "small.csv"\nformat = "csv"\nraw_counts = ["S1"]\n')
    put(example, "small.csv", "S1,label\n1,example\n")
    assert check(cli, example)["status"] == "PASS"
    put(example, "small.csv", contents)
    result = check(cli, example)
    assert result["status"] == "FAIL"
    [finding] = result["details"]
    assert (finding["code"], finding["row"], finding["column"]) == (f"R-83.{code}", row, column)


def test_series_end_marker_required(cli, csv_project):
    assert check(cli, csv_project)["status"] == "PASS"
    path = csv_project / "series.txt"
    put(csv_project, path.name, path.read_bytes().split(b"!series_matrix_table_end")[0])
    [finding] = check(cli, csv_project)["details"]
    assert (finding["code"], finding["row"]) == ("R-83.format", 5)


def test_sample_sheet_duplicate_and_missing_ids(cli, csv_project):
    assert check(cli, csv_project)["status"] == "PASS"
    put(csv_project, "samples.csv", 'sample,note\n"S,1",first\n"S,1",again\n,empty\n')
    result = check(cli, csv_project)
    assert result["status"] == "FAIL"
    assert [(d["code"], d["path"], d["row"], d["column"]) for d in result["details"]] == [
        ("R-83.duplicate_id", "samples.csv", 3, 1),
        ("R-83.missing_id", "samples.csv", 4, 1),
    ]


@pytest.mark.parametrize("kind", ["leaf", "parent", "hard"])
def test_file_links_are_refused(cli, example, kind):
    config(example, CONFIG.replace("results.tsv", "linked-data/results.tsv"))
    assert check(cli, example)["status"] == "INCOMPLETE"
    put(example, "target/results.tsv", HEADER + "\t".join(ROW) + "\n")
    if kind == "parent":
        (example / "linked-data").symlink_to("target", target_is_directory=True)
    else:
        (example / "linked-data").mkdir()
        path = example / "linked-data/results.tsv"
        if kind == "hard":
            os.link(example / "target/results.tsv", path)
        else:
            path.symlink_to("../target/results.tsv")
    result = check(cli, example)
    assert result["status"] == "FAIL"
    assert result["details"][0]["code"] == "R-83.refused"
    assert result["evidence"] == []


@pytest.mark.parametrize("bad", [
    CONFIG.replace("results.tsv", "../results.tsv"),
    CONFIG.replace("results.tsv", "."),
    CONFIG.replace('"hgnc"', '"invalid"'),
    CONFIG.replace('adjusted_p_value = "q"', 'adjusted_p_value = "p"'),
    CONFIG + CONFIG.replace("results.tsv", "./results.tsv"),
])
def test_invalid_contract_is_rejected_by_configuration_rule(cli, example, bad):
    config(example, bad)
    _, report = cli.check(example, "data")
    assert one(report, "R-01")["status"] == "FAIL"
    assert one(report, "R-83")["status"] == "UNKNOWN"


def test_matrix_metadata_and_numeric_boundaries(cli, example):
    config(example, """
[[data.contract]]
path = "results.tsv"
id_column = "gene"
columns = { enabled = "boolean", note = "text" }
na_values = ["."]
metadata_columns = ["enabled", "note", "p", "q"]
raw_counts = ["S1"]
p_value = "p"
adjusted_p_value = "q"
[data.contract.sample_sheet]
path = "samples.tsv"
id_column = "sample"
""")
    put(example, "samples.tsv", "sample\nS1\n")
    header = "gene\tenabled\tnote\tp\tq\tS1\n"
    body = "A\ttrue\tNA\t0.5\t1\t1.00e2\nB\tfalse\t.\t1\t1\t-0\n"  # 0.20.2: an exact 0 is reported as underflow
    put(example, "results.tsv", header + body)
    assert check(cli, example)["status"] == "PASS"
    put(example, "results.tsv", header + body.replace("true", "yes"))
    [finding] = check(cli, example)["details"]
    assert (finding["code"], finding["row"], finding["column"]) == ("R-83.type", 2, 2)


@pytest.mark.parametrize("format_", ["text", "md"])
def test_reports_render_row_and_column(cli, example, tmp_path, format_):
    config(example)
    table(example, ["2-Sep", *ROW[1:]])
    if format_ == "text":
        _, out, err = cli("check", "--repo", example, "data")
    else:
        _, report = cli.check(example, "data")
        put(tmp_path, "report.json", json.dumps(report))
        _, out, err = cli("report", tmp_path / "report.json", "--format", "md")
    assert not err
    assert "row=2 column=1" in out
