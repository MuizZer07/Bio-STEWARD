"""T-CLI: init, check, report behaviour (RELEASE_v0.1_SPEC §6, §8.3)."""

import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

from conftest import gate


def tree_state(root: Path) -> dict[str, tuple[str, int]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


INIT_FILES = {  # AR-03 (0.8.1): the contract and prior-work templates come with a confirmatory profile or --templates
    "steward.toml", "development/DECISIONS.md", "development/templates/task.md", ".gitignore", "AGENTS.md",
}


def test_T_CLI_01_init_then_check_is_eligible(cli, tmp_path):
    code, out, _ = cli("init", "--repo", tmp_path)
    assert code == 0
    assert set(tree_state(tmp_path)) == INIT_FILES
    code, rep = cli.check(tmp_path)
    assert code == 0 and gate(rep)["eligible"]
    assert rep["verdict"]["config_profile"] == "exploratory"


def test_T_CLI_01_templates_validate_once_copied(cli, tmp_path):
    cli("init", "--repo", tmp_path, "--profile", "confirmatory")
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks/t.contract.toml").write_text((tmp_path / "development/templates/benchmark.contract.toml").read_text())
    (tmp_path / "development/prior_work").mkdir()
    (tmp_path / "development/prior_work/t.prior.toml").write_text((tmp_path / "development/templates/prior_work.prior.toml").read_text())
    code, rep = cli.check(tmp_path)
    statuses = {r["rule"]: r["status"] for r in rep["verdict"]["results"]}
    assert statuses["R-02"] == "INCOMPLETE" and statuses["R-05"] == "INCOMPLETE"  # TBDs, not schema failures
    assert rep["verdict"]["summary"]["counts"]["FAIL"] == 0 and code == 2


def test_T_CLI_02_init_is_idempotent_and_never_overwrites(cli, tmp_path):
    (tmp_path / "README.md").write_text("mine\n")
    (tmp_path / "AGENTS.md").write_text("# my agents\n")
    cli("init", "--repo", tmp_path)
    before = tree_state(tmp_path)
    repo_id = (tmp_path / "steward.toml").read_text().split('repo_id = "')[1][:36]
    code, out, _ = cli("init", "--repo", tmp_path, "--profile", "confirmatory")
    after = tree_state(tmp_path)
    # AR-03 (0.8.1): a confirmatory re-run adds the two templates; nothing that existed changes
    assert code == 0 and {k: v for k, v in after.items() if k in before} == before
    assert set(after) - set(before) == {"development/templates/benchmark.contract.toml", "development/templates/prior_work.prior.toml"}
    assert repo_id in (tmp_path / "steward.toml").read_text()
    assert (tmp_path / "README.md").read_text() == "mine\n"
    assert (tmp_path / "AGENTS.md").read_text() == "# my agents\n"  # no markers, no --agents-md: untouched
    assert "left untouched" in out


def test_T_CLI_02_dry_run_writes_nothing(cli, tmp_path):
    code, out, _ = cli("init", "--repo", tmp_path, "--dry-run")
    assert code == 0 and "would create" in out and tree_state(tmp_path) == {}


def test_init_agents_md_flag_appends_block_once(cli, tmp_path):
    (tmp_path / "AGENTS.md").write_text("# my agents\n")
    cli("init", "--repo", tmp_path, "--agents-md")
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# my agents\n") and text.count("<!-- >>> steward -->") == 1
    cli("init", "--repo", tmp_path, "--agents-md")
    assert (tmp_path / "AGENTS.md").read_text() == text


def test_init_gitignore_block_appended_to_existing_file(cli, tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/")
    cli("init", "--repo", tmp_path)
    assert (tmp_path / ".gitignore").read_text() == "node_modules/\n# >>> steward\n.steward/\n# <<< steward\n"


def test_init_copies_skills(cli, tmp_path):
    cli("init", "--repo", tmp_path, "--skills", ".agents/skills")
    names = sorted(p.name for p in (tmp_path / ".agents/skills").iterdir())
    from test_language_and_skills import CORE_SKILLS

    assert names == CORE_SKILLS
    assert (tmp_path / ".agents/skills/using-steward/SKILL.md").is_file()


def test_T_CLI_03_check_outside_a_repository(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _, err = cli("check")
    assert code == 78 and "not a steward repository" in err  # 0.21.0 (STW-047 C6): was 64


def test_check_finds_root_upwards(cli, example, monkeypatch):
    monkeypatch.chdir(example / "benchmarks" / "splits")
    code, out, _ = cli("check")
    assert code == 0 and "Gate default: ELIGIBLE" in out


def test_T_CLI_04_check_writes_nothing_without_output(cli, example):
    before = tree_state(example)
    cli("check", "--repo", example)
    cli("check", "--repo", example, "--format", "json")
    assert tree_state(example) == before


def test_check_output_written_and_refused_inside_privacy_scope(cli, example):
    out = example / ".steward" / "r.json"
    code, _, _ = cli("check", "--repo", example, "--output", out)
    assert code == 0 and json.loads(out.read_text())["schema"] == "steward.report/0.1"
    with open(example / "steward.toml", "a") as f:
        f.write('\n[privacy]\ndenylist_file = ".steward/private/denylist.txt"\n')
    code, _, err = cli("check", "--repo", example, "--output", example / "report.json")
    assert code == 64 and "privacy" in err


def test_usage_errors_exit_64(cli, example):
    assert cli("check", "--repo", example, "bogus-area")[0] == 64
    assert cli("check", "--repo", example, "--gate", "nope")[0] == 64
    assert cli("check", "--repo", example, "--format", "xml")[0] == 64


def test_custom_gate(cli, example):
    with open(example / "steward.toml", "a") as f:
        f.write('\n[gates.planning]\nrequire = ["R-01", "R-05", "R-06"]\n')
    code, rep = cli.check(example, gate="planning")
    assert code == 0 and {g["name"] for g in rep["verdict"]["gates"]} == {"default", "planning"}


def test_T_CLI_05_report_rejects_invalid_and_is_byte_stable(cli, example, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cli("report", bad)[0] == 65
    bad.write_text(json.dumps({"schema": "steward.report/0.1"}))
    assert cli("report", bad)[0] == 65
    assert cli("report", tmp_path / "missing.json")[0] == 64
    rep = tmp_path / "r.json"
    cli("check", "--repo", example, "--output", rep)
    code, md1, _ = cli("report", rep)
    _, md2, _ = cli("report", rep)
    assert code == 0 and md1 == md2
    assert "PASS 28 · FAIL 0 · INCOMPLETE 0 · UNKNOWN 0 · NOT_APPLICABLE 55" in md1
    assert "Scientific validity, and the correctness or acceptance of a manuscript, are not assessed by this tool." in md1
    assert md1.startswith("# Steward report: toy-expression-benchmark")
    _, txt, _ = cli("report", rep, "--format", "text")
    assert "Gate default: ELIGIBLE" in txt


def test_T_CLI_06_no_network(cli, example, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert cli("init", "--repo", tmp_path)[0] == 0
    assert cli("check", "--repo", example, "--output", tmp_path / "r.json")[0] == 0
    assert cli("report", tmp_path / "r.json")[0] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_init_unwritable_directory_exits_73(cli, tmp_path):
    tmp_path.chmod(0o500)
    try:
        assert cli("init", "--repo", tmp_path)[0] == 73
    finally:
        tmp_path.chmod(0o700)
