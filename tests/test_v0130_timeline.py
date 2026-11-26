"""0.13.0: milestones and steward timeline (RELEASE_v0.13.0_SPEC §3; DESIGN_BRIEF_sprint §5)."""

import datetime as dt
import json

import pytest

from conftest import codes, one
from test_v090_requests import TASKS, _add, _task, _write  # noqa: F401
from test_v090_requests import board, proj  # noqa: F401


def _iso(days):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).replace(microsecond=0).isoformat()


def _milestones(root, *blocks):
    (root / "development/milestones.toml").write_text('schema = "steward.milestones/0.1"\n' + "".join(blocks))


def _m(mid, days, **kw):
    lines = [f'\n[[milestone]]\nid = "{mid}"\ntitle = "{mid} goal"\ndue = {_iso(days)}\n']
    for k, v in kw.items():
        lines.append(f"{k} = {json.dumps(v) if not isinstance(v, int) else v}\n")
    return "".join(lines)


def _rows(cli):
    code, out, err = cli("timeline", "--json")
    assert code == 0, err
    return {r["id"]: r for r in json.loads(out)["milestones"]}


def test_M2_soonest_first_with_progress_from_the_board_and_the_gate(cli, board):
    _milestones(board, _m("preprint", 30, kind="preprint", tasks=["TSK-001", "TSK-003"], gate="default"),
                _m("ismb", 10, kind="submission", tasks=["TSK-003"], buffer_days=3))
    code, out, _ = cli("timeline", "--json")
    ids = [r["id"] for r in json.loads(out)["milestones"]]
    assert ids == ["ismb", "preprint"]
    rows = _rows(cli)
    assert rows["ismb"]["progress"]["tasks"] == {"done": 1, "total": 1, "open": [], "unknown": []}
    assert rows["ismb"]["state"] == "ready"
    pre = rows["preprint"]
    assert pre["progress"]["tasks"]["open"] == ["TSK-001"] and "gate" in pre["progress"] and pre["state"] == "on track"
    _, text, _ = cli("timeline")
    assert "tasks: 1 of 2 done; open TSK-001" in text and "not estimated" in text


def test_M2_open_work_after_the_internal_deadline_is_at_risk_and_after_due_is_late(cli, board):
    _milestones(board, _m("soon", 2, tasks=["TSK-001"], buffer_days=5), _m("gone", -1, tasks=["TSK-001"]))
    rows = _rows(cli)
    assert rows["soon"]["state"] == "at risk" and rows["gone"]["state"] == "late"


def test_M1_a_due_time_without_a_time_zone_is_refused(cli, board):
    (board / "development/milestones.toml").write_text(
        'schema = "steward.milestones/0.1"\n[[milestone]]\nid = "x"\ntitle = "x"\ndue = 2027-01-20T23:59:00\n')
    code, _, err = cli("timeline")
    assert code == 65 and "time zone" in err


def test_M3_r70_names_missing_tasks_and_a_past_due_milestone_without_an_outcome(cli, board):
    _milestones(board, _m("a", 5, tasks=["TSK-999"]), _m("b", -2))
    _, rep = cli.check(board, "milestones")
    res = one(rep, "R-70")
    assert res["status"] == "FAIL" and {"R-70.unknown_task", "R-70.past_due"} <= codes(res)
    _milestones(board, _m("b", -2) + '[milestone.outcome]\nstate = "moved"\ndecision = "2026-11-24: moved to March"\n')
    _, rep = cli.check(board, "milestones")
    assert one(rep, "R-70")["status"] == "PASS"


def test_M3_r70_is_advisory_and_not_applicable_without_a_file(cli, board):
    _, rep = cli.check(board, "milestones")
    assert one(rep, "R-70")["status"] == "NOT_APPLICABLE"
    from steward.models import ADVISORY
    assert "R-70" in ADVISORY


def test_V8_tasks_without_a_board_are_not_ready_and_r70_says_so(cli, proj):
    _milestones(proj, _m("x", 10, tasks=["TSK-001"]))
    code, out, _ = cli("timeline", "--json")
    row = json.loads(out)["milestones"][0]
    assert row["state"] != "ready" and row["open_work"] >= 1
    _, rep = cli.check(proj, "milestones")
    assert "R-70.no_board" in codes(one(rep, "R-70"))
