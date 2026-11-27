---
name: progress-audit
description: Audit a project's progress and usefulness when the human says "Progress Audit" - evidence from steward audit progress, ranked improvements, then an offer to plan a sprint with its signatures.
---

# Progress Audit

Run this when the human says **"Progress Audit"**. Start by saying in one line that you are using this skill and why.

## 1. Gather the evidence (read-only)
```bash
steward audit progress            # where we are, use by other projects, pending work, reach
steward timeline                  # milestones, if any
steward tidy                      # stale tasks, pages, exchange items, leftovers, memory (read-only)
STEWARD_NO_REGISTRY=1 steward check --summary   # the gates, without registering this checkout
```
Never change code, files, items or plans during the audit.

## 2. Judge, from the evidence only
Answer, each in two to four lines, naming the numbers you rely on:
1. **Where we are:** version, tag, known issues, gates.
2. **Is it used:** which projects adopted which version; what they filed; how fast filing turned into shipping; areas
   no one configures.
3. **Does it help:** defects reported against each version, especially false passes or false blocks; friction items.
4. **What is pending:** open items, waiting signatures, milestones at risk, unfinished sprint tasks.
5. **Reach:** what still stops a new adopter (the missing list), and what needs the owner's public-release decision.
6. **Needs tidying:** what `steward tidy` lists, for each project. Ask "N tasks have not moved in D days: archive,
   delete or keep?" and "M memory notes look out of date: clean them up?", and act only on the answer.

## 3. Recommend
Give three to seven improvements, ranked by reach for the effort, each with its size (S, M, L) and the evidence line it
rests on. Separate "fixes" (known issues, pending defects) from "growth" (reach, new capability). Write the audit to
`development/assessment/<date>-progress-audit.md`, signed, only if the human asks to keep it.

## 4. Offer a sprint
Ask: "Design a sprint from this?" with the options: the recommendations, the pending items, both, or none. On a yes,
draft it with `steward sprint plan ID` (or `--from exchange`, or `--milestone ID`), list each task's `needs`, and offer
**sign ahead** (spend, unsealing: a budget and an expiry at the window's end) or **sign later** (policy changes:
`steward authorize sign-pending`). Never start the sprint, sign or merge yourself.
