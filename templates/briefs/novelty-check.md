# Task: novelty check: CONTRIBUTION

- **ID:** … (unique, e.g. `ABC-042`)
- **Status:** proposed
- **GO reference:** … (the decision that asks for it)
- **Branch:** … (and the base it is compared with)
- **Owner:** … · **Approver:** …
- **Reviewer:** the agent you dispatch

## Goal
For each contribution this work claims, the nearest prior work (by others and by this group) and how it differs.

## Scope
- In: the contribution list in PAPER-OR-PLAN; the literature and software it competes with; this group's own papers.

## Rules for the reviewer
- Look for the strongest counter-example, not for support. Name overlap with this group's own work as `own_overlap`.
- Cite only what you opened.

## Acceptance criteria
- [ ] A `steward.research/1` record of kind `novelty`: per contribution, `nearest` (source ids), `difference`, and
  `own_overlap`.
- [ ] Per contribution, your assessment for the human, who decides: apparently new, incremental, or already
  done (by whom), with the evidence. Novelty is never decided by the agent.
