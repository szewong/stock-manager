"""Rebuild derived dashboard figures from the current files."""

from __future__ import annotations

from datetime import date

from src.positions import PaperPosition
from src.schema import TEST_ROUND_CRITERIA
from src.state import Fill, WatchRow
from src.stats import counts_by_status, performance_block, sim_snapshot


def trade_log_block(fills: list[Fill]) -> dict:
    entry = [fill for fill in fills if fill.side == "Buy"]
    exit_ = [fill for fill in fills if fill.side == "Sell"]
    commissions = round(sum(fill.commission for fill in fills), 2)
    other = round(sum(fill.other_costs for fill in fills), 2)
    entry_gross = sum(fill.gross for fill in entry)
    exit_gross = sum(fill.gross for fill in exit_)
    return {
        "orders": len(fills),
        "entry_fills": len(entry),
        "exit_fills": len(exit_),
        "total_commissions": commissions,
        "total_other_costs": other,
        "net_cash_flow": round(exit_gross - entry_gross - commissions - other, 2),
    }


def build_radar(watch: list[WatchRow], papers: list[PaperPosition], session: date, horizon: int = 14) -> list[dict[str, str]]:
    open_names = {row.ticker for row in papers if row.status in ("Open", "Half sold")}
    rows: list[dict[str, str]] = []
    for item in watch:
        token = (item.earnings or "").strip()
        if token in ("", "N/A"):
            continue
        try:
            when = date.fromisoformat(token)
        except ValueError:
            continue
        days = (when - session).days
        if 0 <= days <= horizon:
            rows.append(
                {
                    "Ticker": item.ticker,
                    "Earnings date": when.isoformat(),
                    "Days away": str(days),
                    "Open position?": "Yes" if item.ticker in open_names else "No",
                }
            )
    rows.sort(key=lambda row: (row["Earnings date"], row["Ticker"]))
    return rows


def build_dashboard(
    settings: dict,
    papers: list[PaperPosition],
    fills: list[Fill],
    radar: list[dict[str, str]],
    *,
    qqq_close: float | None,
    qqq_ma50: float | None,
    market_filter: str | None,
    last_check: str | None,
    ib_cash: float | None = None,
    ib_as_of: str | None = None,
) -> dict:
    account = float(settings["account_size_usd"])
    risk = float(settings["risk_pct_per_trade"])
    start = settings["test_round_start"]
    end = settings["round_end_date"]
    flag = settings.get("flag_rules_effective_date")
    sim_account = float(settings["sim_account_size_usd"])
    return {
        "test_round": {
            "account_size_usd": account,
            "risk_pct": risk,
            "risk_per_trade_usd": round(account * risk, 2),
            "test_round_start": start.isoformat() if hasattr(start, "isoformat") else str(start),
            "round_end_date": end.isoformat() if hasattr(end, "isoformat") else str(end),
            "round_end_closed_trades": settings["round_end_closed_trades"],
            "max_open_positions": settings["max_open_test_positions"],
            "max_total_open_risk_pct": settings["max_total_open_risk_pct"],
            "circuit_breaker_usd": settings["circuit_breaker_usd"],
            "circuit_breaker_pct": settings["circuit_breaker_pct"],
        },
        "market_regime": {
            "qqq_last_close": None if qqq_close is None else round(qqq_close, 2),
            "qqq_ma50": None if qqq_ma50 is None else round(qqq_ma50, 2),
            "market_filter": market_filter,
            "last_daily_check": last_check,
        },
        "paper_positions": counts_by_status(papers),
        "trade_log": trade_log_block(fills),
        "earnings_radar": radar,
        "test_round_criteria": TEST_ROUND_CRITERIA,
        "paper_performance": performance_block(papers, flag if isinstance(flag, date) else None),
        "sim_portfolio": sim_snapshot(papers, sim_account),
        "ib_cash_available_usd": ib_cash,
        "ib_cash_as_of": ib_as_of,
    }
