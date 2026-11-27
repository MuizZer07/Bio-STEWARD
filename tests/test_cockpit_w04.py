"""STW-048 C14 and C15, with versioned output on both worked examples."""

import json

from steward.milestones import FILE, timeline

from test_cockpit_w03 import NOW, _json, _no_network, commit, needs_git, project, sh  # noqa: F401
from test_interface import machine_example  # noqa: F401
from test_interface_w02 import _check_golden


def test_w04_goldens(cli, machine_example, monkeypatch):
    from steward import milestones

    monkeypatch.setattr(milestones, "timeline", timeline)
    _no_network(monkeypatch)
    name, root = machine_example
    (root / "development/INDEX.md").write_text(
        "# State\n\n## Open decisions\n- Choose the next review date\n  - Keep December\n  - Move to January\n",
        encoding="utf-8",
    )
    docs = {"decisions": _json(cli, "decisions", "--repo", root),
            "timeline": _json(cli, "timeline", "--repo", root, "--now", NOW)}
    _check_golden(f"{name}.w04.json", docs)


@needs_git
def test_drift_reports_an_uncommitted_move_on_both_examples(cli, machine_example, monkeypatch):
    from steward import milestones

    monkeypatch.setattr(milestones, "timeline", timeline)
    _no_network(monkeypatch)
    name, root = machine_example
    sh(root, "git", "init", "-q")
    sh(root, "git", "add", "--", FILE)
    identity = {f"GIT_{role}_{key}": value for role in ("AUTHOR", "COMMITTER")
                for key, value in (("NAME", "Fixture"), ("EMAIL", "fixture@example.invalid"), ("DATE", NOW))}
    sh(root, "git", "-c", "core.hooksPath=/dev/null", "commit", "--no-gpg-sign", "-qm", "Original plan", env=identity)
    path = root / FILE
    path.write_text(path.read_text(encoding="utf-8").replace("12-01", "12-04"), encoding="utf-8")
    doc = _json(cli, "timeline", "--repo", root, "--now", NOW)
    _check_golden(f"{name}.w04-drift.json", doc)


def test_decisions_reads_configured_logs_index_and_handoff_not_design_history(cli, example):
    with (example / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[integrity]\ndecisions = ["development/DECISIONS.md", "development/logs/*.md"]\n')
    dev = example / "development"
    (dev / "logs").mkdir()
    (dev / "logs/extra.md").write_text(
        '## 2026-11-23 — Keep the review\n- **Owner, on the review:** “Keep it\n'
        '  open.”\n  → Record the findings.\n\n'
        '- **Owner (2026-11-25):** "Set the review for Friday." → Update the plan.\n'
        '```md\n## 2026-11-24: Example heading\n- **Quote:** "Ignore this."\n```\n',
        encoding="utf-8",
    )
    (dev / "HANDOFF.md").write_text("## Open decisions\n- none\n", encoding="utf-8")
    (dev / "design").mkdir()
    (dev / "design/guide.md").write_text(
        "## 3. Open decisions\n| ID | Decision | Options | Status |\n|---|---|---|---|\n"
        "| D1 | What next? | Review or wait | Open |\n| D2 | Publish? | Now or later | **Decided** |\n",
        encoding="utf-8",
    )
    (dev / "INDEX.md").write_text(
        "## Owner's open decisions\n- When to report?\n  - Today\n  - Tomorrow\n## Next\n- Do something\n",
        encoding="utf-8",
    )
    doc = _json(cli, "decisions", "--repo", example)
    inline, entry = doc["entries"][:2]
    assert inline["line"] == 6 and inline["date"] == "2026-11-25"
    assert inline["quotes"] == [{"who": "Owner", "text": '"Set the review for Friday."'}]
    assert inline["consequences"] == "Update the plan."
    assert entry["path"] == "development/logs/extra.md" and entry["line"] == 1
    assert entry["quotes"] == [{"who": "Owner", "text": "“Keep it\nopen.”"}]
    assert entry["consequences"] == "Record the findings."
    assert not any(e["date"] == "2026-11-24" for e in doc["entries"])
    # Only the living records count: a design document's "Open decisions" is history (W04 verification).
    assert [q["question"] for q in doc["open_decisions"]] == ["When to report?"]
    assert [q["options"] for q in doc["open_decisions"]] == [["Today", "Tomorrow"]]
    assert not any(q["path"].startswith("development/design/") for q in doc["open_decisions"])


@needs_git
def test_drift_uses_local_git_and_current_task_records(cli, project, monkeypatch):
    _no_network(monkeypatch)
    early = (project / FILE).read_text(encoding="utf-8")
    late = '\n[[milestone]]\nid = "later"\ntitle = "Later goal"\ndue = 2026-12-20T00:00:00Z\ntasks = ["PRJ-002"]\n'
    index = project / "development/INDEX.md"
    index.write_text("## Roadmap\n| Version | Theme | Tasks |\n|---|---|---|\n| 1.0 | Review | |\n", encoding="utf-8")
    (project / FILE).write_text(early + late, encoding="utf-8")
    commit(project, "Plan the later work", 1)
    new = early.replace("12-03", "12-06") + late
    (project / FILE).write_text(new, encoding="utf-8")
    log = project / "development/DECISIONS.md"
    heading = "2026-11-27: Move the preprint"
    log.write_text(f'## {heading}\n- **Quote:** "Move the preprint by three days."\n', encoding="utf-8")
    commit(project, "Move the preprint", 0)
    moved_commit = sh(project, "git", "rev-parse", "HEAD")
    (project / FILE).write_text(new.replace("12-06", "12-08").replace('["PRJ-001"]',
                                             '["PRJ-001", "PRJ-404", "PRJ-004"]'), encoding="utf-8")
    index.write_text(index.read_text(encoding="utf-8").replace("Review", "Outline"), encoding="utf-8")
    for tid, status in (("PRJ-003", "in progress"), ("PRJ-004", "dropped")):
        (project / f"development/tasks/{tid}.md").write_text(
            f"# {tid}\n- **ID:** {tid}\n- **Status:** {status}\n", encoding="utf-8")

    legacy = cli("timeline", "--now", NOW, "--json")
    assert legacy[0] == 0
    doc = _json(cli, "timeline", "--now", NOW)
    assert cli("timeline", "--now", NOW, "--json") == legacy
    assert json.loads(legacy[1]) == {"milestones": doc["milestones"]}
    drift = doc["drift"]
    assert drift["history"] == "available"
    assert drift["date"] == [{"id": "preprint", "first_due": "2026-12-03T00:00:00+00:00",
                             "current_due": "2026-12-08T00:00:00+00:00", "days": 5.0,
                             "moves": 2, "recorded_move": False}]
    assert drift["order"] == [{"earlier": "preprint", "later": "later", "started_tasks": ["PRJ-002"]}]
    assert {(r["reason"], r["id"]) for r in drift["scope"]} == {
        ("unassigned_task", "PRJ-003"), ("unstarted_task", "PRJ-001"), ("missing_task", "PRJ-404"),
        ("dropped_task", "PRJ-004"), ("roadmap_without_task", "1.0"),
    }
    moved, working = [c for c in drift["changes"] if "due" in c["fields"]]
    assert moved["commit"] == moved_commit and moved["decision"] == {
        "path": "development/DECISIONS.md", "line": 1, "heading": heading,
    }
    assert working["commit"] is None and working["time"] is None and working["decision"] is None
    assert working["fields"] == ["due", "tasks"]
    assert any(c["kind"] == "roadmap" and c["fields"] == ["row"] and c["decision"] is None for c in drift["changes"])

    with (project / FILE).open("a", encoding="utf-8") as f:
        f.write(f'[milestone.outcome]\nstate = "moved"\ndecision = "{heading}"\n')
    adjusted = _json(cli, "timeline", "--now", NOW)["drift"]
    later = next(c for c in adjusted["changes"] if c["id"] == "later" and c["fields"] == ["outcome"])
    assert later["decision"] == moved["decision"]


@needs_git
def test_drift_skips_invalid_history_and_keeps_deletions(cli, project):
    plan = (project / FILE).read_text(encoding="utf-8")
    (project / FILE).write_text("invalid TOML", encoding="utf-8")
    commit(project, "Invalid intermediate plan", 1)
    (project / FILE).write_text(plan.replace("12-03", "12-06"), encoding="utf-8")
    commit(project, "Valid plan", 0)
    (project / FILE).unlink()
    commit(project, "Remove plan", 0)
    doc = _json(cli, "timeline", "--now", NOW)
    assert doc["milestones"] == []
    drift = doc["drift"]
    assert drift["history"] == "partial" and len(drift["notes"]) == 1
    assert [change["fields"] for change in drift["changes"]] == [["removed"]]


def test_decisions_missing_config(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli("decisions", "--format", "json")
    assert code == 78 and "not a steward repository" in err
    assert json.loads(out)["schema"] == "steward.error/0.1"
