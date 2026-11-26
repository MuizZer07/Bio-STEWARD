"""Deterministic file helpers: hashing, canonical JSON, POSIX glob matching and repository walking."""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

CONFIG_NAME = "steward.toml"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Canonical, human-readable JSON: sorted keys, UTF-8, 2-space indent, trailing newline."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def compact_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a POSIX glob to a regex: ``**/`` any directories, ``**`` anything, ``*`` and ``?`` within one segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(rel_path: str, pattern: str) -> bool:
    return _glob_regex(pattern).match(rel_path) is not None


def escapes_root(pattern: str) -> bool:
    """True if a configured path or glob is absolute or climbs out of the repository root."""
    if pattern.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", pattern) or "\\" in pattern:
        return True
    return ".." in PurePosixPath(pattern).parts


def iter_repo_files(root: Path) -> Iterator[str]:
    """Every regular file under root as a sorted POSIX relative path. ``.git`` (a directory, or the file of a linked
    worktree or submodule) is never read; links are not followed."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in filenames:
            if name == ".git":  # a linked worktree's or submodule's .git file is git metadata (DEF-023)
                continue
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            found.append(p.relative_to(root).as_posix())
    yield from sorted(found)


def matching_files(root: Path, patterns: list[str]) -> list[str]:
    return [rel for rel in iter_repo_files(root) if any(glob_match(rel, pat) for pat in patterns)]


def find_root(start: Path) -> Path | None:
    """Nearest directory at or above ``start`` that contains steward.toml. Never inferred from git."""
    cur = start.resolve()
    for d in (cur, *cur.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    return None


def inside(root: Path, rel: str) -> bool:
    try:
        (root / rel).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- git, run safely (red-team B4, K1, K3)
# Settings a repository's own .git/config could use to run a program, write state or reach the network. Command-line
# configuration overrides the repository's, so these hold whatever .git/config says.
SAFE_GIT_CONFIG = (
    "core.fsmonitor=false", "core.untrackedCache=false", "core.hooksPath=/dev/null", "core.sshCommand=false",
    "core.pager=cat", "diff.external=", "credential.helper=", "protocol.allow=never", "fetch.recurseSubmodules=false",
    # protocol-specific settings take precedence over protocol.allow, so every transport is denied by name (L3)
    "protocol.file.allow=never", "protocol.git.allow=never", "protocol.ssh.allow=never", "protocol.http.allow=never",
    "protocol.https.allow=never", "protocol.ext.allow=never",
)


def git_env(user_config: bool = False) -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
                # an empty allow-list: no protocol and no custom helper, on any git version, whatever the config (L3, M3)
                "GIT_ALLOW_PROTOCOL": ""})
    if not user_config:
        env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env


def git_run(root: Path, *args: str, text: bool = False, timeout: float = 60, input: bytes | None = None,
            check: bool = False, user_config: bool = False, safe_config: bool = True):
    """Git on `root` and nothing else: no inherited GIT_* variables, no system or user configuration (except for
    signing), no optional index writes, no repository-selected programs, no network transport."""
    import subprocess

    cmd = ["git", "--no-optional-locks"]
    for c in (SAFE_GIT_CONFIG if safe_config else ()):  # off only for path queries that must see core.hooksPath
        cmd += ["-c", c]
    return subprocess.run([*cmd, *args], cwd=root, capture_output=True, text=text, timeout=timeout, input=input,
                          check=check, env=git_env(user_config))


# ---------------------------------------------------------------- directory-relative opens (0.9.0, A6)
class LinkRefused(OSError):
    """A path component is a symbolic link or not a directory, so a directory-relative walk refuses it."""


def open_dir_beneath(base: Path, parts: tuple[str, ...] | list[str], create: bool = False) -> int:
    """A descriptor of `base/parts…`, walked one component at a time with O_NOFOLLOW relative to its parent's
    descriptor. A component below `base` replaced by a link at any time cannot redirect the walk (0.9.0, A6). `create` makes
    missing components (mode 0755). The caller closes the descriptor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(base, flags & ~os.O_NOFOLLOW)  # the base is trusted as given (it may be reached by a link)
    except OSError as e:
        raise LinkRefused(e.errno, f"{base} is not a directory") from None
    for part in parts:
        if part in ("", ".", "..") or "/" in part:
            os.close(fd)
            raise LinkRefused(0, f"unsafe path component {part!r}")
        try:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(part, flags, dir_fd=fd)
        except OSError as e:
            os.close(fd)
            raise LinkRefused(e.errno, f"{part} is a link or not a directory; refusing to walk through it") from None
        os.close(fd)
        fd = nxt
    return fd


def open_at(name: str, flags: int, mode: int, dir_fd: int) -> int:
    """`os.open(name, flags, mode, dir_fd=dir_fd)`. Concurrent `openat` with O_CREAT on one name can fail with a
    spurious ENOENT on macOS (seen in 0.9.0 testing, never with the path form); the open is retried, a bounded
    number of times, only in that case."""
    for _ in range(100):
        try:
            return os.open(name, flags, mode, dir_fd=dir_fd)
        except FileNotFoundError:
            if not flags & os.O_CREAT:
                raise
    return os.open(name, flags, mode, dir_fd=dir_fd)


def write_all(fd: int, data: bytes) -> None:
    """Every byte, or an OSError: a short write is never taken as a complete record (review R2)."""
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError("short write")
        view = view[n:]


def safe_write(root: Path, rel: str, data: bytes, mode: int = 0o644, exclusive: bool = False) -> Path:
    """Write `root/rel` without following a link at any component below `root` and never outside it: parents are
    walked (and made) by descriptor, the bytes go to a fresh temporary file in the final directory, which then
    replaces the entry (or, `exclusive`, is created only when absent). Review of 0.9.0, Q6."""
    import secrets

    if escapes_root(rel):
        raise LinkRefused(0, f"{rel} is outside the repository")
    parts = PurePosixPath(rel).parts
    dfd = open_dir_beneath(root, parts[:-1], create=True)
    name = parts[-1]
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        target = name if exclusive else f".{name}.{secrets.token_hex(6)}.tmp"
        fd = open_at(target, flags, mode, dfd)
        try:
            try:
                write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            if not exclusive:
                os.replace(target, name, src_dir_fd=dfd, dst_dir_fd=dfd)  # replaces the entry; a link is not followed
        except BaseException:
            try:  # R2: a failed write or replace leaves no temporary file and never a partial record
                os.unlink(target, dir_fd=dfd)
            except OSError:
                pass
            raise
    finally:
        os.close(dfd)
    return root / rel


def entry_identity(root: Path, rel: str) -> tuple[int, int] | None:
    """(device, inode) of `root/rel`, reached without links, or None."""
    parts = PurePosixPath(rel).parts
    try:
        dfd = open_dir_beneath(root, parts[:-1])
    except LinkRefused:
        return None
    try:
        st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
        return st.st_dev, st.st_ino
    except OSError:
        return None
    finally:
        os.close(dfd)


def remove_if_same(root: Path, rel: str, ident: tuple[int, int] | None) -> bool:
    """Unlink `root/rel` only if it is still the entry with this identity, reached without links (Q9)."""
    if ident is None:
        return False
    parts = PurePosixPath(rel).parts
    try:
        dfd = open_dir_beneath(root, parts[:-1])
    except LinkRefused:
        return False
    try:
        st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
        if (st.st_dev, st.st_ino) != ident:
            return False
        os.unlink(parts[-1], dir_fd=dfd)
        return True
    except OSError:
        return False
    finally:
        os.close(dfd)


# ---------------------------------------------------------------- ownership locks (0.10.0 K1, review R3)
def owner_lock(root: Path, name: str) -> int | None:
    """Hold `.steward/owners/<name>.lock` for this process's lifetime (an exclusive flock on a file written with
    this pid and start time). `steward session close --end` stops a process only while it holds its lock. An existing
    file is taken over only when it is a regular, singly linked file of this user that nobody holds (S3). Returns the
    descriptor (keep it open), or None when the lock cannot be made."""
    import fcntl
    import json
    import stat as st

    import psutil

    try:
        dfd = open_dir_beneath(root, (".steward", "owners"), create=True)
    except LinkRefused:
        return None
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        try:
            fd = open_at(f"{name}.lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dfd)
        except FileExistsError:
            fd = os.open(f"{name}.lock", flags, dir_fd=dfd)
            s_ = os.fstat(fd)
            if not st.S_ISREG(s_.st_mode) or s_.st_nlink != 1 or s_.st_uid != os.getuid():
                os.close(fd)
                return None
    except OSError:
        return None
    finally:
        os.close(dfd)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        write_all(fd, json.dumps({"pid": os.getpid(), "created": psutil.Process().create_time()}).encode())
        os.fsync(fd)
        return fd
    except OSError:
        os.close(fd)
        return None


def unlink_if_same(dfd: int, name: str, ident: tuple[int, int]) -> bool:
    """Remove `name` in the held directory only if it is the file `ident` names. It is moved to a private name first
    (atomic), checked there, and put back without replacing anything when it is not (R4, U5: no check-then-unlink
    window on the name). True when removed."""
    import secrets

    aside = f".{name}.{secrets.token_hex(8)}.aside"
    try:
        os.rename(name, aside, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError:
        return False
    try:
        st = os.stat(aside, dir_fd=dfd, follow_symlinks=False)
        if (st.st_dev, st.st_ino) == tuple(ident):
            os.unlink(aside, dir_fd=dfd)
            return True
        os.link(aside, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
        os.unlink(aside, dir_fd=dfd)
    except OSError:
        pass
    return False


def release_owner_lock(root: Path, name: str, fd: int | None) -> None:
    """Remove the lock only if the name still refers to the file this descriptor holds (S3, R4)."""
    if fd is None:
        return
    try:
        held = os.fstat(fd)
        dfd = open_dir_beneath(root, (".steward", "owners"))
        try:
            unlink_if_same(dfd, f"{name}.lock", (held.st_dev, held.st_ino))
        finally:
            os.close(dfd)
    except (LinkRefused, OSError):
        pass
    os.close(fd)


def held_owner_locks(root: Path) -> list[tuple[str, dict]]:
    """(name, recorded pid and start time) for each lock some process still holds; stale locks are removed."""
    import fcntl
    import json

    try:
        dfd = open_dir_beneath(root, (".steward", "owners"))
    except LinkRefused:
        return []
    out = []
    try:
        for entry in sorted(os.listdir(dfd)):
            if not entry.endswith(".lock"):
                continue
            try:
                fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError:
                continue
            try:
                import errno
                import stat as st

                s_ = os.fstat(fd)
                if not st.S_ISREG(s_.st_mode) or s_.st_nlink != 1:
                    continue  # S3: not a lock file steward made; never read as held, never deleted
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as e:
                    if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                        continue  # S3: only contention means "held"
                    os.lseek(fd, 0, os.SEEK_SET)
                    try:
                        rec = json.loads(os.read(fd, 4096).decode() or "{}")
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(rec, dict) and isinstance(rec.get("pid"), int):
                        out.append((entry[:-5], {**rec, "_lock": (s_.st_dev, s_.st_ino)}))
                else:  # nobody holds it: stale. Removed while we hold it, and only if the name is still this file
                    try:
                        cur = os.stat(entry, dir_fd=dfd, follow_symlinks=False)
                        if (cur.st_dev, cur.st_ino) == (s_.st_dev, s_.st_ino):
                            os.unlink(entry, dir_fd=dfd)
                    except OSError:
                        pass
            finally:
                os.close(fd)
    finally:
        os.close(dfd)
    return out
