# Check table data contracts

Declare each file to check in `steward.toml`. Run `steward check data` to inspect
the tables or `steward check` to evaluate the default gate, which includes R-83.

## A differential expression table

```toml
[[data.contract]]
path = "results/de.tsv"
format = "tsv"
columns = { gene = "hgnc", contrast = "text", rank = "integer" }
id_column = "gene"
hgnc_table = "references/hgnc.tsv"
p_value = "pvalue"
adjusted_p_value = "padj"
log_fold_change = "log2FoldChange"
log_base = 2
na_values = ["NA", ""]
```

Declare a separate file per contrast if each gene should occur once within a contrast.
`id_column` requires a value on every row and flags repeated values. The `columns`
map names columns and their types. Recognized types are `text`, `integer`,
`number`, `boolean` (literal `true` or `false`), `ensembl`, `entrez` and
`hgnc` and `gene_symbol`. Column names are case sensitive.

Ensembl checks gene ID syntax, including species prefixes and optional version
suffixes. Use either versioned or unversioned IDs consistently within each
declared Ensembl column. Entrez checks positive decimal IDs without leading zeros. HGNC checks
symbol syntax, including forms such as `C12orf57`, and flags date-like forms such
as `2-Sep` and `1-Mar`. Recover suspected conversions from the original export.
Declare a local `hgnc_table` TSV to catch previous or withdrawn symbols in
`hgnc` columns. It needs `symbol`, `prev_symbol` and `status` headers. Use
pipe-separated previous symbols on `Approved` rows and include any withdrawn
entries you want checked. An approved current symbol takes precedence if it
also occurs as a previous symbol. Keep the reference snapshot with the analysis.

For a species casing check, declare `columns = { gene = "gene_symbol" }` and
`study = "study-id"` in the contract. The study's `[references]` supplies
`organism` or `taxon`. The local patterns check human symbols such as `TP53` and
mouse symbols such as `Trp53`. These are spelling and casing checks.

The two p-value fields name columns whose numeric values must be in [0, 1].
When both have values on a row, the adjusted p-value must be at least the raw
p-value. An exact zero makes the check INCOMPLETE and may indicate underflow.
The check fails when every row has a valid raw and adjusted value and each
pair is numerically identical. The log fold change column requires finite
numbers. Declare its `log_base` as a positive number other than 1, or use
`log_base = "e"` for natural logarithms. Existing contracts may omit
`log_base`. The declaration records the intended scale for reviewers.

Missing-value tokens are matched exactly across the table. By default they
are an empty cell, `NA`, `N/A`, `NaN`, `nan`, `NULL` and `null`. Set
`na_values` to list the tokens expected in your file. R-83 flags each missing
token that differs from the first one encountered. Recognized tokens are
allowed in data cells and count as missing in ID columns.

## A count matrix and its sample sheet

```toml
[[data.contract]]
path = "data/counts.tsv"
id_column = "gene_id"
columns = { gene_id = "ensembl" }
raw_counts = ["S1", "S2"]
metadata_columns = ["gene_name"]

[data.contract.sample_sheet]
path = "data/samples.csv"
format = "csv"
id_column = "sample_id"
```

`raw_counts` lists the columns whose values must be nonnegative integers.
Integral values in decimal or scientific notation are accepted. When a sample
sheet is declared, R-83 checks that its sample IDs are unique and match the
matrix column names in the same order. Matrix sample columns are all headers
other than the matrix `id_column` and any declared `metadata_columns`. Matching
uses exact spelling, including case.

Files are UTF-8 with a header row. A byte order mark is accepted. The default
format for both files is `tsv`. Use `format = "csv"` for comma-separated files
or `format = "series_matrix"` for a tab-separated GEO series matrix. The
latter checks the single table between the `!series_matrix_table_begin` and
`!series_matrix_table_end` markers.

Findings give the source path, the physical line on which the record starts,
and the column position, starting at 1. A location is absent when no matching
row or column exists, for example if a file or a declared header is missing.
Files are streamed. Memory grows with the unique IDs and reported findings.

---

2026-11-27 · B01 implementation · Codex, version unknown · OpenAI · exact model ID unknown · checks use local data and declared references.

2026-11-25 · STW-012 implementation · Codex Work, version unknown · OpenAI · exact model ID unknown · local syntax and declared checks.
