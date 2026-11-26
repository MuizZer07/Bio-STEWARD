"""Locate bundled skills and templates: inside an installed wheel, or in the source tree for editable installs."""

from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).resolve().parent


def _base(kind: str) -> Path:
    bundled = _PKG / "_bundled" / kind
    if bundled.is_dir():
        return bundled
    source = _PKG.parents[1] / kind  # <repo>/src/steward -> <repo>/<kind>
    if source.is_dir():
        return source
    raise FileNotFoundError(f"bundled {kind}/ not found; the installation is incomplete")


def template(name: str) -> str:
    return (_base("templates") / name).read_text(encoding="utf-8")


def skills_dir() -> Path:
    return _base("skills")


CONSTITUTION_VERSION = "2"


def constitution_text() -> str:
    """The constitution shipped with this toolkit (bundled in the wheel; the repository root in a source tree)."""
    for p in (_PKG / "_bundled" / "CONSTITUTION.md", _PKG.parents[1] / "CONSTITUTION.md"):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("CONSTITUTION.md not found; the installation is incomplete")
