"""W03 (STW-048 C10, C12; C21): steward next, steward tidy (and R-88), steward notifications.

Regenerate the goldens after an intended change: STEWARD_UPDATE_GOLDENS=1 pytest tests/test_cockpit_w03.py
"""

import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from steward.milestones import timeline as _TIMELINE  # the real one: the W01 fixture pins it to its own instant

from conftest import one
from test_interface import machine_example  # noqa: F401  (the W01 fixture, both worked examples)
from test_interface_w02 import _check_golden, _valid

NOW = "2026-11-27T00:00:00Z"
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a, env=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def _when(days_ago):
    t = dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc) - dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def commit(root, message, days_ago):
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", message, env={"GIT_AUTHOR_DATE": _when(days_ago), "GIT_COMMITTER_DATE": _when(days_ago)})


def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a W03 command opened a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _json(cli, *argv):
    code, out, err = cli(*argv, "--format", "json")
    assert code == 0, err
    return _valid(json.loads(out))


SPRINT = '''schema = "steward.sprint/0.1"
[sprint]
id = "s1"
window = { start = 2026-11-26T00:00:00Z, end = 2026-11-28T00:00:00Z }

[[task]]
id = "A"
title = "first"
command = "true"
done = ["true"]

[[task]]
id = "B"
title = "second"
command = "false"
done = ["true"]

[[task]]
id = "C"
title = "third"
command = "true"
after = ["A"]
done = ["true"]
'''
NONCE = "a" * 32


def _pending(root):
    """A spend authorization waiting for its signature, prepared on 2026-11-26 (for this repository: W12 F1 lists a
    payload with another repo_id as foreign, never waiting)."""
    from steward import authorize as az
    from steward.models import load_config

    payload = {"repo_id": load_config(root).steward.repo_id, "action": "spend", "object": "sha256:" + "0" * 64, "scope": "task=PRJ-001",
               "budget": "10 USD", "expires": "2026-12-31T00:00:00Z", "baseline": "main", "nonce": NONCE}
    (root / ".steward/pending").mkdir(parents=True, exist_ok=True)
    pending = root / f".steward/pending/{NONCE}.txt"
    pending.write_text(az.render(payload, "the baseline run"), encoding="utf-8")
    stamp = dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc).timestamp()
    os.utime(pending, (stamp, stamp))


def _records(root):
    """A waiting signature, a sprint with a done, a failed and a waiting task, and a newer toolkit's release notice."""
    from steward import exchange as xc
    from steward import sprint as sp

    _pending(root)
    (root / "development/sprints").mkdir(parents=True, exist_ok=True)
    (root / "development/sprints/s1.toml").write_text(SPRINT, encoding="utf-8")
    led = sp.led(root, "s1", "x")
    led.append("state", {"task": "A", "state": "done", "branch": "sprint/s1/A"})
    led.append("state", {"task": "B", "state": "failed", "note": "exit 1"})
    # W12 F5, F13: a release notice counts only when it was received (its bytes match the receipt), so it is
    # received here, on the day it was filed, rather than written into the inbox.
    from steward import ledger
    from steward.models import load_config

    code = load_config(root).exchange.code
    notice = {"schema": "steward.exchange/1", "id": "STW-REL-099", "kind": "release", "from": "STW", "to": code,
              "title": "Release v99.0.0", "filed": dt.date(2026, 11, 25), "version": "99.0.0", "tag": "v99.0.0"}
    (root / "exchange/inbox").mkdir(parents=True, exist_ok=True)
    saved = ledger._now
    ledger._now = lambda: "2026-11-25T00:00:00Z"
    try:
        xc.receive(root, "fixture", code, xc.render(notice, "Notes.\n").encode(), {"from": "file"})
    finally:
        ledger._now = saved


# ---------------------------------------------------------------- goldens on both worked examples
def test_w03_goldens(cli, machine_example, monkeypatch):  # noqa: F811
    from steward import milestones

    monkeypatch.setattr(milestones, "timeline", _TIMELINE)  # --now decides the instant here
    _no_network(monkeypatch)
    name, root = machine_example
    _records(root)
    docs = {cmd: _json(cli, cmd, "--repo", root, "--now", NOW) for cmd in ("next", "tidy", "notifications")}
    assert docs["next"]["milestone"]["id"] == "review"
    kinds = {i["kind"] for i in docs["notifications"]["items"]}
    assert kinds == {"upgrade", "approval", "task_finished", "task_failed", "task_waiting"}
    assert all(d["now"] == NOW for d in docs.values())
    _check_golden(f"{name}.w03.json", docs)


def test_interface_lists_the_w03_commands(cli):
    doc = json.loads(cli("interface", "--format", "json")[1])
    for cmd, tag in (("next", "steward.next/0.1"), ("tidy", "steward.tidy/0.1"),
                     ("notifications", "steward.notifications/0.1")):
        assert doc["commands"][cmd] == {"argv": ["--format", "json"], "schema": tag}
        assert tag in doc["schema_files"]


# ---------------------------------------------------------------- a project with a milestone, a pending signature
# and a stale task (STW-048 acceptance)
@pytest.fixture
def project(cli, tmp_path, monkeypatch):
    for k, v in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.org",
                 "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.org"}.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    with (r / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[tasks]\nspecs = ["development/tasks/*.md"]\narchive = ["development/archive/**"]\n'
                'board = "development/BOARD.md"\n\n[session]\n\n[tidy]\nstale_days = 14\nhandoff_days = 7\n')
    (r / "development/tasks").mkdir(parents=True)
    (r / "development/BOARD.md").write_text("# Board\n\n- PRJ-001\n- PRJ-002\n", encoding="utf-8")
    for tid, status in (("PRJ-001", "proposed"), ("PRJ-002", "done")):
        (r / f"development/tasks/{tid}.md").write_text(f"# {tid}\n\n- **ID:** {tid}\n- **Status:** {status}\n",
                                                       encoding="utf-8")
    (r / "development/HANDOFF.md").write_text(
        "# Session handoff\n\n## State\n- version 0.1.0\n\n## Next\n1. Run the baseline under the frozen contract\n"
        "2. Draft the methods\n\n## Open decisions\n- P4: drop cohort C?\n\n## Open items\n- none\n\n"
        "## Working agreements\n- none recorded\n\n## Read first\n- the links above\n\n## Signature\n2026-11-01\n",
        encoding="utf-8")
    sh(r, "git", "init", "-q", "-b", "main")
    commit(r, "start", 30)
    (r / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "preprint"\ntitle = "Preprint"\nkind = "other"\n'
        'due = 2026-12-03T00:00:00Z\nbuffer_days = 7\ntasks = ["PRJ-001"]\nneeds = ["spend"]\n', encoding="utf-8")
    commit(r, "milestone", 1)
    _pending(r)
    monkeypatch.chdir(r)
    return r


@needs_git
def test_next_on_a_project_with_a_milestone_a_signature_and_a_stale_task(cli, project, monkeypatch):
    _no_network(monkeypatch)
    doc = _json(cli, "next", "--now", NOW)
    assert doc["resume"]["path"] == "development/HANDOFF.md"
    assert doc["resume"]["next"] == ["Run the baseline under the frozen contract", "Draft the methods"]
    assert doc["resume"]["age_days"] == 30.0 and doc["resume"]["committed"]
    m = doc["milestone"]
    assert (m["id"], m["state"]) == ("preprint", "at risk")  # inside its 7-day buffer with open work
    assert {(b["kind"], b["id"]) for b in m["blockers"]} == {("task", "PRJ-001"), ("signature", "spend")}
    human = {(h["kind"], h["id"]): h for h in doc["waiting_on_human"]}
    sig = human[("signature", NONCE)]
    assert sig["command"] == "steward authorize sign-pending" and sig["source"] == f".steward/pending/{NONCE}.txt"
    assert any(k == "decision" and h["title"] == "P4: drop cohort C?" for (k, _), h in human.items())
    assert doc["waiting_on_agents"] == []
    assert doc["tidy"]["counts"]["stale_task"] == 1 and doc["tidy"]["counts"]["stale_page"] == 1
    code, text, _ = cli("next", "--now", NOW)
    assert code == 0
    assert "Next milestone: preprint \"Preprint\" · 6 days · AT RISK" in text
    assert "-> steward authorize sign-pending" in text and "Needs tidying (2)" in text
    code, brief, _ = cli("next", "--now", NOW, "--brief")
    assert code == 0 and "->" not in brief.split("Needs tidying")[0] and len(brief.split()) < 300
    assert "Ask before archiving or deleting" in brief


@needs_git
def test_tidy_names_stale_items_and_changes_nothing(cli, project):
    def tree():
        return {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(project.rglob("*")) if p.is_file()}
    before = tree()
    doc = _json(cli, "tidy", "--now", NOW)
    code, text, _ = cli("tidy", "--now", NOW)
    assert code == 0 and "Nothing was changed" in text
    assert tree() == before  # STW-048: tidy deletes and moves nothing without --archive (.git included)
    items = {i["id"]: i for i in doc["items"]}
    stale = items["stale_task:PRJ-001"]
    assert stale["age_days"] == 30.0 and stale["command"] == "steward tidy --archive PRJ-001"
    assert "stale_task:PRJ-002" not in items  # done is closed
    assert items["stale_page:development/HANDOFF.md"]["message"] == "the handoff is 30 days old"
    assert doc["thresholds"]["stale_days"] == 14 and doc["counts"]["stale_task"] == 1


@needs_git
def test_tidy_thresholds_are_per_project(cli, project):
    with (project / "steward.toml").open("a", encoding="utf-8") as f:
        f.write("stale_days = 40\n")  # appended to [tidy], which ends the file
    text = (project / "steward.toml").read_text(encoding="utf-8")
    (project / "steward.toml").write_text(text.replace("stale_days = 14\n", "").replace("handoff_days = 7\n",
                                                                                        "handoff_days = 60\n"),
                                          encoding="utf-8")
    doc = _json(cli, "tidy", "--now", NOW)
    assert doc["thresholds"]["stale_days"] == 40 and doc["items"] == []


@needs_git
def test_tidy_archive_moves_only_the_named_task(cli, project):
    code, out, err = cli("tidy", "--archive", "PRJ-404")
    assert code == 65 and "no task file has ID PRJ-404" in err
    code, out, err = cli("tidy", "--archive", "PRJ-001")
    assert code == 0, err
    assert "moved development/tasks/PRJ-001.md -> development/archive/PRJ-001.md" in out
    assert (project / "development/archive/PRJ-001.md").is_file()
    assert not (project / "development/tasks/PRJ-001.md").exists()
    assert (project / "development/tasks/PRJ-002.md").is_file()
    assert "R  development/tasks/PRJ-001.md -> development/archive/PRJ-001.md" in sh(project, "git", "status", "--short")
    doc = _json(cli, "tidy", "--now", NOW)
    assert doc["counts"]["stale_task"] == 0
    code, _, err = cli("tidy", "--archive", "PRJ-001")
    assert code == 65 and "already archived" in err


@needs_git
def test_r88_is_advisory_and_counts_the_records(cli, project):
    code, rep = cli.check(project)
    r = one(rep, "R-88")
    assert r["status"] == "INCOMPLETE" and r["area"] == "tidy"
    assert {d["code"] for d in r["details"]} == {"R-88.stale_task", "R-88.stale_page"}
    assert "R-88" not in [b["rule"] for g in rep["verdict"]["gates"] if g["name"] == "default" for b in g["blocking"]]
    from steward.models import ADVISORY

    assert "R-88" in ADVISORY


def test_r88_not_applicable_without_tidy(cli, example):
    _, rep = cli.check(example)
    assert one(rep, "R-88")["status"] == "NOT_APPLICABLE"


def test_tidy_lists_memory_entries_never_changes_them(cli, example, tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "old.md").write_text("---\nname: a\n---\nSee `paper/gone.tex` and `paper/main.tex`.\n", encoding="utf-8")
    (mem / "copy.md").write_text("---\nname: b\n---\nSee `paper/gone.tex` and   `paper/main.tex`.\n", encoding="utf-8")
    old = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc).timestamp()
    os.utime(mem / "old.md", (old, old))
    with (example / "steward.toml").open("a", encoding="utf-8") as f:
        f.write(f'\n[tidy]\nmemory = ["{mem.as_posix()}"]\nmemory_days = 30\n')
    before = {p.name: p.read_bytes() for p in mem.iterdir()}
    doc = _json(cli, "tidy", "--repo", example, "--now", NOW)
    mine = {i["id"].rsplit(":", 1)[1] + ":" + Path(i["subject"]).name: i for i in doc["items"] if i["kind"] == "memory"}
    assert "old:old.md" in mine and mine["old:old.md"]["age_days"] == 87.0
    assert mine["paths:old.md"]["message"] == "names paths that no longer exist here: paper/gone.tex"
    assert "duplicate:old.md" in mine  # the same text as copy.md, whitespace aside
    assert {p.name: p.read_bytes() for p in mem.iterdir()} == before
    _, rep = cli.check(example)
    assert one(rep, "R-88")["status"] == "PASS"  # memory is outside the repository: steward tidy only


# ---------------------------------------------------------------- notifications (C21)
@needs_git
def test_notifications_feed(cli, project, monkeypatch):
    _no_network(monkeypatch)
    from steward import ledger

    with (project / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[exchange]\ncode = "PRJ"\n')
    assert cli("exchange", "init")[0] == 0  # the release notice is received (W12 F5)
    times = iter(["2026-11-26T01:00:00Z", "2026-11-26T02:00:00Z", "2026-11-26T03:00:00Z"])
    monkeypatch.setattr(ledger, "_now", lambda: next(times))
    _records(project)
    report = project / ".steward/before.json"
    report.write_text(json.dumps({"verdict": {"gates": [{"name": "default", "eligible": True}]}}), encoding="utf-8")
    doc = _json(cli, "notifications", "--now", NOW, "--against", report)
    by = {i["id"]: i for i in doc["items"]}
    assert by["upgrade:STW-REL-099"]["kind"] == "upgrade" and by["upgrade:STW-REL-099"]["time"] == "2026-11-25T00:00:00Z"
    assert by["task_finished:s1/A"]["time"] == "2026-11-26T02:00:00Z"
    failed = by["task_failed:s1/B"]
    assert failed["urgent"] and failed["command"] == "steward sprint go s1 B --retry"
    assert by["task_waiting:s1/C"]["command"] == "steward sprint go s1 C"
    approval = by[f"approval:{NONCE}"]
    assert approval["urgent"] and approval["time"] == "2026-11-26T00:00:00Z"
    assert by["milestone:preprint:at-risk"]["time"] == "2026-11-26T00:00:00Z"  # its internal deadline
    gate = next(i for i in doc["items"] if i["kind"] == "gate")
    assert gate["id"].startswith("gate:default:") and gate["urgent"] and gate["source"] == "before.json"
    assert [i["time"] for i in doc["items"]] == sorted((i["time"] for i in doc["items"]), reverse=True)
    for i in doc["items"]:
        assert set(i) == {"id", "time", "kind", "source", "title", "command", "urgent"}
    old = _json(cli, "notifications", "--now", "2026-12-20T00:00:00Z", "--days", "7")
    assert not any(i["kind"] in ("task_finished", "task_failed") for i in old["items"])  # older than --days
    assert "gates: not compared" in old["notes"][0]
    code, text, _ = cli("notifications", "--now", NOW)
    assert code == 0 and "-> steward authorize sign-pending" in text


# ---------------------------------------------------------------- usage, configuration, --now
@pytest.mark.parametrize("argv", [("next", "--brief", "--format", "json"), ("next", "--now", "tomorrow"),
                                  ("next", "--now", "2026-11-27T00:00:00"), ("tidy", "--archive", "X", "--format", "json"),
                                  ("notifications", "--days", "0")])
def test_usage_errors(cli, example, argv):
    code, out, _ = cli(*argv, "--repo", example)
    assert code == 64 and not out


@pytest.mark.parametrize("command", ["next", "tidy", "notifications"])
def test_not_configured(cli, tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli(command, "--format", "json")
    assert code == 78 and "not a steward repository" in err
    assert _valid(json.loads(out))["code"] == "not_configured"


def test_timeline_now_reproduces_a_state(cli, example):
    (example / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "m"\ntitle = "M"\ndue = 2027-01-10T00:00:00Z\n'
        'buffer_days = 5\nneeds = ["spend"]\n', encoding="utf-8")
    early = json.loads(cli("timeline", "--repo", example, "--format", "json", "--now", "2026-12-01T00:00:00Z")[1])
    late = json.loads(cli("timeline", "--repo", example, "--format", "json", "--now", "2027-01-11T00:00:00Z")[1])
    assert early["milestones"][0]["days_left"] == 40.0 and late["milestones"][0]["days_left"] == -1.0
    code, _, err = cli("timeline", "--repo", example, "--now", "soon")
    assert code == 64 and "--now" in err
