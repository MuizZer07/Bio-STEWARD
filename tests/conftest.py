"""Shared fixtures. Every fixture is synthetic: a copy of the toy example (stage 1) with one small mutation per test."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from steward.cli import main

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "toy-expression-benchmark"
CONTRACT = "benchmarks/expr-clf.contract.toml"
PRIOR = "development/prior_work/expr-clf.prior.toml"


@pytest.fixture
def example(tmp_path: Path) -> Path:
    dest = tmp_path / "toy"
    # Copy as a clean clone would have it: no local state, no git-ignored LaTeX by-products (red-team A5 / C2).
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns(
        ".steward", "__pycache__", ".DS_Store", "*.aux", "*.bbl", "*.blg", "*.fdb_latexmk", "*.fls", "*.out", "*.nav",
        "*.snm", "*.toc"))
    return dest


def edit(root: Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, f"fixture mutation target not found in {rel}: {old!r}"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def append(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(text)


class Cli:
    def __init__(self, capsys: pytest.CaptureFixture[str]):
        self.capsys = capsys

    def __call__(self, *argv: str | Path) -> tuple[int, str, str]:
        self.capsys.readouterr()
        code = main([str(a) for a in argv])
        out = self.capsys.readouterr()
        return code, out.out, out.err

    def check(self, root: Path, *areas: str, gate: str | None = None) -> tuple[int, dict]:
        args = ["check", "--repo", root, "--format", "json", *areas]
        if gate:
            args += ["--gate", gate]
        code, out, err = self(*args)
        assert out, f"no report on stdout (exit {code}): {err}"
        return code, json.loads(out)


@pytest.fixture
def cli(capsys: pytest.CaptureFixture[str]) -> Cli:
    return Cli(capsys)


def results(report: dict, rule: str) -> list[dict]:
    return [r for r in report["verdict"]["results"] if r["rule"] == rule]


def one(report: dict, rule: str) -> dict:
    rs = results(report, rule)
    assert len(rs) == 1, rs
    return rs[0]


def codes(result: dict) -> set[str]:
    return {d.get("code") for d in result["details"]}


def gate(report: dict, name: str = "default") -> dict:
    return next(g for g in report["verdict"]["gates"] if g["name"] == name)


@pytest.fixture(autouse=True)
def _mcp_read_only_reset():
    """The MCP server switches off signature verification for its own process; tests that build one in-process
    must not leak that into other tests."""
    yield
    from steward import authorize
    authorize.READ_ONLY = False


@pytest.fixture(autouse=True)
def _no_machine_registry(monkeypatch):
    """0.13.0: tests never write the machine's project registry (the registry tests turn it on in a temporary home)."""
    monkeypatch.setenv("STEWARD_NO_REGISTRY", "1")
