"""Write docs/capabilities.md: the agents Bio-STEWARD works with, its Agent Skills by kit, its commands by what you do
and its rule areas, all read from the toolkit itself so the page cannot drift (tests check it is current).

    python tools/build_capabilities.py           # write
    python tools/build_capabilities.py --check   # exit 1 when the page is out of date
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

AGENTS = [
    ("Claude Code", "the plugin (`plugin/`) or `steward init --skills .claude/skills`; `CLAUDE.md` points to `AGENTS.md`",
     "`steward task brief --for claude`"),
    ("Codex", "`steward init --skills .agents/skills`; reads `AGENTS.md`",
     "`steward task brief --for codex` (a self-contained prompt for `codex exec`)"),
    ("Gemini (CLI, Antigravity)", "`steward init --skills .agents/skills`; reads `AGENTS.md`",
     "`steward task brief --for gemini`"),
    ("Any agent that reads `AGENTS.md`", "`steward init` writes the steward block into `AGENTS.md`",
     "`steward task brief --for generic`"),
    ("CI", "the [GitHub Action](../action.yml) and [pre-commit hooks](../.pre-commit-hooks.yaml)", "—"),
    ("MCP clients", "`steward mcp`: a read-only server over the checks and records", "—"),
]


def skills() -> dict[str, str]:
    out = {}
    for f in sorted((ROOT / "skills").glob("*/SKILL.md")):
        head = f.read_text(encoding="utf-8").split("---", 2)[1]
        name = re.search(r"^name:\s*(.+)$", head, re.M).group(1).strip()
        desc = re.search(r"^description:\s*(.+)$", head, re.M).group(1).strip()
        out[name] = desc
    return out


def page() -> str:
    from steward.cli import HELP_GROUPS
    from steward.rules import AREAS, RULES

    kits = tomllib.loads((ROOT / "skills/BUNDLES.toml").read_text(encoding="utf-8"))
    sk = skills()
    lines = ["# What Bio-STEWARD offers", "",
             "Generated from the toolkit itself (`python tools/build_capabilities.py`); the counts are the installed ones.",
             "", "## Agents it works with", "", "| Agent | How it learns the checks | How it gets a task |",
             "|---|---|---|"]
    lines += [f"| {a} | {how} | {task} |" for a, how, task in AGENTS]
    lines += ["", f"## Agent Skills ({len(sk)}, in {len(kits)} kits)", "",
              "Install only the kits you use: `steward init --skills DIR --kits core,paper`. Each kit has a word budget, "
              "because agents preload every installed skill's description.", ""]
    for kit, body in kits.items():
        lines += [f"### {kit} ({len(body['skills'])})", "", "| Skill | Use it when |", "|---|---|"]
        lines += [f"| `{s}` | {sk[s]} |" for s in body["skills"]]
        lines.append("")
    groups = [ln for ln in HELP_GROUPS.splitlines()[1:] if ln.strip() and not ln.startswith("New here")]
    lines += ["## Commands by what you do", "", "| Group | Commands |", "|---|---|"]
    for g in groups:
        name, cmds = g[:19].strip(), g[19:].strip()
        lines.append(f"| {name} | {' · '.join(f'`{c.strip()}`' for c in cmds.split('·'))} |")
    lines += ["", "Every command: `steward COMMAND --help`; the full list: [the command reference](reference/commands.md).",
              "", f"## Rules ({len(RULES)}, by area)", "", "| Area | Rules |", "|---|---|"]
    for area, ids in AREAS.items():
        lines.append(f"| {area} | {' · '.join(f'{r} `{RULES[r][0]}`' for r in ids)} |")
    advisory = __import__("steward.models", fromlist=["ADVISORY"]).ADVISORY
    lines += ["", f"Advisory (reported, not in the default gate): {', '.join(advisory)}. What each rule checks: "
              "`steward explain R-xx`, or [the rule reference](reference/rules.md).", ""]
    return "\n".join(lines)


def main() -> int:
    out = ROOT / "docs/capabilities.md"
    text = page()
    if "--check" in sys.argv:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current != text:
            print("docs/capabilities.md is out of date: python tools/build_capabilities.py", file=sys.stderr)
            return 1
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
