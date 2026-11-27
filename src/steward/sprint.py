"""Supervised sprints (0.13.0; DESIGN_BRIEF_sprint §2 - §3; SP1 - SP6; 0.21.0: STW-051 - STW-053).

A sprint is an ordered list of tasks for a window of time (`development/sprints/<id>.toml`). Each task names the agent
that does it (an adapter: claude-code, codex, antigravity or shell), the permissions it runs with, what it waits for,
its limits and the commands that decide it is done. `steward sprint start` dispatches each task when its order comes
(`dispatch = "order"`, the default: only after `steward sprint go TASK`) or when its dependencies are done
(`"auto"`), each in its own git worktree and branch, through `steward run`, so the watchdog, limits and run ledger
apply unchanged. Every change is a line in the sprint's hash-chained ledger (`development/sprints/<id>.jsonl`).

**Done is decided by the task's commands, never by the agent.** Steward starts agents; it never merges, approves or
signs for them: each done task's branch waits for the human.

0.21.0: each agent adapter maps the task's `permissions` (and its `allow` / `deny` lists) to that agent's own flags,
with a default deny list no task can remove (STW-051); Codex's work is committed after it exits, since its sandbox
cannot write `.git` (S4). Each task's output goes to `.steward/sprints/<id>/<task>.log`, linked from the ledger with
its run (STW-052, S7). The dispatcher reads the sprint file again before each dispatch (S1), but only while no
task runs or on the human's `steward sprint reload` order; a running task keeps the definition it started with
(W12b, F7).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .fsutil import SAFE_GIT_CONFIG
from .models import Strict, Text

DIR = "development/sprints"
WORK = ".steward/sprints"  # worktrees (by default) and task logs; git-ignored
ADAPTERS = ("claude-code", "codex", "antigravity", "shell")
TERMINAL = {"done", "failed", "blocked", "skipped"}
SIGNATURES = ("policy.change", "spend", "unseal", "amend", "waiver")
PERMISSIONS = ("read-only", "edit", "edit-and-run")
# STW-051: commands no agent task may run, whatever its `allow` says. A task's `deny` adds to them; nothing removes one.
DEFAULT_DENY = ("git push", "git merge", "git rebase", "git reset", "git tag", "git update-ref", "git filter-branch",
                "steward authorize", "steward release", "steward spend", "steward unseal", "steward sprint",
                "gh release", "gh pr merge", "npm publish", "twine upload", "uv publish", "cargo publish")
REQUIRES = ("display", "network")
# What each adapter's run can offer (STW-051). Codex's sandbox has no display (GUI processes abort in it); what
# Antigravity's sandbox offers is not known, so it is offered nothing. The shell adapter runs the project's own
# command with what the machine has.
OFFERS = {"claude-code": {"display", "network"}, "codex": {"network"}, "antigravity": set(),
          "shell": {"display", "network"}}
COMMAND_ENTRY = re.compile(r"^[A-Za-z0-9_./@:=+~-][^\n\r()]{0,199}$")
GIT_READ = ("git status", "git diff", "git log", "git show")
GIT_COMMIT = ("git add", "git commit")
READ_COMMANDS = GIT_READ + ("ls", "cat", "grep", "rg", "head", "tail", "wc", "find", "pwd")
PERMISSION_TEXT = {
    "read-only": "read files and run read-only git commands; you cannot change files",
    "edit": "read and edit files in this worktree and commit them with git add and git commit; other commands are refused",
    "edit-and-run": "read and edit files in this worktree, commit them, and run commands",
}
# S4: Codex's workspace-write sandbox refuses writes to .git, so the adapter commits after the agent exits.
# W12b (F9): with the same git configuration overrides as steward's own git calls (no hooks, no fsmonitor, no
# repository-selected programs), since this step runs outside Codex's sandbox. The user's name and e-mail still apply.
_SAFE_GIT = "git " + " ".join(f"-c {shlex.quote(c)}" for c in SAFE_GIT_CONFIG)
COMMIT_STEP = (f'msg=$1; shift; "$@" < /dev/null && {_SAFE_GIT} add -A && '
               f'{{ {_SAFE_GIT} diff --cached --quiet || {_SAFE_GIT} commit --no-verify -q -m "$msg"; }}')
# W12b (F8): commands of dispatch.READ_ONLY an Antigravity edit-and-run task does not get: they run any other command
RUN_EXCLUDED = ("git", "env", "python", "python3", "uv")
LOG_TAIL = 256 * 1024  # bytes of a task log read for its last tool step


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


# W12b (F8): commands that only run another command. Each is removed from the front of an entry before it is compared
# with the deny list, so `env git push` or `sh -c "git push"` is compared as `git push`.
WRAPPERS = ("env", "nohup", "xargs", "command", "exec", "time", "nice", "sudo", "doas", "timeout", "stdbuf")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
INTERPRETERS = ("python", "python3", "node", "perl", "ruby", "deno", "bun")  # alone they run any program
GIT_GLOBAL_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env")
UV_RUN_VALUE = ("--extra", "--with", "--python", "-p", "--project", "--directory", "--group", "--package", "--env-file")
SHELL_META = re.compile(r"[;&|`$<>*?\\]")
# W12c (N1, Muiz: refuse broad forms): an allow entry may not start with a shell, a wrapper or a launcher, whatever
# its options; listing their option spellings one by one missed `env -u HOME git push` and `uvx twine upload`.
LAUNCHERS = WRAPPERS + SHELLS + (
    "fish", "csh", "tcsh", "strace", "script", "uvx", "npx", "pipx", "pnpx", "bunx",
    "eval", "source", ".", "builtin", "su", "pkexec", "runuser", "chroot", "unshare", "nsenter", "setsid", "flock",
    "ionice", "taskset", "watch", "parallel", "caffeinate", "arch", "sandbox-exec", "fakeroot", "busybox", "unbuffer",
    "expect", "rlwrap", "tmux", "screen", "ssh")
# An interpreter runs any program, versioned or not (python3.13, perl5.36, node22): matched by pattern.
INTERPRETER = re.compile(r"^(?:python|pythonw|pypy|ipython|node|nodejs|perl|ruby|irb|deno|bun|php|lua|luajit|"
                         r"rscript|r|julia|tclsh|wish|osascript|pwsh|powershell|awk|gawk|mawk|nawk|jshell|groovy)"
                         r"(?:-?\d+(?:\.\d+)*[a-z]?)?$")
# The one interpreter form an allow entry may name: `python -m MODULE` / `python3 -m MODULE`, with no other option
# before the module, and the module from this list.
PYTHON_MODULES = ("pytest",)
# Subcommands that run or define other commands, refused like a launcher.
LAUNCH_SUB = (("npm", "exec"), ("npm", "x"), ("pnpm", "exec"), ("pnpm", "dlx"), ("yarn", "exec"), ("yarn", "dlx"),
              ("uv", "tool"), ("gh", "api"), ("gh", "alias"), ("gh", "extension"), ("gh", "ext"), ("git", "config"),
              ("git", "submodule", "foreach"), ("git", "bisect", "run"), ("git", "difftool"), ("git", "mergetool"),
              ("steward", "run"), ("steward", "task", "dispatch"))
# `uv run` options an allow entry may carry before its program; the others choose the interpreter, add packages or
# point to another project.
UV_RUN_FLAGS = ("-q", "--quiet", "--frozen", "--locked", "--offline", "--no-sync", "--all-extras", "--dev", "--no-dev")
UV_RUN_KEEP_VALUE = ("--extra", "--group", "--package")


def _base(tok: str) -> str:
    return tok.rsplit("/", 1)[-1] if "/" in tok else tok


def _words(entry: str) -> list[str]:
    toks = entry.replace('"', " ").replace("'", " ").split()
    while toks and toks[-1].endswith("*"):
        last = toks.pop().rstrip("*")
        if last:
            toks.append(last)
    return toks


def normalise(entry: str) -> str:
    """A command entry in the form the deny list is compared in (W12b, F8): whitespace collapsed, quotes and a trailing
    `*` removed, a program path reduced to its name (`/usr/bin/git` is `git`), wrappers removed (`env A=1`, `nohup`,
    `xargs -0`, `sh -c`, `bash -lc`, `uv run --extra dev`), git's global options removed (`git -C dir push` is
    `git push`) and `python -m steward.cli` read as `steward`. An entry that is only a wrapper becomes "".
    W12c (N1): all in lower case, since a case-insensitive file system runs `GIT` as `git`."""
    toks = [t.lower() for t in _words(entry)]
    changed = True
    while toks and changed:
        changed = False
        toks[0] = _base(toks[0])
        head = toks[0]
        if head in WRAPPERS:
            toks.pop(0)
            while toks and (toks[0].startswith("-") or "=" in toks[0] or
                            (head == "timeout" and toks[0][:1].isdigit())):
                toks.pop(0)
            changed = True
        elif head in SHELLS:
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                toks.pop(0)
            changed = True
        elif head == "uv" and toks[1:2] == ["run"]:
            toks = toks[2:]
            while toks and toks[0].startswith("-"):
                opt = toks.pop(0)
                if opt in UV_RUN_VALUE and toks:
                    toks.pop(0)
            changed = True
        elif head in INTERPRETERS and toks[1:3] in (["-m", "steward.cli"], ["-m", "steward"]):
            toks = ["steward", *toks[3:]]
            changed = True
    if toks and toks[0] == "git":
        rest = toks[1:]
        kept = ["git"]
        while rest and rest[0].startswith("-"):
            opt = rest.pop(0)
            if opt in GIT_GLOBAL_VALUE and rest:
                rest.pop(0)
        toks = kept + rest
    return " ".join(toks)


def _covers(denied: str, entry: str) -> bool:
    """True when `entry`, normalised, names the denied command, a form of it (`git push origin main`), or a broader
    command that includes it (`git`, `git*`, `env`, `/usr/bin/git push`, `git -C . push`)."""
    e, d = normalise(entry), normalise(denied)
    return not e or e == d or e.startswith(d + " ") or d.startswith(e + " ")


def _refused_words(toks: list[str]) -> str | None:
    """Why the command `toks` cannot be allowed (W12c, N1), or None. The program is compared in lower case, after a
    path is reduced to its name."""
    if not toks:
        return "an empty command"
    prog = _base(toks[0]).lower()
    words = [prog, *(t.lower() for t in toks[1:])]
    if prog in LAUNCHERS:
        return f"{prog} is a shell, a wrapper or a launcher: it runs any command"
    if INTERPRETER.match(prog):
        if prog in ("python", "python3") and len(words) >= 3 and words[1] == "-m" and words[2] in PYTHON_MODULES:
            return None
        return (f"{prog} is an interpreter: it runs any program (only `python -m MODULE` or `python3 -m MODULE`, "
                f"MODULE one of {', '.join(PYTHON_MODULES)}, may be named)")
    for sub in LAUNCH_SUB:
        if words[:len(sub)] == list(sub):
            return f"{' '.join(sub)} runs or defines other commands"
    for d in DEFAULT_DENY:  # a program with a denied subcommand: the subcommand is named, with no option before it
        dw = d.split()
        for k in range(1, len(dw)):
            if words[:k] != dw[:k]:
                break
            if len(words) == k:
                return f"{' '.join(words)} without its subcommand includes {d}"
            if words[k][:1] in ("-", "+"):
                return f"an option ({toks[k]}) before the subcommand of {' '.join(dw[:k])}, which has {d} denied"
    if any(_covers(d, " ".join(words)) for d in DEFAULT_DENY):
        return "it names a command the default deny list keeps denied"
    if words[:2] == ["uv", "run"]:  # checked again on the program it runs, by the same rules
        i = 2
        while i < len(words) and words[i].startswith("-"):
            if words[i] in UV_RUN_FLAGS:
                i += 1
            elif words[i] in UV_RUN_KEEP_VALUE and i + 1 < len(words):
                i += 2
            else:
                return (f"uv run {toks[i]}: only {', '.join(UV_RUN_FLAGS + UV_RUN_KEEP_VALUE)} may come before "
                        "the program")
        if i >= len(words):
            return "uv run without its program"
        return _refused_words(toks[i:])
    return None


def _refused_allow(entry: str) -> str | None:
    """Why an `allow` entry cannot be given (W12b, F8; W12c, N1), or None."""
    if SHELL_META.search(entry):
        return "shell characters or a glob"
    if not normalise(entry):
        return "a wrapper that runs any command"
    return _refused_words(_words(entry))


def allow_refusal(entry: str) -> str | None:
    """Why `entry` cannot be an allow entry, the default deny list included, or None (W12c: dispatch's lists too)."""
    if not COMMAND_ENTRY.match(entry):
        return "not a command prefix"
    if any(_covers(d, entry) for d in DEFAULT_DENY):
        return "the default deny list keeps it denied"
    return _refused_allow(entry)


class Task(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    title: Text
    ref: str | None = None                       # a board task or an exchange item
    agent: Literal["claude-code", "codex", "antigravity", "shell"] = "shell"
    model: str | None = None                     # suggested; the agent ledger records what ran
    prompt: str | None = None                    # for an agent adapter: what to do
    command: str | None = None                   # for the shell adapter
    permissions: Literal["read-only", "edit", "edit-and-run"] = "edit"  # STW-051: mapped by each agent adapter
    allow: list[str] = Field(default_factory=list)  # command prefixes the agent may also run
    deny: list[str] = Field(default_factory=list)   # command prefixes denied in addition to DEFAULT_DENY
    requires: list[Literal["display", "network"]] = Field(default_factory=list)  # what its run must offer
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
        bad = [e for e in self.allow + self.deny if not COMMAND_ENTRY.match(e)]
        if bad:
            raise ValueError(f"task {self.id}: {bad} are not command prefixes (one line each, no parentheses)")
        kept = [e for e in self.allow if any(_covers(d, e) for d in DEFAULT_DENY)]
        if kept:
            raise ValueError(f"task {self.id}: `allow` names {kept}, which the default deny list keeps denied")
        why = [(e, _refused_allow(e)) for e in self.allow if _refused_allow(e)]
        if why:
            raise ValueError(f"task {self.id}: `allow` cannot name {why[0][0]!r} ({why[0][1]}); name the exact "
                             "command prefix, such as `make test` or `python -m pytest`")
        missing = [r for r in self.requires if r not in OFFERS[self.agent]]
        if missing:
            raise ValueError(f"task {self.id}: the {self.agent} adapter cannot offer {', '.join(missing)}; "
                             "choose an adapter that can")
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
    base: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")  # S9; default: HEAD's branch
    worktree_root: str | None = None  # S8: where task worktrees go (default .steward/sprints); ~ is expanded

    @field_validator("worktree_root")
    @classmethod
    def _root(cls, v: str | None) -> str | None:
        if v is not None and (not v.strip() or ".." in Path(v).parts or "\n" in v):
            raise ValueError("worktree_root is a directory path without '..'")
        return v


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


def deny_list(t: Task) -> list[str]:
    return list(DEFAULT_DENY) + [d for d in t.deny if d not in DEFAULT_DENY]


def task_sha(t: Task) -> str:
    """S1: the hash of a task's definition as the dispatcher read it, recorded when it starts."""
    return hashlib.sha256(json.dumps(t.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def path(root: Path, sid: str) -> Path:
    return root / DIR / f"{sid}.toml"


def ledger_path(root: Path, sid: str) -> Path:
    return root / DIR / f"{sid}.jsonl"


def log_rel(sid: str, tid: str) -> str:
    """STW-052: where a task's output goes (git-ignored; never in a published export)."""
    return f"{WORK}/{sid}/{tid}.log"


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


def window_state(sf: SprintFile, now: dt.datetime | None = None) -> str:
    """S11: `not open`, `open` or `ended`."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now < sf.sprint.window.start:
        return "not open"
    return "open" if now < sf.sprint.window.end else "ended"


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


def plan(evs: list[dict[str, Any]]) -> list[str] | None:
    """The sprint's tasks: those it opened with plus those added by `steward sprint add` (S6); None before it opens."""
    opened = next((e for e in evs if e.get("kind") == "opened"), None)
    if opened is None:
        return None
    ids = list(opened.get("tasks") or [])
    ids += [e["task"] for e in evs if e.get("kind") == "added" and e.get("task") not in ids]
    return ids


STATE_KEYS = ("state", "run", "branch", "checks", "note", "worktree", "commit", "log", "run_log", "agent", "model",
              "task_sha256", "base", "base_commit", "uncommitted")


def states(sf: SprintFile, evs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Task -> {state, orders, run, branch, checks, note, times, …}, folded from the ledger."""
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
            if e.get("state") == "running":  # a new attempt: the last one's results no longer describe the task
                for k in ("checks", "note", "commit", "uncommitted", "ended"):
                    out[t].pop(k, None)
                out[t]["started"] = e.get("time")
            elif e.get("state") in ("done", "failed"):
                out[t]["ended"] = e.get("time")
            out[t].update({k: v for k, v in e.items() if k in STATE_KEYS})
    planned = plan(evs)
    if planned is not None:  # S6: a task in the file that the sprint never opened with, nor added, waits for `add`
        for tid, s in out.items():
            if tid not in planned and s["state"] == "planned":
                s["state"], s["note"] = "proposed", f"not in the sprint's plan; steward sprint add {sf.sprint.id} {tid}"
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


# ---------------------------------------------------------------- adapters (SP3; STW-051)
def permission_summary(t: Task) -> str:
    """One line for the sprint brief: what a task's agent may do."""
    if t.agent == "shell":
        return "shell: the task's own command, with the permissions of the user who runs the sprint"
    parts = [f"{t.agent}, {t.permissions}"]
    if t.agent == "codex" and t.permissions == "edit":
        parts.append("Codex's workspace-write sandbox also runs commands, so edit and edit-and-run are the same there")
    if t.agent == "codex" and t.permissions != "read-only":
        parts.append("committed by the sprint after Codex exits")
    parts.append("network " + ("on" if "network" in t.requires else "off"))
    if t.allow:
        parts.append("also allowed: " + ", ".join(t.allow))
    extra = [d for d in t.deny if d not in DEFAULT_DENY]
    if t.agent == "codex":  # W12b (F9): Codex takes no list of commands; its sandbox is the limit
        parts.append("the default deny list" + (" and " + ", ".join(extra) if extra else "")
                     + " is asked in its prompt, not enforced: Codex's sandbox enforces only "
                     + ("its read-only files" if t.permissions == "read-only" else "a read-only .git")
                     + (" and the network being off" if "network" not in t.requires else
                        "; with network on, publishing commands (npm publish, twine upload, gh release) are not blocked"))
        return "; ".join(parts)
    parts.append("denied: the default list" + (" and " + ", ".join(extra) if extra else ""))
    return "; ".join(parts)


def agent_prompt(t: Task, sf: SprintFile) -> str:
    lines = [f"Sprint {sf.sprint.id}, task {t.id}: {t.title}."]
    if t.ref:
        lines.append(f"It answers {t.ref}; read it first.")
    if t.prompt:
        lines.append(t.prompt)
    lines.append("The task is done only when these commands all exit 0 in this worktree: " + "; ".join(t.done) + ".")
    lines.append(f"You run with the permissions `{t.permissions}`: {PERMISSION_TEXT[t.permissions]}."
                 + (" You may also run: " + ", ".join(t.allow) + "." if t.allow else ""))
    lines.append("These commands are refused: " + ", ".join(deny_list(t)) + ".")
    if t.permissions == "read-only":
        lines.append("Report what you found in your output.")
    elif t.agent == "codex":
        lines.append("Do not commit: your sandbox cannot write .git. When you exit, the sprint commits every change in "
                     "this worktree to its branch.")
    else:
        lines.append("Commit your work on this branch.")
    lines.append("Never merge, push, sign an approval or edit the sprint file.")
    return "\n".join(lines)


def _bash(prefixes) -> list[str]:
    out: list[str] = []
    for p in prefixes:
        out += [f"Bash({p})", f"Bash({p} *)"]
    return out


def claude_argv(t: Task, prompt: str) -> list[str]:
    """Claude Code, headless: tools that need approval are denied unless listed, so the permissions become lists.
    Its event stream (stream-json) goes to the task log, where `sprint status` reads the last tool step."""
    allowed = ["Read", "Glob", "Grep", *_bash(GIT_READ)]
    disallowed: list[str] = []
    if t.permissions == "read-only":
        disallowed += ["Edit", "Write", "NotebookEdit"]
    else:
        allowed += ["Edit", "Write", "NotebookEdit", *_bash(GIT_COMMIT)]
    if t.permissions == "edit-and-run":
        allowed.append("Bash")
    if "network" in t.requires:
        allowed += ["WebFetch", "WebSearch"]
    else:
        disallowed += ["WebFetch", "WebSearch"]
    allowed += _bash(" ".join(a.split()) for a in t.allow)  # W12b (F8): one space between words, as denied
    disallowed += _bash(deny_list(t))  # a denied tool stays denied, also when a broader rule allows it
    argv = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--permission-mode", "default" if t.permissions == "read-only" else "acceptEdits",
            "--allowedTools", *allowed, "--disallowedTools", *disallowed]
    return argv + (["--model", t.model] if t.model else [])


def codex_argv(t: Task, sf: SprintFile, prompt: str) -> list[str]:
    """Codex: its sandbox carries the permissions (it has no list of commands); its JSON events go to the task log.
    S4: the sandbox cannot write .git, so a writing task's work is committed after Codex exits."""
    argv = ["codex", "exec", "-s", "read-only" if t.permissions == "read-only" else "workspace-write",
            "--skip-git-repo-check", "--json"]
    if "network" in t.requires:
        argv += ["-c", "sandbox_workspace_write.network_access=true"]
    argv += (["-m", t.model] if t.model else []) + [prompt]
    if t.permissions == "read-only":
        return argv
    msg = f"{t.title} (sprint {sf.sprint.id}, {t.id}; written by Codex, committed by the sprint task)"
    return ["/bin/sh", "-c", COMMIT_STEP, "steward-sprint-commit", msg, *argv]


def agy_settings(t: Task) -> dict[str, Any]:
    """Antigravity, headless, denies every command not allowed beforehand: a session-only allow and deny list."""
    from .dispatch import READ_ONLY

    allow = list(READ_COMMANDS)
    if t.permissions != "read-only":
        allow += list(GIT_COMMIT)
    if t.permissions == "edit-and-run":  # W12b (F8), W12c (N1): only what an allow entry may name
        allow += [c for c in READ_ONLY if c not in RUN_EXCLUDED and allow_refusal(c) is None and c not in allow]
    allow += [c for c in (" ".join(a.split()) for a in t.allow) if c not in allow]
    return {"permissions": {"allow": [f"command({c})" for c in allow],
                            "deny": [f"command({c})" for c in deny_list(t)]}}


def agy_argv(t: Task, prompt: str, settings: Path | None) -> list[str]:
    from .dispatch import agy_path

    argv = [agy_path() or "agy", "-p", prompt, "--model", t.model or "gemini-4-neon-high", "--sandbox"]
    return argv + (["--settings", str(settings)] if settings else [])


def settings_rel(sid: str, tid: str) -> str:
    return f"{WORK}/{sid}/{tid}.agy-settings.json"


def command(t: Task, sf: SprintFile, settings: Path | None = None) -> list[str]:
    if t.agent == "shell":
        return ["/bin/sh", "-c", t.command or "true"]
    prompt = agent_prompt(t, sf)
    if t.agent == "claude-code":
        return claude_argv(t, prompt)
    if t.agent == "antigravity":
        return agy_argv(t, prompt, settings)
    return codex_argv(t, sf, prompt)


# ---------------------------------------------------------------- the last tool step in a task log (STW-052)
def _one_line(s: Any, limit: int = 200) -> str:
    text = str(s).splitlines()[0] if str(s).strip() else ""
    text = "".join(ch if ch.isprintable() else " " for ch in text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _claude_step(ev: dict[str, Any]) -> dict[str, str] | None:
    if ev.get("type") != "assistant":
        return None
    content = (ev.get("message") or {}).get("content")
    steps = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"] if isinstance(content, list) else []
    if not steps:
        return None
    use = steps[-1]
    args = use.get("input") if isinstance(use.get("input"), dict) else {}
    what = next((args[k] for k in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query")
                 if isinstance(args.get(k), str)), "")  # never `content`, `new_string` or other file text
    return {"tool": _one_line(use.get("name") or "tool", 80), "command": _one_line(what)}


def _codex_step(ev: dict[str, Any]) -> dict[str, str] | None:
    item = ev.get("item") if isinstance(ev.get("item"), dict) else None
    if item and ev.get("type") in ("item.started", "item.completed"):
        kind = item.get("type")
        if kind == "command_execution":
            return {"tool": "shell", "command": _one_line(item.get("command") or "")}
        if kind == "file_change":
            paths = [c.get("path") for c in item.get("changes") or [] if isinstance(c, dict) and c.get("path")]
            return {"tool": "file_change", "command": _one_line(", ".join(map(str, paths)))}
        if kind == "mcp_tool_call":
            return {"tool": _one_line(item.get("tool") or "mcp", 80), "command": _one_line(item.get("server") or "")}
        if kind == "web_search":
            return {"tool": "web_search", "command": _one_line(item.get("query") or "")}
        return None
    msg = ev.get("msg") if isinstance(ev.get("msg"), dict) else None  # the older event format
    if msg and msg.get("type") == "exec_command_begin":
        cmd = msg.get("command")
        return {"tool": "shell", "command": _one_line(" ".join(map(str, cmd)) if isinstance(cmd, list) else cmd or "")}
    if msg and msg.get("type") == "patch_apply_begin":
        changes = msg.get("changes")
        return {"tool": "apply_patch", "command": _one_line(", ".join(changes) if isinstance(changes, dict) else "")}
    return None


def last_step(log: Path) -> dict[str, str] | None:
    """The last tool step in a task log: the tool's name and its command or path on one line, never a file's text."""
    try:
        if log.is_symlink() or not log.is_file():
            return None
        with open(log, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - LOG_TAIL))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            step = _claude_step(ev) or _codex_step(ev)
            if step:
                return step
    return None


# ---------------------------------------------------------------- git: base, worktrees, branches
def base_ref(root: Path, sf: SprintFile) -> str:
    """S9: the branch the sprint's work starts from and merges into: `[sprint] base`, else the checkout's branch."""
    from .fsutil import git_run

    if sf.sprint.base:
        return sf.sprint.base
    r = git_run(root, "symbolic-ref", "--short", "HEAD", text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "HEAD"


def worktree_dir(root: Path, sf: SprintFile, tid: str) -> Path:
    """S8: `[sprint] worktree_root` (relative to the repository, or absolute, ~ expanded); default .steward/sprints."""
    wr = sf.sprint.worktree_root
    if not wr:
        return root / WORK / sf.sprint.id / tid
    base = Path(os.path.expanduser(wr))
    return (base if base.is_absolute() else root / base) / sf.sprint.id / tid


def shown(root: Path, sf: SprintFile, wt: Path) -> str:
    """A worktree as the ledger records it: relative to the repository, or under the configured root as written."""
    if wt == root:
        return "."
    if wt.is_relative_to(root):
        return wt.relative_to(root).as_posix()
    return f"{sf.sprint.worktree_root.rstrip('/')}/{wt.parent.name}/{wt.name}" if sf.sprint.worktree_root else wt.name


def _rev(root: Path, ref: str) -> str | None:
    from .fsutil import git_run

    r = git_run(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


class WorktreeSetupError(RuntimeError):
    """Git could not create the supervisor's task worktree."""


def _parents_beneath(root: Path, sf: SprintFile, wt: Path) -> None:
    """W12b (F9): make a worktree's parent folders one at a time without following a link, from the repository (the
    default) or from the configured `worktree_root` (trusted as given, as the human wrote it)."""
    from .fsutil import LinkRefused, open_dir_beneath

    if wt.parent.is_relative_to(root):
        base, parts = root, wt.parent.relative_to(root).parts
    else:
        base, parts = wt.parent.parent, (wt.parent.name,)  # <worktree_root>/<sprint id>
        if not base.is_dir():
            base.mkdir(parents=True, exist_ok=True)
    try:
        os.close(open_dir_beneath(base, parts, create=True))
    except LinkRefused as e:
        raise RuntimeError(f"the folder of {shown(root, sf, wt)} is reached through a link or is not a folder "
                           f"({e.strerror or e}); remove the link") from None


def _worktree(root: Path, sf: SprintFile, t: Task) -> tuple[Path, str, str | None]:
    """(worktree, branch, the commit its work starts from)."""
    from .fsutil import git_run

    sid = sf.sprint.id
    branch = f"sprint/{sid}/{t.id}"
    wt = worktree_dir(root, sf, t.id)
    base = base_ref(root, sf)
    if wt.is_symlink():
        raise RuntimeError(f"{shown(root, sf, wt)} is a link; remove it")
    _parents_beneath(root, sf, wt)  # W12b (F9): no linked folder on the way to it, also for a reused worktree
    if wt.exists():  # V11 (0.13.0): reused only when it is that task's own worktree on its own branch
        top = git_run(wt, "rev-parse", "--show-toplevel", text=True)
        head = git_run(wt, "symbolic-ref", "--short", "HEAD", text=True)
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(wt) or \
                head.returncode != 0 or head.stdout.strip() != branch:
            raise RuntimeError(f"{shown(root, sf, wt)} exists but is not the worktree of {branch}; remove it")
        mb = git_run(root, "merge-base", base, branch, text=True)
        return wt, branch, (mb.stdout.strip() if mb.returncode == 0 else None)
    exists =git_run(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    start = sf.sprint.base  # unset: the checkout's HEAD, as before 0.21.0
    if exists:
        args = ["worktree", "add", str(wt), branch]
    else:
        args = ["worktree", "add", "-b", branch, str(wt)] + ([start] if start else [])
    out = git_run(root, *args, text=True)
    if out.returncode != 0:
        raise WorktreeSetupError(f"cannot create the worktree for {t.id}: {out.stderr.strip()[:200]}")
    if exists:
        mb = git_run(root, "merge-base", base, branch, text=True)
        return wt, branch, (mb.stdout.strip() if mb.returncode == 0 else None)
    return wt, branch, _rev(root, start or "HEAD")


def sprint_env(sf: SprintFile, t: Task, branch: str, base: str) -> dict[str, str]:
    """S9: what a done command (and the task's command) may use instead of naming the base branch."""
    return {"STEWARD_SPRINT_ID": sf.sprint.id, "STEWARD_SPRINT_TASK": t.id, "STEWARD_SPRINT_BRANCH": branch,
            "STEWARD_SPRINT_BASE": base}


def commits(root: Path, base: str | None, branch: str | None) -> list[dict[str, str]]:
    """The commits on a task's branch since the commit its work started from, oldest first."""
    from .fsutil import git_run

    if not branch or not base or _rev(root, f"refs/heads/{branch}") is None:
        return []
    r = git_run(root, "log", "--reverse", "--format=%H%x09%s", f"{base}..refs/heads/{branch}", text=True)
    if r.returncode != 0:
        return []
    return [{"commit": h, "subject": _one_line(s)} for h, _, s in (ln.partition("\t") for ln in r.stdout.splitlines()) if h]


def changed_files(root: Path, base: str | None, branch: str | None) -> list[str]:
    from .fsutil import git_run

    if not branch or not base or _rev(root, f"refs/heads/{branch}") is None:
        return []
    r = git_run(root, "diff", "--name-only", f"{base}..refs/heads/{branch}", text=True)
    return [ln for ln in r.stdout.splitlines() if ln] if r.returncode == 0 else []


def _start_of(root: Path, sf: SprintFile, s: dict[str, Any]) -> str | None:
    """The commit a task's work started from: recorded when it ran, else where its branch left the base."""
    from .fsutil import git_run

    if s.get("base_commit"):
        return s["base_commit"]
    branch = s.get("branch")
    if not branch or _rev(root, f"refs/heads/{branch}") is None:
        return None
    mb = git_run(root, "merge-base", base_ref(root, sf), f"refs/heads/{branch}", text=True)
    return mb.stdout.strip() if mb.returncode == 0 and mb.stdout.strip() else None


def merge_state(root: Path, sf: SprintFile, s: dict[str, Any]) -> tuple[str, str | None]:
    """S13: ("merged", the branch tip) when the whole branch is in the base; ("checked merged", commit) when the checked
    commit is but later commits are not; ("waiting", None) otherwise. Read from git, never from the ledger alone."""
    from .fsutil import git_run

    base = base_ref(root, sf)
    tip = _rev(root, f"refs/heads/{s['branch']}") if s.get("branch") else None

    def inside(c: str | None) -> bool:
        return bool(c) and git_run(root, "merge-base", "--is-ancestor", c, base).returncode == 0

    if tip and inside(tip):
        return "merged", tip
    if inside(s.get("commit")):
        return "checked merged", s["commit"]
    return "waiting", None


# ---------------------------------------------------------------- the dispatcher
def _checks(cwd: Path, t: Task, cancelled, deadline: dt.datetime, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Each done command, polled: a stop or the end of the window ends it (V13). An unfinished command has exit None."""
    res = []
    for c in t.done:
        if cancelled() or dt.datetime.now(dt.timezone.utc) >= deadline:
            res.append({"command": c, "exit": None, "note": "not run: stopped or the window ended"})
            continue
        proc = subprocess.Popen(c, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, env={**os.environ, **(env or {})})
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


def _clean_commit(wt: Path) -> tuple[bool, str | None, list[str]]:
    """(no uncommitted changes, HEAD commit, the `git status --porcelain` lines) of a task's worktree (V11; S14)."""
    from .fsutil import git_run

    st = git_run(wt, "status", "--porcelain", text=True)
    head = git_run(wt, "rev-parse", "HEAD", text=True)
    lines = [ln for ln in st.stdout.splitlines() if ln.strip()] if st.returncode == 0 else []
    return (st.returncode == 0 and not lines), (head.stdout.strip() if head.returncode == 0 else None), lines


def _verdict(checks: list[dict[str, Any]], clean: bool, lines: list[str]) -> tuple[bool, str | None]:
    ok = all(c["exit"] == 0 for c in checks) and clean
    if ok:
        return True, None
    if clean:
        return False, "an acceptance command did not pass"
    shown_ = ", ".join(_one_line(ln, 120) for ln in lines[:10]) + (f" (and {len(lines) - 10} more)" if len(lines) > 10 else "")
    return False, f"uncommitted changes in its worktree: {shown_}"  # S14: the paths, at the moment it was seen


def _open_log(root: Path, rel: str) -> int:
    """The task log, appended to, never through a link: its folders are opened one at a time beneath the repository
    (W12b, F9), and the file itself with O_NOFOLLOW."""
    from pathlib import PurePosixPath

    from .fsutil import open_dir_beneath

    parts = PurePosixPath(rel).parts
    dfd = open_dir_beneath(root, parts[:-1], create=True)
    try:
        return os.open(parts[-1], os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                       | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=dfd)
    finally:
        os.close(dfd)


def dispatch(root: Path, cfg: Any, sf: SprintFile, *, watch: bool = False, poll: float = 5.0,
             now=lambda: dt.datetime.now(dt.timezone.utc), out=print,
             on_fault: Callable[[Exception], None] | None = None) -> int:
    """Run the sprint until no task can progress (or, with `watch`, until the window ends, every task is finished,
    or `sprint stop`)."""
    from .fsutil import owner_lock, release_owner_lock

    sid = sf.sprint.id
    lock = owner_lock(root, f"sprint-{sid}")  # V12 (0.13.0): one dispatcher per sprint
    if lock is None:
        out(f"steward: another dispatcher is running sprint {sid} (or its lock cannot be made); nothing was started")
        return 75
    try:
        return _dispatch(root, cfg, sf, watch, poll, now, out, on_fault)
    finally:
        release_owner_lock(root, f"sprint-{sid}", lock)


class _Source:
    """S1: the sprint file, read again before each dispatch. A change is said and recorded; an invalid file is kept
    out (the dispatcher goes on with the version it last read).

    W12b (F7): an agent can write files outside its worktree (Claude Code's Edit and Write are not limited to it), so
    the file is read again only while no task runs, or on the human's order (`steward sprint reload`, an order in the
    ledger). A change made while a task ran is not used until that order. A running task keeps the definition it
    started with; a change to it is recorded as refused and never run."""

    def __init__(self, root: Path, sf: SprintFile, lg, out):
        self.root, self.p, self.sf, self.lg, self.out = root, path(root, sf.sprint.id), sf, lg, out
        self.sha = self._sha()
        self.held: str | None = None  # the hash of a version that changed while a task ran, waiting for an order
        self.seen_order = max((e.get("seq", 0) for e in events(root, sf.sprint.id) if _is_reload(e)), default=-1)

    def _sha(self) -> str | None:
        try:
            return hashlib.sha256(self.p.read_bytes()).hexdigest()
        except OSError:
            return None

    def _ordered(self) -> bool:
        orders = [e for e in events(self.root, self.sf.sprint.id) if _is_reload(e) and e.get("seq", 0) > self.seen_order]
        if orders:
            self.seen_order = max(e.get("seq", 0) for e in orders)
        return bool(orders)

    def refresh(self, running: dict[str, Task] | None = None) -> SprintFile:
        running = running or {}
        ordered = self._ordered()
        sha = self._sha()
        if sha is None:  # W12c (N3a): a file that cannot be read is never recorded as valid
            if ordered:
                self.lg.append("reloaded", {"sha256": None, "valid": False, "by": "human",
                                            "note": "the file could not be read"})
                self.out("the sprint file could not be read; going on with the version read before")
            return self.sf
        if sha == self.sha:
            if ordered:  # W12c (N3a): an edit held and then reverted no longer waits; the order settles it
                self.held = None
                self.lg.append("reloaded", {"sha256": sha, "valid": True, "by": "human", "changed": [], "new": [],
                                            "removed": [], "note": "the file had not changed"})
            return self.sf
        if not ordered and (running or self.held):
            if sha != self.held:
                self.held = sha
                self.lg.append("reloaded", {"sha256": sha, "valid": False, "held": True,
                                            "running": sorted(running),
                                            "note": "changed while a task ran; not used until a human orders a reload"})
                self.out(f"the sprint file changed while {', '.join(sorted(running)) or 'a task'} ran; it is not used "
                         f"until you order it: steward sprint reload {self.sf.sprint.id}")
            return self.sf
        self.sha, self.held = sha, None
        new, err = validate_file(self.p)
        if new is not None and new.sprint.id != self.sf.sprint.id:
            new, err = None, f"it declares sprint {new.sprint.id!r}"
        by = {"by": "human"} if ordered else {}
        if new is None:
            self.lg.append("reloaded", {"sha256": sha, "valid": False, "note": err, **by})
            self.out(f"the sprint file changed but is not valid ({err}); going on with the version read before")
            return self.sf
        old = {t.id: task_sha(t) for t in self.sf.task}
        cur = {t.id: task_sha(t) for t in new.task}
        changed = sorted(i for i in cur if i in old and cur[i] != old[i])
        added, removed = sorted(set(cur) - set(old)), sorted(set(old) - set(cur))
        refused = sorted(i for i, t in running.items() if cur.get(i) != task_sha(t))  # never run while it runs
        self.lg.append("reloaded", {"sha256": sha, "valid": True, "changed": changed, "new": added, "removed": removed,
                                    **by, **({"refused": refused} if refused else {})})
        what = "; ".join(x for x in (f"changed {', '.join(changed)}" if changed else "",
                                     f"new {', '.join(added)}" if added else "",
                                     f"removed {', '.join(removed)}" if removed else "") if x) or "no task changed"
        self.out(f"the sprint file changed ({what}); the dispatcher uses it from now on"
                 + (f"; {', '.join(refused)} keep{'s' if len(refused) == 1 else ''} the definition "
                    f"{'it' if len(refused) == 1 else 'they'} started with (the change is refused while it runs)"
                    if refused else ""))
        self.sf = new
        return new


def _is_reload(e: dict[str, Any]) -> bool:
    return e.get("kind") == "order" and e.get("order") == "reload" and e.get("by") == "human"


def _dispatch(root: Path, cfg: Any, sf: SprintFile, watch: bool, poll: float, now, out, on_fault) -> int:
    sid = sf.sprint.id
    lg = led(root, sid, cfg.steward.repo_id)
    source = _Source(root, sf, lg, out)
    run_cfg = getattr(cfg, "run", None)
    run_logs = (getattr(run_cfg, "logs", None) or ".steward/runs").rstrip("/")
    running: dict[str, tuple[subprocess.Popen, Path, str, Task, str]] = {}
    if not any(e.get("kind") == "opened" for e in events(root, sid)):
        lg.append("opened", {"sprint": sid, "tasks": order(sf), "dispatch": sf.sprint.dispatch})
    for tid, s in states(sf, events(root, sid)).items():  # V12: work an ended dispatcher left unfinished
        if s["state"] in ("running", "checking"):
            lg.append("state", {"task": tid, "state": "failed", "branch": s.get("branch"),
                                "note": "its dispatcher ended before it finished (see the run ledger); retry with go --retry"})
            out(f"{tid}: failed (left unfinished by an earlier dispatcher)")
    told: set[str] = set()
    while True:
        sf = source.refresh({tid: r[3] for tid, r in running.items()})
        tasks = {t.id: t for t in sf.task}
        evs = events(root, sid)
        st = states(sf, evs)
        stop = stopped(evs)
        if stop and stop.get("now"):
            for tid, (proc, *_rest) in running.items():
                proc.terminate()  # `steward run` stops its job, records it, and exits
        # finished runs: the acceptance commands decide
        for tid, (proc, wt, branch, started_as, base) in list(running.items()):
            if proc.poll() is None:
                continue
            del running[tid]
            t = started_as  # W12b (F7): the definition it started with decides, whatever the file says now
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
            checks = _checks(wt, t, lambda: bool(stopped(events(root, sid))), sf.sprint.window.end,
                             sprint_env(sf, t, branch, base))
            clean, commit, lines = _clean_commit(wt) if wt != root else (True, None, [])
            ok, note = _verdict(checks, clean, lines)
            lg.append("state", {"task": tid, "state": "done" if ok else "failed", "checks": checks, "branch": branch,
                                "commit": commit, "note": note, **({"uncommitted": lines[:50]} if lines else {})})
            n = sum(c["exit"] == 0 for c in checks)
            out(f"{tid}: done ({n} of {len(checks)} checks passed); branch {branch} waits for your merge" if ok else
                f"{tid}: failed ({n} of {len(checks)} checks passed" + (")" if clean else f"; {note})"))
        st = states(sf, events(root, sid))
        planned = plan(events(root, sid)) or order(sf)
        for tid in order(sf):
            if tid not in planned and tid not in told:
                told.add(tid)
                out(f"{tid} is in the sprint file but not in the sprint; record it with: steward sprint add {sid} {tid}")
        t_now = now()
        in_window = sf.sprint.window.start <= t_now < sf.sprint.window.end
        if not stop and in_window:
            for tid in order(sf):
                if len(running) >= sf.sprint.max_parallel:
                    break
                s, t = st[tid], tasks[tid]
                if s["state"] != "ready" or s.get("hold") or tid in running or tid not in planned:
                    continue
                if sf.sprint.dispatch == "order" and not s.get("go"):
                    continue
                if t_now + dt.timedelta(minutes=t.limits.wall_minutes) > sf.sprint.window.end:
                    continue  # it would not finish before the window ends
                try:
                    wt, branch, base_commit = _worktree(root, sf, t) if t.worktree else (root, "(no worktree)", None)
                except RuntimeError as e:
                    if on_fault is not None and isinstance(e, WorktreeSetupError):
                        on_fault(e)
                    lg.append("state", {"task": tid, "state": "failed", "note": str(e)})
                    out(f"{tid}: failed ({e})")
                    continue
                if now() + dt.timedelta(minutes=t.limits.wall_minutes) > sf.sprint.window.end or \
                        stopped(events(root, sid)):  # V13: the clock and stop read again after setup
                    continue
                try:
                    running[tid] = _launch(root, sf, t, wt, branch, base_commit, run_logs, lg, out)
                except OSError as e:  # W12b (F9): a task log or settings file reached through a link
                    lg.append("state", {"task": tid, "state": "failed", "branch": branch,
                                        "note": f"its log or settings could not be opened safely: {e}"})
                    out(f"{tid}: failed (its log or settings could not be opened safely: {e})")
        if running:
            time.sleep(min(poll, 0.5))
            continue
        st = states(sf, events(root, sid))
        waiting = [i for i, s in st.items() if s["state"] == "ready" and i in planned]
        t_now = now()
        if watch:  # S3: stay while the window is open and any task can still become ready (retry, recheck, order)
            if stop or t_now >= sf.sprint.window.end:
                break
            if not [i for i in planned if i in st and st[i]["state"] not in ("done", "skipped")]:
                break  # every task is finished
            if t_now < sf.sprint.window.start:
                time.sleep(min(poll, max(0.05, (sf.sprint.window.start - t_now).total_seconds())))
            else:
                time.sleep(poll)  # wait for an order, a release or the end, never spinning
            continue
        if stop or not waiting or t_now >= sf.sprint.window.end:
            break
        # V14 (0.14.0): what could start now: ordered (or auto), not held, and fitting before the window ends
        startable = [i for i in waiting if (st[i].get("go") or sf.sprint.dispatch == "auto") and not st[i].get("hold")
                     and t_now + dt.timedelta(minutes=tasks[i].limits.wall_minutes) <= sf.sprint.window.end]
        if t_now < sf.sprint.window.start:
            out(f"the window opens at {sf.sprint.window.start.isoformat()}; nothing was started "
                "(steward sprint start --watch waits for it)")
            break
        if not startable:
            ordered = [i for i in waiting if st[i].get("go") or sf.sprint.dispatch == "auto"]
            if not ordered and sf.sprint.dispatch == "order":
                out("waiting for orders: " + ", ".join(f"steward sprint go {sid} {i}" for i in waiting))
            elif ordered:
                out("nothing more can start now: " + ", ".join(
                    f"{i} ({'held' if st[i].get('hold') else 'would not finish before the window ends'})" for i in ordered))
            break
    return 0


def _launch(root: Path, sf: SprintFile, t: Task, wt: Path, branch: str, base_commit: str | None, run_logs: str,
            lg, out) -> tuple[subprocess.Popen, Path, str, Task, str]:
    from .fsutil import safe_write
    from .runner import new_run_id

    sid, tid = sf.sprint.id, t.id
    settings = None
    if t.agent == "antigravity":
        rel = settings_rel(sid, tid)
        safe_write(root, rel, (json.dumps(agy_settings(t), indent=1) + "\n").encode())
        settings = root / rel
    run_id = new_run_id()
    argv = [sys.executable, "-m", "steward.cli", "run", "--repo", str(root), "--run-id", run_id,
            "--label", f"sprint:{sid}:{tid}", "--wall", str(int(t.limits.wall_minutes * 60))]
    if t.limits.idle_minutes:
        argv += ["--hang-cpu", str(int(t.limits.idle_minutes * 60))]
    argv += ["--", *command(t, sf, settings)]
    base = base_ref(root, sf)
    lrel = log_rel(sid, tid)
    fd = _open_log(root, lrel)
    try:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        os.write(fd, f"--- {stamp} {tid} run {run_id} ({t.agent}) ---\n".encode())
        proc = subprocess.Popen(argv, cwd=wt, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                                env={**os.environ, **sprint_env(sf, t, branch, base)})
    finally:
        os.close(fd)
    lg.append("state", {"task": tid, "state": "running", "branch": branch, "agent": t.agent, "model": t.model,
                        "worktree": shown(root, sf, wt), "run": run_id, "run_log": f"{run_logs}/{run_id}.log",
                        "log": lrel, "task_sha256": task_sha(t), "base": base, "base_commit": base_commit,
                        "permissions": t.permissions})
    out(f"{tid}: running ({t.agent}{', ' + t.model if t.model else ''}) on {branch}; log {lrel}")
    return proc, wt, branch, t, base


def recheck(root: Path, cfg: Any, sf: SprintFile, tid: str, out=print) -> int:
    """S2: run a failed task's done commands on its branch's current head and record the result, by the human."""
    from .fsutil import git_run

    sid = sf.sprint.id
    t = next(x for x in sf.task if x.id == tid)
    s = states(sf, events(root, sid))[tid]
    if s["state"] != "failed":
        out(f"steward: {tid} is {s['state']}; recheck is for a failed task (its work is on its branch)")
        return 64
    if t.worktree:
        wt = worktree_dir(root, sf, tid)
        branch = f"sprint/{sid}/{tid}"
        top = git_run(wt, "rev-parse", "--show-toplevel", text=True) if wt.is_dir() and not wt.is_symlink() else None
        head = git_run(wt, "symbolic-ref", "--short", "HEAD", text=True) if top is not None else None
        if top is None or top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(wt) or \
                head is None or head.stdout.strip() != branch:
            out(f"steward: no worktree of {branch} at {shown(root, sf, wt)}; nothing to recheck")
            return 65
    else:
        wt, branch = root, "(no worktree)"
    lg = led(root, sid, cfg.steward.repo_id)
    lg.append("state", {"task": tid, "state": "checking", "branch": branch, "by": "human", "recheck": True})
    checks = _checks(wt, t, lambda: False, dt.datetime.max.replace(tzinfo=dt.timezone.utc),
                     sprint_env(sf, t, branch, base_ref(root, sf)))
    clean, commit, lines = _clean_commit(wt) if wt != root else (True, None, [])
    ok, note = _verdict(checks, clean, lines)
    lg.append("state", {"task": tid, "state": "done" if ok else "failed", "checks": checks, "branch": branch,
                        "commit": commit, "note": note, "by": "human", "recheck": True,
                        **({"uncommitted": lines[:50]} if lines else {})})
    n = sum(c["exit"] == 0 for c in checks)
    if ok:
        out(f"{tid}: done ({n} of {len(checks)} checks passed at {(commit or '?')[:12]}); "
            f"branch {branch} waits for your merge")
        return 0
    out(f"{tid}: failed ({n} of {len(checks)} checks passed" + (")" if clean else f"; {note})"))
    return 1


# ---------------------------------------------------------------- status and watch (STW-052)
def status_doc(root: Path, sf: SprintFile, now: dt.datetime | None = None) -> dict[str, Any]:
    st = states(sf, events(root, sf.sprint.id))
    tasks = {t.id: t for t in sf.task}
    rows = []
    for tid in order(sf):
        s, t = st[tid], tasks[tid]
        start = _start_of(root, sf, s)
        cs = commits(root, start, s.get("branch"))
        log = s.get("log")
        rows.append({
            "id": tid, "title": t.title, "state": s["state"], "ordered": s["go"], "held": s["hold"], "after": t.after,
            "branch": s.get("branch"), "run": s.get("run"), "commit": s.get("commit"), "checks": s.get("checks") or [],
            "note": s.get("note"), "limits": t.limits.model_dump(mode="json"),
            "agent": t.agent, "model": t.model, "permissions": None if t.agent == "shell" else t.permissions,
            "started": s.get("started"), "ended": s.get("ended"), "log": log, "run_log": s.get("run_log"),
            "commits": cs, "changed_files": changed_files(root, start, s.get("branch")),
            "last_commit_subject": cs[-1]["subject"] if cs else None,
            "last_step": last_step(root / log) if log else None,
            "uncommitted": s.get("uncommitted") or [],
        })
    return {"id": sf.sprint.id, "path": path(root, sf.sprint.id).relative_to(root).as_posix(),
            "window": sf.sprint.window.model_dump(mode="json"), "window_state": window_state(sf, now),
            "dispatch": sf.sprint.dispatch, "tasks": rows}


def _event_line(e: dict[str, Any]) -> str | None:
    k, t, when = e.get("kind"), e.get("task"), (e.get("time") or "")[11:19]
    if k == "opened":
        return f"{when} sprint opened: {', '.join(e.get('tasks') or [])}"
    if k == "order" and e.get("order") == "reload":
        return f"{when} reload ordered by the human"
    if k == "order":
        return f"{when} {t} order {e.get('order')}" + (" (retry)" if e.get("retry") else "") + \
            (f": {_one_line(e.get('reason'))}" if e.get("reason") else "")
    if k == "added":
        return f"{when} {t} added to the sprint"
    if k == "stop":
        return f"{when} stop" + (" now" if e.get("now") else "")
    if k == "reloaded":
        if e.get("held"):
            return f"{when} the sprint file changed while a task ran (not used until a reload order)"
        refused = e.get("refused") or []
        return (f"{when} the sprint file changed" + ("" if e.get("valid") else " (not valid; not used)")
                + (f"; refused for running {', '.join(map(str, refused))}" if refused else ""))
    if k != "state":
        return None
    s = e.get("state")
    if s == "running":
        return f"{when} {t} running ({e.get('agent')}) on {e.get('branch')}; log {e.get('log') or '-'}"
    if s == "checking":
        return f"{when} {t} checking" + (" (recheck)" if e.get("recheck") else "")
    checks = e.get("checks") or []
    parts = "; ".join(f"{_one_line(c.get('command'), 60)} -> {c.get('exit')}" for c in checks)
    line = f"{when} {t} {s}: {sum(c.get('exit') == 0 for c in checks)} of {len(checks)} checks passed"
    return line + (f" ({parts})" if parts else "") + (f"; {_one_line(e.get('note'))}" if e.get("note") else "")


def watch(root: Path, sid: str, *, poll: float = 2.0, out=print, once: bool = False) -> int:
    """One line per new event: ledger entries, new commits on a task's branch, a running task's last tool step.
    Ends when nothing runs and nothing ordered waits, when the sprint stops, or when its window ends. No model is
    called; everything comes from the ledger, git and the task logs."""
    seen_seq = -1
    seen_commits: set[str] = set()
    steps: dict[str, dict[str, str] | None] = {}
    sf = load(root, sid)
    while True:
        fresh, _ = validate_file(path(root, sid))
        sf = fresh if fresh is not None and fresh.sprint.id == sid else sf
        evs = events(root, sid)
        for e in evs:
            if e.get("seq", 0) > seen_seq:
                seen_seq = e.get("seq", 0)
                line = _event_line(e)
                if line:
                    out(line)
        st = states(sf, evs)
        for tid in order(sf):
            s = st[tid]
            for c in commits(root, _start_of(root, sf, s), s.get("branch")):
                if c["commit"] not in seen_commits:
                    seen_commits.add(c["commit"])
                    out(f"{tid} commit {c['commit'][:12]} {c['subject']}")
            if s["state"] == "running" and s.get("log"):
                step = last_step(root / s["log"])
                if step and step != steps.get(tid):
                    steps[tid] = step
                    out(f"{tid} step {step['tool']}: {step['command']}")
        busy = [i for i, s in st.items() if s["state"] in ("running", "checking")]
        ordered = [i for i, s in st.items() if s["state"] in ("planned", "ready") and not s.get("hold")
                   and (s.get("go") or sf.sprint.dispatch == "auto")]
        ended = stopped(evs) is not None or window_state(sf) == "ended"
        if once or (not busy and (not ordered or ended)):
            return 0
        time.sleep(poll)


# ---------------------------------------------------------------- signatures, report, plan
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


def warnings(sf: SprintFile) -> list[str]:
    """STW-051: plans that cannot work as written."""
    out = []
    for t in sf.task:
        if t.agent != "shell" and t.permissions == "read-only" and t.worktree:
            out.append(f"{t.id} is read-only: its agent cannot change the branch, so its done commands check the "
                       "branch as it starts")
    return out


def report(root: Path, sf: SprintFile) -> str:
    evs = events(root, sf.sprint.id)
    st = states(sf, evs)
    lines = [f"# Sprint {sf.sprint.id}", "",
             f"- Window: {sf.sprint.window.start.isoformat()} – {sf.sprint.window.end.isoformat()}",
             f"- Dispatch: {sf.sprint.dispatch}; at most {sf.sprint.max_parallel} at once", "",
             "| Task | Agent | State | Checks | Branch | Checked commit | Merged |", "|---|---|---|---|---|---|---|"]
    tasks = {t.id: t for t in sf.task}
    merged: dict[str, tuple[str, str | None]] = {}
    for tid in order(sf):
        s = st[tid]
        checks = s.get("checks") or []
        if s["state"] == "done":
            merged[tid] = merge_state(root, sf, s)
        m = merged.get(tid, ("", None))
        mtext = {"merged": f"yes @ {(m[1] or '')[:12]}", "checked merged": f"checked commit only @ {(m[1] or '')[:12]}",
                 "waiting": "no"}.get(m[0], "—")
        lines.append(f"| {tid} | {tasks[tid].agent} | {s['state']} | "
                     f"{sum(c.get('exit') == 0 for c in checks)}/{len(checks)} | {s.get('branch') or '—'} | "
                     f"{(s.get('commit') or '—')[:12]} | {mtext} |")
    waiting = [t for t in order(sf) if st[t]["state"] == "done" and merged[t][0] != "merged"]
    lines += ["", "Done is decided by each task's commands, never by the agent. "
              + (f"Branches waiting for your merge (merge the checked commit): "
                 f"{', '.join(st[t]['branch'] + ' @ ' + (st[t].get('commit') or '?')[:12] for t in waiting)}." if waiting
                 else "")]
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
                'permissions = "edit-and-run"   # read-only | edit | edit-and-run; push, merge, tag … stay denied',
                "limits = { wall_minutes = 90, idle_minutes = 15 }",
                'done = ["python -m pytest -q", "steward check --gate default"]', "needs = []"]
    return "\n".join(out) + "\n"


def _q(s: str) -> str:
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
              "failed": {"running", "failed", "checking"}, "done": set()}  # failed -> checking: S2 recheck


def ledger_findings(sf: SprintFile, evs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """V15 (0.14.0): the ledger belongs to this sprint's plan, and each task's states follow the dispatcher's order."""
    out: list[dict[str, Any]] = []
    opened = [e for e in evs if e.get("kind") == "opened"]
    first_open = next((i for i, e in enumerate(evs) if e.get("kind") == "opened"), None)
    early = [e for i, e in enumerate(evs) if e.get("kind") in ("state", "added") and (first_open is None or i < first_open)]
    if early:  # V15 (0.15.0, 0.17.0): every state follows the sprint's opened record
        out.append({"code": "R-71.not_opened", "message": f"{len(early)} task state(s) before the sprint's opened record"})
    if opened and opened[0].get("sprint") != sf.sprint.id:
        out.append({"code": "R-71.foreign_ledger", "message": f"opened for sprint {opened[0].get('sprint')!r}"})
    planned = plan(evs)  # S6: the tasks it opened with and those added since, by the human
    if opened and sorted(planned or []) != sorted(t.id for t in sf.task):
        out.append({"code": "R-71.plan_changed", "message": "the plan's tasks differ from those the sprint opened with"})
    bad_add = [e.get("task") for e in evs if e.get("kind") == "added" and e.get("by") != "human"]
    if bad_add:
        out.append({"code": "R-71.added_not_by_human", "value": ", ".join(map(str, bad_add))})
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
        if prev == "failed" and new == "checking" and not (e.get("recheck") and e.get("by") == "human"):
            out.append({"code": "R-71.bad_transition", "value": t, "message": f"{prev} → checking without a recheck"})
        last[t] = new
    return out
