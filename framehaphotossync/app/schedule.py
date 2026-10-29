"""Compute the next scheduled run for daily / weekly / monthly frequencies."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, tzinfo
from typing import Any


def _at(day: datetime, hh: int, mm: int) -> datetime:
    return day.replace(hour=hh, minute=mm, second=0, microsecond=0)


def next_run(settings: dict[str, Any], now: datetime) -> datetime:
    """Return the first scheduled time strictly after ``now`` (tz-aware ``now``)."""
    hh, mm = (int(p) for p in settings["time"].split(":"))
    freq = settings["frequency"]

    if freq == "daily":
        candidate = _at(now, hh, mm)
        if candidate <= now:
            candidate = _at(now + timedelta(days=1), hh, mm)
        return candidate

    if freq == "weekly":
        days_ahead = (settings["weekday"] - now.weekday()) % 7
        candidate = _at(now + timedelta(days=days_ahead), hh, mm)
        if candidate <= now:
            candidate = _at(now + timedelta(days=days_ahead + 7), hh, mm)
        return candidate

    # monthly: clamp the day to the length of the month (31 -> 28/29/30)
    year, month = now.year, now.month
    for _ in range(2):
        day = min(settings["day_of_month"], calendar.monthrange(year, month)[1])
        candidate = _at(now.replace(year=year, month=month, day=day), hh, mm)
        if candidate > now:
            return candidate
        month += 1
        if month > 12:
            year, month = year + 1, 1
    raise RuntimeError("unreachable")


def now_in(tz: tzinfo) -> datetime:
    return datetime.now(tz)
