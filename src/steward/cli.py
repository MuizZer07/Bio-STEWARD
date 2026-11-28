"""Command line: `steward init | check | report` (RELEASE_v0.1_SPEC §6).

`check` can write an explicit --output file and replaces the local diagnostic on a toolkit fault.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shlex
import subprocess
import sys
from contextvars import ContextVar
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .engine import UnknownGate, run_check
from .fsutil import canonical_json, find_root, glob_match, inside
from .init import apply, plan, sync_agents_block
from .interface import (ERROR_SCHEMA, EXIT_NOT_CONFIGURED, add_json_format, add_json_options, describe, wants_json,
                        write_document, write_json)
from .report import Report, render_markdown, render_summary, render_text, select_results, summary_line
from .rules import AREAS, RULES
from . import models as _models
from .status import (EXIT_CANTCREAT, EXIT_DATAERR, EXIT_OK, EXIT_SOFTWARE, EXIT_USAGE, Status,
                     exit_code_for, gate_exit_code)

NOT_A_REPO = "not a steward repository (no steward.toml); run `steward init`"
# 0.21.0 (STW-047 C6): no steward.toml exits EXIT_NOT_CONFIGURED (78, sysexits EX_CONFIG); it was 64 before.


# Defined in status.py, not here: under `python -m steward.cli` this file is loaded twice (as __main__ and as
# steward.cli, when another module imports from it), and two classes would let the dispatcher miss the exception.
from .status import NotConfigured  # noqa: E402  (C6: `_dispatch` turns it into exit 78)


def _require_root(args: argparse.Namespace) -> Path:
    """The project root, or NotConfigured."""
    root = args.repo.resolve() if args.repo else find_root(Path.cwd())
    if root is None or not (root / "steward.toml").is_file():
        raise NotConfigured(NOT_A_REPO)
    return root


def error_document(code: str, message: str, exit_code: int, hint: str | None = None) -> dict[str, Any]:
    from . import __version__

    return {"schema": ERROR_SCHEMA, "tool_version": __version__, "code": code, "message": message,
            "exit": exit_code, "hint": hint}


def _not_configured(args: argparse.Namespace, e: NotConfigured) -> int:
    print(f"steward: {e}", file=sys.stderr)
    if getattr(args, "format", None) == "json":  # the legacy --json flag keeps its empty stdout
        sys.stdout.write(canonical_json(error_document(
            "not_configured", "not a steward repository (no steward.toml)", EXIT_NOT_CONFIGURED,
            "steward init --for benchmark|reanalysis|paper|agents|licence")))
    return EXIT_NOT_CONFIGURED


_used_options: ContextVar[set[str] | None] = ContextVar("used_options", default=None)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # usage errors exit 64, not argparse's 2 (2 means INCOMPLETE here)
        self.print_usage(sys.stderr)
        print(f"steward: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)

    def _get_values(self, action, arg_strings):
        used = _used_options.get()
        if used is not None and action.option_strings:
            used.add(max(action.option_strings, key=len))
        return super()._get_values(action, arg_strings)


QUIET_BREAKERS = {"R-75.sample_imbalance", "R-53.undelivered", "R-53.upgrade_available"}  # advice visible in --quiet

HELP_GROUPS = """Commands by what you do:
  Start            init · example · check · explain · report · interface · skills · next
  Plan             plans · benchmark · study · research · timeline · sprint
  Run              run · diff · compare · shards · stage · tokens
  Data and records data · freeze · amend · seal · unseal · integrity · frozen · storage · pins · licence · decisions
  Papers and talks paper · talk · docs
  Approvals        authorize · spend
  Agents and tasks task (template · brief · dispatch) · agents · session · audit · tidy · notifications
  Projects         exchange · issue · issues · constitution · channel
  Releases         release · upgrade · stranger-test · repro · hooks · ledger · mcp

New here? `steward init --for reanalysis` (or benchmark, paper, agents, licence), then `steward check --summary`.
"""

# The subcommand destinations that are not `<command>_command` (W12 F6: the fault hint names the subcommand too).
SUBCOMMAND_DESTS = {"authorize": "auth_command", "stranger-test": "stranger_command"}


def subcommand_dest(command: str) -> str:
    return SUBCOMMAND_DESTS.get(command, f"{command.replace('-', '_')}_command")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", type=Path, help="repository directory (default: search upwards from here)")
    common.add_argument("--no-color", action="store_true", help="plain output (output is never coloured in v0.1)")
    common.add_argument("--config-overlay", metavar="FILE", help="an additions-only configuration overlay (else "
                        "STEWARD_CONFIG_OVERLAY, else steward.local.toml)")

    p = _Parser(prog="steward", formatter_class=argparse.RawDescriptionHelpFormatter,
                description="The engineering and integrity layer for agentic computational biology.",
                epilog=HELP_GROUPS)
    p.add_argument("--version", action="version", version=f"steward {__version__}")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    pintr = sub.add_parser("interface", help="describe JSON commands, schemas and exit codes")
    pintr.add_argument("--format", choices=["json"], default="json", help="print the versioned interface as JSON")

    pug = sub.add_parser("upgrade", parents=[common], help="check for a CLI release or install an exact version")
    upgrade_mode = pug.add_mutually_exclusive_group(required=True)
    upgrade_mode.add_argument("--check", action="store_true", help="show the installed and newest known versions")
    upgrade_mode.add_argument("--to", metavar="VERSION", help="install this version after terminal confirmation")
    pug.add_argument("--online", action="store_true", help="with --check, look up the latest release on PyPI")
    pug.add_argument("--format", choices=["text", "json"], default="text",
                     help="with --check, print text or versioned JSON")
    pug.add_argument("--allow-downgrade", action="store_true", help="with --to, permit an older version")

    pi = sub.add_parser("init", parents=[common], help="scaffold this repository (never overwrites)")
    pi.add_argument("--profile", choices=["exploratory", "confirmatory"], default="exploratory",
                    help="exploratory (default: rules report, few demand) or confirmatory (requires a benchmark "
                         "contract and prior-work record, and recommends an independent release review)")
    pi.add_argument("--for", dest="goals", action="append", choices=sorted(GOALS), metavar="GOAL",
                    help="set up for a goal (repeatable): " + ", ".join(sorted(GOALS)))
    pi.add_argument("--agents-md", action="store_true", help="append the steward block to an existing AGENTS.md")
    pi.add_argument("--skills", type=Path, metavar="DIR", action="append",
                    help="copy skills into DIR (e.g. .agents/skills); repeat for more harnesses: the first DIR holds the "
                         "one copy, the others link to it")
    pi.add_argument("--kits", metavar="LIST", help="skill bundles to copy with --skills: core, paper, talk "
                    "(default: core, plus paper with --paper)")
    pi.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    pi.add_argument("--format", choices=["text", "json"], default="text",
                    help="with --dry-run: print the plan as versioned JSON (0.21.0)")
    pi.add_argument("--paper", nargs="?", const="main", metavar="NAME",
                    help="also scaffold a LaTeX paper (paper/ for 'main', papers/NAME/ otherwise)")

    pi.add_argument("--talk", metavar="NAME", help="also scaffold a Beamer talk in talks/NAME/")
    pi.add_argument("--project", metavar="NAME", help="project name (default: the main repository's directory)")
    pi.add_argument("--templates", metavar="LIST", help="templates to add regardless of profile: contract, prior-work")

    pc = sub.add_parser("check", parents=[common], help="evaluate the rules; read-only",
                        epilog="A toolkit fault can replace the local .steward/last-error.json diagnostic. A check lists "
                               "this checkout in the machine's "
                               "project registry (in the user's config folder), so storage cleanup knows who shares a "
                               "folder. For a read-only run (a reviewer's sandbox, CI), set STEWARD_NO_REGISTRY=1; to "
                               "opt the project out for good, set registry = false under [storage.clean] in "
                               "steward.toml (FB-019).")
    # No `choices=` here: Python 3.11 rejects an empty nargs="*" list against choices. Validated in cmd_check.
    pc.add_argument("areas", nargs="*", metavar="AREA", help=f"limit to {', '.join(sorted(AREAS))}")
    pc.add_argument("--gate", default="default")
    pc.add_argument("--format", choices=["text", "json"], default="text")
    pc.add_argument("--output", type=Path, metavar="FILE", help="also write the full JSON report to FILE")
    pc.add_argument("--final", action="store_true", help="final (submission) mode for every paper: stricter R-09 and R-12")
    pc.add_argument("--quiet", action="store_true",
                    help="one line when every gate is eligible and nothing needs attention; otherwise the summary. "
                    "The exit code is the gate's: a FAIL outside every gate exits 0 (use --fail-on fail)")
    pc.add_argument("--fail-on", choices=["fail", "incomplete"],
                    help="for scripts: exit non-zero when any result is FAIL (fail), or FAIL, INCOMPLETE or UNKNOWN "
                    "(incomplete), whatever the gate says (0.21.0)")
    pc.add_argument("--summary", action="store_true",
                    help="compact text: counts, gates and every non-PASS result; the full evidence stays in --output")
    pc.add_argument("--rule", metavar="R-xx", help="check only the areas of this rule and show its results with every "
                    "detail (0.20.1)")
    pc.add_argument("--all", action="store_true", dest="all_lines",
                    help="with --summary: one line per not-applicable rule (default: one folded line naming them)")
    pc.add_argument("--digest-only", action="store_true",
                    help="evaluate no rule: recompute the inputs digest of the report given with --against (0.21.0)")
    pc.add_argument("--against", metavar="FILE", help="with --digest-only: a report written by `steward check` "
                    "(--output FILE or --format json), or - for stdin")
    pex_ = sub.add_parser("explain", parents=[common], help="what a rule checks, why, its result codes and fixes")
    pex_.add_argument("rule", nargs="?", help="a rule ID, e.g. R-42")
    pex_.add_argument("--all", action="store_true", dest="all_rules", help="every rule, in catalogue order (0.21.0)")
    pex_.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")

    psk = sub.add_parser("skills", parents=[common], help="the bundled skills, their bundles and this project's copies")
    psksub = psk.add_subparsers(dest="skills_command", required=True, parser_class=_Parser)
    pskl = psksub.add_parser("list", parents=[common], help="list skills by bundle; with [skills], the state of each "
                             "copy (R-60)")
    pskl.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")

    pp = sub.add_parser("paper", parents=[common], help="PaperKit helpers")
    psub = pp.add_subparsers(dest="paper_command", required=True, parser_class=_Parser)
    pv = psub.add_parser("values", parents=[common], help="compute the values registry; --write regenerates the file the text uses")
    pv.add_argument("name", nargs="?", help="paper name (default: the only paper, or 'main')")
    add_json_format(pv, "paper values", write_option="--write")
    pv.add_argument("--write", action="store_true", help="write the generated values file (values.tex, _variables.yml or values.json)")

    pd = psub.add_parser("displays", parents=[common], help="list displays; --record writes displays.lock after a build")
    pd.add_argument("name", nargs="?", help="paper name (default: the only paper, or 'main')")
    add_json_format(pd, "paper displays", write_option="--record")
    pd.add_argument("--record", action="store_true", help="record script, input and output hashes in displays.lock")

    pci = psub.add_parser("citations", parents=[common], help="the citation verification record (optional; R-77)")
    pci.add_argument("name", nargs="?", help="paper name (default: the only paper, or 'main')")
    add_json_format(pci, "paper citations", write_option="--fetch")
    pci.add_argument("--fetch", action="store_true", help="resolve unrecorded DOIs (Crossref) and PMIDs (PubMed) online")

    pm = psub.add_parser("manifest", parents=[common], help="submission manifest: files, sizes, SHA-256, commit")
    pm.add_argument("name", nargs="?", help="paper name (default: the only paper, or 'main')")
    pm.add_argument("--output", type=Path, metavar="FILE", help="write the manifest JSON to FILE (default: stdout)")

    pu = sub.add_parser("run", parents=[common], help="run a command under resource limits and record it")
    pu.add_argument("--slot", help="concurrency slot from [run] slots")
    pu.add_argument("--wait", action="store_true", help="wait for a free slot instead of refusing")
    pu.add_argument("--wait-timeout", type=float, metavar="SECONDS", help="wait at most this long for a free slot, then refuse (exit 75)")
    pu.add_argument("--wall", type=float, metavar="S")
    pu.add_argument("--mem", type=float, metavar="MB")
    pu.add_argument("--hang", type=float, metavar="S", help="kill after S seconds without output")
    pu.add_argument("--hang-cpu", type=float, metavar="S", help="kill after S seconds without CPU progress of the job's tree")
    pu.add_argument("--socket-timeout", type=float, metavar="S", help="passed to the job as STEWARD_SOCKET_TIMEOUT")
    pu.add_argument("--disk-free", type=float, metavar="MB")
    pu.add_argument("--estimate-min", type=float, metavar="M", help="your run estimate, recorded for comparison")
    pu.add_argument("--input", action="append", default=[], metavar="PATH")
    pu.add_argument("--output", action="append", default=[], metavar="PATH")
    pu.add_argument("--param", action="append", default=[], metavar="K=V")
    pu.add_argument("--seed")
    pu.add_argument("--label")
    pu.add_argument("--run-id", metavar="ID", help="the run's id (default: a new one); the sprint dispatcher passes it "
                    "to link a task to its run (0.21.0)")
    pu.add_argument("--contract", metavar="ID", help="the benchmark contract this run serves (R-39 timing check)")
    pu.add_argument("--metrics", metavar="FILE", help="small JSON metrics file recorded by value (<= 64 KiB) for steward diff run")
    pu.add_argument("--recover", action="store_true", help="mark started runs whose supervisor is gone as interrupted")
    pu.add_argument("cmd", nargs=argparse.REMAINDER, help="-- COMMAND ...")

    pdf_ = sub.add_parser("diff", parents=[common], help="compare runs; change impact")
    dsub = pdf_.add_subparsers(dest="diff_command", required=True, parser_class=_Parser)
    dr = dsub.add_parser("run", parents=[common], help="repeatability of run B against run A")
    dr.add_argument("a")
    dr.add_argument("b")
    dr.add_argument("--tol", action="append", default=[], metavar="POINTER=abs:X|rel:X")
    dr.add_argument("--default-tol", metavar="abs:X|rel:X")
    add_json_options(dr, "diff run")
    dns = dsub.add_parser("runs", parents=[common], help="recorded runs side by side; --svg draws them")
    dns.add_argument("--label", metavar="GLOB", help="only runs whose label matches")
    dns.add_argument("--svg", type=Path, metavar="FILE", help="also write a bar chart (SVG)")
    dns.add_argument("--metric", choices=["duration", "memory"], default="duration")
    add_json_options(dns, "diff runs")
    di = dsub.add_parser("impact", parents=[common], help="results made stale by changed inputs or code")
    add_json_options(di, "diff impact")

    prl = sub.add_parser("release", parents=[common], help="release manifest and distribution audit")
    rsub = prl.add_subparsers(dest="release_command", required=True, parser_class=_Parser)
    rpb = rsub.add_parser("publish", parents=[common], help="publish a release tag to the public repository (model A, 0.19.0)")
    rpb.add_argument("tag")
    rpb.add_argument("--push", action="store_true", help="push the public commit and tag after the summary")
    rpb.add_argument("--dry-run", action="store_true", help="export and scan only")
    rls = rsub.add_parser("status", parents=[common], help="the last public release and what is not yet published")
    add_json_format(rls, "release status")
    rgp = rsub.add_parser("go-public", parents=[common],
                          help="go public with a release mirror: readiness, the plan, and with --apply the steps (0.20.3)")
    rgp.add_argument("--owner", required=True, help="the GitHub owner (user or organisation)")
    rgp.add_argument("--name", required=True, help="the public repository's name (usually the current one)")
    rgp.add_argument("--dev-name", help="the private development repository's new name (default NAME-dev)")
    rgp.add_argument("--tag", help="the release to publish first (default: the latest v* tag)")
    rgp.add_argument("--apply", action="store_true", help="run the steps (renames and creates repositories, pushes)")
    rgp.add_argument("--public", action="store_true",
                     help="create the release repository public at once (default: private, so you look first)")
    rsu = rsub.add_parser("setup", parents=[common], help="choose how releases go public: mirror (A) or open development (B)")
    rsu.add_argument("--mode", choices=["mirror", "open"])
    rsu.add_argument("--remote", help="the public repository (URL or path)")
    rsu.add_argument("--author", help='the public identity: a name and your no-reply address (GitHub settings, Emails)')
    rm_ = rsub.add_parser("manifest", parents=[common], help="record artifact, lock and citation hashes for a release")
    rm_.add_argument("--version")
    rm_.add_argument("--identity", action="append", default=[], metavar="KEY=VALUE",
                     help="an external identity of the release (repeatable), e.g. image=sha256:... doi=10.../...")
    rm_.add_argument("--dist", type=Path, help="the distribution folder (default: [release] dist); may be outside the repository")
    rm_.add_argument("--image", action="append", default=[], metavar="TAG=DIGEST[@PLATFORM]", help="a container image (repeatable)")
    rm_.add_argument("--archives", type=Path, metavar="DIR", help="a folder of image archives (docker save) to record")
    rm_.add_argument("--output", type=Path, metavar="FILE",
                     help="write the manifest here (default: [release] manifest), e.g. into a release folder outside the repository")
    rvf = rsub.add_parser("verify", parents=[common], help="re-hash an image bundle against the manifest")
    rvf.add_argument("dir", type=Path)
    rf = rsub.add_parser("fingerprint", parents=[common], help="AST fingerprint of the runtime modules ([release] fingerprint)")
    rf.add_argument("--record", action="store_true", help="record the current fingerprints as the baseline")
    rk = rsub.add_parser("ack", parents=[common], help="acknowledge a neutral change to a module (append-only, with a reason)")
    rk.add_argument("module")
    rk.add_argument("--reason", required=True)
    rb = rsub.add_parser("bundle", parents=[common], help="write a deterministic zip of release assets (recorded by the manifest)")
    rb.add_argument("name")
    rb.add_argument("--paths", nargs="+", required=True, metavar="PATH", help="repository-relative files or folders")
    rb.add_argument("--out", type=Path, help="output folder (default: [release] bundles)")
    rb.add_argument("--test-report", metavar="CMD", help="run CMD once (no shell) and record its exit code")
    rb.add_argument("--force", action="store_true", help="replace an existing bundle of that name")
    ra = rsub.add_parser("audit", parents=[common], help="list and check every member of the built distributions")
    ra.add_argument("--dist", type=Path, help="distribution directory (default: [release] dist); works without steward.toml")

    pstg = sub.add_parser("stage", parents=[common], help="staged runs: a recorded GO before outcomes, accrual minimum")
    stsub = pstg.add_subparsers(dest="stage_command", required=True, parser_class=_Parser)
    str_ = stsub.add_parser("run", parents=[common], help="run a declared stage's command, if it may run")
    str_.add_argument("name")
    str_.add_argument("cmd", nargs=argparse.REMAINDER, help="-- COMMAND ... (use steward run inside for limits)")
    psh = sub.add_parser("shards", parents=[common], help="balanced parallel shards from a cost file")
    shsub = psh.add_subparsers(dest="shards_command", required=True, parser_class=_Parser)
    shp = shsub.add_parser("plan", parents=[common], help="longest-first balanced plan, with its merge step")
    shp.add_argument("--shards", type=int, required=True)
    shp.add_argument("--cost", type=Path, required=True, help="JSON {job: cost} or CSV lines job,cost")
    shp.add_argument("--out", type=Path)

    pfz = sub.add_parser("frozen", parents=[common], help="frozen file sets (agent versions, golden fixtures)")
    fzsub = pfz.add_subparsers(dest="frozen_command", required=True, parser_class=_Parser)
    fzr = fzsub.add_parser("record", parents=[common], help="record a frozen set's hashes (again only with a decision)")
    fzr.add_argument("name")
    fzr.add_argument("--decision", help="the decisions-log heading text that approves a new version")

    pdo = sub.add_parser("docs", parents=[common], help="generate project documentation and README content (R-69)")
    dsub = pdo.add_subparsers(dest="docs_command", required=True, parser_class=_Parser)
    di = dsub.add_parser("init", parents=[common], help="write mkdocs.yml and a home page; never overwrites")
    di.add_argument("--pages", action="store_true", help="also a GitHub Pages workflow")
    dsub.add_parser("build", parents=[common], help="generate the project pages from its records (privacy-checked)")
    dr = dsub.add_parser("readme", parents=[common], help="update the generated block in README.md")
    dr.add_argument("--pypi", action="store_true", help="print the plain Markdown block for PyPI")

    pag = sub.add_parser("agents", parents=[common], help="multi-agent attribution and scores (append-only)")
    agsub = pag.add_subparsers(dest="agents_command", required=True, parser_class=_Parser)
    aat = agsub.add_parser("attempt", parents=[common], help="record an attempt at a task")
    aat.add_argument("task")
    aat.add_argument("--agent", required=True)
    aat.add_argument("--provider", required=True)
    aat.add_argument("--model", required=True, help="the exact model ID, or unknown")
    aat.add_argument("--suggested", help="the model suggested for the task")
    aat.add_argument("--started")
    aat.add_argument("--ended")
    aat.add_argument("--reviewer")
    # X03: optional performance-ledger fields; an attempt without them is recorded exactly as before.
    aat.add_argument("--estimate-file", metavar="FILE",
                     help="a JSON object with the estimate made before the attempt (assumptions, effort, cost, tokens)")
    aat.add_argument("--harness", help="the harness that ran the agent")
    aat.add_argument("--harness-version", help="the harness's version")
    aat.add_argument("--parent", metavar="TASK", help="the parent task")
    aat.add_argument("--status", help="the task's status at this attempt")
    aev = agsub.add_parser("event", parents=[common], help="record a task milestone (assigned, implemented, ...)")
    aev.add_argument("task")
    aev.add_argument("--kind", required=True, choices=list(_models.AGENT_EVENTS))
    aev.add_argument("--time", required=True, help="when it happened, ISO 8601 with a time zone (e.g. 2026-11-27T10:00:00Z)")
    als = agsub.add_parser("list", parents=[common],
                           help="attempts, estimates, scores and events per task, newest first")
    als.add_argument("task", nargs="?", help="only this task")
    add_json_format(als, "agents list")
    # 0.23.0 (STW-061 D01): delegation, its setup and the agents' availability
    asu = agsub.add_parser("setup", parents=[common],
                           help="find claude, codex and agy, show the [delegation] to write as a diff, write it "
                                "after confirmation (no model call, no network)")
    asu.add_argument("--yes", action="store_true", help="write without asking")
    asu.add_argument("--master", choices=list(_models.DELEGATION_AGENTS),
                     help="the agent that reviews, fixes and merges (default: the configured one, else claude-code)")
    ast_ = agsub.add_parser("status", parents=[common],
                            help="each agent: available, limited until a time, signed out or missing; and the master")
    ast_.add_argument("--now", metavar="TIME", help="the time to judge reset times against (ISO 8601 with a zone)")
    add_json_format(ast_, "agents status")
    asc = agsub.add_parser("score", parents=[common], help="score an attempt (never by its author)")
    asc.add_argument("task")
    asc.add_argument("--attempt", type=int, required=True)
    asc.add_argument("--scorer", required=True)
    asc.add_argument("--score", type=float, required=True)
    asc.add_argument("--rubric", required=True)
    asc.add_argument("--override", metavar="REASON", help="replace an earlier score, with the reason")

    pss = sub.add_parser("session", parents=[common], help="session sign-off and resumption (constitution Article VIII.2)")
    ssub2 = pss.add_subparsers(dest="session_command", required=True, parser_class=_Parser)
    sss = ssub2.add_parser("start", parents=[common], help="print the constitution version and the handoff, nothing else")
    add_json_format(sss, "session start")
    sc_ = ssub2.add_parser("close", parents=[common], help="check the records and write one bounded handoff")
    sc_.add_argument("--decisions-logged", action="store_true",
                     help="you confirm that every owner decision of this session is in the decisions log")
    sc_.add_argument("--next", action="append", default=[], metavar="TEXT", help="a next step with its task ID (1 to 3)")
    sc_.add_argument("--question", action="append", default=[], metavar="TEXT", help="an open decision for the owner")
    sc_.add_argument("--agreement", action="append", default=[], metavar="TEXT", help="a working agreement, with its date")
    sc_.add_argument("--read-first", action="append", default=[], metavar="PATH", help="a record to read first (at most 5)")
    sc_.add_argument("--tests", metavar="TEXT", help="the last test result, as reported")
    sc_.add_argument("--signature", metavar="TEXT", help="the signature line (date · mode · harness · provider · model)")
    sc_.add_argument("--allow-dirty", action="store_true", help="close with uncommitted process records (listed)")
    sc_.add_argument("--end", action="store_true", help="also stop the toolkit's processes and remove its caches")
    sc_.add_argument("--dry-run", action="store_true", help="print the handoff; write and stop nothing")

    prp = sub.add_parser("repro", parents=[common], help="reproduction gate: re-derived outputs against a reference manifest")
    psub = prp.add_subparsers(dest="repro_command", required=True, parser_class=_Parser)
    pm = psub.add_parser("manifest", parents=[common], help="write the contract's manifest from a folder of reference outputs")
    pm.add_argument("id")
    pm.add_argument("--from", dest="source", type=Path, required=True, metavar="DIR")
    pc = psub.add_parser("check", parents=[common], help="compare re-derived outputs with the manifest; append the result")
    pc.add_argument("id")
    pc.add_argument("--work", type=Path, required=True, metavar="DIR")
    pc.add_argument("--run", metavar="RUN_ID", help="the steward run record of the replay (recorded, not verified)")

    pbm = sub.add_parser("benchmark", parents=[common], help="benchmark contract checks (v0.7)")
    bsub = pbm.add_subparsers(dest="benchmark_command", required=True, parser_class=_Parser)
    bsp = bsub.add_parser("splits", parents=[common], help="per-split counts, ID and group overlaps, checks run")
    bsp.add_argument("contract", help="the contract file (repository-relative)")
    add_json_options(bsp, "benchmark splits")
    bpw = bsub.add_parser("power", parents=[common], help="power from development effects (resampled, seeded)")
    bpw.add_argument("contract")
    bpw.add_argument("--effects", required=True, help="JSON list (or one value per line) of per-unit development effects")
    bpw.add_argument("--test", choices=["sign-flip", "bootstrap"], default="sign-flip")
    bpw.add_argument("--alpha", type=float, default=0.05)
    bpw.add_argument("--shrink", default="1,0.5", help="comma-separated effect shrink factors")
    bpw.add_argument("--n", required=True, help="comma-separated numbers of units")
    bpw.add_argument("--reps", type=int, default=1000)
    bpw.add_argument("--seed", type=int, default=20261123)
    bre = bsub.add_parser("results", parents=[common], help="the results matrix: missing cells and thresholds")
    bre.add_argument("contract")
    add_json_options(bre, "benchmark results")

    psp = sub.add_parser("sprint", parents=[common],
                         help="a supervised sequence of agent tasks for a window of time (0.13.0)")
    spsub = psp.add_subparsers(dest="sprint_command", required=True, parser_class=_Parser)
    spl = spsub.add_parser("plan", parents=[common], help="draft a sprint file from the board, the exchange or a milestone")
    spl.add_argument("id")
    spl.add_argument("--from", dest="source", choices=["board", "exchange"], default="board")
    spl.add_argument("--milestone")
    spl.add_argument("--start", help="window start, ISO with time zone (default: now)")
    spl.add_argument("--hours", type=float, default=8.0)
    for name, hlp in (("check", "validate a sprint file"), ("status", "each task's state, from the sprint ledger"),
                      ("report", "write and print the sprint's report"), ("signatures", "the signatures the tasks need")):
        x = spsub.add_parser(name, parents=[common], help=hlp)
        x.add_argument("id")
        if name == "status":
            add_json_format(x, "sprint status")
    sst = spsub.add_parser("start", parents=[common], help="dispatch tasks as their orders come, through steward run")
    sst.add_argument("id")
    sst.add_argument("--watch", action="store_true", help="keep waiting for orders, retries and rechecks until the "
                     "window ends, every task is finished, or `sprint stop`")
    for name, hlp in (("go", "order a task to start (or --retry a failed one)"), ("hold", "hold a task"),
                      ("skip", "skip a task, with a reason")):
        x = spsub.add_parser(name, parents=[common], help=hlp)
        x.add_argument("id")
        x.add_argument("task")
        if name == "go":
            x.add_argument("--retry", action="store_true")
        if name == "skip":
            x.add_argument("--reason", required=True)
    srl = spsub.add_parser("reload", parents=[common],
                           help="order the dispatcher to read the sprint file again, also while a task runs (0.21.0)")
    srl.add_argument("id")
    sstop = spsub.add_parser("stop", parents=[common], help="stop dispatching; --now also stops running tasks")
    sstop.add_argument("id")
    sstop.add_argument("--now", action="store_true")
    sre = spsub.add_parser("recheck", parents=[common],
                           help="run a failed task's done commands on its branch's head and record done or failed (0.21.0)")
    sre.add_argument("id")
    sre.add_argument("task")
    sac = spsub.add_parser("accept", parents=[common],
                           help="mark a worker's task in review done, after the master verified it (0.23.0)")
    sac.add_argument("id")
    sac.add_argument("task")
    srw = spsub.add_parser("rework", parents=[common],
                           help="send a worker's task in review back, with a note, to the same agent or the master "
                                "(0.23.0)")
    srw.add_argument("id")
    srw.add_argument("task")
    srw.add_argument("--note", required=True, help="what to change")
    srw.add_argument("--to", choices=["same", "master"], default="same",
                     help="who does it again: the agent of the last attempt (default) or the master")
    sad = spsub.add_parser("add", parents=[common],
                           help="add a task written into the sprint file after the sprint opened (0.21.0)")
    sad.add_argument("id")
    sad.add_argument("task")
    swa = spsub.add_parser("watch", parents=[common],
                           help="one line per new event (states, commits, tool steps) until nothing runs (0.21.0)")
    swa.add_argument("id")
    swa.add_argument("--poll", type=float, default=2.0, metavar="S", help="seconds between looks (default 2)")

    pch = sub.add_parser("channel", parents=[common], help="switch a tool between its stable and dev source (0.19.0)")
    chsub = pch.add_subparsers(dest="channel_command", required=True, parser_class=_Parser)
    chu = chsub.add_parser("use", parents=[common], help="install a [[channel]] tool from its stable or dev source")
    chu.add_argument("name")
    chu.add_argument("which", choices=["stable", "dev"])
    chu.add_argument("--tag", help="a release tag of that source")
    chu.add_argument("--yes", action="store_true", help="run the install command (otherwise it is printed)")
    chs = chsub.add_parser("status", parents=[common], help="which source each [[channel]] tool was last installed from")
    add_json_format(chs, "channel status")
    plc = sub.add_parser("licence", parents=[common], help="licence governance: inventory and third-party notices (0.19.0)")
    lcsub = plc.add_subparsers(dest="licence_command", required=True, parser_class=_Parser)
    lci = lcsub.add_parser("inventory", parents=[common], help="every dependency with its licence and the policy's verdict")
    add_json_options(lci, "licence inventory")
    lcn = lcsub.add_parser("notices", parents=[common], help="third-party notices (Markdown) or an SBOM (CycloneDX JSON)")
    lcn.add_argument("--format", choices=["md", "cyclonedx"], default="md")
    lcn.add_argument("--write", action="store_true", help="write the notices file declared in [licence] notices")
    pst = sub.add_parser("study", parents=[common], help="study records: inputs, references, tools, results, papers (0.18.0)")
    stsub = pst.add_subparsers(dest="study_command", required=True, parser_class=_Parser)
    stn = stsub.add_parser("new", parents=[common], help="create a study record from the template")
    stn.add_argument("id")
    stn.add_argument("--title", required=True)
    stn.add_argument("--kind", default="study", help="reanalysis, experiment, claim, benchmark, …")
    stl = stsub.add_parser("list", parents=[common], help="every study with its check")
    add_json_options(stl, "study list")
    stw = stsub.add_parser("show", parents=[common], help="a study card")
    stw.add_argument("id")
    add_json_format(stw, "study show")
    sta = stsub.add_parser("add-input", parents=[common], help="record a data source in a study (and fingerprint its files)")
    sta.add_argument("id")
    sta.add_argument("--source", required=True, help="GEO, SRA, ENA, ArrayExpress, Zenodo, a URL host, local, …")
    sta.add_argument("--accession", help="e.g. GSE5281")
    sta.add_argument("--url")
    sta.add_argument("--file", action="append", default=[], metavar="PATH", help="a file of this input (repeatable)")
    stf = stsub.add_parser("fingerprint", parents=[common], help="compare recorded file digests; --write fills missing ones")
    stf.add_argument("id")
    stf.add_argument("--write", action="store_true")
    stf.add_argument("--accept", metavar="PATH", help="record a changed file's new bytes on purpose (0.20.2)")
    pst_ = sub.add_parser("stranger-test", parents=[common],
                          help="a newcomer's first hour with a release, by an agent that has never seen it (0.20.2)")
    stsub_ = pst_.add_subparsers(dest="stranger_command", required=True, parser_class=_Parser)
    stb_ = stsub_.add_parser("brief", parents=[common], help="write the self-contained prompt for an agent")
    stb_.add_argument("--tag", required=True, help="the release (tag or commit) the stranger installs")
    stb_.add_argument("--for", dest="agent", choices=["codex", "gemini", "claude", "generic"], default="generic")
    stb_.add_argument("--output", type=Path, metavar="FILE")
    str_ = stsub_.add_parser("record", parents=[common], help="file a stranger's report in development/assessment/")
    str_.add_argument("report", type=Path)
    str_.add_argument("--tag", required=True)
    str_.add_argument("--agent", required=True, help="who ran it, e.g. codex, gemini")
    pex = sub.add_parser("example", parents=[common], help="copy a worked example into a new folder (0.20.0)")
    pex.add_argument("name", choices=["biology"], help="biology: a public GEO series (GSE7621) checked end to end")
    pex.add_argument("dest", type=Path, help="a new or empty folder")
    pdt = sub.add_parser("data", parents=[common], help="public data: fetch with provenance into a study (0.20.0)")
    dtsub = pdt.add_subparsers(dest="data_command", required=True, parser_class=_Parser)
    dtf = dtsub.add_parser("fetch", parents=[common], help="download an accession's files, check them, record them in a study")
    dtf.add_argument("source", metavar="SOURCE:ACCESSION",
                     help="GEO:GSE5281, ENA:SRR1234567 (or SRA:), ArrayExpress:E-MTAB-1234, Zenodo:1234567, or an https URL")
    dtf.add_argument("--study", required=True, help="the study record that gets the input")
    dtf.add_argument("--file", action="append", default=[], metavar="NAME",
                     help="a file of the accession (GEO supplementary, ArrayExpress, a filter for ENA and Zenodo); repeatable")
    dtf.add_argument("--dest", metavar="DIR", help="folder in the repository (default data/raw/ACCESSION)")
    dtf.add_argument("--sha256", metavar="HEX", help="the expected sha256 (one file), when the source states one")
    dtf.add_argument("--dry-run", action="store_true", help="show the files and where they go; download nothing")
    prs = sub.add_parser("research", parents=[common], help="literature reviews, novelty maps, gaps, dead ends (0.18.0)")
    rssub = prs.add_subparsers(dest="research_command", required=True, parser_class=_Parser)
    rsn = rssub.add_parser("new", parents=[common], help="create a research record from its template")
    rsn.add_argument("kind", choices=["review", "novelty", "gaps", "dead-end"])
    rsn.add_argument("id")
    rsn.add_argument("--title", required=True)
    rsl = rssub.add_parser("list", parents=[common], help="every record, newest first, with what needs attention")
    add_json_options(rsl, "research list")
    cmp = sub.add_parser("compare", parents=[common], help="compare two recorded pipeline runs")
    cmpsub = cmp.add_subparsers(dest="compare_command", required=True, parser_class=_Parser)
    cmpr = cmpsub.add_parser("record", parents=[common], help="record agreement and disagreements by key")
    cmpr.add_argument("name", help="comparison name, or the shadow stage name")
    cmpr.add_argument("--a", required=True, metavar="RUN", help="reference run ID")
    cmpr.add_argument("--b", required=True, metavar="RUN", help="candidate run ID")
    cmpr.add_argument("--key", required=True, metavar="COLUMN", help="unique key column in both tables")
    cmpr.add_argument("--value", metavar="COLUMN", help="class column in both tables")
    cmpr.add_argument("--output-a", metavar="PATH", help="select a recorded CSV or TSV output from run A")
    cmpr.add_argument("--output-b", metavar="PATH", help="select a recorded CSV or TSV output from run B")
    ptk = sub.add_parser("task", parents=[common], help="prepare briefs and mark task windows")
    tksub = ptk.add_subparsers(dest="task_command", required=True, parser_class=_Parser)
    tkboard = tksub.add_parser("board", parents=[common], help="list tasks from the project's task records")
    add_json_format(tkboard, "task board")
    tkboard.add_argument("--now", metavar="TIME", help="evaluate staleness at this time (ISO 8601 with its zone)")
    tkb = tksub.add_parser("brief", parents=[common], help="turn a task file into a self-contained prompt for an agent")
    tkb.add_argument("task", type=Path)
    tkb.add_argument("--for", dest="agent", choices=["codex", "gemini", "claude", "generic"], default="generic")
    tkb.add_argument("--output", type=Path, metavar="FILE")
    tkx = tksub.add_parser("dispatch", parents=[common],
                           help="run a task's brief with Codex or Antigravity, headless, and keep the report (0.20.4)")
    tkx.add_argument("task", type=Path)
    tkx.add_argument("--to", dest="agent", required=True, choices=["codex", "antigravity", "auto"],
                     help="auto (0.23.0): the first available worker of [delegation] that has a headless dispatch")
    tkx.add_argument("--implement", action="store_true",
                     help="let it change files (in a checkout of its own; nothing is committed); default: a review")
    tkx.add_argument("--inline", action="store_true",
                     help="put the task's documents in the prompt and ask for text only (when tools are refused)")
    tkx.add_argument("--model", help="the agent's model (Antigravity default: gemini-4-neon-high)")
    tkx.add_argument("--output", type=Path, metavar="FILE", help="where the report goes (default .steward/dispatch/)")
    tkx.add_argument("--dry-run", action="store_true", help="print what would run; run nothing")
    tkt = tksub.add_parser("template", parents=[common], help="print a brief template (review, literature-review, …)")
    tkt.add_argument("name", nargs="?")
    tkt.add_argument("--output", type=Path, metavar="FILE", help="write it there (folders are made)")
    tks = tksub.add_parser("start", parents=[common], help="open a window for token reporting")
    tks.add_argument("id")
    tks.add_argument("--session", help="count only this session ID for the window")
    tkd = tksub.add_parser("done", parents=[common], help="close a token reporting window")
    tkd.add_argument("id")

    pto = sub.add_parser("tokens", parents=[common], help="read usage from selected local agent logs")
    tosub = pto.add_subparsers(dest="tokens_command", required=True, parser_class=_Parser)
    toe = tosub.add_parser("check", parents=[common], help="show usage against the task budget")
    torch = toe.add_mutually_exclusive_group()
    torch.add_argument("--claude-hook", action="store_true", help="read Claude Code hook JSON from stdin")
    torch.add_argument("--claude-statusline", action="store_true", help="read Claude Code status line JSON from stdin")
    tor = tosub.add_parser("report", parents=[common], help="show task totals and the largest tool outputs")
    tor.add_argument("--since", help="count events from this date (YYYY-MM-DD, UTC)")
    toformat = tor.add_mutually_exclusive_group()
    add_json_options(tor, "tokens report", exclusive=toformat)
    toformat.add_argument("--svg", action="store_true", help="print the chart alone to stdout")
    for action in (toe, tor):
        action.add_argument("--task", metavar="ID")
        for agent in ("claude", "codex", "gemini"):
            action.add_argument(f"--{agent}", action="append", type=Path, metavar="FILE", default=[],
                                help=f"read this {agent} session log (may be repeated)")
    ppn = sub.add_parser("pins", parents=[common], help="pinned dependencies: deprecate, retire (keep the artifact), restore (0.17.0)")
    pnsub = ppn.add_subparsers(dest="pins_command", required=True, parser_class=_Parser)
    pns = pnsub.add_parser("status", parents=[common], help="each pin's state and why, and the object a retirement approval signs")
    add_json_options(pns, "pins status")
    pnr = pnsub.add_parser("retire", parents=[common], help="keep the artifact, drop the install (needs a signed pin.retire approval)")
    pnr.add_argument("name")
    pnr.add_argument("--authorization", metavar="TAG", help="the signed steward/auth/… tag for this pin's plan")
    pnr.add_argument("--resume", action="store_true", help="finish an interrupted retirement of the same recorded plan")
    pno = pnsub.add_parser("restore", parents=[common], help="reinstall a retired pin from its kept artifact and run its check")
    pno.add_argument("name")

    pau = sub.add_parser("audit", parents=[common], help="read-only evidence for audits (0.14.0)")
    ausub = pau.add_subparsers(dest="audit_command", required=True, parser_class=_Parser)
    aup = ausub.add_parser("progress", parents=[common],
                           help="the Progress Audit's evidence: where we are, use by other projects, pending work, reach")
    add_json_options(aup, "audit progress")

    ppl = sub.add_parser("plans", parents=[common], help="project plans, progress and drift")
    add_json_format(ppl, "plans")
    ptl = sub.add_parser("timeline", parents=[common],
                         help="milestone deadlines and progress, with plan drift in versioned JSON")
    add_json_options(ptl, "timeline")
    for action in ptl._actions:  # 0.24.0 (P02): `--events --format svg` draws the schedule
        if "--format" in action.option_strings:
            action.choices = ["text", "json", "svg"]
            action.help = "print text or versioned JSON; with --events, svg draws the schedule"
    ptl.add_argument("--now", metavar="TIME", help="evaluate at this time (ISO 8601 with its zone), to reproduce a state")
    ptl.add_argument("--events", action="store_true",
                     help="every dated record on one time axis: milestones, decisions, releases, papers, reviews, "
                          "research records, sprints and their tasks")
    ptl.add_argument("--all-projects", action="store_true",
                     help="with --events: add the projects the exchange names that are present on disk")
    pde = sub.add_parser("decisions", parents=[common], help="recorded decisions and open questions with their options")
    pde.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")

    # 0.21.0 (W03; STW-048 C10, C12; C21): where the project stands, what is stale, and one feed of what changed
    pnx = sub.add_parser("next", parents=[common],
                         help="where you left off, what changed since, the next milestone, what waits on you and on "
                              "agents, what to tidy")
    pnx.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")
    pnx.add_argument("--now", metavar="TIME", help="evaluate at this time (ISO 8601 with its zone)")
    pnx.add_argument("--brief", action="store_true", help="a short text for an agent starting a session")
    pty = sub.add_parser("tidy", parents=[common],
                         help="stale tasks, pages, exchange items, leftovers and memory (read-only; --archive moves tasks)")
    pty.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")
    pty.add_argument("--now", metavar="TIME", help="evaluate at this time (ISO 8601 with its zone)")
    pty.add_argument("--archive", nargs="+", metavar="ID", help="move these task files to [tidy] archive (the owner's step)")
    pnt = sub.add_parser("notifications", parents=[common],
                         help="one feed: CLI releases, exchange items, sprint tasks, approvals, gates, milestones")
    pnt.add_argument("--format", choices=["text", "json"], default="text", help="print text or versioned JSON")
    pnt.add_argument("--now", metavar="TIME", help="evaluate at this time (ISO 8601 with its zone)")
    pnt.add_argument("--days", type=int, default=14, metavar="N",
                     help="finished and failed sprint tasks of the last N days (default 14)")
    pnt.add_argument("--against", type=Path, metavar="REPORT",
                     help="an earlier check report: name each gate that has turned not eligible since (runs a check)")

    pst = sub.add_parser("storage", parents=[common], help="large artifacts by hash; resource audit (v0.8)")
    ssub = pst.add_subparsers(dest="storage_command", required=True, parser_class=_Parser)
    sr = ssub.add_parser("record", parents=[common], help="hash a file and write its entry in the artifact registry")
    sr.add_argument("path")
    sr.add_argument("--retrieval", required=True, help='how to get it back, e.g. "dvc pull PATH" or a URL')
    sr.add_argument("--tool", choices=["dvc", "datalad", "manual"], default="manual")
    sv = ssub.add_parser("verify", parents=[common], help="compare registered artifacts with what is present")
    add_json_options(sv, "storage verify")
    sa = ssub.add_parser("audit", parents=[common], help="directory sizes against [storage.caps]; largest untracked files (read-only)")
    add_json_options(sa, "storage audit")
    sa.add_argument("--top", type=int, default=10)
    ssc = ssub.add_parser("scan", parents=[common],
                          help="read-only: this project's temporary storage on every disk, its size and who else uses it")
    add_json_options(ssc, "storage scan")
    scl = ssub.add_parser("clean", parents=[common], help="plan a cleanup (--plan), then apply it (--apply PLAN), asking per location")
    scg = scl.add_mutually_exclusive_group(required=True)
    scg.add_argument("--plan", action="store_true", help="write a plan of the cleanable candidates; deletes nothing")
    scg.add_argument("--apply", type=Path, metavar="PLAN", help="check each planned location again, ask, delete, record")
    scl.add_argument("--class", dest="classes", action="append", choices=["toolkit", "python", "docs", "declared", "linked"],
                     help="classes to plan (default: toolkit, python, docs, declared; linked only when named)")

    sub.add_parser("mcp", parents=[common], help="optional MCP server over stdio (read-only tools; v0.8)")
    pex = sub.add_parser("exchange", parents=[common], help="requests and feedback between projects (constitution Article V)")
    xsub = pex.add_subparsers(dest="exchange_command", required=True, parser_class=_Parser)
    xsub.add_parser("init", parents=[common], help="create the exchange/ folder")
    xn = xsub.add_parser("new", parents=[common], help="file a new item in outbox/ (or oneway/)")
    xn.add_argument("kind", choices=["request", "defect", "feedback", "question"])
    xn.add_argument("--to", required=True, help="the receiving project's code")
    xn.add_argument("--title", required=True)
    xn.add_argument("--against", help="the tagged version tested")
    xn.add_argument("--priority", choices=["low", "medium", "high"])
    xn.add_argument("--oneway", action="store_true", help="the receiver does not run Bio-STEWARD (one-way protocol)")
    xn.add_argument("--channel", help="one-way: how it is sent (an issue URL, an email)")
    xs = xsub.add_parser("state", parents=[common], help="record a state change in the exchange ledger")
    xs.add_argument("id")
    xs.add_argument("state")
    xs.add_argument("--note", help="the version, reason, target ID or evidence the state needs")
    xs.add_argument("--by", metavar="ID", help="superseded: the received item that replaces this one (FB-018)")
    xr = xsub.add_parser("receive", parents=[common], help="take one peer item into inbox/ (read-only on the peer)")
    xr.add_argument("path", type=Path)
    xr.add_argument("--allow-terms", action="store_true",
                    help="receive an item that hits this project's R-07 term lists (refused by default; FB-018)")
    xp = xsub.add_parser("pull", parents=[common], help="take items addressed here from eligible peers' committed outboxes")
    xp.add_argument("peer", nargs="?", help="one peer code (default: all declared and discovered peers)")
    xp.add_argument("--allow-terms", action="store_true",
                    help="receive items that hit this project's R-07 term lists (refused by default; FB-018)")
    xrs = xsub.add_parser("respond", parents=[common], help="write a response to an inbox item and record its state")
    xrs.add_argument("id")
    xrs.add_argument("state")
    xrs.add_argument("--note", required=True, help="the decision, with its version, reason, target ID or evidence")
    xrs.add_argument("--by", metavar="ID", help="superseded: the received item that replaces this one (FB-018)")
    xan = xsub.add_parser("announce", parents=[common], help="write a release notice for every declared consumer")
    xan.add_argument("tag", help="the release tag, e.g. v1.2.0")
    xan.add_argument("--previous", help="the previous release tag")
    xan.add_argument("--breaking", action="store_true", help="the release has breaking changes")
    xan.add_argument("--changelog", default="CHANGELOG.md")
    xst = xsub.add_parser("status", parents=[common], help="every item with its place and state")
    add_json_options(xst, "exchange status")
    xst.add_argument("--fetch", action="store_true", help="also fetch peers declared by a git URL (network)")
    xe = xsub.add_parser("export", parents=[common], help="a plain copy of a one-way item, to paste into another tracker")
    xe.add_argument("id")
    issue = sub.add_parser("issue", parents=[common], help="file a toolkit defect in the exchange outbox")
    source = issue.add_mutually_exclusive_group(required=True)
    source.add_argument("description", nargs="?", help="a toolkit problem described in generic terms")
    source.add_argument("--from-last-error", action="store_true", help="report the last local toolkit fault")
    issues = sub.add_parser("issues", parents=[common], help="read toolkit defect reports received through exchange")
    inbox = issues.add_subparsers(dest="issues_command", required=True, parser_class=_Parser)
    add_json_format(inbox.add_parser("inbox", parents=[common], help="group received reports by fingerprint"),
                    "issues inbox")
    pco = sub.add_parser("constitution", parents=[common], help="print the Bio-STEWARD constitution (C-1)")
    pco.add_argument("--version", action="store_true", dest="const_version", help="print its version only")
    pco.add_argument("--changes", action="store_true", help="print its version history")

    ph = sub.add_parser("hooks", parents=[common], help="git hooks")
    hsub = ph.add_subparsers(dest="hooks_command", required=True, parser_class=_Parser)
    hi = hsub.add_parser("install", parents=[common], help="pre-commit (blocks on FAIL) and pre-push (protected branches, gate)")
    hi.add_argument("--force", action="store_true", help="replace existing hooks")
    hi.add_argument("--gate", default="default")
    hi.add_argument("--dry-run", action="store_true", help="print the hooks and the protected branches; write nothing")
    hi.add_argument("--protect", nargs="*", metavar="BRANCH", help="protected branches (default: [release] protected)")
    hi.add_argument("--chain", action="store_true",
                    help="keep an existing hook (also a symlink) as NAME.local and run it before steward's")
    hsub.add_parser("remove", parents=[common], help="remove steward's hooks; restore chained originals")
    hi.add_argument("--unconfigured", choices=["skip", "refuse"], default="skip",
                    help="a pushed commit without steward.toml: skip with a notice (default) or refuse")
    hr = hsub.add_parser("run", help="the hooks' entry point (called by the installed scripts)")
    hr.add_argument("hook", choices=["pre-commit", "pre-push"])
    hr.add_argument("--gate", default="default")
    hr.add_argument("--unconfigured", choices=["skip", "refuse"], default="skip")
    hr.add_argument("--protect", action="append", default=[])
    hr.add_argument("remote", nargs="*", help="(pre-push) the remote name and URL git passes")

    pl = sub.add_parser("ledger", parents=[common], help="ledger maintenance")
    lsub = pl.add_subparsers(dest="ledger_command", required=True, parser_class=_Parser)
    lr = lsub.add_parser("recover", parents=[common], help="quarantine a torn tail (never deletes) and record it")
    lr.add_argument("path", type=Path)

    pa = sub.add_parser("authorize", parents=[common], help="signed human authorizations (git tags signed with SSH keys)")
    asub = pa.add_subparsers(dest="auth_command", required=True, parser_class=_Parser)
    ap = asub.add_parser("prepare", parents=[common], help="write a payload for the human to read and sign")
    ap.add_argument("action")
    ap.add_argument("--object", help="a file or sha256:<hex>; policy.change defaults to the object R-33 checks")
    ap.add_argument("--scope", default="-")
    ap.add_argument("--budget", default="none")
    ap.add_argument("--expires", required=True, help="YYYY-MM-DDTHH:MM:SSZ (UTC)")
    ap.add_argument("--summary", default="", help="what is being approved, in words")
    asg = asub.add_parser("sign", parents=[common], help="sign a prepared payload with git tag -s (the key prompt is the human step)")
    asg.add_argument("nonce")
    asg.add_argument("--expect-sha256", metavar="HASH",
                     help="sign only if the payload's bytes still have this SHA-256 (the payload_sha256 that "
                          "`authorize pending --format json` reports); otherwise refuse and sign nothing")
    av = asub.add_parser("verify", parents=[common], help="verify a signed authorization tag")
    av.add_argument("tag")
    av.add_argument("--action")
    av.add_argument("--object", help="recompute and require this object (file or sha256:)")
    als = asub.add_parser("list", parents=[common], help="list authorization and anchor tags with their status")
    add_json_format(als, "authorize list")
    apd = asub.add_parser("pending", parents=[common], help="list prepared payloads waiting for a signature (deferred signing)")
    add_json_format(apd, "authorize pending")
    apd.add_argument("--all-projects", action="store_true", help="also the peers declared in [exchange] peers (read-only)")
    asp = asub.add_parser("sign-pending", parents=[common],
                          help="show and sign each waiting payload in one sitting (the key prompt is the human step)")
    asp.add_argument("--all-projects", action="store_true", help="also the peers declared in [exchange] peers")
    asp.add_argument("--yes", action="store_true", help="do not ask before each signature (the key may still prompt)")
    aks = asub.add_parser("keys", parents=[common], help="signers at the baseline and their key types")
    add_json_format(aks, "authorize keys")
    aa = asub.add_parser("anchor", parents=[common], help="prepare an anchor payload for a ledger head")
    aa.add_argument("ledger", choices=["runs", "authorizations", "spend", "integrity"])
    apn = asub.add_parser("pin", parents=[common], help="pin this repository's trust root in your per-user trust.toml")
    apn.add_argument("--baseline", help="baseline ref to pin (default: [policy] baseline)")
    aa.add_argument("--expires", default="2099-12-31T23:59:59Z")

    ps_ = sub.add_parser("spend", parents=[common], help="spend guard for paid calls")
    ssub = ps_.add_subparsers(dest="spend_command", required=True, parser_class=_Parser)
    sc = ssub.add_parser("check", parents=[common], help="check a planned call and record its estimate")
    sc.add_argument("model")
    sc.add_argument("tokens_in", type=int)
    sc.add_argument("tokens_out", type=int)
    sc.add_argument("--authorization", required=True, metavar="TAG")
    sc.add_argument("--task", help="the task this call serves (must match task= in the authorization's scope, if set)")
    sr = ssub.add_parser("record", parents=[common], help="record actual usage for a call id")
    sr.add_argument("call")
    sr.add_argument("tokens_in", type=int)
    sr.add_argument("tokens_out", type=int)
    sr.add_argument("--request-id")
    sps = ssub.add_parser("status", parents=[common], help="totals against the cap")
    add_json_format(sps, "spend status")

    pf = sub.add_parser("freeze", parents=[common], help="freeze protocol files, cohorts and parameters (signed if confirmatory)")
    pf.add_argument("name")
    pf.add_argument("--files", nargs="*", default=[], metavar="PATH")
    pf.add_argument("--cohort", nargs="*", default=[], metavar="IDS_FILE")
    pf.add_argument("--params", metavar="FILE", help="confirmatory parameters (.toml or .json)")
    pf.add_argument("--contract", metavar="ID")
    pf.add_argument("--authorization", metavar="TAG", help="freeze.confirmatory authorization (confirmatory contracts)")
    pf.add_argument("--decision", help="the DECISIONS.md entry that approves it (heading text)")
    pf.add_argument("--dry-run", action="store_true", help="print the snapshot hash to authorize; record nothing")
    pam = sub.add_parser("amend", parents=[common], help="propose or apply an amendment to a frozen set")
    amsub = pam.add_subparsers(dest="amend_command", required=True, parser_class=_Parser)
    amp = amsub.add_parser("propose", parents=[common])
    amp.add_argument("name")
    amp.add_argument("--reason", required=True)
    ama = amsub.add_parser("apply", parents=[common])
    ama.add_argument("name")
    ama.add_argument("--authorization", required=True, metavar="TAG")
    ama.add_argument("--decision", required=True)
    pse = sub.add_parser("seal", parents=[common], help="seal a dataset declared in datasets.toml")
    pse.add_argument("dataset")
    pun = sub.add_parser("unseal", parents=[common], help="unseal a dataset with a signed authorization (role becomes spent)")
    pun.add_argument("dataset")
    pun.add_argument("--authorization", required=True, metavar="TAG")
    pun.add_argument("--decision", required=True)
    pin = sub.add_parser("integrity", parents=[common], help="integrity status")
    insub = pin.add_subparsers(dest="integrity_command", required=True, parser_class=_Parser)
    ins = insub.add_parser("status", parents=[common])
    add_json_format(ins, "integrity status")
    iac = insub.add_parser("access", parents=[common], help="may a consumer use a dataset for develop, confirm or metadata?")
    iac.add_argument("dataset")
    iac.add_argument("--consumer", required=True, help="the study or paper ID")
    iac.add_argument("--use", required=True, choices=["develop", "confirm", "metadata"])

    pt = sub.add_parser("talk", parents=[common], help="PresentationKit helpers")
    tsub = pt.add_subparsers(dest="talk_command", required=True, parser_class=_Parser)
    tp = tsub.add_parser("plan", parents=[common], help="missing fields, suggested pattern and outline, stage ceiling")
    tp.add_argument("name", nargs="?")
    add_json_format(tp, "talk plan", write_option="--write-outline")
    tp.add_argument("--write-outline", action="store_true", help="append the suggested [[outline]] if the plan has none")
    tv = tsub.add_parser("values", parents=[common], help="Quarto: write _variables.yml from the linked paper's registry")
    tv.add_argument("name", nargs="?")
    tv.add_argument("--write", action="store_true")
    te = tsub.add_parser("export", parents=[common], help="Keynote: export the .key file to PDF (macOS; opens Keynote)")
    te.add_argument("name", nargs="?")
    tf = tsub.add_parser("prefs", parents=[common], help="show resolved preferences, or set one (explicit write)")
    tf.add_argument("name", nargs="?")
    tf.add_argument("--compact", action="store_true", help="only keys that differ from the defaults")
    add_json_format(tf, "talk prefs", write_option="--set")
    tf.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="write a style key (e.g. style.density sparse)")
    tf.add_argument("--layer", default="project", help="global | project | context:NAME (with --set)")

    pr = sub.add_parser("report", parents=[common], help="render an existing JSON report")
    pr.add_argument("file", help="report JSON file, or - for stdin")
    pr.add_argument("--format", choices=["md", "text", "summary"], default=None)
    pr.add_argument("--rule", metavar="R-xx", help="show only this rule's results (summary and gates unchanged)")
    pr.add_argument("--subject", metavar="PATH", help="show only results for this subject")
    pr.add_argument("--output", type=Path, metavar="FILE")
    return p


def main(argv: list[str] | None = None) -> int:
    used: set[str] = set()
    token = _used_options.set(used)
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        write_option = getattr(args, "json_write_option", None)
        if write_option and args.format == "json" and getattr(args, write_option[2:].replace("-", "_")):
            parser.error(f"--format json cannot be used with {write_option}")
    except SystemExit as e:  # usage errors (64), --help and --version (0)
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    finally:
        _used_options.reset(token)
    from .issues import FaultHint

    subcommand = getattr(args, subcommand_dest(args.command), None)
    name = f"{args.command} {subcommand}" if subcommand else args.command
    args.fault_hint = FaultHint(getattr(args, "repo", None), name, sorted(used))
    overlay = getattr(args, "config_overlay", None)
    if overlay is None:
        return _dispatch(args)
    before = os.environ.get("STEWARD_CONFIG_OVERLAY")
    os.environ["STEWARD_CONFIG_OVERLAY"] = overlay  # for this command only
    try:
        return _dispatch(args)
    finally:
        if before is None:
            os.environ.pop("STEWARD_CONFIG_OVERLAY", None)
        else:
            os.environ["STEWARD_CONFIG_OVERLAY"] = before


def _dispatch(args: argparse.Namespace) -> int:
    try:
        if args.command == "interface":
            write_document(describe())
            return EXIT_OK
        if args.command == "upgrade":
            from .upgrade import command

            return command(args)
        if args.command == "init":
            return cmd_init(args)
        if args.command == "check":
            return cmd_check(args)
        if args.command == "explain":
            return cmd_explain(args)
        if args.command == "skills":
            return cmd_skills(args)
        if args.command in ("freeze", "amend", "seal", "unseal", "integrity"):
            return cmd_integrity(args)
        if args.command == "spend":
            return cmd_spend(args)
        if args.command == "authorize":
            return cmd_authorize(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "hooks":
            return cmd_hooks(args)
        if args.command == "release" and args.release_command in ("publish", "status", "setup", "go-public"):
            from . import cli_research as cr

            return cr.cmd_publish(args)
        if args.command == "release":
            return cmd_release(args)
        if args.command == "benchmark":
            return cmd_benchmark(args)
        if args.command == "repro":
            return cmd_repro(args)
        if args.command == "session":
            return cmd_session(args)
        if args.command == "agents":
            return cmd_agents(args)
        if args.command == "docs":
            return cmd_docs(args)
        if args.command == "stage":
            return cmd_stage(args)
        if args.command == "frozen":
            return cmd_frozen(args)
        if args.command == "shards":
            return cmd_shards(args)
        if args.command == "storage":
            return cmd_storage(args)
        if args.command == "plans":
            return cmd_plans(args)
        if args.command == "timeline":
            return cmd_timeline(args)
        if args.command == "decisions":
            return cmd_decisions(args)
        if args.command in ("next", "tidy", "notifications"):
            return cmd_cockpit(args)
        if args.command == "sprint":
            return cmd_sprint(args)
        if args.command == "audit":
            return cmd_audit(args)
        if args.command == "pins":
            return cmd_pins(args)
        if args.command == "tokens" or (args.command == "task" and args.task_command in ("start", "done")):
            from . import tokens

            return tokens.command(args)
        if args.command == "example":
            from . import cli_research as cr

            return cr.cmd_example(args)
        if args.command == "stranger-test":
            from . import cli_research as cr

            return cr.cmd_stranger(args)
        if args.command in ("study", "research", "task", "licence", "channel", "data"):
            from . import cli_research as cr

            return {"study": cr.cmd_study, "research": cr.cmd_research, "task": cr.cmd_task,
                    "licence": cr.cmd_licence, "channel": cr.cmd_channel, "data": cr.cmd_data}[args.command](args)
        if args.command == "compare":
            from .compare import command

            return command(args)
        if args.command == "exchange":
            return cmd_exchange(args)
        if args.command in ("issue", "issues"):
            return cmd_issues(args)
        if args.command == "constitution":
            from .resources import CONSTITUTION_VERSION, constitution_text

            text = constitution_text()
            if args.const_version:
                print(CONSTITUTION_VERSION)
            elif args.changes:
                print(text.split("Version history:", 1)[-1].strip())
            else:
                sys.stdout.write(text)
            return EXIT_OK
        if args.command == "mcp":
            from . import mcp

            return mcp.main(_require_root(args))
        if args.command == "diff":
            return cmd_diff(args)
        if args.command == "ledger":
            return cmd_ledger_recover(args)
        if args.command == "talk":
            return {"plan": cmd_talk_plan, "prefs": cmd_talk_prefs, "values": cmd_talk_values,
                    "export": cmd_talk_export}[args.talk_command](args)
        if args.command == "paper":
            from .cli_research import cmd_paper_citations

            return {"values": cmd_paper_values, "displays": cmd_paper_displays, "citations": cmd_paper_citations,
                    "manifest": cmd_paper_manifest}[args.paper_command](args)
        return cmd_report(args)
    except NotConfigured as e:
        return _not_configured(args, e)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # a crash of the tool itself (per-rule errors are already UNKNOWN results)
        print(f"steward: internal error ({type(e).__name__})", file=sys.stderr)
        args.fault_hint(EXIT_SOFTWARE, e)
        return EXIT_SOFTWARE


def cmd_init(args: argparse.Namespace) -> int:
    if args.format == "json" and not args.dry_run:
        print("steward: --format json prints a plan; use it with --dry-run", file=sys.stderr)
        return EXIT_USAGE
    root = (args.repo or Path.cwd()).resolve()
    if not root.is_dir():
        print(f"steward: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    skills = None
    if args.skills:
        skills = [d if d.is_absolute() else root / d for d in args.skills]
        if len(skills) > 1 and not all(d.resolve().is_relative_to(root) for d in skills):
            print("steward: with several --skills directories, each must be inside the repository", file=sys.stderr)
            return EXIT_USAGE
    if args.paper is not None and not re.match(r"^[a-z][a-z0-9_-]{0,31}$", args.paper):
        print("steward: paper NAME must match [a-z][a-z0-9_-]{0,31}", file=sys.stderr)
        return EXIT_USAGE
    from .init import bundles

    goals = args.goals or []
    if (goals or args.paper is not None) and (root / "steward.toml").is_symlink():  # AF18, AO3: before anything
        print("steward: steward.toml is a link; nothing was set up", file=sys.stderr)
        return EXIT_DATAERR
    if "paper" in goals and args.paper is None:
        args.paper = "main"
    kits = args.kits.split(",") if args.kits else (["core", "paper"] if args.paper is not None else ["core"])
    if not args.kits:
        kits += [k for g in goals for k in GOALS[g]["kits"] if k not in kits]
    unknown = [k for k in kits if k not in bundles()]
    if unknown:
        print(f"steward: unknown kit(s) {', '.join(unknown)}; choose from {', '.join(bundles())}", file=sys.stderr)
        return EXIT_USAGE
    if args.talk is not None and not re.match(r"^[a-z][a-z0-9_-]{0,31}$", args.talk):
        print("steward: talk NAME must match [a-z][a-z0-9_-]{0,31}", file=sys.stderr)
        return EXIT_USAGE
    if args.talk is not None and not args.kits:
        kits = kits + ["talk"]
    templates = [t.strip() for t in (args.templates or "").split(",") if t.strip()]
    templates += [t for g in goals for t in GOALS[g]["templates"] if t not in templates]
    bad = [t for t in templates if t not in ("contract", "prior-work")]
    if bad:
        print(f"steward: unknown template(s) {bad}; choose from contract, prior-work", file=sys.stderr)
        return EXIT_USAGE
    acts = plan(root, args.profile, args.agents_md, skills, paper=args.paper, kits=kits, talk=args.talk,
                project=args.project, templates=templates)
    if args.format == "json":  # C7: the plan only; the paths are the repository's, never the toolkit's own
        write_document({
            "schema": "steward.init_plan/0.1", "tool_version": __version__, "dry_run": True,
            "profile": args.profile, "kits": kits, "goals": goals, "templates": templates,
            "actions": [{"verb": a.verb, "path": a.path, "note": a.note,
                         **({"content": a.content} if a.verb == "print" else {})} for a in acts],
            "tables": _planned_tables(root, acts, goals, args.paper),
            "next": _init_next(goals),
        })
        return EXIT_OK
    for a in acts:
        print(a.line(args.dry_run))
        if a.verb == "print":
            print(a.content)
    if args.dry_run:
        return EXIT_OK
    try:
        apply(root, acts, skills)
    except OSError as e:
        print(f"steward: cannot write: {e}", file=sys.stderr)
        return EXIT_CANTCREAT
    try:  # V5 (0.14.0): a new project is in the machine registry from the start (opt-out as for check)
        from . import cleanup as _cu
        from .models import load_config as _lc

        _cu.register(root, _lc(root))
    except Exception:  # noqa: BLE001 - registration never fails init
        pass
    if goals and (root / "steward.toml").is_symlink():  # AF18: never extended through a link
        print("steward: steward.toml is a link; the goal tables were not added", file=sys.stderr)
        return EXIT_DATAERR
    added = _goal_tables(root, goals)
    if args.paper is not None:  # 0.20.1 (STW-033): an existing steward.toml gains the paper's table too
        added += _paper_table(root, args.paper)
    for t in added:
        print(f"append         steward.toml  [{t}]")
    print("Next:\n" + "\n".join(f"  {i}. {st}" for i, st in enumerate(_init_next(goals), start=1)))
    return _offer_delegation(args, root)


def _offer_delegation(args: argparse.Namespace, root: Path) -> int:
    """0.23.0 (STW-061 D01): steward init offers `steward agents setup` when an agent CLI is installed and steward.toml
    has no [delegation]. In a terminal it asks; the setup then shows its diff and asks again before writing."""
    from . import delegation as dg

    try:
        cfg = _models.load_config(root)
    except Exception:  # noqa: BLE001 - the offer never fails init
        return EXIT_OK
    if cfg.delegation is not None or not any(dg.locate(n)[0] for n in dg.ORDER):
        return EXIT_OK
    print("Delegation: `steward agents setup` finds claude, codex and agy, and writes [delegation] (the master and "
          "the workers) after you confirm.")
    if not sys.stdin.isatty():
        return EXIT_OK
    try:
        answer = input("Set up delegation now? [y/N] ")
    except EOFError:
        answer = ""
        print()
    if answer.strip().lower() not in ("y", "yes"):
        return EXIT_OK
    return _agents_setup(argparse.Namespace(yes=False, master=None), root, cfg)


def _planned_tables(root: Path, acts: list[Any], goals: list[str], paper: str | None) -> list[str]:
    """The steward.toml tables a real run would append after its plan (C7): computed, never written."""
    from .records import RecordRefused, read_rel

    made = next((a.content for a in acts if a.verb == "create" and a.path == "steward.toml"), None)
    if made is None:
        try:
            made = read_rel(root, "steward.toml").decode("utf-8")
        except (RecordRefused, ValueError, OSError):
            return []
    tables = _goal_tables(root, goals, planned=made)
    return tables + (_paper_table(root, paper, planned=made) if paper is not None else [])


def _init_next(goals: list[str]) -> list[str]:
    steps = [st for g in goals for st in GOALS[g]["next"]] or [
        "steward init --for benchmark|reanalysis|paper|agents|licence   (pick what you do; repeatable)",
        "steward check --summary",
        "ask your coding agent: \"Run the using-steward skill.\""]
    return list(dict.fromkeys(steps))


GOALS: dict[str, dict[str, Any]] = {  # 0.19.0 (STW-006): what a goal needs, and the first commands to run
    "benchmark": {"kits": ["core"], "templates": ["contract", "prior-work"], "tables": {},
                  "next": ["mkdir -p benchmarks && cp development/templates/benchmark.contract.toml benchmarks/my.contract.toml",
                           "edit its datasets, splits (with the group: donor, patient, study), baselines and metrics",
                           "steward check contract benchmark --summary"]},
    "reanalysis": {"kits": ["core", "research"], "templates": [],
                   "tables": {"studies": "[studies]\ndir = \"development/studies\"\n",
                              "research": "[research]\ndir = \"development/research\"\n"},
                   "next": ["steward study new my-study --title \"…\" --kind reanalysis",
                            "steward study add-input my-study --source GEO --accession GSE… --file data/…",
                            "steward check studies --summary"]},
    "paper": {"kits": ["core", "paper"], "templates": [], "tables": {},
              "next": ["steward paper values --write", "steward check paper --summary"]},
    "agents": {"kits": ["core"], "templates": [],
               "tables": {"run": "[run]\n", "agents": "[agents]\n"},
               "next": ["steward run --wall 3600 --mem 8000 --hang-cpu 600 -- python your_job.py",
                        "steward task template review --output development/tasks/T-001.md && steward task brief development/tasks/T-001.md --for codex",
                        "steward tokens report"]},
    "licence": {"kits": ["core", "licence"], "templates": [], "tables": {"licence": None},
                "next": ["steward licence inventory", "steward check licence --summary"]},
}


def _goal_tables(root: Path, goals: list[str], planned: str | None = None) -> list[str]:
    """Append the tables the goals need to steward.toml, never one that is already there. With `planned` (the
    steward.toml text a dry run would leave), only name the tables that would be appended (C7)."""
    import tomllib

    from .fsutil import safe_write
    from .records import RecordRefused, read_rel

    try:  # AF18: read and written inside the repository, never through a link
        current = planned if planned is not None else read_rel(root, "steward.toml").decode("utf-8")
        have = set(tomllib.loads(current))
    except (RecordRefused, ValueError) as e:
        print(f"steward: steward.toml cannot be extended ({e}); nothing appended", file=sys.stderr)
        return []
    added, text = [], ""
    for g in goals:
        for name, body in GOALS[g]["tables"].items():
            if name in have or name in added:
                continue
            if name == "licence":  # declared from LICENSE when it can be identified; otherwise say how
                from . import licence as li

                lic = None
                for f in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING"):
                    try:
                        lic = li.identify_licence_text(read_rel(root, f).decode("utf-8", errors="replace"))
                        break
                    except RecordRefused:
                        continue
                if lic is None:
                    print("note: no identifiable LICENSE: add [licence] declared = \"SPDX-ID\" to steward.toml yourself",
                          file=sys.stderr if planned is not None else sys.stdout)
                    continue
                body = f'[licence]\ndeclared = "{lic}"\ndistribution = "internal"\n'
            text += "\n" + body
            added.append(name)
    if text and planned is None:
        safe_write(root, "steward.toml", (current + text).encode("utf-8"))
    return added


def _paper_table(root: Path, name: str, planned: str | None = None) -> list[str]:
    import tomllib

    from .fsutil import safe_write
    from .init import paper_block
    from .records import RecordRefused, read_rel

    try:
        current = planned if planned is not None else read_rel(root, "steward.toml").decode("utf-8")
        papers = tomllib.loads(current).get("paper") or {}
    except (RecordRefused, ValueError) as e:
        print(f"steward: steward.toml cannot be extended ({e}); add [paper.{name}] yourself", file=sys.stderr)
        return []
    if name in papers:
        return []
    if planned is None:
        safe_write(root, "steward.toml", (current.rstrip("\n") + "\n" + paper_block(name)).encode("utf-8"))
    return [f"paper.{name}"]


@functools.lru_cache(maxsize=1)
def _toolkit_modules() -> list[tuple[str, str]]:
    """(module_name, source) for every toolkit module that can emit result codes (excludes documentation tables)."""
    import pkgutil

    import steward

    out: list[tuple[str, str]] = []
    for m in pkgutil.iter_modules(steward.__path__):
        if m.name in ("code_docs", "rule_docs"):
            continue
        p = Path(steward.__file__).parent / f"{m.name}.py"
        if p.is_file():
            out.append((m.name, p.read_text(encoding="utf-8")))
    return out


@functools.lru_cache(maxsize=1)
def _toolkit_source() -> str:
    return "\n".join(src for _, src in _toolkit_modules())


@functools.lru_cache(maxsize=1)
def _helper_codes() -> dict[str, dict[str, str]]:
    """STW-035 B4: AST extraction of local helper calls that construct `f"R-xx.{param}"` (handles nested calls)."""
    import ast

    per_rule: dict[str, dict[str, str]] = {}
    for _, text in _toolkit_modules():
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            helpers: dict[str, str] = {}
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef) and child is not node and child.args.args:
                    p0 = child.args.args[0].arg
                    for sub in ast.walk(child):
                        if isinstance(sub, ast.JoinedStr) and len(sub.values) >= 2:
                            v0, v1 = sub.values[0], sub.values[1]
                            if (isinstance(v0, ast.Constant) and isinstance(v0.value, str)
                                    and re.fullmatch(r"R-\d{2}\.", v0.value)
                                    and isinstance(v1, ast.FormattedValue)
                                    and isinstance(v1.value, ast.Name) and v1.value.id == p0):
                                helpers[child.name] = v0.value[:-1]
            if not helpers:
                continue
            for child in ast.walk(node):
                if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in helpers):
                    continue
                if not (child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str)):
                    continue
                suf = child.args[0].value
                if not re.fullmatch(r"[a-z0-9_]*[a-z0-9]", suf):
                    continue
                rule = helpers[child.func.id]
                code = f"{rule}.{suf}"
                bucket = per_rule.setdefault(rule, {})
                bucket.setdefault(code, "")
                for kw in child.keywords:
                    if kw.arg == "message" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if not bucket[code] and _remedy(kw.value.value):
                            bucket[code] = kw.value.value
    return per_rule


def code_fixes(rule: str) -> dict[str, str]:
    """Every result code a rule can emit, with its one-line description (0.10.0 review S9; STW-035 B4).
    Read from the whole toolkit's source (one source of truth):
    - literal codes (`"R-07.local_path"`), never a fragment that is completed at run time (`R-07.list_{…}`);
    - codes passed to a local helper that builds `f"R-xx.{code}"` (`bad("invalid")` in R-53);
    - the fixed sets the source builds from values (`rule_docs.DYNAMIC_CODES`).
    Each code gets its literal source remedy when one sits beside it, else its one-line description in `CODE_DOCS`."""
    from .code_docs import CODE_DOCS
    from .rule_docs import DYNAMIC_CODES

    text = _toolkit_source()
    r = re.escape(rule)
    found: dict[str, str] = {c: "" for c in DYNAMIC_CODES.get(rule, [])}
    for m in re.finditer(rf"(?<![\w-]){r}\.[a-z0-9_]*[a-z0-9](?![a-z0-9_{{])", text):
        found.setdefault(m.group(), "")
    for code, msg in _helper_codes().get(rule, {}).items():
        found.setdefault(code, "")
        if msg and not found[code]:
            found[code] = msg
    for m in re.finditer(rf"\"code\": \"({r}\.[a-z0-9_]+)\"(?:(?!\"code\")[^\n])*?\"message\": \"([^\"{{}}]+)\"", text):
        if m.group(1) in found and not found[m.group(1)] and _remedy(m.group(2)):
            found[m.group(1)] = m.group(2)
    for code in list(found):
        if not found[code] and code in CODE_DOCS:
            found[code] = CODE_DOCS[code]
    return dict(sorted(found.items()))


def _remedy(text: str) -> bool:
    """S9 (0.15.0): a whole sentence, not a fragment of a message completed at run time."""
    t = text.strip()
    return len(t.split()) >= 3 and t[:1].isalpha() and not text.startswith(" ") and not text.endswith(" ")


def rule_codes(rule: str) -> list[str]:
    """Every result code a rule can emit (see `code_fixes`)."""
    return list(code_fixes(rule))


def explain_entry(rule: str) -> dict[str, Any]:
    """What `steward explain` says about one rule, as data (C3; one source for the text and the JSON)."""
    from .report import NEXT
    from .rule_docs import RULE_DOCS
    from .rules import rule_area

    name, version = RULES[rule]
    d = RULE_DOCS[rule]
    area = rule_area(rule)
    return {
        "rule": rule, "name": name, "version": version, "area": area,
        "areas": [a for a, rs in AREAS.items() if rule in rs], "governance": d["scope"],
        "checks": d["checks"], "why": d["why"], "pass_does_not_mean": d["not"], "fix": NEXT.get(rule, "-"),
        "codes": [{"code": c, "fix": f or None} for c, f in code_fixes(rule).items()],
        "run": f"steward check {area} --summary",
    }


def _explain_text(e: dict[str, Any]) -> str:
    out = [f"{e['rule']} {e['name']} (version {e['version']}; area: {e['area']}; {e['governance']} governance)", "",
           f"Checks: {e['checks']}", f"Why: {e['why']}", f"A PASS does not mean: {e['pass_does_not_mean']}",
           f"Fix: {e['fix']}"]
    if e["codes"]:  # S9: each code with its own remedy where the source gives one
        out += ["", "Result codes:"] + [f"  {c['code']}" + (f": {c['fix']}" if c["fix"] else "") for c in e["codes"]]
    out += ["", f"Run it: {e['run']}   (details: steward report FILE --rule {e['rule']})"]
    return "\n".join(out)


def cmd_explain(args: argparse.Namespace) -> int:
    if args.all_rules == (args.rule is not None):
        print("steward: name one rule (e.g. steward explain R-42), or --all for every rule", file=sys.stderr)
        return EXIT_USAGE
    rules = sorted(RULES)
    if not args.all_rules:
        rule = args.rule.upper()
        if rule not in RULES:
            print(f"steward: no rule {args.rule}; rules are {min(RULES)} … {max(RULES)} (steward explain --all lists "
                  "them)", file=sys.stderr)
            return EXIT_USAGE
        rules = [rule]
    entries = [explain_entry(r) for r in rules]
    if args.format == "json":
        from . import __version__

        write_document({"schema": "steward.explain/0.1", "tool_version": __version__, "rules": entries})
    else:
        print("\n\n".join(_explain_text(e) for e in entries))
    return EXIT_OK


def _skill_description(path: Path) -> str:
    """The `description:` of a SKILL.md front matter."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---\n"):
        return ""
    for line in text[4:].split("\n---", 1)[0].splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


def skills_document(root: Path | None) -> dict[str, Any]:
    """C8 (0.21.0): the bundled skills by bundle and, in a project with [skills], the canonical directory and the
    state of each copy, from the code R-60 uses."""
    import tomllib

    from .process import skills_copies
    from .resources import skills_dir

    meta = tomllib.loads((skills_dir() / "BUNDLES.toml").read_text(encoding="utf-8"))
    bundles = [{"name": n, "budget_words": b.get("budget_words"), "skills": list(b["skills"])} for n, b in meta.items()]
    member: dict[str, list[str]] = {}
    for b in bundles:
        for sk in b["skills"]:
            member.setdefault(sk, []).append(b["name"])
    names = sorted(p.parent.name for p in skills_dir().glob("*/SKILL.md"))
    skills = [{"name": n, "bundles": member.get(n, []), "description": _skill_description(skills_dir() / n / "SKILL.md")}
              for n in names]
    project = None
    if root is not None:
        sc = _models.load_config(root).skills
        if sc is None:
            project = {"configured": False, "canonical": None, "canonical_usable": None, "installed": [], "copies": []}
        else:
            usable, copies = skills_copies(root, sc)
            installed = sorted(p.parent.name for p in (root / sc.canonical).glob("*/SKILL.md")) if usable else []
            project = {"configured": True, "canonical": sc.canonical, "canonical_usable": usable, "installed": installed,
                       "copies": [{**d, "failed": failed} for failed, d in copies]}
    return {"schema": "steward.skills/0.1", "tool_version": __version__, "bundles": bundles, "skills": skills,
            "project": project}


def cmd_skills(args: argparse.Namespace) -> int:
    root = args.repo.resolve() if args.repo else find_root(Path.cwd())
    if root is not None and not (root / "steward.toml").is_file():
        root = None  # the bundled skills are listed outside a project too
    try:
        doc = skills_document(root)
    except (ValidationError, ValueError, RecursionError, OSError):
        print("steward: steward.toml is not valid; run `steward check config`", file=sys.stderr)
        return EXIT_USAGE
    if args.format == "json":
        write_document(doc)
        return EXIT_OK
    out = [f"{b['name']} ({len(b['skills'])} skill(s)): " + ", ".join(b["skills"]) for b in doc["bundles"]]
    loose = [sk["name"] for sk in doc["skills"] if not sk["bundles"]]
    if loose:
        out.append("in no bundle: " + ", ".join(loose))
    pj = doc["project"]
    if pj is None:
        out.append("No steward.toml here: bundled skills only.")
    elif not pj["configured"]:
        out.append("[skills] is not configured: `steward init --skills DIR` copies them.")
    else:
        out.append(f"canonical: {pj['canonical']}" + (f"; {len(pj['installed'])} skill(s) installed"
                                                       if pj["canonical_usable"] else " (missing or a link)"))
        for c in pj["copies"]:
            out.append(f"  {'FAIL' if c['failed'] else 'ok  '} {c['path']}  {c['code']}"
                       + (f": {c['message']}" if c.get("message") else ""))
    print("\n".join(out))
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    if args.digest_only or args.against is not None:
        return cmd_check_digest(args)
    if args.summary and args.format == "json":
        print("steward: --summary is a text format; use --output FILE to keep the full JSON", file=sys.stderr)
        return EXIT_USAGE
    bad = [a for a in args.areas if a not in AREAS]
    if bad:
        print(f"steward: unknown area(s) {', '.join(bad)}; choose from {', '.join(sorted(AREAS))}", file=sys.stderr)
        return EXIT_USAGE
    rule = (args.rule or "").upper() or None
    if rule:  # 0.20.1 (STW-033): one rule, with every detail, without a saved report
        if rule not in RULES:
            print(f"steward: no rule {args.rule}; rules are {min(RULES)} … {max(RULES)}", file=sys.stderr)
            return EXIT_USAGE
        # AO1: the rule's own areas are always checked (with any named ones)
        args.areas = sorted(set(args.areas) | {a for a, rs in AREAS.items() if rule in rs})
    root = _require_root(args)
    try:
        exclude = ()
        if args.output is not None and args.output.resolve().is_relative_to(root.resolve()):
            exclude = (args.output.resolve().relative_to(root.resolve()).as_posix(),)
        faults: list[Exception | str] = []
        report = run_check(root, areas=args.areas or None, gate=args.gate, final=args.final, rule=rule,
                           exclude=exclude, on_fault=faults.append)
        try:  # SC2 (0.13.0): this checkout in the machine registry, for the storage cleanup's shared-use check
            from . import cleanup as _cu
            from .models import load_config as _lc

            _cu.register(root, _lc(root))
        except Exception:  # noqa: BLE001 - the registry never changes a check's outcome
            pass
    except UnknownGate as e:
        print(f"steward: unknown gate '{e}'", file=sys.stderr)
        return EXIT_USAGE
    gate_name = report.pop("_gate")
    if args.format == "json" or args.output is not None:
        Report.model_validate(report, strict=True)
    if args.output is not None:
        out = args.output.resolve()
        rel = out.relative_to(root).as_posix() if inside(root, str(out)) and out.is_relative_to(root) else None
        if rel and _checked_by_privacy(root, report, rel):
            print(f"steward: --output {rel} is inside a path the privacy rule checks; exclude it or write elsewhere",
                  file=sys.stderr)
            return EXIT_USAGE
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(canonical_json(report), encoding="utf-8")
    if args.format == "json" and args.output is not None:  # 0.20.1: the file holds the report; say where, only
        print(f"wrote {args.output} (summary: {summary_line(report['verdict']['summary']['counts'])})")
    elif args.format == "json":
        sys.stdout.write(canonical_json(report))
    elif rule:
        from .report import render_rule

        sys.stdout.write(render_rule(report, rule))
    elif getattr(args, "quiet", False) and report["verdict"]["gates"] and \
            all(g.get("eligible") for g in report["verdict"]["gates"]) and \
            not any(r["status"] in ("FAIL", "INCOMPLETE", "UNKNOWN") for r in report["verdict"]["results"]) and \
            not any(d.get("code") in QUIET_BREAKERS for r in report["verdict"]["results"] for d in r["details"]):
        n = sum(1 for r in report["verdict"]["results"] if r["status"] == "PASS")  # STW-009: the loop case, one line
        print(f"OK: every gate eligible; {n} result(s) passed; nothing needs attention (--summary for the details)")
    elif args.summary or getattr(args, "quiet", False):
        sys.stdout.write(render_summary(report, str(args.output) if args.output is not None else None,
                                        getattr(args, "all_lines", False)))
    else:
        sys.stdout.write(render_text(report))
    verdict = report["verdict"]
    if rule:  # AO1: the exit code is the selected rule's own
        from .status import combine

        own = [Status(r["status"]) for r in verdict["results"]
               if r["rule"] == rule and r["status"] != "NOT_APPLICABLE"]  # AP1: combine() has no NOT_APPLICABLE
        worst = combine(own) if own else Status.PASS
        code = EXIT_OK if worst == Status.PASS else exit_code_for(worst)
    elif args.areas:
        code = exit_code_for(Status(verdict["summary"]["worst"])) if verdict["summary"]["worst"] != "PASS" else EXIT_OK
    else:
        code = gate_exit_code(next(g for g in verdict["gates"] if g["name"] == gate_name))
    code = _fail_on(args, verdict, code)
    for fault in faults:
        args.fault_hint(code, fault)
    return code


def _fail_on(args: argparse.Namespace, verdict: dict, code: int) -> int:
    """S10 (0.21.0): `--fail-on` makes a FAIL (or anything not passing) exit non-zero, also outside every gate."""
    if code != EXIT_OK or not getattr(args, "fail_on", None):
        return code
    hit = {"fail": ("FAIL",), "incomplete": ("FAIL", "INCOMPLETE", "UNKNOWN")}[args.fail_on]
    found = [Status(r["status"]) for r in verdict["results"] if r["status"] in hit]
    if not found:
        return code
    from .status import combine

    return exit_code_for(combine(found))


def cmd_check_digest(args: argparse.Namespace) -> int:
    """C5 (0.21.0): the present digest of a report's inputs, without evaluating a rule. The report lists the files
    its check read and a digest of the repository's file list; both are recomputed here by the functions the check
    uses, so "current" means the same files hold the same bytes and no file was added or removed."""
    from .engine import inputs_digest, tree_digest
    from .fsutil import sha256_file
    from .models import overlay_label, overlay_path

    if not args.digest_only or args.against is None:
        print("steward: --digest-only needs --against FILE (a report from `steward check`), and --against needs "
              "--digest-only", file=sys.stderr)
        return EXIT_USAGE
    other = [flag for flag, on in (("AREA", bool(args.areas)), ("--rule", bool(args.rule)), ("--output", args.output),
                                   ("--summary", args.summary), ("--quiet", args.quiet), ("--final", args.final),
                                   ("--all", args.all_lines), ("--fail-on", args.fail_on)) if on]
    if other:
        print(f"steward: --digest-only evaluates no rule; {', '.join(other)} cannot be combined with it", file=sys.stderr)
        return EXIT_USAGE
    root = _require_root(args)
    try:
        raw = sys.stdin.read() if args.against == "-" else Path(args.against).read_text(encoding="utf-8")
        report = json.loads(raw)
        Report.model_validate(report)
    except FileNotFoundError:
        print(f"steward: no such report file: {args.against}", file=sys.stderr)
        return EXIT_USAGE
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as e:
        print(f"steward: invalid report (not a steward.report/0.1 document): {str(e).splitlines()[0]}", file=sys.stderr)
        return EXIT_DATAERR
    verdict = report["verdict"]
    if verdict.get("inputs") is None or verdict.get("tree_digest") is None:
        print("steward: this report lists no inputs (written before 0.21.0); run `steward check` again", file=sys.stderr)
        return EXIT_DATAERR
    exclude = ()
    if args.against != "-" and Path(args.against).resolve().is_relative_to(root.resolve()):
        exclude = (Path(args.against).resolve().relative_to(root.resolve()).as_posix(),)
    present: dict[str, str] = {}
    changed, unreadable = [], []
    overlay = overlay_path(root)
    label = overlay_label(root, overlay) if overlay is not None else None
    for item in verdict["inputs"]:
        rel = item["path"]
        path = overlay if rel == label else (root / rel if inside(root, rel) else None)
        try:
            if path is None:  # a label of an overlay that is gone, or a path outside the repository: never read
                raise OSError
            digest = sha256_file(path)
        except OSError:
            unreadable.append(rel)
            continue
        present[rel] = digest
        if digest != item["sha256"]:
            changed.append(rel)
    if label is not None and label not in present and label not in unreadable:
        changed.append(label)  # an overlay the earlier check did not read
    now_tree = tree_digest(root, exclude)
    now = inputs_digest(present) if not unreadable else None
    files_changed = now_tree != verdict["tree_digest"]
    from . import __version__

    tool_changed = report["envelope"]["tool_version"] != __version__
    current = now == verdict["inputs_digest"] and not files_changed and not tool_changed and not changed
    reasons = ([f"{len(changed)} input(s) changed"] if changed else []) + \
        ([f"{len(unreadable)} input(s) cannot be read"] if unreadable else []) + \
        (["files were added or removed"] if files_changed else []) + \
        ([f"the report was written by steward {report['envelope']['tool_version']}"] if tool_changed else [])
    doc = {
        "schema": "steward.digest/0.1",
        "tool_version": __version__,
        "inputs_digest": now,
        "tree_digest": now_tree,
        "report": {"inputs_digest": verdict["inputs_digest"], "tree_digest": verdict["tree_digest"],
                   "tool_version": report["envelope"]["tool_version"]},
        "current": current,
        "changed": sorted(set(changed) | set(unreadable)),
        "reason": "; ".join(reasons) if reasons else "the report's inputs and file list are unchanged",
    }
    if args.format == "json":
        write_document(doc)
    else:
        print(("current: " if current else "stale: ") + doc["reason"])
        for rel in doc["changed"]:
            print(f"  {rel}")
    return EXIT_OK


def _checked_by_privacy(root: Path, report: dict, rel: str) -> bool:
    import tomllib

    try:
        cfg = tomllib.loads((root / "steward.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    priv = cfg.get("privacy")
    if not isinstance(priv, dict):
        return False
    include = priv.get("include", ["**/*"])
    exclude = priv.get("exclude", [".git/**", ".steward/**"])
    return any(glob_match(rel, p) for p in include) and not any(glob_match(rel, p) for p in exclude)


def _paper_ctx(args: argparse.Namespace):
    import tomllib

    from .models import StewardConfig

    root = _require_root(args)
    try:
        cfg = _models.load_config(root)
    except (ValidationError, ValueError, RecursionError, ValueError, OSError):
        print("steward: steward.toml is not valid; run `steward check config`", file=sys.stderr)
        return None
    if not cfg.paper:
        print("steward: no [paper.<name>] table in steward.toml", file=sys.stderr)
        return None
    name = args.name or ("main" if "main" in cfg.paper or len(cfg.paper) != 1 else next(iter(cfg.paper)))
    if name not in cfg.paper:
        print(f"steward: unknown paper '{name}'; configured: {', '.join(sorted(cfg.paper))}", file=sys.stderr)
        return None
    return root, name, cfg.paper[name]


def _config(args: argparse.Namespace):
    import tomllib

    from .models import StewardConfig

    root = _require_root(args)
    try:
        return root, _models.load_config(root)
    except (ValidationError, ValueError, RecursionError, ValueError, OSError):
        print("steward: steward.toml is not valid; run `steward check config`", file=sys.stderr)
        return None, None


def cmd_run(args: argparse.Namespace) -> int:
    import os as _os

    import psutil as _ps

    from . import runner
    from .ledger import Ledger, LedgerError
    from .models import RunSection

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    rc = cfg.run or RunSection()
    led = Ledger(root / rc.ledger, "runs", cfg.steward.repo_id)
    if args.recover:
        try:
            marked = runner.recover(led)
        except LedgerError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_DATAERR
        print(f"marked interrupted: {', '.join(marked) if marked else 'none'}")
        return EXIT_OK
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("steward: give the command after --, e.g. steward run --wall 600 -- python train.py", file=sys.stderr)
        return EXIT_USAGE
    if args.run_id is not None:  # 0.21.0 (S7): an id in the form steward makes, never one the ledger already has
        if not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", args.run_id):
            print("steward: --run-id looks like 20261127T120000Z-1a2b3c4d (UTC time and 8 hex digits)", file=sys.stderr)
            return EXIT_USAGE
        try:
            from .ledger import verify as _verify

            used = led.path.is_file() and any(e.get("run") == args.run_id for e in _verify(led.path).entries)
        except (OSError, ValueError):
            used = False
        if used:
            print(f"steward: run {args.run_id} is already in the run ledger", file=sys.stderr)
            return EXIT_USAGE
    params = {}
    for kv in args.param:
        k, sep, v = kv.partition("=")
        if not sep:
            print(f"steward: --param expects K=V, got {kv!r}", file=sys.stderr)
            return EXIT_USAGE
        params[k] = v
    limits = runner.Limits(rc.wall_s, rc.mem_mb, rc.hang_s, rc.disk_free_mb, rc.hang_cpu_s).tightened(
        runner.Limits(args.wall, args.mem, args.hang, args.disk_free, args.hang_cpu))
    timeout = args.socket_timeout if args.socket_timeout is not None else rc.socket_timeout_s
    job_env = {"STEWARD_SOCKET_TIMEOUT": f"{timeout:g}"} if timeout else {}
    slot = None
    if args.slot:
        if args.slot not in rc.slots:
            print(f"steward: unknown slot {args.slot!r}; configured: {', '.join(sorted(rc.slots)) or 'none'}", file=sys.stderr)
            return EXIT_USAGE
        import math as _math

        if args.wait_timeout is not None and (not _math.isfinite(args.wait_timeout) or args.wait_timeout < 0):
            print("steward: --wait-timeout must be a finite, non-negative number of seconds", file=sys.stderr)
            return EXIT_USAGE
        slot = runner.Slot(root, args.slot, rc.slots[args.slot], rc.slots_dir)
        if not slot.acquire(args.wait, args.wait_timeout):
            print(f"steward: no free '{args.slot}' slot ({rc.slots[args.slot]} permit(s) busy); use --wait", file=sys.stderr)
            return runner.EXIT_NO_SLOT
    if cfg.integrity is not None:
        from . import integrity as ig

        for i in args.input:
            owner = ig.sealed_owner(root, cfg, i)
            if owner:
                if slot:
                    slot.release()
                print(f"steward: REFUSED: input {i} belongs to sealed dataset '{owner}'; unseal it with a signed "
                      "authorization first (steward unseal)", file=sys.stderr)
                return 77
    with runner.StopSignals() as held:  # DEF-012: from before the run is recorded until its outcome is
        return _run_held(args, root, cfg, rc, led, cmd, params, limits, job_env, slot, held.stop)


def _run_held(args, root, cfg, rc, led, cmd, params, limits, job_env, slot, stop) -> int:
    import os as _os
    import signal as _signal

    import psutil as _ps

    from . import runner
    from .ledger import LedgerError

    run_id = args.run_id or runner.new_run_id()
    from .fsutil import owner_lock, release_owner_lock

    run_lock = owner_lock(root, f"run-{run_id}")  # K1: `session close --end` stops a run only while it holds this
    cwd = Path.cwd().resolve()
    try:
        led.append("started", {
            "run": run_id, "label": args.label, "command": [runner.tilde(a) for a in cmd],
            "cwd": cwd.relative_to(root).as_posix() if cwd.is_relative_to(root) else ".",
            "pid": _os.getpid(), "pid_created": _ps.Process().create_time(), "slot": args.slot,
            **({"slot_scope": slot.scope, "slot_dir": slot.spec} if slot else {}),
            "git": runner.git_state(root), "environment": runner.environment(root),
            "inputs": {i: runner.sha_file(root / i) for i in sorted(args.input)}, "params": params, "seed": args.seed,
            # the declared outputs before the command: a later check can tell whether this run wrote them (J6)
            "outputs_before": {o: {"sha256": runner.sha_file(root / o),
                                   "mtime_ns": (root / o).stat().st_mtime_ns if (root / o).is_file() else None} for o in sorted(args.output)},
            "limits": dict(limits.__dict__), "estimate_min": args.estimate_min, "contract": args.contract,
            "code": {a: runner.sha_file(root / a) for a in sorted(set(cmd)) if not a.startswith("-") and _in_repo_file(root, cwd, a)},
        })
        log_rel = f"{rc.logs.rstrip('/')}/{run_id}.log"
        if "sig" in stop:  # signalled during setup: the job never starts, and the run is still recorded
            outcome = runner.Outcome("interrupted", None, 0.0, 0.0,
                                     f"interrupted by {_signal.Signals(stop['sig']).name} before the job started",
                                     {"signal": stop["sig"]})
        else:
            try:
                outcome = runner.execute(cmd, cwd, limits, root / log_rel, env=job_env, stop=stop)
            except FileNotFoundError as e:
                outcome = runner.Outcome("failed", None, 0.0, 0.0, None, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - R20 (0.12.0): a supervision error still records an outcome
                args.fault_hint(1, e)
                outcome = runner.Outcome("failed", None, 0.0, 0.0, f"supervision error: {type(e).__name__}",
                                         {"error": type(e).__name__, "cleanup": "incomplete"})
        metrics, metrics_text = None, None
        if args.metrics:
            mp = cwd / args.metrics
            if mp.is_file() and mp.stat().st_size <= 64 * 1024:
                try:
                    metrics_text = mp.read_text(encoding="utf-8")
                    metrics = json.loads(metrics_text)
                except (ValueError, UnicodeDecodeError):
                    metrics, metrics_text = None, None
        led.append("outcome", {
            # the text is kept so fractional values compare exactly as written (red-team F1); `metrics` is for reading
            "metrics": metrics, "metrics_text": metrics_text, "metrics_file": args.metrics,
            "run": run_id, "status": outcome.status, "exit_code": outcome.exit_code,
            "duration_s": round(outcome.duration_s, 3), "peak_rss_mb": round(outcome.peak_rss_mb, 1),
            "breached": outcome.breached, "log": log_rel, "log_sha256": runner.sha_file(root / log_rel),
            **({"cleanup": outcome.details["cleanup"]} if outcome.details.get("cleanup") else {}),  # S1
            "outputs": {o: runner.sha_file(root / o) for o in sorted(args.output)},
            "outputs_mtime_ns": {o: (root / o).stat().st_mtime_ns if (root / o).is_file() else None for o in sorted(args.output)},
            "actual_min": round(outcome.duration_s / 60, 3),
        })
    except LedgerError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    finally:
        if slot:
            slot.release()
        release_owner_lock(root, f"run-{run_id}", run_lock)
    print(f"steward: run {run_id} {outcome.status}" + (f" ({outcome.breached})" if outcome.breached else "")
          + f", {outcome.duration_s:.1f} s, peak {outcome.peak_rss_mb:.0f} MB", file=sys.stderr)
    if outcome.status == "interrupted":  # DEF-002: the job's tree is gone and the slot released; 128 + signal
        return 128 + int(outcome.details.get("signal", 2))
    if "sig" in stop:  # U12 (0.12.0): a signal after the job ended is never swallowed; the outcome stands as recorded
        print(f"steward: signal {stop['sig']} received after the job ended; its outcome is recorded as {outcome.status}",
              file=sys.stderr)
        return 128 + int(stop["sig"])
    if outcome.status == "killed":
        return runner.EXIT_LIMIT
    return outcome.exit_code if outcome.exit_code is not None else 1


def cmd_authorize(args: argparse.Namespace) -> int:
    from . import authorize as az
    from .ledger import verify as lverify

    if args.auth_command == "prepare" and args.action != "policy.change" and args.object is None:
        print("steward: --object is required for this action", file=sys.stderr)
        return EXIT_USAGE
    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.policy is None and args.auth_command not in ("pending", "sign-pending"):
        print("steward: add a [policy] table to steward.toml (baseline, allowed_signers, revoked)", file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.auth_command in ("pending", "sign-pending"):
            return _pending(root, cfg, args)
        if args.auth_command == "prepare":
            nonce, path = az.prepare(root, cfg, args.action, args.object, args.scope, args.budget, args.expires, args.summary)
            sys.stdout.write(path.read_text())
            print(f"\nRead the payload above. To approve it, run in your own terminal:  steward authorize sign {nonce}")
        elif args.auth_command == "sign":
            data = az.read_pending(root, args.nonce)
            az.check_digest(data, args.expect_sha256)  # before anything else is reported about these bytes
            if args.expect_sha256 is not None:
                print(f"Payload sha256 {az.payload_sha256(data)} matches the expected hash.", flush=True)
            payload = az.parse(az.decode(data))
            az.check_repo_id(payload, cfg.steward.repo_id, root)  # W12 F1, W12c N2: before any notice about another repository's bytes
            if payload["action"] == "policy.change":
                obj = payload["object"]
                try:
                    _, expected = az.current_policy_change(root, cfg)
                except (az.AuthError, OSError, subprocess.SubprocessError) as e:
                    print(f"Policy object {obj} has no confirmed R-33 match ({e}).", flush=True)
                else:
                    if obj == expected:
                        print(f"Policy object {obj} matches R-33.", flush=True)
                    else:
                        print(f"Policy object {obj} does not match R-33. Expected {expected}.", flush=True)
            print(f"signed {az.sign(root, args.nonce, data, repo_id=cfg.steward.repo_id)}")  # `data` passed check_digest above
        elif args.auth_command == "verify":
            exp = az.object_hash(root, args.object) if args.object else None
            v = az.verify(root, cfg, args.tag, action=args.action, expected_object=exp)
            print(f"VERIFIED {v.tag}: {v.payload['action']} {v.payload['object']} by {v.principal}, expires {v.payload['expires']}"
                  + ("" if v.trust_source != "working-tree" else "  [trust root UNPINNED: steward authorize pin]"))
        elif args.auth_command == "list":
            items = []
            tags = az.list_tags(root) + az.list_tags(root, "steward/anchor/")
            if not wants_json(args):  # X05: the text lists the newest tag first; the JSON keeps its order
                from .newest import newest_first

                made = az.tag_times(root)
                tags = newest_first(tags, made.get, str)
            for tag in tags:
                try:
                    v = az.verify(root, cfg, tag)
                    if wants_json(args):
                        items.append({"tag": tag, "verified": True, "action": v.payload["action"],
                                      "principal": v.principal, "trust_source": v.trust_source})
                    else:
                        print(f"{tag}  verified  {v.payload['action']}  by {v.principal}")
                except az.AuthError as e:
                    if wants_json(args):
                        items.append({"tag": tag, "verified": False, "step": e.step, "message": e.message})
                    else:
                        print(f"{tag}  NOT VERIFIED  ({e.step}: {e.message})")
            if wants_json(args):
                write_json(args, {"items": items})
        elif args.auth_command == "pin":
            tf, ref, signers = az.pin(root, cfg, args.baseline)
            print(f"pinned {cfg.steward.repo_id}: baseline {ref}, signers:")
            for f in az.fingerprints(signers):
                print(f"  {f}")
            print(f"in {tf}. Compare these fingerprints with your own key (ssh-keygen -lf ~/.ssh/<key>.pub) before relying on them.")
        elif args.auth_command == "keys":
            base = az.resolve_baseline(root, cfg.policy.baseline)
            text = (az.baseline_file(root, base, cfg.policy.allowed_signers) or b"").decode()
            keys = az.signer_keys(text)
            if wants_json(args):
                write_json(args, {"baseline": base, "keys": keys})
            else:
                for k in keys or [{"principal": "(none)", "type": "-", "hardware": "-"}]:
                    print(f"{k['principal']}  {k['type']}  hardware-backed: {k['hardware']}")
        elif args.auth_command == "anchor":
            paths = {"runs": (cfg.run.ledger if cfg.run else "development/runs.jsonl"),
                     "authorizations": cfg.policy.ledger, "spend": getattr(getattr(cfg, "spend", None), "ledger", "development/spend.jsonl"),
                     "integrity": getattr(getattr(cfg, "integrity", None), "ledger", "development/integrity.jsonl")}
            v = lverify(root / paths[args.ledger])
            if v.errors or not v.head:
                print("steward: ledger missing or not intact; nothing to anchor", file=sys.stderr)
                return EXIT_DATAERR
            head = v.head
            obj = "sha256:" + __import__("hashlib").sha256(f"{args.ledger}:{head['seq']}:{head['hash']}".encode()).hexdigest()
            nonce, path = az.prepare(root, cfg, "anchor", obj, f"ledger={args.ledger} seq={head['seq']} head={head['hash']}",
                                     "none", args.expires, f"Anchor the {args.ledger} ledger at entry {head['seq']}.")
            sys.stdout.write(path.read_text())
            print(f"\nTo anchor, run in your own terminal:  steward authorize sign {nonce}")
    except az.AuthError as e:
        print(f"steward: NOT AUTHORIZED: {e.step}: {e.message}", file=sys.stderr)
        return 1
    return EXIT_OK


def _pending(root: Path, cfg: Any, args: argparse.Namespace) -> int:
    """Deferred signing (0.12.0): the queue of prepared payloads, here and, with --all-projects, in each declared
    peer. Listing is read-only. Signing shows each payload first and asks, then runs `git tag -s` in its own
    repository, so the signing key's prompt stays the human step."""
    from . import authorize as az
    from .exchange import local_peer_path

    json_output = args.auth_command == "pending" and wants_json(args)
    items, skipped = [], []
    projects = [(cfg.exchange.code if cfg.exchange else ".", root)]
    if args.all_projects and cfg.exchange is not None:
        for code, source in sorted(cfg.exchange.peers.items()):
            try:
                path = local_peer_path(root, source)
            except (OSError, RuntimeError):
                path = None
            if path is None:
                if json_output:
                    skipped.append({"peer": code, "reason": "no_local_checkout"})
                else:
                    print(f"{code}: no local checkout for signing; skipped")
            else:
                projects.append((code, path))
    waiting = 0
    for i, (code, proj) in enumerate(projects):
        if not (proj / "steward.toml").is_file():
            if json_output:
                skipped.append({"peer": code, "reason": "not_steward_project"})
            else:
                print(f"{code}: {proj.name}: not a steward project here; skipped")
            continue
        try:  # W12 F1: each project's own repo_id; a payload carrying another one is listed as foreign, never waiting
            proj_id = cfg.steward.repo_id if not i else az.this_repo_id(proj)
        except az.AuthError:  # a project whose configuration cannot be read is never signed for
            proj_id = None
        if json_output:
            for q in az.pending(proj, include_digest=True, repo_id=proj_id):
                # P03: the sign command bound to the bytes listed here; only a waiting payload can be signed
                argv = az.sign_argv(q["nonce"], q["payload_sha256"], proj if i else None) \
                    if q["state"] == "waiting" else None
                items.append({**q, "project": code, "peer": code if i else None, "requester": None,
                              "sign_argv": argv, "sign_command": shlex.join(argv) if argv else None})
                waiting += q["state"] == "waiting"
            continue
        for q in _newest_pending(proj, az.pending(proj, repo_id=proj_id)):  # None: read again there; unreadable: foreign
            # STW-057: a summary's control characters (terminal escapes, carriage returns) are shown, never obeyed;
            # W12 F3: a line feed too, so a multi-line summary cannot add rows to this one-line-per-payload table
            line = az.visible(f"{code}  {q['nonce'][:12]}  {q['state']:<8} {q['action']:<14} expires {q['expires']}  "
                              f"{q.get('summary', '')[:60]}")[0].replace("\n", "\\n")
            if args.auth_command == "pending" or q["state"] != "waiting":
                print(line)
                waiting += q["state"] == "waiting"
                continue
            if proj_id is None or q.get("repo_id") != proj_id:  # U3: never sign another repository's payload here
                print(f"{line}  (skipped: its repo_id is not this project's)")
                continue
            try:
                data = az.read_pending(proj, q["nonce"])  # U3: read once; these bytes are shown and signed
                shown_payload = az.parse(az.decode(data))
            except az.AuthError as e:
                print(f"{line}  (skipped: {e.message})")
                continue
            # The checks and the prompt use the bytes just read, not the earlier listing: the file may have changed.
            if shown_payload.get("nonce") != q["nonce"] or shown_payload.get("repo_id") != proj_id:
                print(f"{line}  (skipped: it changed since it was listed)")
                continue
            digest = az.payload_sha256(data)
            text, hidden = az.visible(data)
            print("\n" + text)
            if hidden:
                print(f"WARNING: this payload holds {hidden} control or invisible character(s), shown above as "
                      "escapes (\\x.., \\u....). Do not sign it unless you know why they are there.")
            action = az.visible(shown_payload["action"])[0]
            print(f"payload sha256 {digest}  action {action}")
            if not args.yes:
                if not sys.stdin.isatty():
                    print("steward: sign-pending asks before each signature; run it in a terminal, or pass --yes",
                          file=sys.stderr)
                    return EXIT_USAGE
                prompt = f"Sign {code} {q['nonce'][:12]}: action {action}, payload sha256 {digest}? [y/N] "
                try:
                    answer = input(prompt)
                except EOFError:  # W12 F3: a closed input (Ctrl-D) is a no, never an internal error
                    answer = ""
                    print()
                if answer.strip().lower() not in ("y", "yes"):
                    print("skipped")
                    waiting += 1
                    continue
            print(f"signed {az.sign(proj, q['nonce'], data, repo_id=proj_id)}")  # the bytes shown, whose digest was shown
    if json_output:
        write_json(args, {"items": items, "waiting": waiting, "skipped": skipped})
    elif args.auth_command == "pending":
        print(f"{waiting} waiting" + ("" if not waiting else "; sign them with: steward authorize sign-pending"
                                      + (" --all-projects" if args.all_projects else "")))
    return EXIT_OK


def _newest_pending(proj: Path, queue: list[dict]) -> list[dict]:
    """X05: the signing queue as text, newest first: by when each payload was prepared (its file's time; the queue is
    local), then by nonce."""
    from .newest import newest_first

    def prepared(q: dict) -> float | None:
        try:
            return (proj / q["path"]).lstat().st_mtime
        except (OSError, KeyError, TypeError):
            return None

    return newest_first(queue, prepared, lambda q: q.get("nonce"))


def _contract_analysis(root: Path, cfg, cid: str) -> str | None:
    import tomllib

    from .fsutil import matching_files

    for rel in matching_files(root, cfg.paths.contracts):
        try:
            data = tomllib.loads((root / rel).read_text(encoding="utf-8"))
        except (ValueError, RecursionError, UnicodeDecodeError):
            continue
        if data.get("id") == cid:
            return data.get("analysis")
    return None


def cmd_integrity(args: argparse.Namespace) -> int:
    from . import authorize as az
    from . import integrity as ig
    from .ledger import LedgerError

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.integrity is None:
        print("steward: add an [integrity] table to steward.toml", file=sys.stderr)
        return EXIT_USAGE
    if args.command == "integrity" and args.integrity_command == "access":
        try:
            ok, why = ig.access(root, cfg, args.dataset, args.consumer, args.use)
        except (ig.IntegrityError, ValueError) as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        print(f"{'ALLOW' if ok else 'DENY'} {args.dataset} for {args.consumer} ({args.use}): {why}")
        return EXIT_OK if ok else 1

    def authorized(tag: str, action: str, obj: str, decision: str | None):
        if cfg.policy is None:
            raise ig.IntegrityError("signed authorizations need a [policy] table")
        v = az.verify(root, cfg, tag, action=action, expected_object=obj, require_pinned=True)
        if not ig.decision_present(root, cfg, decision):
            raise ig.IntegrityError(f"decision {decision!r} not found in {cfg.integrity.primary_decisions}")
        return v

    try:
        st = ig.state(root, cfg)
        led = ig.ledger(root, cfg)
        if args.command == "freeze":
            if args.name in st.frozen:
                raise ig.IntegrityError(f"'{args.name}' is already frozen; propose an amendment instead")
            if args.contract and _contract_analysis(root, cfg, args.contract) is None:
                raise ig.IntegrityError(f"no contract with id {args.contract!r}")
            snap = ig.snapshot(root, args.files, args.cohort, args.params, args.contract)
            confirmatory = bool(args.contract and _contract_analysis(root, cfg, args.contract) == "confirmatory")
            if args.dry_run:
                print(f"snapshot {snap['hash']} ({'confirmatory: needs a signed freeze.confirmatory' if confirmatory else 'not confirmatory'})")
                if confirmatory:
                    print(f"steward authorize prepare freeze.confirmatory --object {snap['hash']} --expires ... --summary ...")
                return EXIT_OK
            entry = {"name": args.name, "snapshot": snap, "object": snap["hash"], "confirmatory": confirmatory,
                     "authorization": None, "decision": args.decision}
            if confirmatory:
                if not args.authorization:
                    raise ig.IntegrityError("a confirmatory freeze needs --authorization (run with --dry-run for the object hash)")
                v = authorized(args.authorization, "freeze.confirmatory", snap["hash"], args.decision)
                az.consume(root, cfg, v, f"freeze {args.name}")
                entry["authorization"] = args.authorization
            led.append("freeze", entry)
            print(f"frozen '{args.name}': {snap['hash']}")
        elif args.command == "amend" and args.amend_command == "propose":
            if args.name not in st.frozen:
                raise ig.IntegrityError(f"'{args.name}' is not frozen")
            frozen = st.frozen[args.name]["snapshot"]
            now = ig.recompute(root, frozen)
            diffs = ig.differences(frozen, now)
            if not diffs:
                raise ig.IntegrityError("nothing changed since the freeze; nothing to propose")
            now["hash"] = ig._canon_hash({k: v for k, v in now.items()})
            led.append("proposal", {"name": args.name, "proposal": now["hash"], "snapshot": now, "diff": diffs, "reason": args.reason})
            print(f"proposed amendment {now['hash']} to '{args.name}' ({len(diffs)} change(s)). To approve, the human runs:")
            print(f"  steward authorize prepare amend --object {now['hash']} --expires ... --summary \"{args.reason}\"")
        elif args.command == "amend":
            prop = st.proposals.get(args.name)
            if prop is None:
                raise ig.IntegrityError(f"no pending proposal for '{args.name}'")
            now = ig.recompute(root, prop["snapshot"])
            now["hash"] = ig._canon_hash({k: v for k, v in now.items()})
            if now["hash"] != prop["proposal"]:
                raise ig.IntegrityError("files changed since the proposal; propose again")
            v = authorized(args.authorization, "amend", prop["proposal"], args.decision)
            az.consume(root, cfg, v, f"amend {args.name}")
            led.append("amend", {"name": args.name, "snapshot": prop["snapshot"], "object": prop["proposal"],
                                 "authorization": args.authorization, "decision": args.decision, "proposal": prop["proposal"]})
            print(f"amended '{args.name}' (authorized by {v.principal})")
        elif args.command in ("seal", "unseal"):
            ds = ig.load_datasets(root, cfg)
            if ds is None or args.dataset not in ds.datasets:
                raise ig.IntegrityError(f"dataset {args.dataset!r} is not declared in {cfg.integrity.datasets}")
            d = ds.datasets[args.dataset]
            content = ig.dataset_hash(root, d)
            role = st.roles.get(args.dataset, ("development", None))[0]
            if args.command == "seal":
                if role != "development":
                    raise ig.IntegrityError(f"'{args.dataset}' is already {role}")
                if content is None:
                    raise ig.IntegrityError(f"no files match the paths of '{args.dataset}'")
                led.append("seal", {"dataset": args.dataset, "content": content})
                print(f"sealed '{args.dataset}' ({content}); set role = \"sealed\" in {cfg.integrity.datasets}")
            else:
                if role != "sealed":
                    raise ig.IntegrityError(f"'{args.dataset}' is {role}, not sealed")
                sealed = st.roles[args.dataset][1]["content"]
                if content != sealed:
                    raise ig.IntegrityError("sealed contents changed since sealing; investigate before unsealing")
                v = authorized(args.authorization, "unseal", sealed, args.decision)
                az.consume(root, cfg, v, f"unseal {args.dataset}")
                led.append("unseal", {"dataset": args.dataset, "object": sealed, "authorization": args.authorization,
                                      "decision": args.decision})
                print(f"unsealed '{args.dataset}' (now spent); set role = \"spent\" in {cfg.integrity.datasets}")
        else:
            if wants_json(args):
                write_json(args, {
                    "frozen": [{"name": name, "sha256": e["snapshot"]["hash"],
                                "confirmatory": bool(e.get("confirmatory")), "amendment_proposed": name in st.proposals}
                               for name, e in sorted(st.frozen.items())],
                    "datasets": [{"name": name, "role": role} for name, (role, _) in sorted(st.roles.items())],
                })
                return EXIT_OK
            for name, e in sorted(st.frozen.items()):
                print(f"frozen {name}: {e['snapshot']['hash']} ({'confirmatory' if e.get('confirmatory') else 'exploratory'})"
                      + ("  [amendment proposed]" if name in st.proposals else ""))
            for n, (role, _) in sorted(st.roles.items()):
                print(f"dataset {n}: {role}")
            if not st.frozen and not st.roles:
                print("nothing frozen or sealed")
    except (ig.IntegrityError, LedgerError) as e:
        print(f"steward: REFUSED: {e}", file=sys.stderr)
        return 1
    except az.AuthError as e:
        print(f"steward: NOT AUTHORIZED: {e.step}: {e.message}", file=sys.stderr)
        return 1
    return EXIT_OK


def cmd_spend(args: argparse.Namespace) -> int:
    from . import spend as sp

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        if args.spend_command == "check":
            call = sp.guard(root, cfg, args.model, args.tokens_in, args.tokens_out, args.authorization, task=args.task)
            print(f"ALLOWED call {call}; record actual usage with: steward spend record {call} IN OUT")
        elif args.spend_command == "record":
            if cfg.spend is None:
                raise sp.SpendRefused("no [spend] table")
            e = sp.record(root, cfg, args.call, args.tokens_in, args.tokens_out, args.request_id)
            print(f"recorded {args.call}: cost {e['cost']} {cfg.spend.currency} (estimate from the price table)")
        else:
            if cfg.spend is None:
                raise sp.SpendRefused("no [spend] table")
            t = sp.totals(root, cfg)
            if wants_json(args):
                write_json(args, {**t, "cap": cfg.spend.cap, "currency": cfg.spend.currency})
                return EXIT_OK
            print(f"calls {t['calls']}; committed {t['committed']} / cap {cfg.spend.cap} {cfg.spend.currency}; "
                  f"actual {t['actual']}; unknown-cost calls {t['unknown_cost_calls']}")
    except sp.SpendRefused as e:
        print(f"steward: REFUSED: {e}", file=sys.stderr)
        return 1
    return EXIT_OK


def _in_repo_file(root: Path, cwd: Path, arg: str) -> bool:
    try:
        p = (cwd / arg).resolve()
        return p.is_file() and p.is_relative_to(root)
    except (OSError, ValueError):
        return False


def cmd_diff(args: argparse.Namespace) -> int:
    from . import evidence as ev

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if args.diff_command == "runs":
        from .cli_research import cmd_diff_runs

        return cmd_diff_runs(args, root, cfg)
    if args.diff_command == "impact":
        res = ev.impact(root, cfg)
        if wants_json(args):
            write_json(args, res)
        else:
            for it in res["outputs"]:
                why = ", ".join(it["inputs_changed"] + it["code_changed"])
                print(f"{it['state']:<18} {it['output']}  (run {it['run']}{'; changed: ' + why if why else ''})")
            for d in res["downstream"]:
                print(f"{'stale downstream':<18} paper {d['paper']}: " + (f"value {d['value']} <- {d['source']}" if "value" in d else f"display {d['display']} <- {', '.join(d['inputs'])}"))
            print(res["coverage"])
        return 1 if any(i["state"] != "current" for i in res["outputs"]) or res["downstream"] else EXIT_OK
    recs = ev.runs(root, cfg)
    for rid in (args.a, args.b):
        if rid not in recs:
            print(f"steward: no run {rid}", file=sys.stderr)
            return EXIT_USAGE
    a, b = recs[args.a], recs[args.b]
    if not a["outcome"] or not b["outcome"] or a["outcome"].get("status") != "finished" or b["outcome"].get("status") != "finished":
        print("steward: INCOMPLETE: both runs must have finished successfully to compare them (red-team A1)", file=sys.stderr)
        return 2
    try:
        tols = {}
        for t in args.tol:
            ptr, sep, spec = t.rpartition("=")  # a JSON pointer may contain "=" (red-team F4)
            if not sep:  # red-team G5: the separator is required; "=SPEC" names the root
                raise ValueError(f"--tol {t!r} must be POINTER=SPEC (use =SPEC for the root)")
            tols[ptr if ptr == "" or ptr.startswith("/") else "/" + ptr] = ev.parse_tol(spec)  # "" is the root (E6)
        default = ev.parse_tol(args.default_tol) if args.default_tol else None
    except ValueError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    res = ev.diff_runs(a, b, tols, default)
    if wants_json(args):
        write_json(args, res)
    else:
        for r in res["results"]:
            label = r.get("pointer") or r.get("output")
            tag = {"equal": "ok  ", "within": "ok  ", "different": "DIFF", "not comparable": "N/C ", "out of range": "OOR "}[r["state"]]
            print(f"{tag} {label}: {r['a']} vs {r['b']}" + (f" (tolerance {r['tolerance']})" if r.get("tolerance") else ""))
        for e in res["environment_differences"]:
            print(f"env  {e['field']}: {e['a']} vs {e['b']}")
        mp = res["metrics_precision"]  # red-team G8: say when a record predates exact metrics
        print(f"metrics precision: A {mp['a']}, B {mp['b']}" + (" (binary64: recorded before 0.6.2; rerun for an exact record)"
                                                               if "binary64" in mp.values() else ""))  # none: no metrics recorded (H7)
        print({"repeatable": "repeatable within tolerance", "not repeatable": "NOT repeatable within tolerance",
               "incomplete": "INCOMPLETE: missing or non-comparable evidence"}[res["verdict"]]
              + f" ({res['compared']} compared, {res['not_comparable']} not comparable). Scientific reproducibility is not assessed by this tool.")
    return {"repeatable": EXIT_OK, "not repeatable": 1, "incomplete": 2}[res["verdict"]]


def _announce(args: argparse.Namespace, root: Path, cfg: Any, code: str, xc: Any) -> int:
    """One release notice per declared consumer (DESIGN_exchange_protocol §5b; 0.9.0 D1)."""
    import datetime as _dt

    from .fsutil import git_run

    consumers = cfg.exchange.consumers
    if not consumers:
        print('steward: declare [exchange] consumers = ["ABC", …] first', file=sys.stderr)
        return EXIT_USAGE
    if git_run(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{args.tag}").returncode != 0:
        print(f"steward: tag {args.tag} does not exist; tag the release first", file=sys.stderr)
        return EXIT_USAGE
    version = args.tag[1:] if args.tag.startswith("v") else args.tag
    # U7 (0.13.0): the changelog as committed at the tag, never the working copy
    shown = git_run(root, "show", f"{args.tag}:{args.changelog}")
    section = xc.changelog_section(shown.stdout.decode("utf-8", "replace"), version) if shown.returncode == 0 else None
    if section is None:
        print(f"steward: {args.changelog} has no section for {version}", file=sys.stderr)
        return EXIT_USAGE
    if not re.search(r"^#{2,4}\s+Upgrade notes", section, re.M | re.I):
        print(f"steward: the {version} section of {args.changelog} has no \"Upgrade notes\" subsection; add one "
              "(what a consumer changes to upgrade, or \"none\")", file=sys.stderr)
        return EXIT_USAGE
    xc.ledger_ok(root)
    # DEF-028: every received item the changelog names as delivered moves to shipped with the tag first
    hist = xc.states(root)
    inbox = {Path(rel).stem: text for rel, text in xc.items(root).get("inbox", [])}
    licence_summary = ""
    if cfg.licence is not None:  # REQ-012: consumers evaluate the release's licence with their own check
        from . import licence as li
        from .records import read_rel

        try:
            rows, problems = li.inventory(root, cfg, lambda r: read_rel(root, r))
            if problems:  # AL4: an inventory with problems is never reported as a count
                raise ValueError("; ".join(problems[:3]))
            counts: dict[str, int] = {}
            for r in rows:
                fam = "unknown" if not r["licence"] else li.expr_family(li.parse_expr(r["licence"]))  # AF11: AND keeps its copyleft
                counts[fam] = counts.get(fam, 0) + 1
            licence_summary = (f"\n## Licence\n- Declared: {cfg.licence.declared} ({cfg.licence.distribution})\n"
                               f"- Dependencies: {len(rows)} (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ")\n")
        except (OSError, ValueError):
            licence_summary = "\n## Licence\n- Declared: " + cfg.licence.declared + " (inventory unavailable)\n"
    named = xc.delivered_ids(section, set(inbox))
    undecided = [i for i in named if xc.current(hist.get(i, [])) not in ("accepted", "deferred", "shipped", "adopted",
                                                                          "closed", "merged")]
    if undecided:
        print(f"steward: the {version} changelog names {', '.join(undecided)} as delivered, but they are not accepted "
              "or deferred; decide them first (steward exchange respond ID accepted --note …), or move them under a "
              "\"Known issues\" or \"Deferred\" heading", file=sys.stderr)
        return EXIT_USAGE
    peers, _ = xc.discover_peers(root, cfg.exchange)
    try:  # AI4: every notice is numbered before any state is written, and never again after
        first = xc.next_id(root, code, "release", peers)
    except ValueError as e:
        print(f"steward: {e}; nothing announced", file=sys.stderr)
        return EXIT_USAGE
    consumers = list(dict.fromkeys(consumers))  # AK5: one notice per distinct consumer
    stem, num = first.rsplit("-", 1)
    notice_ids = {to: f"{stem}-{int(num) + k:03d}" for k, to in enumerate(consumers)}
    shipped_by: dict[str, list[str]] = {}
    for i in named:
        kind_from = xc.parse(inbox[i])[0]
        if xc.current(hist.get(i, [])) in ("accepted", "deferred"):
            xc.set_state(root, cfg.steward.repo_id, i, "shipped", f"{args.tag}: listed in the {version} changelog",
                         code, False, kind_from.get("kind"), place="inbox")
            print(f"{i}: shipped ({args.tag})")
        last = xc.states(root).get(i, [])
        if xc.current(last) == "shipped" and xc.note_tag(last[-1].get("note")) == args.tag:  # U7: shipped in this one
            shipped_by.setdefault(kind_from.get("from"), []).append(i)
    for to in consumers:
        two_way = False
        if to in peers:
            try:
                with xc.peer_revision(root, to, peers[to]):
                    two_way = True
            except xc.PeerError as e:
                print(f"steward: {e}; its notice is one-way", file=sys.stderr)
        iid = notice_ids[to]
        fields = {"schema": "steward.exchange/1", "id": iid, "kind": "release", "from": code, "to": to,
                  "title": f"Release {args.tag}", "filed": _dt.date.today(), "version": version, "tag": args.tag,
                  "previous": args.previous, "breaking": bool(args.breaking),
                  "channel": None if two_way else "release notice (export and send)",
                  "sent": None if two_way else _dt.date.today()}
        mine = shipped_by.get(to, [])
        text = xc.render(fields, "\n" + section + ("\n## Shipped items\n" + "".join(f"- {i}\n" for i in mine) if mine else "")
                         + licence_summary)
        xc.Item.model_validate(xc.parse(text)[0])
        dest = xc.write_new(root, "outbox" if two_way else "oneway", f"{iid}.md", text.encode("utf-8"))
        before = xc.entries_of(root, iid)
        try:
            xc.set_state(root, cfg.steward.repo_id, iid, "filed" if two_way else "sent", None, code, not two_way, "release")
        except Exception:
            if not xc.keep_if_appended(root, dest, iid, before, "filed" if two_way else "sent"):  # U5
                xc.rollback(root, dest)
            raise
        else:
            xc.forget(dest)
        print(f"{iid}: {dest.relative_to(root).as_posix()} ({'two-way: the consumer pulls it' if two_way else f'one-way: steward exchange export {iid}'})")
    return EXIT_OK


def cmd_frozen(args: argparse.Namespace) -> int:
    from .fsutil import canonical_json
    from .process import frozen_hashes, frozen_record_path

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    fs = next((f for f in cfg.frozen if f.name == args.name), None)
    if fs is None:
        print(f"steward: no [[frozen]] set named {args.name!r}", file=sys.stderr)
        return EXIT_USAGE
    rel = frozen_record_path(fs)
    if (root / rel).is_file():
        from .integrity import decision_heading

        if not decision_heading(root, cfg, args.decision):  # R14: an entry heading, checked before the record changes
            print(f"steward: {args.name} is already frozen; a new version needs --decision TEXT naming a decisions-log "
                  "entry", file=sys.stderr)
            return EXIT_USAGE
    files = frozen_hashes(root, fs)
    if not files:
        print(f"steward: {args.name}: no files match {fs.files}", file=sys.stderr)
        return EXIT_USAGE
    from .fsutil import safe_write

    safe_write(root, rel, canonical_json({"schema": "steward.frozen/0.1", "name": fs.name, "files": files,
                                          "decision": args.decision}).encode("utf-8"))
    print(f"recorded {rel}: {len(files)} file(s)")
    return EXIT_OK


def cmd_stage(args: argparse.Namespace) -> int:
    import subprocess as _sp

    from .ledger import Ledger, LedgerError
    from .process import accrual_count, stage_refusal

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("steward: give the command after --", file=sys.stderr)
        return EXIT_USAGE
    from .process import stage_evidence

    why, ev = stage_evidence(root, cfg, args.name)  # R13: checked and recorded from one reading
    if why:
        print(f"steward: REFUSED: {why}", file=sys.stderr)
        return 77
    st = next(s for s in cfg.stages if s.name == args.name)
    count = ev["count"]
    led = Ledger(root / cfg.stages_ledger, "stages", cfg.steward.repo_id, base=root)
    try:  # Q23: the launch, with its GO evidence and the count at launch, is recorded before anything runs
        start = led.append("launch", {"stage": st.name, "reads": st.reads, "go": st.go, "go_log": ev["go_log"],
                                      "count": count})
    except (LedgerError, OSError) as e:
        print(f"steward: REFUSED: the stage record cannot be written ({e}); nothing was run", file=sys.stderr)
        return EXIT_DATAERR
    proc = _sp.run(cmd, cwd=Path.cwd())
    try:
        led.append("stage", {"stage": st.name, "reads": st.reads, "go": st.go, "launch": start["seq"],
                             "count": count, "exit_code": proc.returncode})
    except LedgerError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    return proc.returncode


def cmd_shards(args: argparse.Namespace) -> int:
    from .fsutil import canonical_json

    try:
        text = args.cost.read_text(encoding="utf-8")
        try:
            costs = {str(k): float(v) for k, v in json.loads(text).items()}
        except ValueError:
            costs = {l.split(",")[0].strip(): float(l.split(",")[1]) for l in text.splitlines() if "," in l}
    except (OSError, ValueError, IndexError, AttributeError) as e:
        print(f"steward: cannot read {args.cost}: {e}", file=sys.stderr)
        return EXIT_USAGE
    if args.shards < 1 or not costs:
        print("steward: --shards must be at least 1, and the cost file must list jobs", file=sys.stderr)
        return EXIT_USAGE
    shards: list[list[str]] = [[] for _ in range(args.shards)]
    totals = [0.0] * args.shards
    for job, cost in sorted(costs.items(), key=lambda kv: (-kv[1], kv[0])):  # longest first, onto the lightest shard
        i = min(range(args.shards), key=lambda k: (totals[k], k))
        shards[i].append(job)
        totals[i] += cost
    plan = {"schema": "steward.shards/0.1", "shards": shards, "totals": totals,
            "merge": "after every shard finished: combine the shard outputs in shard order, then verify the job count"}
    text = canonical_json(plan)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return EXIT_OK


def cmd_docs(args: argparse.Namespace) -> int:
    from . import docsite as ds
    from .fsutil import LinkRefused, safe_write
    from .models import DocsSection

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if args.docs_command == "readme":
        from . import docreadme

        try:
            if args.pypi:
                block, _ = docreadme.render(root, cfg, pypi=True)
                sys.stdout.write(block)
            else:
                docreadme.write(root, cfg)
                print("updated the generated block in README.md and its SVG assets")
        except (ds.DocsError, OSError) as e:
            print(f"steward: README: {e}", file=sys.stderr)
            return EXIT_DATAERR
        return EXIT_OK
    if cfg.docs is None:
        cfg.docs = DocsSection()
    try:
        if args.docs_command == "init":
            try:
                scaffold = ds.init_files(root, cfg, args.pages)
            except ds.DocsError as e:
                print(f"steward: refused: the scaffold would publish {e}; nothing was written", file=sys.stderr)
                return 65
            for rel, text in scaffold.items():
                if (root / rel).exists() or (root / rel).is_symlink():
                    print(f"kept {rel} (exists)")
                    continue
                safe_write(root, rel, text.encode("utf-8"), exclusive=True)
                print(f"wrote {rel}")
            print("Next: steward docs build, then mkdocs build --strict (pip install mkdocs-material)")
            return EXIT_OK
        try:
            pages = ds.build_pages(root, cfg)
        except ds.DocsError as e:
            print(f"steward: refused: a page would publish {e}; nothing was written", file=sys.stderr)
            return 65
        for name, text in sorted(pages.items()):
            safe_write(root, f"{cfg.docs.generated.rstrip('/')}/{name}", text.encode("utf-8"))
        gone = ds.retired(root, cfg, set(pages))
        for rel in gone:  # T1: a page the configuration no longer publishes is removed, never left publishable
            (root / rel).unlink()
        print(f"wrote {len(pages)} page(s) to {cfg.docs.generated}/ from the project's records"
              + (f"; removed {len(gone)} retired page(s)" if gone else ""))
        return EXIT_OK
    except LinkRefused as e:
        print(f"steward: refused: {e.strerror or e}", file=sys.stderr)
        return 65


def cmd_agents(args: argparse.Namespace) -> int:
    from .ledger import Ledger, LedgerError
    from .models import AgentsSection
    from .process import agent_entries

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    ac = cfg.agents or AgentsSection()
    if args.agents_command == "list":
        return _agents_list(args, root, ac)
    if args.agents_command == "setup":
        return _agents_setup(args, root, cfg)
    if args.agents_command == "status":
        return _agents_status(args, root, cfg)
    led = Ledger(root / ac.ledger, "agents", cfg.steward.repo_id, base=root)
    extra: dict[str, Any] = {}  # X03: only the optional fields given, so an attempt without them is as before
    if args.agents_command == "attempt":
        if args.estimate_file is not None:
            try:
                estimate = json.loads(Path(args.estimate_file).read_text(encoding="utf-8"))
            except FileNotFoundError:
                print(f"steward: no such estimate file: {args.estimate_file}", file=sys.stderr)
                return EXIT_USAGE
            except (OSError, UnicodeDecodeError, ValueError, RecursionError) as err:
                print(f"steward: the estimate file is not readable JSON: {err}", file=sys.stderr)
                return EXIT_DATAERR
            if not isinstance(estimate, dict):
                print("steward: the estimate file must hold a JSON object", file=sys.stderr)
                return EXIT_DATAERR
            extra["estimate"] = estimate
        for name in ("harness", "harness_version", "parent", "status"):
            if getattr(args, name) is not None:
                extra[name] = getattr(args, name)
    elif args.agents_command == "event":
        if _event_time(args.time) is None:
            print(f"steward: --time {args.time!r} is not an ISO 8601 time with a time zone "
                  "(e.g. 2026-11-27T10:00:00Z)", file=sys.stderr)
            return EXIT_USAGE

    def decide(entries: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        mine = [e for e in entries if e.get("task") == args.task]
        if args.agents_command == "attempt":
            n = 1 + sum(1 for e in mine if e.get("kind") == "attempt")
            return "attempt", {"task": args.task, "attempt": n, "agent": args.agent, "provider": args.provider,
                               "model": args.model, "suggested": args.suggested, "started": args.started,
                               "ended": args.ended, "reviewer": args.reviewer, **extra}
        if args.agents_command == "event":
            return "event", {"task": args.task, "event": args.kind, "at": args.time}
        body = {"task": args.task, "attempt": args.attempt, "scorer": args.scorer, "score": args.score,
                "rubric": args.rubric, "override": (args.override or "").strip() or None}
        problems = agent_entries(entries + [{"kind": "score", **body}], ac.may_score)
        new = [p for p in problems if p["value"] == f"{args.task}#{args.attempt}" and p.get("seq") is None]
        if new:
            raise ValueError({"R-62.self_scored": "an attempt is never scored by its author",
                              "R-62.unknown_attempt": "no such attempt",
                              "R-62.not_permitted": "[agents] may_score does not let "
                                                    f"{args.scorer} score this attempt's author",
                              "R-62.silent_override": "already scored; pass --override REASON"}[new[0]["code"]])
        return "score", body
    try:
        e = led.transaction(decide)
    except ValueError as err:
        print(f"steward: {err}", file=sys.stderr)
        return EXIT_USAGE
    except LedgerError as err:
        print(f"steward: {err}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"{args.task}: {e['kind']} recorded (seq {e['seq']})")
    return EXIT_OK


def _event_time(text: str):
    """An ISO 8601 time with a time zone, or None (X03: `steward agents event --time`)."""
    import datetime as _dt

    try:
        t = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _agents_document(entries: list[dict[str, Any]], only: str | None) -> list[dict[str, Any]]:
    """The attribution ledger per task (X03): tasks by their newest record, and within each task attempts, scores
    and events newest first."""

    def text(v: Any) -> str | None:
        return v if isinstance(v, str) else None

    def number(v: Any) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    tasks: dict[str, dict[str, Any]] = {}
    last: dict[str, int] = {}
    for e in entries:
        task = e.get("task")
        if not isinstance(task, str) or (only is not None and task != only):
            continue
        kind = e.get("kind")
        if kind not in ("attempt", "score", "event"):
            continue
        t = tasks.setdefault(task, {"task": task, "attempts": [], "events": [], "_scores": []})
        last[task] = max(last.get(task, -1), number(e.get("seq")) or 0)
        seen = {"seq": number(e.get("seq")), "recorded": text(e.get("time"))}
        if kind == "attempt":
            estimate = e.get("estimate")
            t["attempts"].append({
                "attempt": number(e.get("attempt")), "agent": text(e.get("agent")),
                "provider": text(e.get("provider")), "model": text(e.get("model")),
                "suggested": text(e.get("suggested")), "started": text(e.get("started")),
                "ended": text(e.get("ended")), "reviewer": text(e.get("reviewer")),
                "estimate": estimate if isinstance(estimate, dict) else None,
                "harness": text(e.get("harness")), "harness_version": text(e.get("harness_version")),
                "parent": text(e.get("parent")), "status": text(e.get("status")), **seen, "scores": []})
        elif kind == "score":
            score = e.get("score")
            t["_scores"].append({
                "attempt": number(e.get("attempt")), "scorer": text(e.get("scorer")),
                "score": float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
                "rubric": text(e.get("rubric")), "override": text(e.get("override")), **seen})
        else:
            t["events"].append({"kind": text(e.get("event")), "time": text(e.get("at")), **seen})

    def newest(item: dict[str, Any]) -> int:
        return item["seq"] if item["seq"] is not None else -1

    out = []
    for task in sorted(tasks, key=lambda k: (last[k], k), reverse=True):
        t = tasks[task]
        by_attempt: dict[int | None, list[dict[str, Any]]] = {}
        for s in t.pop("_scores"):
            by_attempt.setdefault(s.pop("attempt"), []).append(s)
        for a in t["attempts"]:
            a["scores"] = sorted(by_attempt.get(a["attempt"], []), key=newest, reverse=True)
        t["attempts"].sort(key=lambda a: (a["attempt"] or 0, newest(a)), reverse=True)
        t["events"].sort(key=lambda ev: (ev["time"] or "", newest(ev)), reverse=True)
        out.append(t)
    return out


def _agents_list(args: argparse.Namespace, root: Path, ac: Any) -> int:
    from . import ledger as lg

    p = root / ac.ledger
    if p.is_symlink():
        print(f"steward: refused: {ac.ledger} is a link", file=sys.stderr)
        return EXIT_DATAERR
    v = lg.verify(p)
    if v.errors or v.torn_tail:
        print(f"steward: {ac.ledger} was edited, or its last record is torn; run `steward check agents`",
              file=sys.stderr)
        return EXIT_DATAERR
    tasks = _agents_document(v.entries, args.task)
    if wants_json(args):
        write_json(args, {"ledger": ac.ledger, "tasks": tasks})
        return EXIT_OK
    if not tasks:
        print(f"no attempts or events recorded{' for ' + args.task if args.task else ''} ({ac.ledger})")
        return EXIT_OK
    for t in tasks:
        print(f"{t['task']}: {len(t['attempts'])} attempt(s), {len(t['events'])} event(s)")
        for a in t["attempts"]:
            parts = [f"{a['agent']}", f"{a['provider']}/{a['model']}"]
            if a["suggested"] and a["suggested"] != a["model"]:
                parts.append(f"suggested {a['suggested']}")
            if a["harness"]:
                parts.append(f"harness {a['harness']}" + (f" {a['harness_version']}" if a["harness_version"] else ""))
            for key in ("status", "parent", "reviewer", "started", "ended"):
                if a[key]:
                    parts.append(f"{key} {a[key]}")
            print(f"  attempt {a['attempt']}: " + " · ".join(parts))
            if a["estimate"] is not None:
                print(f"    estimate: {json.dumps(a['estimate'], sort_keys=True, ensure_ascii=False)}")
            for s in a["scores"]:
                print(f"    score {s['score']:g} by {s['scorer']} (rubric {s['rubric']})"
                      + (f", override: {s['override']}" if s["override"] else "")
                      if s["score"] is not None else f"    score by {s['scorer']} (no number)")
        for ev in t["events"]:
            print(f"  event {ev['kind']} at {ev['time']}")
    return EXIT_OK


def _agents_setup(args: argparse.Namespace, root: Path, cfg: Any) -> int:
    """`steward agents setup` (0.23.0, STW-061 D01): probe the agent CLIs, show the [delegation] diff, write it after
    confirmation (or with --yes)."""
    from . import delegation as dg
    from .fsutil import safe_write
    from .ledger import LedgerError
    from .records import RecordRefused, read_rel

    seen = [dg.probe(n) for n in dg.ORDER]
    for p in seen:
        if not p["installed"]:
            print(f"  {p['agent']:<12} not installed ({p['executable']} is not on PATH or in its install folder)")
            continue
        signed = {True: "signed in", False: "signed out", None: "sign-in not known"}[p["signed_in"]]
        print(f"  {p['agent']:<12} {p['version'] or 'version not known'} · {signed} · {p['found']}")
    proposal = dg.propose(seen, cfg.delegation, getattr(args, "master", None))
    if proposal is None:
        print("no agent CLI is installed; nothing to write (install claude, codex or agy, then run this again)")
        return EXIT_OK
    try:
        current = read_rel(root, "steward.toml").decode("utf-8")
    except (RecordRefused, ValueError) as e:
        print(f"steward: steward.toml cannot be read ({e}); nothing written", file=sys.stderr)
        return EXIT_DATAERR
    updated = dg.replace_table(current, dg.render(proposal))
    if updated == current:
        print("[delegation] is up to date")
    else:
        print(dg.diff(current, updated), end="")
        if not getattr(args, "yes", False):
            if not sys.stdin.isatty():
                print("not written: confirm in a terminal, or pass --yes")
                return EXIT_OK
            try:
                answer = input("Write this [delegation] to steward.toml? [y/N] ")
            except EOFError:  # a closed input is a no
                answer = ""
                print()
            if answer.strip().lower() not in ("y", "yes"):
                print("not written")
                return EXIT_OK
        import tomllib

        try:  # the text written must parse, and its [delegation] must pass the schema
            _models.DelegationSection.model_validate(tomllib.loads(updated)["delegation"])
        except (ValueError, KeyError) as e:
            print(f"steward: the proposed steward.toml does not parse ({e}); nothing written", file=sys.stderr)
            return EXIT_SOFTWARE
        try:
            safe_write(root, "steward.toml", updated.encode("utf-8"))
        except OSError as e:
            print(f"steward: cannot write steward.toml: {e}", file=sys.stderr)
            return EXIT_CANTCREAT
        print("wrote [delegation] to steward.toml")
    try:
        if sync_agents_block(root):
            print("updated AGENTS.md (steward block)")
    except OSError as e:
        print(f"steward: AGENTS.md was not updated: {e}", file=sys.stderr)
    try:
        dg.record_observed(root, cfg.steward.repo_id, seen)
    except (LedgerError, OSError) as e:
        print(f"steward: the availability ledger was not updated: {e}", file=sys.stderr)
        return EXIT_DATAERR
    print(f"recorded what was found in {dg.LEDGER}")
    return EXIT_OK


def _agents_status(args: argparse.Namespace, root: Path, cfg: Any) -> int:
    from . import delegation as dg
    from .cockpit import parse_now

    try:
        now = parse_now(args.now)
    except ValueError as e:
        print(f"steward: --now: {e}", file=sys.stderr)
        return EXIT_USAGE
    if (root / dg.LEDGER).is_symlink():
        print(f"steward: refused: {dg.LEDGER} is a link", file=sys.stderr)
        return EXIT_DATAERR
    try:
        doc = dg.status(root, cfg, now)
    except ValueError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    if wants_json(args):
        write_json(args, doc)
        return EXIT_OK
    if doc["configured"]:
        print(f"master {doc['master']} · workers {', '.join(doc['workers']) or 'none'} · on_limit {doc['on_limit']}")
    else:
        print("no [delegation] in steward.toml (steward agents setup writes one)")
    for a in doc["agents"]:
        role = f"worker {a['rank']}" if a["role"] == "worker" else a["role"]
        state = {"limited": f"limited until {a['until']}" + ("" if a["reset_known"] else " (no reset time printed)"),
                 "signed_out": "signed out", "missing": "missing", "available": "available"}[a["state"]]
        extra = [x for x in (a["version"], a["model"] and f"model {a['model']}") if x]
        print(f"  {a['agent']:<12} {role:<10} {state}" + (f"  ({', '.join(extra)})" if extra else ""))
    print(f"ledger: {doc['ledger']}")
    return EXIT_OK


def cmd_session(args: argparse.Namespace) -> int:
    from . import session as ss
    from .models import SessionSection

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    sc = cfg.session or SessionSection()
    if cfg.session is None:
        cfg.session = sc
    if args.session_command == "start":
        if wants_json(args):
            from .records import RecordRefused, read_rel

            try:
                handoff = read_rel(root, sc.handoff).decode("utf-8")
            except RecordRefused as e:
                if e.reason != "missing":
                    print(f"steward: {e}", file=sys.stderr)
                    return EXIT_DATAERR
                handoff = None
            except UnicodeDecodeError:
                print(f"steward: {sc.handoff} is not UTF-8", file=sys.stderr)
                return EXIT_DATAERR
            last_commit = ss.handoff_commit(root, sc.handoff) if handoff is not None else None
            commit, _, date = (last_commit or "").partition(" ")
            write_json(args, {"constitution": cfg.steward.constitution,
                              "handoff": {"path": sc.handoff, "text": handoff,
                                          "commit": commit or None, "commit_date": date or None}})
            return EXIT_OK
        print(f"Constitution: {cfg.steward.constitution or 'not declared'} (steward constitution prints it)")
        p = root / sc.handoff
        if not p.is_file():
            print(f"No handoff yet ({sc.handoff}). Read development/INDEX.md, or the project's own start file.")
        else:
            when = ss.handoff_commit(root, sc.handoff)
            print(f"Handoff: {sc.handoff} ({'commit ' + when if when else 'not committed'})\n")
            sys.stdout.write(p.read_text(encoding="utf-8"))
            print("\nRead the links under Read first only when the next step needs them.")
        if cfg.exchange is not None:
            from . import exchange as xc

            _print_exchange_delivery(root, cfg, xc.delivery_status(root, cfg.exchange), advisories=True)
        return EXIT_OK
    log = ss.decisions_log(cfg)
    if not args.decisions_logged:
        print(f"steward: confirm that every owner decision of this session is recorded in {log}, then pass "
              "--decisions-logged (the files cannot show what was said)", file=sys.stderr)
        return EXIT_USAGE
    if len(args.next) > 3 or len(args.read_first) > 5:
        print("steward: at most 3 --next and 5 --read-first", file=sys.stderr)
        return EXIT_USAGE
    try:
        dirty = ss.uncommitted(root, ss.process_paths(root, cfg), {sc.handoff})
    except ss.SessionError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    if dirty and not args.allow_dirty:
        print("steward: uncommitted process records: " + ", ".join(dirty[:20]) + ("…" if len(dirty) > 20 else "")
              + "\ncommit them first, or pass --allow-dirty (the handoff then lists them)", file=sys.stderr)
        return 1
    if not args.next:
        print("steward: warning: no --next step given; the handoff's Next section is empty", file=sys.stderr)
    for rp in args.read_first:
        if not (root / rp).exists():
            print(f"steward: warning: --read-first {rp} does not exist", file=sys.stderr)
    text = ss.render(root, cfg, args, dirty, [] if args.end else None)
    n = ss.words(text)
    if n > sc.budget_words:
        longest = max(ss.sections(text).items(), key=lambda kv: ss.words(kv[1]))
        print(f"steward: the handoff has {n} words, over the budget of {sc.budget_words}; the longest section is "
              f"{longest[0]} ({ss.words(longest[1])} words). Link records instead of describing them.", file=sys.stderr)
        return 1
    # U14: --end checks the final text; X2 (0.15.0): a dry run prints this text, so it is checked exactly
    hits = ss.privacy_hits(root, cfg, text, sc.handoff, preview=bool(args.end and not args.dry_run))
    if hits:
        print(f"steward: the handoff contains {', '.join(hits)}; reword it (it is a committed record)", file=sys.stderr)
        return 65
    if args.dry_run:
        sys.stdout.write(text)
        return EXIT_OK
    from .fsutil import LinkRefused, escapes_root, open_dir_beneath, safe_write

    try:  # Q6: the destination is checked before anything is stopped or written
        if escapes_root(sc.handoff):
            raise LinkRefused(0, "outside the repository")
        parts = Path(sc.handoff).parts
        os.close(open_dir_beneath(root, parts[:-1], create=True))
        if (root / sc.handoff).is_symlink():
            raise LinkRefused(0, "a symbolic link")
    except LinkRefused as e:
        print(f"steward: {sc.handoff}: {e.strerror or e}; refusing to write the handoff", file=sys.stderr)
        return 65
    if args.end and sc.end_hint and ss.privacy_hits(root, cfg, sc.end_hint):  # Q15: scanned before it is written
        print("steward: [session] end_hint contains a private term or a local path; reword it", file=sys.stderr)
        return 65
    report = ss.end(root, cfg) if args.end else None
    if report is not None:
        text = ss.render(root, cfg, args, dirty, report)
        if ss.privacy_hits(root, cfg, text, sc.handoff):  # R11; U14: the handoff's own scope
            print(f"steward: the session-end report holds a private term or a local path; the handoff was not "
                  f"written ({len(report)} report line(s) withheld)", file=sys.stderr)
            return 65
        if ss.words(text) > sc.budget_words:  # R11: the budget holds for the final text too
            print(f"steward: with the session-end report the handoff has {ss.words(text)} words, over "
                  f"{sc.budget_words}; it was not written", file=sys.stderr)
            return 1
    try:
        safe_write(root, sc.handoff, text.encode("utf-8"))
    except LinkRefused as e:
        print(f"steward: {sc.handoff}: {e.strerror or e}", file=sys.stderr)
        return 65
    print(f"wrote {sc.handoff} ({ss.words(text)} of {sc.budget_words} words). Commit it: the next session starts "
          "with `steward session start`.")
    for line in report or []:
        print(line)
    return EXIT_OK


def cmd_repro(args: argparse.Namespace) -> int:
    from . import repro as rp
    from .ledger import LedgerError

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.repro is None:
        print('steward: add [repro] contracts = ["benchmarks/*.repro.toml"] to steward.toml', file=sys.stderr)
        return EXIT_USAGE
    found = rp.contracts(root, cfg)
    for rel, c, err in found.values():
        if err:
            print(f"steward: {rel}: {err}", file=sys.stderr)
    entry = found.get(args.id)
    if entry is None or entry[1] is None:
        print(f"steward: no valid reproduction contract with id {args.id!r}", file=sys.stderr)
        return EXIT_USAGE
    rel, c, _ = entry
    if args.repro_command == "manifest":
        src = args.source if args.source.is_absolute() else root / args.source
        try:
            files = rp.write_manifest(root, c, src)
        except (OSError, ValueError) as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        print(f"wrote {c.manifest}: {len(files)} file(s), canonical form {c.canonical}")
        return EXIT_OK
    work = args.work if args.work.is_absolute() else Path.cwd() / args.work
    if not work.is_dir():
        print(f"steward: {work} is not a folder", file=sys.stderr)
        return EXIT_USAGE
    try:
        res = rp.check(root, c, work)
    except (OSError, ValueError) as e:
        print(f"steward: cannot read the manifest: {e}", file=sys.stderr)
        return EXIT_DATAERR
    commit, tree = rp.git_ids(root)
    body = {"id": c.id, "contract": rel, "contract_sha256": rp.sha_file(root / rel),
            "commit": commit, "tree": tree, "run": args.run, **res}  # R9: the manifest hash of the bytes compared
    try:
        rp.ledger(root, cfg).append("repro", body)
    except LedgerError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_CANTCREAT
    for m in res["mismatches"]:
        print(f"MISMATCH {m['path']}" + (f" {m['pointer']}" if "pointer" in m else "") + f" ({m['state']})")
    print(f"{c.id}: {res['result'].upper()} ({res['files']} file(s); {res['within_tolerance']} within tolerance; "
          f"{res['mismatch_count']} mismatch(es)); recorded in {cfg.repro.ledger}" + ("" if commit else " (no git commit)"))
    return EXIT_OK if res["result"] == "pass" else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    import tomllib

    from . import benchmark as bm
    from . import evidence as ev
    from .fsutil import escapes_root
    from .models import Contract

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    path = root / args.contract
    if escapes_root(args.contract) or not inside(root, args.contract) or not path.is_file():
        print(f"steward: no contract file {args.contract} in this repository", file=sys.stderr)
        return EXIT_USAGE
    try:
        raw = path.read_bytes()
        c = Contract.model_validate(tomllib.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError, RecursionError, UnicodeDecodeError):
        print("steward: the contract is not valid; run `steward check contract`", file=sys.stderr)
        return EXIT_DATAERR

    def blocking(problems: list) -> bool:
        return any(st != "INFO" for st, _, _ in problems)
    if args.benchmark_command == "power":  # REQ-010
        from . import power as pw
        from .fsutil import canonical_json as _cj

        if escapes_root(args.effects) or not inside(root, args.effects) or not (root / args.effects).is_file():
            print(f"steward: no effects file {args.effects} in this repository", file=sys.stderr)
            return EXIT_USAGE
        try:
            effects = pw.read_effects(root / args.effects)
            shrinks = [float(s) for s in args.shrink.split(",")]
            sizes = [int(n) for n in args.n.split(",")]
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        if not (0 < args.alpha < 1) or args.reps < 10 or any(n < 2 for n in sizes):
            print("steward: alpha in (0, 1), --reps at least 10, every --n at least 2", file=sys.stderr)
            return EXIT_USAGE
        rows = pw.table(effects, args.test, args.alpha, shrinks, sizes, args.reps, args.seed)
        out_rel = pw.record_path(args.contract)
        doc = {"schema": "steward.power/0.1", "contract": c.id, "effects": args.effects,
               "effects_sha256": pw.effects_sha(root / args.effects), "test": args.test, "alpha": args.alpha,
               "reps": args.reps, "seed": args.seed, "shrinks": shrinks, "sizes": sizes, "table": rows}
        from .fsutil import safe_write

        safe_write(root, out_rel, _cj(doc).encode("utf-8"))
        for r in rows:
            print(f"n={r['n']:<5} shrink={r['shrink']:<5g} power={r['power']:.3f}")
        print(f"wrote {out_rel} (planning only: it is as good as the development effects)")
        return EXIT_OK
    if args.benchmark_command == "results":
        rf = c.results.file if c.results else None
        if rf is None or escapes_root(rf) or not inside(root, rf) or not (root / rf).is_file():
            print("steward: the contract declares no [results] file in this repository, or it does not exist", file=sys.stderr)
            return EXIT_DATAERR
        try:
            text = (root / rf).read_bytes().decode("utf-8-sig")  # OSError is reported below (K10)
            doc = tomllib.loads(text, parse_float=ev._exact_float) if rf.endswith(".toml") else ev.loads_exact(text, strict_keys=True)
        except (ValueError, UnicodeDecodeError, ValueError, RecursionError, OSError) as e:
            print(f"steward: the results file cannot be read: {e}", file=sys.stderr)
            return EXIT_DATAERR
        try:
            exact = [t.get("value") for t in tomllib.loads(raw.decode("utf-8"), parse_float=ev._exact_float).get("thresholds") or []]
        except (ValueError, RecursionError, AttributeError):
            exact = []
        r = bm.analyze_results(doc, c, exact)
        if wants_json(args):
            write_json(args, {
                "cells": r["cells"], "missing": r["missing"], "thresholds": r["thresholds"],
                "problems": [{"status": st, "code": code, **d} for st, code, d in r["problems"]],
            })
        else:
            for cell, v in r["cells"].items():
                print(f"{cell}: {v}")
            for cell in r["missing"]:
                print(f"missing {cell}")
            for st, code, d in r["problems"]:
                if code != "R-47.missing_result":
                    print(f"{st} {code}: {d.get('field') or ''} {d.get('message') or d.get('value') or ''}".rstrip())
            for t in r["thresholds"]:
                print(f"threshold {t['state']}: {t.get('message', t['split'])}")
            print("thresholds are reported, not gating: accepting the result is the human's decision.")
        return EXIT_OK if not blocking(r["problems"]) else 1
    a = bm.analyze(root, c)
    if wants_json(args):
        write_json(args, {
            "counts": a["counts"], "id_overlap": a["id_overlap"], "group_overlap": a["group_overlap"],
            "time_range": a["time_range"], "checked": a["checked"],
            "problems": [{"status": st, "code": code, **d} for st, code, d in a["problems"]],
        })
    else:
        for name, n in a["counts"].items():
            span = a["time_range"].get(name)
            print(f"{name}: {n} samples" + (f", {span[0]} .. {span[1]}" if span else ""))
        for o in a["id_overlap"]:
            print(f"ID overlap {o['splits'][0]}/{o['splits'][1]}: {o['count']} ({', '.join(o['ids'])})")
        for o in a["group_overlap"]:
            print(f"group overlap {o['splits'][0]}/{o['splits'][1]}: {o['count']} ({', '.join(o['groups'])})")
        for st, code, d in a["problems"]:
            if code not in ("R-45.id_overlap", "R-45.group_overlap"):
                print(f"{st} {code}: {d.get('path') or ''} {d.get('message') or d.get('value') or ''}".rstrip())
        print(f"checked: {', '.join(a['checked'])}. Undeclared leakage types are not checked.")
    return EXIT_OK if not blocking(a["problems"]) else 1


def cmd_sprint(args: argparse.Namespace) -> int:
    import datetime as _dt

    from . import sprint as sp

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    c = args.sprint_command
    if c == "plan":
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", args.id):
            print("steward: a sprint id is lower-case letters, digits, '.', '_' or '-'", file=sys.stderr)
            return EXIT_USAGE
        dest = sp.path(root, args.id)
        if dest.exists():
            print(f"steward: {dest.relative_to(root).as_posix()} exists; edit it, or choose another id", file=sys.stderr)
            return EXIT_USAGE
        start = _dt.datetime.fromisoformat(args.start) if args.start else _dt.datetime.now().astimezone().replace(microsecond=0)
        if start.tzinfo is None:
            print("steward: --start needs its time zone", file=sys.stderr)
            return EXIT_USAGE
        try:
            text = sp.draft(root, cfg, args.id, args.source, args.milestone, start, args.hours)
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        sf, err = sp.validate_file(dest)
        print(f"drafted {dest.relative_to(root).as_posix()}: {len(sf.task) if sf else 0} task(s). Edit it (agents, "
              "prompts, done commands, needs), then: steward sprint check " + args.id)
        if err:
            print(f"note: {err}")
        return EXIT_OK
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", args.id):  # V10 (0.13.0): an id, never a path
        print("steward: a sprint id is lower-case letters, digits, '.', '_' or '-'", file=sys.stderr)
        return EXIT_USAGE
    p = sp.path(root, args.id)
    if p.is_symlink() or any(q.is_symlink() for q in (root / "development", root / sp.DIR)):
        print(f"steward: {sp.DIR}/{args.id}.toml is reached through a link; refused", file=sys.stderr)
        return EXIT_USAGE
    if not p.is_file():
        print(f"steward: no sprint {args.id} ({DIR_HINT})", file=sys.stderr)
        return EXIT_USAGE
    sf, err = sp.validate_file(p)
    if sf is None:
        print(f"steward: {p.relative_to(root).as_posix()} is not valid: {err}", file=sys.stderr)
        return EXIT_DATAERR
    if sf.sprint.id != args.id:
        print(f"steward: {p.name} declares sprint id {sf.sprint.id!r}; the file name and the id must agree", file=sys.stderr)
        return EXIT_DATAERR
    if c == "check":
        print(f"{sf.sprint.id}: {len(sf.task)} task(s) in this order: {', '.join(sp.order(sf))}; dispatch "
              f"{sf.sprint.dispatch}; window {sf.sprint.window.start.isoformat()} – {sf.sprint.window.end.isoformat()}")
        if sf.sprint.window.end < _dt.datetime.now(_dt.timezone.utc):
            print("note: the window has ended")
        tasks = {t.id: t for t in sf.task}
        for tid in sp.order(sf):  # STW-051: the permissions each task runs with
            print(f"permissions: {tid}: {sp.permission_summary(tasks[tid])}")
        print("denied for every agent task: " + ", ".join(sp.DEFAULT_DENY))
        auto = [tid for tid in sp.order(sf) if tasks[tid].agent == sp.AUTO]
        if auto:  # D02: the order an auto task is tried in, and who can run now
            from . import delegation as _dg

            print(f"delegation: {', '.join(auto)}: " + _dg.order_text(cfg))
            if cfg.delegation is not None:
                try:
                    now_ = _dt.datetime.now(_dt.timezone.utc)
                    names = [*cfg.delegation.workers, cfg.delegation.master]
                    avail = _dg.states_now(root, names, now_)
                    print("delegation: now " + "; ".join(
                        _dg.said(n, a) +(" (master)" if n == cfg.delegation.master else "")
                        for n, a in avail.items()))
                except ValueError as e:
                    print(f"warning: {e}")
            else:
                print(f"warning: {', '.join(auto)} cannot start: there is no [delegation] in steward.toml")
        for line in sp.warnings(sf):
            print(f"warning: {line}")
        for line in sp.signing_advice(sf):
            print(f"signatures: {line}")
        return EXIT_OK
    if c == "watch":
        try:
            return sp.watch(root, sf.sprint.id, poll=max(0.1, args.poll))
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_DATAERR
        except KeyboardInterrupt:
            return 130
    if c == "signatures":
        for line in sp.signing_advice(sf):
            print(line)
        return EXIT_OK
    try:
        if c == "start":
            for line in sp.signing_advice(sf):
                print(f"signatures: {line}")
            return sp.dispatch(root, cfg, sf, watch=args.watch, on_fault=lambda e: args.fault_hint(EXIT_OK, e))
        lg = sp.led(root, sf.sprint.id, cfg.steward.repo_id)
        if c in ("go", "hold", "skip"):
            if args.task not in {t.id for t in sf.task}:
                print(f"steward: no task {args.task} in sprint {sf.sprint.id}", file=sys.stderr)
                return EXIT_USAGE
            lg.append("order", {"task": args.task, "order": c, "by": "human",
                                **({"retry": True} if c == "go" and args.retry else {}),
                                **({"reason": args.reason} if c == "skip" else {})})
            print(f"{sf.sprint.id} {args.task}: {c}" + (" (retry)" if c == "go" and args.retry else ""))
            return EXIT_OK
        if c in ("recheck", "add", "accept", "rework") and args.task not in {t.id for t in sf.task}:
            print(f"steward: no task {args.task} in {p.relative_to(root).as_posix()}", file=sys.stderr)
            return EXIT_USAGE
        if c in ("accept", "rework"):  # D02: the master's review step; merging stays the master's own step
            say = lambda m: print(m, file=sys.stderr if m.startswith("steward:") else sys.stdout)  # noqa: E731
            if c == "accept":
                return sp.accept(root, cfg, sf, args.task, out=say)
            return sp.rework(root, cfg, sf, args.task, args.note, args.to, out=say)
        if c == "recheck":
            code = sp.recheck(root, cfg, sf, args.task,
                              out=lambda m: print(m, file=sys.stderr if m.startswith("steward:") else sys.stdout))
            return code
        if c == "add":
            planned = sp.plan(sp.events(root, sf.sprint.id))
            if planned is None:
                print(f"steward: sprint {sf.sprint.id} has not opened; it opens with every task in its file",
                      file=sys.stderr)
                return EXIT_USAGE
            if args.task in planned:
                print(f"steward: {args.task} is already in sprint {sf.sprint.id}", file=sys.stderr)
                return EXIT_USAGE
            lg.append("added", {"task": args.task, "by": "human"})
            print(f"{sf.sprint.id} {args.task}: added; it is planned like the others (order it with steward sprint go)")
            return EXIT_OK
        if c == "reload":  # W12b (F7): a change made while a task ran is used only on this order
            lg.append("order", {"order": "reload", "by": "human"})
            print(f"{sf.sprint.id}: reload ordered; the dispatcher reads {p.relative_to(root).as_posix()} again at its "
                  "next look (a running task keeps the definition it started with)")
            return EXIT_OK
        if c == "stop":
            lg.append("stop", {"now": bool(args.now), "by": "human"})
            print(f"{sf.sprint.id}: stop recorded" + (" (running tasks are stopped too)" if args.now else ""))
            return EXIT_OK
        st = sp.states(sf, sp.events(root, sf.sprint.id))
        if c == "status":
            if wants_json(args):  # STW-052: per task its times, run and log, commits, files and last tool step
                write_json(args, sp.status_doc(root, sf))
                return EXIT_OK
            from .newest import newest_first

            latest: dict[str, str] = {}
            for e in sp.events(root, sf.sprint.id):
                if e.get("task") in st and isinstance(e.get("time"), str):
                    latest[e["task"]] = e["time"]
            for tid in newest_first(sp.order(sf), latest.get, str):  # X05: the task changed last first
                s = st[tid]
                extra = "; ordered" if s.get("go") else "; held" if s.get("hold") else ""
                if s["state"] in ("running", "checking") and s.get("log"):
                    extra += f"; log {s['log']}"  # S7: where its output is
                print(f"{tid:<10} {s['state']:<9} {s.get('branch') or ''}{extra}" + (f"  ({s['note']})" if s.get("note") else ""))
            ws = sp.window_state(sf)  # S11: a window that is not open is said
            if ws == "not open":
                print(f"window: opens at {sf.sprint.window.start.isoformat()}; nothing starts before it")
            elif ws == "ended":
                print(f"window: ended at {sf.sprint.window.end.isoformat()}; nothing more starts")
            return EXIT_OK
        if c == "report":
            text = sp.report(root, sf)
            from .fsutil import open_dir_beneath as _odb
            from .release import write_in_dir

            dfd = _odb(root, tuple(Path(sp.DIR).parts))  # V15: never written through a link
            try:
                write_in_dir(dfd, f"{sf.sprint.id}-report.md", text.encode("utf-8"))
            finally:
                os.close(dfd)
            print(text, end="")
            return EXIT_OK
    except ValueError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    return EXIT_USAGE


DIR_HINT = "sprints live in development/sprints/; draft one with: steward sprint plan ID"


def cmd_pins(args: argparse.Namespace) -> int:
    from . import authorize as az
    from . import pins as pn

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if not cfg.pin:
        print("steward: no [[pin]] declared in steward.toml", file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.pins_command == "status":
            rows = pn.status(root, cfg)
            if wants_json(args):
                write_json(args, {"pins": rows})
                return EXIT_OK
            for r in rows:
                print(f"{r['state']:<16} {r['name']}: {r['package']} {r['version']}" +
                      (f"  (deprecated: {r['deprecated']['reason']})" if r.get("deprecated") else ""))
                for why in r["reasons"]:
                    print(f"{'':17}{why}")
                for d in r.get("caller_detail") or []:  # REQ-020: the rule that found each caller
                    print(f"{'':17}caller {d['path']} ({d['via']}" + ("; ignored: ignore_callers" if d.get("ignored") else "") + ")")
                if r.get("object"):
                    print(f"{'':17}to retire, the human signs: steward authorize prepare pin.retire --object {r['object']} "
                          "--expires YYYY-MM-DDTHH:MM:SSZ, then steward authorize sign <nonce>")
            return EXIT_OK
        if args.pins_command == "retire":
            if cfg.policy is None:
                print("steward: retiring a pin needs a signed approval: add a [policy] table first", file=sys.stderr)
                return EXIT_USAGE
            if not args.authorization:
                print("steward: give --authorization TAG (a signed pin.retire approval of this pin's plan)", file=sys.stderr)
                return EXIT_USAGE
            rep = run_check(root, areas=["policy"])  # Z3 (0.17.0): never act under unapproved policy (resume too)
            r33 = next((r for r in rep["verdict"]["results"] if r["rule"] == "R-33"), None)
            if r33 is None or r33["status"] != "PASS":
                print(f"steward: R-33 is {r33['status'] if r33 else 'missing'}: the policy is not the approved one; "
                      "nothing was retired", file=sys.stderr)
                return EXIT_DATAERR
            if args.resume:  # AA1: the approval was spent by the interrupted run; it still must verify for this plan
                v = az.verify(root, cfg, args.authorization, action="pin.retire", require_pinned=True, consumed=set())

                def _consume_once() -> None:
                    if v.payload["nonce"] not in az.consumed_nonces(root, cfg):
                        az.consume(root, cfg, v, f"pin.retire {args.name}")
                rec = pn.retire(root, cfg, args.name, v, consume=_consume_once, resume=True)
            else:
                v = az.verify(root, cfg, args.authorization, action="pin.retire", require_pinned=True)
                rec = pn.retire(root, cfg, args.name, v, consume=lambda: az.consume(root, cfg, v, f"pin.retire {args.name}"))
            print(f"retired {args.name}: kept {rec['kept']} ({rec['artifact_sha256'][:12]}); removed "
                  f"{len(rec['removed'])} entr(ies), recorded in {pn.settings(cfg).ledger}. Commit the removal.")
            return EXIT_OK
        rec = pn.restore(root, cfg, args.name)
        print(("restored" if rec["ok"] else "NOT restored (it stays retired)") + f" {args.name}"
              + "".join(f"; {k} exit {c}" for k, c in rec["runs"].items()))
        c = (rec["from_commit"] or "COMMIT")[:12]
        if rec["recoverable_from_git"]:
            import shlex as _sh

            print(f"its version-specific files are in git at {c}: git checkout {c} -- "
                  + " ".join(_sh.quote(x) for x in rec["recoverable_from_git"]))
        if rec["not_in_git"]:
            print(f"not in git at {c} with the removed bytes, so not recoverable from it: {', '.join(rec['not_in_git'])}")
        return EXIT_OK if rec["ok"] else EXIT_DATAERR
    except az.AuthError as e:
        print(f"steward: NOT AUTHORIZED: {e.step}: {e.message}", file=sys.stderr)
        return 1
    except pn.PinError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR


def cmd_audit(args: argparse.Namespace) -> int:
    from . import audit as au

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        doc = au.progress(root, cfg)
    except Exception as e:  # noqa: BLE001 - W3: the cause is named, never its text (it can hold a path)
        print(f"steward: the audit could not be completed ({type(e).__name__})", file=sys.stderr)
        return EXIT_DATAERR
    if wants_json(args):
        write_json(args, doc)
    else:
        print(au.render(doc))
    return EXIT_OK


def cmd_plans(args: argparse.Namespace) -> int:
    from . import plans

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        doc = plans.document(root, cfg)
    except ValueError as e:
        print(f"steward: invalid plan record: {str(e).splitlines()[0][:220]}", file=sys.stderr)
        return EXIT_DATAERR
    except OSError:
        print("steward: a plan record could not be read", file=sys.stderr)
        return EXIT_DATAERR
    if wants_json(args):
        write_json(args, doc)
    else:
        print(plans.render(doc))
    return EXIT_OK


def cmd_timeline(args: argparse.Namespace) -> int:
    from pydantic import ValidationError as _VE

    from . import milestones as ms

    if not args.events and (args.all_projects or args.format == "svg"):
        print("steward: --all-projects and --format svg need --events", file=sys.stderr)
        return EXIT_USAGE
    if args.events and args.json:
        print("steward: --events has no legacy --json form; use --format json", file=sys.stderr)
        return EXIT_USAGE
    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        from .cockpit import parse_now

        now = parse_now(args.now) if args.now else None
    except ValueError as e:
        print(f"steward: --now: {e}", file=sys.stderr)
        return EXIT_USAGE
    if args.events:
        return _timeline_events(args, root, cfg, now)
    try:
        rows = ms.timeline(root, cfg) if now is None else ms.timeline(root, cfg, now=now)
        payload = {"milestones": rows}
        if args.format == "json":
            from . import drift

            payload["drift"] = drift.document(root, cfg, rows)
    except _VE as e:
        err = e.errors()[0]
        print(f"steward: {ms.FILE} is not valid: {'.'.join(map(str, err['loc']))}: {err['msg']}", file=sys.stderr)
        return EXIT_DATAERR
    except ValueError as e:
        print(f"steward: {ms.FILE} is not valid: {str(e).splitlines()[0][:200]}", file=sys.stderr)
        return EXIT_DATAERR
    except OSError:
        print("steward: a timeline record could not be read", file=sys.stderr)
        return EXIT_DATAERR
    if wants_json(args):
        write_json(args, payload)
    else:
        print(ms.render(rows))
    return EXIT_OK


def _timeline_events(args: argparse.Namespace, root: Path, cfg: Any, now: Any) -> int:
    """`steward timeline --events` (0.24.0, P02): the research timeline, and with `--format svg` the schedule."""
    from pydantic import ValidationError as _VE

    from . import charts
    from . import timeline_events as te
    from .cockpit import parse_now
    from .interface import OTHER_SCHEMAS

    try:
        doc = te.document(root, cfg, now or parse_now(None), all_projects=args.all_projects,
                          explicit_now=now is not None)
    except _VE as e:
        err = e.errors()[0]
        print(f"steward: a timeline record is not valid: {'.'.join(map(str, err['loc']))}: {err['msg']}", file=sys.stderr)
        return EXIT_DATAERR
    except OSError:
        print("steward: a timeline record could not be read", file=sys.stderr)
        return EXIT_DATAERR
    if args.format == "json":
        write_document({"schema": OTHER_SCHEMAS["timeline --events"], **doc})
    elif args.format == "svg":
        sys.stdout.write(charts.schedule(doc, title=f"Research schedule: {cfg.steward.project}"))
    else:
        print(te.render(doc))
    return EXIT_OK


def cmd_decisions(args: argparse.Namespace) -> int:
    from . import decisions
    from .interface import OTHER_SCHEMAS

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    try:
        doc = decisions.document(root, cfg)
    except OSError:
        print("steward: a decision record could not be read", file=sys.stderr)
        return EXIT_DATAERR
    if args.format == "json":
        write_document({"schema": OTHER_SCHEMAS["decisions"], **doc})
    else:
        print(decisions.render(doc))
    return EXIT_OK


def cmd_cockpit(args: argparse.Namespace) -> int:
    """`steward next`, `steward tidy` and `steward notifications` (0.21.0, W03)."""
    from pydantic import ValidationError as _VE

    from . import cockpit as ck
    from . import milestones as ms
    from .interface import OTHER_SCHEMAS

    if getattr(args, "brief", False) and args.format == "json":
        print("steward: --brief is a text form; --format json already holds every field", file=sys.stderr)
        return EXIT_USAGE
    if getattr(args, "archive", None) and args.format == "json":
        print("steward: --archive prints what it moved as text; run `steward tidy --format json` to list", file=sys.stderr)
        return EXIT_USAGE
    if args.command == "notifications" and args.days < 1:
        print("steward: --days must be 1 or more", file=sys.stderr)
        return EXIT_USAGE
    try:
        now = ck.parse_now(args.now)
    except ValueError as e:
        print(f"steward: --now: {e}", file=sys.stderr)
        return EXIT_USAGE
    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if args.command == "tidy" and args.archive:
        try:
            moves = ck.archive(root, cfg, args.archive)
        except ck.ArchiveError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_DATAERR
        for src, dest in moves:
            print(f"moved {src} -> {dest}")
        print("Review the change, update the board if it lists these tasks, and commit it (history stays in git).")
        return EXIT_OK
    against = None
    if args.command == "notifications" and args.against is not None:
        try:
            against = json.loads(args.against.read_text(encoding="utf-8"))
            # W12 F13: the shape read below (verdict.gates, a list), checked here so a malformed report exits 65
            verdict = against.get("verdict") if isinstance(against, dict) else None
            if not isinstance(verdict, dict) or not isinstance(verdict.get("gates", []), list):
                raise ValueError("not a report")
        except (OSError, ValueError, RecursionError) as e:
            message = f"--against: {args.against} is not a readable check report ({type(e).__name__})"
            print(f"steward: {message}", file=sys.stderr)
            if args.format == "json":
                write_document(error_document("invalid_input", message, EXIT_DATAERR,
                                              "pass a report written by `steward check --format json`"))
            return EXIT_DATAERR
    try:
        if args.command == "next":
            doc = ck.next_doc(root, cfg, now)
        elif args.command == "tidy":
            doc = ck.tidy(root, cfg, now)
        else:
            doc = ck.notifications(root, cfg, now, args.days, against, args.against.name if args.against else None)
    except (_VE, ValueError) as e:
        msg = e.errors()[0]["msg"] if isinstance(e, _VE) else str(e).splitlines()[0][:200]
        print(f"steward: a record could not be read ({ms.FILE} or a ledger): {msg}", file=sys.stderr)
        return EXIT_DATAERR
    if args.format == "json":
        write_document({"schema": OTHER_SCHEMAS[args.command], "tool_version": __version__, **doc})
    elif args.command == "next":
        print(ck.render_next(doc, brief=args.brief))
    elif args.command == "tidy":
        print(ck.render_tidy(doc))
    else:
        print(ck.render_notifications(doc))
    return EXIT_OK


def _storage_clean(args: argparse.Namespace, root: Path, cfg: Any) -> int:
    """`steward storage scan` (read-only) and `steward storage clean --plan | --apply` (DESIGN_BRIEF_storage_cleanup)."""
    from dataclasses import asdict

    from . import cleanup as cu
    from .ledger import Ledger

    if args.storage_command == "scan" or args.plan:
        cands = cu.scan(root, cfg)
        if args.storage_command == "scan" and wants_json(args):
            rows = [{k: v for k, v in asdict(c).items() if k not in ("real", "ident")} for c in cands]
            write_json(args, {"candidates": rows})
            return EXIT_OK
        if args.storage_command == "scan":
            by_vol: dict[str, int] = {}
            for c in sorted(cands, key=lambda c: (c.cls, -c.size)):
                state = "shared: listed only" if c.cls == "shared" else ("kept: " + "; ".join(c.refusals)) if c.refusals \
                    else "cleanable" if c.cls != "linked" else "cleanable only with --class linked"
                print(f"{c.cls:8} {cu.human(c.size):>9}  {c.path}  [{'external disk' if c.external else 'startup disk'} "
                      f"{c.volume}]  {state}")
                for u in c.users:
                    print(f"{'':19}also used: {u}")
                if c.cleanable and c.cls != "linked":
                    by_vol[c.volume] = by_vol.get(c.volume, 0) + c.size
            for v, n in sorted(by_vol.items()):
                print(f"cleanable on {v}: {cu.human(n)}")
            print("Nothing was changed or deleted. Plan a cleanup with: steward storage clean --plan")
            return EXIT_OK
        classes = set(args.classes or cu.DEFAULT_CLASSES)
        chosen = [c for c in cands if c.cls in classes and c.cleanable]
        if not chosen:
            print("nothing to clean in the chosen classes")
            return EXIT_OK
        from .fsutil import LinkRefused

        try:
            plan = cu.write_plan(root, chosen)
        except LinkRefused:
            print("steward: .steward/cleanup is reached through a link; no plan was written", file=sys.stderr)
            return EXIT_DATAERR
        for c in chosen:
            print(f"planned {c.cls:8} {cu.human(c.size):>9}  {c.path}" + (f"  (also used: {'; '.join(c.users)})" if c.users else ""))
        print(f"plan: {plan.relative_to(root).as_posix()}. Nothing is deleted until you run, in a terminal:\n"
              f"  steward storage clean --apply {plan.relative_to(root).as_posix()}")
        return EXIT_OK
    import json as _json

    plan = args.apply if args.apply.is_absolute() else Path.cwd() / args.apply
    try:
        doc = _json.loads(plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"steward: {args.apply} is not a cleanup plan", file=sys.stderr)
        return EXIT_USAGE
    if doc.get("schema") != "steward.cleanup_plan/0.1" or doc.get("root") != str(root.resolve()):
        print("steward: the plan is not this project's", file=sys.stderr)
        return EXIT_USAGE
    if not sys.stdin.isatty():  # SC: an agent never confirms a deletion; there is no --yes
        print("steward: storage clean --apply asks before each deletion; run it in a terminal", file=sys.stderr)
        return EXIT_USAGE
    from .ledger import verify as _lverify

    lp = root / cu.LEDGER
    if lp.is_file() and (lambda v: v.errors or v.torn_tail)(_lverify(lp)):  # V7: refuse before deleting anything
        print(f"steward: {cu.LEDGER} is not intact; deletions could not be recorded. Recover it first", file=sys.stderr)
        return EXIT_DATAERR
    led = Ledger(lp, "storage-cleanup", cfg.steward.repo_id, base=root)  # V7: its folder reached without links
    try:  # V7 (0.15.0): the ledger's folder is reachable and writable before anything is deleted
        from .fsutil import open_dir_beneath as _odb

        _vfd = _odb(root, tuple(Path(cu.LEDGER).parent.parts))
        _ok = os.access(_vfd, os.W_OK) if os.access in os.supports_fd else os.access(root / Path(cu.LEDGER).parent, os.W_OK)
        os.close(_vfd)
        if not _ok or (lp.exists() and (lp.is_symlink() or not os.access(lp, os.W_OK))):
            raise OSError("not writable")

        class _Probe(Exception):
            pass

        def _probe(entries):  # V7 (0.17.0): take the ledger's own lock and read its chain, appending nothing
            raise _Probe()
        try:
            led.transaction(_probe)
        except _Probe:
            pass
    except Exception:  # noqa: BLE001
        print(f"steward: {cu.LEDGER} cannot be written; nothing was deleted", file=sys.stderr)
        return EXIT_DATAERR
    freed: dict[str, int] = {}
    current = cu.scan(root, cfg, check_users=False)
    for e in doc.get("entries", []):
        shown = e["path"] if e["path"].startswith("~") or e["path"].startswith("/") else e["path"]
        where = (f"{shown} (that is {cu.tilde(e['real'])}) on the {'external disk' if e['external'] else 'startup disk'} "
                 f"{e['volume']}")
        why = cu.recheck(root, cfg, e, current)
        if why:
            print(f"skipped {where}: {'; '.join(why)}")
            continue
        projects = [u for u in e.get("users_now", []) if u.startswith("project ")]  # V4: read afresh, not from the plan
        print(f"\n{e['cls']}: {where}, {cu.human(e['size'])}" + (f"\n  also used by: {', '.join(projects)}" if projects else "")
              + ("\n  note: not every one of your processes could be inspected, so an open file there cannot be ruled out"
                 if e.get("blind") else ""))
        want = "shared" if projects else "proceed" if e.get("blind") else "y"
        prompt = ("Other projects rely on it. Type 'shared' to delete it anyway: " if projects else
                  "Type 'proceed' to delete it anyway: " if e.get("blind") else "Delete it? [y/N] ")
        if input(prompt).strip().lower() != want:
            print("kept")
            continue
        try:
            n = cu.delete(e)
        except OSError as err:
            left = cu.size_of(Path(e["real"])) if os.path.lexists(e["real"]) else 0
            gone = max(0, int(e["size"]) - left)
            changed = gone or not os.path.lexists(e["real"]) or cu.entries_under(Path(e["real"])) != e.get("entries")
            if changed:  # V7: a partial deletion is recorded with what it removed (0.15.0: zero-byte files too)
                freed[e["volume"]] = freed.get(e["volume"], 0) + gone
                led.append("partial", {"class": e["cls"], "path": e["path"], "volume": e["volume"],
                                       "external": e["external"], "bytes": gone, "error": str(err)[:200],
                                       "confirmed": "in a terminal"})
                print(f"partly deleted ({cu.human(gone)} removed): {err}")
            else:
                print(f"not deleted ({err})")
            continue
        freed[e["volume"]] = freed.get(e["volume"], 0) + n
        led.append("deleted", {"class": e["cls"], "path": e["path"], "volume": e["volume"], "external": e["external"],
                               "bytes": n, "checks": "identity, volume, git, records, sealed data, runs, open files",
                               "confirmed": "in a terminal", "shared_with": projects})
        print(f"deleted ({cu.human(n)})")
    for v, n in sorted(freed.items()):
        print(f"freed on {v}: {cu.human(n)}")
    if not freed:
        print("nothing was deleted")
    return EXIT_OK


def cmd_storage(args: argparse.Namespace) -> int:
    import tomllib

    from . import storage as stg

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if args.storage_command in ("scan", "clean"):  # 0.13.0: works without a [storage] table
        return _storage_clean(args, root, cfg)
    if cfg.storage is None:
        print("steward: add a [storage] table to steward.toml", file=sys.stderr)
        return EXIT_USAGE
    if args.storage_command == "audit":  # red-team K12: the audit does not need the registry
        a = stg.audit(root, cfg.storage.caps, args.top)
        if wants_json(args):
            write_json(args, a)
        else:
            for d in a["directories"]:
                if d["state"] == "present":
                    print(f"{'OVER ' if d['over'] else 'ok   '} {d['path']}: {d['size_mb']} MB of {d['cap_mb']} MB")
                else:
                    print(f"{d['state']:5} {d['path']}")
            for f in a["largest_untracked"]:
                print(f"untracked {f['size_mb']:>10} MB  {f['path']}")
            print("Nothing was changed or deleted. Cleaning up is your decision.")
        return EXIT_OK
    if not stg.located(root, cfg.storage.artifacts):  # red-team K2
        print(f"steward: the artifact registry {cfg.storage.artifacts} resolves outside the repository", file=sys.stderr)
        return EXIT_USAGE
    reg_path = root / cfg.storage.artifacts
    try:
        reg = stg.load(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else stg.ArtifactsFile.model_validate({"schema": "steward.artifacts/0.1"})
    except (ValidationError, ValueError, RecursionError, UnicodeDecodeError):
        print(f"steward: {cfg.storage.artifacts} is not a valid artifact registry", file=sys.stderr)
        return EXIT_DATAERR
    if args.storage_command == "record":
        rel = Path(args.path).as_posix()
        if not stg.located(root, rel):
            print(f"steward: {rel} resolves outside the repository", file=sys.stderr)
            return EXIT_USAGE
        st = stg.measure(root, rel)
        if st["present"]:
            sha, size = st["sha256"], st["size"]
        elif st["annex"]:
            size, sha = st["annex"]
        else:
            print(f"steward: {rel} is not present and has no annex key; fetch it first", file=sys.stderr)
            return EXIT_DATAERR
        entry = stg.Artifact(path=rel, sha256=sha, size=size, retrieval=args.retrieval, tool=args.tool)
        reg.artifacts = [a for a in reg.artifacts if a.path != rel] + [entry]
        stg.write_registry(reg_path, reg)
        print(f"recorded {rel}: sha256 {sha}, {size} bytes, in {cfg.storage.artifacts}")
        return EXIT_OK
    a = stg.evaluate(root, reg, cfg.storage, False)
    if wants_json(args):
        problems = [{"status": status, "code": code, **detail} for status, code, detail in a["problems"]]
        write_json(args, {"artifacts": a["artifacts"], "problems": problems})
    else:
        for x in a["artifacts"]:
            print(f"{x['state']:8} {x['path']}")
        for s_, c_, d in a["problems"]:
            print(f"{s_} {c_}: {d.get('path') or ''} {d.get('message') or ''}".rstrip())
    return EXIT_OK if not any(s_ in ("FAIL",) for s_, _, _ in a["problems"]) else 1


def cmd_issues(args: argparse.Namespace) -> int:
    from . import issues
    from .ledger import LedgerError

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.exchange is None:
        print('steward: add an [exchange] table with code = "ABC" to steward.toml', file=sys.stderr)
        return EXIT_USAGE
    if args.command == "issues":
        try:
            groups = issues.inbox(root, cfg.exchange.code)
        except (OSError, ValueError, LedgerError):
            print("steward: could not read the exchange inbox; run steward check --rule R-53", file=sys.stderr)
            return EXIT_DATAERR
        if args.format == "json":
            write_json(args, {"groups": groups})
        else:
            if not groups:
                print("No toolkit issue reports received.")
            from .newest import id_key, newest_first

            filed = issues.filed_dates(root, cfg.exchange.code)  # X05: newest first, by the latest report filed
            for group in newest_first(groups, lambda g: max((filed.get(i) or "" for i in g["items"]), default=None),
                                      lambda g: max(g["items"], key=id_key, default="")):
                print(f"{group['fingerprint']} · {group['count']} report(s) · versions "
                      f"{', '.join(group['versions'])} · projects {', '.join(group['projects'])} "
                      f"({', '.join(sorted(group['items'], key=id_key, reverse=True))})")
        return EXIT_OK

    try:
        last = issues.read_last_error(root) if args.from_last_error else None
    except (OSError, ValueError):
        print("steward: no readable last toolkit error; use steward issue with a description", file=sys.stderr)
        return EXIT_DATAERR
    try:
        item_id, repeated = issues.file_issue(root, cfg, args.description, last)
    except issues.IssueError as error:
        print(f"steward: {error}", file=sys.stderr)
        return EXIT_DATAERR
    except (OSError, ValueError, LedgerError):
        print("steward: could not file the report; check the exchange layout, ledger and peer ID records",
              file=sys.stderr)
        return EXIT_DATAERR
    if repeated:
        print(f"{item_id}: seen again (recorded in exchange/log.jsonl)")
    else:
        print(f"{item_id}: exchange/outbox/{item_id}.md (filed)")
    return EXIT_OK


def _removal_advice(root: Path, xc: Any, iid: str) -> None:
    """After superseded / withdrawn: say whether the file may go, by the same criterion R-53 uses (AB5)."""
    if xc.removable(iid, *_ctx_without(xc, root, iid)):
        print(f"Its file may now be removed (git rm exchange/inbox/{iid}.md): the ledger keeps the receipt and the "
              "file's hash, and R-53 accepts it.")
    else:
        print(f"Keep exchange/inbox/{iid}.md: its removal could not be checked (a receipt without a hash, from before "
              "0.9.0; a response to it without an Answers binding; or a replacement that is not received here), so "
              "R-53 would report it missing.")


def _ctx_without(xc: Any, root: Path, iid: str) -> tuple[Any, Any, Any]:
    """The removal context as it would be once this item's file is gone (AC4: what R-53 will then see)."""
    hist, inbox, answers = xc.removal_context(root)
    return hist, inbox - {iid}, answers


def _exchange_name(root: Path, cfg: Any, name: str) -> str:
    from .privacy import private_match

    return "(withheld)" if private_match(root, cfg, name) else name


def _print_exchange_delivery(root: Path, cfg: Any, status: Any, *, advisories: bool = False) -> None:
    from .exchange import delivery_advice

    for peer in sorted(status.unavailable):
        print(f"Exchange: {_exchange_name(root, cfg, peer)}: could not check peer; check its path, ref, or duplicate code.")
    unchecked: dict[str, int] = {}
    for deliveries, direction in ((status.incoming, "from"), (status.outgoing, "to")):
        for delivery in deliveries:
            if delivery.state == "received":
                continue
            item = delivery.item
            iid = _exchange_name(root, cfg, item.id)
            peer = _exchange_name(root, cfg, item.from_ if direction == "from" else item.to)
            if advisories and direction == "to":
                warning = delivery_advice(delivery, cfg.exchange.delivery_days, iid, peer)
                if warning:
                    print(f"R-53 (advisory): {warning}.")
                    continue
            if delivery.state == "unchecked":  # one line per peer, not one per item (token cost, STW-009)
                unchecked[peer] = unchecked.get(peer, 0) + 1
                continue
            message = {
                "waiting": "waiting to be received",
                "changed": "receipt covers different bytes",
                "unchecked": "receiver's ledger could not be checked",
            }[delivery.state]
            print(f"Exchange: {iid} {direction} {peer}: {message}.")
    for peer, n in sorted(unchecked.items()):
        print(f"Exchange: {n} item(s) with {peer}: delivery not checked (declare {peer} under [exchange] peers to check it).")


def cmd_exchange(args: argparse.Namespace) -> int:
    import datetime as _dt
    import tomllib

    from . import exchange as xc
    from .ledger import LedgerError

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if cfg.exchange is None:
        print('steward: add an [exchange] table with code = "ABC" to steward.toml', file=sys.stderr)
        return EXIT_USAGE
    code = cfg.exchange.code
    if args.exchange_command == "init":
        try:
            created = xc.init(root, code)
        except xc.BoundaryError as error:
            print(f"steward: refused: {error}", file=sys.stderr)
            return EXIT_DATAERR
        for m in created or ["(already present)"]:
            print(f"exchange: {m}")
        return EXIT_OK
    if args.exchange_command != "status" and not xc.folder(root).is_dir():
        print("steward: no exchange/ folder; run: steward exchange init", file=sys.stderr)
        return EXIT_USAGE

    def find(iid: str) -> tuple[str, Path] | None:
        for sub in xc.SUBDIRS:
            p = xc.folder(root) / sub / f"{iid}.md"
            if p.is_file():
                return sub, p
        return None

    class _Screen:
        """FB-018: an incoming item passes this project's own R-07 lists before it enters the ledger. `hides`
        tells whether an item ID matches a private term, so it is never printed (AB4)."""

        def __call__(self, rel: str, data: bytes) -> list[dict[str, Any]]:
            from . import privacy as pv

            return [] if getattr(args, "allow_terms", False) else pv.screen_incoming(root, cfg, rel, data)

        def hides(self, text: str) -> bool:
            from . import privacy as pv

            return pv.private_match(root, cfg, text)
    screen = _Screen()

    def retire_extra(iid: str) -> tuple[str | None, dict[str, Any] | None] | None:
        """superseded / withdrawn (FB-018): the note, and the replacing item; None after printing a usage error."""
        by = getattr(args, "by", None)
        if args.state != "superseded":
            if by:
                print("steward: --by goes with the superseded state only", file=sys.stderr)
                return None
            return args.note, None
        if not by or not xc.valid_id(by) or by == iid:
            print("steward: superseded needs --by ID, the received item that replaces this one", file=sys.stderr)
            return None
        rep_hit, own_hit = find(by), find(iid)
        if rep_hit is None or rep_hit[0] != "inbox" or own_hit is None or own_hit[0] != "inbox":
            print(f"steward: {iid} and {by} must both be received items in inbox/", file=sys.stderr)
            return None
        a = xc.parse(own_hit[1].read_text(encoding="utf-8"))[0]
        b = xc.parse(rep_hit[1].read_text(encoding="utf-8"))[0]
        if a.get("from") != b.get("from"):
            print(f"steward: {by} comes from {b.get('from')}, not from {a.get('from')}, the sender of {iid}", file=sys.stderr)
            return None
        if xc.receipt_sha(xc.states(root).get(by, [])) is None:  # AB6: a hashed receipt, not any state history
            print(f"steward: {by} has no receipt with a hash in the ledger; receive it first", file=sys.stderr)
            return None
        note = f"by {by}" + (f": {args.note}" if (args.note or "").strip() else "")
        return note, {"superseded_by": by}
    try:
        if args.exchange_command == "new":
            if args.oneway and not args.channel:
                print("steward: a one-way item needs --channel (where it is sent)", file=sys.stderr)
                return EXIT_USAGE
            peers, _ = xc.discover_peers(root, cfg.exchange)
            iid = xc.next_id(root, code, args.kind, peers)
            fields = {"schema": "steward.exchange/1", "id": iid, "kind": args.kind, "from": code, "to": args.to,
                      "title": args.title, "filed": _dt.date.today(), "against": args.against, "priority": args.priority,
                      "channel": args.channel, "sent": _dt.date.today() if args.oneway else None}
            body = "\n## Need\n\n## Proposed generic shape\n\n## Verify\n"
            text = xc.render(fields, body)
            item = xc.Item.model_validate(xc.parse(text)[0])
            if args.oneway:
                xc.ledger_ok(root)
                dest = xc.write_new(root, "oneway", f"{iid}.md", text.encode("utf-8"))
                xc.forget(dest)  # a one-way item records no state: release the held directory now
            else:
                dest = xc.file_outbox(root, cfg.steward.repo_id, item, text.encode("utf-8"))
            print(f"{iid}: {dest.relative_to(root).as_posix()}" + ("" if args.oneway else " (filed)"))
            return EXIT_OK
        if args.exchange_command == "receive":
            src = args.path
            if not src.is_file():
                print(f"steward: {src} not found", file=sys.stderr)
                return EXIT_USAGE
            source: dict[str, Any] = {"from": "file", **({"terms_allowed": True} if args.allow_terms else {})}
            try:
                iid, outcome = xc.receive(root, cfg.steward.repo_id, code, src.read_bytes(), source, screen)
            except xc.ItemSkipped as e:
                print(f"steward: {e}", file=sys.stderr)
                return EXIT_DATAERR
            if outcome.startswith("already received;"):  # FB-018: superseded or withdrawn here; nothing to do
                print(f"{iid}: {outcome}; not received again")
                return EXIT_OK
            if not outcome.startswith("received"):
                print(f"steward: {iid} is already in inbox/ ({outcome}; an inbox item is never replaced; a correction "
                      "is a new revision the sender files)", file=sys.stderr)
                return EXIT_DATAERR
            print(f"{iid}: received into exchange/inbox/ (acknowledged)" + outcome[len("received"):])
            return EXIT_OK
        if args.exchange_command == "pull":
            peers, ambiguous = xc.discover_peers(root, cfg.exchange)
            names = [args.peer] if args.peer else sorted(peers.keys() | ambiguous)
            for name in sorted(ambiguous.intersection(names)):
                print(f"steward: {_exchange_name(root, cfg, name)}: multiple registered checkouts; declare its path and ref",
                      file=sys.stderr)
            names = [name for name in names if name not in ambiguous]
            if not names and ambiguous:
                return EXIT_USAGE
            unknown = [n for n in names if n not in peers]
            if unknown or not names:
                print(f"steward: no such peer {', '.join(unknown) or '(none configured)'}; declare it in [exchange] peers",
                      file=sys.stderr)
                return EXIT_USAGE
            status = EXIT_DATAERR if not args.peer and ambiguous else EXIT_OK
            for name in names:
                label = "a peer (its code matches a private term)" if screen.hides(name) else name  # AD2
                try:
                    with xc.peer_revision(root, name, peers[name]) as (path, sha):
                        responses = xc.peer_outbox(path, sha, "responses")
                        files = [("outbox", f, d) for f, d in xc.peer_outbox(path, sha)] + \
                            [("responses", f, d) for f, d in responses]
                        peer_inbox = dict(xc.peer_outbox(path, sha, "inbox")) if responses else {}
                        peer_history = (xc.peer_history(path, sha) or {}) if peer_inbox else {}
                        if xc._peer_source(peers[name])[2]:  # AH2: a URL peer's IDs are recorded for offline numbering
                            verified = xc.peer_history(path, sha)
                            if verified is None:  # an unverifiable ledger is never recorded as an empty one
                                xc.forget_peer_ids(root, name)
                                print(f"steward: {label}: its ledger cannot be verified; its IDs are not recorded, so "
                                      "numbering stays refused for it", file=sys.stderr)
                                status = EXIT_DATAERR
                            else:
                                xc.record_peer_ids(root, name, set(verified) |
                                                   {f[:-3] for _, f, _ in files if xc.valid_id(f[:-3])})
                except xc.PeerError as e:
                    msg = str(e) if label == name else str(e).replace(name, "the peer")
                    print(f"steward: {msg}; not eligible for the two-way protocol. Use the one-way protocol: "
                          f"steward exchange new KIND --to {label if label == name else 'CODE'} --oneway --channel "
                          "WHERE", file=sys.stderr)
                    status = EXIT_DATAERR
                    continue
                taken = 0
                for sub, fname, data in files:
                    try:
                        head, _ = xc.parse(data.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError, ValueError, RecursionError):
                        print(f"{label}: {fname}: not a steward.exchange item; skipped")
                        continue
                    if head.get("to") != code:
                        continue
                    if head.get("schema") != f"steward.exchange/{xc.PROTOCOL_MAJOR}":
                        print(f"{label}: {fname}: protocol {head.get('schema')!r} differs from steward.exchange/{xc.PROTOCOL_MAJOR}; skipped")
                        continue
                    hid = head.get("id")
                    if xc.valid_id(hid) and not xc.states(root).get(hid) and \
                            (find(hid) is None or find(hid)[0] == "inbox"):  # AC3: new, or left without a receipt
                        # AD1: the format rule, then the term lists, both before anything is written for it
                        hits = [{"line": 0, "what": "a NUL byte: it cannot be checked as text"}] if b"\x00" in data \
                            else screen(f"{xc.FOLDER}/inbox/{hid}.md", data)
                        if hits:
                            print(f"{label}: {xc.TermsRefused(xc.shown(hid, screen), hits)}", file=sys.stderr)
                            status = EXIT_DATAERR
                            continue
                    target = head.get("responds_to") if head.get("kind") == "response" else None
                    if target and xc.valid_id(target) and find(target) is None:  # U4: a checked ID before any path  # DEF-011: our own item, held only in the peer's inbox
                        orig = peer_inbox.get(f"{target}.md")
                        try:
                            oh = xc.parse(orig.decode("utf-8"))[0] if orig is not None else {}
                        except (ValueError, UnicodeDecodeError, RecursionError):
                            oh = {}
                        try:  # U9 (0.13.0): the response itself first; then the whole original; then the peer's receipt
                            rsp_ok = xc.Item.model_validate(head).from_ == name
                            xc.Item.model_validate(oh)
                        except Exception:  # noqa: BLE001 - anything invalid imports nothing
                            rsp_ok, oh = False, {}
                        rtext = data.decode("utf-8", "replace")
                        ans = xc.answered(rtext)  # U9: a bound response names these bytes
                        if orig is None or (ans is None and re.search(r"^## Answers\s*$", rtext, re.M)) or \
                                (ans is not None and (ans[0] != target or ans[1] != __import__("hashlib").sha256(orig).hexdigest())):
                            rsp_ok = False  # 0.15.0: a malformed binding, or no original, imports nothing
                        if rsp_ok and oh.get("id") == target and oh.get("from") == code and oh.get("to") == name \
                                and xc.recorded_receipt(peer_history.get(target, [])) in (
                                    "unhashed", __import__("hashlib").sha256(orig).hexdigest()):
                            ohits = [{"line": 0, "what": "a NUL byte: it cannot be checked as text"}] if b"\x00" in orig \
                                else screen(f"{xc.FOLDER}/outbox/{target}.md", orig)  # AB2, AD1: the original, at its path
                            if ohits:
                                print(f"{label}: {xc.shown(target, screen)}: this project's own item, held in {label}'s "
                                      "inbox, hits this project's term lists at its outbox path; neither it nor the "
                                      f"response is imported (" + "; ".join(f"line {h['line']}: {h['what']}"
                                                                           for h in ohits[:10]) + ")", file=sys.stderr)
                                status = EXIT_DATAERR
                                continue
                            xc.ledger_ok(root)
                            dest = xc.write_new(root, "outbox", f"{target}.md", orig)
                            before = xc.entries_of(root, target)
                            try:
                                xc.set_state(root, cfg.steward.repo_id, target, "filed",
                                             f"imported unchanged from {name}'s inbox at {sha[:12]} (filed before the "
                                             "exchange protocol)", code, False, oh.get("kind"), place="outbox")
                            except Exception:
                                if not xc.keep_if_appended(root, dest, target, before, "filed"):  # U5
                                    xc.rollback(root, dest)
                                raise
                            else:
                                xc.forget(dest)
                            print(f"{label}: {target}: this project's own item, imported unchanged from {label}'s inbox")
                    try:
                        iid, outcome = xc.receive(root, cfg.steward.repo_id, code, data,
                                                  {"from": name, "commit": sha, "path": f"{xc.FOLDER}/{sub}/{fname}",
                                                   **({"terms_allowed": True} if args.allow_terms else {})}, screen)
                    except xc.ItemSkipped as e:  # FB-018: one refused item never stops the others
                        print(f"{label}: {e}", file=sys.stderr)
                        status = EXIT_DATAERR
                        continue
                    taken += outcome.startswith("received")
                    print(f"{label}: {iid}: {outcome}" + (" (not replaced; the sender files a revision)"
                                                         if outcome == "changed at the peer" else ""))
                print(f"{label}: {taken} new item(s) from {sha[:12]}")
            return status
        def shipped_tag_ok(hit: tuple[str, Any]) -> bool:
            """FB-016: a received item marked shipped names this project's release tag first, and the tag
            exists; the append-only ledger cannot correct a wrong note later."""
            if args.state != "shipped" or hit[0] != "inbox":
                return True
            from .fsutil import git_run

            tag = xc.note_tag(args.note)
            if tag and git_run(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0:
                return True
            print(f"steward: a shipped note starts with the release tag of this project, which must exist "
                  f"(e.g. --note \"v1.2.0: what shipped\"); {tag or '(no first word)'!r} is not a tag here",
                  file=sys.stderr)
            return False

        if args.exchange_command == "respond":
            hit = find(args.id)
            if hit is None or hit[0] != "inbox":
                print(f"steward: {args.id} is not in inbox/", file=sys.stderr)
                return EXIT_USAGE
            if not shipped_tag_ok(hit):
                return EXIT_USAGE
            got = retire_extra(args.id)
            if got is None:
                return EXIT_USAGE
            note, extra = got
            head, _ = xc.parse(hit[1].read_text(encoding="utf-8"))
            peers, _ = xc.discover_peers(root, cfg.exchange)
            rid = xc.next_id(root, code, "response", peers)
            fields = {"schema": "steward.exchange/1", "id": rid, "kind": "response", "from": code, "to": head.get("from"),
                      "title": f"Re: {head.get('title')}", "filed": _dt.date.today(), "responds_to": args.id}
            import hashlib as _hl

            answers = f"{args.id} sha256:{_hl.sha256(hit[1].read_bytes()).hexdigest()}"  # FB-017: which bytes
            text = xc.render(fields, f"\n## Decision\n{args.state}: {note}\n\n## Answers\n{answers}\n")
            xc.Item.model_validate(xc.parse(text)[0])
            xc.ledger_ok(root)
            dest = xc.write_new(root, "responses", f"{rid}.md", text.encode("utf-8"))
            before = xc.entries_of(root, args.id)
            try:
                xc.set_state(root, cfg.steward.repo_id, args.id, args.state, note, code, False, head.get("kind"),
                             {"response": rid, **(extra or {})}, place="inbox")  # AC6: the inbox machine
            except Exception:
                if not xc.keep_if_appended(root, dest, args.id, before, args.state, response=rid):  # Q9, U5
                    xc.rollback(root, dest)
                raise
            else:
                xc.forget(dest)
            print(f"{args.id}: {args.state}; response {rid} in exchange/responses/")
            if args.state in xc.RETIRED_STATES:
                _removal_advice(root, xc, args.id)
            if args.state in ("accepted", "deferred", "declined", "merged"):
                print("Record the decision in the decisions log (Article IV) when it changes scope.")
            return EXIT_OK
        if args.exchange_command == "announce":
            return _announce(args, root, cfg, code, xc)
        if args.exchange_command == "state":
            hit = find(args.id)
            if hit is None and args.state == "closed" and xc.may_be_gone(root, args.id):
                xc.set_state(root, cfg.steward.repo_id, args.id, "closed", args.note, code, False, None, place="inbox")
                print(f"{args.id}: closed (its file was removed after it was {xc.current(xc.states(root)[args.id][:-1])})")
                return EXIT_OK
            if hit is None:
                print(f"steward: no exchange item {args.id}", file=sys.stderr)
                return EXIT_USAGE
            if not shipped_tag_ok(hit):
                return EXIT_USAGE
            kind = xc.parse(hit[1].read_text(encoding="utf-8"))[0].get("kind")
            got = retire_extra(args.id) if hit[0] == "inbox" else (args.note, None)
            if got is None:
                return EXIT_USAGE
            if hit[0] != "inbox" and getattr(args, "by", None):
                print("steward: --by goes with a received item's superseded state only", file=sys.stderr)
                return EXIT_USAGE
            note, extra = got
            xc.set_state(root, cfg.steward.repo_id, args.id, args.state, note, code, hit[0] == "oneway", kind,
                         extra, place=hit[0])
            print(f"{args.id}: {args.state}")
            if hit is not None and hit[0] == "inbox" and args.state in xc.RETIRED_STATES:
                _removal_advice(root, xc, args.id)
            return EXIT_OK
        if args.exchange_command == "status":
            hist = xc.states(root)
            seen_by = xc.observations(root)
            rows = []
            filed: dict[str, Any] = {}
            for place, entries in xc.items(root).items():
                for rel, text in entries:
                    try:
                        head, _ = xc.parse(text)
                    except (ValueError, ValueError, RecursionError):
                        head = {}
                    iid = head.get("id", Path(rel).stem)
                    filed.setdefault(iid, str(head.get("filed")) if head.get("filed") else None)
                    obs = seen_by.get(iid, [])
                    far, last = xc.furthest(obs), (obs[-1] if obs else None)  # FB-019: the furthest, not the last
                    rows.append({"id": iid, "place": place, "kind": head.get("kind"), "title": head.get("title"),
                                 "state": xc.current(hist.get(iid, [])) or "(none)",
                                 **({"observed": {"by": far["by"], "state": far["state"], "evidence": far["evidence"]}}
                                    if far else {}),
                                 **({"observed_latest": {"by": last["by"], "state": last["state"],
                                                         "evidence": last["evidence"]}}
                                    if last is not None and last is not far else {})})
            listed = {r["id"] for r in rows}
            _h, _inbox, _answers = xc.removal_context(root)
            for iid, entries in sorted(hist.items()):  # FB-018: a superseded or withdrawn item whose file is gone
                if iid not in listed and xc.removable(iid, _h, _inbox, _answers):
                    rows.append({"id": iid, "place": "inbox", "kind": None, "title": "(file removed)",
                                 "state": xc.current(entries)})
            delivery = xc.delivery_status(root, cfg.exchange, network=getattr(args, "fetch", False))
            if wants_json(args):
                sent = {d.item.id: d for d in delivery.outgoing}
                for row in rows:
                    if row["place"] in ("outbox", "responses") and (d := sent.get(row["id"])) is not None:
                        row["delivery"] = {"peer": _exchange_name(root, cfg, d.item.to), "state": d.state}
                for d in delivery.incoming:
                    if d.state != "received":
                        rows.append({"id": _exchange_name(root, cfg, d.item.id), "place": "peer",
                                     "kind": d.item.kind, "title": None, "state": d.state,
                                     "delivery": {"peer": _exchange_name(root, cfg, d.item.from_), "state": d.state}})
                for peer in sorted(delivery.unavailable):
                    print(f"steward: could not check peer {_exchange_name(root, cfg, peer)}", file=sys.stderr)
                write_json(args, rows)
            else:
                from .newest import newest_first

                def changed(r):  # X05: an item's latest change: its last state, else the day it was filed
                    entries = hist.get(r["id"], [])
                    return entries[-1].get("time") if entries else filed.get(r["id"])

                for r in newest_first(rows, changed, lambda r: r["id"]):
                    seen = f"  [{r['observed']['by']}: {r['observed']['state']} ({r['observed']['evidence']})" + (
                        f"; latest: {r['observed_latest']['state']} ({r['observed_latest']['evidence']})"
                        if "observed_latest" in r else "") + "]" if "observed" in r else ""
                    print(f"{r['id']:<14} {r['place']:<10} {r['state']:<14} {r['title']}{seen}")
                _print_exchange_delivery(root, cfg, delivery)
            return EXIT_OK
        if args.exchange_command == "export":
            hit = find(args.id)
            if hit is None:
                print(f"steward: no exchange item {args.id}", file=sys.stderr)
                return EXIT_USAGE
            head, body = xc.parse(hit[1].read_text(encoding="utf-8"))
            from . import privacy as pv  # §5a: the text passes the public term lists before it leaves (review N6)

            publics = [t for s in pv.load(root, cfg) if s.public and s.state == "ok" for t in s.terms]
            found, _ = pv.scan_text(f"{head.get('title')}\n{body}", publics, True)
            if found:
                labels = sorted({h["term"].label if h["kind"] == "term" else "local path" for h in found})
                print(f"steward: export refused: the text contains {', '.join(labels)}; reword it first", file=sys.stderr)
                return EXIT_DATAERR
            meta = [f"- Filed: {head.get('filed')}"] + ([f"- Version tested: {head['against']}"] if head.get("against") else []) \
                + ([f"- Reproduced: {head['reproduced']}"] if head.get("reproduced") else [])
            sys.stdout.write(f"# {head.get('title')}\n\n" + "\n".join(meta) + "\n" + body)
            return EXIT_OK
    except xc.BoundaryError as e:
        print(f"steward: refused: {e}", file=sys.stderr)
        return EXIT_DATAERR
    except ValueError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as e:
        print(f"steward: refused: {e.strerror or e} (a link, or a file that already exists)", file=sys.stderr)
        return EXIT_DATAERR
    except (ValidationError, ValueError, RecursionError) as e:
        print(f"steward: the item is not valid steward.exchange/1: {str(e).splitlines()[0]}", file=sys.stderr)
        return EXIT_DATAERR
    except LedgerError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    return EXIT_USAGE


def cmd_release(args: argparse.Namespace) -> int:
    from . import release as rl
    from .engine import _git_state, run_check
    from .models import ReleaseSection

    if args.release_command in ("fingerprint", "ack"):
        return cmd_fingerprint(args)
    if args.release_command == "audit" and args.dist is not None and find_root(Path.cwd()) is None and args.repo is None:
        aud = rl.audit(args.dist, rl.DEFAULT_EXCLUDE, [], local_paths=True)  # standalone: built-in exclusions and local paths
    else:
        root, cfg = _config(args)
        if cfg is None:
            return EXIT_USAGE
        rc = cfg.release or ReleaseSection()
        dist = args.dist if getattr(args, "dist", None) else root / rc.dist
        if args.release_command == "bundle":
            return cmd_release_bundle(args, root, rc)
        if args.release_command == "verify":
            return _release_verify(args, root, rc)
        if args.release_command == "manifest":
            if not rl.artifacts(dist):
                print(f"steward: no distributions in {dist}; build them first", file=sys.stderr)
                return EXIT_USAGE
            claims = None
            if cfg.evidence is not None:
                rep = run_check(root, areas=["evidence"])
                claims = next((r["status"] for r in rep["verdict"]["results"] if r["rule"] == "R-40"), None)
            ids: dict[str, str | None] = {k: None for k in rc.identities}
            for kv in args.identity:
                k, sep, v = kv.partition("=")
                if not sep or k not in rc.identities or not v:
                    print(f"steward: --identity {kv!r}: declare the key in [release] identities ({', '.join(rc.identities) or 'none'}) and give KEY=VALUE", file=sys.stderr)
                    return EXIT_USAGE
                ids[k] = v
            doc = rl.manifest(root, dist, args.version, rc.locks, _git_state(root), claims,
                              cfg.evidence.claims if cfg.evidence else None, ids, rc.bundles)
            if cfg.licence is not None:  # REQ-012: the licence inventory travels with the release; an open
                rep = run_check(root, areas=["licence"])  # licence FAIL or UNKNOWN refuses it
                lic = {r["rule"]: r["status"] for r in rep["verdict"]["results"] if r["rule"] in ("R-79", "R-80", "R-81")}
                from . import licence as li
                from .records import read_rel

                rows, _ = li.inventory(root, cfg, lambda r: read_rel(root, r))
                doc["licence"] = {"declared": cfg.licence.declared, "distribution": cfg.licence.distribution,
                                  "policy": cfg.licence.policy, "checks": lic,
                                  "dependencies": [{k: r[k] for k in ("name", "version", "licence", "status")} for r in rows]}
                bad = {k: v for k, v in lic.items() if v in ("FAIL", "UNKNOWN", "INCOMPLETE")}  # AF5
                if bad:
                    print(f"steward: licence checks are open ({', '.join(f'{k} {v}' for k, v in sorted(bad.items()))}); "
                          "no manifest written (steward check licence)", file=sys.stderr)
                    return EXIT_DATAERR
            if args.image or args.archives:  # REQ-004
                from . import containers as ct

                imgs = []
                for spec in args.image:
                    m = re.match(r"^([^=\s]+)=(sha256:[0-9a-f]{64})(?:@(\S+))?$", spec)
                    if not m:
                        print(f"steward: --image {spec!r}: give TAG=sha256:<64 hex>[@PLATFORM]", file=sys.stderr)
                        return EXIT_USAGE
                    imgs.append({"tag": m.group(1), "digest": m.group(2), "platform": m.group(3)})
                doc["images"] = imgs
                if args.archives:
                    ad = args.archives if args.archives.is_absolute() else Path.cwd() / args.archives
                    doc["archives"] = {a.name: {"sha256": rl.sha(a), "size": a.stat().st_size, "tags": ct.archive_tags(a)}
                                       for a in ct.archives(ad)}
            out = (args.output if args.output.is_absolute() else Path.cwd() / args.output) if args.output else root / rc.manifest
            parent = Path(os.path.abspath(out.parent))
            # U15 (0.13.0): an existing folder reached without links; never one of the files the manifest records
            if out.is_symlink() or not parent.is_dir() or os.path.realpath(parent) != str(parent) or \
                    any(os.path.realpath(out) == os.path.realpath(a) for a in rl.artifacts(dist)) or \
                    any(os.path.realpath(out) == os.path.realpath(dist / l) for l in doc.get("locks_in_dist", [])) or \
                    any(os.path.realpath(out) == os.path.realpath(root / f) for f in
                        [*rc.locks, "CITATION.cff", *([cfg.evidence.claims] if cfg.evidence else [])]) or \
                    (rc.bundles and os.path.realpath(out).startswith(os.path.realpath(root / rc.bundles) + os.sep)) or \
                    (args.archives and os.path.realpath(out).startswith(os.path.realpath(args.archives) + os.sep)):
                print(f"steward: --output {args.output}: not a plain file in an existing folder reached without links, "
                      "or it is one of the recorded files", file=sys.stderr)
                return EXIT_USAGE
            import json as _json

            pfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                rl.write_in_dir(pfd, out.name, (_json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(pfd)
            label = rc.manifest if not args.output else (out.name if not out.resolve().is_relative_to(root.resolve())
                                                         else out.resolve().relative_to(root.resolve()).as_posix())
            print(f"wrote {label}: {len(doc['artifacts'])} artifact(s); claims {claims or 'n/a'}"
                  + (f"; lock(s) from the release folder: {', '.join(doc['locks_in_dist'])}" if doc["locks_in_dist"] else ""))
            return EXIT_OK
        aud = rl.audit_for(root, cfg, dist)  # the same function as R-42 (SR-007)
    for name, n in aud["artifacts"].items():
        print(f"audited {name}: {n} members")
    for f in aud["findings"]:
        where = f"{f['member']}" + (f":{f['line']}" if "line" in f else "")
        print(f"REFUSED {f['artifact']}: {where} ({f['code']}{' ' + f['term'] if 'term' in f else ''})")
    for f in aud.get("declared", []):
        print(f"DECLARED {f['artifact']}: {f['member']} (shipped_secret: {f['reason']}; decision {f['decision']!r})")
    if not aud["artifacts"]:
        print("steward: no distributions found", file=sys.stderr)
        return EXIT_USAGE
    return 1 if aud["findings"] else EXIT_OK


def _release_verify(args: argparse.Namespace, root: Path, rc: Any) -> int:
    """Re-hash an image bundle against the manifest: changed, missing and extra archives, and missing or extra image
    tags (REQ-004)."""
    from . import containers as ct
    from . import release as rl

    try:
        man = json.loads((root / rc.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"steward: no readable manifest at {rc.manifest}", file=sys.stderr)
        return EXIT_USAGE
    if not isinstance(man, dict) or man.get("schema") != "steward.release_manifest/0.1" or not man.get("archives"):
        print(f"steward: {rc.manifest} is not a release manifest that records archives (Q29)", file=sys.stderr)
        return 1
    rec = man.get("archives") or {}
    d = args.dir if args.dir.is_absolute() else Path.cwd() / args.dir
    if not d.is_dir():
        print(f"steward: {args.dir} is not a folder", file=sys.stderr)
        return 1
    now = {a.name: a for a in ct.archives(d)}
    bad = 0
    for name in sorted(set(rec) | set(now)):
        if name not in now:
            print(f"MISSING {name}")
            bad += 1
        elif name not in rec:
            print(f"EXTRA {name} (not in the manifest)")
            bad += 1
        elif rl.sha(now[name]) != rec[name].get("sha256"):
            print(f"CHANGED {name} (hash differs from the manifest)")
            bad += 1
        elif ct.archive_tags(now[name]) != rec[name].get("tags"):  # R18: per-archive tags as recorded
            print(f"CHANGED {name} (its image tags differ from the manifest)")
            bad += 1
        else:
            print(f"ok {name}")
    tags_now = set()
    for a in now.values():
        tags = ct.archive_tags(a)
        if tags is None:  # Q29: an unreadable image list is a problem, not an empty one
            print(f"UNREADABLE {a.name} (no readable manifest.json inside)")
            bad += 1
        else:
            tags_now |= set(tags)
    for img in man.get("images") or []:
        if img.get("tag") not in tags_now:
            print(f"MISSING image {img.get('tag')} (in no archive)")
            bad += 1
    for t in sorted(tags_now - {i.get("tag") for i in man.get("images") or []}):
        if man.get("images"):
            print(f"EXTRA image {t} (not in the manifest)")
            bad += 1
    print(f"{len(now)} archive(s) checked; {bad} problem(s)")
    return 1 if bad else EXIT_OK


def cmd_release_bundle(args: argparse.Namespace, root: Path, rc: Any) -> int:
    from . import release as rl
    from .fsutil import canonical_json, escapes_root

    if not rl.BUNDLE_NAME.match(args.name):
        print("steward: bundle NAME must match [a-z0-9][a-z0-9._-]{0,63}", file=sys.stderr)
        return EXIT_USAGE
    out = args.out if args.out is not None else root / rc.bundles
    if args.out is None and escapes_root(rc.bundles):
        print("steward: [release] bundles must stay inside the repository", file=sys.stderr)
        return EXIT_USAGE
    dest = out / f"{args.name}.zip"
    if (dest.exists() or dest.is_symlink()) and not args.force:
        print(f"steward: {dest} exists; use --force to replace it", file=sys.stderr)
        return EXIT_USAGE
    try:
        members = rl.bundle_members(root, args.paths)
    except rl.BundleError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    if not members:
        print("steward: the paths hold no files", file=sys.stderr)
        return EXIT_USAGE
    from .fsutil import LinkRefused, open_dir_beneath, safe_write

    record: dict[str, Any] = {"schema": "steward.bundle/0.1", "name": args.name, "members": members}
    if args.test_report:
        record["test_report"] = rl.test_report(args.test_report, root)
    try:
        if args.out is None:  # Q6, K2: the configured folder is reached from the repository without links, and held
            bfd = open_dir_beneath(root, Path(rc.bundles).parts, create=True)
        else:
            out.mkdir(parents=True, exist_ok=True)  # an explicit --out is the user's own choice
            bfd = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
        try:
            digest = rl.write_bundle(root, members, dest, bfd)
            record["sha256"] = digest
            side = canonical_json(record).encode("utf-8")
            # R4 (0.12.0): the sidecar goes into the same held directory as its zip, never through a linked leaf
            rl.write_in_dir(bfd, f"{args.name}.bundle.json", side)
        finally:
            os.close(bfd)
    except LinkRefused as e:
        print(f"steward: {rc.bundles}: {e.strerror or e}; refusing to write the bundle", file=sys.stderr)
        return 65
    print(f"wrote {dest.name}: {len(members)} member(s), sha256 {digest[:16]}…"
          + (f"; test command exit {record['test_report']['exit_code']}" if args.test_report else ""))
    print("Next: steward release manifest (records the bundle)")
    return EXIT_OK


def cmd_fingerprint(args: argparse.Namespace) -> int:
    from . import fingerprint as fpm
    from .ledger import Ledger

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    rc = cfg.release
    if rc is None or not rc.fingerprint:
        print("steward: set [release] fingerprint = [\"src/pkg/**/*.py\"] first", file=sys.stderr)
        return EXIT_USAGE
    if args.release_command == "ack":
        current, errors = fpm.fingerprints(root, rc.fingerprint)
        if args.module not in current:
            print(f"steward: {args.module} is not a fingerprinted module" + (f" ({errors[args.module]})" if args.module in errors else ""), file=sys.stderr)
            return EXIT_USAGE
        Ledger(root / rc.acks, "fingerprint-acks", cfg.steward.repo_id).append(
            "ack", {"module": args.module, "fingerprint": current[args.module], "reason": args.reason})
        print(f"acknowledged {args.module} ({current[args.module][:12]}): {args.reason}")
        return EXIT_OK
    if args.record:
        try:
            fp = fpm.record(root, rc.fingerprint, root / rc.fingerprint_file)
        except ValueError as e:
            print(f"steward: {e}", file=sys.stderr)
            return 1
        print(f"recorded {len(fp)} module fingerprint(s) in {rc.fingerprint_file}")
        return EXIT_OK
    current, errors = fpm.fingerprints(root, rc.fingerprint)
    for mod, h in sorted(current.items()):
        print(f"{h[:16]}  {mod}")
    for mod, e in sorted(errors.items()):
        print(f"ERROR  {mod}: {e}")
    return 1 if errors else EXIT_OK


def cmd_hooks(args: argparse.Namespace) -> int:
    from . import hooks as hk
    from .models import ReleaseSection

    if args.hooks_command == "run":  # N1, N2: the work happens here, never in shell text
        if args.hook == "pre-commit":
            return hk.run_pre_commit(Path.cwd(), args.gate)
        return hk.run_pre_push(Path.cwd(), args.gate, args.protect, args.unconfigured, sys.stdin.read().splitlines())

    root, cfg = _config(args)
    if cfg is None:
        return EXIT_USAGE
    if args.hooks_command == "remove":
        try:
            for name, what in hk.remove(root):
                print(f"{name}: {what}")
        except RuntimeError as e:
            print(f"steward: {e}", file=sys.stderr)
            return EXIT_USAGE
        return EXIT_OK
    if args.protect is not None:
        protected = args.protect
    elif cfg.branches is not None and cfg.branches.protected is not None:  # REQ-001
        protected = cfg.branches.protected
    else:
        protected = (cfg.release or ReleaseSection()).protected
    try:
        for name, what in hk.install(root, protected, args.gate, args.force, args.dry_run, args.unconfigured, args.chain):
            print(f"{name}: {what}")
    except (RuntimeError, ValueError) as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_USAGE
    print("Hooks are a convenience (skippable with --no-verify); CI with branch protection is the enforcement point.")
    return EXIT_OK


def cmd_ledger_recover(args: argparse.Namespace) -> int:
    from .ledger import Ledger, LedgerError

    try:
        path = args.path.resolve() if not args.path.is_absolute() else args.path
        base = find_root(Path.cwd()) or Path.cwd()
        try:
            path.parent.resolve().relative_to(base.resolve())
        except ValueError:
            print(f"steward: {args.path} is outside this repository; run recover from the repository that holds it",
                  file=sys.stderr)
            return EXIT_USAGE
        rel_parent = Path(os.path.relpath(path.parent.resolve(), base.resolve()))
        entry = Ledger(base / rel_parent / path.name, args.path.stem, base=base).recover()  # Q8: parents by descriptor
    except LedgerError as e:
        print(f"steward: {e}", file=sys.stderr)
        return EXIT_DATAERR
    print("nothing to recover" if entry is None else f"quarantined {entry['quarantined_bytes']} bytes; recovery entry seq {entry['seq']}")
    return EXIT_OK


def _talk_ctx(args: argparse.Namespace):
    import tomllib

    from . import talk as tk
    from .models import StewardConfig

    root = _require_root(args)
    try:
        cfg = _models.load_config(root)
    except (ValidationError, ValueError, RecursionError, ValueError, OSError):
        print("steward: steward.toml is not valid; run `steward check config`", file=sys.stderr)
        return None
    if not cfg.talk:
        return root, None, None, None
    name = args.name or (next(iter(cfg.talk)) if len(cfg.talk) == 1 else None)
    if name not in cfg.talk:
        print(f"steward: name a talk: {', '.join(sorted(cfg.talk))}", file=sys.stderr)
        return None
    tt = cfg.talk[name]
    plan_path = root / tt.rel(tt.plan)
    try:
        p = tk.TalkPlan.model_validate(tomllib.loads(plan_path.read_text(encoding="utf-8")))
    except (OSError, ValidationError, ValueError, RecursionError) as e:
        print(f"steward: talk plan {tt.rel(tt.plan)} is missing or invalid: {str(e).splitlines()[0]}", file=sys.stderr)
        return None
    return root, name, tt, p


def cmd_talk_plan(args: argparse.Namespace) -> int:
    from . import talk as tk
    from .models import SENTINELS

    got = _talk_ctx(args)
    if got is None or got[1] is None:
        if got is not None:
            print("steward: no [talk.<name>] table in steward.toml", file=sys.stderr)
        return EXIT_USAGE
    root, name, tt, p = got
    missing = [f for f in ("stage", "purpose", "feedback", "audience", "duration_min") if getattr(p, f) in SENTINELS]
    json_output = wants_json(args)
    if json_output and missing:
        write_json(args, {"talk": name, "path": tt.rel(tt.plan), "stage": p.stage, "stage_source": p.stage_source,
                          "purpose": p.purpose, "feedback": p.feedback, "audience": p.audience,
                          "missing": missing, "suggestion": None})
        return 2
    if not json_output:
        print(f"talk {name}: stage={p.stage} ({p.stage_source}), purpose={p.purpose}, feedback={p.feedback}, audience={p.audience}")
        print("missing: " + (", ".join(missing) if missing else "none"))
    if not json_output and p.stage_source != "confirmed":
        print("stage: NOT CONFIRMED. Ask the presenter to confirm the research stage; never infer it.")
    if missing:
        return 2
    ceiling = tk.ceiling(p.stage)
    if not json_output:
        print(f"claim ceiling for stage '{p.stage}': {ceiling or 'unknown stage'}")
    pattern, roles = tk.select_pattern(p.stage, p.purpose, p.feedback, p.pattern)
    if not json_output:
        print(f"pattern: {pattern}: " + " -> ".join(roles))
    prefs = tk.resolve(root, p.overrides, p.context_profile)
    density = prefs["style.density"][0]
    limit = p.max_slides if isinstance(p.max_slides, int) else tk.auto_max_slides(float(p.duration_min), density)
    changed = {k: v for k, v in prefs.items() if v[1] != "default"}
    if json_output:
        write_json(args, {
            "talk": name, "path": tt.rel(tt.plan), "stage": p.stage, "stage_source": p.stage_source,
            "purpose": p.purpose, "feedback": p.feedback, "audience": p.audience, "missing": missing,
            "suggestion": {"claim_ceiling": ceiling, "pattern": pattern, "roles": roles, "max_slides": limit,
                           "max_slides_source": "set" if isinstance(p.max_slides, int) else "auto",
                           "density": density, "preferences": {k: {"value": v, "layer": layer}
                                                               for k, (v, layer) in changed.items()}},
        })
        return EXIT_OK
    print(f"max slides: {limit} ({'set' if isinstance(p.max_slides, int) else f'auto, {density}'})")
    print("preferences (non-default): " + (", ".join(f"{k}={v[0]} [{v[1]}]" for k, v in changed.items()) or "none"))
    if args.write_outline:
        if p.outline:
            print("steward: the plan already has an outline; nothing written", file=sys.stderr)
            return 1
        path = root / tt.rel(tt.plan)
        block = "".join(f'\n[[outline]]\nrole  = "{r}"\ntitle = "{r.replace("-", " ").capitalize()}"\n' for r in roles)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n# Suggested by `steward talk plan` (pattern " + pattern + "); edit freely." + block)
        print(f"wrote {len(roles)} outline entries to {tt.rel(tt.plan)}")
    return EXIT_OK


def cmd_talk_values(args: argparse.Namespace) -> int:
    import tomllib

    from . import values as v

    got = _talk_ctx(args)
    if got is None or got[1] is None:
        return EXIT_USAGE
    root, name, tt, _ = got
    root_cfg = _config(args)[1]
    if not tt.paper or root_cfg is None or tt.paper not in root_cfg.paper:
        print(f"steward: talk '{name}' has no linked paper (set paper = \"...\" in [talk.{name}])", file=sys.stderr)
        return EXIT_USAGE
    pp = root_cfg.paper[tt.paper]
    vf = v.ValuesFile.model_validate(tomllib.loads((root / pp.rel(pp.values)).read_text(encoding="utf-8")))
    comp = v.compute(root, vf)
    for k in sorted(vf.values):
        print(f"{k} = {comp.text.get(k, 'ERROR (' + comp.errors.get(k, ('', '?'))[1] + ')')}")
    if comp.errors:
        print("steward: some values could not be computed; nothing written", file=sys.stderr)
        return 1
    if args.write:
        out = root / tt.rel("_variables.yml")
        out.write_text(v.emit(comp.text, "quarto"), encoding="utf-8", newline="\n")
        print(f"wrote {tt.rel('_variables.yml')}")
    return EXIT_OK


def cmd_talk_export(args: argparse.Namespace) -> int:
    from . import talk_sources as ts

    got = _talk_ctx(args)
    if got is None or got[1] is None:
        return EXIT_USAGE
    root, name, tt, _ = got
    if ts.engine_of(tt.main) != "keynote":
        print("steward: export is for Keynote (.key) talks; other engines build their own PDF", file=sys.stderr)
        return EXIT_USAGE
    try:
        ts.export_keynote((root / tt.rel(tt.main)).resolve(), (root / tt.rel(tt.resolved_pdf())).resolve())
    except (RuntimeError, OSError) as e:
        print(f"steward: export failed: {e}", file=sys.stderr)
        return 1
    print(f"exported {tt.rel(tt.resolved_pdf())}")
    return EXIT_OK


def cmd_talk_prefs(args: argparse.Namespace) -> int:
    from . import talk as tk

    if args.set:
        root = (args.repo.resolve() if args.repo else find_root(Path.cwd())) or Path.cwd()
        try:
            path = tk.layer_path(root, args.layer)
            tk.set_pref(path, args.set[0], args.set[1])
        except (ValueError, ValidationError) as e:
            print(f"steward: not saved: {str(e).splitlines()[0]}", file=sys.stderr)
            return EXIT_USAGE
        print(f"saved {args.set[0]} = {args.set[1]} in {args.layer} ({path})")
        return EXIT_OK
    got = _talk_ctx(args)
    if got is None:
        return EXIT_USAGE
    root, name, tt, p = got
    prefs = tk.resolve(root, p.overrides if p else None, p.context_profile if p else None)
    if wants_json(args):
        write_json(args, {"talk": name, "preferences": {k: {"value": v, "layer": layer}
                                                        for k, (v, layer) in prefs.items()
                                                        if not args.compact or layer != "default"}})
        return EXIT_OK
    for k, (v, layer) in prefs.items():
        if args.compact and layer == "default":
            continue
        print(f"{k} = {v!r}  [{layer}]")
    return EXIT_OK


def cmd_paper_manifest(args: argparse.Namespace) -> int:
    """Record what is being submitted: every file of the paper with size and SHA-256, and the git state."""
    from .engine import _git_state
    from .fsutil import matching_files, sha256_file

    got = _paper_ctx(args)
    if got is None:
        return EXIT_USAGE
    root, name, pp = got
    rels = set(matching_files(root, [pp.rel(g) for g in pp.resolved_sources()]))
    rels |= {pp.rel(x) for x in (pp.main, pp.resolved_pdf(), pp.spec, pp.venue, pp.values, pp.displays,
                                  pp.resolved_values_out(), "displays.lock")}
    rels |= set(matching_files(root, [pp.rel("figures/**/*"), pp.rel("tables/**/*")]))
    files = [{"path": r, "size": (root / r).stat().st_size, "sha256": sha256_file(root / r)}
             for r in sorted(rels) if (root / r).is_file()]
    missing = sorted(r for r in rels if not (root / r).is_file())
    doc = {"schema": "steward.submission_manifest/0.1", "paper": name, "git": _git_state(root),
           "files": files, "not_present": missing}
    text = canonical_json(doc)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output} ({len(files)} files)")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def cmd_paper_displays(args: argparse.Namespace) -> int:
    import tomllib

    from . import displays as dsp

    got = _paper_ctx(args)
    if got is None:
        return EXIT_USAGE
    root, name, pp = got
    mpath = root / pp.rel(pp.displays)
    if not mpath.is_file():
        print(f"steward: no display manifest at {pp.rel(pp.displays)}", file=sys.stderr)
        return EXIT_USAGE
    try:
        df = dsp.DisplaysFile.model_validate(tomllib.loads(mpath.read_text(encoding="utf-8")))
    except (ValidationError, ValueError, RecursionError) as e:
        print(f"steward: invalid display manifest: {str(e).splitlines()[0]}", file=sys.stderr)
        return EXIT_DATAERR
    rows = [(dname, d, dsp.missing_files(root, d)) for dname, d in sorted(df.displays.items())]
    bad = any(missing for _, _, missing in rows)
    if wants_json(args):
        write_json(args, {"paper": name, "path": pp.rel(pp.displays),
                          "displays": [{"id": dname, "kind": d.kind, "label": d.label, "output": d.output,
                                        "missing": missing} for dname, d, missing in rows]})
        return 1 if bad else EXIT_OK
    for dname, d, missing in rows:
        print(f"{dname} ({d.kind}, {d.label}) -> {d.output}" + (f"  MISSING: {', '.join(missing)}" if missing else ""))
    if args.record:
        if bad:
            print("steward: some files are missing; build the displays first; nothing recorded", file=sys.stderr)
            return 1
        lock = mpath.with_name("displays.lock")
        lock.write_text(dsp.lock_text(root, df), encoding="utf-8", newline="\n")
        print(f"wrote {lock.relative_to(root).as_posix()}")
    return 1 if bad else EXIT_OK


def cmd_paper_values(args: argparse.Namespace) -> int:
    import tomllib

    from . import values as v

    got = _paper_ctx(args)
    if got is None:
        return EXIT_USAGE
    root, name, pp = got
    vpath = root / pp.rel(pp.values)
    if not vpath.is_file():
        print(f"steward: no values registry at {pp.rel(pp.values)}", file=sys.stderr)
        return EXIT_USAGE
    try:
        vf = v.ValuesFile.model_validate(tomllib.loads(vpath.read_text(encoding="utf-8")))
    except (ValidationError, ValueError, RecursionError) as e:
        print(f"steward: invalid values registry: {str(e).splitlines()[0]}", file=sys.stderr)
        return EXIT_DATAERR
    comp = v.compute(root, vf)
    if wants_json(args):
        write_json(args, {"paper": name, "path": pp.rel(pp.values), "values": comp.text,
                          "errors": {key: {"code": code, "message": message}
                                     for key, (code, message) in comp.errors.items()}})
        return 1 if comp.errors else EXIT_OK
    for key in sorted(vf.values):
        if key in comp.text:
            print(f"{key} = {comp.text[key]}")
        else:
            print(f"{key} = ERROR ({comp.errors[key][1]})")
    if comp.errors:
        print(f"steward: {len(comp.errors)} value(s) could not be computed; nothing written", file=sys.stderr)
        return 1
    if args.write:
        gen = root / pp.rel(pp.resolved_values_out())
        gen.write_text(v.emit(comp.text, v.emit_format_for(gen.name)), encoding="utf-8", newline="\n")
        print(f"wrote {pp.rel(pp.resolved_values_out())}")
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    try:
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        data = json.loads(raw)
        Report.model_validate(data)
    except FileNotFoundError:
        print(f"steward: no such report file: {args.file}", file=sys.stderr)
        return EXIT_USAGE
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as e:
        print(f"steward: invalid report (not a steward.report/0.1 document): {str(e).splitlines()[0]}", file=sys.stderr)
        return EXIT_DATAERR
    args.rule = args.rule.upper() if args.rule else None
    args.format_default = args.format is None
    args.format = args.format or "md"
    if args.rule is not None and not any(r["rule"] == args.rule for r in data["verdict"]["results"]):
        print(f"steward: no results for rule {args.rule} in this report", file=sys.stderr)
        return EXIT_USAGE
    data = select_results(data, args.rule, args.subject)
    if args.rule is not None and args.format_default:  # 0.20.1 (STW-033): one rule, focused
        from .report import render_rule

        text = render_rule(data, args.rule)
    elif args.format == "md":
        text = render_markdown(data)
    elif args.format == "summary":
        text = render_summary(data, args.file if args.file != "-" else None)
    else:
        text = render_text(data)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
