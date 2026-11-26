"""v0.6.0 evidence: diff run (repeatability), diff impact, claim map (R-40), prior-work links (R-41)."""

import json
import sys

import pytest

from conftest import codes, one, PRIOR, edit

PY = sys.executable
TRAIN = "import json, sys; v = float(sys.argv[1]); open('results/metrics.json','w').write(json.dumps({'auroc': v, 'gain': v - 0.80}))"


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[run]\n\n[evidence]\n')
    (tmp_path / "results").mkdir()
    (tmp_path / "data.csv").write_text("x\n1\n")
    (tmp_path / "train.py").write_text(TRAIN)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(cli, value, metrics=True):
    args = ["run", "--input", "data.csv", "--output", "results/metrics.json"]
    if metrics:
        args += ["--metrics", "results/metrics.json"]
    code, _, err = cli(*args, "--", PY, "train.py", str(value))
    assert code == 0, err
    return err.split("run ")[1].split()[0]


def test_diff_run_repeatable_and_tolerance(cli, repo):
    a, b = run(cli, 0.87), run(cli, 0.87)
    code, out, _ = cli("diff", "run", a, b)
    assert code == 0 and "repeatable within tolerance" in out and "Scientific reproducibility is not assessed" in out
    c = run(cli, 0.8705)
    code, out, _ = cli("diff", "run", a, c)
    assert code == 1 and "DIFF /auroc" in out
    code, out, _ = cli("diff", "run", a, c, "--default-tol", "abs:0.001")
    assert code == 0
    code, out, _ = cli("diff", "run", a, c, "--tol", "auroc=abs:0.001")
    assert code == 1 and "DIFF /gain" in out  # only auroc had a tolerance


def test_diff_run_lists_environment_and_code_differences(cli, repo):
    a = run(cli, 0.87)
    with open(repo / "train.py", "a") as f:
        f.write("\n# changed\n")
    b = run(cli, 0.87)
    code, out, _ = cli("diff", "run", a, b, "--json")
    res = json.loads(out)
    assert res["repeatable"] and any(e["field"] == "code" for e in res["environment_differences"])


def test_diff_impact_stale_after_input_or_code_change(cli, repo):
    run(cli, 0.87)
    code, out, _ = cli("diff", "impact")
    assert code == 0 and out.startswith("current") and "1 of 1 files under results/" in out
    (repo / "data.csv").write_text("x\n2\n")
    code, out, _ = cli("diff", "impact")
    assert code == 1 and "stale" in out and "data.csv" in out


def test_diff_impact_downstream_paper_value(cli, repo):
    run(cli, 0.87)
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[paper.main]\ndir = "paper"\nmain = "main.tex"\n')
    (repo / "paper").mkdir()
    (repo / "paper/values.toml").write_text('schema = "steward.values/0.1"\n[values.auroc]\nsource = "results/metrics.json"\npointer = "/auroc"\n')
    (repo / "train.py").write_text(TRAIN + "\n# v2\n")
    _, out, _ = cli("diff", "impact", "--json")
    res = json.loads(out)
    assert res["downstream"] == [{"paper": "main", "value": "auroc", "source": "results/metrics.json"}]


def claims(repo, body):
    (repo / "development/claims.toml").write_text('schema = "steward.claims/0.1"\n' + body)


def claim(run_id, value=0.07, tol=0.0001, source='source = "results/metrics.json"\npointer = "/gain"'):
    return f'[[claims]]\nid = "gain"\ntext = "gain"\nwhere = "paper:main abstract"\nvalue = {value}\ntolerance = {tol}\n{source}\nruns = ["{run_id}"]\n'


def test_claim_matches_evidence(cli, repo):
    rid = run(cli, 0.87)
    claims(repo, claim(rid))
    _, rep = cli.check(repo)
    assert one(rep, "R-40")["status"] == "PASS"


def test_claim_without_run_or_with_wrong_number(cli, repo):
    rid = run(cli, 0.87)
    claims(repo, claim(rid).replace(f'runs = ["{rid}"]', "runs = []"))
    _, rep = cli.check(repo)
    assert "R-40.no_run" in codes(one(rep, "R-40"))
    claims(repo, claim(rid, value=0.09))
    code, rep = cli.check(repo)
    assert "R-40.value_mismatch" in codes(one(rep, "R-40")) and code == 1


def test_claim_source_rewritten_after_run(cli, repo):
    rid = run(cli, 0.87)
    (repo / "results/metrics.json").write_text(json.dumps({"auroc": 0.87, "gain": 0.07}))  # same numbers, not from the run
    claims(repo, claim(rid))
    _, rep = cli.check(repo)
    assert "R-40.not_from_runs" in codes(one(rep, "R-40"))


def test_claim_from_failed_or_missing_run(cli, repo):
    claims(repo, claim("no-such-run"))
    _, rep = cli.check(repo)
    assert "R-40.run_missing" in codes(one(rep, "R-40"))
    cli("run", "--", PY, "-c", "raise SystemExit(3)")
    from steward.ledger import verify
    failed = [e["run"] for e in verify(repo / "development/runs.jsonl").entries if e.get("kind") == "outcome"][-1]
    claims(repo, claim(failed))
    _, rep = cli.check(repo)
    assert "R-40.run_failed" in codes(one(rep, "R-40"))


def test_claim_map_invalid(cli, repo):
    claims(repo, '[[claims]]\nid = "x"\ntext = "y"\nvalue = 1\nruns = []\n')  # neither source nor value_key
    _, rep = cli.check(repo)
    assert one(rep, "R-40")["status"] == "FAIL"


def test_prior_work_links(cli, example):
    _, rep = cli.check(example)
    assert one(rep, "R-41")["status"] == "PASS"
    edit(example, PRIOR, 'evidence  = ["contract:expr-clf"]', 'evidence  = ["contract:missing"]')
    _, rep = cli.check(example)
    assert "R-41.unknown_contract" in codes(one(rep, "R-41"))
    edit(example, PRIOR, 'evidence  = ["contract:missing"]', "evidence  = []")
    _, rep = cli.check(example)
    assert one(rep, "R-41")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- red-team A1
from steward import evidence as ev  # noqa: E402


def _rec(status="finished", metrics=None, outputs=None):
    return {"command": ["x"], "outcome": {"status": status, "metrics": metrics, "outputs": outputs or {}}}


def test_A1_missing_output_hashes_are_incomplete_not_repeatable():
    res = ev.diff_runs(_rec(outputs={"o": None}), _rec(outputs={"o": None}), {}, None)
    assert res["verdict"] == "incomplete" and not res["repeatable"]


def test_A1_failed_runs_are_never_repeatable(cli, repo):
    cli("run", "--", PY, "-c", "raise SystemExit(1)")
    cli("run", "--", PY, "-c", "raise SystemExit(1)")
    from steward.ledger import verify
    ids = [e["run"] for e in verify(repo / "development/runs.jsonl").entries if e.get("kind") == "started"]
    code, _, err = cli("diff", "run", ids[0], ids[1])
    assert code == 2 and "finished" in err


def test_A1_types_are_preserved():
    res = ev.diff_runs(_rec(metrics={"ok": True}), _rec(metrics={"ok": 1}), {}, ev.parse_tol("abs:1"))
    assert res["verdict"] == "not repeatable"
    res = ev.diff_runs(_rec(metrics={"x": float("nan")}), _rec(metrics={"x": float("nan")}), {}, None)
    assert res["verdict"] == "incomplete"


def test_A1_tolerances_must_be_finite_and_nonnegative():
    for bad in ("abs:-1", "rel:nan", "abs:inf", "abs:", "pct:1"):
        with pytest.raises(ValueError):
            ev.parse_tol(bad)


def test_A1_nothing_comparable_is_incomplete():
    assert ev.diff_runs(_rec(), _rec(), {}, None)["verdict"] == "incomplete"


def test_A1_normal_rerun_still_repeatable():
    res = ev.diff_runs(_rec(metrics={"a": 0.5}), _rec(metrics={"a": 0.5000001}), {}, ev.parse_tol("abs:1e-3"))
    assert res["verdict"] == "repeatable" and res["repeatable"]


# ---------------------------------------------------------------- red-team B1
@pytest.mark.parametrize("ma,mb,verdict", [
    ({"m": [7]}, {"m": {"0": 7}}, "not repeatable"),          # array vs object
    ({"n": 1, "m": []}, {"n": 1}, "not repeatable"),           # an empty container present on one side only
    ({"n": 1, "m": {}}, {"n": 1, "m": {}}, "repeatable"),
    (False, False, "repeatable"),                               # a falsey top-level metric is still evidence
    (0, 0, "repeatable"),
    (10 ** 400, 10 ** 400, "repeatable"),                       # huge integers: no OverflowError
    ({"a": {"b": [1, 2]}}, {"a": {"b": [1, 2]}}, "repeatable"),
    ({"a": {"b": [1, 2]}}, {"a": {"b": [1, 3]}}, "not repeatable"),
])
def test_B1_structure_is_preserved(ma, mb, verdict):
    assert ev.diff_runs(_rec(metrics=ma), _rec(metrics=mb), {}, None)["verdict"] == verdict


def test_B1_metrics_missing_on_one_side_is_incomplete():
    a = _rec(metrics={"x": 1})
    b = {"command": ["x"], "outcome": {"status": "finished", "outputs": {}}}  # no metrics recorded
    assert ev.diff_runs(a, b, {}, None)["verdict"] == "incomplete"


def test_B1_huge_integer_tolerance():
    big = 10 ** 400
    assert ev.diff_runs(_rec(metrics={"x": big}), _rec(metrics={"x": big + 1}), {}, ev.parse_tol("abs:2"))["verdict"] == "repeatable"


# ---------------------------------------------------------------- red-team round 3: D1 - D3
def test_D1_a_metric_key_cannot_collide_with_a_structural_marker():
    res = ev.diff_runs(_rec(metrics={"p": [], "p#type": "x"}), _rec(metrics={"p": {}, "p#type": "x"}), {}, None)
    assert res["verdict"] == "not repeatable"
    same = ev.diff_runs(_rec(metrics={"p": [1], "p#type": "x"}), _rec(metrics={"p": [1], "p#type": "x"}), {}, None)
    assert same["verdict"] == "repeatable"


def test_D1_an_empty_key_is_not_the_root():
    assert ev.diff_runs(_rec(metrics={"": 1}), _rec(metrics=1), {}, None)["verdict"] == "not repeatable"


@pytest.mark.parametrize("m", [{}, [], {"m": [[]]}, {"a": {}, "b": []}])
def test_D2_structure_alone_is_not_repeatability_evidence(m):
    res = ev.diff_runs(_rec(metrics=m), _rec(metrics=m), {}, None)
    assert res["verdict"] == "incomplete" and not res["repeatable"]


def test_D2_structural_differences_are_still_reported_without_leaves():
    assert ev.diff_runs(_rec(metrics={"m": []}), _rec(metrics={"m": {}}), {}, None)["verdict"] == "not repeatable"


def test_D2_a_matching_falsey_scalar_is_evidence():
    assert ev.diff_runs(_rec(metrics={"m": 0}), _rec(metrics={"m": 0}), {}, None)["verdict"] == "repeatable"


BIG = 2 ** 100


@pytest.mark.parametrize("a,b,spec,state", [
    (BIG - 1, 0, f"abs:{BIG}", "within"),
    (BIG, 0, f"abs:{BIG}", "within"),
    (BIG + 1, 0, f"abs:{BIG}", "different"),
    (10 ** 30, 10 ** 30 - 10 ** 10 + 1, "rel:1e-20", "within"),
    (10 ** 30, 10 ** 30 - 10 ** 10, "rel:1e-20", "within"),
    (10 ** 30, 10 ** 30 - 10 ** 10 - 1, "rel:1e-20", "different"),
    (10 ** 400 + 1, 0, "abs:1e400", "different"),
    (10 ** 400, 0, "abs:1e400", "within"),
    (0.1, 0.0, "abs:0.1", "within"),       # a float compares as the decimal it was written as
    (0.1, 0.0, "abs:0.0999", "different"),
])
def test_D3_tolerance_boundary_is_decided_exactly(a, b, spec, state):
    assert ev.compare(a, b, ev.parse_tol(spec)) == state


def test_D3_tolerance_through_the_cli(cli, repo):
    (repo / "big.py").write_text("import json, sys; open('results/metrics.json','w').write(json.dumps({'x': int(sys.argv[1])}))")

    def big(v):
        code, _, err = cli("run", "--output", "results/metrics.json", "--metrics", "results/metrics.json", "--", PY, "big.py", str(v))
        assert code == 0, err
        return err.split("run ")[1].split()[0]
    a, b, c = big(0), big(BIG), big(BIG + 1)
    assert cli("diff", "run", a, b, "--tol", f"x=abs:{BIG}")[0] == 0
    assert cli("diff", "run", a, c, "--tol", f"x=abs:{BIG}")[0] == 1


# ---------------------------------------------------------------- red-team round 4: E1 - E3, E6
def emit(cli, repo, text):
    """A finished run whose metrics file is exactly `text` (JSON)."""
    (repo / "emit.py").write_text("import sys; open('results/metrics.json','w').write(sys.argv[1])")
    code, _, err = cli("run", "--output", "results/metrics.json", "--metrics", "results/metrics.json", "--", PY, "emit.py", text)
    assert code == 0, err
    return err.split("run ")[1].split()[0]


@pytest.mark.parametrize("prec", [3, 28, 60])
def test_E1_relative_scale_is_never_rounded(prec):
    import decimal
    with decimal.localcontext(decimal.Context(prec=prec)):
        assert ev.compare(10 ** 30 + 1, 0, ev.parse_tol("rel:1")) == "within"
        assert ev.compare(10 ** 30 - 1, 0, ev.parse_tol("rel:0." + "9" * 30)) == "different"
        assert ev.compare(-(10 ** 30) - 1, 0, ev.parse_tol("rel:1")) == "within"


def test_E2_extreme_finite_tolerances_are_decided_not_crashed(cli, repo):
    import decimal
    huge, tiny = f"1e{decimal.MAX_EMAX}", f"1e{decimal.MIN_EMIN}"
    assert ev.compare(20, 21, ev.parse_tol(f"rel:{huge}")) == "within"
    assert ev.compare(20, 21, ev.parse_tol(f"rel:{tiny}")) == "different"
    assert ev.compare(20, 21, ev.parse_tol(f"abs:{huge}")) == "within"
    a, b = emit(cli, repo, "20"), emit(cli, repo, "21")
    assert cli("diff", "run", a, b, "--default-tol", f"rel:{huge}")[0] == 0
    assert cli("diff", "run", a, b, "--default-tol", f"rel:{tiny}")[0] == 1


@pytest.mark.parametrize("recorded,status", [("9007199254740992", "FAIL"), ("9007199254740993", "PASS")])
def test_E3_integer_claims_keep_their_exact_value(cli, repo, recorded, status):
    rid = emit(cli, repo, '{"count": %s}' % recorded)
    claims(repo, claim(rid, value=9007199254740993, tol=0, source='source = "results/metrics.json"\npointer = "/count"'))
    _, rep = cli.check(repo)
    res = one(rep, "R-40")
    assert res["status"] == status
    if status == "FAIL":
        assert "R-40.value_mismatch" in codes(res)


def test_E6_an_empty_pointer_names_the_root(cli, repo):
    a, b = emit(cli, repo, "2"), emit(cli, repo, "3")
    assert cli("diff", "run", a, b, "--tol", "=abs:1")[0] == 0
    c, d = emit(cli, repo, '{"": 2}'), emit(cli, repo, '{"": 3}')
    assert cli("diff", "run", c, d, "--tol", "/=abs:1")[0] == 0   # "/" is the property with an empty key
    assert cli("diff", "run", c, d, "--tol", "=abs:1")[0] == 1    # "" is the root, not that property


# ---------------------------------------------------------------- red-team round 5: F1, F4
def test_F1_fractional_metrics_keep_the_precision_they_were_written_with(cli, repo):
    a, b = emit(cli, repo, '{"count": 1.0}'), emit(cli, repo, '{"count": 1.0000000000000001}')
    assert cli("diff", "run", a, b)[0] == 1
    assert cli("diff", "run", a, b, "--tol", "count=abs:0.0000000000000001")[0] == 0
    code, out, _ = cli("diff", "run", a, b, "--json")
    res = json.loads(out)
    assert res["metrics_precision"] == {"a": "exact", "b": "exact"}
    assert next(r for r in res["results"] if r.get("pointer") == "/count")["b"] == "1.0000000000000001"


def test_F1_records_without_the_text_compare_as_recorded_binary_floats():
    legacy = _rec(metrics={"count": 1.0})
    res = ev.diff_runs(legacy, _rec(metrics={"count": 1.0}), {}, None)
    assert res["verdict"] == "repeatable" and res["metrics_precision"] == {"a": "binary64", "b": "binary64"}


@pytest.mark.parametrize("value,tol,status", [
    ("1.0", "0", "FAIL"),
    ("1.0000000000000001", "0", "PASS"),
    ("1.0", "0.0000000000000001", "PASS"),
])
def test_F1_claims_compare_exact_decimals(cli, repo, value, tol, status):
    rid = emit(cli, repo, '{"count": 1.0000000000000001}')
    claims(repo, claim(rid, value=value, tol=tol, source='source = "results/metrics.json"\npointer = "/count"'))
    _, rep = cli.check(repo)
    assert one(rep, "R-40")["status"] == status


def test_F4_a_pointer_may_contain_an_equals_sign(cli, repo):
    a, b = emit(cli, repo, '{"a=b": 2}'), emit(cli, repo, '{"a=b": 3}')
    assert cli("diff", "run", a, b, "--tol", "/a=b=abs:1")[0] == 0
    assert cli("diff", "run", a, b)[0] == 1


# ---------------------------------------------------------------- red-team round 6: G1, G3, G5 - G8
def write_output(cli, repo, path, text):
    """A finished run that writes `text` to `path` and records it as an output."""
    (repo / "write.py").write_text("import sys; open(sys.argv[1],'w').write(sys.argv[2])")
    code, _, err = cli("run", "--output", path, "--", PY, "write.py", path, text)
    assert code == 0, err
    return err.split("run ")[1].split()[0]


def registry(repo, path):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[paper.main]\ndir = "paper"\nmain = "main.tex"\n')
    (repo / "paper").mkdir(exist_ok=True)
    (repo / "paper/values.toml").write_text(f'schema = "steward.values/0.1"\n[values.count]\nsource = "{path}"\npointer = "/count"\n')


@pytest.mark.parametrize("path,text", [("results/m.json", '{"count": 1.0000000000000001}'),
                                       ("results/m.toml", "count = 1.0000000000000001\n")])
@pytest.mark.parametrize("via", ["direct", "registry"])
@pytest.mark.parametrize("value,status", [("1.0000000000000001", "PASS"), ("1.0", "FAIL")])
def test_G1_registry_and_direct_pointers_agree_exactly(cli, repo, path, text, via, value, status):
    rid = write_output(cli, repo, path, text)
    if via == "registry":
        registry(repo, path)
        src = 'value_key = "count"'
    else:
        src = f'source = "{path}"\npointer = "/count"'
    claims(repo, claim(rid, value=value, tol=0, source=src))
    _, rep = cli.check(repo, "evidence")
    assert one(rep, "R-40")["status"] == status


def test_G3_values_beyond_the_supported_range_are_reported_not_crashed(cli, repo):
    import decimal
    a, b = emit(cli, repo, "1"), emit(cli, repo, f"1e{decimal.MAX_EMAX}")
    assert cli("diff", "run", a, b)[0] == 1                            # exact inequality needs no arithmetic
    code, out, _ = cli("diff", "run", a, b, "--default-tol", "abs:1", "--json")
    assert code == 2 and json.loads(out)["results"][-1]["state"] == "out of range"
    c = emit(cli, repo, f"1e{decimal.MAX_EMAX + 1}")                   # beyond the decimal exponent limit
    assert cli("diff", "run", a, c)[0] == 2                            # not representable: out of range, not a guess
    assert cli("diff", "run", a, c, "--default-tol", "abs:1")[0] == 2
    assert cli("diff", "run", c, c)[0] == 2                            # H4: never evidence, even when identical


def test_G3_claims_beyond_the_supported_range_are_unknown(cli, repo):
    import decimal
    rid = write_output(cli, repo, "results/m.json", '{"count": 1e%d}' % decimal.MAX_EMAX)
    claims(repo, claim(rid, value=1, tol=1, source='source = "results/m.json"\npointer = "/count"'))
    _, rep = cli.check(repo, "evidence")
    res = one(rep, "R-40")
    assert res["status"] == "UNKNOWN" and "R-40.out_of_range" in codes(res)


def test_G5_a_tolerance_without_a_pointer_separator_is_a_usage_error(cli, repo):
    a, b = emit(cli, repo, "20"), emit(cli, repo, "21")
    assert cli("diff", "run", a, b, "--tol", "abs:1")[0] == 64
    assert cli("diff", "run", a, b, "--tol", "=abs:1")[0] == 0


def test_G6_claim_tolerances_are_validated_and_shown_as_written(cli, repo):
    rid = write_output(cli, repo, "results/m.json", '{"count": 1.0000000000000001}')
    claims(repo, claim(rid, value="1.0000000000000001", tol="-1e-400", source='source = "results/m.json"\npointer = "/count"'))
    _, rep = cli.check(repo, "evidence")
    assert "R-40.invalid_tolerance" in codes(one(rep, "R-40")) and one(rep, "R-40")["status"] == "FAIL"
    claims(repo, claim(rid, value="1.0", tol="0.00000000000000009", source='source = "results/m.json"\npointer = "/count"'))
    _, rep = cli.check(repo, "evidence")
    msg = next(d["message"] for d in one(rep, "R-40")["details"] if d["code"] == "R-40.value_mismatch")
    assert "0.00000000000000009" in msg and "1.0000000000000001" in msg


def test_G7_one_claim_map_revision_decides_r40(cli, repo, monkeypatch):
    from steward import rules
    rid = write_output(cli, repo, "results/m.json", '{"count": 2}')
    first = claim(rid, value=1, tol=0, source='source = "results/m.json"\npointer = "/count"')   # wrong number
    second = claim("missing-run", value=2, tol=0, source='source = "results/m.json"\npointer = "/count"')
    claims(repo, first)
    p = repo / "development/claims.toml"
    real = rules.Ctx.read

    def read(self, rel):
        data = real(self, rel)
        if rel == "development/claims.toml":  # a save lands right after this read
            p.write_text('schema = "steward.claims/0.1"\n' + second)
        return data
    monkeypatch.setattr(rules.Ctx, "read", read)
    _, rep = cli.check(repo, "evidence")
    res = one(rep, "R-40")
    import hashlib
    assert res["status"] == "FAIL" and "R-40.value_mismatch" in codes(res)
    assert res["evidence"][0]["sha256"] == hashlib.sha256(('schema = "steward.claims/0.1"\n' + first).encode()).hexdigest()


def test_G8_text_output_names_each_runs_metrics_precision(cli, repo):
    from steward.ledger import Ledger, verify
    a, b = emit(cli, repo, '{"x": 1}'), emit(cli, repo, '{"x": 1}')
    led = repo / "development/runs.jsonl"
    entries = verify(led).entries
    # rebuild the ledger with run A's outcome as a pre-0.6.2 record (no metrics_text)
    led.unlink()
    lg = Ledger(led, "runs")
    for e in entries[1:]:
        body = {k: v for k, v in e.items() if k not in ("seq", "prev", "hash", "kind", "time")}
        if e.get("kind") == "outcome" and e.get("run") == a:
            body.pop("metrics_text", None)
        lg.append(e["kind"], body)
    code, out, _ = cli("diff", "run", a, b)
    assert code == 0 and "metrics precision: A binary64" in out and "B exact" in out


# ---------------------------------------------------------------- 0.6.3: known issues H2 - H4, H6, H7
REV1, REV2 = '{"count": 1}', '{"count": 2}'


def two_claims(a, b):
    return 'schema = "steward.claims/0.1"\n' + "".join(
        f'[[claims]]\nid = "c{i}"\ntext = "c"\nwhere = "paper:main abstract"\nvalue = {v}\ntolerance = 0\n{src}\nruns = ["{r}"]\n'
        for i, (v, src, r) in enumerate((a, b)))


@pytest.mark.parametrize("refs", [("direct", "direct"), ("registry", "registry"), ("direct", "registry")])
def test_H2_one_source_snapshot_decides_every_claim(cli, repo, monkeypatch, refs):
    from pathlib import Path
    r1 = write_output(cli, repo, "results/m.json", REV1)
    r2 = write_output(cli, repo, "results/m.json", REV2)
    (repo / "results/m.json").write_text(REV1)  # the current file is revision 1
    if "registry" in refs:
        registry(repo, "results/m.json")
    src = {"direct": 'source = "results/m.json"\npointer = "/count"', "registry": 'value_key = "count"'}
    (repo / "development/claims.toml").write_text(two_claims((1, src[refs[0]], r1), (2, src[refs[1]], r2)))
    real = Path.read_bytes
    reads = []

    def read_bytes(self):
        data = real(self)
        if self.name == "m.json" and self.parent.name == "results":
            reads.append(1)
            self.write_text(REV2)  # a save lands right after each read
        return data
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    _, rep = cli.check(repo, "evidence")
    monkeypatch.setattr(Path, "read_bytes", real)
    res = one(rep, "R-40")
    assert res["status"] == "FAIL"  # revision 1 supports claim c0 only; no single revision supports both


@pytest.mark.parametrize("current,status", [('{"count": 2}', "PASS"), ('{"count": 3}', "FAIL")])
def test_H3_derived_claims_need_provenance_for_their_sources(cli, repo, current, status):
    rid = write_output(cli, repo, "results/m.json", '{"count": 2}')
    registry(repo, "results/m.json")
    with open(repo / "paper/values.toml", "a") as f:
        f.write('[values.calculated]\nderive = "{count} * 2"\n')
    (repo / "results/m.json").write_text(current)
    value = 4 if status == "PASS" else 6  # the stated number matches the derived value either way
    claims(repo, claim(rid, value=value, tol=0, source='value_key = "calculated"'))
    _, rep = cli.check(repo, "evidence")
    res = one(rep, "R-40")
    assert res["status"] == status
    if status == "FAIL":
        assert "R-40.not_from_runs" in codes(res)


def test_H4_out_of_range_operands_are_reported_consistently(cli, repo):
    import decimal
    M = decimal.MAX_EMAX
    a, b = emit(cli, repo, f"9e{M}"), emit(cli, repo, f"-9e{M}")
    assert cli("diff", "run", a, b, "--default-tol", "abs:1")[0] == 2   # the difference itself is out of range
    c = emit(cli, repo, '{"a": 1, "b": 0}')
    d = emit(cli, repo, '{"a": 2, "b": 1e%d}' % (M + 1))
    code, out, _ = cli("diff", "run", c, d)
    assert code == 1  # a difference found takes precedence over out-of-range evidence (documented)


@pytest.mark.parametrize("where", ["direct", "registry", "claim_value", "claim_tolerance"])
def test_H4_claims_report_out_of_range_the_same_way(cli, repo, where):
    import decimal
    big = f"1e{decimal.MAX_EMAX + 1}"
    text = f"count = {big}\n" if where in ("direct", "registry") else "count = 1\n"
    rid = write_output(cli, repo, "results/m.toml", text)
    if where == "registry":
        registry(repo, "results/m.toml")
    src = 'value_key = "count"' if where == "registry" else 'source = "results/m.toml"\npointer = "/count"'
    value = big if where == "claim_value" else 1
    tol = big if where == "claim_tolerance" else 0
    claims(repo, claim(rid, value=value, tol=tol, source=src))
    _, rep = cli.check(repo, "evidence")
    res = one(rep, "R-40")
    assert res["status"] == "UNKNOWN" and "R-40.out_of_range" in codes(res), res


@pytest.mark.parametrize("tol,status", [("inf", "FAIL"), ("-inf", "FAIL"), ("nan", "FAIL"), ("-1", "FAIL"), ("1e999", "PASS")])
def test_H6_nonfinite_tolerances_are_invalid(cli, repo, tol, status):
    rid = write_output(cli, repo, "results/m.json", '{"count": 2}')
    claims(repo, claim(rid, value=2, tol=tol, source='source = "results/m.json"\npointer = "/count"'))
    _, rep = cli.check(repo, "evidence")
    res = one(rep, "R-40")
    assert res["status"] == status
    if status == "FAIL":  # I3: one diagnostic for every invalid tolerance, whatever its sign
        assert "R-40.invalid_tolerance" in codes(res)


def test_H7_runs_without_metrics_are_not_called_legacy(cli, repo):
    a, b = write_output(cli, repo, "results/o.txt", "x"), write_output(cli, repo, "results/o.txt", "x")
    code, out, _ = cli("diff", "run", a, b)
    assert code == 0 and "metrics precision: A none, B none" in out and "before 0.6.2" not in out
    c = emit(cli, repo, '{"x": 1}')
    code, out, _ = cli("diff", "run", a, c, "--json")
    assert json.loads(out)["metrics_precision"] == {"a": "none", "b": "exact"}


# ---------------------------------------------------------------- 0.6.3: I2 (Codex re-verification of b4190ac)
def test_I2_one_check_reads_each_source_once_for_every_rule(cli, repo, monkeypatch):
    from pathlib import Path
    rid = write_output(cli, repo, "results/m.json", '{"count": 2}')
    registry(repo, "results/m.json")
    claims(repo, claim(rid, value=2, tol=0, source='value_key = "count"'))
    real = Path.read_bytes
    reads = []

    def read_bytes(self):
        data = real(self)
        if self.name == "m.json" and self.parent.name == "results":
            reads.append(1)
            self.write_text('{"count": 1}')  # a save lands right after every read
        return data
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    _, rep = cli.check(repo, "paper", "evidence")
    monkeypatch.setattr(Path, "read_bytes", real)
    assert len(reads) == 1, reads
    assert one(rep, "R-40")["status"] == "PASS"   # every rule decided on the one read: revision 2
