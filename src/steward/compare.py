"""Compare tabular outputs of recorded runs and check shadow stages."""

from __future__ import annotations

import csv
import errno
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from .fsutil import canonical_json, escapes_root, open_dir_beneath, safe_write, sha256_bytes
from .ledger import verify_bytes
from .models import Hex64, RunSection, SafePath, StewardConfig, Strict
from .records import RecordId, RecordRefused, read_rel

if TYPE_CHECKING:
    from .rules import Ctx, Result

NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
DELIMITERS = {".csv": ",", ".tsv": "\t"}
UTC_TIME = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


class RunOutput(Strict):
    run: str
    outcome: Hex64
    seq: int = Field(gt=0)
    path: SafePath
    sha256: Hex64


class Agreement(Strict):
    equal: int = Field(ge=0)
    different: int = Field(ge=0)
    only_a: int = Field(ge=0)
    only_b: int = Field(ge=0)

    @property
    def total(self) -> int:
        return self.equal + self.different + self.only_a + self.only_b


class Disagreement(Strict):
    key: str
    a: str | None
    b: str | None


class ClassCount(Strict):
    a: int = Field(default=0, ge=0)
    b: int = Field(default=0, ge=0)
    equal: int = Field(default=0, ge=0)


class Comparison(Strict):
    schema_: Literal["steward.compare/1"] = Field(alias="schema")
    name: RecordId
    a: RunOutput
    b: RunOutput
    completed: Annotated[str, Field(pattern=f"^{UTC_TIME}$")]
    key: str
    value: str
    agreement: Agreement
    disagreements: list[Disagreement]
    classes: dict[str, ClassCount]

    def document(self) -> bytes:
        return canonical_json(self.model_dump(by_alias=True)).encode("utf-8")

    @property
    def order(self) -> tuple[int, int]:
        return self.b.seq, self.a.seq


@dataclass
class Saved:
    path: str
    digest: str
    comparison: Comparison


class CompareError(ValueError):
    pass


def folder(cfg: StewardConfig) -> str:
    base = cfg.paths.records
    if not base or escapes_root(base):
        raise CompareError("the records directory must be inside the repository")
    return (Path(base) / "comparisons").as_posix()


def _readable_path(rel: str) -> bool:
    return bool(Path(rel).parts) and not escapes_root(rel) and "\x00" not in rel


def _read_source(root, cfg, rel, read):
    from .integrity import sealed_owner

    def optional(path: str) -> bytes | None:
        if not _readable_path(path):
            raise CompareError("a source path must be inside the repository")
        try:
            return read(path)
        except RecordRefused as exc:
            if exc.reason != "missing":
                raise
            return None

    if sealed_owner(root, cfg, rel, read=optional):
        raise CompareError(f"{rel} belongs to a sealed dataset")
    data = optional(rel)
    if data is None:
        raise CompareError(f"{rel} is missing")
    return data


def _runs(root, cfg, read):
    path = (cfg.run or RunSection()).ledger
    ledger = verify_bytes(_read_source(root, cfg, path, read))
    header = ledger.entries[0] if ledger.entries else {}
    if (ledger.errors or ledger.torn_tail or header.get("kind") != "genesis" or header.get("ledger") != "runs"
            or header.get("repo_id") != cfg.steward.repo_id):  # AN5: this repository's run ledger, and no other
        raise CompareError(f"{path} is not this repository's intact run ledger")
    by_id = {}
    for entry in ledger.entries[1:]:
        run = entry.get("run")
        if isinstance(run, str) and entry.get("kind") in ("started", "outcome", "interrupted"):
            by_id.setdefault(run, []).append(entry)
    return by_id


def _output(runs, run: str, path: str | None) -> tuple[RunOutput, str]:
    entries = runs.get(run, [])
    if (len(entries) != 2 or entries[0].get("kind") != "started" or entries[1].get("kind") != "outcome"
            or entries[1].get("status") != "finished" or entries[1].get("exit_code") != 0):
        raise CompareError(f"run {run!r} needs one start and one successful outcome")
    outcome = entries[1]
    outputs = outcome.get("outputs")
    if not isinstance(outputs, dict):
        raise CompareError(f"run {run!r} has no recorded outputs")
    tables = sorted(rel for rel in outputs if Path(rel).suffix.lower() in DELIMITERS)
    if path is None:
        if len(tables) != 1:
            raise CompareError(f"run {run!r} needs one recorded CSV or TSV output, or an explicit --output-a or --output-b")
        path = tables[0]
    digest = outputs.get(path)
    if path not in tables or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CompareError(f"run {run!r} has no recorded CSV or TSV digest for {path!r}")
    time = outcome.get("time")
    if not isinstance(time, str) or not re.fullmatch(UTC_TIME, time):
        raise CompareError(f"run {run!r} has no UTC completion time")
    datetime.fromisoformat(time)
    return RunOutput(run=run, outcome=outcome["hash"], seq=outcome["seq"], path=path, sha256=digest), time


def _table(root, cfg, ref: RunOutput, key: str, value: str | None, read) -> tuple[str, dict[str, str]]:
    data = _read_source(root, cfg, ref.path, read)
    if sha256_bytes(data) != ref.sha256:
        raise CompareError(f"{ref.path}: output digest changed since run {ref.run!r}")
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""),
                            delimiter=DELIMITERS[Path(ref.path).suffix.lower()], strict=True)
        header = next(reader, [])
        if any(not column.strip() for column in header):
            raise CompareError(f"{ref.path}: empty column name")
        if len(set(header)) != len(header):
            raise CompareError(f"{ref.path}: duplicate column name")
        if key not in header:
            raise CompareError(f"{ref.path}: no key column {key!r}")
        if value is None:
            other = [column for column in header if column != key]
            if len(other) != 1:
                raise CompareError(f"{ref.path}: specify the class column with --value")
            value = other[0]
        if value == key or value not in header:
            raise CompareError(f"{ref.path}: choose a class column distinct from the key")
        key_index, value_index = header.index(key), header.index(value)
        rows = {}
        for row in reader:
            if len(row) != len(header):
                raise CompareError(f"{ref.path}: line {reader.line_num} has the wrong number of columns")
            item = row[key_index]
            if not item.strip():
                raise CompareError(f"{ref.path}: empty key on line {reader.line_num}")
            if item in rows:
                raise CompareError(f"{ref.path}: duplicate key on line {reader.line_num}")
            rows[item] = row[value_index]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CompareError(f"{ref.path}: could not read the UTF-8 table") from exc
    return value, rows


def _compare(root, cfg, runs, name, run_a, run_b, key, value, output_a, output_b, read) -> Comparison:
    if run_a == run_b:
        raise CompareError("choose two distinct runs")
    a, time_a = _output(runs, run_a, output_a)
    b, time_b = _output(runs, run_b, output_b)
    if not key.strip() or (value is not None and not value.strip()):
        raise CompareError("column names must be nonempty")
    value, rows_a = _table(root, cfg, a, key, value, read)
    _, rows_b = _table(root, cfg, b, key, value, read)
    agreement = Agreement(equal=0, different=0, only_a=0, only_b=0)
    classes: dict[str, ClassCount] = {}
    disagreements = []
    for item in sorted(rows_a.keys() | rows_b.keys()):
        left, right = rows_a.get(item), rows_b.get(item)
        if left is not None:
            classes.setdefault(left, ClassCount()).a += 1
        if right is not None:
            classes.setdefault(right, ClassCount()).b += 1
        if left == right:
            agreement.equal += 1
            classes[left].equal += 1
            continue
        if left is None:
            agreement.only_b += 1
        elif right is None:
            agreement.only_a += 1
        else:
            agreement.different += 1
        disagreements.append(Disagreement(key=item, a=left, b=right))
    if not agreement.total:
        raise CompareError("the two output tables have no rows")
    return Comparison(schema="steward.compare/1", name=name, a=a, b=b, completed=max(time_a, time_b),
                      key=key, value=value, agreement=agreement, disagreements=disagreements, classes=classes)


def _list(root: Path, rel: str) -> list[str]:
    try:
        fd = open_dir_beneath(root, Path(rel).parts)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return []
        raise
    try:
        return sorted(os.listdir(fd))
    finally:
        os.close(fd)


def history(root, cfg, name=None, *, read=None) -> list[Saved]:
    read = read or (lambda rel: read_rel(root, rel))
    base = folder(cfg)
    names = [name] if name is not None else [entry for entry in _list(root, base) if NAME.fullmatch(entry)]
    found = []
    for name in names:
        for file in _list(root, f"{base}/{name}"):
            if not file.endswith(".json"):
                continue
            rel = f"{base}/{name}/{file}"
            try:
                raw = _read_source(root, cfg, rel, read)
                digest = sha256_bytes(raw)
                if file != f"{digest}.json":
                    raise CompareError("the digest does not match the file name")
                doc = Comparison.model_validate_json(raw)
                if doc.name != name or doc.agreement.total == 0:
                    raise CompareError("the name or row count does not match the record format")
            except (OSError, ValueError, RecursionError) as exc:
                raise CompareError(f"{rel}: invalid comparison record") from exc
            found.append(Saved(rel, digest, doc))
    return found


def command(args) -> int:
    import sys

    from .cli import EXIT_DATAERR, EXIT_OK, EXIT_USAGE, _config

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if not NAME.fullmatch(args.name):
        print("steward: use a comparison name matching [a-z0-9][a-z0-9._-]{0,63}", file=sys.stderr)
        return EXIT_USAGE
    try:
        @cache
        def read(rel: str) -> bytes:
            return read_rel(root, rel)

        runs = _runs(root, cfg, read)
        doc = _compare(root, cfg, runs, args.name, args.a, args.b, args.key, args.value,
                       args.output_a, args.output_b, read)
        data = doc.document()
        rel = f"{folder(cfg)}/{args.name}/{sha256_bytes(data)}.json"
        try:
            existing = read(rel)
        except RecordRefused as exc:
            if exc.reason != "missing":
                raise
            safe_write(root, rel, data)
        else:
            if existing != data:
                raise CompareError(f"{rel}: existing comparison record has changed")
    except (OSError, ValueError, RecursionError) as exc:
        print(f"steward: {exc}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"recorded {rel}: {doc.agreement.equal}/{doc.agreement.total} keys agree")
    return EXIT_OK


def r84(ctx: Ctx) -> list[Result]:
    from .rules import Status, result

    cfg = ctx.config
    assert cfg is not None
    names = sorted({stage.name for stage in cfg.stages if stage.shadow})
    if not names:
        return [result("R-84", ".", Status.NOT_APPLICABLE, "no shadow stages declared")]

    snapshot = {}

    def read(rel: str) -> bytes:
        if rel not in snapshot:
            snapshot[rel] = read_rel(ctx.root, rel)
            ctx.inputs[rel] = sha256_bytes(snapshot[rel])
        return snapshot[rel]

    findings = []
    runs = None
    for name in names:
        try:
            records = history(ctx.root, cfg, name, read=read)
        except (CompareError, OSError) as exc:
            findings.append(result("R-84", name, Status.INCOMPLETE, "comparison history could not be read",
                                   [{"code": "R-84.invalid", "message": str(exc)}]))
            continue
        if not records:
            findings.append(result("R-84", name, Status.INCOMPLETE, "no comparison recorded for this shadow stage",
                                   [{"code": "R-84.missing"}]))
            continue
        latest = max(saved.comparison.order for saved in records)
        details, evidence = [], []
        current = False
        for saved in records:
            doc = saved.comparison
            if doc.order != latest:
                continue
            try:
                if runs is None:
                    runs = _runs(ctx.root, cfg, read)
                actual = _compare(ctx.root, cfg, runs, name, doc.a.run, doc.b.run, doc.key, doc.value,
                                  doc.a.path, doc.b.path, read)
                if actual != doc:
                    raise CompareError("the record does not match the run evidence")
            except (OSError, ValueError, RecursionError) as exc:
                details.append({"code": "R-84.stale", "path": saved.path, "message": str(exc)})
            else:
                current = True
            for rel in (saved.path, (cfg.run or RunSection()).ledger, doc.a.path, doc.b.path):
                for item in ctx.evidence(rel):
                    if item not in evidence:
                        evidence.append(item)
        current = current and not details  # AN6: one stale comparison of the latest pair makes the stage stale
        findings.append(result("R-84", name, Status.PASS if current else Status.INCOMPLETE,
                               "comparison is current" if current else "comparison is stale",
                               details, evidence))
    return findings
