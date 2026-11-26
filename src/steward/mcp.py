"""Optional MCP server (v0.8, RELEASE_v0.8_SPEC §3): `steward mcp`, stdio, read-mostly.

Standard library only: the JSON-RPC 2.0 subset of the Model Context Protocol that a tool server needs (initialize,
notifications/initialized, ping, tools/list, tools/call), newline-delimited over stdin / stdout.

Each tool runs the CLI's own read-only command in-process and returns its output, so the result is the CLI's
result. Nothing here signs or verifies signatures, approves, freezes, seals, unseals, waives, spends, runs a command,
writes a file or uses the network. Git runs through `fsutil.git_run`: no index writes, no repository-selected
programs, no transport (red-team K1, K3). Those stay on the CLI, where the human's key and confirmation are required.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

PROTOCOL = "2025-06-18"
RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
TOL = re.compile(r"^(?!-)[^\n]*=(abs|rel):[0-9eE.+-]+$")  # the pointer may contain "=" (as the CLI)
MAX_FRAME = 1 << 20  # bytes per request line (red-team K6)
DEFAULT_TOL = re.compile(r"^(abs|rel):[0-9eE.+-]+$")


class ToolError(Exception):
    pass


def _str_list(v: Any, name: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ToolError(f"{name} must be a list of strings")
    return v


def _repo_path(root: Path, v: Any, name: str) -> str:
    from .fsutil import escapes_root, inside

    if not isinstance(v, str) or not v or v.startswith("-"):
        raise ToolError(f"{name} must be a repository-relative path")
    if escapes_root(v) or not inside(root, v):
        raise ToolError(f"{name} resolves outside the repository")
    return v


def _cli(argv: list[str]) -> tuple[int, str, str]:
    from .cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:  # argparse usage errors
            code = int(e.code) if isinstance(e.code, int) else 64
    return code, out.getvalue(), err.getvalue()


class Server:
    def __init__(self, root: Path):
        from . import authorize

        authorize.READ_ONLY = True  # signature checks report UNKNOWN here, never verified (red-team L2)
        self.root = root.resolve()
        r = str(self.root)
        from .rules import AREAS

        def check(a: dict[str, Any]) -> list[str]:
            areas = _str_list(a.get("areas"), "areas")
            bad = [x for x in areas if x not in AREAS]
            if bad:
                raise ToolError(f"unknown area(s) {bad}")
            argv = ["check", "--repo", r, "--format", "json", *areas]
            if a.get("final"):
                argv.append("--final")
            if a.get("gate") is not None:
                if not isinstance(a["gate"], str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", a["gate"]):
                    raise ToolError("gate must be a gate name")
                argv += ["--gate", a["gate"]]
            return argv

        def diff_run(a: dict[str, Any]) -> list[str]:
            ids = [a.get("a"), a.get("b")]
            if not all(isinstance(x, str) and RUN_ID.fullmatch(x) for x in ids):
                raise ToolError("a and b must be run IDs")
            argv = ["diff", "run", "--repo", r, ids[0], ids[1], "--json"]
            for t in _str_list(a.get("tol"), "tol"):
                if not TOL.fullmatch(t):
                    raise ToolError(f"tol {t!r} must be POINTER=abs:X or POINTER=rel:X")
                argv += ["--tol", t]
            if a.get("default_tol") is not None:
                if not isinstance(a["default_tol"], str) or not DEFAULT_TOL.fullmatch(a["default_tol"]):
                    raise ToolError("default_tol must be abs:X or rel:X")
                argv += ["--default-tol", a["default_tol"]]
            return argv

        def contract(cmd: str) -> Callable[[dict[str, Any]], list[str]]:
            return lambda a: ["benchmark", cmd, "--repo", r, _repo_path(self.root, a.get("contract"), "contract"), "--json"]

        obj = {"type": "object", "additionalProperties": False}
        string = {"type": "string"}
        strings = {"type": "array", "items": string}
        # name -> (description, input schema, argv builder)
        self.tools: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], list[str]]]] = {
            "check": ("Evaluate the declared rules (read-only); the same JSON report as `steward check --format json`.",
                      {**obj, "properties": {"areas": strings, "final": {"type": "boolean"}, "gate": string}}, check),
            "report_rule": ("The results of one rule from a fresh check (optionally one subject).",
                            {**obj, "properties": {"rule": string, "subject": string}, "required": ["rule"]}, check),
            "diff_run": ("Compare two run records (repeatability within declared tolerances); `steward diff run --json`.",
                         {**obj, "properties": {"a": string, "b": string, "tol": strings, "default_tol": string},
                          "required": ["a", "b"]}, diff_run),
            "diff_impact": ("Which results, paper values and figures a change made stale; `steward diff impact --json`.",
                            obj, lambda a: ["diff", "impact", "--repo", r, "--json"]),
            "benchmark_splits": ("Split counts, ID and group overlaps and time ranges for a contract.",
                                 {**obj, "properties": {"contract": string}, "required": ["contract"]}, contract("splits")),
            "benchmark_results": ("A contract's results matrix, missing cells and thresholds (reported, never gating).",
                                  {**obj, "properties": {"contract": string}, "required": ["contract"]}, contract("results")),
            "storage_verify": ("Registered large artifacts compared with what is present.",
                               obj, lambda a: ["storage", "verify", "--repo", r, "--json"]),
            "storage_audit": ("Directory sizes against the configured caps and the largest untracked files (read-only).",
                              obj, lambda a: ["storage", "audit", "--repo", r, "--json"]),
            "integrity_status": ("Frozen sets, pending amendments and dataset roles.",
                                 obj, lambda a: ["integrity", "status", "--repo", r]),
            "spend_status": ("Spend totals against the cap.", obj, lambda a: ["spend", "status", "--repo", r]),
            "runs": ("The run ledger, latest first (read-only).",
                     {**obj, "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 500}}}, lambda a: []),
        }

    # ------------------------------------------------------------ tools
    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in self.tools:
            raise ToolError(f"unknown tool {name!r}")
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        props = self.tools[name][1].get("properties", {})
        extra = sorted(set(args) - set(props))
        if extra:
            raise ToolError(f"unknown argument(s) {extra}")
        for k, v in args.items():  # exact schema types (red-team K11)
            want = props[k].get("type")
            ok = {"string": isinstance(v, str), "boolean": isinstance(v, bool),
                  "integer": isinstance(v, int) and not isinstance(v, bool),
                  "array": isinstance(v, list) and all(isinstance(x, str) for x in v)}.get(want, True)
            if not ok:
                raise ToolError(f"{k} must be of type {want}")
        if name == "runs":
            return self._runs(args.get("limit", 20))
        argv = self.tools[name][2](args)
        code, out, err = _cli(argv)
        if name == "report_rule":
            rule = args.get("rule")
            if not isinstance(rule, str) or not re.fullmatch(r"R-\d{2}", rule):
                raise ToolError("rule must look like R-40")
            try:
                rep = json.loads(out)
            except ValueError:
                raise ToolError(err.strip() or "no report") from None
            from .rules import RULES

            if rule not in RULES:
                raise ToolError(f"unknown rule {rule}")
            rs = [x for x in rep["verdict"]["results"] if x["rule"] == rule and (args.get("subject") in (None, x["subject"]))]
            out = json.dumps(rs, indent=2, sort_keys=True)
        return {"exit_code": code, "stdout": out, "stderr": err}

    def _runs(self, limit: Any) -> dict[str, Any]:
        import tomllib

        from . import evidence as ev
        from .models import StewardConfig

        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ToolError("limit must be an integer from 1 to 500")
        try:
            from .models import load_config

            cfg = load_config(self.root)
        except Exception as e:  # an invalid configuration is reported, not raised
            raise ToolError(f"steward.toml is not valid: {e}") from None
        from .fsutil import escapes_root, inside

        if cfg.run is None:
            return {"exit_code": 0, "stdout": "[]", "stderr": "[run] is not configured"}
        if escapes_root(cfg.run.ledger) or not inside(self.root, cfg.run.ledger):  # red-team K2
            raise ToolError("the run ledger resolves outside the repository")
        recs = list(ev.runs(self.root, cfg).values())[::-1][:limit]
        # only what a client needs: no commands, parameters or environment (they can carry secrets; K2)
        rows = [{"run": r.get("run"), "label": r.get("label"), "contract": r.get("contract"), "time": r.get("time"),
                 "status": (r["outcome"] or {}).get("status"), "outputs": (r["outcome"] or {}).get("outputs")} for r in recs]
        return {"exit_code": 0, "stdout": json.dumps(rows, indent=2, sort_keys=True), "stderr": ""}

    # ------------------------------------------------------------ protocol
    def handle(self, msg: Any) -> dict[str, Any] | None:
        from . import __version__

        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(None, -32600, "invalid request")
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if "id" not in msg:
            return None  # a notification (e.g. notifications/initialized): never answered
        if isinstance(mid, bool) or not isinstance(mid, (str, int)):  # request IDs are strings or integers (K11)
            return _error(None, -32600, "the request id must be a string or an integer")
        if method == "initialize":
            return _result(mid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                                 "serverInfo": {"name": "bio-steward", "version": __version__},
                                 "instructions": "Read-only Bio-STEWARD checks. Approvals, runs, spend and writes stay on the CLI."})
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in self.tools.items()]})
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return _error(mid, -32602, "tools/call needs a tool name")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):  # K11: an array is not an empty object
                return _result(mid, {"content": [{"type": "text", "text": "arguments must be an object"}], "isError": True})
            try:
                res = self.call(params["name"], arguments)
            except ToolError as e:
                return _result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            failed = res["exit_code"] not in (0, 1, 2, 3)  # 1-3 are verdicts (FAIL, INCOMPLETE, UNKNOWN), not errors
            return _result(mid, {"content": [{"type": "text", "text": res["stdout"] or res["stderr"]}],
                                 "structuredContent": res, "isError": failed})
        return _error(mid, -32601, f"method not found: {method}")

    def serve(self, inp: Any, out: TextIO) -> None:
        """Newline-delimited JSON-RPC from a binary stream: each frame is at most MAX_FRAME bytes and UTF-8; a bad
        frame gets an error reply and the session continues (red-team K6)."""
        while True:
            raw = inp.readline(MAX_FRAME + 1)
            if not raw:
                break
            if len(raw) > MAX_FRAME and not raw.endswith(b"\n"):
                while True:  # discard the rest of the oversized line
                    rest = inp.readline(MAX_FRAME)
                    if not rest or rest.endswith(b"\n"):
                        break
                reply: dict[str, Any] | None = _error(None, -32600, f"request larger than {MAX_FRAME} bytes")
                out.write(json.dumps(reply, separators=(",", ":")) + "\n")
                out.flush()
                continue
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                line, reply = "", _error(None, -32700, "parse error: not UTF-8")
                out.write(json.dumps(reply, separators=(",", ":")) + "\n")
                out.flush()
                continue
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (ValueError, RecursionError):
                reply = _error(None, -32700, "parse error")
            else:
                try:
                    reply = self.handle(msg)
                except Exception as e:  # a bug must never take the server down silently
                    reply = _error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"internal error: {e!r}")
            if reply is not None:
                out.write(json.dumps(reply, separators=(",", ":")) + "\n")
                out.flush()


def _result(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def main(root: Path) -> int:
    import os

    from .fsutil import release_owner_lock
    from .session import hold_mcp_lock

    lock = hold_mcp_lock(root)  # K1: held for the server's lifetime; `session close --end` stops only a holder
    try:
        Server(root).serve(sys.stdin.buffer, sys.stdout)
    finally:
        release_owner_lock(root, f"mcp-{os.getpid()}", lock)
    return 0
