"""Shared fixtures for the rule tests."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.calendar_nyse import is_trading_day
from src.market_data import HistoryResult, NewsItem, QuoteResult
from src.rules import Bar
from src.schema import DEFAULT_SETTINGS
from src.state import write_seed


def trading_days_ending(end: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if is_trading_day(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def bar(day: date, close: float, *, high=None, low=None, volume=1_000_000.0, open_=None) -> Bar:
    high = close if high is None else high
    low = close if low is None else low
    open_ = close if open_ is None else open_
    return Bar(day, open_, high, low, close, volume)


def make_repo(path: Path) -> Path:
    write_seed(path)
    (path / "settings.json").write_text(json.dumps(DEFAULT_SETTINGS, indent=2) + "\n", encoding="utf-8")
    (path / "rules.md").write_text("Standing rules.\n", encoding="utf-8")
    (path / "data" / "README.md").write_text(
        "Paper rows are a signal record. Plan shares are the real test plan. "
        "Sim shares are the simulation. The program does not place trades.\n",
        encoding="utf-8",
    )
    return path


class FakeMarket:
    def __init__(self, histories=None, quotes=None, earnings=None, news=None):
        self.histories = histories or {}
        self.quotes = quotes or {}
        self.earnings = earnings or {}
        self._news = news or []
        self.news_error = None

    def history(self, symbol: str) -> HistoryResult:
        bars = self.histories.get(symbol)
        if not bars:
            return HistoryResult(symbol, error="fixture has no series")
        return HistoryResult(
            symbol=symbol,
            bars=list(bars),
            source="fixture",
            company=f"{symbol} Co",
            quote_type="EQUITY",
        )

    def quote(self, symbol: str) -> QuoteResult:
        found = self.quotes.get(symbol)
        if not found:
            return QuoteResult(symbol, error="no quote")
        price, prev = found if isinstance(found, tuple) else (found, None)
        return QuoteResult(symbol, price=price, previous_close=prev)

    def earnings_date(self, symbol: str, quote_type: str | None = None) -> str | None:
        if quote_type and quote_type.upper() == "ETF":
            return "N/A"
        return self.earnings.get(symbol, "2027-04-15")

    def company_name(self, symbol: str) -> str | None:
        return f"{symbol} Co"

    def news(self, symbols: list[str]) -> tuple[list[NewsItem], str | None]:
        return list(self._news), self.news_error
