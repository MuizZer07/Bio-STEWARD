# Compare two pipeline runs

Run the reference and candidate side by side on the same cases. Give each a separate output path so both files remain
available, and declare each output with `steward run --output PATH`. Use the run IDs printed by `steward run`.

```sh
steward compare record classify --a REFERENCE_RUN --b CANDIDATE_RUN --key case_id
```

Each run needs a successful outcome and a recorded SHA-256 digest for the selected output. The command accepts
UTF-8 CSV and TSV files. If a run declares more than one table, use `--output-a PATH` or `--output-b PATH` to
choose the table for that run. If the tables have additional columns, use `--value COLUMN` to choose the class
column. The key and class columns must have the same names in both tables.

The record counts exact string matches across the union of keys. It lists every disagreement with both values, using
JSON `null` when a key is absent on one side. Empty class values remain empty strings. It also counts the occurrences
of each class on each side and the number of keys where both sides assigned that class. Blank or duplicate keys and
malformed rows are refused.

Records are stored under `development/comparisons/NAME/`, or under the configured `[paths] records` directory.
The file name is the SHA-256 digest of the record. Repeating the command with the same evidence produces the same
bytes at the same path. New records preserve the earlier history. Review the row-level disagreements before sharing
a comparison record.

## Check before switching on a shadow stage

Use the stage name as the comparison name and mark the stage in `steward.toml`.

```toml
[[stages]]
name = "classify"
reads = "metadata"
shadow = true
```

Run `steward check compare` before relying on the candidate. R-84 checks the latest comparison by candidate outcome
order in the run ledger, using reference outcome order to break ties. It reports missing comparisons, unreadable
records, and stale evidence. A comparison becomes stale if its runs or output bytes are missing or changed.
R-84 is advisory in the default gate. To require it for promotion, add a named gate and run
`steward check --gate promotion`.

```toml
[gates.promotion]
require = ["R-01", "R-84"]
```

## Show agreement over time

Add `"comparisons"` to `[docs] publish`, then run `steward docs build`. The page charts the percentage of all keys
that agree, grouped by comparison name and ordered by the later run's completion time. It shows historical counts
from saved records. Use R-84 to check current evidence.

---

2026-11-25 · STW-023 implementation · Codex CLI 0.171.0 · OpenAI · exact model ID unknown · local toolkit checks
