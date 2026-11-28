---
name: task-lifecycle
description: Spec, hold for a recorded GO, implement, get independent review, never self-approve. Use when starting, implementing or reviewing a task, or when a human grants or withholds a go-ahead.
---

# Task lifecycle

Start by saying in one line that you are using this skill and why.

One task, one spec, one implementer, one independent reviewer, and a human who decides. This skill keeps those roles
apart.

## 1. Write the spec first
- Copy `development/templates/task.md` to `development/tasks/<short-name>.md`.
- Fill in goal, scope (in/out) and **checkable** acceptance criteria (a command, test or file, e.g.
  "`steward check` gate default is ELIGIBLE", not "works well").
- Set status to `proposed` and show the human.

## 2. Hold until a GO is recorded
- Wait until the human says to go ahead for this task.
- Record their words verbatim in `development/DECISIONS.md` (date, quote, decision, consequences) and link it in
  **GO reference**.
- A GO covers only the spec's scope. Stop and ask before widening it; your transcription is a record, never an
  authorisation beyond what was said.

## 3. Implement
- Keep changes in scope; note anything left out.
- Run the project's tests and `steward check` (see `using-steward`).
- Fill in **Outcome**: what was done, what was not, and evidence (commits, test output, summary and gate lines).
- **Close-out rule:** a task is done only when every acceptance criterion ran and passed, or Outcome names each one
  that did not and why. Never close on a summary.

## Delegating subtasks
- **When:** the project's master (named in `[delegation]` and `AGENTS.md`) delegates any self-contained, specified
  subtask with its own checkable acceptance commands.
- **How:** `steward task dispatch TASK --to auto` for a brief, or `agent = "auto"` in a sprint; steward selects the
  first available worker and re-delegates on usage limits or sign-out.
- **What the master keeps:** reviewing worker output (`steward sprint accept` or `steward sprint rework --note …`),
  merging, and anything that needs a signature.
- Automatic delegation and patch-mode procedure: [delegation.md](delegation.md).

## Toolkit issues
Use `steward issue` for toolkit defects with generic wording (or `--from-last-error` after a fault hint). Keep project
problems in project records.

## 4. Independent review
- Reviewer is not the implementer: another agent session, model or human.
- Check each acceptance criterion against evidence and re-run checks rather than trusting pasted output.
- Record findings in the spec; implementer fixes, reviewer re-checks.

## 5. Decide
- Only the human approves a task as done, merges, or grants the next GO.
- **Archive** closed specs at a release: move them to archive, keep IDs (never reused) and links working.
- **Session end:** record decisions first, then `steward session close --decisions-logged --next …` writes bounded
  `HANDOFF.md`; commit it. Decisions belong in DECISIONS.md, never in the handoff.
- **No agent approves its own work**, a gate, a merge, a spend or a GO.

## Stale tasks and memory: name them and ask
At session start run `steward next --brief` (or `steward tidy`). If it lists stale tasks or memory, say so **for each
project** and ask before acting: "N tasks have not moved in D days: archive, delete or keep?" and "M memory notes look
out of date: clean them up?". Act only on the answer: the human runs `steward tidy --archive ID…`, or tells you which
memory entries to edit or remove. Never archive, delete or rewrite a task or a memory entry because it looks stale.

## Approvals that unlock something (signed authorizations)
Some operations need a **verified** human approval, not a quote: spending past a budget, amending a frozen protocol,
unsealing held-out data, changing policy files. The flow:
1. You (agent or human) prepare the exact payload: `steward authorize prepare ACTION --object FILE --expires ...`.
2. Show it to the human. **They** run `steward authorize sign <nonce>` in their own terminal; their key prompt
   (PIN and touch, or confirmation) is the approval.
3. Anyone verifies: `steward authorize verify <tag> --object FILE`.

Never sign on the human's behalf, never ask for their key or passphrase, and never treat an unsigned approval as
verified. If a signing key works without the human (no prompt), say so: the approval is then only a recorded decision.

## Sign your work
End the spec (and substantive documents) with a signature line:
`date · task · mode · harness and version · provider · exact model ID (or unknown) · limitations`.
Write `unknown` for anything you cannot see (for example, a model ID the harness does not expose). Never guess.

## Hold words
If the human says the task is "plan only", "no implementation", or similar, produce plans and specs only until they
say otherwise. Treat a hold as standing until it is lifted in words.

## Red flags: stop and ask
- The acceptance criteria cannot be checked.
- The work would change files outside the scope, a frozen file, or `steward.toml`.
- You are asked to review work you implemented.
- A check fails and the fix would weaken the check.
