"""Research records (0.18.0): study records (R-75), research-direction records (R-76), citation verification (R-77)
and the hygiene of evaluating language models (R-78).

- **Study records** (`[studies]`): one TOML file per study (a reanalysis, an experiment, a claim and its plan) with its
  inputs (accessions and file fingerprints), references (genome build, annotation release, identifier namespace,
  database versions), tools, plan, results and the papers that cite it. R-75 checks that every recorded file is
  present and unchanged; a changed input makes its study, the studies that depend on it and the papers that cite them
  stale. The same input in two studies is listed (a duplicate across studies).
- **Research-direction records** (`[research]`): literature reviews, novelty maps, gap and flaw lists and dead-end
  reviews, so that what was searched, found and decided outlives a chat. R-76 (advisory) reports stale reviews,
  contributions without their nearest prior work and undecided dead ends.
- **Citation verification** (`[paper.NAME] citations`, optional): each cited DOI or PMID has a record of the title it
  resolves to; R-77 fails a citation whose recorded title is not the cited one.
- **Evaluating language models** (`[llm_eval]` in a benchmark contract): R-78 fails a study (group) present in both
  tuning and test and a model that judges itself; it reports test cases published before a candidate's training
  cutoff and prompts that are not frozen.

Records are written by people or agents and checked here; nothing is fetched while checking.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .models import FileRef, Hex64, SafePath, Strict, Text

RecordId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


# ---------------------------------------------------------------- study records
class Mapping(Strict):
    """0.20.0 (B3): the identifier mapping table a study used, and its version."""
    path: SafePath
    sha256: Hex64 | None = None
    version: Text                     # e.g. "Ensembl 111 BioMart, 2026-01-10" or a GPL table's date


class References(Strict):
    genome: Text | None = None        # e.g. GRCh38
    annotation: Text | None = None    # e.g. GENCODE 44, Ensembl 111, a GPL annotation table and its date
    id_namespace: Text | None = None  # e.g. Entrez, Ensembl gene, HGNC symbol
    databases: dict[str, Text] = Field(default_factory=dict)  # name -> release or download date
    # 0.20.0 (B3): the conventions that silently break reanalyses
    organism: Text | None = None      # e.g. Homo sapiens
    taxon: Annotated[int, Field(ge=1)] | None = None  # NCBI taxon, e.g. 9606
    coordinate_base: Literal[0, 1] | None = None      # 0 (BED, half-open) or 1 (GTF, VCF, SAM)
    chromosome_naming: Literal["ucsc", "ensembl", "refseq"] | None = None  # chr1 / 1 / NC_000001.11
    mapping: Mapping | None = None


CONVENTIONS = ("genome", "annotation", "id_namespace", "organism", "taxon", "coordinate_base", "chromosome_naming")


class StudyInput(Strict):
    id: Text
    source: Text = "local"          # GEO, SRA, ArrayExpress, Zenodo, a URL host, local, …
    accession: Text | None = None
    url: Text | None = None
    retrieved: date | None = None
    files: list[FileRef] = Field(default_factory=list)
    references: References | None = None  # 0.20.0 (B3): what this input's source declares, when it differs per input


class MatrixRef(Strict):
    path: SafePath
    skip_columns: Annotated[int, Field(ge=0)] = 1  # identifier columns before the samples
    subset: bool = False                           # the matrix holds only some of the sheet's samples


class SampleSheet(Strict):
    """0.20.0 (B4): the study's sample metadata and its contract."""
    path: SafePath
    sha256: Hex64 | None = None
    id_column: Text = "sample"
    required: list[Text] = Field(default_factory=lambda: ["organism", "tissue", "condition", "batch"])
    allowed: dict[str, list[Text]] = Field(default_factory=dict)
    matrix: list[MatrixRef] = Field(default_factory=list)


class Tool(Strict):
    name: Text
    version: Text


class Study(Strict):
    schema_: Literal["steward.study/1"] = Field(alias="schema")
    id: RecordId
    title: Text
    kind: Text = "study"
    status: Literal["active", "frozen", "retired"] = "active"
    inputs: list[StudyInput] = Field(default_factory=list)
    references: References = Field(default_factory=References)
    tools: list[Tool] = Field(default_factory=list)
    plan: SafePath | None = None
    plan_sha256: Hex64 | None = None   # AE6: the plan is evidence too
    results: list[FileRef] = Field(default_factory=list)
    papers: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    notes: Text | None = None
    samples: SampleSheet | None = None  # 0.20.0 (B4)


class RecordRefused(OSError):
    """A record path outside the repository, reached through a link, or not a regular file (AE1, AE5). `reason` is
    "missing" (absent evidence), "link", "outside", "kind" or "changed" (AF15, AG5: decided by it, never by the text)."""

    def __init__(self, errno_: int, message: str, reason: str = "refused"):
        super().__init__(errno_, message)
        self.reason = reason


def _open_rel(root: Path, rel: str) -> int:
    """A read descriptor of `root/rel`: never outside the repository, never through a link at any component, and
    only a regular file (opened without blocking, then checked to be what was classified)."""
    import os
    import stat as _st

    from .fsutil import LinkRefused, escapes_root, open_dir_beneath

    import errno as _errno

    if escapes_root(rel):
        raise RecordRefused(0, f"{rel} is outside the repository", "outside")
    parts = Path(rel).parts
    try:
        dfd = open_dir_beneath(root, parts[:-1])
    except LinkRefused as e:  # AG5: an absent folder is absent evidence, a link is a refusal
        if e.errno == _errno.ENOENT:
            raise RecordRefused(0, f"{rel} is missing", "missing") from None
        raise RecordRefused(0, f"{rel} is reached through a link", "link") from None
    try:
        try:
            st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            raise RecordRefused(0, f"{rel} is missing", "missing") from None
        except OSError:
            raise RecordRefused(0, f"{rel} cannot be read", "kind") from None
        if not _st.S_ISREG(st.st_mode):
            raise RecordRefused(0, f"{rel} is a link or not a regular file", "link" if _st.S_ISLNK(st.st_mode) else "kind")
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0), dir_fd=dfd)
    except OSError as e:
        if isinstance(e, RecordRefused):
            raise
        raise RecordRefused(0, f"{rel} cannot be opened", "kind") from None
    finally:
        os.close(dfd)
    now = os.fstat(fd)
    if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino) or not _st.S_ISREG(now.st_mode):
        os.close(fd)
        raise RecordRefused(0, f"{rel} changed while it was opened", "changed")
    return fd


def open_rel(root: Path, rel: str):
    """The link-safe reader used by read_rel, also available for streaming callers."""
    import os

    return os.fdopen(_open_rel(root, rel), "rb", buffering=0)


def read_rel(root: Path, rel: str) -> bytes:
    with open_rel(root, rel) as stream:
        chunks = []
        while chunk := stream.read(1 << 20):
            chunks.append(chunk)
        return b"".join(chunks)


def _toml_files(root: Path, rel_dir: str) -> list[str]:
    """The record files of a folder, listed through a descriptor reached without links (AE1)."""
    import os

    from .fsutil import LinkRefused, escapes_root, open_dir_beneath

    if escapes_root(rel_dir):
        return []
    try:
        dfd = open_dir_beneath(root, Path(rel_dir).parts)
    except LinkRefused:
        return []
    try:
        names = os.listdir(dfd)
    finally:
        os.close(dfd)
    return sorted(f"{rel_dir.rstrip('/')}/{n}" for n in names if n.endswith(".toml"))


def _sha_file(root: Path, rel: str, observe: Any = None) -> str | None:
    """The file's digest, read through `_open_rel` (never a link, never outside); None when refused. `observe(rel,
    sha)` records it as an input of the verdict (AE14)."""
    import os

    try:
        fd = _open_rel(root, rel)
    except RecordRefused:
        return None
    h = hashlib.sha256()
    try:
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            h.update(b)
    finally:
        os.close(fd)
    if observe is not None:
        observe(rel, h.hexdigest())
    return h.hexdigest()


def load_studies(root: Path, cfg: Any, read=None) -> tuple[dict[str, tuple[str, Study]], list[tuple[str, str]]]:
    """({id: (rel, study)}, [(rel, error)])."""
    read = read or (lambda rel: read_rel(root, rel))
    ok: dict[str, tuple[str, Study]] = {}
    bad: list[tuple[str, str]] = []
    for rel in _toml_files(root, cfg.studies.dir):
        try:
            st = Study.model_validate(tomllib.loads(read(rel).decode("utf-8")))
        except Exception as e:  # noqa: BLE001 - any invalid file is reported, never a crash
            bad.append((rel, str(e).splitlines()[0][:200]))
            continue
        if Path(rel).stem != st.id:
            bad.append((rel, f"the file name must be its id ({st.id}.toml)"))
            continue
        ok[st.id] = (rel, st)
    return ok, bad


def study_files(st: Study) -> list[tuple[str, FileRef]]:
    out = [(f"input {i.id}", f) for i in st.inputs for f in i.files] + [("result", f) for f in st.results]
    if st.plan:
        out.append(("plan", FileRef(path=st.plan, sha256=st.plan_sha256)))
    if st.references.mapping:
        out.append(("mapping", FileRef(path=st.references.mapping.path, sha256=st.references.mapping.sha256)))
    if st.samples:
        out.append(("samples", FileRef(path=st.samples.path, sha256=st.samples.sha256)))
    return out


def check_studies(root: Path, cfg: Any, read=None, observe=None) -> list[tuple[str, str, str, list[dict[str, Any]]]]:
    """[(subject, status, reason, details)] for R-75. `observe(rel, sha)` receives every file digest it relied on."""
    studies, bad = load_studies(root, cfg, read)
    rows: list[tuple[str, str, str, list[dict[str, Any]]]] = []
    for rel, err in bad:
        rows.append((rel, "FAIL", "not a valid study record", [{"code": "R-75.invalid", "path": rel, "message": err}]))
    changed: dict[str, list[str]] = {}
    seen_hash: dict[str, list[str]] = {}
    per: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    for sid, (rel, st) in studies.items():
        causes: list[str] = []
        details: list[dict[str, Any]] = []
        for what, fr in study_files(st):
            sha = _sha_file(root, fr.path, observe)
            if sha is None:
                causes.append("FAIL")
                details.append({"code": "R-75.file_missing", "path": fr.path, "message": f"{what}: missing, a link or outside"})
                changed.setdefault(sid, []).append(fr.path)
            elif fr.sha256 is None:
                causes.append("FAIL" if st.status == "frozen" else "INCOMPLETE")
                details.append({"code": "R-75.unfingerprinted", "path": fr.path,
                                "message": f"{what}: no sha256 recorded (steward study fingerprint {sid} --write)"})
            elif fr.sha256 != sha:
                causes.append("FAIL")
                details.append({"code": "R-75.file_changed", "path": fr.path,
                                "message": f"{what}: differs from the recorded sha256 ({fr.sha256[:12]} → {sha[:12]})"})
                changed.setdefault(sid, []).append(fr.path)
            if what.startswith("input") and sha is not None:
                seen_hash.setdefault(sha, []).append(sid)
        unknown_papers = [p for p in st.papers if p not in cfg.paper]
        if unknown_papers:
            causes.append("FAIL")
            details.append({"code": "R-75.unknown_paper", "value": ", ".join(unknown_papers),
                            "message": "not a [paper.NAME] of this project"})
        unknown_deps = [d for d in st.depends_on if d not in studies]
        if unknown_deps:
            causes.append("FAIL")
            details.append({"code": "R-75.unknown_dependency", "value": ", ".join(unknown_deps)})
        if st.status != "retired" and not st.inputs:
            causes.append("INCOMPLETE")
            details.append({"code": "R-75.no_inputs", "message": "no inputs recorded"})
        for c, d in _conventions(root, st, read):  # 0.20.0 (B3, B4)
            causes.append(c)
            details.append(d)
        per[sid] = (causes, details)
    # staleness: a study whose evidence changed makes every study that depends on it, directly or not, stale
    stale = set(changed)
    grew = True
    while grew:
        grew = False
        for sid, (_, st) in studies.items():
            if sid not in stale and any(d in stale for d in st.depends_on):
                stale.add(sid)
                grew = True
    for sid in sorted(stale):
        causes, details = per[sid]
        _, st = studies[sid]
        if sid not in changed:
            causes.append("INCOMPLETE")
            details.append({"code": "R-75.stale_dependency",
                            "value": ", ".join(d for d in st.depends_on if d in stale),
                            "message": "a study it depends on changed"})
        if st.papers:
            details.append({"code": "R-75.stale_paper", "value": ", ".join(st.papers),
                            "message": "these papers cite a study whose evidence changed: check their numbers"})
    for sha, sids in seen_hash.items():
        if len(set(sids)) > 1:
            for sid in sorted(set(sids)):
                per[sid][1].append({"code": "R-75.duplicate_input", "value": ", ".join(sorted(set(sids))),
                                    "message": f"the same input file (sha256 {sha[:12]}) is recorded by these studies"})
    for key in cfg.studies.consistent:
        vals: dict[str, list[str]] = {}
        for sid, (_, st) in studies.items():
            if st.status == "retired":
                continue
            v = getattr(st.references, key)
            if v not in (None, {}):
                vals.setdefault(repr(sorted(v.items())) if isinstance(v, dict) else str(v), []).append(sid)
        if len(vals) > 1:
            for group in vals.values():
                for sid in group:
                    per[sid][0].append("INCOMPLETE")
                    per[sid][1].append({"code": "R-75.inconsistent_references", "value": key,
                                        "message": f"studies record different {key} values: "
                                                   + "; ".join(f"{', '.join(g)}" for g in vals.values())})
    for sid, (causes, details) in sorted(per.items()):
        st_ = "FAIL" if "FAIL" in causes else "INCOMPLETE" if "INCOMPLETE" in causes else "PASS"
        reason = {"FAIL": "a recorded file is missing or changed, or a reference is unknown",
                  "INCOMPLETE": "the record is incomplete, stale or inconsistent",
                  "PASS": f"{len(study_files(studies[sid][1]))} recorded file(s) present and unchanged"}[st_]
        rows.append((studies[sid][0], st_, reason, details))
    return rows


def _conventions(root: Path, st: Study, read=None) -> list[tuple[str, dict[str, Any]]]:
    """0.20.0 (B3, B4): (status, detail) for an input whose declared conventions differ from its study's, a file whose
    chromosome names are not the declared naming, and the sample sheet's contract."""
    from . import biodata as bd

    read = read or (lambda rel: read_rel(root, rel))
    out: list[tuple[str, dict[str, Any]]] = []
    ref = st.references
    for inp in st.inputs:
        if inp.references is None:
            continue
        for key in CONVENTIONS:
            mine, theirs = getattr(inp.references, key), getattr(ref, key)
            if mine is not None and theirs is not None and mine != theirs:
                out.append(("FAIL", {"code": "R-75.convention_mismatch", "path": ", ".join(f.path for f in inp.files) or None,
                                     "value": key, "message": f"input {inp.id}: {key} is {mine!r}, the study's is {theirs!r}"}))
    for inp in st.inputs:
        naming = (inp.references.chromosome_naming if inp.references else None) or ref.chromosome_naming
        if naming is None:
            continue
        for f in inp.files:
            if not bd.chrom_kind(f.path):
                continue
            try:
                sam = f.path.lower().removesuffix(".gz").removesuffix(".bgz").endswith(".sam")  # AN7: SAM names chromosomes in RNAME
                seen, example = bd.chromosome_naming(read(f.path), column=2 if sam else 0)
            except RecordRefused:
                continue  # a missing file is reported by the fingerprint check
            if seen is not None and seen != naming:
                out.append(("FAIL", {"code": "R-75.chromosome_naming", "path": f.path, "value": seen,
                                     "message": f"input {inp.id}: chromosomes are named {seen} ({example}), the study "
                                                f"declares {naming}"}))
    if st.samples is not None:
        try:
            found = bd.check_samples(st.samples, read)
        except RecordRefused as e:
            found = [] if e.reason == "missing" else [{"code": "R-75.samples_refused", "path": st.samples.path,
                                                       "message": str(e)}]
        for d in found:  # AN2: never truncated
            out.append(("FAIL", d))
        recorded = {f.path for i in st.inputs for f in i.files}
        for mx in st.samples.matrix:
            if mx.path not in recorded:
                out.append(("INCOMPLETE", {"code": "R-75.matrix_unrecorded", "path": mx.path,
                                           "message": "the matrix is not a recorded input file of this study"}))
    return out


HEADING = re.compile(r"^\s*(?:\\(?:sub)*section\*?\{\s*(.*?)\s*\}|#{1,6}\s+(.*?)\s*#*|\*\*([^*]+?)\*\*)\s*$", re.M)  # AN10
DA_TITLE = re.compile(r"^(data|data and code|code and data)\s+availability", re.I)


def availability_text(text: str) -> str | None:
    """0.20.0 (B5): the body of a manuscript's data-availability section (LaTeX or Markdown), up to the next heading."""
    heads = [h for h in HEADING.finditer(text) if not _in_fence(text, h.start())]
    for i, h in enumerate(heads):
        title = h.group(1) or h.group(2) or h.group(3) or ""
        if DA_TITLE.match(title):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            return text[h.end():end]
    return None


def fenced_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of fenced code blocks (``` or ~~~, closed by the same marker) and of YAML front matter."""
    spans, pos, opener, start = [], 0, None, 0
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
        if end is not None:
            spans.append((0, sum(map(len, lines[:end + 1]))))
            pos = spans[-1][1]
            lines = lines[end + 1:]
    for ln in lines:  # AO2: CommonMark fences: up to 3 spaces, 3+ markers; a backtick opener has no backtick after it
        m = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", ln.rstrip("\n"))
        if m:
            mark, rest = m.group(1), m.group(2)
            if opener is None:
                if not (mark[0] == "`" and "`" in rest):  # ```code``` on one line is inline code, not a fence
                    opener, start = (mark[0], len(mark)), pos
            elif mark[0] == opener[0] and len(mark) >= opener[1] and rest.strip() == "":
                spans.append((start, pos + len(ln)))
                opener = None
        pos += len(ln)
    if opener is not None:
        spans.append((start, pos))
    return spans


def _in_fence(text: str, at: int, spans: list[tuple[int, int]] | None = None) -> bool:
    return any(a <= at < b for a, b in (spans if spans is not None else fenced_spans(text)))


def accession_named(acc: str, text: str) -> bool:
    flat = text.replace("\\_", "_").replace("\\-", "-").replace("~", " ")
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(acc) + r"(?![0-9])", flat, re.I) is not None


def accept(root: Path, cfg: Any, sid: str, path: str) -> tuple[str, str]:
    """0.20.2 (STW-040), AQ1: record a changed file's new bytes on purpose: its sha256 and size are replaced and the
    archive's md5 dropped, in that file's own entry only. The record is parsed again afterwards: the file must carry
    the new digest and every other file of the study its old one, or nothing is written. (old, new) digests."""
    from .fsutil import safe_write

    if not path:
        raise ValueError("--accept needs the path of a file of the study")
    studies, _ = load_studies(root, cfg)
    if sid not in studies:
        raise ValueError(f"no study {sid} in {cfg.studies.dir}/")
    rel, st = studies[sid]
    before = [(fr.path, fr.sha256) for _, fr in study_files(st)]
    old = next((sha for p_, sha in before if p_ == path), "missing")
    if old == "missing":
        raise ValueError(f"{path} is not a file of study {sid}")
    if old is None:
        raise ValueError(f"{path} has no recorded digest yet: steward study fingerprint {sid} --write")
    try:
        data = read_rel(root, path)  # one read: the digest and the size come from the same bytes
    except RecordRefused as e:
        raise ValueError(f"{path}: {e}; restore it first") from None
    new, size = hashlib.sha256(data).hexdigest(), len(data)
    if old == new:
        raise ValueError(f"{path} is unchanged; nothing to accept")
    text = read_rel(root, rel).decode("utf-8")
    lit = r"""(?:"{p}"|'{p}')""".replace("{p}", re.escape(path))
    sha_re = re.compile(r"""(sha256\s*=\s*)(["']){o}\2""".replace("{o}", old))

    def candidates():
        lines = text.split("\n")
        offs = [0]
        for ln in lines:
            offs.append(offs[-1] + len(ln) + 1)
        for m in re.finditer(r"path\s*=\s*" + lit, text):
            ln_no = text.count("\n", 0, m.start())
            if lines[ln_no].lstrip().startswith("#") or "#" in lines[ln_no][:m.start() - offs[ln_no]]:
                continue  # a comment
            ob, cb = text.rfind("{", 0, m.start()), text.find("}", m.end())
            if ob != -1 and text.rfind("}", 0, m.start()) < ob and cb != -1 and "\n" not in text[ob:cb]:
                yield ob, cb + 1, True  # its inline table
            else:
                nxt = re.search(r"^\s*\[", text[m.end():], re.M)
                yield offs[ln_no], m.end() + (nxt.start() if nxt else len(text) - m.end()), False  # its table

    for a, b, inline in candidates():
        span = text[a:b]
        if not sha_re.search(span):
            continue  # not the entry that holds the old digest (a [samples] matrix, say)
        seg = sha_re.sub(lambda mm: f"{mm.group(1)}{mm.group(2)}{new}{mm.group(2)}", span, count=1)
        seg = re.sub(r"""(,\s*md5\s*=\s*["'][0-9a-f]{32}["'])""" if inline else r"""^\s*md5\s*=\s*["'][0-9a-f]{32}["']\s*\n""", "",
                     seg, count=1, flags=0 if inline else re.M)
        seg = re.sub(r"(size\s*=\s*)\d+", rf"\g<1>{size}", seg, count=1)
        candidate = text[:a] + seg + text[b:]
        try:
            after_st = Study.model_validate(tomllib.loads(candidate))
        except Exception:  # noqa: BLE001
            continue
        after = [(fr.path, fr.sha256) for _, fr in study_files(after_st)]
        want = [(p_, new if p_ == path else sha) for p_, sha in before]
        if after == want:  # AQ1: exactly this file changed, and nothing else
            safe_write(root, rel, candidate.encode("utf-8"))
            return old, new
    raise ValueError(f"the digest of {path} cannot be changed in {rel} without touching another entry; edit it by hand")


def fingerprint(root: Path, cfg: Any, sid: str, write: bool) -> tuple[list[tuple[str, str | None, str | None]], list[str]]:
    """([(path, recorded, actual)] for every file of the study, [paths whose digest could not be written]). With
    `write`, missing digests are filled in: an inline `{ path = "…" }` on a line that is not a comment, and the
    plan's `plan_sha256` after its `plan = "…"` line. A recorded digest is never overwritten, and every write is
    checked by reading the record back (AE7)."""
    studies, _ = load_studies(root, cfg)
    if sid not in studies:
        raise ValueError(f"no study {sid} in {cfg.studies.dir}/")
    rel, st = studies[sid]
    out = [(fr.path, fr.sha256, _sha_file(root, fr.path)) for _, fr in study_files(st)]
    todo = {path: act for path, rec, act in out if rec is None and act is not None}
    if not write or not todo:
        return out, []
    lines = read_rel(root, rel).decode("utf-8").split("\n")
    done: set[str] = set()
    table = ""
    tabled = {st.samples.path: "samples"} if st.samples else {}
    if st.references.mapping:
        tabled[st.references.mapping.path] = "references.mapping"
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        hm = re.match(r"^\s*\[\s*([A-Za-z0-9_.]+)\s*\]\s*(#.*)?$", line)
        if hm:
            table = hm[1]
        for path, act in todo.items():
            if path in done:
                continue
            if tabled.get(path) == table and re.match(r'^\s*path\s*=\s*"' + re.escape(path) + r'"\s*(#.*)?$', line):
                lines[i] = line + f'\nsha256 = "{act}"'  # 0.20.0: the sample sheet and the mapping table
                done.add(path)
                continue
            if st.plan == path and re.match(r'^\s*plan\s*=\s*"' + re.escape(path) + r'"\s*(#.*)?$', line):
                lines[i] = line + f'\nplan_sha256 = "{act}"'
                done.add(path)
                continue
            pat = re.compile(r'\{\s*path\s*=\s*"' + re.escape(path) + r'"\s*(?=[,}])')  # 0.20.0: other keys may follow
            if pat.search(line):
                lines[i] = pat.sub(f'{{ path = "{path}", sha256 = "{act}" ', line, count=1)
                line = lines[i]
                done.add(path)
    text = "\n".join(lines)
    try:  # the new text must still be a valid record, holding exactly the digests written
        new = Study.model_validate(tomllib.loads(text))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"the updated record would not be valid ({str(e).splitlines()[0][:120]}); nothing written") from None
    from .fsutil import safe_write

    safe_write(root, rel, text.encode("utf-8"))
    landed = {fr.path: fr.sha256 for _, fr in study_files(load_studies(root, cfg)[0][sid][1])}
    del new
    missed = sorted(p for p, act in todo.items() if landed.get(p) != act)
    return out, missed


STUDY_TEMPLATE = '''schema = "steward.study/1"
id = "{id}"
title = "{title}"
kind = "{kind}"            # reanalysis, experiment, claim, benchmark, …
status = "active"          # active | frozen (every file fingerprinted) | retired
# Top-level keys come before the first [table]:
# plan = "development/plans/{id}.md"          # the frozen analysis plan, if any (fingerprinted as plan_sha256)
# results = [{{ path = "results/{id}/de.tsv" }}]
# papers = ["main"]                            # [paper.NAME] tables that cite this study
# depends_on = []                              # other study ids this one builds on

# Where the data came from. One [[inputs]] table per source; files are fingerprinted with
#   steward study fingerprint {id} --write
# [[inputs]]
# id = "GSE00000"
# source = "GEO"
# accession = "GSE00000"
# retrieved = {today}
# files = [{{ path = "data/GSE00000_series_matrix.txt" }}]

[references]
# genome = "GRCh38"
# annotation = "GENCODE 44"
# id_namespace = "Entrez"
# databases = {{ GO = "2026-10-01", Reactome = "v90" }}
# organism = "Homo sapiens"
# taxon = 9606
# coordinate_base = 1                        # 0 (BED) or 1 (GTF, VCF)
# chromosome_naming = "ucsc"                 # ucsc (chr1) | ensembl (1) | refseq (NC_000001.11)
# mapping = {{ path = "data/probe-to-gene.tsv", version = "GPL570 annotation, 2026-01-10" }}

# The sample metadata and its contract (checked against every matrix listed)
# [samples]
# path = "data/samples.tsv"
# id_column = "sample"
# required = ["organism", "tissue", "condition", "batch"]
# allowed = {{ condition = ["control", "case"] }}
# matrix = [{{ path = "data/GSE00000_series_matrix.txt.gz" }}]

# [[tools]]
# name = "limma"
# version = "3.58.1"

'''


def _md(v: Any) -> str:
    """Record text as inert Markdown: no HTML, no table breaks, no links or emphasis from the record itself."""
    import html

    return re.sub(r"([\\`*_{}\[\]()#+!|~])", r"\\\1", html.escape(str(v).replace("\n", " "), quote=False))


def card(st: Study, rows: dict[str, str]) -> str:
    """A study card (Markdown) for the docs site: what a reviewer or a reanalysis needs. Every value from the record is
    escaped (a title is text, never markup)."""
    state = rows.get(st.id, "—")
    badge = {"PASS": "✅ checked", "INCOMPLETE": "🟡 incomplete", "FAIL": "🔴 changed or missing"}.get(state, state)
    ref = st.references
    lines = [f"### {_md(st.title)}", "", f"`{st.id}` · {_md(st.kind)} · {st.status} · {badge}", ""]
    if st.inputs:
        lines.append("| Input | Source | Accession | Retrieved | Files |")
        lines.append("|---|---|---|---|---|")
        for i in st.inputs:
            lines.append(f"| {_md(i.id)} | {_md(i.source)} | {_md(i.accession or '—')} | {i.retrieved or '—'} | {len(i.files)} |")
        lines.append("")
    refs = [(k, getattr(ref, k)) for k in ("genome", "annotation", "id_namespace") if getattr(ref, k)]
    refs += [(f"database {k}", v) for k, v in sorted(ref.databases.items())]
    if refs:
        lines.append("**References:** " + " · ".join(f"{_md(k)}: {_md(v)}" for k, v in refs))
    if st.tools:
        lines.append("**Tools:** " + " · ".join(f"{_md(t.name)} {_md(t.version)}" for t in st.tools))
    if st.papers:
        lines.append("**Cited by:** " + ", ".join(_md(p) for p in st.papers))
    if st.depends_on:
        lines.append("**Builds on:** " + ", ".join(_md(d) for d in st.depends_on))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- research-direction records
class Source(Strict):
    id: Text          # doi:…, pmid:…, arxiv:…, url:…, or another stable identifier
    title: Text
    year: int | None = None
    included: bool = True
    why: Text | None = None


class Review(Strict):
    question: Text
    searched: date
    method: Text | None = None      # where and how: databases, queries, inclusion criteria
    sources: list[Source] = Field(default_factory=list)
    summary: Text | None = None


class Contribution(Strict):
    claim: Text
    nearest: list[Text] = Field(default_factory=list)       # source ids of the closest prior work
    difference: Text | None = None
    own_overlap: list[Text] = Field(default_factory=list)   # this group's own papers or studies it overlaps


class Gap(Strict):
    text: Text
    kind: Literal["gap", "flaw", "limitation", "threat"] = "gap"
    status: Literal["open", "addressed", "accepted"] = "open"
    decision: Text | None = None    # how it was addressed or why it is accepted (a decision, a task, a commit)
    source: Text | None = None


class Option(Strict):
    option: Text
    evidence: list[Text] = Field(default_factory=list)


class DeadEnd(Strict):
    results: list[Text] = Field(min_length=1)   # the negative results, runs or studies under review
    options: list[Option] = Field(default_factory=list)
    decision: Literal["stop", "pivot", "reframe", "continue"] | None = None
    decided: date | None = None
    rationale: Text | None = None


class ResearchRecord(Strict):
    schema_: Literal["steward.research/1"] = Field(alias="schema")
    id: RecordId
    title: Text
    kind: Literal["review", "novelty", "gaps", "dead-end"]
    status: Literal["draft", "done"] = "done"   # AE8: a record made from a template is a draft until filled in
    date: date
    relates: list[Text] = Field(default_factory=list)   # study ids or paper names
    review: Review | None = None
    contributions: list[Contribution] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    dead_end: DeadEnd | None = None

    @model_validator(mode="after")
    def _body(self) -> "ResearchRecord":
        need = {"review": self.review is not None, "novelty": bool(self.contributions), "gaps": bool(self.gaps),
                "dead-end": self.dead_end is not None}
        if not need[self.kind]:
            field = {"review": "[review]", "novelty": "[[contributions]]", "gaps": "[[gaps]]", "dead-end": "[dead_end]"}
            raise ValueError(f"a {self.kind} record needs {field[self.kind]}")
        return self


def load_research(root: Path, cfg: Any, read=None) -> tuple[dict[str, tuple[str, ResearchRecord]], list[tuple[str, str]]]:
    read = read or (lambda rel: read_rel(root, rel))
    ok: dict[str, tuple[str, ResearchRecord]] = {}
    bad: list[tuple[str, str]] = []
    for rel in _toml_files(root, cfg.research.dir):
        try:
            r = ResearchRecord.model_validate(tomllib.loads(read(rel).decode("utf-8")))
        except Exception as e:  # noqa: BLE001
            bad.append((rel, str(e).splitlines()[0][:200]))
            continue
        if Path(rel).stem != r.id:
            bad.append((rel, f"the file name must be its id ({r.id}.toml)"))
            continue
        ok[r.id] = (rel, r)
    return ok, bad


def check_research(root: Path, cfg: Any, today: date, read=None) -> list[tuple[str, str, str, list[dict[str, Any]]]]:
    recs, bad = load_research(root, cfg, read)
    studies = set(load_studies(root, cfg, read)[0]) if cfg.studies else set()
    known = studies | set(cfg.paper)
    rows = [(rel, "FAIL", "not a valid research record", [{"code": "R-76.invalid", "path": rel, "message": err}])
            for rel, err in bad]
    for rid, (rel, r) in sorted(recs.items()):
        details: list[dict[str, Any]] = []
        if r.status == "draft":
            fields = {"review": "the question, the dated search (sources, query, method) and each source's inclusion "
                                "decision with its reason",
                      "novelty": "the contribution and its nearest prior work",
                      "gaps": "each gap or flaw and the decision on it",
                      "dead-end": "the negative results, what others did at the same wall, the options and the decision"}
            details.append({"code": "R-76.draft", "message": "a draft: fill " + fields.get(r.kind, "the template's "
                            "fields") + ", then set status = \"done\""})
        if r.review is not None:
            age = (today - r.review.searched).days
            if age > cfg.research.stale_days:
                details.append({"code": "R-76.stale_review", "value": age,
                                "message": f"searched {age} days ago (over {cfg.research.stale_days}): run it again"})
            if not any(s.included for s in r.review.sources):
                details.append({"code": "R-76.no_sources", "message": "no included source"})
        for i, c in enumerate(r.contributions, start=1):
            if not c.nearest:
                details.append({"code": "R-76.no_nearest", "value": i, "message": f"contribution {i} names no nearest prior work"})
            if not c.difference:
                details.append({"code": "R-76.no_difference", "value": i, "message": f"contribution {i} does not say how it differs"})
        for i, g in enumerate(r.gaps, start=1):
            if g.status != "open" and not g.decision:
                details.append({"code": "R-76.undecided_gap", "value": i, "message": f"{g.kind} {i} is {g.status} without a decision"})
        if r.dead_end is not None and r.dead_end.decision is None:
            details.append({"code": "R-76.undecided_dead_end", "message": "no decision yet: stop, pivot, reframe or continue"})
        unknown = [x for x in r.relates if x not in known]
        if unknown:
            details.append({"code": "R-76.unknown_relation", "value": ", ".join(unknown)})
        st = "INCOMPLETE" if details else "PASS"
        rows.append((rel, st, {"PASS": f"{r.kind} record complete", "INCOMPLETE": f"{r.kind} record needs attention"}[st],
                     details))
    return rows


RESEARCH_TEMPLATES = {
    "review": '''schema = "steward.research/1"
id = "{id}"
title = "{title}"
kind = "review"
status = "draft"      # set to "done" once the examples below are replaced
date = {today}
relates = []          # study ids or paper names

[review]
question = "What is known about …?"
searched = {today}
method = "PubMed and Europe PMC, query: …; inclusion: …"
# summary = "What is settled, contested and missing"

[[review.sources]]
id = "doi:10.0000/example"
title = "Title of the paper"
year = 2025
included = true
why = "closest method"
''',
    "novelty": '''schema = "steward.research/1"
id = "{id}"
title = "{title}"
kind = "novelty"
status = "draft"      # set to "done" once the examples below are replaced
date = {today}
relates = []

[[contributions]]
claim = "What this work adds, in one sentence"
nearest = ["doi:10.0000/example"]   # the closest prior work, by source id
difference = "How it differs from the nearest work"
own_overlap = []                     # this group's own papers or studies it overlaps
''',
    "gaps": '''schema = "steward.research/1"
id = "{id}"
title = "{title}"
kind = "gaps"
status = "draft"      # set to "done" once the examples below are replaced
date = {today}
relates = []

[[gaps]]
text = "A gap in the field, a flaw in our design, a limitation or a threat to validity"
kind = "flaw"          # gap | flaw | limitation | threat
status = "open"        # open | addressed | accepted (both need a decision)
# decision = "How it was addressed, or why it is accepted"
# source = "Where it was found"
''',
    "dead-end": '''schema = "steward.research/1"
id = "{id}"
title = "{title}"
kind = "dead-end"
status = "draft"      # set to "done" once the examples below are replaced
date = {today}
relates = []

[dead_end]
results = ["the negative results under review: runs, studies, records"]
# decision = "reframe"   # stop | pivot | reframe | continue: only once the human decides
# decided = {today}
# rationale = "Why"

[[dead_end.options]]
option = "Reframe the question as …"
evidence = ["doi:10.0000/example"]
''',
}


def research_page(root: Path, cfg: Any) -> str:
    recs, _ = load_research(root, cfg)
    if not recs:
        return "No research records.\n"
    icon = {"review": "📚", "novelty": "✨", "gaps": "🧩", "dead-end": "🧭"}
    out = ["| | Record | Kind | Date | Summary |", "|---|---|---|---|---|"]
    for rid, (_, r) in sorted(recs.items(), key=lambda kv: kv[1][1].date, reverse=True):
        if r.review:
            summary = f"{sum(s.included for s in r.review.sources)} sources: {r.review.question}"
        elif r.contributions:
            summary = f"{len(r.contributions)} contribution(s)"
        elif r.gaps:
            summary = f"{sum(g.status == 'open' for g in r.gaps)} open of {len(r.gaps)}"
        else:
            summary = f"decision: {r.dead_end.decision or 'pending'}"
        out.append(f"| {icon[r.kind]} | {_md(r.title)} | {r.kind} | {r.date} | {_md(summary)} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- citation verification (optional, R-77)
class CitationRecord(Strict):
    key: Text                 # the bibliography key
    id: Text                  # doi:… or pmid:…
    title: Text               # the title the identifier resolves to
    checked: date
    via: Literal["crossref", "pubmed", "manual"] = "manual"


class CitationsFile(Strict):
    schema_: Literal["steward.citations/1"] = Field(alias="schema")
    citation: list[CitationRecord] = Field(default_factory=list)


def norm_title(t: str) -> str:
    """Titles compared as their case-folded words in any script: punctuation, braces, accent marks and spacing never
    decide (AE4: a title in Chinese, Arabic or Greek keeps its words)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", re.sub(r"[{}\\]", "", t or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return " ".join(w for w in re.findall(r"\w+", t) if w != "_")


DOI_URL = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$", re.I)
PMID_URL = re.compile(r"^https?://(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)/?$", re.I)


def cite_id(ids: dict[str, str]) -> str | None:
    """`doi:…` or `pmid:…` from the entry's fields, or from a DOI or PubMed URL (AE9)."""
    if ids.get("doi"):
        return "doi:" + ids["doi"].lower()
    if ids.get("pmid"):
        return "pmid:" + ids["pmid"]
    url = ids.get("url", "")
    if m := DOI_URL.match(url):
        return "doi:" + m.group(1).lower()
    if m := PMID_URL.match(url):
        return "pmid:" + m.group(1)
    return None


TEX_COMMENT = re.compile(r"(?<!\\)%.*$")


def cited_entries(root: Path, pp: Any, read) -> tuple[list[tuple[str, Any, str]], list[dict[str, Any]], int]:
    """The bibliography entries the manuscript cites, with an identifier: [(bib rel, entry, cid)], problems, and the
    number of cited keys (AE9: an uncited entry is out of scope; a citation with no bibliography is a problem)."""
    from . import bib
    from .fsutil import matching_files

    files = matching_files(root, [pp.rel(g) for g in pp.resolved_sources()])
    keys: set[str] = set()
    nocite_all = False
    for rel in files:
        if rel.endswith(".tex"):
            for line in read(rel).decode("utf-8", errors="replace").splitlines():
                for grp in bib.CITE.findall(TEX_COMMENT.sub("", line)):
                    for k in (x.strip() for x in grp.split(",")):
                        nocite_all |= k == "*"
                        if k and k != "*":
                            keys.add(k)
    problems: list[dict[str, Any]] = []
    entries: list[tuple[str, Any]] = []
    bibs = [f for f in files if f.endswith(".bib")]
    for rel in bibs:
        try:
            entries += [(rel, e) for e in bib.parse(read(rel).decode("utf-8", errors="replace"))]
        except bib.BibError as e:
            problems.append({"code": "R-77.parse", "path": rel, "message": str(e)})
    if keys and not bibs:
        problems.append({"code": "R-77.no_bibliography", "message": f"{len(keys)} cited key(s) but no .bib among the paper's sources"})
    out = []
    for rel, e in entries:
        if e.key in keys or nocite_all:
            cid = cite_id(bib.identifiers(e))
            if cid is not None:
                out.append((rel, e, cid))
    return out, problems, len(keys)


def fetch_title(cid: str, timeout: float = 20) -> tuple[str, str] | None:
    """(title, via) from Crossref (DOI) or NCBI E-utilities (PMID); None when it cannot be resolved. Network: used
    only by `steward paper citations --fetch`, never by a check."""
    import json
    import urllib.parse
    import urllib.request

    headers = {"User-Agent": "bio-steward (citation check)"}
    try:
        if cid.startswith("doi:"):
            url = "https://api.crossref.org/works/" + urllib.parse.quote(cid[4:], safe="/")
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                titles = json.load(r)["message"].get("title") or []
            return (titles[0], "crossref") if titles else None
        if cid.startswith("pmid:"):
            url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id="
                   + urllib.parse.quote(cid[5:]))
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                res = json.load(r)["result"]
            t = res.get(cid[5:], {}).get("title")
            return (t.rstrip("."), "pubmed") if t else None
    except Exception:  # noqa: BLE001 - unresolvable is reported, never a crash
        return None
    return None


def _toml_str(v: str) -> str:
    """A TOML basic string: quotes, backslashes and every control character escaped (AE10)."""
    out = []
    for c in v:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def render_citations(records: list[CitationRecord]) -> str:
    out = ['schema = "steward.citations/1"', ""]
    for r in sorted(records, key=lambda x: x.key):
        out += ["[[citation]]", f"key = {_toml_str(r.key)}", f"id = {_toml_str(r.id)}", f"title = {_toml_str(r.title)}",
                f"checked = {r.checked}", f'via = "{r.via}"', ""]
    text = "\n".join(out)
    CitationsFile.model_validate(tomllib.loads(text))  # AE10: what is written reads back
    return text


# ---------------------------------------------------------------- evaluating language models (R-78)
def check_llm_eval(root: Path, cfg: Any, ev: Any, read, prompts_state: tuple[str, str] | None = None
                   ) -> tuple[str, str, list[dict[str, Any]]]:
    """(status, reason, details) for one contract's [llm_eval]. `prompts_state` is R-63's verdict on the named
    [[frozen]] set: (status, reason). Unusable evidence is never a PASS (AE3, AE11)."""
    details: list[dict[str, Any]] = []
    causes: list[str] = []

    def add(code: str, st: str, **kw: Any) -> None:
        causes.append(st)
        details.append({"code": f"R-78.{code}", **kw})
    try:
        text = read(ev.cases).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return "FAIL", f"the cases file {ev.cases} cannot be read", [{"code": "R-78.cases_missing", "path": ev.cases}]
    rows = list(csv.DictReader(io.StringIO(text)))
    cols = set(rows[0]) if rows else set()
    need = [ev.id_column, ev.published_column, ev.group_column, ev.split_column]
    missing = [c for c in need if c not in cols]
    if missing or not rows:
        return "FAIL", "the cases file lacks its columns", [{"code": "R-78.columns", "value": ", ".join(missing) or "(no rows)"}]
    # one entry per case: the same ID twice with another split or group is a contradiction (AE3)
    cases: dict[str, tuple[str, str, str]] = {}
    conflicts, blank_ids, blank_groups = set(), 0, set()
    for r in rows:
        cid = (r[ev.id_column] or "").strip()
        split = (r[ev.split_column] or "").strip().lower()
        group = (r[ev.group_column] or "").strip()
        pub = (r[ev.published_column] or "").strip()
        if not cid:
            blank_ids += 1
            continue
        if split in ("tune", "dev", "test") and not group:
            blank_groups.add(cid)
        prev = cases.get(cid)
        if prev is not None and prev[:2] != (split, group):
            conflicts.add(cid)
        cases.setdefault(cid, (split, group, pub))
    if blank_ids:
        add("blank_id", "FAIL", value=blank_ids, message="rows without a case ID")
    if conflicts:
        add("id_conflict", "FAIL", value=", ".join(sorted(conflicts)[:10]),
            message=f"{len(conflicts)} case ID(s) recorded with different splits or groups")
    if blank_groups:
        add("blank_group", "INCOMPLETE", value=len(blank_groups),
            message="cases without a group: leakage between tuning and test cannot be told")
    groups: dict[str, set[str]] = {}
    for split, group, _ in cases.values():
        if group:
            groups.setdefault(split, set()).add(group)
    leak = sorted(groups.get("test", set()) & (groups.get("tune", set()) | groups.get("dev", set())))
    if leak:
        add("group_leak", "FAIL", value=", ".join(leak[:10]),
            message=f"{len(leak)} group(s) in both tuning and test: a model tuned on a study is tested on it")
    tests = {cid: c for cid, c in cases.items() if c[0] == "test"}
    if not tests:
        add("no_test_cases", "INCOMPLETE", message="no case has split = test")
    cands = [m for m in ev.models if m.role == "candidate"]
    judges = [m for m in ev.models if m.role == "judge"]
    if not cands:
        add("no_candidates", "INCOMPLETE", message="no model with role = candidate")
    selfj = sorted({m.name for m in judges} & {m.name for m in cands})
    if selfj:
        add("self_judging", "FAIL", value=", ".join(selfj), message="a model judges its own answers")
    dated: dict[str, date] = {}
    undated = []
    for cid, (_, _, pub) in tests.items():
        try:
            dated[cid] = date.fromisoformat(pub)  # the whole value: no trailing text (AE3)
        except ValueError:
            undated.append(cid)
    if undated and cands:
        add("undated_cases", "INCOMPLETE", value=len(undated), message=f"test cases without an ISO date ({', '.join(undated[:5])})")
    for m in cands:
        if m.training_cutoff is None:
            add("cutoff_unknown", "INCOMPLETE", value=m.name, message="no training_cutoff: exposure cannot be told")
            continue
        early = sorted(cid for cid, d in dated.items() if d <= m.training_cutoff)
        if early:
            add("contamination_risk", "INCOMPLETE", value=len(early),
                message=f"{m.name}: {len(early)} of {len(tests)} test case(s) were public by its stated cutoff "
                        f"{m.training_cutoff} ({', '.join(early[:5])}{' …' if len(early) > 5 else ''})")
    if ev.prompts is None:
        add("prompts_not_frozen", "INCOMPLETE", message="name the [[frozen]] set that holds the prompts")
    elif ev.prompts not in {f.name for f in cfg.frozen}:
        add("prompts_unknown", "FAIL", value=ev.prompts, message="no [[frozen]] set of that name")
    elif prompts_state is None or prompts_state[0] != "PASS":  # AE11: the set's record must exist and still match
        st_ = prompts_state[0] if prompts_state else "UNKNOWN"
        add("prompts_not_intact", "FAIL" if st_ == "FAIL" else "INCOMPLETE", value=ev.prompts,
            message=f"the prompt set is not recorded and intact (R-63: {st_}"
                    + (f", {prompts_state[1]}" if prompts_state else "") + ")")
    st = "FAIL" if "FAIL" in causes else "INCOMPLETE" if "INCOMPLETE" in causes else "PASS"
    reason = {"FAIL": "a study leaks into the test set, a case contradicts itself, a model judges itself, or the prompts "
                      "are unknown or changed",
              "INCOMPLETE": "exposure risk, missing evidence or prompts not recorded",
              "PASS": f"{len(tests)} test case(s) after every stated cutoff; groups apart; prompts recorded and intact"}[st]
    return st, reason, details


def today_utc() -> date:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


__all__ = ["Study", "ResearchRecord", "CitationsFile", "check_studies", "check_research", "check_llm_eval",
           "fingerprint", "card", "research_page", "norm_title", "fetch_title", "timedelta"]
