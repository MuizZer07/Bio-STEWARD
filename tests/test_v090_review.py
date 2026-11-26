"""The Codex pre-release review of 711db5d (development/assessment/2026-11-23-review-v0.9.0-711db5d.md): one test (or
more) per finding, named after its ID."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import codes, gate, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STEWARD_CONFIG_OVERLAY", raising=False)


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


# ---------------------------------------------------------------- Q4: session end never signals what it did not start
def test_Q4_a_matching_pid_of_another_program_is_never_signalled(cli, proj):
    import psutil
    add(proj, "\n[session]\n")
    git(proj)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (proj / ".steward").mkdir(exist_ok=True)
        (proj / f".steward/mcp-{other.pid}.pid").write_text(
            json.dumps({"pid": other.pid, "created": psutil.Process(other.pid).create_time()}))
        cli("session", "close", "--decisions-logged", "--next", "x", "--end", "--allow-dirty")
        assert other.poll() is None
    finally:
        other.kill()


def test_Q4_K1_a_ledger_entry_without_a_held_lock_never_leads_to_a_signal(cli, proj):
    import psutil
    from steward import session as ss
    from steward.ledger import Ledger
    from steward.models import load_config
    add(proj, "\n[session]\n")
    look = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "steward", "run"])
    try:
        Ledger(proj / "development/runs.jsonl", "runs").append(
            "started", {"run": "r1", "pid": look.pid, "pid_created": psutil.Process(look.pid).create_time()})
        ss.end(proj, load_config(proj))
        assert look.poll() is None
    finally:
        look.kill()


# ---------------------------------------------------------------- Q5: cleanup never deletes unrelated trees
@git_needed
def test_Q5_a_look_alike_worktree_outside_the_temp_folder_is_kept(cli, proj, tmp_path):
    from steward import session as ss
    from steward.models import load_config
    add(proj, "\n[session]\n")
    git(proj)
    look = tmp_path / "steward-push-mine" / "wt"
    sh(proj, "git", "worktree", "add", "--detach", "-q", str(look))
    (tmp_path / "steward-push-mine" / "notes.txt").write_text("keep me")
    ss.end(proj, load_config(proj))
    assert (tmp_path / "steward-push-mine" / "notes.txt").is_file() and look.is_dir()


def test_Q5_a_linked_steward_folder_is_not_followed(cli, proj, tmp_path):
    from steward import session as ss
    from steward.models import load_config
    add(proj, "\n[session]\n")
    outside = tmp_path / "outside"
    (outside / "cache").mkdir(parents=True)
    (outside / "cache" / "precious").write_text("x")
    shutil.rmtree(proj / ".steward", ignore_errors=True)
    (proj / ".steward").symlink_to(outside)
    ss.end(proj, load_config(proj))
    assert (outside / "cache" / "precious").is_file()


# ---------------------------------------------------------------- Q6: writers never follow a linked parent
@pytest.mark.parametrize("writer", ["frozen", "handoff"])
def test_Q6_record_writers_refuse_a_linked_parent(cli, proj, tmp_path, writer):
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(proj / "development")
    (proj / "development").symlink_to(outside)
    if writer == "frozen":
        add(proj, '\n[[frozen]]\nname = "a"\nfiles = ["x.txt"]\n')
        write(proj, "x.txt", "x")
        cli("frozen", "record", "a")
    else:
        add(proj, "\n[session]\n")
        cli("session", "close", "--decisions-logged", "--next", "x", "--allow-dirty")
    assert not any(outside.rglob("*")), list(outside.rglob("*"))


# ---------------------------------------------------------------- Q7: hooks activate an original only through --chain
@git_needed
def test_Q7_a_stray_local_hook_is_neither_chained_nor_restored(cli, proj):
    git(proj)
    hooks = proj / ".git/hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit.local").write_text("#!/bin/sh\nexit 0\n")
    code, out, _ = cli("hooks", "install")
    assert "refused" in out and "pre-commit.local" in out
    assert not (hooks / "pre-commit").exists() or "chained" not in (hooks / "pre-commit").read_text()
    cli("hooks", "remove")
    assert not (hooks / "pre-commit").exists() and (hooks / "pre-commit.local").exists()


def test_Q7_the_chained_pre_push_stops_when_its_input_cannot_be_saved():
    from steward import hooks as hk
    text = hk.render_chained("pre-push", "default", [])
    assert 'cat > "$tmp" || { rm -f "$tmp"; exit 1; }' in text


# ---------------------------------------------------------------- Q8: recovery never truncates without a verified copy
def test_Q8_an_unrelated_file_in_the_quarantine_slot_is_not_trusted(tmp_path):
    import hashlib
    from steward.ledger import Ledger, verify
    p = tmp_path / "led" / "log.jsonl"
    led = Ledger(p, "t")
    led.append("x", {})
    tail = b'{"seq": 2, "torn'
    with open(p, "ab") as f:
        f.write(tail)
    q = p.parent / (p.name + ".quarantine")
    q.mkdir()
    digest = hashlib.sha256(tail).hexdigest()
    (q / f"2-{digest[:16]}.partial").write_bytes(b"partial")  # a failed earlier write
    led.recover()
    saved = [f.read_bytes() for f in q.iterdir()]
    assert tail in saved and not verify(p).torn_tail


# ---------------------------------------------------------------- Q9: rollback only removes what it created
def test_Q9_rollback_leaves_a_replaced_entry_alone(cli, proj):
    from steward import exchange as xc
    add(proj, '\n[exchange]\ncode = "ABC"\n')
    cli("exchange", "init")
    dest = xc.write_new(proj, "outbox", "ABC-REQ-009.md", b"x")
    dest.rename(dest.with_name("moved-away.md"))  # kept, so its inode cannot be reused for the replacement (Linux)
    dest.write_text("someone else's file")
    xc.rollback(proj, dest)
    assert dest.read_text() == "someone else's file"


# ---------------------------------------------------------------- Q30: the shipped-secret exception is narrow
CFF = "cff-version: 1.2.0\nmessage: m\ntitle: t\nauthors:\n  - name: n\n"


def _wheel(proj, members):
    import zipfile
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        write(proj, name, text)
    (proj / "dist").mkdir(exist_ok=True)
    with zipfile.ZipFile(proj / "dist/p-1.0-py3-none-any.whl", "w") as z:
        for m, data in members.items():
            z.writestr(m, data)


@pytest.mark.parametrize("member, decision_text, refused", [
    ("development/notes.md", "## 2026-11-20: ship it\n", True),                  # not secret-like: never waived
    ("p/config/service.env", "a body line mentioning 2026-11-20: ship it\n", True),  # a mention, not the heading
    ("p/config/service.env", "## 2026-11-20: ship it\n", False),
])
def test_Q30_only_a_secret_like_member_with_its_decision_heading_is_waived(cli, proj, member, decision_text, refused,
                                                                        monkeypatch):
    from steward import authorize as az
    monkeypatch.setattr(az, "verify", lambda *a, **k: object())  # a verified `waive` (R19; signing is tested elsewhere)
    add(proj, f'\n[policy]\nstate = "pending"\n[release]\n[[release.shipped_secret]]\npath = "{member}"\nreason = "r"\n'
              'decision = "2026-11-20: ship it"\nauthorization = "steward/auth/0"\n')
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n" + decision_text)
    _wheel(proj, {"p/__init__.py": "x = 1\n", member: "TOKEN=1\n"})
    code, out, _ = cli("release", "audit")
    assert (code == 1) is refused, out


def test_Q30_a_waived_member_is_still_scanned_for_local_paths(cli, proj, monkeypatch):
    from steward import authorize as az
    monkeypatch.setattr(az, "verify", lambda *a, **k: object())
    add(proj, '\n[policy]\nstate = "pending"\n[release]\n[[release.shipped_secret]]\npath = "p/service.env"\nreason = "r"\n'
              'decision = "2026-11-20: ship it"\nauthorization = "steward/auth/0"\n')
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-20: ship it\n")
    _wheel(proj, {"p/__init__.py": "x\n", "p/service.env": "CERT=/" "Users/someone/key.pem\n"})  # steward: allow R-07 (example)
    code, out, _ = cli("release", "audit")
    assert code == 1 and "local_path" in out


# ---------------------------------------------------------------- Q32: interruption and CPU progress
def test_Q32_descendants_never_outlive_the_run(cli, proj, tmp_path):
    marker = tmp_path / "child.pid"
    prog = (f"import subprocess, sys\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"open({str(marker)!r}, 'w').write(str(p.pid))\n")
    cli("run", "--", sys.executable, "-c", prog)  # the leader exits at once, leaving its child
    import psutil
    pid = int(marker.read_text())
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_Q32_a_busy_successor_worker_counts_as_progress():
    from steward import runner as rn

    class P:
        def __init__(self, pid, cpu):
            self.pid, self.cpu = pid, cpu

        def create_time(self):
            return float(self.pid)

        def cpu_times(self):
            return type("T", (), {"user": self.cpu, "system": 0.0})()
    state = {"at": 0.0}
    seq = [[P(1, 50.0)], [P(2, 1.0)], [P(2, 3.0)], [P(2, 5.0)]]
    import steward.runner as mod
    orig = mod._tree
    try:
        for i, procs in enumerate(seq):
            mod._tree = lambda _ps, procs=procs: procs
            assert not rn._cpu_progress(None, float(i), 0.5, state), i  # every step makes progress
    finally:
        mod._tree = orig


# ---------------------------------------------------------------- Q33: a seal holds for every consumer
DATASETS = '''schema = "steward.datasets/0.1"
[datasets.held]
role = "sealed"
identifier = "TBD"
paths = ["data/held/*"]
consumers = { study1 = "development" }
'''


def test_Q33_a_consumer_role_cannot_override_an_active_seal(cli, proj):
    add(proj, "\n[integrity]\n")
    write(proj, "development/datasets.toml", DATASETS)
    code, out, _ = cli("integrity", "access", "held", "--consumer", "study1", "--use", "develop")
    assert code == 1 and "sealed" in out


def test_Q33_an_unusable_ledger_gives_no_answer(cli, proj):
    add(proj, "\n[integrity]\n")
    write(proj, "development/datasets.toml", DATASETS.replace('role = "sealed"', 'role = "development"'))
    write(proj, "development/integrity.jsonl", '{"torn')
    code, _, err = cli("integrity", "access", "held", "--consumer", "study1", "--use", "develop")
    assert code == 64 and "not intact" in err


# ---------------------------------------------------------------- Q1 - Q3: the overlay
def test_Q1_added_rules_never_satisfy_the_base_gates_minimum(cli, proj):
    add(proj, '\n[gates.push]\nrequire = ["R-01", "R-05"]\nmin_evaluated = 2\n')
    _, rep = cli.check(proj, gate="push")
    assert not gate(rep, "push")["eligible"]  # R-05 is not applicable: only one rule evaluated
    write(proj, "steward.local.toml", '[gates.push]\nrequire = ["R-61"]\n')  # R-61 passes everywhere
    _, rep = cli.check(proj, gate="push")
    assert not gate(rep, "push")["eligible"], gate(rep, "push")


def test_Q2_an_added_prior_work_glob_keeps_the_relocated_default(cli, proj):
    text = (proj / "steward.toml").read_text().replace("[paths]\n", '[paths]\nrecords = "process"\n', 1)
    if "[paths]" not in text:
        text += '\n[paths]\nrecords = "process"\n'
    (proj / "steward.toml").write_text(text)
    write(proj, "process/prior_work/bad.prior.toml", "not = [valid\n")
    _, rep = cli.check(proj, "prior-work")
    before = one(rep, "R-05")["status"] if [r for r in rep["verdict"]["results"] if r["rule"] == "R-05"] else None
    write(proj, "steward.local.toml", '[paths]\nprior_work = ["elsewhere/**/*.prior.toml"]\n')
    _, rep = cli.check(proj, "prior-work")
    statuses = {r["status"] for r in rep["verdict"]["results"] if r["rule"] == "R-05"}
    assert before == "FAIL" and "FAIL" in statuses, (before, statuses)


def test_Q3_commands_see_the_same_effective_configuration_as_r01(cli, proj):
    write(proj, "steward.local.toml", '[paths]\nprior_work = ["../outside/*.prior.toml"]\n')
    _, rep = cli.check(proj)
    assert one(rep, "R-01")["status"] == "FAIL"
    code, _, err = cli("exchange", "status")  # any command that loads the configuration
    assert code == 64 and "not valid" in err


def test_Q3_the_command_line_names_an_overlay_and_errors_omit_its_path(cli, proj, tmp_path):
    secret_dir = tmp_path / "private-name-xyz"
    code, out, err = cli("check", "--config-overlay", str(secret_dir / "missing.toml"), "--format", "json")
    assert "private-name-xyz" not in out + err


# ---------------------------------------------------------------- Q12: R-38 history
ENTRY = '\n## 2026-11-20: x\n- **Quote:** "q"\n- **Decision:** d\n- **Consequences:** c\n'


@pytest.fixture
def hist(cli, proj):
    add(proj, '\n[integrity]\ndecisions_format = "template"\n')
    (proj / "development/DECISIONS.md").unlink()
    git(proj)
    sh(proj, "git", "checkout", "-q", "-b", "dev")
    write(proj, "development/DECISIONS.md", "# D\n" + ENTRY)
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "log")
    return proj


@git_needed
def test_Q12_a_log_deleted_and_recreated_is_not_a_fresh_history(cli, hist):
    sh(hist, "git", "rm", "-q", "development/DECISIONS.md")
    sh(hist, "git", "commit", "-qm", "remove")
    write(hist, "development/DECISIONS.md", "# D\n" + ENTRY.replace('"q"', '"rewritten"'))
    sh(hist, "git", "add", "-A")
    sh(hist, "git", "commit", "-qm", "re-create")
    _, rep = cli.check(hist, "integrity")
    assert one(rep, "R-38")["status"] == "FAIL", one(rep, "R-38")


@git_needed
def test_Q12_history_that_cannot_be_listed_is_unknown(cli, hist, monkeypatch):
    from steward import fsutil
    real = fsutil.git_run

    def failing(root, *args, **kw):
        if args and args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 128, "", "boom")
        return real(root, *args, **kw)
    monkeypatch.setattr(fsutil, "git_run", failing)
    _, rep = cli.check(hist, "integrity")
    assert one(rep, "R-38")["status"] == "UNKNOWN", one(rep, "R-38")


@git_needed
def test_Q12_a_globbed_log_deleted_since_the_base_fails(cli, proj):
    add(proj, '\n[integrity]\ndecisions = ["development/DECISIONS.md", "studies/*/DECISIONS.md"]\n')
    write(proj, "studies/a/DECISIONS.md", "# A\n" + ENTRY)
    git(proj)
    sh(proj, "git", "checkout", "-q", "-b", "task")
    sh(proj, "git", "rm", "-q", "studies/a/DECISIONS.md")
    sh(proj, "git", "commit", "-qm", "drop a study log")
    _, rep = cli.check(proj, "integrity")
    res = one(rep, "R-38")
    assert res["status"] == "FAIL" and "R-38.log_removed" in codes(res), res


# ---------------------------------------------------------------- Q13: R-52 repro
REPRO = '''schema = "steward.repro/0.1"
id = "r1"
manifest = "bench/MANIFEST.json"
reference = "bench/ref"
canonical = "json-sorted"
[compare]
default = "{default}"
'''


@pytest.fixture
def repro(cli, proj):
    add(proj, '\n[repro]\ncontracts = ["bench/*.repro.toml"]\n')
    write(proj, "bench/r.repro.toml", REPRO.format(default="exact"))
    write(proj, "bench/ref/out.json", '{"a": 0.5}')
    cli("repro", "manifest", "r1", "--from", "bench/ref")
    git(proj)
    return proj


def test_Q13_a_number_and_its_text_are_different_outputs(cli, repro, tmp_path):
    w = tmp_path / "w"
    write(w, "out.json", '{"a": "0.5"}')
    code, out, _ = cli("repro", "check", "r1", "--work", w)
    assert code == 1, out


def test_Q13_an_empty_manifest_never_passes(cli, repro, tmp_path):
    write(repro, "bench/MANIFEST.json", '{"schema": "steward.repro_manifest/0.1", "files": {}}')
    code, out, err = cli("repro", "check", "r1", "--work", tmp_path)
    assert code != 0, out


def test_Q13_a_stale_reference_cannot_widen_a_tolerance(cli, repro, tmp_path):
    write(repro, "bench/r.repro.toml", REPRO.format(default="abs:0.5"))
    write(repro, "bench/ref/out.json", '{"a": 0.9}')  # the reference changed after the manifest
    w = tmp_path / "w"
    write(w, "out.json", '{"a": 0.95}')
    code, out, _ = cli("repro", "check", "r1", "--work", w)
    assert code == 1 and "reference" in out, out


def test_Q13_a_torn_ledger_and_duplicate_ids_block(cli, repro, tmp_path):
    w = tmp_path / "w"
    write(w, "out.json", '{"a": 0.5}')
    assert cli("repro", "check", "r1", "--work", w)[0] == 0
    with open(repro / "development/repro.jsonl", "ab") as f:
        f.write(b'{"torn')
    _, rep = cli.check(repro, "repro")
    assert {r["status"] for r in rep["verdict"]["results"] if r["rule"] == "R-52"} == {"FAIL"}
    write(repro, "bench/r2.repro.toml", REPRO.format(default="exact"))  # the same id again
    _, rep = cli.check(repro, "repro")
    assert "FAIL" in {r["status"] for r in rep["verdict"]["results"] if r["rule"] == "R-52"}


# ---------------------------------------------------------------- Q23: stages
STAGES = '''
[[stages]]
name = "outcomes"
reads = "outcomes"
go = "2026-11-21: GO for outcomes"
'''


def test_Q23_a_mention_is_not_a_go_and_a_blocked_ledger_prevents_launch(cli, proj, tmp_path):
    add(proj, STAGES)
    marker = tmp_path / "ran"
    cmd = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')"]
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\nWe might write 2026-11-21: GO for outcomes later.\n")
    assert cli("stage", "run", "outcomes", "--", *cmd)[0] == 77 and not marker.exists()
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-21: GO for outcomes\n")
    (proj / "development/stages.jsonl").mkdir()  # the record cannot be written
    assert cli("stage", "run", "outcomes", "--", *cmd)[0] != 0 and not marker.exists()


def test_Q23_a_run_record_without_its_launch_evidence_fails(cli, proj):
    from steward.ledger import Ledger
    add(proj, STAGES)
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-21: GO for outcomes\n")
    Ledger(proj / "development/stages.jsonl", "stages").append(
        "stage", {"stage": "outcomes", "reads": "outcomes", "go": "2026-11-21: GO for outcomes", "count": None, "exit_code": 0})
    _, rep = cli.check(proj, "stages")
    res = one(rep, "R-68")
    assert res["status"] == "FAIL" and "R-68.no_launch" in codes(res), res


# ---------------------------------------------------------------- Q25: R-64
@pytest.fixture
def ctxp(cli, proj):
    add(proj, '\n[containers]\ncontexts = ["svc"]\ndev_only = ["svc/scratch"]\n')
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    write(proj, "svc/.dockerignore", "conf/\n")
    return proj


def test_Q25_a_re_included_secret_is_found(cli, ctxp):
    write(ctxp, "svc/conf/.env", "S=1\n")
    write(ctxp, "svc/.dockerignore", "conf/\n!conf/.env\n")
    _, rep = cli.check(ctxp, "containers")
    assert "R-64.secret_file" in codes(one(rep, "R-64"))


def test_Q25_regular_files_in_a_dev_only_folder_are_found(cli, ctxp):
    write(ctxp, "svc/scratch/data.bin", "x")
    _, rep = cli.check(ctxp, "containers")
    res = one(rep, "R-64")
    assert res["status"] == "FAIL" and "R-64.dev_only" in codes(res), res


def test_Q25_a_linked_context_root_is_refused(cli, proj, tmp_path):
    add(proj, '\n[containers]\ncontexts = ["svc"]\n')
    (tmp_path / "elsewhere").mkdir()
    (proj / "svc").symlink_to(tmp_path / "elsewhere")
    _, rep = cli.check(proj, "containers")
    res = one(rep, "R-64")
    assert res["status"] == "FAIL" and "R-64.link_context" in codes(res), res


@git_needed
def test_Q25_pre_push_refuses_a_link_inside_a_declared_context(cli, proj, tmp_path):
    from steward import hooks as hk
    add(proj, '\n[containers]\ncontexts = ["svc"]\n')
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    (proj / "svc/data").symlink_to("/tmp")
    git(proj)
    dest = tmp_path / "stage"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="build context"):
        hk.materialize(proj, sh(proj, "git", "rev-parse", "HEAD"), dest)


# ---------------------------------------------------------------- Q10, Q11: exchange binding
def _xrepo(cli, path, code, extra=""):
    path.mkdir()
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.name", "T")
    sh(path, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", path)
    with open(path / "steward.toml", "a") as f:
        f.write(f'\n[exchange]\ncode = "{code}"\n{extra}')
    cwd = os.getcwd()
    os.chdir(path)
    try:
        cli("exchange", "init")
    finally:
        os.chdir(cwd)
    sh(path, "git", "add", "-A")
    sh(path, "git", "commit", "-qm", "init")
    return path


def test_Q11_receive_refuses_a_sender_other_than_the_peer(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    me = _xrepo(cli, tmp_path / "me", "AAA")
    item = ('+++\nschema = "steward.exchange/1"\nid = "ZZZ-REQ-001"\nkind = "request"\nfrom = "ZZZ"\nto = "AAA"\n'
            'title = "t"\nfiled = 2026-11-23\n+++\n')
    with pytest.raises(ValueError, match="peer"):
        xc.receive(me, "r", "AAA", item.encode(), {"from": "PPP", "commit": "0" * 40})
    assert not (me / "exchange/inbox/ZZZ-REQ-001.md").exists()


def test_Q11_a_response_from_the_wrong_counterparty_is_refused(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    me = _xrepo(cli, tmp_path / "me", "AAA")
    monkeypatch.chdir(me)
    cli("exchange", "new", "request", "--to", "BBB", "--title", "t")
    rsp = ('+++\nschema = "steward.exchange/1"\nid = "CCC-RSP-001"\nkind = "response"\nfrom = "CCC"\nto = "AAA"\n'
           'title = "Re"\nfiled = 2026-11-23\nresponds_to = "AAA-REQ-001"\n+++\n## Decision\naccepted: x\n')
    with pytest.raises(ValueError, match="addressed"):
        xc.receive(me, "r", "AAA", rsp.encode(), {"from": "CCC", "commit": "0" * 40})


def test_Q10_a_failed_observation_is_recorded_on_retry(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    me = _xrepo(cli, tmp_path / "me", "AAA")
    monkeypatch.chdir(me)
    cli("exchange", "new", "request", "--to", "BBB", "--title", "t")
    rsp = ('+++\nschema = "steward.exchange/1"\nid = "BBB-RSP-001"\nkind = "response"\nfrom = "BBB"\nto = "AAA"\n'
           'title = "Re"\nfiled = 2026-11-23\nresponds_to = "AAA-REQ-001"\n+++\n## Decision\nverified: x\n')
    real = xc.observe
    monkeypatch.setattr(xc, "observe", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        xc.receive(me, "r", "AAA", rsp.encode(), {"from": "BBB", "commit": "0" * 40})
    monkeypatch.setattr(xc, "observe", real)
    xc.receive(me, "r", "AAA", rsp.encode(), {"from": "BBB", "commit": "0" * 40})
    assert [e["state"] for e in xc.observations(me).get("AAA-REQ-001", [])] == ["verified"]


# ---------------------------------------------------------------- Q14: R-54 says what it verified
def test_Q14_an_item_without_a_receipt_hash_is_not_called_verified(cli, tmp_path, monkeypatch):
    from steward import exchange as xc
    me = _xrepo(cli, tmp_path / "me", "AAA")
    monkeypatch.chdir(me)
    write(me, "exchange/inbox/BBB-REQ-001.md", '+++\nschema = "steward.exchange/1"\nid = "BBB-REQ-001"\nkind = "request"\n'
          'from = "BBB"\nto = "AAA"\ntitle = "t"\nfiled = 2026-11-23\n+++\n')
    xc.set_state(me, "r", "BBB-REQ-001", "acknowledged", "legacy", "AAA", False)
    _, rep = cli.check(me, "governance")
    res = one(rep, "R-54")
    assert "R-54.receipt_unverified" in codes(res) and "as received" not in res["reason"], res


# ---------------------------------------------------------------- Q15: staged is not committed
@git_needed
def test_Q15_a_staged_but_uncommitted_record_is_dirty(cli, proj):
    add(proj, "\n[session]\n")
    git(proj)
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-24: staged only\n")
    sh(proj, "git", "add", "development/DECISIONS.md")
    code, _, err = cli("session", "close", "--decisions-logged", "--next", "x")
    assert code == 1 and "DECISIONS.md" in err


# ---------------------------------------------------------------- Q16: R-56
BOUND = '\n[boundary]\npackages = ["src/lib"]\nforbidden_imports = ["pkg.secret"]\nforbidden_distributions = ["bad"]\nallow_groups = ["dev"]\n'


def test_Q16_a_forbidden_submodule_imported_from_its_parent_fails(cli, proj):
    add(proj, BOUND)
    write(proj, "src/lib/a.py", "from pkg import secret\n")
    _, rep = cli.check(proj, "boundary")
    assert one(rep, "R-56")["status"] == "FAIL"


def test_Q16_an_included_group_and_a_missing_pyproject_are_checked(cli, proj):
    add(proj, BOUND)
    write(proj, "src/lib/a.py", "import json\n")
    _, rep = cli.check(proj, "boundary")
    assert one(rep, "R-56")["status"] == "INCOMPLETE"  # forbidden distributions declared, no pyproject to check
    write(proj, "pyproject.toml", '[project]\nname = "x"\n[dependency-groups]\ndev = ["bad"]\ntest = [{include-group = "dev"}]\n')
    _, rep = cli.check(proj, "boundary")
    assert one(rep, "R-56")["status"] == "FAIL"


# ---------------------------------------------------------------- Q17: R-57
def test_Q17_a_prose_mention_is_not_a_board_entry(cli, proj):
    add(proj, '\n[tasks]\nspecs = ["tasks/*.md"]\nboard = "BOARD.md"\nid_pattern = "T-\\\\d{3}"\n')
    write(proj, "tasks/a.md", "- **ID:** T-001\n- **Status:** in progress\n")
    write(proj, "BOARD.md", "# Board\n\nWe discussed T-001 at length.\n\nNext unused ID: T-002\n")
    _, rep = cli.check(proj, "tasks")
    assert "R-57.not_on_board" in codes(one(rep, "R-57"))


def test_Q17_the_next_id_must_match_the_pattern(cli, proj):
    add(proj, '\n[tasks]\nspecs = ["tasks/*.md"]\nboard = "BOARD.md"\nid_pattern = "T-\\\\d{3}"\n')
    write(proj, "BOARD.md", "# Board\n\nNext unused ID: banana\n")
    _, rep = cli.check(proj, "tasks")
    assert one(rep, "R-57")["status"] == "FAIL"


# ---------------------------------------------------------------- Q18: R-58
@pytest.fixture
def clog(cli, proj):
    add(proj, '\n[changelog]\nentry_pattern = "^- .+ \\\\(Status: [a-z]+\\\\)$"\nready = "ready"\n')
    write(proj, "CHANGELOG.md", "# C\n\n## Unreleased\n- old thing (Status: ready)\n\n## 1.0\n- x\n")
    write(proj, "src/x.py", "x = 1\n")
    git(proj)
    sh(proj, "git", "tag", "v1.0")
    return proj


@git_needed
def test_Q18_editing_only_an_older_section_is_not_an_unreleased_entry(cli, clog):
    write(clog, "src/x.py", "x = 2\n")
    write(clog, "CHANGELOG.md", "# C\n\n## Unreleased\n- old thing (Status: ready)\n\n## 1.0\n- x, reworded\n")
    sh(clog, "git", "commit", "-qam", "c")
    _, rep = cli.check(clog, "changelog")
    assert "R-58.not_updated" in codes(one(rep, "R-58"))


@git_needed
def test_Q18_final_readiness_is_checked_even_when_only_excluded_files_changed(cli, clog):
    write(clog, "CHANGELOG.md", "# C\n\n## Unreleased\n- new (Status: draft)\n\n## 1.0\n- x\n")
    sh(clog, "git", "commit", "-qam", "c")
    _, out, _ = cli("check", "--repo", clog, "--format", "json", "--final", "changelog")
    res = one(json.loads(out), "R-58")
    assert res["status"] == "FAIL" and "R-58.not_ready" in codes(res), res
    assert all("draft" not in json.dumps(d) for d in res["details"])  # diagnostics never copy the entry text


# ---------------------------------------------------------------- Q19: R-59
@git_needed
def test_Q19_an_unresolvable_since_is_unknown(cli, proj):
    add(proj, '\n[branches]\nrelease = "main"\nsince = "no-such-ref"\n')
    git(proj)
    _, rep = cli.check(proj, "branches")
    assert one(rep, "R-59")["status"] == "UNKNOWN"


# ---------------------------------------------------------------- Q20: R-60 links inside copies
def test_Q20_a_nested_link_difference_is_drift_and_targets_are_not_printed(cli, tmp_path):
    r = tmp_path / "s"
    r.mkdir()
    cli("init", "--repo", r, "--skills", ".agents/skills", "--skills", ".claude/skills")
    (r / ".claude/skills").unlink()
    shutil.copytree(r / ".agents/skills", r / ".claude/skills")
    (r / ".claude/skills/extra-link").symlink_to("/nonexistent/elsewhere/secret-dir")
    _, rep = cli.check(r, "skills")
    res = one(rep, "R-60")
    assert res["status"] == "FAIL" and "R-60.drift" in codes(res), res
    assert "secret-dir" not in json.dumps(res)


# ---------------------------------------------------------------- Q21: R-61 coverage
def test_Q21_a_large_text_file_is_still_scanned_and_the_marker_is_a_header(cli, proj):
    big = "x\n" * (1_200_000) + "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> o\n"
    write(proj, "data/big.txt", big)
    _, rep = cli.check(proj, "files")
    assert one(rep, "R-61")["status"] == "FAIL"
    write(proj, "data/big.txt", "x\n" * 50 + "steward: allow conflict-markers\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> o\n")
    _, rep = cli.check(proj, "files")
    assert one(rep, "R-61")["status"] == "FAIL"  # a marker buried in the body does not exempt the file


# ---------------------------------------------------------------- Q22: torn ledgers and blank overrides
def test_Q22_a_torn_attribution_ledger_and_a_blank_override_are_refused(cli, proj):
    add(proj, "\n[agents]\n")
    cli("agents", "attempt", "T-1", "--agent", "a1", "--provider", "p", "--model", "m")
    cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a2", "--score", "4", "--rubric", "r")
    code, _, _ = cli("agents", "score", "T-1", "--attempt", "1", "--scorer", "a3", "--score", "2", "--rubric", "r",
                     "--override", "   ")
    assert code == 64
    with open(proj / "development/agents.jsonl", "ab") as f:
        f.write(b'{"torn')
    _, rep = cli.check(proj, "agents")
    assert one(rep, "R-62")["status"] == "FAIL"


# ---------------------------------------------------------------- Q24: R-63 records
def test_Q24_an_empty_or_foreign_record_never_passes(cli, proj):
    add(proj, '\n[[frozen]]\nname = "a"\nfiles = ["agents/**"]\n')
    write(proj, "development/frozen/a.json", "{}")
    _, rep = cli.check(proj, "frozen")
    assert one(rep, "R-63")["status"] == "FAIL"


@git_needed
def test_Q24_a_changed_record_needs_its_decision_heading(cli, proj):
    add(proj, '\n[[frozen]]\nname = "a"\nfiles = ["agents/**"]\n')
    write(proj, "agents/p.md", "v1\n")
    cli("frozen", "record", "a")
    git(proj)
    write(proj, "agents/p.md", "v2\n")
    from steward.process import frozen_hashes
    from steward.models import load_config
    fs = load_config(proj).frozen[0]
    write(proj, "development/frozen/a.json", json.dumps({"schema": "steward.frozen/0.1", "name": "a",
                                                          "files": frozen_hashes(proj, fs), "decision": None}))
    _, rep = cli.check(proj, "frozen")
    res = one(rep, "R-63")
    assert res["status"] == "FAIL" and "R-63.no_decision" in codes(res), res


# ---------------------------------------------------------------- Q26: R-65 values and paths
COMPOSE = """services:
  web:
    environment:
      API_URL:
"""


def test_Q26_an_empty_url_a_missing_service_and_a_missing_shipped_file_are_not_passes(cli, proj):
    pytest.importorskip("yaml")
    add(proj, '\n[containers]\ncontexts = ["svc"]\ncompose = ["compose.yml"]\nship_with_image = ["svc/w.bin"]\n'
              '[containers.urls]\nweb = ["API_URL"]\n[containers.user_data]\nworker = ["/data"]\n')
    write(proj, "compose.yml", COMPOSE)
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    _, rep = cli.check(proj, "containers")
    res = one(rep, "R-65")
    assert res["status"] == "FAIL"
    assert {"R-65.missing_key", "R-65.unknown_service", "R-65.ship_missing"} <= codes(res), res


# ---------------------------------------------------------------- Q27: R-66 removals and records
@git_needed
def test_Q27_a_removed_pin_file_needs_a_record_and_records_need_their_schema(cli, proj):
    add(proj, '\n[dependencies]\npins = ["requirements*.txt"]\n')
    write(proj, "requirements-extra.txt", "scanpy==1.10.1\n")
    git(proj)
    sh(proj, "git", "tag", "v1.0")
    sh(proj, "git", "rm", "-q", "requirements-extra.txt")
    sh(proj, "git", "commit", "-qm", "drop")
    _, rep = cli.check(proj, "dependencies")
    assert one(rep, "R-66")["status"] == "INCOMPLETE"
    write(proj, "development/upgrades/x.toml", 'package = "scanpy"\nold = "1.10.1"\nnew = "removed"\napproval = "a"\n'
          '[[harnesses]]\nverdict = "pass"\n')  # no schema, an unnamed harness
    _, rep = cli.check(proj, "dependencies")
    assert one(rep, "R-66")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- Q28: R-67 tables
def test_Q28_an_incomplete_or_invalid_power_table_never_passes(cli, example, monkeypatch):
    monkeypatch.chdir(example)
    p = example / "benchmarks/expr-clf.contract.toml"
    p.write_text(p.read_text().replace('analysis = "confirmatory"', 'analysis = "confirmatory"\nminimum_units = 10', 1))
    write(example, "dev/e.json", "[1, 2, 3]")
    import hashlib
    sha = hashlib.sha256((example / "dev/e.json").read_bytes()).hexdigest()
    for table, contract in (([{"n": 10, "shrink": 1.0, "power": 1.5}], "expr-clf"),       # out of range
                            ([{"n": 10, "shrink": 1.0, "power": 0.99}], "another")):       # another contract
        write(example, "benchmarks/expr-clf.power.json", json.dumps({
            "schema": "steward.power/0.1", "contract": contract, "effects": "dev/e.json", "effects_sha256": sha,
            "shrinks": [1.0, 0.5], "sizes": [10], "test": "sign-flip", "alpha": 0.05, "table": table}))
        _, rep = cli.check(example, "benchmark")
        assert one(rep, "R-67")["status"] != "PASS", (table, contract)


# ---------------------------------------------------------------- Q29: release evidence
def test_Q29_verify_without_coverage_fails(cli, proj, tmp_path):
    add(proj, "\n[release]\n")
    write(proj, "release-manifest.json", json.dumps({"something": "else"}))
    (tmp_path / "empty").mkdir()
    code, out, err = cli("release", "verify", str(tmp_path / "empty"))
    assert code != 0


def test_Q29_a_bundle_record_bound_to_its_zip(cli, proj):
    import zipfile
    add(proj, "\n[release]\n")
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n")):
        write(proj, name, text)
    (proj / "dist").mkdir()
    with zipfile.ZipFile(proj / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
    write(proj, "golden/a.txt", "a\n")
    cli("release", "bundle", "g", "--paths", "golden", "--test-report", f"{sys.executable} -c pass")
    cli("release", "manifest")
    (proj / "dist/bundles/g.bundle.json").unlink()
    _, rep = cli.check(proj, "release")
    assert one(rep, "R-42")["status"] == "FAIL"


# ---------------------------------------------------------------- Q31: URLs and file URIs
@pytest.mark.parametrize("line, found", [
    ("https://example.org/api?file=/" "home/user2/data.csv", True),  # steward: allow R-07 (example)
    ("file://localhost/" "home/user2/x", True),  # steward: allow R-07 (example)
    ("https://example.org/" "home/about/", False),
])
def test_Q31_local_paths_in_queries_and_file_authorities_are_found(line, found):  # steward: allow R-07 (example)
    from steward import privacy as pv
    hits, _ = pv.scan_text(line, [], True)
    assert bool(hits) is found


# ---------------------------------------------------------------- R19: Article II.3 for the shipped-secret waiver
def test_R19_without_a_verified_waive_authorization_the_member_stays_refused(cli, proj):
    add(proj, '\n[release]\n[[release.shipped_secret]]\npath = "p/service.env"\nreason = "r"\ndecision = "2026-11-20: ship it"\n')
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-20: ship it\n")
    _wheel(proj, {"p/__init__.py": "x\n", "p/service.env": "T=1\n"})
    code, out, _ = cli("release", "audit")
    assert code == 1 and "service.env" in out


# ---------------------------------------------------------------- re-verification of f895128: R2, R8, R9, R13, R15, R21
def test_R2_a_short_write_never_replaces_a_record(tmp_path, monkeypatch):
    import os as _os
    from steward import fsutil
    (tmp_path / "rec.json").write_text("original")
    real = _os.write
    monkeypatch.setattr(_os, "write", lambda fd, data: 0 if len(data) > 2 else real(fd, data))
    with pytest.raises(OSError):
        fsutil.safe_write(tmp_path, "rec.json", b"a new record")
    monkeypatch.setattr(_os, "write", real)
    assert (tmp_path / "rec.json").read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["rec.json"]  # no temporary file left


@git_needed
def test_R8_a_sole_globbed_log_deleted_in_history_still_blocks(cli, proj):
    add(proj, '\n[integrity]\ndecisions = ["studies/*/DECISIONS.md"]\n')
    (proj / "development/DECISIONS.md").unlink()
    git(proj)
    write(proj, "studies/a/DECISIONS.md", "# A\n" + ENTRY)
    sh(proj, "git", "add", "-A")
    sh(proj, "git", "commit", "-qm", "add")
    sh(proj, "git", "rm", "-q", "studies/a/DECISIONS.md")
    sh(proj, "git", "commit", "-qm", "remove")
    _, rep = cli.check(proj, "integrity")
    assert one(rep, "R-38")["status"] == "FAIL", one(rep, "R-38")


def test_R9_recorded_zero_file_evidence_never_certifies(cli, repro):
    from steward.ledger import Ledger
    from steward import repro as rp
    write(repro, "bench/MANIFEST.json", '{"schema": "steward.repro_manifest/0.1", "files": {}}')
    commit, tree = rp.git_ids(repro)
    Ledger(repro / "development/repro.jsonl", "repro").append("repro", {
        "id": "r1", "contract": "bench/r.repro.toml", "contract_sha256": rp.sha_file(repro / "bench/r.repro.toml"),
        "manifest_sha256": rp.sha_file(repro / "bench/MANIFEST.json"), "commit": commit, "tree": tree,
        "result": "pass", "files": 0, "mismatch_count": 0})
    _, rep = cli.check(repro, "repro")
    assert one(rep, "R-52")["status"] == "FAIL"


def test_R13_a_heading_inside_a_code_example_is_not_a_go(cli, proj):
    add(proj, STAGES)
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n```\n## 2026-11-21: GO for outcomes\n```\n")
    assert cli("stage", "run", "outcomes", "--", sys.executable, "-c", "pass")[0] == 77


def test_R13_a_launch_after_its_outcome_or_with_other_reads_fails(cli, proj):
    from steward.ledger import Ledger
    add(proj, STAGES)
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-21: GO for outcomes\n")
    led = Ledger(proj / "development/stages.jsonl", "stages")
    start = led.append("launch", {"stage": "outcomes", "reads": "metadata", "go": "2026-11-21: GO for outcomes",
                                  "go_log": "development/DECISIONS.md", "count": None})
    led.append("stage", {"stage": "outcomes", "reads": "outcomes", "go": None, "launch": start["seq"], "exit_code": 0})
    _, rep = cli.check(proj, "stages")
    assert one(rep, "R-68")["status"] == "FAIL"


@git_needed
@pytest.mark.parametrize("spelling", ["./svc", "svc/", "."])
def test_R15_equivalent_context_spellings_are_matched_in_the_staged_tree(cli, proj, tmp_path, spelling):
    from steward import hooks as hk
    add(proj, f'\n[containers]\ncontexts = ["{spelling}"]\n')
    write(proj, "svc/Dockerfile", "FROM scratch\n")
    (proj / "svc/data").symlink_to("/tmp")
    git(proj)
    dest = tmp_path / "stage"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="build context"):
        hk.materialize(proj, sh(proj, "git", "rev-parse", "HEAD"), dest)


def test_R21_access_and_the_run_guard_agree_after_an_unseal(cli, proj):
    from steward import integrity as ig
    from steward.ledger import Ledger
    from steward.models import load_config
    add(proj, "\n[integrity]\n")
    write(proj, "development/datasets.toml", DATASETS.replace("consumers = { study1 = \"development\" }\n", ""))
    write(proj, "data/held/x.csv", "1\n")
    Ledger(proj / "development/integrity.jsonl", "integrity").append("unseal", {"dataset": "held"})
    cfg = load_config(proj)
    assert ig.sealed_owner(proj, cfg, "data/held/x.csv") is None          # spent: the run guard lets it in
    ok, why = ig.access(proj, cfg, "held", "study1", "develop")
    assert ok and "spent" in why                                          # and access agrees
