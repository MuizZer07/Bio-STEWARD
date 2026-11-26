---
name: benchmark-contract
description: Fix datasets, splits, baselines, metrics, comparison and thresholds before results are seen. Use when designing an evaluation, comparing methods with baselines, or planning a confirmatory analysis.
---

# Benchmark contract

Start by saying in one line that you are using this skill and why.

A benchmark contract (`*.contract.toml`, schema `steward.contract/0.1`) states in advance what will be compared, on
which data, by which metric, and what counts as success. Writing it before seeing outcomes makes later changes
visible and keeps exploratory and confirmatory work apart.

## Start from the template
```bash
cp development/templates/benchmark.contract.toml benchmarks/<name>.contract.toml
steward check contract
```
The default glob is `benchmarks/**/*.contract.toml`. The template's `TBD` fields are reported as INCOMPLETE until
filled.

## Fill it in, section by section
| Section | Write | Watch for |
|---|---|---|
| `analysis` | `exploratory` or `confirmatory`, decided **before** outcomes are seen | Never switch a contract to exploratory to avoid confirmatory rules |
| `[[datasets]]` | ID, version, SHA-256, source (accession, URL or internal path) | Compute the hash from the file (`shasum -a 256 <file>`); if you cannot, write `unknown` |
| `[splits]` | `group_key`: the unit that must not cross splits (donor, patient, subject, sequence cluster); `time_key` if time ordering matters; `metadata`: a CSV with one row per sample (`id_column`, the group and time columns); `temporal = true` if train must precede dev / validation and test | Samples from one donor or patient in two splits is leakage. Say `"none"` only if samples are truly independent. Without `metadata`, groups and times cannot be checked |
| `[[splits.sets]]` | One entry per split with role `train`, `dev`, `validation` or `test`, and the file of sample IDs | At least one `test` split. Split files are evidence: they must exist |
| `[[baselines]]` | Name, reference (`doi:…`, `pmid:…`, `arxiv:…`, `url:https://…` or `internal`), version | Include a simple baseline (majority class, mean predictor) as well as the strongest published method you can run |
| `[metrics]` | `primary` plus `[[metrics.defs]]` with a definition and the path of the code that computes it | One primary metric, chosen before results. Secondary metrics are descriptive |
| `[comparison]` | Method (e.g. `paired_bootstrap_ci`), seed, resamples, alpha; `output`: the file the procedure writes | Confirmatory contracts must specify all of these. Produce `output` with `steward run --input <each split file> --seed ... --param resamples=...` |
| `[[thresholds]]` | Metric, comparator, value, and `absolute` or `baseline:<name>` | Confirmatory contracts need at least one |
| `[exclusions]` | Rules for excluding samples, and the resulting excluded-ID file | Exclusions decided after seeing outcomes must be reported as such |
| `[outputs]` | Result files the evaluation must produce | Checked for existence from a later version |
| `[results]` | `file`: a matrix `{split: {method: {metric: number}}}`, methods being the baselines and `candidate`; `splits` (default: the test splits) | Every metric × method × required split needs a number. Thresholds are reported, never gating: accepting a result is the human's decision |
| `[leakage]` | One entry per undetectable type (below): `{ status = "checked", evidence = "<file>" }` or `{ status = "not_applicable", reason = "..." }` | A declaration is recorded, not verified. Write `unknown` rather than claim a check you did not do |

## Honest placeholders
- `TBD`: not decided yet. Reported INCOMPLETE.
- `unknown`: cannot be known now (for example, a dataset hash you cannot compute). Reported UNKNOWN.
- Never invent a hash, version, accession or reference to clear a result. Ask the human instead.

## Check it
```bash
steward check contract
```
R-02 checks the schema; R-03 checks cross-references (primary metric defined, thresholds refer to defined metrics and
baselines, split names unique, a test split exists, referenced files exist, confirmatory settings specified); R-04
requires a confirmatory contract under the confirmatory profile.

```bash
steward check benchmark                       # R-02, R-03 and R-45 - R-49
steward benchmark splits benchmarks/x.contract.toml     # counts, ID and group overlaps, which checks ran
steward benchmark results benchmarks/x.contract.toml    # missing cells, thresholds met or not met
```
- **R-45:** sample IDs repeated or shared across splits; with `metadata`, groups shared across splits and (with
  `temporal = true`) time order.
- **R-46:** a dataset whose `source` is a repository file must match its `sha256`.
- **R-47:** the results matrix is complete.
- **R-48:** the comparison output came from a recorded run on the current split files.
- **R-49:** every undetectable leakage type is declared (required for confirmatory contracts).

## Leakage the checks cannot detect
Seven types cannot be detected from sample IDs and metadata. Walk the human through each `[leakage]` key with
[leakage.md](leakage.md) (load it when filling that table). Record the answers the human gives; do not answer for
them. A passing check means the declared design is coherent and the declared checks found no violation, not that the
benchmark is free of bias.

## Freeze before the first run; seal the held-out data
A confirmatory contract is frozen **before** its first run (R-39 fails a later freeze), and held-out data is sealed.
The commands, the human's signed approvals and amendments are in [freezing.md](freezing.md); load it when freezing.

## After the contract is agreed
Do not change splits, metrics, baselines or thresholds of a confirmatory contract after results are seen. If a change
is needed, propose it to the human with the reason, and record their decision verbatim in `development/DECISIONS.md`.
