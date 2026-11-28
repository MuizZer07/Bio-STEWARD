"""Offline biology checks through their CLI entry points."""
import hashlib
import json
import socket

import pytest

from conftest import append, codes, one, results
from steward.runner import environment
from test_interface import machine_example  # noqa: F401
from test_interface_w02 import _check_golden, _valid


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("biology checks must stay offline")

    monkeypatch.setenv("STEWARD_NO_REGISTRY", "1")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _study(root, *, references="", tools="", samples=None, design=""):
    record = ('schema = "steward.study/1"\nid = "biology-fixture"\ntitle = "Biology fixture"\n'
              '[[inputs]]\nid = "fixture"\n')
    if references:
        record += f"\n[references]\n{references}\n"
    record += tools
    if samples is not None:
        digest = _put(root, "fixture-samples.tsv", samples)
        record += (f'\n[samples]\npath = "fixture-samples.tsv"\nsha256 = "{digest}"\n'
                   'required = []\n' + design)
    return _put(root, "development/studies/biology-fixture.toml", record)


def _study_result(cli, root):
    _, report = cli.check(root, "studies")
    return next(row for row in results(report, "R-75") if row["subject"].endswith("/biology-fixture.toml"))


def _contract(root, fields):
    append(root, "steward.toml", '\n[[data.contract]]\npath = "fixture-results.tsv"\n' + fields)


def _contract_result(cli, root):
    _, report = cli.check(root, "data")
    return next(row for row in results(report, "R-83") if row["subject"] == "fixture-results.tsv")


def test_hgnc_previous_retired_and_current(cli, example):
    _contract(example, 'columns = { gene = "hgnc" }\nhgnc_table = "fixture-hgnc.tsv"\n')
    digest = _put(example, "fixture-hgnc.tsv", "symbol\tprev_symbol\tstatus\n"
                  "SEPTIN7\tSEPT7|CDC10\tApproved\nCDC10\t\tApproved\n"
                  "OLD1~withdrawn\t\tEntry Withdrawn\n")
    _put(example, "fixture-results.tsv", "gene\nSEPTIN7\nCDC10\n")
    result = _contract_result(cli, example)
    assert result["status"] == "PASS"
    assert {"path": "fixture-hgnc.tsv", "sha256": digest} in result["evidence"]

    _put(example, "fixture-results.tsv", "gene\nSEPTIN7\nOLD1\nSEPT7\n")
    result = _contract_result(cli, example)
    assert result["status"] == "FAIL"
    assert [(d["code"], d["row"], d["column"]) for d in result["details"]] == [
        ("R-83.retired_hgnc_symbol", 3, 1), ("R-83.previous_hgnc_symbol", 4, 1),
    ]

    _put(example, "fixture-hgnc.tsv", "symbol\tprev_symbol\tstatus\n")
    assert codes(_contract_result(cli, example)) == {"R-83.hgnc_reference"}
    (example / "fixture-hgnc.tsv").unlink()
    assert _contract_result(cli, example)["status"] == "INCOMPLETE"


def test_ensembl_suffixes_are_checked_within_each_column(cli, example):
    _contract(example, 'columns = { gene = "ensembl", other = "ensembl" }\n')
    header = "gene\tother\n"
    first = "ENSG00000000001.1\tENSG00000000002\n"
    _put(example, "fixture-results.tsv", header + first + "ENSG00000000003.2\tNA\n")
    assert _contract_result(cli, example)["status"] == "PASS"
    _put(example, "fixture-results.tsv", header + first + "ENSG00000000003\tNA\n")
    [finding] = _contract_result(cli, example)["details"]
    assert (finding["code"], finding["row"], finding["column"]) == ("R-83.mixed_ensembl_versions", 3, 1)


@pytest.mark.parametrize(("reference", "good", "bad"), [
    ('taxon = 10090', "Trp53", "TP53"),
    ('organism = "Homo sapiens"', "TP53", "Trp53"),
])
def test_symbol_case_uses_study_organism(cli, example, reference, good, bad):
    append(example, "steward.toml", "\n[studies]\n")
    _contract(example, 'columns = { gene = "gene_symbol" }\nstudy = "biology-fixture"\n')
    _put(example, "fixture-results.tsv", f"gene\n{good}\n")
    assert _contract_result(cli, example)["status"] == "INCOMPLETE"
    digest = _study(example, references=reference)
    result = _contract_result(cli, example)
    assert result["status"] == "PASS"
    assert {"path": "development/studies/biology-fixture.toml", "sha256": digest} in result["evidence"]
    _put(example, "fixture-results.tsv", f"gene\n{bad}\n")
    [finding] = _contract_result(cli, example)["details"]
    assert (finding["code"], finding["row"], finding["column"]) == ("R-83.symbol_case", 2, 1)


@pytest.mark.parametrize("base", ["2", '"e"'])
def test_statistics_use_exact_numbers_and_all_rows(cli, example, base):
    _contract(example, f'p_value = "p"\nadjusted_p_value = "q"\nlog_fold_change = "lfc"\nlog_base = {base}\n')
    header = "p\tq\tlfc\n"
    _put(example, "fixture-results.tsv", header + "1e-500\t2e-500\t-1\n")
    assert _contract_result(cli, example)["status"] == "PASS"
    _put(example, "fixture-results.tsv", header + "0e-500\t2e-500\t-1\n")
    result = _contract_result(cli, example)
    assert result["status"] == "INCOMPLETE" and codes(result) == {"R-83.p_zero"}

    _put(example, "fixture-results.tsv", header + "0.2\t2e-1\t-1\n")
    result = _contract_result(cli, example)
    assert result["status"] == "FAIL" and codes(result) == {"R-83.adjusted_equals_raw"}
    _put(example, "fixture-results.tsv", header + "0.2\t2e-1\t-1\n0.3\tNA\t0\n")
    assert _contract_result(cli, example)["status"] == "PASS"


@pytest.mark.parametrize("base", ['1', '0', '-2', 'inf', '"two"'])
def test_bad_log_base_rejected(cli, example, base):
    _contract(example, f'log_fold_change = "lfc"\nlog_base = {base}\n')
    _, report = cli.check(example, "data")
    assert one(report, "R-01")["status"] == "FAIL"


def _samples(columns, groups):
    rows = ["\t".join(columns)]
    for condition, batch, count in groups:
        rows += [f"S{i}\t{condition}\t{batch}" for i in range(len(rows), len(rows) + count)]
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize(("groups", "status", "code"), [
    ([("case", "A", 2), ("control", "B", 2)], "FAIL", "sample_confounding"),
    ([("case", "A", 9), ("control", "A", 1), ("case", "B", 1), ("control", "B", 9)], "PASS", "sample_imbalance"),
    ([("case", "A", 8), ("control", "A", 2), ("case", "B", 1), ("control", "B", 9)], "PASS", None),
    ([("case", "A", 1), ("control", "A", 1), ("case", "B", 1), ("control", "B", 1)], "PASS", None),
    # Each condition occurs in more than one batch, but the third one is disconnected.
    ([("case", "A", 1), ("control", "A", 1), ("case", "B", 1), ("control", "B", 1),
      ("other", "C", 1), ("other", "D", 1)], "FAIL", "sample_confounding"),
])
def test_batch_cross_table(cli, example, groups, status, code):
    append(example, "steward.toml", "\n[studies]\n")
    _study(example, samples=_samples(("sample", "condition", "batch"), groups))
    result = _study_result(cli, example)
    assert result["status"] == status
    assert codes(result) == ({f"R-75.{code}"} if code else set())
    if code:
        [detail] = result["details"]
        assert "condition columns 'case', 'control'" in detail["message"]
        assert "batch rows 'A': 'case'=" in detail["message"]
        assert detail["value"] == "batch"
    if code == "sample_imbalance":
        for flag in ("--summary", "--quiet"):
            exit_code, output, err = cli("check", "--repo", example, "studies", flag)
            assert exit_code == 0 and not err
            assert "R-75 fixture-samples.tsv — Advisory:" in output


def test_covariates_and_missing_values(cli, example):
    append(example, "steward.toml", "\n[studies]\n")
    design = 'condition_column = "group"\ncovariates = ["site"]\n'
    header = "sample\tgroup\tsite\n"
    _study(example, samples=header + "S1\tcase\tA\nS2\tcontrol\tB\n", design=design)
    assert codes(_study_result(cli, example)) == {"R-75.sample_confounding"}
    _study(example, samples=header + "S1\tcase\tA\nS2\tcontrol\tB\nS3\tcase\tNA\n", design=design)
    assert codes(_study_result(cli, example)) == {"R-75.sample_value_missing"}
    _study(example, samples=header.replace("site", "other") + "S1\tcase\tA\n", design=design)
    assert codes(_study_result(cli, example)) == {"R-75.sample_field_missing"}


@pytest.mark.parametrize("prefix,digits", [("phs", 6), ("EGAD", 11), ("egas", 11), ("pht", 6)])
def test_controlled_access_redacts_accessions(cli, example, prefix, digits):
    append(example, "steward.toml", "\n[privacy]\nlocal_paths = false\nallow = ['private.txt']\n")
    accession = prefix + "9" * digits
    _put(example, "private.txt", accession + "\n")
    _put(example, "accessions.txt", "GSE999999\n" + f"x{accession}\n{accession}1\n" +
         f"{accession}  # steward: allow R-07\n")
    _, report = cli.check(example, "privacy")
    assert one(report, "R-07")["status"] == "PASS"
    append(example, "accessions.txt", f"ID: {accession}.v1\n")
    _, report = cli.check(example, "privacy")
    result = one(report, "R-07")
    assert result["status"] == "FAIL" and accession not in json.dumps(result)
    assert [(d["path"], d["line"], d["column"]) for d in result["details"] if d["code"] == "R-07.controlled_access"] == [
        ("accessions.txt", 5, 5),
    ]


def test_environment_locks_and_bioconductor_release(cli, example):
    assert environment(example)["lock_files"] == {}
    locks = {name: _put(example, name, text) for name, text in {
        "renv.lock": '{"R":{"Version":"4.5.1"}}\n',
        "conda-lock.yml": "version: 1\nmetadata: {}\npackage: []\n",
    }.items()}
    assert environment(example)["lock_files"] == locks
    append(example, "steward.toml", "\n[studies]\n")
    tools = '\n[[tools]]\nname = "Bioconductor"\nversion = "{}"\n'
    _study(example, tools=tools.format("3.21"))
    assert _study_result(cli, example)["status"] == "PASS"
    _study(example, tools=tools.format("latest"))
    assert codes(_study_result(cli, example)) == {"R-75.invalid"}


def test_biology_report_goldens(cli, machine_example):
    name, root = machine_example
    _contract(root, 'columns = { gene = "ensembl" }\np_value = "p"\n')
    _put(root, "fixture-results.tsv", "gene\tp\nENSG00000000001.1\t1e-20\nENSG00000000002\t0\n")
    _study(root, samples="sample\tgroup\tsite\nS1\tcase\tA\nS2\tcontrol\tB\n",
           design='condition_column = "group"\ncovariates = ["site"]\n',
           tools='\n[[tools]]\nname = "Bioconductor"\nversion = "3.21"\n')
    _put(root, "fixture-accession.txt", "study: " + "phs" + "9" * 6 + "\n")
    # The worked examples leave privacy unconfigured.
    append(root, "steward.toml", "\n[privacy]\nlocal_paths = false\n")
    _, report = cli.check(root, "data", "studies", "privacy")
    _valid(report)
    if name == "biology-geo":
        assert all(row["status"] == "PASS" for row in results(report, "R-75") + results(report, "R-83")
                   if "fixture" not in row["subject"])
    code, out, err = cli("study", "show", "biology-fixture", "--repo", root, "--format", "json")
    assert code == 0 and not err
    _check_golden(f"{name}.b01.json", {
        "study show": _valid(json.loads(out)),
        "check": {"schema": report["schema"], "results": [
            row for row in report["verdict"]["results"] if "fixture" in row["subject"] or row["rule"] == "R-07"
        ]},
    })
