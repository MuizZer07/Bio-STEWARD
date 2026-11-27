"""Schemas for steward.toml/0.1, steward.contract/0.1 and steward.prior_work/0.1 (RELEASE_v0.1_SPEC §2–§3).

Deferrable fields accept the sentinels ``"TBD"`` (→ INCOMPLETE) and ``"unknown"`` (→ UNKNOWN). Non-deferrable
text fields reject both, so a sentinel there is a schema violation (→ FAIL). Unknown keys are always rejected.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path, PurePosixPath
from datetime import date as _dt_date
from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

TBD = "TBD"
UNKNOWN = "unknown"
SENTINELS = (TBD, UNKNOWN)
Sentinel = Literal["TBD", "unknown"]


def _no_sentinel(v: str) -> str:
    if v in SENTINELS:
        raise ValueError(f"'{v}' is a sentinel; this field is not deferrable")
    if not v.strip():
        raise ValueError("must not be empty")
    return v


Text = Annotated[str, AfterValidator(_no_sentinel)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# ---------------------------------------------------------------- identifiers (spec §3.3)
IDENTIFIER_PATTERNS = {
    "doi": re.compile(r"^doi:10\.\d{4,9}/\S+$"),
    "pmid": re.compile(r"^pmid:[1-9]\d{0,8}$"),
    "arxiv": re.compile(r"^arxiv:(\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(v\d+)?$"),
    "url": re.compile(r"^url:https?://[^\s/?#]+\.[^\s/?#]+\S*$"),
}


def identifier_ok(value: str) -> bool:
    return any(p.match(value) for p in IDENTIFIER_PATTERNS.values())


def _identifier(v: str) -> str:
    if v in SENTINELS:
        return v
    if not identifier_ok(v):
        raise ValueError(f"malformed identifier '{v}' (expected doi:, pmid:, arxiv: or url:https://)")
    return v


def _reference(v: str) -> str:
    return v if v == "internal" else _identifier(v)


Identifier = Annotated[str, AfterValidator(_identifier)]
Reference = Annotated[str, AfterValidator(_reference)]
Hex64 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


# ---------------------------------------------------------------- steward.toml
RULE_IDS = ("R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07", "R-08", "R-09", "R-10", "R-11", "R-12", "R-13", "R-14", "R-15",
            "R-21", "R-22", "R-23", "R-24", "R-25", "R-26", "R-27", "R-28", "R-29", "R-31", "R-32", "R-33", "R-34",
            "R-35", "R-36", "R-37", "R-38", "R-39", "R-40", "R-41", "R-42", "R-43", "R-44",
            "R-45", "R-46", "R-47", "R-48", "R-49", "R-50", "R-51", "R-52", "R-53", "R-54", "R-55", "R-56", "R-57", "R-58", "R-59", "R-60", "R-61", "R-62", "R-63", "R-64", "R-65", "R-66", "R-67", "R-68", "R-69", "R-70", "R-71", "R-72", "R-73", "R-74", "R-75", "R-76", "R-77", "R-78", "R-79", "R-80", "R-81", "R-82", "R-83", "R-84", "R-85", "R-86", "R-87", "R-88")
ADVISORY = ("R-55", "R-58", "R-70", "R-71", "R-72", "R-74", "R-76", "R-82", "R-84", "R-87", "R-88")  # rules the default gate does not require; a named gate may (0.9.0 B5)
CONFIG_SCHEMAS = ("steward.toml/0.1", "steward.toml/0.2")


class StewardSection(Strict):
    schema_: Literal["steward.toml/0.1", "steward.toml/0.2"] = Field(alias="schema")
    repo_id: str
    project: Text
    profile: Literal["exploratory", "confirmatory"] = "exploratory"
    constitution: Annotated[str, Field(pattern=r"^\d+$")] | None = None  # C-1: the constitution version followed

    @field_validator("repo_id")
    @classmethod
    def _uuid4(cls, v: str) -> str:
        try:
            u = uuid.UUID(v)
        except ValueError as e:
            raise ValueError("repo_id must be a UUID") from e
        if u.version != 4 or str(u) != v:
            raise ValueError("repo_id must be a canonical lowercase UUID version 4")
        return v


class PathsSection(Strict):
    contracts: list[str] = Field(default_factory=lambda: ["benchmarks/**/*.contract.toml"])
    prior_work: list[str] = Field(default_factory=lambda: ["development/prior_work/**/*.prior.toml"])
    records: str = "development"  # SR-006: the root of every default record path
    records_required: bool = False  # SR-006: a missing records root or decisions log is INCOMPLETE


class PrivacySection(Strict):
    denylist_file: str | None = None  # a private list (never committed); optional since 0.8.1
    include: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude: list[str] = Field(default_factory=lambda: [".git/**", ".steward/**"])
    allow: list[str] = Field(default_factory=list)  # files exempt from the denylist and local-path scan (SR-004)
    local_paths: bool = True  # SR-005: absolute home paths with a user name
    binary_excludes: bool = True  # FB-3: fonts, images, archives and .DS_Store are excluded, not "not evaluated"


class OccurrenceAllow(Strict):
    """One accepted occurrence of a term, narrower than a whole-file `allow` (0.12.0, REQ-009). Every condition
    given must hold; everything else in the file is scanned as usual."""
    path: str                                   # file or archive-member glob
    term: int | str                             # the list line (as reported, list:line), or the term text
    context: str | None = None                  # a literal fragment containing {term}, which must surround it
    max: int | None = Field(default=None, ge=1)  # at most this many accepted occurrences per file
    sha256: Hex64 | None = None                 # accepted only while the file has exactly these bytes

    @field_validator("context")
    @classmethod
    def _has_term(cls, v: str | None) -> str | None:
        if v is not None and v.count("{term}") != 1:
            raise ValueError("context must contain {term} exactly once")
        return v


class TermList(Strict):
    """A named term list (0.8.1: SR-004, AR-04). Public lists are published policy, so their hits show the term."""
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]
    file: Text
    public: bool = False
    include: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude: list[str] = Field(default_factory=lambda: [".git/**", ".steward/**"])
    allow: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    patterns: bool = False  # each line is a regular expression
    allow_occurrence: list[OccurrenceAllow] = Field(default_factory=list)  # REQ-009


class GateSection(Strict):
    require: list[str]
    min_evaluated: int = Field(default=0, ge=0)  # AR-19: below this many PASS results the gate is not eligible
    added: list[str] = Field(default_factory=list)  # 0.9.0 B9: an overlay's rules; never counted toward min_evaluated

    @field_validator("added")
    @classmethod
    def _known_added(cls, v: list[str]) -> list[str]:
        unknown = [r for r in v if r not in RULE_IDS]
        if unknown:
            raise ValueError(f"unknown rule IDs {unknown}")
        return v

    @field_validator("require")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = [r for r in v if r not in RULE_IDS]
        if unknown:
            raise ValueError(f"unknown rule IDs {unknown}")
        if "R-01" not in v:
            raise ValueError("a gate must require R-01")
        return v


GATE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
DEFAULT_PLACEHOLDERS = (r"\bTODO\b", r"\bTBD\b", r"\bFIXME\b", r"\bXX+\b", r"\[CONFIRM", r"\[RESULT")


class PaperSection(Strict):
    """One paper (RELEASE_v0.2_SPEC §1). Paths are relative to ``dir``, which is relative to the repository root."""

    dir: str
    main: str
    spec: str = "spec.toml"
    venue: str = "venue.toml"
    sources: list[str] | None = None
    build_log: str | None = None
    mode: Literal["draft", "final"] = "draft"
    values: str = "values.toml"
    displays: str = "displays.toml"
    pdf: str | None = None  # built PDF, relative to dir (default: main with .pdf)
    main_ends_at: str = "References"  # text marking the end of the main text in the PDF (for pages_main)
    anonymity_file: str | None = None  # gitignored list of author names, affiliations, links (double-blind venues)
    values_out: str | None = None
    placeholders: list[str] = Field(default_factory=lambda: list(DEFAULT_PLACEHOLDERS))
    citations: str | None = None  # 0.18.0 (optional): the citation verification record, relative to dir (R-77)

    @field_validator("placeholders")
    @classmethod
    def _regexes(cls, v: list[str]) -> list[str]:
        for pat in v:
            try:
                re.compile(pat)
            except re.error as e:
                raise ValueError(f"invalid placeholder regex {pat!r}: {e}") from e
        return v

    @property
    def ext(self) -> str:
        return Path(self.main).suffix.lower()

    def resolved_sources(self) -> list[str]:
        if self.sources is not None:
            return self.sources
        if self.ext == ".tex":
            return ["**/*.tex", "**/*.bib"]
        if self.ext in (".md", ".qmd"):
            return ["**/*.md", "**/*.qmd", "**/*.bib"]
        return [self.main]

    def resolved_log(self) -> str | None:
        if self.build_log is not None:
            return self.build_log
        return str(Path(self.main).with_suffix(".log")) if self.ext == ".tex" else None

    def resolved_pdf(self) -> str:
        return self.pdf if self.pdf is not None else str(Path(self.main).with_suffix(".pdf"))

    def resolved_values_out(self) -> str:
        if self.values_out is not None:
            return self.values_out
        return {".tex": "values.tex", ".md": "_variables.yml", ".qmd": "_variables.yml"}.get(self.ext, "values.json")

    def rel(self, path: str) -> str:
        return f"{self.dir.rstrip('/')}/{path}" if self.dir not in ("", ".") else path


class TalkSection(Strict):
    """One talk (RELEASE_v0.3_SPEC §1). Paths are relative to ``dir``."""

    dir: str
    main: str = "slides.tex"
    plan: str = "talk.toml"
    paper: str | None = None  # share this paper's values registry and display manifest
    mode: Literal["draft", "final"] = "draft"
    pdf: str | None = None
    build_log: str | None = None
    displays: str = "displays.toml"  # the talk's own manifest, if any

    def rel(self, path: str) -> str:
        return f"{self.dir.rstrip('/')}/{path}" if self.dir not in ("", ".") else path

    def resolved_pdf(self) -> str:
        return self.pdf or str(Path(self.main).with_suffix(".pdf"))

    def resolved_log(self) -> str:
        return self.build_log or str(Path(self.main).with_suffix(".log"))


class RunSection(Strict):
    """`steward run` defaults (RELEASE_v0.4_SPEC §2). Command-line limits may only tighten these."""

    ledger: str = "development/runs.jsonl"
    logs: str = ".steward/runs"
    wall_s: float | None = Field(default=None, gt=0)
    mem_mb: float | None = Field(default=None, gt=0)
    hang_s: float | None = Field(default=None, gt=0)
    hang_cpu_s: float | None = Field(default=None, gt=0)       # REQ-009: no CPU progress for this long
    socket_timeout_s: float | None = Field(default=None, gt=0)  # REQ-009: passed as STEWARD_SOCKET_TIMEOUT
    disk_free_mb: float | None = Field(default=None, ge=0)
    slots: dict[str, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)
    slots_dir: str | None = None  # SR-001: a directory shared by checkouts (~ expanded); STEWARD_SLOTS_DIR overrides


class PolicySection(Strict):
    """Signed authorizations and the policy baseline (RELEASE_v0.4_SPEC §3)."""

    baseline: str = "origin/main"
    allowed_signers: str = "development/allowed_signers"
    revoked: str = "development/revoked.txt"
    ledger: str = "development/authorizations.jsonl"
    state: Literal["active", "pending"] = "active"  # REQ-016: declared, trust root not set up yet


class Price(Strict):
    input_per_1k: float = Field(ge=0)
    output_per_1k: float = Field(ge=0)
    cache_read_per_1k: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_per_1k: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: Text  # where the price was read (url or document)
    retrieved: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class SpendSection(Strict):
    """Spend guard (RELEASE_v0.4_SPEC §4). Prices are per 1,000 tokens, in `currency`."""

    ledger: str = "development/spend.jsonl"
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    cap: float = Field(ge=0)
    prices: dict[str, Price] = Field(default_factory=dict)


class IntegritySection(Strict):
    """Research integrity (RELEASE_v0.5_SPEC §2)."""

    ledger: str = "development/integrity.jsonl"
    datasets: str = "development/datasets.toml"
    decisions: str | list[str] = "development/DECISIONS.md"  # REQ-013: a path, a list, or globs
    decisions_format: Literal["free", "template"] = "free"  # AR-06: "template" checks each entry's parts
    decisions_base: str | None = None  # AR-06: the git ref for append-only without [policy] (default: merge-base)


    @property
    def primary_decisions(self) -> str:
        """The first decisions log: the one single-path uses name (the programme log)."""
        return self.decisions if isinstance(self.decisions, str) else (self.decisions[0] if self.decisions else
                                                                        "development/DECISIONS.md")

    def decision_logs(self, root: Path) -> list[str]:
        """Every decisions log, globs expanded, in order (REQ-013)."""
        from .fsutil import glob_match, iter_repo_files

        pats = [self.decisions] if isinstance(self.decisions, str) else list(self.decisions)
        out: list[str] = []
        files: list[str] | None = None
        for pat in pats:
            if any(c in pat for c in "*?["):
                files = files if files is not None else list(iter_repo_files(root))
                out += [f for f in files if glob_match(f, pat)]
            else:
                out.append(pat)
        return list(dict.fromkeys(out))


class EvidenceSection(Strict):
    """Claim-to-evidence map (RELEASE_v0.6_SPEC §1.4)."""

    claims: str = "development/claims.toml"


class ArtifactRule(Strict):
    """Per-artifact audit rules (0.9.0 B1, REQ-002): for distributions whose file name matches `match`."""

    match: Text
    forbid: list[str] = Field(default_factory=list)   # member globs refused in this artifact
    require: list[str] = Field(default_factory=list)  # member globs that must each match a member


class ShippedSecret(Strict):
    """A credential a private package ships on purpose (REQ-006): reported, not refused, once decided."""

    path: Text          # member glob
    reason: Text
    decision: Text      # the decisions-log heading text that records it
    authorization: str | None = None  # Article II.3: the signed `waive` authorization tag (steward/auth/<nonce>)


class ReleaseChecks(Strict):
    expect: list[str] = Field(default_factory=list)  # each file-name glob must match a distribution
    same_version: bool = False                       # every distribution's version (from its name) is equal


class ReleaseSection(Strict):
    """Release integrity (RELEASE_v0.6_SPEC §2)."""

    dist: str = "dist"
    required: list[str] = Field(default_factory=lambda: ["CITATION.cff", "LICENSE", "README.md"])
    exclude: list[str] = Field(default_factory=list)  # added to the built-in exclusions
    locks: list[str] = Field(default_factory=list)
    identities: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]] = Field(default_factory=list)  # SR-003
    stopping_rule: Literal["none", "no-blocking-no-wrong-result"] = "none"  # AR-13
    known_issues: str | None = None  # AR-13: the release notes file that lists open limitations by ID
    manifest: str = "release-manifest.json"
    review_required: bool = False  # independent red-team review gate (R-43); off: recommended in every report
    findings: str = "development/assessment/findings.toml"
    fingerprint: list[str] = Field(default_factory=list)  # module globs for the runtime fingerprint (R-44)
    fingerprint_file: str = "development/fingerprint.json"
    acks: str = "development/fingerprint-acks.jsonl"
    protected: list[str] = Field(default_factory=lambda: ["main"])  # branches the pre-push hook protects
    artifact: list[ArtifactRule] = Field(default_factory=list)  # 0.9.0 B1
    bundles: str = "dist/bundles"
    shipped_secret: list[ShippedSecret] = Field(default_factory=list)  # REQ-006  # 0.9.0 B8: `steward release bundle` writes here; the manifest records them
    checks: ReleaseChecks = Field(default_factory=ReleaseChecks)


class ExchangePeer(Strict):
    """A checkout or Git URL, and the revision that carries exchange records."""
    path: Text | None = None
    url: Text | None = None
    ref: Text = "HEAD"

    @model_validator(mode="after")
    def _source(self) -> "ExchangePeer":
        if (self.path is None) == (self.url is None):
            raise ValueError("a peer needs either path or url")
        return self


class ExchangeSection(Strict):
    """The exchange protocol (constitution Article V; DESIGN_exchange_protocol). The folder is always `exchange/`."""
    code: Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")]
    peers: dict[Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")], str | ExchangePeer] = Field(default_factory=dict)
    ack_days: int = Field(default=14, ge=1)
    delivery_days: int = Field(default=14, ge=1)
    oneway_days: int = Field(default=30, ge=1)
    consumers: list[Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")]] = Field(default_factory=list)  # 0.9.0 D1
    uses: dict[Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")], str] = Field(default_factory=dict)  # D2: code -> version used


class ReportSection(Strict):
    to: Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")] = "STW"


class GovernanceSection(Strict):
    required: bool = False  # C-1: the constitution must be declared, and its records present


def _safe_path(v: str) -> str:
    from .fsutil import escapes_root

    if not v or escapes_root(v):
        raise ValueError(f"{v!r} must be a path inside the repository")
    return v


SafePath = Annotated[str, AfterValidator(_safe_path)]


class FileRef(Strict):
    path: SafePath
    sha256: Hex64 | None = None
    size: Annotated[int, Field(ge=0)] | None = None                     # bytes, as fetched
    md5: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None  # the archive's checksum, when it publishes one
    url: Text | None = None                                           # where this file was fetched from


class ModelWeights(FileRef):
    sha256: Hex64


class ModelMetric(Strict):
    pointer: Annotated[str, Field(pattern=r"^(?:/(?:[^~/]|~[01])*)*$")]
    value: Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")]


class ModelRecord(Strict):
    name: Text
    version: Text
    weights: ModelWeights
    training_studies: list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]] = Field(min_length=1)
    contract: SafePath
    split: Text
    run: Text
    metrics: dict[Text, ModelMetric] = Field(min_length=1)
    intended_use: Text
    known_limits: list[Text] = Field(min_length=1)
    licence: Text


class PinDeprecation(Strict):
    """A pin announced for retirement (0.17.0, Muiz: "deprecated soon"): it stays installed and is reported while
    anything still depends on it."""
    reason: Text
    target: str | None = None  # a version, a date or a milestone the deprecation aims at


class PinSpec(Strict):
    """A pinned dependency kept side by side with others (0.17.0, REQ-019)."""
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    package: Text
    version: Text
    artifact: SafePath                                # the exact wheel or archive, kept on retirement
    sha256: Hex64 | None = None                       # the artifact's expected digest
    module: str | None = None                         # the import name that identifies this pin's callers
    # REQ-020 (0.18.0): pins of one library share one import name, so a caller is told apart by what it names:
    # tracked files that mention one of these strings (a folder, a loader script) are this pin's callers
    references: list[Annotated[str, Field(min_length=3)]] = Field(default_factory=list)
    callers: Literal["module", "references", "both"] | None = None  # default: references when set, else module
    ignore_callers: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)  # globs; listed, not blocking
    install: list[SafePath] = Field(default_factory=list)  # removed on retirement: installs, scripts, adapters, tests
    protects: list[SafePath] = Field(default_factory=list)  # records (locks, freezes) that depend on this version
    retire_when: list[str] = Field(default_factory=lambda: ["no_callers"])
    deprecated: PinDeprecation | None = None
    install_command: str | None = None                # restore: how to reinstall from the kept artifact ({artifact})
    check_command: str | None = None                  # restore: the pin's own check

    @field_validator("retire_when")
    @classmethod
    def _conditions(cls, v: list[str]) -> list[str]:
        import re as _re

        ok = _re.compile(r"^(no_callers|never|superseded_by:[^\s]+|after:[^\s]+)$")
        bad = [c for c in v if not ok.match(c)]
        if bad:
            raise ValueError(f"unknown retire_when condition(s) {bad}: use no_callers, superseded_by:<version>, "
                             "after:<record path>, after:milestone:<id> or never")
        return v

    @model_validator(mode="after")
    def _caller_rule(self) -> "PinSpec":
        if self.callers in ("references", "both") and not self.references:
            raise ValueError(f"callers = {self.callers!r} needs a non-empty references list")
        return self

    @property
    def caller_rule(self) -> str:
        """How this pin's callers are found: `references`, `module` or `both` (REQ-020)."""
        return self.callers or ("references" if self.references else "module")


class StrangerTestSection(Strict):
    """The stranger test (0.20.2, STW-041; R-87 advisory): an agent that has never seen the project tries to get value
    from it using only what a newcomer sees."""
    audience: Text | None = None                   # who the stranger is, e.g. "a data scientist who has just found it"
    missions: list[Text] = Field(default_factory=list)  # what they try to achieve, in the project's own terms
    may_read: list[Text] = Field(default_factory=lambda: ["README.md", "docs/"])
    must_not_read: list[Text] = Field(default_factory=lambda: ["src/", "tests/", "development/"])
    install: Text | None = None                    # shell lines installing the release; {repo} and {tag} are filled in
    max_age_days: int = Field(default=120, ge=1)   # R-87: the last record older than this is due again


class TidySection(Strict):
    """Tidying (0.21.0, STW-048 C12; R-88 advisory): the thresholds `steward tidy` and `steward next` use, and the
    memory folders a harness keeps for this project. The toolkit lists what looks stale; it deletes nothing."""
    stale_days: int = Field(default=14, ge=1, le=3650)    # an open task untouched for longer is stale
    handoff_days: int = Field(default=7, ge=1, le=3650)   # a session handoff committed longer ago is stale
    memory_days: int = Field(default=30, ge=1, le=3650)   # a memory entry not changed for longer is listed
    memory: list[Text] = Field(default_factory=list)      # folders (may be outside the repository; ~ is expanded)
    index: SafePath = "development/INDEX.md"              # the state page checked against the latest tag
    archive: SafePath = "development/archive"             # where `steward tidy --archive ID` moves task files


class PublishSection(Strict):
    """`[publish]` (0.19.0): where and how released versions are published (model A mirror or model B open)."""
    mode: Literal["mirror", "open"] = "mirror"
    remote: Text | None = None               # the public repository (URL or path); the staging clone pushes there
    branch: Text = "main"
    include: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude: list[str] = Field(default_factory=list)   # added to the paths that are always private
    author: Text | None = None                # the public identity: a name and a no-reply address (never your own)
    staging: Text = ".steward/publish"        # the staging clone (inside .steward/, never committed)
    redact_ids: bool = True                   # remove private item IDs from the published changelog
    private_codes: list[Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")]] = Field(default_factory=list)  # beyond [exchange]
    binary: list[str] = Field(default_factory=list)  # binary kinds that may be published unscanned, e.g. "**/*.png"
    changelog: Text = "CHANGELOG.md"


class Channel(Strict):
    """`[[channel]]`: a tool this project installs from two sources."""
    name: Text                                  # the distribution, e.g. bio-steward
    stable: Text                                # e.g. git+https://github.com/org/tool.git (the public mirror)
    dev: Text                                   # e.g. a private git+ssh URL of the development repository
    installer: Literal["uv-tool", "pipx", "pip"] = "uv-tool"


class LicenceSection(Strict):
    """Licence governance (0.19.0, REQ-012; R-79 – R-82). Checks declared rules and package metadata; not legal
    advice."""
    declared: Text                                       # the project's SPDX expression, e.g. "MIT"
    distribution: Literal["internal", "network", "public"] = "internal"
    policy: Literal["permissive-only", "weak-copyleft-ok", "gpl-compatible"] = "weak-copyleft-ok"
    allow: list[str] = Field(default_factory=list)       # SPDX ids (globs) always accepted
    deny: list[str] = Field(default_factory=list)        # SPDX ids (globs) always refused; deny wins
    lockfile: SafePath | None = None                     # uv.lock, poetry.lock or a requirements file
    site_packages: list[str] = Field(default_factory=lambda: [".venv/lib/python3*/site-packages"])
    ignore_packages: list[str] = Field(default_factory=list)  # development-only tools never distributed
    exceptions: SafePath | None = None                   # steward.licence-exceptions/1
    third_party: SafePath | None = None                  # steward.third-party/1: copied, ported, vendored code and assets
    notices: SafePath = "THIRD_PARTY_NOTICES.md"         # required and current when distribution = "public"


def _table_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.parts or "\x00" in value or not value.strip() or path.parts[0] == ".git":
        raise ValueError("must name a data file inside the repository")
    return path.as_posix()


TablePath = Annotated[SafePath, AfterValidator(_table_path)]
ColumnType = Literal["text", "integer", "number", "boolean", "ensembl", "entrez", "hgnc"]


class SampleSheet(Strict):
    path: TablePath
    id_column: Text
    format: Literal["tsv", "csv"] = "tsv"


class DataContract(Strict):
    path: TablePath
    format: Literal["tsv", "csv", "series_matrix"] = "tsv"
    columns: dict[Text, ColumnType] = Field(default_factory=dict)
    id_column: Text | None = None
    raw_counts: list[Text] = Field(default_factory=list)
    p_value: Text | None = None
    adjusted_p_value: Text | None = None
    log_fold_change: Text | None = None
    na_values: list[str] = Field(default_factory=lambda: ["", "NA", "N/A", "NaN", "nan", "NULL", "null"])
    sample_sheet: SampleSheet | None = None
    metadata_columns: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def _roles(self) -> "DataContract":
        if self.sample_sheet is not None:
            if self.id_column is None:
                raise ValueError("sample_sheet needs the matrix id_column")
            if self.sample_sheet.path == self.path:
                raise ValueError("sample_sheet must be a separate file")
        elif self.metadata_columns:
            raise ValueError("metadata_columns needs a sample_sheet")
        if self.p_value is not None and self.p_value == self.adjusted_p_value:
            raise ValueError("p_value and adjusted_p_value must name different columns")
        return self


class DataSection(Strict):
    contract: list[DataContract] = Field(default_factory=list)

    @field_validator("contract")
    @classmethod
    def _unique_paths(cls, contracts: list[DataContract]) -> list[DataContract]:
        if len({c.path for c in contracts}) != len(contracts):
            raise ValueError("declare one data contract per file")
        return contracts


class StudiesSection(Strict):
    """Study records (0.18.0): one TOML file per study (a reanalysis, an experiment, a claim and its plan) holding
    its inputs, references, tools, plan, results and the papers that cite it. Checked by R-75."""
    dir: SafePath = "development/studies"
    consistent: list[Literal["genome", "annotation", "id_namespace", "databases", "organism", "taxon", "coordinate_base",
                             "chromosome_naming"]] = Field(default_factory=list)


class ResearchSection(Strict):
    """Research-direction records (0.18.0): literature reviews, novelty maps, gap and flaw lists, dead-end reviews.
    Checked by R-76 (advisory)."""
    dir: SafePath = "development/research"
    stale_days: int = Field(default=90, ge=1)  # a literature review older than this is due for a re-run


class PinsSection(Strict):
    keep_dir: SafePath = "pins/retired"               # where retired artifacts, manifests and checksums are kept
    ledger: SafePath = "development/pins.jsonl"


class CleanSection(Strict):
    """Project storage cleanup (0.13.0; DESIGN_BRIEF_storage_cleanup)."""

    paths: list[str] = Field(default_factory=list)  # this project's temporary folders, in the repository or absolute
    registry: bool = True                            # SC2: list this checkout in the machine's project registry


class StorageSection(Strict):
    """Large artifacts by hash and the resource audit (RELEASE_v0.8_SPEC)."""

    artifacts: str = "development/artifacts.toml"
    large_mb: float = Field(default=50, gt=0)
    caps: dict[str, Annotated[float, Field(gt=0)]] = Field(default_factory=dict)  # directory -> MB (advisory audit)
    clean: CleanSection | None = None


class BenchmarkSection(Strict):
    require_leakage: bool = False  # v0.7: R-49 applies to exploratory contracts too


def _safe_globs(v: list[str]) -> list[str]:
    from .fsutil import escapes_root

    bad = [g for g in v if escapes_root(g)]
    if bad:
        raise ValueError(f"paths must stay inside the repository: {bad}")
    return v


SafeGlobs = Annotated[list[str], AfterValidator(_safe_globs)]


class BoundarySection(Strict):
    """Dependency boundary (0.9.0 B3, REQ-005; R-56)."""

    packages: SafeGlobs                                             # source roots or globs of .py files
    forbidden_imports: list[str] = Field(default_factory=list)     # module prefixes
    forbidden_distributions: list[str] = Field(default_factory=list)  # PEP 503 names
    allow_groups: list[str] = Field(default_factory=list)          # extras / dependency groups exempt (e.g. dev)
    pyproject: str = "pyproject.toml"


class TasksSection(Strict):
    """Task board (0.9.0 B4, REQ-007; R-57)."""

    specs: SafeGlobs
    archive: SafeGlobs = Field(default_factory=list)
    board: str
    id_pattern: str = r"[A-Z]+-\d{3}"
    statuses: list[str] = Field(default_factory=lambda: ["proposed", "on hold", "GO recorded", "in progress",
                                                         "in review", "done"])
    closed: list[str] = Field(default_factory=lambda: ["done"])

    @field_validator("id_pattern")
    @classmethod
    def _regex(cls, v: str) -> str:
        re.compile(v)
        return v


LogPath = Annotated[str, Field(min_length=1, pattern=r"^[^\x00\r\n]+$")]


class TokensSection(Strict):
    """Local session log files selected for per-project token reporting."""

    claude: list[LogPath] = Field(default_factory=list)
    codex: list[LogPath] = Field(default_factory=list)
    gemini: list[LogPath] = Field(default_factory=list)


class TaskTokenBudget(Strict):
    """Optional token budget declared in a Markdown task file."""

    tokens_budget: int = Field(gt=0)


class ChangelogSection(Strict):
    """Changelog `Unreleased` rule (0.9.0 B5, REQ-008; R-58, advisory)."""

    file: str = "CHANGELOG.md"
    format: Literal["keep-a-changelog"] = "keep-a-changelog"
    exclude: SafeGlobs = Field(default_factory=list)
    tag_pattern: str = "v*"
    entry_pattern: str | None = None  # REQ-014: every Unreleased entry line must match
    ready: str | None = None          # REQ-014: the `Status:` value that may ship (checked under --final)


class BranchesSection(Strict):
    """Branch model (0.9.0 B6, REQ-009; R-59 and the pre-push check)."""

    release: str | None = None                # every first-parent commit carries a release tag
    integration: str | None = None
    merge: Literal["no-ff", "any"] = "any"
    task_patterns: list[str] = Field(default_factory=list)
    tag_pattern: str = "v*"
    since: str | None = None                  # history before this ref is not checked (adoption point)
    protected: list[str] | None = None        # REQ-001: branches the pre-push hook protects, without [release]
    # REQ-018: "merged-parent" accepts a release-branch merge commit whose second parent carries the tag
    release_tag_on: Literal["commit", "merged-parent"] = "commit"


class ReproSection(Strict):
    """Reproduction gate (0.9.0 B2, REQ-008; R-52)."""

    contracts: SafeGlobs
    ledger: str = "development/repro.jsonl"


class SessionSection(Strict):
    """Session sign-off and resumption (0.9.0 G; DESIGN_session_handoff S1 – S5; R-55, advisory)."""

    handoff: str = "development/HANDOFF.md"   # one file, replaced at each close; history in git (S2)
    budget_words: int = Field(default=600, ge=50, le=1500)  # S1
    end_hint: str | None = None               # the harness's own end / delete command, as text (S4)
    process: SafeGlobs = Field(default_factory=list)  # further process-record paths checked at close (S5)


class AgentsSection(Strict):
    """Multi-agent attribution and scores (REQ-016; R-62)."""

    ledger: str = "development/agents.jsonl"


class StageDef(Strict):
    """One declared stage of a staged run (REQ-008)."""

    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    reads: Literal["metadata", "restricted", "outcomes"]
    go: str | None = None   # the decisions-log heading text that opens it; required for an outcomes stage
    shadow: bool = False


class AccrualSection(Strict):
    stage: str
    minimum: int = Field(ge=1)
    count_file: str          # JSON {"count": N}, or a file holding the number


class FrozenSet(Strict):
    """A set of files frozen together (REQ-011): agent prompts, tool definitions, configuration, golden fixtures."""

    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    files: SafeGlobs
    record: str | None = None  # default: development/frozen/<name>.json


class DependenciesSection(Strict):
    """Pinned-dependency upgrade parity (REQ-012; R-66)."""

    pins: SafeGlobs
    records: SafeGlobs = Field(default_factory=lambda: ["development/upgrades/*.toml"])
    tag_pattern: str = "v*"


class ContainersSection(Strict):
    """Container build contexts and compose parity (REQ-003, 005; R-64, R-65)."""

    contexts: SafeGlobs = Field(default_factory=list)       # build-context folders
    dev_only: list[str] = Field(default_factory=list)        # paths no context may reach (absolute or repository-relative)
    max_unignored_mb: float = Field(default=500, gt=0)
    compose: SafeGlobs = Field(default_factory=list)
    urls: dict[str, list[str]] = Field(default_factory=dict)       # service -> keys it must set
    user_data: dict[str, list[str]] = Field(default_factory=dict)  # service -> container paths on named volumes
    ship_with_image: SafeGlobs = Field(default_factory=list)       # repository paths that must not be dockerignored


class DocsSection(Strict):
    """A documentation site for the project (0.11.0; R-69)."""

    dir: str = "docs"
    generated: str = "docs/project"
    publish: list[Literal["overview", "contracts", "runs", "values", "releases", "decisions", "exchange", "timeline",
                          "studies", "research", "comparisons", "models"]] = Field(
        default_factory=lambda: ["overview", "contracts", "runs", "values", "releases"])
    title: str | None = None
    readme_report: SafePath | None = None

    @field_validator("dir", "generated")
    @classmethod
    def _inside(cls, v: str) -> str:
        import re

        from .fsutil import escapes_root

        if escapes_root(v):
            raise ValueError(f"{v} must stay inside the repository")
        # T9: plain relative folder names only, so the path is safe in mkdocs.yml and in the Pages workflow
        parts = v.strip("/").split("/")
        if not v.strip("/") or any(p in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]*", p)
                                   for p in parts):
            raise ValueError(f"{v!r} must be a relative folder of plain names (letters, digits, '.', '_', '-')")
        return v.strip("/")

    @model_validator(mode="after")
    def _generated_in_dir(self) -> "DocsSection":
        # T9: MkDocs serves only what is under `dir`, so the generated pages must be a folder strictly inside it
        if not self.generated.startswith(self.dir + "/"):
            raise ValueError(f"[docs] generated ({self.generated}) must be a folder inside [docs] dir ({self.dir}), "
                             "not equal to it or outside it")
        return self


class SkillsSection(Strict):
    """One canonical skills directory and its linked copies (0.9.0 B7, REQ-014; R-60)."""

    canonical: str
    copies: list[str] = Field(default_factory=list)


class StewardConfig(Strict):
    steward: StewardSection
    paths: PathsSection = Field(default_factory=PathsSection)
    privacy: PrivacySection | None = None
    terms: list[TermList] = Field(default_factory=list)
    paper: dict[str, PaperSection] = Field(default_factory=dict)
    talk: dict[str, TalkSection] = Field(default_factory=dict)
    run: RunSection | None = None
    policy: PolicySection | None = None
    spend: SpendSection | None = None
    integrity: IntegritySection | None = None
    evidence: EvidenceSection | None = None
    release: ReleaseSection | None = None
    benchmark: BenchmarkSection | None = None
    storage: StorageSection | None = None
    governance: GovernanceSection | None = None
    exchange: ExchangeSection | None = None
    report: ReportSection | None = None
    boundary: BoundarySection | None = None
    tasks: TasksSection | None = None
    tokens: TokensSection | None = None
    changelog: ChangelogSection | None = None
    branches: BranchesSection | None = None
    skills: SkillsSection | None = None
    repro: ReproSection | None = None
    session: SessionSection | None = None
    agents: AgentsSection | None = None
    stages: list[StageDef] = Field(default_factory=list)
    stages_ledger: str = "development/stages.jsonl"
    accrual: AccrualSection | None = None
    frozen: list[FrozenSet] = Field(default_factory=list)
    pin: list[PinSpec] = Field(default_factory=list)        # 0.17.0: [[pin]] tables (REQ-019)
    licence: LicenceSection | None = None                    # 0.19.0: licence governance (R-79 – R-82)
    publish: PublishSection | None = None                    # 0.19.0: release publishing (model A or B)
    stranger_test: StrangerTestSection | None = None          # 0.20.2: the stranger test (R-87, advisory)
    tidy: TidySection | None = None                          # 0.21.0: stale tasks, pages and memory (R-88, advisory)
    channel: list[Channel] = Field(default_factory=list)     # 0.19.0: tools installed from a stable or a dev source
    data: DataSection | None = None
    model: list[ModelRecord] = Field(default_factory=list)
    studies: StudiesSection | None = None                    # 0.18.0: study records (R-75)
    research: ResearchSection | None = None                  # 0.18.0: research-direction records (R-76)
    pins: PinsSection | None = None
    dependencies: DependenciesSection | None = None
    containers: ContainersSection | None = None
    docs: DocsSection | None = None
    gates: dict[str, GateSection] = Field(default_factory=dict)

    @field_validator("paper")
    @classmethod
    def _paper_names(cls, v: dict[str, PaperSection]) -> dict[str, PaperSection]:
        bad = [k for k in v if not GATE_NAME.match(k)]
        if bad:
            raise ValueError(f"invalid paper names {bad}")
        return v

    @model_validator(mode="after")
    def _paper_needs_02(self) -> "StewardConfig":
        if self.paper and self.steward.schema_ == "steward.toml/0.1":
            raise ValueError("[paper] requires schema steward.toml/0.2")
        if self.talk and self.steward.schema_ == "steward.toml/0.1":
            raise ValueError("[talk] requires schema steward.toml/0.2")
        bad = [k for k in self.talk if not GATE_NAME.match(k)]
        if bad:
            raise ValueError(f"invalid talk names {bad}")
        unknown = [f"{k}->{t.paper}" for k, t in self.talk.items() if t.paper and t.paper not in self.paper]
        if unknown:
            raise ValueError(f"talks link to unknown papers: {unknown}")
        return self

    @model_validator(mode="after")
    def _records_root(self) -> "StewardConfig":
        """SR-006: default record paths follow `[paths] records`; a path set explicitly wins."""
        root = self.paths.records.rstrip("/")
        if root == "development":
            return self

        def moved(v: str) -> str:
            return root + v[len("development"):] if v.startswith("development/") else v
        # a value equal to the built-in default follows the root (templates write defaults out); a customised one stays
        if self.paths.prior_work == PathsSection.model_fields["prior_work"].default_factory():
            self.paths.prior_work = [moved(v) for v in self.paths.prior_work]
        for sec in (self.run, self.policy, self.spend, self.integrity, self.evidence, self.release, self.storage, self.repro, self.session, self.agents, self.tidy):
            if sec is None:
                continue
            for name, f in type(sec).model_fields.items():
                v = getattr(sec, name)
                if isinstance(v, str) and v.startswith("development/") and v == f.default:
                    setattr(sec, name, moved(v))
        return self

    @field_validator("gates")
    @classmethod
    def _gate_names(cls, v: dict[str, GateSection]) -> dict[str, GateSection]:
        bad = [k for k in v if not GATE_NAME.match(k)]
        if bad:
            raise ValueError(f"invalid gate names {bad}")
        return v

    def gate_added(self, name: str) -> list[str]:
        return list(self.gates[name].added) if name in self.gates else []

    def gate_min(self, name: str) -> int:
        return self.gates[name].min_evaluated if name in self.gates else 0

    def gate_require(self, name: str) -> list[str] | None:
        if name in self.gates:
            return self.gates[name].require
        return [r for r in RULE_IDS if r not in ADVISORY] if name == "default" else None


# ---------------------------------------------------------------- benchmark contract
ContractId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


class Dataset(Strict):
    id: Text
    version: Union[Text, Sentinel]
    sha256: Union[Hex64, Sentinel]
    source: Union[Text, Sentinel]


class SplitSet(Strict):
    name: Text
    role: Literal["train", "dev", "validation", "test"]
    ids_file: Union[Text, Sentinel]


class Splits(Strict):
    group_key: Union[Text, Sentinel] = "none"
    time_key: Union[Text, Sentinel] = "none"
    metadata: Text | None = None  # v0.7: a CSV with one row per sample (id, group and time columns)
    id_column: Text = "id"
    temporal: bool = False  # v0.7: train precedes dev / validation, which precede test
    sets: list[SplitSet] = Field(min_length=1)


class Baseline(Strict):
    name: Text
    reference: Union[Reference, Sentinel]
    version: Union[Text, Sentinel]


class MetricDef(Strict):
    name: Text
    definition: Union[Text, Sentinel]
    implementation: Union[Text, Sentinel]


class Metrics(Strict):
    primary: Text
    defs: list[MetricDef] = Field(min_length=1)


class Comparison(Strict):
    method: Union[Text, Sentinel]
    seed: Union[int, Sentinel]
    resamples: Union[Annotated[int, Field(ge=1)], Sentinel]
    alpha: Union[Annotated[float, Field(gt=0, lt=1)], Sentinel]
    output: Text | None = None  # v0.7: the procedure's output, produced by a recorded run (R-48)


class Results(Strict):
    """v0.7: a results matrix {split: {method: {metric: number}}}; methods are the baselines and "candidate"."""
    file: Text
    splits: list[Text] | None = Field(default=None, min_length=1)  # default: every test-role split; never empty (J4)


class Threshold(Strict):
    metric: Text
    comparator: Literal[">=", ">", "<=", "<"]
    value: Union[float, Sentinel]
    against: Annotated[str, Field(pattern=r"^(absolute|baseline:.+)$")]


class Exclusions(Strict):
    rules: list[Text] = Field(default_factory=list)
    excluded_ids_file: Union[Text, Sentinel, None] = None


class Outputs(Strict):
    required: Union[list[Text], Sentinel] = Field(default_factory=list)


LEAKAGE_TYPES = ("near_duplicate", "batch_confounding", "preprocessing_fit", "label_leakage", "test_tuning",
                 "undeclared_groups", "test_reuse")


class LeakageDecl(Strict):
    """v0.7: a declaration about a leakage type that cannot be detected from identifiers (R-49). Not a check."""
    status: Literal["checked", "not_applicable"]
    evidence: Text | None = None  # a repository file; an optional #anchor is ignored
    reason: Text | None = None


class Contract(Strict):
    schema_: Literal["steward.contract/0.1"] = Field(alias="schema")
    id: ContractId
    title: Text
    analysis: Literal["exploratory", "confirmatory"]
    datasets: list[Dataset] = Field(min_length=1)
    splits: Splits
    baselines: list[Baseline] = Field(min_length=1)
    metrics: Metrics
    comparison: Comparison | None = None
    thresholds: list[Threshold] = Field(default_factory=list)
    exclusions: Exclusions | None = None
    outputs: Outputs | None = None
    results: Results | None = None
    leakage: dict[str, Union[LeakageDecl, Sentinel]] | None = None
    minimum_units: int | None = Field(default=None, ge=1)        # REQ-010: checked by R-67 against the power table
    power_target: float = Field(default=0.8, gt=0, le=1)
    llm_eval: "LlmEval | None" = None                             # 0.18.0: evaluating language models (R-78)


class LlmModel(Strict):
    name: Text
    training_cutoff: _dt_date | None = None  # the provider's stated cutoff; unknown leaves contamination undecided
    role: Literal["candidate", "judge"] = "candidate"


class LlmEval(Strict):
    """Evaluating language models on scientific cases (0.18.0, R-78): contamination by publication date, leakage of a
    study (group) across tuning and test, prompts frozen, and no model judging itself."""
    cases: SafePath                # CSV in the repository: one row per case with the columns below
    id_column: Text = "id"
    published_column: Text = "published"   # ISO date the case's source was public
    group_column: Text = "group"           # e.g. the study or series the case comes from
    split_column: Text = "split"           # tune | dev | test (any other value is ignored)
    models: list[LlmModel] = Field(min_length=1)
    prompts: Text | None = None    # the name of a [[frozen]] set holding the prompts


# ---------------------------------------------------------------- prior-work record
class Work(Strict):
    id: Text
    citation: Text
    identifier: Union[Identifier, Sentinel]
    relation: Literal["closest_method", "baseline", "related"]
    summary: Union[Text, Sentinel]


class ComparisonRow(Strict):
    dimension: Text
    ours: Union[Text, Sentinel]
    theirs: dict[str, Union[Text, Sentinel]] = Field(default_factory=dict)


class ClaimedDifference(Strict):
    id: Text
    statement: Text
    evidence: Union[list[Annotated[str, Field(pattern=r"^contract:.+$")]], Sentinel]


class Judgment(Strict):
    novelty: Text


class PriorWork(Strict):
    schema_: Literal["steward.prior_work/0.1"] = Field(alias="schema")
    id: Text
    question: Text
    works: list[Work] = Field(min_length=1)
    comparisons: list[ComparisonRow] = Field(default_factory=list)
    claimed_differences: list[ClaimedDifference] = Field(default_factory=list)
    judgment: Judgment


# ---------------------------------------------------------------- paper spec and venue profile (C16)
class Question(Strict):
    id: Text
    text: Union[Text, Sentinel]


class Contribution(Strict):
    id: Text
    text: Union[Text, Sentinel]
    strength: Literal["demonstrates", "suggests", "explores"]
    evidence: Union[list[Annotated[str, Field(pattern=r"^(contract|value|display|run|claim):.+$")]], Sentinel] = Field(default_factory=list)


class SectionPlan(Strict):
    id: Text
    title: Text
    purpose: Union[Text, Sentinel] = "TBD"


class PaperSpec(Strict):
    schema_: Literal["steward.paper_spec/0.1"] = Field(alias="schema")
    type: Literal["preprint", "conference", "journal", "thesis", "other"]
    title_candidates: Union[list[Text], Sentinel]
    story: Union[Text, Sentinel]
    questions: list[Question] = Field(default_factory=list)
    contributions: list[Contribution] = Field(default_factory=list)
    sections: list[SectionPlan] = Field(default_factory=list)
    never_claim: list[Text] = Field(default_factory=list)
    limitations: Union[list[Text], Sentinel]
    names: dict[str, Union[Text, Sentinel]] = Field(default_factory=dict)
    data_availability: Text | None = None  # 0.20.0 (B5): the file (relative to the paper's dir) holding the statement


IntOrNone = Union[Annotated[int, Field(ge=0)], Literal["none"], Sentinel]


class VenueLimits(Strict):
    pages_main: IntOrNone = "TBD"
    pages_total: IntOrNone = "TBD"
    abstract_words: IntOrNone = "TBD"
    title_words: IntOrNone = "TBD"


class VenueAnonymity(Strict):
    double_blind: Union[bool, Sentinel] = "TBD"


class VenueRequired(Strict):
    sections: Union[list[Text], Sentinel] = "TBD"
    declarations: Union[list[Text], Sentinel] = "TBD"


class VenueFigures(Strict):
    formats: Union[list[Text], Sentinel] = "TBD"
    min_dpi: Union[Annotated[int, Field(ge=1)], Sentinel] = "TBD"


class ChecklistItem(Strict):
    item: Text
    kind: Literal["human", "auto"]


class Venue(Strict):
    schema_: Literal["steward.venue/0.1"] = Field(alias="schema")
    name: Text
    kind: Literal["preprint", "conference", "journal"]
    source_url: Union[Annotated[str, Field(pattern=r"^url:https?://\S+$")], Sentinel]
    retrieved: Union[Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")], Sentinel]
    limits: VenueLimits = Field(default_factory=VenueLimits)
    anonymity: VenueAnonymity = Field(default_factory=VenueAnonymity)
    required: VenueRequired = Field(default_factory=VenueRequired)
    figures: VenueFigures = Field(default_factory=VenueFigures)
    checklist: list[ChecklistItem] = Field(default_factory=list)


# ---------------------------------------------------------------- sentinel scanning
def find_sentinels(data: Any, path: str = "") -> list[tuple[str, str]]:
    """Every (field path, sentinel) in validated data. Only deferrable fields can hold one after validation."""
    found: list[tuple[str, str]] = []
    if isinstance(data, BaseModel):
        for name in type(data).model_fields:
            alias = type(data).model_fields[name].alias or name
            found += find_sentinels(getattr(data, name), f"{path}.{alias}" if path else alias)
    elif isinstance(data, dict):
        for k in sorted(data):
            found += find_sentinels(data[k], f"{path}.{k}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            found += find_sentinels(item, f"{path}[{i}]")
    elif isinstance(data, str) and data in SENTINELS:
        found.append((path, data))
    return found


def format_errors(exc: Exception) -> list[dict[str, Any]]:
    """Pydantic errors as deterministic detail records."""
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return [{"code": "schema", "message": str(exc)}]
    seen: set[tuple[str, str]] = set()
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in err["loc"] if not _is_union_tag(p))
        seen.add((loc, err["msg"]))
    # A failed union also reports "should be a sentinel"; drop that noise when the field has a real error.
    fields_with_real = {f for f, m in seen if m != _SENTINEL_MSG}
    kept = {(f, m) for f, m in seen if not (m == _SENTINEL_MSG and f in fields_with_real)}
    return [{"code": "schema", "field": f, "message": m} for f, m in sorted(kept)]


_SENTINEL_MSG = "Input should be 'TBD' or 'unknown'"
_UNION_TAGS = {"int", "float", "str", "bool", "none"}


def _is_union_tag(part: Any) -> bool:
    p = str(part)
    return p in _UNION_TAGS or p.startswith(("function-after[", "literal[", "list[", "union[", "constrained-"))


# ---------------------------------------------------------------- the configuration overlay (0.9.0 B9, REQ-006)
OVERLAY_NAME = "steward.local.toml"
OVERLAY_LISTS = ("contracts", "prior_work")  # [paths] lists an overlay may extend


def overlay_path(root: Path) -> Path | None:
    """`STEWARD_CONFIG_OVERLAY` (relative to the repository, or absolute), else `steward.local.toml` when present."""
    import os

    env = os.environ.get("STEWARD_CONFIG_OVERLAY")
    if env:
        p = Path(env).expanduser()
        return p if p.is_absolute() else root / p
    p = root / OVERLAY_NAME
    return p if p.is_file() else None


def merge_overlay(base: dict[str, Any], over: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
    """(the base configuration with the overlay's gate additions, every key the overlay may not set, the record globs
    to add after validation). An overlay only adds: new gates; rules a base gate must also pass (`added`, which
    never counts toward the base gate's `min_evaluated`: review Q1); a higher `min_evaluated`;
    `records_required = true`; more record globs (added after the records root moves the defaults: review Q2).
    Never [policy], trust settings or term lists (Article II; RELEASE_v0.9.0_SPEC §2.9)."""
    import copy

    merged = copy.deepcopy(base)
    refused: list[str] = []
    adds: dict[str, list[str]] = {}
    for key, val in over.items():
        if key == "gates" and isinstance(val, dict):
            gates = merged.setdefault("gates", {})
            if not isinstance(gates, dict):  # R1: a malformed base table is refused, never a crash
                refused.append("gates (the base table is not a table)")
                continue
            for name, g in val.items():
                if not isinstance(g, dict) or not isinstance(gates.get(name, {}), dict):
                    refused.append(f"gates.{name}")
                    continue
                if isinstance(g.get("require"), list) and any(r not in RULE_IDS for r in g["require"]):
                    refused.append(f"gates.{name}.require (unknown rule ids)")  # R1: added rules are validated too
                    continue
                existing = name in gates or name == "default"
                prior = gates.get(name, {})
                bad_base = [k for k in ("require", "added") if k in prior and not (
                    isinstance(prior[k], list) and all(isinstance(x, str) for x in prior[k]))]
                bm = prior.get("min_evaluated", 0)
                if "min_evaluated" in prior and (not isinstance(bm, int) or isinstance(bm, bool) or bm < 0):
                    bad_base.append("min_evaluated")
                if bad_base:  # R1 (0.12.0): an overlay never repairs or reshapes an invalid base gate
                    refused.append(f"gates.{name} (the base gate's {', '.join(bad_base)} is not valid)")
                    continue
                cur = gates.setdefault(name, {})
                if name == "default" and "require" not in cur:
                    cur["require"] = [r for r in RULE_IDS if r not in ADVISORY]
                for gk, gv in g.items():
                    if gk == "require" and isinstance(gv, list):
                        if existing:
                            have = set(cur.get("require", [])) | set(cur.get("added", []))
                            cur["added"] = [*cur.get("added", []), *[r for r in gv if r not in have]]
                        else:
                            cur["require"] = list(dict.fromkeys(gv))
                    elif gk == "min_evaluated" and isinstance(gv, int) and not isinstance(gv, bool):
                        base_min = cur.get("min_evaluated", 0)
                        cur["min_evaluated"] = max(base_min if isinstance(base_min, int) else 0, gv)
                    else:
                        refused.append(f"gates.{name}.{gk}")
        elif key == "paths" and isinstance(val, dict):
            paths = merged.setdefault("paths", {})
            for pk, pv in val.items():
                if pk == "records_required" and pv is True:
                    paths["records_required"] = True
                elif pk in OVERLAY_LISTS and isinstance(pv, list) and all(isinstance(x, str) for x in pv):
                    adds[pk] = list(pv)
                else:
                    refused.append(f"paths.{pk}")
        else:
            refused.append(key)
    return merged, refused, adds


def apply_adds(cfg: "StewardConfig", adds: dict[str, list[str]]) -> None:
    for k, v in adds.items():
        setattr(cfg.paths, k, list(dict.fromkeys([*getattr(cfg.paths, k), *v])))


def config_data(root: Path, read=None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(merged configuration data, overlay info {path, sha256, refused, adds} or None). Kept for callers that need
    the data; `load_config` is the loader every command uses."""
    import hashlib
    import tomllib

    read = read or (lambda rel: (root / rel).read_bytes())
    data = tomllib.loads(read("steward.toml").decode("utf-8"))
    op = overlay_path(root)
    if op is None:
        return data, None
    raw = op.read_bytes()
    merged, refused, adds = merge_overlay(data, tomllib.loads(raw.decode("utf-8")))
    return merged, {"path": overlay_label(root, op), "sha256": hashlib.sha256(raw).hexdigest(), "refused": refused,
                    "adds": adds}


def overlay_label(root: Path, op: Path) -> str:
    try:
        return op.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return "(an overlay outside the repository)"


def load_config(root: Path) -> "StewardConfig":
    """The effective configuration, exactly as R-01 builds and checks it (one source; review Q3). Raises ValueError
    with R-01's reason when R-01 fails."""
    from .rules import Ctx, r01

    ctx = Ctx(root=root)
    res = r01(ctx)
    if ctx.config is None or any(r.status.value == "FAIL" for r in res):
        why = "; ".join(f"{r.reason} ({', '.join(d.get('code', '') for d in r.details if d.get('code'))})" for r in res)
        raise ValueError(why)
    return ctx.config
