"""Per-rule acceptance tests R-01 … R-07: pass, fail, missing evidence, malformed, out of coverage (spec §8.1).

Regression goldens live in test_determinism.py.
"""

import json

from conftest import CONTRACT, PRIOR, append, codes, edit, gate, one, results


# ---------------------------------------------------------------- example baseline
def test_example_passes_every_applicable_rule(cli, example):
    code, rep = cli.check(example)
    assert code == 0 and gate(rep)["eligible"]
    assert rep["verdict"]["summary"]["counts"] == {"PASS": 28, "FAIL": 0, "INCOMPLETE": 0, "UNKNOWN": 0, "NOT_APPLICABLE": 55}


# ---------------------------------------------------------------- R-01 config.valid
def test_R01_unknown_key_fails_and_other_rules_not_evaluated(cli, example):
    append(example, "steward.toml", "\n[polcy]\nx = 1\n")
    code, rep = cli.check(example)
    assert one(rep, "R-01")["status"] == "FAIL" and code == 1
    for rule in ("R-02", "R-03", "R-04", "R-05", "R-06", "R-07"):
        res = one(rep, rule)
        assert res["status"] == "UNKNOWN" and "config is not valid" in res["reason"]


def test_R01_gate_without_R01_fails(cli, example):
    append(example, "steward.toml", '\n[gates.quick]\nrequire = ["R-02"]\n')
    _, rep = cli.check(example)
    assert one(rep, "R-01")["status"] == "FAIL"


def test_R01_malformed_toml(cli, example):
    append(example, "steward.toml", "\n[steward\n")
    _, rep = cli.check(example)
    res = one(rep, "R-01")
    assert res["status"] == "FAIL" and "parse" in codes(res)


def test_R01_unsupported_schema_version(cli, example):
    edit(example, "steward.toml", 'schema  = "steward.toml/0.2"', 'schema  = "steward.toml/9"')
    _, rep = cli.check(example)
    res = one(rep, "R-01")
    assert res["status"] == "FAIL" and "unsupported config schema steward.toml/9" in res["reason"]


def test_R01_path_escaping_root_fails(cli, example):
    edit(example, "steward.toml", 'contracts  = ["benchmarks/**/*.contract.toml"]', 'contracts  = ["../x/*.toml"]')
    _, rep = cli.check(example)
    res = one(rep, "R-01")
    assert res["status"] == "FAIL" and "path_escapes_root" in codes(res)


def test_R01_repo_id_must_be_uuid4(cli, example):
    text = (example / "steward.toml").read_text()
    rid = text.split('repo_id = "')[1].split('"')[0]
    edit(example, "steward.toml", rid, "not-a-uuid")
    _, rep = cli.check(example)
    assert one(rep, "R-01")["status"] == "FAIL"


# ---------------------------------------------------------------- R-02 contract.valid
def test_R02_sentinel_in_non_deferrable_field_fails(cli, example):
    edit(example, CONTRACT, 'title    = "Responder', 'title    = "TBD"\n# "Responder')
    _, rep = cli.check(example)
    res = one(rep, "R-02")
    assert res["status"] == "FAIL" and any("not deferrable" in d.get("message", "") for d in res["details"])


def test_R02_tbd_is_incomplete(cli, example):
    edit(example, CONTRACT, "value      = 0.05", 'value      = "TBD"')
    code, rep = cli.check(example)
    res = one(rep, "R-02")
    assert res["status"] == "INCOMPLETE" and {"field": "thresholds[0].value", "value": "TBD", "code": "sentinel"} in res["details"]
    assert code == 2


def test_R02_malformed_toml_and_wrong_types(cli, example):
    append(example, CONTRACT, "\n[[broken\n")
    _, rep = cli.check(example)
    assert one(rep, "R-02")["status"] == "FAIL"
    assert one(rep, "R-03")["status"] == "UNKNOWN"  # not evaluated: R-02 failed; never silently skipped


def test_R02_wrong_type_fails(cli, example):
    edit(example, CONTRACT, "resamples = 2000", 'resamples = "many"')
    _, rep = cli.check(example)
    assert one(rep, "R-02")["status"] == "FAIL"


def test_R02_unknown_hash_is_unknown(cli, example):
    edit(example, CONTRACT, 'sha256  = "8e74100e93ac4830be76b1e8d342d534bec629774da6db9a82da29d8f98c3f13"', 'sha256  = "unknown"')
    code, rep = cli.check(example)
    assert one(rep, "R-02")["status"] == "UNKNOWN" and code == 3


def test_R02_no_files_is_not_applicable(cli, example):
    (example / CONTRACT).unlink()
    _, rep = cli.check(example)
    res = one(rep, "R-02")
    assert res["status"] == "NOT_APPLICABLE" and res["subject"] == "."
    assert one(rep, "R-04")["status"] == "INCOMPLETE"  # confirmatory profile still requires a contract


# ---------------------------------------------------------------- R-03 contract.consistent
def test_R03_undefined_primary_metric(cli, example):
    edit(example, CONTRACT, 'primary = "auroc"', 'primary = "auprc"')
    code, rep = cli.check(example)
    res = one(rep, "R-03")
    assert res["status"] == "FAIL" and "R-03.primary_undefined" in codes(res) and code == 1


def test_R03_duplicate_contract_ids_across_files(cli, example):
    (example / "benchmarks/copy.contract.toml").write_text((example / CONTRACT).read_text())
    _, rep = cli.check(example)
    assert [r["status"] for r in results(rep, "R-03")] == ["FAIL", "FAIL"]


def test_R03_no_test_role(cli, example):
    edit(example, CONTRACT, 'name     = "test"\nrole     = "test"', 'name     = "test"\nrole     = "dev"')
    _, rep = cli.check(example)
    assert "R-03.no_test_role" in codes(one(rep, "R-03"))


def test_R03_missing_ids_file_is_incomplete(cli, example):
    (example / "benchmarks/splits/test.txt").unlink()
    code, rep = cli.check(example)
    res = one(rep, "R-03")
    assert res["status"] == "INCOMPLETE" and "R-03.missing_file" in codes(res) and code == 2


def test_R03_confirmatory_unknown_alpha_is_unknown(cli, example):
    edit(example, CONTRACT, "alpha     = 0.05", 'alpha     = "unknown"')
    _, rep = cli.check(example)
    res = one(rep, "R-03")
    assert res["status"] == "UNKNOWN" and "R-03.confirmatory_unspecified" in codes(res)


def test_R03_confirmatory_without_thresholds_fails(cli, example):
    text = (example / CONTRACT).read_text()
    start, end = text.index("[[thresholds]]"), text.index("[exclusions]")
    (example / CONTRACT).write_text(text[:start] + text[end:])
    _, rep = cli.check(example)
    assert "R-03.confirmatory_without_thresholds" in codes(one(rep, "R-03"))


def test_R03_referenced_path_outside_repository_fails(cli, example):
    edit(example, CONTRACT, 'implementation = "analysis/metrics.py"', 'implementation = "../../etc/passwd"')
    _, rep = cli.check(example)
    assert "R-03.path_outside" in codes(one(rep, "R-03"))


# ---------------------------------------------------------------- R-04 / R-06 required under confirmatory
def test_R04_R06_not_applicable_under_exploratory(cli, example):
    edit(example, "steward.toml", 'profile = "confirmatory"', 'profile = "exploratory"')
    _, rep = cli.check(example)
    for rule in ("R-04", "R-06"):
        res = one(rep, rule)
        assert res["status"] == "NOT_APPLICABLE" and "exploratory" in res["reason"]


def test_R04_exploratory_contract_does_not_satisfy_confirmatory_profile(cli, example):
    edit(example, CONTRACT, 'analysis = "confirmatory"', 'analysis = "exploratory"')
    _, rep = cli.check(example)
    assert one(rep, "R-04")["status"] == "INCOMPLETE"


def test_R06_missing_record_is_incomplete(cli, example):
    (example / PRIOR).unlink()
    code, rep = cli.check(example)
    assert one(rep, "R-06")["status"] == "INCOMPLETE" and code == 2


def test_R06_record_without_closest_method(cli, example):
    edit(example, PRIOR, 'relation   = "closest_method"', 'relation   = "related"')
    _, rep = cli.check(example)
    assert one(rep, "R-06")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- R-05 prior_work.valid
def test_R05_malformed_identifier_fails(cli, example):
    edit(example, PRIOR, 'identifier = "url:https://example.org/fictional/donor-aware-classifier"', 'identifier = "doi:11.x"')
    _, rep = cli.check(example)
    assert one(rep, "R-05")["status"] == "FAIL"


def test_R05_identifier_syntax_variants():
    from steward.models import identifier_ok

    good = ["doi:10.1038/s41586-020-2649-2", "pmid:12345678", "arxiv:2401.01234v2", "arxiv:q-bio/0601001",
            "url:https://example.org/x"]
    bad = ["doi:11.x", "10.1038/x", "pmid:0123", "arxiv:abc", "url:ftp://x.org", "url:https://nodot"]
    assert all(identifier_ok(g) for g in good)
    assert not any(identifier_ok(b) for b in bad)


def test_R05_comparison_refers_to_unlisted_work(cli, example):
    edit(example, PRIOR, 'W2 = "Ignores donor structure"', 'W9 = "Ignores donor structure"')
    _, rep = cli.check(example)
    res = one(rep, "R-05")
    assert res["status"] == "FAIL" and "R-05.unknown_work" in codes(res)


def test_R05_tbd_incomplete_unknown_identifier_unknown(cli, example):
    edit(example, PRIOR, 'summary    = "Fictional work: mixed-effects', 'summary    = "TBD"\n# "')
    _, rep = cli.check(example)
    assert one(rep, "R-05")["status"] == "INCOMPLETE"
    edit(example, PRIOR, 'summary    = "TBD"', 'summary    = "x"')
    edit(example, PRIOR, 'identifier = "url:https://example.org/fictional/logistic-baselines"', 'identifier = "unknown"')
    _, rep = cli.check(example)
    assert one(rep, "R-05")["status"] == "UNKNOWN"


def test_R05_novelty_judgment_is_reported_never_assessed(cli, example):
    _, rep = cli.check(example)
    res = one(rep, "R-05")
    judg = [d for d in res["details"] if d["code"] == "R-05.human_judgment"]
    assert judg and "not verified" in judg[0]["note"]
    edit(example, PRIOR, 'novelty = "pending"', 'novelty = "TBD"')  # not deferrable: a human field
    _, rep = cli.check(example)
    assert one(rep, "R-05")["status"] == "FAIL"


def test_R05_malformed_toml(cli, example):
    append(example, PRIOR, "\nnovelty = = 1\n")
    _, rep = cli.check(example)
    assert one(rep, "R-05")["status"] == "FAIL"


# ---------------------------------------------------------------- R-07 privacy.denylist
PRIVACY = '\n[privacy]\ndenylist_file = ".steward/private/denylist.txt"\n'


def test_R07_not_configured_is_not_applicable(cli, example):
    _, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "NOT_APPLICABLE"


def test_R07_pass_and_fail_without_leaking_the_term(cli, example):
    append(example, "steward.toml", PRIVACY)
    append(example, ".steward/private/denylist.txt", "# private names\nProjectNightjar\nzz-collaborator\n")
    code, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "PASS" and code == 0
    append(example, "README.md", "\nInternal codename: projectnightjar.\n")
    code, rep = cli.check(example)
    res = one(rep, "R-07")
    assert res["status"] == "FAIL" and code == 1
    # FB-2 (0.8.1): the term is named by its list and line, never by an index that skips comments
    assert {"code": "R-07.hit", "path": "README.md", "term": "denylist:2"} == {k: res["details"][0][k] for k in ("code", "path", "term")}
    blob = json.dumps(rep).lower()
    assert "nightjar" not in blob  # the report never contains the term


def test_R07_whole_words_only(cli, example):
    append(example, "steward.toml", PRIVACY)
    append(example, ".steward/private/denylist.txt", "jar\n")
    append(example, "README.md", "\nnightjar is one word\n")
    _, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "PASS"


def test_R07_missing_or_invalid_denylist_is_unknown(cli, example):
    append(example, "steward.toml", PRIVACY)
    code, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "UNKNOWN" and code == 3
    (example / ".steward/private").mkdir(parents=True)
    (example / ".steward/private/denylist.txt").write_bytes(b"\xff\xfe bad")
    _, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "UNKNOWN"
    (example / ".steward/private/denylist.txt").write_text("# only comments\n\n")
    _, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "UNKNOWN"  # an empty denylist checks nothing; never PASS


def test_R07_binary_and_non_utf8_files_are_listed_not_evaluated(cli, example):
    append(example, "steward.toml", PRIVACY)
    append(example, ".steward/private/denylist.txt", "secretterm\n")
    (example / "data/blob.bin").write_bytes(b"\x00\x01secretterm")
    (example / "data/latin1.txt").write_bytes("café secretterm".encode("latin-1"))
    _, rep = cli.check(example)
    assert one(rep, "R-07")["status"] == "PASS"
    assert {"path": "data/blob.bin", "reason": "binary"} in rep["verdict"]["coverage"]["not_evaluated"]
    assert {"path": "data/latin1.txt", "reason": "not UTF-8"} in rep["verdict"]["coverage"]["not_evaluated"]
