"""Differential expression, Parkinson's disease against controls, in GSE7621 (substantia nigra, GPL570).

Standard library only, so the example runs anywhere Python does. MAS 5.0 signals (as deposited) are log2-transformed
(floored at 1); probes with a missing value in any sample are left out; probes expressed in either group (mean log2 signal >= 8) are tested with Welch's t-test, and
p-values are adjusted by Benjamini-Hochberg over the probes tested. This is a worked example of keeping a
reanalysis honest, not a new finding: the paper the data come from (PMID 17571925) is the reference.

    python analysis/de.py      # writes results/de.tsv, results/top_genes.tsv and results/summary.toml
"""

from __future__ import annotations

import csv
import gzip
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "data/raw/GSE7621/GSE7621_series_matrix.txt.gz"
SAMPLES = ROOT / "data/samples.tsv"
MAPPING = ROOT / "data/probe-to-gene.tsv"
EXPRESSED = 8.0   # mean log2 MAS5 signal in either group
TOP = 25


def read_matrix(path: Path) -> tuple[list[str], dict[str, list[float]]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("!series_matrix_table_begin"):
                break
        rows = csv.reader(f, delimiter="\t")
        head = next(rows)[1:]
        data, missing = {}, 0
        for r in rows:
            if not r or r[0].startswith("!"):
                continue
            if any(v.strip().lower() in ("", "null", "na") for v in r[1:]):
                missing += 1  # a probe with a missing value in any sample is not tested
                continue
            data[r[0]] = [math.log2(max(float(v), 1.0)) for v in r[1:]]
    print(f"{missing} probes with a missing value were left out")
    return head, data


def betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (Numerical Recipes, 6.4)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 3e-14:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * betacf(a, b, x) / a
    return 1 - math.exp(lbt) * betacf(b, a, 1 - x) / b


def welch(x: list[float], y: list[float]) -> tuple[float, float]:
    """(t, two-sided p) of Welch's t-test, y against x."""
    nx, ny = len(x), len(y)
    mx, my = sum(x) / nx, sum(y) / ny
    vx = sum((v - mx) ** 2 for v in x) / (nx - 1)
    vy = sum((v - my) ** 2 for v in y) / (ny - 1)
    se2 = vx / nx + vy / ny
    if se2 == 0:
        return 0.0, 1.0
    t = (my - mx) / math.sqrt(se2)
    df = se2 ** 2 / ((vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1))
    return t, betai(df / 2, 0.5, df / (df + t * t))


def bh(p: list[float]) -> list[float]:
    order = sorted(range(len(p)), key=lambda i: p[i])
    out, prev = [0.0] * len(p), 1.0
    for rank in range(len(p), 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * len(p) / rank)
        out[i] = prev
    return out


def main() -> None:
    head, data = read_matrix(MATRIX)
    with open(SAMPLES, encoding="utf-8") as f:
        sheet = {r["sample"]: r for r in csv.DictReader(f, delimiter="\t")}
    ctrl = [i for i, s in enumerate(head) if sheet[s]["condition"] == "control"]
    pd = [i for i, s in enumerate(head) if sheet[s]["condition"] == "parkinsons_disease"]
    rows = []
    for probe, v in sorted(data.items()):
        a, b = [v[i] for i in ctrl], [v[i] for i in pd]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        if max(ma, mb) < EXPRESSED:
            continue
        t, p = welch(a, b)
        rows.append([probe, ma, mb, mb - ma, t, p])
    adj = bh([r[5] for r in rows])
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    with open(out / "de.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["probe_id", "mean_control", "mean_pd", "log2_fold_change", "t", "p_value", "adj_p_value"])
        for r, q in zip(rows, adj):
            w.writerow([r[0], f"{r[1]:.4f}", f"{r[2]:.4f}", f"{r[3]:.4f}", f"{r[4]:.4f}", f"{r[5]:.6g}", f"{q:.6g}"])
    with open(MAPPING, encoding="utf-8") as f:
        genes = {r["probe_id"]: r["gene_symbol"] for r in csv.DictReader(f, delimiter="\t")}
    top = sorted(range(len(rows)), key=lambda i: rows[i][5])[:TOP]
    with open(out / "top_genes.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["probe_id", "gene_symbol", "all_symbols", "log2_fold_change", "p_value", "adj_p_value"])
        for i in top:  # gene_symbol: the first symbol the annotation lists; all_symbols: every one ("///"-separated)
            r = rows[i]
            names = genes.get(r[0], "")
            w.writerow([r[0], names.split("///")[0], names, f"{r[3]:.4f}", f"{r[5]:.6g}", f"{adj[i]:.6g}"])
    n_sig = sum(q < 0.05 for q in adj)
    (out / "summary.toml").write_text(
        f'samples_control = {len(ctrl)}\nsamples_pd = {len(pd)}\nprobes_tested = {len(rows)}\n'
        f'probes_adj_p_below_0_05 = {n_sig}\n', encoding="utf-8")
    print(f"{len(rows)} probes tested ({len(ctrl)} controls, {len(pd)} PD); {n_sig} with adjusted p < 0.05")


if __name__ == "__main__":
    main()
