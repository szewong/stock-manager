"""Read-only session checks. They never write the state files."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from src.market_data import MarketData
from src.report import keep_headline, render_intraday, render_market_open
from src.sizing import gap_rule
from src.state import load_fills, load_json, load_papers, load_settings, load_watch


def _flags(root: Path, client: MarketData, session: date) -> list[str]:
    settings = load_settings(root)
    watch = load_watch(root)
    papers = load_papers(root)
    window = int(settings["earnings_filter_calendar_days"])
    flags: list[str] = []
    for row in watch:
        if row.consol_high is None and row.ma50 is None:
            continue
        quote = client.quote(row.ticker)
        if quote.price is None:
            continue
        price = quote.price
        earnings_note = ""
        token = (row.earnings or "").strip()
        if token not in ("", "N/A"):
            try:
                when = date.fromisoformat(token)
            except ValueError:
                when = None
            if when is not None and 0 <= (when - session).days <= window:
                earnings_note = f" Earnings {when.isoformat()} — a trigger would be skipped."
        if row.consol_high and price >= row.consol_high * 0.99:
            flags.append(
                f"{row.ticker} breakout-approaching: price {price:.2f}, consolidation high {row.consol_high:.2f}.{earnings_note}"
            )
        if row.ma50 and row.ma50 <= price <= row.ma50 * 1.01:
            extra = ""
            if price < row.ma50 * (1 + float(settings["pullback_min_separation"])):
                extra = " A close at this level would not flag (minimum separation)."
            flags.append(
                f"{row.ticker} pullback-approaching: price {price:.2f}, MA50 {row.ma50:.2f}.{extra}{earnings_note}"
            )
    for pos in papers:
        if pos.status not in ("Open", "Half sold"):
            continue
        quote = client.quote(pos.ticker)
        if quote.price is None:
            continue
        price = quote.price
        if pos.status == "Open":
            if pos.target * 0.98 <= price < pos.target:
                flags.append(
                    f"{pos.ticker} target-approaching: price {price:.2f}, target {pos.target:.2f}."
                )
            if pos.stop < price <= pos.stop * 1.02:
                flags.append(
                    f"{pos.ticker} stop-approaching: price {price:.2f}, stop {pos.stop:.2f}."
                )
        elif pos.trail is not None and pos.trail < price <= pos.trail * 1.02:
            flags.append(
                f"{pos.ticker} trail-approaching: price {price:.2f}, trail {pos.trail:.2f}."
            )
    return flags


def run_intraday(root: Path, kind: str, session: date, client: MarketData) -> str:
    flags = _flags(root, client, session)
    if not flags:
        return "NO_FLAGS"
    return render_intraday(kind, session, flags)


def _move_line(symbol: str, price: float, prev: float | None, reason: str = "") -> str:
    if prev is None or prev == 0:
        return f"{symbol}: price {price:.2f}; prior close unavailable."
    move = (price - prev) / prev * 100.0
    tail = f" {reason}" if reason else ""
    return f"{symbol}: {move:+.2f}% from the prior close ({prev:.2f} to {price:.2f}).{tail}"


def run_market_open(root: Path, session: date, client: MarketData) -> str:
    settings = load_settings(root)
    watch = load_watch(root)
    papers = load_papers(root)
    fills = load_fills(root)
    dashboard = load_json(root / "data" / "dashboard.json")
    regime = dashboard.get("market_regime") or {}
    qqq = client.quote(settings.get("market_filter_symbol") or "QQQ")
    spx = client.quote("^GSPC")
    tone_bits = []
    if qqq.price is None:
        tone_bits.append("QQQ price unavailable.")
    else:
        tone_bits.append(_move_line("QQQ", qqq.price, qqq.previous_close))
        ma50 = regime.get("qqq_ma50")
        if ma50:
            relation = "above" if qqq.price > ma50 else "not above"
            tone_bits.append(
                f"QQQ {qqq.price:.2f} is {relation} the stored MA50 {float(ma50):.2f} (intraday indication only)."
            )
        else:
            tone_bits.append("Stored QQQ MA50 is blank; the daily check has not recorded it.")
    if spx.price is None:
        tone_bits.append("S&P 500 price unavailable.")
    else:
        tone_bits.append(_move_line("S&P 500", spx.price, spx.previous_close))

    yesterday = session - timedelta(days=1)
    earnings_lines = []
    today_lines = []
    open_names = {pos.ticker for pos in papers if pos.status in ("Open", "Half sold")}
    for row in watch:
        token = (row.earnings or "").strip()
        if token in ("", "N/A"):
            continue
        try:
            when = date.fromisoformat(token)
        except ValueError:
            continue
        quote = client.quote(row.ticker)
        move = ""
        if quote.price is not None and quote.previous_close:
            pct = (quote.price - quote.previous_close) / quote.previous_close * 100.0
            move = f" Session move so far {pct:+.2f}%."
        if when in (yesterday, session):
            held = " Open paper position." if row.ticker in open_names else ""
            earnings_lines.append(
                f"{row.ticker} earnings date {when.isoformat()}.{held}{move} Result figures are not fetched."
            )
        if when == session:
            held = " Open paper position." if row.ticker in open_names else ""
            today_lines.append(
                f"{row.ticker} reports on today's date.{held} Consensus is not fetched."
            )

    position_lines = []
    for pos in papers:
        if pos.status not in ("Open", "Half sold"):
            continue
        quote = client.quote(pos.ticker)
        if quote.price is None:
            position_lines.append(f"{pos.ticker} {pos.status}: price unavailable.")
            continue
        vs = (quote.price - pos.entry) / pos.entry * 100.0
        day = ""
        if quote.previous_close:
            day = f", day move {(quote.price - quote.previous_close) / quote.previous_close * 100.0:+.2f}%"
        level = ""
        if pos.status == "Open":
            if quote.price >= pos.target or quote.price <= pos.stop:
                level = " Price is already through a level; the close still confirms."
            elif abs(quote.price - pos.target) / pos.target <= 0.02 or abs(quote.price - pos.stop) / pos.entry <= 0.02:
                level = " Price is within 2% of a level; the close still confirms."
            level += f" Target {pos.target:.2f}, stop {pos.stop:.2f}."
        elif pos.trail:
            if quote.price <= pos.trail:
                level = " Price is already through the trail; the close still confirms."
            elif abs(quote.price - pos.trail) / pos.trail <= 0.02:
                level = " Price is within 2% of the trail; the close still confirms."
            level += f" Trail {pos.trail:.2f}."
        position_lines.append(
            f"{pos.ticker} {pos.status}: price {quote.price:.2f}{day}, vs entry {vs:.2f}%.{level}"
        )

    mover_rows = []
    for row in watch:
        quote = client.quote(row.ticker)
        if quote.price is None or not quote.previous_close:
            continue
        move = (quote.price - quote.previous_close) / quote.previous_close * 100.0
        if abs(move) < 3.0:
            continue
        flagged = row.pullback == "Yes" or row.consolidating == "Yes"
        mover_rows.append((0 if flagged else 1, -abs(move), row.ticker, move))
    mover_rows.sort()
    mover_lines = [
        f"{ticker}: {move:+.2f}% so far."
        for _, _, ticker, move in mover_rows[:8]
    ]

    pending = []
    budget = float(settings["account_size_usd"]) * float(settings["risk_pct_per_trade"])
    start = settings["test_round_start"]
    for pos in papers:
        if pos.status != "Open" or not pos.shares or pos.entry_date < start:
            continue
        if "gap rule" in (pos.notes or ""):
            continue
        if any(fill.ticker == pos.ticker and fill.side == "Buy" and fill.day and fill.day >= pos.entry_date for fill in fills):
            continue
        quote = client.quote(pos.ticker)
        operative = pos.shares
        digits = "".join(ch if ch.isdigit() else " " for ch in (pos.buy_decision or ""))
        numbers = [int(part) for part in digits.split() if part]
        if numbers:
            operative = numbers[0]
        stop = pos.original_stop()
        if quote.price is None:
            pending.append(
                f"{pos.ticker}: plan size {operative} shares, signal {pos.entry:.2f}, stop {stop:.2f}, target {pos.target:.2f}. Current price unavailable, so the gap rule is not applied."
            )
            continue
        verdict = gap_rule(quote.price, stop, pos.target, operative, budget)
        pending.append(
            f"{pos.ticker}: plan size {operative} shares, signal {pos.entry:.2f}, stop {stop:.2f}, "
            f"target {pos.target:.2f}, full-size limit {verdict.stop_plus:.2f}, "
            f"midpoint {verdict.midpoint:.2f}, binding maximum {verdict.binding_max:.2f}. "
            f"At {quote.price:.2f}: {verdict.detail}."
        )
    cost = 0.0
    priced = True
    for pos in papers:
        if pos.status != "Open" or not pos.shares or pos.entry_date < start:
            continue
        if "gap rule" in (pos.notes or ""):
            continue
        if any(fill.ticker == pos.ticker and fill.side == "Buy" and fill.day and fill.day >= pos.entry_date for fill in fills):
            continue
        quote = client.quote(pos.ticker)
        if quote.price is None:
            priced = False
            break
        cost += pos.shares * quote.price
    cash_line = ""
    if pending:
        cash = settings.get("ib_cash_available_usd")
        as_of = settings.get("ib_cash_as_of") or "no as-of date"
        if not priced:
            cash_line = "Combined pending cost was not computed because a price is missing."
        elif cash is None:
            cash_line = (
                f"Combined pending cost at plan size and current prices: US${cost:.2f}. "
                "IB cash has not been reported."
            )
        else:
            cash_line = (
                f"Combined pending cost at plan size and current prices: US${cost:.2f}. "
                f"IB cash US${float(cash):.2f} as of {as_of}."
            )

    news_line = "No headlines kept."
    symbols = [pos.ticker for pos in papers if pos.status in ("Open", "Half sold")][:5]
    if symbols:
        items, err = client.news(symbols)
        kept = [item for item in items if keep_headline(item.title)][:5]
        if kept:
            news_line = " ".join(
                f"{item.symbol}: {item.title} — {item.source}" + (f" ({item.link})" if item.link else "")
                for item in kept
            )
        elif err:
            news_line = "News fetch failed; nothing invented."

    return render_market_open(
        {
            "session": session,
            "tone": " ".join(tone_bits),
            "earnings": earnings_lines,
            "positions": position_lines,
            "movers": mover_lines,
            "today_earnings": today_lines,
            "pending": pending,
            "cash_line": cash_line,
            "news_line": news_line,
        }
    )
