"""0.22.0 X03: the agents ledger: directional scoring ([agents] may_score, R-62), the optional attempt fields, and
`steward agents event` / `steward agents list`.

Regenerate the goldens after an intended change: STEWARD_UPDATE_GOLDENS=1 pytest tests/test_v0220_agents_ledger.py
"""

import json
import os

import pytest

from conftest import codes, one
from test_interface import GOLDEN, _golden_bytes, machine_example  # noqa: F401
from test_interface_w02 import _valid


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    return r


def add(root, text):
    with open(root / "steward.toml", "a") as f:
        f.write(text)


def attempt(cli, task, agent, *extra):
    return cli("agents", "attempt", task, "--agent", agent, "--provider", "p", "--model", "m", *extra)


def score(cli, task, n, scorer, *extra):
    return cli("agents", "score", task, "--attempt", str(n), "--scorer", scorer, "--score", "4", "--rubric", "r",
               *extra)


def ledger_lines(root):
    return [json.loads(line) for line in (root / "development/agents.jsonl").read_text().splitlines()]


# ---------------------------------------------------------------- Verify 1: directional scoring
def test_X03_verify_1_impl_may_not_score_final_and_final_may_score_impl(cli, proj):
    add(proj, '\n[agents]\nmay_score = { final = ["impl"] }\n')
    assert attempt(cli, "T-1", "final")[0] == 0
    assert attempt(cli, "T-2", "impl")[0] == 0
    code, _, err = score(cli, "T-1", 1, "impl")
    assert code == 64 and "may_score" in err and "impl" in err
    assert score(cli, "T-2", 1, "final")[0] == 0
    assert [e["kind"] for e in ledger_lines(proj)][-1] == "score"  # the refused score was never written
    assert sum(e["kind"] == "score" for e in ledger_lines(proj)) == 1
    _, rep = cli.check(proj, "agents")
    assert one(rep, "R-62")["status"] == "PASS"


def test_X03_a_scorer_not_in_the_table_is_refused_and_self_scoring_still_is(cli, proj):
    add(proj, '\n[agents]\nmay_score = { final = ["impl"] }\n')
    attempt(cli, "T-1", "impl")
    code, _, err = score(cli, "T-1", 1, "other")
    assert code == 64 and "may_score" in err
    code, _, err = score(cli, "T-1", 1, "impl")
    assert code == 64 and "author" in err


def test_X03_an_override_is_checked_against_the_table_too(cli, proj):
    add(proj, '\n[agents]\nmay_score = { final = ["impl"], lead = ["impl", "final"] }\n')
    attempt(cli, "T-1", "impl")
    assert score(cli, "T-1", 1, "final")[0] == 0
    assert score(cli, "T-1", 1, "lead", "--override", "second reading")[0] == 0
    attempt(cli, "T-2", "final")
    assert score(cli, "T-2", 1, "impl", "--override", "a reason")[0] == 64
    assert score(cli, "T-2", 1, "lead")[0] == 0


def test_X03_r62_fails_a_hand_written_score_outside_the_table(cli, proj):
    from steward.ledger import Ledger

    add(proj, '\n[agents]\nmay_score = { final = ["impl"] }\n')
    attempt(cli, "T-1", "final")
    Ledger(proj / "development/agents.jsonl", "agents").append(
        "score", {"task": "T-1", "attempt": 1, "scorer": "impl", "score": 5, "rubric": "r", "override": None})
    _, rep = cli.check(proj, "agents")
    res = one(rep, "R-62")
    assert res["status"] == "FAIL" and "R-62.not_permitted" in codes(res)


def test_X03_without_the_table_any_non_author_may_score_as_before(cli, proj):
    add(proj, "\n[agents]\n")
    attempt(cli, "T-1", "final")
    assert score(cli, "T-1", 1, "impl")[0] == 0
    _, rep = cli.check(proj, "agents")
    res = one(rep, "R-62")
    assert res["status"] == "PASS" and res["reason"] == "1 attempt(s); every score by another agent"


def test_X03_an_empty_table_lets_no_one_score(cli, proj):
    add(proj, "\n[agents]\nmay_score = {}\n")
    attempt(cli, "T-1", "impl")
    assert score(cli, "T-1", 1, "final")[0] == 64


# ---------------------------------------------------------------- Verify 2: estimate and events in the output
def test_X03_verify_2_an_attempt_with_an_estimate_and_events_lists_both(cli, proj):
    add(proj, "\n[agents]\n")
    (proj / "estimate.json").write_text('{"assumptions": ["one module"], "effort": "2h", "cost": 1.5, "tokens": 900}')
    assert attempt(cli, "T-1", "impl", "--estimate-file", "estimate.json", "--harness", "H", "--harness-version",
                   "1.2", "--parent", "T-0", "--status", "review")[0] == 0
    for kind, time in (("assigned", "2026-11-27T09:00:00Z"), ("implemented", "2026-11-27T11:00:00Z"),
                       ("reviewed", "2026-11-27T12:00:00+00:00")):
        assert cli("agents", "event", "T-1", "--kind", kind, "--time", time)[0] == 0
    code, out, err = cli("agents", "list")
    assert code == 0, err
    assert "estimate: " in out and '"effort": "2h"' in out
    assert "harness H 1.2" in out and "status review" in out and "parent T-0" in out
    events = [line.strip() for line in out.splitlines() if line.strip().startswith("event ")]
    assert events == ["event reviewed at 2026-11-27T12:00:00+00:00", "event implemented at 2026-11-27T11:00:00Z",
                      "event assigned at 2026-11-27T09:00:00Z"]  # newest first
    code, out, err = cli("agents", "list", "--format", "json")
    assert code == 0, err
    task, = _valid(json.loads(out))["tasks"]
    a, = task["attempts"]
    assert a["estimate"] == {"assumptions": ["one module"], "effort": "2h", "cost": 1.5, "tokens": 900}
    assert (a["harness"], a["harness_version"], a["parent"], a["status"]) == ("H", "1.2", "T-0", "review")
    assert [e["kind"] for e in task["events"]] == ["reviewed", "implemented", "assigned"]


def test_X03_verify_2_without_the_new_fields_an_attempt_is_recorded_as_before(cli, proj):
    add(proj, "\n[agents]\n")
    attempt(cli, "T-1", "impl", "--suggested", "m", "--started", "2026-11-27T10:00:00Z")
    entry = ledger_lines(proj)[-1]
    body = {k: v for k, v in entry.items() if k not in ("seq", "prev", "time", "hash")}
    assert body == {"kind": "attempt", "task": "T-1", "attempt": 1, "agent": "impl", "provider": "p", "model": "m",
                    "suggested": "m", "started": "2026-11-27T10:00:00Z", "ended": None, "reviewer": None}


def test_X03_events_are_checked_and_stored_without_touching_the_ledger_envelope(cli, proj):
    add(proj, "\n[agents]\n")
    code, _, err = cli("agents", "event", "T-1", "--kind", "merged", "--time", "2026-11-27T12:00:00")
    assert code == 64 and "time zone" in err
    code, _, err = cli("agents", "event", "T-1", "--kind", "merged", "--time", "yesterday")
    assert code == 64
    code, _, err = cli("agents", "event", "T-1", "--kind", "shipped", "--time", "2026-11-27T12:00:00Z")
    assert code == 64
    assert not (proj / "development/agents.jsonl").exists()
    assert cli("agents", "event", "T-1", "--kind", "verified", "--time", "2026-11-27T12:00:00Z")[0] == 0
    entry = ledger_lines(proj)[-1]
    assert entry["kind"] == "event" and entry["event"] == "verified" and entry["at"] == "2026-11-27T12:00:00Z"
    _, rep = cli.check(proj, "agents")
    assert one(rep, "R-62")["status"] == "PASS"  # events are not scores


def test_X03_an_estimate_file_must_hold_a_json_object(cli, proj):
    add(proj, "\n[agents]\n")
    (proj / "list.json").write_text("[1, 2]")
    (proj / "bad.json").write_text("{not json")
    assert attempt(cli, "T-1", "impl", "--estimate-file", "list.json")[0] == 65
    assert attempt(cli, "T-1", "impl", "--estimate-file", "bad.json")[0] == 65
    assert attempt(cli, "T-1", "impl", "--estimate-file", "missing.json")[0] == 64
    assert not (proj / "development/agents.jsonl").exists()


def test_X03_list_orders_tasks_attempts_and_scores_newest_first(cli, proj):
    add(proj, "\n[agents]\n")
    attempt(cli, "T-1", "a1")
    attempt(cli, "T-2", "a1")
    attempt(cli, "T-1", "a1")
    score(cli, "T-1", 2, "a2")
    score(cli, "T-1", 2, "a3", "--override", "second reading")
    _, out, _ = cli("agents", "list", "--format", "json")
    doc = _valid(json.loads(out))
    assert [t["task"] for t in doc["tasks"]] == ["T-1", "T-2"]
    t1 = doc["tasks"][0]
    assert [a["attempt"] for a in t1["attempts"]] == [2, 1]
    assert [s["scorer"] for s in t1["attempts"][0]["scores"]] == ["a3", "a2"]
    _, out, _ = cli("agents", "list", "T-2", "--format", "json")
    assert [t["task"] for t in json.loads(out)["tasks"]] == ["T-2"]
    _, out, _ = cli("agents", "list")
    assert out.index("T-1:") < out.index("T-2:")
    assert out.index("attempt 2:") < out.index("attempt 1:")


def test_X03_list_without_a_ledger_and_with_an_edited_one(cli, proj):
    add(proj, "\n[agents]\n")
    code, out, _ = cli("agents", "list")
    assert code == 0 and "no attempts or events recorded" in out
    code, out, _ = cli("agents", "list", "--format", "json")
    assert code == 0 and _valid(json.loads(out))["tasks"] == []
    attempt(cli, "T-1", "a1")
    p = proj / "development/agents.jsonl"
    p.write_text(p.read_text().replace('"agent":"a1"', '"agent":"a9"'))
    code, out, err = cli("agents", "list")
    assert code == 65 and not out and "edited" in err


# ---------------------------------------------------------------- goldens on both worked examples
def test_X03_agents_list_goldens(cli, machine_example, monkeypatch):  # noqa: F811
    name, root = machine_example
    with open(root / "steward.toml", "a") as f:
        f.write('\n[agents]\nmay_score = { final = ["impl"] }\n')
    (root / "fixture-estimate.json").write_text('{"effort": "3h", "tokens": 1200}')
    assert attempt(cli, "EX-1", "impl", "--repo", root, "--estimate-file", str(root / "fixture-estimate.json"),
                   "--harness", "fixture-harness", "--harness-version", "1.0", "--status", "review")[0] == 0
    assert score(cli, "EX-1", 1, "final", "--repo", root)[0] == 0
    assert attempt(cli, "EX-2", "final", "--repo", root, "--parent", "EX-1")[0] == 0
    for kind, time in (("assigned", "2026-11-27T09:00:00Z"), ("implemented", "2026-11-27T10:00:00Z")):
        assert cli("agents", "event", "EX-1", "--kind", kind, "--time", time, "--repo", root)[0] == 0
    code, out, err = cli("agents", "list", "--repo", root, "--format", "json")
    assert code == 0 and not err, err
    doc = _valid(json.loads(out))
    path = GOLDEN / f"{name}.agents-list.json"
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.write_text(out, encoding="utf-8", newline="\n")
    assert out == path.read_text(encoding="utf-8") == _golden_bytes(doc), f"output differs from {path}"
    code, interface, _ = cli("interface", "--format", "json")
    assert json.loads(interface)["commands"]["agents list"]["schema"] == doc["schema"] == "steward.agents_list/0.1"
