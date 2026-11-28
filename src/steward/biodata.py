"""Public biological data (0.20.0): fetch with provenance (B1), conventions (B3) and sample metadata (B4).

- **Fetch** (`steward data fetch SOURCE:ACCESSION --study ID`): resolves an accession to the files its archive
  serves (GEO series matrices and supplementary files, ENA/SRA runs, ArrayExpress/BioStudies files, Zenodo records, a
  plain URL), downloads them into the repository (resuming a partial download), checks the checksum the archive
  publishes when it publishes one (ENA and Zenodo md5) and the size, and records accession, URL, retrieval date,
  size and sha256 in the study record. A mismatch refuses and records nothing. This command is the only one here that
  reaches the network; checks stay offline.
- **Conventions** (B3): what a file's chromosome names say (`chr1`, `1`, `NC_000001.11`) against the naming the
  study declares; an input whose declared organism, genome, coordinate base or naming differs from its study's.
- **Sample metadata** (B4): a sample sheet with required fields and allowed values, and every sample of a matrix
  present in the sheet and the reverse.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .fsutil import LinkRefused, escapes_root, open_at, open_dir_beneath, write_all

USER_AGENT = "bio-steward-data-fetch"
TIMEOUT = 60
CHUNK = 1 << 20


def _urlopen(req: urllib.request.Request, timeout: float = TIMEOUT):  # replaced in tests: no network there
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https and ftp archives only (checked below)


@dataclass
class Remote:
    """One file an archive serves for an accession."""

    name: str
    url: str
    md5: str | None = None
    size: int | None = None
    key: str | None = None  # the archive's own name for it (a Zenodo key may hold folders)


@dataclass
class Plan:
    source: str
    accession: str | None
    files: list[Remote] = field(default_factory=list)


class FetchError(Exception):
    """A fetch that cannot go on; nothing is recorded."""


SOURCES = ("GEO", "SRA", "ENA", "ArrayExpress", "Zenodo", "URL")
_ACC = {
    "GEO": re.compile(r"^G(SE|DS)\d{1,9}$"),
    "ENA": re.compile(r"^(PRJ[EDN][A-Z]\d+|[EDS]R[APRSXZ]\d{6,}|SAM[EDN][A-Z]?\d+)$"),
    "ArrayExpress": re.compile(r"^E-[A-Z]{4}-\d+$"),
    "Zenodo": re.compile(r"^\d{1,12}$"),
}


def parse_spec(spec: str) -> tuple[str, str]:
    """('GEO', 'GSE5281') from 'GEO:GSE5281'; ('URL', url) from an https URL."""
    if re.match(r"^(https?|ftp)://", spec, re.I):
        return "URL", spec
    src, sep, acc = spec.partition(":")
    canon = {s.lower(): s for s in SOURCES} | {"sra": "ENA", "zenodo": "Zenodo", "arrayexpress": "ArrayExpress",
                                               "biostudies": "ArrayExpress"}
    s = canon.get(src.lower()) if sep else None
    if s is None:
        raise FetchError(f"{spec}: name a source and an accession, e.g. GEO:GSE5281, ENA:SRR1234567, "
                         "ArrayExpress:E-MTAB-1234, Zenodo:1234567, or an https URL")
    if s == "URL":
        return parse_spec(acc)
    acc = acc.strip()
    if not _ACC[s].match(acc):
        raise FetchError(f"{acc} is not a {s} accession")
    return s, acc


def _get(url: str, headers: dict[str, str] | None = None):
    _allowed(url)
    return _urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}))


def _allowed(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("https", "http", "ftp") or not p.hostname:
        raise FetchError(f"{url}: only https, http and ftp URLs are fetched")


def _json(url: str) -> Any:
    """An archive's JSON answer; a missing record or an unreachable archive is a FetchError, never a crash (0.20.2)."""
    import urllib.error

    try:
        with _get(url) as r:
            return json.loads(r.read(16 << 20).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise FetchError(f"{url}: the archive answered {e.code}" + (" (no such record)" if e.code == 404 else "")) from None
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"{url}: the archive cannot be reached ({getattr(e, 'reason', e)})") from None
    except ValueError:
        raise FetchError(f"{url}: the archive's answer is not JSON") from None


def _basename(url: str) -> str:
    name = PurePosixPath(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
    if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith("."):
        raise FetchError(f"{url}: no usable file name")
    return name


def geo_dir(acc: str) -> str:
    """GSE5281 -> GSE5nnn; GSE123 -> GSEnnn (the NCBI FTP layout)."""
    m = re.match(r"^(G(?:SE|DS))(\d+)$", acc)
    assert m
    return f"{m[1]}{m[2][:-3]}nnn"


def resolve(source: str, acc: str, names: list[str]) -> Plan:
    """The files to fetch. `names` picks files (GEO supplementary files, one archive file each, or a filter)."""
    if source == "URL":
        return Plan("URL", None, [Remote(_basename(acc), acc)])
    if source == "GEO":
        base = f"https://ftp.ncbi.nlm.nih.gov/geo/{'series' if acc.startswith('GSE') else 'datasets'}/{geo_dir(acc)}/{acc}"
        if not names:
            name = f"{acc}_series_matrix.txt.gz" if acc.startswith("GSE") else f"{acc}.soft.gz"
            return Plan("GEO", acc, [Remote(name, f"{base}/{'matrix' if acc.startswith('GSE') else 'soft'}/{name}")])
        return Plan("GEO", acc, [Remote(_safe_name(n), f"{base}/suppl/{urllib.parse.quote(n)}") for n in names])
    if source == "ArrayExpress":
        if not names:
            raise FetchError("ArrayExpress: name the file(s) to fetch with --file (see the study's file list)")
        return Plan("ArrayExpress", acc, [Remote(_safe_name(n), f"https://www.ebi.ac.uk/biostudies/files/{acc}/"
                                                                  f"{urllib.parse.quote(n)}") for n in names])
    if source == "ENA":
        q = urllib.parse.urlencode({"accession": acc, "result": "read_run", "format": "json",
                                    "fields": "run_accession,fastq_ftp,fastq_md5,fastq_bytes"})
        rows = _json(f"https://www.ebi.ac.uk/ena/portal/api/filereport?{q}")
        files = []
        for row in rows if isinstance(rows, list) else []:
            urls, md5s, sizes = (str(row.get(k) or "").split(";") for k in ("fastq_ftp", "fastq_md5", "fastq_bytes"))
            for i, u in enumerate(urls):  # AN8: positions stay aligned with md5s and sizes; an empty slot is skipped
                if not u:
                    continue
                url = u if "://" in u else f"https://{u}"
                md5 = md5s[i].lower() if i < len(md5s) and re.fullmatch(r"[0-9a-fA-F]{32}", md5s[i]) else None
                size = int(sizes[i]) if i < len(sizes) and sizes[i].isdigit() else None
                files.append(Remote(_basename(url), url, md5, size))
        return Plan("ENA", acc, _pick(files, names, acc))
    if source == "Zenodo":
        rec = _json(f"https://zenodo.org/api/records/{acc}")
        files = []
        for f in rec.get("files", []) if isinstance(rec, dict) else []:
            ck = str(f.get("checksum") or "")
            md5 = ck.split(":", 1)[1].lower() if ck.lower().startswith("md5:") else None  # AN8
            if md5 is not None and not re.fullmatch(r"[0-9a-f]{32}", md5):
                raise FetchError(f"Zenodo:{acc}: {f.get('key')} has a malformed md5 checksum")
            url = (f.get("links") or {}).get("self") or f"https://zenodo.org/records/{acc}/files/{f.get('key')}"
            key = str(f.get("key") or "")
            files.append(Remote(key.rsplit("/", 1)[-1], url, md5, f.get("size") if isinstance(f.get("size"), int) else None,
                                key))
        local = [r.name for r in files]
        for r in files:  # AQ5: two folders, one name: the folders become part of the local name
            if local.count(r.name) > 1 and r.key:
                r.name = r.key.replace("/", "__")
            r.name = _safe_name(r.name)
        return Plan("Zenodo", acc, _pick(files, names, acc))
    raise FetchError(f"unknown source {source}")


def _safe_name(n: str) -> str:
    if not n or "/" in n or "\\" in n or n.startswith(".") or n in ("..",):
        raise FetchError(f"{n!r}: a file name, without folders")
    return n


def _pick(files: list[Remote], names: list[str], acc: str) -> list[Remote]:
    if not files:
        raise FetchError(f"{acc}: the archive lists no files")
    if not names:
        return files
    out = [f for f in files if f.name in names or (f.key and f.key in names)]
    missing = sorted(set(names) - {f.name for f in out} - {f.key for f in out if f.key})
    if missing:
        raise FetchError(f"{acc}: no file {', '.join(missing)} (it serves {', '.join(f.name for f in files[:8])})")
    return out


def _dest_dir(root: Path, rel_dir: str) -> int:
    if escapes_root(rel_dir) or PurePosixPath(rel_dir).is_absolute():
        raise FetchError(f"{rel_dir} is outside the repository")
    parts = [p for p in PurePosixPath(rel_dir).parts if p not in ("", ".")]
    if parts and parts[0] in (".git", ".steward"):
        raise FetchError(f"{rel_dir}: not a data folder")
    try:
        return open_dir_beneath(root, parts, create=True)
    except LinkRefused as e:
        raise FetchError(f"{rel_dir}: {e}") from None


def _hash_fd(fd: int) -> tuple[str, str, int]:
    os.lseek(fd, 0, os.SEEK_SET)
    s, m, n = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    while True:
        b = os.read(fd, CHUNK)
        if not b:
            return s.hexdigest(), m.hexdigest(), n
        s.update(b)
        m.update(b)
        n += len(b)


def _open_plain(name: str, flags: int, dfd: int, rel: str) -> int:
    """A descriptor of a regular file with one link (AN1): never a link, a hard link, a FIFO or a folder."""
    import stat as _st

    fd = open_at(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dfd)
    st = os.fstat(fd)
    if not _st.S_ISREG(st.st_mode) or st.st_nlink != 1:
        os.close(fd)
        raise FetchError(f"{rel} is not a plain file (a link, a hard link, a FIFO or a folder); move it aside")
    return fd


def _expected_total(r: Any, have: int, status: int) -> int | None:
    """The full size the server states (AN8): Content-Range on a 206, else Content-Length."""
    h = getattr(r, "headers", None)
    get = h.get if h is not None else (lambda k, d=None: d)
    rng = get("Content-Range") or ""
    if status == 206 and "/" in rng and rng.rsplit("/", 1)[1].isdigit():
        return int(rng.rsplit("/", 1)[1])
    length = get("Content-Length")
    if length and str(length).isdigit():
        return int(length) + (have if status == 206 else 0)
    return None


def download(root: Path, rel_dir: str, rf: Remote, expect_sha256: str | None = None,
             progress: Callable[[str], None] | None = None) -> tuple[str, str, int, bool]:
    """(rel path, sha256, size, fetched). Resumes a `.NAME.part`; checks size, md5 and sha256 where known (and the size
    the server states); a mismatch removes the partial file and raises. An existing file is kept only when it matches
    every known checksum. Every file opened is a plain file with one link (AN1)."""
    import urllib.error

    dfd = _dest_dir(root, rel_dir)
    rel = f"{rel_dir.rstrip('/')}/{rf.name}" if rel_dir not in ("", ".") else rf.name
    part = f".{rf.name}.part"
    try:
        try:
            fd = _open_plain(rf.name, os.O_RDONLY, dfd, rel)
        except FileNotFoundError:
            fd = -1
        except FetchError:
            raise
        except OSError:
            raise FetchError(f"{rel} is a link or cannot be read") from None
        if fd >= 0:
            try:
                sha, md5, size = _hash_fd(fd)
            finally:
                os.close(fd)
            bad = _mismatch(rf, sha, md5, size, expect_sha256)
            if bad:
                raise FetchError(f"{rel} already exists and {bad}; move it aside to fetch again")
            return rel, sha, size, False
        try:
            pfd = _open_plain(part, os.O_RDWR | os.O_CREAT, dfd, f"{rel_dir}/{part}")
        except FetchError:
            raise
        except OSError:
            raise FetchError(f"{rel_dir}/{part} is a link or cannot be written") from None
        stated = rf.size
        try:
            have = os.fstat(pfd).st_size
            if rf.size is not None and have > rf.size:
                os.ftruncate(pfd, 0)
                have = 0
            if not (rf.size is not None and have == rf.size):
                for attempt in (1, 2):
                    headers = {"Range": f"bytes={have}-"} if have else {}
                    try:
                        with _get(rf.url, headers) as r:
                            status = getattr(r, "status", None) or r.getcode()
                            if have and status != 206:  # the server ignored the range: start again
                                os.ftruncate(pfd, 0)
                                have = 0
                            stated = stated if stated is not None else _expected_total(r, have, status)
                            os.lseek(pfd, have, os.SEEK_SET)
                            while True:
                                b = r.read(CHUNK)
                                if not b:
                                    break
                                write_all(pfd, b)
                        break
                    except urllib.error.HTTPError as e:
                        if e.code == 416 and have and attempt == 1:  # AN8: nothing left to resume: start again
                            os.ftruncate(pfd, 0)
                            have = 0
                            continue
                        raise
            os.fsync(pfd)
            sha, md5, size = _hash_fd(pfd)
        except FetchError:
            raise
        except OSError as e:  # a broken transfer keeps its partial file for the next run to resume
            raise FetchError(f"{rf.url}: {getattr(e, 'reason', None) or e} (run again to resume)") from None
        finally:
            os.close(pfd)
        if stated is not None and size < stated:  # AN8: a transfer that ended early, kept for resuming
            raise FetchError(f"{rf.url}: {size} of {stated} bytes arrived (run again to resume)")
        bad = _mismatch(Remote(rf.name, rf.url, rf.md5, rf.size if rf.size is not None else stated), sha, md5, size,
                        expect_sha256)
        if bad:
            os.unlink(part, dir_fd=dfd)
            raise FetchError(f"{rf.name}: {bad}; nothing recorded")
        os.replace(part, rf.name, src_dir_fd=dfd, dst_dir_fd=dfd)
        if progress:
            progress(f"fetched {rel} ({size} bytes)")
        return rel, sha, size, True
    finally:
        os.close(dfd)


def _mismatch(rf: Remote, sha: str, md5: str, size: int, expect_sha256: str | None) -> str | None:
    if rf.size is not None and size != rf.size:
        return f"its size {size} is not the archive's {rf.size}"
    if rf.md5 and md5 != rf.md5.lower():
        return f"its md5 {md5} is not the archive's {rf.md5}"
    if expect_sha256 and sha != expect_sha256.lower():
        return f"its sha256 {sha[:12]}… is not the expected {expect_sha256[:12]}…"
    return None


# ---------------------------------------------------------------- B3: conventions read from the files
CHROM_KINDS = (".bed", ".bedgraph", ".narrowpeak", ".broadpeak", ".gtf", ".gff", ".gff3", ".vcf", ".bedpe", ".sam")
NAMING = {
    "ucsc": re.compile(r"^chr([0-9]{1,2}|X|Y|M|Un)(_.*)?$"),
    "ensembl": re.compile(r"^([0-9]{1,2}|X|Y|MT)$"),
    "refseq": re.compile(r"^N[CTW]_\d+\.\d+$"),
}


def _text_head(data: bytes, limit: int = 256 << 20) -> str:
    """The text of a file, gzip or BGZF (every member, AN7), up to `limit` bytes."""
    if data[:2] == b"\x1f\x8b":
        out, rest = [], data
        try:
            while rest[:2] == b"\x1f\x8b" and sum(map(len, out)) < limit:
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                out.append(d.decompress(rest, limit))
                rest = d.unused_data
        except zlib.error:
            return ""
        data = b"".join(out)
    return data[:limit].decode("utf-8", "replace")


def chrom_kind(path: str) -> bool:
    p = path.lower().removesuffix(".gz").removesuffix(".bgz")
    return p.endswith(CHROM_KINDS)


def chromosome_naming(data: bytes, lines: int | None = None, column: int = 0) -> tuple[str | None, str | None]:
    """(naming, an example) from the first column of a BED/GTF/GFF/VCF-like file: 'ucsc', 'ensembl', 'refseq',
    'mixed' or None (nothing recognised)."""
    seen: dict[str, str] = {}
    n = 0
    for ln in _text_head(data).splitlines():
        if not ln or ln.startswith(("#", "track", "browser", "@")):
            continue
        parts = ln.split("\t")
        if len(parts) <= column:
            continue
        col = parts[column].strip()
        if col == "*":  # SAM: an unplaced read
            continue
        n += 1
        for k, rx in NAMING.items():
            if rx.match(col):
                seen.setdefault(k, col)
                break
        if lines is not None and n >= lines:
            break
    if not seen:
        return None, None
    if len(seen) > 1:
        return "mixed", ", ".join(f"{v} ({k})" for k, v in seen.items())
    (k, v), = seen.items()
    return k, v


# ---------------------------------------------------------------- B4: sample metadata
MISSING = {"", "na", "n/a", "nan", "null", "none", "-", "?", "missing", "unknown"}


def _rows(data: bytes, path: str) -> list[list[str]]:
    text = _text_head(data, 64 << 20)
    delim = "," if path.lower().removesuffix(".gz").endswith(".csv") else "\t"
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]


def matrix_samples(data: bytes, path: str, skip: int = 1) -> list[str]:
    """The sample columns of a matrix: the header after `skip` identifier columns. In a GEO series matrix the header
    is the line after `!series_matrix_table_begin` (metadata lines start with '!')."""
    text = _text_head(data, 8 << 20)
    delim = "," if path.lower().removesuffix(".gz").endswith(".csv") else "\t"
    lines = text.splitlines()
    if any(ln.startswith("!series_matrix_table_begin") for ln in lines):
        i = next(i for i, ln in enumerate(lines) if ln.startswith("!series_matrix_table_begin"))
        lines = lines[i + 1:]
    for ln in lines:
        if ln.strip() and not ln.startswith(("!", "#")):
            head = next(csv.reader([ln], delimiter=delim))
            return [h.strip() for h in head[skip:]]
    return []


def _design_factors(sheet: Any, header: dict[str, int]) -> tuple[str, list[str], list[str]]:
    condition = sheet.condition_column or "condition"
    batch = sheet.batch_column or "batch"
    factors = list(sheet.covariates)
    if sheet.batch_column or (batch in header and batch not in {condition, sheet.id_column}):
        factors.insert(0, batch)
    if condition not in header and not (sheet.condition_column or sheet.batch_column or sheet.covariates):
        factors = []
    required = [condition, *factors] if factors or sheet.condition_column else []
    return condition, [f for f in factors if f in header], required


def _design_finding(path: str, condition: str, factor: str, counts: Counter[tuple[str, str]]) -> dict[str, Any] | None:
    levels: dict[str, Counter[str]] = defaultdict(Counter)
    by_condition: dict[str, set[str]] = defaultdict(set)
    for (group, level), count in counts.items():
        levels[level][group] = count
        by_condition[group].add(level)
    if len(levels) < 2 or len(by_condition) < 2:
        return None

    # In an additive design, contrasts across disconnected groups cannot separate condition and factor.
    pending = [next(iter(by_condition))]
    reached_groups: set[str] = set(pending)
    reached_levels: set[str] = set()
    while pending:
        for level in by_condition[pending.pop()] - reached_levels:
            reached_levels.add(level)
            new_groups = levels[level].keys() - reached_groups
            reached_groups.update(new_groups)
            pending.extend(new_groups)

    if len(reached_groups) < len(by_condition):
        code = "R-75.sample_confounding"
        message = "Complete confounding prevents separating some condition contrasts from this factor."
    else:
        totals = {level: sum(groups.values()) for level, groups in levels.items()}
        # Within a factor, compare each condition's smallest and largest shares across the levels.
        for group in by_condition:
            shares = [Fraction(levels[level][group], totals[level]) for level in by_condition[group]]
            smallest = min(shares) if len(shares) == len(levels) else 0
            if max(shares) - smallest >= Fraction(4, 5):
                break
        else:
            return None
        code = "R-75.sample_imbalance"
        message = "Advisory: a condition's share differs by at least 80 percentage points across factor levels."
    groups = sorted(by_condition)
    table = ", ".join(
        f"{level!r}: " + ", ".join(f"{group!r}={n}" for group, n in sorted(levels[level].items()))
        for level in sorted(levels)
    )
    return {"code": code, "path": path, "value": factor,
            "message": f"{message} {condition} columns {', '.join(map(repr, groups))}. {factor} rows {table}. "
                       "Unlisted cells have zero samples."}


def check_samples(sheet: Any, read: Callable[[str], bytes]) -> list[dict[str, Any]]:
    """Findings (details with `code`, and `path`, `row`, `value` where they apply) for one study's sample sheet."""
    out: list[dict[str, Any]] = []
    rows = _rows(read(sheet.path), sheet.path)
    if not rows:
        return [{"code": "R-75.samples_empty", "path": sheet.path, "message": "the sample sheet has no header"}]
    head = [h.strip() for h in rows[0]]
    if sheet.id_column not in head:
        return [{"code": "R-75.samples_no_id", "path": sheet.path, "value": sheet.id_column,
                 "message": f"no column {sheet.id_column!r} (columns: {', '.join(head[:12])})"}]
    col = {h: i for i, h in enumerate(head)}
    condition, factors, design_required = _design_factors(sheet, col)
    required = [*sheet.required, *(f for f in design_required if f not in sheet.required)]
    for f in required:
        if f not in col:
            out.append({"code": "R-75.sample_field_missing", "path": sheet.path, "value": f,
                        "message": f"required column {f!r} is absent"})
    ids: dict[str, int] = {}
    counts: dict[str, Counter[tuple[str, str]]] = {factor: Counter() for factor in factors}
    missing_design: set[str] = set()
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        cell = lambda h: r[col[h]].strip() if col.get(h, len(r)) < len(r) else ""
        sid = cell(sheet.id_column)
        if not sid:
            out.append({"code": "R-75.sample_no_id", "path": sheet.path, "row": n, "message": f"row {n}: no sample ID"})
            continue
        if sid in ids:
            out.append({"code": "R-75.sample_duplicate", "path": sheet.path, "row": n, "value": sid,
                        "message": f"row {n}: {sid} also on row {ids[sid]}"})
        else:
            group = cell(condition)
            for factor in factors:
                level = cell(factor)
                if group.lower() in MISSING or level.lower() in MISSING:
                    missing_design.add(factor)
                else:
                    counts[factor][group, level] += 1
        ids.setdefault(sid, n)
        for f in required:
            if f in col and cell(f).lower() in MISSING:
                out.append({"code": "R-75.sample_value_missing", "path": sheet.path, "row": n, "value": f,
                            "message": f"row {n} ({sid}): {f} is empty or a missing-value marker"})
        for f, allowed in sheet.allowed.items():
            v = cell(f) if f in col else ""
            if f in col and v.lower() not in MISSING and v not in allowed:
                out.append({"code": "R-75.sample_value_not_allowed", "path": sheet.path, "row": n, "value": f,
                            "message": f"row {n} ({sid}): {f} = {v!r} is not one of {', '.join(allowed)}"})
    for factor in factors:
        if factor not in missing_design and (finding := _design_finding(sheet.path, condition, factor, counts[factor])):
            out.append(finding)
    from .records import RecordRefused

    for mx in sheet.matrix:
        try:
            cols = matrix_samples(read(mx.path), mx.path, mx.skip_columns)
        except RecordRefused as e:  # AN3: the sheet's findings stay; the matrix is named
            out.append({"code": "R-75.matrix_missing" if e.reason == "missing" else "R-75.matrix_refused",
                        "path": mx.path, "message": str(e)})
            continue
        if not cols:
            out.append({"code": "R-75.matrix_no_header", "path": mx.path, "message": "no header line found"})
            continue
        for s in [c for c in cols if c not in ids]:
            out.append({"code": "R-75.sample_not_in_metadata", "path": mx.path, "value": s,
                        "message": f"matrix column {s} has no row in {sheet.path}"})
        if not mx.subset:
            have = set(cols)
            for s in [s for s in ids if s not in have]:
                out.append({"code": "R-75.sample_not_in_matrix", "path": sheet.path, "row": ids[s], "value": s,
                            "message": f"{s} is not a column of {mx.path}"})
    return out

