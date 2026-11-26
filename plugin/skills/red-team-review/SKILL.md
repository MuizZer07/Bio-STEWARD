---
name: red-team-review
description: Run and record an independent adversarial review before a release, with findings, regression tests and re-verification kept separate from fixing. Use before any public release or when asked to red-team a repository.
---

# Red-team review

Start by saying in one line that you are using this skill and why.

Before a public release, someone who did not build the work tries to break it: false passes, bypasses, leaked
private data, broken clean-checkout setups, overstated claims. Findings are recorded, fixed with a regression test,
and re-verified by the reviewer. Strongly recommended before every public release; enforced when `[release]
review_required = true` (rule R-43).

## Roles (never combined)
- **Reviewer:** finds and later re-verifies. Does not fix what they found, and does not close findings.
- **Implementer:** fixes each confirmed finding: a failing test first, then the fix. The test is never removed.
- **Human owner:** sets severity, accepts known limits (a signed `waive` for high or critical ones) and closes
  findings.

## 1. Brief the reviewer
Give the threat model and the documented limits (what is out of coverage), the revision to review (a commit or tag),
and where to write: `development/assessment/<date>-<topic>.md`. Ask for findings with ID, severity, reproduction,
affected file:line and a suggested regression test, and a verdict per earlier finding when re-verifying.
Review a clean export of the revision (`git archive <rev> | tar -x -C <dir>`), not a working tree.

## 2. Record in `development/assessment/findings.toml`
```toml
schema = "steward.findings/0.1"
[[reviews]]
id = "2026-11-23-redteam"
reviewer = "an independent reviewer"
implementer = "the team that built it"
revision = "<commit reviewed>"
file = "2026-11-23-redteam.md"

[[findings]]
id = "A1"
review = "2026-11-23-redteam"
severity = "high"            # critical | high | medium | low | info
title = "Repeatability can pass without evidence"
status = "fixed"             # open | confirmed | fixed | verified | accepted | superseded
test = "tests/test_evidence.py::test_A1_failed_runs_are_never_repeatable"
verified_by = ""             # the reviewer, after re-verification
```

## 3. Respond and fix
Acknowledge each finding by ID (confirmed, needs evidence, superseded). Fix in order of severity, each with its
regression test. Mark `fixed`, never `verified`: only the reviewer verifies.

## 4. Before the release
Ask the reviewer to re-verify at the release commit (a docs-only change after the review is still covered). Then:
```bash
steward check release --summary     # R-42 release integrity, R-43 release review
```
R-43 blocks (when required) on: no review of this commit, reviewer equal to implementer, an open or confirmed high
or critical finding, a fixed one not yet re-verified, a verified one without a regression test, or one accepted
without a signed waiver. When not required, every report still carries the recommendation.

A recorded review shows that a review happened and how findings were closed; it cannot show the review was thorough.
