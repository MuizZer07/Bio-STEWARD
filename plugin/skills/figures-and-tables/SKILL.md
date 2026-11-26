---
name: figures-and-tables
description: Build every figure and table with a declared script from declared inputs, record the build, and keep displays cited and current. Use when making or changing a figure or table.
---

# Figures and tables

Start by saying in one line that you are using this skill and why.

A figure or table is evidence only if anyone can rebuild it from data. Each display is declared in the paper's
`displays.toml` with the script that builds it, the files it reads and the label the text cites; a lock records the
build, so a later change to the data or the script shows the display as stale.

## 1. Declare the display
```toml
schema = "steward.displays/0.1"
[displays.auroc_by_method]
kind   = "figure"                          # figure | table
output = "paper/figures/auroc.pdf"         # paths from the repository root
script = "analysis/plot_auroc.py"
inputs = ["results/metrics.json"]          # every file the script reads
params = { seed = 1 }                      # settings that change the output
label  = "fig:auroc"                       # the label the text cites
```

## 2. Build it with a script, then record
- Write the script with the project's own tools (matplotlib, seaborn, ggplot2, pgfplots, TikZ). steward does not
  plot.
- The script reads only the declared inputs and writes only the output. Never edit the output by hand.
- Numbers drawn in the artwork come from the same result files as the text (see `number-crosscheck`).
- After building: `steward paper displays --record` (writes `displays.lock` with script, input and output hashes).

## 3. Use it in the paper
- Include it (`\includegraphics{figures/auroc}` or `\input{tables/auroc}`) inside a figure or table environment with
  `\label{fig:auroc}`, and cite it (`Figure~\ref{fig:auroc}`) where its claim is made.
- One message per display; legible at print size (about 6.5 pt minimum); colour-blind-safe palette; no number shown
  twice across text, figure and table; no internal names or versions in artwork.

## 4. Check
`steward check paper --summary` runs **R-11** `paper.displays`:
- FAIL: the script or an input changed since the output was recorded (stale), a script is missing, the manifest is
  invalid, or (final mode) a figure is included with no manifest entry;
- INCOMPLETE: an output or input is missing, a display is not cited or not included, the build is not recorded, or
  (draft mode) a figure is unregistered.

After data or code changes: rebuild, inspect the new display, `--record`, re-read the sentences that describe it.

## Limits
The lock shows what was declared at build time; it cannot show that the script produced the file. Recording without
rebuilding defeats it: rebuild first.
