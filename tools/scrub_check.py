"""Scrub check (0.10.0 H6): nothing published names an adopter, a person's home path or an e-mail address.

    python tools/scrub_check.py        # exit 1 and list findings

Adopter names and codes come from development/ADOPTION.md (`- **Name (CODE):**` lines), which is itself not
published content. (The exchange codes in item IDs are traceability kept by decision; scrubbing them is a step of
the public release.) A failed inventory, an empty one, or a
published text file that cannot be read is a finding, never a clean scan (0.10.0 review S6).
Published = tracked files under README.md, docs, skills, templates, src, schemas, examples, tests, tools, CHANGELOG.md,
CONSTITUTION.md. development/ and exchange/ are history kept by decision D5. A line may carry `scrub: allow`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ["README.md", "CHANGELOG.md", "CONSTITUTION.md", "docs", "skills", "templates", "src", "schemas",
             "examples", "tests", "tools", "mkdocs.yml", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md",
             "action.yml", ".pre-commit-hooks.yaml", ".claude-plugin", ".github", "paper", "plugin", "CITATION.cff",
             "pyproject.toml"]
# `…@openssh.com` names are OpenSSH protocol identifiers (key types such as sk-ssh-ed25519@openssh.com), not addresses.
EMAIL = re.compile(r"(?<![\\\w.%+-])[A-Za-z0-9._%+-]+@(?!example\.(?:org|com)\b|noreply\.|openssh\.com\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,6}\b")
HOME = re.compile(r"(?<![\w/])(?:/Users/|/home/)(?!(?:you|user|username|name|someone|example|shared|user2)/)[A-Za-z0-9._-]+/")
ALLOW = "scrub: allow"


def adopter_patterns(root: Path) -> list[re.Pattern[str]]:
    p = root / "development" / "ADOPTION.md"
    names = re.findall(r"^- \*\*([^*(]+?)\s*\(", p.read_text(encoding="utf-8"), re.M) if p.is_file() else []
    out = []
    for n in names:
        core = re.sub(r"[^A-Za-z0-9]", "", n)  # Acme-Tool, AcmeTool, acme_tool, acme tool
        out.append(re.compile(r"[\W_]*".join(re.escape(c) for c in core), re.I))
    return out


BINARY = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip", ".gz", ".whl", ".woff", ".woff2", ".ttf",
          ".otf", ".pptx", ".docx", ".xlsx", ".key", ".sqlite", ".npy", ".parquet")


def adopter_codes(root: Path) -> list[re.Pattern[str]]:
    """Adopter codes from the adoption map: in an ID (`CODE-REQ-001`), or as a whole upper-case word of three or more
    letters (two-letter codes are too common to scan as words)."""
    codes: set[str] = set()
    p = root / "development" / "ADOPTION.md"
    if p.is_file():
        codes |= set(re.findall(r"^- \*\*[^*(]+?\s*\(([A-Z][A-Z0-9]{1,7})\)", p.read_text(encoding="utf-8"), re.M))
    out = [re.compile(rf"\b{re.escape(c)}-[A-Z]+-\d+") for c in sorted(codes)]
    out += [re.compile(rf"\b{re.escape(c)}\b") for c in sorted(codes) if len(c) >= 3]
    return out


def findings(root: Path = ROOT) -> list[str]:
    inv = subprocess.run(["git", "ls-files", "-z", "--", *PUBLISHED], cwd=root, capture_output=True)
    if inv.returncode != 0:
        return [f"inventory: git ls-files failed (exit {inv.returncode}); nothing was scanned"]
    files = [r for r in inv.stdout.split(b"\0") if r]
    if not files:
        return ["inventory: no published files are tracked; nothing was scanned"]
    pats, codes = adopter_patterns(root), adopter_codes(root)
    out = []
    for raw in files:
        rel = raw.decode("utf-8", errors="replace")
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if not rel.lower().endswith(BINARY):
                out.append(f"{rel}: not UTF-8 and not a known binary type; not scanned")
            continue
        except OSError:
            out.append(f"{rel}: cannot be read; not scanned")
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if ALLOW in line or "steward: allow R-07" in line:
                continue
            if any(p.search(line) for p in pats):
                out.append(f"{rel}:{n}: adopter name")
            if any(p.search(line) for p in codes):
                out.append(f"{rel}:{n}: adopter code")
            if EMAIL.search(line):
                out.append(f"{rel}:{n}: e-mail address")
            if HOME.search(line):
                out.append(f"{rel}:{n}: home path")
    return out


def main() -> int:
    found = findings()
    for f in found:
        print(f)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
