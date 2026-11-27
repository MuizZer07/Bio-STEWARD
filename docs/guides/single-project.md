# Single-project governance

One repository, one owner, one or more agents. What it gives you:

- **Decisions recorded where they are made:** the decisions log is append-only (R-38); several logs are possible
  (a programme log and one per study).
- **Tasks with IDs that never collide:** task specs and a board (R-57); the `task-lifecycle` skill.
- **Runs you can trace:** `steward run` with limits, slots and a record for every run (R-31, R-32).
- **Branch and changelog discipline:** R-59 and R-58 (advisory unless a gate requires it).
- **Hooks that block what the gate blocks:** `steward hooks install` (or `--chain` beside your own hooks).
- **Session continuity:** `steward session close` writes one short handoff; the next session starts with
  `steward session start` instead of a transcript.
- **Private overlays:** `steward.local.toml` can add requirements on a private branch, never remove them.

## Read decisions and open questions

Run `steward decisions` for a summary or `steward decisions --format json` for `steward.decisions/0.1`: the dated
decisions from the logs and the open questions from the project index and the session handoff, each with its file
and line. See [Read decisions and open questions](decisions.md).
