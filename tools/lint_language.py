"""Verification-language lint (DESIGN_v0.4 §3): toolkit text says what was checked, never what is true.

    python tools/lint_language.py            # exit 1 and list findings when a disallowed phrase is used

Scans README.md, skills/, templates/, docs/, examples/ and the report renderer strings. A line may quote a disallowed phrase as a
counter-example when it carries the marker ``lint: allow``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["README.md", "skills", "templates", "docs", "examples", "src/steward/report.py", "src/steward/engine.py"]
ALLOW_MARKER = "lint: allow"

DISALLOWED = [
    (re.compile(r"\bprov(e|es|ed|en|ing)\b", re.I), "claims proof"),
    (re.compile(r"\bguarantee(s|d)?\b", re.I), "claims a guarantee"),
    (re.compile(r"\bfair(ly|ness)?\b", re.I), "claims fairness"),
    (re.compile(r"\b(is|are|was|were|be)\s+(scientifically\s+)?(valid|correct|true)\b", re.I), "claims validity or truth"),
    (re.compile(r"\b(valid|correct|verified)\s+(result|finding|claim|conclusion|science)s?\b", re.I), "claims validity"),
    (re.compile(r"\breproducib(le|ility)\b", re.I), "unqualified reproducibility; say 'repeatable within tolerance' or 'artifact integrity'"),
    (re.compile(r"\bcertif(y|ies|ied)\b", re.I), "claims certification"),
    # A7 (DESIGN_v0.5 §4): never advise skipping verification to save tokens or time.
    (re.compile(r"(?<!not )(?<!never )(?<!n't )\bskip(ping)? (the |a |any )?(steward |deterministic )?(check|rule|gate|verification)", re.I),
     "advises skipping verification"),
    (re.compile(r"\bno need to (run|check|verify)\b", re.I), "advises skipping verification"),
    (re.compile(r"\bto save (tokens|context|time)\b", re.I), "trades verification for cost"),
]


def files(root: Path) -> list[Path]:
    out: list[Path] = []
    for t in TARGETS:
        p = root / t
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.is_file() and q.suffix in {".md", ".toml", ".tmpl", ".py", ".txt"})
    return out


# The toolkit's own name (Scientific Toolkit for Engineering, Workflow Assurance, Reproducibility, and Development),
# also when a line break falls inside it: a name, not a claim.
NAME = re.compile(r"Assurance,\s+Reproducibility,\s+and\b")


def lint_text(text: str) -> list[tuple[int, str, str]]:
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        line = NAME.sub("Assurance, and", line)
        for pat, why in DISALLOWED:
            m = pat.search(line)
            if m:
                found.append((n, m.group(0), why))
    return found


def main(root: Path = ROOT) -> int:
    bad = 0
    for f in files(root):
        for n, phrase, why in lint_text(f.read_text(encoding="utf-8")):
            print(f"{f.relative_to(root)}:{n}: '{phrase}' ({why})")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
