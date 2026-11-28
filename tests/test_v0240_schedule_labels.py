"""0.24.0 (P04): the schedule's labels never overlap.

Milestones close together (a release candidate and its release, a few days apart at the end of the lane, as on this
repository's own schedule) and several on one day: every label drawn stays clear of the others in its text row, a
shortened label carries its full name in its `<title>`, and a lone milestone keeps its full name on the lane's row.
"""

import xml.etree.ElementTree as ET

from steward import charts

NS = "{http://www.w3.org/2000/svg}"


def _milestone(name, time):
    return {"kind": "milestone", "id": f"milestone:{name}", "title": name, "time": time, "end": None,
            "internal": None, "moved_from": None, "moved_to": None, "state": "planned", "day": True,
            "project": None, "path": "development/milestones.toml", "line": 1}


def _doc(events):
    return {"schema": "steward.timeline_events/0.1", "now": "2026-01-05T00:00:00Z",
            "projects": [{"code": None}], "events": sorted(events, key=lambda e: e["time"], reverse=True)}


def _labels(svg):
    """Each label as (row y, left x, right x, text shown, full name)."""
    out = []
    for el in ET.fromstring(svg).iter(f"{NS}text"):
        if el.get("font-size") != "11":
            continue
        shown = el.text
        title = el.find(f"{NS}title")
        w = len(shown) * charts.LABEL_CHAR
        x = float(el.get("x"))
        a = x - w if el.get("text-anchor") == "end" else x
        out.append((el.get("y"), a, a + w, shown, title.text if title is not None else shown))
    return out


def _no_overlap(labels):
    for i, (row, a, b, *_rest) in enumerate(labels):
        for row2, a2, b2, *_ in labels[i + 1:]:
            assert row != row2 or b <= a2 or b2 <= a, f"labels overlap: {labels[i]} and {(row2, a2, b2)}"


def test_P04_close_milestone_labels_do_not_overlap():
    names = ["core-machine-interface", "pypi-stable", "vscode-0.1.0-alpha", "vscode-0.1.0-rc", "vscode-0.1.0"]
    times = ["2026-01-10", "2026-01-08", "2026-01-08", "2026-04-04", "2026-04-28"]
    svg = charts.schedule(_doc([_milestone(n, f"{t}T00:00:00Z") for n, t in zip(names, times)]))
    labels = _labels(svg)
    _no_overlap(labels)
    full = {lab[4] for lab in labels}
    assert {"vscode-0.1.0-rc", "vscode-0.1.0"} <= full  # both are labelled, neither hides the other
    for _row, _a, _b, shown, name in labels:
        assert shown == name or (shown.startswith("…") and name.endswith(shown[1:]))
    assert len({lab[0] for lab in labels}) == 2  # the second text row is used


def test_P04_many_milestones_on_one_day_stay_apart():
    events = [_milestone(f"gate-{k}-review", "2026-03-01T00:00:00Z") for k in range(8)]
    events.append(_milestone("start", "2026-01-01T00:00:00Z"))
    labels = _labels(charts.schedule(_doc(events)))
    _no_overlap(labels)
    assert labels  # some are labelled; the rest keep their names in their marks' tooltips


def test_P04_a_lone_milestone_keeps_its_full_name_on_its_row():
    svg = charts.schedule(_doc([_milestone("vscode-0.1.0", "2026-02-01T00:00:00Z")]))
    [(row, _a, _b, shown, name)] = _labels(svg)
    assert shown == name == "vscode-0.1.0" and row == "91.0"  # the lane's own row (the first lane's middle + 4)
