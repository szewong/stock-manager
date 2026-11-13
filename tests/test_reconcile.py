"""Broker CSV reconciliation stays read-only."""

from datetime import date
from pathlib import Path

from src.reconcile import reconcile_statement
from src.state import Fill, save_fills
from tests.support import make_repo


def test_empty_month_stops_without_guessing(tmp_path):
    root = make_repo(tmp_path)
    statement = tmp_path / "empty.csv"
    statement.write_text("Symbol,TradeDate,Buy/Sell,Quantity,Price,Commission\n", encoding="utf-8")
    text = reconcile_statement(root, statement, date(2026, 12, 3))
    assert "No real executions" in text
    assert "November 2026" in text


def test_statement_trade_missing_from_the_log(tmp_path):
    root = make_repo(tmp_path)
    statement = tmp_path / "ib.csv"
    statement.write_text(
        "Symbol,TradeDate,Buy/Sell,Quantity,Price,Commission,Fees\n"
        "AAPL,2026-11-20,Buy,5,103.00,1.00,0.00\n",
        encoding="utf-8",
    )
    text = reconcile_statement(root, statement, date(2026, 12, 3))
    assert "Discrepancies found" in text
    assert "AAPL" in text
    assert "entry" in text
    assert "Buy" not in text.split("Discrepancies")[1]


def test_matching_fill(tmp_path):
    root = make_repo(tmp_path)
    fill = Fill()
    fill.day = date(2026, 11, 20)
    fill.ticker = "AAPL"
    fill.side = "Buy"
    fill.shares = 5
    fill.price = 103
    fill.signal_price = 103
    fill.commission = 1
    save_fills(root, [fill])
    statement = tmp_path / "ib.csv"
    statement.write_text(
        "Symbol,TradeDate,Buy/Sell,Quantity,Price,Commission,Fees\n"
        "AAPL,2026-11-20,Buy,5,103.00,1.00,0.25\n",
        encoding="utf-8",
    )
    text = reconcile_statement(root, statement, date(2026, 12, 3))
    assert "other costs" in text
    assert "Discrepancies found" in text


def test_missing_file_does_not_invent_figures(tmp_path):
    root = make_repo(tmp_path)
    text = reconcile_statement(root, Path("/tmp/does-not-exist-statement.csv"), date(2026, 12, 3))
    assert "No statement file" in text
    assert "not guessed" in text
