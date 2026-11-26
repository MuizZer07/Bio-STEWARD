"""v0.7 benchmark checks (RELEASE_v0.7_SPEC): split integrity (R-45), dataset hashes (R-46)."""

import hashlib
import json

import pytest

from conftest import CONTRACT, append, codes, edit, one


def splits(root):
    return {n: (root / f"benchmarks/splits/{n}.txt").read_text().split() for n in ("train", "validation", "test")}


def write_split(root, name, ids):
    (root / f"benchmarks/splits/{name}.txt").write_text("\n".join(ids) + "\n")


def r45(cli, root):
    _, rep = cli.check(root, "benchmark")
    return one(rep, "R-45")


# ---------------------------------------------------------------- v0.7.0: R-45 split integrity
def test_worked_example_splits_pass(cli, example):
    res = r45(cli, example)
    assert res["status"] == "PASS", res
    assert "ID, group and temporal overlap as declared" in res["reason"]
    assert "R-45.checked" in codes(res)


def test_id_overlap_across_splits_fails(cli, example):
    s = splits(example)
    write_split(example, "train", s["train"] + [s["test"][0]])
    res = r45(cli, example)
    assert res["status"] == "FAIL" and "R-45.id_overlap" in codes(res)
    d = next(d for d in res["details"] if d["code"] == "R-45.id_overlap")
    assert d["value"] == 1 and s["test"][0] in d["message"]


def test_duplicate_within_a_split_fails(cli, example):
    s = splits(example)
    write_split(example, "test", s["test"] + [s["test"][0]])
    assert "R-45.duplicate_id" in codes(r45(cli, example))


def test_group_overlap_fails(cli, example):
    s = splits(example)
    moved = s["test"][0]                       # one sample of a test donor moves to train; its donor now spans both
    write_split(example, "test", s["test"][1:])
    write_split(example, "train", s["train"] + [moved])
    res = r45(cli, example)
    assert res["status"] == "FAIL" and "R-45.group_overlap" in codes(res) and "R-45.id_overlap" not in codes(res)


def test_sample_missing_from_metadata_is_incomplete(cli, example):
    s = splits(example)
    write_split(example, "test", s["test"] + ["S999_1"])
    res = r45(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-45.no_metadata" in codes(res)


def test_group_key_without_metadata_is_incomplete(cli, example):
    edit(example, CONTRACT, 'metadata  = "data/samples.csv"\n', "")
    res = r45(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-45.group_unchecked" in codes(res)


def test_blank_lines_and_comments_are_ignored(cli, example):
    s = splits(example)
    (example / "benchmarks/splits/test.txt").write_text("# test split\n\n" + "\n".join(f"  {i}  " for i in s["test"]) + "\n\n")
    assert r45(cli, example)["status"] == "PASS"


def _temporal(example, times):
    """Rewrite metadata with a time column; `times` maps split name -> one time for all of its samples."""
    s = splits(example)
    rows = ["sample_id,donor_id,collected"]
    for name, ids in s.items():
        rows += [f"{i},{i.split('_')[0].replace('S', 'D')},{times[name]}" for i in ids]
    (example / "data/meta.csv").write_text("\n".join(rows) + "\n")
    edit(example, CONTRACT, 'metadata  = "data/samples.csv"', 'metadata  = "data/meta.csv"')
    edit(example, CONTRACT, 'time_key  = "none"', 'time_key  = "collected"')
    edit(example, CONTRACT, 'id_column = "sample_id"', 'id_column = "sample_id"\ntemporal  = true')


@pytest.mark.parametrize("times,status,code", [
    ({"train": "2020-01-01", "validation": "2021-01-01", "test": "2022-06-30"}, "PASS", None),
    ({"train": "2020-01-01", "validation": "2021-01-01", "test": "2021-01-01"}, "PASS", None),   # ties allowed
    ({"train": "2022-01-01", "validation": "2021-01-01", "test": "2023-01-01"}, "FAIL", "R-45.temporal_order"),
    ({"train": "2020-01-01", "validation": "2021-01-01", "test": "2019-12-31T23:00:00"}, "FAIL", "R-45.temporal_order"),
    ({"train": "1", "validation": "2", "test": "3"}, "PASS", None),                               # numeric times
    ({"train": "2020-01-01", "validation": "soon", "test": "2023-01-01"}, "INCOMPLETE", "R-45.time_unparsed"),
    ({"train": "2020-01-01", "validation": "5", "test": "2023-01-01"}, "INCOMPLETE", "R-45.time_unparsed"),  # mixed kinds
])
def test_temporal_order(cli, example, times, status, code):
    _temporal(example, times)
    res = r45(cli, example)
    assert res["status"] == status, res
    if code:
        assert code in codes(res)


def test_not_temporal_means_times_are_not_ordered(cli, example):
    _temporal(example, {"train": "2022-01-01", "validation": "2021-01-01", "test": "2020-01-01"})
    edit(example, CONTRACT, "temporal  = true", "temporal  = false")
    res = r45(cli, example)
    assert res["status"] == "PASS" and "R-45.temporal_order" not in codes(res)


def test_old_contracts_without_the_new_fields_still_validate(cli, example):
    edit(example, CONTRACT, 'metadata  = "data/samples.csv"\n', "")
    edit(example, CONTRACT, 'id_column = "sample_id"\n', "")
    edit(example, CONTRACT, 'group_key = "donor_id"', 'group_key = "none"')
    _, rep = cli.check(example, "benchmark")
    assert one(rep, "R-02")["status"] == "PASS" and one(rep, "R-45")["status"] == "PASS"


def test_splits_command(cli, example):
    code, out, _ = cli("benchmark", "splits", "--repo", example, CONTRACT, "--json")
    assert code == 0
    doc = json.loads(out)
    assert doc["counts"] == {"train": 72, "validation": 24, "test": 24} and doc["id_overlap"] == [] and doc["group_overlap"] == []


# ---------------------------------------------------------------- v0.7.0: R-46 dataset hashes
def _dataset_source(example, source):
    edit(example, CONTRACT, 'source  = "data/expression.csv (generated by make_data.py, seed 20261123)"', f'source  = "{source}"')


def test_dataset_file_hash_matches(cli, example):
    _dataset_source(example, "data/expression.csv")
    _, rep = cli.check(example, "benchmark")
    assert one(rep, "R-46")["status"] == "PASS"
    append(example, "data/expression.csv", "tampered\n")
    _, rep = cli.check(example, "benchmark")
    res = one(rep, "R-46")
    assert res["status"] == "FAIL" and "R-46.hash_mismatch" in codes(res)


def test_external_dataset_source_is_not_hashed(cli, example):
    _dataset_source(example, "https://example.org/expression.csv")
    _, rep = cli.check(example, "benchmark")
    res = one(rep, "R-46")
    assert res["status"] == "NOT_APPLICABLE" and "R-46.not_a_repository_file" in codes(res)


def test_worked_example_dataset_hash_is_real():
    from conftest import EXAMPLE
    h = hashlib.sha256((EXAMPLE / "data/expression.csv").read_bytes()).hexdigest()
    assert h in (EXAMPLE / CONTRACT).read_text()


# ---------------------------------------------------------------- slice 2: R-47 results
RESULTS = {"test": {"candidate": {"auroc": 0.83}, "logistic-regression": {"auroc": 0.78}, "majority-class": {"auroc": 0.5}}}


def _results(example, doc=None, extra=""):
    if 'file   = "results/benchmark.json"' not in (example / CONTRACT).read_text():
        append(example, CONTRACT, f'\n[results]\nfile   = "results/benchmark.json"\n{extra}')
    if doc is not None:
        (example / "results").mkdir(exist_ok=True)
        (example / "results/benchmark.json").write_text(doc if isinstance(doc, str) else json.dumps(doc))


def r47(cli, root):
    _, rep = cli.check(root, "benchmark")
    return one(rep, "R-47")


def test_results_not_declared_is_not_applicable(cli, example):
    assert r47(cli, example)["status"] == "NOT_APPLICABLE"


def test_results_file_missing_is_incomplete(cli, example):
    _results(example)
    res = r47(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-47.no_results" in codes(res)


def test_complete_results_pass_and_thresholds_are_reported_exactly(cli, example):
    _results(example, RESULTS)   # 0.83 - 0.78 is exactly 0.05 as written; binary floats would make it 0.04999...
    res = r47(cli, example)
    assert res["status"] == "PASS", res
    met = next(d for d in res["details"] if d["code"] == "R-47.threshold_met")
    assert "0.05" in met["message"] and "logistic-regression" in met["message"]


def test_a_threshold_not_met_is_reported_without_changing_the_status(cli, example):
    doc = json.loads(json.dumps(RESULTS))
    doc["test"]["candidate"]["auroc"] = 0.80
    _results(example, doc)
    res = r47(cli, example)
    assert res["status"] == "PASS" and "R-47.threshold_not_met" in codes(res)
    assert "not gating" in res["reason"] or "thresholds reported" in res["reason"]


def test_missing_baseline_result_is_incomplete(cli, example):
    doc = json.loads(json.dumps(RESULTS))
    del doc["test"]["majority-class"]
    _results(example, doc)
    res = r47(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-47.missing_result" in codes(res)
    assert "majority-class" in next(d for d in res["details"] if d["code"] == "R-47.missing_result")["message"]


@pytest.mark.parametrize("value,status,code", [('"TBD"', "INCOMPLETE", "sentinel"), ('"unknown"', "UNKNOWN", "sentinel"),
                                               ('"high"', "FAIL", "R-47.not_numeric"), ("true", "FAIL", "R-47.not_numeric")])
def test_cell_values(cli, example, value, status, code):
    _results(example, json.dumps(RESULTS).replace("0.5", value))
    res = r47(cli, example)
    assert res["status"] == status and code in codes(res)


def test_undeclared_results_are_listed_not_counted(cli, example):
    doc = json.loads(json.dumps(RESULTS))
    doc["test"]["random-forest"] = {"auroc": 0.8}
    _results(example, doc)
    res = r47(cli, example)
    assert res["status"] == "PASS" and "R-47.undeclared" in codes(res)


def test_required_splits_must_exist(cli, example):
    _results(example, RESULTS, extra='splits = ["test", "holdout"]\n')
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.unknown_split" in codes(res)


def test_results_command(cli, example):
    _results(example, RESULTS)
    code, out, _ = cli("benchmark", "results", "--repo", example, CONTRACT, "--json")
    doc = json.loads(out)
    assert code == 0 and doc["missing"] == [] and doc["thresholds"][0]["state"] == "met"


# ---------------------------------------------------------------- slice 2: R-48 comparison provenance
import sys  # noqa: E402

CMP = "import json; open('results/comparison.json','w').write(json.dumps({'ci': [0.01, 0.09]}))"
SPLIT_INPUTS = [a for n in ("train", "validation", "test") for a in ("--input", f"benchmarks/splits/{n}.txt")]


@pytest.fixture
def comparing(example, monkeypatch):
    append(example, "steward.toml", "\n[run]\n")
    append(example, CONTRACT, "")
    text = (example / CONTRACT).read_text().replace("alpha     = 0.05\n", 'alpha     = 0.05\noutput    = "results/comparison.json"\n', 1)
    (example / CONTRACT).write_text(text)
    (example / "results").mkdir(exist_ok=True)
    (example / "compare.py").write_text(CMP)
    monkeypatch.chdir(example)
    return example


def _compare(cli, *extra):
    code, _, err = cli("run", *SPLIT_INPUTS, "--output", "results/comparison.json", *extra, "--", sys.executable, "compare.py")
    assert code == 0, err


def r48(cli, root):
    _, rep = cli.check(root, "benchmark")
    return one(rep, "R-48")


def test_comparison_from_a_recorded_run_on_the_current_splits_passes(cli, comparing):
    _compare(cli, "--seed", "20261123", "--param", "resamples=2000")
    res = r48(cli, comparing)
    assert res["status"] == "PASS", res


def test_comparison_output_missing_is_incomplete(cli, comparing):
    assert r48(cli, comparing)["status"] == "INCOMPLETE"


def test_comparison_not_from_a_run_fails(cli, comparing):
    (comparing / "results/comparison.json").write_text("{}")
    res = r48(cli, comparing)
    assert res["status"] == "FAIL" and "R-48.not_from_run" in codes(res)


def test_comparison_from_older_splits_fails(cli, comparing):
    _compare(cli, "--seed", "20261123", "--param", "resamples=2000")
    s = splits(comparing)
    write_split(comparing, "test", s["test"][1:])
    write_split(comparing, "train", s["train"] + [s["test"][0]])
    res = r48(cli, comparing)
    assert res["status"] == "FAIL" and "R-48.inputs_changed" in codes(res)


def test_comparison_run_without_the_split_inputs_fails(cli, comparing):
    code, _, err = cli("run", "--output", "results/comparison.json", "--seed", "20261123", "--param", "resamples=2000",
                       "--", sys.executable, "compare.py")
    assert code == 0, err
    res = r48(cli, comparing)
    assert res["status"] == "FAIL" and "R-48.inputs_changed" in codes(res)


def test_confirmatory_procedure_must_be_recorded(cli, comparing):
    _compare(cli)  # no seed, no resamples
    res = r48(cli, comparing)
    assert res["status"] == "INCOMPLETE" and "R-48.procedure_unrecorded" in codes(res)


# ---------------------------------------------------------------- slice 3: R-49 leakage declarations
TYPES = ("near_duplicate", "batch_confounding", "preprocessing_fit", "label_leakage", "test_tuning", "undeclared_groups", "test_reuse")


def _leakage(example, **decl):
    """Replace the example's [leakage] table with `decl` (type -> TOML value)."""
    text = (example / CONTRACT).read_text()
    text = text.split("\n[leakage]")[0].rstrip("\n") + "\n"
    if decl is not None:
        text += "\n[leakage]\n" + "".join(f"{k} = {v}\n" for k, v in decl.items())
    (example / CONTRACT).write_text(text)


def r49(cli, root):
    _, rep = cli.check(root, "benchmark")
    return one(rep, "R-49")


ALL_NA = {t: '{ status = "not_applicable", reason = "r" }' for t in TYPES}


def test_worked_example_declares_every_type(cli, example):
    res = r49(cli, example)
    assert res["status"] == "PASS", res
    assert "declared, not verified" in res["reason"]


def test_an_undeclared_type_on_a_confirmatory_contract_is_unknown(cli, example):
    decl = dict(ALL_NA)
    del decl["test_tuning"]
    _leakage(example, **decl)
    res = r49(cli, example)
    assert res["status"] == "UNKNOWN" and "R-49.undeclared" in codes(res)
    assert "test_tuning" in next(d for d in res["details"] if d["code"] == "R-49.undeclared")["message"]


@pytest.mark.parametrize("value,status,code", [
    ('"TBD"', "INCOMPLETE", "sentinel"),
    ('"unknown"', "UNKNOWN", "R-49.undeclared"),
    ('{ status = "checked", evidence = "missing.txt" }', "INCOMPLETE", "R-49.evidence_missing"),
    ('{ status = "checked", evidence = "make_data.py#batch" }', "PASS", None),
    ('{ status = "checked" }', "INCOMPLETE", "R-49.evidence_missing"),
])
def test_declaration_forms(cli, example, value, status, code):
    _leakage(example, **{**ALL_NA, "near_duplicate": value})
    res = r49(cli, example)
    assert res["status"] == status, res
    if code:
        assert code in codes(res)


def test_an_unknown_type_key_fails(cli, example):
    _leakage(example, **{**ALL_NA, "near_duplicates": '{ status = "not_applicable", reason = "typo" }'})
    res = r49(cli, example)
    assert res["status"] == "FAIL" and "R-49.unknown_type" in codes(res)


def test_exploratory_contracts_are_advisory(cli, example):
    edit(example, CONTRACT, 'analysis = "confirmatory"', 'analysis = "exploratory"')
    _leakage(example, **{"near_duplicate": '"unknown"'})
    res = r49(cli, example)
    assert res["status"] == "NOT_APPLICABLE" and "R-49.undeclared" in codes(res)
    append(example, "steward.toml", "\n[benchmark]\nrequire_leakage = true\n")
    assert r49(cli, example)["status"] == "UNKNOWN"


# ---------------------------------------------------------------- pre-release review of v0.7 (J1 - J11)
def _meta_rows(example):
    return (example / "data/samples.csv").read_text().splitlines()


def _move_group(example, sample, donor):
    rows = [r if not r.startswith(sample + ",") else f"{sample},{donor}," + ",".join(r.split(",")[2:]) for r in _meta_rows(example)]
    (example / "data/samples.csv").write_text("\n".join(rows) + "\n")


def test_J1_one_metadata_snapshot_decides_r45(cli, example, monkeypatch):
    from pathlib import Path
    s = splits(example)
    original = (example / "data/samples.csv").read_text()
    train_donor = next(r.split(",")[1] for r in _meta_rows(example) if r.startswith(s["train"][0] + ","))
    _move_group(example, s["test"][0], train_donor)          # stable revision: a donor spans train and test
    real_bytes, real_text = Path.read_bytes, Path.read_text
    reads = []

    def hook(self, data):
        if self.name == "samples.csv":
            reads.append(1)
            self.write_text(original)                         # a save lands right after the read
        return data
    monkeypatch.setattr(Path, "read_bytes", lambda self: hook(self, real_bytes(self)))
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: hook(self, real_text(self, *a, **k)))
    res = r45(cli, example)
    monkeypatch.undo()
    assert len(reads) == 1 and res["status"] == "FAIL" and "R-45.group_overlap" in codes(res)


@pytest.mark.parametrize("mutate,code,status", [
    (lambda rows: rows + [rows[-1].rsplit(",", 3)[0] + ",D999,0,1"], "R-45.metadata_invalid", "FAIL"),   # duplicate ID
    (lambda rows: ["sample_id,donor_id,donor_id,responder"] + rows[1:], "R-45.metadata_invalid", "FAIL"),  # duplicate header
    (lambda rows: rows[:-1] + [rows[-1].split(",")[0]], "R-45.metadata_invalid", "FAIL"),               # short row
    (lambda rows: rows[:-1] + [rows[-1].split(",")[0] + ",,0,1"], "R-45.blank_group", "INCOMPLETE"),     # blank group
])
def test_J2_ambiguous_metadata_is_refused(cli, example, mutate, code, status):
    (example / "data/samples.csv").write_text("\n".join(mutate(_meta_rows(example))) + "\n")
    res = r45(cli, example)
    assert res["status"] == status and code in codes(res), res


@pytest.mark.parametrize("times,status,code", [
    ({"train": "NaN", "validation": "2", "test": "3"}, "INCOMPLETE", "R-45.time_unparsed"),
    ({"train": "9007199254740993", "validation": "9007199254740992", "test": "9007199254740994"}, "FAIL", "R-45.temporal_order"),
    ({"train": "20200101", "validation": "2020-01-02", "test": "2020-01-03"}, "INCOMPLETE", "R-45.time_unparsed"),
])
def test_J3_temporal_order_is_established_not_assumed(cli, example, times, status, code):
    _temporal(example, times)
    res = r45(cli, example)
    assert res["status"] == status and code in codes(res), res
    if "20200101" in times.values():
        assert "YYYY-MM-DD" in next(d for d in res["details"] if d["code"] == code)["message"]


def test_J3_temporal_without_a_time_key_is_incomplete(cli, example):
    edit(example, CONTRACT, 'id_column = "sample_id"', 'id_column = "sample_id"\ntemporal  = true')
    res = r45(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-45.time_unchecked" in codes(res)


def test_J4_required_splits_cannot_be_empty(cli, example):
    _results(example, {}, extra="splits = []\n")
    _, rep = cli.check(example, "benchmark")
    assert one(rep, "R-02")["status"] == "FAIL"


def test_J4_a_baseline_named_candidate_is_refused(cli, example):
    edit(example, CONTRACT, 'name      = "majority-class"', 'name      = "candidate"')
    _results(example, {"test": {"candidate": {"auroc": 0.83}, "logistic-regression": {"auroc": 0.78}}})
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.reserved_name" in codes(res)


def test_J4_duplicate_keys_in_results_are_refused(cli, example):
    _results(example, json.dumps(RESULTS)[:-3] + ', "auroc": 0.9}}}')
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.invalid" in codes(res)


def test_J5_nonfinite_cells_fail(cli, example):
    _results(example, json.dumps(RESULTS).replace("0.5", "NaN"))
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.not_numeric" in codes(res)


def test_J5_toml_nan_is_a_failure_not_an_internal_error(cli, example):
    append(example, CONTRACT, '\n[results]\nfile   = "results/benchmark.toml"\n')
    (example / "results").mkdir(exist_ok=True)
    (example / "results/benchmark.toml").write_text('[test.candidate]\nauroc = nan\n[test.logistic-regression]\nauroc = 0.78\n'
                                                    '[test.majority-class]\nauroc = 0.5\n')
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.not_numeric" in codes(res)
    code, _, _ = cli("benchmark", "results", "--repo", example, CONTRACT)
    assert code == 1


def test_J5_thresholds_use_the_literal_written(cli, example):
    edit(example, CONTRACT, "value      = 0.05", "value      = 0.050000000000000001")
    _results(example, RESULTS)
    res = r47(cli, example)
    assert res["status"] == "PASS" and "R-47.threshold_not_met" in codes(res)
    assert "0.050000000000000001" in next(d for d in res["details"] if d["code"] == "R-47.threshold_not_met")["message"]


def test_J6_a_run_that_did_not_write_the_output_is_not_provenance(cli, comparing):
    (comparing / "results/comparison.json").write_text('{"ci": [0.01, 0.09]}')
    code, _, err = cli("run", *SPLIT_INPUTS, "--output", "results/comparison.json", "--seed", "20261123",
                       "--param", "resamples=2000", "--", sys.executable, "-c", "pass")
    assert code == 0, err
    res = r48(cli, comparing)
    assert res["status"] == "FAIL" and "R-48.not_from_run" in codes(res)


def test_J6_a_run_labelled_for_another_contract_does_not_count(cli, comparing):
    _compare(cli, "--seed", "20261123", "--param", "resamples=2000", "--contract", "other-benchmark")
    res = r48(cli, comparing)
    assert res["status"] == "FAIL" and "R-48.not_from_run" in codes(res)


def test_J6_the_best_qualifying_run_decides(cli, comparing):
    _compare(cli, "--seed", "20261123", "--param", "resamples=2000")
    _compare(cli, "--seed", "20261123", "--param", "resamples=5")    # same bytes, wrong procedure, later
    assert r48(cli, comparing)["status"] == "PASS"


def test_J6_a_missing_split_file_is_incomplete(cli, comparing):
    _compare(cli, "--seed", "20261123", "--param", "resamples=2000")
    (comparing / "benchmarks/splits/validation.txt").unlink()
    res = r48(cli, comparing)
    assert res["status"] == "INCOMPLETE" and "R-48.split_missing" in codes(res)


def test_J8_an_advisory_unknown_does_not_block_through_r02(cli, example):
    edit(example, CONTRACT, 'analysis = "confirmatory"', 'analysis = "exploratory"')
    _leakage(example, **{**ALL_NA, "near_duplicate": '"unknown"', "test_reuse": '"TBD"'})
    _, rep = cli.check(example, "benchmark")
    assert one(rep, "R-02")["status"] == "PASS" and one(rep, "R-49")["status"] == "NOT_APPLICABLE"


def test_J9_a_missing_split_file_is_incomplete_and_reported_by_the_command(cli, example):
    (example / "benchmarks/splits/test.txt").unlink()
    res = r45(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-45.split_missing" in codes(res)
    code, out, _ = cli("benchmark", "splits", "--repo", example, CONTRACT, "--json")
    assert code == 1 and any(p["code"] == "R-45.split_missing" for p in json.loads(out)["problems"])


def test_J9_an_unreadable_split_file_is_named(cli, example):
    (example / "benchmarks/splits/test.txt").write_bytes(b"\xff\xfe\x00bad\n")
    res = r45(cli, example)
    assert res["status"] == "INCOMPLETE"
    d = next(d for d in res["details"] if d["code"] == "R-45.split_unreadable")
    assert d["path"] == "benchmarks/splits/test.txt"


def test_J9_splits_command_reports_time_ranges(cli, example):
    _temporal(example, {"train": "2020-01-01", "validation": "2021-01-01", "test": "2022-06-30"})
    code, out, _ = cli("benchmark", "splits", "--repo", example, CONTRACT, "--json")
    assert code == 0 and json.loads(out)["time_range"]["test"] == ["2022-06-30", "2022-06-30"]


def test_J9_results_command_shows_values_and_handles_malformed_input(cli, example):
    _results(example, RESULTS)
    code, out, _ = cli("benchmark", "results", "--repo", example, CONTRACT, "--json")
    assert json.loads(out)["cells"]["test/candidate/auroc"] == "0.83"
    (example / "results/benchmark.json").write_text("{not json")
    code, _, err = cli("benchmark", "results", "--repo", example, CONTRACT)
    assert code == 65 and "cannot be read" in err


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "outside"
    d.mkdir()
    (d / "f.csv").write_text("sample_id,donor_id\n")
    return d / "f.csv"


def test_J10_metadata_outside_the_repository_is_refused(cli, example, outside):
    (example / "data/link.csv").symlink_to(outside)
    edit(example, CONTRACT, 'metadata  = "data/samples.csv"', 'metadata  = "data/link.csv"')
    res = r45(cli, example)
    assert res["status"] == "FAIL" and "R-45.path_outside" in codes(res)


def test_J10_dataset_and_results_outside_the_repository(cli, example, outside):
    (example / "data/link.csv").symlink_to(outside)
    _dataset_source(example, "data/link.csv")
    _, rep = cli.check(example, "benchmark")
    assert one(rep, "R-46")["status"] == "NOT_APPLICABLE"
    (example / "results").mkdir()
    (example / "results/benchmark.json").symlink_to(outside)
    _results(example)
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.path_outside" in codes(res)


def test_J10_leakage_evidence_outside_the_repository(cli, example, outside):
    (example / "data/link.csv").symlink_to(outside)
    _leakage(example, **{**ALL_NA, "near_duplicate": '{ status = "checked", evidence = "data/link.csv" }'})
    res = r49(cli, example)
    assert res["status"] == "INCOMPLETE" and "R-49.evidence_missing" in codes(res)


def test_J11_the_freezing_companion_binds_every_split():
    from conftest import REPO
    text = (REPO / "skills/benchmark-contract/freezing.md").read_text()
    for split in ("train", "validation", "test"):
        assert f"benchmarks/splits/{split}.txt" in text, split
    assert "--expires" in text


def test_J11_the_documented_freeze_changes_with_every_split(cli, example, monkeypatch):
    append(example, "steward.toml", "\n[integrity]\n")
    monkeypatch.chdir(example)
    cohort = [f"benchmarks/splits/{n}.txt" for n in ("train", "validation", "test")]

    def snapshot():
        code, out, err = cli("freeze", "design", "--files", CONTRACT, "data/samples.csv", "--cohort", *cohort, "--dry-run")
        assert code == 0, err
        return out.split()[1]
    first = snapshot()
    for name in ("train", "validation", "test"):
        p = example / f"benchmarks/splits/{name}.txt"
        before = p.read_text()
        p.write_text(before + "S999_9\n")
        assert snapshot() != first, name
        p.write_text(before)


# ---------------------------------------------------------------- v0.8 review: K9, K10
def test_K9_no_required_split_is_a_failure_not_a_complete_matrix(cli, example):
    edit(example, CONTRACT, 'role     = "test"', 'role     = "validation"')
    _results(example, {})
    res = r47(cli, example)
    assert res["status"] == "FAIL" and "R-47.no_required_splits" in codes(res)
    code, _, _ = cli("benchmark", "results", "--repo", example, CONTRACT, "--json")
    assert code == 1


def test_K10_read_errors_name_the_split_file(cli, example, monkeypatch):
    from pathlib import Path
    real = Path.read_bytes

    def denied(self):
        if self.name == "test.txt":
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", denied)
    res = r45(cli, example)
    d = next(d for d in res["details"] if d["code"] == "R-45.split_unreadable")
    assert res["status"] == "INCOMPLETE" and d["path"] == "benchmarks/splits/test.txt"
    code, out, _ = cli("benchmark", "splits", "--repo", example, CONTRACT, "--json")
    assert code == 1 and any(p["code"] == "R-45.split_unreadable" for p in json.loads(out)["problems"])
