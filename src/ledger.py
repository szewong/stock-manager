"""Simulation cash ledger.

On one date the order is half-sale proceeds, then exit proceeds, then entry
costs, with file order as the tiebreak. Cash is not allowed to go negative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.positions import PaperPosition, half_sale_date, sort_paper


def _cents(amount: float) -> int:
    return int(round(amount * 100))


def _dollars(cents: int) -> float:
    return cents / 100.0


@dataclass(frozen=True)
class CashEvent:
    day: date
    kind: str
    row_index: int
    ticker: str
    amount_cents: int


_KIND_ORDER = {"half": 0, "exit": 1, "entry": 2}


def events_for(rows: list[PaperPosition]) -> list[CashEvent]:
    events: list[CashEvent] = []
    for index, pos in enumerate(rows):
        if not pos.sim_shares:
            continue
        shares = pos.sim_shares
        events.append(
            CashEvent(
                pos.entry_date,
                "entry",
                index,
                pos.ticker,
                -_cents(shares * pos.entry),
            )
        )
        half_day = half_sale_date(pos.notes)
        if half_day is not None:
            events.append(
                CashEvent(
                    half_day,
                    "half",
                    index,
                    pos.ticker,
                    _cents(shares * pos.target / 2.0),
                )
            )
        if pos.status == "Exited" and pos.exit_date and pos.exit_price is not None:
            remaining = 0.5 if half_day is not None else 1.0
            events.append(
                CashEvent(
                    pos.exit_date,
                    "exit",
                    index,
                    pos.ticker,
                    _cents(shares * remaining * pos.exit_price),
                )
            )
    events.sort(key=lambda event: (event.day, _KIND_ORDER[event.kind], event.row_index))
    return events


@dataclass
class LedgerWalk:
    starting_cash: float
    cash: float
    went_negative: bool
    events: list[dict]


def walk_ledger(rows: list[PaperPosition], starting_cash: float) -> LedgerWalk:
    cash = _cents(starting_cash)
    went_negative = False
    recorded: list[dict] = []
    for event in events_for(rows):
        cash += event.amount_cents
        if cash < 0:
            went_negative = True
        recorded.append(
            {
                "date": event.day.isoformat(),
                "kind": event.kind,
                "ticker": event.ticker,
                "row": event.row_index,
                "amount": _dollars(event.amount_cents),
                "cash_after": _dollars(cash),
            }
        )
    return LedgerWalk(
        starting_cash=round(starting_cash, 2),
        cash=_dollars(cash),
        went_negative=went_negative,
        events=recorded,
    )


def candidate_fits(
    accepted: list[PaperPosition],
    candidate: PaperPosition,
    starting_cash: float,
) -> tuple[bool, float]:
    """Whether `candidate` (already carrying sim shares) keeps cash non-negative.

    Returns (fits, cash available just before that entry's cost).
    """
    ordered = sort_paper([*accepted, candidate])
    cash = _cents(starting_cash)
    for event in events_for(ordered):
        row = ordered[event.row_index]
        if event.kind == "entry" and row is candidate:
            available = _dollars(cash)
            return cash + event.amount_cents >= 0, available
        cash += event.amount_cents
    return False, _dollars(cash)


def ledger_document(rows: list[PaperPosition], starting_cash: float) -> dict:
    walked = walk_ledger(sort_paper(rows), starting_cash)
    return {
        "starting_cash": walked.starting_cash,
        "cash": walked.cash,
        "events": walked.events,
    }
