"""0.6.2: runtime fingerprint (R-44) and git hooks."""

import shutil
import subprocess

import pytest

from conftest import codes, one


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\nrequired = []\nfingerprint = ["src/**/*.py"]\n')
    (tmp_path / "CITATION.cff").write_text('cff-version: 1.2.0\nmessage: "m"\ntitle: "t"\nauthors:\n  - name: "A"\n')
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/core.py").write_text('"""Docs."""\n\ndef f(x):\n    return x + 1\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_record_then_unchanged_passes(cli, repo):
    _, rep = cli.check(repo)
    assert one(rep, "R-44")["status"] == "INCOMPLETE"
    assert cli("release", "fingerprint", "--record")[0] == 0
    _, rep = cli.check(repo)
    assert one(rep, "R-44")["status"] == "PASS"


def test_comment_docstring_whitespace_changes_are_neutral(cli, repo):
    cli("release", "fingerprint", "--record")
    (repo / "src/pkg/core.py").write_text('"""Other docs."""\n# a comment\n\n\ndef f(x):\n    """Doc."""\n    return x + 1   # note\n')
    _, rep = cli.check(repo)
    assert one(rep, "R-44")["status"] == "PASS"


def test_code_change_fails_until_acknowledged(cli, repo):
    cli("release", "fingerprint", "--record")
    (repo / "src/pkg/core.py").write_text('def f(x):\n    return x + 2\n')
    code, rep = cli.check(repo)
    assert "R-44.changed" in codes(one(rep, "R-44")) and code == 1
    assert cli("release", "ack", "src/pkg/core.py", "--reason", "refactor checked by review")[0] == 0
    _, rep = cli.check(repo)
    assert one(rep, "R-44")["status"] == "PASS" and "R-44.acknowledged" in codes(one(rep, "R-44"))
    (repo / "src/pkg/core.py").write_text('def f(x):\n    return x + 3\n')  # an ack covers one fingerprint only
    _, rep = cli.check(repo)
    assert one(rep, "R-44")["status"] == "FAIL"


def test_added_module_and_syntax_error(cli, repo):
    cli("release", "fingerprint", "--record")
    (repo / "src/pkg/new.py").write_text("y = 1\n")
    (repo / "src/pkg/bad.py").write_text("def (:\n")
    _, rep = cli.check(repo)
    assert {"R-44.added", "R-44.unparsable"} <= codes(one(rep, "R-44"))


def test_not_configured(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-44")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- hooks
pytestmark_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def git(repo, *a, check=True):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=check)


@pytestmark_git
def test_hooks_install_keep_existing_and_force(cli, repo):
    git(repo, "init", "-q", "-b", "main")
    (repo / ".git/hooks/pre-commit").write_text("#!/bin/sh\necho mine\n")
    _, out, _ = cli("hooks", "install")
    assert "pre-commit: kept existing hook" in out and "pre-push: installed" in out
    assert (repo / ".git/hooks/pre-commit").read_text() == "#!/bin/sh\necho mine\n"
    _, out, _ = cli("hooks", "install", "--force")
    assert "pre-commit: installed" in out


@pytestmark_git
def test_pre_commit_blocks_on_fail(cli, repo):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@example.org")
    cli("hooks", "install")
    cli("release", "fingerprint", "--record")
    git(repo, "add", "-A")
    assert git(repo, "commit", "-qm", "ok", check=False).returncode == 0
    (repo / "src/pkg/core.py").write_text("def f(x):\n    return 0\n")  # R-44 FAIL
    git(repo, "add", "-A")
    r = git(repo, "commit", "-qm", "bad", check=False)
    assert r.returncode != 0 and "commit blocked" in r.stderr


@pytestmark_git
def test_pre_push_refuses_force_push_to_protected(cli, repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@example.org")
    cli("release", "fingerprint", "--record")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    cli("hooks", "install")
    (repo / "NOTES.md").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--amend", "-m", "rewritten", "--no-verify")
    r = git(repo, "push", "-q", "--force", "origin", "main", check=False)
    assert r.returncode != 0 and "force-push to protected branch" in r.stderr
