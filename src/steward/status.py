"""The C10 result model: five statuses, rule results, summaries and gates (DESIGN_v0.4 §1).

The summary describes; only a gate decides. ``worst`` is information, never a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


ALL_STATUSES = (Status.PASS, Status.FAIL, Status.INCOMPLETE, Status.UNKNOWN, Status.NOT_APPLICABLE)

# Severity for `worst` and for precedence inside one result: FAIL > INCOMPLETE > UNKNOWN > PASS.
_SEVERITY = {Status.FAIL: 3, Status.INCOMPLETE: 2, Status.UNKNOWN: 1, Status.PASS: 0}

# Exit codes (RELEASE_v0.1_SPEC §6).
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_INCOMPLETE = 2
EXIT_UNKNOWN = 3
EXIT_USAGE = 64
EXIT_DATAERR = 65
EXIT_SOFTWARE = 70
EXIT_CANTCREAT = 73

_EXIT_FOR = {Status.FAIL: EXIT_FAIL, Status.INCOMPLETE: EXIT_INCOMPLETE, Status.UNKNOWN: EXIT_UNKNOWN}


def worst(statuses: list[Status]) -> Status:
    """Most severe status, NOT_APPLICABLE excluded. No applicable status at all is UNKNOWN, never PASS."""
    applicable = [s for s in statuses if s is not Status.NOT_APPLICABLE]
    if not applicable:
        return Status.UNKNOWN
    return max(applicable, key=lambda s: _SEVERITY[s])


def combine(causes: list[Status]) -> Status:
    """Status of one result from its causes; no causes means PASS (every check of that rule held)."""
    return max(causes, key=lambda s: _SEVERITY[s]) if causes else Status.PASS


def exit_code_for(status: Status) -> int:
    return _EXIT_FOR.get(status, EXIT_OK)


@dataclass
class Result:
    rule: str
    name: str
    rule_version: int
    subject: str
    status: Status
    reason: str
    details: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "name": self.name,
            "rule_version": self.rule_version,
            "subject": self.subject,
            "status": self.status.value,
            "reason": self.reason,
            "details": self.details,
            "evidence": self.evidence,
        }


def sort_key(r: Result) -> tuple[str, str]:
    return (r.rule, r.subject)


def summarize(results: list[Result]) -> dict[str, Any]:
    counts = {s.value: 0 for s in ALL_STATUSES}
    for r in results:
        counts[r.status.value] += 1
    return {"counts": counts, "worst": worst([r.status for r in results]).value}


def evaluate_gate(name: str, require: list[str], results: list[Result], *, partial: bool, min_evaluated: int = 0) -> dict[str, Any]:
    """Gate eligibility (DESIGN_v0.4 §1).

    Eligible iff every required result is PASS or NOT_APPLICABLE (or a waived UNKNOWN, from v0.2) and at least
    one required result is PASS. A partial run never evaluates a gate.
    """
    required = [r for r in results if r.rule in require]
    gate: dict[str, Any] = {
        "name": name,
        "evaluated": not partial,
        "eligible": False,
        "required_count": len(require),
        "evaluated_count": len({r.rule for r in required}),
        "pass_count": len({r.rule for r in required if r.status is Status.PASS}),
        "not_applicable_count": len({r.rule for r in required if r.status is Status.NOT_APPLICABLE}
                                    - {r.rule for r in required if r.status is not Status.NOT_APPLICABLE}),
        "blocking": [],
        "waived": [],
    }
    if partial:
        gate["reason"] = "partial_check"
        return gate
    blocking = [r for r in required if r.status not in (Status.PASS, Status.NOT_APPLICABLE)]
    gate["blocking"] = [{"rule": r.rule, "subject": r.subject, "status": r.status.value} for r in blocking]
    if blocking:
        gate["reason"] = "blocking results"
    elif not any(r.status is Status.PASS for r in required):
        gate["reason"] = "gate.vacuous"
    elif gate["pass_count"] < min_evaluated:  # AR-19
        gate["reason"] = "gate.min_evaluated"
    else:
        gate["eligible"] = True
        gate["reason"] = "eligible"
    return gate


def gate_exit_code(gate: dict[str, Any]) -> int:
    if gate["eligible"]:
        return EXIT_OK
    statuses = {b["status"] for b in gate["blocking"]}
    if Status.FAIL.value in statuses:
        return EXIT_FAIL
    if Status.INCOMPLETE.value in statuses:
        return EXIT_INCOMPLETE
    return EXIT_UNKNOWN
