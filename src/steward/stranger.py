"""The stranger test (0.20.2, STW-041): an agent that has never seen a project tries to get value from it using only
what a newcomer sees, and the result is kept.

Any project can declare `[stranger_test]` in steward.toml: who the stranger is (`audience`), what they try to do
(`missions`), what they may read and must not, and how a stranger installs the release under test. `steward
stranger-test brief` turns that into a self-contained prompt for Codex, Gemini, Claude or any agent; `steward
stranger-test record` files the report; R-87 (advisory) reports when no stranger test of a recent release is on
record. Nothing here is specific to a field: the project's own declaration says what a newcomer should achieve.
"""

from __future__ import annotations

import re
import shlex
from datetime import date
from pathlib import Path
from typing import Any

GENERIC_MISSIONS = (
    "First contact: from the README alone, install the project and reach its first useful result. Is it clear what "
    "happened and what to do next?",
)
CLOSING_MISSIONS = (
    "Follow one guide or quick start end to end, exactly as written. Where does it stop working, or stop being clear?",
    "Break something on purpose (a wrong input, a missing file, a bad setting) and fix it using only the project's own "
    "messages, help and documentation.",
)
DEFAULT_MISSION = ("Do the main thing the README says this project is for, on a small example of your own, and judge "
                   "whether the result is right.")

RECORD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-stranger-test-(.+)-([a-z0-9_.]+)\.md$")  # AQ2: agent has no hyphen


def _install(sec: Any, repo: str, tag: str) -> str:
    """The install lines, with {repo} and {tag} filled in (both are checked plain values: AQ4)."""
    if sec.install:
        return sec.install.replace("{repo}", repo).replace("{tag}", tag)
    return (f"git clone -q {shlex.quote(repo)} project && git -C project checkout -q {shlex.quote(tag)}   "
            "# then install it the way its README says")


SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+/-]{0,127}$")


def brief(root: Path, cfg: Any, tag: str, agent: str, brief_file: str = "BRIEF.md") -> str:
    """The stranger-test prompt for `agent`, from the project's `[stranger_test]` (or the generic defaults). The tag and
    the repository path must be plain values (AQ4): they are written into shell lines."""
    from .briefs import AGENTS

    if not SAFE_TAG.match(tag) or ".." in tag:
        raise ValueError(f"{tag!r} is not a plain tag or commit name")
    if re.search(r"[\"$`\\\n]", str(root.resolve())):
        raise ValueError("the repository path holds a quote, $, ` or a line break; move it to a plain path first")

    sec = cfg.stranger_test
    name = cfg.steward.project
    audience = sec.audience or "someone in this project's intended audience who has just found it"
    missions = list(GENERIC_MISSIONS) + (list(sec.missions) or [DEFAULT_MISSION]) + list(CLOSING_MISSIONS)
    repo = str(root.resolve())
    brief_abs = shlex.quote(str((root / brief_file).resolve()) if not Path(brief_file).is_absolute() else brief_file)
    run = {  # AQ4: from the repository, into a folder beside it, reading the brief by its full path
        "codex": f'mkdir -p ../stranger && cd ../stranger && codex exec -s workspace-write --skip-git-repo-check '
                 f'-C "$PWD" "$(cat {brief_abs})" < /dev/null',
        "gemini": "open Gemini (CLI or Antigravity) in an empty folder outside the repository and paste the brief",
        "claude": f'mkdir -p ../stranger && cd ../stranger && claude -p "$(cat {brief_abs})"',
        "generic": "start the agent in an empty folder outside the repository and give it the brief",
    }[agent]
    lines = [
        f"# Brief for {AGENTS[agent]['name']}: stranger test of {name} ({tag})", "",
        "You are given one task. Everything you need is below; ask nothing, and say plainly what you could not check.",
        "", "## Who you are",
        f"You are {audience}. You have never seen {name} before. You are testing whether a newcomer can get real value "
        "from it in about an hour, not reviewing its code.", "",
        "## Setup (do exactly this; never install over a shared tool)",
        "You are started in an empty folder. Everything you create stays in it.",
        "```bash",
        f'REPO="{repo}"   # the project (read only)',
        f'TAG="{tag}"',
        'WORK="$PWD"',
        _install(sec, repo, tag),
        "```",
        "If the install needs the network and you have none, say so, and recover with what is available locally.", "",
        "## What you may read",
        "Only what a newcomer sees: " + ", ".join(f"`{p}`" for p in sec.may_read) + ", the tool's own `--help` and "
        "messages, and what the install produces. Do not open " + ", ".join(f"`{p}`" for p in sec.must_not_read)
        + ": a stranger cannot see them.", "",
        "## The missions (time each; stop a mission after 15 minutes and record why)",
    ]
    lines += [f"{i}. {m}" for i, m in enumerate(missions, start=1)]
    lines += [
        "", "## What to record",
        "- A **friction log** per mission: every place you were unsure, what you tried (command or page), what happened, "
        "what you expected; mark each **blocking**, **slowing** or **cosmetic**, with the time the mission took.",
        "- **Words you did not understand** in the output or the documentation.",
        "- **Output an agent had to read**: roughly how much each command printed (words), when the tool is meant to be "
        "used by agents too.",
        "- **Suggestions**: five to ten capabilities that would make it more useful to its audience, each with the "
        "problem it would prevent and a public example if you know one, ranked; say which you would use first.",
        "", "## Rules",
        f"- Act only inside the empty folder; change no file in `{repo}`.",
        "- Never install anything globally or over an existing installation.",
        "- Cite only what you opened; say what you could not try.",
        "", "## The report",
        f'Title it "# Stranger test of {name} ({tag}, {agent if agent != "generic" else "AGENT NAME"})", open with a one-paragraph **verdict** (would {audience} '
        "keep using it after an hour, and why), then the friction log, the unclear words, the output measures and the "
        "ranked suggestions. Save it as `report.md` in the folder and print it as your final answer.",
        "Sign it: date, harness and version, provider, exact model ID (or unknown), and limitations.", "",
        "---",
        f"How to run: {run}",
        f"Then: steward stranger-test record ../stranger/report.md --tag {shlex.quote(tag)} --agent {agent}",
    ]
    return "\n".join(lines) + "\n"


def record_path(tag: str, agent: str, today: date | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", tag).strip("-") or "untagged"
    who = re.sub(r"[^a-z0-9_.]+", "", agent.lower()) or "agent"  # AQ2: the last part is always the agent
    return f"{DIR}/{(today or date.today()).isoformat()}-stranger-test-{safe}-{who}.md"


DIR = "development/assessment"
TITLE = re.compile(rb"^# Stranger test of ", re.M)


def records(root: Path, read=None) -> tuple[list[tuple[str, date, str, str]], list[str]]:
    """([(rel, date, tag, agent)] of the stranger-test records, oldest first; [names ignored, with why]). The folder is
    reached without links and each record is read the same way, and must hold a report's title (AQ2)."""
    import os

    from .fsutil import LinkRefused, open_dir_beneath
    from .records import RecordRefused, read_rel

    read = read or (lambda rel: read_rel(root, rel))
    try:
        dfd = open_dir_beneath(root, DIR.split("/"))
    except LinkRefused:
        return [], []
    try:
        names = sorted(os.listdir(dfd))
    finally:
        os.close(dfd)
    out, ignored = [], []
    for name in names:
        m = RECORD_RE.match(name)
        if not m:
            continue
        rel = f"{DIR}/{name}"
        try:
            when = date.fromisoformat(m.group(1))
            data = read(rel)
        except (ValueError, RecordRefused):
            ignored.append(f"{name}: not a readable record")
            continue
        if when > date.today():
            ignored.append(f"{name}: dated in the future")
            continue
        if not TITLE.search(data):
            ignored.append(f"{name}: not a stranger-test report (no '# Stranger test of …' title)")
            continue
        out.append((rel, when, m.group(2), m.group(3)))
    return sorted(out, key=lambda r: (r[1], r[0])), ignored


def r87(ctx: Any) -> list:
    """Advisory: with `[stranger_test]`, a stranger test of a recent release is on record (AQ2: read, not named)."""
    import hashlib

    from .records import read_rel
    from .rules import result
    from .status import Status

    cfg = ctx.config
    if cfg is None or cfg.stranger_test is None:
        return [result("R-87", ".", Status.NOT_APPLICABLE, "[stranger_test] is not configured")]

    def safe(rel: str) -> bytes:
        if rel not in ctx.snapshot:
            ctx.snapshot[rel] = read_rel(ctx.root, rel)
        ctx.inputs[rel] = hashlib.sha256(ctx.snapshot[rel]).hexdigest()
        return ctx.snapshot[rel]
    recs, ignored = records(ctx.root, safe)
    notes = [{"code": "R-87.ignored", "message": n} for n in ignored]
    if not recs:
        return [result("R-87", DIR, Status.INCOMPLETE,
                       "no stranger test on record (steward stranger-test brief --tag TAG --for AGENT)",
                       [{"code": "R-87.none"}] + notes)]
    rel, when, tag, agent = recs[-1]
    age = (date.today() - when).days
    ev = ctx.evidence(rel)
    if age > cfg.stranger_test.max_age_days:
        return [result("R-87", rel, Status.INCOMPLETE,
                       f"the last stranger test ({tag}, {agent}) is {age} days old; run one on the coming release",
                       [{"code": "R-87.stale", "value": str(age), "path": rel}] + notes, ev)]
    return [result("R-87", rel, Status.PASS, f"a stranger test of {tag} by {agent}, {age} day(s) ago", notes, ev)]
