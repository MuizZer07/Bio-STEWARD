# Worked example: the toy expression benchmark

The repository ships a synthetic benchmark, committed fully built, at `examples/toy-expression-benchmark`. It has a
contract, splits, a prior-work record, a LaTeX preprint and a Beamer talk.

```bash
steward check --final --summary --repo examples/toy-expression-benchmark
```

| Step | File | What the toolkit checks |
|---|---|---|
| 1. Plan | `benchmarks/expr-clf.contract.toml` | the design passes its schema and is internally consistent (R-02, R-03); a confirmatory profile has one (R-04) |
| 2. Prior work | `development/prior_work/expr-clf.prior.toml` | the record and its links (R-05, R-41) |
| 3. Splits | `benchmarks/splits/*.txt`, `data/samples.csv` | no ID or donor (group) overlap between splits (R-45) |
| 4. Results | `results/` | the matrix is complete, thresholds met, baselines compared as declared (R-47, R-48) |
| 5. Paper | `paper/` | every number from `paper/values.toml`, figures locked, venue limits, citations (R-08 – R-15) |
| 6. Talk | `talks/progress-update/` | the same numbers, the claim ceiling, limitations, slide checks (R-21 – R-29) |

Try a break: edit a number in `paper/main.tex` by hand, then run the check again. R-10 fails and names the line.
Ask your agent to fix it: it should change the value at its source, not the text.

`tools/example_setup.sh` regenerates the data, values, displays and (with LaTeX) the paper and talk.
