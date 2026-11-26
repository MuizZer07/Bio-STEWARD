"""Generate the synthetic data of the toy expression benchmark. Fictional: no real samples, donors or genes.

    python make_data.py          # writes data/ and benchmarks/splits/; prints the dataset SHA-256

Standard library only. Seeded (20261123) and formatted with fixed decimals, so the bytes are identical on every
run and platform. 40 donors x 3 samples = 120 samples, 200 genes, 2 batches; the binary "responder" label is
assigned per donor. Genes g001-g010 carry a label signal; g051-g060 carry a batch effect unrelated to the label.
Splits are by donor (24 train / 8 validation / 8 test), so no donor appears in two splits.
"""

import hashlib
import random
from pathlib import Path

SEED = 20261123
N_DONORS, PER_DONOR, N_GENES = 40, 3, 200
HERE = Path(__file__).resolve().parent


def main() -> None:
    rng = random.Random(SEED)
    donors = [f"D{d:03d}" for d in range(1, N_DONORS + 1)]
    label = {d: int(i % 2 == 0) for i, d in enumerate(donors)}
    batch = {d: (i // 2) % 2 for i, d in enumerate(donors)}
    genes = [f"g{g:03d}" for g in range(1, N_GENES + 1)]

    samples, rows = [], []
    for d in donors:
        donor_offset = rng.gauss(0.0, 0.3)
        for k in range(1, PER_DONOR + 1):
            sid = f"S{d[1:]}_{k}"
            samples.append(f"{sid},{d},{batch[d]},{label[d]}")
            values = []
            for gi in range(N_GENES):
                x = rng.gauss(0.0, 1.0) + donor_offset
                if gi < 10 and label[d]:
                    x += 0.8
                if 50 <= gi < 60 and batch[d]:
                    x += 0.3
                values.append(f"{x:.4f}")
            rows.append(sid + "," + ",".join(values))

    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data/samples.csv").write_text("sample_id,donor_id,batch,responder\n" + "\n".join(samples) + "\n", newline="\n")
    expr = "sample_id," + ",".join(genes) + "\n" + "\n".join(rows) + "\n"
    (HERE / "data/expression.csv").write_text(expr, newline="\n")

    order = donors[:]
    rng.shuffle(order)
    split = {"train": order[:24], "validation": order[24:32], "test": order[32:]}
    (HERE / "benchmarks/splits").mkdir(parents=True, exist_ok=True)
    for name, ds in split.items():
        ids = sorted(f"S{d[1:]}_{k}" for d in ds for k in range(1, PER_DONOR + 1))
        (HERE / f"benchmarks/splits/{name}.txt").write_text("\n".join(ids) + "\n", newline="\n")

    print("data/expression.csv sha256", hashlib.sha256(expr.encode()).hexdigest())


if __name__ == "__main__":
    main()
