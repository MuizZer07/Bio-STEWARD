"""Check the public documentation against the toolkit (0.20.4): every relative link reaches a file the public release
publishes, every documented `steward …` command and flag exists, and every rule ID named exists.

    python tools/check_docs.py      # exit 1 with the problems listed
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LINK = re.compile(r"\]\(([^)\s]+)\)|href=\"([^\"]+)\"|src=\"([^\"]+)\"")


def problems() -> list[str]:
    from steward import publish as pb
    from steward.cli import build_parser
    from steward.models import load_config
    from steward.rules import RULES

    if not (ROOT / "steward.toml").is_file():  # a public clone: what is here is what is published
        return []
    cfg = load_config(ROOT)
    if cfg.publish is None:
        return []
    public = set(pb.export(ROOT, "HEAD", pb.settings(cfg), pb.private_paths(cfg)))
    docs = [d for d in ["README.md"] + sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").glob("**/*.md"))
            + sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "examples").glob("*/README.md")) if d in public]
    out: list[str] = []
    parser = build_parser()
    for d in docs:
        text = (ROOT / d).read_text(encoding="utf-8")
        base = (ROOT / d).parent
        for m in LINK.finditer(text):
            url = next(g for g in m.groups() if g)
            path = url.split("#")[0]
            if re.match(r"^(https?:|mailto:|#)", url) or not path:
                continue
            try:
                rel = (base / path).resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                out.append(f"{d}: link {url} leaves the repository")
                continue
            if not (rel in public or any(p.startswith(rel.rstrip("/") + "/") for p in public)):
                out.append(f"{d}: link {url} " + ("is not published" if (ROOT / rel).exists() else "is missing"))
        out += [f"{d}: no rule R-{r}" for r in sorted(set(re.findall(r"\bR-(\d{2})\b", text))) if f"R-{r}" not in RULES]
        cmds = [m.group(1) for m in re.finditer(r"`(steward [^`]+)`", text)]
        for blk in re.findall(r"```(?:bash|sh|console)?\n(.*?)```", text, re.S):
            cmds += [ln.strip().lstrip("$ ").strip() for ln in blk.splitlines() if ln.strip().lstrip("$ ").startswith("steward ")]
        for ln in cmds:
            ln = re.sub(r"\s*\\$", "", ln.split(" #")[0].split("&&")[0].split("|")[0].split(">")[0]).strip()
            try:
                toks = shlex.split(ln)[1:]
            except ValueError:
                continue
            toks = [t for t in toks if "…" not in t and t != "..." and (t.startswith("-") or not re.fullmatch(
                r"\[.*\]|<.*>|[A-Z][A-Z_-]*", t))]
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    _, unknown = parser.parse_known_args(toks)
                bad = [u for u in unknown if u.startswith("-")]
                if bad:
                    out.append(f"{d}: `{ln}`: no option {' '.join(bad)}")
            except SystemExit:
                msg = (err.getvalue().strip().splitlines() or ["error"])[-1]
                if not re.search(r"required|expected (one|at least one) argument|COMMAND", msg + ln):
                    out.append(f"{d}: `{ln}`: {msg[:120]}")
    return out


def main() -> int:
    found = problems()
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
