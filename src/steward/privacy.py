"""Term lists and local-path detection (0.8.1: SR-004, AR-04, SR-005, FB-2, FB-3, FB-11), shared by R-07 and
`steward release audit` so the rule and the command apply the same scan.

- **Lists.** `[[terms]]` tables, plus the legacy `[privacy] denylist_file` (a private list named `denylist`).
  - A **private** list's hits never show the term, only `list:line`.
  - A **public** list's hits show the term: it is published policy.
- **Term lines.** A plain line matches whole words. `substr:TEXT` matches inside identifiers. With `patterns = true`,
  each line is a regular expression.
- **Local paths.** Absolute home paths with a user name (`/Users/<name>/`, `/home/<name>/`, `C:\\Users\\<name>\\`);
  the path itself is never shown.
- **Exemptions.** List files themselves, `allow` globs, and any line containing the marker `steward: allow R-07`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fsutil import glob_match

MARKER = "steward: allow R-07"
CONTROLLED_ACCESS = re.compile(
    r"(?<![A-Za-z0-9])(?:ph[astv][0-9]{6}|EGA[CDFNPRS][0-9]{11})(?![A-Za-z0-9])",
    re.IGNORECASE | re.ASCII,
)
CONTROLLED_ACCESS_MESSAGE = "A controlled-access accession. Keep it in a private record."
# a macOS user name may contain spaces (review N7)
# T8: a bare home directory (no separator after the name) is a local path too; it ends at a character that cannot
# continue a user name or a path. The bare forms take a name without spaces, as a space ends the path in prose.
_NAME = r"[A-Za-z0-9._-]+(?: [A-Za-z0-9._-]+)*"
_END = r"(?![A-Za-z0-9._\\/-])"
LOCAL_PATH = re.compile(
    rf"(?:/Users/|/home/)(?:({_NAME})/|([A-Za-z0-9._-]+){_END})"
    rf"|\b[A-Za-z]:\\\\?Users\\\\?(?:({_NAME})\\|([A-Za-z0-9._-]+){_END})")
PLACEHOLDER_USERS = {"you", "user", "username", "name", "yourname", "your-name", "me", "example", "shared"}
BINARY_GLOBS = ["**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.otf", "**/*.eot", "**/*.png", "**/*.jpg", "**/*.jpeg",
                "**/*.gif", "**/*.ico", "**/*.webp", "**/*.zip", "**/*.gz", "**/*.tgz", "**/*.whl", "**/*.pyc",
                "**/.DS_Store", ".DS_Store"]


@dataclass
class Term:
    list: str
    line: int
    text: str
    regex: re.Pattern[str]
    public: bool
    occ: list[Any] = field(default_factory=list)  # REQ-009: the list's accepted occurrences

    @property
    def label(self) -> str:
        return f"{self.list}:{self.line}"


@dataclass
class TermSource:
    name: str
    file: str
    public: bool = False
    include: list[str] = field(default_factory=lambda: ["**/*"])
    exclude: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    case_sensitive: bool = False
    patterns: bool = False
    occurrences: list[Any] = field(default_factory=list)
    terms: list[Term] = field(default_factory=list)
    state: str = "ok"  # ok | missing | unreadable | empty
    errors: list[dict[str, Any]] = field(default_factory=list)

    def applies(self, rel: str) -> bool:
        return (any(glob_match(rel, p) for p in self.include) and not any(glob_match(rel, p) for p in self.exclude)
                and not any(glob_match(rel, p) for p in self.allow) and rel != self.file)


def parse(src: TermSource, raw: bytes) -> None:
    flags = 0 if src.case_sensitive else re.IGNORECASE
    for lineno, line in enumerate(raw.decode("utf-8").splitlines(), start=1):  # UnicodeDecodeError: caller
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if src.patterns:
            try:
                rx = re.compile(s, flags)
            except re.error as e:
                src.errors.append({"code": "R-07.bad_pattern", "value": f"{src.name}:{lineno}", "message": str(e)})
                continue
        elif s.startswith("substr:"):
            rx = re.compile(re.escape(s[len("substr:"):]), flags)
        else:
            rx = re.compile(r"(?<!\w)" + re.escape(s) + r"(?!\w)", flags)
        src.terms.append(Term(src.name, lineno, s, rx, src.public, list(src.occurrences)))
    if not src.terms and not src.errors:
        src.state = "empty"


def sources(cfg: Any) -> list[TermSource]:
    out = []
    priv = getattr(cfg, "privacy", None)
    if priv is not None and priv.denylist_file:
        out.append(TermSource("denylist", priv.denylist_file, False, list(priv.include), list(priv.exclude), list(priv.allow)))
    for t in getattr(cfg, "terms", []) or []:
        out.append(TermSource(t.name, t.file, t.public, list(t.include), list(t.exclude), list(t.allow),
                              t.case_sensitive, t.patterns, list(getattr(t, "allow_occurrence", []) or [])))
    return out


def load(root: Path, cfg: Any, read=None) -> list[TermSource]:
    """Every configured list, read (through `read` when given, the check's snapshot)."""
    read = read or (lambda rel: (root / rel).read_bytes())
    out = sources(cfg)
    for src in out:
        if not (root / src.file).is_file():
            src.state = "missing"
            continue
        try:
            parse(src, read(src.file))
        except (OSError, UnicodeDecodeError):
            src.state = "unreadable"
    return out


URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
PATH_OPENERS = set(" \t\"'`=([{<,:;|>")


def _path_start(line: str, m: re.Match[str]) -> bool:
    """A home path is reported only where a filesystem path can begin: at the start of the line, after a space, a
    quote or an opener, or in a file:// URL. A `/home/` or `/Users/` segment inside any other URL, or inside a longer
    path, is not one (DEF-001). The Windows form keeps its word boundary."""
    i = m.start()
    if m.group(3) is not None or m.group(4) is not None:
        return True
    for u in URL.finditer(line):
        if u.group().lower().startswith("file://") or not u.start() <= i < u.end():
            continue
        q = re.search(r"[?#]", u.group())  # Q31: only the scheme, host and path of a URL are exempt, not its query
        if q is None or i < u.start() + q.start():
            return False
    before = line[:i].lower()
    return i == 0 or line[i - 1] in PATH_OPENERS or bool(re.search(r"file://[^/\s]*$", before))


def local_user(match: re.Match[str]) -> str | None:
    name = match.group(1) or match.group(2) or match.group(3) or match.group(4)
    return None if name is None or name.lower() in PLACEHOLDER_USERS else name


def _rules_for(t: Term, rel: str | None, sha: str | None) -> list[Any]:
    """The accepted-occurrence rules of `t` that apply to this file (REQ-009)."""
    if rel is None or not t.occ:
        return []
    return [o for o in t.occ if glob_match(rel, o.path)
            and (o.term == t.line if isinstance(o.term, int) else o.term == t.text)
            and (o.sha256 is None or o.sha256 == sha or sha == "*")]  # "*": a preview; the final text is checked


def _accepted(line: str, m: re.Match[str], rules: list[Any], used: dict[int, int]) -> bool:
    for i, o in enumerate(rules):
        if o.max is not None and used.get(i, 0) >= o.max:
            continue
        if o.context is not None:
            frag = o.context.replace("{term}", m.group())
            off = o.context.index("{term}")
            if not any(k.start() + off == m.start() for k in re.finditer(re.escape(frag), line)):
                continue
        used[i] = used.get(i, 0) + 1
        return True
    return False


def scan_text(text: str, terms: list[Term], local_paths: bool, honour_marker: bool = True, rel: str | None = None,
              sha: str | None = None, *, controlled_access: bool = False) -> tuple[list[dict[str, Any]], int]:
    """(hits, allowed line count). A hit is {line, column, kind, term?}. Publication scans pass
    `honour_marker=False`: a repository's waiver for committed text never waives what is published (T3). With `rel`
    (and the file's `sha`), a list's accepted occurrences apply: an occurrence is accepted only where a rule's path,
    term, context, count and hash all hold; any other occurrence in the same file is a hit (REQ-009)."""
    hits, allowed = [], 0
    rules = {id(t): _rules_for(t, rel, sha) for t in terms}
    used: dict[int, dict[int, int]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        if honour_marker and MARKER in line:
            allowed += 1
            continue
        for t in terms:  # C4 (0.21.0): each hit carries the 1-based column of its first match
            if not rules[id(t)]:
                first = t.regex.search(line)
                if first:
                    hits.append({"line": lineno, "column": first.start() + 1, "kind": "term", "term": t})
                continue
            u = used.setdefault(id(t), {})
            found = list(t.regex.finditer(line))
            verdicts = [_accepted(line, m, rules[id(t)], u) for m in found]  # U14: every match counted
            if not all(verdicts):
                first = next(m for m, ok in zip(found, verdicts) if not ok)
                hits.append({"line": lineno, "column": first.start() + 1, "kind": "term", "term": t})
        if local_paths:
            first = next((m for m in LOCAL_PATH.finditer(line) if _path_start(line, m) and local_user(m)), None)
            if first is not None:
                hits.append({"line": lineno, "column": first.start() + 1, "kind": "local_path"})
        if controlled_access and (first := CONTROLLED_ACCESS.search(line)):
            hits.append({"line": lineno, "column": first.start() + 1, "kind": "controlled_access"})
    return hits, allowed


def exempt(rel: str, lists: list[TermSource], extra_allow: list[str]) -> bool:
    return rel in {s.file for s in lists} or any(glob_match(rel, p) for p in extra_allow)


def screen_incoming(root: Path, cfg: Any, rel: str, data: bytes) -> list[dict[str, Any]]:
    """What R-07 would report for `data` committed at `rel` (FB-018, 0.18.0): the same lists that apply to the path,
    the same local-path scope, the same marker and accepted occurrences. Each hit is {line, what}: a private list's
    term is never named (the report must not leak what it protects). Empty when R-07 is not configured, the file is
    exempt, or nothing is found. Text that is not UTF-8 is one hit: R-07 could not read it either."""
    import hashlib

    priv = getattr(cfg, "privacy", None)
    lists = load(root, cfg)
    if priv is None and not lists:
        return []
    if exempt(rel, lists, []):
        return []
    readable = [s for s in lists if s.state == "ok"]
    own = [t for s in readable if s.applies(rel) for t in s.terms]
    scope_inc = priv.include if priv else ["**/*"]
    scope_exc = priv.exclude if priv else [".git/**", ".steward/**"]
    allow = priv.allow if priv else []
    in_scope = any(glob_match(rel, p) for p in scope_inc) and not any(glob_match(rel, p) for p in scope_exc) \
        and not any(glob_match(rel, p) for p in allow)
    lp = (priv is None or priv.local_paths) and in_scope
    if not own and not in_scope:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [{"line": 0, "what": "not UTF-8 text"}] if own or lp else []
    found, _ = scan_text(text, own, lp, rel=rel, sha=hashlib.sha256(data).hexdigest(), controlled_access=in_scope)
    out = []
    for h in found:
        if h["kind"] == "local_path":
            out.append({"line": h["line"], "what": "a local path with a user name"})
        elif h["kind"] == "controlled_access":
            out.append({"line": h["line"], "what": CONTROLLED_ACCESS_MESSAGE})
        else:
            t = h["term"]
            out.append({"line": h["line"], "what": f"term {t.label}" + (f" ({t.text})" if t.public else "")})
    return out


def private_match(root: Path, cfg: Any, text: str) -> bool:
    """True when `text` (an item ID about to be printed) matches any private term of any list, wherever that list
    applies (AB4): printing is withheld more often than needed, never less."""
    lists = [s for s in load(root, cfg) if s.state == "ok" and not s.public]
    return any(t.regex.search(text) for s in lists for t in s.terms)
