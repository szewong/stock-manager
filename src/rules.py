"""Breakout, pullback, and earnings rules. Pure functions plus indicator math."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import pandas as pd


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class Indicators:
    ma20: float | None
    ma50: float | None
    ma100: float | None
    consol_high: float | None
    consol_low: float | None
    range_pct: float | None
    consolidating: bool
    base_high: float | None
    base_low: float | None
    base_range_pct: float | None
    base_ok: bool
    volume_ratio: float | None
    volume_unknown: bool
    daily_move_pct: float | None


@dataclass(frozen=True)
class BreakoutEval:
    flag: bool
    unverifiable_volume: bool
    market_filter_block: bool
    reason: str


@dataclass(frozen=True)
class PullbackEval:
    flag: bool
    near_miss: str | None
    reason: str


def _finite(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    number = float(value)
    if number != number:  # NaN
        return None
    return number


def _range_pct(high: float, low: float) -> float | None:
    mid = (high + low) / 2.0
    if mid <= 0:
        return None
    return (high - low) / mid


def compute_indicators(
    bars: Sequence[Bar],
    *,
    sessions: int = 15,
    volume_avg_sessions: int = 20,
    range_limit: float = 0.08,
) -> Indicators:
    empty = Indicators(
        None, None, None, None, None, None, False,
        None, None, None, False, None, True, None,
    )
    if not bars:
        return empty

    frame = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume if b.volume is not None else float("nan") for b in bars],
        }
    )
    close = frame["close"]
    ma20 = _finite(close.rolling(20).mean().iloc[-1]) if len(frame) >= 20 else None
    ma50 = _finite(close.rolling(50).mean().iloc[-1]) if len(frame) >= 50 else None
    ma100 = _finite(close.rolling(100).mean().iloc[-1]) if len(frame) >= 100 else None

    if len(frame) >= sessions:
        window = frame.iloc[-sessions:]
        c_high = float(window["high"].max())
        c_low = float(window["low"].min())
        span = _range_pct(c_high, c_low)
        consolidating = span is not None and span <= range_limit + 1e-12
    else:
        c_high = c_low = span = None
        consolidating = False

    if len(frame) >= sessions + 1:
        base = frame.iloc[-(sessions + 1) : -1]
        b_high = float(base["high"].max())
        b_low = float(base["low"].min())
        b_span = _range_pct(b_high, b_low)
        base_ok = b_span is not None and b_span <= range_limit + 1e-12
    else:
        b_high = b_low = b_span = None
        base_ok = False

    volume_ratio = None
    volume_unknown = True
    latest_volume = _finite(frame["volume"].iloc[-1])
    if latest_volume is not None and len(frame) >= volume_avg_sessions + 1:
        prior = frame["volume"].iloc[-(volume_avg_sessions + 1) : -1]
        if prior.notna().all() and float(prior.sum()) > 0:
            volume_ratio = latest_volume / float(prior.mean())
            volume_unknown = False

    daily_move = None
    if len(frame) >= 2:
        prev = _finite(frame["close"].iloc[-2])
        last = _finite(frame["close"].iloc[-1])
        if prev and last is not None and prev > 0:
            daily_move = (last - prev) / prev * 100.0

    return Indicators(
        ma20,
        ma50,
        ma100,
        c_high,
        c_low,
        span,
        consolidating,
        b_high,
        b_low,
        b_span,
        base_ok,
        volume_ratio,
        volume_unknown,
        daily_move,
    )


def evaluate_breakout(
    bars: Sequence[Bar],
    indicators: Indicators,
    *,
    qqq_above_ma50: bool | None,
    volume_multiple: float = 1.5,
) -> BreakoutEval:
    if (
        not bars
        or indicators.base_high is None
        or indicators.base_low is None
        or not indicators.base_ok
    ):
        if not bars or indicators.base_high is None:
            return BreakoutEval(False, False, False, "not enough history for a 15-session base")
        return BreakoutEval(False, False, False, "base range is wider than the limit")
    if indicators.ma50 is None or indicators.ma100 is None:
        return BreakoutEval(False, False, False, "moving averages unavailable")

    close = bars[-1].close
    missing = []
    if not close > indicators.base_high:
        missing.append("close is not above the base high")
    if not close > indicators.ma50:
        missing.append("close is not above MA50")
    if not close > indicators.ma100:
        missing.append("close is not above MA100")
    if missing:
        return BreakoutEval(False, False, False, "; ".join(missing))

    if qqq_above_ma50 is False:
        return BreakoutEval(False, False, True, "QQQ is not above its MA50")
    if qqq_above_ma50 is None:
        return BreakoutEval(False, False, False, "QQQ market filter unavailable")

    if indicators.volume_unknown or indicators.volume_ratio is None:
        return BreakoutEval(False, True, False, "volume unavailable; breakout not verified")
    if indicators.volume_ratio < volume_multiple:
        return BreakoutEval(False, False, False, "volume below the required multiple")
    return BreakoutEval(True, False, False, "meets the breakout rule")


def sessions_after(bars: Sequence[Bar], trigger: date, session: date) -> int:
    return sum(1 for bar in bars if trigger < bar.day <= session)


def breakout_invalidated(
    *,
    close: float,
    base_low: float,
    sessions_after_trigger: int,
    window: int = 5,
) -> bool:
    if sessions_after_trigger < 1 or sessions_after_trigger > window:
        return False
    return close < base_low


def evaluate_pullback(
    bars: Sequence[Bar],
    ma50: float | None,
    *,
    touch_band: float = 0.01,
    min_separation: float = 0.005,
    lookback: int = 3,
) -> PullbackEval:
    if ma50 is None or ma50 <= 0 or len(bars) < lookback:
        return PullbackEval(False, None, "MA50 or recent sessions unavailable")
    window = list(bars[-lookback:])
    close = window[-1].close
    ceiling = ma50 * (1.0 + touch_band)
    touched = any(bar.low <= ceiling + 1e-9 for bar in window)
    closed_under = [bar for bar in window if bar.close < ma50]
    if close > ma50 and closed_under:
        day = closed_under[-1].day.isoformat()
        return PullbackEval(
            False,
            "snap-back",
            (
                f"snap-back: {day} closed {closed_under[-1].close:.2f} under MA50 "
                f"{ma50:.2f} inside the last {lookback} sessions"
            ),
        )
    floor = ma50 * (1.0 + min_separation)
    if touched and close > ma50 and close < floor:
        gap = (close - ma50) / ma50 * 100.0
        return PullbackEval(
            False,
            "separation",
            (
                f"separation: close {close:.2f} is only {gap:.2f}% above MA50 "
                f"{ma50:.2f} (minimum is {min_separation * 100:.1f}%)"
            ),
        )
    if touched and close >= floor and not closed_under:
        return PullbackEval(True, None, "meets the pullback rule")
    return PullbackEval(False, None, "no qualifying MA50 touch")


def pullback_invalidated(flag: str, close: float, ma50: float | None) -> bool:
    if flag != "Yes" or ma50 is None:
        return False
    return close < ma50


def earnings_blocks(
    earnings: date | str | None,
    trigger_day: date,
    *,
    window_days: int = 5,
) -> tuple[bool, str]:
    """Return (skip_new_flag, note).

    A date on the trigger day through `window_days` calendar days later skips
    a new flag. `N/A` (ETFs) never skips. An unknown date does not skip.
    """
    if earnings is None or earnings == "":
        return False, "earnings date unknown"
    if isinstance(earnings, str):
        token = earnings.strip()
        if token.upper() == "N/A":
            return False, ""
        earnings = date.fromisoformat(token)
    delta = (earnings - trigger_day).days
    if 0 <= delta <= window_days:
        return (
            True,
            f"earnings {earnings.isoformat()} fall within {window_days} calendar days",
        )
    return False, ""


def choose_setup(breakout: bool, pullback: bool) -> str | None:
    """Both patterns on one day collapse to a single breakout position."""
    if breakout:
        return "Breakout"
    if pullback:
        return "Pullback"
    return None
