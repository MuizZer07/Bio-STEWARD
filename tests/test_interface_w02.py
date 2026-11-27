"""W02 (STW-047 C3 – C8, area and scope): explain, digest, locations, not configured, init and skills JSON.

Regenerate the goldens after an intended change: STEWARD_UPDATE_GOLDENS=1 pytest tests/test_interface_w02.py
"""

import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

import pytest

from conftest import REPO, one
from test_interface import GOLDEN, _golden_bytes, machine_example  # noqa: F401  (the W01 fixture, both examples)


def _schema(schema_id):
    from jsonschema import Draft202012Validator

    from steward.interface import describe
    from steward.resources import schemas_dir

    file = schemas_dir() / describe()["schema_files"][schema_id]
    schema = json.loads(file.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _valid(doc):
    _schema(doc["schema"]).validate(doc)
    return doc


def _versionless(doc):
    """The goldens hold no tool version, so a release bump does not rewrite them, and no file-list digest, which a
    local file the copy keeps (a built PDF) would change; the digest tests check it."""
    if isinstance(doc, dict):
        return {k: ("(version)" if k == "tool_version" else "(file list)" if k == "tree_digest" else _versionless(v))
                for k, v in doc.items()}
    if isinstance(doc, list):
        return [_versionless(v) for v in doc]
    return doc


def _check_golden(name, doc):
    path = GOLDEN / name
    text = _golden_bytes(_versionless(doc))
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text, f"output differs from {path}; regenerate only if intended"


# ---------------------------------------------------------------- goldens on both worked examples
def test_w02_goldens(cli, machine_example, tmp_path, monkeypatch):  # noqa: F811
    name, root = machine_example
    docs = {}
    code, out, err = cli("skills", "list", "--repo", root, "--format", "json")
    assert code == 0, err
    docs["skills list"] = _valid(json.loads(out))
    code, out, err = cli("init", "--repo", root, "--dry-run", "--format", "json", "--for", "agents")
    assert code == 0, err
    docs["init --dry-run"] = _valid(json.loads(out))
    report = root / ".steward" / "report.json"
    code, _, err = cli("check", "--repo", root, "--output", report)
    rep = json.loads(report.read_text(encoding="utf-8"))
    _valid(rep)
    docs["check (area, scope)"] = {"scope": rep["verdict"]["scope"],
                                   "areas": sorted({(r["rule"], r["area"]) for r in rep["verdict"]["results"]})}
    code, out, err = cli("check", "--repo", root, "--digest-only", "--against", report, "--format", "json")
    assert code == 0, err
    digest = _valid(json.loads(out))
    assert digest["current"] and digest["inputs_digest"] == rep["verdict"]["inputs_digest"]  # STW-047 acceptance
    docs["check --digest-only"] = digest
    docs["explain R-60"] = _valid(json.loads(cli("explain", "R-60", "--format", "json")[1]))
    monkeypatch.chdir(tmp_path)
    code, out, err = cli("check", "--format", "json")
    assert code == 78 and "not a steward repository" in err
    docs["not configured"] = _valid(json.loads(out))
    _check_golden(f"{name}.w02.json", docs)


def test_explain_all_golden(cli):
    code, out, err = cli("explain", "--all", "--format", "json")
    assert code == 0 and not err
    doc = _valid(json.loads(out))
    from steward.rules import RULES

    assert [r["rule"] for r in doc["rules"]] == sorted(RULES)
    _check_golden("explain-all.json", doc)


# ---------------------------------------------------------------- C3 explain
def test_explain_text_and_json_agree(cli):
    code, text, _ = cli("explain", "r-42")
    assert code == 0
    doc = json.loads(cli("explain", "R-42", "--format", "json")[1])["rules"][0]
    assert text.startswith(f"R-42 {doc['name']} (version {doc['version']}; area: {doc['area']}; "
                           f"{doc['governance']} governance)\n")
    for c in doc["codes"]:
        assert f"  {c['code']}" + (f": {c['fix']}" if c["fix"] else "") in text.splitlines()
    assert text.rstrip().endswith(f"Run it: {doc['run']}   (details: steward report FILE --rule R-42)")


def test_explain_all_text_lists_every_rule(cli):
    from steward.rules import RULES

    code, text, _ = cli("explain", "--all")
    assert code == 0
    assert re.findall(r"^(R-\d{2}) ", text, re.M) == sorted(RULES)


@pytest.mark.parametrize("argv", [("explain",), ("explain", "R-01", "--all"), ("explain", "R-99")])
def test_explain_usage(cli, argv):
    code, out, _ = cli(*argv)
    assert code == 64 and not out


# ---------------------------------------------------------------- area and scope
def test_every_rule_has_an_area():
    from steward.rules import RULES, rule_area

    assert [r for r in RULES if rule_area(r) == "unassigned"] == []
    assert rule_area("R-02") == "contract" and rule_area("R-85") == "paper"


def test_scope_of_full_area_and_rule_runs(cli, example):
    _, full = cli.check(example)
    assert full["verdict"]["scope"] == {"full": True, "areas": [], "rule": None}
    _, scoped = cli.check(example, "paper", "contract")
    assert scoped["verdict"]["scope"] == {"full": False, "areas": ["contract", "paper"], "rule": None}
    code, out, _ = cli("check", "--repo", example, "--rule", "R-46", "--format", "json")
    assert json.loads(out)["verdict"]["scope"] == {"full": False, "areas": ["benchmark"], "rule": "R-46"}
    from steward.rules import rule_area

    assert all(r["area"] == rule_area(r["rule"]) for r in full["verdict"]["results"])


def test_reports_before_0_21_still_render(cli, example, tmp_path):
    _, rep = cli.check(example)
    for r in rep["verdict"]["results"]:
        del r["area"]
    for key in ("inputs", "tree_digest", "scope"):
        del rep["verdict"][key]
    old = tmp_path / "old.json"
    old.write_text(json.dumps(rep), encoding="utf-8")
    code, out, err = cli("report", old, "--format", "summary")
    assert code == 0, err
    code, _, err = cli("check", "--repo", example, "--digest-only", "--against", old)
    assert code == 65 and "lists no inputs" in err


# ---------------------------------------------------------------- C5 digest
def _saved(cli, root):
    report = root / ".steward" / "report.json"
    code, _, err = cli("check", "--repo", root, "--output", report)
    assert code in (0, 1, 2, 3), err
    return report


def _digest(cli, root, report):
    code, out, err = cli("check", "--repo", root, "--digest-only", "--against", report, "--format", "json")
    assert code == 0, err
    return _valid(json.loads(out))


def test_digest_follows_an_edited_input(cli, example):
    report = _saved(cli, example)
    with (example / "steward.toml").open("a", encoding="utf-8") as f:
        f.write("\n# edited\n")
    d = _digest(cli, example, report)
    assert not d["current"] and d["changed"] == ["steward.toml"]
    report2 = _saved(cli, example)
    assert d["inputs_digest"] == json.loads(report2.read_text())["verdict"]["inputs_digest"]


def test_digest_sees_an_added_or_removed_file(cli, example):
    report = _saved(cli, example)
    (example / "notes.txt").write_text("a file no rule read before\n", encoding="utf-8")
    d = _digest(cli, example, report)
    assert not d["current"] and d["changed"] == [] and "added or removed" in d["reason"]
    (example / "notes.txt").unlink()
    assert _digest(cli, example, report)["current"]


def test_digest_names_a_missing_input(cli, example):
    report = _saved(cli, example)
    rep = json.loads(report.read_text())
    victim = next(i["path"] for i in rep["verdict"]["inputs"] if i["path"] != "steward.toml")
    (example / victim).unlink()
    d = _digest(cli, example, report)
    assert not d["current"] and d["inputs_digest"] is None and victim in d["changed"]


def test_digest_of_another_tool_version_is_not_current(cli, example):
    report = _saved(cli, example)
    rep = json.loads(report.read_text())
    rep["envelope"]["tool_version"] = "0.0.1"
    report.write_text(json.dumps(rep), encoding="utf-8")
    d = _digest(cli, example, report)
    assert d["inputs_digest"] == rep["verdict"]["inputs_digest"] and not d["current"]


def test_digest_from_stdin_and_text(cli, example, monkeypatch):
    import io

    report = _saved(cli, example)
    monkeypatch.setattr("sys.stdin", io.StringIO(report.read_text()))
    code, out, _ = cli("check", "--repo", example, "--digest-only", "--against", "-")
    # stdin names no file to leave out of the file list, and the report is inside the repository
    assert code == 0 and out.startswith("stale: files were added or removed")
    code, out, _ = cli("check", "--repo", example, "--digest-only", "--against", report)
    assert code == 0 and out == "current: the report's inputs and file list are unchanged\n"


@pytest.mark.parametrize("extra", [("--digest-only",), ("--against", "x.json"),
                                   ("--digest-only", "--against", "x.json", "paper"),
                                   ("--digest-only", "--against", "x.json", "--rule", "R-01"),
                                   ("--digest-only", "--against", "x.json", "--summary")])
def test_digest_usage(cli, example, extra):
    code, out, _ = cli("check", "--repo", example, *extra)
    assert code == 64 and not out


@pytest.mark.parametrize("name", ["biology-geo", "toy-expression-benchmark"])
def test_digest_costs_a_fraction_of_a_check(cli, tmp_path, name):
    root = tmp_path / name
    shutil.copytree(REPO / "examples" / name, root, ignore=shutil.ignore_patterns(".steward", "__pycache__"))
    report = root / "out" / "report.json"
    best_check = best_digest = float("inf")
    for _ in range(3):
        t = time.perf_counter()
        cli("check", "--repo", root, "--output", report)
        best_check = min(best_check, time.perf_counter() - t)
        t = time.perf_counter()
        d = _digest(cli, root, report)
        best_digest = min(best_digest, time.perf_counter() - t)
        assert d["current"]
    # STW-047 asks for at most 10 %; the bound here leaves room for a loaded test machine (measured: task record)
    assert best_digest <= 0.25 * best_check, (best_digest, best_check)


# ---------------------------------------------------------------- C6 not configured
def test_not_configured_exits_78(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli("check")
    assert (code, out) == (78, "") and "not a steward repository" in err
    code, out, err = cli("timeline", "--json")  # the legacy flag keeps an empty stdout
    assert (code, out) == (78, "")
    code, out, err = cli("timeline", "--format", "json")
    assert code == 78
    doc = _valid(json.loads(out))
    assert doc["code"] == "not_configured" and doc["exit"] == 78
    from steward.interface import describe

    assert describe()["exit_codes"]["78"].startswith("Not configured")
    assert describe()["error_schema"] == doc["schema"]


# ---------------------------------------------------------------- C7 init --dry-run
def test_init_plan_writes_nothing(cli, tmp_path):
    code, out, err = cli("init", "--repo", tmp_path, "--dry-run", "--format", "json", "--for", "reanalysis",
                         "--paper", "--skills", ".agents/skills")
    assert code == 0, err
    doc = _valid(json.loads(out))
    assert list(tmp_path.iterdir()) == []
    verbs = {a["path"]: a["verb"] for a in doc["actions"]}
    assert verbs["steward.toml"] == "create" and verbs[".agents/skills/using-steward/"] == "create"
    assert doc["tables"] == ["studies", "research"] and doc["kits"] == ["core", "paper", "research"]
    assert str(REPO) not in out  # a skill's source is the toolkit's own path: never in the plan
    code, _, _ = cli("init", "--repo", tmp_path)
    assert code == 0  # the text plan is unchanged by the JSON one


def test_init_json_needs_dry_run(cli, tmp_path):
    code, out, err = cli("init", "--repo", tmp_path, "--format", "json")
    assert code == 64 and not out and list(tmp_path.iterdir()) == []


def test_init_plan_of_an_existing_project_names_the_tables(cli, example):
    code, out, err = cli("init", "--repo", example, "--dry-run", "--format", "json", "--for", "reanalysis")
    assert code == 0, err
    assert json.loads(out)["tables"] == ["studies", "research"]
    assert "[studies]" not in (example / "steward.toml").read_text()


# ---------------------------------------------------------------- C8 skills list
def test_skills_list_outside_a_project(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli("skills", "list", "--format", "json")
    assert code == 0, err
    doc = _valid(json.loads(out))
    from steward.init import bundles

    assert doc["project"] is None
    assert {b["name"]: b["skills"] for b in doc["bundles"]} == bundles()
    assert all(s["description"] for s in doc["skills"])


def test_skills_list_shares_r60(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")
    (r / ".claude/skills").unlink()
    shutil.copytree(r / ".agents/skills", r / ".claude/skills")
    md = next((r / ".claude/skills").glob("*/SKILL.md"))
    md.write_text(md.read_text() + "\nedited\n")
    code, out, err = cli("skills", "list", "--repo", r, "--format", "json")
    assert code == 0, err
    pj = _valid(json.loads(out))["project"]
    assert pj["configured"] and pj["canonical"] == ".agents/skills" and "using-steward" in pj["installed"]
    _, rep = cli.check(r, "skills")
    assert [{k: v for k, v in c.items() if k != "failed"} for c in pj["copies"]] == one(rep, "R-60")["details"]
    assert [c["failed"] for c in pj["copies"]] == [True]
    code, text, _ = cli("skills", "list", "--repo", r)
    assert code == 0 and "FAIL .claude/skills  R-60.drift" in text


# ---------------------------------------------------------------- C4 locations
def location_problems(detail):
    """The location contract (docs/ci.md): `line` needs `path`; `column` and `end_line` need `line` (a `column`
    beside `row` is a table column); every number is a positive integer; `end_line` is not before `line`."""
    out = []
    if "path" not in detail:
        return out  # R-28 names a PDF page as `line` without a `path`: not a location
    path = detail["path"]
    if not isinstance(path, str) or path.startswith("/") or "\\" in path:
        out.append(f"path {path!r}")
    for k in ("line", "column", "end_line"):
        v = detail.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            out.append(f"{k} {v!r}")
    if "column" in detail and "line" not in detail and "row" not in detail:
        out.append("column without line")
    if "end_line" in detail and (detail.get("line") is None or detail["end_line"] < detail["line"]):
        out.append("end_line without line, or before it")
    return out


def _all_details(rep):
    return [(r["rule"], d) for r in rep["verdict"]["results"] for d in r["details"]]


def test_locations_follow_the_contract(cli, example):
    from test_determinism import mixed

    for root in (example, REPO / "examples" / "biology-geo"):
        _, rep = cli.check(root)
        assert [(r, d) for r, d in _all_details(rep) if location_problems(d)] == []
    _, rep = cli.check(mixed(example))
    assert [(r, d) for r, d in _all_details(rep) if location_problems(d)] == []
    r07 = [d for d in one(rep, "R-07")["details"] if d.get("path") == "README.md" and "line" in d]
    assert r07, one(rep, "R-07")
    line = (example / "README.md").read_text().splitlines()[r07[0]["line"] - 1]
    assert line[r07[0]["column"] - 1:].startswith("nightjar")


def test_r09_marker_has_a_column(cli, example):
    tex = example / "paper" / "main.tex"
    tex.write_text(tex.read_text() + "\nSome text TODO later.\n", encoding="utf-8")
    _, rep = cli.check(example, "paper")
    marks = [d for r in rep["verdict"]["results"] if r["rule"] == "R-09" for d in r["details"]
             if d["code"] == "R-09.marker"]
    assert marks and not any(location_problems(d) for d in marks)
    d = marks[-1]
    line = tex.read_text().splitlines()[d["line"] - 1]
    assert line[d["column"] - 1:].startswith("TODO")


TASKS = '\n[tasks]\nspecs = ["development/tasks/*.md"]\nboard = "development/BOARD.md"\nid_pattern = "TSK-\\\\d{3}"\n'


def test_r57_details_name_the_line(cli, example):
    with (example / "steward.toml").open("a", encoding="utf-8") as f:
        f.write(TASKS)
    tasks = example / "development" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "a.md").write_text("# Task\n\n- **ID:** `TSK-001`\n- **Status:** wip\n", encoding="utf-8")
    (tasks / "b.md").write_text("# Task\n\n\n- **ID:** `TSK-001`\n- **Status:** proposed\n", encoding="utf-8")
    (example / "development" / "BOARD.md").write_text("# Board\n\nNext unused ID: TSK-002\n", encoding="utf-8")
    _, rep = cli.check(example, "tasks")
    got = {(d["code"], d["path"]): d.get("line") for d in one(rep, "R-57")["details"] if "path" in d}
    assert got[("R-57.unknown_status", "development/tasks/a.md")] == 4
    assert got[("R-57.duplicate_id", "development/tasks/b.md")] == 4
    assert got[("R-57.not_on_board", "development/tasks/a.md")] == 3


def located_codes():
    """Codes per rule in the source, and how many of them have `path`, and `path` with `line`, in a literal detail
    (a static count: details built from a shared dict, as R-07's, are not seen)."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO / "src" / "steward").glob("*.py")))
    keys = defaultdict(set)
    for m in re.finditer(r"\{\"code\": f?\"(R-\d{2}\.[a-z_]+)\"([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text):
        keys[m.group(1)].add(frozenset(re.findall(r"\"([a-z_]+)\":", m.group(2))))
    with_path = {c for c, ks in keys.items() if any("path" in k for k in ks)}
    with_line = {c for c, ks in keys.items() if any({"path", "line"} <= k for k in ks)}
    return len(keys), len(with_path), len(with_line)


def test_located_code_count_recorded():
    # Recorded in development/tasks/v0.21-W02.md: before C4 456 codes, 174 with path, 24 with path and line
    total, with_path, with_line = located_codes()
    assert total >= 456 and with_path >= 174 and with_line >= 27
