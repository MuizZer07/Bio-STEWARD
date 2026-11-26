"""Licence governance from the first commit (0.19.0; REQ-012).

A project declares its licence (an SPDX expression), its distribution state (internal, network, public) and a policy
profile. Steward then checks, deterministically and offline:

- **R-79 licence.declared**: LICENSE, package metadata (pyproject.toml, package.json, DESCRIPTION) and CITATION.cff
  agree with the declared licence;
- **R-80 licence.dependencies**: every dependency's licence (from its installed metadata: the SPDX
  `License-Expression` first, then the licence classifiers, then the free-text field) is compatible with the policy
  for the distribution state; an unknown licence is UNKNOWN, never a pass; weak copyleft passes with its obligation
  stated when the profile allows it; a public project needs a current third-party notices file;
- **R-81 licence.code**: copied, ported or translated code declared in `third_party` and files carrying
  `SPDX-License-Identifier:` or `Derived-from:` headers are compatible;
- **R-82 licence.provenance (advisory)**: comments that suggest an undeclared port ("ported from", "translated from",
  "adapted from") are listed for a human to look at; never a pass or a fail by themselves.

Exceptions carry a reason, a scope, an approver, a date and an expiry; an expired one fails. The compatibility tables
are declared policy data, not legal advice: legal interpretation stays with the human, and the reports say so.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from datetime import date
from email.parser import Parser
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import Strict, Text

LEGAL = "Checks declared rules and package metadata only; this is not legal advice."

# ---------------------------------------------------------------- licence families (policy data)
PERMISSIVE = {
    "MIT", "MIT-0", "MIT-CMU", "BSD-2-Clause", "BSD-3-Clause", "BSD-3-Clause-Clear", "BSD-4-Clause", "0BSD", "ISC",
    "Apache-2.0", "PSF-2.0", "Python-2.0", "HPND", "Zlib", "Unlicense", "CC0-1.0", "BSL-1.0", "NCSA", "X11", "curl",
    "W3C", "Artistic-2.0", "CC-BY-4.0", "BlueOak-1.0.0", "UPL-1.0", "PostgreSQL", "OFL-1.1",
}
WEAK = {"LGPL-2.0", "LGPL-2.1", "LGPL-3.0", "MPL-1.1", "MPL-2.0", "EPL-1.0", "EPL-2.0", "CDDL-1.0", "CDDL-1.1", "EUPL-1.2",
        "CC-BY-SA-4.0"}
STRONG = {"GPL-1.0", "GPL-2.0", "GPL-3.0"}
NETWORK = {"AGPL-1.0", "AGPL-3.0", "SSPL-1.0", "OSL-3.0"}
OBLIGATION = {
    "weak": "weak copyleft: keep its notices; link to it without modifying its files (changes to its own files must "
            "be shared under its terms)",
    "strong": "strong copyleft: distributing a combined work requires the whole under compatible terms",
    "network": "network copyleft: offering it over a network triggers the source obligation, without distribution",
}

CLASSIFIERS = {
    "MIT License": "MIT", "BSD License": "BSD-3-Clause", "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0", "zlib/libpng License": "Zlib",
    "The Unlicense (Unlicense)": "Unlicense", "Public Domain": "Unlicense", "Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0", "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0", "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0", "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0", "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0",
    "GNU General Public License (GPL)": "GPL-2.0", "GNU Affero General Public License v3": "AGPL-3.0",
    "GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0",
}


def base_id(spdx: str) -> str:
    """`GPL-2.0-or-later` → `GPL-2.0`; `LGPL-3.0-only` → `LGPL-3.0`; `GPL-3.0+` → `GPL-3.0`."""
    return re.sub(r"(-or-later|-only|\+)$", "", spdx.strip())


def family(spdx: str) -> str:
    """permissive | weak | strong | network | unknown, for one SPDX identifier."""
    b = base_id(spdx)
    for fam, ids in (("permissive", PERMISSIVE), ("weak", WEAK), ("strong", STRONG), ("network", NETWORK)):
        if b in ids:
            return fam
    if b.startswith("LicenseRef-"):
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------- SPDX expressions
TOKEN = re.compile(r"\s*(\(|\)|AND\b|OR\b|WITH\b|[A-Za-z0-9.+:-]+)\s*")


def parse_expr(expr: str) -> Any:
    """A small SPDX expression parser: ('OR', [...]) / ('AND', [...]) / an identifier string. ValueError when
    malformed. `X WITH exception` keeps X (an exception only relaxes it)."""
    toks = [t for t in TOKEN.findall(expr or "") if t]
    if not toks or "".join(toks).replace(" ", "") != re.sub(r"\s+", "", expr or ""):
        raise ValueError(f"not an SPDX expression: {expr!r}")
    pos = 0

    def atom() -> Any:
        nonlocal pos
        if pos >= len(toks):
            raise ValueError("unexpected end")
        t = toks[pos]
        pos += 1
        if t == "(":
            e = orexpr()
            if pos >= len(toks) or toks[pos] != ")":
                raise ValueError("unbalanced parenthesis")
            pos += 1
            return e
        if t in (")", "AND", "OR", "WITH"):
            raise ValueError(f"unexpected {t}")
        if pos < len(toks) and toks[pos] == "WITH":
            if pos + 1 >= len(toks) or toks[pos + 1] in ("(", ")", "AND", "OR", "WITH"):
                raise ValueError("WITH needs an exception identifier")
            pos += 2
        return t

    def andexpr() -> Any:
        nonlocal pos
        items = [atom()]
        while pos < len(toks) and toks[pos] == "AND":
            pos += 1
            items.append(atom())
        return items[0] if len(items) == 1 else ("AND", items)

    def orexpr() -> Any:
        nonlocal pos
        items = [andexpr()]
        while pos < len(toks) and toks[pos] == "OR":
            pos += 1
            items.append(andexpr())
        return items[0] if len(items) == 1 else ("OR", items)
    e = orexpr()
    if pos != len(toks):
        raise ValueError("trailing tokens")
    return e


def ids_of(e: Any) -> list[str]:
    return [e] if isinstance(e, str) else [i for x in e[1] for i in ids_of(x)]


FAMILY_ORDER = ["permissive", "weak", "strong", "network", "unknown"]


def expr_family(e: Any) -> str:
    """The family an expression binds a user to (AF11): OR takes the least restrictive option, AND keeps the most
    restrictive part (its copyleft component is required)."""
    if isinstance(e, str):
        return family(e)
    fams = [expr_family(x) for x in e[1]]
    pick = min if e[0] == "OR" else max
    return pick(fams, key=FAMILY_ORDER.index)


# ---------------------------------------------------------------- configuration
class Exception_(Strict):
    target: Text                    # a package name or a path glob
    licence: Text                   # the SPDX expression it is accepted under
    reason: Text
    scope: Text = "project"
    approver: Text
    date: date
    expires: date


class ExceptionsFile(Strict):
    schema_: Literal["steward.licence-exceptions/1"] = Field(alias="schema")
    exception: list[Exception_] = Field(default_factory=list)


class ThirdParty(Strict):
    path: Text                      # a file or a glob
    licence: Text                   # SPDX expression of the source
    source: Text                    # where it came from (project, file, URL)
    kind: Literal["vendored", "ported", "translated", "snippet", "data", "asset"] = "vendored"


class ThirdPartyFile(Strict):
    schema_: Literal["steward.third-party/1"] = Field(alias="schema")
    item: list[ThirdParty] = Field(default_factory=list)


# ---------------------------------------------------------------- the policy
def verdict(expr: str, cfg: Any) -> tuple[str, str]:
    """(status, why) for one SPDX expression under the project's `[licence]`: PASS, PASS_OBLIGATION, FAIL or UNKNOWN.
    OR takes the most acceptable option; AND needs every part acceptable."""
    lc = cfg.licence
    try:
        e = parse_expr(expr)
    except ValueError:
        return "UNKNOWN", f"{expr!r} is not an SPDX expression"
    rank = {"PASS": 0, "PASS_OBLIGATION": 1, "UNKNOWN": 2, "FAIL": 3}

    def one(i: str) -> tuple[str, str]:
        if any(fnmatch.fnmatchcase(i, d) for d in lc.deny):
            return "FAIL", f"{i} is on the deny list"
        if any(fnmatch.fnmatchcase(i, a) for a in lc.allow):
            return "PASS", f"{i} is on the allow list"
        fam = family(i)
        if fam == "unknown":
            return "UNKNOWN", f"{i}: not a licence the policy knows (add it to allow or deny)"
        if fam == "permissive":
            return "PASS", f"{i}: permissive"
        if lc.distribution == "internal":
            return "PASS_OBLIGATION", f"{i}: {OBLIGATION[fam]} (internal use: no distribution yet)"
        if fam == "network":
            return "FAIL", f"{i}: {OBLIGATION[fam]}"
        if lc.distribution == "network":  # copyleft without network clauses: no distribution yet
            return "PASS_OBLIGATION", f"{i}: {OBLIGATION[fam]} (network use: not distributed)"
        ok = {"permissive-only": set(), "weak-copyleft-ok": {"weak"}, "gpl-compatible": {"weak", "strong"}}[lc.policy]
        if fam in ok:
            return "PASS_OBLIGATION", f"{i}: {OBLIGATION[fam]}"
        return "FAIL", f"{i}: {OBLIGATION[fam]}; not allowed by the {lc.policy} policy for a public project"

    def ev(x: Any) -> tuple[str, str]:
        if isinstance(x, str):
            return one(x)
        parts = [ev(p) for p in x[1]]
        if x[0] == "OR":
            return min(parts, key=lambda p: rank[p[0]])
        worst = max(parts, key=lambda p: rank[p[0]])
        return worst[0], "; ".join(w for _, w in parts)
    return ev(e)


# ---------------------------------------------------------------- declared licence consistency (R-79)
LICENSE_TEXTS = [
    ("MIT", re.compile(r"Permission is hereby granted, free of charge", re.I)),
    ("Apache-2.0", re.compile(r"Apache License,?\s+Version 2\.0", re.I)),
    ("BSD-3-Clause", re.compile(r"Neither the name of .{0,200} nor the names of", re.I | re.S)),
    ("BSD-2-Clause", re.compile(r"Redistribution and use in source and binary forms", re.I)),
    ("GPL-3.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("GPL-2.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 2", re.I)),
    ("AGPL-3.0", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("LGPL-3.0", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("MPL-2.0", re.compile(r"Mozilla Public License,?\s+(?:v\.|version)\s*2\.0", re.I)),
    ("ISC", re.compile(r"Permission to use, copy, modify, and/or distribute this software for any", re.I)),
]


def identify_licence_text(text: str) -> str | None:
    """The SPDX id a LICENSE text reads as (the first match in a fixed order: BSD-3 before BSD-2), or None."""
    hits = [i for i, rx in LICENSE_TEXTS if rx.search(text)]
    if "BSD-3-Clause" in hits:  # the 3-clause text contains the 2-clause opening
        hits = [h for h in hits if h != "BSD-2-Clause"]
    return hits[0] if len(hits) == 1 else None  # none, or ambiguous: never guessed


def same_licence(a: str, b: str) -> bool:
    """Two declarations name the same licence: identical expressions, ignoring case, spacing and -only/-or-later on
    single identifiers."""
    norm = lambda s: re.sub(r"\s+", " ", s.strip()).upper()
    if norm(a) == norm(b):
        return True
    if "WITH" in norm(a) or "WITH" in norm(b):  # AF9: an exception clause makes another licence
        return False
    try:
        ea, eb = parse_expr(a), parse_expr(b)
    except ValueError:
        return False
    if isinstance(ea, str) and isinstance(eb, str):
        return base_id(ea).upper() == base_id(eb).upper()
    return False


def declarations(root: Path, read) -> list[tuple[str, str | None]]:
    """[(source, the licence it states, or None when it states none readable)] for every declaration file present."""
    out: list[tuple[str, str | None]] = []

    def text(rel: str) -> str | None:
        try:
            return read(rel).decode("utf-8", errors="replace")
        except OSError:
            return None
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING"):
        t = text(name)
        if t is not None:
            out.append((name, identify_licence_text(t)))
            break
    t = text("pyproject.toml")
    if t is not None:
        try:
            proj = tomllib.loads(t).get("project", {})
        except ValueError:
            proj = {}
        lic = proj.get("license")
        if isinstance(lic, str):
            out.append(("pyproject.toml", lic))
        elif isinstance(lic, dict) and isinstance(lic.get("text"), str):
            out.append(("pyproject.toml", lic["text"].strip()))
        else:
            cls = [CLASSIFIERS.get(c.split("::")[-1].strip()) for c in proj.get("classifiers", []) if c.startswith("License ::")]
            if [c for c in cls if c]:
                out.append(("pyproject.toml (classifier)", next(c for c in cls if c)))
    t = text("package.json")
    if t is not None:
        import json

        try:
            v = json.loads(t).get("license")
        except (ValueError, AttributeError):
            v = None
        out.append(("package.json", v if isinstance(v, str) else None))
    t = text("DESCRIPTION")
    if t is not None:
        m = re.search(r"^License:\s*(.+)$", t, re.M)
        out.append(("DESCRIPTION", re.sub(r"\s*\+\s*file\s+LICEN[CS]E", "", m.group(1)).strip() if m else None))
    t = text("CITATION.cff")
    if t is not None:
        m = re.search(r"^license:\s*['\"]?([^'\"\n]+)", t, re.M)
        out.append(("CITATION.cff", m.group(1).strip() if m else None))
    return out


# ---------------------------------------------------------------- dependency inventory (R-80)
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed(root: Path, globs: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """({normalised name: {name, version, licence, how}}, problems) from the `*.dist-info/METADATA` files under the
    declared site-packages folders (the project's environment, never the toolkit's own). Every file is read inside
    the repository without following a link (AF12); a refused one is a problem, never a smaller inventory. The licence
    comes from `License-Expression` (PEP 639), else the licence classifiers, else the free-text field when it is one
    SPDX id."""
    from .records import RecordRefused, read_rel

    out: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for g in globs:
        parts, linked = Path(g).parts, []
        for i in range(1, len(parts) + 1):  # AF12: every folder the pattern passes through, matched in full or not
            linked = [c for c in sorted(root.glob("/".join(parts[:i]))) if c.is_symlink()]
            if linked:  # AK6: never expanded beneath a link
                break
        if linked:
            problems += [f"{x.relative_to(root).as_posix()}: reached through a link" for x in linked]
            continue
        for sp in sorted(root.glob(g)):
            rel_sp = sp.relative_to(root).as_posix() if sp.is_relative_to(root) else None
            if rel_sp is None:
                continue
            cur = root
            linked = False
            for part in Path(rel_sp).parts:
                cur = cur / part
                linked = linked or cur.is_symlink()
            if linked:  # AF12: an environment reached through a link is a problem, even when it holds nothing
                problems.append(f"{rel_sp}: reached through a link")
                continue
            if not sp.is_dir():
                continue
            for di in sorted(sp.glob("*.dist-info")):  # AF12: a linked distribution folder is named, METADATA or not
                if di.is_symlink():
                    problems.append(f"{di.relative_to(root).as_posix()}: reached through a link")
            for meta in sorted(sp.glob("*.dist-info/METADATA")):
                if meta.parent.is_symlink():
                    continue
                rel = meta.relative_to(root).as_posix()
                try:
                    md = Parser().parsestr(read_rel(root, rel).decode("utf-8", errors="replace"), headersonly=True)
                except RecordRefused as e:
                    problems.append(f"{rel}: {e}")
                    continue
                name = md.get("Name") or ""
                if not name:
                    continue
                lic, how = md.get("License-Expression"), "License-Expression"
                if not lic:
                    cls = [CLASSIFIERS.get(c.split("::")[-1].strip()) for c in md.get_all("Classifier") or []
                           if c.startswith("License ::")]
                    cls = sorted({c for c in cls if c})
                    if cls:
                        lic, how = " OR ".join(cls) if len(cls) > 1 else cls[0], "classifier"
                if not lic:
                    free = (md.get("License") or "").strip()
                    if free and re.fullmatch(r"[A-Za-z0-9.+-]+", free) and family(free) != "unknown":
                        lic, how = free, "License field"
                out[_norm(name)] = {"name": name, "version": md.get("Version") or "", "licence": lic, "how": how if lic else None}
    return out, problems


def lock_packages(text: str, rel: str) -> list[tuple[str, str]]:
    """(name, version) of the packages a lockfile pins: uv.lock / poetry.lock ([[package]] tables) or a
    requirements file (name==version lines)."""
    out: list[tuple[str, str]] = []
    if rel.endswith(".lock"):
        try:
            doc = tomllib.loads(text)
        except ValueError:
            raise ValueError(f"{rel} is not valid TOML") from None
        pkgs = doc.get("package", [])
        if not isinstance(pkgs, list) or any(not isinstance(p, dict) or not isinstance(p.get("name"), str)
                                             for p in pkgs):
            raise ValueError(f"{rel} has a [[package]] entry without a name")  # AF7: never read as fewer packages
        for p in pkgs:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                src = p.get("source") if isinstance(p.get("source"), dict) else {}
                if src.get("editable") == "." or src.get("virtual") == ".":
                    continue  # the project itself
                v = p.get("version", "")
                if not isinstance(v, str):  # AF7: a version is text; a number or a table is not evidence of one
                    raise ValueError(f"{rel}: the version of {p['name']} is not a string")
                out.append((p["name"], v))
        return out
    include = re.compile(r"^(-[rce]|--requirement|--constraint|--editable)|^(\.|/|file:|git\+)")
    for line in text.lstrip("\ufeff").splitlines():  # AM1: read as pip reads it: no byte-order mark
        body = line.split(" #", 1)[0] if not line.lstrip().startswith("#") else ""
        if any(include.match(tok) for tok in body.split()):  # AM1: an include anywhere on the line, after any option
            raise ValueError(f"{rel}: {line.strip()[:60]}: an include, editable or local entry is not a pinned version")
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;#]+)", line)
        if m:
            out.append((m.group(1), m.group(2)))
        elif re.match(r"^\s*[A-Za-z0-9]", line):  # AF7: an unpinned requirement is not evidence of a version
            raise ValueError(f"{rel}: {line.strip()[:60]} is not pinned with ==")
        elif re.match(r"^\s*(-[rce]|--requirement|--constraint|--editable)|^\s*(\.|/|file:|git\+)", line):  # AF7: -rFILE too
            raise ValueError(f"{rel}: {line.strip()[:60]}: an include, editable or local entry is not a pinned version")
    return out


def inventory(root: Path, cfg: Any, read, env_root: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """([{name, version, licence, how, status, why, exception?}], problems). With a lockfile, every package it pins is
    judged (one not installed is UNKNOWN); without one, every installed distribution."""
    lc = cfg.licence
    env, problems = installed(env_root or root, lc.site_packages)
    if lc.lockfile:
        try:
            pins = lock_packages(read(lc.lockfile).decode("utf-8", errors="replace"), lc.lockfile)
        except OSError:
            return [], [f"the lockfile {lc.lockfile} cannot be read"]
        except ValueError as e:  # AF7: an unreadable lock is never an empty inventory
            return [], [str(e)]
        names = [(n, v) for n, v in pins]
    else:
        names = [(d["name"], d["version"]) for d in env.values()]
        if not env:
            problems.append("no installed distributions found under site_packages (declare the project's environment)")
    project = _norm(project_name(root, read) or "")
    skip = {_norm(x) for x in lc.ignore_packages} | {project}
    exc = exceptions(root, cfg, read)
    rows = []
    for n, v in sorted(set(names), key=lambda x: _norm(x[0])):
        if _norm(n) in skip:
            continue
        d = env.get(_norm(n))
        lic = d["licence"] if d else None
        row: dict[str, Any] = {"name": n, "version": v or (d or {}).get("version", ""), "licence": lic,
                               "how": d["how"] if d else None}
        if lc.lockfile and not v:  # AF7: a pin needs its version
            row["licence"], lic = None, None
            row["status"], row["why"] = "UNKNOWN", "locked without a version: the evidence cannot be matched"
        elif d is not None and v and d["version"] != v:  # AF7: the locked version's own metadata (none: unknown)
            row["licence"], lic = None, None
            row["status"], row["why"] = "UNKNOWN", f"installed {d['version']}, locked {v}: the locked version's licence is not known"
        elif lic is None:
            row["status"], row["why"] = "UNKNOWN", ("not installed in the declared environment" if d is None
                                                    else "no licence in its metadata")
        else:
            row["status"], row["why"] = verdict(lic, cfg)
        e = match_exception(exc, n, lic)
        if e is not None and row["status"] in ("FAIL", "UNKNOWN"):
            if e.expires < date.today():
                row["status"], row["why"] = "FAIL", f"exception expired {e.expires} ({e.reason})"
            else:
                row["status"], row["why"], row["exception"] = "PASS", f"exception until {e.expires}: {e.reason} (approved by {e.approver})", True
        rows.append(row)
    return rows, problems


def project_name(root: Path, read) -> str | None:
    try:
        return tomllib.loads(read("pyproject.toml").decode("utf-8")).get("project", {}).get("name")
    except (OSError, ValueError):
        return None


def exceptions(root: Path, cfg: Any, read) -> list[Exception_]:
    if not cfg.licence.exceptions:
        return []
    try:
        return ExceptionsFile.model_validate(tomllib.loads(read(cfg.licence.exceptions).decode("utf-8"))).exception
    except OSError:
        return []


def match_exception(exc: list[Exception_], target: str, licence: str | None) -> Exception_ | None:
    """The exception for this target and exactly this licence (AF9): a target whose licence changed is judged again."""
    for e in exc:
        in_scope = e.scope == "project" or fnmatch.fnmatchcase(target, e.scope) or _norm(e.scope) == _norm(target)
        exact = re.sub(r"\s+", " ", e.licence.strip()).upper() == re.sub(r"\s+", " ", (licence or "").strip()).upper()
        if (_norm(e.target) == _norm(target) or fnmatch.fnmatchcase(target, e.target)) and licence is not None \
                and in_scope and exact:  # AF9: -only and -or-later are distinct licences for an exception
            return e
    return None


# ---------------------------------------------------------------- copied and ported code (R-81, R-82)
CODE_EXT = (".py", ".r", ".R", ".js", ".ts", ".jsx", ".tsx", ".c", ".h", ".cc", ".cpp", ".hpp", ".go", ".rs", ".java",
            ".jl", ".sh", ".m", ".f90", ".pl", ".rb", ".scala", ".kt", ".swift", ".cs", ".sql")
COMMENT = r"^[ \t]*(?:#+|//+|/\*+|\*+|--+|;+|%+|<!--)[ \t]*"   # a header sits on a comment line of its own
SPDX_HDR = re.compile(COMMENT + r"SPDX-License-Identifier:[ \t]*([A-Za-z0-9.+:()\- ]+?)[ \t]*(?:\*/|-->)?[ \t]*$", re.M)
DERIVED_HDR = re.compile(COMMENT + r"Derived-from:[ \t]*([^()\n]+?)[ \t]*\(([A-Za-z0-9.+:()\- ]+)\)[ \t]*(?:\*/|-->)?[ \t]*$",
                         re.M)
COMMENT_LINE = re.compile(r"^[ \t]*(?:#|//|/\*|\*(?!\*)|--|;|%|<!--)|[ \t]#[ \t]")  # a comment line, or a trailing # comment
HINT = re.compile(r"\b(ported from|port of|translated from|translation of|adapted from|copied from|"
                  r"based on [A-Z][\w.+-]*'s|taken from)\b", re.I)


def code_findings(root: Path, cfg: Any, files: list[str], read) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(R-81 findings, R-82 hints). R-81: every declared third-party item and every header that names another
    licence, judged by the policy; R-82: undeclared port markers in code comments."""
    lc = cfg.licence
    tp: list[ThirdParty] = []
    if lc.third_party:
        try:
            tp = ThirdPartyFile.model_validate(tomllib.loads(read(lc.third_party).decode("utf-8"))).item
        except OSError:
            pass
    declared_paths = [t.path for t in tp]
    exc = exceptions(root, cfg, read)
    findings, hints = [], []

    def judge(path: str, lic: str, what: str) -> None:
        st, why = verdict(lic, cfg)
        e = match_exception(exc, path, lic)
        if e is not None and st in ("FAIL", "UNKNOWN"):
            st, why = ("FAIL", f"exception expired {e.expires}") if e.expires < date.today() else \
                ("PASS", f"exception until {e.expires}: {e.reason} (approved by {e.approver})")
        findings.append({"path": path, "licence": lic, "status": st, "why": f"{what}: {why}"})
    for t in tp:
        matched = [f for f in files if fnmatch.fnmatchcase(f, t.path)] or [t.path]
        for f in matched:
            judge(f, t.licence, f"{t.kind} from {t.source}")
    for f in files:
        if not f.endswith(CODE_EXT):
            continue
        try:
            text = read(f).decode("utf-8", errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:40])
        decl = [t for t in tp if fnmatch.fnmatchcase(f, t.path)]
        declared = bool(decl)
        for m in DERIVED_HDR.finditer(head):  # AF10: a header is judged even when the file is declared
            judge(f, m.group(2).strip(), f"Derived-from {m.group(1).strip()}")
            if decl and not any(same_licence(m.group(2).strip(), t.licence) for t in decl):
                findings.append({"path": f, "licence": m.group(2).strip(), "status": "FAIL",
                                 "why": f"the header's licence differs from the third_party declaration ({decl[0].licence})"})
        for m in SPDX_HDR.finditer(head):
            lic = m.group(1).strip()
            if declared and not any(same_licence(lic, t.licence) for t in decl):
                findings.append({"path": f, "licence": lic, "status": "FAIL",
                                 "why": f"the SPDX header differs from the third_party declaration ({decl[0].licence})"})
            elif not same_licence(lic, lc.declared):
                judge(f, lic, "SPDX-License-Identifier header")
        if declared or DERIVED_HDR.search(head):
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if HINT.search(line) and COMMENT_LINE.search(line):
                hints.append({"path": f, "line": n, "text": HINT.search(line).group(0)})
    return findings, hints


# ---------------------------------------------------------------- notices and SBOM
def notices_text(rows: list[dict[str, Any]], cfg: Any, project: str) -> str:
    lines = [f"Third-party notices for {project}", "", f"{project} is licensed under {cfg.licence.declared}. It depends on "
             "the following packages, each under its own licence.", ""]
    for r in sorted(rows, key=lambda r: r["name"].lower()):
        lines.append(f"- {r['name']} {r['version']}: {r['licence'] or 'UNKNOWN'}")
    lines += ["", LEGAL, ""]
    return "\n".join(lines)


def notices_current(text: str, rows: list[dict[str, Any]]) -> list[str]:
    """The packages (with their licence) the notices file does not name."""
    lines = {ln.strip() for ln in text.splitlines()}  # AF11: the exact line notices_text writes, nothing looser
    return [f"{r['name']} {r['version']} {r['licence'] or 'UNKNOWN'}" for r in rows
            if f"- {r['name']} {r['version']}: {r['licence'] or 'UNKNOWN'}" not in lines]


def cyclonedx(rows: list[dict[str, Any]], project: str, version: str) -> dict[str, Any]:
    """A minimal CycloneDX 1.5 SBOM: one component per dependency with its licence expression."""
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": project, "version": version}},
            "components": [{"type": "library", "name": r["name"], "version": r["version"],
                            **({"licenses": [{"expression": r["licence"]}]} if r["licence"] else {})}
                           for r in sorted(rows, key=lambda r: r["name"].lower())]}


# ---------------------------------------------------------------- the release gate (AF5)
def release_findings(root: Path, cfg: Any, files: dict[str, bytes]) -> list[str]:
    """Licence findings for exactly the files a release publishes (AF5), at public strictness: R-79's declarations
    (a LICENSE file is required), R-80's inventory (the environment is the working checkout's: a release holds no
    installed packages), current notices among the published files, and R-81's code. FAIL, UNKNOWN and INCOMPLETE
    all refuse."""
    import tempfile

    pub_cfg = cfg.model_copy(update={"licence": cfg.licence.model_copy(update={"distribution": "public"})})
    out: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for rel, data in files.items():
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        read = lambda rel: (tmp / rel).read_bytes()  # noqa: E731 - the export, in a private folder
        decl = declarations(tmp, read)
        if not any(src.startswith(("LICENSE", "LICENCE", "COPYING")) for src, _ in decl):
            out.append("R-79: no LICENSE file among the published files")
        for src, stated in decl:
            if stated is None:
                out.append(f"R-79: {src} states no identifiable licence")
            elif not same_licence(stated, cfg.licence.declared):
                out.append(f"R-79: {src} states {stated}, not {cfg.licence.declared}")
        rows, problems = inventory(tmp, pub_cfg, read, env_root=root)
        out += [f"R-80: {p}" for p in problems]
        out += [f"R-80: {x['name']} {x['version']}: {x['status']} ({x['why']})" for x in rows
                if x["status"] in ("FAIL", "UNKNOWN")]
        if pub_cfg.licence.notices in files:
            stale = notices_current(files[pub_cfg.licence.notices].decode("utf-8", "replace"), rows)
            out += [f"R-80: the notices do not name {s_}" for s_ in stale[:10]]
        else:
            out.append(f"R-80: {pub_cfg.licence.notices} is not among the published files (steward licence notices --write)")
        found, _ = code_findings(tmp, pub_cfg, sorted(files), read)
        out += [f"R-81: {f['path']}: {f['status']} ({f['why']})" for f in found if f["status"] in ("FAIL", "UNKNOWN")]
    return out
