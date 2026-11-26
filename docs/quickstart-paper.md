# Quick start: a paper whose numbers come from result files

```bash
steward init --for paper
steward check paper --summary
steward check --summary
```

`steward init --for paper` adds `[paper.main]` and the `paper/` files, also to an existing `steward.toml`.

Expected gate: `Gate default: NOT ELIGIBLE` until the paper is filled in. The blocking results name what is left:
R-08 (the `TBD` fields of `paper/spec.toml` and `paper/venue.toml`), R-09 (the placeholders in the draft), R-12 (build
the paper once) and R-13 (the venue limits). An area check (`steward check paper`) lists results only; the gate is
evaluated by a full `steward check`.

1. Put each reported number in `paper/values.toml` (written by `steward init`) with the file it comes from:

    ```toml
    schema = "steward.values/0.1"

    [values.auroc]
    source  = "results/metrics.json"     # relative to the repository root
    pointer = "/test/auroc"               # RFC 6901, into JSON or TOML; or csv = { row = "gene=TP53", col = "lfc" }
    format  = "{:.3f}"                    # or count = "rows" / "unique:COLUMN" for a table; derive = "{a} - {b}"
    ```

2. Write `\val{name}` in the LaTeX source instead of the number.
3. `steward paper values --write` regenerates the macros; R-10 fails when a number in the text has no source.
4. Before submission: `steward check --final --summary` (placeholders, venue limits, citations, consistency).

Ask your agent: *"Use the paper-kit skill to wire the results into the manuscript."*
