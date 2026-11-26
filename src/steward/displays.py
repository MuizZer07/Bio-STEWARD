"""Display manifest (PaperKit v0.2.2): every figure and table is built by a declared script from declared inputs.

``displays.toml`` (in the paper directory) declares each display: kind, output, script, inputs, parameters and the
LaTeX label the text cites. ``steward paper displays NAME --record`` writes ``displays.lock`` with the SHA-256 of the
script, inputs and output after a build; R-11 then detects a display whose script or inputs changed since its
output was recorded (stale), as well as missing files, uncited displays and figures with no provenance.

A lock records what the author declared at build time; it cannot prove the script produced the output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import Field, model_validator

from .models import Strict, Text

Scalar = Union[int, float, str, bool]


class Display(Strict):
    kind: Literal["figure", "table"]
    output: Text  # repository-relative path of the built file (pdf, png, tex, …)
    script: Text  # repository-relative path of the script that builds it
    inputs: list[Text] = Field(default_factory=list)  # repository-relative data/result files
    params: dict[str, Scalar] = Field(default_factory=dict)
    label: Text  # LaTeX label the text cites, e.g. "fig:splits"


class DisplaysFile(Strict):
    schema_: Literal["steward.displays/0.1"] = Field(alias="schema")
    displays: dict[str, Display] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique(self) -> "DisplaysFile":
        labels = [d.label for d in self.displays.values()]
        outs = [d.output for d in self.displays.values()]
        dup = sorted({x for x in labels if labels.count(x) > 1} | {x for x in outs if outs.count(x) > 1})
        if dup:
            raise ValueError(f"duplicate labels or outputs: {dup}")
        return self


def _sha(root: Path, rel: str) -> str | None:
    p = root / rel
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def fingerprint(root: Path, d: Display) -> dict[str, Any]:
    return {
        "script": {d.script: _sha(root, d.script)},
        "inputs": {i: _sha(root, i) for i in sorted(d.inputs)},
        "params": dict(sorted(d.params.items())),
        "output": {d.output: _sha(root, d.output)},
    }


def lock_text(root: Path, df: DisplaysFile) -> str:
    entries = {name: fingerprint(root, d) for name, d in sorted(df.displays.items())}
    return json.dumps({"schema": "steward.displays_lock/0.1", "displays": entries}, indent=2, sort_keys=True) + "\n"


def missing_files(root: Path, d: Display) -> list[str]:
    return [p for p in [d.script, *d.inputs, d.output] if not (root / p).is_file()]


def stale_parts(recorded: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Which parts differ between the lock and now: script, inputs, params, output."""
    return [part for part in ("script", "inputs", "params", "output") if recorded.get(part) != current.get(part)]
