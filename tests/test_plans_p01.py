"""P01 plans discovery, versioned output and progress across the worked examples."""

import json

from steward.cockpit import parse_now
from test_cockpit_w03 import NOW, _json, _no_network, commit, needs_git, project  # noqa: F401
from test_interface import _golden_bytes, machine_example  # noqa: F401
from test_interface_w02 import _check_golden, _valid

SPRINT = """schema = "steward.sprint/0.1"

[sprint]
id = "example"
window = { start = 2026-11-26T00:00:00Z, end = 2026-12-02T00:00:00Z }

[[task]]
id = "T1"
title = "Review the records"
agent = "shell"
command = "true"
done = ["true"]

[[task]]
id = "T2"
title = "Summarize the review"
agent = "shell"
command = "true"
done = ["true"]
after = ["T1"]
"""


def test_plans_goldens_and_progress(cli, machine_example, monkeypatch):
    from datetime import datetime, timezone

    from steward import sprint
    from steward.models import load_config

    name, root = machine_example
    dev = root / "development"
    with (root / "steward.toml").open("a", encoding="utf-8") as f:
        f.write('\n[tasks]\nspecs = ["development/tasks/*.md"]\nboard = "development/TASKS.md"\n')
    (dev / "tasks").mkdir(exist_ok=True)
    (dev / "tasks/review.md").write_text("# Review\n- **ID:** TASK-001\n- **Status:** done\n", encoding="utf-8")
    with (dev / "milestones.toml").open("a", encoding="utf-8") as f:
        f.write('tasks = ["TASK-001"]\n')
    (dev / "INDEX.md").write_text(
        "# Development index\n\n## Roadmap\n\n| Version | Theme | State | Date | Task |\n"
        "|---|---|---|---|---|\n| v1.2 | Finish the review | Planned | 2026-11-28 | TASK-001 |\n",
        encoding="utf-8",
    )
    (dev / "design").mkdir()
    (dev / "design/RELEASE_v1.2_SPEC.md").write_text(
        "# Release specification for v1.2\n\n*Signature: 2026-11-25 · planning*\n", encoding="utf-8",
    )
    (dev / "sprints").mkdir()
    (dev / "sprints/example.toml").write_text(SPRINT, encoding="utf-8")
    cfg = load_config(root)
    ledger = sprint.led(root, "example", cfg.steward.repo_id)
    ledger.append("opened", {"tasks": ["T1"]})
    ledger.append("state", {"task": "T1", "state": "done"})
    real_window_state = sprint.window_state
    instant = datetime(2026, 11, 27, tzinfo=timezone.utc)
    monkeypatch.setattr(sprint, "window_state", lambda sf, now=None: real_window_state(sf, instant))

    code, out, err = cli("plans", "--repo", root, "--format", "json")
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    assert out == _golden_bytes(doc)
    rows = {row["kind"]: row for row in doc["plans"]}
    assert list(rows) == ["milestone", "roadmap", "sprint", "release"]
    _check_golden(f"{name}.plans.json", doc)

    _, out, _ = cli("timeline", "--repo", root, "--json")
    milestone = json.loads(out)["milestones"][0]
    assert rows["milestone"]["progress"] == milestone["progress"]
    assert milestone["progress"]["tasks"]["done"] == 1
    assert rows["milestone"]["state"] == milestone["state"]
    _, out, _ = cli("sprint", "status", "example", "--repo", root, "--format", "json")
    status = json.loads(out)
    sprint_progress = rows["sprint"]["progress"]
    assert rows["sprint"]["state"] == status["window_state"]
    assert sprint_progress["total"] == len(status["tasks"])
    assert sprint_progress["done"] == sum(task["state"] == "done" for task in status["tasks"])
    assert {task["id"]: task["state"] for task in sprint_progress["tasks"]} == {
        task["id"]: task["state"] for task in status["tasks"]
    }

    code, out, err = cli("plans", "--repo", root)
    assert code == 0 and not err, err
    assert "1 of 2 tasks done" in out
    for row in doc["plans"]:
        assert f"{row['path']}:{row['line']}" in out


@needs_git
def test_plans_drift_uses_timeline_findings(cli, project, monkeypatch):
    from steward import milestones

    _no_network(monkeypatch)
    original = milestones.timeline
    monkeypatch.setattr(milestones, "timeline", lambda root, cfg, now=None: original(root, cfg, parse_now(NOW)))
    source = project / milestones.FILE
    source.write_text(source.read_text(encoding="utf-8").replace("12-03", "12-06"), encoding="utf-8")
    commit(project, "Move the milestone", 1)
    source.write_text(source.read_text(encoding="utf-8").replace("12-06", "12-08"), encoding="utf-8")

    doc = _json(cli, "plans", "--repo", project)
    timeline = _json(cli, "timeline", "--repo", project)
    row = next(row for row in doc["plans"] if row["id"] == "preprint")
    assert row["drift"]["date"] == timeline["drift"]["date"][0]
    assert row["drift"]["changes"] == timeline["drift"]["changes"][::-1]
    assert row["drift"]["changes"][0]["commit"] is None
    assert row["drift"]["date"]["moves"] == 2
    assert source.read_text(encoding="utf-8").splitlines()[row["line"] - 1] == "[[milestone]]"
