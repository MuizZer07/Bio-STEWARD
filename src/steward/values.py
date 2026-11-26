"""Values registry (PaperKit v0.2.1, DESIGN_v0.6 §4.2): every reported number comes from a result file.

``values.toml`` maps a key to a source (JSON pointer, CSV cell, a row count or unique count, or an arithmetic
derivation of other keys). The text refers to keys (LaTeX ``\\val{key}``); a generated file supplies the values.
Assertions (``[[assert]]``) state relations that must hold between values, e.g. split sizes summing to the total.

Everything here is deterministic and offline. No value is ever estimated: a source that cannot be read is an error.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import math
import operator
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import Field, model_validator

from .models import Strict, Text

KEY = r"^[a-z][a-z0-9_]{0,63}$"
REF = re.compile(r"\{([a-z][a-z0-9_]{0,63})\}")


class CsvCell(Strict):
    row: Text  # "column=value" selecting exactly one row
    col: Text


class ValueDef(Strict):
    source: str | None = None
    pointer: str | None = None  # RFC 6901 JSON pointer into a .json or .toml source
    csv: CsvCell | None = None
    count: str | None = None  # "rows" | "unique:<column>"
    derive: str | None = None  # arithmetic over {other_key}s and numbers: + - * / ( )
    format: str = "{}"

    @model_validator(mode="after")
    def _one_kind(self) -> "ValueDef":
        kinds = [self.pointer is not None, self.csv is not None, self.count is not None, self.derive is not None]
        if sum(kinds) != 1:
            raise ValueError("exactly one of pointer, csv, count or derive is required")
        if self.derive is None and not self.source:
            raise ValueError("source is required unless the value is derived")
        if self.derive is not None and self.source:
            raise ValueError("a derived value has no source")
        if self.count is not None and not re.match(r"^(rows|unique:.+)$", self.count):
            raise ValueError("count must be 'rows' or 'unique:<column>'")
        try:
            self.format.format(1.0)
        except (ValueError, IndexError, KeyError) as e:
            raise ValueError(f"invalid format {self.format!r}: {e}") from e
        return self


class Assertion(Strict):
    expr: Text  # e.g. "{n_train} + {n_val} + {n_test} == {n_samples}"
    tol: float = Field(default=0.0, ge=0)


class ValuesFile(Strict):
    schema_: Literal["steward.values/0.1"] = Field(alias="schema")
    values: dict[str, ValueDef] = Field(default_factory=dict)
    assert_: list[Assertion] = Field(default_factory=list, alias="assert")

    @model_validator(mode="after")
    def _keys(self) -> "ValuesFile":
        bad = [k for k in self.values if not re.match(KEY, k)]
        if bad:
            raise ValueError(f"invalid value keys {bad} (lowercase letters, digits, underscores)")
        return self


# ---------------------------------------------------------------- evaluation
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_CMP = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


def _arith(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_arith(node.left, env), _arith(node.right, env))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_arith(node.operand, env)
    raise ValueError("only numbers, {keys}, + - * / and parentheses are allowed")


def _parse(expr: str) -> tuple[ast.AST, list[str]]:
    keys = REF.findall(expr)
    code = REF.sub(lambda m: f"v_{m.group(1)}", expr)
    return ast.parse(code, mode="eval").body, keys


def derive(expr: str, numbers: dict[str, float]) -> float:
    node, keys = _parse(expr)
    return _arith(node, {f"v_{k}": numbers[k] for k in keys})


def check_assertion(a: Assertion, numbers: dict[str, float]) -> bool:
    node, keys = _parse(a.expr)
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP):
        raise ValueError("an assertion is one comparison: ==, !=, <, <=, >, >=")
    env = {f"v_{k}": numbers[k] for k in keys}
    left, right = _arith(node.left, env), _arith(node.comparators[0], env)
    op = _CMP[type(node.ops[0])]
    close = math.isclose(left, right, rel_tol=0.0, abs_tol=a.tol) if a.tol else left == right
    return {"==": close, "!=": not close, "<": left < right, "<=": left <= right or close,
            ">": left > right, ">=": left >= right or close}[op]


def json_pointer(doc: Any, pointer: str) -> Any:
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise KeyError("a JSON pointer starts with '/'")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(doc, list):
            doc = doc[int(part)]
        elif isinstance(doc, dict):
            doc = doc[part]
        else:
            raise KeyError(part)
    return doc


@dataclass
class Computed:
    raw: dict[str, Any] = field(default_factory=dict)  # key -> raw value (number or string)
    text: dict[str, str] = field(default_factory=dict)  # key -> formatted
    errors: dict[str, tuple[str, str]] = field(default_factory=dict)  # key -> (kind, message); missing | unknown | error
    read: dict[str, bytes] = field(default_factory=dict)  # rel path -> bytes (for evidence hashes)


def compute(root: Path, vf: ValuesFile, exact: bool = False, read: dict[str, bytes] | None = None) -> Computed:
    """With `exact`, fractional source numbers are the decimals written (JSON, TOML, CSV cells), for comparisons
    (red-team G1); derived values stay binary floats. Rendering uses the default. `read` shares source bytes with
    the caller, so each file is read once per check (0.6.3, H2)."""
    out = Computed()
    if read is not None:
        out.read = read

    def src_bytes(rel: str) -> bytes | None:
        if rel not in out.read:
            p = root / rel
            if not p.is_file():
                return None
            out.read[rel] = p.read_bytes()
        return out.read[rel]

    def rows(text: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(text)))

    pending = dict(sorted(vf.values.items()))
    for key, d in list(pending.items()):
        if d.derive is not None:
            continue
        data = src_bytes(d.source or "")
        if data is None:
            out.errors[key] = ("missing", f"source {d.source} not found")
            continue
        try:
            text = data.decode("utf-8")
            if d.pointer is not None:
                if exact:
                    from .evidence import _exact_float, loads_exact
                    doc = tomllib.loads(text, parse_float=_exact_float) if (d.source or "").endswith(".toml") else loads_exact(text)
                else:
                    doc = tomllib.loads(text) if (d.source or "").endswith(".toml") else json.loads(text)
                val = json_pointer(doc, d.pointer)
            elif d.csv is not None:
                col_sel, _, want = d.csv.row.partition("=")
                hits = [r for r in rows(text) if r.get(col_sel) == want]
                if len(hits) != 1:
                    raise KeyError(f"row {d.csv.row!r} matched {len(hits)} rows (need exactly 1)")
                if d.csv.col not in hits[0]:
                    raise KeyError(f"column {d.csv.col!r} not found")
                val = _num(hits[0][d.csv.col], exact)
            elif d.count == "rows":
                src = (d.source or "").lower()
                if src.endswith(".csv"):
                    val = len(rows(text))
                elif src.endswith((".tsv", ".tab")):  # AN9: a tab-separated table has a header row too
                    val = max(0, sum(1 for l in text.splitlines() if l.strip()) - 1)
                else:
                    val = sum(1 for l in text.splitlines() if l.strip())
            else:
                col = (d.count or "")[len("unique:"):]
                table = rows(text)
                if table and col not in table[0]:
                    raise KeyError(f"column {col!r} not found")
                val = len({r[col] for r in table})
            if isinstance(val, (dict, list)) or val is None:
                raise ValueError("the pointer selects a structure or null, not a value")
            if val in ("TBD", "unknown"):  # a sentinel in the source (e.g. a contract field not decided yet)
                out.errors[key] = ("missing" if val == "TBD" else "unknown", f"source value is {val!r}")
                continue
            out.raw[key] = val
        except (KeyError, IndexError, ValueError, json.JSONDecodeError, ValueError, RecursionError, UnicodeDecodeError) as e:
            out.errors[key] = ("error", f"{type(e).__name__}: {e}")
    # derived values, resolved in dependency order (cycles and missing inputs are errors)
    remaining = {k: d for k, d in pending.items() if d.derive is not None}
    while remaining:
        progressed = False
        for key, d in sorted(remaining.items()):
            deps = REF.findall(d.derive or "")
            if any(k in out.errors or k not in vf.values for k in deps):
                bad = [k for k in deps if k in out.errors or k not in vf.values]
                kinds = {out.errors[k][0] if k in out.errors else "error" for k in bad}
                kind = "error" if "error" in kinds else ("missing" if "missing" in kinds else "unknown")
                out.errors[key] = (kind, f"derive depends on unavailable keys {bad}")
            elif all(k in out.raw for k in deps):
                try:
                    out.raw[key] = derive(d.derive or "", {k: float(out.raw[k]) for k in deps})
                except (ValueError, TypeError, ZeroDivisionError, SyntaxError) as e:
                    out.errors[key] = ("error", f"{type(e).__name__}: {e}")
            else:
                continue
            del remaining[key]
            progressed = True
            break
        if not progressed:
            for key in remaining:
                out.errors[key] = ("error", "derive has a dependency cycle")
            break
    for key, val in out.raw.items():
        try:
            out.text[key] = vf.values[key].format.format(val)
        except (ValueError, TypeError) as e:
            out.errors[key] = ("error", f"format {vf.values[key].format!r} cannot render {val!r}: {e}")
    for key in out.errors:
        out.text.pop(key, None)
    return out


def _num(s: str, exact: bool = False) -> Any:
    try:
        return int(s)
    except ValueError:
        try:
            if exact:
                from decimal import Decimal, InvalidOperation
                try:
                    d = Decimal(s.strip())
                    return d if d.is_finite() else float(s)
                except InvalidOperation:
                    raise ValueError(s) from None
            return float(s)
        except ValueError:
            return s


# ---------------------------------------------------------------- emitters
def emit(text: dict[str, str], fmt: str) -> str:
    keys = sorted(text)
    if fmt == "tex":
        head = ["% Generated by `steward paper values --write`. Do not edit; regenerate after results change.",
                "% Use \\val{key} in the text. An unknown key stops the build with an error.",
                "\\makeatletter",
                "\\providecommand{\\val}[1]{\\@ifundefined{stewardval@#1}"
                "{\\PackageError{steward}{Unknown value key #1}{Add it to values.toml}}{\\@nameuse{stewardval@#1}}}"]
        body = [f"\\@namedef{{stewardval@{k}}}{{{_tex_escape(text[k])}}}" for k in keys]
        return "\n".join(head + body + ["\\makeatother", ""])
    if fmt == "json":
        return json.dumps({k: text[k] for k in keys}, indent=2, ensure_ascii=False) + "\n"
    if fmt == "quarto":
        lines = ["# Generated by `steward paper values --write` (Quarto _variables.yml). Do not edit."]
        lines += [f"{k}: {json.dumps(text[k], ensure_ascii=False)}" for k in keys]
        return "\n".join(lines) + "\n"
    raise ValueError(fmt)


def _tex_escape(s: str) -> str:
    return re.sub(r"([%&#_$])", r"\\\1", s)


def emit_format_for(path: str) -> str:
    if path.endswith(".tex"):
        return "tex"
    if path.endswith((".yml", ".yaml")):
        return "quarto"
    return "json"


VAL_REF = re.compile(r"\\val\{([^}]*)\}")
QUARTO_REF = re.compile(r"\{\{<\s*var\s+([^\s>]+)\s*>\}\}")
