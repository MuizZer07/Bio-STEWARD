"""Build the curated Claude Code plugin payload (0.17.0, review Y7): `plugin/` holds only the skills and the plugin
manifest, so installing the plugin copies no internal record of this repository.

    python tools/build_plugin.py           # write plugin/
    python tools/build_plugin.py --check   # exit 1 when plugin/ differs from skills/ and the manifest (tests run this)
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "plugin"


def manifest() -> str:
    from steward import __version__

    return json.dumps({
        "name": "bio-steward",
        "description": "Deterministic guardrails for agent-driven research in computational biology: run and read "
                       "steward checks, plan benchmarks, keep paper numbers true to their results, freeze, seal and "
                       "approve, release, and audit progress. The steward command must be installed.",
        "version": __version__.split(".dev")[0],
        "license": "MIT",
        "keywords": ["computational-biology", "reproducibility", "benchmarking", "research-integrity", "agents"],
    }, indent=2) + "\n"


def wanted() -> dict[str, bytes]:
    files = {".claude-plugin/plugin.json": manifest().encode()}
    for p in sorted((ROOT / "skills").rglob("*")):
        if p.is_symlink():  # AA9 (0.17.0): nothing from outside skills/ reaches the payload
            raise SystemExit(f"skills/{p.relative_to(ROOT / 'skills').as_posix()} is a link; refused")
        if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store":
            files[f"skills/{p.relative_to(ROOT / 'skills').as_posix()}"] = p.read_bytes()
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    return files


def current() -> dict[str, bytes]:
    if not OUT.is_dir():
        return {}
    out = {}
    for p in sorted(OUT.rglob("*")):
        if p.is_symlink():  # AA9: a linked payload entry is never current, whatever its bytes
            return {"(link)": b""}
        if p.is_file():
            out[p.relative_to(OUT).as_posix()] = p.read_bytes()
    return out


def main(check: bool) -> int:
    want = wanted()
    if check:
        if current() != want:
            print("plugin/ is out of date; run python tools/build_plugin.py")
            return 1
        return 0
    if OUT.is_symlink():
        print("plugin/ is a link; refused", file=sys.stderr)
        return 2
    if OUT.exists():
        shutil.rmtree(OUT)
    for rel, data in want.items():
        p = OUT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
