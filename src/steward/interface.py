"""Versioned CLI discovery and opt-in tagged JSON output."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from typing import Any

from . import __version__
from .fsutil import canonical_json
from .resources import schemas_dir
from .status import (
    EXIT_CANTCREAT, EXIT_DATAERR, EXIT_FAIL, EXIT_INCOMPLETE, EXIT_OK, EXIT_SOFTWARE, EXIT_UNKNOWN, EXIT_USAGE,
)

INTERFACE_SCHEMA = "steward.interface/1"
TAGGED_COMMANDS = {
    "audit progress": "steward.progress_audit/0.1",
    "benchmark results": "steward.benchmark_results/0.1",
    "benchmark splits": "steward.benchmark_splits/0.1",
    "diff impact": "steward.diff_impact/0.1",
    "diff run": "steward.diff_run/0.1",
    "diff runs": "steward.diff_runs/0.1",
    "exchange status": "steward.exchange_status/0.1",
    "licence inventory": "steward.licence_inventory/0.1",
    "pins status": "steward.pins_status/0.1",
    "research list": "steward.research_list/0.1",
    "storage audit": "steward.storage_audit/0.1",
    "storage scan": "steward.storage_scan/0.1",
    "storage verify": "steward.storage_verify/0.1",
    "study list": "steward.study_list/0.1",
    "timeline": "steward.timeline/0.1",
    "tokens report": "steward.tokens_report/0.1",
}

# 0.21.0 (W02): documents of commands that have no legacy --json flag, and the error document (C6).
OTHER_SCHEMAS = {
    "explain": "steward.explain/0.1",
    "check --digest-only": "steward.digest/0.1",
    "init": "steward.init_plan/0.1",
    "skills list": "steward.skills/0.1",
    # 0.21.0 (W03; STW-048 C10, C12; C21)
    "next": "steward.next/0.1",
    "tidy": "steward.tidy/0.1",
    "notifications": "steward.notifications/0.1",
    "decisions": "steward.decisions/0.1",
    "upgrade --check": "steward.upgrade/0.1",
    "issues inbox": "steward.issues_inbox/0.1",
    # 0.22.0 (X03): the attribution ledger per task
    "agents list": "steward.agents_list/0.1",
}
# Read commands without a legacy --json option (W05, STW-050).
READ_COMMANDS = {
    name: f"steward.{name.replace(' ', '_')}/0.1"
    for name in (
        "task board", "authorize pending", "authorize list", "authorize keys", "sprint status",
        "session start", "study show", "integrity status", "spend status", "release status",
        "channel status", "paper values", "paper displays", "paper citations", "talk plan", "talk prefs",
    )
}
ERROR_SCHEMA = "steward.error/0.1"
EXIT_NOT_CONFIGURED = 78


def add_json_options(parser: ArgumentParser, command: str, *, exclusive=None) -> None:
    options = exclusive if exclusive is not None else parser.add_mutually_exclusive_group()
    options.add_argument("--json", action="store_true", help="print JSON in the legacy format")
    options.add_argument("--format", choices=["text", "json"], default="text",
                         help="print text or versioned JSON")
    parser.set_defaults(json_schema=TAGGED_COMMANDS[command])


def add_json_format(parser: ArgumentParser, command: str, *, write_option: str | None = None) -> None:
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="print text or versioned JSON")
    parser.set_defaults(json_schema=(READ_COMMANDS | OTHER_SCHEMAS)[command], json_write_option=write_option)


def wants_json(args: Namespace) -> bool:
    return getattr(args, "json", False) or args.format == "json"


def write_json(args: Namespace, payload: dict | list) -> None:
    if args.format == "json":
        fields = payload if isinstance(payload, dict) else {"items": payload}
        write_document({**fields, "schema": args.json_schema})
    else:
        sys.stdout.write(canonical_json(payload))


class OutputSchemaError(RuntimeError):
    """The CLI built an output that does not meet its published schema."""


def write_document(document: dict) -> None:
    from pydantic import ValidationError

    from .interface_schemas import SCHEMAS

    tag = document["schema"]
    stem, version = tag.split("/")
    data = canonical_json(document)
    try:
        SCHEMAS[f"{stem}-{version}.schema.json"].model_validate_json(data, strict=True)
    except ValidationError as error:
        raise OutputSchemaError(tag) from error
    sys.stdout.write(data)


def describe() -> dict[str, Any]:
    from .runner import EXIT_LIMIT, EXIT_NO_SLOT

    schema_files = {}
    for path in sorted(schemas_dir().glob("*.schema.json")):
        name, version = path.name.removesuffix(".schema.json").rsplit("-", 1)
        schema_files[f"{name}/{version}"] = path.name
    commands = {
        name: {"argv": ["--format", "json"], "schema": schema, "legacy_argv": ["--json"]}
        for name, schema in TAGGED_COMMANDS.items()
    }
    commands.update({
        "check": {"argv": ["--format", "json"], "schema": "steward.report/0.1"},
        "check --digest-only": {"argv": ["--digest-only", "--against", "FILE", "--format", "json"],
                                "schema": OTHER_SCHEMAS["check --digest-only"]},
        "explain": {"argv": ["--all", "--format", "json"], "schema": OTHER_SCHEMAS["explain"]},
        "init": {"argv": ["--dry-run", "--format", "json"], "schema": OTHER_SCHEMAS["init"]},
        "skills list": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["skills list"]},
        "next": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["next"]},
        "tidy": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["tidy"]},
        "notifications": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["notifications"]},
        "decisions": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["decisions"]},
        "upgrade --check": {"argv": ["--check", "--format", "json"], "schema": OTHER_SCHEMAS["upgrade --check"]},
        "issues inbox": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["issues inbox"]},
        "agents list": {"argv": ["--format", "json"], "schema": OTHER_SCHEMAS["agents list"]},
        "interface": {"argv": ["--format", "json"], "schema": INTERFACE_SCHEMA},
        "licence notices": {"argv": ["--format", "cyclonedx"], "schema": "CycloneDX/1.5"},
        "paper manifest": {"argv": [], "schema": "steward.submission_manifest/0.1"},
        "shards plan": {"argv": ["--shards", "N", "--cost", "FILE"], "schema": "steward.shards/0.1"},  # W12 F11
        "tokens check": {"argv": ["--claude-hook"], "schema": None},
    })
    commands.update({
        name: {"argv": ["--format", "json"], "schema": schema}
        for name, schema in READ_COMMANDS.items()
    })
    return {
        "schema": INTERFACE_SCHEMA,
        "interface_version": 1,
        "tool_version": __version__,  # the CLI that wrote this document, for a consumer's handshake
        "schema_files": schema_files,
        "error_schema": ERROR_SCHEMA,  # C6: on stdout with --format json when a command exits 78
        "commands": commands,
        "exit_codes": {
            str(EXIT_OK): "Success",
            str(EXIT_FAIL): "Failed check or negative command outcome",
            str(EXIT_INCOMPLETE): "Incomplete check or comparison",
            str(EXIT_UNKNOWN): "Unknown check outcome",
            str(EXIT_USAGE): "Invalid usage or an invalid configuration",
            str(EXIT_DATAERR): "Invalid data or refused operation",
            str(EXIT_SOFTWARE): "Internal error",
            str(EXIT_CANTCREAT): "Could not create the requested files",
            str(EXIT_NOT_CONFIGURED): "Not configured: no steward.toml (a steward.error/0.1 document with --format json)",
            str(EXIT_NO_SLOT): "Run slot unavailable",
            "77": "Operation refused by the project policy",
            str(EXIT_LIMIT): "Run limit reached",
            "130": "Interrupted",
        },
    }
