"""0.21.0 W06 (STW-050, STW-057): signing bound to the payload's hash, and prompts that show what is signed."""

import hashlib
import io
import json
import shutil
import sys

import pytest

from test_authorize import expires, repo, sh  # noqa: F401  (the signed-authorization fixture)

signing = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen")


def _prepare(cli, summary="approve protocol v1"):
    code, out, err = cli("authorize", "prepare", "amend", "--object", "approve.txt", "--expires", expires(),
                         "--summary", summary)
    assert code == 0, err
    return out.split("authorize sign ")[1].strip()


def _tags(repo):
    return sh(repo, "git", "tag", "-l", "steward/auth/*").split()


def _pending_file(repo, nonce):
    return repo / ".steward/pending" / f"{nonce}.txt"


class _Terminal(io.StringIO):
    def isatty(self):
        return True


# ---------------------------------------------------------------- authorize sign --expect-sha256
@signing
def test_sign_with_the_hash_pending_reported_signs(cli, repo):
    nonce = _prepare(cli)
    code, out, err = cli("authorize", "pending", "--format", "json")
    assert code == 0, err
    digest = next(i["payload_sha256"] for i in json.loads(out)["items"] if i["nonce"] == nonce)
    assert digest == hashlib.sha256(_pending_file(repo, nonce).read_bytes()).hexdigest()
    code, out, err = cli("authorize", "sign", nonce, "--expect-sha256", digest.upper())
    assert code == 0, err
    assert f"Payload sha256 {digest} matches the expected hash." in out
    assert f"signed steward/auth/{nonce}" in out
    code, _, err = cli("authorize", "verify", f"steward/auth/{nonce}")
    assert code == 0, err


@signing
def test_sign_refuses_a_payload_changed_after_its_hash_was_shown(cli, repo):
    nonce = _prepare(cli)
    p = _pending_file(repo, nonce)
    shown = hashlib.sha256(p.read_bytes()).hexdigest()
    p.write_text(p.read_text().replace("approve protocol v1", "approve anything"))  # changed after it was shown
    code, out, err = cli("authorize", "sign", nonce, "--expect-sha256", shown)
    assert code == 1
    assert "NOT AUTHORIZED: sign: the payload changed since it was shown" in err
    assert f"expected {shown}" in err and "nothing signed" in err
    assert "signed" not in out
    assert _tags(repo) == []


@signing
def test_sign_refuses_a_hash_that_is_not_64_hex_digits(cli, repo):
    nonce = _prepare(cli)
    for bad in ("sha256:" + "0" * 64, "0" * 63, "g" * 64, ""):
        code, _, err = cli("authorize", "sign", nonce, "--expect-sha256", bad)
        assert code == 1 and "--expect-sha256 must be 64 hexadecimal digits" in err, (bad, err)
    assert _tags(repo) == []


@signing
def test_sign_without_the_option_is_unchanged(cli, repo):
    nonce = _prepare(cli)
    code, out, err = cli("authorize", "sign", nonce)
    assert code == 0, err
    assert out == f"signed steward/auth/{nonce}\n"


def test_sign_checks_the_hash_of_the_bytes_it_signs(tmp_path):
    from steward import authorize as az

    with pytest.raises(az.AuthError, match="changed since it was shown"):
        az.sign(tmp_path, "0" * 32, b"steward-authorization/1\n", expect_sha256="0" * 64)


# ---------------------------------------------------------------- sign-pending: what the human sees
def test_visible_escapes_controls_and_keeps_line_feeds():
    from steward import authorize as az

    text, hidden = az.visible("a\x1b[2Kb\rc\td‮e​f\u0085g\\h\ni".encode() + b"\xff")
    assert text == "a\\x1b[2Kb\\rc\\td\\u202ee\\u200bf\\u0085g\\\\h\ni\\xff"
    assert hidden == 7
    assert az.visible("plain summary: ok\n") == ("plain summary: ok\n", 0)


@signing
def test_sign_pending_shows_control_characters_visibly(cli, repo):
    nonce = _prepare(cli)
    p = _pending_file(repo, nonce)
    hostile = "  approve protocol v1\x1b[2K\r  ‮approve anything\n"
    p.write_bytes(p.read_text().replace("  approve protocol v1\n", hostile).encode())
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0, err
    assert "\x1b" not in out and "\r" not in out and "‮" not in out
    assert "approve protocol v1\\x1b[2K\\r  \\u202eapprove anything" in out
    assert "WARNING: this payload holds 3 control or invisible character(s)" in out
    assert f"payload sha256 {digest}  action amend" in out
    assert f"signed steward/auth/{nonce}" in out


@signing
def test_sign_pending_listing_shows_a_summary_s_controls_visibly(cli, repo):
    nonce = _prepare(cli)
    p = _pending_file(repo, nonce)
    p.write_text(p.read_text().replace("approve protocol v1", "ok\x1b]0;title\x07"))
    code, out, err = cli("authorize", "pending")
    assert code == 0, err
    assert "\x1b" not in out and "\x07" not in out and "ok\\x1b]0;title\\x07" in out


@signing
def test_sign_pending_prompt_names_the_digest_and_the_action(cli, repo, monkeypatch):
    nonce = _prepare(cli)
    digest = hashlib.sha256(_pending_file(repo, nonce).read_bytes()).hexdigest()
    prompts = []
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "n")
    code, out, err = cli("authorize", "sign-pending")
    assert code == 0, err
    assert prompts == [f"Sign . {nonce[:12]}: action amend, payload sha256 {digest}? [y/N] "]
    assert "skipped" in out and _tags(repo) == []


@signing
def test_sign_pending_signs_after_yes_at_the_prompt(cli, repo, monkeypatch):
    nonce = _prepare(cli)
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    code, out, err = cli("authorize", "sign-pending")
    assert code == 0, err
    assert _tags(repo) == [f"steward/auth/{nonce}"]


@signing
def test_sign_pending_checks_the_bytes_it_read_not_the_listing(cli, repo, monkeypatch):
    from steward import authorize as az

    nonce = _prepare(cli)
    real = az.read_pending

    def other_repository(root, n):  # the file is replaced between the listing and the read
        data = real(root, n).decode()
        rid = next(line.split(": ", 1)[1] for line in data.splitlines() if line.startswith("repo_id: "))
        return data.replace(rid, "00000000-0000-4000-8000-000000000000").encode()
    monkeypatch.setattr(az, "read_pending", other_repository)
    code, out, err = cli("authorize", "sign-pending", "--yes")
    assert code == 0, err
    assert "(skipped: it changed since it was listed)" in out
    assert _tags(repo) == []
