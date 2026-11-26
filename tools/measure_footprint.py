"""Measure the toolkit's agent-facing footprint in words and bytes (DESIGN_v0.5 §3.1, TE-1/TE-2).

    python tools/measure_footprint.py            # print measurements as JSON
    python tools/measure_footprint.py --check    # exit 1 if a budget (F2, regression limits) is exceeded

Tokens are not reported: tokenizers differ by provider, and an estimate would be invented (DESIGN_v0.5 §6).
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Regression limits adopted 2026-11-23 (F2). Raising one is a recorded decision, not a convenience.
BUDGETS = {
    "agents_block_words": 120,
    "skill_description_words": 35,  # 2026-11-23 growth guard (was 60)
    # Per-bundle description totals live in skills/BUNDLES.toml (H2, 2026-11-23; replaces G2's single 450 total).
    "skill_body_words": 900,
    "skill_body_lines": 200,
}


def _wb(text: str) -> dict[str, int]:
    return {"words": len(text.split()), "bytes": len(text.encode("utf-8")), "lines": len(text.splitlines())}


def description(skill_md: str) -> str:
    front = skill_md.split("---")[1]
    m = re.search(r"^description:\s*(.+)$", front, re.M)
    return m.group(1).strip() if m else ""


def measure(root: Path = ROOT) -> dict:
    skills = {}
    for d in sorted(p for p in (root / "skills").iterdir() if (p / "SKILL.md").is_file()):
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        skills[d.name] = {"description": _wb(description(text)), "body": _wb(text)}
    bundles = tomllib.loads((root / "skills" / "BUNDLES.toml").read_text(encoding="utf-8"))
    return {
        "always_loaded": {
            "agents_block": _wb((root / "templates" / "agents_block.md").read_text(encoding="utf-8")),
            "bundles": {
                name: {"budget_words": b["budget_words"], "decision": b.get("decision"), "skills": b["skills"],
                       "description_words": sum(skills[n]["description"]["words"] for n in b["skills"] if n in skills)}
                for name, b in bundles.items()
            },
        },
        "skills": skills,
    }


def violations(m: dict) -> list[str]:
    out = []
    if m["always_loaded"]["agents_block"]["words"] > BUDGETS["agents_block_words"]:
        out.append(f"AGENTS block {m['always_loaded']['agents_block']['words']} words > {BUDGETS['agents_block_words']}")
    listed: list[str] = []
    for name, b in m["always_loaded"]["bundles"].items():
        listed += b["skills"]
        if b["description_words"] > b["budget_words"]:
            out.append(f"bundle {name}: descriptions {b['description_words']} words > {b['budget_words']}")
        out += [f"bundle {name}: unknown skill {s}" for s in b["skills"] if s not in m["skills"]]
    out += [f"skill {s} is in no bundle" for s in m["skills"] if s not in listed]
    decisions = (ROOT / "development" / "DECISIONS.md")
    text = decisions.read_text(encoding="utf-8") if decisions.is_file() else ""
    for name, b in m["always_loaded"]["bundles"].items():
        if not b.get("decision"):
            out.append(f"bundle {name}: budget has no decision reference")
        elif text and b["decision"] not in text:
            out.append(f"bundle {name}: decision {b['decision']!r} not found in development/DECISIONS.md")
    out += [f"skill {s} is in more than one bundle" for s in sorted(set(listed)) if listed.count(s) > 1]
    for name, s in m["skills"].items():
        if s["description"]["words"] > BUDGETS["skill_description_words"]:
            out.append(f"{name}: description {s['description']['words']} words > {BUDGETS['skill_description_words']}")
        if s["body"]["words"] > BUDGETS["skill_body_words"]:
            out.append(f"{name}: body {s['body']['words']} words > {BUDGETS['skill_body_words']}")
        if s["body"]["lines"] > BUDGETS["skill_body_lines"]:
            out.append(f"{name}: body {s['body']['lines']} lines > {BUDGETS['skill_body_lines']}")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    m = measure()
    if "--check" in argv:
        for name, b in m["always_loaded"]["bundles"].items():
            if b["budget_words"] and b["description_words"] >= 0.9 * b["budget_words"]:
                print(f"warning: bundle {name} at {b['description_words']}/{b['budget_words']} words (>= 90%): "
                      "trim or merge before adding a skill")
        bad = violations(m)
        for b in bad:
            print(b)
        return 1 if bad else 0
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
