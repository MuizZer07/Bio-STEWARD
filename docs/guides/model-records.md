# Record and publish model cards

Add one `[[model]]` record per model name and version in `steward.toml`. Keep a study record for each source of
training data. Every training study needs recorded input files with SHA-256 fingerprints. See the
[research records guide](research-records.md) for study setup.

Run the evaluation from the project root. Record the contract ID and split name, and pass the weights, contract
file and every split file as inputs. Use the same JSON file for `--metrics` and `--output`. The evaluation
command must write that file.

```bash
steward run --contract classifier --param split=test \
  --input models/classifier.bin --input benchmarks/classifier.contract.toml \
  --input benchmarks/splits/train.txt --input benchmarks/splits/test.txt \
  --metrics results/evaluation.json --output results/evaluation.json \
  -- python evaluate.py
```

Use the run ID from the outcome in the run ledger. Steward reads `[run].ledger` when configured and uses
`development/runs.jsonl` by default. Use the metric names from the contract and JSON pointers into the
recorded metrics. For example, `/test/auroc` selects `auroc` inside the `test` object. Quote the numbers to
preserve every digit for the exact comparison.

```toml
[[model]]
name = "Classifier"
version = "1.0"
weights = { path = "models/classifier.bin", sha256 = "<replace with 64 lowercase hex digits>" }
training_studies = ["training-study"]
contract = "benchmarks/classifier.contract.toml"
split = "test"
run = "<evaluation run ID>"
metrics = { auroc = { pointer = "/test/auroc", value = "0.913" } }
intended_use = "Compare classifiers on the project's benchmark."
known_limits = ["Evaluated on synthetic data only."]
licence = "Apache-2.0"
```

`steward check models` runs R-86. The default gate includes it. A change to the weights, contract or split files
requires a current evaluation. The check compares the card's numbers with the JSON captured in the run ledger.
The weights licence uses SPDX expression syntax. The project owner remains responsible for use and distribution
decisions.

Add `"models"` to `[docs].publish` and run `steward docs build`. The generated project index links to
`models.md`. In an existing MkDocs site with a custom navigation list, add that page under the project
section. A new site includes the link when you run `steward docs init`. The build checks the cards and applies
the site's privacy scan before writing pages. See [the project site guide](project-site.md).

<!-- 2026-11-25 · STW-022 implementation · Codex CLI 0.171.0 · OpenAI · model ID unknown · Local checks only. -->
