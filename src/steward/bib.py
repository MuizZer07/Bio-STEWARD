"""Minimal, dependency-free BibTeX reader and citation helpers for R-14 (PaperKit v0.2.3).

It reads entry types, keys and fields (braced, quoted or bare values, nested braces). It does not expand @string
macros or cross-references; entries using them are still listed, with the raw field text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DOI = re.compile(r"^10\.\d{4,9}/\S+$")
PMID = re.compile(r"^[1-9]\d{0,8}$")
ARXIV = re.compile(r"^(\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(v\d+)?$")
CITE = re.compile(r"\\(?:no)?cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")


class BibError(ValueError):
    pass


@dataclass
class Entry:
    type: str
    key: str
    line: int
    fields: dict[str, str] = field(default_factory=dict)


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at == -1:
            return entries
        m = re.match(r"@\s*([A-Za-z]+)\s*([{(])", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        open_ch = m.group(2)
        close_ch = "}" if open_ch == "{" else ")"
        start = at + m.end()
        depth, j = 1, start
        while j < n and depth:
            if text[j] == open_ch:
                depth += 1
            elif text[j] == close_ch:
                depth -= 1
            j += 1
        if depth:
            raise BibError(f"unbalanced braces in entry starting at line {text.count(chr(10), 0, at) + 1}")
        body = text[start:j - 1]
        i = j
        if etype in ("comment", "string", "preamble"):
            continue
        key, _, rest = body.partition(",")
        key = key.strip()
        if not key:
            raise BibError(f"entry without a key at line {text.count(chr(10), 0, at) + 1}")
        entries.append(Entry(etype, key, text.count("\n", 0, at) + 1, _fields(rest)))


def _fields(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        m = re.match(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*", s[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        if i < n and s[i] == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(s[j], 0)
                j += 1
            out[name] = s[i + 1:j - 1].strip()
            i = j
        elif i < n and s[i] == '"':
            j = s.find('"', i + 1)
            j = n if j == -1 else j
            out[name] = s[i + 1:j].strip()
            i = j + 1
        else:
            m2 = re.match(r"[^,]*", s[i:])
            out[name] = m2.group(0).strip() if m2 else ""
            i += m2.end() if m2 else 1
    return out


def normalise_doi(value: str) -> str:
    v = value.strip()
    v = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", v, flags=re.I)
    return v


def identifiers(e: Entry) -> dict[str, str]:
    ids = {}
    if "doi" in e.fields:
        ids["doi"] = normalise_doi(e.fields["doi"])
    if "pmid" in e.fields:
        ids["pmid"] = e.fields["pmid"].strip()
    if "eprint" in e.fields and e.fields.get("archiveprefix", e.fields.get("eprinttype", "")).lower() == "arxiv":
        ids["arxiv"] = e.fields["eprint"].strip()
    if "url" in e.fields:
        ids["url"] = e.fields["url"].strip()
    return ids


def malformed(ids: dict[str, str]) -> list[str]:
    bad = []
    if "doi" in ids and not DOI.match(ids["doi"]):
        bad.append(f"doi {ids['doi']!r}")
    if "pmid" in ids and not PMID.match(ids["pmid"]):
        bad.append(f"pmid {ids['pmid']!r}")
    if "arxiv" in ids and not ARXIV.match(ids["arxiv"]):
        bad.append(f"arxiv {ids['arxiv']!r}")
    return bad
