"""Regenerate the JSON Schemas in schemas/ from the pydantic models.

    python tools/regenerate_schemas.py           # write
    python tools/regenerate_schemas.py --check   # exit 1 if a committed schema is out of date (run by the tests)

Output depends on the pydantic version; the dev extra pins it so CI and contributors produce identical bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from steward.fsutil import canonical_json
from steward.models import Contract, PaperSpec, PriorWork, StewardConfig, Venue
from steward.report import Report
from steward.values import ValuesFile
from steward.displays import DisplaysFile
from steward.talk import Prefs, TalkPlan
from steward.integrity import DatasetsFile
from steward.evidence import ClaimsFile
from steward.review import FindingsFile
from steward.storage import ArtifactsFile
from steward.milestones import MilestonesFile
from steward.sprint import SprintFile

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "steward.toml-0.2.schema.json": StewardConfig,  # accepts 0.1 and 0.2 configs
    "steward.contract-0.1.schema.json": Contract,
    "steward.artifacts-0.1.schema.json": ArtifactsFile,
    "steward.prior_work-0.1.schema.json": PriorWork,
    "steward.report-0.1.schema.json": Report,
    "steward.paper_spec-0.1.schema.json": PaperSpec,
    "steward.venue-0.1.schema.json": Venue,
    "steward.values-0.1.schema.json": ValuesFile,
    "steward.displays-0.1.schema.json": DisplaysFile,
    "steward.talk-0.1.schema.json": TalkPlan,
    "steward.presentation_prefs-0.1.schema.json": Prefs,
    "steward.datasets-0.1.schema.json": DatasetsFile,
    "steward.claims-0.1.schema.json": ClaimsFile,
    "steward.findings-0.1.schema.json": FindingsFile,
    "steward.milestones-0.1.schema.json": MilestonesFile,
    "steward.sprint-0.1.schema.json": SprintFile,
}
# 0.21.0 (W01): the tagged `--format json` documents and the interface, kept in their own registry.
from steward.interface_schemas import SCHEMAS as INTERFACE_SCHEMAS  # noqa: E402

SCHEMAS.update(INTERFACE_SCHEMAS)


def render(model) -> str:
    schema = model.model_json_schema(by_alias=True, mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return canonical_json(schema)


SKILL = ROOT / "skills" / "using-steward" / "SKILL.md"
BEGIN, END = "<!-- rules:begin -->", "<!-- rules:end -->"


def rule_catalogue() -> str:
    """The using-steward rule list, from the rule catalogue (red-team AR-18: the skill must never describe an older
    toolkit)."""
    from steward.rules import AREAS, RULES

    lines = []
    for area, ids in AREAS.items():
        own = [i for i in ids if i in RULES and not any(i in AREAS[a] for a in list(AREAS)[:list(AREAS).index(area)])]
        if own:
            lines.append(f"- **{area}:** " + " · ".join(f"{i} `{RULES[i][0]}`" for i in own))
    return "\n".join(lines)


def skill_text() -> str:
    text = SKILL.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + BEGIN + "\n" + rule_catalogue() + "\n" + END + tail


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    stale = []
    want = skill_text()
    if check and SKILL.read_text(encoding="utf-8") != want:
        stale.append("../skills/using-steward/SKILL.md (rule catalogue)")
    elif not check:
        SKILL.write_text(want, encoding="utf-8", newline="\n")
    for name, model in SCHEMAS.items():
        path = ROOT / "schemas" / name
        text = render(model)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    for name in stale:
        print(f"schemas/{name} is out of date; run python tools/regenerate_schemas.py")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
