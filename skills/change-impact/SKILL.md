---
name: change-impact
description: Trace which results, contracts and artifacts a change may invalidate, and state what was not traced. Use after changing preprocessing, data, parameters, metrics, baselines, prompts or evaluation code.
---

# Change impact (advisory)

Start by saying in one line that you are using this skill and why.

A change to preprocessing, a dataset, a parameter, a metric, a baseline, a prompt or an evaluation script can make
earlier results stale. This skill produces an **impact note**: what may be affected, how confident the trace is, and
what was not traced. It is advisory: a careful trace, never a complete dependency analysis.

## 0. Start with the recorded runs (deterministic)
`steward diff impact` lists every result file produced under `steward run` as current, stale (a recorded input or
script changed) or changed since its run, plus paper values and displays built from stale results. It covers only
dependencies declared to `steward run`; its coverage line says how many result files have run records. Everything it
cannot see is what steps 1–3 trace. Large inputs kept outside git keep their recorded hash (R-50,
`steward storage verify`), so a change to them is visible even when the file is absent.

## 1. List the changes
```bash
git diff --name-only <base>..HEAD      # or against the commit the results were produced from
git diff --stat <base>..HEAD
```
Classify each changed file: preprocessing, dataset or split, parameter or config, metric, baseline, model or prompt,
evaluation, plotting or reporting, docs only.

## 2. Use a real dependency graph where one exists (deterministic)
If the project uses a workflow tool, ask it instead of reasoning:
- DVC: `dvc status` (stages whose dependencies changed)
- Snakemake: `snakemake --list-changes code`, `--list-changes params`, `--list-changes input`, or `--summary`
- Nextflow: what `-resume` would re-run (cache misses) for the changed processes
- Make: `make -n <target>`

Report what the tool says, with the command used.

## 3. Trace by reading (advisory)
For changes not covered by a tool:
- find references to the changed module, function, file or parameter (imports, paths, config keys);
- check benchmark contracts: does a changed file appear as a metric `implementation`, a split `ids_file`, a dataset
  `source` or an exclusion file? (`steward check contract` still checks consistency, not staleness);
- find result files, figures and tables produced downstream, and the claims or text that quote them.

## 4. Write the impact note
In the task spec's Outcome, or `development/impact/<date>-<topic>.md`:
```markdown
## Impact: <change> (<commit or diff range>)
| Artifact | How affected | Trace | Confidence |
|---|---|---|---|
| results/metrics.json | computed with the changed normalisation | dvc status | traced |
| Figure 2 | built from results/metrics.json | read plotting script | likely |
| contract:expr-clf | metric implementation changed | contract field | traced |

Not traced: <files or areas you could not follow, and why>
Stale until re-run: <list>
This is not a complete dependency analysis.
```
Confidence levels: **traced** (a tool or explicit reference shows it), **likely** (read but not confirmed by a tool),
**unknown** (could not tell). Never omit the "Not traced" line or the final sentence.

## 5. Decide with the human
- Results marked traced or likely are stale until re-run; do not quote them as current.
- If a **confirmatory** contract's metric, split, baseline or evaluation code changed after results were seen, stop
  and raise it with the human. That is an amendment, not a routine fix.
- Re-running is a run: see `run-estimate` for anything long or paid.
