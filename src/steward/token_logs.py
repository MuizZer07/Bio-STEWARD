"""Read-only adapters. Only usage, event metadata, read paths and output sizes cross this module."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def identifier(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", value):
        return value
    return None


def timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _array(value: Any) -> list:
    return value if isinstance(value, list) else []


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value < 2**63 else None


def _path(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= 4096 and value.isprintable():
        return value
    return None


def _size(output: Any) -> int | None:
    """Measure recorded output bytes without returning, displaying or interpreting the payload."""
    if isinstance(output, str):
        return len(output.encode("utf-8", errors="surrogatepass"))
    if isinstance(output, (dict, list)):
        return len(json.dumps(output, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
    return None


@dataclass(frozen=True)
class Usage:
    input: int  # all input, including cache
    output: int  # all output, including reasoning when recorded
    cache_read: int | None
    cache_write: int | None

    @property
    def tokens(self) -> int:
        return self.input + self.output


@dataclass(frozen=True)
class Event:
    time: datetime
    session: str | None
    model: str | None
    key: tuple
    usage: Usage | None = None
    paths: tuple[str, ...] = ()
    output_bytes: int | None = None
    missing_usage: bool = False


@dataclass
class Log:
    include_tools: bool = True
    events: list[Event] = field(default_factory=list)
    issues: set[str] = field(default_factory=set)

    def add(self, when, session, model, key, **metrics) -> None:
        time = timestamp(when)
        if time is None:
            if "usage" in metrics or metrics.get("missing_usage"):
                self.issues.add("usage without a timestamp")
            return
        self.events.append(Event(time, session, model, key, **metrics))

    def message_usage(self, messages: dict[tuple, Event], when: Any, session: str | None, model: str | None,
                      msg_id: str | None, usage: Usage | None) -> None:
        at = timestamp(when)
        if at is None:
            self.issues.add("usage without a timestamp")
            return
        key = ("usage", msg_id or (at, len(self.events)))
        event = Event(at, session, model, key, usage, missing_usage=usage is None)
        if msg_id is None:
            self.events.append(event)
            return
        prior = messages.get((session, msg_id))
        # Streaming snapshots share an ID. Preserve the first timestamp and the most complete count.
        if prior is None or (usage and (prior.usage is None or usage.tokens >= prior.usage.tokens)):
            messages[session, msg_id] = replace(event, time=min(prior.time, at)) if prior else event


def _jsonl(stream, log: Log) -> Iterator[dict]:
    for line in stream:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                yield row
                continue
        except (ValueError, RecursionError):
            pass
        log.issues.add("unreadable record")


def _claude(rows: Iterable[dict], log: Log) -> None:
    # Claude can persist the same assistant message more than once while streaming.
    messages: dict[tuple, Event] = {}
    reads: dict[tuple, str] = {}
    for row in rows:
        kind = row.get("type")
        session = identifier(row.get("sessionId"))
        when = row.get("timestamp")
        msg = _object(row.get("message"))
        blocks = map(_object, _array(msg.get("content"))) if log.include_tools else ()
        if kind == "assistant":
            for block in blocks:
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    call = identifier(block.get("id"))
                    path = _path(_object(block.get("input")).get("file_path"))
                    if call and path:
                        reads[session, call] = path
            if msg.get("model") == "<synthetic>":
                continue
            model = identifier(msg.get("model"))
            msg_id = identifier(msg.get("id"))
            data = _object(msg.get("usage"))
            fresh, output = (_count(data.get(field)) for field in ("input_tokens", "output_tokens"))
            cache = [data.get(field) for field in ("cache_read_input_tokens", "cache_creation_input_tokens")]
            read, write = map(_count, cache)
            usage = None
            if fresh is not None and output is not None and all(v is None or _count(v) is not None for v in cache):
                usage = Usage(fresh + (read or 0) + (write or 0), output, read, write)
            log.message_usage(messages, when, session, model, msg_id, usage)
        elif kind == "user":
            for block in blocks:
                if block.get("type") != "tool_result":
                    continue
                call = identifier(block.get("tool_use_id"))
                path = reads.get((session, call)) if call else None
                log.add(when, session, None, ("tool", call) if call else ("tool", when, len(log.events)),
                        paths=(path,) if path and block.get("is_error") is not True else (),
                        output_bytes=_size(block.get("content")))
    log.events.extend(messages.values())


def _codex_counts(value: Any) -> Usage | None:
    data = _object(value)
    inp, out = (_count(data.get(field)) for field in ("input_tokens", "output_tokens"))
    cache = [data.get(field) for field in ("cached_input_tokens", "cache_write_input_tokens")]
    read, write = map(_count, cache)
    if (inp is None or out is None or (read or 0) + (write or 0) > inp
            or any(v is not None and _count(v) is None for v in cache)):
        return None
    total = data.get("total_tokens")
    if total is not None and _count(total) != inp + out:
        return None
    return Usage(inp, out, read, write)


def _successive_codex_usage(total: Usage, previous: Usage | None, last: Usage) -> bool:
    """Check that a cumulative snapshot advances by exactly one recorded response."""
    if previous is None:
        return total == last
    for field in ("input", "output", "cache_read", "cache_write"):
        cumulative, before, response = (getattr(value, field) for value in (total, previous, last))
        if None not in (cumulative, before, response) and cumulative - before != response:
            return False
    return True


def _codex(rows: Iterable[dict], log: Log) -> None:
    session = model = None
    previous = None
    tools: dict[str, dict] = {}
    for row in rows:
        payload = _object(row.get("payload"))
        kind, item, when = row.get("type"), payload.get("type"), row.get("timestamp")
        if kind == "session_meta":
            session = identifier(payload.get("id"))
        elif kind == "turn_context":
            model = identifier(payload.get("model"))
        elif kind == "event_msg" and item == "token_count":
            info = payload.get("info")
            if "info" in payload and info is None:  # rate limits can be emitted without usage
                continue
            data = _object(info)
            last = _codex_counts(data.get("last_token_usage"))
            total = _codex_counts(data.get("total_token_usage"))
            if total is not None and total == previous:
                continue
            missing = last is None or (data.get("total_token_usage") is not None and total is None)
            if total and last:
                missing |= not _successive_codex_usage(total, previous, last)
            previous = total
            log.add(when, session, identifier(payload.get("model")) or model, ("usage", when, total, last),
                    usage=last, missing_usage=missing)
        elif log.include_tools:
            if kind == "response_item" and item in ("function_call_output", "custom_tool_call_output"):
                _codex_tool(tools, payload, when, model, identifier(payload.get("call_id")), command=False)
            elif kind == "event_msg" and item == "exec_command_end":
                _codex_tool(tools, payload, when, model, identifier(payload.get("call_id")), command=True)
            elif kind == "event_msg" and item == "item_completed":
                result = _object(payload.get("item"))
                if result.get("type") in ("CommandExecution", "FunctionCallOutput"):
                    _codex_tool(tools, result, when, model, identifier(result.get("id")),
                                command=result["type"] == "CommandExecution")
    for call, tool in tools.items():
        log.add(tool.pop("when"), session, tool.pop("model"), ("tool", call), **tool)


def _codex_tool(tools, record, when, model, call, *, command):
    tool = tools.setdefault(call or ("unidentified", len(tools)), {"when": when, "model": model})
    if command:
        paths = [_path(cmd.get("path")) for cmd in map(_object, _array(record.get("parsed_cmd")))
                 if cmd.get("type") == "read"]
        if record.get("exit_code") in (None, 0) and record.get("status") not in ("failed", "declined"):
            tool["paths"] = tuple(p for p in paths if p)
        tool.setdefault("output_bytes", _size(record.get("aggregated_output")))
    else:
        size = _size(record.get("output"))
        if size is not None:
            tool.update(output_bytes=size, when=when, model=model)


def _gemini_usage(data: dict) -> Usage | None:
    inp, out = (_count(data.get(field)) for field in ("input", "output"))
    cached, total = _count(data.get("cached")), _count(data.get("total"))
    thoughts, tool = (_count(data.get(field, 0)) for field in ("thoughts", "tool"))
    if None in (inp, out, total, thoughts, tool) or (cached is not None and cached > inp):
        return None
    # Some records include the tool prompt in input. The total distinguishes the two layouts.
    output = out + thoughts
    if total not in (inp + output, inp + output + tool):
        return None
    return Usage(total - output, output, cached, None)


def _gemini(rows: Iterable[dict], log: Log) -> None:
    session = None
    messages: dict[tuple, Event] = {}
    calls: dict[tuple, Event] = {}
    for row in rows:
        if "sessionId" in row:
            session = identifier(row.get("sessionId"))
        if log.include_tools and "$patch" in row:
            patch = _object(row["$patch"])
            for update in [patch, *map(_object, _array(patch.get("updates")))]:
                for call in map(_object, _array(update.get("toolCalls"))):
                    key = (session, identifier(update.get("id")), identifier(call.get("id")))
                    found = calls.get(key)
                    if found and "result" in call:  # patches can arrive after the initial message
                        calls[key] = replace(found, output_bytes=_size(call["result"]))
        if row.get("type") != "gemini":
            continue
        when = row.get("timestamp")
        msg_id, model = identifier(row.get("id")), identifier(row.get("model"))
        usage = _gemini_usage(_object(row.get("tokens")))
        if model is not None or row.get("tokens") is not None:
            log.message_usage(messages, when, session, model, msg_id, usage)
        for call in map(_object, _array(row.get("toolCalls"))) if log.include_tools else ():
            call_time = timestamp(call.get("timestamp")) or timestamp(when)
            if call_time is None:
                continue
            call_id = identifier(call.get("id"))
            args = _object(call.get("args"))
            path = _path(args.get("file_path") or args.get("path")) if call.get("name") == "read_file" else None
            if call.get("status") in ("error", "cancelled"):
                path = None
            key = (session, msg_id, call_id or len(calls))
            calls[key] = Event(call_time, session, model, ("tool", msg_id, key[-1]), paths=(path,) if path else (),
                               output_bytes=_size(call.get("result")))
    log.events.extend(messages.values())
    log.events.extend(calls.values())


_ADAPTERS = {"claude": _claude, "codex": _codex, "gemini": _gemini}
AGENTS = tuple(_ADAPTERS)


def read(agent: str, path: Path, *, include_tools: bool = True) -> Log:
    log = Log(include_tools=include_tools)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("expected a regular file")
            if agent == "gemini" and path.suffix.lower() == ".json":
                document = _object(json.load(stream))
                _gemini([document, *map(_object, _array(document.get("messages")))], log)
            else:
                _ADAPTERS[agent](_jsonl(stream, log), log)
    except (OSError, ValueError, RecursionError):
        log.issues.add("unreadable log")
    return log
