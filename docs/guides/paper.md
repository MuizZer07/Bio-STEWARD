# Keep paper numbers true to results

- Numbers live in `paper/values.toml`, each with its result file and pointer; the manuscript uses `\val{name}`.
- Figures and tables are locked to their sources (`steward paper displays --record`, R-11).
- `steward check --final` adds the submission checks: no placeholders, the venue's limits, resolved citations.
- When a result changes, `steward diff impact` lists what in the paper is now stale.

Ask your agent: *"Use the number-crosscheck skill before I send the draft."*
