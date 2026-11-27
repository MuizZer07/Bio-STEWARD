"""0.21.0 W08: sprint adapters with permissions (STW-051), task logs and live status (STW-052), S1 - S14 (STW-053).

Agent CLIs are not run here: small stand-ins on PATH read the argv the adapter built and act as that argv permits
(Claude Code: a denied pattern wins over an allowed one). They test the contract between the adapter and the agent's
flags, not the agent itself.
"""

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

from steward import sprint as sp

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    real = socket.socket.connect

    def guard(self, address, *a, **k):
        if isinstance(address, tuple):
            pytest.fail(f"network access to {address}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    for k, v in (("GIT_AUTHOR_NAME", "T"), ("GIT_AUTHOR_EMAIL", "t@example.org"),
                 ("GIT_COMMITTER_NAME", "T"), ("GIT_COMMITTER_EMAIL", "t@example.org")):
        monkeypatch.setenv(k, v)
    r = tmp_path / "r"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


def _iso(hours):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).replace(microsecond=0).isoformat()


def write_sprint(repo, tasks, dispatch="auto", start=-1, end=8, meta=""):
    (repo / "development/sprints").mkdir(parents=True, exist_ok=True)
    (repo / "development/sprints/day1.toml").write_text(
        f'schema = "steward.sprint/0.1"\n[sprint]\nid = "day1"\n'
        f"window = {{ start = {_iso(start)}, end = {_iso(end)} }}\n"
        f'dispatch = "{dispatch}"\n{meta}\n{tasks}')


def task(tid, command="true", done='["true"]', extra=""):
    return (f'\n[[task]]\nid = "{tid}"\ntitle = "task {tid}"\nagent = "shell"\ncommand = {json.dumps(command)}\n'
            f"limits = {{ wall_minutes = 5 }}\ndone = {done}\n{extra}\n")


def agent_task(tid, agent, extra="", done='["true"]'):
    return (f'\n[[task]]\nid = "{tid}"\ntitle = "task {tid}"\nagent = "{agent}"\nprompt = "Do it."\n'
            f'limits = {{ wall_minutes = 5 }}\ndone = {done}\n{extra}\n')


def states(cli):
    code, out, err = cli("sprint", "status", "day1", "--format", "json")
    assert code == 0, err
    return {t["id"]: t for t in json.loads(out)["tasks"]}


def events(repo):
    return [json.loads(ln) for ln in (repo / "development/sprints/day1.jsonl").read_text().splitlines()]


def test_STW054_supervisor_fault_prints_the_hint(cli, repo, monkeypatch):
    from steward import issues

    write_sprint(repo, task("T1"))

    def cannot_set_up(*args):
        raise sp.WorktreeSetupError("test worktree failure")

    monkeypatch.setattr(sp, "_worktree", cannot_set_up)
    code, _, err = cli("sprint", "start", "day1")
    fault = issues.read_last_error(repo)
    assert code == 0 and fault.exit_code == code and issues.HINT in err
    assert fault.command == "sprint start" and fault.error_type == "WorktreeSetupError"
    assert states(cli)["T1"]["state"] == "failed"


def parse(text):
    sf = sp.SprintFile.model_validate(__import__("tomllib").loads(text))
    return sf, sf.task[0]


SPRINT_HEAD = ('schema = "steward.sprint/0.1"\n[sprint]\nid = "s"\n'
               "window = { start = 2026-11-27T00:00:00Z, end = 2026-11-28T00:00:00Z }\n")


def one_task(agent, extra=""):
    body = 'command = "true"\n' if agent == "shell" else 'prompt = "Do it."\n'
    return parse(SPRINT_HEAD + f'[[task]]\nid = "T1"\ntitle = "t"\nagent = "{agent}"\n{body}done = ["true"]\n{extra}')


def _between(argv, flag):
    i = argv.index(flag) + 1
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


# ---------------------------------------------------------------- STW-051: each adapter's argv
@pytest.mark.parametrize("perm", sp.PERMISSIONS)
def test_claude_code_argv_maps_permissions_and_the_default_deny_list(perm):
    sf, t = one_task("claude-code", f'permissions = "{perm}"\nallow = ["make test"]\ndeny = ["rm -rf"]\nmodel = "m1"')
    argv = sp.command(t, sf)
    assert argv[:3] == ["claude", "-p", sp.agent_prompt(t, sf)] and argv[-2:] == ["--model", "m1"]
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    allowed, denied = _between(argv, "--allowedTools"), _between(argv, "--disallowedTools")
    for d in sp.DEFAULT_DENY + ("rm -rf",):
        assert f"Bash({d})" in denied and f"Bash({d} *)" in denied
    assert "Bash(make test *)" in allowed and "WebFetch" in denied
    mode = argv[argv.index("--permission-mode") + 1]
    if perm == "read-only":
        assert mode == "default" and "Edit" in denied and "Edit" not in allowed and "Bash" not in allowed
    else:
        assert mode == "acceptEdits" and {"Edit", "Write", "Bash(git commit *)"} <= set(allowed)
    assert ("Bash" in allowed) == (perm == "edit-and-run")
    prompt = sp.agent_prompt(t, sf)
    assert f"`{perm}`" in prompt and "git push" in prompt and "make test" in prompt


def test_codex_argv_has_its_sandbox_event_stream_and_commit_step():
    sf, t = one_task("codex", 'permissions = "edit-and-run"\nrequires = ["network"]\nmodel = "c1"')
    argv = sp.command(t, sf)
    assert argv[:3] == ["/bin/sh", "-c", sp.COMMIT_STEP]
    inner = argv[5:]
    assert inner[:6] == ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check", "--json"]
    assert "sandbox_workspace_write.network_access=true" in inner and inner[-3:-1] == ["-m", "c1"]
    assert "written by Codex, committed by the sprint task" in argv[4]
    prompt = inner[-1]
    assert "Do not commit" in prompt and "steward sprint" in prompt
    sf, t = one_task("codex", 'permissions = "read-only"')
    argv = sp.command(t, sf)
    assert argv[:4] == ["codex", "exec", "-s", "read-only"] and "network_access" not in " ".join(argv)


def test_antigravity_argv_and_settings_carry_the_deny_list(tmp_path):
    sf, t = one_task("antigravity", 'permissions = "edit"\nallow = ["make test"]\nmodel = "g1"')
    settings = tmp_path / "s.json"
    argv = sp.command(t, sf, settings)
    assert argv[0].endswith("agy") and argv[1:3] == ["-p", sp.agent_prompt(t, sf)]
    assert argv[argv.index("--model") + 1] == "g1" and "--sandbox" in argv and argv[-2:] == ["--settings", str(settings)]
    doc = sp.agy_settings(t)["permissions"]
    assert {f"command({d})" for d in sp.DEFAULT_DENY} <= set(doc["deny"])
    assert {"command(git commit)", "command(make test)"} <= set(doc["allow"])
    assert not [a for a in doc["allow"] if a in doc["deny"]]


def test_shell_argv_is_unchanged():
    sf, t = one_task("shell")
    assert sp.command(t, sf) == ["/bin/sh", "-c", "true"]


@pytest.mark.parametrize("extra, msg", [
    ('allow = ["git push"]', "default deny list"),
    ('allow = ["git push origin main"]', "default deny list"),
    ('allow = ["steward sprint *"]', "default deny list"),
    ('allow = ["echo $(id)"]', "not command prefixes"),
    ('requires = ["display"]', "cannot offer display"),
])
def test_a_task_cannot_remove_a_default_deny_or_ask_codex_for_a_display(extra, msg):
    with pytest.raises(ValueError, match=msg):
        one_task("codex", extra)


def test_check_states_the_permissions_and_warns_about_read_only_tasks(cli, repo):
    write_sprint(repo, agent_task("T1", "claude-code", 'permissions = "read-only"')
                 + agent_task("T2", "codex", 'permissions = "edit"'))
    code, out, err = cli("sprint", "check", "day1")
    assert code == 0, err
    assert "permissions: T1: claude-code, read-only" in out
    assert "permissions: T2: codex, edit" in out and "committed by the sprint after Codex exits" in out
    assert "denied for every agent task: git push" in out
    assert "warning: T1 is read-only" in out


# ---------------------------------------------------------------- stand-in agents on PATH
FAKE_CLAUDE = r'''
import json, subprocess, sys
a = sys.argv[1:]
def between(flag):
    i, out = a.index(flag) + 1, []
    while i < len(a) and not a[i].startswith("--"):
        out.append(a[i]); i += 1
    return out
allowed, denied = between("--allowedTools"), between("--disallowedTools")
mode = a[a.index("--permission-mode") + 1]
def matches(p, cmd):
    if p == "Bash":
        return True
    if not p.startswith("Bash("):
        return False
    body = p[5:-1]
    return cmd == body or (body.endswith(" *") and cmd.startswith(body[:-2] + " "))
def permitted(cmd):  # Claude Code: a denied pattern wins over an allowed one
    return not any(matches(p, cmd) for p in denied) and any(matches(p, cmd) for p in allowed)
def step(name, inp):
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}), flush=True)
if mode == "acceptEdits" and "Write" in allowed:
    open("edited.txt", "w").write("edited\n")
    step("Write", {"file_path": "edited.txt", "content": "SECRET-CONTENT"})
for cmd in ("git add edited.txt", "git commit -qm edited"):
    step("Bash", {"command": cmd})
    if permitted(cmd):
        subprocess.run(cmd.split(), check=True)
step("Bash", {"command": "git push origin HEAD"})
if permitted("git push origin HEAD"):
    subprocess.run(["git", "push", "-q", "origin", "HEAD"], check=True)
else:
    print("denied: git push", flush=True)
print(json.dumps({"type": "result", "result": "finished"}))
'''

FAKE_CODEX = r'''
import json, sys
a = sys.argv[1:]
assert a[0] == "exec" and a[a.index("-s") + 1] == "workspace-write" and "--json" in a
assert sys.stdin.read() == ""  # stdin is closed: it never waits for input
print(json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "bash -lc 'ls'\nsecond line"}}))
open("codex.txt", "w").write("from codex\n")
print(json.dumps({"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "codex.txt", "kind": "add"}]}}))
'''


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
        f = b / name
        f.write_text(f"#!{sys.executable}\n{body}")
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    return b


def test_a_dispatched_claude_code_task_can_edit_and_commit_but_cannot_push(cli, repo, tmp_path, fake_bin):
    bare = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", str(bare))
    sh(repo, "git", "remote", "add", "origin", str(bare))
    write_sprint(repo, agent_task("T1", "claude-code", 'permissions = "edit"', done='["test -f edited.txt"]'))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    s = states(cli)["T1"]
    assert s["state"] == "done", s
    assert sh(repo, "git", "show", "sprint/day1/T1:edited.txt") == "edited"
    assert sh(bare, "git", "for-each-ref") == ""  # nothing was pushed
    log = (repo / s["log"]).read_text()
    assert "denied: git push" in log
    assert s["last_step"] == {"tool": "Bash", "command": "git push origin HEAD"}
    assert s["agent"] == "claude-code" and s["permissions"] == "edit"
    assert [c["subject"] for c in s["commits"]] == ["edited"] and s["changed_files"] == ["edited.txt"]
    _, raw, _ = cli("sprint", "status", "day1", "--format", "json")
    assert "SECRET-CONTENT" not in raw  # tool names and commands, never file contents
    running = next(e for e in events(repo) if e.get("state") == "running")
    assert running["agent"] == "claude-code" and running["permissions"] == "edit"  # S5


def test_codex_work_is_committed_after_it_exits(cli, repo, fake_bin):
    write_sprint(repo, agent_task("T1", "codex", 'permissions = "edit"'))
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    s = states(cli)["T1"]
    assert s["state"] == "done", s
    assert sh(repo, "git", "show", "sprint/day1/T1:codex.txt") == "from codex"
    assert "written by Codex, committed by the sprint task" in sh(repo, "git", "log", "-1", "--format=%s", "sprint/day1/T1")
    assert s["last_step"] == {"tool": "file_change", "command": "codex.txt"}


# ---------------------------------------------------------------- STW-052: logs, status, watch
def test_a_shell_task_that_commits_twice_shows_both_commits_and_the_final_checks_in_watch(cli, repo):
    write_sprint(repo, task("T1", "echo a > a.txt && git add a.txt && git commit -qm 'first commit' && "
                            "echo b > b.txt && git add b.txt && git commit -qm 'second commit' && echo progress",
                            '["test -f a.txt", "test -f b.txt"]'))
    assert cli("sprint", "start", "day1")[0] == 0
    code, out, err = cli("sprint", "watch", "day1", "--poll", "0.1")
    assert code == 0, err
    assert "first commit" in out and "second commit" in out
    assert "T1 done: 2 of 2 checks passed (test -f a.txt -> 0; test -f b.txt -> 0)" in out
    s = states(cli)["T1"]
    assert s["log"] == ".steward/sprints/day1/T1.log" and "progress" in (repo / s["log"]).read_text()
    assert s["run"] and s["run_log"] == f".steward/runs/{s['run']}.log" and (repo / s["run_log"]).is_file()
    runs = (repo / "development/runs.jsonl").read_text()
    assert f'"run":"{s["run"]}"' in runs  # S7: the task's run is the run ledger's
    assert s["started"] and s["ended"] and s["last_commit_subject"] == "second commit"
    assert sh(repo, "git", "check-ignore", s["log"])  # the log is git-ignored: never in a published export


def test_watch_follows_a_running_sprint_and_exits_when_nothing_runs(cli, repo):
    write_sprint(repo, task("T1", "sleep 1 && echo a > a.txt && git add a.txt && git commit -qm live", '["true"]'))
    from steward.models import load_config

    lines: list[str] = []
    th = threading.Thread(target=lambda: sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), out=lambda m: None))
    th.start()
    deadline = time.monotonic() + 20
    while not (repo / "development/sprints/day1.jsonl").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sp.watch(repo, "day1", poll=0.1, out=lines.append) == 0
    th.join()
    text = "\n".join(lines)
    assert "T1 running (shell)" in text and "live" in text and "T1 done" in text


@pytest.mark.parametrize("ev, want", [
    ({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"},
      {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "SECRET"}}]}},
     {"tool": "Edit", "command": "a.py"}),
    ({"type": "item.completed", "item": {"type": "command_execution", "command": "pytest -q\nsecond"}},
     {"tool": "shell", "command": "pytest -q"}),
    ({"msg": {"type": "exec_command_begin", "command": ["bash", "-lc", "ls"]}}, {"tool": "shell", "command": "bash -lc ls"}),
    ({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write",
      "input": {"content": "SECRET"}}]}}, {"tool": "Write", "command": ""}),
])
def test_last_step_names_the_tool_and_command_never_file_text(tmp_path, ev, want):
    log = tmp_path / "t.log"
    log.write_text("plain output\n" + json.dumps(ev) + "\nnot json {\n")
    assert sp.last_step(log) == want


# ---------------------------------------------------------------- STW-053
def test_S1_a_command_edited_after_start_is_the_one_that_runs(cli, repo):
    write_sprint(repo, task("T1", "exit 3", '["test -f b.txt"]'), dispatch="order")
    from steward.models import load_config

    said: list[str] = []
    th = threading.Thread(target=lambda: sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), watch=True,
                                                     poll=0.1, out=said.append))
    th.start()
    try:
        deadline = time.monotonic() + 10
        while not (repo / "development/sprints/day1.jsonl").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        p = repo / "development/sprints/day1.toml"
        p.write_text(p.read_text().replace('"exit 3"', '"echo b > b.txt && git add b.txt && git commit -qm b"'))
        assert cli("sprint", "go", "day1", "T1")[0] == 0
        deadline = time.monotonic() + 30
        while states(cli)["T1"]["state"] != "done" and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        cli("sprint", "stop", "day1")
        th.join(30)
    assert states(cli)["T1"]["state"] == "done"
    evs = events(repo)
    reload = next(e for e in evs if e["kind"] == "reloaded")
    assert reload["valid"] and reload["changed"] == ["T1"]
    running = next(e for e in evs if e.get("state") == "running")
    assert running["task_sha256"] == sp.task_sha(sp.load(repo, "day1").task[0])
    assert any("the sprint file changed (changed T1)" in m for m in said)


def test_S2_recheck_records_done_on_passing_checks_and_failed_otherwise(cli, repo):
    write_sprint(repo, task("T1", "echo a > a.txt", '["test -f a.txt"]') + task("T2", extra='after = ["T1"]'))
    cli("sprint", "start", "day1")
    s = states(cli)
    assert s["T1"]["state"] == "failed" and s["T2"]["state"] == "blocked"
    assert s["T1"]["uncommitted"] == ["?? a.txt"] and "a.txt" in s["T1"]["note"]  # S14: the paths
    wt = repo / ".steward/sprints/day1/T1"
    (wt / "a.txt").unlink()
    sh(wt, "git", "commit", "--allow-empty", "-qm", "by hand")
    code, out, _ = cli("sprint", "recheck", "day1", "T1")
    assert code == 1 and states(cli)["T1"]["state"] == "failed"
    (wt / "a.txt").write_text("a\n")
    sh(wt, "git", "add", "a.txt")
    sh(wt, "git", "commit", "-qm", "the work, committed by hand")
    code, out, err = cli("sprint", "recheck", "day1", "T1")
    assert code == 0, err
    s = states(cli)
    head = sh(repo, "git", "rev-parse", "sprint/day1/T1")
    assert s["T1"]["state"] == "done" and s["T1"]["commit"] == head and s["T1"]["checks"][0]["exit"] == 0
    assert s["T2"]["state"] == "ready"
    last = events(repo)[-1]
    assert last["by"] == "human" and last["recheck"] is True
    code, _, err = cli("sprint", "recheck", "day1", "T1")
    assert code == 64 and "recheck is for a failed task" in err
    assert cli("check", "sprints", "--format", "json")[0] == 0  # R-71 accepts failed -> checking by a recheck


def test_S3_a_watching_dispatcher_survives_a_failure_and_runs_a_later_retry(cli, repo, tmp_path, monkeypatch):
    flag = tmp_path / "flag"
    monkeypatch.setenv("W08_FLAG", str(flag))
    write_sprint(repo, task("T1", 'test -f "$W08_FLAG" && echo a > a.txt && git add a.txt && git commit -qm a',
                            '["test -f a.txt"]'))
    from steward.models import load_config

    th = threading.Thread(target=lambda: sp.dispatch(repo, load_config(repo), sp.load(repo, "day1"), watch=True,
                                                     poll=0.1, out=lambda m: None))
    th.start()
    try:
        deadline = time.monotonic() + 30
        while (not (repo / "development/sprints/day1.jsonl").exists() or states(cli)["T1"]["state"] != "failed") \
                and time.monotonic() < deadline:
            time.sleep(0.1)
        assert states(cli)["T1"]["state"] == "failed"
        time.sleep(0.5)
        assert th.is_alive()  # it stays while the window is open and the task can still become ready
        flag.write_text("go\n")
        assert cli("sprint", "go", "day1", "T1", "--retry")[0] == 0
        deadline = time.monotonic() + 30
        while states(cli)["T1"]["state"] != "done" and time.monotonic() < deadline:
            time.sleep(0.1)
        assert states(cli)["T1"]["state"] == "done"
        th.join(10)
        assert not th.is_alive()  # every task finished: it ends on its own
    finally:
        if th.is_alive():
            cli("sprint", "stop", "day1")
            th.join(30)


def test_S6_a_task_added_to_the_file_waits_for_add(cli, repo):
    write_sprint(repo, task("T1"))
    cli("sprint", "start", "day1")
    p = repo / "development/sprints/day1.toml"
    p.write_text(p.read_text() + task("T13"))
    assert states(cli)["T13"]["state"] == "proposed"
    _, out, _ = cli("sprint", "start", "day1")
    assert "steward sprint add day1 T13" in out and states(cli)["T13"]["state"] == "proposed"
    code, report, _ = cli("check", "sprints", "--format", "json")
    assert "R-71.plan_changed" in report
    assert cli("sprint", "add", "day1", "T13")[0] == 0
    assert cli("sprint", "add", "day1", "T13")[0] == 64
    cli("sprint", "start", "day1")
    assert states(cli)["T13"]["state"] == "done"
    code, report, _ = cli("check", "sprints", "--format", "json")
    assert "R-71.plan_changed" not in report and code == 0


def test_S8_S9_worktree_root_and_the_variables_for_done_commands(cli, repo, tmp_path):
    wroot = tmp_path / "wt"
    write_sprint(repo, task("T1", 'test "$STEWARD_SPRINT_TASK" = T1 && echo a > a.txt && git add a.txt && git commit -qm a',
                            '["test \\"$STEWARD_SPRINT_BASE\\" = main", "test \\"$STEWARD_SPRINT_BRANCH\\" = sprint/day1/T1",'
                            ' "test \\"$STEWARD_SPRINT_ID\\" = day1"]'),
                 meta=f'worktree_root = "{wroot}"\nbase = "main"')
    code, out, err = cli("sprint", "start", "day1")
    assert code == 0, err
    s = states(cli)["T1"]
    assert s["state"] == "done", s
    assert (wroot / "day1/T1/a.txt").is_file() and not (repo / ".steward/sprints/day1/T1").exists()
    running = next(e for e in events(repo) if e.get("state") == "running")
    assert running["worktree"] == f"{wroot}/day1/T1" and running["base"] == "main"


def test_S10_fail_on_fail_exits_non_zero_for_a_fail_outside_every_gate(cli, repo):
    (repo / "development/sprints").mkdir(parents=True, exist_ok=True)
    (repo / "development/sprints/broken.toml").write_text('schema = "steward.sprint/0.1"\n[sprint]\nid = "broken"\n')
    _, report, _ = cli("check", "--format", "json")
    doc = json.loads(report)
    assert any(r["rule"] == "R-71" and r["status"] == "FAIL" for r in doc["verdict"]["results"])
    plain = cli("check", "--quiet")[0]
    code = cli("check", "--quiet", "--fail-on", "fail")[0]
    assert code == 1 and (plain == 0 or plain == code)
    assert cli("check", "--fail-on", "incomplete")[0] in (1, 2, 3)


def test_S10_fail_on_only_ever_raises_the_exit_code():
    from argparse import Namespace

    from steward.cli import _fail_on

    verdict = {"results": [{"status": "PASS"}, {"status": "INCOMPLETE"}]}
    assert _fail_on(Namespace(fail_on=None), verdict, 0) == 0
    assert _fail_on(Namespace(fail_on="fail"), verdict, 0) == 0
    assert _fail_on(Namespace(fail_on="incomplete"), verdict, 0) == 2
    assert _fail_on(Namespace(fail_on="fail"), {"results": [{"status": "FAIL"}]}, 0) == 1
    assert _fail_on(Namespace(fail_on="fail"), {"results": []}, 3) == 3


def test_S11_status_names_a_window_that_is_not_open(cli, repo):
    write_sprint(repo, task("T1"), start=2, end=8)
    _, out, _ = cli("sprint", "status", "day1")
    assert "window: opens at" in out
    _, raw, _ = cli("sprint", "status", "day1", "--format", "json")
    assert json.loads(raw)["window_state"] == "not open"


def test_S13_the_report_reads_the_merge_state_from_git(cli, repo):
    write_sprint(repo, task("T1", "echo a > a.txt && git add a.txt && git commit -qm a", '["test -f a.txt"]'))
    cli("sprint", "start", "day1")
    _, out, _ = cli("sprint", "report", "day1")
    assert "waiting for your merge" in out and "| no |" in out
    wt = repo / ".steward/sprints/day1/T1"
    sh(wt, "git", "commit", "--allow-empty", "-qm", "a reviewer's fix")
    sh(repo, "git", "merge", "-q", "--no-edit", "sprint/day1/T1")
    _, out, _ = cli("sprint", "report", "day1")
    tip = sh(repo, "git", "rev-parse", "sprint/day1/T1")
    assert f"yes @ {tip[:12]}" in out and "waiting for your merge" not in out


def test_run_id_is_checked(cli, repo):
    code, _, err = cli("run", "--run-id", "../x", "--", "true")
    assert code == 64 and "--run-id" in err
    rid = "20261127T120000Z-0123abcd"
    assert cli("run", "--run-id", rid, "--", "true")[0] == 0
    code, _, err = cli("run", "--run-id", rid, "--", "true")
    assert code == 64 and "already" in err
