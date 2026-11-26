# Toy expression benchmark (synthetic example)

A fictional study used to demonstrate steward end to end. Everything here is synthetic:
- the data come from `make_data.py` (seed 20261123): 40 donors × 3 samples, 200 genes, 2 batches, a per-donor
  "responder" label;
- the prior-work entries are fictional and point at the reserved `example.org` domain.

The example grows with each toolkit version. Each stage adds one part of the research-engineering workflow.

| Stage | Toolkit version | Walkthrough |
|---|---|---|
| 1 | v0.1 | Plan the benchmark: contract, prior-work record, `steward check`, `steward report` (below) |
| 1b | v0.2 (PaperKit) | `paper/`: spec, venue profile and a LaTeX preprint of the design; `steward check --final` |
| 1c | v0.3 (PresentationKit) | `talks/progress-update/`: a targeted progress update sharing the paper's values and table |
| 2 | later | Run the baselines under `steward run` with resource limits and run records |
| 3 | later | Freeze the contract and splits; seal the test split; amendments need a signed authorization |
| 4 | later | Claim map for the AUROC claim; release checks; change impact after a preprocessing change |
| 5 | later | Benchmark checks: a leaky variant with a donor in two splits is detected |

## Stage 1: plan and check
```bash
cd examples/toy-expression-benchmark
python make_data.py                 # regenerates data/ and splits; prints the dataset SHA-256 used in the contract
steward check                       # every rule; gate "default"
steward check --format json --output .steward/report.json
steward report .steward/report.json --format md
```

The repository was created with `steward init --profile confirmatory`. The confirmatory profile requires:
- a confirmatory benchmark contract (R-04);
- a prior-work record with a closest method (R-06).

**Files:**

| File | What |
|---|---|
| `steward.toml` | Configuration (profile confirmatory) |
| `benchmarks/expr-clf.contract.toml` | Datasets (with SHA-256), donor-level splits, two baselines, AUROC, paired bootstrap, threshold |
| `benchmarks/splits/*.txt` | Sample IDs per split; each donor's three samples sit in one split only |
| `development/prior_work/expr-clf.prior.toml` | Closest method, baseline, comparison, a claimed difference; novelty left `pending` for the human |
| `development/tasks/expr-clf-baselines.md` | The task spec, with its GO reference |
| `development/DECISIONS.md` | The recorded GO (verbatim quote) |
| `analysis/metrics.py` | The AUROC implementation the contract points to |

**Try the statuses:**
- Replace the threshold `value` with `"TBD"`: R-02 and R-03 report INCOMPLETE, and the gate is not eligible
  (exit 2).
- Set `alpha = "unknown"`: UNKNOWN (exit 3).
- Point `metrics.primary` at an undefined metric: FAIL (exit 1).

**What stage 1 does not check:**
- whether the split files really separate donors (stage 5);
- whether the dataset hash matches the file (stage 3);
- anything about the scientific merit of the comparison (never).

## Stage 1b: the paper (PaperKit)
```bash
cd paper && SOURCE_DATE_EPOCH=1768435200 FORCE_SOURCE_DATE=1 latexmk -pdf main.tex && cd ..   # byte-stable rebuild
steward check paper --summary      # R-08 spec and venue profile, R-09 placeholders, R-12 build log
steward check --final --summary    # submission mode: comments scanned, overfull boxes block
```

**What it shows:**
- `paper/spec.toml` fixes a contribution at strength `explores`, because there are no results yet;
- it lists what must never be claimed, and every limitation.

**Every number in `paper/main.tex` comes from `paper/values.toml`** (`steward paper values --write` regenerates
`paper/values.tex`):
- donor and sample counts come from `data/samples.csv` and the split files;
- bootstrap settings and the threshold come from the contract.

Two assertions check that the splits add up to the totals. Change a split file and `steward check` reports the paper
stale (R-10).

**What it does not check yet:**
- figure provenance;
- venue limits on the built PDF.

## Stage 1c: the talk (PresentationKit)
```bash
steward talk plan progress-update             # stage (confirmed), pattern, claim ceiling, slide budget
cd talks/progress-update && SOURCE_DATE_EPOCH=1768435200 FORCE_SOURCE_DATE=1 latexmk -pdf slides.tex && cd ../..
steward check talk --summary                  # R-21 … R-29
```

**What it shows:**
- the talk takes its numbers and its table from the paper (one source of truth);
- the "Decisions we need" slide shows the plan's unresolved decision;
- the one claim (`implemented`) stays within the development-stage ceiling.
