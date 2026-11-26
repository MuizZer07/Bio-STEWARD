---
name: negative-results
description: Record every failed or negative result with where it will be reported; never drop or relabel it. Use when an experiment, run, check or hypothesis fails or gives a null result.
---

# Negative results

Start by saying in one line that you are using this skill and why.

A failed or null result is evidence. Dropping it, re-running until something works, or relabelling a confirmatory
analysis as exploratory after the fact biases what the project reports. This skill makes sure every negative result
has a record and a destination.

## When it applies
- An experiment, benchmark or analysis does not meet its threshold, or the effect is absent or reversed.
- A run fails (crash, timeout, out of memory) and its partial outputs matter.
- A hypothesis is not supported, or a preregistered expectation is not met.
- `steward check` reports FAIL on a contract or record after work was done against it.

## Record it, before the next attempt
Add an entry to `development/negative_results.md` (create it if missing):
```markdown
## <date>: <short title>
- **What was tested:** hypothesis or question; contract or protocol reference (e.g. contract:expr-clf)
- **Run / evidence:** command, commit, output files, run IDs, logs
- **Outcome:** the numbers, with uncertainty where computed; not "it didn't work"
- **Analysis type:** exploratory | confirmatory (as declared before the run)
- **Likely causes:** what is known, what is guessed (mark guesses), literature consulted
- **Decision:** stop | amend (needs the human) | retry with a stated change
- **Destination:** where this will be reported (limitations section, supplement, internal report, issue)
- **Signature:** see signature-and-attribution
```

## Rules
- **Never delete** failed runs, logs or outputs that a record points to. Move them, if needed, and update the record.
- **Never re-run silently.** Every retry is recorded with what changed and why, so the number of attempts is visible.
- **Never relabel** a confirmatory analysis as exploratory after seeing results, and never change a contract's splits,
  metrics, baselines or thresholds to turn a negative into a positive. Raise it with the human instead.
- **Before the next attempt,** look for known causes and remedies (see `prior-work-grounding`, "After a failure"),
  and state the remedy and its basis.
- **Destination is required.** "Not reported" is a decision the human makes and records, not a default.

## What to tell the human
One short paragraph: what failed, the numbers, the likely cause (marked as a guess if it is one), the recorded
decision you recommend, and the record's path.
