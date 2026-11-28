"""Signed human authorizations (v0.4.1; DESIGN_v0.4 §2, RELEASE_v0.4_SPEC §3).

A verified authorization is a signed annotated git tag `steward/auth/<nonce>` whose message is a canonical payload
naming exactly what is approved. Cryptography is delegated to git and ssh-keygen; steward only builds payloads and
checks them against the policy baseline. A signature proves possession of a key, not that its holder read the
payload; keys usable by an agent reduce an authorization to a recorded decision.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIONS = ("spend", "amend", "unseal", "freeze.confirmatory", "waive", "policy.change", "anchor", "pin.retire")
SINGLE_USE = ("amend", "unseal", "freeze.confirmatory", "waive", "policy.change", "pin.retire")
HEADER = "steward-authorization/1"
PENDING_MAX_BYTES = 1 << 20
FIELDS = ("repo_id", "action", "object", "scope", "budget", "expires", "baseline", "nonce")


class AuthError(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(f"{step}: {message}")
        self.step, self.message = step, message


@dataclass
class Verified:
    tag: str
    principal: str
    payload: dict[str, str]
    trust_source: str = "working-tree"  # env | user | working-tree (unpinned)


@dataclass
class Trust:
    baseline_ref: str
    signers: bytes | None
    source: str  # "env" (maintainer CI), "user" (per-user trust.toml), "working-tree" (unpinned)
    revoked: str = ""  # revocations stored with the pin (by value); unioned with every other source


def trust_file() -> Path:
    from .talk import config_home

    return config_home() / "trust.toml"


def env_value(value: str) -> bytes | None:
    """STEWARD_TRUST_SIGNERS is a file path, or the allowed-signers lines themselves (adopter review, 0.8.1): a CI
    secret naturally holds the line. A value with a key type in it is content; otherwise it is a path."""
    if re.search(r"\s(ssh-|sk-|ecdsa-)", value):
        return (value.rstrip("\n") + "\n").encode()
    p = Path(value)
    return p.read_bytes() if p.is_file() else None


_CHECKOUT_HINT: list[Path] = []


class checkout_hint:
    """While a hook checks a staged copy of a pushed commit, the invoking checkout's pin still applies (review O4)."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def __enter__(self) -> "checkout_hint":
        _CHECKOUT_HINT.append(self.root)
        return self

    def __exit__(self, *exc: Any) -> None:
        _CHECKOUT_HINT.pop()


def pin_for_checkout(root: Path | None) -> str | None:
    """The repo_id a per-user pin records for this checkout (or for the checkout a hook is checking on behalf of),
    or None (review N3, O4)."""
    import tomllib

    tf = trust_file()
    if (root is None and not _CHECKOUT_HINT) or not tf.is_file():
        return None
    try:
        repos = tomllib.loads(tf.read_text(encoding="utf-8")).get("repos", {})
    except (ValueError, RecursionError):
        return None
    places = {str(Path(root).resolve())} if root is not None else set()
    places |= {str(p) for p in _CHECKOUT_HINT}
    return next((rid for rid, e in repos.items() if e.get("checkout") in places), None)


def pinned_trust_exists(cfg: Any, root: Path | None = None) -> str | None:
    """Where a trust root for this repository is pinned outside it ("env", "user", "user-checkout"), or None. A pin
    recorded for this checkout counts even when the configuration's repo_id was changed (review N3)."""
    import tomllib

    if os.environ.get("STEWARD_TRUST_BASELINE") and os.environ.get("STEWARD_TRUST_SIGNERS"):
        return "env"
    tf = trust_file()
    if tf.is_file():
        try:
            if tomllib.loads(tf.read_text(encoding="utf-8")).get("repos", {}).get(cfg.steward.repo_id):
                return "user"
        except (ValueError, RecursionError):
            return "user"  # an unreadable pin is still a pin; never read as "no trust root"
    if pin_for_checkout(root):
        return "user-checkout"
    return None


def policy_active(cfg: Any, root: Path | None = None) -> bool:
    """[policy] is enforced: declared, and either active or pending with a trust root already pinned. `pending`
    never switches off a pinned policy (REQ-016)."""
    pol = getattr(cfg, "policy", None)
    if pol is None:
        return False
    return pol.state != "pending" or pinned_trust_exists(cfg, root) is not None


def resolve_trust(root: Path, cfg: Any) -> Trust:
    """The trust root, in order of strength (red-team A3): STEWARD_TRUST_BASELINE + STEWARD_TRUST_SIGNERS (maintainer
    CI), then the per-user trust.toml entry for this repo_id (signer keys stored by value), then the working-tree
    [policy] (unpinned: an agent that edits steward.toml can repoint it)."""
    import tomllib

    env_ref, env_signers = os.environ.get("STEWARD_TRUST_BASELINE"), os.environ.get("STEWARD_TRUST_SIGNERS")
    if env_ref and env_signers:
        rv = Path(os.environ.get("STEWARD_TRUST_REVOKED", "/nonexistent"))
        return Trust(env_ref, env_value(env_signers), "env", rv.read_text() if rv.is_file() else "")
    tf = trust_file()
    if tf.is_file():
        try:
            repos = tomllib.loads(tf.read_text(encoding="utf-8")).get("repos", {})
        except (ValueError, RecursionError):  # S2: a damaged pin is unavailable evidence, never "no pin"
            return Trust("", None, "unreadable")
        entry = repos.get(cfg.steward.repo_id) if isinstance(repos, dict) else None
        if entry and isinstance(entry, dict) and entry.get("baseline") and entry.get("signers"):
            return Trust(entry["baseline"], str(entry["signers"]).encode(), "user", entry.get("revoked", ""))
    return Trust(cfg.policy.baseline, None, "working-tree")


def pin(root: Path, cfg: Any, baseline: str | None) -> tuple[Path, str, bytes]:
    """Write the per-user trust entry for this repository: baseline ref and the signer keys at that baseline, by value."""
    import tomllib

    ref = baseline or cfg.policy.baseline
    commit = resolve_baseline(root, ref)
    signers = baseline_file(root, commit, cfg.policy.allowed_signers)
    if not signers:
        raise AuthError("pin", f"{cfg.policy.allowed_signers} not found at {ref}")
    tf = trust_file()
    data = tomllib.loads(tf.read_text(encoding="utf-8")) if tf.is_file() else {}
    revoked = (baseline_file(root, commit, cfg.policy.revoked) or b"").decode()
    # the baseline is stored as the commit it resolves to, never as a moving ref (adopter review, 0.8.1): a branch tip
    # that later gains an unsigned policy edit must not become the baseline. Re-pin to move it.
    data.setdefault("repos", {})[cfg.steward.repo_id] = {"baseline": commit, "baseline_ref": ref, "signers": signers.decode(),
                                                          "revoked": revoked, "checkout": str(root.resolve())}
    lines = ["# steward trust roots, outside every repository (red-team A3). One entry per repo_id.",
             "# The signer keys are stored by value: editing a repository cannot change them."]
    for rid in sorted(data["repos"]):
        e = data["repos"][rid]
        lines += [f'\n[repos."{rid}"]', f'baseline = "{e["baseline"]}"']
        if e.get("baseline_ref"):
            lines.append(f'baseline_ref = "{e["baseline_ref"]}"  # what was pinned; the baseline is the commit above')
        if e.get("checkout"):  # per-user file, outside every repository: a local path is fine here
            lines.append(f'checkout = "{e["checkout"]}"  # a repo_id edit in this checkout cannot detach the pin (review N3)')
        lines += ['signers = """', e["signers"].rstrip("\n"), '"""',
                  'revoked = """', e.get("revoked", "").rstrip("\n"), '"""']
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tf, ref, signers


def fingerprints(signers: bytes) -> list[str]:
    out = []
    for line in signers.decode("utf-8", errors="replace").splitlines():
        toks = line.split()
        key = next((i for i, t in enumerate(toks) if t.startswith(("ssh-", "sk-", "ecdsa-"))), None)
        if key is None or key + 1 >= len(toks):
            continue
        import base64
        try:
            blob = base64.b64decode(toks[key + 1])
        except ValueError:
            continue
        fp = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
        out.append(f"{toks[0]} {toks[key]} SHA256:{fp}")
    return out


def _git(root: Path, *args: str, check: bool = False, input: bytes | None = None,
         user_config: bool = False) -> subprocess.CompletedProcess:
    """Git, run on `root` and nothing else (red-team B4): every inherited GIT_* variable is dropped, so the caller
    cannot select another repository, object store or configuration (GIT_DIR, GIT_WORK_TREE, GIT_OBJECT_DIRECTORY,
    GIT_CONFIG_*). System and user configuration are ignored, except for signing, which needs the user's key."""
    from .fsutil import git_run

    return git_run(root, *args, input=input, check=check, user_config=user_config)


def ssh_keygen() -> str:
    """The verifier program, pinned by absolute path. Red-team C1: a repository's .git/config (writable by an agent)
    must not choose the program that decides whether a signature is good. A replaced binary on the user's own PATH,
    or in the system directories, is outside coverage."""
    for candidate in ("/usr/bin/ssh-keygen", "/bin/ssh-keygen", "/usr/local/bin/ssh-keygen", "/opt/homebrew/bin/ssh-keygen"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("ssh-keygen")
    if not found:
        raise AuthError("signature", "ssh-keygen not found; cannot verify SSH signatures")
    return str(Path(found).resolve())


def signing_config() -> tuple[str, ...]:
    """`git -c` options that pin the signing program for `git tag -s` (STW-057): SSH signatures only, made by the
    same pinned ssh-keygen that verifies them, and no repository-chosen command to pick the key. The tag message is
    kept verbatim (W12 F2): with Git's default cleanup, a repository's `core.commentChar` would strip lines from the
    payload, so the signed bytes would differ from the bytes shown and hashed."""
    return ("-c", "gpg.format=ssh", "-c", f"gpg.ssh.program={ssh_keygen()}", "-c", "gpg.ssh.defaultKeyCommand=",
            "-c", "tag.cleanup=verbatim")


def object_hash(root: Path, ref: str) -> str:
    if ref.startswith("sha256:") and re.match(r"^sha256:[0-9a-f]{64}$", ref):
        return ref
    p = (root / ref)
    if not p.is_file():
        raise AuthError("object", f"{ref} is neither sha256:<hex> nor a file")
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def render(fields: dict[str, str], summary: str) -> str:
    lines = [HEADER] + [f"{k}: {fields[k]}" for k in FIELDS] + ["summary: |"]
    lines += ["  " + l for l in (summary.strip().splitlines() or ["(none)"])]
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict[str, str]:
    text = text.split("-----BEGIN SSH SIGNATURE-----")[0].split("-----BEGIN PGP SIGNATURE-----")[0]
    lines = text.splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise AuthError("payload", "not a steward-authorization/1 payload")
    out: dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("summary: |"):
            out["summary"] = "\n".join(l[2:] for l in lines[i + 1:] if l.startswith("  ")).strip()
            break
        key, sep, value = line.partition(": ")
        if not sep or key not in FIELDS or key in out:
            raise AuthError("payload", f"unexpected line {line!r}")
        out[key] = value.strip()
        i += 1
    missing = [f for f in FIELDS if f not in out]
    if missing:
        raise AuthError("payload", f"missing fields {missing}")
    if out["action"] not in ACTIONS:
        raise AuthError("payload", f"unknown action {out['action']!r}")
    return out


def resolve_baseline(root: Path, ref: str) -> str:
    out = _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if out.returncode != 0:
        raise AuthError("baseline", f"baseline ref {ref!r} not found")
    return out.stdout.decode().strip()


def baseline_file(root: Path, commit: str, rel: str) -> bytes | None:
    out = _git(root, "cat-file", "blob", f"{commit}:{rel}")  # no textconv or filters, unlike `show` (L1)
    return out.stdout if out.returncode == 0 else None


def prepare(root: Path, cfg: Any, action: str, obj: str | None, scope: str, budget: str, expires: str,
            summary: str) -> tuple[str, Path]:
    if action not in ACTIONS:
        raise AuthError("prepare", f"action must be one of {ACTIONS}")
    try:
        datetime.strptime(expires, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise AuthError("prepare", "expires must be YYYY-MM-DDTHH:MM:SSZ (UTC)") from e
    if action == "policy.change":
        baseline, target = current_policy_change(root, cfg)
        if obj is not None and obj != target:
            raise AuthError("object", f"supplied {obj!r}; R-33 expects {target}")
    else:
        if obj is None:
            raise AuthError("object", f"--object is required for {action}")
        target = object_hash(root, obj)
        baseline = resolve_baseline(root, resolve_trust(root, cfg).baseline_ref)
    nonce = secrets.token_hex(16)
    fields = {"repo_id": cfg.steward.repo_id, "action": action, "object": target, "scope": scope or "-",
              "budget": budget or "none", "expires": expires, "baseline": baseline,
              "nonce": nonce}
    path = root / ".steward" / "pending" / f"{nonce}.txt"
    from .fsutil import LinkRefused, safe_write

    try:  # AF15: the queue is written through .steward/pending walked without links, as the signer reads it
        safe_write(root, f".steward/pending/{nonce}.txt", render(fields, summary).encode("utf-8"), exclusive=True)
    except LinkRefused as e:
        raise AuthError("prepare", f"the pending queue is reached through a link ({e}); nothing written") from None
    return nonce, path


def tag_name(payload: dict[str, str]) -> str:
    if payload["action"] == "anchor":
        scope = dict(kv.split("=", 1) for kv in payload["scope"].split() if "=" in kv)
        return f"steward/anchor/{scope.get('ledger', 'x')}/{scope.get('seq', '0')}"
    return f"steward/auth/{payload['nonce']}"


def read_pending(root: Path, nonce: str) -> bytes:
    """A queued payload's bytes, read once through `.steward/pending` walked without links (U3)."""
    from .fsutil import LinkRefused, open_dir_beneath

    if not re.fullmatch(r"[0-9a-f]{32}", nonce or ""):
        raise AuthError("sign", f"not a payload nonce: {nonce!r}")
    try:
        dfd = open_dir_beneath(root, (".steward", "pending"))
    except (LinkRefused, OSError):
        raise AuthError("sign", "the pending folder cannot be opened without links") from None
    try:
        fd = os.open(f"{nonce}.txt", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
    except OSError:
        raise AuthError("sign", f"no pending payload {nonce}") from None
    finally:
        os.close(dfd)
    with os.fdopen(fd, "rb") as f:
        data = f.read(PENDING_MAX_BYTES + 1)
    if len(data) > PENDING_MAX_BYTES:  # W12 F3: refused, never cut to a prefix that would then be hashed and signed
        raise AuthError("sign", f"pending payload {nonce} is larger than {PENDING_MAX_BYTES} bytes; nothing signed")
    return data


def decode(data: bytes) -> str:
    """A payload's bytes as text; bytes that are not UTF-8 are refused as a payload error (W12 F3)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise AuthError("payload", "not UTF-8") from None


def this_repo_id(root: Path) -> str:
    """The repo_id in `root`'s steward.toml; a configuration that cannot be read is refused (W12 F1)."""
    from .models import load_config

    try:
        return load_config(root).steward.repo_id
    except Exception:  # noqa: BLE001 - a repository whose configuration cannot be read is never signed for
        raise AuthError("repo_id", "this repository's steward.toml cannot be read; nothing signed") from None


def check_pinned(root: Path, repo_id: str) -> None:
    """Refuse when a per-user pin records another repo_id for this checkout (W12c, N2; as current_policy_change() does):
    steward.toml is in the working tree, which an agent can edit, so its repo_id alone does not say which repository
    this is."""
    pinned = pin_for_checkout(root)
    if pinned and pinned != repo_id:
        raise AuthError("repo_id", f"steward.toml names repo_id {repo_id!r}, but this checkout is pinned to {pinned!r}; "
                                   "nothing signed")


def check_repo_id(payload: dict[str, str], repo_id: str, root: Path | None = None) -> None:
    """Refuse a payload prepared for another repository (W12 F1): its signature would verify there. With `root`, the
    repo_id must also be the one pinned for that checkout, if any (W12c, N2)."""
    if root is not None:
        check_pinned(root, repo_id)
    if payload.get("repo_id") != repo_id:
        raise AuthError("repo_id", f"the payload belongs to repository {payload.get('repo_id')!r}, not this one "
                                   f"({repo_id!r}); nothing signed")


def payload_sha256(data: bytes) -> str:
    """The SHA-256 of a payload's bytes, as `authorize pending --format json` reports it (`payload_sha256`)."""
    return hashlib.sha256(data).hexdigest()


def sign_argv(nonce: str, digest: str, repo: Path | None = None) -> list[str] | None:
    """P03: the exact `authorize sign` command bound to the payload bytes whose SHA-256 is `digest`, as arguments;
    `--repo` names a peer project's checkout. None when `nonce` or `digest` cannot be signed as given."""
    if not (re.fullmatch(r"[0-9a-f]{32}", nonce or "") and re.fullmatch(r"[0-9a-f]{64}", digest or "")):
        return None
    return ["steward", "authorize", "sign", nonce, "--expect-sha256", digest, *(["--repo", str(repo)] if repo else [])]


def check_digest(data: bytes, expect_sha256: str | None) -> None:
    """Refuse when the payload's bytes no longer have the hash the human was shown (STW-050, STW-057)."""
    if expect_sha256 is None:
        return
    want = expect_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", want):
        raise AuthError("sign", f"--expect-sha256 must be 64 hexadecimal digits, got {expect_sha256!r}")
    got = payload_sha256(data)
    if got != want:
        raise AuthError("sign", f"the payload changed since it was shown: its sha256 is {got}, expected {want}; "
                                "nothing signed. Read it again (steward authorize pending) before signing")


_NAMED_ESCAPES = {"\t": "\\t", "\r": "\\r", "\\": "\\\\"}


def visible(data: bytes | str) -> tuple[str, int]:
    """The payload as text with every control, format (bidirectional, zero-width), separator, private-use or
    undecodable character written as an escape (`\\x1b`, `\\r`, `\\u202e`), and a backslash as `\\\\`, so an escape
    in the output always stands for one character: `\\x80` – `\\xff` are bytes that are not UTF-8, `\\u0080` and up
    are characters. Line feeds are kept. Returns the text and how many characters
    were escaped (backslashes not counted)."""
    import unicodedata

    text = data.decode("utf-8", errors="surrogateescape") if isinstance(data, bytes) else data
    out, hidden = [], 0
    for ch in text:
        o = ord(ch)
        if ch == "\n":
            out.append(ch)
        elif ch == "\\":
            out.append(_NAMED_ESCAPES[ch])
        elif 0xDC80 <= o <= 0xDCFF:  # a byte that is not UTF-8, kept by surrogateescape
            out.append(f"\\x{o - 0xDC00:02x}")
            hidden += 1
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            out.append(_NAMED_ESCAPES.get(ch) or (f"\\x{o:02x}" if o < 0x80 else f"\\u{o:04x}" if o < 0x10000
                                                   else f"\\U{o:08x}"))
            hidden += 1
        else:
            out.append(ch)
    return "".join(out), hidden


def sign(root: Path, nonce: str, data: bytes | None = None, *, expect_sha256: str | None = None,
         repo_id: str | None = None) -> str:
    """Create the signed tag from exactly `data` (the bytes the human was shown), or from the payload read now. The
    signing key's own prompt (PIN, touch, confirmation) is the human step (U3: the signed bytes are the shown bytes).
    With `expect_sha256`, the bytes must still have that hash, or nothing is signed. The payload's repo_id must be
    `repo_id` (by default, the one in `root`'s steward.toml), or nothing is signed (W12 F1); a pin for this checkout
    that records another repo_id refuses signing (W12c, N2)."""
    import tempfile

    data = read_pending(root, nonce) if data is None else data
    check_digest(data, expect_sha256)
    payload = parse(decode(data))
    if payload.get("nonce") != nonce:
        raise AuthError("sign", "the payload's nonce is not the one named")
    check_repo_id(payload, this_repo_id(root) if repo_id is None else repo_id, root)
    tag = tag_name(payload)
    with tempfile.NamedTemporaryFile("wb", prefix="steward-sign-", suffix=".txt", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        # STW-057: the signing program is pinned like the verifier (red-team C1). A repository's own .git/config is
        # writable by an agent; without these, `gpg.ssh.program` (or `gpg.format` with `gpg.program`) there would choose
        # the program that runs as the human and holds their key agent, and `gpg.ssh.defaultKeyCommand` a command run
        # to pick the key. The key itself may still come from any config: a signature by the wrong key is refused when
        # it is verified against the allowed signers.
        out = _git(root, *signing_config(), "tag", "-s", "--cleanup=verbatim", tag, "-F", tmp, user_config=True)
    finally:
        os.unlink(tmp)
    if out.returncode != 0:
        raise AuthError("sign", out.stderr.decode("utf-8", errors="replace").strip() or "git tag -s failed")
    return tag


def pending(root: Path, now: datetime | None = None, *, include_digest: bool = False,
            repo_id: str | None = None) -> list[dict[str, str]]:
    """The queue of prepared, unsigned authorizations (0.12.0, deferred signing): each payload under
    .steward/pending/ with its nonce, its tag and a state: `waiting`, `signed` (its tag exists), `expired`, or
    `foreign` (W12 F1: its repo_id is not `repo_id`, by default the one in `root`'s steward.toml; a foreign payload is
    never signable here, and with no readable configuration every payload is foreign; so is every payload when a pin
    for this checkout records another repo_id, W12c N2). Links and unreadable files are
    skipped; the queue is local and never itself evidence of approval.
    With a digest, parse and hash the same bytes from a link-safe read."""
    from .records import open_rel

    d = root / ".steward" / "pending"
    if not d.is_dir() or d.is_symlink():
        return []
    now = now or datetime.now(timezone.utc)
    if repo_id is None:
        try:
            repo_id = this_repo_id(root)
        except AuthError:
            repo_id = None
    if repo_id is not None:
        try:
            check_pinned(root, repo_id)
        except AuthError:
            repo_id = None
    out = []
    for f in sorted(d.glob("*.txt")):
        if f.is_symlink() or not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        try:
            if include_digest:
                with io.BufferedReader(open_rel(root, rel)) as stream:
                    data = stream.read(PENDING_MAX_BYTES + 1)
                if len(data) > PENDING_MAX_BYTES:
                    continue
                payload = parse(data.decode("utf-8"))
                payload["payload_sha256"] = hashlib.sha256(data).hexdigest()
            else:
                payload = parse(f.read_text(encoding="utf-8"))
            exp = datetime.strptime(payload["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            tag = tag_name(payload)
        except (AuthError, KeyError, ValueError, OSError, UnicodeDecodeError):
            continue
        if payload.get("nonce") != f.stem:
            continue
        signed = _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0
        state = ("foreign" if repo_id is None or payload.get("repo_id") != repo_id
                 else "signed" if signed else "expired" if exp < now else "waiting")
        out.append({**payload, "tag": tag, "state": state, "path": rel})
    return out


def verify_record(root: Path, cfg: Any, tag: str) -> dict[str, str]:
    """A signed authorization or anchor tag as a record (U2, DEF-013): its signature by an allowed signer of the
    pinned trust root, this repository's repo_id, and a payload whose own tag name is this tag. Expiry, revocation and
    use do not make a signed record unpublishable. Raises AuthError; returns the payload."""
    trust = resolve_trust(root, cfg)
    if trust.source in ("unreadable", "working-tree"):
        raise AuthError("trust_root", "the trust root is not pinned here; run `steward authorize pin` first")
    base = resolve_baseline(root, trust.baseline_ref)
    signers = trust.signers or baseline_file(root, base, cfg.policy.allowed_signers)
    if not signers:
        raise AuthError("allowed_signers", "no allowed signers")
    _principal, raw = verify_ssh_tag(root, tag, signers)
    payload = parse(raw.split("\n\n", 1)[1] if "\n\n" in raw else "")
    if payload.get("repo_id") != cfg.steward.repo_id:
        raise AuthError("repo_id", "authorization belongs to another repository")
    if tag_name(payload) != tag:
        raise AuthError("payload", "its name does not match the payload it carries")
    return payload


def _baseline_policy(root: Path, commit: str) -> dict[str, Any]:
    import tomllib

    raw = baseline_file(root, commit, "steward.toml")
    try:
        return (tomllib.loads(raw.decode("utf-8")) if raw else {}).get("policy", {}) or {}
    except (ValueError, RecursionError, UnicodeDecodeError):
        return {}


def revoked_nonces(root: Path, cfg: Any, trust: "Trust", commit: str) -> set[str]:
    """Union of every revocation source (red-team B3): the pin, the baseline's own [policy] path, the working-tree path,
    each at the baseline and in the working tree. Revocation only restricts, so a union can never grant."""
    texts = [trust.revoked]
    for path in {cfg.policy.revoked, _baseline_policy(root, commit).get("revoked", "development/revoked.txt")}:
        texts.append((baseline_file(root, commit, path) or b"").decode("utf-8", errors="replace"))
        if (root / path).is_file():
            texts.append((root / path).read_text(encoding="utf-8", errors="replace"))
    return {l.strip() for t in texts for l in t.splitlines() if l.strip() and not l.startswith("#")}


def verify(root: Path, cfg: Any, tag: str, *, action: str | None = None, expected_object: str | None = None,
           now: datetime | None = None, consumed: set[str] | None = None, require_pinned: bool = False) -> Verified:
    """All checks of DESIGN_v0.4 §2.2. Raises AuthError naming the failed step. Controlled operations pass
    require_pinned=True: an unpinned trust root is refused (red-team B3)."""
    pol = cfg.policy
    trust = resolve_trust(root, cfg)
    if trust.source == "unreadable":  # S2: never verified against a repository-selected signer list instead
        raise AuthError("trust_root", "the per-user trust pin cannot be read; repair it or re-pin")
    if require_pinned and trust.source == "working-tree":
        raise AuthError("trust_root", "trust root not pinned: run `steward authorize pin` (or set STEWARD_TRUST_* in CI)")
    base = resolve_baseline(root, trust.baseline_ref)
    signers = trust.signers if trust.source != "working-tree" else baseline_file(root, base, pol.allowed_signers)
    if not signers:
        raise AuthError("allowed_signers", f"no allowed signers ({trust.source} trust root, baseline {trust.baseline_ref})")
    principal, raw = verify_ssh_tag(root, tag, signers)
    payload = parse(raw.split("\n\n", 1)[1] if "\n\n" in raw else "")
    if payload["repo_id"] != cfg.steward.repo_id:
        raise AuthError("repo_id", "authorization belongs to another repository")
    if action and payload["action"] != action:
        raise AuthError("action", f"authorizes {payload['action']}, not {action}")
    if expected_object and payload["object"] != expected_object:
        raise AuthError("object", "the object changed since it was approved")
    now = now or datetime.now(timezone.utc)
    if datetime.strptime(payload["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < now:
        raise AuthError("expires", f"expired at {payload['expires']}")
    if _git(root, "merge-base", "--is-ancestor", payload["baseline"], base).returncode != 0:
        raise AuthError("baseline", "approved against a policy baseline that is not an ancestor of the current one")
    if payload["nonce"] in revoked_nonces(root, cfg, trust, base):
        raise AuthError("revoked", "authorization revoked")
    if payload["action"] in SINGLE_USE and payload["nonce"] in (consumed if consumed is not None else consumed_nonces(root, cfg, base)):
        raise AuthError("consumed", "single-use authorization already used")
    return Verified(tag, principal, payload, trust.source)


SSH_BEGIN = b"-----BEGIN SSH SIGNATURE-----"


READ_ONLY = False  # set by the MCP server: it never verifies signatures (verification writes temporary files; L2)


def verify_ssh_tag(root: Path, tag: str, signers: bytes) -> tuple[str, str]:
    """Verify an annotated tag's SSH signature without `git verify-tag` (red-team B4): the tag object is read as raw
    bytes with replacement objects disabled, and the pinned ssh-keygen checks the signed bytes against the given
    allowed-signers content. Git configuration plays no part. Only SSH signatures are accepted."""
    if READ_ONLY:
        raise AuthError("unavailable", "signatures are not verified through the MCP server; run `steward check` in a terminal")
    name = tag[len("refs/tags/"):] if tag.startswith("refs/tags/") else tag
    if _git(root, "cat-file", "-t", f"refs/tags/{name}").stdout.decode().strip() != "tag":
        raise AuthError("tag", f"{tag} is not an annotated tag")
    raw = _git(root, "cat-file", "tag", f"refs/tags/{name}").stdout
    if SSH_BEGIN not in raw:
        if b"-----BEGIN PGP SIGNATURE-----" in raw or b"-----BEGIN SIGNED MESSAGE-----" in raw:
            raise AuthError("signature", "only SSH signatures are accepted")
        raise AuthError("signature", "the tag is not signed")
    idx = raw.index(SSH_BEGIN)
    signed, sig = raw[:idx], raw[idx:]
    header = signed.split(b"\n\n", 1)[0].decode("utf-8", errors="replace")
    if f"\ntag {name}\n" not in "\n" + header + "\n":
        raise AuthError("tag", "the tag object names a different tag")
    keygen = ssh_keygen()
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    with tempfile.TemporaryDirectory() as d:
        sp, fp = Path(d) / "sig", Path(d) / "signers"
        sp.write_bytes(sig)
        fp.write_bytes(signers)
        found = subprocess.run([keygen, "-Y", "find-principals", "-s", str(sp), "-f", str(fp)],
                               capture_output=True, timeout=60, env=env)
        for principal in found.stdout.decode("utf-8", errors="replace").split():
            ok = subprocess.run([keygen, "-Y", "verify", "-f", str(fp), "-I", principal, "-n", "git", "-s", str(sp)],
                                input=signed, capture_output=True, timeout=60, env=env)
            if ok.returncode == 0:
                return principal, signed.decode("utf-8", errors="replace")
    raise AuthError("signature", "missing, invalid, or not from a pinned signer")


def consumed_nonces(root: Path, cfg: Any, commit: str | None = None) -> set[str]:
    """Union of consumed nonces from every authorization ledger path (working tree and baseline policy), each read in
    the working tree and at the baseline (red-team B3). A ledger that is not intact refuses: never read as empty."""
    from .ledger import verify as lverify

    paths = {cfg.policy.ledger}
    if commit:
        paths.add(_baseline_policy(root, commit).get("ledger", "development/authorizations.jsonl"))
    nonces: set[str] = set()
    for path in sorted(paths):
        sources: list[Path] = [root / path]
        tmp = None
        if commit:
            data = baseline_file(root, commit, path)
            if data:
                tmp = tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False)
                tmp.write(data)
                tmp.close()
                sources.append(Path(tmp.name))
        try:
            for src in sources:
                if not src.is_file():
                    continue
                v = lverify(src)
                if v.errors:
                    raise AuthError("consumed", f"authorization ledger {path} is not intact; restore it from version control")
                nonces |= {e["nonce"] for e in v.entries if e.get("kind") == "consume"}
        finally:
            if tmp:
                Path(tmp.name).unlink(missing_ok=True)
    return nonces


def consume(root: Path, cfg: Any, verified: Verified, use: str) -> None:
    from .ledger import Ledger

    nonce = verified.payload["nonce"]

    def decide(entries: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        # red-team D7: single use is decided under the ledger lock, not only by the earlier verify()
        if verified.payload["action"] in SINGLE_USE and any(e.get("kind") == "consume" and e.get("nonce") == nonce for e in entries):
            raise AuthError("consumed", "single-use authorization already used")
        return "consume", {"nonce": nonce, "tag": verified.tag, "action": verified.payload["action"],
                           "principal": verified.principal, "use": use}

    Ledger(root / cfg.policy.ledger, "authorizations", cfg.steward.repo_id).transaction(decide)


def tag_times(root: Path) -> dict[str, int]:
    """X05: each authorization or anchor tag -> when it was made (its tagger date, or its commit's)."""
    out = _git(root, "for-each-ref", "--format=%(creatordate:unix) %(refname:short)", "refs/tags/steward/")
    times: dict[str, int] = {}
    for line in (out.stdout.decode(errors="replace").splitlines() if out.returncode == 0 else []):
        stamp, _, tag = line.partition(" ")
        if stamp.isdigit() and tag:
            times[tag] = int(stamp)
    return times


def list_tags(root: Path, prefix: str = "steward/auth/") -> list[str]:
    out = _git(root, "tag", "-l", f"{prefix}*")
    return sorted(t for t in out.stdout.decode().splitlines() if t) if out.returncode == 0 else []


def ledger_anchors(root: Path, cfg: Any, name: str) -> tuple[list[tuple[int, str]], list[str]]:
    """Verified anchors (seq, head hash) for a ledger, and tags that failed verification."""
    good, bad = [], []
    if cfg is None or getattr(cfg, "policy", None) is None:
        return good, bad
    for tag in list_tags(root, f"steward/anchor/{name}/"):
        try:
            v = verify(root, cfg, tag, action="anchor")
        except AuthError:
            bad.append(tag)
            continue
        scope = dict(kv.split("=", 1) for kv in v.payload["scope"].split() if "=" in kv)
        if "seq" in scope and "head" in scope:
            good.append((int(scope["seq"]), scope["head"]))
    return good, bad


def policy_bundle(root: Path, cfg: Any, from_commit: str | None = None) -> tuple[str, dict[str, str | None]]:
    """Hash of the policy files (working tree, or a commit): steward.toml, allowed_signers, revoked list."""
    # public term lists are committed policy (adopter review, 0.8.1); private lists stay out of the repository
    paths = sorted({"steward.toml", cfg.policy.allowed_signers, cfg.policy.revoked}
                   | {t.file for t in getattr(cfg, "terms", []) or [] if t.public})
    parts: dict[str, str | None] = {}
    from .records import RecordRefused, read_rel

    for p in paths:
        if from_commit:
            data = baseline_file(root, from_commit, p)
        else:  # AF15: working-tree policy files are read inside the repository, never through a link
            try:
                data = read_rel(root, p)
            except RecordRefused as e:
                if e.reason != "missing":
                    raise AuthError("policy", f"{p}: {e}") from None
                data = None
        parts[p] = hashlib.sha256(data).hexdigest() if data is not None else None
    bundle = "\n".join(f"{p}\0{h}" for p, h in parts.items())
    return "sha256:" + hashlib.sha256(bundle.encode()).hexdigest(), parts


def policy_change(root: Path, cfg: Any, baseline: str) -> tuple[str | None, list[str]]:
    """Return the object R-33 checks and the paths changed against the baseline."""
    current, parts = policy_bundle(root, cfg)
    original, original_parts = policy_bundle(root, cfg, baseline)
    if current == original:
        return None, []
    return current, sorted(path for path in parts if parts[path] != original_parts.get(path))  # a new file counts


def current_policy_change(root: Path, cfg: Any) -> tuple[str, str]:
    """Resolve the baseline and object together for a policy approval."""
    pinned_rid = pin_for_checkout(root)
    if pinned_rid and pinned_rid != cfg.steward.repo_id:
        raise AuthError("repo_id", "repo_id differs from the one pinned for this checkout")
    if not policy_active(cfg, root):
        raise AuthError("policy", "an active [policy] is required")
    trust = resolve_trust(root, cfg)
    if trust.source == "unreadable":
        raise AuthError("trust_root", "the per-user trust pin cannot be read; repair it or re-pin")
    baseline = resolve_baseline(root, trust.baseline_ref)
    signers = trust.signers if trust.source != "working-tree" else baseline_file(root, baseline, cfg.policy.allowed_signers)
    if signers is None:
        raise AuthError("allowed_signers", "signing is not set up for the policy baseline")
    target, _ = policy_change(root, cfg, baseline)
    if target is None:
        raise AuthError("object", "no policy change: policy files match the baseline")
    return baseline, target


def signer_keys(text: str) -> list[dict[str, str]]:
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        toks = line.split()
        ktype = next((t for t in toks[1:] if t.startswith(("ssh-", "sk-", "ecdsa-"))), "unknown")
        keys.append({"principal": toks[0], "type": ktype,
                     "hardware": "yes" if ktype.startswith("sk-") else "unknown (software or agent key)"})
    return keys
