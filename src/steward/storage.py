"""Storage (v0.8, RELEASE_v0.8_SPEC): large artifacts kept outside git, recorded by hash in git (R-50), and an
advisory resource audit. DVC pointer files and git-annex keys are read when present; neither tool is required.

A recorded hash shows which bytes a result used. It does not keep those bytes available: retrieval is the note's job.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .fsutil import escapes_root, git_run, inside
from .models import Hex64, Strict, Text

ANNEX_KEY = re.compile(r"SHA256E?-s(\d+)--([0-9a-f]{64})")
MB = 1024 * 1024


class Artifact(Strict):
    path: Text
    sha256: Hex64
    size: int = Field(ge=0)
    retrieval: Text | None = None  # e.g. "dvc pull PATH", a URL, "regenerate: python train.py"
    tool: Literal["dvc", "datalad", "manual"] = "manual"


class ArtifactsFile(Strict):
    schema_: Literal["steward.artifacts/0.1"] = Field(alias="schema")
    artifacts: list[Artifact] = Field(default_factory=list)


def sha_stream(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_stream(p: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def annex_key(root: Path, rel: str) -> tuple[int, str] | None:
    """(size, sha256) from a git-annex symlink's key, without reading the content."""
    p = root / rel
    if not p.is_symlink():
        return None
    m = ANNEX_KEY.search(Path(os.readlink(p)).name)
    return (int(m.group(1)), m.group(2)) if m else None


def dvc_pointer(root: Path, rel: str) -> tuple[str, bytes] | None:
    """(pointer path, bytes) of `PATH.dvc` if it is a file inside the repository; None otherwise."""
    prel = rel + ".dvc"
    if not (root / prel).is_file() and not (root / prel).is_symlink():
        return None
    return (prel, (root / prel).read_bytes()) if located(root, prel) and (root / prel).is_file() else (prel, b"")


def dvc_md5(data: bytes, rel: str) -> str | None:
    """The MD5 a DVC pointer's `outs:` list records for PATH (red-team K4): only entries under `outs:`, with YAML
    comments and quotes removed. Reads the simple pointer form DVC writes; no DVC API."""
    entries: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    section = None
    for raw in data.decode("utf-8", errors="replace").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "-")):
            section = line.split(":", 1)[0].strip()
            cur = None
            continue
        if section != "outs":
            continue
        s = line.strip()
        if s.startswith("- "):
            cur = {}
            entries.append(cur)
            s = s[2:]
        if cur is not None and ":" in s:
            k, _, v = s.partition(":")
            cur[k.strip()] = v.strip().strip("'\"")
    name = Path(rel).name
    hit = next((e for e in entries if e.get("path") in (name, rel) and "md5" in e), None)
    return hit["md5"] if hit else None


def large_tracked(root: Path, limit_mb: float) -> list[tuple[str, int]] | None:
    """Git-tracked regular files larger than the limit; None when git cannot list them."""
    try:
        out = git_run(root, "ls-files", "-z")
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    big = []
    for rel in out.stdout.decode("utf-8", errors="replace").split("\0"):
        p = root / rel
        if rel and located(root, rel) and p.is_file() and not p.is_symlink():
            size = p.stat().st_size
            if size > limit_mb * MB:
                big.append((rel, size))
    return big


def located(root: Path, rel: str) -> bool:
    return not escapes_root(rel) and inside(root, rel)


def observe(p: Path) -> dict[str, Any] | None:
    """SHA-256, MD5 and size from one read of the file (red-team K4); None if it changed while being read."""
    sha, md5, n = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    before = p.stat()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
            n += len(chunk)
    after = p.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or n != after.st_size:
        return None
    return {"sha256": sha.hexdigest(), "md5": md5.hexdigest(), "size": n}


def measure(root: Path, rel: str) -> dict[str, Any]:
    """The artifact's observable state: one observation of a present file, its annex key, its DVC pointer."""
    p = root / rel
    state: dict[str, Any] = {"annex": annex_key(root, rel), "dvc": dvc_pointer(root, rel)}
    if p.is_file():
        o = observe(p)
        state.update(present=True, unstable=o is None, **(o or {}))
    else:
        state["present"] = False
    return state


def evaluate(root: Path, reg: ArtifactsFile | None, cfg: Any, final: bool) -> dict[str, Any]:
    """Per-artifact states and problems (status name, code, details) for R-50 and `steward storage verify`."""
    problems: list[tuple[str, str, dict[str, Any]]] = []
    states = []
    registered = set()
    pointers: dict[str, str] = {}
    for a in (reg.artifacts if reg else []):
        registered.add(a.path)
        if not located(root, a.path):
            problems.append(("FAIL", "R-50.path_outside", {"path": a.path}))
            states.append({"path": a.path, "state": "outside"})
            continue
        st = measure(root, a.path)
        if st["dvc"] is not None:
            prel, pdata = st["dvc"]
            if not pdata and not located(root, prel):
                problems.append(("FAIL", "R-50.path_outside", {"path": prel, "message": "the DVC pointer resolves outside the repository"}))
                st["dvc"] = None
            else:
                pointers[prel] = hashlib.sha256(pdata).hexdigest()  # part of the verdict's inputs (K4)
        if st.get("unstable"):
            problems.append(("INCOMPLETE", "R-50.unstable", {"path": a.path, "message": "the file changed while it was read"}))
            states.append({"path": a.path, "state": "changing"})
            continue
        if not a.retrieval:
            problems.append(("INCOMPLETE", "R-50.no_retrieval", {"path": a.path, "message": "say how to get the file back"}))
        if st["annex"] and (st["annex"][1] != a.sha256 or st["annex"][0] != a.size):
            problems.append(("FAIL", "R-50.annex_mismatch", {"path": a.path, "message": "the annex key differs from the registry"}))
        if st["present"]:
            if st["sha256"] != a.sha256 or st["size"] != a.size:
                problems.append(("FAIL", "R-50.hash_mismatch", {"path": a.path}))
            want = dvc_md5(st["dvc"][1], a.path) if st["dvc"] else None
            if want is not None and want != st["md5"]:
                problems.append(("FAIL", "R-50.dvc_mismatch", {"path": a.path, "message": "the DVC pointer records another MD5"}))
            states.append({"path": a.path, "state": "present", "sha256": st["sha256"], "size": st["size"]})
        elif st["annex"] and st["annex"][1] == a.sha256:  # K8: absent content counts as absent when final
            problems.append(("INCOMPLETE" if final else "INFO", "R-50.annex_key_only", {"path": a.path,
                             "message": f"content not present; the annex key matches; retrieval: {a.retrieval or '(none recorded)'}"}))
            states.append({"path": a.path, "state": "absent", "annex_key": True})
        else:
            problems.append(("INCOMPLETE" if final else "INFO", "R-50.not_present",
                             {"path": a.path, "message": f"not present locally; retrieval: {a.retrieval or '(none recorded)'}"}))
            states.append({"path": a.path, "state": "absent"})
    big = large_tracked(root, cfg.large_mb)
    if big is None:
        problems.append(("INFO", "R-50.git_unavailable", {"message": "git could not list tracked files; large files not checked"}))
    else:
        for rel, size in big:
            if rel not in registered:
                problems.append(("INCOMPLETE", "R-50.large_tracked", {"path": rel, "value": size,
                                 "message": f"over {cfg.large_mb} MB in git: register it and move it out of git, or raise large_mb"}))
    return {"artifacts": states, "problems": problems, "pointers": pointers}


def dir_size(p: Path) -> int:
    """Total bytes of regular files under p; symbolic links are not followed."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
        for f in filenames:
            fp = Path(dirpath) / f
            if not fp.is_symlink():
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    return total


def untracked(root: Path) -> list[str]:
    """Files git does not track (ignored ones included); a plain walk outside .git when git is unavailable."""
    try:
        out = git_run(root, "ls-files", "--others", "-z", timeout=120)
        if out.returncode == 0:
            return [r for r in out.stdout.decode("utf-8", errors="replace").split("\0") if r]
    except (OSError, subprocess.SubprocessError):
        pass
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts]


def audit(root: Path, caps: dict[str, float], top: int = 10) -> dict[str, Any]:
    """Sizes of the configured directories against their caps, and the largest untracked files. Read-only: it never
    deletes or changes anything; cleaning up is the human's decision."""
    dirs = []
    for rel, cap in sorted(caps.items()):
        if not located(root, rel):
            dirs.append({"path": rel, "state": "outside", "cap_mb": cap})
            continue
        p = root / rel
        if not p.is_dir():
            dirs.append({"path": rel, "state": "absent", "cap_mb": cap, "size_mb": 0.0, "over": False})
            continue
        mb = dir_size(p) / MB
        dirs.append({"path": rel, "state": "present", "cap_mb": cap, "size_mb": round(mb, 3), "over": mb > cap})
    sizes = []
    for rel in untracked(root):
        fp = root / rel
        if fp.is_file() and not fp.is_symlink():
            sizes.append((fp.stat().st_size, rel))
    largest = [{"path": rel, "size_mb": round(size / MB, 3)} for size, rel in sorted(sizes, key=lambda x: (-x[0], x[1]))[:top]]
    return {"directories": dirs, "largest_untracked": largest}


def load(text: str) -> ArtifactsFile:
    return ArtifactsFile.model_validate(tomllib.loads(text))


def _q(v: str) -> str:
    """A TOML basic string (red-team K5): backslash, quote and every control character escaped."""
    out = []
    for ch in v:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def write_registry(path: Path, reg: ArtifactsFile) -> None:
    """Atomic replace: a failure leaves the previous registry intact. The text is re-read before it replaces it."""
    import tempfile

    text = dump(reg)
    load(text)  # never write a registry this module cannot read back
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".artifacts.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dump(reg: ArtifactsFile) -> str:
    out = ["# Large artifacts kept outside git, recorded by hash (schema steward.artifacts/0.1). Written by",
           "# `steward storage record`; checked by rule R-50.", 'schema = "steward.artifacts/0.1"']
    for a in sorted(reg.artifacts, key=lambda a: a.path):
        out += ["", "[[artifacts]]", f"path      = {_q(a.path)}", f"sha256    = {_q(a.sha256)}", f"size      = {a.size}"]
        if a.retrieval:
            out.append(f"retrieval = {_q(a.retrieval)}")
        out.append(f"tool      = {_q(a.tool)}")
    return "\n".join(out) + "\n"
