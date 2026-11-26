"""v0.4.1: signed authorizations, policy baseline (R-33) and ledger anchors. Uses software SSH keys in a temporary
repository (hardware-key prompts cannot be automated; the tests say so). Skipped without git or ssh-keygen."""

import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from steward import authorize as az
from steward.ledger import Ledger

from conftest import codes, one

pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def keygen(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "", "-f", str(path)], check=True)
    return path.with_suffix(".pub").read_text().strip()


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config-home"))  # never the real per-user trust file
    monkeypatch.delenv("STEWARD_TRUST_BASELINE", raising=False)
    monkeypatch.delenv("STEWARD_TRUST_SIGNERS", raising=False)
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "Test")
    sh(r, "git", "config", "user.email", "test@example.org")
    sh(r, "git", "config", "gpg.format", "ssh")
    sh(r, "git", "config", "tag.gpgSign", "false")
    pub = keygen(tmp_path / "human")
    sh(r, "git", "config", "user.signingkey", str(tmp_path / "human"))
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[policy]\nbaseline = "main"\n\n[run]\n')
    (r / "development/allowed_signers").write_text(f'human@example.org namespaces="git" {pub}\n')
    (r / "development/revoked.txt").write_text("")
    (r / "approve.txt").write_text("protocol v1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "baseline")
    monkeypatch.chdir(r)
    assert cli("authorize", "pin")[0] == 0  # the human pins the trust root once (per-user, outside the repository)
    return r


def expires(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def approve(cli, repo, action="amend", obj="approve.txt", exp=None):
    code, out, _ = cli("authorize", "prepare", action, "--object", obj, "--expires", exp or expires(), "--summary", "test")
    assert code == 0
    nonce = out.split("authorize sign ")[1].strip()
    code, out, err = cli("authorize", "sign", nonce)
    assert code == 0, err
    return out.split("signed ")[1].strip()


def test_valid_authorization_verifies(cli, repo):
    tag = approve(cli, repo)
    code, out, _ = cli("authorize", "verify", tag, "--action", "amend", "--object", "approve.txt")
    assert code == 0 and "VERIFIED" in out and "human@example.org" in out


def test_prepare_alone_never_authorizes(cli, repo):
    cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires())
    assert az.list_tags(repo) == []  # only `git tag -s` (the human's key) creates an authorization


def test_unsigned_tag_refused(cli, repo):
    _, out, _ = cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires())
    nonce = out.split("authorize sign ")[1].strip()
    sh(repo, "git", "tag", "-a", f"steward/auth/{nonce}", "-F", f".steward/pending/{nonce}.txt")
    code, _, err = cli("authorize", "verify", f"steward/auth/{nonce}")
    assert code == 1 and "signature" in err


def test_wrong_signer_refused(cli, repo):
    keygen(repo.parent / "agent")
    sh(repo, "git", "config", "user.signingkey", str(repo.parent / "agent"))
    tag = approve(cli, repo)
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "signature" in err


def test_signer_added_only_in_working_tree_refused(cli, repo):
    agent_pub = keygen(repo.parent / "agent")
    with open(repo / "development/allowed_signers", "a") as f:
        f.write(f'agent@example.org namespaces="git" {agent_pub}\n')
    sh(repo, "git", "config", "user.signingkey", str(repo.parent / "agent"))
    tag = approve(cli, repo)
    assert cli("authorize", "verify", tag)[0] == 1  # signers are read from the baseline, not the working tree
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "FAIL" and {"code": "R-33.changed", "path": "development/allowed_signers"} in res["details"]


def test_object_changed_refused(cli, repo):
    tag = approve(cli, repo)
    (repo / "approve.txt").write_text("protocol v2\n")
    code, _, err = cli("authorize", "verify", tag, "--object", "approve.txt")
    assert code == 1 and "object" in err


def test_expired_and_wrong_action_refused(cli, repo):
    tag = approve(cli, repo, exp="2020-01-01T00:00:00Z")
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "expires" in err
    tag = approve(cli, repo)
    assert "action" in cli("authorize", "verify", tag, "--action", "unseal")[2]


def test_revoked_at_baseline_refused(cli, repo):
    tag = approve(cli, repo)
    nonce = tag.rsplit("/", 1)[1]
    (repo / "development/revoked.txt").write_text(nonce + "\n")
    sh(repo, "git", "commit", "-qam", "revoke")
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "revoked" in err


def test_single_use_consumed_refused(cli, repo):
    from steward.cli import _config  # noqa: F401
    import tomllib
    from steward.models import StewardConfig

    cfg = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    tag = approve(cli, repo)
    v = az.verify(repo, cfg, tag)
    az.consume(repo, cfg, v, "test")
    with pytest.raises(az.AuthError) as e:
        az.verify(repo, cfg, tag)
    assert e.value.step == "consumed"


def test_policy_change_authorized(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "FAIL"
    obj = next(d["value"] for d in res["details"] if d["code"] == "R-33.object")
    approve(cli, repo, action="policy.change", obj=obj)
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "PASS"


def test_prepare_uses_r33_object_and_one_signature_is_enough(cli, repo, capsys, monkeypatch):
    with (repo / "steward.toml").open("a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')
    _, rep = cli.check(repo, "policy")
    expected = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    file_hash = "sha256:" + hashlib.sha256((repo / "steward.toml").read_bytes()).hexdigest()

    code, _, err = cli("authorize", "prepare", "policy.change", "--object", file_hash, "--expires", expires())
    assert code == 1 and file_hash in err and expected in err
    assert az.pending(repo) == []

    code, out, err = cli("authorize", "prepare", "policy.change", "--expires", expires())
    assert code == 0, err
    nonce = out.split("authorize sign ")[1].strip()
    assert az.parse(az.read_pending(repo, nonce).decode())["object"] == expected
    assert one(cli.check(repo, "policy")[1], "R-33")["status"] == "INCOMPLETE"

    sign = az.sign

    def sign_after_notice(root, signing_nonce, data=None):
        notice = capsys.readouterr().out
        assert "matches R-33" in notice and expected in notice
        return sign(root, signing_nonce, data)

    monkeypatch.setattr(az, "sign", sign_after_notice)
    code, _, err = cli("authorize", "sign", nonce)
    assert code == 0, err
    assert az.list_tags(repo) == [f"steward/auth/{nonce}"]
    assert one(cli.check(repo, "policy")[1], "R-33")["status"] == "PASS"


def test_prepare_policy_change_refuses_when_policy_matches_baseline(cli, repo):
    code, _, err = cli("authorize", "prepare", "policy.change", "--expires", expires())
    assert code == 1 and "no policy change" in err
    assert az.pending(repo) == []


def test_sign_reports_stale_policy_object_before_signing(cli, repo, capsys, monkeypatch):
    with (repo / "steward.toml").open("a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')
    code, out, err = cli("authorize", "prepare", "policy.change", "--expires", expires())
    assert code == 0, err
    nonce = out.split("authorize sign ")[1].strip()
    original = az.parse(az.read_pending(repo, nonce).decode())["object"]
    with (repo / "steward.toml").open("a") as f:
        f.write('\n[gates.other]\nrequire = ["R-01"]\n')
    _, rep = cli.check(repo, "policy")
    expected = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")

    def sign_after_notice(root, signing_nonce, data=None):
        notice = capsys.readouterr().out
        assert "does not match R-33" in notice and expected in notice and original in notice
        assert data == az.read_pending(root, signing_nonce)
        return "test authorization"

    monkeypatch.setattr(az, "sign", sign_after_notice)
    code, _, err = cli("authorize", "sign", nonce)
    assert code == 0, err


def test_prepare_requires_object_for_other_actions(cli, repo):
    code, _, err = cli("authorize", "prepare", "amend", "--expires", expires())
    assert code == 64 and "--object" in err
    assert az.pending(repo) == []


def test_policy_matches_baseline_and_keys_reported(cli, repo):
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "PASS" and "R-33.signer" in codes(res)
    assert "hardware-backed: unknown" in cli("authorize", "keys")[1]


def test_no_baseline_is_unknown(cli, repo):
    (repo.parent / "config-home/trust.toml").unlink()  # unpinned: the working-tree ref is used, and it does not exist
    text = (repo / "steward.toml").read_text().replace('baseline = "main"', 'baseline = "origin/main"')
    (repo / "steward.toml").write_text(text)
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "UNKNOWN"


def test_anchor_detects_truncated_tail(cli, repo):
    import sys
    cli("run", "--", sys.executable, "-c", "pass")
    cli("run", "--", sys.executable, "-c", "pass")
    code, out, _ = cli("authorize", "anchor", "runs")
    nonce = out.split("authorize sign ")[1].strip()
    assert cli("authorize", "sign", nonce)[0] == 0
    _, rep = cli.check(repo)
    assert "R-31.anchor_ok" in codes(next(r for r in rep["verdict"]["results"] if r["rule"] == "R-31" and "runs" in r["subject"]))
    p = repo / "development/runs.jsonl"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:-1]) + "\n")  # the last run's outcome removed
    _, rep = cli.check(repo)
    res = next(r for r in rep["verdict"]["results"] if r["rule"] == "R-31" and "runs" in r["subject"])
    assert res["status"] == "FAIL" and "R-31.anchor_mismatch" in codes(res)


def test_payload_parser_is_strict():
    good = az.render({k: "x" for k in az.FIELDS} | {"action": "amend"}, "s")
    assert az.parse(good)["action"] == "amend"
    with pytest.raises(az.AuthError):
        az.parse(good.replace("nonce: x", "nonce: x\nextra: y"))
    with pytest.raises(az.AuthError):
        az.parse(good.replace("action: amend", "action: approve-everything"))


def test_C1_repository_configured_signature_program_cannot_fake_verification(cli, repo):
    """Red-team C1: a writable .git/config must not be able to replace the signature verifier."""
    keygen(repo.parent / "agent")
    sh(repo, "git", "config", "user.signingkey", str(repo.parent / "agent"))
    tag = approve(cli, repo)  # signed by a key that is NOT an allowed signer
    fake = repo.parent / "fake-ssh-keygen"
    fake.write_text('#!/bin/sh\n'
                    'case "$*" in *find-principals*) echo human@example.org; exit 0;; esac\n'
                    'cat >/dev/null\n'
                    'echo \'Good "git" signature for human@example.org with ED25519 key SHA256:fake\'\n'
                    'echo \'Good "git" signature for human@example.org with ED25519 key SHA256:fake\' >&2\n'
                    'exit 0\n')
    fake.chmod(0o755)
    sh(repo, "git", "config", "gpg.ssh.program", str(fake))
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "signature" in err


# ---------------------------------------------------------------- red-team A3: trust root
def _agent_branch(repo):
    agent_pub = keygen(repo.parent / "agent")
    sh(repo, "git", "checkout", "-q", "-b", "agent")
    (repo / "development/allowed_signers").write_text(f'agent@example.org namespaces="git" {agent_pub}\n')
    sh(repo, "git", "commit", "-qam", "agent trusts itself")
    sh(repo, "git", "checkout", "-q", "main")
    sh(repo, "git", "config", "user.signingkey", str(repo.parent / "agent"))
    text = (repo / "steward.toml").read_text().replace('baseline = "main"', 'baseline = "agent"')
    (repo / "steward.toml").write_text(text)


def test_A3_pinned_trust_root_ignores_a_repointed_baseline(cli, repo):
    _agent_branch(repo)
    tag = approve(cli, repo)
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "signature" in err  # pinned keys are used, not the agent's branch
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"  # steward.toml differs from the pinned baseline


def test_A3_unpinned_trust_root_is_unknown_never_pass(cli, repo):
    (repo.parent / "config-home/trust.toml").unlink()
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "UNKNOWN" and "not pinned" in res["reason"]
    assert {"code": "R-33.trust_root", "value": "working-tree"} == {k: v for k, v in res["details"][0].items() if k != "message"}
    _agent_branch(repo)
    tag = approve(cli, repo)
    code, out, _ = cli("authorize", "verify", tag)
    assert code == 0 and "UNPINNED" in out  # the weakness is shown, not hidden


def test_A3_ci_environment_trust_root(cli, repo, monkeypatch):
    (repo.parent / "config-home/trust.toml").unlink()
    signers = repo.parent / "ci-signers"
    signers.write_text((repo / "development/allowed_signers").read_text())
    monkeypatch.setenv("STEWARD_TRUST_BASELINE", "main")
    monkeypatch.setenv("STEWARD_TRUST_SIGNERS", str(signers))
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "PASS" and "env trust root" in res["reason"]
    assert any(d["code"] == "R-33.fingerprint" and "SHA256:" in d["message"] for d in res["details"])


def _forged_pgp_tag(repo, cli, name):
    """A tag object whose message is a valid payload but whose 'signature' is a PGP block nobody signed."""
    _, out, _ = cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires())
    nonce = out.split("authorize sign ")[1].strip()
    payload = (repo / ".steward/pending" / f"{nonce}.txt").read_text()
    head = sh(repo, "git", "rev-parse", "HEAD").strip()
    obj = (f"object {head}\ntype commit\ntag {name}\ntagger T <t@example.org> 1700000000 +0000\n\n{payload}"
           "-----BEGIN PGP SIGNATURE-----\n\nZmFrZQ==\n-----END PGP SIGNATURE-----\n")
    tag_sha = subprocess.run(["git", "mktag"], cwd=repo, input=obj, capture_output=True, text=True, check=True).stdout.strip()
    sh(repo, "git", "update-ref", f"refs/tags/{name}", tag_sha)
    return name


def test_B4_repository_gpg_program_cannot_fake_a_pgp_signature(cli, repo):
    """Red-team B4: git picks its verifier from the signature type; a repository gpg.program must not decide."""
    fake = repo.parent / "fake-gpg"
    fake.write_text('#!/bin/sh\necho \'Good "git" signature for human@example.org with ED25519 key SHA256:fake\' >&2\n'
                    'echo "[GNUPG:] GOODSIG 0 human"\nexit 0\n')
    fake.chmod(0o755)
    sh(repo, "git", "config", "gpg.program", str(fake))
    sh(repo, "git", "config", "gpg.openpgp.program", str(fake))
    tag = _forged_pgp_tag(repo, cli, "steward/auth/forged-pgp")
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "signature" in err


def test_B4_valid_tag_verifies_whatever_the_repository_git_config(cli, repo):
    tag = approve(cli, repo)
    for k, v in (("gpg.format", "openpgp"), ("gpg.ssh.allowedSignersFile", "/nonexistent"), ("gpg.program", "/bin/false"),
                 ("gpg.ssh.program", "/bin/false")):
        sh(repo, "git", "config", k, v)
    code, out, _ = cli("authorize", "verify", tag)
    assert code == 0 and "VERIFIED" in out


# ---------------------------------------------------------------- red-team B3
def _repoint(repo, key, value):
    text = (repo / "steward.toml").read_text()
    text = text.replace("[policy]\n", f"[policy]\n{key} = \"{value}\"\n", 1)
    (repo / "steward.toml").write_text(text)


def test_B3_revocation_survives_a_repointed_revoked_path(cli, repo):
    tag = approve(cli, repo)
    (repo / "development/revoked.txt").write_text(tag.rsplit("/", 1)[1] + "\n")
    sh(repo, "git", "commit", "-qam", "revoke")
    _repoint(repo, "revoked", "development/empty.txt")  # agent edit, uncommitted
    code, _, err = cli("authorize", "verify", tag)
    assert code == 1 and "revoked" in err


def test_B3_consumption_survives_a_repointed_ledger(cli, repo):
    import tomllib
    from steward.models import StewardConfig

    tag = approve(cli, repo)
    cfg = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    az.consume(repo, cfg, az.verify(repo, cfg, tag), "test")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "consumed")
    _repoint(repo, "ledger", "development/fresh.jsonl")
    cfg2 = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    with pytest.raises(az.AuthError) as e:
        az.verify(repo, cfg2, tag)
    assert e.value.step == "consumed"


def test_B3_broken_authorization_ledger_refuses(cli, repo):
    import tomllib
    from steward.models import StewardConfig

    tag = approve(cli, repo)
    (repo / "development/authorizations.jsonl").write_text('{"seq": 5, "garbage": true}\n')
    cfg = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    with pytest.raises(az.AuthError) as e:
        az.verify(repo, cfg, tag)
    assert e.value.step == "consumed"


def test_B3_controlled_operations_require_a_pinned_trust_root(cli, repo):
    import tomllib
    from steward.models import StewardConfig

    tag = approve(cli, repo)
    (repo.parent / "config-home/trust.toml").unlink()
    cfg = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    assert az.verify(repo, cfg, tag).trust_source == "working-tree"  # informational verify still answers
    with pytest.raises(az.AuthError) as e:
        az.verify(repo, cfg, tag, require_pinned=True)
    assert e.value.step == "trust_root"


# ---------------------------------------------------------------- red-team round 3: D7, B4
def _cfg(repo):
    import tomllib
    from steward.models import StewardConfig
    return StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))


def test_D7_single_use_is_decided_when_it_is_consumed(cli, repo):
    cfg = _cfg(repo)
    tag = approve(cli, repo)
    first, second = az.verify(repo, cfg, tag), az.verify(repo, cfg, tag)  # both pass before either is consumed
    az.consume(repo, cfg, first, "first")
    with pytest.raises(az.AuthError) as e:
        az.consume(repo, cfg, second, "second")
    assert e.value.step == "consumed"


def test_D7_concurrent_uses_run_the_protected_operation_once(cli, repo):
    import threading
    cfg = _cfg(repo)
    tag = approve(cli, repo)
    verified = [az.verify(repo, cfg, tag) for _ in range(4)]
    barrier = threading.Barrier(len(verified))
    ran, refused = [], []

    def use(v, i):
        barrier.wait()
        try:
            az.consume(repo, cfg, v, f"use {i}")
        except az.AuthError:
            refused.append(i)
            return
        ran.append(i)  # the protected operation, reached only after a successful consumption

    threads = [threading.Thread(target=use, args=(v, i)) for i, v in enumerate(verified)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ran) == 1 and len(refused) == len(verified) - 1


def test_B4_the_callers_git_environment_cannot_choose_the_repository(cli, repo, tmp_path, monkeypatch):
    cfg = _cfg(repo)
    tag = approve(cli, repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    sh(elsewhere, "git", "init", "-q")
    for k, v in (("GIT_DIR", elsewhere / ".git"), ("GIT_WORK_TREE", elsewhere), ("GIT_OBJECT_DIRECTORY", elsewhere / ".git/objects"),
                 ("GIT_CONFIG_GLOBAL", elsewhere / "gitconfig")):
        monkeypatch.setenv(k, str(v))
    seen = []
    real = subprocess.run

    def spy(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append(dict(k.get("env") or {}))
        return real(cmd, *a, **k)
    monkeypatch.setattr(az.subprocess, "run", spy)
    assert az.verify(repo, cfg, tag).payload["action"] == "amend"
    allowed = {"GIT_CONFIG_NOSYSTEM", "GIT_NO_REPLACE_OBJECTS", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_NO_LAZY_FETCH", "GIT_ALLOW_PROTOCOL"}
    assert seen and all(not {k for k in env if k.startswith("GIT_")} - allowed for env in seen)
    assert all(env.get("GIT_CONFIG_GLOBAL") == os.devnull for env in seen)


# ---------------------------------------------------------------- re-verification of e7a6344: M1
def test_M1_blocked_verification_is_unknown_not_a_failure(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')
    _, rep = cli.check(repo)
    obj = next(d["value"] for d in one(rep, "R-33")["details"] if d["code"] == "R-33.object")
    approve(cli, repo, action="policy.change", obj=obj)
    az.READ_ONLY = True  # as inside the MCP server
    try:
        _, rep = cli.check(repo)
    finally:
        az.READ_ONLY = False
    res = one(rep, "R-33")
    assert res["status"] == "UNKNOWN" and "R-33.verification_unavailable" in codes(res)
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "PASS"  # the terminal still verifies


# ---------------------------------------------------------------- 0.8.1: the pinned baseline is a commit (adopter review)
def test_pin_stores_the_commit_so_a_moving_branch_cannot_absorb_an_unsigned_edit(cli, repo):
    import tomllib
    from steward import authorize as az2
    entry = next(iter(tomllib.loads(az2.trust_file().read_text())["repos"].values()))
    assert len(entry["baseline"]) == 40 and entry.get("baseline_ref") == "main"
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.sneaky]\nrequire = ["R-01"]\n')
    sh(repo, "git", "commit", "-qam", "unsigned policy edit on the baseline branch")
    _, rep = cli.check(repo)
    assert one(rep, "R-33")["status"] == "FAIL"  # the pinned commit, not the branch tip, is the baseline


def test_a_moving_baseline_is_reported(cli, repo, monkeypatch):
    import tomllib
    monkeypatch.setenv("STEWARD_TRUST_BASELINE", "main")
    monkeypatch.setenv("STEWARD_TRUST_SIGNERS", str(repo / "development/allowed_signers"))
    _, rep = cli.check(repo)
    assert "R-33.baseline_moving" in codes(one(rep, "R-33"))


def test_public_term_lists_are_part_of_the_policy(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "policy"\nfile = "development/policy_terms.txt"\npublic = true\n')
    (repo / "development/policy_terms.txt").write_text("AcmeHost\n")
    from steward import authorize as az2
    import tomllib
    from steward.models import StewardConfig
    cfg = StewardConfig.model_validate(tomllib.loads((repo / "steward.toml").read_text()))
    _, parts = az2.policy_bundle(repo, cfg)
    assert "development/policy_terms.txt" in parts


# ---------------------------------------------------------------- 0.8.1: trust model (adopter review 3)
def test_removing_policy_while_a_trust_root_is_pinned_fails(cli, repo):
    text = (repo / "steward.toml").read_text().replace('[policy]\nbaseline = "main"\n', "")
    (repo / "steward.toml").write_text(text)
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "FAIL" and "R-33.policy_removed" in codes(res)


def test_trust_signers_accepts_the_signer_line_itself(cli, repo, monkeypatch):
    monkeypatch.setenv("STEWARD_TRUST_BASELINE", sh(repo, "git", "rev-parse", "HEAD").strip())
    monkeypatch.setenv("STEWARD_TRUST_SIGNERS", (repo / "development/allowed_signers").read_text().strip())
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "PASS" and res["details"][0]["value"] == "env"


# ---------------------------------------------------------------- 0.8.1 review: N3 (high)
def test_N3_changing_repo_id_cannot_detach_the_pin(cli, repo):
    import uuid
    text = (repo / "steward.toml").read_text()
    old = text.split('repo_id = "')[1].split('"')[0]
    (repo / "steward.toml").write_text(text.replace(old, str(uuid.uuid4())))
    _, rep = cli.check(repo)
    res = one(rep, "R-33")
    assert res["status"] == "FAIL" and "R-33.repo_id_changed" in codes(res)


def test_N3_a_pinned_trust_root_puts_r33_in_every_gate(cli, repo):
    with open(repo / "steward.toml", "a") as f:
        f.write('\n[gates.quick]\nrequire = ["R-01"]\n')
    code, rep = cli.check(repo, gate="quick")   # an unsigned edit added this gate, so R-33 FAILs
    g = next(x for x in rep["verdict"]["gates"] if x["name"] == "quick")
    assert one(rep, "R-33")["status"] == "FAIL"
    assert not g["eligible"] and any(b["rule"] == "R-33" for b in g["blocking"]) and code == 1


def test_policy_change_counts_a_new_policy_file_without_a_key_error(monkeypatch, tmp_path):
    from steward import authorize as az
    calls = iter([("sha256:new", {"steward.toml": "a", "development/new.md": "b"}), ("sha256:old", {"steward.toml": "a"})])
    monkeypatch.setattr(az, "policy_bundle", lambda root, cfg, frm=None: next(calls))
    assert az.policy_change(tmp_path, None, "base") == ("sha256:new", ["development/new.md"])
