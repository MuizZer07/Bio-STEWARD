"""Supervised sprints (0.13.0; DESIGN_BRIEF_sprint §2 - §3; SP1 - SP6).

A sprint is an ordered list of tasks for a window of time (`development/sprints/<id>.toml`). Each task names the agent
that does it (an adapter: claude-code, codex or shell), what it waits for, its limits and the commands that decide it
is done. `steward sprint start` dispatches each task when its order comes (`dispatch = "order"`, the default: only
after `steward sprint go TASK`) or when its dependencies are done (`"auto"`), each in its own git worktree and branch,
through `steward run`, so the watchdog, limits and run ledger apply unchanged. Every change is a line in the sprint's
hash-chained ledger (`development/sprints/<id>.jsonl`).

**Done is decided by the task's commands, never by the agent.** Steward starts agents; it never merges, approves or
signs for them: each done task's branch waits for the human.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .models import Strict, Text

DIR = "development/sprints"
ADAPTERS = ("claude-code", "codex", "shell")
TERMINAL = {"done", "failed", "blocked", "skipped"}
SIGNATURES = ("policy.change", "spend", "unseal", "amend", "waiver")


class Window(Strict):
    start: dt.datetime
    end: dt.datetime

    @model_validator(mode="after")
    def _order(self) -> "Window":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window start and end need their time zone")
        if self.end <= self.start:
            raise ValueError("the window ends before it starts")
        return self


class Limits(Strict):
    wall_minutes: float = Field(default=60, gt=0)
    idle_minutes: float | None = Field(default=None, gt=0)  # no CPU progress for this long is a hang


class Task(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    title: Text
    ref: str | None = None                       # a board task or an exchange item
    agent: Literal["claude-code", "codex", "shell"] = "shell"
    model: str | None = None                     # suggested; the agent ledger records what ran
    prompt: str | None = None                    # for an agent adapter: what to do
    command: str | None = None                   # for the shell adapter
    after: list[str] = Field(default_factory=list)
    worktree: bool = True                        # SP2: each task in its own worktree and branch
    limits: Limits = Field(default_factory=Limits)
    done: list[str] = Field(default_factory=list)  # acceptance commands: every one must exit 0
    needs: list[str] = Field(default_factory=list)  # signatures this task will need (§3)

    @model_validator(mode="after")
    def _what(self) -> "Task":
        if self.agent == "shell" and not self.command:
            raise ValueError(f"task {self.id}: the shell adapter needs `command`")
        if self.agent != "shell" and not (self.prompt or self.title):
            raise ValueError(f"task {self.id}: an agent task needs `prompt`")
        if not self.done:
            raise ValueError(f"task {self.id}: `done` needs at least one command (an agent never decides it is done)")
        return self

    @field_validator("needs")
    @classmethod
    def _needs(cls, v: list[str]) -> list[str]:
        bad = [n for n in v if n.split(":")[0] not in SIGNATURES]
        if bad:
            raise ValueError(f"unknown signature kind(s) {bad}; use {', '.join(SIGNATURES)}")
        return v


class SprintMeta(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    window: Window
    max_parallel: int = Field(default=1, ge=1, le=16)
    dispatch: Literal["order", "auto"] = "order"  # SP1
    milestone: str | None = None


class SprintFile(Strict):
    schema_: Literal["steward.sprint/0.1"] = Field(alias="schema")
    sprint: SprintMeta
    task: list[Task] = Field(default_factory=list)

    @model_validator(mode="after")
    def _graph(self) -> "SprintFile":
        ids = [t.id for t in self.task]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate task id(s) {dup}")
        for t in self.task:
            unknown = [a for a in t.after if a not in ids]
            if unknown:
                raise ValueError(f"task {t.id} waits for unknown task(s) {unknown}")
        deps = {t.id: set(t.after) for t in self.task}
        seen: set[str] = set()
        while len(seen) < len(ids):  # Kahn: a cycle leaves tasks that never become free
            free = [i for i in ids if i not in seen and deps[i] <= seen]
            if not free:
                raise ValueError(f"the tasks wait for each other in a cycle: {sorted(set(ids) - seen)}")
            seen |= set(free)
        return self


def path(root: Path, sid: str) -> Path:
    return root / DIR / f"{sid}.toml"


def ledger_path(root: Path, sid: str) -> Path:
    return root / DIR / f"{sid}.jsonl"


def load(root: Path, sid_or_file: str) -> SprintFile:
    p = Path(sid_or_file)
    p = p if p.suffix == ".toml" else path(root, sid_or_file)
    p = p if p.is_absolute() else (root / p if not p.is_file() else p)
    return SprintFile.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))


def order(sf: SprintFile) -> list[str]:
    ids = [t.id for t in sf.task]
    deps = {t.id: set(t.after) for t in sf.task}
    out: list[str] = []
    while len(out) < len(ids):
        out += [i for i in ids if i not in out and deps[i] <= set(out)]
    return out


# ---------------------------------------------------------------- the ledger and the state of each task
def led(root: Path, sid: str, repo_id: str):
    from .ledger import Ledger

    return Ledger(ledger_path(root, sid), "sprint", repo_id)


def events(root: Path, sid: str) -> list[dict[str, Any]]:
    from .ledger import verify

    p = ledger_path(root, sid)
    if not p.is_file():
        return []
    v = verify(p)
    if v.errors or v.torn_tail:
        raise ValueError(f"the sprint ledger {p.name} is not intact; run `steward ledger recover {DIR}/{p.name}`")
    return v.entries


def states(sf: SprintFile, evs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Task -> {state, orders, run, branch, checks, note}, folded from the ledger."""
    out = {t.id: {"state": "planned", "go": False, "hold": False} for t in sf.task}
    for e in evs:
        t = e.get("task")
        if t not in out:
            continue
        if e.get("kind") == "order":
            o = e.get("order")
            if o == "go":
                out[t]["go"], out[t]["hold"] = True, False
                if e.get("retry") and out[t]["state"] in ("failed", "blocked"):
                    out[t]["state"] = "planned"
            elif o == "hold":
                out[t]["hold"] = True
            elif o == "skip":
                out[t]["state"] = "skipped"
                out[t]["note"] = e.get("reason")
        elif e.get("kind") == "state":
            out[t].update({k: v for k, v in e.items() if k in ("state", "run", "branch", "checks", "note", "worktree", "commit")})
    # dependants of a failed or skipped task are blocked, transitively
    changed = True
    while changed:
        changed = False
        for tk in sf.task:
            s = out[tk.id]
            if s["state"] in ("planned", "ready") and any(out[a]["state"] in ("failed", "blocked") for a in tk.after):
                s["state"], s["note"] = "blocked", "a task it waits for failed"
                changed = True
    for tk in sf.task:
        s = out[tk.id]
        if s["state"] == "planned" and all(out[a]["state"] in ("done", "skipped") for a in tk.after):
            s["state"] = "ready"
    return out


def stopped(evs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((e for e in reversed(evs) if e.get("kind") == "stop"), None)


# ---------------------------------------------------------------- adapters (SP3)
def agent_prompt(t: Task, sf: SprintFile) -> str:
    lines = [f"Sprint {sf.sprint.id}, task {t.id}: {t.title}."]
    if t.ref:
        lines.append(f"It answers {t.ref}; read it first.")
    if t.prompt:
        lines.append(t.prompt)
    lines.append("The task is done only when these commands all exit 0 in this worktree: " + "; ".join(t.done) + ".")
    lines.append("Commit your work on this branch. Never merge, push, sign an approval or edit the sprint file.")
    return "\n".join(lines)


def command(t: Task, sf: SprintFile) -> list[str]:
    if t.agent == "shell":
        return ["/bin/sh", "-c", t.command or "true"]
    if t.agent == "claude-code":
        return ["claude", "-p", agent_prompt(t, sf)] + (["--model", t.model] if t.model else [])
    return ["codex", "exec"] + (["-m", t.model] if t.model else []) + [agent_prompt(t, sf)]


# ---------------------------------------------------------------- the dispatcher
def _worktree(root: Path, sid: str, t: Task) -> tuple[Path, str]:
    from .fsutil import git_run

    branch = f"sprint/{sid}/{t.id}"
    wt = root / ".steward" / "sprints" / sid / t.id
    if wt.is_symlink():
        raise RuntimeError(f"{wt.relative_to(root)} is a link; remove it")
    if wt.exists():  # V11 (0.13.0): reused only when it is that task's own worktree on its own branch
        top = git_run(wt, "rev-parse", "--show-toplevel", text=True)
        head = git_run(wt, "symbolic-ref", "--short", "HEAD", text=True)
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(wt) or \
                head.returncode != 0 or head.stdout.strip() != branch:
            raise RuntimeError(f"{wt.relative_to(root)} exists but is not the worktree of {branch}; remove it")
        return wt, branch
    wt.parent.mkdir(parents=True, exist_ok=True)
    exists = git_run(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = ["worktree", "add", str(wt), branch] if exists else ["worktree", "add", "-b", branch, str(wt)]
    out = git_run(root, *args, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"cannot create the worktree for {t.id}: {out.stderr.strip()[:200]}")
    return wt, branch


def _checks(cwd: Path, t: Task, cancelled, deadline: dt.datetime) -> list[dict[str, Any]]:
    """Each done command, polled: a stop or the end of the window ends it (V13). An unfinished command has exit None."""
    res = []
    for c in t.done:
        if cancelled() or dt.datetime.now(dt.timezone.utc) >= deadline:
            res.append({"command": c, "exit": None, "note": "not run: stopped or the window ended"})
            continue
        proc = subprocess.Popen(c, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        code = None
        while code is None:
            code = proc.poll()
            if code is None and (cancelled() or dt.datetime.now(dt.timezone.utc) >= deadline):
                try:
                    os.killpg(proc.pid, 15)
                except OSError:
                    pass
                proc.wait()
                res.append({"command": c, "exit": None, "note": "ended: stopped or the window ended"})
                break
            time.sleep(0.05)
        else:
            res.append({"command": c, "exit": code})
    return res


def _clean_commit(wt: Path) -> tuple[bool, str | None]:
    """(no uncommitted changes, HEAD commit) of a task's worktree (V11: the merge is the checked commit)."""
    from .fsutil import git_run

    st = git_run(wt, "status", "--porcelain", text=True)
    head = git_run(wt, "rev-parse", "HEAD", text=True)
    return (st.returncode == 0 and not st.stdout.strip()), (head.stdout.strip() if head.returncode == 0 else None)


def dispatch(root: Path, cfg: Any, sf: SprintFile, *, watch: bool = False, poll: float = 5.0,
             now=lambda: dt.datetime.now(dt.timezone.utc), out=print) -> int:
    """Run the sprint until no task can progress (or, with `watch`, until the window ends or `sprint stop`)."""
    from .fsutil import owner_lock, release_owner_lock

    sid = sf.sprint.id
    lock = owner_lock(root, f"sprint-{sid}")  # V12 (0.13.0): one dispatcher per sprint
    if lock is None:
        out(f"steward: another dispatcher is running sprint {sid} (or its lock cannot be made); nothing was started")
        return 75
    try:
        return _dispatch(root, cfg, sf, watch, poll, now, out)
    finally:
        release_owner_lock(root, f"sprint-{sid}", lock)


def _dispatch(root: Path, cfg: Any, sf: SprintFile, watch: bool, poll: float, now, out) -> int:
    sid = sf.sprint.id
    lg = led(root, sid, cfg.steward.repo_id)
    tasks = {t.id: t for t in sf.task}
    running: dict[str, tuple[subprocess.Popen, Path, str]] = {}
    if not any(e.get("kind") == "opened" for e in events(root, sid)):
        lg.append("opened", {"sprint": sid, "tasks": order(sf), "dispatch": sf.sprint.dispatch})
    for tid, s in states(sf, events(root, sid)).items():  # V12: work an ended dispatcher left unfinished
        if s["state"] in ("running", "checking"):
            lg.append("state", {"task": tid, "state": "failed", "branch": s.get("branch"),
                                "note": "its dispatcher ended before it finished (see the run ledger); retry with go --retry"})
            out(f"{tid}: failed (left unfinished by an earlier dispatcher)")
    while True:
        evs = events(root, sid)
        st = states(sf, evs)
        stop = stopped(evs)
        if stop and stop.get("now"):
            for tid, (proc, _, _) in running.items():
                proc.terminate()  # `steward run` stops its job, records it, and exits
        # finished runs: the acceptance commands decide
        for tid, (proc, wt, branch) in list(running.items()):
            if proc.poll() is None:
                continue
            del running[tid]
            if proc.returncode != 0:
                lg.append("state", {"task": tid, "state": "failed", "note": f"steward run exited {proc.returncode}",
                                    "branch": branch})
                out(f"{tid}: failed (steward run exited {proc.returncode})")
                continue
            if stopped(events(root, sid)):  # V13: no acceptance after a stop
                lg.append("state", {"task": tid, "state": "failed", "branch": branch, "note": "stopped before its checks"})
                out(f"{tid}: failed (stopped before its checks)")
                continue
            lg.append("state", {"task": tid, "state": "checking", "branch": branch})
            checks = _checks(wt, tasks[tid], lambda: bool(stopped(events(root, sid))), sf.sprint.window.end)
            clean, commit = _clean_commit(wt) if wt != root else (True, None)
            ok = all(c["exit"] == 0 for c in checks) and clean
            lg.append("state", {"task": tid, "state": "done" if ok else "failed", "checks": checks, "branch": branch,
                                "commit": commit, "note": None if ok else (
                                    "an acceptance command did not pass" if clean else "uncommitted changes in its worktree")})
            out(f"{tid}: {'done' if ok else 'failed'} ({sum(c['exit'] == 0 for c in checks)} of {len(checks)} checks "
                f"passed); branch {branch} waits for your merge" if ok else
                f"{tid}: failed ({sum(c['exit'] == 0 for c in checks)} of {len(checks)} checks passed)")
        st = states(sf, events(root, sid))
        t_now = now()
        in_window = sf.sprint.window.start <= t_now < sf.sprint.window.end
        if not stop and in_window:
            for tid in order(sf):
                if len(running) >= sf.sprint.max_parallel:
                    break
                s, t = st[tid], tasks[tid]
                if s["state"] != "ready" or s.get("hold") or tid in running:
                    continue
                if sf.sprint.dispatch == "order" and not s.get("go"):
                    continue
                if t_now + dt.timedelta(minutes=t.limits.wall_minutes) > sf.sprint.window.end:
                    continue  # it would not finish before the window ends
                try:
                    wt, branch = _worktree(root, sid, t) if t.worktree else (root, "(no worktree)")
                except RuntimeError as e:
                    lg.append("state", {"task": tid, "state": "failed", "note": str(e)})
                    out(f"{tid}: failed ({e})")
                    continue
                if now() + dt.timedelta(minutes=t.limits.wall_minutes) > sf.sprint.window.end or \
                        stopped(events(root, sid)):  # V13: the clock and stop read again after setup
                    continue
                argv = [sys.executable, "-m", "steward.cli", "run", "--repo", str(root),
                        "--label", f"sprint:{sid}:{tid}", "--wall", str(int(t.limits.wall_minutes * 60))]
                if t.limits.idle_minutes:
                    argv += ["--hang-cpu", str(int(t.limits.idle_minutes * 60))]
                argv += ["--", *command(t, sf)]
                proc = subprocess.Popen(argv, cwd=wt, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                running[tid] = (proc, wt, branch)
                lg.append("state", {"task": tid, "state": "running", "branch": branch, "agent": t.agent,
                                    "model": t.model, "worktree": wt.relative_to(root).as_posix() if wt != root else "."})
                out(f"{tid}: running ({t.agent}{', ' + t.model if t.model else ''}) on {branch}")
        if running:
            time.sleep(min(poll, 0.5))
            continue
        st = states(sf, events(root, sid))
        waiting = [i for i, s in st.items() if s["state"] == "ready"]
        t_now = now()
        if stop or not waiting or t_now >= sf.sprint.window.end:
            break
        # V14 (0.14.0): what could start now: ordered (or auto), not held, and fitting before the window ends
        startable = [i for i in waiting if (st[i].get("go") or sf.sprint.dispatch == "auto") and not st[i].get("hold")
                     and t_now + dt.timedelta(minutes=tasks[i].limits.wall_minutes) <= sf.sprint.window.end]
        if t_now < sf.sprint.window.start:
            if not watch:
                out(f"the window opens at {sf.sprint.window.start.isoformat()}; nothing was started "
                    "(steward sprint start --watch waits for it)")
                break
            time.sleep(min(poll, max(0.05, (sf.sprint.window.start - t_now).total_seconds())))
            continue
        if not startable:
            if not watch:
                ordered = [i for i in waiting if st[i].get("go") or sf.sprint.dispatch == "auto"]
                if not ordered and sf.sprint.dispatch == "order":
                    out("waiting for orders: " + ", ".join(f"steward sprint go {sid} {i}" for i in waiting))
                elif ordered:
                    out("nothing more can start now: " + ", ".join(
                        f"{i} ({'held' if st[i].get('hold') else 'would not finish before the window ends'})" for i in ordered))
                break
            time.sleep(poll)  # watch: wait for an order, a release or the end, never spinning
            continue
    return 0


def signatures(sf: SprintFile) -> dict[str, list[str]]:
    """Signature kind -> the tasks that need it (§3: pre-sign or defer before the sprint starts)."""
    out: dict[str, list[str]] = {}
    for t in sf.task:
        for n in t.needs:
            out.setdefault(n.split(":")[0], []).append(t.id)
    return out


def signing_advice(sf: SprintFile) -> list[str]:
    need = signatures(sf)
    if not need:
        return ["No task declares a signature it needs."]
    end = sf.sprint.window.end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []
    for kind, tids in sorted(need.items()):
        if kind == "policy.change":
            lines.append(f"{kind} ({', '.join(tids)}): sign later. The change is prepared when made; R-33 waits for you; "
                         "sign the queue with `steward authorize sign-pending` (it cannot be signed before it exists).")
        else:
            lines.append(f"{kind} ({', '.join(tids)}): sign ahead now, ending with the window: "
                         f"`steward authorize prepare {kind} --object … --budget … --expires {end}`, then "
                         "`steward authorize sign <nonce>`.")
    return lines


def report(root: Path, sf: SprintFile) -> str:
    evs = events(root, sf.sprint.id)
    st = states(sf, evs)
    lines = [f"# Sprint {sf.sprint.id}", "",
             f"- Window: {sf.sprint.window.start.isoformat()} – {sf.sprint.window.end.isoformat()}",
             f"- Dispatch: {sf.sprint.dispatch}; at most {sf.sprint.max_parallel} at once", "",
             "| Task | Agent | State | Checks | Branch | Checked commit |", "|---|---|---|---|---|---|"]
    tasks = {t.id: t for t in sf.task}
    for tid in order(sf):
        s = st[tid]
        checks = s.get("checks") or []
        lines.append(f"| {tid} | {tasks[tid].agent} | {s['state']} | "
                     f"{sum(c.get('exit') == 0 for c in checks)}/{len(checks)} | {s.get('branch') or '—'} | "
                     f"{(s.get('commit') or '—')[:12]} |")
    done = [t for t in order(sf) if st[t]["state"] == "done"]
    lines += ["", "Done is decided by each task's commands, never by the agent. "
              + (f"Branches waiting for your merge (merge the checked commit): "
                 f"{', '.join(st[t]['branch'] + ' @ ' + (st[t].get('commit') or '?')[:12] for t in done)}." if done else "")]
    return "\n".join(lines) + "\n"


def draft(root: Path, cfg: Any, sid: str, source: str, milestone: str | None, start: dt.datetime, hours: float) -> str:
    """A sprint file drafted from the board's open tasks, the open exchange items, or a milestone's open tasks."""
    from . import exchange as xc

    refs: list[tuple[str, str]] = []
    if milestone:
        from . import milestones as ms

        mf = ms.load(root)
        m = next((x for x in (mf.milestone if mf else []) if x.id == milestone), None)
        if m is None:
            raise ValueError(f"no milestone {milestone!r} in {ms.FILE}")
        states_ = ms._task_states(root, cfg) or {}
        closed = set(getattr(getattr(cfg, "tasks", None), "closed", []) or [])
        refs = [(t, f"{m.title}: {t}") for t in m.tasks if states_.get(t) not in closed]
    elif source == "exchange":
        hist = xc.states(root) if xc.folder(root).is_dir() else {}
        for rel, text in xc.items(root).get("inbox", []):
            iid = Path(rel).stem
            if xc.current(hist.get(iid, [])) in ("acknowledged", "verified", "accepted", "deferred"):
                head = xc.parse(text)[0]
                if head.get("kind") != "response":
                    refs.append((iid, str(head.get("title", iid))))
    else:
        from . import milestones as ms

        states_ = ms._task_states(root, cfg) or {}
        closed = set(getattr(getattr(cfg, "tasks", None), "closed", []) or [])
        refs = [(tid, tid) for tid, s in sorted(states_.items()) if s not in closed]
    end = start + dt.timedelta(hours=hours)
    out = [f'schema = "steward.sprint/0.1"\n', "[sprint]", f'id = "{sid}"',
           f"window = {{ start = {start.isoformat()}, end = {end.isoformat()} }}",
           "max_parallel = 1", 'dispatch = "order"   # tasks start only on `steward sprint go`; "auto" once trusted']
    if milestone:
        out.append(f'milestone = "{milestone}"')
    for i, (ref, title) in enumerate(refs, start=1):
        tid = f"T{i}"
        out += ["", "[[task]]", f'id = "{tid}"', f"title = {_q(title)}", f"ref = {_q(ref)}", 'agent = "claude-code"',
                f"prompt = {_q('Resolve ' + ref + '. Write or extend its regression test first.')}",
                "limits = { wall_minutes = 90, idle_minutes = 15 }",
                'done = ["python -m pytest -q", "steward check --gate default"]', "needs = []"]
    return "\n".join(out) + "\n"


def _q(s: str) -> str:
    import json

    return json.dumps(s)


def validate_file(p: Path) -> tuple[SprintFile | None, str | None]:
    try:
        return SprintFile.model_validate(tomllib.loads(p.read_text(encoding="utf-8"))), None
    except ValidationError as e:
        err = e.errors()[0]
        return None, f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
    except (OSError, ValueError) as e:
        return None, str(e).splitlines()[0][:200]



NEXT_STATE = {None: {"running", "failed"}, "running": {"checking", "failed"}, "checking": {"done", "failed"},
              "failed": {"running", "failed"}, "done": set()}


def ledger_findings(sf: SprintFile, evs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """V15 (0.14.0): the ledger belongs to this sprint's plan, and each task's states follow the dispatcher's order."""
    out: list[dict[str, Any]] = []
    opened = [e for e in evs if e.get("kind") == "opened"]
    first_open = next((i for i, e in enumerate(evs) if e.get("kind") == "opened"), None)
    early = [e for i, e in enumerate(evs) if e.get("kind") == "state" and (first_open is None or i < first_open)]
    if early:  # V15 (0.15.0, 0.17.0): every state follows the sprint's opened record
        out.append({"code": "R-71.not_opened", "message": f"{len(early)} task state(s) before the sprint's opened record"})
    if opened and opened[0].get("sprint") != sf.sprint.id:
        out.append({"code": "R-71.foreign_ledger", "message": f"opened for sprint {opened[0].get('sprint')!r}"})
    if opened and sorted(opened[0].get("tasks") or []) != sorted(t.id for t in sf.task):
        out.append({"code": "R-71.plan_changed", "message": "the plan's tasks differ from those the sprint opened with"})
    ids = {t.id for t in sf.task}
    last: dict[str, str | None] = {}
    for e in evs:
        if e.get("kind") != "state":
            continue
        t, new = e.get("task"), e.get("state")
        if t not in ids:
            out.append({"code": "R-71.unknown_task", "value": t})
            continue
        prev = last.get(t)
        retried = prev in ("failed",) and new == "running"
        if new not in NEXT_STATE.get(prev, set()) and not retried:
            out.append({"code": "R-71.bad_transition", "value": t, "message": f"{prev or '(new)'} → {new}"})
        last[t] = new
    return out
