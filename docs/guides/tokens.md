# Track tokens per task

Mark the start and end of a task in the worktree where you do the work. Select session logs with the project's
`[tokens]` table or pass them on the command line. The commands work locally and make no network calls.

```sh
steward task start PROJ-042
steward tokens check --task PROJ-042 --claude "$CLAUDE_LOG"
steward task done PROJ-042
steward tokens report --task PROJ-042 --claude "$CLAUDE_LOG" --codex "$CODEX_LOG" --gemini "$GEMINI_LOG"
```

Set each variable to a log file for a session that worked on this project. Pass only the flags you need. Repeat a
flag for multiple files. Steward reads only the selected files and opens them read-only. A report shows unavailable
usage for unsupported formats or missing measurements. A partial result shows the observed subtotal. Keep any
session logs you want to use for later reports.

## Configure log files for a project

Put a `[tokens]` table in `steward.toml`.

```toml
[tokens]
claude = ["~/.claude/projects/project/session.jsonl"]
codex = [".steward/usage/rollout.jsonl"]
gemini = []
```

Each list accepts individual files. Absolute paths and `~` are supported, and relative paths resolve from the
project root. With no per-agent flags, `steward tokens report --format json` and `steward tokens check` use
these lists. Supplying any of `--claude`, `--codex` or `--gemini` selects only the supplied files for that
invocation. The Claude hook and status line use the transcript from their input.

| Agent | Supported local records |
| --- | --- |
| Claude Code | Session transcript JSONL in the Claude projects directory. Steward counts per-message usage and deduplicates repeated snapshots of an assistant message. |
| Codex | Rollout JSONL in the Codex sessions directory. Steward counts per-response usage from `token_count` events, ignores repeated cumulative values and flags gaps in the counters. |
| Gemini CLI | A saved chat JSON or JSONL file under the project's Gemini chats directory, with per-message `tokens` records. |

Usage is attributed by the recorded event timestamp, from the start inclusive to the end exclusive. You can reopen a
task to add another window. For concurrent tasks, give each start command its own session ID using `--session ID`.
If a record matches two task IDs, its usage is excluded from both totals. Task markers live in the worktree's local
`.steward/task-tokens.jsonl`. For task IDs without markers, Steward uses R-62 agent attempts with supported agent names
and zoned start and end timestamps. An attempt with only a start timestamp is treated as open.

## Check a budget

Add a positive integer to the header of the Markdown task file next to its ID.

```md
- **ID:** PROJ-042
- **tokens_budget:** 200000
```

Steward searches the task specs and archive globs from `[tasks]` or, by default, Markdown files under
`development/tasks/`. `steward tokens check` shows open tasks by default. Pass `--task ID` to include a closed task.
The check warns when observed tokens reach 80% and again at 100%. Input, including cache reads and writes, and
output, including recorded reasoning, count toward the budget. The warning is advisory and can appear again on
later checks.

To show the warning in Claude Code, add this example to your local settings or merge it into your existing hook
configuration. Run Claude from the worktree you want to measure, with `steward` on its command path.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "steward tokens check --claude-hook"}
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "steward tokens check --claude-statusline"
  }
}
```

Use `PostToolUse` in place of `Stop` for a check after each tool call. Each integration uses the transcript path and
session ID supplied by Claude Code. It covers that session only. For a custom status line, pass the same JSON input
to `steward tokens check --claude-statusline`. The hook returns a warning as a `systemMessage` without blocking the
session. [Claude Code hooks reference](https://code.claude.com/docs/en/hooks) · [Claude Code status line reference](https://code.claude.com/docs/en/statusline)

## Report usage and cost

`steward tokens report` shows task, agent and model totals with a terminal chart. Use `--since YYYY-MM-DD` to
count only events on or after midnight UTC on that date. Use `--json` for the report data or redirect `--svg` output
to a chart file.

```sh
steward tokens report --claude "$CLAUDE_LOG" --svg > task-tokens.svg
```

Cost is estimated using the project's exact model keys in `[spend.prices]`. Set `cache_read_per_1k` and
`cache_write_per_1k` for the rates that apply to recorded cache activity. The report shows unavailable cost when a
required count, rate or model is missing. The estimate uses the table as configured at report time. Provider invoices remain
the billing record.

The report ranks up to ten tool outputs by recorded bytes and up to ten paths by read count. JSON includes the log
path, timestamp in Unix milliseconds, session ID and any recorded file paths for each ranked output. These metrics
cover tool results and structured file-read records the adapters recognize. The same file can appear under multiple
path spellings. Output size counts UTF-8 bytes for text and compact JSON bytes for structured results. The saved
output may already be truncated. Steward returns counts, identifiers and paths. Prompt text, model replies, shell
commands and tool result contents stay out of the report.

[Claude token accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) · [Codex usage event definitions](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs) · [Gemini CLI session record definitions](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/services/chatRecordingTypes.ts)

---

2026-11-25 · STW-018 · implementation · Codex (installed CLI 0.171.0) · OpenAI · exact model ID unknown · verified with fixture logs and simulated Claude integration input.

2026-11-27 · W05 documentation · Codex CLI 0.171.0 · OpenAI · exact model ID unknown · verified with worked-example fixtures.
