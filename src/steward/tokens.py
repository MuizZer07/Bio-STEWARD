"""Task windows, budget checks and opt-in reports for local agent logs."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from pathlib import Path

from pydantic import ValidationError

from . import charts, spend, token_logs
from .fsutil import LinkRefused, escapes_root, matching_files
from .interface import wants_json, write_json
from .ledger import Ledger, LedgerError, verify_bytes
from .models import AgentsSection, StewardConfig, TaskTokenBudget
from .newest import newest_first
from .process import ID_LINE
from .records import read_rel
from .status import EXIT_DATAERR, EXIT_OK, EXIT_USAGE
from .token_logs import AGENTS, Event, Log, identifier, timestamp

WINDOW_LEDGER = ".steward/task-tokens.jsonl"
BUDGET_LINE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?tokens_budget\s*[:=](?:\*\*)?[ \t]*(.*)$", re.M)
AGENT_NAMES = {"claude": "claude", "claude code": "claude", "codex": "codex", "openai codex": "codex",
               "gemini": "gemini", "gemini cli": "gemini"}


class TokenError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Window:
    task: str
    start: datetime
    end: datetime | None = None
    session: str | None = None
    agent: str | None = None
    model: str | None = None
    source: str = "task-tokens"  # X05: task-tokens (by hand), agents, sprint, run, or all activity
    ledger: str | None = None    # X05: the record the window was read from

    @property
    def tier(self) -> int:
        """X05: usage inside a window by hand (or from the agents ledger) belongs to it as before; inside none of
        those, to a sprint task's window; inside none of those either, to a run's."""
        return {"sprint": 1, "run": 2}.get(self.source, 0)

    def matches(self, agent: str, event: Event) -> bool:
        return ((self.agent is None or self.agent == agent)
                and (self.session is None or self.session == event.session)
                and (self.model is None or event.model is None or self.model == event.model)
                and self.start <= event.time and (self.end is None or event.time < self.end))


def _entries(root: Path, rel: str, name: str, repo_id: str) -> list[dict]:
    if escapes_root(rel):
        raise TokenError(f"{name} ledger is unavailable")
    path = root / rel
    if not path.exists() and not path.is_symlink():
        return []
    try:
        ledger = verify_bytes(read_rel(root, rel))
        if (ledger.errors or ledger.torn_tail or not ledger.entries or ledger.entries[0].get("kind") != "genesis"
                or ledger.entries[0].get("ledger") != name or ledger.entries[0].get("repo_id") != repo_id):
            raise TokenError(f"{name} ledger is unavailable")
    except (OSError, ValueError, RecursionError) as error:
        raise TokenError(f"{name} ledger is unavailable") from error
    return ledger.entries


def _markers(entries: list[dict]) -> list[Window]:
    windows = []
    opened: dict[str, int] = {}
    for row in entries:
        if row.get("kind") == "genesis":
            continue
        task, when = identifier(row.get("task")), timestamp(row.get("at"))
        if task and when:
            if row.get("kind") == "start" and task not in opened:
                session = row.get("session")
                if session is None or identifier(session):
                    opened[task] = len(windows)
                    windows.append(Window(task, when, session=session))
                    continue
            if row.get("kind") == "done" and task in opened:
                index = opened.pop(task)
                if when >= windows[index].start:
                    windows[index] = replace(windows[index], end=when)
                    continue
        raise TokenError("task-tokens ledger has an invalid task window")
    return windows


def _windows(root: Path, cfg: StewardConfig) -> tuple[list[Window], set[str]]:
    repo_id = cfg.steward.repo_id
    windows = [replace(w, ledger=WINDOW_LEDGER) for w in _markers(_entries(root, WINDOW_LEDGER, "task-tokens", repo_id))]
    recorded = {w.task for w in windows}
    issues = set()
    try:
        entries = _entries(root, (cfg.agents or AgentsSection()).ledger, "agents", repo_id)
    except TokenError as err:
        return windows, {str(err)}
    for row in entries:
        task = identifier(row.get("task"))
        if row.get("kind") != "attempt" or task in recorded:
            continue
        label = row.get("agent")
        agent = AGENT_NAMES.get(label.strip().lower()) if isinstance(label, str) else None
        start, end = timestamp(row.get("started")), timestamp(row.get("ended"))
        model = identifier(row.get("model"))
        if task and agent and start and (row.get("ended") is None or (end and end >= start)):
            windows.append(Window(task, start, end, agent=agent, model=None if model == "unknown" else model,
                                  source="agents", ledger=(cfg.agents or AgentsSection()).ledger))
        else:
            issues.add("agents ledger has attempts without a supported agent or usable dates")
    return windows, issues


# X05: the sprint adapters, as the agent whose logs hold their usage; any other adapter matches every agent's logs
SPRINT_AGENTS = {"claude-code": "claude", "codex": "codex"}


def _sprint_end(root: Path, sid: str) -> datetime | None:
    """The end of a sprint's window, from its file; a task cannot run past it."""
    from . import sprint as sp

    sf, _ = sp.validate_file(root / sp.DIR / f"{sid}.toml")
    return sf.sprint.window.end.astimezone(timezone.utc) if sf is not None and sf.sprint.id == sid else None


def _sprint_windows(root: Path, rel: str, repo_id: str) -> tuple[list[Window], set[str]]:
    """X05: each attempt of each sprint task, from `running` to `done`, `failed` or a `skip` order, labelled
    `sprint <id> <task>`. An attempt still open ends with the sprint's window. Also returns the runs the ledger names
    (each task's own `steward run`, which this window already covers)."""
    entries = _entries(root, rel, "sprint", repo_id)
    opened = next((e for e in entries if e.get("kind") == "opened"), {})
    sid = identifier(opened.get("sprint")) or Path(rel).stem
    windows: list[Window] = []
    open_: dict[str, int] = {}
    runs: set[str] = set()
    for e in entries:
        task, when = identifier(e.get("task")), timestamp(e.get("time"))
        if e.get("kind") == "state" and isinstance(e.get("run"), str):
            runs.add(e["run"])
        if not task or not when:
            continue
        state = e.get("state") if e.get("kind") == "state" else None
        ends = state in ("done", "failed") or (e.get("kind") == "order" and e.get("order") == "skip")
        if (state == "running" or ends) and task in open_:
            index = open_.pop(task)
            windows[index] = replace(windows[index], end=max(when, windows[index].start))
        if state == "running":
            agent = SPRINT_AGENTS.get(e.get("agent")) if isinstance(e.get("agent"), str) else None
            open_[task] = len(windows)
            windows.append(Window(f"sprint {sid} {task}", when, agent=agent, source="sprint", ledger=rel))
    if open_:
        end = _sprint_end(root, sid)
        for index in open_.values():
            if end is not None:
                windows[index] = replace(windows[index], end=max(end, windows[index].start))
    return windows, runs


def _alive(row: dict) -> bool:
    """A run without an outcome still runs when its recorded process does (the check `steward run` recovery uses)."""
    import psutil

    try:
        proc = psutil.Process(int(row.get("pid")))
        return abs(proc.create_time() - float(row.get("pid_created"))) < 1.0
    except (psutil.Error, TypeError, ValueError, OverflowError):
        return False


def _record_windows(root: Path, cfg: StewardConfig, recorded: set[str]) -> tuple[list[Window], set[str]]:
    """X05: the windows the project's records already hold: each sprint task's (its sprint ledger) and each
    `steward run`'s (the run ledger). A sprint task that has a window by hand or in the agents ledger keeps that one."""
    from . import sprint as sp
    from .models import RunSection

    repo_id = cfg.steward.repo_id
    windows: list[Window] = []
    issues: set[str] = set()
    sprint_runs: set[str] = set()
    folder = root / sp.DIR
    names = sorted(p.name for p in folder.glob("*.jsonl")) if folder.is_dir() and not folder.is_symlink() else []
    for name in names:
        rel = f"{sp.DIR}/{name}"
        try:
            found, runs = _sprint_windows(root, rel, repo_id)
        except TokenError:
            issues.add(f"sprint ledger {rel} is unavailable")
            continue
        sprint_runs |= runs
        windows += [w for w in found if w.task.rsplit(" ", 1)[-1] not in recorded]
    rel = (cfg.run or RunSection()).ledger
    try:
        entries = _entries(root, rel, "runs", repo_id)
    except TokenError:
        issues.add(f"run ledger {rel} is unavailable")
        return windows, issues
    started: dict[str, dict] = {}
    ended: dict[str, datetime] = {}
    for e in entries:
        run = identifier(e.get("run"))
        if not run:
            continue
        if e.get("kind") == "started":
            started.setdefault(run, e)
        elif e.get("kind") in ("outcome", "interrupted") and (when := timestamp(e.get("time"))):
            ended.setdefault(run, when)
    stale = 0
    for run, row in started.items():
        label = row.get("label")
        if run in sprint_runs or (isinstance(label, str) and label.startswith("sprint:")):
            continue  # a sprint task's own run: the sprint window covers it
        start = timestamp(row.get("time"))
        if start is None:
            continue
        end = ended.get(run)
        if end is None and not _alive(row):
            stale += 1
            continue
        windows.append(Window(f"run {run}", start, max(end, start) if end else None, source="run", ledger=rel))
    if stale:
        issues.add(f"{stale} run(s) have no recorded end and no live process; their windows are left out")
    return windows, issues


def _mark(root: Path, cfg: StewardConfig, args) -> None:
    task = identifier(args.id)
    session = getattr(args, "session", None)
    if not task or (session is not None and not identifier(session)):
        raise TokenError("use a task or session ID made of identifier characters")
    ledger = Ledger(root / WINDOW_LEDGER, "task-tokens", cfg.steward.repo_id, base=root)

    def update(entries):
        active = any(w.task == task and w.end is None for w in _markers(entries))
        action = args.task_command
        if action == "start" and active:
            raise TokenError(f"{task} already has an open window")
        if action == "done" and not active:
            raise TokenError(f"{task} has no open window")
        body = {"task": task, "at": now().isoformat()}
        if action == "start" and session:
            body["session"] = session
        _markers([*entries, {"kind": action, **body}])
        return action, body

    (root / WINDOW_LEDGER).parent.mkdir(exist_ok=True)
    ledger.transaction(update)
    print(f"{task} token window {'opened' if args.task_command == 'start' else 'closed'}")


def _budget_files(root: Path, cfg: StewardConfig, ids: set[str]) -> dict[str, list[str]]:
    patterns = [*cfg.tasks.specs, *cfg.tasks.archive] if cfg.tasks else ["development/tasks/**/*.md"]
    matches = defaultdict(list)
    for rel in matching_files(root, patterns):
        if cfg.tasks and rel == cfg.tasks.board:
            continue
        try:
            text = read_rel(root, rel).decode("utf-8")
        except (OSError, UnicodeError):
            continue
        found = ID_LINE.search(text)
        if found and found[1] in ids:
            matches[found[1]].append(text)
    return matches


def _budget(specs: list[str]) -> tuple[int | None, str]:
    if len(specs) != 1:
        return None, "task file missing" if not specs else "multiple task files have this ID"
    # Look in the task header. Examples and work log entries may contain the same spelling.
    header = re.split(r"^#{2,}[ \t]+", specs[0], maxsplit=1, flags=re.M)[0]
    found = BUDGET_LINE.findall(header)
    if not found:
        return None, "no tokens_budget set"
    try:
        value = TaskTokenBudget(tokens_budget=int(found[0].strip(" `"))).tokens_budget if len(found) == 1 else None
    except (ValueError, ValidationError):
        value = None
    return value, "" if value is not None else "tokens_budget must be a single positive integer"


def _summarize_log(log: Log) -> tuple[str, list[str]]:
    usable = any(e.usage is not None for e in log.events)
    problems = log.issues | ({"usage records missing or incomplete"} if any(e.missing_usage for e in log.events) else set())
    if not usable:
        return "unavailable", sorted(problems or {"no supported usage records"})
    return ("partial" if problems else "available"), sorted(problems)


def _sources(paths: dict[str, list[Path]], session: str | None, *, include_tools: bool):
    sources = {}
    logs = {}
    for agent, files in paths.items():
        unique: dict[tuple, tuple[Path, Event]] = {}
        unknown_scope = False
        descriptions = []
        for path in dict.fromkeys(files):
            log = token_logs.read(agent, path, include_tools=include_tools)
            if session is not None:
                log.events = [e for e in log.events if e.session == session]
            status, issues = _summarize_log(log)
            descriptions.append({"path": str(path), "status": status, "issues": issues})
            unknown_scope |= status == "unavailable" or bool(log.issues)
            for event in log.events:
                identity = (event.session or path, event.key)
                previous = unique[identity][1] if identity in unique else None
                if (previous is None
                        or (event.usage is not None and
                            (previous.usage is None or event.usage.tokens > previous.usage.tokens))
                        or (event.output_bytes is not None and
                            (previous.output_bytes is None or event.output_bytes > previous.output_bytes))):
                    unique[identity] = path, event
        states = {d["status"] for d in descriptions}
        state = ("available" if states == {"available"} else
                 "unavailable" if not states or states == {"unavailable"} else "partial")
        sources[agent] = {"status": state, "files": descriptions}
        logs[agent] = (list(unique.values()), unknown_scope)
    return sources, logs


def _priced(cfg: StewardConfig, model: str | None, events: list[Event]) -> dict:
    usage = [e.usage for e in events if e.usage is not None]
    inputs = sum(u.input for u in usage)
    outputs = sum(u.output for u in usage)
    read = None if any(u.cache_read is None for u in usage) else sum(u.cache_read for u in usage)
    observed_write = sum(u.cache_write or 0 for u in usage)
    write = None if any(u.cache_write is None for u in usage) else observed_write
    cost = None
    if model and read is not None:
        cost = spend.price(cfg, model, inputs - read - observed_write, outputs, cache_read=read,
                           cache_write=observed_write)
    return {"model": model, "tokens": inputs + outputs, "input": inputs, "output": outputs,
            "cache_read": read, "cache_write": write, "cost": cost}


def _report(cfg: StewardConfig, windows: list[Window], selected: set[str], logs, since: datetime | None, current: datetime):
    by_task = defaultdict(list)
    gaps = defaultdict(set)
    for agent, (events, unknown_scope) in logs.items():
        applicable = [w for w in windows if w.agent in (None, agent)]
        if unknown_scope:
            for w in applicable:
                gaps[w.task].add("a selected log has missing or unreadable records")
        for path, event in events:
            if event.time > current or (since is not None and event.time < since):
                continue
            hits = [w for w in applicable if w.matches(agent, event)]
            tier = min((w.tier for w in hits), default=0)  # X05: windows by hand first, then sprint tasks, then runs
            tasks = {w.task for w in hits if w.tier == tier}
            if len(tasks) > 1:
                if event.usage is not None or event.missing_usage:
                    for task in tasks:
                        gaps[task].add("some usage matched multiple tasks")
                continue
            if tasks:
                task = next(iter(tasks))
                by_task[task].append((agent, path, event))
                if event.missing_usage:
                    gaps[task].add("usage records missing or incomplete")
    rows = []
    for task in sorted(selected):
        grouped = defaultdict(list)
        files = Counter()
        tools = []
        for agent, path, event in by_task[task]:
            if event.usage is not None:
                grouped[agent, event.model].append(event)
            files.update(event.paths)
            if event.output_bytes is not None:
                tools.append({"agent": agent, "session": event.session, "bytes": event.output_bytes,
                              "log_path": str(path), "time_ms": int(event.time.timestamp() * 1000),
                              "paths": list(event.paths)})
        models = [{"agent": agent, **_priced(cfg, model, events)}
                  for (agent, model), events in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or ""))]
        agents = [{"agent": agent, "tokens": sum(m["tokens"] for m in models if m["agent"] == agent)}
                  for agent in sorted({m["agent"] for m in models})]
        total = sum(m["tokens"] for m in models) if models else None
        if total is None:
            gaps[task].add("no usable counts matched the task window")
        cost = (sum(m["cost"] for m in models)
                if models and not gaps[task] and all(m["cost"] is not None for m in models) else None)
        rows.append({"task": task, "tokens": total, "cost": cost, "models": models, "agents": agents,
                     "status": "unavailable" if total is None else "partial" if gaps[task] else "available",
                     "issues": sorted(gaps[task]),
                     "files_read": [{"path": path, "reads": n}
                                    for path, n in sorted(files.items(), key=lambda x: (-x[1], x[0]))[:10]],
                     "tool_outputs": sorted(tools, key=lambda t: (-t["bytes"], t["agent"], t["session"] or ""))[:10]})
    return rows


def _checks(root: Path, cfg: StewardConfig, rows: list[dict]) -> tuple[list[str], list[str]]:
    specs = _budget_files(root, cfg, {row["task"] for row in rows}) if rows else {}
    lines, warnings = [], []
    for row in rows:
        task, total = row["task"], row["tokens"]
        budget, reason = _budget(specs.get(task, []))
        if total is None:
            lines.append(f"{task} token usage unavailable")
        elif budget is None:
            lines.append(f"{task} {total:,} tokens ({reason})")
        else:
            threshold = 100 if total >= budget else 80 if total * 5 >= budget * 4 else None
            unit = "observed tokens, coverage partial" if row["status"] == "partial" else "tokens"
            usage = f"{task} {total:,} / {budget:,} {unit}"
            if threshold is not None:
                usage = f"WARNING {usage} (budget threshold {threshold}%)"
                warnings.append(usage)
            lines.append(usage)
    return lines, warnings


def _window_doc(w: Window) -> dict:
    return {"source": w.source, "ledger": w.ledger, "start": w.start.isoformat(),
            "end": w.end.isoformat() if w.end else None}


def _plain_report(rows: list[dict], sources: dict, issues: set[str], currency: str | None,
                  windows: list[Window] = ()) -> None:
    kinds = defaultdict(set)
    for w in windows:
        kinds[w.task].add(w.source)
    chart = charts.text_bars([(row["task"], row["tokens"]) for row in rows if row["tokens"] is not None], "tokens")
    if chart:
        print(chart)
    if not rows:
        print("No task windows match.")
    for row in rows:
        detail = "unavailable" if row["tokens"] is None else f"{row['tokens']:,} observed tokens ({row['status']})"
        cost = "unavailable" if row["cost"] is None else f"{row['cost']:.6g} {currency}"
        where = sorted(kinds.get(row["task"], set()) - {"task-tokens"})  # X05: a window from the records says so
        print(f"{row['task']}  {detail}  estimated cost {cost}" + (f"  (window: {', '.join(where)})" if where else ""))
        for issue in row["issues"]:
            print(f"  {issue}")
        for agent in row["agents"]:
            print(f"  {agent['agent']}  {agent['tokens']:,} tokens")
        for model in row["models"]:
            read, write = (model[field] if model[field] is not None else "unavailable"
                           for field in ("cache_read", "cache_write"))
            model_cost = "unavailable" if model["cost"] is None else f"{model['cost']:.6g} {currency}"
            print(f"    {model['agent']} / {model['model'] or 'unknown model'}  {model['tokens']:,} tokens "
                  f"(input {model['input']}, output {model['output']}, cache read {read}, cache write {write}) "
                  f"estimated cost {model_cost}")
        print("  Largest recorded tool outputs (bytes)" if row["tool_outputs"] else "  Tool output sizes unavailable")
        for tool in row["tool_outputs"]:
            location = ", ".join(tool["paths"]) or repr(tool["log_path"])
            print(f"    {tool['bytes']:,}  {tool['agent']} / {tool['session'] or 'unknown session'}  {location}")
        print("  Most-read files" if row["files_read"] else "  File-read counts unavailable")
        for file in row["files_read"]:
            print(f"    {file['reads']:>4}  {file['path']}")
    for agent, source in sources.items():
        print(f"{agent} logs {source['status']}" + (" (no files selected)" if not source["files"] else ""))
        for file in source["files"]:
            if file["issues"]:
                print(f"  {file['path']!r}  {', '.join(file['issues'])}")
    for issue in sorted(issues):
        print(issue)


def command(args) -> int:
    from .cli import _config

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        if args.command == "task":
            _mark(root, cfg, args)
            return EXIT_OK
        return _token_command(root, cfg, args)
    except (TokenError, LedgerError, OSError, LinkRefused) as error:
        print(f"steward: {error}", file=sys.stderr)
        return EXIT_DATAERR


def _redact(root: Path, rows: list[dict], sources: dict) -> tuple[list[dict], dict]:
    """Report-safe rows (AF14): a file is shown relative to the repository, or as "(outside the repository)"; a log
    file by its agent and number; a session by a short hash. The numbers are unchanged."""
    import hashlib

    base = root.resolve()
    from . import privacy as pv
    from .records import read_rel

    try:  # AF14: a path or model name that holds a private term is withheld
        terms = [t for s_ in pv.load(root, _cfg_for(root), read=lambda rel: read_rel(root, rel)) if s_.state == "ok"
                 for t in s_.terms]
    except Exception:  # noqa: BLE001 - no configuration: nothing to match
        terms = []

    def safe(v: str) -> str:
        return "(withheld: a private term)" if terms and pv.scan_text(v, terms, False, honour_marker=False)[0] else v

    def where(p: str) -> str:
        try:
            q = Path(p)
            rel = (q if q.is_absolute() else base / q).resolve().relative_to(base)
            return safe(rel.as_posix())
        except (ValueError, OSError):
            return "(outside the repository)"

    def sess(v: str | None) -> str | None:
        return None if not v else "session-" + hashlib.sha256(v.encode()).hexdigest()[:8]
    logs: dict[str, str] = {}
    for agent, src in sources.items():
        for i, f in enumerate(src.get("files", []), start=1):
            logs[f["path"]] = f"{agent} log {i}"
            f["path"] = logs[f["path"]]
    for row in rows:
        merged: dict[str, int] = {}
        for f in row.get("files_read", []):
            k = where(f["path"])
            merged[k] = merged.get(k, 0) + f["reads"]
        row["files_read"] = [{"path": k, "reads": n} for k, n in sorted(merged.items(), key=lambda x: (-x[1], x[0]))]
        for t in row.get("tool_outputs", []):
            t["session"] = sess(t.get("session"))
            t["log_path"] = logs.get(t.get("log_path"), "log")
            t["paths"] = sorted({where(x) for x in t.get("paths", [])})
        for m in row.get("models", []):
            if m.get("model"):
                m["model"] = safe(m["model"])
    return rows, sources


def _cfg_for(root: Path):
    from .models import load_config

    return load_config(root)


def _token_command(root: Path, cfg: StewardConfig, args) -> int:
    checking = args.tokens_command == "check"
    hook, statusline = checking and args.claude_hook, checking and args.claude_statusline
    paths = {agent: getattr(args, agent) for agent in AGENTS}
    session = None
    if hook or statusline:
        try:
            payload = json.load(sys.stdin)
            session = identifier(payload.get("session_id")) if isinstance(payload, dict) else None
            path = payload.get("transcript_path") if isinstance(payload, dict) else None
            if not session or not isinstance(path, str) or not Path(path).is_absolute() or "\0" in path:
                raise ValueError
        except (ValueError, OSError, RecursionError):
            print("{}" if hook else "Token usage unavailable")
            return EXIT_OK
        paths = {"claude": [Path(path)], "codex": [], "gemini": []}
    elif cfg.tokens is not None and not any(paths.values()):
        try:
            paths = {
                agent: [root / Path(value).expanduser() for value in getattr(cfg.tokens, agent)]
                for agent in AGENTS
            }
        except RuntimeError:
            raise TokenError("a [tokens] log path names an unavailable home directory") from None
    since = None
    if not checking and args.since is not None:
        try:
            day = date.fromisoformat(args.since)
            if day.isoformat() != args.since:
                raise ValueError
            since = datetime.combine(day, time.min, tzinfo=timezone.utc)
        except ValueError:
            print("steward: --since needs a date in YYYY-MM-DD format", file=sys.stderr)
            return EXIT_USAGE
    windows, issues = _windows(root, cfg)
    # X05: the report also takes the windows the records hold (sprint ledgers, run ledger). `tokens check` and the
    # legacy `--json` output keep the 0.21 windows only, so they are unchanged.
    records = not checking and not getattr(args, "json", False)
    if records:
        found, more = _record_windows(root, cfg, {w.task for w in windows})
        windows, issues = [*windows, *found], issues | more
    current = now()
    selected = {w.task for w in windows if (not args.task or w.task == args.task)
                and (since is None or w.end is None or w.end > since)
                and (not checking or args.task or w.end is None)
                and (session is None or (w.agent in (None, "claude") and w.session in (None, session)))}
    if args.task and args.task not in {w.task for w in windows}:
        print("steward: no window recorded for this task", file=sys.stderr)
        return EXIT_USAGE
    sources, logs = _sources(paths, session, include_tools=not checking)
    everything = Window(task="all activity", start=since or datetime(1970, 1, 1, tzinfo=timezone.utc), end=None,
                        source="all activity")
    if not checking and not args.task and not windows:  # no task recorded yet: all activity in the period, so the
        windows = [*windows, everything]  # first report is useful before any task window
        selected = {"all activity"}
    rows = _report(cfg, windows, selected, logs, since, current)
    if records:  # X05: a run in which no agent logged usage is not a task; it is left out unless asked for by name
        runs = {w.task for w in windows if w.source == "run"}
        rows = [r for r in rows if r["task"] not in runs or r["tokens"] is not None or r["tool_outputs"]
                or r["task"] == args.task]
        if not rows and not args.task and windows and all(w.source == "run" for w in windows):
            windows, selected = [everything], {"all activity"}
            rows = _report(cfg, windows, selected, logs, since, current)
    rows, sources = _redact(root, rows, sources)  # AF14: numbers leave the logs; paths and identifiers do not
    if checking:
        lines, warnings = _checks(root, cfg, rows)
        if hook:
            print(json.dumps({"systemMessage": "\n".join(warnings)} if warnings else {}))
        elif statusline:
            print(" | ".join(lines) if lines else "No active token window")
        else:
            print("\n".join([*lines, *sorted(issues)]) if lines or issues else "No active token window")
    elif args.svg:
        sys.stdout.write(charts.bars([{"label": r["task"], "tokens": r["tokens"], "status": r["status"]} for r in rows],
                                     "tokens", "Observed tokens by task", "tokens"))
    else:
        currency = cfg.spend.currency if cfg.spend else None
        if args.format == "json":  # X05: each task names its windows and where each came from
            for row in rows:
                row["windows"] = [_window_doc(w) for w in sorted((w for w in windows if w.task == row["task"]),
                                                                 key=lambda w: (w.start, w.end or current))]
        if wants_json(args):
            write_json(args, {"tasks": rows, "sources": sources, "issues": sorted(issues), "currency": currency})
        else:
            latest = {}
            for w in windows:
                latest[w.task] = max(latest.get(w.task, w.start), w.start)
            _plain_report(newest_first(rows, lambda r: latest.get(r["task"]), lambda r: r["task"]), sources, issues,
                          currency, windows)
    return EXIT_OK
