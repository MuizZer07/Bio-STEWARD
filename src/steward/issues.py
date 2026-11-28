"""Local fault breadcrumbs and explicit toolkit defect reports (STW-054)."""

from __future__ import annotations

import builtins
import os
import re
import stat
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Iterator, Literal

from pydantic import Field

from . import __version__, exchange, privacy
from .fsutil import canonical_json, find_root, open_dir_beneath, owner_lock, release_owner_lock, safe_write, sha256_bytes
from .models import Hex64, StewardConfig, Strict

LAST_ERROR = ".steward/last-error.json"
LAST_ERROR_SCHEMA = "steward.last_error/0.1"
PACKAGE = Path(__file__).resolve().parent
VERSION = r"^v?[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9.+-]*$"
MARKER = re.compile(r"Toolkit issue fingerprint: ([a-f0-9]{64})")
FINISHED = {"declined", "merged", "shipped", "adopted", "closed", *exchange.RETIRED_STATES}
HINT = "this looks like a toolkit problem: steward issue --from-last-error to report it"


class ErrorFrame(Strict):
    file: str = Field(pattern=r"^steward/(?:[a-z_][a-z_0-9]*/)*[a-z_][a-z_0-9]*\.py$")
    line: int = Field(ge=1)


class LastError(Strict):
    schema_: Literal["steward.last_error/0.1"] = Field(alias="schema")
    fingerprint: Hex64
    tool_version: str = Field(pattern=VERSION)
    command: str = Field(pattern=r"^[a-z][a-z-]*(?: [a-z][a-z-]*)?$")
    flags: list[Annotated[str, Field(pattern=r"^--?[a-zA-Z][a-zA-Z0-9-]*$")]]
    exit_code: int
    error_type: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    frames: list[ErrorFrame]


def fingerprint(error_type: str, frames: list[ErrorFrame]) -> str:
    data = {"type": error_type, "frames": [frame.model_dump() for frame in frames]}
    return sha256_bytes(canonical_json(data).encode("utf-8"))


def breadcrumb(command: str, flags: list[str], code: int, error: Exception | str) -> LastError:
    if isinstance(error, str):
        name = error.replace("-", "_").replace(".", "_")
        trace = None
    else:
        error_class = type(error)
        name = error_class.__name__
        if getattr(builtins, name, None) is not error_class and not error_class.__module__.startswith("steward."):
            name = "Exception"
        trace = error.__traceback__
    frames = []
    while trace is not None:
        code_path = Path(trace.tb_frame.f_code.co_filename)
        if code_path.is_absolute() and code_path.is_relative_to(PACKAGE):
            rel = code_path.relative_to(PACKAGE).as_posix()
            frames.append(ErrorFrame(file=f"steward/{rel}", line=trace.tb_lineno))
        trace = trace.tb_next
    return LastError(schema=LAST_ERROR_SCHEMA, fingerprint=fingerprint(name, frames), tool_version=__version__,
                     command=command, flags=flags, exit_code=code, error_type=name, frames=frames)


class FaultHint:
    """Replace the last breadcrumb on each fault and emit at most one hint per invocation."""

    def __init__(self, repo: Path | None, command: str, flags: list[str]):
        self.repo = repo
        self.command = command
        self.flags = flags
        self.hinted = False

    def __call__(self, code: int, error: Exception | str) -> None:
        saved = False
        try:
            root = self.repo.resolve() if self.repo else find_root(Path.cwd())
            if root is not None and (root / "steward.toml").is_file():
                record = breadcrumb(self.command, self.flags, code, error)
                safe_write(root, LAST_ERROR, canonical_json(record.model_dump(by_alias=True)).encode("utf-8"),
                           mode=0o600)
                saved = True
        except (OSError, ValueError, RuntimeError):
            pass  # a diagnostic write must not hide the original fault
        if saved and not self.hinted:
            print(f"{HINT} (saved {LAST_ERROR}; nothing was sent)", file=sys.stderr)
        elif not self.hinted:
            print("this looks like a toolkit problem: steward issue with a description to report it "
                  "(no last error was saved; nothing was sent)", file=sys.stderr)
        self.hinted = True


def _read_regular(root: Path, path: Path, limit: int) -> bytes:
    directory = open_dir_beneath(root, path.parts[:-1])
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("expected a regular file")
            data = stream.read(limit + 1)
    finally:
        os.close(directory)
    if len(data) > limit:
        raise ValueError("file is too large")
    return data


def read_last_error(root: Path) -> LastError:
    record = LastError.model_validate_json(_read_regular(root, Path(LAST_ERROR), 64 * 1024))
    if fingerprint(record.error_type, record.frames) != record.fingerprint:
        raise ValueError("last error fingerprint does not match")
    return record


class IssueError(ValueError):
    """A report the project cannot file, with a message safe to print."""


def _screen(root: Path, cfg: StewardConfig, text: str) -> None:
    lists = privacy.load(root, cfg)
    if any(source.errors or source.state not in ("ok", "empty") for source in lists):
        raise IssueError("the report could not be screened against the project's term lists")
    terms = [term for source in lists for term in source.terms]
    hits, _ = privacy.scan_text(text, terms, local_paths=True, honour_marker=False)
    if hits:
        raise IssueError("report refused by the project's term or local-path screen; use generic wording")


def _report_fields(text: str | None, last: LastError | None) -> tuple[str, str, str, str]:
    if last is None:
        text = (text or "").strip()
        if not text or any(not ch.isprintable() and ch not in "\n\t" for ch in text):
            raise IssueError("provide a nonempty issue description in plain text")
        key = sha256_bytes(("text:" + " ".join(text.split())).encode("utf-8"))
        return key, text.splitlines()[0][:120], text, __version__
    invoked = " ".join([last.command, *last.flags])
    context = [f"Error type: {last.error_type}", f"Command and flags: `{invoked}`", f"Exit: {last.exit_code}"]
    context.extend(f"- `{frame.file}:{frame.line}`" for frame in last.frames)
    return last.fingerprint, "Toolkit fault", "\n".join(context), last.tool_version


def _self_reports(root: Path, place: str) -> Iterator[tuple[exchange.Item, str, bytes]]:
    folder = exchange.guard(root, place)
    for path in sorted(folder.glob("*.md")):
        try:
            raw = _read_regular(root, path.relative_to(root), 1 << 20)
            head, body = exchange.parse(raw.decode("utf-8"))
            item = exchange.Item.model_validate(head)
        except (OSError, ValueError):
            continue
        marker = MARKER.fullmatch(body.partition("\n")[0])
        if item.kind == "defect" and item.id == path.stem and marker and re.fullmatch(VERSION, item.against or ""):
            yield item, marker[1], raw


class _IssueClosed(Exception):
    pass


def _seen_again(root: Path, cfg: StewardConfig, item: exchange.Item, key: str, version: str,
                previous: bytes) -> bool | None:
    def decide(entries):
        current = next((e["state"] for e in reversed(entries) if e.get("kind") == "state" and
                        e.get("item") == item.id), None)
        if current in FINISHED:
            raise _IssueClosed
        if current is None:
            # A process may have stopped after writing the file but before appending the filed state.
            _screen(root, cfg, previous.decode("utf-8"))
            return "state", {"item": item.id, "state": "filed", "from_state": None, "note": "", "by": item.from_}
        return "issue_seen_again", {"item": item.id, "fingerprint": key, "version": version, "note": "seen again"}

    try:
        entry = exchange.ledger(root, cfg.steward.repo_id).transaction(decide)
    except _IssueClosed:
        return None
    return entry["kind"] == "issue_seen_again"


def file_issue(root: Path, cfg: StewardConfig, text: str | None, last: LastError | None) -> tuple[str, bool]:
    from .cockpit import TOOLKIT_CODE

    if cfg.exchange is None:
        raise IssueError('add an [exchange] table with code = "ABC" to steward.toml')
    sender = cfg.exchange.code
    recipient = cfg.report.to if cfg.report else TOOLKIT_CODE
    if sender == recipient:
        raise IssueError("the report recipient must differ from the sender; set [report] to in steward.toml")
    key, title, description, version = _report_fields(text, last)
    _screen(root, cfg, description)
    if any(not exchange.guard(root, sub).is_dir() for sub in exchange.SUBDIRS):
        raise IssueError("run steward exchange init before filing a report")

    lock = owner_lock(root, "issue")
    if lock is None:
        raise IssueError("could not lock issue reporting; retry after any other report finishes")
    try:
        exchange.ledger_ok(root)
        for item, item_key, previous in _self_reports(root, "outbox"):
            if (item.from_, item.to, item_key) == (sender, recipient, key):
                repeated = _seen_again(root, cfg, item, key, version, previous)
                if repeated is not None:
                    return item.id, repeated

        peers, _ = exchange.discover_peers(root, cfg.exchange, recipients={recipient})
        item_id = exchange.next_id(root, sender, "defect", peers)
        fields = {"schema": "steward.exchange/1", "id": item_id, "kind": "defect", "from": sender, "to": recipient,
                  "title": title, "filed": date.today(), "against": version}
        body = f"Toolkit issue fingerprint: {key}\n\n## Report\n\n{description}\n"
        text = exchange.render(fields, body)
        _screen(root, cfg, text)
        data = text.encode("utf-8")
        if len(data) > 1 << 20:  # the exchange pull's item size limit
            raise IssueError("the report is too large for exchange")
        exchange.file_outbox(root, cfg.steward.repo_id, exchange.Item.model_validate(exchange.parse(text)[0]), data)
        return item_id, False
    finally:
        release_owner_lock(root, "issue", lock)


def filed_dates(root: Path, code: str) -> dict[str, str]:
    """X05: each received report's ID -> the date it was filed (for the text view's newest-first order)."""
    return {item.id: str(item.filed) for item, _key, _raw in _self_reports(root, "inbox")
            if item.to == code and getattr(item, "filed", None)}


def inbox(root: Path, code: str) -> list[dict]:
    exchange.ledger_ok(root)
    history = exchange.states(root)
    groups = {}
    for item, key, raw in _self_reports(root, "inbox"):
        if item.to != code or item.from_ == code or exchange.receipt_sha(history.get(item.id, [])) != sha256_bytes(raw):
            continue
        groups.setdefault(key, []).append(item)
    return [
        {"fingerprint": key, "count": len(items), "versions": sorted({item.against for item in items}),
         "projects": sorted({item.from_ for item in items}), "items": sorted(item.id for item in items)}
        for key, items in sorted(groups.items())
    ]
