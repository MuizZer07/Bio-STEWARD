"""0.12.0 features: deferred signing (DESIGN_BRIEF_sprint §3) and the consumer items (RELEASE_v0.12.0_SPEC §3)."""

import shutil

import pytest

from conftest import codes, one
from test_authorize import expires, repo, sh  # noqa: F401  (the signed-authorization fixture)

signing = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")


def _change_policy(repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')


def _prepare(cli, obj, exp=None):
    code, out, err = cli("authorize", "prepare", "policy.change", "--object", obj, "--expires", exp or expires(),
                         "--summary", "add the quick gate")
    assert code == 0, err
    return out.split("authorize sign ")[1].strip()


# ---------------------------------------------------------------- D: deferred signing
@signing
def test_D_a_prepared_policy_change_is_incomplete_awaiting_signature_not_fail(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "FAIL"
    obj = next(d["value"] for d in res["details"] if d["code"] == "R-33.object")
    assert "--expires" in next(d["message"] for d in res["details"] if d["code"] == "R-33.object")  # the adopter's hint
    nonce = _prepare(cli, obj)
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "INCOMPLETE" and "R-33.awaiting_signature" in codes(res), res
    code, out, _ = cli("authorize", "pending")
    assert code == 0 and nonce[:12] in out and "waiting" in out and "1 waiting" in out
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0 and "signed steward/auth/" in out, err
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "PASS"
    _, out, _ = cli("authorize", "pending")
    assert "signed" in out and "0 waiting" in out


@signing
def test_D_an_edit_after_prepare_is_a_fail_again(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    _prepare(cli, obj)
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.other]\nrequire = ["R-01"]\n')
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"


@signing
def test_D_an_expired_preparation_does_not_hold_the_check(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    _prepare(cli, obj, exp="2020-01-01T00:00:00Z")
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"
    _, out, _ = cli("authorize", "pending")
    assert "expired" in out


@signing
def test_D_sign_pending_asks_and_refuses_without_a_terminal(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    _prepare(cli, obj)
    code, _, err = cli("authorize", "sign-pending")
    assert code == 64 and "--yes" in err
    assert sh(repo, "git", "tag", "-l", "steward/auth/*").strip() == ""


@signing
def test_D_a_forged_queue_file_is_never_a_pass(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    nonce = _prepare(cli, obj)
    p = repo / ".steward/pending" / f"{nonce}.txt"
    p.rename(p.with_name("0" * 32 + ".txt"))  # a payload whose name is not its nonce is ignored
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"


# ---------------------------------------------------------------- B9, B11, B10: R-59 and R-57 (DEF-029, REQ-018, DEF-030)
from test_v090_requests import TASKS, _add, _task, _write, git_needed  # noqa: E402
from test_v090_requests import branches, board, proj  # noqa: E402,F401
from test_v090_requests import sh as gsh  # noqa: E402


def _commit(root, name):
    _write(root, name, name + "\n")
    gsh(root, "git", "add", "-A")
    gsh(root, "git", "commit", "-qm", name)


@git_needed
@pytest.mark.parametrize("with_since, status", [(True, "PASS"), (False, "FAIL")])
def test_DEF_029_since_applies_after_the_last_tag(cli, branches, with_since, status):
    _commit(branches, "direct.txt")  # a direct commit on main after the tag v0.1: before the adoption point
    gsh(branches, "git", "checkout", "-q", "-b", "task/c")
    _commit(branches, "c.txt")
    gsh(branches, "git", "checkout", "-q", "main")
    gsh(branches, "git", "merge", "-q", "--no-ff", "-m", "merge task/c", "task/c")
    if with_since:
        _add(branches, f'since = "{gsh(branches, "git", "rev-parse", "HEAD~1")}"\n')  # appended to [branches]
    _, rep = cli.check(branches, "branches")
    res = one(rep, "R-59")
    assert res["status"] == status, res


def _release_by_merge(root, tag_it):
    gsh(root, "git", "checkout", "-q", "-b", "prep-v0.2", "main")
    _commit(root, "notes.txt")
    if tag_it:
        gsh(root, "git", "tag", "v0.2")
    gsh(root, "git", "checkout", "-q", "release")
    gsh(root, "git", "merge", "-q", "--no-ff", "-m", "release v0.2", "prep-v0.2")
    tip = gsh(root, "git", "rev-parse", "HEAD")
    gsh(root, "git", "checkout", "-q", "main")
    gsh(root, "git", "branch", "-D", "prep-v0.2")
    return tip


@git_needed
@pytest.mark.parametrize("mode, tag_it, status", [("merged-parent", True, "PASS"), ("merged-parent", False, "FAIL"),
                                                  ("commit", True, "FAIL")])
def test_REQ_018_release_tag_on_the_merged_parent(cli, branches, mode, tag_it, status, capsys):
    from steward import hooks as hk

    gsh(branches, "git", "checkout", "-q", "-b", "task/model")  # committed, so the released commit carries it too
    _add(branches, f'release_tag_on = "{mode}"\n')
    gsh(branches, "git", "commit", "-qam", "release model")
    gsh(branches, "git", "checkout", "-q", "main")
    gsh(branches, "git", "merge", "-q", "--no-ff", "-m", "merge task/model", "task/model")
    tip = _release_by_merge(branches, tag_it)
    _, rep = cli.check(branches, "branches")
    res = one(rep, "R-59")
    assert res["status"] == status, res
    line = [f"refs/heads/release {tip} refs/heads/release {'0' * 40}"]
    capsys.readouterr()
    assert (hk.run_pre_push(branches, "default", [], "skip", line) == 0) is (status == "PASS"), capsys.readouterr().err


@pytest.mark.parametrize("next_line, status_line, ok", [
    ("**Next unused ID: TSK-004.**", "in progress", True),
    ("Next unused ID: TSK-004", "in progress (left: CI)", True),
    ("Next unused ID: TSK-004", "in progress — waiting on review", True),
    ("Next unused ID: TSK-004", "in progressive", False),
])
def test_DEF_030_next_id_punctuation_and_status_qualifiers(cli, board, next_line, status_line, ok):
    _write(board, "development/BOARD.md", f"# Board\n\n- TSK-001 one\n\n{next_line}\n")
    _task(board, "development/tasks/one.md", "TSK-001", status_line)
    _, rep = cli.check(board, "tasks")
    res = one(rep, "R-57")
    assert (res["status"] == "PASS") is ok, res
    if not ok:
        assert "R-57.unknown_status" in codes(res)


# ---------------------------------------------------------------- DEF-013: pushing a signed authorization tag
@signing
def test_DEF_013_an_authorization_tag_is_verified_not_gated(cli, repo, capsys):
    from steward import hooks as hk
    from test_authorize import approve

    tag = approve(cli, repo)
    sha = gsh(repo, "git", "rev-parse", f"refs/tags/{tag}")
    _change_policy(repo)  # the tagged commit would no longer pass the gate under a changed policy
    line = [f"refs/tags/{tag} {sha} refs/tags/{tag} {'0' * 40}"]
    assert hk.run_pre_push(repo, "default", [], "skip", line) == 0, capsys.readouterr().err
    gsh(repo, "git", "tag", "steward/auth/" + "f" * 32, "HEAD")  # unsigned, under the reserved prefix
    bad = gsh(repo, "git", "rev-parse", "refs/tags/steward/auth/" + "f" * 32)
    line = [f"refs/tags/steward/auth/{'f' * 32} {bad} refs/tags/steward/auth/{'f' * 32} {'0' * 40}"]
    assert hk.run_pre_push(repo, "default", [], "skip", line) == 1
    assert "not a verified authorization" in capsys.readouterr().err


# ---------------------------------------------------------------- B12, B13: session close (DEF-031, DEF-032)
from test_v090_session import CLOSE  # noqa: E402
from test_v090_session import proj as sproj  # noqa: E402,F401


@git_needed
def test_DEF_031_steward_lock_files_and_ignored_files_are_not_uncommitted_records(cli, sproj):
    with open(sproj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "TOY"\n')
    cli("exchange", "init")
    gsh(sproj, "git", "add", "-A")
    gsh(sproj, "git", "commit", "-qm", "exchange")
    (sproj / "exchange/log.jsonl.lock").write_text("")  # steward's own lock, beside its ledger
    (sproj / ".git/info/exclude").write_text("development/scratch.md\n")
    (sproj / "development/scratch.md").write_text("ignored notes\n")
    code, _, err = cli(*CLOSE)
    assert code == 0, err
    (sproj / "development/new-record.md").write_text("a new record\n")  # control: a real record is still refused
    code, _, err = cli(*CLOSE)
    assert code != 0 and "development/new-record.md" in err


@git_needed
@pytest.mark.parametrize("include, refused", [('["src/**"]', False), (None, True)])
def test_DEF_032_the_handoff_is_scanned_with_each_list_s_scope(cli, sproj, include, refused):
    with open(sproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "independence"\nfile = "development/independence.txt"\npublic = true\n'
                + (f"include = {include}\n" if include else ""))
    (sproj / "development/independence.txt").write_text("Consumerco\n")
    gsh(sproj, "git", "add", "-A")
    gsh(sproj, "git", "commit", "-qm", "terms")
    argv = list(CLOSE)
    argv[argv.index("--next") + 1] = "send the notice to Consumerco"
    code, _, err = cli(*argv)
    assert (code == 65) is refused, err
    argv[argv.index("--next") + 1] = "see /" "Users/alice/x"  # scrub: allow; steward: allow R-07 (synthetic)
    assert cli(*argv)[0] == 65  # the local-path check always applies


# ---------------------------------------------------------------- FB-016, FB-017, DEF-010: exchange
@pytest.fixture
def xproj(cli, tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    r = tmp_path / "x"
    r.mkdir()
    gsh(r, "git", "init", "-q", "-b", "main")
    gsh(r, "git", "config", "user.name", "T")
    gsh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "AAA"\n')
    monkeypatch.chdir(r)
    cli("exchange", "init")
    return r


def _item(xproj, iid, kind="request", frm="BBB", to="AAA", extra="", body="## Need\nx\n"):
    from steward import exchange as xc
    text = xc.render({"schema": "steward.exchange/1", "id": iid, "kind": kind, "from": frm, "to": to,
                      "title": f"item {iid}", "filed": __import__("datetime").date(2026, 11, 24)}, body)
    if extra:
        text = text.replace("+++\n", "+++\n" + extra, 1) if False else text.replace('title = ', extra + 'title = ', 1)
    p = xproj / "drop" / f"{iid}.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(text)
    return p


def test_FB_016_a_shipped_note_must_start_with_an_existing_tag(cli, xproj):
    assert cli("exchange", "receive", _item(xproj, "BBB-REQ-001"))[0] == 0
    for s, n in (("verified", "seen"), ("accepted", "planned")):
        assert cli("exchange", "state", "BBB-REQ-001", s, "--note", n)[0] == 0
    code, _, err = cli("exchange", "respond", "BBB-REQ-001", "shipped", "--note", "T-1: re-filed and done")
    assert code == 64 and "release tag" in err
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "x")
    gsh(xproj, "git", "tag", "v1.0.0")
    assert cli("exchange", "respond", "BBB-REQ-001", "shipped", "--note", "v1.0.0: done")[0] == 0
    readme = (xproj / "exchange/README.md").read_text()
    assert "## States" in readme and "| acknowledged | merged*, not-reproduced*, superseded*, verified*, withdrawn* |" in readme


def test_FB_017_a_received_response_has_no_decision_clock_and_can_be_noted(cli, xproj, monkeypatch):
    import steward.process as pr
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "mine")[0] == 0
    mine = (xproj / "exchange/outbox/AAA-REQ-001.md").read_bytes()
    body = f"\n## Decision\naccepted: planned\n\n## Answers\nAAA-REQ-001 sha256:{__import__('hashlib').sha256(mine).hexdigest()}\n"
    p = _item(xproj, "BBB-RSP-001", kind="response", extra='responds_to = "AAA-REQ-001"\n', body=body)
    assert cli("exchange", "receive", p)[0] == 0
    monkeypatch.setattr(pr, "_today", lambda: __import__("datetime").date(2027, 6, 1))
    _, rep = cli.check(xproj, "governance")
    assert "R-54.no_decision" not in codes(one(rep, "R-54")), one(rep, "R-54")
    assert cli("exchange", "state", "BBB-RSP-001", "noted")[0] == 0
    _, out, _ = cli("exchange", "status")
    assert "accepted" in [l for l in out.splitlines() if l.startswith("AAA-REQ-001")][0]


def test_FB_017_a_response_to_other_bytes_is_not_recorded_against_this_item(cli, xproj):
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "mine")[0] == 0
    body = "\n## Decision\ndeclined: not ours\n\n## Answers\nAAA-REQ-001 sha256:" + "0" * 64 + "\n"
    p = _item(xproj, "BBB-RSP-001", kind="response", extra='responds_to = "AAA-REQ-001"\n', body=body)
    code, out, err = cli("exchange", "receive", p)
    assert code == 0 and "ID collision" in out, err
    _, out, _ = cli("exchange", "status")
    assert "declined" not in [l for l in out.splitlines() if l.startswith("AAA-REQ-001")][0]
    _, rep = cli.check(xproj, "governance")
    assert "R-53.response_target_mismatch" in codes(one(rep, "R-53"))


@pytest.mark.parametrize("old, new", [("AAA-REQ-001", "AAA-REQ-009"), ("AAA-REQ-009", "AAA-REQ-001")])
def test_DEF_010_a_refiled_item_may_alias_the_merged_item_it_replaces(cli, xproj, old, new):
    from steward import exchange as xc
    ob = xproj / "exchange/outbox"
    for iid, aliases in ((old, ""), (new, f'aliases = ["{old}"]\n')):
        t = xc.render({"schema": "steward.exchange/1", "id": iid, "kind": "request", "from": "AAA", "to": "BBB",
                       "title": iid, "filed": __import__("datetime").date(2026, 11, 24)}, "## Need\nx\n")
        (ob / f"{iid}.md").write_text(t.replace("title = ", aliases + "title = ", 1))
        cli("exchange", "state", iid, "filed")
    _, rep = cli.check(xproj, "governance")
    assert "R-53.duplicate_id" in codes(one(rep, "R-53"))  # the old item is still open
    assert cli("exchange", "state", old, "acknowledged")[0] == 0
    assert cli("exchange", "state", old, "merged", "--note", f"re-filed as {new}.")[0] == 0
    _, rep = cli.check(xproj, "governance")
    assert "R-53.duplicate_id" not in codes(one(rep, "R-53")), one(rep, "R-53")


# ---------------------------------------------------------------- REQ-009: accepted occurrences, not whole files
@pytest.fixture
def tproj(cli, tmp_path, monkeypatch):
    r = tmp_path / "t"
    r.mkdir()
    cli("init", "--repo", r)
    (r / "development/policy-terms.txt").write_text("video\n")
    monkeypatch.chdir(r)
    return r


def _occ(tproj, extra):
    with open(tproj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "policy"\nfile = "development/policy-terms.txt"\npublic = true\n'
                '\n[[terms.allow_occurrence]]\npath = "assets/index-*.css"\nterm = 1\n'
                'context = "img,svg,{term},audio"\nmax = 1\n' + extra)


def _r07(cli, tproj):
    _, rep = cli.check(tproj, "privacy")
    return one(rep, "R-07")


def test_REQ_009_an_occurrence_inside_its_context_is_accepted_and_nothing_else(cli, tproj):
    _occ(tproj, "")
    css = tproj / "assets/index-1.css"
    css.parent.mkdir()
    css.write_text("img,svg,video,audio{display:block}\n")
    assert _r07(cli, tproj)["status"] == "PASS", _r07(cli, tproj)
    css.write_text("img,svg,video,audio{display:block}\n.video-player{}\n")  # the same term elsewhere in the file
    assert _r07(cli, tproj)["status"] == "FAIL"
    css.write_text("img,svg,video,audio{x}\nimg,svg,video,audio{y}\n")  # over max = 1
    assert _r07(cli, tproj)["status"] == "FAIL"
    css.write_text("img,svg,video,audio{display:block}\n")
    (tproj / "assets/index-2.css").write_text("a video here\n")  # a second matching file without the fragment
    assert _r07(cli, tproj)["status"] == "FAIL"


def test_REQ_009_a_hash_bound_occurrence_stops_when_the_file_changes(cli, tproj):
    import hashlib
    t = tproj / "tests/test_policy.py"
    t.parent.mkdir()
    t.write_text('FORBIDDEN = ["video"]\n')
    sha = hashlib.sha256(t.read_bytes()).hexdigest()
    _occ(tproj, f'\n[[terms.allow_occurrence]]\npath = "tests/test_policy.py"\nterm = 1\nsha256 = "{sha}"\n')
    assert _r07(cli, tproj)["status"] == "PASS", _r07(cli, tproj)
    t.write_text('FORBIDDEN = ["video"]  # edited\n')
    assert _r07(cli, tproj)["status"] == "FAIL"


def test_REQ_009_a_context_without_the_placeholder_is_invalid(cli, tproj):
    _occ(tproj, '\n[[terms.allow_occurrence]]\npath = "x"\nterm = 1\ncontext = "no placeholder"\n')
    code, _, err = cli("check", "config", "--summary")
    assert code != 0


# ---------------------------------------------------------------- FB-015: the template shows [[terms]] and [exchange]
def test_FB_015_the_commented_term_and_exchange_blocks_are_valid_when_uncommented(cli, tmp_path):
    import re
    from conftest import REPO
    tmpl = (REPO / "templates/steward.toml.tmpl").read_text()
    block = tmpl[tmpl.index("# [[terms]]"):tmpl.index("# ack_days")] + "# ack_days = 14\n"
    lines = [re.sub(r"^# ?", "", l) for l in block.splitlines() if l.startswith("# ") and "sha256" not in l]
    lines = [l for l in lines if not l.startswith(("Requests and release", "Named term"))]
    cli("init", "--repo", tmp_path)
    (tmp_path / "development/policy-terms.txt").write_text("term\n")
    with open(tmp_path / "steward.toml", "a") as f:
        f.write("\n" + "\n".join(lines) + "\n")
    code, out, err = cli("check", "--repo", tmp_path, "config", "--summary")
    assert "PASS 1 · FAIL 0" in out and "governance" in out.split("not configured")[0], out + err


# ---------------------------------------------------------------- REQ-010: manifest --output and locks in --dist
def test_REQ_010_output_and_a_lock_beside_the_artifacts(cli, tmp_path, monkeypatch):
    import hashlib
    import json
    import zipfile
    repo, rel = tmp_path / "repo", tmp_path / "rel"
    repo.mkdir()
    rel.mkdir()
    cli("init", "--repo", repo)
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[release]\nlocks = ["requirements.lock"]\n')
    with zipfile.ZipFile(rel / "pkg-1.0-py3-none-any.whl", "w") as z:
        z.writestr("pkg/__init__.py", "x = 1\n")
    (rel / "requirements.lock").write_text("pkg==1.0\n")
    monkeypatch.chdir(repo)
    before = sorted(p.name for p in repo.iterdir())
    code, out, err = cli("release", "manifest", "--dist", rel, "--output", rel / "release-manifest.json")
    assert code == 0, err
    man = json.loads((rel / "release-manifest.json").read_text())
    assert man["locks"]["requirements.lock"] == hashlib.sha256(b"pkg==1.0\n").hexdigest()
    assert man["locks_in_dist"] == ["requirements.lock"] and "from the release folder" in out
    assert sorted(p.name for p in repo.iterdir()) == before  # the repository is untouched


# ---------------------------------------------------------------- DEF-012: a signal during the run's setup
def _run_entries(root):
    import json
    p = root / "development/runs.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.is_file() else []


def test_DEF_012_a_signal_during_setup_is_recorded_and_exits_128_plus_n(cli, tmp_path, monkeypatch):
    import os
    import signal
    from steward import ledger as lg
    cli("init", "--repo", tmp_path)
    monkeypatch.chdir(tmp_path)
    real = lg.Ledger.append

    def append(self, kind, data):
        out = real(self, kind, data)
        if kind == "started":
            os.kill(os.getpid(), signal.SIGTERM)  # arrives after the run is recorded, before the job starts
        return out
    monkeypatch.setattr(lg.Ledger, "append", append)
    code, _, err = cli("run", "--", "sleep", "100")
    assert code == 128 + signal.SIGTERM, err
    out = [e for e in _run_entries(tmp_path) if e.get("kind") == "outcome"]
    assert len(out) == 1 and out[0]["status"] == "interrupted" and out[0]["exit_code"] is None
    assert "before the job started" in out[0]["breached"]


@pytest.mark.parametrize("delay", [0.4, 0.8, 2.0])
def test_DEF_012_a_real_signal_at_any_time_after_start_is_recorded(cli, tmp_path, delay):
    import os
    import signal
    import subprocess
    import sys
    import time
    cli("init", "--repo", tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.Popen([sys.executable, "-m", "steward.cli", "run", "--", "sleep", "100"], cwd=tmp_path, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(delay)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 128 + signal.SIGTERM
    out = [e for e in _run_entries(tmp_path) if e.get("kind") == "outcome"]
    assert len(out) == 1 and out[0]["status"] == "interrupted", out
    assert out[0]["exit_code"] is None or out[0]["exit_code"] != 0, out


# ---------------------------------------------------------------- DEF-011: pull imports the requester's originals
@git_needed
def test_DEF_011_pull_imports_this_project_s_own_original_from_the_peer_inbox(cli, tmp_path, monkeypatch):
    import datetime
    import os
    from steward import exchange as xc
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    a, b = tmp_path / "a", tmp_path / "b"
    for r, c in ((a, "AAA"), (b, "BBB")):
        r.mkdir()
        gsh(r, "git", "init", "-q", "-b", "main")
        cli("init", "--repo", r)
        with open(r / "steward.toml", "a") as f:
            f.write(f'\n[exchange]\ncode = "{c}"\n' + ('peers = { BBB = "../b" }\n' if c == "AAA" else ""))
        cli("exchange", "init", "--repo", r)
    orig = xc.render({"schema": "steward.exchange/1", "id": "AAA-REQ-001", "kind": "request", "from": "AAA", "to": "BBB",
                      "title": "an old need", "filed": datetime.date(2026, 11, 1)}, "## Need\nx\n")
    (b / "exchange/inbox/AAA-REQ-001.md").write_text(orig)  # migrated into the receiver's inbox only
    from steward.exchange import set_state
    from steward.models import load_config
    rid = load_config(b).steward.repo_id  # AF13 (0.19.0): a receiver's ledger names its own repo_id
    set_state(b, rid, "AAA-REQ-001", "acknowledged", "migrated", "BBB", False, "request", place="inbox")  # its record
    rsp = xc.render({"schema": "steward.exchange/1", "id": "BBB-RSP-001", "kind": "response", "from": "BBB", "to": "AAA",
                     "title": "Re: an old need", "filed": datetime.date(2026, 11, 2), "responds_to": "AAA-REQ-001"},
                    "\n## Decision\naccepted: planned\n")
    (b / "exchange/responses/BBB-RSP-001.md").write_text(rsp)
    for r in (a, b):
        gsh(r, "git", "add", "-A")
        gsh(r, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    monkeypatch.chdir(a)
    code, out, err = cli("exchange", "pull", "BBB")
    assert code == 0 and "imported unchanged" in out, out + err
    assert (a / "exchange/outbox/AAA-REQ-001.md").read_text() == orig
    _, rep = cli.check(a, "governance")
    assert "R-53.orphan_response" not in codes(one(rep, "R-53")), one(rep, "R-53")


# ---------------------------------------------------------------- DEF-028: what a release delivered is shipped
CHANGELOG = """# Changelog

## 1.0.0 (2026-11-24)

### Added
- the thing asked in BBB-REQ-001.

### Known issues
- BBB-REQ-002 is still open.

### Upgrade notes
- None.
"""


def _receiver(cli, xproj):
    with open(xproj / "steward.toml", "a") as f:
        f.write('consumers = ["BBB"]\n')  # appended to [exchange]
    for i in ("BBB-REQ-001", "BBB-REQ-002", "BBB-REQ-003"):
        assert cli("exchange", "receive", _item(xproj, i))[0] == 0
    cli("exchange", "state", "BBB-REQ-001", "verified", "--note", "seen")
    cli("exchange", "state", "BBB-REQ-001", "accepted", "--note", "planned")
    cli("exchange", "state", "BBB-REQ-003", "verified", "--note", "seen")
    cli("exchange", "state", "BBB-REQ-003", "deferred", "--note", "v1.0.0")
    (xproj / "CHANGELOG.md").write_text(CHANGELOG)
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "release")
    gsh(xproj, "git", "tag", "v1.0.0")


def test_DEF_028_announce_ships_what_the_changelog_delivers_and_the_notice_lists_it(cli, xproj):
    _receiver(cli, xproj)
    code, out, err = cli("exchange", "announce", "v1.0.0")
    assert code == 0, err
    _, st, _ = cli("exchange", "status")
    row = lambda i: [l for l in st.splitlines() if l.startswith(i)][0]  # noqa: E731
    assert "shipped" in row("BBB-REQ-001") and "shipped" not in row("BBB-REQ-002")
    notice = next((xproj / "exchange/oneway").glob("AAA-REL-*.md")).read_text()
    assert "## Shipped items\n- BBB-REQ-001\n" in notice
    _, rep = cli.check(xproj, "governance")
    res = one(rep, "R-53")
    assert any(d["code"] == "R-53.deferred_stale" and d.get("value") == "BBB-REQ-003" for d in res["details"]), res


def test_DEF_028_announce_refuses_an_undecided_item_listed_as_delivered(cli, xproj):
    _receiver(cli, xproj)
    (xproj / "CHANGELOG.md").write_text(CHANGELOG.replace("### Known issues", "### Fixed"))
    gsh(xproj, "git", "commit", "-qam", "changelog")  # 0.13.0 (U7): announce reads the changelog at the tag
    gsh(xproj, "git", "tag", "-f", "v1.0.0")
    code, _, err = cli("exchange", "announce", "v1.0.0")
    assert code == 64 and "BBB-REQ-002" in err


def test_DEF_028_the_consumer_records_its_items_shipped_from_the_notice(cli, xproj):
    from steward import exchange as xc
    assert cli("exchange", "new", "request", "--to", "BBB", "--title", "mine")[0] == 0
    notice = xc.render({"schema": "steward.exchange/1", "id": "BBB-REL-001", "kind": "release", "from": "BBB", "to": "AAA",
                        "title": "Release v2.0.0", "filed": __import__("datetime").date(2026, 11, 24), "version": "2.0.0",
                        "tag": "v2.0.0", "breaking": False}, "\n## Shipped items\n- AAA-REQ-001\n")
    p = xproj / "drop/BBB-REL-001.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(notice)
    assert cli("exchange", "receive", p)[0] == 0
    _, st, _ = cli("exchange", "status")
    assert "shipped" in [l for l in st.splitlines() if l.startswith("AAA-REQ-001")][0], st


# ---------------------------------------------------------------- review of 0.12.0: U1, U2, U3, U4, U11
@signing
def test_U1_a_queued_payload_of_another_repository_does_not_hold_r33(cli, repo):
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    nonce = _prepare(cli, obj)
    p = repo / ".steward/pending" / f"{nonce}.txt"
    t = p.read_text()
    rid = next(l.split(": ", 1)[1] for l in t.splitlines() if l.startswith("repo_id: "))
    p.write_text(t.replace(rid, "00000000-0000-4000-8000-000000000000"))
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"


@signing
def test_U2_a_reserved_destination_or_another_object_is_refused(cli, repo, capsys):
    from steward import hooks as hk
    from test_authorize import approve
    tag = approve(cli, repo)
    head = gsh(repo, "git", "rev-parse", "HEAD")
    line = [f"refs/heads/main {head} refs/tags/{tag} {'0' * 40}"]  # an ordinary source into a reserved name
    assert hk.run_pre_push(repo, "default", [], "skip", line) == 1
    line = [f"refs/tags/{tag} {head} refs/tags/{tag} {'0' * 40}"]  # not the object of that tag
    assert hk.run_pre_push(repo, "default", [], "skip", line) == 1
    assert "not the local tag" in capsys.readouterr().err


@signing
def test_U3_sign_pending_signs_exactly_the_bytes_it_showed(cli, repo, monkeypatch):
    from steward import authorize as az
    _change_policy(repo)
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    nonce = _prepare(cli, obj)
    shown = az.read_pending(repo, nonce)
    real = az.read_pending
    p = repo / ".steward/pending" / f"{nonce}.txt"

    def read_then_swap(root, n):
        data = real(root, n)
        p.write_text(data.decode().replace("add the quick gate", "something else"))  # replaced after it was read
        return data
    monkeypatch.setattr(az, "read_pending", read_then_swap)
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0, err
    tag = out.split("signed ")[1].split()[0]
    msg = gsh(repo, "git", "cat-file", "-p", f"refs/tags/{tag}")
    assert "add the quick gate" in msg and "something else" not in msg and shown.decode().splitlines()[0] in msg


def test_U4_a_response_target_outside_the_id_format_is_invalid(cli, xproj):
    p = _item(xproj, "BBB-RSP-001", kind="response", extra='responds_to = "../../../etc/passwd"\n',
              body="\n## Decision\naccepted: x\n")
    code, _, err = cli("exchange", "receive", p)
    assert code != 0 and not (xproj / "exchange/inbox/BBB-RSP-001.md").exists()


def test_U11_a_linked_exchange_item_is_never_published(cli, xproj, tmp_path):
    with open(xproj / "steward.toml", "a") as f:
        f.write('\n[docs]\npublish = ["overview", "exchange"]\n')
    outside = tmp_path / "secret.md"
    outside.write_text(_item(xproj, "BBB-REQ-007").read_text())
    (xproj / "exchange/inbox/BBB-REQ-007.md").symlink_to(outside)
    code, _, err = cli("docs", "build")
    assert code == 65 and "link" in err and not (xproj / "docs/project/exchange.md").exists()


# ---------------------------------------------------------------- review of 0.12.0: U8, U10, U12, U16, U17
def test_U8_a_malformed_or_foreign_answers_block_is_a_mismatch(xproj):
    from steward import exchange as xc
    (xproj / "exchange/outbox/AAA-REQ-001.md").write_text("x\n")
    assert xc.target_mismatch(xproj, "## Answers\nnot a binding\n", "AAA-REQ-001")
    assert xc.target_mismatch(xproj, "## Answers\nAAA-REQ-002 sha256:" + "0" * 64 + "\n", "AAA-REQ-001")
    assert not xc.target_mismatch(xproj, "## Decision\naccepted: x\n", "AAA-REQ-001")  # legacy: no section


def test_U10_a_closed_item_without_a_merge_keeps_its_id(cli, xproj):
    from steward import exchange as xc
    ob = xproj / "exchange/outbox"
    for iid, aliases in (("AAA-REQ-001", ""), ("AAA-REQ-009", 'aliases = ["AAA-REQ-001"]\n')):
        t = xc.render({"schema": "steward.exchange/1", "id": iid, "kind": "request", "from": "AAA", "to": "BBB",
                       "title": iid, "filed": __import__("datetime").date(2026, 11, 24)}, "## Need\nx\n")
        (ob / f"{iid}.md").write_text(t.replace("title = ", aliases + "title = ", 1))
        cli("exchange", "state", iid, "filed")
    cli("exchange", "state", "AAA-REQ-001", "closed", "--note", "see AAA-REQ-009")
    _, rep = cli.check(xproj, "governance")
    assert "R-53.duplicate_id" in codes(one(rep, "R-53"))


def test_U12_a_signal_after_the_job_ended_is_not_swallowed(cli, tmp_path, monkeypatch):
    import os
    import signal
    from steward import ledger as lg
    cli("init", "--repo", tmp_path)
    monkeypatch.chdir(tmp_path)
    real = lg.Ledger.append

    def append(self, kind, data):
        out = real(self, kind, data)
        if kind == "outcome":
            os.kill(os.getpid(), signal.SIGTERM)
        return out
    monkeypatch.setattr(lg.Ledger, "append", append)
    code, _, err = cli("run", "--", "true")
    assert code == 128 + signal.SIGTERM and "after the job ended" in err


@pytest.mark.parametrize("name", ["true", "null", "1.5", "yes"])
def test_U16_a_yaml_looking_docs_dir_stays_a_string(cli, xproj, name):
    import yaml
    with open(xproj / "steward.toml", "a") as f:
        f.write(f'\n[docs]\ndir = "{name}"\ngenerated = "{name}/project"\n')
    assert cli("docs", "init")[0] == 0
    line = next(l for l in (xproj / "mkdocs.yml").read_text().splitlines() if l.startswith("docs_dir:"))
    assert yaml.safe_load(line)["docs_dir"] == name


@git_needed
def test_U17_a_tracked_lock_shaped_record_still_counts(cli, sproj):
    (sproj / "development/notes.jsonl.lock").write_text("a tracked record\n")
    gsh(sproj, "git", "add", "-A")
    gsh(sproj, "git", "commit", "-qm", "x")
    (sproj / "development/notes.jsonl.lock").write_text("changed\n")
    code, _, err = cli(*CLOSE)
    assert code != 0 and "notes.jsonl.lock" in err
