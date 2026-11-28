"""P03 (0.24.0): what the cockpit still missed. `steward next` gains `since`; `task board --format json` gives each
task its owner, implementer, task window and the `steward tidy` stale mark; `authorize pending --format json` items
carry the sign command bound to the payload's SHA-256."""

import hashlib
import json
import shlex

from test_cockpit_w03 import NONCE, NOW, _json, _no_network, commit, needs_git, project, sh  # noqa: F401


def one(rows):
    rows = list(rows)
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------- next: since the last session handoff
@needs_git
def test_since_lists_what_changed_after_the_handoff_newest_first(cli, project, monkeypatch):  # noqa: F811
    from steward import ledger
    from steward import sprint as sp

    _no_network(monkeypatch)
    (project / "development/DECISIONS.md").write_text(
        "# Decisions\n\n## 2026-10-01: before the handoff\nOld.\n\n## 2026-11-20: keep cohort C\nNew.\n",
        encoding="utf-8")
    commit(project, "record a decision", 3)
    sh(project, "git", "tag", "v0.1.0")
    (project / "development/sprints").mkdir(parents=True, exist_ok=True)
    (project / "development/sprints/s1.toml").write_text(
        'schema = "steward.sprint/0.1"\n[sprint]\nid = "s1"\n'
        'window = { start = 2026-11-26T00:00:00Z, end = 2026-11-28T00:00:00Z }\n'
        '[[task]]\nid = "A"\ntitle = "first"\ncommand = "true"\ndone = ["true"]\n', encoding="utf-8")
    saved = ledger._now
    ledger._now = lambda: "2026-11-26T12:00:00Z"
    try:
        sp.led(project, "s1", "x").append("state", {"task": "A", "state": "done", "branch": "sprint/s1/A"})
    finally:
        ledger._now = saved

    doc = _json(cli, "next", "--now", NOW)
    since = doc["since"]
    kinds = [row["kind"] for row in since]
    assert {"commit", "decision", "release", "sprint"} <= set(kinds)
    titles = [row["title"] for row in since]
    assert "milestone" in titles and "record a decision" in titles and "start" not in titles  # the handoff's commit
    decision = one(row for row in since if row["kind"] == "decision")
    assert decision["title"] == "2026-11-20: keep cohort C" and decision["source"] == "development/DECISIONS.md"
    assert decision["line"] == 6
    release = one(row for row in since if row["kind"] == "release")
    assert release["id"] == "v0.1.0" and release["source"] == "refs/tags/v0.1.0"
    event = one(row for row in since if row["kind"] == "sprint" and "task A" in row["title"])
    assert event["time"] == "2026-11-26T12:00:00Z" and event["title"] == "sprint s1 task A: done"
    assert all(row["source"] for row in since)
    times = [row["time"] for row in since]
    assert times == sorted(times, reverse=True)  # newest first

    code, text, _ = cli("next", "--now", NOW)
    assert code == 0
    assert f"Since last handoff ({len(since)})" in text and "[development/DECISIONS.md:6]" in text


@needs_git
def test_since_is_empty_right_after_a_handoff(cli, project, monkeypatch):  # noqa: F811
    _no_network(monkeypatch)
    handoff = project / "development/HANDOFF.md"
    handoff.write_text(handoff.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    commit(project, "handoff", 0)
    doc = _json(cli, "next", "--now", NOW)
    assert doc["since"] == []
    assert "Since last handoff (0): nothing" in cli("next", "--now", NOW)[1]


# ---------------------------------------------------------------- task board: owner, implementer, window, stale
@needs_git
def test_board_gives_owner_implementer_window_and_the_tidy_stale_mark(cli, project, monkeypatch):  # noqa: F811
    from steward import ledger
    from steward.ledger import Ledger
    from steward.models import load_config

    _no_network(monkeypatch)
    task = project / "development/tasks/PRJ-001.md"
    task.write_text(task.read_text(encoding="utf-8") + "- **Owner:** Example owner · **Approver:** Example approver\n"
                    "- **Implementer:** Example agent\n\n## Notes\n- **Owner:** not a header field\n",
                    encoding="utf-8")
    commit(project, "task header", 20)
    cfg = load_config(project)
    saved = ledger._now
    ledger._now = lambda: "2026-11-02T00:00:00Z"
    try:
        led = Ledger(project / ".steward/task-tokens.jsonl", "task-tokens", cfg.steward.repo_id)
        led.append("start", {"task": "PRJ-001", "at": "2026-11-01T00:00:00Z"})
        led.append("done", {"task": "PRJ-001", "at": "2026-11-02T00:00:00Z"})
    finally:
        ledger._now = saved

    board = _json(cli, "task", "board", "--now", NOW)
    rows = {row["id"]: row for row in board["tasks"]}
    open_ = rows["PRJ-001"]
    assert (open_["owner"], open_["implementer"]) == ("Example owner", "Example agent")
    assert open_["window"] == {"open": False, "start": "2026-11-01T00:00:00Z", "end": "2026-11-02T00:00:00Z",
                               "source": "task-tokens", "ledger": ".steward/task-tokens.jsonl"}
    tidy = one(i for i in _json(cli, "tidy", "--now", NOW)["items"] if i["kind"] == "stale_task")
    assert open_["stale"] and open_["stale_reason"] == tidy["message"] == "proposed; untouched for 20 days"
    done = rows["PRJ-002"]
    assert done["owner"] is None and not done["stale"] and done["stale_reason"] is None  # a closed task is never stale

    fresh = _json(cli, "task", "board", "--now", "2026-11-10T00:00:00Z")  # 3 days after its last commit
    assert not {r["id"]: r for r in fresh["tasks"]}["PRJ-001"]["stale"]
    code, text, _ = cli("task", "board", "--now", NOW)
    assert code == 0 and "development/tasks/PRJ-001.md (stale)" in text
    code, _, err = cli("task", "board", "--now", "yesterday")
    assert code == 64 and "yesterday" in err  # EX_USAGE


# ---------------------------------------------------------------- authorize pending: the sign command
@needs_git
def test_pending_items_carry_the_sign_command_bound_to_the_payload_bytes(cli, project, monkeypatch):  # noqa: F811
    _no_network(monkeypatch)
    doc = _json(cli, "authorize", "pending")
    item = one(doc["items"])
    payload = (project / f".steward/pending/{NONCE}.txt").read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert item["nonce"] == NONCE and item["payload_sha256"] == digest and item["state"] == "waiting"
    assert item["sign_argv"] == ["steward", "authorize", "sign", NONCE, "--expect-sha256", digest]
    assert item["sign_command"] == shlex.join(item["sign_argv"])


@needs_git
def test_a_payload_that_cannot_be_signed_here_has_no_sign_command(cli, project, monkeypatch):  # noqa: F811
    _no_network(monkeypatch)
    path = project / f".steward/pending/{NONCE}.txt"
    text = path.read_text(encoding="utf-8")
    from steward.models import load_config

    path.write_text(text.replace(load_config(project).steward.repo_id, "00000000-0000-4000-8000-0000000000ff"),
                    encoding="utf-8")
    item = one(_json(cli, "authorize", "pending")["items"])
    assert item["state"] == "foreign" and item["sign_argv"] is None and item["sign_command"] is None


def test_sign_argv_names_a_peer_checkout_and_refuses_odd_values(tmp_path):
    from steward import authorize as az

    digest = "f" * 64
    assert az.sign_argv(NONCE, digest, tmp_path)[-2:] == ["--repo", str(tmp_path)]
    assert az.sign_argv("not-a-nonce", digest) is None
    assert az.sign_argv(NONCE, "abc") is None
    json.dumps(az.sign_argv(NONCE, digest))
