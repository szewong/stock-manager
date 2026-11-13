"""Column names, standing settings, and the test-round criteria paragraph."""

from __future__ import annotations

WATCHLIST_COLUMNS = [
    "Ticker",
    "Company",
    "Theme",
    "Pullback?",
    "Consolidating?",
    "Trigger?",
    "Stop",
    "Shares",
    "Last price",
    "MA50",
    "MA100",
    "Consol. high",
    "Consol. low",
    "15-day range %",
    "Volume vs 20-day avg",
    "Last check",
    "Notes",
    "Earnings Date",
    "Vs MA50 %",
    "To consol. high %",
]

PAPER_COLUMNS = [
    "Ticker",
    "Last close",
    "Live price",
    "vs Entry %",
    "Setup",
    "Entry date",
    "Entry",
    "Stop",
    "Target (2R)",
    "Trail stop (MA20)",
    "Status",
    "Exit date",
    "Exit price",
    "Blended result %",
    "Shares",
    "Notes",
    "Sim Shares",
    "Sim result (US$)",
    "Buy decision",
]

TRADE_COLUMNS = [
    "Date",
    "Ticker",
    "Buy/Sell",
    "Shares",
    "Price",
    "Signal price",
    "Gross amount",
    "Commission",
    "Other costs",
    "Setup",
    "Notes",
]

REAL_COLUMNS = [
    "Ticker",
    "Status",
    "Net shares",
    "Avg cost",
    "Cost basis",
    "Live price",
    "Market value",
    "Unrealized P&L",
    "Unrealized %",
    "Bought (shares)",
    "Sold (shares)",
    "Realized P&L",
    "Total P&L",
    "Last activity",
    "Setup (latest)",
]

RADAR_COLUMNS = ["Ticker", "Earnings date", "Days away", "Open position?"]

BENCH_COLUMNS = [
    "Name",
    "Ticker",
    "Sector",
    "Market cap",
    "Fit",
    "Named in review date",
    "Notes",
]

SECTORS = [
    "Biotech & healthcare",
    "Chips & AI compute",
    "AI infrastructure, data centres & networking",
    "Software, security & platforms",
    "Power, nuclear & grid",
    "Big Tech, consumer & index",
    "Financials",
    "Energy",
    "Defense & aerospace",
    "Minerals & metals",
]

# Percent columns are stored as percentage points (8.00 means 8%).
# Money columns are decimal dollars. Settings rates stay as fractions (0.02 means 2%).

DEFAULT_SETTINGS: dict = {
    "timezone": "America/New_York",
    "account_size_usd": 750,
    "risk_pct_per_trade": 0.02,
    "test_round_start": "2026-11-19",
    "round_end_date": "2026-12-31",
    "round_end_closed_trades": 10,
    "weekly_watchlist_review": True,
    "max_open_test_positions": 3,
    "max_total_open_risk_pct": 0.06,
    "circuit_breaker_pct": 0.20,
    "circuit_breaker_usd": 150,
    "sim_account_size_usd": 100000,
    "sim_risk_pct_per_trade": 0.02,
    "sim_concentration_ceiling_pct": 0.25,
    "breakout_range_pct": 0.08,
    "breakout_sessions": 15,
    "breakout_volume_multiple": 1.5,
    "breakout_volume_avg_sessions": 20,
    "pullback_touch_band": 0.01,
    "pullback_sessions": 3,
    "pullback_min_separation": 0.005,
    "earnings_filter_calendar_days": 5,
    "market_filter_symbol": "QQQ",
    "market_filter_ma_sessions": 50,
    "market_filter_applies_to": "breakouts",
    "profit_target_r": 2,
    "partial_fraction": 0.5,
    "trail_ma_sessions": 20,
    "earnings_radar_calendar_days": 14,
    "ib_cash_available_usd": None,
    "ib_cash_as_of": None,
    "flag_rules_effective_date": "2026-11-12",
    "check_times_et": {
        "market_open": "11:00",
        "midday": "13:14",
        "late": "15:15",
        "after_close": "17:14",
        "health_check": "Sun 09:14",
        "watchlist_review": "Sun 10:14",
        "reconcile": "day 3 10:14",
    },
}

TEST_ROUND_CRITERIA = (
    "Round ends at the first 10 closed real trades or on 2026-12-31, whichever "
    "comes first. Judged on win rate, average R, slippage versus the signal price, "
    "and commissions as a share of gross result, with the real record set beside "
    "the paper record over the same window. Benchmark: QQQ's change from the close "
    "the session before the round starts to the round-end close, compared with the "
    "account's change over that same window. Beating that QQQ change is the "
    "pre-agreed score for the round, not a view on holding QQQ. Circuit breaker: "
    "if the cumulative real result (trade-log realized result plus unrealized "
    "result) reaches -20% of the account before the round ends, new real-plan "
    "sizing pauses and new triggers stay on paper until the round is resumed; "
    "positions already open are still tracked."
)
