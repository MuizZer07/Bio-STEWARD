# Task: independent pre-release review of VERSION

- **ID:** … (unique, e.g. `ABC-042`)
- **Status:** proposed
- **GO reference:** … (the decision that asks for it)
- **Branch:** … (and the base it is compared with)
- **Owner:** … · **Approver:** …
- **Reviewer:** the agent you dispatch (never the implementer)

## Goal
An independent, read-only defensive review of everything VERSION changes, before it is tagged.

## Scope
- In: `git diff BASE..BRANCH -- src tests docs CHANGELOG.md`, and the items it ships with their own Verify sections.
- Out: code unchanged since BASE, unless a new path calls it.

## What to look for
- False passes (a check passes when it should not) and false blocks.
- Privacy: anything private printed or published.
- Whether each item's Verify scenarios are actually tested.
- Documentation claims the code does not back.

## Rules for the reviewer
- Read-only: change no file. Tests may be run.
- No speculative findings: each names its trace (file:line).

## Acceptance criteria
- [ ] Written to `development/assessment/DATE-review-VERSION-SHA.md`, opening with a one-paragraph **Verdict**.
- [ ] Each finding as `### X<n> — High | Medium | Low · title` with **Trace.**, **Observed.** and **Regression test.**
- [ ] A "Not found" section: what was checked and found sound.
