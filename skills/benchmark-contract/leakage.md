# Leakage the checks cannot detect: the `[leakage]` walk-through

Companion to the `benchmark-contract` skill. Ask the human each question; record their answer as
`{ status = "checked", evidence = "<file>" }` or `{ status = "not_applicable", reason = "..." }`, or `"unknown"`.

| Key | Ask |
|---|---|
| `near_duplicate` | Are there near-identical or homologous samples across splits (similar sequences, structures, cell profiles)? Evidence: a clustering output |
| `batch_confounding` | Are batch, site or plate aligned with the label? |
| `preprocessing_fit` | Was normalisation, feature selection or imputation fitted on all data before splitting? |
| `label_leakage` | Is any feature derived from the label or the outcome? |
| `test_tuning` | Were hyperparameters or the model chosen using the test split? |
| `undeclared_groups` | Is there group structure (family, lab, time point) that `group_key` does not capture? |
| `test_reuse` | Has this test set been used in many earlier comparisons? |

Record the answers the human gives; do not answer for them. A passing check means the declared design is internally
coherent and the declared checks found no violation, not that the benchmark is free of bias.
