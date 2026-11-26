"""0.10.0 hardening (RELEASE_v0.10.0_SPEC H2 - H4): seeded fuzzing of every parser, property tests, performance.

Fuzzing: each file the toolkit parses is mutated (truncated, bytes flipped, NUL and control bytes inserted, deeply
nested, huge values, emptied, values replaced by other types) and `steward check` must answer every time with a
status and a reason: no rule may report `internal_error`, and no command may exit 70.
Performance tests run with STEWARD_SLOW=1.
"""

import json
import os
import random
import shutil
import time

import pytest

from conftest import EXAMPLE

SEED = 20261124
SLOW = pytest.mark.skipif(not os.environ.get("STEWARD_SLOW"), reason="performance budgets: set STEWARD_SLOW=1")


def mutations(data: bytes, rng: random.Random, n: int = 8) -> list[bytes]:
    out = [b"", data[: len(data) // 2], data + b"\x00\x01\xff", b"[" * 5000 + b"]" * 5000, b"x = " + b"9" * 5000 + b"\n"]
    for _ in range(n):
        b = bytearray(data)
        for _ in range(rng.randint(1, 6)):
            if b:
                b[rng.randrange(len(b))] = rng.randrange(256)
        out.append(bytes(b))
    swapped = data.replace(b'"', b"[").replace(b"= [", b"= {")
    out.append(swapped)
    return out


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """One repository with every table configured and a valid sample of every parsed file."""
    root = tmp_path_factory.mktemp("fuzz") / "toy"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".steward", "__pycache__", "*.aux", "*.fls", "*.log"))
    with open(root / "steward.toml", "a") as f:
        f.write('''
[exchange]
code = "ABC"
[repro]
contracts = ["bench/*.repro.toml"]
[dependencies]
pins = ["requirements*.txt"]
[containers]
contexts = ["svc"]
compose = ["compose.yml"]
[changelog]
file = "CHANGELOG.md"
[session]
[agents]
[tasks]
specs = ["tasks/*.md"]
board = "BOARD.md"
[[frozen]]
name = "agent"
files = ["agents/**"]
''')
    files = {
        "exchange/inbox/XYZ-REQ-001.md": '+++\nschema = "steward.exchange/1"\nid = "XYZ-REQ-001"\nkind = "request"\nfrom = "XYZ"\n'
                                         'to = "ABC"\ntitle = "t"\nfiled = 2026-11-23\n+++\n## Need\nx\n',
        "exchange/log.jsonl": "",
        "bench/r.repro.toml": 'schema = "steward.repro/0.1"\nid = "r"\nmanifest = "bench/M.json"\ncanonical = "json-sorted"\n',
        "bench/M.json": '{"schema": "steward.repro_manifest/0.1", "files": {"a.json": "' + "0" * 64 + '"}}',
        "requirements.txt": "numpy==1.26.4\n",
        "development/upgrades/u.toml": 'schema = "steward.upgrade/0.1"\npackage = "numpy"\nold = "1"\nnew = "2"\n',
        "svc/Dockerfile": "FROM scratch\n",
        "svc/.dockerignore": "*.old\n!keep.old\n",
        "compose.yml": "services:\n  web:\n    environment:\n      A: b\n",
        "CHANGELOG.md": "# C\n\n## Unreleased\n- x\n\n## 1.0\n- y\n",
        "development/HANDOFF.md": "# Session handoff\n\n## State\nx\n",
        "development/agents.jsonl": "",
        "tasks/a.md": "- **ID:** T-001\n- **Status:** done\n",
        "BOARD.md": "# Board\nNext unused ID: T-002\n",
        "agents/prompt.md": "be careful\n",
        "development/frozen/agent.json": '{"schema": "steward.frozen/0.1", "name": "agent", "files": {}}',
        "development/datasets.toml": 'schema = "steward.datasets/0.1"\n[datasets.a]\nrole = "development"\nidentifier = "TBD"\n',
        "release-manifest.json": '{"schema": "steward.release_manifest/0.1"}',
        "steward.local.toml": '[gates.private]\nrequire = ["R-01"]\n',
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for sub in ("outbox", "responses", "oneway"):
        (root / "exchange" / sub).mkdir(parents=True, exist_ok=True)
    (root / "exchange/README.md").write_text("x\n")
    return root


TARGETS = ["steward.toml", "steward.local.toml", "benchmarks/expr-clf.contract.toml",
           "development/prior_work/expr-clf.prior.toml", "development/datasets.toml", "exchange/inbox/XYZ-REQ-001.md",
           "exchange/log.jsonl", "bench/r.repro.toml", "bench/M.json", "development/upgrades/u.toml",
           "development/assessment/findings.toml", "release-manifest.json", "compose.yml", "svc/.dockerignore",
           "CHANGELOG.md", "development/DECISIONS.md", "development/HANDOFF.md", "development/agents.jsonl",
           "tasks/a.md", "BOARD.md", "development/frozen/agent.json", "paper/spec.toml", "requirements.txt"]


@pytest.mark.parametrize("target", TARGETS)
def test_H2_no_mutation_of_a_parsed_file_crashes_a_rule(cli, base, target, tmp_path):
    root = tmp_path / "r"
    shutil.copytree(base, root, symlinks=True)
    p = root / target
    original = p.read_bytes() if p.is_file() else b"x = 1\n"
    rng = random.Random(f"{SEED}:{target}")
    for i, data in enumerate(mutations(original, rng)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        code, out, err = cli("check", "--repo", root, "--format", "json")
        assert code != 70, (target, i, err[:300])
        rep = json.loads(out)
        crashed = [r["rule"] for r in rep["verdict"]["results"] if r["reason"] == "internal_error"]
        assert not crashed, (target, i, crashed, [r["details"] for r in rep["verdict"]["results"] if r["rule"] in crashed])


# ---------------------------------------------------------------- H3: properties
def test_H3_canonical_json_ignores_key_order_and_whitespace():
    from steward.fsutil import canonical_json, sha256_bytes
    rng = random.Random(SEED)
    for _ in range(200):
        d = {f"k{rng.randrange(50)}": rng.choice([1, "x", [1, 2], {"a": rng.random()}]) for _ in range(rng.randrange(1, 12))}
        shuffled = dict(rng.sample(list(d.items()), len(d)))
        assert canonical_json(d) == canonical_json(shuffled)
        assert sha256_bytes(canonical_json(json.loads(json.dumps(d, indent=7))).encode()) == sha256_bytes(canonical_json(d).encode())


def test_H3_any_one_byte_edit_of_a_ledger_is_detected(tmp_path):
    from steward.ledger import Ledger, verify
    p = tmp_path / "l.jsonl"
    led = Ledger(p, "t")
    for i in range(20):
        led.append("x", {"i": i, "note": f"entry {i}"})
    good = p.read_bytes()
    clean = verify(p).entries
    rng = random.Random(SEED)
    for _ in range(300):
        b = bytearray(good)
        pos = rng.randrange(len(b))
        new = rng.randrange(256)
        if new == b[pos]:
            continue
        b[pos] = new
        p.write_bytes(bytes(b))
        v = verify(p)
        assert v.errors or v.torn_tail or v.entries != clean, pos


def test_H3_combine_is_commutative_associative_and_monotone():
    from steward.status import Status, combine
    causes = [Status.PASS, Status.UNKNOWN, Status.INCOMPLETE, Status.FAIL]  # what a rule combines
    rng = random.Random(SEED)
    for _ in range(500):
        xs = [rng.choice(causes) for _ in range(rng.randrange(0, 8))]
        assert combine(xs) == combine(list(reversed(xs))) == combine(rng.sample(xs, len(xs)))
        k = rng.randrange(len(xs) + 1)
        assert combine([combine(xs[:k]), combine(xs[k:])]) == combine(xs)  # associative
        assert combine([*xs, Status.FAIL]) == Status.FAIL  # a worse input never gives a better status
        worse = combine([*xs, Status.INCOMPLETE])
        assert causes.index(worse) >= causes.index(combine(xs)) or worse == Status.FAIL


def test_H3_a_gate_is_never_eligible_with_a_blocking_required_result():
    from steward.status import Result, Status, evaluate_gate
    rng = random.Random(SEED)
    for _ in range(300):
        rules = [f"R-{i:02d}" for i in range(1, 9)]
        res = [Result(r, "n", 1, ".", rng.choice(list(Status)), "x", [], []) for r in rules]
        req = rng.sample(rules, rng.randrange(1, len(rules)))
        g = evaluate_gate("g", req, res, partial=False, min_evaluated=0)
        blocking = [r for r in res if r.rule in req and r.status in (Status.FAIL, Status.INCOMPLETE, Status.UNKNOWN)]
        if blocking:
            assert not g["eligible"]


# ---------------------------------------------------------------- H4: performance (STEWARD_SLOW=1)
@SLOW
def test_H4_split_overlap_on_a_million_ids(tmp_path):
    import tomllib
    from steward import benchmark as bm
    from steward.models import Contract
    root = tmp_path / "toy"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".steward", "__pycache__"))
    n = 1_000_000
    sizes = {"train": 800_000, "validation": 100_000, "test": 100_000}
    start = 0
    rows = ["sample_id,donor_id"]
    for name, k in sizes.items():
        ids = [f"s{i}" for i in range(start, start + k)]
        (root / f"benchmarks/splits/{name}.txt").write_text("\n".join(ids) + "\n")
        rows += [f"{s},d{i // 3}" for i, s in enumerate(ids, start=start)]
        start += k
    (root / "data/samples.csv").write_text("\n".join(rows) + "\n")
    c = Contract.model_validate(tomllib.loads((root / "benchmarks/expr-clf.contract.toml").read_text()))
    t0 = time.monotonic()
    bm.analyze(root, c)
    took = time.monotonic() - t0
    assert took < 60, f"{n} IDs took {took:.1f} s (budget 60 s)"


@SLOW
def test_H4_ledger_verification_of_a_hundred_thousand_entries(tmp_path):
    from steward.ledger import GENESIS, entry_hash, verify
    p = tmp_path / "big.jsonl"
    prev, lines = GENESIS, []
    for i in range(100_000):
        e = {"seq": i, "prev": prev, "kind": "x", "i": i}
        e["hash"] = entry_hash(e)
        prev = e["hash"]
        lines.append(json.dumps(e, sort_keys=True, separators=(",", ":")))
    p.write_text("\n".join(lines) + "\n")
    t0 = time.monotonic()
    v = verify(p)
    took = time.monotonic() - t0
    assert not v.errors and len(v.entries) == 100_000 and took < 30, f"{took:.1f} s (budget 30 s)"


@SLOW
def test_H4_repository_walk_and_conflict_scan_of_ten_thousand_files(cli, tmp_path):
    root = tmp_path / "many"
    root.mkdir()
    cli("init", "--repo", root)
    for i in range(10_000):
        d = root / f"d{i // 500}"
        d.mkdir(exist_ok=True)
        (d / f"f{i}.txt").write_text("line\n" * 20)
    t0 = time.monotonic()
    code, out, _ = cli("check", "--repo", root, "files", "--format", "json")
    took = time.monotonic() - t0
    assert took < 60, f"{took:.1f} s (budget 60 s)"
