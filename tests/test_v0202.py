"""0.20.2: the stranger test as a feature (STW-041) and the fixes from the Codex stranger test (STW-040)."""

import io
import json
import subprocess
import tomllib
from datetime import date, timedelta

import pytest

from conftest import codes, results
from test_v0120_features import gsh, xproj  # noqa: F401
from test_v0200_biology import MATRIX, _Resp, _study_cfg


def _fresh(tmp_path, name="p"):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


# ---------------------------------------------------------------- STW-041: the stranger test
def test_a_brief_names_the_projects_own_audience_and_missions(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d, "--project", "widget")
    with open(d / "steward.toml", "a") as f:
        f.write('\n[stranger_test]\naudience = "a data engineer"\nmissions = ["Load a CSV and get the report."]\n'
                'install = \'pip install "git+file://{repo}@{tag}"\'\n')
    code, out, err = cli("stranger-test", "brief", "--repo", d, "--tag", "v1.0.0", "--for", "codex")
    assert code == 0, err
    assert "You are a data engineer." in out and "stranger test of widget (v1.0.0)" in out
    missions = [ln for ln in out.splitlines() if ln[:2] in ("1.", "2.", "3.", "4.")]
    assert missions[0].startswith("1. First contact") and "Load a CSV" in missions[1]
    assert missions[-1].startswith("4. Break something on purpose")
    assert f'git+file://{d.resolve()}@v1.0.0' in out and "--skip-git-repo-check" in out
    assert "biolog" not in out.lower()  # generic: nothing of this toolkit's own field


def test_without_a_declaration_the_generic_test_runs(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, err = cli("stranger-test", "brief", "--repo", d, "--tag", "v0.1.0", "--for", "gemini")
    assert code == 0 and "the main thing the README says" in out and "no [stranger_test]" in err


def test_a_report_is_recorded_once_and_r87_follows_it(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write("\n[stranger_test]\nmax_age_days = 30\n")
    _, rep = cli.check(d, "release")
    assert results(rep, "R-87")[0]["status"] == "INCOMPLETE"
    report = tmp_path / "report.md"
    report.write_text("# Stranger test of x (v1.0.0, codex)\n\n**Verdict.** Yes.\n")
    code, out, _ = cli("stranger-test", "record", report, "--repo", d, "--tag", "v1.0.0", "--agent", "codex")
    assert code == 0 and f"{date.today().isoformat()}-stranger-test-v1.0.0-codex.md" in out
    _, rep = cli.check(d, "release")
    assert results(rep, "R-87")[0]["status"] == "PASS"
    assert cli("stranger-test", "record", report, "--repo", d, "--tag", "v1.0.0", "--agent", "codex")[0] == 65
    (tmp_path / "other.md").write_text("notes\n")
    assert cli("stranger-test", "record", tmp_path / "other.md", "--repo", d, "--tag", "v2", "--agent", "x")[0] == 65
    old = (date.today() - timedelta(days=40)).isoformat()
    for p in (d / "development/assessment").glob("*stranger-test*"):
        p.rename(p.with_name(p.name.replace(date.today().isoformat(), old)))
    _, rep = cli.check(d, "release")
    r = results(rep, "R-87")[0]
    assert r["status"] == "INCOMPLETE" and "R-87.stale" in codes(r)


def test_r87_is_advisory_and_not_applicable_without_the_table(cli, tmp_path):
    from steward.models import ADVISORY
    assert "R-87" in ADVISORY
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    _, rep = cli.check(d, "release")
    assert results(rep, "R-87")[0]["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- STW-040
def test_a_changed_input_can_be_accepted_on_purpose(cli, xproj):
    _study_cfg(xproj)
    (xproj / "data").mkdir()
    (xproj / "data/m.txt").write_text("a\n")
    cli("study", "new", "s1", "--title", "S")
    cli("study", "add-input", "s1", "--source", "GEO", "--accession", "GSE1", "--file", "data/m.txt")
    (xproj / "data/m.txt").write_text("b\n")
    _, out, _ = cli("check", "studies", "--summary")
    assert "--accept PATH" in out
    code, out, err = cli("study", "fingerprint", "s1", "--accept", "data/m.txt")
    assert code == 0 and "accepted" in out, err
    _, rep = cli.check(xproj, "studies")
    assert results(rep, "R-75")[0]["status"] == "PASS"
    assert cli("study", "fingerprint", "s1", "--accept", "data/m.txt")[0] == 65  # unchanged now


def test_a_template_is_written_in_place_and_a_brief_warns_of_placeholders(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, err = cli("task", "template", "review", "--repo", d, "--output", d / "development/tasks/R-001.md")
    assert code == 0 and (d / "development/tasks/R-001.md").is_file(), err
    code, out, err = cli("task", "brief", d / "development/tasks/R-001.md", "--repo", d, "--for", "codex",
                         "--output", d / "brief.md")
    assert code == 0 and "placeholders" in err
    text = (d / "brief.md").read_text()
    assert f"$(cat {d / 'brief.md'})" in text and "none yet" in text  # AQ9: the path as given


def _contract_table(x, rows):
    (x / "results").mkdir(exist_ok=True)
    (x / "results/de.tsv").write_text("gene\tp\tq\n" + "".join(f"G{i}\t{p}\t{q}\n" for i, (p, q) in enumerate(rows)))
    with open(x / "steward.toml", "a") as f:
        f.write('\n[[data.contract]]\npath = "results/de.tsv"\nid_column = "gene"\np_value = "p"\nadjusted_p_value = "q"\n')


def test_r83_reports_zero_p_values_once_and_adjusted_equal_to_raw(cli, xproj):
    _contract_table(xproj, [(0, 0), (0.01, 0.01), (0.2, 0.2)])
    _, rep = cli.check(xproj, "data")
    c = codes(results(rep, "R-83")[0])
    assert "R-83.p_zero" in c and "R-83.adjusted_equals_raw" in c


def test_r83_a_proper_table_has_neither(cli, xproj):
    _contract_table(xproj, [(0.001, 0.003), (0.01, 0.015), (0.2, 0.2)])
    _, rep = cli.check(xproj, "data")
    assert results(rep, "R-83")[0]["status"] == "PASS"


def test_an_empty_project_says_what_its_eligible_gate_means(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    _, out, _ = cli("check", "--repo", d, "--summary")
    assert "nothing is broken, not that anything is verified" in out and "passing: R-01" in out
    assert "red-team" not in out  # exploratory: the release-review recommendation is for confirmatory projects


def test_the_draft_review_names_its_fields(cli, xproj):
    with open(xproj / "steward.toml", "a") as f:
        f.write("\n[research]\n")
    cli("research", "new", "review", "lr-1", "--title", "x")
    _, rep = cli.check(xproj, "research")
    d = [x for x in results(rep, "R-76")[0]["details"] if x["code"] == "R-76.draft"][0]
    assert "dated search" in d["message"]


def test_the_split_check_detail_is_in_words(cli, example):
    _, rep = cli.check(example, "benchmark")
    d = [x for r in results(rep, "R-45") for x in r["details"] if x["code"] == "R-45.checked"][0]
    assert d["message"].startswith("checked sample IDs") and "sample(s)" in d["message"]


def test_a_missing_archive_record_is_a_clear_refusal(cli, xproj, monkeypatch):
    import urllib.error

    from steward import biodata as bd

    def gone(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "NOT FOUND", {}, None)
    monkeypatch.setattr(bd, "_urlopen", gone)
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    code, _, err = cli("data", "fetch", "Zenodo:1", "--study", "s1", "--dry-run")
    assert code == 65 and "no such record" in err and "internal error" not in err


def test_a_zenodo_key_with_folders_gets_its_last_part_as_name(monkeypatch):
    from steward import biodata as bd
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: _Resp(json.dumps({"files": [
        {"key": "user/tool-v1.zip", "size": 3, "checksum": "md5:" + "B" * 32, "links": {"self": "https://zenodo.org/x"}}
    ]}).encode()))
    f = bd.resolve("Zenodo", "1", []).files[0]
    assert f.name == "tool-v1.zip" and f.md5 == "b" * 32


def test_a_416_on_resume_restarts_cleanly(cli, xproj, monkeypatch):
    import urllib.error

    from steward import biodata as bd
    _study_cfg(xproj)
    cli("study", "new", "s1", "--title", "S")
    d = xproj / "data/raw/url"
    d.mkdir(parents=True)
    (d / ".m.tsv.part").write_bytes(MATRIX + b"extra")

    def serve(req, timeout=None):
        if req.get_header("Range"):
            raise urllib.error.HTTPError(req.full_url, 416, "Range Not Satisfiable", {}, None)
        return _Resp(MATRIX)
    monkeypatch.setattr(bd, "_urlopen", serve)
    code, _, err = cli("data", "fetch", "https://example.org/m.tsv", "--study", "s1")
    assert code == 0, err
    assert (d / "m.tsv").read_bytes() == MATRIX


def test_the_most_specific_detail_comes_first(cli, tmp_path):
    from steward.report import _by_specificity
    ds = [{"code": "R-75.file_changed"}, {"code": "R-75.sample_value_not_allowed"}]
    assert [d["code"] for d in _by_specificity(ds)] == ["R-75.sample_value_not_allowed", "R-75.file_changed"]
    _ = io  # noqa: F841
    _ = tomllib  # noqa: F841
    _ = pytest  # noqa: F841


def test_an_ellipsis_in_a_quotation_is_not_a_placeholder():
    from steward import briefs as br
    task = ('# Task: x\n\n- **ID:** T-1\n- **GO reference:** DECISIONS.md, the owner ("yes do it … keep it generic")\n'
            '- **Owner:** … (who)\n\n## Goal\ny\n')
    assert br.unfilled(task) == ["Owner"]


# ---------------------------------------------------------------- STW-042 (Gemini review of 0.20.2): AQ1 – AQ9
import hashlib  # noqa: E402


def _two_files(xproj, record):
    _study_cfg(xproj)
    (xproj / "data").mkdir(exist_ok=True)
    for n in ("a", "b", "m"):
        (xproj / f"data/{n}.txt").write_text("same\n")
    old = hashlib.sha256(b"same\n").hexdigest()
    (xproj / "development/studies").mkdir(parents=True, exist_ok=True)
    (xproj / "development/studies/s1.toml").write_text(record.replace("OLD", old))
    for n in ("a", "b", "m"):
        (xproj / f"data/{n}.txt").write_text(f"{n} changed\n")
    return old


HEAD = 'schema = "steward.study/1"\nid = "s1"\ntitle = "S"\n\n'


def test_AQ1_accept_never_touches_another_files_digest(cli, xproj):
    old = _two_files(xproj, HEAD + "[[inputs]]\nid = \"x\"\nfiles = [{ path = 'data/a.txt', sha256 = 'OLD' }, "
                                   '{ path = "data/b.txt", sha256 = "OLD" }]\n')
    assert cli("study", "fingerprint", "s1", "--accept", "data/a.txt")[0] == 0
    st = tomllib.loads((xproj / "development/studies/s1.toml").read_text())
    f = {x["path"]: x["sha256"] for x in st["inputs"][0]["files"]}
    assert f["data/b.txt"] == old and f["data/a.txt"] == hashlib.sha256(b"a changed\n").hexdigest()


def test_AQ1_accept_finds_the_input_not_the_samples_matrix(cli, xproj):
    _two_files(xproj, HEAD + '# files = [{ path = "data/m.txt" }]\n[samples]\npath = "data/b.txt"\nsha256 = "OLD"\n'
                             'required = []\nmatrix = [{ path = "data/m.txt" }]\n\n[[inputs]]\nid = "x"\n'
                             'files = [{ path = "data/m.txt", sha256 = "OLD", size = 5, md5 = "' + "0" * 32 + '" }]\n')
    code, out, err = cli("study", "fingerprint", "s1", "--accept", "data/m.txt")
    assert code == 0, err
    st = tomllib.loads((xproj / "development/studies/s1.toml").read_text())
    fr = st["inputs"][0]["files"][0]
    assert fr["sha256"] == hashlib.sha256(b"m changed\n").hexdigest() and fr["size"] == 10 and "md5" not in fr
    assert st["samples"]["sha256"] != fr["sha256"]


def test_AQ1_accept_in_table_form_and_bad_arguments(cli, xproj):
    _two_files(xproj, HEAD + '[[inputs]]\nid = "x"\n\n[[inputs.files]]\npath = "data/a.txt"\nsha256 = "OLD"\n'
                             'md5 = "' + "1" * 32 + '"\nsize = 5\n')
    assert cli("study", "fingerprint", "s1", "--accept", "data/a.txt")[0] == 0
    fr = tomllib.loads((xproj / "development/studies/s1.toml").read_text())["inputs"][0]["files"][0]
    assert fr["size"] == 10 and "md5" not in fr
    assert cli("study", "fingerprint", "s1", "--accept", "")[0] != 0
    assert cli("study", "fingerprint", "s1", "--accept", "data/a.txt", "--write")[0] == 64


def _r87(cli, d):
    _, rep = cli.check(d, "release")
    return results(rep, "R-87")[0]


def test_AQ2_r87_reads_its_records(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write("\n[stranger_test]\n")
    a = d / "development/assessment"
    a.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (a / f"{today}-stranger-test-v1-codex.md").write_text("")
    (a / f"{(date.today() + timedelta(days=3)).isoformat()}-stranger-test-v1-fake.md").write_text("# Stranger test of x\n")
    r = _r87(cli, d)
    assert r["status"] == "INCOMPLETE" and len([x for x in r["details"] if x["code"] == "R-87.ignored"]) == 2
    (a / f"{today}-stranger-test-v1.0.0-rc1-codex.md").write_text("# Stranger test of x (v1.0.0-rc1, codex)\n")
    r = _r87(cli, d)
    assert r["status"] == "PASS" and "v1.0.0-rc1 by codex" in r["reason"] and r["evidence"]


def test_AQ2_a_linked_assessment_folder_is_not_evidence(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    with open(d / "steward.toml", "a") as f:
        f.write("\n[stranger_test]\n")
    ext = tmp_path / "ext/assessment"
    ext.mkdir(parents=True)
    (ext / f"{date.today().isoformat()}-stranger-test-v1-codex.md").write_text("# Stranger test of x\n")
    import shutil
    shutil.rmtree(d / "development", ignore_errors=True)
    (d / "development").symlink_to(tmp_path / "ext")
    assert _r87(cli, d)["status"] == "INCOMPLETE"


def test_AQ3_a_zero_p_value_reason_is_not_a_missing_file(cli, xproj):
    _contract_table(xproj, [(0, 0.001), (0.01, 0.02), (0.2, 0.3)])
    _, rep = cli.check(xproj, "data")
    r = results(rep, "R-83")[0]
    assert r["status"] == "INCOMPLETE" and "needs checking" in r["reason"]


def test_AQ4_the_brief_runs_from_a_folder_beside_the_repository_and_refuses_unsafe_tags(cli, tmp_path):
    d = _fresh(tmp_path)
    cli("init", "--repo", d)
    code, out, _ = cli("stranger-test", "brief", "--repo", d, "--tag", "v1.0.0", "--for", "codex", "--output", d / "B.md")
    text = (d / "B.md").read_text()
    assert "cd ../stranger" in text and f"$(cat {(d / 'B.md').resolve()})" in text
    for bad in ('v1"; rm -rf ~', "v1\nx", "$(id)", "../x"):
        assert cli("stranger-test", "brief", "--repo", d, "--tag", bad)[0] == 64


def test_AQ5_zenodo_keys_with_the_same_name_in_two_folders(monkeypatch):
    from steward import biodata as bd
    monkeypatch.setattr(bd, "_urlopen", lambda req, timeout=None: _Resp(json.dumps({"files": [
        {"key": "dir1/data.csv", "size": 1, "checksum": "md5:" + "a" * 32, "links": {"self": "https://zenodo.org/1"}},
        {"key": "dir2/data.csv", "size": 2, "checksum": "md5:" + "b" * 32, "links": {"self": "https://zenodo.org/2"}},
        {"key": "only/one.csv", "size": 3, "checksum": "md5:" + "c" * 32, "links": {"self": "https://zenodo.org/3"}},
    ]}).encode()))
    names = [f.name for f in bd.resolve("Zenodo", "1", []).files]
    assert names == ["dir1__data.csv", "dir2__data.csv", "one.csv"]
    assert [f.name for f in bd.resolve("Zenodo", "1", ["dir2/data.csv"]).files] == ["dir2__data.csv"]


def test_AQ6_the_benchmark_guide_snippet_works_as_written(cli, xproj):
    import re as _re
    text = (__import__("pathlib").Path(__file__).parents[1] / "docs/guides/benchmark.md").read_text()
    assert "move `S2` to the test list" in text
    cli("init", "--repo", xproj, "--for", "benchmark")
    (xproj / "data").mkdir(exist_ok=True)
    (xproj / "benchmarks").mkdir(exist_ok=True)
    (xproj / "data/samples.csv").write_text("id,donor_id\nS1,D1\nS2,D2\nS3,D2\n")
    (xproj / "benchmarks/train.txt").write_text("S1\nS2\n")
    (xproj / "benchmarks/test.txt").write_text("S3\n")
    t = (xproj / "development/templates/benchmark.contract.toml").read_text()
    t = t.replace('group_key = "TBD"', 'group_key = "donor_id"').replace('# metadata  = "data/samples.csv"', 'metadata  = "data/samples.csv"')
    t = t.replace('# id_column = "id"', 'id_column = "id"')
    t = _re.sub(r'ids_file = "TBD"', 'ids_file = "benchmarks/train.txt"', t, count=1)
    t = _re.sub(r'ids_file = "TBD"', 'ids_file = "benchmarks/test.txt"', t, count=1)
    (xproj / "benchmarks/my.contract.toml").write_text(t)
    assert cli("benchmark", "splits", "benchmarks/my.contract.toml")[0] == 1
    (xproj / "benchmarks/train.txt").write_text("S1\n")
    (xproj / "benchmarks/test.txt").write_text("S2\nS3\n")
    assert cli("benchmark", "splits", "benchmarks/my.contract.toml")[0] == 0


def test_AQ7_a_template_never_overwrites_and_makes_folders_outside(cli, tmp_path):
    out = tmp_path / "elsewhere/deep/T.md"
    assert cli("task", "template", "review", "--output", out)[0] == 0 and out.is_file()
    out.write_text("mine\n")
    assert cli("task", "template", "review", "--output", out)[0] == 65 and out.read_text() == "mine\n"
