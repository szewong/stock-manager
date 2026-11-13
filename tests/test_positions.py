"""2R partial, breakeven stop, and the same-day MA20 trail."""

from datetime import date

from src.positions import PaperPosition, apply_session, blended_fraction, target_price
from tests.support import bar


def _open(entry=100.0, stop=90.0) -> PaperPosition:
    return PaperPosition(
        ticker="ABC",
        last_close=entry,
        live_price=entry,
        vs_entry_pct=0.0,
        setup="Breakout",
        entry_date=date(2026, 11, 20),
        entry=entry,
        stop=stop,
        target=target_price(entry, stop),
        trail=95,
        status="Open",
        exit_date=None,
        exit_price=None,
        blended_pct=None,
        shares=3,
        notes=f"Original stop {stop:.2f}.",
        sim_shares=10,
        sim_result=None,
    )


def test_target_and_blend_formulas():
    assert target_price(100, 90) == 120
    assert blended_fraction(100, 110, 120, False) == 0.10
    assert blended_fraction(100, 100, 120, True) == 0.10


def test_half_sale_moves_stop_to_entry_and_keeps_the_original():
    pos = _open()
    events = apply_session(pos, bar(date(2026, 11, 20), 110, high=121, low=99), ma20=105)
    assert events == ["half"]
    assert pos.status == "Half sold"
    assert pos.stop == 100
    assert pos.original_stop() == 90
    assert "Half at target on 2026-11-20" in pos.notes
    assert pos.trail == 105
    assert pos.blended_pct is None


def test_same_day_trail_exit_after_the_partial():
    pos = _open()
    events = apply_session(pos, bar(date(2026, 11, 20), 100, high=121, low=99), ma20=105)
    assert events == ["half", "exit-trail"]
    assert pos.status == "Exited"
    assert pos.exit_price == 100
    assert abs(pos.blended_pct - 10.0) < 1e-9
    assert pos.sim_result == 100.0  # 10 shares * 100 entry * 10%
    assert pos.live_price is None
    assert pos.vs_entry_pct == 0


def test_open_stop_exit_uses_the_close():
    pos = _open()
    events = apply_session(pos, bar(date(2026, 11, 21), 89, high=110, low=88), ma20=95)
    assert events == ["exit-stop"]
    assert pos.blended_pct == -11.0
    assert "close below stop" in pos.notes


def test_half_sold_row_exits_when_the_close_is_under_ma20():
    pos = _open()
    apply_session(pos, bar(date(2026, 11, 20), 110, high=121, low=99), ma20=105)
    events = apply_session(pos, bar(date(2026, 11, 21), 104, high=112, low=103), ma20=106)
    assert events == ["exit-trail"]
    assert pos.exit_date == date(2026, 11, 21)
    # 0.5 * 20% + 0.5 * 4% = 12%
    assert abs(pos.blended_pct - 12.0) < 1e-9
