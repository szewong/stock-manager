"""Aggregates for the dashboard, summary, and health check."""

from __future__ import annotations

from datetime import date
from statistics import median

from src.positions import PaperPosition


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_percents(values: list[float]) -> dict:
    if not values:
        return {
            "exited": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": None,
            "average_result_pct": None,
            "median_result_pct": None,
            "average_win_pct": None,
            "average_loss_pct": None,
            "best_pct": None,
            "worst_pct": None,
            "sum_pct": None,
        }
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "exited": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": 100.0 * len(wins) / len(values),
        "average_result_pct": _mean(values),
        "median_result_pct": float(median(values)),
        "average_win_pct": _mean(wins),
        "average_loss_pct": _mean(losses),
        "best_pct": max(values),
        "worst_pct": min(values),
        "sum_pct": sum(values),
    }


def sim_unrealized(pos: PaperPosition) -> float:
    if not pos.sim_shares or pos.last_close is None:
        return 0.0
    if pos.status == "Open":
        return pos.sim_shares * (pos.last_close - pos.entry)
    if pos.status == "Half sold":
        half = pos.sim_shares / 2.0
        banked = half * (pos.target - pos.entry)
        remaining = half * (pos.last_close - pos.entry)
        return banked + remaining
    return 0.0


def sim_snapshot(rows: list[PaperPosition], sim_account: float) -> dict:
    opened = [
        row
        for row in rows
        if row.status in ("Open", "Half sold") and row.sim_shares
    ]
    closed = [row for row in rows if row.status == "Exited" and row.sim_shares]
    realized = round(sum((row.sim_result or 0.0) for row in closed), 2)
    unrealized = round(sum(sim_unrealized(row) for row in opened), 2)
    total = round(realized + unrealized, 2)
    ret = (total / sim_account * 100.0) if sim_account else None
    return {
        "positions_open": len(opened),
        "positions_closed": len(closed),
        "realized_usd": realized,
        "unrealized_usd": unrealized,
        "total_usd": total,
        "return_pct": ret,
    }


def performance_block(
    rows: list[PaperPosition], rules_date: date | None
) -> dict:
    exited = [row for row in rows if row.status == "Exited" and row.blended_pct is not None]

    def pack(subset: list[PaperPosition]) -> dict:
        return summarize_percents([row.blended_pct for row in subset if row.blended_pct is not None])

    by_setup = {
        "Breakout": pack([row for row in exited if row.setup == "Breakout"]),
        "Pullback": pack([row for row in exited if row.setup == "Pullback"]),
    }
    if rules_date is None:
        before: list[PaperPosition] = []
        after = exited
    else:
        before = [row for row in exited if row.entry_date < rules_date]
        after = [row for row in exited if row.entry_date >= rules_date]
    return {
        "all": pack(exited),
        "by_setup": by_setup,
        "by_rules_date": {"before": pack(before), "from": pack(after)},
    }


def counts_by_status(rows: list[PaperPosition]) -> dict:
    return {
        "open": sum(1 for row in rows if row.status == "Open"),
        "half_sold": sum(1 for row in rows if row.status == "Half sold"),
        "exited": sum(1 for row in rows if row.status == "Exited"),
        "voided": sum(1 for row in rows if row.status == "Voided"),
    }
