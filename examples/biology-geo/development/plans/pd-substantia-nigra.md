# Analysis plan: Parkinson's disease substantia nigra (GSE7621)

Written before the analysis was run.

- **Question.** Which probe sets differ between Parkinson's disease and control substantia nigra in GSE7621?
- **Data.** The GEO series matrix (MAS 5.0 signals, GPL570), 9 controls and 16 PD; sample metadata from the series.
- **Method.** log2 of the signal (floored at 1); probe sets with a missing value are left out; probe sets with a mean
  log2 signal of at least 8 in either group are tested with Welch's t-test; Benjamini-Hochberg over those tested.
- **Reported.** The number tested, the number with adjusted p < 0.05, and the 25 smallest p-values with gene symbols
  from the GPL570 annotation.
- **Known limits.** No processing batch is recorded for this series, so batch cannot be modelled; postmortem interval
  and age are not in the series matrix; MAS 5.0 signals are used as deposited.
