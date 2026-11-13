"""After-close engine on synthetic bars. No network."""

import re
from datetime import date
from pathlib import Path

from src.engine import run_after_close
from src.rules import compute_indicators, evaluate_breakout, evaluate_pullback
from src.state import WatchRow, load_papers, load_watch, save_fills, save_watch
from src.state import Fill
from tests.support import FakeMarket, bar, make_repo, trading_days_ending

SESSION = date(2026, 11, 20)


def _breakout_bars():
    days = trading_days_ending(SESSION, 130)
    bars = [bar(day, 100, high=101, low=99) for day in days[:-16]]
    bars += [bar(day, 101, high=102, low=100) for day in days[-16:-1]]
    bars.append(bar(days[-1], 104, high=106, low=103, volume=2_000_000))
    return bars


def _qqq_bars(last_above=True):
    days = trading_days_ending(SESSION, 80)
    bars = []
    for index, day in enumerate(days):
        close = 400 + index
        bars.append(bar(day, close, high=close + 1, low=close - 1))
    if not last_above:
        bars[-1] = bar(days[-1], 100, high=101, low=99)
    return bars


def _seed_watch(root: Path, symbols):
    rows = []
    for symbol in symbols:
        row = WatchRow()
        row.ticker = symbol
        row.company = f"{symbol} Co"
        row.theme = "Chips & AI compute"
        row.pullback = "No"
        row.consolidating = "No"
        row.trigger = "No"
        row.last_price = 50
        row.earnings = ""
        rows.append(row)
    save_watch(root, rows)


def test_breakout_opens_one_paper_row_and_a_factual_report(tmp_path):
    root = make_repo(tmp_path)
    _seed_watch(root, ["ABC", "XYZ"])
    abc = _breakout_bars()
    qqq = _qqq_bars()
    indicators = compute_indicators(abc)
    assert evaluate_breakout(abc, indicators, qqq_above_ma50=True).flag
    client = FakeMarket({"ABC": abc, "QQQ": qqq})
    report = run_after_close(root, SESSION, client)
    assert "Daily after-close report — 2026-11-20" in report
    assert "not investment advice" in report.lower()
    assert not re.search(r"\byou should\b|\bbuy\b|\bsell\b", report, re.I)
    papers = load_papers(root)
    assert len(papers) == 1
    pos = papers[0]
    assert pos.ticker == "ABC"
    assert pos.setup == "Breakout"
    assert pos.entry == 104
    assert pos.stop == 100
    assert pos.shares == 3
    assert pos.target == 112
    assert pos.sim_shares == 240
    assert "Sim trimmed" in pos.notes
    watch = {row.ticker: row for row in load_watch(root)}
    assert watch["XYZ"].last_price == 50  # fetch failed; row unchanged
    assert watch["ABC"].trigger == "Yes"
    assert watch["ABC"].last_check == SESSION
    assert "XYZ" in report
    again = run_after_close(root, SESSION, client)
    assert len(load_papers(root)) == 1
    assert "No new triggers, failures, or skips today." in again


def test_circuit_breaker_and_guardrail_leave_the_paper_row(tmp_path):
    root = make_repo(tmp_path)
    _seed_watch(root, ["ABC"])
    sold = Fill()
    sold.day = date(2026, 11, 19)
    sold.ticker = "ZZZ"
    sold.side = "Sell"
    sold.shares = 10
    sold.price = 5
    sold.signal_price = 20
    bought = Fill()
    bought.day = date(2026, 11, 19)
    bought.ticker = "ZZZ"
    bought.side = "Buy"
    bought.shares = 10
    bought.price = 20
    bought.signal_price = 20
    save_fills(root, [bought, sold])
    client = FakeMarket({"ABC": _breakout_bars(), "QQQ": _qqq_bars()})
    report = run_after_close(root, SESSION, client)
    pos = load_papers(root)[0]
    assert pos.shares is None
    assert "Circuit breaker — paper only" in pos.notes
    assert pos.sim_shares == 240
    assert "Circuit breaker" in report
    assert not re.search(r"\bbuy\b|\bsell\b|\byou should\b", report, re.I)


def test_pullback_still_flags_when_the_breakout_filter_is_closed(tmp_path):
    root = make_repo(tmp_path)
    _seed_watch(root, ["PB"])
    days = trading_days_ending(SESSION, 80)
    bars = [bar(day, 100, high=110, low=90) for day in days[:-3]]
    bars += [
        bar(days[-3], 101, low=100.2, high=102),
        bar(days[-2], 101.2, low=100.2, high=102),
        bar(days[-1], 101.0, low=100.4, high=102),
    ]
    indicators = compute_indicators(bars)
    assert evaluate_pullback(bars, indicators.ma50).flag
    assert not evaluate_breakout(bars, indicators, qqq_above_ma50=False).flag
    client = FakeMarket({"PB": bars, "QQQ": _qqq_bars(last_above=False)})
    run_after_close(root, SESSION, client)
    papers = load_papers(root)
    assert len(papers) == 1
    assert papers[0].setup == "Pullback"
    assert papers[0].shares is not None
