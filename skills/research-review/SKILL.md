---
name: research-review
description: Keep literature reviews, novelty maps, gap and flaw lists and dead-end reviews as checkable records. Use for a literature review, a novelty or overlap check, gaps or flaws, or negative results.
---

# Research review

Start by saying in one line that you are using this skill and why.

Research direction is decided in conversation and then lost. This skill keeps it as records under `[research]`
(`steward research new KIND ID --title "…"`), checked by R-76 and shown on the project's documentation site. The
human decides; the record shows what the decision rested on.

## Which record
| The request | Kind | What it holds |
|---|---|---|
| "do a literature review", "what is known about …" | `review` | question, date searched, method (databases, queries, inclusion), every source with its identifier and why |
| "is this novel", "does it overlap our other paper" | `novelty` | per contribution: the nearest prior work (others' and the group's own), how it differs |
| "find flaws", "research gaps", "limitations", "threats" | `gaps` | each gap, flaw, limitation or threat; open, addressed or accepted, with the decision |
| "the results are negative", "we hit a dead end" | `dead-end` | the negative results, the options with their evidence, the decision (stop, pivot, reframe, continue) |

## How
1. **Search, then cite only what you opened.** Every source gets a stable identifier (`doi:`, `pmid:`, `arxiv:`,
   `url:`). Never cite from memory; mark preprints and self-reported results. Prefer recent work; say where evidence
   disagrees.
2. **Look for the counter-example.** For novelty, the strongest prior work against the claim, including the group's
   own papers (`own_overlap`). Give an assessment; novelty is the human's call (as in `prior-work-grounding`).
3. **Dead ends are reviewed, not re-run.** List what failed and why it might have, search for how others got past the
   same wall, and lay out options with evidence. Do not start a new run until the human picks one.
4. **Record, then check:** fill the record from its template and run `steward check research`. A review older than
   `stale_days` is due again; R-76 says so.
5. **Link it:** `relates` names the study IDs or papers it informs; the decision goes to the decisions log when it
   changes scope.

To hand a review to another agent: `steward task template literature-review` (or `novelty-check`), fill it in, and
`steward task brief FILE --for codex|gemini|claude`.

Never present a search as complete, a contribution as novel, or a dead end as final; say what was not searched.
