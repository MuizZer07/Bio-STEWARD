"""Dispatch briefs (0.18.0): a task file turned into a self-contained prompt for another agent.

A task (the task template's Markdown) already names its goal, scope, rules and acceptance criteria. `steward task
brief TASK --for AGENT` assembles them, with the repository state and the agent's own conventions, into one prompt
that can be pasted or piped to Codex, Gemini, Claude or any agent. The brief is generated from the record, so the
record stays the source of truth and the brief can be regenerated at any time."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

AGENTS: dict[str, dict[str, str]] = {
    "codex": {"name": "Codex", "run": 'codex exec -s read-only -C "$REPO" "$(cat BRIEF.md)" < /dev/null',
              "note": "You run in a read-only sandbox: print your result as your answer; the human saves it to the path the "
                      "acceptance criteria name."},
    "gemini": {"name": "Gemini", "run": "paste the brief into Gemini (CLI or IDE agent) opened at the repository",
               "note": "Read files from the repository; do not change any file unless the brief asks for it."},
    "claude": {"name": "Claude", "run": "claude -p \"$(cat BRIEF.md)\" (or paste it into a session at the repository)",
               "note": "Follow the repository's AGENTS.md and CLAUDE.md; do not change files outside the brief's scope."},
    "generic": {"name": "the agent", "run": "give the brief to the agent at the repository",
                "note": "Work only within the scope below and say plainly what you could not check."},
}

SECTION = re.compile(r"^## (.+?)\s*$", re.M)


def parse_task(text: str) -> dict[str, Any]:
    """{title, fields: {ID, Status, …}, sections: {Goal: text, …}} from the task template's Markdown."""
    m = re.search(r"^# Task:\s*(.+)$", text, re.M) or re.search(r"^# (.+)$", text, re.M)
    title = m.group(1).strip() if m else "Task"
    fields: dict[str, str] = {}
    head = SECTION.split(text, maxsplit=1)[0]
    for fm in re.finditer(r"^- \*\*(.+?):\*\*\s*(.*(?:\n  .*)*)", head, re.M):
        fields[fm.group(1).strip()] = " ".join(x.strip() for x in fm.group(2).splitlines())
    parts = SECTION.split(text)
    sections = {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return {"title": title, "fields": fields, "sections": sections}


SKIP = {"Work log", "Outcome", "Follow-ups", "Signature"}


def brief(text: str, agent: str, repo: Path, git: dict[str, str]) -> str:
    t = parse_task(text)
    a = AGENTS[agent]
    f = t["fields"]
    out = [f"# Brief for {a['name']}: {t['title']}" + (f" ({f['ID']})" if f.get("ID") else ""), "",
           "You are given one task in this repository. Everything you need is below; ask nothing, and say plainly what you "
           "could not check.", "", "## Context",
           f"- **Repository:** the current checkout (`{repo.name}`), branch `{git.get('branch', 'unknown')}`, commit "
           f"`{git.get('commit', 'none yet')}`."]
    for k in ("Branch", "Dependencies", "Owner", "Reviewer", "GO reference"):
        if f.get(k):
            out.append(f"- **{k}:** {f[k]}")
    out += ["", f"_{a['note']}_", ""]
    for name, body in t["sections"].items():
        if name in SKIP or not body:
            continue
        out += [f"## {name}", body, ""]
    out += ["## When you finish",
            "End with a short verdict, then the details. Sign your result: date, task, mode, harness and version, provider, "
            "exact model ID (or unknown), and limitations.", "",
            "---", f"How to run: {f['Run']}" if f.get("Run") else f"How to run: `{a['run']}`"]  # a task's own (0.19.0)
    return "\n".join(out).rstrip() + "\n"


TEMPLATES = ("review", "reverification", "literature-review", "novelty-check", "figure-check")


# a template's own placeholders: a value that is (or starts with) "…", "… (e.g. …)", and its capitalised slots; an
# ellipsis inside a quotation is not one
PLACEHOLDER = re.compile(r"^\s*…|…\s*\(|\bVERSION\b|\bBASE\.\.BRANCH\b|\bDATE\b|\bSHA\b")


def unfilled(text: str) -> list[str]:
    """0.20.2 (STW-040): the template words a task still holds (its header and its Scope), so a brief is not sent with
    them."""
    t = parse_task(text)
    out = [k for k, v in t["fields"].items() if PLACEHOLDER.search(v)]
    if PLACEHOLDER.search(t["title"]):
        out.insert(0, "title")
    if PLACEHOLDER.search(t["sections"].get("Scope", "")):
        out.append("Scope")
    return out


def template(name: str) -> str:
    from .resources import template as _t

    return _t(f"briefs/{name}.md")
