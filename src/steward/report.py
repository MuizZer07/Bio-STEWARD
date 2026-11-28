"""The C10 report schema (steward.report/0.1) and its text and Markdown renderings (RELEASE_v0.1_SPEC §5–§6).

Rendering is deterministic for a given report. Wording follows DESIGN_v0.4 §3: results describe what was checked
against declared rules, never the truth of a claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

StatusName = Literal["PASS", "FAIL", "INCOMPLETE", "UNKNOWN", "NOT_APPLICABLE"]
ORDER = ("FAIL", "INCOMPLETE", "UNKNOWN", "NOT_APPLICABLE", "PASS")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(_M):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResultItem(_M):
    rule: str = Field(pattern=r"^R-\d{2}$")
    name: str
    rule_version: int
    subject: str
    status: StatusName
    reason: str
    details: list[dict[str, Any]]
    evidence: list[EvidenceItem]
    area: str | None = None  # 0.21.0 (STW-047): the rule's area; absent from earlier reports


class Counts(_M):
    PASS: int
    FAIL: int
    INCOMPLETE: int
    UNKNOWN: int
    NOT_APPLICABLE: int


class Summary(_M):
    counts: Counts
    worst: StatusName


class GateRef(_M):
    rule: str
    subject: str
    status: StatusName


class WaivedGateRef(GateRef):
    authorization: str


class Gate(_M):
    name: str
    evaluated: bool
    eligible: bool
    reason: str
    required_count: int
    evaluated_count: int
    pass_count: int = 0
    not_applicable_count: int = 0
    blocking: list[GateRef]
    waived: list[WaivedGateRef]


class NotEvaluated(_M):
    path: str
    reason: str


class Areas(_M):
    configured: list[str] = []
    nothing_recorded: list[str] = []
    not_configured: list[str] = []


class Coverage(_M):
    not_evaluated: list[NotEvaluated]
    statement: str
    areas: Areas = Areas()


class Scope(_M):
    full: bool
    areas: list[str]
    rule: str | None = None


class Verdict(_M):
    repo_id: str
    project: str
    config_profile: str
    inputs_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    # 0.21.0 (STW-047): the inputs behind the digest, the file-list digest, and what the run covered. Absent from
    # earlier reports.
    inputs: list[EvidenceItem] | None = None
    tree_digest: str | None = Field(None, pattern=r"^sha256:[0-9a-f]{64}$")
    scope: Scope | None = None
    results: list[ResultItem]
    summary: Summary
    gates: list[Gate]
    coverage: Coverage


class Envelope(_M):
    tool: str
    tool_version: str
    created: str
    platform: dict[str, str]
    git: Union[dict[str, Any], Literal["unknown"]]


class Report(_M):
    schema_: Literal["steward.report/0.1"] = Field(alias="schema")
    envelope: Envelope
    verdict: Verdict


# ---------------------------------------------------------------- rendering
# Red-team A6: say which kits a verdict covers, and what to do next for each blocking result.
NEXT = {
    "R-01": "fix steward.toml (see the detail lines); `steward check config`",
    "R-02": "fill the contract's TBD fields with real values, or fix the schema errors",
    "R-03": "make the contract's cross-references consistent; create the referenced files",
    "R-04": "add a confirmatory benchmark contract (development/templates/benchmark.contract.toml)",
    "R-05": "fix the prior-work record; use 'unknown' for identifiers you cannot find",
    "R-06": "add a prior-work record with a closest_method work",
    "R-07": "remove the private terms at the listed file:line (or install poppler for PDFs)",
    "R-08": "fill the paper spec and venue profile (source_url and retrieved date)",
    "R-09": "resolve the TODO/TBD markers listed",
    "R-10": "register numbers in paper/values.toml; `steward paper values --write`",
    "R-11": "rebuild the displays, then `steward paper displays --record`",
    "R-12": "rebuild the paper (latexmk) and fix undefined references or citations",
    "R-13": "meet the venue rules listed (pages, words, sections, anonymity, figures)",
    "R-14": "fix the bibliography: missing, duplicate or malformed entries",
    "R-15": "check the values in the failed assertion",
    "R-21": "complete talks/<name>/talk.toml; `steward talk plan <name>`",
    "R-22": "ask the presenter to confirm the research stage; set stage_source = \"confirmed\"",
    "R-23": "lower the claim's status, or add evidence that supports it",
    "R-24": "use \\val{key} / {{< var key >}} for numbers; `steward talk values` for Quarto",
    "R-25": "add a limitations section (outline role and slide)",
    "R-26": "make the structure match the feedback intent (decisions, backup slides)",
    "R-27": "use registered, current displays on slides",
    "R-28": "fewer slides, larger fonts, no overflow; build or export the PDF, or install a PDF reader (poppler or the [talk] extra)",
    "R-29": "review the strong wording listed (advisory)",
    "R-31": "restore the ledger from version control, or `steward ledger recover` a torn tail",
    "R-32": "`steward run --recover` for interrupted runs",
    "R-33": "pin the trust root (`steward authorize pin`) or authorize the policy change",
    "R-34": "authorize the spend, or stay within the cap",
    "R-35": "revert the frozen files, or propose and sign an amendment",
    "R-36": "make datasets.toml roles match `steward integrity status`",
    "R-37": "investigate the use of sealed data before its unseal",
    "R-38": "record the decision in DECISIONS.md and use a verified authorization; never rewrite the log",
    "R-39": "freeze the confirmatory contract before its first run",
    "R-40": "tie the claim to finished runs whose output matches the stated value",
    "R-41": "link each claimed difference to an existing contract",
    "R-42": "add the required files, `steward release manifest` after building, remove refused members",
    "R-43": "record an independent review of this commit; verify or waive every high/critical finding",
    "R-44": "review the code change; `steward release ack MODULE --reason ...` if neutral, else re-record after review",
    "R-45": "fix the split files or the sample metadata; `steward benchmark splits CONTRACT` lists overlaps",
    "R-46": "restore the dataset file, or update the contract's sha256 after a reviewed change",
    "R-47": "fill the results matrix for every metric, method and required split; `steward benchmark results CONTRACT`",
    "R-53": "fix the item or ledger entry named. Record states with `steward exchange state ID STATE --note ...`. "
            "For a missing receipt, check the peer's ref and ask it to pull and commit its receipt. For an item edited "
            "after the peer received it, restore the received bytes, or re-file the revision under a new ID",
    "R-52": "re-derive the outputs on this commit and run `steward repro check ID --work DIR`",
    "R-54": "restore an edited inbox item from version control (a correction is a new revision the sender files); decide acknowledged items with `steward exchange respond`",
    "R-55": "close the session again with `steward session close` and commit the handoff",
    "R-61": "resolve the merge conflict in the file named (or mark a file that holds markers on purpose)",
    "R-62": "record scores with `steward agents score` by an agent other than the author; append an override with a reason",
    "R-68": "record the GO in the decisions log before an outcome stage runs; accrue to the minimum first",
    "R-63": "restore the frozen files, or record the new version with `steward frozen record NAME --decision ...`",
    "R-66": "write the upgrade's parity record (package, old, new, harnesses with verdicts, approval)",
    "R-67": "run `steward benchmark power` for the contract, or raise minimum_units to reach the target",
    "R-64": "add the path to the context's .dockerignore, or remove the link or file",
    "R-65": "set the key in the service's environment or env_file, mount user data on a named volume, or un-ignore the shipped path",
    "R-69": "run `steward docs build` for site pages or `steward docs readme` for the README and its SVG assets",
    "R-70": "fix development/milestones.toml; record each past milestone's outcome (met, moved with a decision, dropped)",
    "R-71": "fix the sprint file named (steward sprint check ID), or recover its ledger",
    "R-72": "write the report of each sprint whose window has ended: steward sprint report ID",
    "R-73": "restore the kept artifact of a retired pin (or the pinned artifact itself); see steward pins status",
    "R-74": "move callers off a deprecated pin; retire an eligible one with a signed approval (steward pins status)",
    "R-75": "restore the recorded file, or accept its new bytes on purpose (steward study fingerprint ID --accept PATH); a missing digest: steward study fingerprint ID --write",
    "R-76": "re-run a stale review; name the nearest prior work; record the decision on a gap or dead end",
    "R-77": "record the citation (steward paper citations NAME --fetch) or correct the cited title or identifier",
    "R-78": "move a shared study out of tuning or test; use another judge; freeze the prompts; review cases before a cutoff",
    "R-79": "state the same SPDX licence in LICENSE, the package metadata and CITATION.cff",
    "R-80": "replace the dependency, declare it in [licence] use as invoked when it only runs as a separate tool, record a dated exception with its approver, or update the notices (steward licence notices --write)",
    "R-81": "declare the source and licence in third_party, rewrite the code independently, or record an exception",
    "R-82": "declare the code's source in third_party, or confirm it is original",
    "R-83": "inspect the reported row and column, then correct the export or the declared table contract",
    "R-85": "name every accession of the cited studies in the paper's data-availability statement",
    "R-87": "run a stranger test on the coming release: steward stranger-test brief --tag TAG --for AGENT",
    "R-88": "run steward tidy, then ask the owner whether to archive, delete or keep each item",
    "R-89": "install the agent named, or run steward agents setup to write a [delegation] of the installed agents",
    "R-84": "keep both recorded outputs and run steward compare record with the shadow stage name",
    "R-86": "check the weights and training studies, then record a current evaluation run and use its metric values",
    "R-56": "remove the forbidden import or dependency named, or move it to an allowed group",
    "R-57": "give each task spec a unique ID and a known status, list open tasks on the board, and raise its next unused ID",
    "R-58": "add an entry under Unreleased in the changelog for the changes since the last release tag",
    "R-59": "tag the release commit, merge task branches with --no-ff, or rename the branch to a declared pattern",
    "R-60": "edit only the canonical skills directory; replace a drifted copy by a link to it",
    "R-51": "declare `constitution` under [steward] (steward constitution), or read --changes and update the version",
    "R-50": "fetch or restore the artifact (see its retrieval note), or `steward storage record PATH --retrieval ...` after a reviewed change",
    "R-49": "declare each leakage type in the contract's [leakage] table: checked (with evidence) or not_applicable (with a reason)",
    "R-48": "rerun the comparison with `steward run --input <each split file> --output <comparison.output> --seed ...`",
}


def recommendations(results: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in results:
        out += [f"R-75 {d['path']} — {d['message']}" for d in r["details"] if d.get("code") == "R-75.sample_imbalance"]
        out += [f"Recommended: {d['message']}" for d in r["details"] if str(d.get("code", "")).endswith(".recommended")]
        out += [f"R-53 (advisory): {d['message']}" for d in r["details"] if d.get("code") == "R-53.undelivered"]
    return sorted(set(out))


def kits(results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    from .rules import AREAS

    active, inactive = [], []
    for area, rules in AREAS.items():
        rs = [r for r in results if r["rule"] in rules]
        if not rs:
            continue
        (active if any(r["status"] != "NOT_APPLICABLE" for r in rs) else inactive).append(area)
    return active, inactive


def kits_line(results: list[dict[str, Any]], areas: dict[str, Any] | None = None, brief: bool = False) -> str:
    """FB-4 / FB-9: which areas are configured (from the configuration, not only from results). `brief` (the
    summary, 0.19.0) counts the areas not configured instead of naming them."""
    if areas:
        conf, empty, missing = areas.get("configured", []), areas.get("nothing_recorded", []), areas.get("not_configured", [])
        total = len(conf) + len(missing)
        shown = [a + (" (nothing recorded)" if a in empty else "") for a in conf]
        rest = (f"{len(missing)} areas (named by steward check --summary --all)" if brief else ", ".join(missing))
        return (f"Configured: {len(conf)} of {total} areas: {', '.join(shown) or 'none'}"
                + (f" · not configured: {rest}" if missing else ""))
    active, inactive = kits(results)
    return f"Checked: {', '.join(active) or 'none'}" + (f" · not configured: {', '.join(inactive)}" if inactive else "")


CODE_NEXT = {  # 0.20.1 (STW-033): a hint for the case, where the rule's general hint would not fit
    "R-75.sample_confounding": "review the sample counts and which condition contrasts the design can estimate",
    "R-07.controlled_access": "keep the accession in a private record",
    "R-75.none": "steward study new ID --title \"…\" --kind reanalysis, then steward study add-input ID …",
    "R-75.file_changed": "restore the recorded file (git checkout -- PATH), or accept its new bytes on purpose: "
                         "steward study fingerprint ID --accept PATH (then recheck the papers that cite it)",
    "R-75.unfingerprinted": "steward study fingerprint ID --write (records each missing sha256)",
    "R-75.file_missing": "restore the file, or fetch it again (steward data fetch …)",
}
LATE = {"R-75.file_changed", "R-75.stale_paper", "R-75.stale_dependency", "R-75.duplicate_input", "R-45.checked"}


def _next(r: dict[str, Any]) -> str:
    if r["status"] not in ("FAIL", "INCOMPLETE", "UNKNOWN"):
        return ""
    codes = [d.get("code") for d in _by_specificity(r["details"])]
    hit = next((c for c in codes if c in CODE_NEXT), None)  # 0.20.2: the most specific case with its own hint
    if hit:
        return f"  next: {CODE_NEXT[hit]}"
    return f"  next: {NEXT[r['rule']]}" if r["rule"] in NEXT else ""
def summary_line(counts: dict[str, int]) -> str:
    return " · ".join(f"{k} {counts[k]}" for k in ("PASS", "FAIL", "INCOMPLETE", "UNKNOWN", "NOT_APPLICABLE"))


def gate_line(g: dict[str, Any]) -> str:
    if not g["evaluated"]:
        return f"Gate {g['name']}: not evaluated ({g['reason']}; only a full `steward check` evaluates gates)"
    waived = ", ".join(f"{w['rule']} {w['subject']} ({w['authorization']})" for w in g["waived"])
    suffix = f" · waived: {waived}" if waived else ""
    if g["eligible"]:  # AR-19: say how much the eligibility rests on
        return (f"Gate {g['name']}: ELIGIBLE ({g['required_count']} required: {g.get('pass_count', '?')} passed, "
                f"{g.get('not_applicable_count', '?')} not applicable)" + suffix)
    return f"Gate {g['name']}: NOT ELIGIBLE ({g['reason']}; {len(g['blocking'])} blocking)" + suffix


def _detail_text(d: dict[str, Any]) -> str:
    parts = [str(d.get("code", ""))]
    for key in ("field", "path", "line", "row", "column", "value", "term", "id", "files", "message", "note"):
        if key in d:
            parts.append(f"{key}={d[key]}")
    return " ".join(parts)


def _ordered(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(results, key=lambda r: (ORDER.index(r["status"]), r["rule"], r["subject"]))


def render_text(report: dict[str, Any]) -> str:
    v = report["verdict"]
    lines = []
    for r in _ordered(v["results"]):
        lines.append(f"{r['status']:<14} {r['rule']} {r['name']:<20} {r['subject']} — {r['reason']}")
        if r["status"] != "PASS":
            for d in r["details"]:
                lines.append(f"{'':<15}· {_detail_text(d)}")
            if _next(r):
                lines.append(f"{'':<13}{_next(r)}")
    lines.append("")
    lines.append("Summary: " + summary_line(v["summary"]["counts"]))
    for g in v["gates"]:
        lines.append(gate_line(g))
    lines.append(kits_line(v["results"], v["coverage"].get("areas")))
    lines += recommendations(v["results"])
    for n in v["coverage"]["not_evaluated"]:
        lines.append(f"Not evaluated: {n['path']} ({n['reason']})")
    lines.append(v["coverage"]["statement"])
    return "\n".join(lines) + "\n"


def _md_cell(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    v, env = report["verdict"], report["envelope"]
    out = [f"# Steward report: {v['project']}", ""]
    out += [f"- Repository ID: `{v['repo_id']}`", f"- Profile: {v['config_profile']}", ""]
    out += ["## Summary", "", summary_line(v["summary"]["counts"]), ""]
    out += ["## Gates", ""]
    for g in v["gates"]:
        out.append(f"- {gate_line(g)}")
        for b in g["blocking"]:
            out.append(f"  - {b['status']}: {b['rule']} `{b['subject']}`" + (f" ({NEXT[b['rule']]})" if b["rule"] in NEXT else ""))
    out += ["", kits_line(v["results"], v["coverage"].get("areas"))] + [f"- {r}" for r in recommendations(v["results"])]
    out += ["", "## Results", "", "| Status | Rule | Subject | Reason | Details |", "|---|---|---|---|---|"]
    for r in _ordered(v["results"]):
        details = "<br>".join(_md_cell(_detail_text(d)) for d in r["details"]) if r["status"] != "PASS" else ""
        out.append(f"| {r['status']} | {r['rule']} {r['name']} | `{_md_cell(r['subject'])}` | {_md_cell(r['reason'])} | {details} |")
    out += ["", "## Not evaluated", ""]
    out += [f"- `{n['path']}`: {n['reason']}" for n in v["coverage"]["not_evaluated"]] or ["- (none)"]
    out += ["", "## Coverage", "", v["coverage"]["statement"], ""]
    git = env["git"] if isinstance(env["git"], str) else f"{env['git'].get('head', 'unknown')} (dirty: {env['git'].get('dirty')})"
    out += ["## Envelope", "", f"- Tool: {env['tool']} {env['tool_version']}", f"- Created: {env['created']}",
            f"- Platform: {env['platform'].get('os')} / Python {env['platform'].get('python')}", f"- Git: {git}",
            f"- Inputs digest: `{v['inputs_digest']}`", ""]
    return "\n".join(out)


SHORT_COVERAGE = ("Coverage: declared rules only; artifact integrity and computational repeatability not assessed in "
                  "this version; scientific validity and manuscript correctness not assessed by this tool.")


def render_summary(report: dict[str, Any], report_path: str | None = None, all_lines: bool = False) -> str:
    """Compact output for agents (DESIGN_v0.5 §3.2): counts, gates, EVERY non-PASS result (never truncated),
    a short coverage line and where the full evidence is. Statuses, counts and exit codes are those of the full run."""
    v = report["verdict"]
    lines = ["Summary: " + summary_line(v["summary"]["counts"])]
    lines += [gate_line(g) for g in v["gates"]]
    na = sorted({r["rule"] for r in v["results"] if r["status"] == "NOT_APPLICABLE"}
                - {r["rule"] for r in v["results"] if r["status"] not in ("NOT_APPLICABLE",)})
    # 0.19.0 (STW-006, STW-009): what needs action comes first; a broken configuration is reported once; the rules it
    # left unevaluated, and the rules not configured, are counted (every one is listed with --all)
    config_broken = any(r["rule"] == "R-01" and r["status"] == "FAIL" for r in v["results"])
    if config_broken:  # every result stays listed (A2); the cause is said once, first
        lines.append("Start here: steward.toml is not valid (R-01), so the other rules cannot be evaluated; fix it "
                     "first (steward check config), then check again")
    for r in _ordered(v["results"]):
        if r["status"] == "PASS" or (r["status"] == "NOT_APPLICABLE" and r["rule"] in na and not all_lines):
            continue
        n = len(r["details"])
        lines.append(f"{r['status']} {r['rule']} {r['name']} {r['subject']} — {r['reason']}" + (f" ({n} details)" if n else ""))
        lines += [detail_line(d) for d in _shown(_by_specificity(r["details"]))[:2]]  # 0.20.1: what failed, where
        shown_n = len(_shown(r["details"]))
        if shown_n > 2:
            lines.append(f"  … {shown_n - 2} more: steward check --rule {r['rule']}")
        if _next(r):
            lines.append(_next(r))
    configured = set(((v["coverage"].get("areas") or {}).get("configured")) or [])
    if not config_broken and v["coverage"].get("areas") and not (configured - {"config", "governance", "files"}):
        passed = sorted({r["rule"] for r in v["results"] if r["status"] == "PASS"})
        lines.append("Start here: nothing project-specific is checked yet"
                     + (f" (passing: {', '.join(passed)}: the configuration and the repository itself)" if passed else "")
                     + "; an eligible gate here means nothing is broken, not that anything is verified. Pick a goal: "
                     "steward init --for benchmark | reanalysis | paper | agents | licence (docs: Recipes)")
    lines.append(kits_line(v["results"], v["coverage"].get("areas"), brief=not all_lines))
    lines += recommendations(v["results"])
    if na and not all_lines:  # 0.10.0 U2: every rule still named, on one line; --all gives one line each
        lines.append(f"NOT_APPLICABLE ({len(na)}): {' '.join(na)} (not configured; steward check --summary --all, "
                     "or steward explain R-xx)")
    if v["coverage"]["not_evaluated"]:
        from collections import Counter

        by_ext = Counter((Path(n["path"]).suffix or Path(n["path"]).name) for n in v["coverage"]["not_evaluated"])
        lines.append(f"Not evaluated: {len(v['coverage']['not_evaluated'])} file(s) ("  # FB-3: counted, not listed
                     + ", ".join(f"{k}: {c}" for k, c in sorted(by_ext.items(), key=lambda x: (-x[1], x[0]))[:8])
                     + "); listed in the full report")
    lines.append("Coverage: " + v["coverage"]["statement"].replace("Checked against declared rules only. ", "declared rules only; "))
    if report_path:
        lines.append(f"Details: steward report {report_path} --format text --rule <R-xx> [--subject <path>]")
    else:
        lines.append("Details: steward check --format json --output .steward/report.json, then "
                     "steward report .steward/report.json --format text --rule <R-xx> [--subject <path>]")
    return "\n".join(lines) + "\n"


def _by_specificity(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """0.20.2: what is wrong inside a file before the fact that its digest changed (stable otherwise)."""
    return sorted(details, key=lambda d: d.get("code") in LATE)


def _shown(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The details worth a line: those with a message, a value or a place (a bare status code says nothing new)."""
    return [d for d in details if d.get("message") or d.get("value") or d.get("path") or d.get("field")]


def detail_line(d: dict[str, Any], width: int = 160) -> str:
    """One detail as one indented line: where (path:row:column), then what."""
    where = d.get("path") or d.get("field") or ""
    for k in ("row", "line"):
        if d.get(k) is not None:
            where += f":{d[k]}"
            break
    if d.get("column") is not None:
        where += f":{d['column']}"
    what = d.get("message") or ""
    if d.get("value") not in (None, "") and str(d["value"]) not in what:
        what = f"{d['value']}: {what}" if what else str(d["value"])
    text = f"  - {where + ' ' if where else ''}{what or d.get('code', '')}".rstrip()
    return text if len(text) <= width else text[:width - 1] + "…"


def render_rule(report: dict[str, Any], rule: str) -> str:
    """One rule's results with every detail (STW-033, B2/B3): what `check --rule` and `report --rule` print."""
    rs = [r for r in report["verdict"]["results"] if r["rule"] == rule]
    lines = []
    for r in _ordered(rs):
        lines.append(f"{r['status']} {r['rule']} {r['name']} {r['subject']} — {r['reason']}")
        lines += [detail_line(d, 240) for d in _by_specificity(r["details"])]  # AQ8
        if r["status"] != "PASS" and _next(r):
            lines.append(_next(r))
    lines.append(f"Explain: steward explain {rule}")
    return "\n".join(lines) + "\n"


def select_results(report: dict[str, Any], rule: str | None, subject: str | None) -> dict[str, Any]:
    """The same report restricted to some results, for fetching one result's evidence. Summary and gates are kept
    unchanged, so a filtered rendering can never look better than the full run."""
    if rule is None and subject is None:
        return report
    v = dict(report["verdict"])
    v["results"] = [r for r in v["results"] if (rule is None or r["rule"] == rule) and (subject is None or r["subject"] == subject)]
    return {**report, "verdict": v}
