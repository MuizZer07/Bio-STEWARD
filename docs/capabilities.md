# What Bio-STEWARD offers

Generated from the toolkit itself (`python tools/build_capabilities.py`); the counts are the installed ones.

## Agents it works with

| Agent | How it learns the checks | How it gets a task |
|---|---|---|
| Claude Code | the plugin (`plugin/`) or `steward init --skills .claude/skills`; `CLAUDE.md` points to `AGENTS.md` | `steward task brief --for claude` |
| Codex | `steward init --skills .agents/skills`; reads `AGENTS.md` | `steward task brief --for codex` (a self-contained prompt for `codex exec`) |
| Gemini (CLI, Antigravity) | `steward init --skills .agents/skills`; reads `AGENTS.md` | `steward task brief --for gemini` |
| Any agent that reads `AGENTS.md` | `steward init` writes the steward block into `AGENTS.md` | `steward task brief --for generic` |
| CI | the [GitHub Action](../action.yml) and [pre-commit hooks](../.pre-commit-hooks.yaml) | — |
| MCP clients | `steward mcp`: a read-only server over the checks and records | — |

## Agent Skills (24, in 6 kits)

Install only the kits you use: `steward init --skills DIR --kits core,paper`. Each kit has a word budget, because agents preload every installed skill's description.

### core (12)

| Skill | Use it when |
|---|---|
| `using-steward` | Run and read steward checks. Use in any repository with steward.toml before reporting work as ready, or when asked whether research code, contracts or records are ready. |
| `task-lifecycle` | Spec, hold for a recorded GO, implement, get independent review, never self-approve. Use when starting, implementing or reviewing a task, or when a human grants or withholds a go-ahead. |
| `benchmark-contract` | Fix datasets, splits, baselines, metrics, comparison and thresholds before results are seen. Use when designing an evaluation, comparing methods with baselines, or planning a confirmatory analysis. |
| `prior-work-grounding` | Record closest prior methods, comparisons, claimed differences and distinguishing experiments; never judge novelty. Use when claiming a contribution, choosing baselines, writing related work, or after a failed experiment. |
| `signature-and-attribution` | Sign substantive work with date, harness, provider and exact model ID; unknowns stay unknown. Use when finishing a document, report, task, review or commit message. |
| `negative-results` | Record every failed or negative result with where it will be reported; never drop or relabel it. Use when an experiment, run, check or hypothesis fails or gives a null result. |
| `run-estimate` | State count, duration, memory, disk and cost before a run, with the basis; compare with actuals after. Use before long, heavy or paid computations. |
| `no-paid-tests` | Keep tests free of live paid calls to LLM APIs or cloud services; use recorded fixtures. Use when writing or running tests or verification scripts for code calling paid services. |
| `change-impact` | Trace which results, contracts and artifacts a change may invalidate, and state what was not traced. Use after changing preprocessing, data, parameters, metrics, baselines, prompts or evaluation code. |
| `red-team-review` | Run and record an independent adversarial review before a release, with findings, regression tests and re-verification kept separate from fixing. Use before any public release or when asked to red-team a repository. |
| `container-release` | Ship container images after auditing build contexts and compose files, then record and verify the bundle. Use before shipping images. |
| `dependency-upgrade` | Upgrade a pinned dependency with parity harnesses, a record and approval before the pins move. Use before changing a pin. |

### paper (6)

| Skill | Use it when |
|---|---|
| `paper-kit` | Set up and run a paper project (preprint, conference, journal, thesis) in LaTeX with a spec, venue profile and checks. Use when starting or restructuring a paper, or choosing a venue. |
| `submission-readiness` | Prepare a preprint, conference or journal submission with final-mode checks, the venue checklist and a clean package. Use when a paper is close to submission or a deadline. |
| `number-crosscheck` | Tie every reported number to a result file through the values registry and check relations between them. Use when adding numbers to a paper, after results change, or before sharing a draft. |
| `figures-and-tables` | Build every figure and table with a declared script from declared inputs, record the build, and keep displays cited and current. Use when making or changing a figure or table. |
| `manuscript-drafting` | Draft or revise paper sections from the approved spec, with registered numbers, cited displays, matched claim strength and stated limitations. Use when writing or revising any manuscript section. |
| `manuscript-review` | Review a draft with deterministic checks first, then advisory scientific, methodological and editorial comments kept apart; also structure responses to peer review. Use when asked to review a draft or answer reviewers. |

### talk (3)

| Skill | Use it when |
|---|---|
| `presentation-planning` | Plan a talk from its confirmed research stage, purpose, audience, duration and feedback intent before building slides. Use when preparing any presentation, poster or demo. |
| `presentation-building` | Build slides in Beamer from an approved talk plan, with numbers and figures from the shared evidence and the presenter's style preferences. Use when creating or revising slides. |
| `presentation-review` | Review a talk for stage-consistent claims, overstatement and understatement, audience fit and feedback intent, keeping objective check results apart from advice. Use before presenting or when asked to review slides. |

### manage (1)

| Skill | Use it when |
|---|---|
| `progress-audit` | Audit a project's progress and usefulness when the human says "Progress Audit" - evidence from steward audit progress, ranked improvements, then an offer to plan a sprint with its signatures. |

### research (1)

| Skill | Use it when |
|---|---|
| `research-review` | Keep literature reviews, novelty maps, gap and flaw lists and dead-end reviews as checkable records. Use for a literature review, a novelty or overlap check, gaps or flaws, or negative results. |

### licence (1)

| Skill | Use it when |
|---|---|
| `licence-compliance` | Check licences before adding a dependency, copying or porting code, or bundling data. Use when a task adds a package, vendors or translates code, or the project moves towards release. |

## Commands by what you do

| Group | Commands |
|---|---|
| Start | `init` · `example` · `check` · `explain` · `report` · `interface` · `skills` · `next` |
| Plan | `plans` · `benchmark` · `study` · `research` · `timeline` · `sprint` |
| Run | `run` · `diff` · `compare` · `shards` · `stage` · `tokens` |
| Data and records | `data` · `freeze` · `amend` · `seal` · `unseal` · `integrity` · `frozen` · `storage` · `pins` · `licence` · `decisions` |
| Papers and talks | `paper` · `talk` · `docs` |
| Approvals | `authorize` · `spend` |
| Agents and tasks | `task (template` · `brief` · `dispatch)` · `agents` · `session` · `audit` · `tidy` · `notifications` |
| Projects | `exchange` · `issue` · `issues` · `constitution` · `channel` |
| Releases | `release` · `upgrade` · `stranger-test` · `repro` · `hooks` · `ledger` · `mcp` |

Every command: `steward COMMAND --help`; the full list: [the command reference](reference/commands.md).

## Rules (83, by area)

| Area | Rules |
|---|---|
| config | R-01 `config.valid` |
| contract | R-02 `contract.valid` · R-03 `contract.consistent` · R-04 `contract.required` |
| prior-work | R-05 `prior_work.valid` · R-06 `prior_work.required` |
| privacy | R-07 `privacy.denylist` |
| paper | R-08 `paper.spec_valid` · R-09 `paper.placeholders` · R-10 `paper.values` · R-11 `paper.displays` · R-12 `paper.build` · R-13 `paper.venue` · R-14 `paper.citations` · R-15 `paper.consistency` · R-77 `paper.citations_verified` · R-85 `paper.data_availability` |
| talk | R-21 `talk.plan_valid` · R-22 `talk.stage_confirmed` · R-23 `talk.claim_ceiling` · R-24 `talk.values` · R-25 `talk.limitations` · R-26 `talk.structure` · R-27 `talk.figures` · R-28 `talk.visual` · R-29 `talk.language` |
| run | R-31 `ledger.integrity` · R-32 `run.records` |
| policy | R-33 `policy.baseline` |
| spend | R-34 `spend.ledger` |
| integrity | R-35 `integrity.frozen` · R-36 `integrity.datasets` · R-37 `integrity.sealed_use` · R-38 `integrity.decisions` · R-39 `integrity.contract_frozen` |
| evidence | R-40 `evidence.claims` · R-41 `prior_work.links` |
| release | R-42 `release.integrity` · R-43 `release.review` · R-44 `release.fingerprint` · R-87 `release.stranger_test` |
| benchmark | R-02 `contract.valid` · R-03 `contract.consistent` · R-45 `benchmark.splits` · R-46 `benchmark.datasets` · R-47 `benchmark.results` · R-48 `benchmark.comparison` · R-49 `benchmark.leakage` · R-67 `benchmark.power` · R-78 `benchmark.llm_eval` |
| storage | R-50 `storage.artifacts` |
| governance | R-51 `governance.constitution` · R-53 `exchange.items` · R-54 `exchange.inbox` |
| boundary | R-56 `boundary.imports` |
| tasks | R-57 `tasks.board` |
| changelog | R-58 `changelog.unreleased` |
| branches | R-59 `branches.model` |
| skills | R-60 `skills.copies` |
| repro | R-52 `repro.current` |
| session | R-55 `session.handoff` |
| files | R-61 `files.conflict_markers` |
| agents | R-62 `agents.ledger` · R-89 `delegation.installed` |
| stages | R-68 `stages.records` |
| frozen | R-63 `frozen.sets` |
| dependencies | R-66 `dependencies.parity` |
| containers | R-64 `containers.context` · R-65 `containers.compose` |
| docs | R-69 `docs.current` |
| milestones | R-70 `milestones.valid` |
| sprints | R-71 `sprint.valid` · R-72 `sprint.closed` |
| pins | R-73 `pins.records` · R-74 `pins.retirement` |
| studies | R-75 `studies.records` · R-85 `paper.data_availability` |
| research | R-76 `research.records` |
| licence | R-79 `licence.declared` · R-80 `licence.dependencies` · R-81 `licence.code` · R-82 `licence.provenance` |
| data | R-83 `data.contracts` |
| compare | R-84 `compare.shadow` |
| models | R-86 `model.records` |
| tidy | R-88 `tidy.stale` |

Advisory (reported, not in the default gate): R-55, R-58, R-70, R-71, R-72, R-74, R-76, R-82, R-84, R-87, R-88, R-89. What each rule checks: `steward explain R-xx`, or [the rule reference](reference/rules.md).
