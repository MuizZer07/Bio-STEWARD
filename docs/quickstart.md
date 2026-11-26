# Quick start (core)

Five minutes in a fresh folder. Each command below is run by the test suite exactly as written.

```bash
steward init
steward check --summary
steward explain R-07
steward check --summary --all
```

- `steward init` writes `steward.toml`, a decisions log, the task template and an AGENTS.md block. It never
  overwrites anything.
- `steward check --summary` evaluates every rule. Most are NOT_APPLICABLE until you add their table; they are named on
  one folded line. The gate line says whether the repository is ready.
- Expected gate: `Gate default: ELIGIBLE`. A fresh project has nothing that blocks; each kit you add brings its own
  rules into the gate.
- `steward explain R-07` says what a rule checks, why, its result codes and fixes, and what a PASS does not mean.

## Next
1. Tell your agent: *"Run the using-steward skill."*
2. Add the kit you need: a benchmark contract ([guide](guides/benchmark.md)), a paper ([quick start](quickstart-paper.md)),
   or run limits and records (`[run]` in `steward.toml`).
3. In CI, run `steward check --gate default` ([CI guide](ci.md)).
