"""After-close engine and the add-ticker path. The trade log is never written here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ledger import candidate_fits, ledger_document
from src.market_data import MarketData, bars_for_session
from src.positions import (
    PaperPosition,
    apply_session,
    last_base_low,
    last_trigger_date,
    money,
    sort_paper,
    target_price,
)
from src.report import build_summary, keep_headline, render_after_close
from src.rules import (
    breakout_invalidated,
    choose_setup,
    compute_indicators,
    earnings_blocks,
    evaluate_breakout,
    evaluate_pullback,
    pullback_invalidated,
    sessions_after,
)
from src.sizing import (
    GuardrailState,
    capital_cap_note,
    circuit_breaker_limit,
    circuit_breaker_tripped,
    guardrail_note,
    plan_shares,
    sim_share_size,
    trim_note,
)
from src.state import (
    load_fills,
    load_papers,
    load_settings,
    load_watch,
    rebuild_real,
    real_total_pnl,
    save_papers,
    save_radar,
    save_real,
    save_watch,
    write_json,
    WatchRow,
)
from src.textutil import append_note
from src.views import build_dashboard, build_radar


@dataclass
class _Signal:
    ticker: str
    setup: str
    entry: float
    stop: float
    ma20: float | None
    base_high: float | None
    base_low: float | None


def _guardrail(rows: list[PaperPosition], settings: dict) -> GuardrailState:
    start: date = settings["test_round_start"]
    count = 0
    risk = 0.0
    for pos in rows:
        if pos.status not in ("Open", "Half sold"):
            continue
        if pos.entry_date < start or not pos.shares:
            continue
        count += 1
        risk += pos.shares * (pos.entry - pos.stop)
    return GuardrailState(count, risk)


def _price_fields(row: WatchRow, indicators, session: date) -> None:
    last = indicators
    row.ma50 = None if last.ma50 is None else money(last.ma50)
    row.ma100 = None if last.ma100 is None else money(last.ma100)
    row.consol_high = None if last.consol_high is None else money(last.consol_high)
    row.consol_low = None if last.consol_low is None else money(last.consol_low)
    row.range_pct_points = None if last.range_pct is None else last.range_pct * 100.0
    row.consolidating = "Yes" if last.consolidating else "No"
    if last.volume_unknown or last.volume_ratio is None:
        row.volume_vs_avg = "Unknown"
    else:
        row.volume_vs_avg = f"{last.volume_ratio:.2f}"
    row.last_check = session


def _refresh_earnings(row: WatchRow, client: MarketData, session: date, quote_type: str | None) -> None:
    token = (row.earnings or "").strip()
    needs = token == ""
    if token and token.upper() != "N/A":
        try:
            if date.fromisoformat(token) < session:
                needs = True
        except ValueError:
            needs = True
    if not needs:
        return
    found = client.earnings_date(row.ticker, quote_type)
    if found:
        row.earnings = found
        return
    row.notes = append_note(row.notes, "earnings date unknown")


def _sizing_notes(
    *,
    entry: float,
    stop: float,
    settings: dict,
    session: date,
    rows: list[PaperPosition],
    pnl: float | None,
) -> tuple[int | None, str]:
    start: date = settings["test_round_start"]
    if session < start:
        return None, ""
    if pnl is None:
        return None, "Circuit breaker not evaluated — a live price is missing; real plan left blank."
    limit = circuit_breaker_limit(
        float(settings["account_size_usd"]), float(settings["circuit_breaker_pct"])
    )
    if circuit_breaker_tripped(pnl, limit):
        return None, "Circuit breaker — paper only"
    plan = plan_shares(
        float(settings["account_size_usd"]),
        float(settings["risk_pct_per_trade"]),
        entry,
        stop,
    )
    if plan.shares is None:
        return None, plan.note or ""
    state = _guardrail(rows, settings)
    blocked = guardrail_note(
        state,
        plan.planned_risk,
        account=float(settings["account_size_usd"]),
        max_positions=int(settings["max_open_test_positions"]),
        max_total_risk_pct=float(settings["max_total_open_risk_pct"]),
    )
    if blocked:
        return None, blocked
    return plan.shares, ""


def _apply_sim(pos: PaperPosition, accepted: list[PaperPosition], settings: dict) -> None:
    start: date = settings["test_round_start"]
    if pos.entry_date < start:
        pos.sim_shares = None
        pos.sim_result = None
        return
    size = sim_share_size(
        float(settings["sim_account_size_usd"]),
        float(settings["sim_risk_pct_per_trade"]),
        float(settings["sim_concentration_ceiling_pct"]),
        pos.entry,
        pos.original_stop(),
    )
    if size.shares <= 0:
        pos.sim_shares = None
        pos.sim_result = None
        pos.notes = append_note(pos.notes, "Sim skipped — size rounded to 0.")
        return
    pos.sim_shares = size.shares
    if pos.status == "Exited":
        from src.positions import blended_fraction, sim_result_usd

        fraction = blended_fraction(
            pos.entry, pos.exit_price or pos.entry, pos.target, pos.had_half_sale()
        )
        pos.sim_result = sim_result_usd(pos.sim_shares, pos.entry, fraction)
    fits, available = candidate_fits(
        accepted, pos, float(settings["sim_account_size_usd"])
    )
    if not fits:
        cost = pos.sim_shares * pos.entry
        pos.sim_shares = None
        pos.sim_result = None
        pos.notes = append_note(pos.notes, capital_cap_note(cost, available))
        return
    if size.trimmed:
        pos.notes = append_note(
            pos.notes, trim_note(size, float(settings["sim_concentration_ceiling_pct"]))
        )


def _event_line(pos: PaperPosition, sizing_note: str) -> str:
    shares = "blank" if pos.shares is None else str(pos.shares)
    if sizing_note and pos.shares is None:
        shares = f"blank ({sizing_note})"
    if pos.sim_shares is None and "Sim skipped — capital cap" in (pos.notes or ""):
        sim = "blank (capital cap)"
    elif pos.sim_shares is None:
        sim = "blank"
    else:
        sim = str(pos.sim_shares)
    return (
        f"{pos.ticker} {pos.setup.lower()}: entry {pos.entry:.2f}, stop {pos.original_stop():.2f}, "
        f"plan shares {shares}, sim shares {sim}, target {pos.target:.2f}."
    )


def _paper_lines(pos: PaperPosition, session: date) -> tuple[str | None, str | None]:
    """Return (status-change line or None, resting line or None)."""
    half_today = f"Half at target on {session.isoformat()}" in (pos.notes or "")
    exited_today = pos.status == "Exited" and pos.exit_date == session
    if exited_today:
        reason = "the MA20 trail" if "close below MA20" in (pos.notes or "") else "the stop"
        return (
            f"{pos.ticker} Exited: close {pos.exit_price:.2f} under {reason}; blended result {pos.blended_pct:.2f}%.",
            None,
        )
    if pos.status not in ("Open", "Half sold"):
        return None, None
    if pos.status == "Half sold":
        trail = f"{pos.trail:.2f}" if pos.trail is not None else "n/a"
        prefix = (
            f"{pos.ticker} Half sold: recorded stop is the entry {pos.entry:.2f}; trail {trail}."
        )
        if half_today:
            prefix = (
                f"{pos.ticker} Half sold: the session high reached target {pos.target:.2f}; "
                f"recorded stop is now the entry {pos.entry:.2f}; trail {trail}."
            )
        line = (
            f"{prefix} Close {pos.last_close:.2f}, vs entry {pos.vs_entry_pct:.2f}%."
        )
        return (line, None) if half_today else (None, line)
    close = pos.last_close or pos.entry
    to_target = (pos.target - close) / close * 100.0 if close else 0.0
    to_stop = (close - pos.stop) / close * 100.0 if close else 0.0
    line = (
        f"{pos.ticker} Open: close {close:.2f}, vs entry {(pos.vs_entry_pct or 0):.2f}%, "
        f"target {pos.target:.2f} ({to_target:.2f}% from the close), "
        f"stop {pos.stop:.2f} ({to_stop:.2f}% from the close)."
    )
    return None, line


def _action_lines(
    pos: PaperPosition,
    session: date,
    settings: dict,
    real_net: dict[str, int],
) -> list[str]:
    lines: list[str] = []
    held = real_net.get(pos.ticker, 0)
    if (
        pos.entry_date == session
        and pos.shares
        and pos.status in ("Open", "Half sold")
    ):
        from src.sizing import gap_rule

        stop = pos.original_stop()
        budget = float(settings["account_size_usd"]) * float(settings["risk_pct_per_trade"])
        verdict = gap_rule(pos.entry, stop, pos.target, pos.shares, budget)
        partial = (
            "The documented partial at the target is the whole position, because the plan is 1 share."
            if pos.shares == 1
            else f"The documented partial at the target is {pos.shares // 2} shares."
        )
        lines.append(
            (
                f"{pos.ticker}: plan size {pos.shares} shares, signal price {pos.entry:.2f}, "
                f"stop {stop:.2f}, target {pos.target:.2f}. "
                f"Full planned size stays within the risk budget at or under {verdict.stop_plus:.2f}. "
                f"The gap rule leaves the plan unused above the stop-target midpoint {verdict.midpoint:.2f}, "
                "at or below the stop, or when one share would risk more than the trade budget. "
                "Between the full-size limit and that midpoint the share count is cut. "
                f"{partial} "
                "A GTC limit at the target is the documented way to carry out the planned target exit. "
                "Fills and skips are recorded when they are reported."
            )
        )
    if pos.status == "Exited" and pos.exit_date == session and held > 0:
        lines.append(
            (
                f"{pos.ticker}: the paper row exited at {pos.exit_price:.2f}. "
                f"The pre-agreed plan for a holding of {held} shares is an exit at the next open, "
                "and cancelling a standing GTC in that same session. "
                "The order itself is placed by the account holder."
            )
        )
    if (
        pos.status == "Half sold"
        and f"Half at target on {session.isoformat()}" in (pos.notes or "")
        and held > 0
        and pos.entry_date != session
    ):
        lines.append(
            (
                f"{pos.ticker}: the paper row reached its target this session. "
                "A GTC limit at the target is the documented way to carry out the planned partial exit. "
                "Report the fill if one occurred."
            )
        )
    return lines


def _theme_lines(watch: list[WatchRow], moves: dict[str, float]) -> list[str]:
    grouped: dict[str, list[tuple[str, float]]] = {}
    for row in watch:
        if row.ticker not in moves:
            continue
        grouped.setdefault(row.theme or "Unspecified", []).append((row.ticker, moves[row.ticker]))
    ranked = []
    for theme, pairs in grouped.items():
        avg = sum(value for _, value in pairs) / len(pairs)
        ranked.append((avg, theme, pairs))
    ranked.sort(key=lambda item: item[0], reverse=True)
    lines = []
    for avg, theme, pairs in ranked:
        risers = sum(1 for _, value in pairs if value > 0)
        fallers = sum(1 for _, value in pairs if value < 0)
        best = max(pairs, key=lambda item: item[1])
        worst = min(pairs, key=lambda item: item[1])
        lines.append(
            f"{theme}: {len(pairs)} names, {risers} up / {fallers} down, "
            f"average move {avg:.2f}%, best {best[0]} {best[1]:+.2f}%, worst {worst[0]} {worst[1]:+.2f}%."
        )
    return lines


def _persist(
    root: Path,
    settings: dict,
    watch: list[WatchRow],
    papers: list[PaperPosition],
    *,
    session: date,
    qqq_close: float | None,
    qqq_ma50: float | None,
    market_filter: str | None,
) -> dict:
    fills = load_fills(root)
    prices: dict[str, float | None] = {}
    for row in watch:
        if row.last_price is not None:
            prices[row.ticker] = row.last_price
    for pos in papers:
        if pos.last_close is not None:
            prices.setdefault(pos.ticker, pos.last_close)
    real_rows = rebuild_real(fills, prices)
    radar = build_radar(
        watch, papers, session, int(settings.get("earnings_radar_calendar_days") or 14)
    )
    dashboard = build_dashboard(
        settings,
        papers,
        fills,
        radar,
        qqq_close=qqq_close,
        qqq_ma50=qqq_ma50,
        market_filter=market_filter,
        last_check=session.isoformat(),
        ib_cash=settings.get("ib_cash_available_usd"),
        ib_as_of=settings.get("ib_cash_as_of"),
    )
    summary = build_summary(dashboard, papers, watch, radar)
    ledger = ledger_document(papers, float(settings["sim_account_size_usd"]))
    save_watch(root, watch)
    save_papers(root, papers)
    save_real(root, real_rows)
    save_radar(root, radar)
    write_json(root / "data" / "dashboard.json", dashboard)
    write_json(root / "data" / "sim_ledger.json", ledger)
    (root / "data" / "summary.md").write_text(summary, encoding="utf-8")
    return dashboard


def run_after_close(root: Path, session: date, client: MarketData) -> str:
    settings = load_settings(root)
    sessions = int(settings["breakout_sessions"])
    vol_sessions = int(settings["breakout_volume_avg_sessions"])
    range_limit = float(settings["breakout_range_pct"])
    watch = load_watch(root)
    papers = load_papers(root)
    fills = load_fills(root)

    symbols = sorted(
        {row.ticker for row in watch}
        | {pos.ticker for pos in papers if pos.status in ("Open", "Half sold")}
        | {settings.get("market_filter_symbol") or "QQQ"}
    )
    histories = {}
    meta = {}
    errors: dict[str, str] = {}
    for symbol in symbols:
        result = client.history(symbol)
        meta[symbol] = result
        trimmed = bars_for_session(result.bars, session) if result.bars else None
        if trimmed is None:
            errors[symbol] = result.error or f"no completed bar for {session.isoformat()}"
        else:
            histories[symbol] = trimmed

    qqq_symbol = settings.get("market_filter_symbol") or "QQQ"
    qqq_close = None
    qqq_ma50 = None
    qqq_above: bool | None = None
    if qqq_symbol in histories:
        qqq_ind = compute_indicators(
            histories[qqq_symbol],
            sessions=sessions,
            volume_avg_sessions=vol_sessions,
            range_limit=range_limit,
        )
        qqq_close = histories[qqq_symbol][-1].close
        qqq_ma50 = qqq_ind.ma50
        if qqq_ma50 is None:
            qqq_above = None
        else:
            qqq_above = qqq_close > qqq_ma50
    market_filter = {True: "Pass", False: "Fail"}.get(qqq_above) if qqq_above is not None else "Unavailable"

    data_quality: list[str] = []
    if qqq_above is None:
        data_quality.append(
            f"{qqq_symbol}: no usable completed session, so the breakout filter did not flag new breakouts."
        )

    for pos in papers:
        if pos.status not in ("Open", "Half sold"):
            continue
        bars = histories.get(pos.ticker)
        if not bars:
            data_quality.append(
                f"{pos.ticker}: open paper row left unchanged ({errors.get(pos.ticker, 'no bar')})."
            )
            continue
        indicators = compute_indicators(
            bars, sessions=sessions, volume_avg_sessions=vol_sessions, range_limit=range_limit
        )
        apply_session(pos, bars[-1], indicators.ma20)

    events: list[str] = []
    near: list[str] = []
    signals: list[_Signal] = []
    unknown_volume = 0
    moves: dict[str, float] = {}

    for row in watch:
        bars = histories.get(row.ticker)
        if not bars:
            data_quality.append(
                f"{row.ticker}: series does not include {session.isoformat()}; row left unchanged."
            )
            continue
        indicators = compute_indicators(
            bars, sessions=sessions, volume_avg_sessions=vol_sessions, range_limit=range_limit
        )
        if indicators.daily_move_pct is not None:
            moves[row.ticker] = indicators.daily_move_pct
        quote_type = meta[row.ticker].quote_type if row.ticker in meta else None
        _refresh_earnings(row, client, session, quote_type)
        close = bars[-1].close
        row.last_price = money(close)

        if row.trigger == "Yes":
            trigger_day = last_trigger_date(row.notes)
            base_low = last_base_low(row.notes)
            if trigger_day and base_low is not None:
                after = sessions_after(bars, trigger_day, session)
                if breakout_invalidated(close=close, base_low=base_low, sessions_after_trigger=after):
                    row.trigger = "Failed"
                    row.notes = append_note(
                        row.notes,
                        f"Breakout failed {session.isoformat()} close under base low {base_low:.2f}.",
                    )
                    events.append(
                        f"{row.ticker} breakout flag Failed: close {close:.2f} under base low {base_low:.2f} within 5 sessions."
                    )
        if pullback_invalidated(row.pullback, close, indicators.ma50):
            row.pullback = "Failed"
            row.notes = append_note(
                row.notes, f"Pullback failed {session.isoformat()} close under MA50."
            )
            events.append(
                f"{row.ticker} pullback flag Failed: close {close:.2f} under MA50 {indicators.ma50:.2f}."
            )

        breakout = evaluate_breakout(
            bars,
            indicators,
            qqq_above_ma50=qqq_above,
            volume_multiple=float(settings["breakout_volume_multiple"]),
        )
        pullback = evaluate_pullback(
            bars,
            indicators.ma50,
            touch_band=float(settings["pullback_touch_band"]),
            min_separation=float(settings["pullback_min_separation"]),
            lookback=int(settings["pullback_sessions"]),
        )
        new_breakout = False
        new_pullback = False
        if breakout.flag:
            skip, why = earnings_blocks(
                row.earnings or None,
                session,
                window_days=int(settings["earnings_filter_calendar_days"]),
            )
            if why == "earnings date unknown":
                row.notes = append_note(row.notes, "earnings date unknown")
            if skip:
                events.append(f"{row.ticker} breakout not flagged: {why}.")
            else:
                if row.trigger != "Yes":
                    new_breakout = True
                row.trigger = "Yes"
        elif breakout.market_filter_block:
            near.append(f"{row.ticker} breakout blocked: QQQ is not above its MA50.")
        elif breakout.unverifiable_volume:
            data_quality.append(
                f"{row.ticker}: volume unavailable, so an otherwise valid breakout was not flagged."
            )
        elif indicators.volume_unknown:
            unknown_volume += 1

        if pullback.flag:
            skip, why = earnings_blocks(
                row.earnings or None,
                session,
                window_days=int(settings["earnings_filter_calendar_days"]),
            )
            if why == "earnings date unknown":
                row.notes = append_note(row.notes, "earnings date unknown")
            if skip:
                events.append(f"{row.ticker} pullback not flagged: {why}.")
            else:
                if row.pullback != "Yes":
                    new_pullback = True
                row.pullback = "Yes"
        elif pullback.near_miss:
            near.append(f"{row.ticker} pullback not flagged: {pullback.reason}.")

        if new_breakout or new_pullback:
            setup = choose_setup(new_breakout, new_pullback)
            stop = indicators.base_low if setup == "Breakout" else indicators.ma50
            assert stop is not None
            note = f"Triggered {session.isoformat()}."
            if new_breakout and indicators.base_high is not None and indicators.base_low is not None:
                note += (
                    f" Base high {indicators.base_high:.2f}. Base low {indicators.base_low:.2f}."
                )
            note += f" Original stop {stop:.2f}."
            row.notes = append_note(row.notes, note)
            row.stop = money(stop)
            signals.append(
                _Signal(
                    ticker=row.ticker,
                    setup=setup,
                    entry=close,
                    stop=float(stop),
                    ma20=indicators.ma20,
                    base_high=indicators.base_high,
                    base_low=indicators.base_low,
                )
            )
        _price_fields(row, indicators, session)
        row.recompute_distances()

    prices = {symbol: bars[-1].close for symbol, bars in histories.items()}
    for fill in fills:
        prices.setdefault(fill.ticker, None)
    # Closed real rows do not need a price. Open rows do.
    provisional = rebuild_real(fills, {k: v for k, v in prices.items() if v is not None})
    missing_live = [row.ticker for row in provisional if row.net_shares > 0 and row.total is None]
    if missing_live:
        for ticker in missing_live:
            if ticker not in errors:
                data_quality.append(
                    f"{ticker}: real-position price missing, so the circuit breaker was not evaluated."
                )
        pnl = None
    else:
        pnl = real_total_pnl(provisional)

    signals.sort(key=lambda item: item.ticker)
    accepted = list(papers)
    for signal in signals:
        shares, sizing_note = _sizing_notes(
            entry=money(signal.entry),
            stop=money(signal.stop),
            settings=settings,
            session=session,
            rows=accepted,
            pnl=pnl,
        )
        notes = (
            f"Triggered {session.isoformat()}. Original stop {money(signal.stop):.2f}."
        )
        if signal.setup == "Breakout" and signal.base_high is not None and signal.base_low is not None:
            notes = (
                f"Triggered {session.isoformat()}. Base high {signal.base_high:.2f}. "
                f"Base low {signal.base_low:.2f}. Original stop {money(signal.stop):.2f}."
            )
        if sizing_note:
            notes = append_note(notes, sizing_note)
        pos = PaperPosition(
            ticker=signal.ticker,
            last_close=money(signal.entry),
            live_price=money(signal.entry),
            vs_entry_pct=0.0,
            setup=signal.setup,
            entry_date=session,
            entry=money(signal.entry),
            stop=money(signal.stop),
            target=target_price(money(signal.entry), money(signal.stop), float(settings["profit_target_r"])),
            trail=None if signal.ma20 is None else money(signal.ma20),
            status="Open",
            exit_date=None,
            exit_price=None,
            blended_pct=None,
            shares=shares,
            notes=notes,
            sim_shares=None,
            sim_result=None,
            buy_decision="",
        )
        bars = histories[signal.ticker]
        indicators = compute_indicators(
            bars, sessions=sessions, volume_avg_sessions=vol_sessions, range_limit=range_limit
        )
        apply_session(pos, bars[-1], indicators.ma20)
        _apply_sim(pos, accepted, settings)
        for watch_row in watch:
            if watch_row.ticker == signal.ticker:
                watch_row.shares = pos.shares
                watch_row.stop = pos.original_stop()
                if sizing_note:
                    watch_row.notes = append_note(watch_row.notes, sizing_note)
        accepted.append(pos)
        events.append(_event_line(pos, sizing_note))

    nudges: list[str] = []
    for pos in accepted:
        if pos.entry_date < settings["test_round_start"]:
            continue
        if not pos.shares or pos.status not in ("Open", "Half sold"):
            continue
        if pos.entry_date >= session:
            continue
        if "Reconciliation nudge sent" in (pos.notes or ""):
            continue
        if "gap rule" in (pos.notes or ""):
            continue
        matched = any(
            fill.ticker == pos.ticker and fill.side == "Buy" and fill.day and fill.day >= pos.entry_date
            for fill in fills
        )
        if matched:
            continue
        pos.notes = append_note(pos.notes, f"Reconciliation nudge sent {session.isoformat()}.")
        nudges.append(
            f"{pos.ticker} sized {pos.entry_date.isoformat()} — no matching trade-log entry found. "
            "Report the fill to log it, or say the plan was skipped and the paper row can be voided."
        )

    papers_out = sort_paper(accepted)
    real_net = {row.ticker: row.net_shares for row in provisional}
    actions: list[str] = []
    status_changes: list[str] = []
    open_lines: list[str] = []
    for pos in papers_out:
        actions.extend(_action_lines(pos, session, settings, real_net))
        change, resting = _paper_lines(pos, session)
        if change:
            status_changes.append(change)
        elif resting:
            open_lines.append(resting)

    dashboard = _persist(
        root,
        settings,
        watch,
        papers_out,
        session=session,
        qqq_close=qqq_close,
        qqq_ma50=qqq_ma50,
        market_filter=market_filter if market_filter != "Unavailable" else None,
    )
    # Keep the explicit Unavailable string in the report even when the file stores null.
    regime = dict(dashboard["market_regime"])
    if market_filter == "Unavailable":
        regime["market_filter"] = "Unavailable"

    headlines = []
    news_symbols = []
    for pos in papers_out:
        if pos.status in ("Open", "Half sold"):
            news_symbols.append(pos.ticker)
    for row in watch:
        token = (row.earnings or "").strip()
        move = abs(moves.get(row.ticker, 0.0))
        soon = False
        if token not in ("", "N/A"):
            try:
                soon = 0 <= (date.fromisoformat(token) - session).days <= 3
            except ValueError:
                soon = False
        if soon or move >= 4.0:
            news_symbols.append(row.ticker)
    ordered_symbols = []
    for symbol in news_symbols:
        if symbol not in ordered_symbols:
            ordered_symbols.append(symbol)
    news_line = "No material headlines kept."
    if ordered_symbols:
        items, news_error = client.news(ordered_symbols[:8])
        kept = [item for item in items if keep_headline(item.title)][:8]
        if kept:
            bits = []
            for item in kept:
                link = f" ({item.link})" if item.link else ""
                bits.append(f"{item.symbol}: {item.title} — {item.source}{link}")
            news_line = " ".join(bits)
        elif news_error:
            news_line = "News fetch failed; nothing invented."

    volume_note = ""
    if unknown_volume and not any("volume unavailable" in line for line in data_quality):
        volume_note = f"Volume was unavailable for {unknown_volume} names; that did not change a flag."

    model = {
        "session": session,
        "actions": actions,
        "regime": regime,
        "events": events,
        "status_changes": status_changes,
        "open_lines": open_lines,
        "sim": dashboard["sim_portfolio"],
        "news_line": news_line,
        "themes": _theme_lines(watch, moves),
        "watch_state": {
            "updated": sum(1 for row in watch if row.last_check == session),
            "pullback_yes": sum(1 for row in watch if row.pullback == "Yes"),
            "consolidating_yes": sum(1 for row in watch if row.consolidating == "Yes"),
        },
        "near_misses": near,
        "radar": dashboard["earnings_radar"],
        "nudges": nudges,
        "data_quality": data_quality,
        "volume_note": volume_note,
        "updated_files": [
            "data/watchlist.csv",
            "data/paper_positions.csv",
            "data/real_positions.csv",
            "data/dashboard.json",
            "data/summary.md",
            "data/earnings_radar.csv",
            "data/sim_ledger.json",
            f"reports/{session.isoformat()}-after-close.md",
        ],
    }
    report = render_after_close(model)
    report_path = root / "reports" / f"{session.isoformat()}-after-close.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report


def add_ticker(root: Path, symbol: str, sector: str, client: MarketData, session: date) -> str:
    symbol = symbol.strip().upper()
    sector = " ".join(sector.split())
    if not symbol or not sector:
        raise ValueError("add-ticker needs a symbol and a sector")
    settings = load_settings(root)
    watch = load_watch(root)
    if any(row.ticker == symbol for row in watch):
        return f"{symbol} is already on the watchlist. Nothing changed."
    result = client.history(symbol)
    bars = bars_for_session(result.bars, session) if result.bars else None
    if bars is None:
        detail = result.error or f"no completed bar for {session.isoformat()}"
        return f"{symbol} was not added. Price history unavailable ({detail}). Nothing was invented."

    sessions = int(settings["breakout_sessions"])
    vol_sessions = int(settings["breakout_volume_avg_sessions"])
    range_limit = float(settings["breakout_range_pct"])
    indicators = compute_indicators(
        bars, sessions=sessions, volume_avg_sessions=vol_sessions, range_limit=range_limit
    )
    qqq_symbol = settings.get("market_filter_symbol") or "QQQ"
    qqq = client.history(qqq_symbol)
    qqq_bars = bars_for_session(qqq.bars, session) if qqq.bars else None
    qqq_above: bool | None = None
    qqq_close = None
    qqq_ma50 = None
    if qqq_bars:
        qqq_ind = compute_indicators(
            qqq_bars, sessions=sessions, volume_avg_sessions=vol_sessions, range_limit=range_limit
        )
        qqq_close = qqq_bars[-1].close
        qqq_ma50 = qqq_ind.ma50
        if qqq_ma50 is not None:
            qqq_above = qqq_close > qqq_ma50
    market_filter = {True: "Pass", False: "Fail"}.get(qqq_above) if qqq_above is not None else None

    row = WatchRow()
    row.ticker = symbol
    row.company = result.company or symbol
    row.theme = sector
    row.pullback = "No"
    row.trigger = "No"
    row.earnings = ""
    _refresh_earnings(row, client, session, result.quote_type)
    close = bars[-1].close
    row.last_price = money(close)
    breakout = evaluate_breakout(
        bars,
        indicators,
        qqq_above_ma50=qqq_above,
        volume_multiple=float(settings["breakout_volume_multiple"]),
    )
    pullback = evaluate_pullback(
        bars,
        indicators.ma50,
        touch_band=float(settings["pullback_touch_band"]),
        min_separation=float(settings["pullback_min_separation"]),
        lookback=int(settings["pullback_sessions"]),
    )
    reasons = []
    new_breakout = False
    new_pullback = False
    if breakout.flag:
        skip, why = earnings_blocks(
            row.earnings or None, session, window_days=int(settings["earnings_filter_calendar_days"])
        )
        if skip:
            reasons.append(f"breakout not flagged: {why}")
        else:
            new_breakout = True
            row.trigger = "Yes"
    else:
        reasons.append(f"no breakout ({breakout.reason})")
    if pullback.flag:
        skip, why = earnings_blocks(
            row.earnings or None, session, window_days=int(settings["earnings_filter_calendar_days"])
        )
        if skip:
            reasons.append(f"pullback not flagged: {why}")
        else:
            new_pullback = True
            row.pullback = "Yes"
    else:
        reasons.append(f"no pullback ({pullback.reason})")
        row.pullback = "No"
    row.notes = " ".join(reasons)
    if new_breakout and indicators.base_high is not None and indicators.base_low is not None:
        row.notes = append_note(
            row.notes,
            f"Triggered {session.isoformat()}. Base high {indicators.base_high:.2f}. Base low {indicators.base_low:.2f}.",
        )
    elif new_pullback:
        row.notes = append_note(row.notes, f"Triggered {session.isoformat()}.")
    _price_fields(row, indicators, session)

    papers = load_papers(root)
    if new_breakout or new_pullback:
        setup = choose_setup(new_breakout, new_pullback)
        stop = float(indicators.base_low if setup == "Breakout" else indicators.ma50)
        fills = load_fills(root)
        prices = {symbol: close}
        if qqq_close is not None:
            prices[qqq_symbol] = qqq_close
        provisional = rebuild_real(fills, prices)
        if any(item.net_shares > 0 and item.total is None for item in provisional):
            pnl = None
        else:
            pnl = real_total_pnl(provisional)
            if pnl is None:
                pnl = 0.0
        shares, sizing_note = _sizing_notes(
            entry=money(close),
            stop=money(stop),
            settings=settings,
            session=session,
            rows=papers,
            pnl=pnl,
        )
        notes = f"Triggered {session.isoformat()}. Original stop {money(stop):.2f}."
        if setup == "Breakout" and indicators.base_high is not None:
            notes = (
                f"Triggered {session.isoformat()}. Base high {indicators.base_high:.2f}. "
                f"Base low {indicators.base_low:.2f}. Original stop {money(stop):.2f}."
            )
        if sizing_note:
            notes = append_note(notes, sizing_note)
            row.notes = append_note(row.notes, sizing_note)
        pos = PaperPosition(
            ticker=symbol,
            last_close=money(close),
            live_price=money(close),
            vs_entry_pct=0.0,
            setup=setup,
            entry_date=session,
            entry=money(close),
            stop=money(stop),
            target=target_price(money(close), money(stop), float(settings["profit_target_r"])),
            trail=None if indicators.ma20 is None else money(indicators.ma20),
            status="Open",
            exit_date=None,
            exit_price=None,
            blended_pct=None,
            shares=shares,
            notes=notes,
            sim_shares=None,
            sim_result=None,
        )
        apply_session(pos, bars[-1], indicators.ma20)
        _apply_sim(pos, papers, settings)
        row.shares = pos.shares
        row.stop = pos.original_stop()
        papers.append(pos)
        flag_text = f"Paper row opened ({setup}, stop {pos.original_stop():.2f}, plan shares {pos.shares if pos.shares is not None else 'blank'})."
    else:
        joined = " ".join(reasons)
        if joined:
            joined = joined[0].upper() + joined[1:]
        flag_text = "No paper row. " + joined

    _persist(
        root,
        settings,
        watch + [row],
        papers,
        session=session,
        qqq_close=qqq_close,
        qqq_ma50=qqq_ma50,
        market_filter=market_filter,
    )
    saved = next(item for item in load_watch(root) if item.ticker == symbol)
    return (
        f"{saved.ticker} added under {saved.theme}. Company {saved.company}. "
        f"Last price {saved.last_price:.2f}. MA50 {saved.ma50 if saved.ma50 is not None else 'n/a'}. "
        f"MA100 {saved.ma100 if saved.ma100 is not None else 'n/a'}. "
        f"Consolidating {saved.consolidating}. Trigger {saved.trigger}. Pullback {saved.pullback}. "
        f"Last check {saved.last_check}. {flag_text}"
    )
