# Task: figure and table check for PAPER

- **ID:** … (unique, e.g. `ABC-042`)
- **Status:** proposed
- **GO reference:** … (the decision that asks for it)
- **Branch:** … (and the base it is compared with)
- **Owner:** … · **Approver:** …
- **Reviewer:** the agent you dispatch

## Goal
Every number in the figures, tables and text of PAPER matches the records it comes from.

## Scope
- In: the paper's values registry, displays.lock, figures, tables, supplement.

## Rules for the reviewer
- Read-only. Recompute from the recorded outputs; never from the text.
- Run `steward check paper` and report what it found as well.

## Acceptance criteria
- [ ] Each mismatch with its location (file:line or figure/panel), the recorded value and the shown value.
- [ ] A list of numbers that have no record behind them.
