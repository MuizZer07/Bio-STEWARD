"""Runtime fingerprint (0.6.2, RELEASE_v0.6_SPEC §3, rule R-44): an AST fingerprint per module.

Comments, whitespace and docstrings do not change a fingerprint; code does. `steward release fingerprint --record`
writes the baseline; a changed module fails R-44 unless `steward release ack MODULE --reason TEXT` recorded the new
fingerprint as a neutral change (an append-only ledger entry). An acknowledgement is a recorded decision, not proof
that the change is neutral.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from .fsutil import matching_files


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def module_fingerprint(path: Path) -> str:
    tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def fingerprints(root: Path, patterns: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """(module -> fingerprint, module -> parse error)."""
    out, errors = {}, {}
    for rel in matching_files(root, patterns):
        if not rel.endswith(".py"):
            continue
        try:
            out[rel] = module_fingerprint(root / rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            errors[rel] = f"{type(e).__name__}: {e}"
    return out, errors


def record(root: Path, patterns: list[str], path: Path) -> dict[str, str]:
    fp, errors = fingerprints(root, patterns)
    if errors:
        raise ValueError(f"cannot fingerprint: {errors}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "steward.fingerprint/0.1", "modules": fp}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return fp
