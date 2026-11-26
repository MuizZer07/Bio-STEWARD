---
title: "A provenance-checked reanalysis of Parkinson's disease substantia nigra expression (GSE7621)"
---

## Abstract

We reanalyse a public microarray series of postmortem substantia nigra ({{< var n_samples >}} samples:
{{< var n_control >}} controls and {{< var n_pd >}} with Parkinson's disease) to show a reanalysis whose inputs,
samples, method and numbers are each checked. Of {{< var n_tested >}} expressed probe sets, {{< var n_significant >}}
differ at a Benjamini-Hochberg adjusted p below 0.05.

## Methods

The GEO series matrix was fetched with `steward data fetch GEO:GSE7621`, which recorded its URL, size and sha256.
Sample metadata were taken from the series and checked against the matrix columns. The plan, written before the
analysis, is in `development/plans/pd-substantia-nigra.md`: log2 MAS 5.0 signals, Welch's t-test on probe sets
expressed in either group, Benjamini-Hochberg adjustment.

## Results

Of {{< var n_tested >}} probe sets tested, {{< var n_significant >}} have an adjusted p below 0.05
(`results/de.tsv`; the 25 smallest p-values with gene symbols are in `results/top_genes.tsv`).

## Limitations

No processing batch is recorded for the series, so batch could not be modelled. Postmortem interval and age are
not in the series matrix. MAS 5.0 signals are used as deposited. This reproduces a workflow on published data
(Lesnick et al. 2007, PMID 17571925); it is not a new finding.

## Data availability

See the statement in `paper/data-availability.md`.

## Competing interests

None.
