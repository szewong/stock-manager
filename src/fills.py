"""Append one reported fill and rebuild the derived real-position file."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.ledger import ledger_document
from src.market_data import MarketData
from src.report import build_summary
from src.state import (
    Fill,
    load_fills,
    load_json,
    load_papers,
    load_settings,
    load_watch,
    rebuild_real,
    save_fills,
    save_radar,
    save_real,
    write_json,
)
from src.views import build_dashboard, build_radar


def record_fill(
    root: Path,
    *,
    day: date,
    ticker: str,
    side: str,
    shares: int,
    price: float,
    commission: float,
    other_costs: float,
    setup: str,
    notes: str,
    signal_price: float | None,
    client: MarketData | None,
) -> str:
    if side not in ("Buy", "Sell"):
        raise ValueError("side must be the fill label Buy or Sell")
    if shares <= 0 or price <= 0 or commission < 0 or other_costs < 0:
        raise ValueError("shares and price must be positive, and costs cannot be negative")
    ticker = ticker.strip().upper()
    papers = load_papers(root)
    if signal_price is None or not setup:
        matches = [
            pos
            for pos in papers
            if pos.ticker == ticker and pos.entry_date <= day and pos.entry_date != date.min
        ]
        matches.sort(key=lambda pos: (pos.status not in ("Open", "Half sold"), -pos.entry_date.toordinal()))
        if matches:
            signal_price = signal_price if signal_price is not None else matches[0].entry
            setup = setup or matches[0].setup
    if signal_price is None:
        raise ValueError(
            f"No paper row matches {ticker} on or before {day.isoformat()}. "
            "Pass --signal-price. A signal price is not invented."
        )
    fill = Fill()
    fill.day = day
    fill.ticker = ticker
    fill.side = side
    fill.shares = int(shares)
    fill.price = round(price, 2)
    fill.signal_price = round(signal_price, 2)
    fill.commission = round(commission, 2)
    fill.other_costs = round(other_costs, 2)
    fill.setup = setup
    fill.notes = notes
    fills = load_fills(root)
    fills.append(fill)
    save_fills(root, fills)

    prices: dict[str, float | None] = {}
    if client is not None:
        for name in sorted({item.ticker for item in fills}):
            quote = client.quote(name)
            prices[name] = quote.price
    real_rows = rebuild_real(fills, prices)
    save_real(root, real_rows)

    settings = load_settings(root)
    watch = load_watch(root)
    radar = build_radar(watch, papers, day, int(settings.get("earnings_radar_calendar_days") or 14))
    save_radar(root, radar)
    previous = load_json(root / "data" / "dashboard.json")
    regime = previous.get("market_regime") or {}
    dashboard = build_dashboard(
        settings,
        papers,
        fills,
        radar,
        qqq_close=regime.get("qqq_last_close"),
        qqq_ma50=regime.get("qqq_ma50"),
        market_filter=regime.get("market_filter"),
        last_check=regime.get("last_daily_check"),
        ib_cash=settings.get("ib_cash_available_usd"),
        ib_as_of=settings.get("ib_cash_as_of"),
    )
    write_json(root / "data" / "dashboard.json", dashboard)
    write_json(
        root / "data" / "sim_ledger.json",
        ledger_document(papers, float(settings["sim_account_size_usd"])),
    )
    (root / "data" / "summary.md").write_text(
        build_summary(dashboard, papers, watch, radar), encoding="utf-8"
    )
    label = "entry" if side == "Buy" else "exit"
    return (
        f"Logged {ticker} {label} {shares} shares at {price:.2f} on {day.isoformat()}. "
        f"Signal price {signal_price:.2f}. Real positions rebuilt."
    )
