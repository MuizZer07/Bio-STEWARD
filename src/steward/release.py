"""Release integrity (v0.6.1, RELEASE_v0.6_SPEC §2): manifest, distribution audit, CITATION.cff structure.

The manifest records what is published (artifact hashes, lock files, commit). The audit lists every member of each
wheel, source archive or tarball (standard library only) and refuses development-only and secret-looking content.
Neither establishes that the software is correct; they establish that what ships is what was declared.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from .fsutil import glob_match

DEFAULT_EXCLUDE = [
    "development/**", ".steward/**", "**/.steward/**", ".git/**", ".github/**", ".env", "**/.env", "*.env", "**/*.env",
    "**/*.pem", "**/*.key", "**/id_rsa*", "**/id_ed25519*", "**/*.p12", "**/.DS_Store", ".venv/**", "**/__pycache__/**",
]
ARTIFACT_EXT = (".whl", ".tar.gz", ".zip", ".tgz")
CFF_REQUIRED = ("cff-version", "message", "title", "authors")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifacts(dist: Path) -> list[Path]:
    return sorted(p for p in dist.iterdir() if p.is_file() and p.name.endswith(ARTIFACT_EXT)) if dist.is_dir() else []


def members(p: Path) -> list[tuple[str, bytes | None]]:
    """(relative member name, small text payload or None). Source archives drop their top-level directory."""
    out: list[tuple[str, bytes | None]] = []
    if p.name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                if not info.is_dir():
                    data = z.read(info) if info.file_size <= 1 << 20 else None
                    out.append((info.filename, data))
    else:
        with tarfile.open(p) as t:
            for m in t.getmembers():
                if not m.isfile():
                    continue
                name = m.name.split("/", 1)[1] if "/" in m.name else m.name
                f = t.extractfile(m) if m.size <= 1 << 20 else None
                out.append((name, f.read() if f else None))
    return out


def audit(dist: Path, exclude: list[str], lists: list[Any] | None = None, local_paths: bool = True,
          allow: list[str] | None = None) -> dict[str, Any]:
    """Members of every artifact against the exclusions, the term lists and the local-path pattern (0.8.1: one scan,
    shared with R-07; SR-004, SR-005, FB-11). `lists` are privacy.TermSource objects (read); legacy callers may pass
    plain strings, taken as a private list."""
    from . import privacy as pv

    groups: list[tuple[list[str], list[Any]]] = []  # (allow globs of the list, its terms): each list's own exemptions
    legacy = [s for s in lists or [] if isinstance(s, str)]
    if legacy:
        groups.append(([], [pv.Term("denylist", i, t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I), False)
                            for i, t in enumerate(legacy, start=1)]))
    for src in lists or []:
        if not isinstance(src, str) and src.state == "ok":
            groups.append((list(src.allow), src.terms))
    allow = allow or []
    findings: list[dict[str, Any]] = []
    listing: dict[str, int] = {}
    unscanned: list[dict[str, Any]] = []
    list_files = {s.file for s in lists or [] if not isinstance(s, str)}
    for src in lists or []:  # review N7: a list that could not be read leaves the audit incomplete; never a clean verdict
        if not isinstance(src, str) and (src.errors or (src.public and src.state != "ok")):
            findings.append({"artifact": "(configuration)", "member": src.file, "code": "terms_unavailable", "term": src.name})
    for art in artifacts(dist):
        ms = members(art)
        listing[art.name] = len(ms)
        for name, data in ms:
            if any(glob_match(name, e) for e in exclude):
                findings.append({"artifact": art.name, "member": name, "code": "excluded"})
                continue
            if any(glob_match(name, a) for a in allow) or name in list_files:  # a packaged list is exempt from itself
                continue
            terms = [t for globs, ts in groups if not any(glob_match(name, g) for g in globs) for t in ts]
            for t in terms:
                if t.regex.search(name):
                    findings.append({"artifact": art.name, "member": name, "code": "private_term_in_name" if not t.public
                                     else "policy_term_in_name", "term": t.label})
            if data is None or b"\x00" in data[:8192]:
                unscanned.append({"artifact": art.name, "member": name, "reason": "too large" if data is None else "binary"})
                continue
            hits, _ = pv.scan_text(data.decode("utf-8", errors="replace"), terms, local_paths, rel=name,
                                   sha=hashlib.sha256(data).hexdigest())
            for h in hits:
                if h["kind"] == "local_path":
                    findings.append({"artifact": art.name, "member": name, "code": "local_path", "line": h["line"]})
                else:
                    findings.append({"artifact": art.name, "member": name, "line": h["line"], "term": h["term"].label,
                                     "code": "policy_term" if h["term"].public else "private_term",
                                     **({"value": h["term"].text} if h["term"].public else {})})
    return {"artifacts": listing, "findings": findings, "unscanned": unscanned}


def artifact_version(name: str) -> str | None:
    """The version in a distribution's file name: a wheel's second field, or a source archive's last `-` field."""
    if name.endswith(".whl"):
        parts = name[:-4].split("-")
        return parts[1] if len(parts) >= 3 else None
    for ext in (".tar.gz", ".tgz", ".zip"):
        if name.endswith(ext):
            m = re.match(r"^(.+)-(\d[^-]*)$", name[: -len(ext)])
            return m.group(2) if m else None
    return None


def artifact_findings(dist: Path, rc: Any) -> list[dict[str, Any]]:
    """Per-artifact `forbid` / `require`, the expected set and `same_version` (0.9.0 B1, REQ-002). A distribution
    that matches no `[[release.artifact]]` table is audited by the global lists only."""
    findings: list[dict[str, Any]] = []
    arts = artifacts(dist)
    for art in arts:
        rules = [r for r in rc.artifact if glob_match(art.name, r.match)]
        if not rules:
            continue
        names = [n for n, _ in members(art)]
        for r in rules:
            for n in names:
                if any(glob_match(n, g) for g in r.forbid):
                    findings.append({"artifact": art.name, "member": n, "code": "forbidden_member"})
            for g in r.require:
                if not any(glob_match(n, g) for n in names):
                    findings.append({"artifact": art.name, "member": g, "code": "missing_member"})
    for g in rc.checks.expect:
        if not any(glob_match(a.name, g) for a in arts):
            findings.append({"artifact": "(dist)", "member": g, "code": "missing_artifact"})
    if rc.checks.same_version and arts:
        versions = {a.name: artifact_version(a.name) for a in arts}
        counts: dict[str | None, int] = {}
        for v in versions.values():
            counts[v] = counts.get(v, 0) + 1
        common = max(sorted(counts, key=str), key=lambda v: counts[v])  # the most frequent; ties by order
        for name, v in versions.items():
            if v != common or v is None:
                findings.append({"artifact": name, "member": f"(version {v or 'unreadable'}; expected {common})",
                                 "code": "version_mismatch"})
    return findings


def _unique_member(dist: Path, artifact: str, member: str) -> bool:
    return sum(1 for n, _ in members(dist / artifact) if n == member) == 1


def _waive_verified(az: Any, root: Path, cfg: Any, tag: str | None) -> bool:
    if not tag or getattr(cfg, "policy", None) is None:
        return False
    try:
        az.verify(root, cfg, tag, action="waive", consumed=set(), require_pinned=True)
        return True
    except az.AuthError:
        return False


def _content_findings(dist: Path, artifact: str, member: str, lists: list[Any], priv: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(term and local-path findings of one member, by name and content; what could not be scanned). R19."""
    from . import privacy as pv

    terms = [t for s in lists if not isinstance(s, str) and s.state == "ok" for t in s.terms]
    found = [{"artifact": artifact, "member": member, "code": "private_term_in_name" if not t.public else "policy_term_in_name",
              "term": t.label} for t in terms if t.regex.search(member)]
    for name, data in members(dist / artifact):
        if name != member:
            continue
        if data is None or b"\x00" in data[:8192]:
            return found, [{"artifact": artifact, "member": member, "reason": "too large" if data is None else "binary"}]
        hits, _ = pv.scan_text(data.decode("utf-8", errors="replace"), terms, bool(priv is None or priv.local_paths),
                               rel=member, sha=hashlib.sha256(data).hexdigest())
        return found + [{"artifact": artifact, "member": member, "line": h["line"],
                         "code": "local_path" if h["kind"] == "local_path" else ("policy_term" if h["term"].public else "private_term"),
                         **({"term": h["term"].label} if h["kind"] == "term" else {})} for h in hits], []
    return found, [{"artifact": artifact, "member": member, "reason": "not found"}]


def audit_for(root: Path, cfg: Any, dist: Path, read=None) -> dict[str, Any]:
    """The audit as configured: R-42 and `steward release audit` call this one function (SR-007 parity)."""
    from . import privacy as pv

    rc = cfg.release
    priv = getattr(cfg, "privacy", None)
    lists = pv.load(root, cfg, read=read)
    out = audit(dist, DEFAULT_EXCLUDE + (rc.exclude if rc else []), lists, bool(priv is None or priv.local_paths),
                list(priv.allow) if priv else [])
    if rc is not None:
        out["findings"] += artifact_findings(dist, rc)
        out["declared"] = []
        if rc.shipped_secret:  # REQ-006: a decided, declared credential is reported, not refused
            from .containers import SECRET_NAMES
            from .integrity import decision_heading
            from . import privacy as pv

            import fnmatch

            from . import authorize as az

            exclude = DEFAULT_EXCLUDE + list(rc.exclude)
            keep = []
            for f in out["findings"]:
                decl = next((s for s in rc.shipped_secret if glob_match(f["member"], s.path)), None)
                base = f["member"].rsplit("/", 1)[-1]
                matching = [e for e in exclude if glob_match(f["member"], e)]
                # R19: waivable only when every exclusion that matches is a secret-file rule (never development/**,
                # caches or a project's own exclusions), the member name is unique in its artifact, and Article II.3
                # holds: a signed `waive` authorization verified against the pinned trust root, plus the decision
                only_secret = bool(matching) and all(any(fnmatch.fnmatchcase(e.rsplit("/", 1)[-1], s) or e.rsplit("/", 1)[-1] in
                                                         ("*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12", ".env", "*.env")
                                                         for s in SECRET_NAMES) for e in matching)
                secret_like = any(fnmatch.fnmatchcase(base, s) for s in SECRET_NAMES)
                ok = decl is not None and f["code"] == "excluded" and secret_like and only_secret \
                    and _unique_member(dist, f["artifact"], f["member"]) and decision_heading(root, cfg, decl.decision) \
                    and _waive_verified(az, root, cfg, decl.authorization)
                if ok:
                    out["declared"].append({**f, "code": "shipped_secret", "reason": decl.reason, "decision": decl.decision})
                    found, unscanned = _content_findings(dist, f["artifact"], f["member"], lists, priv)
                    keep += found  # still scanned, by name and content
                    out["unscanned"] = out.get("unscanned", []) + unscanned
                else:
                    keep.append(f)
            out["findings"] = keep
    return out


def cff_problems(path: Path) -> list[str]:
    """A structural check without a YAML dependency: required top-level keys, and at least one author entry."""
    if not path.is_file():
        return ["CITATION.cff is missing"]
    text = path.read_text(encoding="utf-8", errors="replace")
    keys = {m.group(1) for m in re.finditer(r"^([A-Za-z][\w-]*):", text, re.M)}
    problems = [f"missing key {k}" for k in CFF_REQUIRED if k not in keys]
    if "authors" in keys and not re.search(r"^authors:\s*\n\s+-\s", text, re.M):
        problems.append("authors has no entries")
    return problems


def _in_repo(root: Path, rel: str) -> bool:
    """U15 (0.15.0): a repository file reached without any link: its real path is its own path."""
    p = root / rel
    return p.is_file() and not Path(rel).is_absolute() and os.path.realpath(p) == os.path.join(os.path.realpath(root), os.path.normpath(rel))


def _in_dist(dist: Path, lock: str) -> bool:
    from .fsutil import escapes_root

    p = dist / lock
    # U15 (0.17.0): no link anywhere below the folder: the real path is the folder's real path plus the lock's own
    exact = os.path.realpath(p) == os.path.join(os.path.realpath(dist), os.path.normpath(lock))
    return not Path(lock).is_absolute() and not escapes_root(lock) and p.is_file() and not p.is_symlink() and exact


def manifest(root: Path, dist: Path, version: str | None, locks: list[str], git: Any, claims_status: str | None,
             claims_file: str | None = None, identities: dict[str, str | None] | None = None,
             bundle_dir: str | None = None) -> dict[str, Any]:
    try:  # FB-10: a folder outside the repository is named without its local path
        dist_label = dist.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        dist_label = "(outside the repository)"
    return {
        "schema": "steward.release_manifest/0.1",
        "dist": dist_label,
        "identities": identities or {},  # SR-003: external identities (image digest, DOI); recorded, never verified
        "version": version,
        "git": git,
        "artifacts": {a.name: {"sha256": sha(a), "size": a.stat().st_size} for a in artifacts(dist)},
        "locks": {l: (sha(root / l) if _in_repo(root, l) else sha(dist / l) if _in_dist(dist, l) else None)
                  for l in sorted(locks)},
        # REQ-010: a relative lock not in the repository but beside the artifacts is read from the folder
        "locks_in_dist": sorted(l for l in locks if not (root / l).is_file() and _in_dist(dist, l)),
        "citation_sha256": sha(root / "CITATION.cff") if (root / "CITATION.cff").is_file() else None,
        "claims": claims_status,
        "claims_sha256": sha(root / claims_file) if claims_file and (root / claims_file).is_file() else None,
        "bundles": bundles(root / bundle_dir) if bundle_dir else {},
    }


# ---------------------------------------------------------------- bundles (0.9.0 B8, REQ-015)
BUNDLE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    pass


def bundle_members(root: Path, paths: list[str]) -> list[str]:
    """Every regular file under the given repository-relative paths, sorted; links are refused, never followed."""
    from .fsutil import escapes_root, inside, iter_repo_files

    out: set[str] = set()
    for rel in paths:
        rel = rel.rstrip("/")
        if escapes_root(rel) or not inside(root, rel):
            raise BundleError(f"{rel} is outside the repository")
        p = root / rel
        if p.is_symlink():
            raise BundleError(f"{rel} is a symbolic link")
        if p.is_file():
            out.add(Path(rel).as_posix())
        elif p.is_dir():
            out |= {f"{Path(rel).as_posix()}/{f}" for f in iter_repo_files(p)}
        else:
            raise BundleError(f"{rel} does not exist")
    return sorted(out)


def write_in_dir(dfd: int, name: str, data: bytes) -> None:
    """`name` in the held directory `dfd`, replaced atomically; a temporary file is created exclusively and without
    following links, and the rename replaces a link at `name` instead of writing through it (R4)."""
    import secrets

    from .fsutil import open_at, write_all

    tmp = f".{name}.{secrets.token_hex(6)}.tmp"
    fd = open_at(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dfd)
    try:
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise


def write_bundle(root: Path, members: list[str], dest: Path, dfd: int | None = None) -> str:
    """A zip whose bytes depend only on the member names, contents and executable bits: sorted entries, a fixed
    timestamp, modes 0644 or 0755, a fixed creator system and compression level. Returns its sha256. With `dfd`, the
    zip is written in that held directory descriptor and renamed there (K2, review R4)."""
    import secrets
    import stat as st

    own = dfd is None
    if own:
        dfd = os.open(dest.parent, os.O_RDONLY | os.O_DIRECTORY)
    tmp = f".{dest.name}.{secrets.token_hex(6)}.tmp"
    try:
        from .fsutil import open_at

        fd = open_at(tmp, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dfd)
        try:
            h = hashlib.sha256()
            with os.fdopen(fd, "w+b") as f:
                with zipfile.ZipFile(f, "w") as z:
                    for rel in members:
                        path = root / rel
                        info = zipfile.ZipInfo(rel, date_time=FIXED_TIME)
                        info.create_system = 3  # Unix, on every platform
                        executable = bool(os.stat(path).st_mode & st.S_IXUSR)
                        info.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
                        info.compress_type = zipfile.ZIP_DEFLATED
                        z.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                f.flush()
                os.fsync(f.fileno())
                f.seek(0)
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            os.replace(tmp, dest.name, src_dir_fd=dfd, dst_dir_fd=dfd)
            return h.hexdigest()
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
            raise
    finally:
        if own:
            os.close(dfd)


def test_report(cmd: str, root: Path) -> dict[str, Any]:
    """Run the test command once (no shell) and record what ran and how it ended; its output is not kept."""
    import platform
    import shlex
    import subprocess

    argv = shlex.split(cmd)
    proc = subprocess.run(argv, cwd=root, capture_output=True, timeout=3600)
    return {"command": cmd, "exit_code": proc.returncode, "python": platform.python_version()}


def bundles(out_dir: Path) -> dict[str, dict[str, Any]]:
    """name -> {sha256, size, members} for every bundle in the folder (read by the manifest and R-42)."""
    found: dict[str, dict[str, Any]] = {}
    if not out_dir.is_dir():
        return found
    for z in sorted(out_dir.glob("*.zip")):
        rec_path = z.with_name(z.name[:-4] + ".bundle.json")
        rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {}
        zsha = sha(z)
        bound = rec_path.is_file() and rec.get("sha256") == zsha
        found[z.name[:-4]] = {"sha256": zsha, "size": z.stat().st_size, "members": len(rec.get("members", [])),
                              # Q29, R18: the record (with any test evidence) counts only when bound to this zip
                              "record_sha256": sha(rec_path) if bound else None, "record_bound": bound,
                              **({"test_report": rec["test_report"]} if bound and rec.get("test_report") else {})}
    return found


def write_manifest(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
