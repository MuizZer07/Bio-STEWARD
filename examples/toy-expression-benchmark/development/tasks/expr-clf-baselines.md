# Task: benchmark contract and baselines for responder classification

- **Status:** GO recorded
- **GO reference:** development/DECISIONS.md, 2026-01-15 entry
- **Implementer:** agent session (fictional example)
- **Reviewer:** a second agent session (never the implementer)

## Goal
Fix the evaluation design before any model is trained: datasets, donor-level splits, baselines, metric, comparison
and threshold.

## Scope
- In: benchmark contract, split files, prior-work record, AUROC implementation.
- Out: model training (stage 2), freezing the contract (stage 3).

## Acceptance criteria
- [x] `steward check` gate default is ELIGIBLE under the confirmatory profile.
- [x] Splits are by donor: each donor's samples are in exactly one split file.
- [x] Prior-work record lists at least one closest method; novelty judgment left pending.

## Outcome
Contract `benchmarks/expr-clf.contract.toml`, splits in `benchmarks/splits/`, record in
`development/prior_work/expr-clf.prior.toml`. `steward check`: see the README walkthrough.

## Signature
2026-01-15 · example task · implementation · fictional harness · fictional provider · unknown · synthetic data only
