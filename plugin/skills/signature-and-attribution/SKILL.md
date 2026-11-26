---
name: signature-and-attribution
description: Sign substantive work with date, harness, provider and exact model ID; unknowns stay unknown. Use when finishing a document, report, task, review or commit message.
---

# Signature and attribution

Start by saying in one line that you are using this skill and why.

A signature lets a reader know who or what produced a piece of work, under which conditions, and with which known
limits. It is a record, not an approval.

## When to sign
- Substantive documents: designs, plans, reviews, reports, analyses.
- Task specs, when you record the outcome (`development/templates/task.md` has a Signature section).
- Reviews of another agent's or person's work.
- Not needed for trivial edits (typos, formatting).

## The signature line
```
Signature: <date> · <task> · <mode> · <harness and version> · <provider> · <exact model ID> · limitations: <…>
```
| Field | Write | If you cannot see it |
|---|---|---|
| date | ISO date of the work (`2026-11-23`) | Ask, or `unknown` |
| task | Task name or spec path | `ad hoc` |
| mode | e.g. planning only, implementation, review | — |
| harness and version | The agent tool and its version, as the harness reports it | `unknown` |
| provider | The model provider, as the harness reports it | `unknown` |
| exact model ID | The model identifier exposed by the harness or API (not a marketing name) | `unknown` |
| limitations | What you did not check, could not run, or assumed | Never empty: write `none known` only if true |

Optional fields when relevant: branch and commits, evidence (test output, `steward check` summary line), session ID.

## Unknown stays unknown
- Never infer a model ID, version, duration, cost or date you cannot see. Write `unknown`.
- Do not "correct" an unknown later by guessing; correct it only with a value you can point to.
- Report what was not verified in **limitations**, not in a hedge buried in the text.

## Attribution in commits and files
- Follow the repository's own rules first (AGENTS.md, CONTRIBUTING, project instructions). Some projects require an
  AI co-author trailer; others forbid one. Do what this repository says, and ask if it says nothing.
- Never put personal details (emails, local paths, account IDs) into files that may become public, unless the human
  asks.

## A signature is not authority
Signing records who did the work. It never approves the work, grants a GO, or authorises a run or a spend. Those are
human decisions (see `task-lifecycle`).
