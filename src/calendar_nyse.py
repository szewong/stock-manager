"""NYSE session calendar and the America/New_York clock.

Full-day closures for the standard NYSE holiday set. A session that closes
early is still a session. Holidays are derived from the exchange rules so
2026 and 2027 are covered without a market-calendar package.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLOSE_TIME = time(16, 5)


def now_et() -> datetime:
    raw = os.environ.get("STOCK_MANAGER_NOW")
    if raw:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ET)
        return parsed.astimezone(ET)
    return datetime.now(ET)


def easter(year: int) -> date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year, 12, 31)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


@lru_cache(maxsize=16)
def nyse_holidays(year: int) -> frozenset[date]:
    days = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    new_year = _observed(date(year + 1, 1, 1))
    if new_year.year == year:
        days.add(new_year)
    return frozenset(d for d in days if d.year == year)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def previous_trading_day(day: date) -> date:
    cursor = day - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def last_completed_session(moment: datetime | None = None) -> date:
    """Session date whose official close is already in, as of `moment` in ET."""
    moment = moment or now_et()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ET)
    else:
        moment = moment.astimezone(ET)
    if is_trading_day(moment.date()) and moment.time() >= CLOSE_TIME:
        return moment.date()
    probe = moment.date() - timedelta(days=1)
    while not is_trading_day(probe):
        probe -= timedelta(days=1)
    return probe
