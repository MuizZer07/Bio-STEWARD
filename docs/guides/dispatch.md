# Dispatch a task to another agent

A review, a re-verification or an implementation can go to another agent: one that did not write the change. `steward
task brief` writes the prompt; `steward task dispatch` also runs it, the way each agent needs when nobody is at the
keyboard, and keeps the report.

```bash
steward task template review --output development/tasks/T-007.md     # fill it in
steward task dispatch development/tasks/T-007.md --to codex           # a read-only review
steward task dispatch development/tasks/T-007.md --to antigravity     # the same, with Gemini in Antigravity
steward task dispatch development/tasks/T-007.md --to antigravity --inline   # when its tools are refused
```

The report goes to `.steward/dispatch/DATE-ID-AGENT.md` (or `--output`). Read it, then record it in
`development/assessment/`. `--dry-run` prints what would run.

## What a dispatch takes care of

| Pitfall | What happens without it | What `dispatch` does |
|---|---|---|
| The reviewer reads your working tree | it reviews uncommitted edits, or changes them | a review runs in a clean, detached checkout of the current commit, removed afterwards; a file it changed is reported |
| A sandbox that cannot reach `.git` | in a linked worktree `.git` points back to your repository, outside the agent's sandbox, so `git diff`, `git log` and the tests cannot run | a review's checkout is a local clone in `.steward/dispatch/review-<ID>/` with its own `.git`: every branch and tag, no remote, objects copied (no hard links), no hooks; your repository is not written |
| Codex outside a git repository | `Not inside a trusted directory and --skip-git-repo-check was not specified`; nothing runs | `--skip-git-repo-check`, `-s read-only` (a review) or `-s workspace-write` (`--implement`), stdin closed |
| Antigravity's headless mode | it cannot ask for permission, so it denies every shell command not allowed beforehand, and may print nothing | `--sandbox` and a session-only allow-list of a review's read-only commands (git's reading subcommands such as `git log` and `git diff`, `grep`, `cat`, `python -m pytest`; no `rm`, `cp`, `env`, bare `python` or git as a whole), with the sprint's default deny list |
| A run that still prints nothing | an empty report, read as "no findings" | refused, with the advice to use `--inline` |
| `--dangerously-skip-permissions` | every tool approved for an agent you are not watching | never used |
| Template text left in the task | the agent gets `VERSION` and `…` | refused until the task is filled in |

## `--inline`: no tools at all

With `--inline`, the documents the task names (each `git diff A..B` range in it, and each repository file in
backticks) are put in the prompt, and the agent is told it has no tools and must answer in text only. It works with
any agent and any permission setting; what does not fit (about 200,000 characters) is listed in the prompt, so the
agent says what it could not check. Name the diff and the files in the task's Scope, for example:

```markdown
## Scope
- In: `git diff v1.2.0..HEAD -- src tests`; `CHANGELOG.md`.
```

## Implementing

`--implement` gives the agent a writable checkout of its own (Codex: `-s workspace-write`); nothing is committed,
pushed or merged. Review its changes there, and bring them over yourself.

Other agents (Claude, Gemini CLI, any chat window): `steward task brief TASK --for claude|gemini|generic` and paste
it.
