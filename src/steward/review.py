"""Release review (0.6.2): an independent red-team review gate for releases (rule R-43).

`development/assessment/findings.toml` (schema steward.findings/0.1) records reviews (who reviewed which revision)
and findings (severity, status, regression test, re-verifier, waiver). With `[release] review_required = true` the
gate needs: a review of the commit being released (or of a commit that differs only in documentation), a reviewer
other than the implementer, and every critical or high finding verified with a regression test or accepted with a
signed `waive` authorization. Off by default; then every report recommends the review before a public release.

A recorded review shows that a review happened and how its findings were closed. It cannot show that the review was
thorough.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .fsutil import glob_match
from .models import Strict, Text

BLOCKING = ("critical", "high")
DOC_ONLY = ["**/*.md", "development/**", "docs/**", "**/*.txt", "CITATION.cff", "LICENSE"]


class Review(Strict):
    id: Text
    reviewer: Text  # e.g. "Codex (OpenAI)", a person, a team
    implementer: str | None = None  # who built the reviewed work; must differ from the reviewer
    revision: Text  # the commit reviewed (full or abbreviated)
    file: str | None = None  # the assessment document


class Finding(Strict):
    id: Text
    review: Text
    severity: Literal["critical", "high", "medium", "low", "info"]
    title: Text
    status: Literal["open", "confirmed", "fixed", "verified", "accepted", "accepted_on_tests", "superseded"]
    class_: Literal["blocking", "wrong_result", "limitation"] | None = Field(default=None, alias="class")  # AR-13
    decision: str | None = None  # AR-13: the DECISIONS.md heading that accepts it on its tests
    test: str | None = None  # regression test, e.g. tests/test_x.py::test_name
    verified_by: str | None = None
    waiver: str | None = None  # steward/auth/<nonce> with action waive and scope finding=<ID>


class FindingsFile(Strict):
    schema_: Literal["steward.findings/0.1"] = Field(alias="schema")
    reviews: list[Review] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    # the repository is `root`, never one chosen by inherited GIT_* variables (as authorize._git, red-team B4)
    from .fsutil import git_run

    return git_run(root, *args, text=True)


def coverage(root: Path, revision: str) -> tuple[bool | None, list[str]]:
    """Does a review of `revision` cover HEAD? True if HEAD is it, or later changes touch documentation only.
    None when git cannot tell."""
    head = _git(root, "rev-parse", "HEAD")
    rev = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if head.returncode != 0 or rev.returncode != 0:
        return None, []
    if head.stdout.strip() == rev.stdout.strip():
        return True, []
    if _git(root, "merge-base", "--is-ancestor", rev.stdout.strip(), head.stdout.strip()).returncode != 0:
        return False, ["(reviewed revision is not an ancestor of HEAD)"]
    diff = _git(root, "diff", "--name-only", rev.stdout.strip(), head.stdout.strip())
    if diff.returncode != 0:  # red-team M2: a comparison that failed is not coverage
        return None, []
    code = [f for f in diff.stdout.split() if not any(glob_match(f, p) for p in DOC_ONLY)]
    return (not code), code


def _bindings(module: list[Any], name: str) -> int:
    """How many module-level statements bind `name` (class, function, assignment, import)."""
    import ast

    n = 0

    def module_scope(nodes: list[Any]):  # every statement at module scope, inside if / try / for / with blocks too
        for node in nodes:
            yield node
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                for field in ("body", "orelse", "finalbody"):
                    yield from module_scope(getattr(node, field, []) or [])
                for h in getattr(node, "handlers", []) or []:
                    yield from module_scope(h.body)
    for node in module_scope(module):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            n += 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            n += sum(1 for t in targets for x in ast.walk(t) if isinstance(x, ast.Name) and x.id == name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            n += sum(1 for a in node.names if (a.asname or a.name.split(".")[0]) == name)
        if isinstance(node, (ast.For, ast.AsyncFor)):  # review N10: loop targets bind at module scope too
            n += sum(1 for x in ast.walk(node.target) if isinstance(x, ast.Name) and x.id == name)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            n += sum(1 for it in node.items if it.optional_vars is not None
                     for x in ast.walk(it.optional_vars) if isinstance(x, ast.Name) and x.id == name)
    return n


def _has_constructor(cls: Any, module: list[Any], depth: int = 0) -> bool:
    """True if the class declares or inherits `__init__` / `__new__`, or if a base cannot be resolved in this file
    (an imported base is not inspected: refused rather than guessed, red-team I1)."""
    import ast

    if depth > 20:
        return True
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ("__init__", "__new__") for n in cls.body):
        return True
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "object" and _bindings(module, "object") == 0:
            continue  # the built-in object, unless the module rebinds the name (K7)
        if not isinstance(base, ast.Name) or _bindings(module, base.id) != 1:
            return True  # imported, an attribute, or bound more than once: not resolvable statically (I1, J7)
        local = next((n for n in module if isinstance(n, ast.ClassDef) and n.name == base.id), None)
        if local is None or _has_constructor(local, module, depth + 1):
            return True
    return False


def test_exists(root: Path, node: str) -> bool:
    """`path::test_x` or `path::TestC::test_x` names a test pytest would collect with its default naming (functions
    `test*`, classes `Test*` without a declared or inherited `__init__` / `__new__`; a base class imported from
    another module cannot be inspected, so it is refused). The file is parsed, not run: this shows the test exists, not that it passes.
    Parameter references (`[...]`) are not accepted (red-team E5, F3, G2): pytest's ID escaping is not reproduced,
    so a reference names the whole test."""
    import ast

    path, *names = node.split("::")
    if not names or "[" in node or not path.endswith(".py") or not (root / path).is_file():
        return False
    from .fsutil import escapes_root, inside

    if escapes_root(path) or not inside(root, path) or (root / path).is_symlink():  # review N10: the reviewed tree only
        return False
    try:
        body: list[ast.stmt] = ast.parse((root / path).read_text(encoding="utf-8")).body
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return False
    module = body
    for i, name in enumerate(names):
        final = i == len(names) - 1
        kinds = (ast.FunctionDef, ast.AsyncFunctionDef) if final else ast.ClassDef
        hit = next((n for n in body if isinstance(n, kinds) and n.name == name), None)
        if hit is None or not name.startswith("test" if final else "Test"):
            return False
        if not final and _has_constructor(hit, module):
            return False  # pytest does not collect a test class with a constructor, declared or inherited (H1, I1)
        body = getattr(hit, "body", [])
    return True


def known_issue_listed(text: str, fid: str) -> bool:
    """The ID appears in a section whose heading says "known issues" (review N10), not anywhere in the file."""
    import re

    inside_section, level = False, 0
    for line in text.splitlines():
        m = re.match(r"^(#+)\s+(.*)$", line)
        if m:
            if inside_section and len(m.group(1)) <= level:
                inside_section = False
            if "known issue" in m.group(2).lower():
                inside_section, level = True, len(m.group(1))
            continue
        if inside_section and re.search(rf"(?<![\w-]){re.escape(fid)}(?![\w-])", line):
            return True
    return False


def decision_heading(text: str, decision: str) -> bool:
    """A decisions-log entry heading (`## …`) that names the decision (review N10), not prose elsewhere."""
    return any(line.startswith("## ") and decision.strip() and decision.strip() in line for line in text.splitlines())


def _decisions_text(root: Path, cfg: Any) -> str:
    integ = getattr(cfg, "integrity", None)
    paths = getattr(cfg, "paths", None)
    rel = integ.decisions if integ else f"{getattr(paths, 'records', 'development').rstrip('/')}/DECISIONS.md"
    p = root / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def evaluate(root: Path, cfg: Any, ff: FindingsFile) -> tuple[list[str], list[dict[str, Any]]]:
    """Returns (causes as status names, details). Status names: FAIL, INCOMPLETE, UNKNOWN."""
    from . import authorize as az

    causes: list[str] = []
    details: list[dict[str, Any]] = []
    if not ff.reviews:
        return ["INCOMPLETE"], [{"code": "R-43.no_review", "message": "no review recorded"}]
    best = None
    for r in ff.reviews:
        if not (r.implementer or "").strip():  # red-team D8: independence is shown, never assumed
            causes.append("INCOMPLETE")
            details.append({"code": "R-43.independence_unknown", "value": r.id,
                            "message": "the review names no implementer, so independence cannot be checked"})
        elif r.reviewer.strip().lower() == r.implementer.strip().lower():
            causes.append("FAIL")
            details.append({"code": "R-43.not_independent", "value": r.id, "message": "reviewer and implementer are the same"})
        cov, changed = coverage(root, r.revision)
        if cov:
            best = r
        details.append({"code": "R-43.review", "value": r.id, "message": f"{r.reviewer} reviewed {r.revision}"
                        + ("" if cov else f"; not covering HEAD ({len(changed)} code file(s) changed since)" if cov is False else "; coverage unknown (git)")})
    if best is None:
        if all(coverage(root, r.revision)[0] is None for r in ff.reviews):
            causes.append("UNKNOWN")
        else:
            causes.append("INCOMPLETE")
            details.append({"code": "R-43.stale_review", "message": "no review covers the commit being released; request a re-review"})
    rc = getattr(cfg, "release", None)
    stopping = getattr(rc, "stopping_rule", "none") == "no-blocking-no-wrong-result"
    known = ""
    if stopping and getattr(rc, "known_issues", None) and (root / rc.known_issues).is_file():
        known = (root / rc.known_issues).read_text(encoding="utf-8", errors="replace")
    decisions_text = _decisions_text(root, cfg)
    for f in ff.findings:
        cls = f.class_ or ("blocking" if f.severity in BLOCKING else "limitation")
        if f.status == "accepted_on_tests":  # AR-13: an owner's acceptance on the regression test, recorded
            if not f.decision or not decision_heading(decisions_text, f.decision) or not test_exists(root, f.test or ""):
                causes.append("FAIL")
                details.append({"code": "R-43.accepted_on_tests_unrecorded", "value": f.id,
                                "message": "needs a test that exists and a decision reference found in the decisions log"})
            elif f.severity in BLOCKING:
                causes.append("INCOMPLETE")  # critical and high still need re-verification or a signed waiver
                details.append({"code": "R-43.not_reverified", "value": f.id, "message": "accepted on tests; a critical or high finding is re-verified or waived"})
            continue
        if stopping and f.status in ("open", "confirmed", "fixed"):
            if cls in ("blocking", "wrong_result"):
                causes.append("FAIL")
                details.append({"code": "R-43.open", "value": f.id, "message": f"{cls}: {f.title}"})
            elif not known_issue_listed(known, f.id):
                causes.append("INCOMPLETE")
                details.append({"code": "R-43.unlisted_limitation", "value": f.id,
                                "message": f"an open limitation must be listed in {getattr(rc, 'known_issues', None) or '[release] known_issues'}"})
            else:
                details.append({"code": "R-43.known_issue", "value": f.id})
            continue
        if f.severity not in BLOCKING and cls != "wrong_result":
            if f.status in ("open", "confirmed"):
                details.append({"code": "R-43.open_minor", "value": f.id, "message": f"{f.severity}: {f.title}"})
            continue
        if f.status in ("open", "confirmed"):
            causes.append("FAIL")
            details.append({"code": "R-43.open", "value": f.id, "message": f"{f.severity}: {f.title}"})
        elif f.status == "fixed":
            causes.append("INCOMPLETE")
            details.append({"code": "R-43.not_reverified", "value": f.id, "message": "fixed, awaiting re-verification by the reviewer"})
        elif f.status == "verified":
            if not test_exists(root, f.test or ""):  # red-team D8: the named test itself, not only its file
                causes.append("INCOMPLETE")
                details.append({"code": "R-43.no_regression_test", "value": f.id, "message": f"test {f.test or '(none)'} not found as a collectable test "
                                "(path::test_name or path::TestClass::test_name; no [parameter] suffix)"})
            if not (f.verified_by or "").strip():
                causes.append("INCOMPLETE")
                details.append({"code": "R-43.no_reverifier", "value": f.id, "message": "verified, but no re-verifier is recorded"})
        elif f.status == "accepted":
            ok, unavailable = False, False
            if f.waiver and getattr(cfg, "policy", None) is not None:
                try:
                    v = az.verify(root, cfg, f.waiver, action="waive", consumed=set(), require_pinned=True)
                    ok = f"finding={f.id}" in v.payload["scope"].split()
                except az.AuthError as err:
                    unavailable = err.step == "unavailable"  # M1: not verifiable here, not unwaived
            if unavailable:
                causes.append("UNKNOWN")
                details.append({"code": "R-43.verification_unavailable", "value": f.id, "message": "run `steward check` in a terminal"})
            elif not ok:
                causes.append("FAIL")
                details.append({"code": "R-43.unwaived", "value": f.id, "message": "a high or critical finding accepted without a signed waive (scope finding=ID)"})
    return causes, details
