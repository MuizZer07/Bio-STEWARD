"""0.21.0 second fix pass W12c: the second review's findings N1 (allow entries that still reached a denied command),
N2 (the repo_id pinned for this checkout when signing and listing) and N3 (reload and review-clone edge cases).

Each test reproduces the reviewer's evidence where it is practical. Agents are stand-ins, never the real CLIs, and no
test reaches the network.
"""

import json
import os
import re
import shutil

import pytest

from steward import authorize as az
from steward import dispatch as dp
from steward import sprint as sp
from steward.models import load_config
from test_authorize import expires, repo as signing_repo, sh  # noqa: F401  (the signed-authorization fixture)
from test_interface_w02 import _valid
from test_v0120_features import gsh, xproj  # noqa: F401
from test_w08_sprint import events, one_task, repo, task, write_sprint  # noqa: F401
from test_w12b_fix_pass import REVIEW_TASK

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
signing = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="needs ssh-keygen")


def _allow(entry):
    return one_task("claude-code", f"allow = [{json.dumps(entry)}]")


# ---------------------------------------------------------------- N1: allow entries
# The second review's evidence, its four groups, every entry it names; then more of the same kinds.
N1_WRAPPERS = ["env -u HOME git push", "env -C . git push", "env --chdir . git push", "sudo -u root git push",
               "nice -n 10 git push", "timeout -s TERM 10 git push", "xargs -n 1 git push", "stdbuf -o 0 git push",
               "bash -o errexit -c 'git push'", "sh -o posix -c 'git push'"]
N1_INTERPRETERS = ["python3 -P -m steward.cli authorize", "python -u -m steward authorize",
                   "python3 -msteward.cli authorize", "python3 -cfoo bar", "node --eval foo", "python3.13",
                   "python3.11 -c", "python3.13 -m steward.cli authorize", "python3 -m twine upload",
                   "python3 -m uv publish"]
N1_OPTIONS = ["uv --no-config publish", "uv -q publish", "uv --no-config run git push",
              "uv tool run steward authorize", "uvx steward authorize", "uvx twine upload",
              "pipx run steward authorize", "npx steward authorize", "npm -s publish", "npm --prefix . publish",
              "cargo -q publish", "cargo +nightly publish", "gh pr -R owner/repo merge"]
N1_CASE = ["GIT push", "/usr/bin/GIT push", "ENV git push"]
N1_MORE = ["doas -u root git push", "strace -f git push", "script -q /dev/null git push", "fish -c 'git push'",
           "csh -c 'git push'", "tcsh -c 'git push'", "zsh -o x -c 'git push'", "/bin/BASH -c 'git push'",
           "command -p git push", "exec -a x git push", "time -p git push", "nohup -- git push",
           "pnpx steward authorize", "bunx twine upload", "perl5.36 -e 1", "ruby3.2", "node22 -e 1",
           "python3.13t -m pytest", "PYTHON3 -c 1", "python -m steward.cli", "uv run python", "uv run python3 -c 1",
           "uv run --with twine twine upload", "uv run --python /tmp/x pytest", "uv run", "npm exec steward",
           "gh api -X PUT repos/o/r/pulls/1/merge", "Git Push", "git --no-pager push", "steward run git push",
           "twine", "cargo", "gh pr"]
N1_REFUSED = N1_WRAPPERS + N1_INTERPRETERS + N1_OPTIONS + N1_CASE + N1_MORE
N1_ORDINARY = ["make test", "npm test", "npm run build", "git status", "git diff", "uv run pytest", "python -m pytest",
               "pytest", "python3 -m pytest -q", "uv run --extra dev python -m pytest", "steward check",
               "gh pr view", "cargo test", "twine check"]


def test_W12c_N1_the_review_evidence_has_its_47_entries():
    assert len(N1_WRAPPERS + N1_INTERPRETERS + N1_OPTIONS + N1_CASE) == 36  # every entry the review lists
    assert len(N1_REFUSED) >= 47


@pytest.mark.parametrize("entry", N1_REFUSED)
def test_W12c_N1_an_allow_entry_from_the_review_evidence_is_refused(entry):
    with pytest.raises(ValueError, match="default deny list|cannot name|not command prefixes"):
        _allow(entry)
    assert sp.allow_refusal(entry) is not None


@pytest.mark.parametrize("entry", N1_ORDINARY)
def test_W12c_N1_ordinary_allow_entries_still_work(entry):
    sf, t = _allow(entry)
    assert f"Bash({entry} *)" in sp.command(t, sf)
    assert sp.allow_refusal(entry) is None


def test_W12c_N1_the_refusal_says_why():
    with pytest.raises(ValueError, match="env is a shell, a wrapper or a launcher"):
        _allow("env -u HOME git push")
    with pytest.raises(ValueError, match="python3.13 is an interpreter"):
        _allow("python3.13")
    with pytest.raises(ValueError, match=r"an option \(-s\) before the subcommand of npm"):
        _allow("npm -s publish")
    with pytest.raises(ValueError, match="default deny list"):
        _allow("GIT push")


def test_W12c_N1_normalise_compares_program_names_in_lower_case():
    assert sp.normalise("/usr/bin/GIT Push") == "git push"
    assert sp.normalise("ENV git push") == "git push"


def test_W12c_N1_dispatch_lists_name_only_what_an_allow_entry_may(xproj):
    assert [c for c in dp.REVIEW if sp.allow_refusal(c)] == []
    impl = dp.implement_list()
    assert [c for c in impl if sp.allow_refusal(c)] == []
    for c in ("git", "env", "python", "python3", "uv", "awk"):
        assert c not in impl
    assert {"git add", "git commit", "git diff", "python -m pytest", "pytest"} <= set(impl)
    doc = json.loads(dp.agy_settings(xproj, implement=True).read_text())["permissions"]
    assert "command(env)" not in doc["allow"] and "command(git)" not in doc["allow"]
    assert "command(git commit)" in doc["allow"] and "command(git push)" in doc["deny"]
    sf, t = one_task("antigravity", 'permissions = "edit-and-run"')
    allow = [a[len("command("):-1] for a in sp.agy_settings(t)["permissions"]["allow"]]
    assert "awk" not in allow and [c for c in allow if sp.allow_refusal(c)] == []


# ---------------------------------------------------------------- N2: the repo_id pinned for this checkout
def _prepare(cli):
    code, out, err = cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires(),
                         "--summary", "a request")
    assert code == 0, err
    return out.split("authorize sign ")[1].strip()


REPO_B = "00000000-0000-4000-8000-00000000000b"  # the repo_id the agent writes


def _respoof(root, nonce, new=REPO_B):
    """The reviewer's scenario: an agent edits steward.toml's repo_id and plants a payload carrying it."""
    own = load_config(root).steward.repo_id
    cfg = root / "steward.toml"
    cfg.write_text(re.sub(r'(?m)^repo_id = "[^"]*"', f'repo_id = "{new}"', cfg.read_text(), count=1))
    assert load_config(root).steward.repo_id == new
    p = root / ".steward/pending" / f"{nonce}.txt"
    p.write_text(p.read_text().replace(f"repo_id: {own}\n", f"repo_id: {new}\n"))
    return own, az.payload_sha256(p.read_bytes())


@signing
def test_W12c_N2_sign_refuses_when_the_checkouts_pin_names_another_repo_id(cli, signing_repo, monkeypatch, tmp_path):
    nonce = _prepare(cli)
    own, digest = _respoof(signing_repo, nonce)  # the fixture pinned this checkout with its own repo_id
    assert az.pin_for_checkout(signing_repo) == own
    code, out, err = cli("authorize", "sign", nonce, "--expect-sha256", digest)
    assert code == 1 and "pinned to" in err and "signed" not in out, (out, err)
    with pytest.raises(az.AuthError, match="pinned to"):
        az.sign(signing_repo, nonce)
    with pytest.raises(az.AuthError, match="pinned to"):
        az.sign(signing_repo, nonce, repo_id=REPO_B)  # the callers' form, the repo_id from steward.toml
    assert sh(signing_repo, "git", "tag", "-l", "steward/auth/*").split() == []


@signing
def test_W12c_N2_pending_lists_every_payload_as_foreign_under_a_differing_pin(cli, signing_repo, monkeypatch,
                                                                              tmp_path):
    nonce = _prepare(cli)
    own, _ = _respoof(signing_repo, nonce)
    assert az.pin_for_checkout(signing_repo) == own
    code, out, err = cli("authorize", "pending", "--format", "json")
    assert code == 0, err
    doc = _valid(json.loads(out))
    assert {i["nonce"]: i["state"] for i in doc["items"]} == {nonce: "foreign"} and doc["waiting"] == 0
    assert [q["state"] for q in az.pending(signing_repo, repo_id=REPO_B)] == ["foreign"]
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0, err
    assert sh(signing_repo, "git", "tag", "-l", "steward/auth/*").split() == []


@signing
def test_W12c_N2_a_pin_that_agrees_still_lists_and_signs(cli, signing_repo, monkeypatch, tmp_path):
    nonce = _prepare(cli)
    assert az.pin_for_checkout(signing_repo) == load_config(signing_repo).steward.repo_id
    assert [q["state"] for q in az.pending(signing_repo)] == ["waiting"]
    assert az.sign(signing_repo, nonce) == f"steward/auth/{nonce}"


# ---------------------------------------------------------------- N3a: the sprint file and the reload order
def _source(repo):
    cfg = load_config(repo)
    sf = sp.load(repo, "day1")
    said: list[str] = []
    return sp._Source(repo, sf, sp.led(repo, "day1", cfg.steward.repo_id), said.append), sf, said


def test_W12c_N3a_an_unreadable_file_on_a_reload_order_is_recorded_as_not_valid(cli, repo):
    write_sprint(repo, task("T1"))
    src, sf, said = _source(repo)
    (repo / "development/sprints/day1.toml").unlink()
    src.lg.append("order", {"order": "reload", "by": "human"})  # what `steward sprint reload` appends
    assert src.refresh() is sf
    rl = [e for e in events(repo) if e["kind"] == "reloaded"]
    assert len(rl) == 1 and rl[0]["valid"] is False and rl[0]["sha256"] is None
    assert rl[0]["note"] == "the file could not be read" and rl[0]["by"] == "human"


def test_W12c_N3a_a_held_edit_reverted_before_the_order_holds_no_later_edit(cli, repo):
    write_sprint(repo, task("T1") + task("T2"))
    p = repo / "development/sprints/day1.toml"
    original = p.read_text()
    src, sf, said = _source(repo)
    t1 = next(t for t in sf.task if t.id == "T1")
    p.write_text(original.replace('title = "task T2"', 'title = "edited while T1 ran"'))
    src.refresh({"T1": t1})
    assert src.held is not None
    p.write_text(original)  # reverted
    assert cli("sprint", "reload", "day1")[0] == 0
    src.refresh()
    assert src.held is None
    p.write_text(original.replace('title = "task T2"', 'title = "a later idle edit"'))
    new = src.refresh()  # no task runs and no order: an idle edit is used
    assert next(t for t in new.task if t.id == "T2").title == "a later idle edit"
    assert [e.get("held") for e in events(repo) if e["kind"] == "reloaded"] == [True, None, None]


# ---------------------------------------------------------------- N3b: a linked dispatch folder is a usage error
def test_W12c_N3b_a_linked_dispatch_folder_exits_64_not_70(cli, xproj, tmp_path, monkeypatch):
    (xproj / "T-007.md").write_text(REVIEW_TASK)
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "a commit to review")
    outside = tmp_path / "outside"
    outside.mkdir()
    (xproj / ".steward").mkdir(exist_ok=True)
    shutil.rmtree(xproj / ".steward/dispatch", ignore_errors=True)
    os.symlink(outside, xproj / ".steward/dispatch")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "codex").write_text("#!/bin/sh\nexit 0\n")
    (bin_ / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    code, out, err = cli("task", "dispatch", "T-007.md", "--to", "codex")
    assert code == 64, (code, out, err)
    assert "cannot be used for a review clone" in err
    assert list(outside.iterdir()) == []
    with pytest.raises(RuntimeError, match="cannot be used for a review clone"):
        dp.review_clone(xproj, "T-1")
