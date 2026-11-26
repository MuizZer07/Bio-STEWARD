# Run a supervised sprint

A sprint is a list of tasks for a window of time (a day, an afternoon), each done by a coding agent or a command,
started one by one when you give the order. Steward supervises each through `steward run` (time and hang limits, the
run ledger), keeps each in its own branch, and decides that a task is done only when its commands pass. It never
merges, approves or signs for an agent.

## 1. Plan
```bash
steward sprint plan day1                       # from the board's open tasks
steward sprint plan day1 --from exchange       # from the open requests of other projects
steward sprint plan day1 --milestone ismb-2027 # from a milestone's open tasks
```
Edit `development/sprints/day1.toml`:

```toml
schema = "steward.sprint/0.1"
[sprint]
id = "day1"
window = { start = 2026-11-25T09:00:00+00:00, end = 2026-11-25T18:00:00+00:00 }
max_parallel = 2
dispatch = "order"          # tasks start only on `steward sprint go`; "auto" starts each when what it waits for is done

[[task]]
id = "T1"
title = "Fix the leakage check for grouped splits"
ref = "BP-110"
agent = "claude-code"        # claude-code | codex | shell
model = "opus"
prompt = "Resolve BP-110. Write the regression test first."
after = []
limits = { wall_minutes = 90, idle_minutes = 15 }
done = ["python -m pytest -q", "steward check --gate default"]
needs = ["spend"]            # signatures it will need: policy.change, spend, unseal, amend, waiver
```

`steward sprint check day1` validates it (no cycles, every task has `done` commands) and lists the signatures needed.

## 2. Signatures before you leave
For each signature the tasks need, `check` and `start` say how to handle it: **sign ahead** (spend, unsealing: a
budget and an expiry at the end of the window) or **sign later** (policy changes: they wait for
`steward authorize sign-pending`). See [Sign ahead, or sign later](signing-ahead.md).

## 3. Run
```bash
steward sprint go day1 T1          # the order for T1
steward sprint start day1          # dispatch what has its order; returns when nothing more can start
steward sprint start day1 --watch  # keep waiting for orders until the window ends or `sprint stop`
steward sprint status day1
steward sprint hold day1 T2 / skip day1 T2 --reason "…" / go day1 T2 --retry
steward sprint stop day1 [--now]   # --now also stops the running tasks (each run records its interruption)
```
Each task runs in `.steward/sprints/<sprint>/<task>` on the branch `sprint/<sprint>/<task>`. When its run ends, its
`done` commands run there: all exit 0 → **done**; otherwise **failed**, and what waits for it is **blocked**. Nothing
starts outside the window, or when it could not finish before the window ends.

## 4. Report and merge
`steward sprint report day1` writes `development/sprints/day1-report.md`: each task, its agent, its state, its
checks, and the branches waiting for your merge. Review and merge them yourself.
