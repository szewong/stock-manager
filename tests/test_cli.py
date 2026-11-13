"""Scheduled commands exit cleanly, and the trading-day probe uses ET."""

from src.cli import main
from src.fills import record_fill
from src.health import audit
from src.state import load_real
from tests.support import make_repo


def test_is_trading_day_exit_codes(monkeypatch):
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-20T12:00:00")
    assert main(["is-trading-day"]) == 0
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-26T12:00:00")
    assert main(["is-trading-day"]) == 1
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-21T12:00:00")
    assert main(["is-trading-day"]) == 1
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-07-03T15:00:00")
    assert main(["is-trading-day"]) == 1
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-27T15:00:00")
    assert main(["is-trading-day"]) == 0


def test_after_close_is_silent_on_a_holiday(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    monkeypatch.setenv("STOCK_MANAGER_ROOT", str(root))
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-26T18:00:00")
    assert main(["after-close"]) == 0
    assert capsys.readouterr().out == ""
    assert list((root / "reports").glob("*-after-close.md")) == []


def test_midday_is_silent_on_a_weekend(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    monkeypatch.setenv("STOCK_MANAGER_ROOT", str(root))
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-21T13:14:00")
    assert main(["midday"]) == 0
    assert main(["late"]) == 0
    assert main(["market-open"]) == 0
    assert capsys.readouterr().out == ""


def test_midday_marker_when_nothing_is_flagged(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    monkeypatch.setenv("STOCK_MANAGER_ROOT", str(root))
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-20T13:14:00")
    assert main(["midday"]) == 0
    assert capsys.readouterr().out.strip() == "NO_FLAGS"


def test_health_check_on_a_fresh_store(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-13T09:00:00")
    failures, counts = audit(root)
    assert failures == []
    assert "watchlist 0" in counts


def test_record_fill_rebuilds_real_positions(tmp_path):
    root = make_repo(tmp_path)
    text = record_fill(
        root,
        day=__import__("datetime").date(2026, 11, 20),
        ticker="abc",
        side="Buy",
        shares=4,
        price=25,
        commission=1,
        other_costs=0.5,
        setup="Breakout",
        notes="reported fill",
        signal_price=24.5,
        client=None,
    )
    assert "entry" in text
    rows = load_real(root)
    assert rows[0].ticker == "ABC"
    assert rows[0].net_shares == 4
    assert rows[0].avg_cost == 25
    assert rows[0].status == "Open"
    record_fill(
        root,
        day=__import__("datetime").date(2026, 11, 21),
        ticker="ABC",
        side="Sell",
        shares=4,
        price=30,
        commission=1,
        other_costs=0,
        setup="Breakout",
        notes="",
        signal_price=24.5,
        client=None,
    )
    closed = load_real(root)[0]
    assert closed.status == "Closed"
    assert closed.net_shares == 0
    # sell gross 120 - avg 25 * 4 - commissions 2 - other 0.5 = 17.5
    assert closed.realized == 17.5
