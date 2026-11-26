# Freezing a contract and sealing held-out data

Companion to the `benchmark-contract` skill. Needs `[integrity]` in `steward.toml`.

**Bind every split, not only the test split.** A frozen snapshot covers only the files it lists. Changing an
unlisted train or validation split would leave the snapshot hash unchanged. List every split file of the contract
(`[[splits.sets]] ids_file`) as a cohort, and list the sample metadata, if declared, as a file:

```bash
steward freeze design --files benchmarks/x.contract.toml data/samples.csv \
  --cohort benchmarks/splits/train.txt benchmarks/splits/validation.txt benchmarks/splits/test.txt \
  --params configs/confirmatory.toml --contract x --dry-run     # prints the snapshot hash to approve
# the human approves and signs (in their own terminal):
steward authorize prepare freeze.confirmatory --object sha256:... --expires 2026-12-31T00:00:00Z \
  --summary "Freeze design x before its first run"
steward authorize sign <nonce>
steward freeze design ... --authorization steward/auth/<nonce> --decision "<DECISIONS.md heading>"
steward seal heldout                     # declared in development/datasets.toml; set its role to "sealed"
steward run --contract x --input ... -- python evaluate.py      # refuses sealed inputs (exit 77)
```

- **Before the first run:** a confirmatory contract is frozen before its first run (R-39 fails a later freeze).
- **Amendments:** after freezing, changes are amendments. `steward amend propose design --reason ...` records the
  diff, and only the human's signed `amend` authorization applies it.
- **Unsealing:** held-out data is unsealed only with a signed `unseal`, after which it is `spent`.
- **What sealing covers:** sealing checks the inputs declared to `steward run`. Truly confidential holdouts also need
  a separate execution identity or access-controlled storage.
