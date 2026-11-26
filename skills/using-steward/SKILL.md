---
name: using-steward
description: Run and read steward checks. Use in any repository with steward.toml before reporting work as ready, or when asked whether research code, contracts or records are ready.
---

# Using steward

steward is a deterministic checker: it evaluates declared rules over the repository's files, one status per
result. It never judges the science.

## When to run it
- At a session start: `steward session start`; read nothing else until the next step needs it.
- Before you say a task is ready or done.
- After editing `steward.toml`, a benchmark contract (`*.contract.toml`) or a prior-work record (`*.prior.toml`).
- When the human asks whether the repository is ready.

Start by saying in one line that you are using this skill and why.

## How to run it
```bash
steward check --summary --output .steward/report.json   # every rule, compact; full evidence saved to the file
steward check --rule R-03   # one rule, with every detail
steward check contract prior-work   # only some areas while editing; gates are NOT evaluated
steward report .steward/report.json --format md   # a full report for a human
```
- `--summary` lists every non-PASS result (never truncated), the counts and the gate: same rules, statuses and exit
  code as a full check.
- **Fetch the details** (`--rule`) for every FAIL before changing anything it names; never guess a fix from the reason.
- If the command is not found, tell the human; never emulate the checks.

## Read the whole result
Every report ends with a summary line and a gate line, for example:
```
Summary: PASS 4 · FAIL 0 · INCOMPLETE 1 · UNKNOWN 1 · NOT_APPLICABLE 1
Gate default: NOT ELIGIBLE (blocking results; 2 blocking)
```
- **The gate decides; the summary describes.** A repository is ready for a gate only when the gate line says
  ELIGIBLE. A partial check (`steward check contract`) never evaluates a gate.
- **Read all five counts**, even when the gate is ELIGIBLE: results outside the gate still matter to the human.

| Status | Meaning | What you do |
|---|---|---|
| FAIL | A declared rule is violated, or a file is malformed | Fix it first. Read every detail line. |
| INCOMPLETE | Something required is missing or marked `TBD` | Fill it in only if you know the true value; otherwise ask the human |
| UNKNOWN | The rule could not be evaluated, or a field is marked `unknown` | Report it to the human verbatim. It is never a pass. |
| NOT_APPLICABLE | The config says the rule does not apply | Nothing |
| PASS | The rule held for the declared inputs | Nothing |

Exit codes: 0 gate eligible; 1 a FAIL blocks; 2 an INCOMPLETE blocks; 3 an UNKNOWN blocks (or the gate had nothing to
evaluate); 64 usage error; 65 invalid report file; 70 internal error.

## Rules you must follow
- Never describe a NOT ELIGIBLE gate as passed, nearly passed or "fine".
- Never replace `TBD` or `unknown` with a made-up value to clear a result.
- Never edit `steward.toml` to make a rule pass without telling the human what you changed and why.
- Never mark a rule not applicable yourself; only the config does that.
- Report the summary, gate and coverage lines exactly as printed.

## Adopting, cleaning up, signing while away
[adopting.md](adopting.md) (parity first, then removal); [away-and-cleanup.md](away-and-cleanup.md).

## What the rules cover
The configuration schema is `steward.toml/0.2`. This catalogue is generated.

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
- **agents:** R-62 `agents.ledger`
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
<!-- rules:end -->

A PASS means the declared inputs are consistent with these rules, not that a result holds, a method is new or a
benchmark is unbiased. Say so when it matters.
