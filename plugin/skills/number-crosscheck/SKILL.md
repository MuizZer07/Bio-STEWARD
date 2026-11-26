---
name: number-crosscheck
description: Tie every reported number to a result file through the values registry and check relations between them. Use when adding numbers to a paper, after results change, or before sharing a draft.
---

# Number cross-check

Start by saying in one line that you are using this skill and why.

A number in a paper must come from a file that a computation produced. The values registry (`values.toml` in the
paper directory) maps each key to its source; the text uses the key (`\val{key}` in LaTeX, `{{< var key >}}` in
Quarto); a generated file supplies the value. steward recomputes every value and fails on any difference.

## 1. Register each number
```toml
schema = "steward.values/0.1"

[values.auroc_test]                      # keys: lowercase letters, digits, underscores
source  = "results/metrics.json"         # path from the repository root
pointer = "/test/auroc"                  # JSON pointer into a .json or .toml file
format  = "{:.3f}"                       # Python format; rounding happens here, once

[values.auroc_logreg]
source = "results/baselines.csv"
csv    = { row = "method=logreg", col = "auroc" }   # the row must match exactly one line

[values.n_test]
source = "benchmarks/splits/test.txt"
count  = "rows"                          # or "unique:<column>" for a CSV

[values.gain]
derive = "{auroc_test} - {auroc_logreg}" # arithmetic on other keys: + - * / ( )
format = "{:.3f}"

[[assert]]                               # relations that must hold (R-15)
expr = "{n_train} + {n_val} + {n_test} == {n_samples}"
```
- Register the number from the file the computation wrote, not from a log you read or a value you remember.
- Never type a result number into the text. If a source does not exist yet, leave the key unresolved and say so;
  steward reports it as INCOMPLETE.
- Use `derive` for percentages, differences and totals, so they follow their parts.
- Add an `[[assert]]` for every relation a reader would check: parts sum to the total, a subset is smaller than the
  set, a reported difference matches its two values (use `tol` for rounding).

## 2. Generate and use
```bash
steward paper values                 # prints key = value; any ERROR stops here
steward paper values --write         # writes values.tex (LaTeX), _variables.yml (Quarto) or values.json
```
In LaTeX, add `\input{values}` to the preamble and write `\val{auroc_test}`. An unknown key stops the build.

## 3. Check
```bash
steward check paper --summary
```
- **R-10** `paper.values`: every value recomputes from its source; the generated file is current; every key used in
  the text exists. A missing source is INCOMPLETE; a mismatch, an unknown key or a stale generated file is FAIL.
- **R-15** `paper.consistency`: every `[[assert]]` holds.
- R-10 also **lists bare numbers** in the LaTeX body (a heuristic). In final mode they block until each is
  registered or marked as a design constant with a `% literal-ok` comment on its line. Years are ignored.

## Claims that need their evidence (claim map)
For headline claims (abstract, conclusions, talk takeaways), add an entry to `development/claims.toml`: the stated
value, its tolerance, the source and JSON pointer (or a `value_key`), and the run IDs that produced it. R-40 fails a
claim with no run, from a failed run, whose source was rewritten after the run, or whose number differs. Use
`steward run --metrics results/metrics.json` so reruns can be compared with `steward diff run A B --tol ...`.

## 4. After results change
1. Re-run the computation (see `run-estimate` for long or paid runs).
2. `steward paper values` and compare with the previous values; explain every change in the task notes.
3. `steward paper values --write`, rebuild the paper, `steward check paper`.
4. Re-read every sentence that interprets a changed value: the number updates itself, the wording does not.
   Use `change-impact` for what else may be affected.

## Limits (say them when reporting)
- The registry vouches for registered numbers only. Numbers inside figure artwork are covered only if the figure
  script reads them from the same sources.
- The bare-number scan is a heuristic: it can miss numbers written as words and list harmless ones.
- A matching number says the text agrees with the file, not that the computation behind the file was right.
