"""Read dated decisions and open questions from project Markdown records."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .fsutil import escapes_root

HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s*[:—–]\s*|\s+-\s+)(\S.*)$")
FIELD = re.compile(r"^[-*+]\s+\*\*([^*]+?)(?::\*\*|\*\*:)\s*(.*)$")
DATED_SPEAKER = re.compile(r"^(.+?)\s+\((\d{4}-\d{2}-\d{2})\)$")
INLINE_EFFECT = re.compile(r'(?<=["”])[.;]?\s+(?:→|->)\s+')
BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
OPEN = re.compile(r"\b(?:open|remaining|unresolved)\s+(?:(?:design|owner)\s+)?(?:decisions|questions)\b", re.I)
CLOSED = re.compile(r"^\W*(?:decided|resolved|closed|accepted|approved)\b", re.I)
EMPTY = {"", "none", "none.", "(none)", "—", "n/a"}


def index_path(cfg) -> str:
    return cfg.tidy.index if cfg.tidy else f"{cfg.paths.records.rstrip('/')}/INDEX.md"


def read_record(root: Path, rel: str) -> str | None:
    """Read only regular project records, without traversing symlinked paths."""
    if escapes_root(rel) or ".git" in Path(rel).parts:
        return None
    path = root / rel
    if not path.is_file() or path.resolve() != root.resolve() / Path(rel):
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def markdown_lines(text: str):
    """Line numbers outside fenced examples."""
    fence = ""
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, trailing = marker.groups()
            if not fence:
                fence = run
                continue
            if run.startswith(fence) and not trailing.strip():
                fence = ""
                continue
        if not fence:
            yield number, line


def entries(text: str, path: str) -> list[dict]:
    result = []
    lines = text.splitlines()
    headings = [(n, m[2]) for n, line in markdown_lines(text) if (m := HEADING.match(line)) and len(m[1]) <= 2]
    for number, line in markdown_lines(text):
        field = FIELD.match(line)
        if not field or not (speaker := DATED_SPEAKER.fullmatch(field[1])):
            continue
        who, date = speaker.groups()
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            continue
        # An explicitly dated speaker bullet is its own record, even under an older dated heading.
        headings.append((number, ""))
        end = number
        while end < len(lines) and lines[end].startswith((" ", "\t")):
            end += 1
        body = lines[number - 1:end]
        words, effect = _speaker_words([field[2], *(line.strip() for line in body[1:])])
        result.append({"date": date, "heading": field[1], "title": who, "path": path, "line": number,
                       "quotes": [{"who": who, "text": words}] if '"' in words or '“' in words else [],
                       "decision": None, "consequences": effect, "body": "\n".join(body)})
    headings.sort()
    for (number, heading), (end, _) in zip(headings, [*headings[1:], (len(lines) + 1, "")]):
        match = DATED.fullmatch(heading)
        if not match:
            continue
        date, title = match.groups()
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            continue
        body = lines[number:end - 1]
        record = {"date": date, "heading": heading, "title": title, "path": path, "line": number,
                  "quotes": [], "decision": None, "consequences": None, "body": "\n".join(body).strip("\n")}
        fields = []
        active = None
        for _, line in markdown_lines("\n".join(body)):
            field = FIELD.match(line)
            if field:
                active = [field[2]]
                fields.append((field[1], active))
            elif active is not None and line.startswith((" ", "\t")):
                active.append(line.strip())
            elif line.strip():
                active = None
        speaker_keys = ("who", "owner", "speaker", "by")
        speaker = next(("\n".join(parts).strip() for label, parts in fields
                        if label.lower() in speaker_keys), None)
        for label, parts in fields:
            key = label.lower()
            value = "\n".join(parts).strip()
            if key in speaker_keys:
                continue
            if key in ("decision", "consequences"):
                record[key] = record[key] or value
            elif key in ("quote", "verbatim"):
                record["quotes"].append({"who": speaker, "text": value})
            elif value.startswith(('"', '“', '- "', '- “')) or any(p.startswith(("→", "->")) for p in parts):
                who = label.split(",", 1)[0]
                words, effect = _speaker_words(parts)
                if words:
                    record["quotes"].append({"who": who, "text": words})
                if effect:
                    record["consequences"] = "\n".join(filter(None, [record["consequences"], effect]))
        result.append(record)
    return sorted(result, key=lambda record: record["line"])


def _speaker_words(parts: list[str]) -> tuple[str, str | None]:
    """Separate a speaker's words from a recorded effect without rewriting their wording."""
    words = []
    effects = []
    for part in parts:
        note = re.match(r"^(?:[-*+]\s+)?(?:→|->)\s*(.*)$", part)
        if note:
            effects.append(note[1])
        elif effects:
            effects.append(part)
        else:
            split = INLINE_EFFECT.split(part, maxsplit=1)
            words.append(split[0])
            effects.extend(split[1:])
    value = "\n".join(words).strip()
    return value, "\n".join(effects).strip() or None


def cells(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def table_separator(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)


def questions(text: str, path: str) -> list[dict]:
    result = []
    section = 0
    current = None
    indent = 0
    header = []
    for number, line in markdown_lines(text):
        heading = HEADING.match(line)
        if heading:
            depth = len(heading[1])
            if OPEN.search(heading[2]):
                section = depth
            elif section and depth <= section:
                section = 0
            current, header = None, []
            continue
        if not section:
            continue
        bullet = BULLET.match(line)
        if bullet:
            level, value = len(bullet[1].expandtabs()), bullet[2].strip()
            if current is not None and level > indent:
                current["options"].append(value)
            else:
                current, indent = None, level
                if value.casefold() not in EMPTY and not CLOSED.match(value):
                    current = {"question": value, "options": [], "path": path, "line": number}
                    result.append(current)
        elif line.lstrip().startswith("|"):
            current = None
            row = cells(line)
            if not header:
                header = [cell.casefold() for cell in row]
            elif len(row) == len(header) and not table_separator(row):
                question = next((v for k, v in zip(header, row) if k in ("decision", "question")), "")
                status = next((v for k, v in zip(header, row) if "status" in k), "")
                if question.casefold() not in EMPTY and not CLOSED.match(status):
                    options = [v for k, v in zip(header, row)
                               if ("option" in k or "recommendation" in k) and v.casefold() not in EMPTY]
                    result.append({"question": question, "options": options, "path": path, "line": number})
        elif line.strip():
            header = []
            if current is not None and line.startswith((" ", "\t")):
                current["question"] += " " + line.strip()
            else:
                current = None
        else:
            header = []
    return result


def recorded(root: Path, cfg) -> list[dict]:
    from .integrity import decision_logs

    found = [entry for rel in decision_logs(root, cfg) for entry in entries(read_record(root, rel) or "", rel)]
    return sorted(found, key=lambda entry: entry["date"], reverse=True)


def document(root: Path, cfg) -> dict:
    from .models import SessionSection

    # Open decisions come from the living records only: the index and the session handoff. Design documents are
    # kept unchanged as history (AGENTS.md: new versions are new files), so their "Open decisions" lists go stale
    # once a later record settles them; reading them gave 41 settled questions as open on this repository (W04).
    paths = [index_path(cfg), (cfg.session or SessionSection()).handoff]
    return {"entries": recorded(root, cfg),
            "open_decisions": [item for path in dict.fromkeys(paths) for item in
                               questions(read_record(root, path) or "", path)]}


def render(doc: dict) -> str:
    lines = ["Open decisions"]
    lines.extend(f"- {item['question']} ({item['path']}:{item['line']})"
                 + "".join(f"\n  - {option}" for option in item["options"]) for item in doc["open_decisions"])
    if not doc["open_decisions"]:
        lines.append("- None recorded")
    lines += ["", "Recorded decisions"]
    lines.extend(f"- {entry['heading']} ({entry['path']}:{entry['line']})" for entry in doc["entries"])
    if not doc["entries"]:
        lines.append("- None recorded")
    return "\n".join(lines)
