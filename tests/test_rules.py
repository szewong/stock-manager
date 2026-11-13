"""Signal math: breakout, pullback (including snap-back), earnings."""

from datetime import date, timedelta

from src.rules import (
    Indicators,
    breakout_invalidated,
    choose_setup,
    compute_indicators,
    earnings_blocks,
    evaluate_breakout,
    evaluate_pullback,
    pullback_invalidated,
    sessions_after,
)
from tests.support import bar, trading_days_ending


def _indicators(**overrides) -> Indicators:
    base = dict(
        ma20=100,
        ma50=100,
        ma100=90,
        consol_high=102,
        consol_low=100,
        range_pct=0.02,
        consolidating=True,
        base_high=102,
        base_low=100,
        base_range_pct=0.02,
        base_ok=True,
        volume_ratio=2.0,
        volume_unknown=False,
        daily_move_pct=1.0,
    )
    base.update(overrides)
    return Indicators(**base)


def _bars(close=104.0):
    return [bar(date(2026, 11, 20), close, high=106, low=103, volume=2_000_000)]


def test_both_patterns_collapse_to_the_breakout_stop():
    assert choose_setup(True, True) == "Breakout"
    assert choose_setup(False, True) == "Pullback"
    assert choose_setup(False, False) is None


def test_breakout_flags_when_base_volume_and_market_agree():
    result = evaluate_breakout(_bars(), _indicators(), qqq_above_ma50=True)
    assert result.flag
    assert result.reason == "meets the breakout rule"


def test_breakout_rejects_a_wide_base_and_thin_volume():
    wide = evaluate_breakout(_bars(), _indicators(base_ok=False), qqq_above_ma50=True)
    assert not wide.flag
    assert "wider" in wide.reason
    thin = evaluate_breakout(_bars(), _indicators(volume_ratio=1.2), qqq_above_ma50=True)
    assert not thin.flag
    assert not thin.unverifiable_volume


def test_breakout_below_ma100_does_not_flag():
    result = evaluate_breakout(_bars(95), _indicators(ma100=100, ma50=90), qqq_above_ma50=True)
    assert not result.flag
    assert "MA100" in result.reason


def test_breakout_market_filter_blocks_without_calling_volume_unverifiable():
    blocked = evaluate_breakout(_bars(), _indicators(), qqq_above_ma50=False)
    assert blocked.market_filter_block and not blocked.flag
    missing = evaluate_breakout(
        _bars(), _indicators(volume_ratio=None, volume_unknown=True), qqq_above_ma50=True
    )
    assert missing.unverifiable_volume and not missing.flag


def test_breakout_from_a_synthetic_series():
    days = trading_days_ending(date(2026, 11, 20), 130)
    bars = []
    for day in days[:-16]:
        bars.append(bar(day, 100, high=101, low=99))
    for day in days[-16:-1]:
        bars.append(bar(day, 101, high=102, low=100))
    bars.append(bar(days[-1], 104, high=106, low=103, volume=2_000_000))
    indicators = compute_indicators(bars)
    assert indicators.base_ok
    assert indicators.base_high == 102
    assert indicators.base_low == 100
    assert indicators.volume_ratio == 2
    assert evaluate_breakout(bars, indicators, qqq_above_ma50=True).flag
    assert not evaluate_breakout(bars, indicators, qqq_above_ma50=False).flag


def test_invalidation_window_is_five_sessions():
    assert breakout_invalidated(close=99, base_low=100, sessions_after_trigger=3)
    assert not breakout_invalidated(close=99, base_low=100, sessions_after_trigger=6)
    assert not breakout_invalidated(close=101, base_low=100, sessions_after_trigger=2)
    days = [date(2026, 11, 2) + timedelta(days=offset) for offset in range(0, 12, 2)]
    bars = [bar(day, 100) for day in days]
    assert sessions_after(bars, days[0], days[3]) == 3


def test_pullback_flags_a_clean_touch():
    ma = 100.0
    days = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    bars = [
        bar(days[0], 101, low=100.4, high=102),
        bar(days[1], 101.2, low=100.2, high=102),
        bar(days[2], 101.0, low=100.5, high=102),
    ]
    result = evaluate_pullback(bars, ma)
    assert result.flag
    assert result.near_miss is None


def test_pullback_snap_back_is_not_a_flag():
    days = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    bars = [
        bar(days[0], 101, low=100.2, high=102),
        bar(days[1], 99.0, low=98.5, high=101),
        bar(days[2], 101.0, low=100.0, high=102),
    ]
    result = evaluate_pullback(bars, 100)
    assert not result.flag
    assert result.near_miss == "snap-back"


def test_pullback_separation_near_miss_and_exact_boundary():
    days = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    near = [
        bar(days[0], 100.2, low=100.0, high=100.4),
        bar(days[1], 100.2, low=100.0, high=100.4),
        bar(days[2], 100.14, low=100.0, high=100.3),
    ]
    missed = evaluate_pullback(near, 100)
    assert not missed.flag
    assert missed.near_miss == "separation"
    exact = [
        bar(days[0], 100.6, low=100.5, high=100.8),
        bar(days[1], 100.6, low=100.5, high=100.8),
        bar(days[2], 100.5, low=101.0, high=100.7),
    ]
    # low 101 is NOT a touch (band ceiling is 101). Replace with a real tag.
    exact[0] = bar(days[0], 100.6, low=100.9, high=100.8)
    flagged = evaluate_pullback(exact, 100)
    assert flagged.flag


def test_pullback_touch_must_reach_the_band():
    days = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    bars = [bar(day, 102, low=101.01, high=103) for day in days]
    result = evaluate_pullback(bars, 100)
    assert not result.flag
    assert result.near_miss is None


def test_pullback_invalidation():
    assert pullback_invalidated("Yes", 99, 100)
    assert not pullback_invalidated("Yes", 100, 100)
    assert not pullback_invalidated("No", 99, 100)


def test_earnings_filter_boundaries():
    day = date(2026, 11, 20)
    assert earnings_blocks(date(2026, 11, 20), day)[0]
    assert earnings_blocks(date(2026, 11, 25), day)[0]
    assert not earnings_blocks(date(2026, 11, 26), day)[0]
    assert not earnings_blocks(date(2026, 11, 19), day)[0]
    assert not earnings_blocks("N/A", day)[0]
    skip, note = earnings_blocks(None, day)
    assert not skip and note == "earnings date unknown"
    assert earnings_blocks("2026-11-22", day)[0]
