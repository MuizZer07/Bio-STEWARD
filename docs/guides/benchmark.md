# Plan a benchmark before results exist

1. `steward init --for benchmark` writes the template; copy it:
   `mkdir -p benchmarks && cp development/templates/benchmark.contract.toml benchmarks/my.contract.toml`.
2. Declare datasets (with hashes), splits (ID files, a group key, a time key), baselines, metrics, the comparison,
   thresholds, and how each leakage type is handled.
3. `steward check benchmark --summary`, and `steward benchmark splits benchmarks/my.contract.toml` for counts and
   overlaps.
4. For a confirmatory test, set `minimum_units` and run `steward benchmark power` on development effects (R-67).
5. Freeze the design before the held-out data is used (`steward freeze design …`; see
   [freeze, seal and approve](integrity.md)).

## The smallest split check that catches a leaked donor

Three samples, two donors; `S2` and `S3` come from the same donor, one in train and one in test:

```bash
mkdir -p benchmarks data
printf 'id,donor_id\nS1,D1\nS2,D2\nS3,D2\n' > data/samples.csv
printf 'S1\nS2\n' > benchmarks/train.txt
printf 'S3\n' > benchmarks/test.txt
```

In the contract's `[splits]`: `group_key = "donor_id"`, `metadata = "data/samples.csv"`, `id_column = "id"`, and the
two sets' `ids_file = "benchmarks/train.txt"` and `"benchmarks/test.txt"`. Then `steward benchmark splits
benchmarks/my.contract.toml` reports one shared donor (`D2`) and exits 1; move `S2` to the test list (so donor `D2`
is only in test) and it passes.

Ask your agent: *"Use the benchmark-contract skill."* It drafts the contract with you; only you decide it is final.
