"""Models for the JSON documents advertised by the CLI interface."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, create_model
from typing_extensions import NotRequired, TypedDict

from .audit import WITHHELD
from .interface import ERROR_SCHEMA, INTERFACE_SCHEMA, OTHER_SCHEMAS, READ_COMMANDS, TAGGED_COMMANDS
from .issues import LastError
from .milestones import Outcome
from .models import Hex64, PinDeprecation
from .records import Study as StudyRecord
from .sprint import Limits, Window

Object = dict[str, JsonValue]
Sha256Ref = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ProgressAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "anyOf": [{"required": ["where", "usage", "pending", "reach"]}, {"required": [WITHHELD]}],
    })

    schema_: Literal["steward.progress_audit/0.1"] = Field(alias="schema")
    where: Object = Field(default_factory=dict)
    usage: Object = Field(default_factory=dict)
    pending: Object = Field(default_factory=dict)
    reach: Object = Field(default_factory=dict)
    redacted: JsonValue = Field(None, alias=WITHHELD)

class Command(TypedDict):
    argv: list[str]
    schema: str | None
    legacy_argv: NotRequired[list[str]]


class Problem(TypedDict):
    status: str
    code: str
    field: NotRequired[str]
    path: NotRequired[str]
    message: NotRequired[str]
    value: NotRequired[JsonValue]


class Threshold(TypedDict):
    split: str
    metric: str
    against: str
    state: Literal["met", "not met", "not evaluable"]
    message: str


class IdOverlap(TypedDict):
    splits: list[str]
    count: int
    ids: list[str]


class GroupOverlap(TypedDict):
    splits: list[str]
    count: int
    groups: list[str]


class ImpactOutput(TypedDict):
    output: str
    run: str
    state: Literal["current", "stale", "changed since run"]
    inputs_changed: list[str]
    code_changed: list[str]


class ImpactValue(TypedDict):
    paper: str
    value: str
    source: str


class ImpactDisplay(TypedDict):
    paper: str
    display: str
    inputs: list[str]


class Difference(TypedDict):
    a: JsonValue
    b: JsonValue
    field: str


class Comparison(TypedDict):
    a: JsonValue
    b: JsonValue
    pointer: NotRequired[str]
    output: NotRequired[str]
    tolerance: NotRequired[str | None]
    leaf: NotRequired[bool]
    state: str
    within: bool


class Run(TypedDict):
    run: str | None
    label: str
    status: str
    duration_s: float | None
    peak_rss_mb: float | None
    exit_code: int | None
    time: str | None


class Delivery(TypedDict):
    peer: str
    state: str


class Observation(TypedDict):
    by: str
    state: str
    evidence: str


class ExchangeItem(TypedDict):
    # The local status view also lists entries whose front matter has not passed validation.
    id: JsonValue
    place: Literal["inbox", "outbox", "responses", "oneway", "peer"]
    kind: JsonValue
    title: JsonValue
    state: str
    delivery: NotRequired[Delivery]
    observed: NotRequired[Observation]
    observed_latest: NotRequired[Observation]


class Dependency(TypedDict):
    name: str
    version: str
    licence: str | None
    how: str | None
    status: str
    why: str
    use: NotRequired[Literal["linked", "bundled", "invoked"]]
    exception: NotRequired[bool]


class Caller(TypedDict):
    path: str
    via: Literal["module", "reference", "module+reference"]
    ignored: NotRequired[bool]


class Pin(TypedDict):
    name: str
    package: str
    version: str
    state: str
    reasons: list[str]
    protects: list[str]
    callers: NotRequired[list[str] | None]
    caller_rule: NotRequired[str]
    caller_detail: NotRequired[list[Caller] | None]
    deprecated: NotRequired[PinDeprecation]
    object: NotRequired[Sha256Ref]  # W12 F10: the retire authorization's object, "sha256:<hex>" (pins.plan)


class ResearchRecord(TypedDict):
    id: str
    kind: str
    title: str
    date: str
    check: str


class Study(TypedDict):
    id: str
    title: str
    kind: str
    status: str
    check: str | None
    inputs: int
    papers: list[str]


class DirectoryUsage(TypedDict):
    path: str
    state: Literal["outside", "absent", "present"]
    cap_mb: float
    size_mb: NotRequired[float]
    over: NotRequired[bool]


class FileSize(TypedDict):
    path: str
    size_mb: float


class CleanupCandidate(TypedDict):
    cls: str
    path: str
    kind: Literal["dir", "file"]
    size: int
    volume: str
    external: bool
    users: list[str]
    refusals: list[str]
    entries: int


class Artifact(TypedDict):
    path: str
    state: Literal["outside", "absent", "changing", "present"]
    sha256: NotRequired[str]
    size: NotRequired[int]
    annex_key: NotRequired[bool]


class MilestoneStatus(TypedDict):
    id: str
    title: str
    kind: str
    due: str
    internal: str
    days_left: float
    state: str
    open_work: int
    progress: dict[str, Object]
    outcome: NotRequired[Outcome]


class DecisionSource(TypedDict):
    path: str
    line: int
    heading: str


class DecisionQuote(TypedDict):
    who: str | None
    text: str


class RecordedDecision(DecisionSource):
    date: str
    title: str
    quotes: list[DecisionQuote]
    decision: str | None
    consequences: str | None
    body: str


class OpenDecision(TypedDict):
    question: str
    options: list[str]
    path: str
    line: int


class DateDrift(TypedDict):
    id: str
    first_due: str | None
    current_due: str
    days: float | None
    moves: int
    recorded_move: bool


class ScopeDrift(TypedDict):
    reason: Literal["unassigned_task", "missing_task", "dropped_task", "unstarted_task", "roadmap_without_task"]
    id: str
    milestone: str | None
    path: str
    line: int | None


class OrderDrift(TypedDict):
    earlier: str
    later: str
    started_tasks: list[str]


class DueChange(TypedDict):
    before: str
    after: str


class PlanChange(TypedDict):
    kind: Literal["milestone", "roadmap"]
    id: str
    path: str
    commit: str | None
    time: str | None
    fields: list[str]
    due: DueChange | None
    decision: DecisionSource | None


class TimelineDrift(TypedDict):
    history: Literal["available", "unavailable", "shallow", "partial"]
    notes: list[str]
    date: list[DateDrift]
    scope: list[ScopeDrift]
    order: list[OrderDrift]
    changes: list[PlanChange]


class AgentTotal(TypedDict):
    agent: str
    tokens: int


class ModelTotal(AgentTotal):
    model: str | None
    input: int
    output: int
    cache_read: int | None
    cache_write: int | None
    cost: float | None


class ToolOutput(TypedDict):
    agent: str
    session: str | None
    bytes: int
    log_path: str
    time_ms: int
    paths: list[str]


class FileReads(TypedDict):
    path: str
    reads: int


class TaskWindow(TypedDict):
    """X05: one window of a task and the record it came from: `task-tokens` (opened by hand), `agents` (the agents
    ledger), `sprint` (a sprint ledger), `run` (the run ledger) or `all activity` (no window recorded)."""
    source: Literal["task-tokens", "agents", "sprint", "run", "all activity"]
    ledger: str | None
    start: str
    end: str | None


class TaskAttempt(TypedDict):
    """0.23.0 (STW-061 D02): one attempt of a delegated sprint task, as the agents ledger records it."""

    attempt: int
    agent: str
    model: str | None
    outcome: str | None  # redelegated, review, done or failed
    reason: str | None  # the "cannot run" ending of a re-delegated attempt
    tokens: int | None


class TaskTokens(TypedDict):
    task: str
    tokens: int | None
    cost: float | None
    models: list[ModelTotal]
    agents: list[AgentTotal]
    status: str
    issues: list[str]
    files_read: list[FileReads]
    tool_outputs: list[ToolOutput]
    windows: NotRequired[list[TaskWindow]]  # X05: with --format json; oldest first
    attempts: NotRequired[list[TaskAttempt]]  # D02: a sprint task's attempts by the supervisor; newest first


class SourceFile(TypedDict):
    path: str
    status: str
    issues: list[str]


class Source(TypedDict):
    status: str
    files: list[SourceFile]


def _document(name, tag, **fields):
    return create_model(
        name,
        __config__=ConfigDict(extra="forbid"),
        schema_=(Literal[tag], Field(alias="schema")),
        **{key: (annotation, ...) for key, annotation in fields.items()},
    )


SCHEMAS = {"steward.progress_audit-0.1.schema.json": ProgressAudit,
           "steward.last_error-0.1.schema.json": LastError}


def _add(command, name, **fields):
    tag = INTERFACE_SCHEMA if command == "interface" else TAGGED_COMMANDS[command]
    stem, version = tag.split("/")
    SCHEMAS[f"{stem}-{version}.schema.json"] = _document(name, tag, **fields)


_add("interface", "Interface", interface_version=Literal[1], tool_version=str, schema_files=dict[str, str],
     error_schema=str, commands=dict[str, Command], exit_codes=dict[str, str])
_add("benchmark results", "BenchmarkResults", cells=dict[str, str], missing=list[str],
     thresholds=list[Threshold], problems=list[Problem])
_add("benchmark splits", "BenchmarkSplits", counts=dict[str, int], id_overlap=list[IdOverlap],
     group_overlap=list[GroupOverlap], time_range=dict[str, list[str]], checked=list[str], problems=list[Problem])
_add("diff impact", "DiffImpact", outputs=list[ImpactOutput], downstream=list[ImpactValue | ImpactDisplay], coverage=str)
_add("diff run", "DiffRun", verdict=Literal["repeatable", "not repeatable", "incomplete"], repeatable=bool,
     compared=int, evidence=int, metrics_precision=dict[str, str], not_comparable=int, finished=bool,
     results=list[Comparison], environment_differences=list[Difference])
_add("diff runs", "DiffRuns", runs=list[Run])
_add("exchange status", "ExchangeStatus", items=list[ExchangeItem])
_add("licence inventory", "LicenceInventory", declared=str, distribution=str, policy=str, dependencies=list[Dependency])
_add("pins status", "PinsStatus", pins=list[Pin])
_add("research list", "ResearchList", records=list[ResearchRecord], invalid=list[str])
_add("storage audit", "StorageAudit", directories=list[DirectoryUsage], largest_untracked=list[FileSize])
_add("storage scan", "StorageScan", candidates=list[CleanupCandidate])
_add("storage verify", "StorageVerify", artifacts=list[Artifact], problems=list[Problem])
_add("study list", "StudyList", studies=list[Study], invalid=list[str])
_add("timeline", "Timeline", milestones=list[MilestoneStatus], drift=TimelineDrift)
_add("tokens report", "TokensReport", tasks=list[TaskTokens], sources=dict[str, Source], issues=list[str],
     currency=str | None)


class PlanTask(TypedDict):
    id: str
    state: str


class PlanTaskProgress(TypedDict):
    done: int
    total: int
    tasks: list[PlanTask]


class PlanRecord(TypedDict):
    id: str
    title: str
    state: str
    date: str | None
    path: str
    line: Annotated[int, Field(ge=1)]


class PlanDrift(TypedDict):
    date: DateDrift | None
    scope: list[ScopeDrift]
    order: list[OrderDrift]
    changes: list[PlanChange]


class RoadmapPlan(PlanRecord):
    kind: Literal["roadmap"]
    progress: PlanTaskProgress | None
    drift: PlanDrift


class ReleasePlanProgress(TypedDict):
    tag: str | None


class ReleasePlanDrift(TypedDict):
    changed_since_tag: bool


class ReleasePlan(PlanRecord):
    kind: Literal["release"]
    progress: ReleasePlanProgress
    drift: ReleasePlanDrift | None


class SprintPlanDrift(TypedDict):
    unplanned_tasks: list[str]
    missing_tasks: list[str]


class SprintPlan(PlanRecord):
    kind: Literal["sprint"]
    progress: PlanTaskProgress
    drift: SprintPlanDrift | None


class MilestonePlan(PlanRecord):
    kind: Literal["milestone"]
    progress: dict[str, Object]
    drift: PlanDrift


Plan = Annotated[RoadmapPlan | ReleasePlan | SprintPlan | MilestonePlan, Field(discriminator="kind")]


# 0.21.0 (W02, STW-047 C3 – C8): the documents of explain, check --digest-only, init --dry-run, skills list, and the
# error document of a command that needs a configured project.
def _add_tag(tag, name, **fields):
    stem, version = tag.split("/")
    SCHEMAS[f"{stem}-{version}.schema.json"] = _document(name, tag, **fields)


_add_tag(OTHER_SCHEMAS["plans"], "Plans", plans=list[Plan],
         history=Literal["available", "unavailable", "shallow", "partial"], notes=list[str])


class ManifestFile(TypedDict):
    path: str
    size: int
    sha256: Hex64


class GitState(TypedDict):
    head: str
    dirty: str


# W12 F11: the two documents `steward interface` names that had no bundled schema. Both commands write JSON by default
# (no --format option), so these schemas describe their output as it has always been written.
_add_tag("steward.submission_manifest/0.1", "SubmissionManifest", paper=str, git=GitState | Literal["unknown"],
         files=list[ManifestFile], not_present=list[str])
_add_tag("steward.shards/0.1", "Shards", shards=list[list[str]], totals=list[float], merge=str)
_add_tag(OTHER_SCHEMAS["decisions"], "Decisions", entries=list[RecordedDecision], open_decisions=list[OpenDecision])
_add_tag(OTHER_SCHEMAS["upgrade --check"], "Upgrade", installed_version=str, latest_version=str | None,
         source=Literal["exchange", "pypi"] | None, install_method=Literal["uv-tool", "pipx", "pip", "channel", "unknown"],
         channel=Literal["dev", "stable"] | None, upgrade_available=bool, command=list[str] | None, note=str | None)


class CodeFix(TypedDict):
    code: str
    fix: str | None


class RuleExplained(TypedDict):
    rule: str
    name: str
    version: int
    area: str
    areas: list[str]
    governance: str
    checks: str
    why: str
    pass_does_not_mean: str
    fix: str
    codes: list[CodeFix]
    run: str


class ReportDigests(TypedDict):
    inputs_digest: str
    tree_digest: str
    tool_version: str


class InitAction(TypedDict):
    verb: Literal["create", "skip", "update", "unchanged", "print"]
    path: str
    note: str
    content: NotRequired[str]


class Bundle(TypedDict):
    name: str
    budget_words: int | None
    skills: list[str]


class Skill(TypedDict):
    name: str
    bundles: list[str]
    description: str


class SkillCopy(TypedDict):
    code: str
    path: str
    failed: bool
    message: NotRequired[str]
    value: NotRequired[JsonValue]


class SkillsProject(TypedDict):
    configured: bool
    canonical: str | None
    canonical_usable: bool | None
    installed: list[str]
    copies: list[SkillCopy]


_add_tag(OTHER_SCHEMAS["explain"], "Explain", tool_version=str, rules=list[RuleExplained])
_add_tag(OTHER_SCHEMAS["check --digest-only"], "Digest", tool_version=str, inputs_digest=str | None,
         tree_digest=str, report=ReportDigests, current=bool, changed=list[str], reason=str)
_add_tag(OTHER_SCHEMAS["init"], "InitPlan", tool_version=str, dry_run=Literal[True], profile=str, kits=list[str],
         goals=list[str], templates=list[str], actions=list[InitAction], tables=list[str], next=list[str])
_add_tag(OTHER_SCHEMAS["skills list"], "SkillsList", tool_version=str, bundles=list[Bundle], skills=list[Skill],
         project=SkillsProject | None)
_add_tag(ERROR_SCHEMA, "Error", tool_version=str, code=Literal["not_configured", "invalid_input"], message=str, exit=int,
         hint=str | None)


# 0.21.0 (W03; STW-048 C10, C12; C21): steward next, steward tidy, steward notifications.
TIDY_KINDS = Literal["stale_task", "contradiction", "stale_page", "exchange", "leftover", "memory"]


class TidyItem(TypedDict):
    id: str
    kind: TIDY_KINDS
    subject: str
    message: str
    age_days: float | None
    command: str | None


class TidyThresholds(TypedDict):
    stale_days: int
    handoff_days: int
    memory_days: int
    archive: str
    memory_folders: int


class TidyCounts(TypedDict):
    stale_task: int
    contradiction: int
    stale_page: int
    exchange: int
    leftover: int
    memory: int


class Resume(TypedDict):
    path: str
    age_days: float | None
    committed: bool
    next: list[str]
    open_decisions: list[str]
    command: str


class Blocker(TypedDict):
    kind: Literal["rule", "task", "exchange", "signature"]
    id: str
    command: str


class NextMilestone(TypedDict):
    id: str
    title: str
    kind: str
    due: str
    days_left: float
    state: str
    open_work: int
    blockers: list[Blocker]
    command: str


class NextEntry(TypedDict):
    kind: Literal["signature", "decision", "exchange", "task_waiting", "task_failed", "task_done", "task_running",
                  "task_ordered", "task_review", "task_limited"]  # D02: the master's review; a wait for a reset
    id: str
    title: str
    source: str
    command: str
    time: str | None


class SinceEntry(TypedDict):
    """P03: one change since the last session handoff, newest first, with its source."""
    kind: Literal["commit", "decision", "exchange", "sprint", "release"]
    id: str
    title: str
    source: str
    line: int | None
    time: str | None


class NextTidy(TypedDict):
    counts: TidyCounts
    total: int
    command: str


class Notification(TypedDict):
    id: str
    kind: Literal["upgrade", "exchange", "task_finished", "task_failed", "task_waiting", "approval", "gate",
                  "milestone"]
    time: str | None
    source: str
    title: str
    command: str
    urgent: bool


_add_tag(OTHER_SCHEMAS["next"], "Next", tool_version=str, now=str, project=str, resume=Resume | None,
         milestone=NextMilestone | None, waiting_on_human=list[NextEntry], waiting_on_agents=list[NextEntry],
         since=list[SinceEntry], tidy=NextTidy, notes=list[str])
_add_tag(OTHER_SCHEMAS["tidy"], "Tidy", tool_version=str, now=str, thresholds=TidyThresholds, items=list[TidyItem],
         counts=TidyCounts, total=int, notes=list[str])
_add_tag(OTHER_SCHEMAS["notifications"], "Notifications", tool_version=str, now=str, days=int,
         items=list[Notification], notes=list[str])


class BoardTaskWindow(TypedDict):
    """P03: the task's newest recorded window (`task-tokens`, `agents` or `sprint`)."""
    open: bool
    start: str
    end: str | None
    source: Literal["task-tokens", "agents", "sprint"]
    ledger: str | None


class BoardTask(TypedDict):
    id: str
    path: str
    status: str
    closed: bool
    archived: bool
    owner: str | None
    implementer: str | None
    window: BoardTaskWindow | None
    stale: bool
    stale_reason: str | None


class PendingAuthorization(TypedDict):
    nonce: str
    payload_sha256: Hex64
    repo_id: str
    project: str
    peer: str | None
    requester: str | None
    action: str
    object: str
    scope: str
    budget: str
    expires: str
    baseline: str
    state: Literal["waiting", "signed", "expired", "foreign"]
    summary: NotRequired[str]
    tag: str
    path: str
    sign_argv: list[str] | None
    sign_command: str | None


class SkippedPeer(TypedDict):
    peer: str
    reason: Literal["no_local_checkout", "not_steward_project"]


class VerifiedAuthorization(TypedDict):
    tag: str
    verified: Literal[True]
    action: str
    principal: str
    trust_source: str


class UnverifiedAuthorization(TypedDict):
    tag: str
    verified: Literal[False]
    step: str
    message: str


class SignerKey(TypedDict):
    principal: str
    type: str
    hardware: str


class SprintCheck(TypedDict):
    command: str
    exit: int | None
    note: NotRequired[str]


class SprintCommit(TypedDict):
    commit: str
    subject: str


class SprintStep(TypedDict):
    tool: str
    command: str


class SprintAttempt(TypedDict):
    agent: str | None
    model: str | None
    role: Literal["worker", "master"] | None
    started: str | None
    ended: str | None
    outcome: Literal["redelegated", "review", "done", "failed"] | None
    reason: str | None
    reset: str | None


class SprintDelegation(TypedDict):
    """0.23.0 (STW-061 D02): who ran a delegated task, a wait for a reset time, the review brief, and every attempt
    (newest first)."""

    role: Literal["worker", "master"] | None
    agent: str | None
    until: str | None
    review: str | None
    attempts: list[SprintAttempt]


class SprintTask(TypedDict):
    id: str
    title: str
    state: str
    ordered: bool
    held: bool
    after: list[str]
    branch: str | None
    run: str | None
    commit: str | None
    checks: list[SprintCheck]
    limits: Limits
    note: str | None
    agent: Literal["claude-code", "codex", "antigravity", "shell", "auto"]
    model: str | None
    permissions: Literal["read-only", "edit", "edit-and-run"] | None
    started: str | None
    ended: str | None
    log: str | None
    run_log: str | None
    commits: list[SprintCommit]
    changed_files: list[str]
    last_commit_subject: str | None
    last_step: SprintStep | None
    uncommitted: list[str]
    delegation: NotRequired[SprintDelegation]  # D02: only for a delegated task


class Handoff(TypedDict):
    path: str
    text: str | None
    commit: str | None
    commit_date: str | None


class FrozenStatus(TypedDict):
    name: str
    sha256: str
    confirmatory: bool
    amendment_proposed: bool


class DatasetStatus(TypedDict):
    name: str
    role: str


class ChannelStatus(TypedDict):
    name: str
    channel: Literal["dev", "stable"] | None
    tag: str | None
    time: str | None


class ReadProblem(TypedDict):
    code: str
    message: str


class DisplayStatus(TypedDict):
    id: str
    kind: Literal["figure", "table"]
    label: str
    output: str
    missing: list[str]


class CitationProblem(ReadProblem):
    path: NotRequired[str]


class UnverifiedCitation(TypedDict):
    key: str
    id: str


class MismatchedCitation(UnverifiedCitation):
    title: str


class Preference(TypedDict):
    value: JsonValue
    layer: str


class TalkSuggestion(TypedDict):
    claim_ceiling: str | None
    pattern: str
    roles: list[str]
    max_slides: int
    max_slides_source: Literal["set", "auto"]
    density: str
    preferences: dict[str, Preference]


_add_tag(READ_COMMANDS["task board"], "TaskBoard", board=str | None, tasks=list[BoardTask])
_add_tag(READ_COMMANDS["authorize pending"], "AuthorizePending", items=list[PendingAuthorization],
         waiting=int, skipped=list[SkippedPeer])
_add_tag(READ_COMMANDS["authorize list"], "AuthorizeList", items=list[VerifiedAuthorization | UnverifiedAuthorization])
_add_tag(READ_COMMANDS["authorize keys"], "AuthorizeKeys", baseline=str, keys=list[SignerKey])
_add_tag(READ_COMMANDS["sprint status"], "SprintStatus", id=str, path=str, window=Window,
         window_state=Literal["not open", "open", "ended"], dispatch=Literal["order", "auto"], tasks=list[SprintTask])
_add_tag(READ_COMMANDS["session start"], "SessionStart", constitution=str | None, handoff=Handoff)
_add_tag(READ_COMMANDS["study show"], "StudyShow", path=str, check=str | None, study=StudyRecord)
_add_tag(READ_COMMANDS["integrity status"], "IntegrityStatus", frozen=list[FrozenStatus], datasets=list[DatasetStatus])
_add_tag(READ_COMMANDS["spend status"], "SpendStatus", calls=int, committed=float, actual=float, unknown_cost_calls=int,
         cap=float, currency=str)
_add_tag(READ_COMMANDS["release status"], "ReleaseStatus", mode=Literal["mirror", "open"], remote=str | None,
         last_public=str | None, last_public_pushed=bool | None, unpublished=list[str], staging=str | None)
_add_tag(READ_COMMANDS["channel status"], "ChannelsStatus", channels=list[ChannelStatus])
_add_tag(READ_COMMANDS["paper values"], "PaperValues", paper=str, path=str, values=dict[str, str], errors=dict[str, ReadProblem])
_add_tag(READ_COMMANDS["paper displays"], "PaperDisplays", paper=str, path=str, displays=list[DisplayStatus])
_add_tag(READ_COMMANDS["paper citations"], "PaperCitations", paper=str, path=str, verified=int,
         mismatched=list[MismatchedCitation], unverified=list[UnverifiedCitation], problems=list[CitationProblem])
_add_tag(READ_COMMANDS["talk plan"], "TalkPlanStatus", talk=str, path=str, stage=str,
         stage_source=Literal["confirmed", "proposed"], purpose=str, feedback=str, audience=str, missing=list[str],
         suggestion=TalkSuggestion | None)
_add_tag(READ_COMMANDS["talk prefs"], "TalkPrefs", talk=str | None, preferences=dict[str, Preference])


class IssueGroup(TypedDict):
    fingerprint: Hex64
    count: int
    versions: list[str]
    projects: list[str]
    items: list[str]


_add_tag(OTHER_SCHEMAS["issues inbox"], "IssuesInbox", groups=list[IssueGroup])


# 0.22.0 (X03): `steward agents list --format json`, the attribution ledger per task.
class AgentScore(TypedDict):
    scorer: str | None
    score: float | None
    rubric: str | None
    override: str | None
    seq: int | None
    recorded: str | None


class AgentAttempt(TypedDict):
    attempt: int | None
    agent: str | None
    provider: str | None
    model: str | None
    suggested: str | None
    started: str | None
    ended: str | None
    reviewer: str | None
    estimate: Object | None
    harness: str | None
    harness_version: str | None
    parent: str | None
    status: str | None
    seq: int | None
    recorded: str | None
    scores: list[AgentScore]


class AgentEvent(TypedDict):
    kind: str | None
    time: str | None
    seq: int | None
    recorded: str | None


class AgentTask(TypedDict):
    task: str
    attempts: list[AgentAttempt]
    events: list[AgentEvent]


class AgentsList(BaseModel):
    """The attribution ledger per task. Order, newest first: tasks by their newest record (ledger seq, then task ID,
    highest first); attempts by attempt number; each attempt's scores by seq; events by their time, then seq. A field
    an attempt did not record is null."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["steward.agents_list/0.1"] = Field(alias="schema")
    ledger: str
    tasks: list[AgentTask]


SCHEMAS[OTHER_SCHEMAS["agents list"].replace("/", "-") + ".schema.json"] = AgentsList


# 0.23.0 (STW-061 D01): `steward agents status --format json`, the delegation and each agent's availability.
class AgentLastRecord(TypedDict):
    kind: Literal["ending", "observed"] | None
    state: str | None
    reset: str | None
    message: str | None
    source: str | None
    time: str | None
    seq: int | None


class AgentAvailability(TypedDict):
    agent: Literal["claude-code", "codex", "antigravity"]
    executable: str
    role: Literal["master", "worker", "unassigned"]
    rank: int | None
    installed: bool
    found: Literal["PATH", "known folder"] | None
    model: str | None
    state: Literal["available", "limited", "signed_out", "missing"]
    until: str | None
    reset_known: bool | None
    version: str | None
    signed_in: bool | None
    last: AgentLastRecord | None


class AgentsStatus(BaseModel):
    """The delegation ([delegation] in steward.toml) and each agent's availability: missing when its CLI is not on
    PATH or in its install folder; limited until `until` when the availability ledger's newest record for it is a
    limit whose reset has not passed (`reset_known` false: no reset time was printed, so it counts for an hour from
    the record); signed out when that record says so; otherwise available. `last` is that newest record; `version`
    and `signed_in` come from the newest record `steward agents setup` made. Order: the master, then the workers in
    their order, then the other agents in a fixed order (claude-code, codex, antigravity). Nothing is run."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["steward.agents_status/0.1"] = Field(alias="schema")
    ledger: str
    now: str
    configured: bool
    master: str | None
    workers: list[str]
    on_limit: Literal["next", "master", "wait"] | None
    agents: list[AgentAvailability]


SCHEMAS[OTHER_SCHEMAS["agents status"].replace("/", "-") + ".schema.json"] = AgentsStatus


# 0.24.0 (P02): `steward timeline --events --format json`, every dated record on one time axis.
class TimelineEvent(TypedDict):
    id: str
    kind: Literal["milestone", "milestone_moved", "milestone_outcome", "decision", "release", "paper", "review",
                  "research", "sprint", "task"]
    project: str | None
    time: str
    day: bool
    end: str | None
    internal: str | None
    moved_from: str | None
    moved_to: str | None
    state: str | None
    title: str
    path: str | None
    line: int | None
    ref: str | None


class TimelineProject(TypedDict):
    code: str | None
    path: str | None
    reachable: bool
    note: str | None


class TimelineEvents(BaseModel):
    """Every dated record on one time axis: milestones (`internal` is due minus the buffer; `moved_from` the first
    committed due date when it differs), their moves (`milestone_moved`, at the commit that moved the date, from
    `moved_from` to `moved_to`) and outcomes, decisions, releases (local `v*` tags; `ref` is the tag), papers (the
    date the venue requirements were retrieved), independent reviews (the time of the reviewed commit), research
    records, sprint windows (`time` to `end`) and their tasks (started to ended). Times are UTC; `day` marks a record
    that dates a day, not a moment. Each event names its source file (`path`, null for a tag) and `line`. `project` is
    null for this project and the exchange code of another project read with --all-projects; `projects` lists this
    project first, then the others by code. A record without a date is left out; `notes` says what was not dated or
    not read. Order: `events` newest first (by time, then ID, highest first)."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["steward.timeline_events/0.1"] = Field(alias="schema")
    now: str
    projects: list[TimelineProject]
    events: list[TimelineEvent]
    notes: list[str]


SCHEMAS[OTHER_SCHEMAS["timeline --events"].replace("/", "-") + ".schema.json"] = TimelineEvents


# X05 (0.22.0): each document says the order of its lists, so a reader can sort. The text views print the newest
# entry first; these documents keep the order they had in 0.21 (a contract).
_TEXT = " The text view prints the newest entry first."
_UNDATED = "Order: its lists are not ordered by date; each keeps the order of its source (a file, a declaration, a name)."
ORDER = {
    "authorize_keys": "Order: keys as the allowed-signers file lists them.",
    "authorize_list": "Order: authorization tags, then anchor tags, each by tag name (A to Z)." + _TEXT,
    "authorize_pending": "Order: this project's queue first, then each peer's (by peer code); within one, by nonce "
                         "(A to Z). `skipped` by peer code." + _TEXT,
    "channel_status": "Order: channels by name (A to Z).",
    "decisions": "Order: `entries` newest first by date (entries of one date in file order); `open_decisions` in "
                 "file order." + _TEXT,
    "diff_runs": "Order: runs as the run ledger records them, oldest first." + _TEXT,
    "exchange_status": "Order: items by folder, then by file name (A to Z); then the items whose file was removed, "
                       "by ID; then the peers' items." + _TEXT,
    "explain": "Order: rules by rule ID.",
    "integrity_status": "Order: frozen sets and datasets by name (A to Z).",
    "issues_inbox": "Order: groups by fingerprint; within a group, versions, projects and items A to Z." + _TEXT,
    "next": "Order: `waiting_on_human` and `waiting_on_agents` grouped by the kind of record, in the order they are "
            "read; each entry's `time` sorts them. `since` newest first (by time, then ID, highest first)." + _TEXT,
    "notifications": "Order: items newest first (by time, then ID, highest first).",
    "plans": "Order: plans by recorded date, newest first, then by natural ID, highest first. Undated plans come last. "
             "Sprint tasks use their latest ledger event, with natural ID as a fallback. Milestone progress retains "
             "the order used by timeline.",
    "research_list": "Order: records newest first (by date).",
    "sprint_status": "Order: tasks in dispatch order (each after the tasks it waits for, else as the sprint file "
                     "lists them)." + _TEXT,
    "study_list": "Order: studies by ID (A to Z); `invalid` by path." + _TEXT,
    "task_board": "Order: tasks by path, as the repository lists its files." + _TEXT,
    "tidy": "Order: items by kind, a worktree before its branch, then by ID.",
    "timeline": "Order: milestones by due date, earliest first." + _TEXT,
    "tokens_report": "Order: tasks by task label (A to Z); per task, models by agent then model, agents by name, "
                     "files most read first, tool outputs largest first, windows oldest first, attempts newest "
                     "first; `issues` A to Z."
                     + _TEXT,
}


def _describe_order() -> None:
    for name, model in SCHEMAS.items():
        stem = name.removesuffix(".schema.json").rsplit("-", 1)[0].removeprefix("steward.")
        if stem in ("agents_list", "agents_status", "timeline_events"):  # its docstring already says its order
            continue
        own = (model.__doc__ or "").strip() if model in (ProgressAudit, LastError) else ""
        text = ORDER.get(stem, _UNDATED)
        model.model_config["json_schema_extra"] = {"description": f"{own} {text}" if own else text}
        model.model_rebuild(force=True)


_describe_order()
