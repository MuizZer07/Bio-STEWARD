"""Delegation (0.23.0, STW-061 D01): the installed agent CLIs, the endings that mean a worker cannot run, and the
local availability ledger.

- **Finding the agents.** `claude` (Claude Code), `codex` (Codex) and `agy` (Antigravity) are looked for on PATH and
  in the folders their installers use (for example `~/.gemini/bin/agy`). `probe` reads each one's version and whether
  it is signed in from its own local commands (`--version`, and a status subcommand only when the agent's `--help`
  lists it). No prompt is passed, so no model is called, and steward itself opens no connection.
- **"Cannot run".** One table per agent of the endings that mean the worker could not do the task at all: a usage or
  rate limit (with its reset time when the agent prints one), not signed in, not installed, or a sandbox that did not
  start. Everything else is a task failure, as before. Only the end of a log is read, and of a JSON-lines log only the
  error events (an agent's tool output can quote a limit message without being limited).
- **The availability ledger.** `.steward/agents/availability.jsonl`, hash-chained and local: what setup observed and
  what each run's ending said. `status` turns it into one state per agent: available, limited until a time, signed
  out, or missing.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LEDGER = ".steward/agents/availability.jsonl"
KINDS = ("limited", "signed_out", "missing", "sandbox")  # the endings that mean "cannot run"
STATES = ("available", "limited", "signed_out", "missing")
LOG_TAIL = 64 * 1024  # bytes of a log read for its ending
TEXT_TAIL = 30  # plain-text lines at the end of a log that may hold the ending
PROBE_TIMEOUT = 15  # seconds per local status command
UNKNOWN_RESET_HOLD = dt.timedelta(hours=1)  # a limit that printed no reset time counts this long (raised in S2-D01)


@dataclass(frozen=True)
class Agent:
    name: str
    executable: str
    folders: tuple[str, ...]  # install folders under the home directory, after PATH
    status: tuple[str, ...] | None  # the local sign-in status subcommand, or None when the agent has none
    default_model: str | None = None


AGENTS: dict[str, Agent] = {
    "claude-code": Agent("claude-code", "claude", (".local/bin", ".claude/local", ".npm-global/bin"), ("auth", "status")),
    "codex": Agent("codex", "codex", (".npm-global/bin", ".local/bin", ".codex/bin"), ("login", "status")),
    "antigravity": Agent("antigravity", "agy", (".gemini/bin", ".local/bin"), None, "gemini-4-neon-high"),
}
ORDER = tuple(AGENTS)  # the order setup proposes: claude-code first (the usual master), then the workers


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def locate(name: str) -> tuple[str | None, str | None]:
    """(the executable's path, where it was found: "PATH" or "known folder"), or (None, None). Nothing is run."""
    a = AGENTS[name]
    found = shutil.which(a.executable)
    if found:
        return found, "PATH"
    for folder in a.folders:
        p = _home() / folder / a.executable
        if p.is_file() and os.access(p, os.X_OK):
            return str(p), "known folder"
    return None, None


def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                              env={**os.environ, "NO_COLOR": "1", "CI": "1"})
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


VERSION = re.compile(r"\b(\d+\.\d+(?:\.\d+)?(?:[-+.][0-9A-Za-z.]+)?)\b")
SIGNED_OUT = re.compile(r"not (?:logged|signed) in|logged out|signed out|\"loggedIn\"\s*:\s*false|no credentials|"
                        r"please (?:log|sign) ?in|run [`']?\w+ login", re.I)


def probe(name: str) -> dict[str, Any]:
    """What the local commands say about one agent: installed, where, version, signed in (True, False or None when
    the agent has no status command or it could not be read). The status subcommand runs only when `--help` lists
    it, so an older CLI never receives it as a prompt."""
    a = AGENTS[name]
    path, where = locate(name)
    out: dict[str, Any] = {"agent": name, "executable": a.executable, "installed": path is not None, "found": where,
                           "path": path, "version": None, "signed_in": None}
    if path is None:
        return out
    r = _run([path, "--version"])
    if r is not None and r.returncode == 0:
        m = VERSION.search(r.stdout or r.stderr or "")
        out["version"] = m.group(1) if m else None
    if a.status is not None:
        h = _run([path, "--help"])
        listed = h is not None and re.search(rf"^\s+{re.escape(a.status[0])}\b", (h.stdout or "") + (h.stderr or ""), re.M)
        if listed:
            s = _run([path, *a.status])
            if s is not None:
                said = (s.stdout or "") + (s.stderr or "")
                out["signed_in"] = s.returncode == 0 and not SIGNED_OUT.search(said)
    return out


# ---------------------------------------------------------------- the endings that mean a worker cannot run
@dataclass(frozen=True)
class Ending:
    agent: str
    kind: str  # one of KINDS
    reset: str | None  # ISO 8601 UTC, when the agent printed when the limit resets
    message: str  # the line that matched, on one line, at most 200 characters

    def as_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "kind": self.kind, "reset": self.reset, "message": self.message}


_MISSING = [r"\b(?:{exe}): (?:command )?not found\b", r"No such file or directory: '?[^'\s]*\b{exe}'?",
            r"\b{exe}\b[^\n]{{0,40}} is not installed"]
_SANDBOX = [r"sandbox-exec: [^\n]*(?:Operation not permitted|failed|denied)", r"\bbwrap: [^\n]*(?:No permissions|"
            r"Operation not permitted|Creating new namespace failed|setting up uid map)",
            r"\bsandbox (?:failed to (?:start|initiali[sz]e)|could not be (?:started|created)|is not available)"]

# One table per agent: (kind, pattern). The first matching row of the newest candidate line wins.
ENDINGS: dict[str, list[tuple[str, str]]] = {
    "claude-code": [
        ("limited", r"You've hit your (?:[\w-]+ )*limit"),
        ("limited", r"Claude AI usage limit reached"),
        ("limited", r"\busage limit reached\b"),
        ("limited", r"^(?:rate_limit|billing_error)$"),  # the error code of Claude Code's API error message
        ("signed_out", r"^authentication_failed$"),
        ("signed_out", r"Invalid API key\b"),
        ("signed_out", r"Not logged in\b"),
        ("signed_out", r"Please run /login\b"),
        ("signed_out", r"OAuth token (?:has )?(?:expired|been revoked)"),
        ("signed_out", r"\bauthentication_error\b"),
    ],
    "codex": [
        ("limited", r"You've hit your usage limit"),
        ("limited", r"\busage_limit_reached\b"),
        ("limited", r"exceeded retry limit, last status: 429"),
        ("signed_out", r"\bNot logged in\b"),
        ("signed_out", r"access token could not be refreshed"),
        ("signed_out", r"\b401 Unauthorized\b"),
        ("signed_out", r"Please (?:run [`']?codex login[`']?|log ?in|sign in)"),
    ],
    "antigravity": [
        ("limited", r"You have exhausted your capacity on this model"),
        ("limited", r"Your quota will reset after"),
        ("limited", r"\bRESOURCE_EXHAUSTED\b"),
        ("limited", r"Quota exceeded for quota metric"),
        ("limited", r"\b429\b[^\n]{0,40}Too Many Requests"),
        ("signed_out", r"\bUNAUTHENTICATED\b"),
        ("signed_out", r"\bPlease (?:sign|log) ?in\b"),
        ("signed_out", r"\bnot (?:signed|logged) in\b"),
    ],
}


def _tables() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    out = {}
    for name, rows in ENDINGS.items():
        exe = re.escape(AGENTS[name].executable)
        full = rows + [("sandbox", p) for p in _SANDBOX] + [("missing", p.format(exe=exe)) for p in _MISSING]
        out[name] = [(kind, re.compile(p, re.I if kind in ("missing", "sandbox") else 0)) for kind, p in full]
    return out


_COMPILED = _tables()


def _one_line(text: str, limit: int = 200) -> str:
    s = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _texts(ev: dict[str, Any]) -> list[str]:
    """The error text an event carries; nothing from a tool's output or the agent's ordinary messages."""
    out: list[str] = []
    kind = ev.get("type")
    if kind == "result" and ev.get("is_error") and isinstance(ev.get("result"), str):  # Claude Code's last event
        out.append(ev["result"])
    if kind == "assistant" and (ev.get("error") or ev.get("isApiErrorMessage")):  # Claude Code's API error message
        if isinstance(ev.get("error"), str):  # its code first, so its words are read before it (newest first)
            out.append(ev["error"])
        content = (ev.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                out.append(c["text"])
    if kind == "error" and isinstance(ev.get("message"), str):  # codex exec --json
        out.append(ev["message"])
    if kind == "turn.failed" and isinstance(ev.get("error"), dict) and isinstance(ev["error"].get("message"), str):
        out.append(ev["error"]["message"])
    msg = ev.get("msg")
    if isinstance(msg, dict) and msg.get("type") in ("error", "stream_error") and isinstance(msg.get("message"), str):
        out.append(msg["message"])  # the older codex event format
    err = ev.get("error")
    if kind is None and isinstance(err, dict):  # a provider's error document
        out += [str(err[k]) for k in ("status", "message") if isinstance(err.get(k), (str, int))]
    return out


def _epoch_reset(ev: dict[str, Any]) -> str | None:
    q = ev.get("quotaLimits")
    if isinstance(q, dict) and q.get("status") == "rejected" and isinstance(q.get("resetsAt"), (int, float)):
        return _iso(dt.datetime.fromtimestamp(q["resetsAt"], dt.timezone.utc))
    return None


def candidates(text: str) -> list[tuple[str, str | None]]:
    """The lines at the end of a log that may hold its ending, newest first: each error event of a JSON-lines log
    (with the reset time it states as a number, if any), then the last plain-text lines."""
    found: list[tuple[str, str | None]] = []
    plain: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("{"):
            try:
                ev = json.loads(s)
            except ValueError:
                ev = None
            if isinstance(ev, dict):
                reset = _epoch_reset(ev)
                found += [(t, reset) for t in _texts(ev)]
                continue
        plain.append(s)
    found += [(s, None) for s in plain[-TEXT_TAIL:]]
    return list(reversed(found))


def ending(agent: str, text: str, now: dt.datetime | None = None, local: dt.tzinfo | None = None) -> Ending | None:
    """The "cannot run" ending of a task log or a dispatch output, or None (a task failure, or no failure). `now`
    and `local` (the machine's time zone) place a reset time the agent printed without a date or a zone."""
    if agent not in _COMPILED:
        raise ValueError(f"no endings table for {agent}")
    now = now or dt.datetime.now(dt.timezone.utc)
    for line, epoch in candidates(text):
        for kind, pat in _COMPILED[agent]:
            if pat.search(line):
                reset = epoch or (reset_time(line, now, local) if kind == "limited" else None)
                return Ending(agent, kind, reset, _one_line(line))
    return None


def read_ending(agent: str, log: Path, now: dt.datetime | None = None, local: dt.tzinfo | None = None) -> Ending | None:
    """`ending` of the last LOG_TAIL bytes of a log file; None for a file that is missing, a link, or unreadable."""
    try:
        if log.is_symlink() or not log.is_file():
            return None
        with open(log, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - LOG_TAIL))
            data = fh.read()
    except OSError:
        return None
    return ending(agent, data.decode("utf-8", errors="replace"), now, local)


# ---------------------------------------------------------------- reset times
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), start=1)}
_CLOCK = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)?"
_DATE = r"(?P<mon>[A-Za-z]{3})[a-z]*\.? (?P<day>\d{1,2})(?:st|nd|rd|th)?,?(?: (?P<year>\d{4}))?"
RESET_AT = [
    re.compile(rf"\bresets (?:{_DATE},? at )?{_CLOCK}(?:\s*\((?P<zone>[A-Za-z0-9_/+-]+)\))?", re.I),  # Claude Code
    re.compile(rf"\btry again at (?:{_DATE},? )?{_CLOCK}", re.I),  # Codex
]
RESET_IN = [
    re.compile(r"\btry again in (?P<dur>(?:\d+\s*(?:days?|hours?|hrs?|minutes?|mins?|seconds?|secs?)[\s,]*(?:and\s+)?)+)",
               re.I),
    re.compile(r"\breset after (?P<dur>(?:\d+\s*[dhms]\s*)+)", re.I),  # Gemini-based agents: 2h13m5s
]
_UNITS = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _duration(text: str) -> dt.timedelta | None:
    parts: dict[str, int] = {}
    for n, unit in re.findall(r"(\d+)\s*(days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|[dhms])(?![a-z])", text, re.I):
        key = _UNITS[unit[0].lower()]
        parts[key] = parts.get(key, 0) + int(n)
    return dt.timedelta(**parts) if parts else None


def reset_time(line: str, now: dt.datetime, local: dt.tzinfo | None = None) -> str | None:
    """The reset time a limit message prints, as ISO 8601 UTC, or None. A clock time with no date is its next
    occurrence after `now`; a date with no year is this year's, or next year's when this year's is half a year past."""
    for pat in RESET_IN:
        m = pat.search(line)
        if m and (d := _duration(m.group("dur"))):
            return _iso(now + d)
    for pat in RESET_AT:
        m = pat.search(line)
        if not m:
            continue
        g = m.groupdict()
        zone: dt.tzinfo | None = local or now.astimezone().tzinfo
        if g.get("zone"):
            try:
                zone = ZoneInfo(g["zone"])
            except (ZoneInfoNotFoundError, ValueError):
                return None
        hour, minute = int(g["h"]), int(g["m"] or 0)
        ap = (g.get("ap") or "").replace(".", "").lower()
        if ap:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if ap == "pm" else 0)
        if hour > 23 or minute > 59:
            return None
        here = now.astimezone(zone)
        try:
            if g.get("mon"):
                month = MONTHS.get(g["mon"][:3].lower())
                if month is None:
                    return None
                year = int(g["year"]) if g.get("year") else here.year
                t = dt.datetime(year, month, int(g["day"]), hour, minute, tzinfo=zone)
                if not g.get("year") and t < here - dt.timedelta(days=180):  # a January reset printed in December
                    t = t.replace(year=year + 1)
            else:
                t = here.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if t <= here:
                    t += dt.timedelta(days=1)
        except ValueError:
            return None
        return _iso(t)
    return None


# ---------------------------------------------------------------- the availability ledger
def ledger(root: Path, repo_id: str):
    """The availability ledger, its folder made beneath the repository without following a link."""
    from .fsutil import LinkRefused, open_dir_beneath
    from .ledger import Ledger, LedgerError

    try:
        os.close(open_dir_beneath(root, tuple(Path(LEDGER).parent.parts), create=True))
    except (LinkRefused, OSError) as e:
        raise LedgerError(f"{Path(LEDGER).parent} cannot be used: {e}") from None
    return Ledger(root / LEDGER, "availability", repo_id, base=root)


def record_ending(root: Path, repo_id: str, e: Ending, source: str, **extra: Any) -> dict[str, Any]:
    """Append a run's "cannot run" ending (`source`: the log or dispatch output it was read from, repository-relative).
    D02: `extra` adds what followed, such as `redelegated` (the task handed to the next agent)."""
    return ledger(root, repo_id).append("ending", {"agent": e.agent, "state": e.kind, "reset": e.reset,
                                                  "message": e.message, "source": source, **extra})


def record_observed(root: Path, repo_id: str, seen: list[dict[str, Any]]) -> None:
    """Append what `agents setup` observed of each agent: installed, its version and its sign-in state."""
    led = ledger(root, repo_id)
    for p in seen:
        state = "missing" if not p["installed"] else "signed_out" if p["signed_in"] is False else "available"
        led.append("observed", {"agent": p["agent"], "state": state, "version": p["version"],
                                "signed_in": p["signed_in"], "found": p["found"]})


def _when(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def availability(entries: list[dict[str, Any]], name: str, installed: bool, now: dt.datetime) -> dict[str, Any]:
    """One agent's state from the ledger and whether it is installed now: missing (not installed), limited until a
    time (a limit whose reset has not passed), signed out (the newest record says so), or available."""
    mine = [e for e in entries if e.get("agent") == name and e.get("kind") in ("ending", "observed")]
    last = mine[-1] if mine else None
    observed = next((e for e in reversed(mine) if e.get("kind") == "observed"), None)
    state, until, known = "available", None, None
    if not installed:
        state = "missing"
    elif last is not None and last.get("state") == "limited":
        reset = _when(last.get("reset"))
        known = reset is not None
        if reset is None and (at := _when(last.get("time"))) is not None:
            reset = at + UNKNOWN_RESET_HOLD
        if reset is not None and reset > now:
            state, until = "limited", _iso(reset)
        else:
            known = None
    elif last is not None and last.get("state") == "signed_out":
        state = "signed_out"
    return {"state": state, "until": until, "reset_known": known,
            "version": observed.get("version") if observed else None,
            "signed_in": observed.get("signed_in") if observed else None,
            "last": None if last is None else {
                "kind": last.get("kind"), "state": last.get("state"), "reset": last.get("reset"),
                "message": last.get("message"), "source": last.get("source"), "time": last.get("time"),
                "seq": last.get("seq")}}


def status(root: Path, cfg: Any, now: dt.datetime) -> dict[str, Any]:
    """The `steward.agents_status/0.1` document (without its schema tag). Nothing is run: installation is looked up
    on PATH and in the known folders, the rest comes from the ledger."""
    from . import ledger as lg

    v = lg.verify(root / LEDGER)
    if v.errors or v.torn_tail:
        raise ValueError(f"{LEDGER} was edited, or its last record is torn; run `steward ledger recover {LEDGER}`")
    d = cfg.delegation
    names = ([d.master] + list(d.workers) if d else []) + [n for n in ORDER if not d or n not in [d.master, *d.workers]]
    agents = []
    for name in names:
        _, where = locate(name)
        role = "master" if d and name == d.master else "worker" if d and name in d.workers else "unassigned"
        agents.append({"agent": name, "executable": AGENTS[name].executable, "role": role,
                       "rank": d.workers.index(name) + 1 if role == "worker" else None,
                       "installed": where is not None, "found": where,
                       "model": (d.models.get(name) if d else None),
                       **availability(v.entries, name, where is not None, now)})
    return {"ledger": LEDGER, "now": _iso(now), "configured": d is not None,
            "master": d.master if d else None, "workers": list(d.workers) if d else [],
            "on_limit": d.on_limit if d else None, "agents": agents}


# ---------------------------------------------------------------- [delegation] in steward.toml
def propose(seen: list[dict[str, Any]], current: Any, master: str | None = None) -> dict[str, Any] | None:
    """The [delegation] setup would write: the master (asked for, else the configured one, else claude-code when it
    is installed, else the first installed agent), the installed agents other than the master as workers (the
    configured order first), and the configured on_limit and models. None when no agent is installed."""
    installed = [p["agent"] for p in seen if p["installed"]]
    if master is None:
        master = current.master if current else ("claude-code" if "claude-code" in installed else
                                                  next(iter(installed), None))
    if master is None:
        return None
    order = [w for w in (current.workers if current else []) if w in installed] + [n for n in ORDER if n in installed]
    workers = [w for w in dict.fromkeys(order) if w != master]
    models = dict(current.models) if current else {}
    for w in workers:
        if w not in models and AGENTS[w].default_model:
            models[w] = AGENTS[w].default_model
    return {"master": master, "workers": workers, "on_limit": current.on_limit if current else "next",
            "models": {k: models[k] for k in ORDER if k in models}}


def render(d: dict[str, Any]) -> str:
    lines = ["[delegation]", f"master = {json.dumps(d['master'])}",
             "workers = [" + ", ".join(json.dumps(w) for w in d["workers"]) + "]",
             f"on_limit = {json.dumps(d['on_limit'])}"]
    if d["models"]:
        lines += ["", "[delegation.models]"] + [f"{k} = {json.dumps(v)}" for k, v in d["models"].items()]
    return "\n".join(lines) + "\n"


_HEADER = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\"-]+?)\s*\]\]?\s*(?:#.*)?$")


def replace_table(text: str, block: str) -> str:
    """steward.toml with its [delegation] and [delegation.*] tables replaced by `block` where the first of them
    stood, or `block` appended when there is none. Every other line is kept as it is."""
    out: list[str] = []
    held: list[str] = []  # the lines of a [delegation] table, dropped unless they are the next table's comments
    placed = inside = False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line)
        if m:
            name = m.group(1).replace('"', "")
            now_inside = name == "delegation" or name.startswith("delegation.")
            if now_inside and not placed:
                out.append(block)
                placed = True
            if inside and not now_inside:  # leaving: keep the comments that introduce the next table
                tail: list[str] = []
                while held and (held[-1].strip() == "" or held[-1].lstrip().startswith("#")):
                    tail.insert(0, held.pop())
                while tail and tail[0].strip() == "":
                    tail.pop(0)
                out += ["\n"] + tail
            held, inside = [], now_inside
            if inside:
                continue
        if inside:
            held.append(line)
        else:
            out.append(line)
    if placed:
        return "".join(out)
    base = text if text.endswith("\n") or not text else text + "\n"
    return base + ("\n" if base else "") + block


def diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        "steward.toml", "steward.toml (proposed)"))


def missing_configured(cfg: Any) -> list[tuple[str, str]]:
    """(agent, role) for each agent [delegation] names that is not installed: on PATH or in its known folders."""
    d = cfg.delegation
    if d is None:
        return []
    return [(n, "master" if n == d.master else "worker") for n in [d.master, *d.workers] if locate(n)[0] is None]


# ---------------------------------------------------------------- choosing who runs a task (D02)
PROVIDERS = {"claude-code": "anthropic", "codex": "openai", "antigravity": "google"}


@dataclass(frozen=True)
class Choice:
    """Who runs a task now. `agent` None: nobody can now; `until` is then the earliest reset time when `on_limit`
    is "wait", and `why` says what stopped each agent."""

    agent: str | None
    role: str | None  # "worker" or "master"
    model: str | None
    until: str | None
    why: str


def _entries(root: Path) -> list[dict[str, Any]]:
    from . import ledger as lg

    p = root / LEDGER
    if not p.is_file():
        return []
    v = lg.verify(p)
    if v.errors or v.torn_tail:
        raise ValueError(f"{LEDGER} was edited, or its last record is torn; run `steward ledger recover {LEDGER}`")
    return v.entries


def states_now(root: Path, names: list[str], now: dt.datetime) -> dict[str, dict[str, Any]]:
    """Each named agent's availability now: installed (looked up, nothing run) and the ledger's records."""
    entries = _entries(root)
    return {n: availability(entries, n, locate(n)[1] is not None, now) for n in dict.fromkeys(names)}


def said(name: str, a: dict[str, Any]) -> str:
    """One agent's availability in words: "codex limited until …", "antigravity signed out"."""
    if a["state"] == "limited":
        return f"{name} limited until {a['until']}"
    return f"{name} {a['state'].replace('_', ' ')}"


def choose(root: Path, cfg: Any, requires: list[str], now: dt.datetime, tried: list[str] | tuple[str, ...] = (),
           prefer: str | None = None, only: tuple[str, ...] | None = None) -> Choice:
    """The agent that takes an `agent = "auto"` task (D02): the first available worker in `[delegation] workers` that
    can offer what the task requires and has not been tried in this round. When none can, `on_limit` decides: the
    master ("next"; "master" also as soon as a worker could not run), or a wait until the earliest reset time
    ("wait"). `prefer` (a rework sent to one agent) is taken first when it is available; `only` limits the workers to
    those agents (a headless dispatch has no Claude Code worker)."""
    from .sprint import OFFERS

    d = cfg.delegation
    if d is None:
        return Choice(None, None, None, None,
                      'agent = "auto" needs [delegation] in steward.toml (steward agents setup writes it)')
    need = set(requires)
    workers = [w for w in d.workers if only is None or w in only]
    avail = states_now(root, list(dict.fromkeys([*workers, d.master, *([prefer] if prefer else [])])), now)

    def fits(n: str) -> bool:
        return need <= OFFERS[n]

    def role(n: str) -> str:
        return "master" if n == d.master else "worker"

    if prefer and prefer in avail and prefer not in tried and fits(prefer) and avail[prefer]["state"] == "available":
        return Choice(prefer, role(prefer), d.models.get(prefer), None, f"{prefer} (asked for)")
    skipped: list[str] = []
    if d.on_limit == "master" and tried:
        skipped.append("on_limit = master")
    else:
        for w in workers:
            if w in tried:
                skipped.append(f"{w} could not run")
            elif not fits(w):
                skipped.append(f"{w} cannot offer {', '.join(sorted(need - OFFERS[w]))}")
            elif avail[w]["state"] != "available":
                skipped.append(said(w, avail[w]))
            else:
                return Choice(w, "worker", d.models.get(w), None,
                              w + (f" (skipped: {'; '.join(skipped)})" if skipped else ""))
    m = d.master
    if d.on_limit in ("next", "master"):
        if m not in tried and fits(m) and avail[m]["state"] == "available":
            return Choice(m, "master", d.models.get(m), None,
                          f"the master {m}" + (f" (no worker can run: {'; '.join(skipped)})" if skipped else ""))
        skipped.append(f"the master {m} could not run" if m in tried else
                       f"the master {m} cannot offer {', '.join(sorted(need - OFFERS[m]))}" if not fits(m) else
                       "the master " + said(m, avail[m]))
        return Choice(None, None, None, None, "no agent can run: " + "; ".join(skipped))
    untils = sorted(a["until"] for n, a in avail.items()
                    if n in workers and fits(n) and a["state"] == "limited" and a["until"])
    if untils:
        return Choice(None, None, None, untils[0],
                      f"no worker can run ({'; '.join(skipped)}); waits until {untils[0]} (on_limit = wait)")
    return Choice(None, None, None, None, "no worker can run and none has a reset time: " + "; ".join(skipped))


def order_text(cfg: Any) -> str:
    """The order an `agent = "auto"` task is tried in, for `sprint check`."""
    d = cfg.delegation
    if d is None:
        return 'agent = "auto" needs [delegation] in steward.toml (steward agents setup writes it)'
    then = {"next": f"then the master {d.master}",
            "master": f"the master {d.master} as soon as a worker cannot run",
            "wait": "then a wait until the earliest reset time"}[d.on_limit]
    return f"tries {', '.join(d.workers) or 'no worker'}; {then} (on_limit = {d.on_limit})"


def read_ending_from(agent: str, log: Path, offset: int, now: dt.datetime | None = None) -> Ending | None:
    """`ending` of what a log gained after `offset` (one attempt's output, never an earlier attempt's), at most its
    last LOG_TAIL bytes; None for a missing file, a link, or an unreadable one."""
    try:
        if log.is_symlink() or not log.is_file():
            return None
        with open(log, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(offset, size - LOG_TAIL, 0))
            data = fh.read()
    except OSError:
        return None
    return ending(agent, data.decode("utf-8", errors="replace"), now)
