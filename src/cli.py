"""Command line for the stock watchlist record.

    python -m src.cli after-close
    python -m src.cli midday
    python -m src.cli late
    python -m src.cli market-open
    python -m src.cli health-check
    python -m src.cli reconcile <statement-file>
    python -m src.cli watchlist-review
    python -m src.cli add-ticker <SYM> <sector>
    python -m src.cli record-fill --date ... --ticker ... --side Buy --shares N --price P
    python -m src.cli is-trading-day
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, time
from pathlib import Path

from src.calendar_nyse import is_trading_day, last_completed_session, now_et
from src.engine import add_ticker, run_after_close
from src.fills import record_fill
from src.health import audit
from src.intraday import run_intraday, run_market_open
from src.market_data import YFinanceClient
from src.reconcile import reconcile_statement
from src.report import render_health
from src.review import run_review
from src.state import repo_root


def _write_report(root: Path, name: str, day: date, text: str) -> None:
    path = root / "reports" / f"{day.isoformat()}-{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _session_from_args(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    after = sub.add_parser("after-close", help="evaluate the completed session and write the daily report")
    after.add_argument("--session-date", help="YYYY-MM-DD completed session")

    sub.add_parser("midday", help="read-only heads-up; prints NO_FLAGS when nothing is close")
    sub.add_parser("late", help="read-only late heads-up; prints NO_FLAGS when nothing is close")
    sub.add_parser("market-open", help="read-only morning briefing")
    sub.add_parser("health-check", help="audit files and change nothing")

    recon = sub.add_parser("reconcile", help="compare a broker activity CSV with the trade log")
    recon.add_argument("statement_file")

    sub.add_parser("watchlist-review", help="propose membership changes without editing the list")

    add = sub.add_parser("add-ticker", help="vet one symbol and append it when prices are available")
    add.add_argument("symbol")
    add.add_argument("sector")
    add.add_argument("--session-date", help="YYYY-MM-DD completed session to treat as the check date")

    fill = sub.add_parser("record-fill", help="append one fill that already happened")
    fill.add_argument("--date", required=True)
    fill.add_argument("--ticker", required=True)
    fill.add_argument("--side", required=True, choices=["Buy", "Sell"])
    fill.add_argument("--shares", required=True, type=int)
    fill.add_argument("--price", required=True, type=float)
    fill.add_argument("--commission", type=float, default=0.0)
    fill.add_argument("--other-costs", type=float, default=0.0)
    fill.add_argument("--setup", default="")
    fill.add_argument("--notes", default="")
    fill.add_argument("--signal-price", type=float, default=None)

    sub.add_parser("is-trading-day", help="exit 0 on an NYSE session date in ET, else 1")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = repo_root()
    moment = now_et()
    command = args.command

    if command == "is-trading-day":
        day = moment.date()
        if is_trading_day(day):
            print(f"{day.isoformat()} trading-day")
            return 0
        print(f"{day.isoformat()} not-trading-day")
        return 1

    if command in {"after-close", "midday", "late", "market-open"}:
        explicit = _session_from_args(getattr(args, "session_date", None))
        if explicit is None and not is_trading_day(moment.date()):
            return 0
        if command == "after-close" and explicit is None and moment.time() < time(16, 5):
            print("Session is still open; after-close does not run before the close.")
            return 0
        if explicit is not None and not is_trading_day(explicit):
            print(f"{explicit.isoformat()} is not an NYSE session.")
            return 0
        session = explicit or (moment.date() if command != "after-close" else moment.date())
        client = YFinanceClient()
        if command == "after-close":
            report = run_after_close(root, session, client)
            sys.stdout.write(report if report.endswith("\n") else report + "\n")
            return 0
        if command == "market-open":
            report = run_market_open(root, session, client)
            _write_report(root, "market-open", session, report)
            sys.stdout.write(report if report.endswith("\n") else report + "\n")
            return 0
        text = run_intraday(root, command, session, client)
        if text == "NO_FLAGS":
            print("NO_FLAGS")
            return 0
        _write_report(root, command, session, text)
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return 0

    if command == "health-check":
        failures, counts = audit(root, moment.date())
        text = render_health(moment.date(), failures, counts)
        _write_report(root, "health-check", moment.date(), text)
        sys.stdout.write(text)
        return 0

    if command == "watchlist-review":
        text = run_review(root, moment.date())
        _write_report(root, "watchlist-review", moment.date(), text)
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return 0

    if command == "reconcile":
        text = reconcile_statement(root, Path(args.statement_file), moment.date())
        _write_report(root, "reconcile", moment.date(), text)
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return 0

    if command == "add-ticker":
        explicit = _session_from_args(args.session_date)
        session = explicit or last_completed_session(moment)
        if explicit is not None and not is_trading_day(explicit):
            print(f"{explicit.isoformat()} is not an NYSE session. Nothing was added.")
            return 0
        text = add_ticker(root, args.symbol, args.sector, YFinanceClient(), session)
        print(text)
        return 0

    if command == "record-fill":
        text = record_fill(
            root,
            day=date.fromisoformat(args.date),
            ticker=args.ticker,
            side=args.side,
            shares=args.shares,
            price=args.price,
            commission=args.commission,
            other_costs=args.other_costs,
            setup=args.setup,
            notes=args.notes,
            signal_price=args.signal_price,
            client=YFinanceClient(),
        )
        print(text)
        return 0

    parser.error(f"unknown command {command}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
