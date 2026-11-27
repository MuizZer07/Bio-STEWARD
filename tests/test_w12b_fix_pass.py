"""0.21.0 fix pass W12b: the independent review's findings F7, F8 and F9 on the sprint supervisor, and the review
dispatch limitation (a read-only reviewer's checkout had its .git outside the reviewer's sandbox).

Each test reproduces the reviewer's evidence where it is practical. Agents are stand-ins (shell commands and small
scripts), never the real CLIs, and no test reaches the network.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from steward import dispatch as dp
from steward import sprint as sp
from test_v0120_features import gsh, xproj  # noqa: F401
from test_w08_sprint import _no_network, events, one_task, repo, states, task, write_sprint  # noqa: F401

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def _wait(pred, seconds=30):
    deadline = time.monotonic() + seconds
    while not pred() and time.monotonic() < deadline:
        time.sleep(0.05)
    return pred()


def _run_dispatch(repo, watch=False):
    from steward.models import load_config

    said: list[str] = []
    code = sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), watch=watch, poll=0.1, out=said.append)
    return code, said


def _edit_script(tmp_path, pairs):
    """A stand-in for an agent that writes the sprint file of the main checkout from inside its worktree (as Claude
    Code's Edit can), then keeps running a moment."""
    script = tmp_path / "tamper.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "p = pathlib.Path('../../../../development/sprints/day1.toml')\n"
        "s = p.read_text()\n"
        f"for a, b in {pairs!r}:\n"
        "    s = s.replace(a, b)\n"
        "p.write_text(s)\n"
        "time.sleep(1.0)\n")
    return f"{sys.executable} {script}"


# ---------------------------------------------------------------- F7
def test_W12_F7_a_running_task_cannot_rewrite_its_own_done_commands(cli, repo, tmp_path, monkeypatch):
    mark = tmp_path / "injected"
    monkeypatch.setenv("W12_MARK", str(mark))
    cmd = _edit_script(tmp_path, [('done = ["false"]', 'done = ["touch $W12_MARK"]')])
    write_sprint(repo, task("T1", cmd, '["false"]'))
    _run_dispatch(repo)
    assert not mark.exists()  # the injected done command never ran
    s = states(cli)["T1"]
    assert s["state"] == "failed" and [c["command"] for c in s["checks"]] == ["false"]
    held = [e for e in events(repo) if e["kind"] == "reloaded"]
    assert held and held[0]["held"] is True and held[0]["running"] == ["T1"]


def test_W12_F7_a_change_made_while_a_task_ran_is_not_used_without_an_order(cli, repo, tmp_path, monkeypatch):
    mark = tmp_path / "t2-tampered"
    monkeypatch.setenv("W12_MARK", str(mark))
    cmd = _edit_script(tmp_path, [('command = "true"', 'command = "touch $W12_MARK"')])
    write_sprint(repo, task("T1", cmd) + task("T2", "true"), dispatch="auto")
    code, said = _run_dispatch(repo)
    assert not mark.exists()  # T2 ran the command the human wrote, not the one T1 wrote
    s = states(cli)
    assert s["T1"]["state"] == "done" and s["T2"]["state"] == "done"
    assert any("steward sprint reload day1" in m for m in said)
    assert not [e for e in events(repo) if e["kind"] == "reloaded" and e.get("valid")]


def test_W12_F7_a_reload_order_applies_a_change_but_never_to_the_running_task(cli, repo, tmp_path, monkeypatch):
    t1_mark, t2_mark = tmp_path / "t1-new-done", tmp_path / "t2-new-command"
    gate = tmp_path / "gate"
    monkeypatch.setenv("W12_GATE", str(gate))
    write_sprint(repo, task("T1", 'while [ ! -f "$W12_GATE" ]; do sleep 0.05; done', '["true"]')
                 + task("T2", "true", extra='after = ["T1"]'), dispatch="auto")
    th = threading.Thread(target=lambda: _run_dispatch(repo, watch=True))
    th.start()
    try:
        assert _wait(lambda: (repo / "development/sprints/day1.jsonl").exists()
                     and states(cli)["T1"]["state"] == "running")
        p = repo / "development/sprints/day1.toml"
        text = p.read_text()
        p.write_text(text.replace('done = ["true"]', f'done = ["touch {t1_mark}"]', 1)
                     .replace('command = "true"', f'command = "touch {t2_mark}"'))
        code, out, err = cli("sprint", "reload", "day1")
        assert code == 0 and "reload ordered" in out, err
        assert _wait(lambda: any(e["kind"] == "reloaded" and e.get("by") == "human" for e in events(repo)))
        gate.write_text("go")
        assert _wait(lambda: states(cli)["T2"]["state"] in ("done", "failed"))
    finally:
        cli("sprint", "stop", "day1")
        th.join(30)
    assert not t1_mark.exists()  # T1 kept the done commands it started with
    assert t2_mark.exists()  # T2 had not started: the human's change applies to it
    rl = next(e for e in events(repo) if e["kind"] == "reloaded" and e.get("by") == "human")
    assert rl["valid"] and rl["refused"] == ["T1"]
    order = next(e for e in events(repo) if e.get("kind") == "order" and e.get("order") == "reload")
    assert order["by"] == "human"
    assert cli("check", "sprints", "--format", "json")[0] == 0  # R-71 accepts the order and the record


# ---------------------------------------------------------------- F8
@pytest.mark.parametrize("entry", [
    "git", "git*", "git  push", "git\\tpush", "/usr/bin/git push", "git -C . push", "git -c a=b push origin",
    "env", "env git push", "env A=1 git push", "sh -c", "bash -c 'git push'", "nohup git push", "xargs git push",
    "steward", "python -m steward.cli authorize", "uv run steward sprint", "gh", "npm", "uv",
])
def test_W12_F8_an_allow_entry_that_covers_a_default_deny_is_refused(entry):
    with pytest.raises(ValueError, match="default deny list"):
        one_task("claude-code", f'allow = ["{entry}"]')


@pytest.mark.parametrize("entry", ["python", "python3 -c", "python -m", "node", "make*", "make; git push"])
def test_W12_F8_an_allow_entry_that_runs_anything_is_refused(entry):
    with pytest.raises(ValueError, match="cannot name|not command prefixes"):
        one_task("claude-code", f'allow = ["{entry}"]')


@pytest.mark.parametrize("entry", ["make test", "python -m pytest", "uv run pytest", "git status", "npm test"])
def test_W12_F8_exact_command_prefixes_are_still_allowed(entry):
    one_task("claude-code", f'allow = ["{entry}"]')


def test_W12_F8_normalise_reads_paths_wrappers_and_git_options():
    assert sp.normalise("/usr/bin/git   push") == "git push"
    assert sp.normalise("env -i A=1 nohup /bin/sh -c 'git -C /x push origin'") == "git push origin"
    assert sp.normalise("uv run --extra dev python3 -m steward.cli spend") == "steward spend"
    assert sp.normalise("xargs -0 env") == ""
    assert sp.normalise("make test *") == "make test"


def test_W12_F8_claude_gets_the_allow_entry_with_one_space_between_words():
    sf, t = one_task("claude-code", 'allow = ["make   test"]')
    argv = sp.command(t, sf)
    assert "Bash(make test *)" in argv and "Bash(make   test *)" not in argv


def test_W12_F8_antigravity_edit_and_run_gets_no_wrapper_or_interpreter():
    sf, t = one_task("antigravity", 'permissions = "edit-and-run"')
    allow = sp.agy_settings(t)["permissions"]["allow"]
    for c in ("env", "python", "python3", "uv", "git"):
        assert f"command({c})" not in allow
    assert "command(pytest)" in allow and "command(git commit)" in allow


def test_W12_F8_review_dispatch_has_its_own_read_only_list(xproj):
    for c in ("git", "env", "python", "python3", "cp", "mkdir", "touch", "tar", "sed", "uv", "find"):
        assert c not in dp.REVIEW
    assert {"git log", "git diff", "python -m pytest"} <= set(dp.REVIEW)
    doc = json.loads(dp.agy_settings(xproj).read_text())["permissions"]
    assert "command(git push)" in doc["deny"] and "command(git log)" in doc["allow"]
    assert "command(env)" not in doc["allow"]


# ---------------------------------------------------------------- F9
def test_W12_F9_the_codex_commit_step_runs_no_repository_hook(repo, tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    mark = tmp_path / "hook-ran"
    for name in ("pre-commit", "commit-msg", "post-commit"):
        (hooks / name).write_text(f"#!/bin/sh\necho {name} >> {mark}\n")
        (hooks / name).chmod(0o755)
    subprocess.run(["git", "config", "core.hooksPath", str(hooks)], cwd=repo, check=True)
    r = subprocess.run(["/bin/sh", "-c", sp.COMMIT_STEP, "steward-sprint-commit", "by codex",
                        "/bin/sh", "-c", "echo x > made.txt"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert gsh(repo, "git", "log", "-1", "--format=%s") == "by codex"
    assert not mark.exists()
    assert "core.hooksPath=/dev/null" in sp.COMMIT_STEP and "--no-verify" in sp.COMMIT_STEP


def test_W12_F9_a_linked_parent_folder_does_not_take_the_worktree_outside(cli, repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".steward").mkdir(exist_ok=True)
    shutil.rmtree(repo / ".steward/sprints", ignore_errors=True)
    (repo / ".steward/sprints").symlink_to(outside)
    write_sprint(repo, task("T1"))
    _run_dispatch(repo)
    s = states(cli)["T1"]
    assert s["state"] == "failed" and "link" in s["note"]
    assert list(outside.iterdir()) == []


def test_W12_F9_a_task_log_is_never_opened_through_a_linked_folder(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".steward/sprints").mkdir(parents=True, exist_ok=True)
    (repo / ".steward/sprints/day1").symlink_to(outside)
    with pytest.raises(OSError):
        sp._open_log(repo, ".steward/sprints/day1/T1.log")
    assert list(outside.iterdir()) == []


def test_W12_F9_a_task_without_a_worktree_fails_on_a_linked_log_folder(cli, repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".steward/sprints").mkdir(parents=True, exist_ok=True)
    (repo / ".steward/sprints/day1").symlink_to(outside)
    write_sprint(repo, task("T1", extra="worktree = false"))
    _run_dispatch(repo)
    s = states(cli)["T1"]
    assert s["state"] == "failed" and "opened safely" in s["note"]
    assert list(outside.iterdir()) == []


def test_W12_F9_the_codex_summary_says_the_deny_list_is_not_enforced():
    _, t = one_task("codex", 'permissions = "edit"\nrequires = ["network"]')
    text = sp.permission_summary(t)
    assert "denied: the default list" not in text and "not enforced" in text and "npm publish" in text
    _, t = one_task("codex", 'permissions = "edit"')
    text = sp.permission_summary(t)
    assert "not enforced" in text and "network being off" in text
    _, t = one_task("claude-code")
    assert "denied: the default list" in sp.permission_summary(t)


# ---------------------------------------------------------------- the review dispatch limitation
REVIEW_TASK = """# Task: review of the change

- **ID:** T-007
- **Status:** proposed
- **GO reference:** the owner's decision of today
- **Owner:** the owner · **Approver:** the owner

## Goal
Review the change.

## Scope
- In: `git diff HEAD~1..HEAD -- src`.

## Acceptance criteria
- [ ] A report.
"""


def test_W12_dispatch_a_reviewer_gets_a_clone_where_git_and_pytest_work(cli, xproj, tmp_path, monkeypatch):
    (xproj / "src").mkdir(exist_ok=True)
    (xproj / "src/tool.py").write_text("print('v1')\n")
    (xproj / "checks").mkdir()
    (xproj / "checks/test_tool.py").write_text("def test_one():\n    assert 1 + 1 == 2\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "v1")
    (xproj / "src/tool.py").write_text("print('v2')\n")
    gsh(xproj, "git", "commit", "-qam", "v2")
    (xproj / "T-007.md").write_text(REVIEW_TASK)
    refs_before = gsh(xproj, "git", "for-each-ref")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    # a stand-in for Codex: it runs, in the folder it is given, what the 0.21.0 reviewer could not
    (bin_ / "codex").write_text(
        "#!/bin/sh\n"
        'while [ "$1" != "-C" ]; do shift; done; cd "$2" || exit 9\n'
        'echo "gitdir: $(git rev-parse --absolute-git-dir)"\n'
        'echo "top: $(pwd -P)"\n'
        'echo "log: $(git log --format=%s | tr "\\n" " ")"\n'
        'echo "diff: $(git diff --stat HEAD~1..HEAD -- src | head -1)"\n'
        'echo "remotes: [$(git remote)]"\n'
        f'echo "pytest: $({sys.executable} -m pytest -q -p no:cacheprovider checks 2>&1 | tail -1)"\n'
        'git push origin HEAD:refs/heads/injected >/dev/null 2>&1 && echo "push: yes" || echo "push: no"\n')
    (bin_ / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "codex")
    assert code == 0, err
    report = next((xproj / ".steward/dispatch").glob("*-T-007-codex.md")).read_text()
    got = dict(ln.split(": ", 1) for ln in report.splitlines() if ": " in ln)
    top = got["top"]
    assert top.endswith(".steward/dispatch/review-T-007")
    assert got["gitdir"] == top + "/.git"  # .git inside the reviewer's folder, so its sandbox can read it
    assert got["log"].split()[:2] == ["v2", "v1"] and "src/tool.py" in got["diff"]
    assert got["remotes"] == "[]" and got["push"] == "no"
    assert "1 passed" in got["pytest"]
    assert gsh(xproj, "git", "for-each-ref") == refs_before  # the source repository is unchanged
    assert gsh(xproj, "git", "worktree", "list").count("\n") == 0
    assert not (xproj / ".steward/dispatch/review-T-007").exists()  # removed after the review


def test_W12_dispatch_the_clone_shares_no_file_with_the_source(xproj):
    (xproj / "a.txt").write_text("a\n")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "a")
    dest = dp.review_clone(xproj, "T-1")
    try:
        assert (dest / ".git").is_dir() and (dest / "a.txt").read_text() == "a\n"
        for dirpath, _, files in os.walk(dest / ".git/objects"):
            for f in files:
                assert os.stat(os.path.join(dirpath, f)).st_nlink == 1  # copied, never hard linked
        assert gsh(dest, "git", "rev-parse", "HEAD") == gsh(xproj, "git", "rev-parse", "HEAD")
        assert subprocess.run(["git", "remote"], cwd=dest, capture_output=True, text=True).stdout == ""
    finally:
        dp.remove_checkout(xproj, dest)
    assert not dest.exists()
