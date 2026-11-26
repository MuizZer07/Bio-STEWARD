# Worked example: a public GEO series, checked end to end

A real, small public dataset taken through the toolkit: GSE7621, postmortem substantia nigra from 9 controls and
16 people with Parkinson's disease (Affymetrix HG-U133 Plus 2.0; Lesnick et al. 2007, PMID 17571925). GEO places no
restrictions on the use of its data; cite the original study when you reuse it.

This reproduces a workflow on published data. It is not a new finding.

```bash
steward example biology my-example && cd my-example
steward check --summary                # passes: every recorded file, sample, table and number checks out
python analysis/de.py                  # re-runs the analysis (standard library only); the outputs do not change
```

| Step | What it shows | Rule |
|---|---|---|
| `steward data fetch GEO:GSE7621 --study pd-substantia-nigra` | the download recorded with URL, size and sha256 | R-75 |
| `data/samples.tsv` and `[samples]` in the study | every matrix column has a sample row with the required fields, and the reverse | R-75 |
| `[references]` in the study | organism, taxon, annotation and the probe-to-gene table with its version, fingerprinted | R-75 |
| `[[data.contract]]` in `steward.toml` | p-values in [0, 1], adjusted ≥ raw, finite fold changes, gene symbols not turned into dates | R-83 |
| `paper/values.toml` | every number in the text read from `results/summary.toml` | R-10 |
| `paper/data-availability.md` | the statement names every accession the study used | R-85 |

## Break it on purpose

Each change below fails the check the way a real mistake would. Undo it with `git checkout -- .` (or copy the
example again).

| Change | What `steward check --summary` says |
|---|---|
| Open `results/top_genes.tsv` in a spreadsheet and save it, or replace a symbol with `7-Sep` | FAIL R-83: a gene symbol that looks like a date, with its row and column; FAIL R-75: a recorded result changed |
| Change `control` to `Control` on one row of `data/samples.tsv` | FAIL R-75: a value not allowed for `condition`, and the sample sheet no longer matches its fingerprint |
| Delete both mentions of `GSE7621` (the accession and the link) from `paper/data-availability.md` | INCOMPLETE R-85: the statement does not name GSE7621 |
| Change `EXPRESSED = 8.0` to `7.0` in `analysis/de.py` and run it | FAIL R-75: the results changed; FAIL R-10: the paper's numbers no longer match their source |
| Replace one byte of the series matrix | FAIL R-75: the input differs from the sha256 recorded at fetch |

## Files

- `data/raw/GSE7621/GSE7621_series_matrix.txt.gz`: the GEO series matrix, as fetched.
- `data/samples.tsv`: sample metadata taken from the series (no processing batch is recorded for it).
- `data/probe-to-gene.tsv`: the GPL570 annotation (GEO, 2016-08-09), restricted to the probes tested.
- `development/plans/pd-substantia-nigra.md`: the analysis plan, written before the analysis and fingerprinted.
- `development/studies/pd-substantia-nigra.toml`: the study record that ties all of it together.
- `analysis/de.py`, `results/`: the analysis and its outputs.
- `paper/`: a short Markdown preprint whose numbers come from `results/summary.toml`.
