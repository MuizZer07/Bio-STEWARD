"""0.24.0 (P02): the research timeline (`steward timeline --events`) and the schedule (`--format svg`).

Goldens on both worked examples; a Git project that dates every kind of event; `--all-projects` with a peer on disk
and one that is only a URL; the existing timeline outputs unchanged. Rewrite the goldens with
STEWARD_UPDATE_GOLDENS=1 pytest tests/test_v0240_timeline_events.py
"""

import json
import os
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from conftest import REPO
from test_interface import GOLDEN, _golden_bytes, machine_example  # noqa: F401
from test_interface_w02 import _valid

NOW = "2026-11-27T00:00:00Z"


def _pin_timeline(monkeypatch):
    """The worked-example fixture pins `milestones.timeline` to its instant (NOW) and takes no `now`; --now passes
    the same instant, so accept it."""
    from steward import milestones

    pinned = milestones.timeline
    monkeypatch.setattr(milestones, "timeline", lambda root, cfg, now=None: pinned(root, cfg))


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("the timeline attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _check_golden(path, out):
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.write_text(out, encoding="utf-8", newline="\n")
    assert out == path.read_text(encoding="utf-8"), f"output differs from {path}"


def _svg_ok(svg):
    tree = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    assert tree.get("role") == "img" and tree.get("aria-labelledby") == "schedule-title schedule-desc"
    assert tree.find(f"{ns}title").text and tree.find(f"{ns}desc").text
    assert "<script" not in svg.lower() and " on" not in "".join(f" {k}" for el in tree.iter() for k in el.attrib)
    assert "prefers-color-scheme: dark" in svg and ">today</text>" in svg
    return tree


# ---------------------------------------------------------------- goldens on both worked examples
def test_P02_timeline_events_goldens(cli, machine_example, monkeypatch, no_network):  # noqa: F811
    name, root = machine_example
    _pin_timeline(monkeypatch)
    code, out, err = cli("timeline", "--events", "--repo", root, "--format", "json", "--now", NOW)
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    assert doc["schema"] == "steward.timeline_events/0.1" and out == _golden_bytes(doc)
    _check_golden(GOLDEN / f"{name}.timeline-events.json", out)
    kinds = {e["kind"] for e in doc["events"]}
    assert "milestone" in kinds and "paper" in kinds
    assert [e["time"] for e in doc["events"]] == sorted((e["time"] for e in doc["events"]), reverse=True)
    for e in doc["events"]:
        assert e["path"] and (e["line"] or e["kind"] == "release"), e  # each names its source file and line
        assert e["path"] == "." or (root / e["path"]).is_file()
    milestone = next(e for e in doc["events"] if e["kind"] == "milestone")
    assert (milestone["path"], milestone["line"]) == ("development/milestones.toml", 3)
    code, svg, err = cli("timeline", "--events", "--repo", root, "--format", "svg", "--now", NOW)
    assert code == 0 and not err, err
    _svg_ok(svg)
    _check_golden(GOLDEN / f"{name}.schedule.svg", svg)
    code, text, _ = cli("timeline", "--events", "--repo", root, "--now", NOW)
    assert code == 0 and text.startswith(f"Research timeline ({len(doc['events'])} events, newest first")
    lines = [ln for ln in text.splitlines() if ln.startswith("  ")]
    assert [ln.split()[0] for ln in lines] == [e["time"][:10] for e in doc["events"]]  # newest first
    code, interface, _ = cli("interface", "--format", "json")
    entry = json.loads(interface)["commands"]["timeline --events"]
    assert entry == {"argv": ["--events", "--format", "json"], "schema": "steward.timeline_events/0.1"}


def test_P02_all_projects_reads_only_what_is_on_disk(cli, machine_example, monkeypatch, no_network, tmp_path):  # noqa: F811
    name, root = machine_example
    _pin_timeline(monkeypatch)
    # The fixture's peer is a URL: it is listed and not fetched.
    code, out, err = cli("timeline", "--events", "--all-projects", "--repo", root, "--format", "json", "--now", NOW)
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    assert doc["projects"] == [
        {"code": "DEMO", "path": ".", "reachable": True, "note": None},
        {"code": "PEER", "path": None, "reachable": False, "note": "a remote URL: not fetched"},
    ]
    # A peer checkout on disk is read from its own records.
    peer = tmp_path / "peer-project"
    shutil.copytree(REPO / "examples" / "toy-expression-benchmark", peer, ignore=shutil.ignore_patterns(".steward"))
    with (peer / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[exchange]\ncode = "PEER"\n')
    (peer / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "peer-preprint"\ntitle = "Peer preprint"\n'
        'due = 2027-01-10T00:00:00Z\nkind = "preprint"\nbuffer_days = 5\n', encoding="utf-8")
    toml = (root / "steward.toml").read_text(encoding="utf-8")
    (root / "steward.toml").write_text(toml.replace('url = "https://example.invalid/peer.git"',
                                                    f'path = "{peer.as_posix()}"'), encoding="utf-8")
    code, out, err = cli("timeline", "--events", "--all-projects", "--repo", root, "--format", "json", "--now", NOW)
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    assert doc["projects"][1] == {"code": "PEER", "path": str(peer.resolve()), "reachable": True, "note": None}
    theirs = [e for e in doc["events"] if e["project"] == "PEER"]
    assert {e["kind"] for e in theirs} >= {"milestone", "decision", "paper"}
    ms = next(e for e in theirs if e["kind"] == "milestone")
    assert ms["id"] == "PEER/milestone:peer-preprint" and ms["internal"] == "2027-01-05T00:00:00Z"
    assert ms["state"] is None  # another project's gates are not run
    code, svg, _ = cli("timeline", "--events", "--all-projects", "--repo", root, "--format", "svg", "--now", NOW)
    assert code == 0 and "PEER · Milestones" in svg and "DEMO · Milestones" in svg
    _svg_ok(svg)


# ---------------------------------------------------------------- a Git project that dates every kind
def _git(root, *args, when="2026-11-01T10:00:00Z"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], cwd=root, env=env, check=True, capture_output=True)


MILESTONES = ('schema = "steward.milestones/0.1"\n\n[[milestone]]\nid = "preprint"\ntitle = "Preprint"\n'
              'due = {due}\nkind = "preprint"\nbuffer_days = 3\n\n[[milestone]]\nid = "talk"\ntitle = "Lab talk"\n'
              'due = 2026-11-10T00:00:00Z\n\n[milestone.outcome]\nstate = "met"\ndecision = "2026-11-10: talk given"\n'
              'on = 2026-11-10\n')


@pytest.fixture
def dated_project(tmp_path):
    from steward import sprint as sp
    from steward.models import load_config

    root = tmp_path / "dated"
    shutil.copytree(REPO / "examples" / "toy-expression-benchmark", root, ignore=shutil.ignore_patterns(".steward"))
    with (root / "steward.toml").open("a", encoding="utf-8") as f:
        f.write("\n[research]\n")
    _git(root, "init", "-q", "-b", "main")
    (root / "development/milestones.toml").write_text(MILESTONES.format(due="2026-12-01T00:00:00Z"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "plan")
    _git(root, "tag", "-a", "v0.1.0", "-m", "first", when="2026-11-03T09:00:00Z")
    (root / "development/milestones.toml").write_text(MILESTONES.format(due="2026-12-15T00:00:00Z"), encoding="utf-8")
    _git(root, "commit", "-q", "-am", "move the preprint", when="2026-11-05T12:00:00Z")
    (root / "development/assessment").mkdir(parents=True)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    (root / "development/assessment/findings.toml").write_text(
        f'schema = "steward.findings/0.1"\n\n[[reviews]]\nid = "R1"\nreviewer = "an independent reviewer"\n'
        f'revision = "{rev}"\n', encoding="utf-8")
    (root / "development/research").mkdir(parents=True)
    (root / "development/research/lit-1.toml").write_text(
        'schema = "steward.research/1"\nid = "lit-1"\ntitle = "Splits in expression benchmarks"\nkind = "review"\n'
        'date = 2026-11-06\n\n[review]\nquestion = "How are donors split?"\nsearched = 2026-11-04\n', encoding="utf-8")
    (root / sp.DIR).mkdir(parents=True)
    (root / sp.DIR / "s1.toml").write_text(
        'schema = "steward.sprint/0.1"\n\n[sprint]\nid = "s1"\n'
        'window = { start = 2026-11-20T00:00:00Z, end = 2026-11-30T00:00:00Z }\n\n'
        '[[task]]\nid = "T1"\ntitle = "Baselines"\ncommand = "true"\ndone = ["true"]\n\n'
        '[[task]]\nid = "T2"\ntitle = "Figures"\ncommand = "true"\ndone = ["true"]\n\n'
        '[[task]]\nid = "T3"\ntitle = "Not started"\ncommand = "true"\ndone = ["true"]\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "records", when="2026-11-06T12:00:00Z")
    led = sp.led(root, "s1", load_config(root).steward.repo_id)
    import steward.ledger as lg

    times = iter(["2026-11-21T09:00:00Z", "2026-11-21T09:00:00Z", "2026-11-21T11:30:00Z", "2026-11-22T08:00:00Z"])
    real = lg._now
    lg._now = lambda: next(times)
    try:
        led.append("state", {"task": "T1", "state": "running"})
        led.append("state", {"task": "T1", "state": "done"})
        led.append("state", {"task": "T2", "state": "running"})
    finally:
        lg._now = real
    return root


def test_P02_every_kind_is_dated_with_its_source(cli, dated_project, no_network):
    root = dated_project
    code, out, err = cli("timeline", "--events", "--repo", root, "--format", "json", "--now", "2026-11-25T00:00:00Z")
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    by_id = {e["id"]: e for e in doc["events"]}
    assert {e["kind"] for e in doc["events"]} == {"milestone", "milestone_moved", "milestone_outcome", "decision",
                                                   "release", "paper", "review", "research", "sprint", "task"}
    pre = by_id["milestone:preprint"]
    assert (pre["time"], pre["internal"], pre["moved_from"]) == ("2026-12-15T00:00:00Z", "2026-12-12T00:00:00Z",
                                                                  "2026-12-01T00:00:00Z")
    assert (pre["path"], pre["line"]) == ("development/milestones.toml", 4)
    move = next(e for e in doc["events"] if e["kind"] == "milestone_moved")
    assert move["time"] == "2026-11-05T12:00:00Z" and move["moved_from"] == "2026-12-01T00:00:00Z"
    assert move["moved_to"] == "2026-12-15T00:00:00Z" and len(move["ref"]) == 40
    talk = by_id["milestone_outcome:talk"]
    assert (talk["time"], talk["day"], talk["state"]) == ("2026-11-10T00:00:00Z", True, "met")
    rel = by_id["release:v0.1.0"]
    assert (rel["time"], rel["path"], rel["ref"]) == ("2026-11-03T09:00:00Z", None, "refs/tags/v0.1.0")
    rv = by_id["review:R1"]
    assert rv["time"] == "2026-11-05T12:00:00Z" and rv["path"] == "development/assessment/findings.toml"
    assert rv["line"] == 4
    assert by_id["research:lit-1"]["line"] == 5 and by_id["research:lit-1:searched"]["time"] == "2026-11-04T00:00:00Z"
    s1 = by_id["sprint:s1"]
    assert (s1["time"], s1["end"], s1["state"], s1["line"]) == ("2026-11-20T00:00:00Z", "2026-11-30T00:00:00Z",
                                                                 "open", 5)
    t1, t2 = by_id["task:s1/T1"], by_id["task:s1/T2"]
    assert (t1["time"], t1["end"], t1["state"], t1["line"]) == ("2026-11-21T09:00:00Z", "2026-11-21T11:30:00Z",
                                                                 "done", 8)
    assert (t2["end"], t2["state"], t2["line"]) == (None, "running", 14)
    assert "task:s1/T3" not in by_id  # never started: nothing dates it
    assert by_id["decision:development/DECISIONS.md:12"]["day"] is True
    ordered = [(e["time"], e["id"]) for e in doc["events"]]
    from steward.newest import id_key

    assert ordered == sorted(ordered, key=lambda p: (p[0], id_key(p[1])), reverse=True)  # newest first
    code, svg, _ = cli("timeline", "--events", "--repo", root, "--format", "svg", "--now", "2026-11-25T00:00:00Z")
    tree = _svg_ok(svg)
    desc = tree.find("{http://www.w3.org/2000/svg}desc").text
    assert "Coming deadlines: Preprint due 2026-12-15, internal deadline 2026-12-12, first due 2026-12-01" in desc
    assert "Lab talk" not in desc.split("Newest first")[0]  # met: not a coming deadline
    assert "first due 2026-12-01" in svg and "buffer: internal deadline 2026-12-12" in svg
    for lane in ("Milestones", "Sprints", "Sprint tasks", "Releases", "Decisions", "Research", "Papers and reviews"):
        assert f">{lane}</text>" in svg


def test_P02_existing_timeline_outputs_are_unchanged(cli, dated_project):
    from steward import drift
    from steward import milestones as ms
    from steward.cockpit import parse_now
    from steward.fsutil import canonical_json
    from steward.models import load_config

    root = dated_project
    now = "2026-11-25T00:00:00Z"
    code, legacy, _ = cli("timeline", "--repo", root, "--json", "--now", now)
    cfg = load_config(root)
    rows = ms.timeline(root, cfg, now=parse_now(now))
    assert code == 0 and legacy == canonical_json({"milestones": rows})
    code, tagged, _ = cli("timeline", "--repo", root, "--format", "json", "--now", now)
    doc = json.loads(tagged)
    assert set(doc) == {"schema", "milestones", "drift"} and doc["schema"] == "steward.timeline/0.1"
    assert doc["drift"] == json.loads(canonical_json(drift.document(root, cfg, rows)))
    code, text, _ = cli("timeline", "--repo", root, "--now", now)
    assert code == 0 and text == ms.render(rows) + "\n"


def test_P02_usage(cli, dated_project):
    root = dated_project
    for argv in (("--format", "svg"), ("--all-projects",), ("--events", "--json")):
        code, out, err = cli("timeline", *argv, "--repo", root)
        assert code == 64 and not out and err, argv
    code, out, err = cli("timeline", "--events", "--all-projects", "--repo", root, "--format", "json")
    doc = json.loads(out)
    assert code == 0 and len(doc["projects"]) == 1
    assert "--all-projects: no [exchange] table, so no other project is named" in doc["notes"]


def test_P02_schedule_without_records():
    from steward.charts import schedule

    svg = schedule({"now": "2026-11-27T00:00:00Z", "projects": [{"code": None}], "events": []})
    assert "No dated records." in svg
    _svg_ok(svg)
    assert datetime(2026, 11, 27, tzinfo=timezone.utc).strftime("%Y-%m-%d") in svg
