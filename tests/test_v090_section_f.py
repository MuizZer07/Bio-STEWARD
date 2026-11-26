"""0.9.0, section F: requests and defects received through the exchange protocol (RELEASE_v0.9.0_SPEC §8). Each test
is named after its item ID."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git(path):
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.name", "T")
    sh(path, "git", "config", "user.email", "t@example.org")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_TRUST_BASELINE", raising=False)
    monkeypatch.delenv("STEWARD_TRUST_SIGNERS", raising=False)


ENTRY = '\n## 2026-11-20: adopt the toolkit\n- **Quote:** "adopt it"\n- **Decision:** adopted\n- **Consequences:** none\n'


@pytest.fixture
def decisions(cli, tmp_path, monkeypatch):
    r = tmp_path / "r"
    r.mkdir()
    _git(r)
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[integrity]\ndecisions_format = "template"\n')
    (r / "development/DECISIONS.md").write_text("# Decisions (append-only)\n" + ENTRY)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "base")
    monkeypatch.chdir(r)
    return r


def r38(cli, root):
    _, rep = cli.check(root, "integrity")
    return one(rep, "R-38")


# ---------------------------------------------------------------- DEF-021: wrapped and nested template fields
@git_needed
def test_DEF_021_wrapped_quote_and_nested_decision_are_well_formed(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-21: wrapped\n- **Quote:** not recorded verbatim (source: a note that\n  wraps here)\n"
                "- **Decision:**\n  1. item one\n  2. item two\n- **Consequences:**\n  - first\n")
    res = r38(cli, decisions)
    assert "R-38.entry_malformed" not in codes(res), res


@git_needed
def test_DEF_021_a_missing_field_is_still_malformed(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write('\n## 2026-11-21: no decision\n- **Quote:** "x"\n- **Consequences:** none\n')
    res = r38(cli, decisions)
    assert res["status"] == "FAIL" and "R-38.entry_malformed" in codes(res)


@git_needed
def test_DEF_021_an_empty_field_block_is_malformed(cli, decisions):
    with open(decisions / "development/DECISIONS.md", "a") as f:
        f.write('\n## 2026-11-21: empty\n- **Quote:** "x"\n- **Decision:**\n- **Consequences:** none\n')
    assert "R-38.entry_malformed" in codes(r38(cli, decisions))


# ---------------------------------------------------------------- DEF-022 (high): no false pass without a base log
@pytest.fixture
def integration(cli, tmp_path, monkeypatch):
    """The default branch has no decisions log; it was added on an integration branch."""
    r = tmp_path / "i"
    r.mkdir()
    _git(r)
    cli("init", "--repo", r)
    (r / "development/DECISIONS.md").unlink()
    with open(r / "steward.toml", "a") as f:
        f.write('\n[integrity]\ndecisions_format = "template"\n')
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "base without log")
    sh(r, "git", "checkout", "-q", "-b", "develop")
    (r / "development/DECISIONS.md").write_text("# Decisions\n" + ENTRY)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "log")
    with open(r / "development/DECISIONS.md", "a") as f:
        f.write(ENTRY.replace("2026-11-20", "2026-11-21").replace("adopt it", "second"))
    sh(r, "git", "commit", "-qam", "second entry")
    monkeypatch.chdir(r)
    return r


@git_needed
def test_DEF_022_a_rewrite_in_the_working_tree_is_found_without_a_base_log(cli, integration):
    p = integration / "development/DECISIONS.md"
    p.write_text(p.read_text().replace('"adopt it"', '"adopted it, edited"'))
    res = r38(cli, integration)
    assert res["status"] != "PASS", res
    assert "R-38.decisions_rewritten" in codes(res)


@git_needed
def test_DEF_022_a_rewrite_in_an_earlier_commit_is_found(cli, integration):
    p = integration / "development/DECISIONS.md"
    p.write_text(p.read_text().replace('"adopt it"', '"rewritten"'))
    sh(integration, "git", "commit", "-qam", "rewrite")
    with open(p, "a") as f:
        f.write(ENTRY.replace("2026-11-20", "2026-11-22"))
    sh(integration, "git", "commit", "-qam", "third")
    res = r38(cli, integration)
    assert res["status"] == "FAIL" and "R-38.decisions_rewritten" in codes(res), res


@git_needed
def test_DEF_022_an_append_only_history_passes_and_says_how_it_was_checked(cli, integration):
    res = r38(cli, integration)
    assert res["status"] == "PASS", res
    assert "R-38.append_only_history" in codes(res)


@git_needed
def test_DEF_022_the_configured_base_still_decides(cli, integration):
    p = integration / "development/DECISIONS.md"
    text = (integration / "steward.toml").read_text().replace('decisions_format = "template"',
                                                              'decisions_format = "template"\ndecisions_base = "develop"')
    (integration / "steward.toml").write_text(text)
    p.write_text(p.read_text().replace('"adopt it"', '"edited"'))
    res = r38(cli, integration)
    assert res["status"] == "FAIL" and "R-38.decisions_rewritten" in codes(res)


# ---------------------------------------------------------------- DEF-023: the .git file of a linked worktree
def test_DEF_023_r07_never_scans_the_git_file_of_a_linked_worktree(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[privacy]\ninclude = ["**/*"]\nexclude = [".git/**"]\n')
    # a linked worktree's .git is a file naming the main repository's absolute path
    (tmp_path / ".git").write_text("gitdir: /" "Users/someone/main/.git/worktrees/wt\n")  # steward: allow R-07 (example)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/.git").write_text("gitdir: /" "home/someone/main/.git/modules/sub\n")  # steward: allow R-07 (example)
    _, rep = cli.check(tmp_path, "privacy")
    res = one(rep, "R-07")
    assert res["status"] == "PASS", res
    from steward.fsutil import iter_repo_files
    assert not [f for f in iter_repo_files(tmp_path) if f == ".git" or f.endswith("/.git")]


# ---------------------------------------------------------------- DEF-024: local paths without a [privacy] table
def test_DEF_024_local_paths_are_checked_with_term_lists_only(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "policy"\nfile = "development/policy.txt"\npublic = true\n')
    (tmp_path / "development/policy.txt").write_text("AcmeHost\n")
    (tmp_path / "notes.md").write_text("see /" "Users/someone/x\n")  # steward: allow R-07 (example)
    _, rep = cli.check(tmp_path, "privacy")
    res = one(rep, "R-07")
    assert res["status"] == "FAIL" and "R-07.local_path" in codes(res), res


def test_DEF_024_local_paths_false_still_turns_it_off(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[privacy]\nlocal_paths = false\n[[terms]]\nname = "policy"\nfile = "development/policy.txt"\npublic = true\n')
    (tmp_path / "development/policy.txt").write_text("AcmeHost\n")
    (tmp_path / "notes.md").write_text("see /" "Users/someone/x\n")  # steward: allow R-07 (example)
    _, rep = cli.check(tmp_path, "privacy")
    assert "R-07.local_path" not in codes(one(rep, "R-07"))


# ---------------------------------------------------------------- DEF-001: home paths inside URLs
@pytest.mark.parametrize("line, found", [
    ("https://example.org/" "home/about/policies/", False),
    ("see <https://example.org/" "Users/guide/x>", False),
    ('open("/' 'home/user2/data.csv")', True),  # steward: allow R-07 (example)
    ("cd /" "Users/user2/project", True),  # steward: allow R-07 (example)
    ("file:///" "home/user2/x", True),  # steward: allow R-07 (example)
    ("path=/" "home/user2/x", True),  # steward: allow R-07 (example)
])
def test_DEF_001_urls_are_not_home_paths(line, found):
    from steward import privacy as pv
    hits, _ = pv.scan_text(line, [], True)
    assert bool(hits) is found, line


# ---------------------------------------------------------------- DEF-025, 026, 027: the requester's side
def _repo(cli, path, code, extra=""):
    path.mkdir()
    _git(path)
    cli("init", "--repo", path)
    with open(path / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "{code}"\n{extra}')
    cwd = os.getcwd()
    os.chdir(path)
    try:
        cli("exchange", "init")
    finally:
        os.chdir(cwd)
    sh(path, "git", "add", "-A")
    sh(path, "git", "commit", "-qm", "init")
    return path


@pytest.fixture
def requester(cli, tmp_path, monkeypatch):
    lib = _repo(cli, tmp_path / "lib", "LIB", 'peers = { APP = "../app" }\n')
    app = _repo(cli, tmp_path / "app", "APP", 'peers = { LIB = "../lib" }\n')
    monkeypatch.chdir(app)
    cli("exchange", "new", "defect", "--to", "LIB", "--title", "a generic defect")
    sh(app, "git", "add", "-A")
    sh(app, "git", "commit", "-qm", "file")
    monkeypatch.chdir(lib)
    cli("exchange", "pull", "APP")
    cli("exchange", "respond", "APP-DEF-001", "verified", "--note", "reproduced")
    sh(lib, "git", "add", "-A")
    sh(lib, "git", "commit", "-qm", "respond")
    monkeypatch.chdir(app)
    return lib, app


@git_needed
def test_DEF_026_a_pulled_response_to_an_own_item_is_not_an_orphan(cli, requester):
    lib, app = requester
    code, out, err = cli("exchange", "pull", "LIB")
    assert code == 0, err
    assert (app / "exchange/inbox/LIB-RSP-001.md").is_file()
    _, rep = cli.check(app, "governance")
    res = one(rep, "R-53")
    assert "R-53.orphan_response" not in codes(res) and res["status"] == "PASS", res


@git_needed
def test_DEF_025_the_receivers_state_is_an_observation_not_the_requesters(cli, requester):
    lib, app = requester
    cli("exchange", "pull", "LIB")
    log = [json.loads(l) for l in (app / "exchange/log.jsonl").read_text().splitlines()]
    own = [e for e in log if e.get("kind") == "state" and e.get("item") == "APP-DEF-001"]
    assert [e["state"] for e in own] == ["filed"]  # nothing claims the requester verified its own item
    obs = [e for e in log if e.get("kind") == "observed" and e.get("item") == "APP-DEF-001"]
    assert obs and obs[-1]["state"] == "verified" and obs[-1]["by"] == "LIB" and obs[-1]["evidence"] == "LIB-RSP-001"
    _, out, _ = cli("exchange", "status")
    line = next(l for l in out.splitlines() if l.startswith("APP-DEF-001"))
    assert "LIB: verified" in line


@git_needed
def test_DEF_025_the_requester_reaches_adopted_from_filed(cli, requester):
    lib, app = requester
    code, _, err = cli("exchange", "state", "APP-DEF-001", "adopted", "--note", "LIB v1.0; parity: parity.md")
    assert code == 0, err
    _, rep = cli.check(app, "governance")
    assert one(rep, "R-53")["status"] == "PASS"


@git_needed
def test_DEF_027_a_shipped_outbox_item_names_the_receivers_tag_without_failing(cli, requester):
    lib, app = requester
    code, _, err = cli("exchange", "state", "APP-DEF-001", "shipped", "--note", "LIB@v9.9.9")
    assert code == 0, err
    _, rep = cli.check(app, "governance")
    res = one(rep, "R-53")
    assert "R-53.tag_missing" not in codes(res) and "R-53.tag_not_verified" in codes(res), res


# ---------------------------------------------------------------- REQ-016: [policy] state = "pending"
def test_REQ_016_a_pending_policy_is_incomplete_with_steps_and_r38_keeps_its_own_check(cli, decisions):
    with open(decisions / "steward.toml", "a") as f:
        f.write('\n[policy]\nstate = "pending"\n')
    _, rep = cli.check(decisions)
    r33 = one(rep, "R-33")
    assert r33["status"] == "INCOMPLETE" and "R-33.pending" in codes(r33), r33
    r38_ = one(rep, "R-38")
    assert r38_["status"] == "PASS" and "R-38.append_only_weak" in codes(r38_), r38_


def test_REQ_016_pending_cannot_switch_off_a_pinned_policy(cli, decisions, monkeypatch):
    monkeypatch.setenv("STEWARD_TRUST_BASELINE", "0" * 40)
    monkeypatch.setenv("STEWARD_TRUST_SIGNERS", "x ssh-ed25519 AAAA")
    with open(decisions / "steward.toml", "a") as f:
        f.write('\n[policy]\nstate = "pending"\n')
    _, rep = cli.check(decisions)
    assert one(rep, "R-33")["status"] not in ("INCOMPLETE", "PASS", "NOT_APPLICABLE")


# ---------------------------------------------------------------- REQ-017: CI and approval-key setup documented
def test_REQ_017_the_ci_and_key_guide_covers_each_step():
    from conftest import REPO
    text = (REPO / "docs/ci.md").read_text()
    for needle in ("fine-grained", "Contents", "read-only", "x-access-token", "fetch-depth: 0", "ed25519-sk",
                   "allowed_signers", "steward authorize pin", "STEWARD_TRUST_BASELINE", "STEWARD_TRUST_SIGNERS",
                   "rotate"):
        assert needle in text, needle
    assert "docs/ci.md" in (REPO / "README.md").read_text()


# ================================================================ second intake (2026-11-23): DEF-002, 003, REQ-001, 002
# ---------------------------------------------------------------- DEF-002 (high): a stopped `steward run` stops its job
@pytest.mark.parametrize("sig, code", [("SIGINT", 130), ("SIGTERM", 143), ("SIGHUP", 129)])
def test_DEF_002_a_signal_to_steward_run_stops_the_job_records_it_and_exits_128_plus_n(cli, tmp_path, sig, code):
    import signal
    import sys
    import time

    import psutil
    r = tmp_path / "run"
    r.mkdir()
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write("\n[run]\nslots = { heavy = 1 }\n")
    proc = subprocess.Popen([sys.executable, "-m", "steward.cli", "run", "--slot", "heavy", "--",
                             sys.executable, "-c", "import time; time.sleep(60)"], cwd=r,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = None
    for _ in range(100):
        kids = psutil.Process(proc.pid).children(recursive=True)
        if kids:
            job = kids[0]
            break
        time.sleep(0.1)
    assert job is not None, "the job did not start"
    time.sleep(0.3)
    proc.send_signal(getattr(signal, sig))
    try:
        rc = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert rc == code
    assert not job.is_running() or job.status() == psutil.STATUS_ZOMBIE, "the job survived steward run"
    log = [json.loads(l) for l in (r / "development/runs.jsonl").read_text().splitlines()]
    out = next(e for e in log if e.get("kind") == "outcome")
    assert out["status"] == "interrupted" and out["breached"] == f"interrupted by {sig}"


# ---------------------------------------------------------------- DEF-003: a failed worktree removal refuses the push
@git_needed
def test_DEF_003_pre_push_refuses_when_the_temporary_worktree_cannot_be_removed(cli, tmp_path, monkeypatch, capsys):
    from steward import fsutil
    from steward import hooks as hk
    r = tmp_path / "pp"
    r.mkdir()
    _git(r)
    cli("init", "--repo", r)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "x")
    sha = sh(r, "git", "rev-parse", "HEAD")
    real = fsutil.git_run

    def failing(root, *args, **kw):
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess(args, 1, b"", b"busy")
        return real(root, *args, **kw)
    monkeypatch.setattr(fsutil, "git_run", failing)
    line = [f"refs/heads/main {sha} refs/heads/main {'0' * 40}"]
    assert hk.run_pre_push(r, "default", [], "skip", line) == 1
    assert "could not remove the temporary worktree" in capsys.readouterr().err
    monkeypatch.setattr(fsutil, "git_run", real)
    sh(r, "git", "worktree", "prune")
    assert hk.run_pre_push(r, "default", [], "skip", line) == 0
    assert "steward-push-" not in sh(r, "git", "worktree", "list")


# ---------------------------------------------------------------- REQ-001: branch protection without release checks
def test_REQ_001_branch_protection_alone_does_not_fail_release_integrity(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[branches]\nprotected = ["main", "develop"]\n')
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-42")["status"] == "NOT_APPLICABLE"
    from steward.cli import main
    assert main(["hooks", "install", "--dry-run", "--repo", str(tmp_path)]) in (0, 64)  # no git here: path query fails


def test_REQ_001_release_without_a_build_is_not_a_failure_until_final_or_built(cli, tmp_path):
    import zipfile
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\nprotected = ["main"]\n')
    _, rep = cli.check(tmp_path, "release")
    res = one(rep, "R-42")
    assert res["status"] == "NOT_APPLICABLE" and "R-42.missing_required" in codes(res), res  # said, not failed
    _, out, _ = cli("check", "--repo", tmp_path, "--format", "json", "--final", "release")
    assert one(json.loads(out), "R-42")["status"] == "FAIL"
    (tmp_path / "dist").mkdir()
    with zipfile.ZipFile(tmp_path / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
    _, rep = cli.check(tmp_path, "release")
    assert one(rep, "R-42")["status"] == "FAIL"  # built packages still need LICENSE and the citation


@git_needed
def test_REQ_001_hooks_take_protected_branches_from_branches(cli, tmp_path, monkeypatch):
    r = tmp_path / "b"
    r.mkdir()
    _git(r)
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[branches]\nprotected = ["main", "develop"]\n')
    monkeypatch.chdir(r)
    code, out, _ = cli("hooks", "install", "--dry-run")
    assert code == 0 and "protected: main develop" in out


# ---------------------------------------------------------------- REQ-002: chaining with an adopter's own hooks
@git_needed
def test_REQ_002_chain_keeps_the_adopters_hook_runs_both_and_unchains_byte_for_byte(cli, tmp_path, monkeypatch):
    r = tmp_path / "c"
    r.mkdir()
    _git(r)
    cli("init", "--repo", r)
    own = r / "scripts/hooks"
    own.mkdir(parents=True)
    (own / "pre-commit").write_text("#!/bin/sh\necho adopter-pre-commit >> \"$(git rev-parse --show-toplevel)/ran.txt\"\n"
                                    "[ -f STOP ] && exit 7\nexit 0\n")
    (own / "pre-commit").chmod(0o755)
    hooks = r / ".git/hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").symlink_to("../../scripts/hooks/pre-commit")
    before = os.readlink(hooks / "pre-commit")
    monkeypatch.chdir(r)
    code, out, err = cli("hooks", "install", "--chain")
    assert code == 0, err
    assert (hooks / "pre-commit.local").is_symlink() and os.readlink(hooks / "pre-commit.local") == before
    assert (own / "pre-commit").read_text().startswith("#!/bin/sh\necho adopter")  # never written through
    sh(r, "git", "add", "-A")
    p = subprocess.run(["git", "commit", "-qm", "x"], cwd=r, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "adopter-pre-commit" in (r / "ran.txt").read_text()
    (r / "STOP").write_text("x")
    sh(r, "git", "add", "STOP")
    p = subprocess.run(["git", "commit", "-qm", "y"], cwd=r, capture_output=True, text=True)
    assert p.returncode != 0  # the adopter's refusal still blocks
    p = subprocess.run([str(hooks / "pre-commit")], cwd=r, capture_output=True, text=True)
    assert p.returncode == 7  # and its exit code is kept
    code, out, err = cli("hooks", "remove")
    assert code == 0, err
    assert (hooks / "pre-commit").is_symlink() and os.readlink(hooks / "pre-commit") == before
    assert not (hooks / "pre-commit.local").exists() and not (hooks / "pre-push").exists()
