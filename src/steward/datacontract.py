"""R-83. Check declared tables one record at a time with local, deterministic rules."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

from .models import DataContract, SampleSheet
from .records import RecordRefused, open_rel
from .rules import Ctx, result
from .status import Result, Status, combine

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
_INFINITY = re.compile(r"[+-]?inf(?:inity)?", re.IGNORECASE | re.ASCII)
_IDENTIFIERS = {
    "ensembl": re.compile(r"ENS[A-Z]*G[0-9]{11}(?:\.[1-9][0-9]*)?"),
    "entrez": re.compile(r"[1-9][0-9]*"),
    "hgnc": re.compile(r"(?=[A-Z0-9-]*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)*|C(?:[0-9]+|X|Y)orf[0-9]+"),
}
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_EXCEL_DATE = re.compile(
    rf"(?:[0-9]{{1,2}}[-/ ]{_MONTH}|{_MONTH}[-/ ][0-9]{{1,2}})(?:[-/ ][0-9]{{2,4}})?"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}", re.IGNORECASE | re.ASCII,
)
_BEGIN = ["!series_matrix_table_begin"]
_END = ["!series_matrix_table_end"]


class _DigestReader(io.RawIOBase):
    def __init__(self, stream: BinaryIO):
        super().__init__()
        self.stream = stream
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        size = self.stream.readinto(buffer)
        self.digest.update(memoryview(buffer)[:size])
        return size


class _FormatError(ValueError):
    def __init__(self, row: int | None, message: str):
        super().__init__(message)
        self.row = row


def _rows(stream: io.TextIOWrapper, format_: str) -> Iterator[tuple[int, list[str]]]:
    reader = csv.reader(stream, delimiter="," if format_ == "csv" else "\t", strict=True)
    is_series = format_ == "series_matrix"
    started = ended = False
    while True:
        row = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise _FormatError(row, f"The delimited record cannot be read: {exc}.") from None
        if not is_series:
            yield row, cells
        elif cells == _BEGIN:
            if started:
                raise _FormatError(row, "Expected one series matrix table.")
            started = True
        elif cells == _END:
            if not started or ended:
                raise _FormatError(row, "The series matrix end marker has no open table.")
            ended = True
        elif started and not ended:
            yield row, cells
    if is_series and not ended:
        marker = "end" if started else "begin"
        raise _FormatError(reader.line_num + 1, f"The series matrix {marker} marker is missing.")


@dataclass
class _Scan:
    path: str
    details: list[dict] = field(default_factory=list)
    samples: dict[str, tuple[int, int]] = field(default_factory=dict)
    status: Status = Status.PASS
    evidence: list[dict[str, str]] = field(default_factory=list)

    def add(self, code: str, row: int | None, column: int | None, message: str,
            status: Status = Status.FAIL) -> None:
        self.status = combine([self.status, status])
        self.details.append({"code": code, "path": self.path, "row": row, "column": column, "message": message})


def _number(value: str) -> Decimal | None:
    if _NUMBER.fullmatch(value):
        try:
            return Decimal(value)
        except InvalidOperation:
            pass
    return None


def _integral(value: Decimal) -> bool:
    return value == value.to_integral_value()


def _check_type(scan: _Scan, row: int, column: int, value: str, kind: str, number: Decimal | None) -> None:
    if kind in _IDENTIFIERS:
        if kind == "hgnc" and _EXCEL_DATE.fullmatch(value):
            scan.add("R-83.excel_date", row, column,
                     f"{value[:40]!r} looks like a spreadsheet date: check the original gene symbol")
        elif not _IDENTIFIERS[kind].fullmatch(value):
            scan.add("R-83.identifier", row, column, f"{value[:40]!r} is not an identifier in {kind} format")
    elif (kind == "number" and number is None
          or kind == "integer" and (number is None or not _integral(number))
          or kind == "boolean" and value not in ("true", "false")):
        scan.add("R-83.type", row, column, f"Expected a value of type {kind}.")


def _header(scan: _Scan, rows: Iterator[tuple[int, list[str]]], required: set[str]) -> tuple[int, list[str]] | None:
    record = next(rows, None)
    if record is None:
        scan.add("R-83.header", None, None, "The table has no header.")
        return None
    row, header = record
    if not header:
        scan.add("R-83.header", row, 1, "The header row is empty.")
    seen: set[str] = set()
    for column, name in enumerate(header, 1):
        if not name.strip() or "\x00" in name:
            scan.add("R-83.header", row, column, "Give this column a valid name.")
        elif name in seen:
            scan.add("R-83.header", row, column, "Give this column a unique name.")
        seen.add(name)
    for name in sorted(required - seen):
        scan.add("R-83.missing_column", row, None, f"The declared column {name!r} is missing.")
    return record if scan.status == Status.PASS else None


def _body(scan: _Scan, rows: Iterator[tuple[int, list[str]]], width: int) -> Iterator[tuple[int, list[str]]]:
    for row, cells in rows:
        if len(cells) != width:
            scan.add("R-83.row_width", row, min(len(cells), width) + 1,
                     f"Expected {width} columns and found {len(cells)}.")
        else:
            yield row, cells


def _unique_id(scan: _Scan, ids: dict[str, tuple[int, int]], value: str, row: int, column: int,
               missing: set[str]) -> None:
    if value in missing or not value.strip() or "\x00" in value:
        scan.add("R-83.missing_id", row, column, "Supply an identifier for this row.")
    elif value in ids:
        first_row, _ = ids[value]
        scan.add("R-83.duplicate_id", row, column, f"This identifier also occurs on row {first_row}.")
    else:
        ids[value] = (row, column)


def _table(scan: _Scan, rows: Iterator[tuple[int, list[str]]], spec: DataContract, missing: set[str]) -> None:
    counts = set(spec.raw_counts)
    p_columns = {spec.p_value, spec.adjusted_p_value} - {None}
    numeric = counts | p_columns | {spec.log_fold_change}
    metadata = {spec.id_column, *spec.metadata_columns}
    required = (set(spec.columns) | numeric | metadata) - {None}
    record = _header(scan, rows, required)
    if record is None:
        return
    header_row, header = record
    positions = {name: col for col, name in enumerate(header, 1)}
    if spec.sample_sheet is not None:
        scan.samples = {name: (header_row, positions[name]) for name in header if name not in metadata}
        if not scan.samples:
            scan.add("R-83.no_samples", header_row, None, "The matrix has no sample columns.")
    ids: dict[str, tuple[int, int]] = {}
    first_na: str | None = None
    zeros: dict[str, tuple[int, int, int]] = {}  # 0.20.2: column -> (first row, column, count) of p = 0
    pairs = differ = 0                            # rows with both p-values; rows where they differ
    for row, cells in _body(scan, rows, len(header)):
        p_values: dict[str, Decimal] = {}
        for column, (name, value) in enumerate(zip(header, cells), 1):
            if "\x00" in value:
                scan.add("R-83.invalid_cell", row, column, "Remove the NUL character from this cell.")
                continue
            if name == spec.id_column:
                _unique_id(scan, ids, value, row, column, missing)
            if value in missing:
                if first_na is None:
                    first_na = value
                elif value != first_na:
                    scan.add("R-83.mixed_na", row, column, "Use the same missing-value token throughout the table.")
                continue

            kind = spec.columns.get(name)
            number = _number(value) if name in numeric or kind in ("number", "integer") else None
            if kind is not None:
                _check_type(scan, row, column, value, kind, number)
            if name in counts and (number is None or number < 0 or not _integral(number)):
                scan.add("R-83.raw_count", row, column, "Expected a nonnegative integer count.")
            if name in p_columns:
                if number is None or not 0 <= number <= 1:
                    scan.add("R-83.p_value", row, column, "Expected a p-value between zero and one, inclusive.")
                else:
                    p_values[name] = number
                    if number == 0:
                        r0, c0, n0 = zeros.get(name, (row, column, 0))
                        zeros[name] = (r0, c0, n0 + 1)
            if name == spec.log_fold_change and number is None:
                if _INFINITY.fullmatch(value):
                    scan.add("R-83.infinite_lfc", row, column, "Check the source of the infinite log fold change.")
                else:
                    scan.add("R-83.log_fold_change", row, column, "Expected a finite log fold change.")

        raw, adjusted = spec.p_value, spec.adjusted_p_value
        if raw in p_values and adjusted in p_values and p_values[adjusted] < p_values[raw]:
            scan.add("R-83.p_order", row, positions[adjusted], "The adjusted p-value is below the raw p-value.")
        if raw in p_values and adjusted in p_values:
            pairs += 1
            differ += p_values[raw] != p_values[adjusted]
    for name, (r0, c0, n0) in zeros.items():  # 0.20.2 (STW-040): an underflow reported as zero
        scan.add("R-83.p_zero", r0, c0, f"{n0} p-value(s) of exactly 0 in {name!r}: an underflow; report them as below "
                 "the smallest value the method can give", Status.INCOMPLETE)
    if pairs >= 3 and not differ:
        scan.add("R-83.adjusted_equals_raw", None, positions.get(spec.adjusted_p_value),
                 f"the adjusted p-value equals the raw one on all {pairs} rows: was the raw column reported as adjusted?")


def _sheet(scan: _Scan, rows: Iterator[tuple[int, list[str]]], spec: SampleSheet, missing: set[str]) -> None:
    record = _header(scan, rows, {spec.id_column})
    if record is None:
        return
    _, header = record
    column = header.index(spec.id_column) + 1
    for row, cells in _body(scan, rows, len(header)):
        _unique_id(scan, scan.samples, cells[column - 1], row, column, missing)


def _alignment(table: _Scan, sheet: _Scan) -> None:
    for name, (row, column) in sheet.samples.items():
        if name not in table.samples:
            sheet.add("R-83.sample_not_in_matrix", row, column, "This sample has no matrix column.")
    for name, (row, column) in table.samples.items():
        if name not in sheet.samples:
            table.add("R-83.sample_not_in_sheet", row, column, "This column has no sample sheet row.")
    if table.samples.keys() == sheet.samples.keys():
        for sample, header in zip(sheet.samples, table.samples):
            if sample != header:
                row, column = sheet.samples[sample]
                sheet.add("R-83.sample_order", row, column, "Put the samples in matrix column order.")
                break


def _scan(ctx: Ctx, spec: DataContract | SampleSheet, missing: set[str]) -> _Scan:
    scan = _Scan(spec.path)
    try:
        with open_rel(ctx.root, spec.path) as source:
            before = os.fstat(source.fileno())
            if before.st_nlink != 1:
                raise RecordRefused(0, "multiple hard links", "link")
            raw = _DigestReader(source)
            with io.BufferedReader(raw) as binary, io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
                rows = _rows(text, spec.format)
                try:
                    if isinstance(spec, DataContract):
                        _table(scan, rows, spec, missing)
                    else:
                        _sheet(scan, rows, spec, missing)
                    # Check format markers even if the header was rejected.
                    for _ in rows:
                        pass
                except _FormatError as exc:
                    scan.add("R-83.format", exc.row, None, str(exc))
                except UnicodeDecodeError:
                    scan.add("R-83.encoding", None, None, "Save the table as UTF-8.")
                while binary.read(1 << 20):
                    pass
            after = os.fstat(source.fileno())
        digest = raw.digest.hexdigest()
        if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or ctx.inputs.get(spec.path, digest) != digest):
            raise RecordRefused(0, "changed while checking", "changed")
        ctx.inputs[spec.path] = digest
        scan.evidence = ctx.evidence(spec.path)
    except RecordRefused as exc:
        if exc.reason == "missing":
            scan.add("R-83.missing_file", None, None, "Supply the declared file.", Status.INCOMPLETE)
        elif exc.reason == "changed":
            scan.add("R-83.unreadable", None, None, "The file changed during this check. Run the check again.",
                     Status.UNKNOWN)
        else:
            scan.add("R-83.refused", None, None, "Use a regular file with no symbolic or additional hard links.")
    except OSError:
        scan.add("R-83.unreadable", None, None, "The declared file could not be read.", Status.UNKNOWN)
    return scan


def check_contracts(ctx: Ctx) -> list[Result]:
    if ctx.config is None or ctx.config.data is None or not ctx.config.data.contract:
        return [result("R-83", ".", Status.NOT_APPLICABLE, "no data contracts declared")]

    results = []
    for spec in ctx.config.data.contract:
        missing = set(spec.na_values)
        table = _scan(ctx, spec, missing)
        scans = [table]
        if spec.sample_sheet is not None:
            sheet = _scan(ctx, spec.sample_sheet, missing)
            scans.append(sheet)
            if table.samples and sheet.status == Status.PASS and table.evidence:
                _alignment(table, sheet)
        status = combine([scan.status for scan in scans])
        reason = {
            Status.PASS: "table meets the declared contract",
            Status.FAIL: "table contract findings need attention",
            Status.INCOMPLETE: "a declared file is missing, or a value needs checking (see the details)",
            Status.UNKNOWN: "a declared file could not be checked",
        }[status]
        results.append(result("R-83", spec.path, status, reason,
                              [d for scan in scans for d in scan.details],
                              [e for scan in scans for e in scan.evidence]))
    return results
