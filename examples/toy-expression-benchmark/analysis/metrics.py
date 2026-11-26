"""Metrics for the toy expression benchmark (referenced by the contract's metrics.defs)."""


def auroc(labels: list[int], scores: list[float]) -> float:
    """Area under the ROC curve: the probability that a random positive scores above a random negative (ties 0.5)."""
    pos = [s for y, s in zip(labels, scores) if y == 1]
    neg = [s for y, s in zip(labels, scores) if y == 0]
    if not pos or not neg:
        raise ValueError("AUROC needs at least one positive and one negative sample")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))
