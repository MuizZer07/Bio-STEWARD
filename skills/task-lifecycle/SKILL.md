---
name: task-lifecycle
description: Spec, hold for a recorded GO, implement, get independent review, never self-approve. Use when starting, implementing or reviewing a task, or when a human grants or withholds a go-ahead.
---

# Task lifecycle

Start by saying in one line that you are using this skill and why.

One task, one spec, one implementer, one independent reviewer, and a human who decides. This skill keeps those roles
apart.

## 1. Write the spec first
- Copy `development/templates/task.md` (created by `steward init`) to `development/tasks/<short-name>.md`.
- Fill in the goal, the scope (in and out) and **checkable** acceptance criteria: a command, a test or a file that
  must exist. "Works well" is not checkable; "`steward check` gate default is ELIGIBLE" is.
- Set the status to `proposed` and show the spec to the human.

## 2. Hold until a GO is recorded
- Do not start implementing until the human says to go ahead for this task.
- Record the human's words verbatim in `development/DECISIONS.md` (date, quote, decision, consequences) and put the
  link in the spec's **GO reference**.
- A GO covers the scope written in the spec, nothing more. If the work needs more than that, stop and ask.
- Your transcription of the human's words is a record, not an authorisation for anything beyond what they said.

## 3. Implement
- Keep changes inside the scope. Note anything you deliberately left out.
- Run the project's tests and `steward check` (see the `using-steward` skill).
- Fill in **Outcome**: what was done, what was not, the evidence (commits, test output, the `steward check` summary
  line and gate line).
- **Close-out rule:** a task is done only when every acceptance criterion ran and passed, or the Outcome names each
  one that did not, and why. Never close it on a summary.
- Work delegated to another agent comes back as a patch: apply, run and review it before it counts. The procedure is
  in [delegation.md](delegation.md).

## 4. Independent review
- The reviewer is not the implementer: another agent session, another model, or a human.
- The reviewer checks each acceptance criterion against evidence, not against the implementer's summary, and
  re-runs the checks rather than trusting pasted output.
- Findings are recorded in the spec. The implementer fixes them; the reviewer re-checks.

## 5. Decide
- Only the human approves the task as done, merges, or grants the next GO.
- **Archive** closed specs at a release: move them to the archive folder, keep their IDs (never reused), and keep
  links working.
- **When the session ends,** record the decisions first, then `steward session close --decisions-logged --next …`
  writes the bounded `HANDOFF.md`; commit it. Decisions go to DECISIONS.md, never into the handoff.
- **No agent approves its own work**, and no agent approves a gate, a merge, a spend or a GO.

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
