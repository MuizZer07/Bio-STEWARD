"""Bounded local checks of study inputs against a chromosome-sizes table."""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from .records import open_rel

MAX_SIZES = 8 << 20
MAX_SCAN = 256 << 20
MAX_LINE = 1 << 20


class PreflightError(ValueError):
    def __init__(self, message: str, row: int | None = None):
        super().__init__(message)
        self.row = row


class _ReadBudget(io.RawIOBase):
    """Bound raw reads too, including gzip headers and runs of empty gzip members."""

    def __init__(self, source: BinaryIO, limit: int):
        self.source = source
        self.remaining = limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        count = self.source.readinto(memoryview(buffer)[:self.remaining + 1])
        if count > self.remaining:
            raise PreflightError("raw byte limit exceeded")
        self.remaining -= count
        return count


@contextmanager
def _input(root: Path, path: str) -> Iterator[io.BufferedReader]:
    with open_rel(root, path) as source, io.BufferedReader(_ReadBudget(source, MAX_SCAN)) as raw:
        if raw.peek(2).startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=raw) as compressed, io.BufferedReader(compressed) as stream:
                yield stream
        else:
            yield raw


def input_kind(path: str) -> str:
    suffix = Path(path.lower().removesuffix(".gz").removesuffix(".bgz").removesuffix(".bgzf")).suffix
    return suffix if suffix in {".vcf", ".sam", ".bed"} else ""


def _lines(stream: io.BufferedReader, limit: int, prefix: bytes = b"") -> Iterator[tuple[int, bytes]]:
    row = 0
    remaining = limit
    while stream.peek(1).startswith(prefix):
        raw = stream.readline(min(MAX_LINE, remaining) + 1)
        if not raw:
            return
        row += 1
        if len(raw) > remaining:
            raise PreflightError(f"scan exceeds {limit} bytes", row)
        if len(raw) > MAX_LINE:
            raise PreflightError(f"line exceeds {MAX_LINE} bytes", row)
        remaining -= len(raw)
        yield row, raw


def _integer(text: str) -> int:
    digits = text.lstrip("0") or "0"
    if len(digits) > 20 or not re.fullmatch(r"[0-9]+", text):
        raise ValueError("expected a nonnegative decimal integer of at most 20 significant digits")
    return int(digits)


def chromosome_sizes(root: Path, path: str) -> tuple[dict[str, int], str]:
    sizes: dict[str, int] = {}
    digest = hashlib.sha256()
    with open_rel(root, path) as raw, io.BufferedReader(raw) as stream:
        for row, line in _lines(stream, MAX_SIZES):
            digest.update(line)
            try:
                text = line.decode("utf-8").strip()
                if not text or text.startswith("#"):
                    continue
                name, length = text.split()
                size = _integer(length)
                if size == 0:
                    raise ValueError("contig length must be positive")
                if name in sizes:
                    raise ValueError(f"duplicate contig {name!r}")
            except ValueError as exc:
                raise PreflightError(f"expected a contig name and positive length ({exc})", row) from exc
            sizes[name] = size
    if not sizes:
        raise PreflightError("the chromosome-sizes file has no contigs")
    return sizes, digest.hexdigest()


_VCF_FIELD = re.compile(r'([^=,\s]+)=("(?:[^"\\]|\\.)*"|[^",]*)(,|$)')
_BED_DIRECTIVE = re.compile(r"^\s*(?:track\s+\w+=|browser\s+(?:position|hide|dense|pack|squish|full)\s)")


def _vcf_contig(line: str) -> tuple[str, str | None]:
    if not line.startswith("##contig=<") or not line.endswith(">"):
        raise ValueError("expected ##contig=<ID=…,length=…>")
    text = line[len("##contig=<"):-1]
    fields = {}
    pos = 0
    while pos < len(text):
        match = _VCF_FIELD.match(text, pos)
        if match is None or match[1] in fields or (match[3] and match.end() == len(text)):
            raise ValueError("malformed or repeated ##contig field")
        fields[match[1]] = match[2]
        pos = match.end()
    if not fields.get("ID") or re.search(r'["\s]', fields["ID"]):
        raise ValueError("##contig needs an ID")
    return fields["ID"], fields.get("length")


def _sam_contig(line: str) -> tuple[str, str]:
    fields = [field for field in line.split("\t")[1:] if field.startswith(("SN:", "LN:"))]
    values = {field[:2]: field[3:] for field in fields}
    if len(fields) != 2 or not values.get("SN") or not values.get("LN"):
        raise ValueError("@SQ needs one SN and one LN field")
    return values["SN"], values["LN"]


def _compare(stream: io.BufferedReader, kind: str, sizes: dict[str, int]) -> tuple[int | None, str] | None:
    prefix = {".vcf": b"#", ".sam": b"@", ".bed": b""}[kind]
    seen: set[str] = set()
    missing_length = None
    for row, raw in _lines(stream, MAX_SCAN, prefix):
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
            if kind == ".vcf":
                if line.startswith("#CHROM\t"):
                    break
                if not line.startswith("##contig="):
                    continue
                name, length = _vcf_contig(line)
            elif kind == ".sam":
                if line != "@SQ" and not line.startswith("@SQ\t"):
                    continue
                name, length = _sam_contig(line)
            else:
                parts = line.split(None, 3)
                if not parts or parts[0].startswith("#") or _BED_DIRECTIVE.match(line):
                    continue
                if len(parts) < 3:
                    raise ValueError("BED row needs a contig, start and end")
                name, start, length = parts[:3]
                if _integer(start) > _integer(length):
                    raise ValueError("BED start exceeds end")
            expected = sizes.get(name)
            if expected is None:
                raise ValueError(f"contig {name!r} is absent from the chromosome-sizes file")
            if kind != ".bed" and name in seen:
                raise ValueError(f"duplicate header contig {name!r}")
            seen.add(name)
            if length is None:
                if missing_length is None:
                    missing_length = (row, f"contig {name!r} has no length in its VCF header")
                continue
            actual = _integer(length)
            if kind == ".bed" and actual > expected:
                raise ValueError(f"contig {name!r} interval end {actual} exceeds reference length {expected}")
            if kind != ".bed" and actual != expected:
                raise ValueError(f"contig {name!r} has header length {actual}, reference length {expected}")
        except ValueError as exc:
            raise PreflightError(str(exc), row) from exc
    if not seen:
        return None, f"no contigs found in the {kind[1:].upper()} {'rows' if kind == '.bed' else 'header'}"
    return missing_length


def check_input(root: Path, path: str, kind: str, sizes: dict[str, int]) -> tuple[int | None, str] | None:
    try:
        with _input(root, path) as stream:
            return _compare(stream, kind, sizes)
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise PreflightError("cannot read compressed genomic text") from exc
