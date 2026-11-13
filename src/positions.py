"""Paper-position exits: 2R partial, breakeven stop, MA20 trail."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from src.rules import Bar
from src.textutil import append_note

_ORIGINAL_STOP = re.compile(r"Original stop ([0-9]+(?:\.[0-9]+)?)")
_BASE_LOW = re.compile(r"Base low ([0-9]+(?:\.[0-9]+)?)")
_TRIGGERED = re.compile(r"Triggered (\d{4}-\d{2}-\d{2})")
_HALF = re.compile(r"Half at target on (\d{4}-\d{2}-\d{2})")


def money(value: float) -> float:
    return round(float(value), 2)


def target_price(entry: float, stop: float, r_multiple: float = 2.0) -> float:
    return money(entry + r_multiple * (entry - stop))


def blended_fraction(
    entry: float,
    exit_price: float,
    target: float,
    had_half: bool,
    partial: float = 0.5,
) -> float:
    full = (exit_price - entry) / entry
    if not had_half:
        return full
    at_target = (target - entry) / entry
    return partial * at_target + (1.0 - partial) * full


def sim_result_usd(sim_shares: int, entry: float, blended: float) -> float:
    return round(sim_shares * entry * blended, 2)


@dataclass
class PaperPosition:
    ticker: str
    last_close: float | None
    live_price: float | None
    vs_entry_pct: float | None
    setup: str
    entry_date: date
    entry: float
    stop: float
    target: float
    trail: float | None
    status: str
    exit_date: date | None
    exit_price: float | None
    blended_pct: float | None
    shares: int | None
    notes: str
    sim_shares: int | None
    sim_result: float | None
    buy_decision: str = ""

    def original_stop(self) -> float:
        found = _ORIGINAL_STOP.findall(self.notes or "")
        if found:
            return float(found[-1])
        return self.stop

    def had_half_sale(self) -> bool:
        return "Half at target on" in (self.notes or "")


def last_trigger_date(notes: str) -> date | None:
    found = _TRIGGERED.findall(notes or "")
    if not found:
        return None
    return date.fromisoformat(found[-1])


def last_base_low(notes: str) -> float | None:
    found = _BASE_LOW.findall(notes or "")
    if not found:
        return None
    return float(found[-1])


def half_sale_date(notes: str) -> date | None:
    found = _HALF.findall(notes or "")
    if not found:
        return None
    return date.fromisoformat(found[-1])


def _mark(pos: PaperPosition, bar: Bar, ma20: float | None) -> None:
    pos.last_close = money(bar.close)
    pos.live_price = money(bar.close)
    pos.vs_entry_pct = (bar.close - pos.entry) / pos.entry * 100.0
    pos.exit_date = None
    pos.exit_price = None
    pos.blended_pct = None
    pos.sim_result = None
    if ma20 is not None:
        pos.trail = money(ma20)


def _exit(pos: PaperPosition, bar: Bar, reason: str) -> None:
    had_half = pos.had_half_sale()
    pos.status = "Exited"
    pos.exit_date = bar.day
    pos.exit_price = money(bar.close)
    pos.last_close = pos.exit_price
    pos.live_price = None
    pos.vs_entry_pct = (bar.close - pos.entry) / pos.entry * 100.0
    fraction = blended_fraction(pos.entry, bar.close, pos.target, had_half)
    pos.blended_pct = fraction * 100.0
    if pos.sim_shares:
        pos.sim_result = sim_result_usd(pos.sim_shares, pos.entry, fraction)
    else:
        pos.sim_result = None
    pos.notes = append_note(
        pos.notes, f"Exited {bar.day.isoformat()} {reason} at {bar.close:.2f}."
    )


def apply_session(pos: PaperPosition, bar: Bar, ma20: float | None) -> list[str]:
    """Advance one open paper row by a completed session. Return event labels."""
    if pos.status not in ("Open", "Half sold"):
        return []
    events: list[str] = []
    if pos.status == "Open" and round(bar.high, 4) >= round(pos.target, 4):
        if "Original stop" not in (pos.notes or ""):
            pos.notes = append_note(pos.notes, f"Original stop {pos.stop:.2f}.")
        pos.stop = money(pos.entry)
        pos.status = "Half sold"
        pos.notes = append_note(
            pos.notes,
            (
                f"Half at target on {bar.day.isoformat()} "
                f"(day high {bar.high:.2f} vs target {pos.target:.2f}); "
                "stop moved to entry."
            ),
        )
        events.append("half")

    if pos.status == "Half sold":
        if ma20 is not None and bar.close < ma20:
            if ma20 is not None:
                pos.trail = money(ma20)
            _exit(pos, bar, "close below MA20")
            events.append("exit-trail")
            return events
        _mark(pos, bar, ma20)
        return events

    if bar.close < pos.stop:
        _exit(pos, bar, "close below stop")
        events.append("exit-stop")
        return events
    _mark(pos, bar, ma20)
    return events


def sort_paper(rows: list[PaperPosition]) -> list[PaperPosition]:
    order = {"Open": 0, "Half sold": 1, "Exited": 2, "Voided": 3}
    return sorted(
        rows,
        key=lambda row: (order.get(row.status, 9), -row.entry_date.toordinal()),
    )
