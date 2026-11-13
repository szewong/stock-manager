"""Sim cash: half sales, then exits, then entries, on the same date."""

from datetime import date

from src.ledger import candidate_fits, walk_ledger
from src.positions import PaperPosition, sort_paper


def _row(ticker, status, entry_date, entry, stop, target, sim_shares, notes="", exit_date=None, exit_price=None):
    return PaperPosition(
        ticker=ticker,
        last_close=exit_price or entry,
        live_price=None if status == "Exited" else entry,
        vs_entry_pct=0,
        setup="Breakout",
        entry_date=entry_date,
        entry=entry,
        stop=stop,
        target=target,
        trail=None,
        status=status,
        exit_date=exit_date,
        exit_price=exit_price,
        blended_pct=None,
        shares=None,
        notes=notes,
        sim_shares=sim_shares,
        sim_result=None,
    )


def test_same_day_proceeds_fund_a_later_entry():
    day = date(2026, 11, 20)
    exiting = _row(
        "OLD",
        "Exited",
        date(2026, 11, 18),
        10,
        8,
        14,
        10,
        notes="Half at target on 2026-11-20.",
        exit_date=day,
        exit_price=12,
    )
    # Prior entry cost was 100. Same-day half proceeds are 70 and the exit adds 60.
    newbie = _row("NEW", "Open", day, 50, 40, 70, 2, notes="Original stop 40.00.")
    # New cost is 100. It fits only because same-day proceeds are applied first.
    ordered = sort_paper([newbie, exiting])
    walked = walk_ledger(ordered, 100)
    assert not walked.went_negative
    kinds = [event["kind"] for event in walked.events if event["date"] == day.isoformat()]
    assert kinds == ["half", "exit", "entry"]
    assert walked.cash == 30


def test_second_entry_is_skipped_when_cash_runs_out():
    day = date(2026, 11, 20)
    first = _row("AAA", "Open", day, 80, 70, 100, 1, notes="Original stop 70.00.")
    second = _row("BBB", "Open", day, 80, 70, 100, 1, notes="Original stop 70.00.")
    assert candidate_fits([], first, 100)[0]
    assert not candidate_fits([first], second, 100)[0]
