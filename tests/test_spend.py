"""v0.4.2: spend guard and R-34. Refusals past the cap, without or with an expired authorization, at unknown prices,
in test mode; estimates and actuals recorded apart."""

import tomllib

import pytest

from steward import spend as sp
from steward.models import StewardConfig

from conftest import codes, one
from test_authorize import approve, expires, pytestmark, repo, sh  # noqa: F401  (fixture and helpers)

PRICES = '''
[spend]
cap = 1.0
[spend.prices.model-a]
input_per_1k = 0.01
output_per_1k = 0.03
source = "https://example.org/fictional/prices"
retrieved = "2026-11-23"
'''


@pytest.fixture
def srepo(repo, monkeypatch):
    with open(repo / "steward.toml", "a") as f:
        f.write(PRICES)
    sh(repo, "git", "commit", "-qam", "spend config")
    # the baseline is a pinned commit (0.8.1): a reviewed policy commit is adopted by re-pinning, as a human does
    from steward.cli import main
    assert main(["authorize", "pin", "--repo", str(repo)]) == 0
    monkeypatch.delenv("STEWARD_NO_PAID_CALLS", raising=False)
    return repo


def cfg(repo):
    return StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))


def budget_tag(cli, repo, budget, exp=None, scope="models=model-a,model-z"):
    code, out, _ = cli("authorize", "prepare", "spend", "--object", "steward.toml", "--budget", budget, "--scope", scope,
                       "--expires", exp or expires(), "--summary", "pilot calls")
    nonce = out.split("authorize sign ")[1].strip()
    return cli("authorize", "sign", nonce)[1].split("signed ")[1].strip()


def test_allowed_call_records_estimate_and_actual(cli, srepo):
    tag = budget_tag(cli, srepo, "USD 0.50")
    code, out, _ = cli("spend", "check", "model-a", "1000", "1000", "--authorization", tag)
    assert code == 0 and "ALLOWED" in out
    call = out.split("call ")[1].split(";")[0]
    assert cli("spend", "record", call, "1200", "900", "--request-id", "req-1")[0] == 0
    t = sp.totals(srepo, cfg(srepo))
    assert t["calls"] == 1 and t["actual"] == pytest.approx(0.012 + 0.027)
    _, rep = cli.check(srepo)
    assert one(rep, "R-34")["status"] == "PASS"


def test_refused_without_or_with_bad_authorization(cli, srepo):
    code, _, err = cli("spend", "check", "model-a", "10", "10", "--authorization", "steward/auth/none")
    assert code == 1 and "REFUSED" in err
    tag = budget_tag(cli, srepo, "USD 0.50", exp="2020-01-01T00:00:00Z")
    assert "expires" in cli("spend", "check", "model-a", "10", "10", "--authorization", tag)[2]


def test_refused_past_authorized_budget_and_cap(cli, srepo):
    tag = budget_tag(cli, srepo, "USD 0.05")
    assert cli("spend", "check", "model-a", "1000", "1000", "--authorization", tag)[0] == 0   # 0.04
    code, _, err = cli("spend", "check", "model-a", "1000", "1000", "--authorization", tag)  # +0.04 > 0.05
    assert code == 1 and "authorized budget exceeded" in err
    big = budget_tag(cli, srepo, "USD 100")
    code, _, err = cli("spend", "check", "model-a", "40000", "40000", "--authorization", big)  # 1.6 > cap 1.0
    assert code == 1 and "repository cap exceeded" in err


def test_unknown_price_refused_unless_authorized_with_ceiling(cli, srepo):
    tag = budget_tag(cli, srepo, "USD 0.50")
    code, _, err = cli("spend", "check", "model-z", "10", "10", "--authorization", tag)
    assert code == 1 and "no price" in err
    unk = budget_tag(cli, srepo, "unknown-price calls=1")
    assert cli("spend", "check", "model-z", "10", "10", "--authorization", unk)[0] == 0
    code, _, err = cli("spend", "check", "model-z", "10", "10", "--authorization", unk)
    assert code == 1 and "call ceiling" in err


def test_test_mode_refuses_everything(cli, srepo, monkeypatch):
    tag = budget_tag(cli, srepo, "USD 0.50")
    monkeypatch.setenv("STEWARD_NO_PAID_CALLS", "1")
    code, _, err = cli("spend", "check", "model-a", "1", "1", "--authorization", tag)
    assert code == 1 and "STEWARD_NO_PAID_CALLS" in err


def test_library_guard_raises(srepo):
    with pytest.raises(sp.SpendRefused):
        sp.guard(srepo, cfg(srepo), "model-a", 1, 1, "steward/auth/missing")


def test_R34_flags_unauthorized_and_over_cap(cli, srepo):
    from steward.ledger import Ledger

    led = Ledger(srepo / "development/spend.jsonl", "spend")
    led.append("estimate", {"call": "x1", "model": "model-a", "est_in": 0, "est_out": 0, "est_cost": 2.0,
                            "tag": "steward/auth/forged", "nonce": "n"})
    led.append("actual", {"call": "orphan", "model": "model-a", "tokens_in": 1, "tokens_out": 1, "cost": 0.0})
    _, rep = cli.check(srepo)
    res = one(rep, "R-34")
    assert res["status"] == "FAIL" and {"R-34.unauthorized", "R-34.over_cap", "R-34.actual_without_estimate"} <= codes(res)


def test_budget_parser():
    assert sp.parse_budget("USD 50 calls=10").amount == 50 and sp.parse_budget("USD 50 calls=10").calls == 10
    assert sp.parse_budget("unknown-price calls=3").unknown_price_ok
    with pytest.raises(sp.SpendRefused):
        sp.parse_budget("lots")


# ---------------------------------------------------------------- red-team A2
def test_A2_scope_is_enforced(cli, srepo):
    tag = budget_tag(cli, srepo, "USD 0.50", scope="models=model-a task=pilot")
    assert cli("spend", "check", "model-a", "10", "10", "--authorization", tag, "--task", "pilot")[0] == 0
    code, _, err = cli("spend", "check", "model-a", "10", "10", "--authorization", tag, "--task", "other")
    assert code == 1 and "task" in err
    code, _, err = cli("spend", "check", "model-z", "10", "10", "--authorization", tag, "--task", "pilot")
    assert code == 1 and "outside the authorized scope" in err
    unscoped = budget_tag(cli, srepo, "USD 0.50", scope="-")
    assert "names no models" in cli("spend", "check", "model-a", "10", "10", "--authorization", unscoped)[2]


def test_A2_concurrent_workers_cannot_both_take_the_last_allocation(cli, srepo):
    import subprocess
    import sys
    tag = budget_tag(cli, srepo, "USD 0.05")  # room for one 0.04 call, not two
    go = srepo / "go"
    prog = (
        "import os, sys, time, tomllib\n"
        "from pathlib import Path\n"
        "from steward import spend\n"
        "from steward.models import StewardConfig\n"
        "root = Path('.').resolve()\n"
        "cfg = StewardConfig.model_validate(tomllib.loads(Path('steward.toml').read_text()))\n"
        "while not Path('go').exists(): time.sleep(0.005)\n"
        "try:\n    spend.guard(root, cfg, 'model-a', 1000, 1000, sys.argv[1]); print('OK')\n"
        "except spend.SpendRefused as e:\n    print('REFUSED', e)\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", prog, tag], cwd=srepo, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    import time
    time.sleep(1.0)
    go.write_text("")
    outs = [p.communicate(timeout=60)[0] for p in procs]
    assert sum(o.startswith("OK") for o in outs) == 1, outs
    assert sp.totals(srepo, cfg(srepo))["calls"] == 1


# ---------------------------------------------------------------- red-team B2, B3
def test_B2_unknown_price_needs_a_call_ceiling():
    for text in ("unknown-price", "unknown-price calls=0"):
        with pytest.raises(sp.SpendRefused):
            sp.parse_budget(text)
    assert sp.parse_budget("unknown-price calls=3").calls == 3


def test_B2_unbounded_unknown_price_refused_before_any_reservation(cli, srepo):
    tag = budget_tag(cli, srepo, "unknown-price")
    code, _, err = cli("spend", "check", "model-z", "10", "10", "--authorization", tag)
    assert code == 1 and "REFUSED" in err
    assert sp.totals(srepo, cfg(srepo))["calls"] == 0


def test_B3_spend_refused_with_unpinned_trust_root(cli, srepo):
    tag = budget_tag(cli, srepo, "USD 0.50")
    (srepo.parent / "config-home/trust.toml").unlink()
    code, _, err = cli("spend", "check", "model-a", "10", "10", "--authorization", tag)
    assert code == 1 and "not pinned" in err
