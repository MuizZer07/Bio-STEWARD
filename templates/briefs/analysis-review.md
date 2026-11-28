# Task: independent review of ANALYSIS

- **ID:** … (unique, e.g. `AR-001`)
- **Status:** proposed
- **GO reference:** … (the `development/DECISIONS.md` entry giving the human go-ahead for this task)
- **Branch:** … (and the base commit or tag, if comparing changes)
- **Owner:** … · **Approver:** …
- **Reviewer:** the agent you dispatch (never the implementer)

## Goal
An independent, read-only review of the ANALYSIS scripts, notebooks, intermediate tables and figures, checking that inputs, transformations, statistics and reported numbers agree.

## Scope
- In: scripts (`analysis/`, `src/`), notebooks, pipelines, sample sheets, result tables, figures and study records for ANALYSIS.
- Out: raw input files and unrelated analyses, unless a script reads them.

## What to look for
- Data and identifier hygiene: gene-symbol date mangling, retired or mixed-version IDs, duplicate or missing samples, and sample-order mismatches.
- Experimental design and leakage: batch/condition confounding, donor or group overlap across splits, and unrecorded filtering or threshold changes.
- Statistics and reporting: raw versus adjusted p-values, exact-zero p-value underflow, log-base mixups, and hardcoded numbers that drift from result files or figures.
- Execution and provenance: unpinned seeds or environments, hidden state in notebooks (out-of-order cells), and outputs that do not match the generating scripts.

## Rules for the reviewer
- Read-only: change no file. Existing checks (`steward check --summary`) and read-only scripts may be run.
- No speculative findings: every finding names its exact trace (`file:line`, notebook cell, or table row and column).

## Acceptance criteria
- [ ] Written to `development/assessment/DATE-analysis-review-ANALYSIS.md`, opening with a one-paragraph **Verdict**.
- [ ] Each finding as `### X<n> — High | Medium | Low · title` with **Trace.**, **Observed.** and **Check or fix.**
- [ ] A "Not found" section: which scripts, notebooks, tables and figures were inspected and showed no discrepancy.
