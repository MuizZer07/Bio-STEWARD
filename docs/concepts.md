# Concepts

## Statuses
| Status | Meaning |
|---|---|
| PASS | the rule held for the declared inputs |
| FAIL | a declared rule is violated, or a file is malformed |
| INCOMPLETE | something required is missing or marked `TBD` |
| UNKNOWN | the rule could not be evaluated; never a pass |
| NOT_APPLICABLE | the configuration says the rule does not apply |

## Gates
A gate lists the rules it requires. It is ELIGIBLE only when none of them is FAIL, INCOMPLETE or UNKNOWN, and when at
least `min_evaluated` of them were evaluated. The exit code is the gate's. A partial check (`steward check paper`)
never evaluates a gate.

## What a PASS does not mean
A PASS means your files agree with the rules you declared. It does not establish that a result holds, that a method
is new, or that a benchmark is unbiased. `steward explain R-xx` states, for each rule, what its PASS does not mean.

## Trust and approvals
Policy files and approvals are judged against a baseline pinned outside the repository (`steward authorize pin`, or
CI secrets). An agent can edit the working tree; it cannot move the pin or sign as you.

## Limits
Checks cover what goes through `steward`. A process that detaches from `steward run`, a paid call made directly to a
provider, or a commit with hooks skipped is outside its view; branch protection and CI stay the enforcement point.

## Words you will meet early

| Word | Meaning |
|---|---|
| **Profile** | `exploratory` (the default: rules report, few demand) or `confirmatory` (a benchmark contract and a prior-work record are required, and an independent review is recommended before a release). Set in `steward.toml`. |
| **Gate** | A named list of rules that must not FAIL, be INCOMPLETE or UNKNOWN. NOT_APPLICABLE never blocks, so a new project's gate is ELIGIBLE: nothing is broken, nothing is verified yet. |
| **GO reference** | In a task file: the decision (in `development/DECISIONS.md`) that asked for the work, so every task traces back to someone's go-ahead. |
| **Advisory rule** | Reported, but not in the default gate; a named gate may require it. |
| **Stranger test** | An agent that has never seen the project tries to get value from a release in an hour; see [the guide](guides/stranger-test.md). |
