"""PresentationKit (C17, RELEASE_v0.3_SPEC): talk plans, taxonomy, patterns and layered style preferences.

Preferences are style only: the schema has no field for talk content or personal data, and unknown keys are rejected.
Precedence: talk [overrides] → project presentation/profile.toml → context profile → global. Only an explicit
`steward talk prefs set` writes a preference file.
"""

from __future__ import annotations

import math
import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .models import Sentinel, Strict, Text
from .resources import template

CLAIM_STATUSES = ("proposed", "implemented", "preliminary", "validated", "published", "unknown")
Hex = str


# ---------------------------------------------------------------- preferences (style only)
class PStyle(Strict):
    theme: str | None = None
    density: Literal["sparse", "balanced", "dense"] | None = None
    aspect: Literal["16:9", "4:3"] | None = None


class PTypography(Strict):
    family: str | None = None
    min_font_pt: float | None = Field(default=None, gt=0)


class PPalette(Strict):
    text: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    background: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class PStory(Strict):
    depth: Literal["overview", "standard", "deep"] | None = None
    takeaways: int | None = Field(default=None, ge=1)


class PFigures(Strict):
    max_panels: int | None = Field(default=None, ge=1)
    prefer: Literal["plots", "tables"] | None = None


class PMotion(Strict):
    transitions: Literal["none", "minimal", "rich"] | None = None


class PNotes(Strict):
    mode: Literal["none", "bullets", "script"] | None = None


class PLanguage(Strict):
    tone: Literal["formal", "conversational"] | None = None
    spelling: Literal["en-GB", "en-US"] | None = None
    avoid: list[str] | None = None


class PAccessibility(Strict):
    min_contrast: float | None = Field(default=None, ge=1, le=21)
    alt_text: bool | None = None


class Prefs(Strict):
    style: PStyle = Field(default_factory=PStyle)
    typography: PTypography = Field(default_factory=PTypography)
    palette: PPalette = Field(default_factory=PPalette)
    story: PStory = Field(default_factory=PStory)
    figures: PFigures = Field(default_factory=PFigures)
    motion: PMotion = Field(default_factory=PMotion)
    notes: PNotes = Field(default_factory=PNotes)
    language: PLanguage = Field(default_factory=PLanguage)
    accessibility: PAccessibility = Field(default_factory=PAccessibility)


DEFAULTS: dict[str, Any] = {
    "style.density": "balanced", "style.aspect": "16:9", "typography.min_font_pt": 14.0,
    "palette.text": "#1a1a1a", "palette.background": "#ffffff", "accessibility.min_contrast": 4.5,
    "accessibility.alt_text": True, "notes.mode": "bullets", "motion.transitions": "minimal",
}
TALK_ONLY = {"allow_feedback_slides"}  # override-only switches that are not preferences


def flatten(p: Prefs) -> dict[str, Any]:
    out = {}
    for section, model in p:
        for key, value in model:
            if value is not None:
                out[f"{section}.{key}"] = value
    return out


def config_home() -> Path:
    if os.environ.get("STEWARD_CONFIG_HOME"):
        return Path(os.environ["STEWARD_CONFIG_HOME"])
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "steward"


def _load_prefs(path: Path) -> Prefs:
    if not path.is_file():
        return Prefs()
    return Prefs.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


def resolve(root: Path, overrides: dict[str, Any] | None, context: str | None) -> dict[str, tuple[Any, str]]:
    """Resolved preferences: key -> (value, layer). Raises pydantic ValidationError on an invalid layer."""
    home = config_home()
    ov = {k: v for k, v in (overrides or {}).items() if k not in TALK_ONLY}
    layers = [
        ("talk", flatten(Prefs.model_validate(ov))),
        ("project", flatten(_load_prefs(root / "presentation" / "profile.toml"))),
        (f"context:{context}", flatten(_load_prefs(home / "contexts" / f"{context}.toml")) if context else {}),
        ("global", flatten(_load_prefs(home / "presentation.toml"))),
        ("default", DEFAULTS),
    ]
    out: dict[str, tuple[Any, str]] = {}
    for layer, values in layers:
        for k, v in values.items():
            out.setdefault(k, (v, layer))
    return dict(sorted(out.items()))


def layer_path(root: Path, layer: str) -> Path:
    if layer == "global":
        return config_home() / "presentation.toml"
    if layer == "project":
        return root / "presentation" / "profile.toml"
    if layer.startswith("context:") and re.match(r"^[a-z][a-z0-9_-]{0,31}$", layer[8:]):
        return config_home() / "contexts" / f"{layer[8:]}.toml"
    raise ValueError("layer must be global, project or context:NAME")


def set_pref(path: Path, key: str, raw: str) -> None:
    """Set one style key in a preference file, validating the result before writing."""
    section, _, name = key.partition(".")
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    value: Any = raw
    for conv in (int, float):
        try:
            value = conv(raw)
            break
        except ValueError:
            pass
    if raw in ("true", "false"):
        value = raw == "true"
    data.setdefault(section, {})[name] = value
    Prefs.model_validate(data)  # refuse anything outside the style schema
    lines = ["# steward presentation preferences (style only). Edit freely; `steward talk prefs` shows the result."]
    for sec in sorted(data):
        lines.append(f"\n[{sec}]")
        for k in sorted(data[sec]):
            v = data[sec][k]
            lines.append(f"{k} = {_toml_value(v)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(v: Any) -> str:
    import json

    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def contrast(fg: str, bg: str) -> float:
    """WCAG 2 contrast ratio between two #rrggbb colours."""
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def auto_max_slides(duration_min: float, density: str) -> int:
    return math.ceil(duration_min * {"sparse": 0.7, "balanced": 1.0, "dense": 1.5}[density])


# ---------------------------------------------------------------- plan
class Outline(Strict):
    role: Text
    title: Text


class Claim(Strict):
    id: Text
    text: Text
    status: Literal["proposed", "implemented", "preliminary", "validated", "published", "unknown"]
    evidence: list[str] = Field(default_factory=list)
    where: str | None = None


class TalkPlan(Strict):
    schema_: Literal["steward.talk/0.1"] = Field(alias="schema")
    stage: Union[Text, Sentinel]
    stage_source: Literal["confirmed", "proposed"]
    purpose: Union[Text, Sentinel]
    feedback: Union[Literal["open", "targeted", "informational", "defense"], Sentinel]
    audience: Union[Literal["specialist", "technical", "interdisciplinary", "public"], Sentinel]
    duration_min: Union[Annotated[float, Field(gt=0)], Sentinel]
    format: Literal["talk", "poster", "lightning", "demo"] = "talk"
    max_slides: Union[int, Literal["auto"]] = "auto"
    context_profile: str | None = None
    evidence: list[str] = Field(default_factory=list)
    required_sections: list[str] = Field(default_factory=list)
    unresolved_decisions: list[Text] = Field(default_factory=list)
    pattern: str | None = None
    outline: list[Outline] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)


def taxonomy() -> dict[str, Any]:
    return tomllib.loads(template("talk/taxonomy.toml"))


def patterns() -> dict[str, Any]:
    return tomllib.loads(template("talk/patterns.toml"))


def ceiling(stage: str) -> str | None:
    st = taxonomy()["stages"].get(stage)
    return st["ceiling"] if st else None


def rank(status: str) -> int:
    order = taxonomy()["claim_order"]
    return order.index(status) if status in order else -1


def select_pattern(stage: str, purpose: str, feedback: str, explicit: str | None = None) -> tuple[str, list[str]]:
    data = patterns()
    name = explicit
    if name is None:
        for rule in data["select"]:
            if ("stage" not in rule or stage in rule["stage"]) and ("purpose" not in rule or purpose in rule["purpose"]):
                name = rule["pattern"]
                break
    name = name or "progress"
    roles = list(data["patterns"][name]["roles"])
    extra = [r for r in data["feedback_roles"].get(feedback, []) if r not in roles]
    if extra:
        roles = roles[:-1] + extra + roles[-1:] if roles else extra
    if rank(ceiling(stage) or "") >= rank("preliminary") and stage in ("evaluation", "completed", "published") \
            and "limitations" not in roles:
        roles.insert(max(len(roles) - 1, 0), "limitations")
    return name, roles


def unusual(stage: str, purpose: str) -> bool:
    return any(u["stage"] == stage and u["purpose"] == purpose for u in taxonomy().get("unusual", []))
