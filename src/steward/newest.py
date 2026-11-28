"""Newest first (0.22.0, X05): the order every text list prints in.

A list is ordered by its entries' dates, newest first, then by their IDs, highest first. IDs compare as people read
them (`T10` after `T9`). An entry without a date comes after every dated one. The versioned JSON documents keep their
own documented order; only the text views use this one.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")
_PARTS = re.compile(r"\d+|\D+")


def id_key(value: Any) -> tuple:
    """An ID's natural sort key: runs of digits compare as numbers, the rest as text."""
    text = "" if value is None else str(value)
    return tuple((1, int(p), "") if p.isdigit() else (0, 0, p) for p in _PARTS.findall(text))


def when_key(value: Any) -> tuple[int, float]:
    """A date, a datetime, an ISO 8601 string or a number of seconds as a sort key; (0, 0) when there is none."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return 1, moment.timestamp()
    if isinstance(value, date):
        return 1, datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 1, float(value)
    if isinstance(value, str) and value:
        text = value.strip().replace("Z", "+00:00") if value.strip().endswith("Z") else value.strip()
        try:
            return when_key(datetime.fromisoformat(text))
        except ValueError:
            try:
                return when_key(date.fromisoformat(text[:10]))
            except ValueError:
                return 0, 0.0
    return 0, 0.0


def newest_first(items: Iterable[T], when: Callable[[T], Any], ident: Callable[[T], Any]) -> list[T]:
    """`items` by date, newest first, then by ID, highest first; undated entries last."""
    return sorted(items, key=lambda item: (when_key(when(item)), id_key(ident(item))), reverse=True)
