# Task: re-verification of the VERSION fix pass

- **ID:** … (unique, e.g. `ABC-042`)
- **Status:** proposed
- **GO reference:** … (the decision that asks for it)
- **Branch:** … (and the base it is compared with)
- **Owner:** … · **Approver:** …
- **Reviewer:** the agent you dispatch (never the implementer)

## Goal
Confirm, read-only, that each finding of the last review is fixed as it asked, and that the fixes add no new defect.

## Scope
- In: `git diff REVIEWED..BRANCH`; each finding's "Regression test" paragraph against the tests the fix added.

## Rules for the reviewer
- Read-only: change no file. Each verdict names its trace (file:line).

## Acceptance criteria
- [ ] For each finding: **verified**, **partially verified** (what remains) or **not fixed**, with its trace.
- [ ] New findings, if any, in the review's format.
