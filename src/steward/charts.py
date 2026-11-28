"""Small, dependency-free SVG charts for the records (0.18.0): runs compared side by side and the docs site's pages.

The charts carry their own light and dark colours (`prefers-color-scheme`), a title and a text alternative, and every
value is drawn from a record: nothing is estimated."""

from __future__ import annotations

from html import escape
from typing import Any

PALETTE = {"finished": "#2f9e66", "failed": "#d64545", "killed": "#e08a1e", "interrupted": "#8a8f98", "other": "#4c7bd9"}

STYLE = """<style>
  .bg { fill: #ffffff; } .ink { fill: #1d2330; } .muted { fill: #5b6475; } .grid { stroke: #e3e6ec; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #14171f; } .ink { fill: #e8ebf2; } .muted { fill: #a3abba; } .grid { stroke: #2a2f3b; }
  }
  text { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; font-size: 12px; }
</style>"""


def bars(rows: list[dict[str, Any]], value: str, title: str, unit: str, width: int = 720,
         *, maximum: float | None = None) -> str:
    """A horizontal bar chart: one bar per row (`label`, `status`, value), coloured by status."""
    rows = [r for r in rows if isinstance(r.get(value), (int, float))]
    bar_h, gap, left, top = 18, 8, 180, 44
    height = top + len(rows) * (bar_h + gap) + 36
    vmax = maximum if maximum is not None else max([r[value] for r in rows] + [1e-9])
    plot = width - left - 70
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="{escape(title)}">', STYLE, f'<rect class="bg" width="{width}" height="{height}" rx="10"/>',
           f'<text class="ink" x="16" y="26" font-weight="600" font-size="15">{escape(title)}</text>']
    for k in range(5):
        x = left + plot * k / 4
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{height - 28}"/>')
        out.append(f'<text class="muted" x="{x:.1f}" y="{height - 12}" text-anchor="middle">{vmax * k / 4:.3g} {escape(unit)}</text>')
    for i, r in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = (plot * r[value] / vmax) if maximum is not None else max(2.0, plot * r[value] / vmax)
        colour = PALETTE.get(str(r.get("status")), PALETTE["other"])
        label = escape(str(r.get("label") or r.get("run") or "")[:26])
        out.append(f'<text class="ink" x="{left - 10}" y="{y + 13}" text-anchor="end">{label}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="4" fill="{colour}">'
                   f'<title>{label}: {r[value]:.4g} {escape(unit)} ({escape(str(r.get("status")))})</title></rect>')
        out.append(f'<text class="muted" x="{left + w + 6:.1f}" y="{y + 13}">{r[value]:.3g}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def legend_md() -> str:
    return " · ".join(f'<span style="color:{c}">■</span> {k}' for k, c in PALETTE.items() if k != "other")


def text_bars(rows: list[tuple[str, int]], unit: str, width: int = 28) -> str:
    """Print a compact horizontal chart with exact values alongside the bars."""
    maximum = max((value for _, value in rows), default=0)
    return "\n".join(f"{label}  {'#' * (max(1, value * width // maximum) if value else 0)} {value:,} {unit}"
                     for label, value in rows)


# ---------------------------------------------------------------- the schedule (0.24.0, P02)
SCHEDULE_STYLE = """<style>
  .lane { fill: #f4f6f9; } .today { stroke: #d64545; } .today-ink { fill: #d64545; } .link { stroke: #8a8f98; }
  @media (prefers-color-scheme: dark) {
    .lane { fill: #1b1f29; } .today { stroke: #ff7b7b; } .today-ink { fill: #ff7b7b; } .link { stroke: #a3abba; }
  }
</style>"""
SCHEDULE_LANES = (
    ("Milestones", ("milestone", "milestone_moved", "milestone_outcome")),
    ("Sprints", ("sprint",)),
    ("Sprint tasks", ("task",)),
    ("Releases", ("release",)),
    ("Decisions", ("decision",)),
    ("Research", ("research",)),
    ("Papers and reviews", ("paper", "review")),
)
STATE_COLOUR = {"late": "#d64545", "at risk": "#e08a1e", "met": "#2f9e66", "ready": "#2f9e66", "done": "#2f9e66",
                "dropped": "#8a8f98", "failed": "#d64545", "moved": "#e08a1e", "review": "#e08a1e",
                "running": "#4c7bd9", "skipped": "#8a8f98", "draft": "#8a8f98"}
KIND_COLOUR = {"decision": "#7a5af5", "release": "#2f9e66", "research": "#0f9bb5", "paper": "#c2559b",
               "review": "#e08a1e", "sprint": "#4c7bd9", "task": "#4c7bd9", "milestone": "#4c7bd9"}


def _moment(text: str | None) -> Any:
    from datetime import datetime

    return None if not text else datetime.fromisoformat(text.replace("Z", "+00:00"))


def _ticks(t0: Any, t1: Any) -> list[tuple[Any, str]]:
    """Grid lines: days or weeks for a short span, months (at most about twelve labels) up to four years, else years."""
    from datetime import datetime, timedelta

    days = (t1 - t0).total_seconds() / 86400
    out: list[tuple[Any, str]] = []
    if days <= 62:
        t = datetime(t0.year, t0.month, t0.day, tzinfo=t0.tzinfo) + timedelta(days=1)
        step = 1 if days <= 7 else 2 if days <= 14 else 7
        while t <= t1:
            out.append((t, t.strftime("%m-%d")))
            t += timedelta(days=step)
        return out
    if days <= 365 * 4:
        every = max(1, -(-(int(days // 30) + 1) // 12))
        y, m = t0.year, t0.month
        while True:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            t = datetime(y, m, 1, tzinfo=t0.tzinfo)
            if t > t1:
                return out
            if (m - 1) % every == 0:
                out.append((t, t.strftime("%Y-%m")))
    return [(datetime(y, 1, 1, tzinfo=t0.tzinfo), str(y)) for y in range(t0.year + 1, t1.year + 1)]


def _when(e: dict[str, Any]) -> str:
    return e["time"][:10] if e["day"] else e["time"][:16].replace("T", " ")


def _schedule_desc(events: list[dict[str, Any]], lanes: list, now: Any, first: Any, last: Any) -> list[str]:
    desc = [f"{len(events)} dated events from {first:%Y-%m-%d} to {last:%Y-%m-%d}; today is {now:%Y-%m-%d}."]
    if lanes:
        desc.append("Lanes: " + ", ".join(f"{name} {len(rows)}" for name, rows in lanes) + ".")
    coming = [e for e in events if e["kind"] == "milestone" and _moment(e["time"]) >= now
              and e["state"] not in ("met", "moved", "dropped")]  # a recorded outcome is no longer coming
    if coming:
        desc.append("Coming deadlines: " + "; ".join(
            f"{e['title']} due {e['time'][:10]}" + (f", internal deadline {e['internal'][:10]}" if e["internal"] else "")
            + (f", first due {e['moved_from'][:10]}" if e["moved_from"] else "")
            + (f", {e['state']}" if e["state"] else "") for e in reversed(coming)) + ".")
    shown = events[:30]
    if shown:
        desc.append("Newest first: " + "; ".join(f"{_when(e)} {e['kind']} {e['title']}" for e in shown)
                    + (f"; and {len(events) - len(shown)} more" if len(events) > len(shown) else "") + ".")
    return desc


LABEL_CHAR = 6.2  # the width of one character of an 11-pixel label, estimated
LABEL_GAP = 4.0  # the space kept between two labels of one text row


def _schedule_label(name: str, at: float, marks: list[float], i: int, left: float, plot: float,
                    placed: dict[int, list[tuple[float, float]]], rows: tuple[int, int],
                    may_go_left: bool) -> tuple[float, int, str, str] | None:
    """Where the label of mark `i` (at `at`) goes: `(x, dy, anchor, text)`, or None when no label fits. It stays
    inside the lane and clear of the labels already `placed` in its text row; on the lane's own row (`rows[0]`, level
    with the marks) it also stays between its neighbouring marks. The second row (`rows[1]`) is above the marks. It
    tries the full name on the lane's own row (right of the mark, then left), then on the second row, then the same
    places with a shorter name that keeps its end from a `-`, `_` or `.` on (`…0.1.0-rc`, `…rc`), whose full name is
    then in the label's `<title>`."""
    after = min([m for m in marks[i + 1:] if m > at + 1] + [left + plot]) - at - 14
    before = at - max([m for m in marks[:i] if m < at - 1] + [left]) - 14
    room = {rows[0]: (after, before), rows[1]: (left + plot - at - 14, at - left - 14)}
    shorter = ["…" + name[n + 1:] for n in range(len(name) - 1) if name[n] in "-_." and len(name) - n > 3]
    for shown in [name] + shorter:
        w = len(shown) * LABEL_CHAR
        for dy in rows:
            spans = placed.setdefault(dy, [])
            right, left_room = room[dy]
            sides = [("start", at + 11, w <= right)] + ([("end", at - 11 - w, w <= left_room)] if may_go_left else [])
            for anchor, a, fits in sides:
                if fits and all(a + w + LABEL_GAP <= p or a >= q + LABEL_GAP for p, q in spans):
                    spans.append((a, a + w))
                    return (at + 11 if anchor == "start" else at - 11), dy, anchor, shown
    return None


def schedule(doc: dict[str, Any], title: str = "Research schedule", width: int = 960) -> str:
    """The research timeline as a schedule (`steward timeline --events --format svg`): one lane per kind of record
    (per project with `--all-projects`), milestones with their buffers and moved dates (the old date faint), sprint
    windows with their tasks, and today. It has a title and a text alternative (`<desc>`), and no script."""
    from datetime import timedelta

    events = doc["events"]
    now = _moment(doc["now"])
    codes = [p["code"] for p in doc["projects"]]
    lanes = []
    for n, code in enumerate(codes):
        for label, kinds in SCHEDULE_LANES:
            rows = [e for e in events if e["kind"] in kinds and e["project"] == (None if n == 0 else code)]
            if rows:
                lanes.append((f"{code or 'this project'} · {label}" if len(codes) > 1 else label, rows))
    moments = [now] + [_moment(e[k]) for e in events for k in ("time", "end", "internal", "moved_from", "moved_to")
                       if e[k]]
    first, last = min(moments), max(moments)
    pad = max((last - first) * 0.03, timedelta(days=1))
    t0, t1 = first - pad, last + pad
    left, right, top, lane_h = 190, 24, 70, 34
    plot = width - left - right
    bottom = top + max(1, len(lanes)) * lane_h
    height = bottom + 34

    def x(t: Any) -> float:
        return left + plot * (t - t0).total_seconds() / (t1 - t0).total_seconds()

    desc = _schedule_desc(events, lanes, now, first, last)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" '
           'aria-labelledby="schedule-title schedule-desc">',
           f'<title id="schedule-title">{escape(title)}</title>',
           f'<desc id="schedule-desc">{escape(" ".join(desc))}</desc>', STYLE, SCHEDULE_STYLE,
           f'<rect class="bg" width="{width}" height="{height}" rx="10"/>',
           f'<text class="ink" x="16" y="26" font-weight="600" font-size="15">{escape(title)}</text>',
           f'<text class="muted" x="16" y="44">{escape(desc[0])}</text>']
    if not lanes:
        out.append(f'<text class="muted" x="{left}" y="{top + 20}">No dated records.</text>')
    for k, (name, _) in enumerate(lanes):
        y = top + k * lane_h
        out.append(f'<rect class="lane" x="{left}" y="{y + 3}" width="{plot}" height="{lane_h - 6}" rx="4"/>')
        out.append(f'<text class="ink" x="{left - 10}" y="{y + lane_h / 2 + 4:.1f}" text-anchor="end">'
                   f'{escape(name[:30])}</text>')
    for t, label in _ticks(t0, t1):
        out.append(f'<line class="grid" x1="{x(t):.1f}" y1="{top}" x2="{x(t):.1f}" y2="{bottom}"/>')
        out.append(f'<text class="muted" x="{x(t):.1f}" y="{bottom + 16}" text-anchor="middle">{label}</text>')
    for k, (_, rows) in enumerate(lanes):
        mid = top + k * lane_h + lane_h / 2
        ordered = sorted(rows, key=lambda e: (e["time"], e["id"]))  # drawn oldest first
        marks = [x(_moment(e["moved_from"] if e["kind"] == "milestone_moved" else e["time"])) for e in ordered]
        placed: dict[int, list[tuple[float, float]]] = {}  # the labels drawn so far in this lane, per text row
        for i, e in enumerate(ordered):
            label = _when(e) + " " + e["title"] + (f" until {_when({**e, 'time': e['end']})}" if e["end"] else "") \
                + (f" ({e['state']})" if e["state"] else "")
            tip = f"<title>{escape(label)}</title>"
            colour = STATE_COLOUR.get(e["state"] or "", KIND_COLOUR.get(e["kind"], PALETTE["other"]))
            at = x(_moment(e["time"]))
            # a short name beside a milestone, a release or a sprint, where it fits before the next mark of its lane
            # (or, at the end of the lane, after the previous one) and clear of the labels already drawn
            name = e["id"].split(":", 1)[1].split("/")[-1] if e["kind"] in ("milestone", "release", "sprint") else ""
            if name:
                text = _schedule_label(name, at, marks, i, left, plot, placed,
                                       (4, -11) if e["kind"] != "release" else (-2, -14), e["kind"] != "sprint")
                if text is not None:
                    tx, dy, anchor, shown = text
                    full = f"<title>{escape(name)}</title>" if shown != name else ""
                    out.append(f'<text class="muted" x="{tx:.1f}" y="{mid + dy:.1f}" font-size="11"'
                               + (' text-anchor="end"' if anchor == "end" else "") + f'>{escape(shown)}{full}</text>')
            if e["kind"] == "milestone":
                if e["internal"]:
                    xi = x(_moment(e["internal"]))
                    out.append(f'<rect x="{xi:.1f}" y="{mid - 9:.1f}" width="{max(1.0, at - xi):.1f}" height="18" '
                               f'fill="#e08a1e" fill-opacity="0.22"><title>buffer: internal deadline '
                               f'{e["internal"][:10]}</title></rect>')
                if e["moved_from"]:
                    xo = x(_moment(e["moved_from"]))
                    out.append(f'<line class="link" x1="{xo:.1f}" y1="{mid:.1f}" x2="{at:.1f}" y2="{mid:.1f}" '
                               'stroke-dasharray="3 3" stroke-opacity="0.6"/>')
                    out.append(f'<path d="M{xo:.1f} {mid - 6:.1f} l6 6 l-6 6 l-6 -6 z" fill="{colour}" '
                               f'fill-opacity="0.3"><title>first due {e["moved_from"][:10]}</title></path>')
                out.append(f'<path d="M{at:.1f} {mid - 8:.1f} l8 8 l-8 8 l-8 -8 z" fill="{colour}">{tip}</path>')
            elif e["kind"] == "milestone_moved":
                xo, xn = x(_moment(e["moved_from"])), x(_moment(e["moved_to"]))
                out.append(f'<line class="link" x1="{xo:.1f}" y1="{mid + 11:.1f}" x2="{xn:.1f}" y2="{mid + 11:.1f}" '
                           f'stroke-dasharray="2 3" stroke-opacity="0.5">{tip}</line>')
                out.append(f'<circle cx="{xo:.1f}" cy="{mid + 11:.1f}" r="2.5" fill="{colour}" fill-opacity="0.4">'
                           f'{tip}</circle>')
            elif e["kind"] in ("sprint", "task"):
                start = _moment(e["time"])
                end = _moment(e["end"]) if e["end"] else (now if e["kind"] == "task" and now > start else None)
                xe = x(end) if end is not None else at + 3
                h, y = (18, mid - 9) if e["kind"] == "sprint" else (6, mid - 11 + (i % 3) * 8)
                out.append(f'<rect x="{at:.1f}" y="{y:.1f}" width="{max(3.0, xe - at):.1f}" height="{h}" rx="3" '
                           f'fill="{colour}" fill-opacity="{0.25 if e["kind"] == "sprint" else 0.85}" '
                           f'stroke="{colour}">{tip}</rect>')
            elif e["kind"] == "release":
                out.append(f'<path d="M{at:.1f} {mid - 8:.1f} l7 14 l-14 0 z" fill="{colour}">{tip}</path>')
            else:
                r = 5 if e["kind"] == "milestone_outcome" else 4
                out.append(f'<circle cx="{at:.1f}" cy="{mid:.1f}" r="{r}" fill="{colour}" fill-opacity="0.8">'
                           f'{tip}</circle>')
    xt = x(now)
    out.append(f'<line class="today" x1="{xt:.1f}" y1="{top - 4}" x2="{xt:.1f}" y2="{bottom}" stroke-width="1.5" '
               'stroke-dasharray="4 3"/>')
    out.append(f'<text class="today-ink" x="{xt:.1f}" y="{top - 8}" text-anchor="middle">today</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
