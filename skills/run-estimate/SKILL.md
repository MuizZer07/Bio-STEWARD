---
name: run-estimate
description: State count, duration, memory, disk and cost before a run, with the basis; compare with actuals after. Use before long, heavy or paid computations.
---

# Run estimate

Start by saying in one line that you are using this skill and why.

Before a computation that is long, memory-heavy, disk-heavy or paid, state what it will cost and on what basis, so
the human can decide before resources are spent. An estimate is not a promise; say how it was obtained.

## When it applies
Any of:
- expected wall time over about 10 minutes, or unknown;
- many items (samples, files, prompts, API calls);
- large memory or disk use (more than a quarter of the machine's free memory or disk), or unknown;
- any paid call (LLM APIs, cloud compute, paid databases).

## Estimate from a measurement, not a guess
1. **Count** the items from the actual inputs (`wc -l`, a manifest, a query), not from memory.
2. **Pilot** on a small, representative subset (for example 1-5% or 10 items) and measure time, peak memory
   (`/usr/bin/time -v` on Linux, `/usr/bin/time -l` on macOS) and output size.
3. **Scale** to the full count. State whether scaling is linear and why; flag steps that are not.
4. **Paid calls:** calls × tokens or units per call (from the pilot) × the published price, with the price source and
   date. If a price or usage figure is not available, write `unknown`; do not invent one.

## State it like this
```
Run estimate: <what> on <N items>
- basis: pilot of <n> items on <machine>; <measured per-item time>, <peak memory>, <output per item>
- duration: ~<total> (assumes linear scaling; <exceptions>)
- memory: peak ~<value>; disk: ~<value> written to <path>
- paid calls: <count> × <unit> × <price, source, date> = ~<cost>, or unknown
- risks: <long tail items, rate limits, retries>
```
Ask the human before starting when the duration is long, a resource limit is close, or anything is paid. Running paid
work needs their explicit go-ahead for that run and budget.

## Run it under `steward run`
```bash
steward run --wall 3600 --mem 12000 --hang 600 --estimate-min 45 --slot heavy \
  --input data/cohort.h5ad --output results/metrics.json --param lr=1e-3 --seed 7 -- python train.py
```
The process tree is stopped at the first limit (exit 124). Inputs, parameters, seed, git state, environment, peak
memory and output hashes go to the run ledger (`development/runs.jsonl`), and your estimate is recorded next to the
actual duration. Limits from `[run]` in `steward.toml` are defaults that the command line can only tighten. Processes
started outside `steward run`, or that detach from its tree, are not supervised.

## After the run
Compare estimate with actual (duration, peak memory, disk, cost) in the task's Outcome or the run notes. A large
miss is information for the next estimate; record it, do not hide it.

## Do not
- Start a long or paid run "to see how long it takes". Pilot first.
- Present a single number without its basis.
- Drop the comparison after the run because the estimate was wrong.
