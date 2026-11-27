"""0.20.4: dispatching a task to Codex or Antigravity, headless (STW-046)."""

import os
import subprocess

import pytest

from test_v0120_features import gsh, xproj  # noqa: F401

TASK = """# Task: review of the change

- **ID:** T-007
- **Status:** proposed
- **GO reference:** the owner's decision of today
- **Owner:** the owner · **Approver:** the owner

## Goal
Review the change.

## Scope
- In: `git diff HEAD~1..HEAD -- src`; the file `src/tool.py`.

## Acceptance criteria
- [ ] A report.
"""


@pytest.fixture
def agents(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls.log"
    (bin_ / "codex").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n[ -n "$FAKE_DIRTY" ] && echo x >> README.md\n'
                                 'echo "# Independent review (fake codex)"\necho "Verdict. Fine."\n')
    (bin_ / "agy").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n'
                              'case "$*" in *--settings*) if [ -n "$FAKE_DENY" ]; then echo "jetski: no output produced — '
                              'a tool required the command permission that headless mode cannot prompt for, so it was '
                              'auto-denied" >&2; exit 0; fi;; esac\n'
                              'case "$*" in *"## Documents"*) echo "# Review from the documents"; echo "saw: $(echo "$*" | '
                              'grep -c "print(.v2.)")";; *) echo "# Review (fake agy)";; esac\n')
    for f in ("codex", "agy"):
        (bin_ / f).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return log


def _project(xproj):
    (xproj / "src").mkdir(exist_ok=True)
    (xproj / "src/tool.py").write_text("print('v1')\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "v1")
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    (xproj / "T-007.md").write_text(TASK)


def test_codex_review_runs_read_only_in_a_clean_checkout(cli, xproj, agents):
    _project(xproj)
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "codex")
    assert code == 0, err
    call = agents.read_text()
    assert "exec -s read-only --skip-git-repo-check -C" in call and ".steward/dispatch/review-T-007" in call  # W12b
    report = next((xproj / ".steward/dispatch").glob("*-T-007-codex.md"))
    assert "fake codex" in report.read_text()
    assert not (xproj / ".steward/dispatch/review-T-007").exists()  # the checkout is removed
    assert subprocess.run(["git", "worktree", "list"], cwd=xproj, capture_output=True, text=True).stdout.count("\n") == 1


def test_a_reviewer_that_changes_a_file_is_reported(cli, xproj, agents, monkeypatch):
    _project(xproj)
    monkeypatch.setenv("FAKE_DIRTY", "1")
    code, _, err = cli("task", "dispatch", "T-007.md", "--to", "codex")
    assert code == 0 and "changed 1 file" in err
    assert "x" not in (xproj / "README.md").read_text() if (xproj / "README.md").exists() else True


def test_antigravity_gets_a_sandbox_and_an_allow_list_never_skip_permissions(cli, xproj, agents):
    _project(xproj)
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "antigravity")
    assert code == 0, err
    call = agents.read_text()
    assert "--sandbox" in call and "--settings" in call and "dangerously" not in call
    assert "--model gemini-4-neon-high" in call
    settings = (xproj / ".steward/dispatch/agy-settings.json").read_text()
    # W12b (F8): a review's own read-only list: git's reading subcommands, never git as a whole
    assert "command(git log)" in settings and "command(git)" not in settings and "command(rm)" not in settings


def test_a_refused_antigravity_run_says_to_use_inline(cli, xproj, agents, monkeypatch):
    _project(xproj)
    monkeypatch.setenv("FAKE_DENY", "1")
    code, _, err = cli("task", "dispatch", "T-007.md", "--to", "antigravity")
    assert code == 65 and "--inline" in err and "never --dangerously-skip-permissions" in err


def test_inline_puts_the_documents_in_the_prompt_and_needs_no_tool(cli, xproj, agents, monkeypatch):
    _project(xproj)
    monkeypatch.setenv("FAKE_DENY", "1")  # tools would be refused; inline needs none
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "antigravity", "--inline")
    assert code == 0, err
    report = next((xproj / ".steward/dispatch").glob("*-T-007-antigravity.md")).read_text()
    assert "from the documents" in report and "saw: 1" in report  # the diff (with v2) was in the prompt
    assert "--settings" not in agents.read_text()


def test_a_dry_run_runs_nothing_and_placeholders_refuse(cli, xproj, agents):
    _project(xproj)
    code, out, _ = cli("task", "dispatch", "T-007.md", "--to", "codex", "--dry-run")
    assert code == 0 and "nothing was run" in out and not agents.exists()
    (xproj / "T-008.md").write_text(TASK.replace("the owner's decision of today", "… (the decision)"))
    assert cli("task", "dispatch", "T-008.md", "--to", "codex")[0] == 64
