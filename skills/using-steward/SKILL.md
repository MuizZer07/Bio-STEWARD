---
name: using-steward
description: Run and read steward checks. Use in any repository with steward.toml before reporting work as ready, or when asked whether research code, contracts or records are ready.
---

# Using steward

steward evaluates declared rules deterministically, one status per result; it never judges the science.

## When to run it
- At session start: `steward session start`; read nothing else until needed.
- Before reporting a task ready or done.
- After editing `steward.toml`, `*.contract.toml` or `*.prior.toml`.
- When asked whether the repository is ready.

Start by saying in one line that you are using this skill and why.

## How to run it
```bash
steward check --summary --output .steward/report.json   # compact; full evidence saved
steward check --rule R-03   # one rule, full detail
steward check contract prior-work   # partial; gates not evaluated
steward report .steward/report.json --format md   # human report
```
- `--summary` lists non-PASS results, counts and gates, keeping statuses and exit codes.
- **Read each FAIL with `--rule` before editing.** Never guess fixes.
- Never emulate checks; tell the human when steward is missing.

## Read the whole result
Reports end with summary and gate lines:
```
Summary: PASS 4 · FAIL 0 · INCOMPLETE 1 · UNKNOWN 1 · NOT_APPLICABLE 1
Gate default: NOT ELIGIBLE (blocking results; 2 blocking)
```
- **The gate decides; the summary describes.** Ready only when ELIGIBLE. Partial checks never evaluate a gate.
- **Read all five counts**, even when ELIGIBLE: non-gating results still matter.

| Status | Meaning | What you do |
|---|---|---|
| FAIL | Rule violated or file malformed | Fix first; read every detail |
| INCOMPLETE | Required field missing or `TBD` | Fill if known; else ask the human |
| UNKNOWN | Unchecked or `unknown` | Report verbatim; never a pass |
| NOT_APPLICABLE | Config excludes rule | Nothing |
| PASS | Declared inputs held | Nothing |

Exit codes: 0 eligible; 1 FAIL; 2 INCOMPLETE; 3 UNKNOWN or empty gate; 64 usage; 65 invalid report; 70 internal.

## Rules you must follow
- Never call NOT ELIGIBLE passed, nearly passed or "fine".
- Never replace `TBD` or `unknown` with invented values.
- Never edit `steward.toml` to pass a rule without telling the human why.
- Never mark rules not applicable; only config does.
- Report summary, gate and coverage lines verbatim.
- File toolkit defects with `steward issue`; keep project issues local.

## Delegating subtasks
With `[delegation]` in `steward.toml`, the project's **master** (named in `AGENTS.md`) delegates self-contained,
specified subtasks that have their own checkable acceptance commands. Use `steward task dispatch TASK --to auto` for a
brief, or `agent = "auto"` in a sprint; `steward agents status` shows who can run. The master always keeps review
(`steward sprint accept` / `rework`), merging, and anything that needs a signature.

## Adopting, cleaning up, signing while away
[adopting.md](adopting.md) (parity first, then removal); [away-and-cleanup.md](away-and-cleanup.md).

## What the rules cover
Config schema: `steward.toml/0.2`. Generated catalogue:

<!-- rules:begin -->
- **config:** R-01 `config.valid`
- **contract:** R-02 `contract.valid` · R-03 `contract.consistent` · R-04 `contract.required`
- **prior-work:** R-05 `prior_work.valid` · R-06 `prior_work.required`
- **privacy:** R-07 `privacy.denylist`
- **paper:** R-08 `paper.spec_valid` · R-09 `paper.placeholders` · R-10 `paper.values` · R-11 `paper.displays` · R-12 `paper.build` · R-13 `paper.venue` · R-14 `paper.citations` · R-15 `paper.consistency` · R-77 `paper.citations_verified` · R-85 `paper.data_availability`
- **talk:** R-21 `talk.plan_valid` · R-22 `talk.stage_confirmed` · R-23 `talk.claim_ceiling` · R-24 `talk.values` · R-25 `talk.limitations` · R-26 `talk.structure` · R-27 `talk.figures` · R-28 `talk.visual` · R-29 `talk.language`
- **run:** R-31 `ledger.integrity` · R-32 `run.records`
- **policy:** R-33 `policy.baseline`
- **spend:** R-34 `spend.ledger`
- **integrity:** R-35 `integrity.frozen` · R-36 `integrity.datasets` · R-37 `integrity.sealed_use` · R-38 `integrity.decisions` · R-39 `integrity.contract_frozen`
- **evidence:** R-40 `evidence.claims` · R-41 `prior_work.links`
- **release:** R-42 `release.integrity` · R-43 `release.review` · R-44 `release.fingerprint` · R-87 `release.stranger_test`
- **benchmark:** R-45 `benchmark.splits` · R-46 `benchmark.datasets` · R-47 `benchmark.results` · R-48 `benchmark.comparison` · R-49 `benchmark.leakage` · R-67 `benchmark.power` · R-78 `benchmark.llm_eval`
- **storage:** R-50 `storage.artifacts`
- **governance:** R-51 `governance.constitution` · R-53 `exchange.items` · R-54 `exchange.inbox`
- **boundary:** R-56 `boundary.imports`
- **tasks:** R-57 `tasks.board`
- **changelog:** R-58 `changelog.unreleased`
- **branches:** R-59 `branches.model`
- **skills:** R-60 `skills.copies`
- **repro:** R-52 `repro.current`
- **session:** R-55 `session.handoff`
- **files:** R-61 `files.conflict_markers`
- **agents:** R-62 `agents.ledger` · R-89 `delegation.installed`
- **stages:** R-68 `stages.records`
- **frozen:** R-63 `frozen.sets`
- **dependencies:** R-66 `dependencies.parity`
- **containers:** R-64 `containers.context` · R-65 `containers.compose`
- **docs:** R-69 `docs.current`
- **milestones:** R-70 `milestones.valid`
- **sprints:** R-71 `sprint.valid` · R-72 `sprint.closed`
- **pins:** R-73 `pins.records` · R-74 `pins.retirement`
- **studies:** R-75 `studies.records`
- **research:** R-76 `research.records`
- **licence:** R-79 `licence.declared` · R-80 `licence.dependencies` · R-81 `licence.code` · R-82 `licence.provenance`
- **data:** R-83 `data.contracts`
- **compare:** R-84 `compare.shadow`
- **models:** R-86 `model.records`
- **tidy:** R-88 `tidy.stale`
<!-- rules:end -->

A PASS means the declared inputs are consistent with these rules, not that a result holds, a method is new or a
benchmark is unbiased. Say so when it matters.
