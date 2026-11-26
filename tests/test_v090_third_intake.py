"""0.9.0, third intake: REQ-003 - 016 (RELEASE_v0.9.0_SPEC §14). Each test is named after its item ID."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import codes, gate, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
CFF = "cff-version: 1.2.0\nmessage: m\ntitle: t\nauthors:\n  - name: n\n"


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    return r


def add(root, text):
    with open(root / "steward.toml", "a") as f:
        f.write(text)


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def git(root):
    sh(root, "git", "init", "-q", "-b", "main")
    sh(root, "git", "config", "user.name", "T")
    sh(root, "git", "config", "user.email", "t@example.org")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "init")


# ---------------------------------------------------------------- REQ-015: conflict markers
CONFLICT = "a\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\nb\n"


def test_REQ_015_conflict_markers_fail_and_the_allow_marker_exempts(cli, proj):
    _, rep = cli.check(proj, "files")
    assert one(rep, "R-61")["status"] == "PASS"
    write(proj, "notes/record.md", CONFLICT)
    _, rep = cli.check(proj)
    res = one(rep, "R-61")
    assert res["status"] == "FAIL" and "R-61.conflict_marker" in codes(res) and not gate(rep)["eligible"]
    write(proj, "notes/record.md", "<!-- steward: allow conflict-markers -->\n" + CONFLICT)
    _, rep = cli.check(proj, "files")
    assert one(rep, "R-61")["status"] == "PASS"


def test_REQ_015_a_markdown_rule_line_is_not_a_conflict(cli, proj):
    write(proj, "doc.md", "Title\n=======\n\ntext\n")
    _, rep = cli.check(proj, "files")
    assert one(rep, "R-61")["status"] == "PASS"


# ---------------------------------------------------------------- REQ-013: several decisions logs
ENTRY = '\n## 2026-11-20: x\n- **Quote:** "q"\n- **Decision:** d\n- **Consequences:** c\n'


@git_needed
def test_REQ_013_every_listed_log_is_append_only(cli, proj):
    add(proj, '\n[integrity]\ndecisions = ["development/DECISIONS.md", "studies/*/DECISIONS.md"]\n')
    write(proj, "studies/a/DECISIONS.md", "# A\n" + ENTRY)
    write(proj, "studies/b/DECISIONS.md", "# B\n" + ENTRY)
    git(proj)
    sh(proj, "git", "checkout", "-q", "-b", "task")
    with open(proj / "studies/a/DECISIONS.md", "a") as f:
        f.write(ENTRY.replace("2026-11-20", "2026-11-21"))
    _, rep = cli.check(proj, "integrity")
    assert one(rep, "R-38")["status"] == "PASS", one(rep, "R-38")
    p = proj / "studies/b/DECISIONS.md"
    p.write_text(p.read_text().replace('"q"', '"edited"'))
    _, rep = cli.check(proj, "integrity")
    res = one(rep, "R-38")
    assert res["status"] == "FAIL" and any(d.get("path") == "studies/b/DECISIONS.md" and d["code"] == "R-38.decisions_rewritten"
                                           for d in res["details"]), res


# ---------------------------------------------------------------- REQ-014: changelog entry fields
@git_needed
def test_REQ_014_entries_need_their_fields_and_a_release_needs_ready(cli, proj):
    add(proj, '\n[changelog]\nentry_pattern = "^- .+ \\\\(Gate: [a-z-]+; Status: [a-z-]+\\\\)$"\nready = "ready"\n')
    write(proj, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n## 1.0\n- x\n")
    git(proj)
    sh(proj, "git", "tag", "v1.0")
    write(proj, "src/x.py", "x = 1\n")
    write(proj, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n- added x (Status: ready)\n\n## 1.0\n- x\n")
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "x")
    _, rep = cli.check(proj, "changelog")
    res = one(rep, "R-58")
    assert res["status"] == "FAIL" and "R-58.entry_malformed" in codes(res), res
    write(proj, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n- added x (Gate: core; Status: draft)\n\n## 1.0\n- x\n")
    sh(proj, "git", "commit", "-qam", "y")
    _, rep = cli.check(proj, "changelog")
    assert one(rep, "R-58")["status"] == "PASS"
    _, out, _ = cli("check", "--repo", proj, "--format", "json", "--final", "changelog")
    res = one(json.loads(out), "R-58")
    assert res["status"] == "FAIL" and "R-58.not_ready" in codes(res), res


# ---------------------------------------------------------------- REQ-006: declared shipped secrets
def _release(cli, proj, member):
    import zipfile
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        write(proj, name, text)
    (proj / "dist").mkdir()
    with zipfile.ZipFile(proj / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
        z.writestr(member, "SECRET=1\n")


def test_REQ_006_a_declared_and_decided_shipped_secret_is_reported_not_refused(cli, proj, monkeypatch):
    from steward import authorize as az
    monkeypatch.setattr(az, "verify", lambda *a, **k: object())  # Article II.3: a verified waive (R19)
    add(proj, '\n[policy]\nstate = "pending"\n[release]\n[[release.shipped_secret]]\npath = "p/config/*.env"\n'
              'reason = "private package"\ndecision = "2026-11-20: ship the service credentials"\n'
              'authorization = "steward/auth/0"\n')
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-20: ship the service credentials\n")
    _release(cli, proj, "p/config/service.env")
    code, out, _ = cli("release", "audit")
    assert code == 0 and "shipped_secret" in out, out
    _release_undeclared = "p/other.env"
    import zipfile
    with zipfile.ZipFile(proj / "dist/p-1.0-py3-none-any.whl", "a") as z:
        z.writestr(_release_undeclared, "SECRET=2\n")
    code, out, _ = cli("release", "audit")
    assert code == 1 and "p/other.env" in out


def test_REQ_006_without_its_decision_the_declaration_does_not_exempt(cli, proj):
    add(proj, '\n[release]\n[[release.shipped_secret]]\npath = "p/config/*.env"\nreason = "r"\ndecision = "2026-01-01: nowhere"\n')
    _release(cli, proj, "p/config/service.env")
    code, out, _ = cli("release", "audit")
    assert code == 1 and "service.env" in out


# ---------------------------------------------------------------- REQ-016: attribution ledger
def test_REQ_016_self_scoring_and_silent_overrides_fail(cli, proj):
    add(proj, "\n[agents]\n")
    assert cli("agents", "attempt", "T-1", "--agent", "a1", "--provider", "p", "--model", "m-1",
               "--suggested", "m-1", "--started", "2026-11-23T10:00:00Z", "--ended", "2026-11-23T11:00:00Z")[0] == 0
    _, out, _ = cli("check", "--repo", proj, "agents", "--format", "json")
    assert one(json.loads(out), "R-62")["status"] == "PASS"
    code, _, err = cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a1", "--score", "4", "--rubric", "r")
    assert code == 64 and "author" in err  # refused at the command
    assert cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a2", "--score", "4", "--rubric", "r")[0] == 0
    assert cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a3", "--score", "2", "--rubric", "r")[0] == 64
    assert cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a3", "--score", "2", "--rubric", "r",
               "--override", "rubric misread")[0] == 0
    _, rep = cli.check(proj, "agents")
    assert one(rep, "R-62")["status"] == "PASS"


def test_REQ_016_an_edited_earlier_score_fails(cli, proj):
    add(proj, "\n[agents]\n")
    cli("agents", "attempt", "T-1", "--agent", "a1", "--provider", "p", "--model", "unknown")
    cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a2", "--score", "4", "--rubric", "r")
    p = proj / "development/agents.jsonl"
    p.write_text(p.read_text().replace('"score":4', '"score":5'))
    _, rep = cli.check(proj, "agents")
    assert one(rep, "R-62")["status"] == "FAIL"


def test_REQ_016_a_hand_written_self_score_fails(cli, proj):
    from steward.ledger import Ledger
    add(proj, "\n[agents]\n")
    cli("agents", "attempt", "T-1", "--agent", "a1", "--provider", "p", "--model", "m")
    Ledger(proj / "development/agents.jsonl", "agents").append(
        "score", {"task": "T-1", "attempt": 1, "scorer": "a1", "score": 5, "rubric": "r", "override": None})
    _, rep = cli.check(proj, "agents")
    res = one(rep, "R-62")
    assert res["status"] == "FAIL" and "R-62.self_scored" in codes(res)


# ---------------------------------------------------------------- REQ-007: dataset roles per consumer
DATASETS = '''schema = "steward.datasets/0.1"
[datasets.pool-a]
role = "development"
identifier = "TBD"
paths = ["data/a/*"]
consumers = { study1 = "spent", study2 = "development" }
[datasets.pool-b]
role = "development"
identifier = "TBD"
paths = ["data/b/*"]
consumers = { study1 = "reserved" }
[datasets.pool-c]
role = "census-only"
identifier = "TBD"
paths = ["data/c/*"]
'''


@pytest.mark.parametrize("dataset, consumer, use, allowed", [
    ("pool-a", "study2", "confirm", False),    # spent for study1: never confirmatory again, for anyone
    ("pool-a", "study2", "develop", True),
    ("pool-b", "study1", "develop", False),    # reserved for study1's later design
    ("pool-b", "study2", "develop", True),
    ("pool-c", "study1", "metadata", True),    # census-only: metadata only
    ("pool-c", "study1", "develop", False),
])
def test_REQ_007_access_answers_per_consumer_and_use(cli, proj, dataset, consumer, use, allowed):
    add(proj, "\n[integrity]\n")
    write(proj, "development/datasets.toml", DATASETS)
    code, out, _ = cli("integrity", "access", dataset, "--consumer", consumer, "--use", use)
    assert (code == 0) is allowed, out
    assert ("ALLOW" if allowed else "DENY") in out


# ---------------------------------------------------------------- REQ-008: staged gates and accrual
STAGES = '''
[[stages]]
name = "prepare"
reads = "metadata"
[[stages]]
name = "outcomes"
reads = "outcomes"
go = "2026-11-21: GO for the outcome stage"
[accrual]
stage = "outcomes"
minimum = 3
count_file = "work/count.json"
'''


def test_REQ_008_outcome_stage_needs_its_go_and_the_accrual_minimum(cli, proj):
    import sys
    add(proj, STAGES)
    ok = [sys.executable, "-c", "print('ran')"]
    assert cli("stage", "run", "prepare", "--", *ok)[0] == 0
    write(proj, "work/count.json", '{"count": 5}')
    code, _, err = cli("stage", "run", "outcomes", "--", *ok)
    assert code == 77 and "GO" in err
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-21: GO for the outcome stage\n")
    write(proj, "work/count.json", '{"count": 2}')
    code, _, err = cli("stage", "run", "outcomes", "--", *ok)
    assert code == 77 and "minimum" in err
    write(proj, "work/count.json", '{"count": 3}')
    assert cli("stage", "run", "outcomes", "--", *ok)[0] == 0
    _, rep = cli.check(proj, "stages")
    assert one(rep, "R-68")["status"] == "PASS", one(rep, "R-68")


def test_REQ_008_a_recorded_outcome_run_without_its_go_fails(cli, proj):
    from steward.ledger import Ledger
    add(proj, STAGES)
    led = Ledger(proj / "development/stages.jsonl", "stages")
    start = led.append("launch", {"stage": "outcomes", "reads": "outcomes", "go": None, "go_log": None, "count": 9})
    led.append("stage", {"stage": "outcomes", "reads": "outcomes", "go": None, "launch": start["seq"], "count": 9,
                         "exit_code": 0})
    _, rep = cli.check(proj, "stages")
    res = one(rep, "R-68")
    assert res["status"] == "FAIL" and "R-68.no_go" in codes(res)


# ---------------------------------------------------------------- REQ-009: run supervision
def test_REQ_009_a_silent_busy_job_survives_and_an_idle_one_is_stopped(cli, proj):
    import sys
    busy = "import time\nt=time.time()\nwhile time.time()-t<3: pass\n"
    code, _, err = cli("run", "--hang-cpu", "1", "--", sys.executable, "-c", busy)
    assert code == 0, err
    code, _, err = cli("run", "--hang-cpu", "1", "--", sys.executable, "-c", "import time; time.sleep(30)")
    assert code != 0 and "CPU" in err


def test_REQ_009_the_socket_timeout_reaches_the_job(cli, proj):
    import sys
    code, _, _ = cli("run", "--socket-timeout", "7", "--", sys.executable, "-c",
                     "import os, sys; sys.exit(0 if os.environ.get('STEWARD_SOCKET_TIMEOUT') == '7' else 3)")
    assert code == 0


def test_REQ_009_shards_are_balanced_longest_first(cli, proj):
    write(proj, "cost.json", json.dumps({"a": 10, "b": 9, "c": 5, "d": 4, "e": 3, "f": 1}))
    code, out, err = cli("shards", "plan", "--shards", "3", "--cost", "cost.json", "--out", "plan.json")
    assert code == 0, err
    plan = json.loads((proj / "plan.json").read_text())
    totals = plan["totals"]
    assert sorted(j for s in plan["shards"] for j in s) == list("abcdef")
    assert max(totals) - min(totals) <= 10 and plan["merge"]


# ---------------------------------------------------------------- REQ-010: power from development effects
@pytest.fixture
def contract(cli, example, monkeypatch):
    monkeypatch.chdir(example)
    return example


def _set_minimum(root, n, target=0.8):
    p = root / "benchmarks/expr-clf.contract.toml"
    p.write_text(p.read_text().replace('analysis = "confirmatory"',
                                       f'analysis = "confirmatory"\nminimum_units = {n}\npower_target = {target}', 1))


def test_REQ_010_power_table_and_minimum_units(cli, contract):
    write(contract, "dev/effects.json", json.dumps([0.9, 1.1, 0.7, 1.3, 0.8, 1.0, 1.2, 0.6, 0.95, 1.05]))
    _set_minimum(contract, 15)
    code, out, err = cli("benchmark", "power", "benchmarks/expr-clf.contract.toml", "--effects", "dev/effects.json",
                         "--test", "sign-flip", "--alpha", "0.05", "--shrink", "1,0.5", "--n", "5,15", "--reps", "200")
    assert code == 0, err
    rec = json.loads((contract / "benchmarks/expr-clf.power.json").read_text())
    assert {(r["n"], r["shrink"]) for r in rec["table"]} == {(5, 1.0), (5, 0.5), (15, 1.0), (15, 0.5)}
    again = cli("benchmark", "power", "benchmarks/expr-clf.contract.toml", "--effects", "dev/effects.json",
                "--test", "sign-flip", "--alpha", "0.05", "--shrink", "1,0.5", "--n", "5,15", "--reps", "200")
    assert json.loads((contract / "benchmarks/expr-clf.power.json").read_text()) == rec  # seeded: repeatable
    _, rep = cli.check(contract, "benchmark")
    assert one(rep, "R-67")["status"] == "PASS", one(rep, "R-67")


def test_REQ_010_too_few_units_for_the_target_is_incomplete(cli, contract):
    write(contract, "dev/effects.json", json.dumps([0.3, -0.2, 0.4, -0.1, 0.2, 0.1, -0.3, 0.5]))
    _set_minimum(contract, 5, 0.9)
    cli("benchmark", "power", "benchmarks/expr-clf.contract.toml", "--effects", "dev/effects.json",
        "--test", "bootstrap", "--alpha", "0.05", "--shrink", "1,0.5", "--n", "5", "--reps", "200")
    _, rep = cli.check(contract, "benchmark")
    res = one(rep, "R-67")
    assert res["status"] == "INCOMPLETE" and "R-67.underpowered" in codes(res), res


def test_REQ_010_minimum_units_without_a_power_record_is_incomplete(cli, contract):
    _set_minimum(contract, 10)
    _, rep = cli.check(contract, "benchmark")
    assert one(rep, "R-67")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- REQ-011: frozen sets (agent versions, fixtures)
def test_REQ_011_a_frozen_prompt_change_fails_until_re_recorded_with_a_decision(cli, proj):
    add(proj, '\n[[frozen]]\nname = "agent-v1"\nfiles = ["agents/v1/**"]\n')
    write(proj, "agents/v1/prompt.md", "You are a careful assistant.\n")
    write(proj, "agents/v1/tools.json", "[]\n")
    _, rep = cli.check(proj, "frozen")
    assert one(rep, "R-63")["status"] == "INCOMPLETE"
    assert cli("frozen", "record", "agent-v1")[0] == 0
    _, rep = cli.check(proj, "frozen")
    assert one(rep, "R-63")["status"] == "PASS"
    write(proj, "agents/v1/prompt.md", "You are a fast assistant.\n")
    _, rep = cli.check(proj, "frozen")
    res = one(rep, "R-63")
    assert res["status"] == "FAIL" and "R-63.changed" in codes(res)
    code, _, err = cli("frozen", "record", "agent-v1")
    assert code == 64 and "--decision" in err
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-23: agent-v1 prompt revised\n")
    assert cli("frozen", "record", "agent-v1", "--decision", "2026-11-23: agent-v1 prompt revised")[0] == 0
    _, rep = cli.check(proj, "frozen")
    assert one(rep, "R-63")["status"] == "PASS"


# ---------------------------------------------------------------- REQ-012: dependency upgrade parity
@git_needed
def test_REQ_012_a_pin_change_needs_a_complete_parity_record(cli, proj):
    add(proj, '\n[dependencies]\npins = ["requirements*.txt"]\n')
    write(proj, "requirements.txt", "numpy==1.26.4\nscanpy==1.10.1\n")
    git(proj)
    sh(proj, "git", "tag", "v1.0")
    write(proj, "requirements.txt", "numpy==1.26.4\nscanpy==1.11.0\n")
    sh(proj, "git", "commit", "-qam", "bump scanpy")
    _, rep = cli.check(proj, "dependencies")
    res = one(rep, "R-66")
    assert res["status"] == "INCOMPLETE" and "R-66.no_record" in codes(res), res
    write(proj, "development/upgrades/scanpy-1.11.toml",
          'schema = "steward.upgrade/0.1"\npackage = "scanpy"\nold = "1.10.1"\nnew = "1.11.0"\n'
          'approval = "2026-11-23: move scanpy to 1.11"\n'
          '[[harnesses]]\nname = "parity-a"\nverdict = "pass"\n[[harnesses]]\nname = "parity-b"\nverdict = "differs"\n')
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "record")
    _, rep = cli.check(proj, "dependencies")
    res = one(rep, "R-66")
    assert res["status"] == "INCOMPLETE" and "R-66.incomplete" in codes(res), res  # one harness not passed or accepted
    p = proj / "development/upgrades/scanpy-1.11.toml"
    p.write_text(p.read_text().replace('verdict = "differs"', 'verdict = "accepted"\nnote = "within tolerance"'))
    sh(proj, "git", "commit", "-qam", "accepted")
    _, rep = cli.check(proj, "dependencies")
    assert one(rep, "R-66")["status"] == "PASS", one(rep, "R-66")


# ---------------------------------------------------------------- REQ-003: container build-context audit
@pytest.fixture
def ctx_proj(cli, proj, tmp_path):
    add(proj, '\n[containers]\ncontexts = ["svc"]\nmax_unignored_mb = 1\n')
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    write(proj, "svc/app.py", "x = 1\n")
    write(proj, "svc/.dockerignore", "backup.old/\n.env\n")
    return proj


def test_REQ_003_a_clean_context_passes(cli, ctx_proj):
    _, rep = cli.check(ctx_proj, "containers")
    assert one(rep, "R-64")["status"] == "PASS", one(rep, "R-64")


@pytest.mark.parametrize("mutate, code", [
    (lambda r, t: write(r, "svc/big.old/blob.bin", "x" * (2 << 20)), "R-64.large_folder"),
    (lambda r, t: write(r, "svc/conf/.env.local", "SECRET=1\n"), "R-64.secret_file"),
    (lambda r, t: (t / "external").mkdir() or (r / "svc/data").symlink_to(t / "external"), "R-64.link_outside"),
])
def test_REQ_003_each_hazard_fails_and_ignoring_it_passes(cli, ctx_proj, tmp_path, mutate, code):
    mutate(ctx_proj, tmp_path)
    _, rep = cli.check(ctx_proj, "containers")
    res = one(rep, "R-64")
    assert res["status"] == "FAIL" and code in codes(res), res
    with open(ctx_proj / "svc/.dockerignore", "a") as f:
        f.write("big.old/\nconf/\ndata\n")
    _, rep = cli.check(ctx_proj, "containers")
    assert one(rep, "R-64")["status"] == "PASS", one(rep, "R-64")


# ---------------------------------------------------------------- REQ-004: images and archives in the manifest
def _docker_save(path, tags):
    import io
    import tarfile
    data = json.dumps([{"RepoTags": tags, "Config": "c.json", "Layers": []}]).encode()
    with tarfile.open(path, "w:gz") as t:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))


def test_REQ_004_manifest_records_images_and_verify_checks_the_bundle(cli, proj):
    import zipfile
    add(proj, "\n[release]\n")
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        write(proj, name, text)
    (proj / "dist").mkdir()
    with zipfile.ZipFile(proj / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
    (proj / "bundle").mkdir()
    _docker_save(proj / "bundle/app-amd64.tar.gz", ["app:1.0"])
    _docker_save(proj / "bundle/app-arm64.tar.gz", ["app:1.0-arm64"])
    d = "sha256:" + "a" * 64
    code, _, err = cli("release", "manifest", "--image", f"app:1.0={d}@linux/amd64",
                       "--image", f"app:1.0-arm64={d}@linux/arm64", "--archives", "bundle")
    assert code == 0, err
    man = json.loads((proj / "release-manifest.json").read_text())
    assert len(man["images"]) == 2 and set(man["archives"]) == {"app-amd64.tar.gz", "app-arm64.tar.gz"}
    code, out, _ = cli("release", "verify", "bundle")
    assert code == 0, out
    with open(proj / "bundle/app-arm64.tar.gz", "ab") as f:
        f.write(b"corrupt")
    code, out, _ = cli("release", "verify", "bundle")
    assert code == 1 and "app-arm64.tar.gz" in out
    (proj / "bundle/app-arm64.tar.gz").unlink()
    code, out, _ = cli("release", "verify", "bundle")
    assert code == 1 and "MISSING image app:1.0-arm64" in out


# ---------------------------------------------------------------- REQ-005: compose and environment parity
COMPOSE = """services:
  web:
    build: ./svc
    environment:
      API_URL: http://api:8000
    volumes:
      - userdata:/srv/uploads
  api:
    build: ./svc
    env_file: [api.env]
volumes:
  userdata: {}
"""


@pytest.fixture
def compose(cli, proj):
    pytest.importorskip("yaml")
    add(proj, '\n[containers]\ncontexts = ["svc"]\ncompose = ["compose.yml"]\nship_with_image = ["svc/models/weights.bin"]\n'
              '[containers.urls]\nweb = ["API_URL"]\napi = ["DB_URL"]\n[containers.user_data]\nweb = ["/srv/uploads"]\n')
    write(proj, "compose.yml", COMPOSE)
    write(proj, "api.env", "DB_URL=postgres://db/x\n")
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    write(proj, "svc/models/weights.bin", "w")
    write(proj, "svc/.dockerignore", "*.old\n")
    return proj


def test_REQ_005_a_consistent_compose_passes(cli, compose):
    _, rep = cli.check(compose, "containers")
    assert one(rep, "R-65")["status"] == "PASS", one(rep, "R-65")


@pytest.mark.parametrize("mutate, code", [
    (lambda r: write(r, "api.env", "OTHER=1\n"), "R-65.missing_key"),
    (lambda r: write(r, "compose.yml", COMPOSE.replace("userdata:/srv/uploads", "./local:/srv/uploads")), "R-65.user_data_not_volume"),
    (lambda r: write(r, "svc/.dockerignore", "models/\n"), "R-65.ship_ignored"),
])
def test_REQ_005_each_mismatch_fails_with_the_service_named(cli, compose, mutate, code):
    mutate(compose)
    _, rep = cli.check(compose, "containers")
    res = one(rep, "R-65")
    assert res["status"] == "FAIL" and code in codes(res), res
