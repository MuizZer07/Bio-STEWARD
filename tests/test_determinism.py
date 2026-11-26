"""T-DET: verdicts are a pure function of repository bytes; regression goldens (spec §8.1 'Regression', §8.4).

Regenerate goldens after an intended behaviour change: STEWARD_UPDATE_GOLDENS=1 pytest tests/test_determinism.py
"""

import os
import shutil
from pathlib import Path

from steward.engine import run_check
from steward.fsutil import canonical_json

from conftest import CONTRACT, PRIOR, append, edit

GOLDEN = Path(__file__).parent / "golden"


def verdict(root: Path) -> str:
    return canonical_json(run_check(root)["verdict"])


def mixed(root: Path) -> Path:
    """One fixture showing every status: FAIL, INCOMPLETE, UNKNOWN, NOT_APPLICABLE, PASS."""
    edit(root, "steward.toml", 'profile = "confirmatory"', 'profile = "exploratory"')  # R-04, R-06 NOT_APPLICABLE
    edit(root, CONTRACT, 'primary = "auroc"', 'primary = "auprc"')               # R-03 FAIL
    edit(root, CONTRACT, "value      = 0.05", 'value      = "TBD"')              # R-02 INCOMPLETE
    edit(root, PRIOR, 'identifier = "url:https://example.org/fictional/logistic-baselines"', 'identifier = "unknown"')  # R-05 UNKNOWN
    append(root, "steward.toml", '\n[privacy]\ndenylist_file = ".steward/private/denylist.txt"\n')
    append(root, ".steward/private/denylist.txt", "nightjar\n")
    append(root, "README.md", "\nnightjar\n")                                     # R-07 FAIL
    return root


def check_golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text, f"verdict differs from {path}; regenerate only if intended"


def test_T_DET_01_two_runs_identical(example):
    assert verdict(example) == verdict(example)


def test_T_DET_02_same_verdict_at_another_path(example, tmp_path):
    other = tmp_path / "elsewhere" / "nested"
    shutil.copytree(example, other)
    assert verdict(example) == verdict(other)


def test_golden_example(example):
    check_golden("example.verdict.json", verdict(example))


def test_golden_mixed_statuses(example):
    text = verdict(mixed(example))
    counts = run_check(example)["verdict"]["summary"]["counts"]
    assert all(counts[s] > 0 for s in ("PASS", "FAIL", "INCOMPLETE", "UNKNOWN", "NOT_APPLICABLE"))
    check_golden("mixed.verdict.json", text)


def test_envelope_varies_verdict_does_not(example):
    a, b = run_check(example), run_check(example)
    assert a["verdict"] == b["verdict"]
    assert set(a["envelope"]) == {"tool", "tool_version", "created", "platform", "git"}
