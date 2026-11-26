"""`steward run`: execute a command under resource limits and record it (RELEASE_v0.4_SPEC §2).

Enforced only within its boundary: the command's process group and its process tree. Processes that leave the tree
(double fork with setsid), work in containers started through a daemon, and GPU memory are not supervised.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import platform
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from .ledger import Ledger

EXIT_LIMIT = 124
EXIT_NO_SLOT = 75
LOCK_FILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt", "requirements.lock",
              "environment.yml", "environment.yaml", "conda-lock.yml", "renv.lock", "pixi.lock")


@dataclass
class Limits:
    wall_s: float | None = None
    mem_mb: float | None = None
    hang_s: float | None = None
    disk_free_mb: float | None = None
    hang_cpu_s: float | None = None  # REQ-009: no CPU-time progress of the tree for this long

    def tightened(self, other: "Limits") -> "Limits":
        """Command-line limits may only tighten configured defaults."""
        def pick(a: float | None, b: float | None) -> float | None:
            return b if a is None else (a if b is None else min(a, b))
        return Limits(pick(self.wall_s, other.wall_s), pick(self.mem_mb, other.mem_mb),
                      pick(self.hang_s, other.hang_s), pick(self.disk_free_mb, other.disk_free_mb),
                      pick(self.hang_cpu_s, other.hang_cpu_s))


@dataclass
class Outcome:
    status: str  # finished | failed | killed | interrupted
    exit_code: int | None
    duration_s: float
    peak_rss_mb: float
    breached: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def sha_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state(root: Path) -> dict[str, Any]:
    def run(*a: str) -> str | None:
        try:
            out = __import__("steward.fsutil", fromlist=["git_run"]).git_run(root, *a, timeout=30)
            return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    head = run("rev-parse", "HEAD")
    if head is None:
        return {"head": "unknown", "dirty": "unknown", "diff_sha256": "unknown"}
    diff = run("diff", "HEAD") or ""
    return {"head": head.strip(), "dirty": bool((run("status", "--porcelain") or "").strip()),
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff else None}


def tilde(arg: str) -> str:
    """The argument with the user's home directory written as `~`: run ledgers are committed, so they must not carry a
    user name (SR-005). The command itself runs unchanged."""
    home = str(Path.home())
    if not home or home == "/":
        return arg
    if arg == home:
        return "~"
    return arg.replace(home + os.sep, "~" + os.sep)


def environment(root: Path) -> dict[str, Any]:
    return {
        "python": platform.python_version(), "platform": sys.platform, "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "threads": {k: v for k, v in sorted(os.environ.items()) if k.endswith("_NUM_THREADS")},
        "lock_files": {f: sha_file(root / f) for f in LOCK_FILES if (root / f).is_file()},
    }


class Slot:
    """One of N permits for a named slot, held with flock for the life of the run."""

    def __init__(self, root: Path, name: str, permits: int, configured: str | None = None):
        """The permit directory: STEWARD_SLOTS_DIR, then `[run] slots_dir`, then `<repo>/.steward/slots` (SR-001).
        `scope` and `spec` describe it for the run record without a local path."""
        env = os.environ.get("STEWARD_SLOTS_DIR")
        if env:
            self.dir, self.scope, self.spec = Path(env).expanduser(), "shared", "$STEWARD_SLOTS_DIR"
        elif configured:
            self.dir, self.scope, self.spec = Path(configured).expanduser(), "shared", tilde(configured)  # review N11
        else:
            self.dir, self.scope, self.spec = root / ".steward" / "slots", "repository", ".steward/slots"
        self.name, self.permits, self.fh = name, permits, None

    def acquire(self, wait: bool, timeout: float | None = None) -> bool:
        """Take a permit. `wait` waits indefinitely; `timeout` waits at most that many seconds (SR-001)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            for i in range(self.permits):
                fh = open(self.dir / f"{self.name}.{i}.lock", "a+")
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.fh = fh
                    return True
                except BlockingIOError:
                    fh.close()
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                time.sleep(min(0.2, left))  # review N11: the bound is honoured, not rounded up to the poll interval
                continue
            if not wait:
                return False
            time.sleep(0.2)

    def release(self) -> None:
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def _tree(proc: psutil.Process) -> list[psutil.Process]:
    try:
        return [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return []


def _rss_mb(procs: list[psutil.Process]) -> float:
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total / (1 << 20)


def _terminate(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """TERM, then KILL, to the job's group and its observed tree. The group is signalled by the leader's pid only
    while the leader is not yet reaped (this runs before `proc.wait()`), so the group id cannot have been reused (R20).
    A failure to list the tree never stops the group from being signalled (R20, S1)."""
    try:
        tree = _tree(psutil.Process(proc.pid))
    except (psutil.Error, OSError):
        tree = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        for p in tree:
            try:
                p.send_signal(sig)
            except psutil.Error:
                pass
        if sig == signal.SIGTERM:
            if not tree:  # U13 (0.12.0): the tree is not visible: give the leader its grace, then escalate anyway
                if _leader_exits(proc.pid, grace):
                    return
                continue
            _, alive = psutil.wait_procs(tree, timeout=grace)
            if not alive:
                return
            tree = alive


def _leader_exits(pid: int, grace: float) -> bool:
    """True when the group leader has exited within `grace` seconds. It is never reaped here (WNOWAIT), so its group id
    stays reserved for the KILL that may follow (U13)."""
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if hasattr(os, "waitid"):
            try:
                if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                    return True
            except (ChildProcessError, OSError):
                return False
        else:  # macOS has no waitid: an unreaped, exited leader is a zombie
            try:
                if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                    return True
            except psutil.NoSuchProcess:
                return True
            except psutil.Error:
                pass
        time.sleep(0.05)
    return False


def _cpu_s(procs: list[psutil.Process]) -> float:
    total = 0.0
    for p in procs:
        try:
            c = p.cpu_times()
            total += c.user + c.system
        except psutil.Error:
            continue
    return total


class StopSignals:
    """SIGINT, SIGTERM and SIGHUP recorded, not obeyed, while held: stopping `steward run` stops its job first and
    records the run (DEF-002). `steward run` holds it from before the run is recorded until its outcome is, so a
    signal at any moment, also during setup, gives an `interrupted` outcome and exit 128 + N (DEF-012)."""

    def __init__(self) -> None:
        self.stop: dict[str, int] = {}
        self._previous: dict[int, Any] = {}

    def __enter__(self) -> "StopSignals":
        import threading

        if threading.current_thread() is threading.main_thread():
            for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self._previous[s] = signal.signal(s, lambda signum, _f: self.stop.setdefault("sig", signum))
        return self

    def __exit__(self, *exc: Any) -> None:
        for s, h in self._previous.items():
            signal.signal(s, h)


def execute(cmd: list[str], cwd: Path, limits: Limits, log_path: Path, poll: float = 0.5,
            env: dict[str, str] | None = None, stop: dict[str, int] | None = None) -> Outcome:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    if stop is not None:  # the caller holds the signals already (DEF-012)
        return _supervise(cmd, cwd, limits, log_path, poll, start, stop, env)
    with StopSignals() as held:
        return _supervise(cmd, cwd, limits, log_path, poll, start, held.stop, env)


def _cpu_progress(ps: psutil.Process, now: float, limit: float, state: dict[str, Any]) -> bool:
    """True when no process of the tree has used CPU for `limit` seconds. Each process is followed by its own pid
    and start time, so a busy new worker counts even when a retired one had used more (review of 0.9.0, Q32)."""
    seen: dict[tuple[int, float], float] = state.setdefault("procs", {})
    progressed = False
    for p in _tree(ps):
        try:
            key = (p.pid, p.create_time())
            state.setdefault("seen", set()).add(key)
            c = p.cpu_times()
            cpu = c.user + c.system
        except psutil.Error:
            continue
        if cpu > seen.get(key, -1.0) + 0.01:
            progressed = True
        seen[key] = max(cpu, seen.get(key, 0.0))
    if progressed:
        state["at"] = now
        return False
    return now - state["at"] > limit


def _members(pgid: int, token: str, seen: set[tuple[int, float]], blind: list[bool] | None = None) -> list[psutil.Process]:
    """Processes of the job's group that are provably the job's: they carry its run token, or the supervisor saw
    them in the job's tree (pid and start time). A reused group id is never enough (review R20)."""
    out = []
    try:
        procs = list(psutil.process_iter())
    except (psutil.Error, OSError):  # S1: enumeration denied: fall back to the members the supervisor observed
        if blind is not None:
            blind.append(True)  # U13 (0.12.0): unobserved members could remain; the caller cannot claim completeness
        procs = []
        for pid, ctime in seen:
            try:
                q = psutil.Process(pid)
                if abs(q.create_time() - ctime) < 0.01:
                    procs.append(q)
            except psutil.Error:
                continue
    for p in procs:
        try:
            if os.getpgid(p.pid) != pgid:
                continue
            key = (p.pid, p.create_time())
        except (psutil.Error, OSError):
            continue
        ok = key in seen
        if not ok:
            try:
                ok = p.environ().get("STEWARD_RUN_TOKEN") == token
            except (psutil.Error, OSError):
                ok = False
        if ok:
            out.append(p)
    return out


def _kill_group(pgid: int, token: str = "", seen: set[tuple[int, float]] | None = None) -> bool:
    """Whatever is left of the job after its leader ended (descendants never outlive the run), signalled through
    psutil handles of verified members only (R20). Never raises; False when cleanup could not be completed (S1)."""
    blind: list[bool] = []
    try:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            procs = _members(pgid, token, seen or set(), blind)
            if not procs:
                return not blind  # U13: "none found" is complete only when the system could be asked
            for p in procs:
                try:
                    p.send_signal(sig)
                except psutil.Error:
                    pass
            psutil.wait_procs(procs, timeout=0.5)
        return not _members(pgid, token, seen or set(), blind) and not blind
    except Exception:
        return False


def _supervise(cmd: list[str], cwd: Path, limits: Limits, log_path: Path, poll: float, start: float,
               stop: dict[str, int], env: dict[str, str] | None = None) -> Outcome:
    last_output = start
    cpu_state: dict[str, Any] = {"at": start}
    peak = 0.0
    breached = None
    with open(log_path, "wb") as log:
        token = uuid.uuid4().hex  # R20: marks the job's processes, so cleanup can tell them from a reused group
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                                env={**os.environ, **(env or {}), "STEWARD_RUN_TOKEN": token})
        seen: set[tuple[int, float]] = set()
        cpu_state["seen"] = seen
        try:
            assert proc.stdout is not None
            os.set_blocking(proc.stdout.fileno(), False)  # R20: inside the guarded interval
            res = _watch(proc, cwd, limits, log, poll, start, stop, cpu_state, last_output)
        except BaseException:
            _kill_group(proc.pid, token, seen)  # Q32: on every exit path, also when discovery failed after launch
            raise
        if not _kill_group(proc.pid, token, seen):  # S1: the outcome stands, and says cleanup was incomplete
            res.details["cleanup"] = "incomplete"
        return res


def _watch(proc: subprocess.Popen, cwd: Path, limits: Limits, log: Any, poll: float, start: float,
           stop: dict[str, int], cpu_state: dict[str, Any], last_output: float) -> Outcome:
    peak = 0.0
    breached = None
    if True:
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            ps = psutil.Process(proc.pid)
        except psutil.Error:
            ps = None
        while True:
            for key, _ in sel.select(timeout=poll):
                chunk = key.fileobj.read(65536)  # type: ignore[union-attr]
                if chunk:
                    last_output = time.monotonic()
                    log.write(chunk)
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.flush()
            if proc.poll() is not None:
                rest = proc.stdout.read() or b""
                log.write(rest)
                sys.stdout.buffer.write(rest)
                if "sig" in stop:  # Q32: an interruption that came with the leader's exit is still one
                    breached = f"interrupted by {signal.Signals(stop['sig']).name}"
                break
            if "sig" in stop:
                breached = f"interrupted by {signal.Signals(stop['sig']).name}"
                _terminate(proc)
                proc.wait()
                break
            now = time.monotonic()
            if ps is None:
                continue
            try:
                tree = _tree(ps)
                rss = _rss_mb(tree)
                for q in tree:  # R20: every process seen in the job's tree is the job's
                    try:
                        cpu_state.setdefault("seen", set()).add((q.pid, q.create_time()))
                    except psutil.Error:
                        pass
            except psutil.Error:
                continue
            peak = max(peak, rss)
            if limits.wall_s is not None and now - start > limits.wall_s:
                breached = f"wall time > {limits.wall_s:g} s"
            elif limits.mem_mb is not None and rss > limits.mem_mb:
                breached = f"memory {rss:.0f} MB > {limits.mem_mb:g} MB"
            elif limits.hang_s is not None and now - last_output > limits.hang_s:
                breached = f"no output for > {limits.hang_s:g} s"
            elif limits.hang_cpu_s is not None and _cpu_progress(ps, now, limits.hang_cpu_s, cpu_state):
                breached = f"no CPU progress for > {limits.hang_cpu_s:g} s"
            elif limits.disk_free_mb is not None and shutil.disk_usage(cwd).free / (1 << 20) < limits.disk_free_mb:
                breached = f"free disk < {limits.disk_free_mb:g} MB"
            if breached:
                _terminate(proc)
                proc.wait()
                break
        sel.close()
    duration = time.monotonic() - start
    if "sig" in stop:  # DEF-012: the job's own status, or null; a stopped job never reads as a clean exit 0
        return Outcome("interrupted", proc.returncode or None, duration, peak, breached, {"signal": stop["sig"]})
    if breached:
        return Outcome("killed", proc.returncode, duration, peak, breached)
    return Outcome("finished" if proc.returncode == 0 else "failed", proc.returncode, duration, peak)


def new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]


def recover(ledger: Ledger) -> list[str]:
    """Mark started runs whose process is gone as interrupted. Never deletes anything."""
    from .ledger import verify

    v = verify(ledger.path)
    done = {e.get("run") for e in v.entries if e.get("kind") in ("outcome", "interrupted")}
    marked = []
    for e in v.entries:
        if e.get("kind") == "started" and e["run"] not in done:
            pid = e.get("pid")
            alive = False
            if isinstance(pid, int):
                try:  # the supervising steward process; a reused pid has a different creation time
                    alive = psutil.pid_exists(pid) and abs(psutil.Process(pid).create_time() - e.get("pid_created", 0)) < 1
                except psutil.Error:
                    alive = False
            if not alive:
                ledger.append("interrupted", {"run": e["run"]})
                marked.append(e["run"])
    return marked
