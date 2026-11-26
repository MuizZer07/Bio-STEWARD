"""0.9.0, section G: session sign-off and resumption (DESIGN_session_handoff, approved S1 - S5)."""

import os
import shutil
import subprocess

import pytest
from pathlib import Path

from conftest import codes, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    r = tmp_path / "p"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[session]\nend_hint = "run your harness\'s session delete command"\n')
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


CLOSE = ["session", "close", "--decisions-logged", "--next", "G2: write the start command (plan §G)",
         "--question", "Budget 600 or 1500? (DESIGN_session_handoff §10)", "--agreement", "commit under the owner's name only",
         "--read-first", "development/DECISIONS.md", "--tests", "12 passed", "--signature", "2026-11-23 · handoff · test"]


# ---------------------------------------------------------------- G1: close
@git_needed
def test_G1_close_writes_one_bounded_handoff_with_the_fixed_headings(cli, proj):
    code, out, err = cli(*CLOSE)
    assert code == 0, err
    text = (proj / "development/HANDOFF.md").read_text()
    for h in ("## State", "## Next", "## Open decisions", "## Open items", "## Working agreements", "## Read first",
              "## Signature"):
        assert h in text, h
    assert "G2: write the start command" in text and "confirmed by the agent" in text and "12 passed" in text
    assert len(text.split()) <= 600


@git_needed
def test_G1_close_refuses_without_the_decisions_confirmation(cli, proj):
    code, _, err = cli("session", "close", "--next", "x")
    assert code == 64 and "--decisions-logged" in err and not (proj / "development/HANDOFF.md").exists()


@git_needed
def test_G1_S5_uncommitted_process_records_refuse_unless_allowed(cli, proj):
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-23: a new decision\n")
    code, _, err = cli(*CLOSE)
    assert code != 0 and "development/DECISIONS.md" in err and not (proj / "development/HANDOFF.md").exists()
    code, _, err = cli(*CLOSE, "--allow-dirty")
    assert code == 0, err
    assert "development/DECISIONS.md" in (proj / "development/HANDOFF.md").read_text()


@git_needed
def test_G1_over_budget_refuses_and_names_the_longest_section(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write("")
    text = (proj / "steward.toml").read_text().replace("[session]\n", "[session]\nbudget_words = 60\n")
    (proj / "steward.toml").write_text(text)
    sh(proj, "git", "commit", "-qam", "budget")
    long = " ".join(["word"] * 80)
    code, _, err = cli("session", "close", "--decisions-logged", "--next", long)
    assert code != 0 and "Next" in err and "60" in err


@git_needed
def test_G1_a_private_term_or_home_path_refuses(cli, proj):
    code, _, err = cli("session", "close", "--decisions-logged", "--next", "see /" "Users/someone/notes")  # steward: allow R-07 (example)
    assert code != 0 and "local path" in err


@git_needed
def test_G1_open_findings_and_exchange_items_are_listed_by_id(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "ABC"\n')
    cli("exchange", "init")
    cli("exchange", "new", "request", "--to", "XYZ", "--title", "t")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "x")
    cli(*CLOSE)
    assert "ABC-REQ-001 (filed)" in (proj / "development/HANDOFF.md").read_text()


# ---------------------------------------------------------------- G2: start
@git_needed
def test_G2_start_prints_the_constitution_and_the_handoff_only(cli, proj):
    cli(*CLOSE)
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "handoff")
    code, out, _ = cli("session", "start")
    assert code == 0
    assert out.splitlines()[0].startswith("Constitution:")
    assert "G2: write the start command" in out and "Read the links under" in out
    assert "## Decisions" not in out  # nothing else is printed


@git_needed
def test_G2_start_without_a_handoff_says_so(cli, proj):
    code, out, _ = cli("session", "start")
    assert code == 0 and "No handoff yet" in out


# ---------------------------------------------------------------- G3: R-55 session.handoff (advisory)
@git_needed
def test_G3_r55_passes_for_a_committed_current_handoff(cli, proj):
    cli(*CLOSE)
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "handoff")
    _, rep = cli.check(proj, "session")
    assert one(rep, "R-55")["status"] == "PASS", one(rep, "R-55")


@git_needed
def test_G3_r55_a_decision_after_the_handoff_makes_it_stale_but_does_not_block_the_default_gate(cli, proj):
    from conftest import gate
    cli(*CLOSE)
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "handoff")
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-24: later\n")
    sh(proj, "git", "commit", "-qam", "later decision")
    _, rep = cli.check(proj)
    res = one(rep, "R-55")
    assert res["status"] == "INCOMPLETE" and "R-55.stale" in codes(res), res
    assert gate(rep)["eligible"], gate(rep)


@git_needed
def test_G3_r55_missing_and_malformed(cli, proj):
    _, rep = cli.check(proj, "session")
    assert one(rep, "R-55")["status"] == "INCOMPLETE"
    (proj / "development/HANDOFF.md").write_text("# Session handoff\n\n## State\nx\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "bad")
    _, rep = cli.check(proj, "session")
    res = one(rep, "R-55")
    assert res["status"] == "FAIL" and "R-55.shape" in codes(res), res


# ---------------------------------------------------------------- G4: --end
@git_needed
def test_G4_end_stops_toolkit_processes_removes_toolkit_caches_and_gives_the_harness_step(cli, proj, tmp_path):
    import json
    import sys
    import time
    cache = proj / ".steward/cache"
    cache.mkdir(parents=True)
    (cache / "x").write_text("x")
    # a leftover staged pre-push worktree
    import tempfile
    stale = Path(tempfile.mkdtemp(prefix="steward-push-")) / "wt"
    sh(proj, "git", "worktree", "add", "--detach", "-q", str(stale))
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()  # 0.12.0 (R4): the staged worktree records its owner; this pre-push has ended
    (stale.parent / "owner.json").write_text(json.dumps({"root": str(proj.resolve()), "pid": ended.pid}))
    # a toolkit MCP server recorded in its pid file
    # a stand-in carrying steward's MCP command line (`steward mcp`), as the server records itself
    # a stand-in that holds an MCP ownership lock (K1) and carries steward's MCP command line
    holder = ("import sys, time\nfrom pathlib import Path\nfrom steward.fsutil import owner_lock\n"
              "fd = owner_lock(Path(sys.argv[1]), 'mcp-test')\nprint('held', flush=True)\ntime.sleep(60)\n")
    mcp = subprocess.Popen([sys.executable, "-c", holder, str(proj), "steward", "mcp"], stdout=subprocess.PIPE, text=True)
    assert mcp.stdout.readline().strip() == "held"
    try:
        code, out, err = cli(*CLOSE, "--end", "--allow-dirty")
        assert code == 0, err
        for _ in range(50):
            if mcp.poll() is not None:
                break
            time.sleep(0.1)
        assert mcp.poll() is not None
    finally:
        if mcp.poll() is None:
            mcp.kill()
    assert not cache.exists() and str(stale) not in sh(proj, "git", "worktree", "list")
    text = (proj / "development/HANDOFF.md").read_text()
    assert "## Session end" in text and "run your harness's session delete command" in out
    assert "cannot" in out  # it says what it cannot do


@git_needed
def test_G4_end_never_stops_an_unrelated_process(cli, proj):
    import json
    import sys
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # holds no lock
    (proj / ".steward").mkdir(exist_ok=True)
    import psutil
    (proj / f".steward/mcp-{other.pid}.pid").write_text(  # right pid and start time, but not steward's MCP server
        json.dumps({"pid": other.pid, "created": psutil.Process(other.pid).create_time()}))
    try:
        cli(*CLOSE, "--end", "--allow-dirty")
        assert other.poll() is None
    finally:
        other.kill()
