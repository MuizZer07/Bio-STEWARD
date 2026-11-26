"""STW-018: native log fixtures, attribution, budget warnings and privacy."""

import json
from datetime import datetime

import pytest

from steward.cli import main
from steward.ledger import Ledger

SECRET = "never-print-this-prompt-or-tool-output"
START = "2026-11-25T12:00:00+00:00"
MID = "2026-11-25T12:01:00+00:00"
END = "2026-11-25T12:02:00+00:00"


def jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "steward.toml").write_text("""[steward]
schema = "steward.toml/0.2"
repo_id = "123e4567-e89b-42d3-a456-426614174000"
project = "Token fixture"
[spend]
cap = 1
[spend.prices.claude-test]
input_per_1k = 1
output_per_1k = 2
cache_read_per_1k = 0.5
cache_write_per_1k = 3
source = "fixture"
retrieved = "2026-11-25"
""")
    tasks = tmp_path / "development/tasks"
    tasks.mkdir(parents=True)
    (tasks / "task.md").write_text("# Task\n\n- **ID:** TEST-001\n- **tokens_budget:** 100\n")
    return tmp_path


def mark(project, monkeypatch, operation, when, *args):
    from steward import tokens
    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(when))
    assert main(["task", operation, "TEST-001", *args]) == 0


def claude_messages(extra=0):
    call = {"type": "tool_use", "id": "tool-one", "name": "Read", "input": {"file_path": "src/example.py"}}
    reply = {"type": "tool_result", "tool_use_id": "tool-one", "content": SECRET}
    message = {"id": "message-one", "model": "claude-test", "content": [{"type": "text", "text": SECRET}, call],
               "usage": {"input_tokens": 30, "output_tokens": 20 + extra, "cache_read_input_tokens": 20,
                         "cache_creation_input_tokens": 10}}
    return [
        {"type": "assistant", "sessionId": "session-claude", "timestamp": MID, "message": message},
        {"type": "assistant", "sessionId": "session-claude", "timestamp": MID, "message": message},
        {"type": "user", "sessionId": "session-claude", "timestamp": MID, "message": {"content": [reply]}},
    ]


def codex_messages():
    def usage(uncached, cached, output):
        return {"input_tokens": uncached + cached, "cached_input_tokens": cached, "output_tokens": output,
                "reasoning_output_tokens": 2, "total_tokens": uncached + cached + output}

    def count(when, last, total):
        return {"type": "event_msg", "timestamp": when, "payload": {"type": "token_count", "info": {
            "last_token_usage": last, "total_token_usage": total}}}

    return [
        {"type": "session_meta", "payload": {"id": "session-codex"}},
        {"type": "turn_context", "payload": {"model": "codex-test"}},
        count("2026-11-25T11:59:00+00:00", usage(10, 2, 5), usage(10, 2, 5)),
        count(MID, usage(7, 5, 4), usage(17, 7, 9)),
        count(MID, usage(7, 5, 4), usage(17, 7, 9)),
        {"type": "response_item", "timestamp": MID,
         "payload": {"type": "function_call_output", "call_id": "one", "output": SECRET}},
        {"type": "event_msg", "timestamp": MID, "payload": {
            "type": "exec_command_end", "call_id": "one", "parsed_cmd": [
                {"type": "read", "path": "src/example.py", "cmd": SECRET}], "aggregated_output": SECRET}},
        count(END, usage(1, 0, 2), usage(18, 7, 11)),
    ]


def gemini_messages():
    return [{"id": "message-one", "type": "gemini", "model": "gemini-test", "timestamp": MID, "content": SECRET,
             "tokens": {"input": 22, "cached": 5, "output": 8, "thoughts": 3, "tool": 2, "total": 35},
             "toolCalls": [{"id": "tool-one", "name": "read_file", "args": {"file_path": "src/example.py"},
                            "timestamp": MID, "result": SECRET}]}]


def test_report_hand_count(project, monkeypatch, capsys):
    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    claude = jsonl(project / "claude.jsonl", claude_messages())
    codex = jsonl(project / "codex.jsonl", codex_messages())
    gemini = project / "gemini.json"
    gemini.write_text(json.dumps({"sessionId": "session-gemini", "messages": gemini_messages()}))
    capsys.readouterr()
    args = ["--claude", str(claude), "--codex", str(codex), "--gemini", str(gemini)]
    assert main(["tokens", "report", "--task", "TEST-001", "--since", "2026-11-25", "--json", *args]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    task, = json.loads(out)["tasks"]
    assert task["tokens"] == 131
    assert task["cost"] is None
    assert task["status"] == "available"
    by_agent = {row["agent"]: row for row in task["models"]}
    assert by_agent["claude"]["cost"] == pytest.approx(0.11)
    assert by_agent["claude"]["cache_write"] == by_agent["claude"]["cache_read"] // 2 == 10
    assert by_agent["codex"]["tokens"] == 16
    assert by_agent["codex"]["cache_read"] == by_agent["gemini"]["cache_read"] == 5
    assert by_agent["gemini"]["tokens"] == 35
    assert task["files_read"] == [{"path": "src/example.py", "reads": 3}]
    assert [row["bytes"] for row in task["tool_outputs"]] == [len(SECRET)] * 3
    assert main(["tokens", "report", "--svg", *args]) == 0
    out, err = capsys.readouterr()
    assert "<svg" in out and "TEST-001" in out and SECRET not in out + err


@pytest.mark.parametrize(("extra", "warning"), [(0, "80%"), (20, "100%")])
def test_check_warns_in_terminal_hook_and_status_line(project, monkeypatch, capsys, extra, warning):
    import io
    import sys

    mark(project, monkeypatch, "start", START)
    from steward import tokens
    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(END))
    path = jsonl(project / "claude.jsonl", claude_messages(extra))
    capsys.readouterr()
    assert main(["tokens", "check", "--claude", str(path)]) == 0
    assert warning in capsys.readouterr().out
    for option in ("--claude-hook", "--claude-statusline"):
        payload = {"session_id": "session-claude", "transcript_path": str(path), "tool_response": SECRET}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert main(["tokens", "check", option]) == 0
        out, err = capsys.readouterr()
        assert SECRET not in out + err
        assert warning in (json.loads(out)["systemMessage"] if option == "--claude-hook" else out)


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_unavailable_and_opt_in(project, monkeypatch, capsys, agent):
    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    path = jsonl(project / "unknown.jsonl", [{"content": SECRET}])
    capsys.readouterr()
    assert main(["tokens", "report", "--json", f"--{agent}", str(path)]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    report = json.loads(out)
    assert report["sources"][agent]["status"] == "unavailable"
    assert report["tasks"][0]["tokens"] is None
    assert main(["tokens", "report", "--json"]) == 0
    assert all(not src["files"] for src in json.loads(capsys.readouterr().out)["sources"].values())


def test_agents_ledger_filters_models_and_gemini_jsonl(project, monkeypatch, capsys):
    from steward import tokens

    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(END))
    Ledger(project / "development/agents.jsonl", "agents", "123e4567-e89b-42d3-a456-426614174000", base=project).append("attempt", {
        "task": "TEST-001", "agent": "Gemini CLI", "model": "gemini-test", "started": START, "ended": END,
    })
    messages = gemini_messages()
    wrong_model = {**messages[0], "model": "gemini-other", "id": "other"}
    gemini = jsonl(project / "gemini.jsonl", [{"sessionId": "session-gemini", "projectHash": "test"},
                                             *messages, wrong_model])
    assert main(["tokens", "report", "--json", "--gemini", str(gemini)]) == 0
    task, = json.loads(capsys.readouterr().out)["tasks"]
    assert task["tokens"] == 35
    assert main(["tokens", "report", "--json", "--since", "2026-11-26", "--gemini", str(gemini)]) == 0
    assert not json.loads(capsys.readouterr().out)["tasks"]


def test_overlapping_windows_exclude_ambiguous_usage_even_in_filtered_report(project, monkeypatch, capsys):
    from steward import tokens

    mark(project, monkeypatch, "start", START)
    assert main(["task", "start", "TEST-002"]) == 0
    assert main(["task", "start", "TEST-001"]) == 65
    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(END))
    assert main(["task", "done", "TEST-003"]) == 65
    assert main(["task", "done", "TEST-002"]) == 0
    path = jsonl(project / "claude.jsonl", claude_messages())
    capsys.readouterr()
    assert main(["tokens", "report", "--task", "TEST-001", "--json", "--claude", str(path)]) == 0
    row, = json.loads(capsys.readouterr().out)["tasks"]
    assert row["tokens"] is None
    assert row["status"] == "unavailable"


def test_concurrent_sessions_and_partial_budget_warning(project, monkeypatch, capsys):
    from steward import tokens

    mark(project, monkeypatch, "start", START, "--session", "session-claude")
    assert main(["task", "start", "TEST-002", "--session", "other-session"]) == 0
    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(END))
    transcript = jsonl(project / "claude.jsonl", claude_messages())
    with transcript.open("a") as stream:
        stream.write("{" + SECRET)
    capsys.readouterr()
    assert main(["tokens", "report", "--json", "--claude", str(transcript)]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    first, second = json.loads(out)["tasks"]
    assert first["tokens"] == 80 and first["status"] == "partial" and first["cost"] is None
    assert second["tokens"] is None
    assert main(["tokens", "check", "--task", "TEST-001", "--claude", str(transcript)]) == 0
    assert "coverage partial (budget threshold 80%)" in capsys.readouterr().out


def test_missing_counters_and_cache_prices(project, monkeypatch, capsys):
    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    records = claude_messages()
    (project / "steward.toml").write_text((project / "steward.toml").read_text().replace("cache_write_per_1k = 3\n", ""))
    broken = {**records[0], "message": {"id": "broken", "model": "claude-test", "usage": {"input_tokens": 999}}}
    rows = codex_messages()
    for row, last, total in ((rows[2], 0, 0), (rows[3], 3, 3), (rows[4], 3, 3), (rows[-1], 0, 3)):
        info = row["payload"]["info"]
        info["last_token_usage"]["cache_write_input_tokens"] = last
        info["total_token_usage"]["cache_write_input_tokens"] = total
    codex = jsonl(project / "codex.jsonl", rows)
    claude = jsonl(project / "claude.jsonl", [*records, broken])
    capsys.readouterr()
    assert main(["tokens", "report", "--json", "--codex", str(codex), "--claude", str(claude)]) == 0
    row, = json.loads(capsys.readouterr().out)["tasks"]
    assert row["status"] == "partial" and row["tokens"] == 96
    anthro, openai = row["models"]
    assert anthro["tokens"] == 80 and anthro["cost"] is None
    assert openai["cache_write"] == 3


def test_unknown_claude_cache_counts_are_unavailable(project, monkeypatch, capsys):
    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    rows = claude_messages()
    for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        del rows[0]["message"]["usage"][key]
    transcript = jsonl(project / "claude.jsonl", rows)
    capsys.readouterr()
    assert main(["tokens", "report", "--json", "--claude", str(transcript)]) == 0
    result, = json.loads(capsys.readouterr().out)["tasks"]
    model, = result["models"]
    assert model["tokens"] == 50
    assert model["cache_read"] is None and model["cache_write"] is None and model["cost"] is None


def test_gemini_result_patch_changes_size_without_leaking_content(project, monkeypatch, capsys):
    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    message, = gemini_messages()
    path = jsonl(project / "gemini.jsonl", [
        {"sessionId": "session-gemini", "projectHash": "test"}, {**message, "tokens": None}, message,
        {"$patch": {"updates": [{"id": "message-one", "toolCalls": [{"id": "tool-one", "result": SECRET * 2}]}]}},
    ])
    capsys.readouterr()
    assert main(["tokens", "report", "--json", "--gemini", str(path)]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    result, = json.loads(out)["tasks"]
    assert result["status"] == "available" and result["tokens"] == 35
    tool, = result["tool_outputs"]
    assert tool["bytes"] == len(SECRET) * 2
    assert tool["log_path"] == "gemini log 1" and tool["paths"] == ["src/example.py"]  # AF14: no local log path


def test_task_file_from_board_and_below_threshold(project, monkeypatch, capsys):
    original = project / "development/tasks/task.md"
    spec = project / "spec.md"
    original.rename(spec)
    with spec.open("a") as stream:
        stream.write("\n## Work log\n\n- **tokens_budget:** 1\n")
    with (project / "steward.toml").open("a") as stream:
        stream.write('\n[tasks]\nboard = "BOARD.md"\nspecs = ["spec.md"]\n')
    mark(project, monkeypatch, "start", START)
    from steward import tokens
    monkeypatch.setattr(tokens, "now", lambda: datetime.fromisoformat(END))
    log = jsonl(project / "claude.jsonl", claude_messages(-1))
    capsys.readouterr()
    assert main(["tokens", "check", "--claude", str(log)]) == 0
    out, _ = capsys.readouterr()
    assert "79 / 100 tokens" in out and "WARNING" not in out


def test_link_or_fifo_log_is_unavailable_and_reports_read_only(project, monkeypatch, capsys):
    import os

    mark(project, monkeypatch, "start", START)
    mark(project, monkeypatch, "done", END)
    transcript = jsonl(project / "claude.jsonl", claude_messages())
    link = project / "symlink.jsonl"
    link.symlink_to(transcript)
    fifo = project / "fifo.jsonl"
    os.mkfifo(fifo)
    snapshot = {p: p.read_bytes() for p in (project / ".steward").iterdir() if p.is_file()}
    before = transcript.read_bytes()
    capsys.readouterr()
    assert main(["tokens", "report", "--json", "--claude", str(link), "--claude", str(fifo)]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    assert json.loads(out)["sources"]["claude"]["status"] == "unavailable"
    assert transcript.read_bytes() == before
    assert all(p.read_bytes() == content for p, content in snapshot.items())


def test_codex_completed_items_and_date_cutoff(project, monkeypatch, capsys):
    mark(project, monkeypatch, "start", "2026-11-24T23:00:00+00:00")
    mark(project, monkeypatch, "done", END)
    rows = codex_messages()
    rows[2]["timestamp"] = "2026-11-24T23:59:00+00:00"
    rows[6]["payload"] = {"type": "item_completed", "item": {
        "type": "CommandExecution", "id": "one", "status": "completed", "exit_code": 0,
        "parsed_cmd": [{"type": "read", "path": "src/new.py", "cmd": SECRET}],
        "aggregated_output": SECRET,
    }}
    path = jsonl(project / "codex.jsonl", rows)
    capsys.readouterr()
    assert main(["tokens", "report", "--since", "2026-11-25", "--json", "--codex", str(path)]) == 0
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    task, = json.loads(out)["tasks"]
    assert task["tokens"] == 16
    assert task["files_read"] == [{"path": "src/new.py", "reads": 1}]
    assert len(task["tool_outputs"]) == 1


def test_without_a_task_window_the_report_shows_all_activity(project, capsys):
    """The first report is useful before any task was started: every event in the period, as one row."""
    claude = jsonl(project / "claude.jsonl", claude_messages())
    capsys.readouterr()
    assert main(["tokens", "report", "--since", "2026-11-25", "--json", "--claude", str(claude)]) == 0
    out, err = capsys.readouterr()
    task, = json.loads(out)["tasks"]
    assert task["task"] == "all activity" and task["tokens"] and SECRET not in out + err


def test_reports_carry_numbers_never_local_paths_or_session_ids(project, capsys):
    """AF14: file paths outside the repository, log paths and session identifiers stay out of every output."""
    claude = jsonl(project / "claude.jsonl", claude_messages())
    capsys.readouterr()
    for fmt in (["--json"], [], ["--svg"]):
        assert main(["tokens", "report", "--since", "2026-11-25", *fmt, "--claude", str(claude)]) == 0
        out, err = capsys.readouterr()
        assert str(project) not in out + err and str(claude) not in out + err
        assert "session-claude" not in out  # raw identifiers are hashed
