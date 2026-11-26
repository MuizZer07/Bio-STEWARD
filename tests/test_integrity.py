"""v0.5.0 research integrity: freeze, amend, seal/unseal, R-35 … R-39 (RELEASE_v0.5_SPEC §7)."""

import shutil
import sys

import pytest

from conftest import codes, one
from test_authorize import approve, expires, pytestmark, repo, sh  # noqa: F401

PY = sys.executable
DECISION = "2026-11-23 — approve the frozen design"


@pytest.fixture
def irepo(repo):
    with open(repo / "steward.toml", "a") as f:
        f.write("\n[integrity]\n")
    (repo / "proto").mkdir()
    (repo / "proto/protocol.md").write_text("Primary metric: AUROC\n")
    (repo / "proto/params.toml").write_text("alpha = 0.05\nresamples = 2000\n[model]\nlr = 0.001\n")
    (repo / "proto/test_ids.txt").write_text("S1\nS2\nS3\n")
    (repo / "data/heldout").mkdir(parents=True)
    (repo / "data/heldout/b.csv").write_text("id,y\nS9,1\n")
    (repo / "data/dev.csv").write_text("id,y\nS1,0\n")
    (repo / "development/datasets.toml").write_text(
        'schema = "steward.datasets/0.1"\n[datasets.heldout]\nrole = "development"\nidentifier = "unknown"\n'
        'paths = ["data/heldout/**"]\nsha256 = "TBD"\n')
    with open(repo / "development/DECISIONS.md", "a") as f:
        f.write(f"\n## {DECISION}\n- Quote: \"yes\"\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "add", "-f", "development/DECISIONS.md")  # a global *.md ignore must not hide the log
    sh(repo, "git", "commit", "-qm", "integrity setup")
    # the baseline is a pinned commit (0.8.1): the reviewed setup commit is adopted by re-pinning
    from steward.cli import main
    assert main(["authorize", "pin", "--repo", str(repo)]) == 0
    return repo


def freeze(cli, args=("--files", "proto/protocol.md", "--cohort", "proto/test_ids.txt", "--params", "proto/params.toml")):
    return cli("freeze", "design", *args)


def test_freeze_then_drift_detected(cli, irepo):
    assert freeze(cli)[0] == 0
    _, rep = cli.check(irepo)
    assert one(rep, "R-35")["status"] == "PASS"
    (irepo / "proto/protocol.md").write_text("Primary metric: AUPRC\n")
    (irepo / "proto/test_ids.txt").write_text("S1\nS2\nS4\nS5\n")
    (irepo / "proto/params.toml").write_text("alpha = 0.1\nresamples = 2000\n[model]\nlr = 0.001\n")
    code, rep = cli.check(irepo)
    res = one(rep, "R-35")
    assert res["status"] == "FAIL" and code == 1
    assert {"protocol.drift", "cohort.changed", "params.changed"} <= codes(res)
    cohort = next(d for d in res["details"] if d["code"] == "cohort.changed")
    # the cohort IDs never appear in the R-35 result (scoped: a generated key fingerprint elsewhere in the report
    # can contain the text "S4"; review of 0.10.0, verification limits)
    assert cohort["message"] == "2 added, 1 removed (IDs not shown)" and not __import__("re").search(r"\bS4\b", str(res))


def test_refreeze_refused(cli, irepo):
    freeze(cli)
    code, _, err = freeze(cli)
    assert code == 1 and "already frozen" in err


def test_amend_propose_incomplete_then_signed_apply(cli, irepo):
    freeze(cli)
    (irepo / "proto/params.toml").write_text("alpha = 0.05\nresamples = 5000\n[model]\nlr = 0.001\n")
    code, out, _ = cli("amend", "propose", "design", "--reason", "more resamples")
    assert code == 0
    obj = out.split("--object ")[1].split()[0]
    _, rep = cli.check(irepo)
    assert one(rep, "R-35")["status"] == "FAIL"  # drift stays visible until the amendment is applied
    assert "R-35.proposal_pending" in codes(one(rep, "R-35"))
    code, _, err = cli("amend", "apply", "design", "--authorization", "steward/auth/none", "--decision", DECISION)
    assert code == 1 and "NOT AUTHORIZED" in err
    tag = approve(cli, irepo, action="amend", obj=obj)
    assert cli("amend", "apply", "design", "--authorization", tag, "--decision", DECISION)[0] == 0
    _, rep = cli.check(irepo)
    assert one(rep, "R-35")["status"] == "PASS" and one(rep, "R-38")["status"] == "PASS"
    (irepo / "proto/params.toml").write_text("alpha = 0.05\nresamples = 9000\n[model]\nlr = 0.001\n")
    _, out, _ = cli("amend", "propose", "design", "--reason", "again")
    code, _, err = cli("amend", "apply", "design", "--authorization", tag, "--decision", DECISION)
    assert code == 1 and ("object" in err or "consumed" in err)  # single use, and bound to its object


def test_amend_apply_refused_if_files_changed_after_proposal(cli, irepo):
    freeze(cli)
    (irepo / "proto/protocol.md").write_text("v2\n")
    _, out, _ = cli("amend", "propose", "design", "--reason", "r")
    obj = out.split("--object ")[1].split()[0]
    (irepo / "proto/protocol.md").write_text("v3\n")
    tag = approve(cli, irepo, action="amend", obj=obj)
    code, _, err = cli("amend", "apply", "design", "--authorization", tag, "--decision", DECISION)
    assert code == 1 and "changed since the proposal" in err


def test_apply_needs_a_recorded_decision(cli, irepo):
    freeze(cli)
    (irepo / "proto/protocol.md").write_text("v2\n")
    _, out, _ = cli("amend", "propose", "design", "--reason", "r")
    tag = approve(cli, irepo, action="amend", obj=out.split("--object ")[1].split()[0])
    code, _, err = cli("amend", "apply", "design", "--authorization", tag, "--decision", "a decision nobody wrote")
    assert code == 1 and "not found" in err


def test_seal_blocks_run_and_unseal_needs_signature(cli, irepo):
    assert cli("seal", "heldout")[0] == 0
    _, rep = cli.check(irepo)
    assert "R-36.role_mismatch" in codes(one(rep, "R-36"))  # datasets.toml still says development
    text = (irepo / "development/datasets.toml").read_text().replace('role = "development"', 'role = "sealed"')
    (irepo / "development/datasets.toml").write_text(text)
    code, _, err = cli("run", "--input", "data/heldout/b.csv", "--", PY, "-c", "pass")
    assert code == 77 and "sealed dataset 'heldout'" in err
    shutil.copy(irepo / "data/heldout/b.csv", irepo / "data/renamed.csv")  # a copy under another name: matched by hash
    assert cli("run", "--input", "data/renamed.csv", "--", PY, "-c", "pass")[0] == 77
    assert cli("run", "--input", "data/dev.csv", "--", PY, "-c", "pass")[0] == 0
    code, _, err = cli("unseal", "heldout", "--authorization", "steward/auth/none", "--decision", DECISION)
    assert code == 1
    sealed = next(e for e in __import__("steward.integrity", fromlist=["x"]).state(irepo, _cfg(irepo)).entries if e.get("kind") == "seal")["content"]
    tag = approve(cli, irepo, action="unseal", obj=sealed)
    assert cli("unseal", "heldout", "--authorization", tag, "--decision", DECISION)[0] == 0
    (irepo / "development/datasets.toml").write_text(text.replace('role = "sealed"', 'role = "spent"'))
    assert cli("run", "--input", "data/heldout/b.csv", "--", PY, "-c", "pass")[0] == 0
    _, rep = cli.check(irepo)
    assert one(rep, "R-36")["status"] in ("INCOMPLETE", "UNKNOWN")  # sha256 TBD / identifier unknown, no mismatch
    assert "R-36.role_mismatch" not in codes(one(rep, "R-36"))


def _cfg(repo):
    import tomllib
    from steward.models import StewardConfig
    return StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))


def test_sealed_contents_changed_fails(cli, irepo):
    cli("seal", "heldout")
    (irepo / "development/datasets.toml").write_text((irepo / "development/datasets.toml").read_text().replace('"development"', '"sealed"'))
    (irepo / "data/heldout/b.csv").write_text("id,y\nS9,0\n")
    _, rep = cli.check(irepo)
    assert "R-36.sealed_changed" in codes(one(rep, "R-36"))


def test_sealed_use_detected_in_run_records_and_values(cli, irepo):
    from steward.ledger import Ledger

    cli("seal", "heldout")
    Ledger(irepo / "development/runs.jsonl", "runs").append("started", {"run": "sneaky", "inputs": {"data/heldout/b.csv": "x"}})
    with open(irepo / "steward.toml", "a") as f:
        f.write('\n[paper.main]\ndir = "paper"\nmain = "main.tex"\n')
    (irepo / "paper").mkdir()
    (irepo / "paper/values.toml").write_text('schema = "steward.values/0.1"\n[values.n]\nsource = "data/heldout/b.csv"\ncount = "rows"\n')
    _, rep = cli.check(irepo)
    c = codes(one(rep, "R-37"))
    assert one(rep, "R-37")["status"] == "FAIL" and {"R-37.run_read_sealed", "R-37.paper_reports_sealed"} <= c


def test_unauthorized_gated_entry_and_rewritten_decisions(cli, irepo):
    from steward.integrity import ledger

    ledger(irepo, _cfg(irepo)).append("unseal", {"dataset": "heldout", "object": "sha256:" + "0" * 64,
                                                  "authorization": "steward/auth/forged", "decision": "nope"})
    (irepo / "development/DECISIONS.md").write_text("# rewritten history\n")
    _, rep = cli.check(irepo)
    c = codes(one(rep, "R-38"))
    assert one(rep, "R-38")["status"] == "FAIL" and {"R-38.unauthorized", "R-38.no_decision", "R-38.decisions_rewritten"} <= c


def test_confirmatory_contract_freeze_needs_signature_and_timing(cli, irepo):
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "examples/toy-expression-benchmark/benchmarks/expr-clf.contract.toml"
    (irepo / "benchmarks").mkdir()
    shutil.copy(src, irepo / "benchmarks/expr-clf.contract.toml")
    sh(irepo, "git", "add", "-A")
    sh(irepo, "git", "commit", "-qm", "contract")
    _, rep = cli.check(irepo)
    assert "R-39.not_frozen" in codes(one(rep, "R-39"))
    args = ("--files", "benchmarks/expr-clf.contract.toml", "--contract", "expr-clf")
    code, _, err = cli("freeze", "c", *args)
    assert code == 1 and "needs --authorization" in err
    _, out, _ = cli("freeze", "c", *args, "--dry-run")
    obj = out.split()[1]
    cli("run", "--contract", "expr-clf", "--", PY, "-c", "pass")  # a run before the freeze
    import time
    time.sleep(1.1)
    tag = approve(cli, irepo, action="freeze.confirmatory", obj=obj)
    assert cli("freeze", "c", *args, "--authorization", tag, "--decision", DECISION)[0] == 0
    _, rep = cli.check(irepo)
    assert "R-39.frozen_after_run" in codes(one(rep, "R-39"))
    assert one(rep, "R-38")["status"] == "PASS"


def test_not_configured_is_not_applicable(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    assert all(one(rep, r)["status"] == "NOT_APPLICABLE" for r in ("R-35", "R-36", "R-37", "R-38", "R-39"))


def test_decisions_log_missing_from_baseline_is_stated(cli, irepo):
    sh(irepo, "git", "rm", "-q", "--cached", "development/DECISIONS.md")
    sh(irepo, "git", "commit", "-qm", "untrack log")
    cli("authorize", "pin")  # the pinned baseline is a commit (0.8.1): adopt the untracking commit
    _, rep = cli.check(irepo)
    # 0.9.0 (DEF-022): no longer only stated; the log's own history is checked, and said to be weaker
    assert {"R-38.append_only_history", "R-38.append_only_weak"} <= {d["code"] for d in one(rep, "R-38")["details"]}
