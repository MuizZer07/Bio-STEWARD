# Recipes

Each recipe is something you can ask your agent to do; the commands show what it runs.

=== "Reanalyse a GEO study"

    1. `steward init --for reanalysis` (adds `[studies]` and `[research]` to steward.toml)
    2. `steward study new gse5281 --title "GSE5281 reanalysis" --kind reanalysis`
    3. `steward data fetch GEO:GSE5281 --study gse5281` (downloads and records URL, size and sha256), or, for a file you
       already have, `steward study add-input gse5281 --source GEO --accession GSE5281 --file data/…`
    4. Record the genome and annotation release, the sample sheet (`[samples]`) and tools in the study record, then
       `steward study fingerprint gse5281 --write`.
    5. Run the analysis under `steward run`; add its results to the study record.
    6. `steward check`: R-75 tells you when an input changes and which papers it makes stale. See it end to end:
       `steward example biology my-example`.

=== "Benchmark without leakage"

    1. `steward init --for benchmark`, then copy the contract template:
       `mkdir -p benchmarks && cp development/templates/benchmark.contract.toml benchmarks/my.contract.toml`.
    2. Declare datasets, splits (with the group: donor, patient, study), baselines and metrics **before** any result.
    3. `steward check contract benchmark`: shared IDs, groups and time order are checked.
    4. For language models, add `[llm_eval]` with each model's training cutoff: R-78 reports contaminated test cases.

=== "Let an agent draft the paper"

    1. `steward init --for paper` (adds `[paper.main]` and `paper/values.toml`); every number goes through the values
       registry.
    2. The agent writes; `steward paper values --write` fills the numbers from result files.
    3. Optional: `citations = "citations.toml"` and `steward paper citations main --fetch`.
    4. `steward check --final --gate submission` before you submit.

=== "Review the literature"

    1. `steward research new review lr-cell-types --title "Cell-type deconvolution methods"`
    2. Ask the agent to fill it with the research-review skill, or dispatch it:
       `steward task template literature-review`, then `steward task brief FILE --for gemini`.
    3. `steward research list`: what is stale, what lacks a nearest prior work, what is undecided.

=== "Get past a dead end"

    1. `steward research new dead-end de-2b --title "Pilot results negative"`
    2. List the negative results; search how others got past the same wall; lay out options with evidence.
    3. Decide (stop, pivot, reframe, continue); the record keeps what the decision rested on.

=== "Dispatch a review to another agent"

    1. `steward task template review --output development/tasks/R-001.md` and fill it in.
    2. `steward task brief development/tasks/R-001.md --for codex --output brief.md`
    3. Hand it over; record the result in `development/assessment/`.
