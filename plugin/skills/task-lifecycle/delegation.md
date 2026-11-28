# Delegating subtasks to other agents

Companion to the `task-lifecycle` skill (constitution, Article VIII).

## Automatic delegation (`[delegation]`)

When `[delegation]` is configured in `steward.toml` (written by `steward agents setup`), the project's **master**
(named in `AGENTS.md`) delegates well-specified subtasks to the configured **workers** and reviews the result.

- **When to delegate:** a self-contained, specified subtask with clear file scope and checkable acceptance commands.
- **How to delegate:**
  - Brief dispatch: `steward task dispatch TASK --to auto` (tries available headless workers in order).
  - Sprint task: set `agent = "auto"` in the sprint file; `steward sprint check` shows the order it will try, and
    `steward agents status` shows who can run.
  - When a worker hits a usage limit, is signed out, is missing or fails to start its sandbox, steward records the
    ending in `.steward/agents/availability.jsonl` and hands the task to the next available worker on the same branch
    (keeping earlier commits), or follows `on_limit` (`next`, `master`, or `wait`).
- **What the master keeps:**
  - Reviewing every worker's passing task (which ends in `review` with `.steward/sprints/<sprint>/<task>.review.md`),
    then running `steward sprint accept ID TASK` or `steward sprint rework ID TASK --note "…"`.
  - Merging task branches into the base branch.
  - Anything that needs a human signature (spend, policy changes, unsealing, releases).

## Delegated work in patch mode

Use this when another agent implements part of a task in a sandbox that cannot write the repository or run its tests,
and returns a unified diff.

1. **Ask for the patch in the first dispatch,** with the task ID, the files in scope, and the acceptance criteria it
   must meet. Generated files are excluded: they are regenerated here.
2. **Check that it applies:** `git apply --check patch.diff`. A patch that does not apply cleanly goes back with the
   error.
3. **Apply it on the task branch,** regenerate any generated files, and run the project's tests and
   `steward check`.
4. **Review it** as you would your own change: every acceptance criterion against evidence.
5. **Record it** in the task's work log: who produced the patch, the commands run, their results.

A patch that was never run is never merged, however plausible it looks. Unrun patches carry wrong results that only
a run and a review catch.
