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
