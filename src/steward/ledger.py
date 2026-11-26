"""Append-only, hash-chained JSON Lines ledgers (RELEASE_v0.4_SPEC §1; DESIGN_v0.4 §4).

Tamper evidence, not tamper proof: edits, deletions in the middle and sequence gaps are detected; a consistent
rewrite or a truncated tail is detected only against an anchor (a signed tag holding the head hash).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fsutil import open_at

GENESIS = "0" * 64


class LedgerError(Exception):
    pass


def _canon(entry: dict[str, Any]) -> bytes:
    return json.dumps({k: v for k, v in entry.items() if k != "hash"}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(entry)).hexdigest()


@dataclass
class Verification:
    entries: list[dict[str, Any]] = field(default_factory=list)
    torn_tail: bytes | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)  # chain / sequence / json problems

    @property
    def head(self) -> dict[str, Any] | None:
        return self.entries[-1] if self.entries else None


def verify(path: Path) -> Verification:
    """Read and verify a ledger. A last line without newline, or unparsable last line, is a torn tail."""
    return verify_bytes(path.read_bytes() if path.is_file() else b"")


def verify_bytes(data: bytes) -> Verification:
    v = Verification()
    if not data:
        return v
    lines = data.split(b"\n")
    tail = lines.pop()  # after the final \n this is b"" for a well-formed file
    if tail:
        v.torn_tail = tail
    prev = GENESIS
    for i, raw in enumerate(lines):
        try:
            e = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            if i == len(lines) - 1 and v.torn_tail is None:
                v.torn_tail = raw + b"\n"
                break
            v.errors.append({"code": "ledger.json", "line": i + 1})
            break
        if not isinstance(e, dict) or "seq" not in e or "hash" not in e or "prev" not in e:
            v.errors.append({"code": "ledger.not_a_ledger", "line": i + 1})
            break
        if e["seq"] != len(v.entries):
            v.errors.append({"code": "ledger.sequence", "line": i + 1, "value": e["seq"], "message": f"expected {len(v.entries)}"})
        if e["prev"] != prev:
            v.errors.append({"code": "ledger.chain_broken", "line": i + 1, "value": e["seq"]})
        if entry_hash(e) != e["hash"]:
            v.errors.append({"code": "ledger.hash_mismatch", "line": i + 1, "value": e["seq"]})
        prev = e["hash"]
        v.entries.append(e)
    return v


_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


def _read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


class Ledger:
    """Every open is relative to the parent directory's descriptor, never follows a link, never blocks (a FIFO is
    refused, not waited on), and is checked by `fstat` to be a regular, singly linked file before anything is read,
    locked or written (0.8.1 review N4, O5; 0.9.0 A2, A3). With `base`, the parent directory itself is reached from
    `base` one component at a time without following links (0.9.0 A6)."""

    def __init__(self, path: Path, name: str, repo_id: str = "unknown", base: Path | None = None):
        self.path, self.name, self.repo_id, self.base = path, name, repo_id, base

    def _parent(self) -> int:
        from .fsutil import LinkRefused, open_dir_beneath

        try:
            if self.base is not None:
                rel = self.path.parent.relative_to(self.base)
                return open_dir_beneath(self.base, rel.parts)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC)
        except (LinkRefused, ValueError) as e:
            raise LedgerError(f"{self.path.parent}: {e}; refusing to open the ledger") from None

    def _open(self, dfd: int, name: str, flags: int) -> int:
        try:
            fd = open_at(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC, 0o644, dfd)
        except FileNotFoundError:
            raise
        except OSError as e:
            raise LedgerError(f"{self.path.parent / name} is not a regular file reached without links "
                              f"({e.strerror}); refusing") from None
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:  # no special file, no shared inode (review O5, P3)
            os.close(fd)
            raise LedgerError(f"{self.path.parent / name} is not a regular, singly linked file; refusing")
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
        return fd

    def _locked(self, work):
        """Run work(dir_fd) under the exclusive lock (red-team A2: no check-then-act gap)."""
        dfd = self._parent()
        try:
            lock = self._open(dfd, self.path.name + ".lock", os.O_RDWR | os.O_CREAT | os.O_APPEND)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    return work(dfd)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            finally:
                os.close(lock)
        finally:
            os.close(dfd)

    def append(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.transaction(lambda entries: (kind, body))

    def transaction(self, decide) -> dict[str, Any]:
        """Read, decide and append under one exclusive lock, through one checked descriptor.
        `decide(entries)` returns (kind, body) to append, or raises to append nothing."""
        def work(dfd: int) -> dict[str, Any]:
            fd = self._open(dfd, self.path.name, os.O_RDWR | os.O_APPEND | os.O_CREAT)
            try:
                v = verify_bytes(_read_all(fd))
                if v.errors or v.torn_tail:
                    raise LedgerError(f"{self.path}: ledger tail is not valid; run `steward ledger recover {self.path}`")
                kind, body = decide(v.entries)
                return self._add(fd, v.entries, kind, body)
            finally:
                os.close(fd)
        return self._locked(work)

    def _add(self, fd: int, entries: list[dict[str, Any]], kind: str, body: dict[str, Any]) -> dict[str, Any]:
        head = entries[-1] if entries else self._write(fd, {"seq": 0, "prev": GENESIS, "kind": "genesis",
                                                            "ledger": self.name, "repo_id": self.repo_id, "time": _now()})
        return self._write(fd, {"seq": head["seq"] + 1, "prev": head["hash"], "kind": kind, "time": _now(), **body})

    @staticmethod
    def _write(fd: int, entry: dict[str, Any]) -> dict[str, Any]:
        from .fsutil import write_all

        entry["hash"] = entry_hash(entry)
        write_all(fd, json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        os.fsync(fd)
        return entry

    @staticmethod
    def _quarantine(qfd: int, stem: str, tail: bytes) -> bool:
        """Save the tail under the quarantine folder: an existing copy counts only when its bytes are exactly the tail
        (a regular file, read back); otherwise a new name is used (review of 0.9.0, Q8)."""
        for n in range(100):
            name = f"{stem}.partial" if n == 0 else f"{stem}.{n}.partial"
            try:
                pfd = open_at(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC, 0o644, qfd)
            except FileExistsError:
                try:
                    rfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC, dir_fd=qfd)
                except OSError:
                    continue
                try:
                    if stat.S_ISREG(os.fstat(rfd).st_mode) and _read_all(rfd) == tail:
                        return True
                finally:
                    os.close(rfd)
                continue
            try:
                from .fsutil import write_all

                write_all(pfd, tail)
                os.fsync(pfd)
            finally:
                os.close(pfd)
            # R2: the copy counts only when it reads back as the whole tail
            rfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | _CLOEXEC, dir_fd=qfd)
            try:
                return _read_all(rfd) == tail
            finally:
                os.close(rfd)
        return False

    def recover(self) -> dict[str, Any] | None:
        """Quarantine a torn tail (never delete) and record the recovery. Returns the recovery entry, or None.
        Every check of an append runs before the first write; the truncation goes through the checked descriptor,
        and the quarantine file is created exclusively in a directory reached without links (0.9.0 A2)."""
        def work(dfd: int) -> dict[str, Any] | None:
            try:
                fd = self._open(dfd, self.path.name, os.O_RDWR)
            except FileNotFoundError:
                return None
            try:
                data = _read_all(fd)
                v = verify_bytes(data)
                if v.errors:
                    raise LedgerError("the chain is broken before the tail; restore from version control (no automatic repair)")
                if not v.torn_tail:
                    return None
                qname = self.path.name + ".quarantine"
                try:
                    os.mkdir(qname, 0o755, dir_fd=dfd)
                except FileExistsError:
                    pass
                try:
                    qfd = os.open(qname, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC, dir_fd=dfd)
                except OSError as e:
                    raise LedgerError(f"{self.path.parent / qname} is a link or not a directory ({e.strerror}); refusing") from None
                digest = hashlib.sha256(v.torn_tail).hexdigest()
                try:
                    if not self._quarantine(qfd, f"{len(v.entries)}-{digest[:16]}", v.torn_tail):
                        raise LedgerError("the torn tail could not be saved to quarantine; nothing was truncated")
                finally:
                    os.close(qfd)
                os.ftruncate(fd, len(data) - len(v.torn_tail))
                os.fsync(fd)
                os.lseek(fd, 0, os.SEEK_END)  # not opened for append: write after the kept entries
                return self._add(fd, v.entries, "recovery", {"quarantined_sha256": digest,
                                                             "quarantined_bytes": len(v.torn_tail)})
            finally:
                os.close(fd)
        return self._locked(work)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
