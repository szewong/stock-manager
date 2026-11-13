"""Markdown reports. Every sentence states what the pre-set rules say."""

from __future__ import annotations

from datetime import date

from src.positions import PaperPosition
from src.schema import SECTORS
from src.state import WatchRow
from src.textutil import assert_factual, has_advice_wording


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"US${value:.2f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def price(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _bar(value: float, scale: float, width: int = 20) -> str:
    if scale <= 0:
        return ""
    cells = int(round(min(width, abs(value) / scale * width)))
    mark = "+" if value >= 0 else "-"
    return mark * cells


def build_summary(
    dashboard: dict,
    papers: list[PaperPosition],
    watch: list[WatchRow],
    radar: list[dict[str, str]],
) -> str:
    regime = dashboard.get("market_regime") or {}
    perf = (dashboard.get("paper_performance") or {}).get("all") or {}
    sim = dashboard.get("sim_portfolio") or {}
    trade = dashboard.get("trade_log") or {}
    test = dashboard.get("test_round") or {}
    qqq = regime.get("qqq_last_close")
    ma50 = regime.get("qqq_ma50")
    vs = None
    if qqq is not None and ma50 not in (None, 0):
        vs = (qqq - ma50) / ma50 * 100.0
    open_paper = [
        row for row in papers if row.status in ("Open", "Half sold")
    ]
    sim_rows = [row for row in papers if row.sim_shares and row.status == "Exited" and row.sim_result is not None]
    sim_rows += [
        row
        for row in papers
        if row.sim_shares and row.status in ("Open", "Half sold")
    ]
    lines = [
        "# Stock watchlist",
        "",
        "A rules record of one person's watchlist, paper positions, and an optional small test round.",
        "This is not investment advice. The program does not place trades.",
        "Figures below are computed from the other files in `data/`.",
        "",
        "## Market status",
        "",
        f"- QQQ close: {price(qqq)}",
        f"- QQQ MA50: {price(ma50)}",
        f"- QQQ vs MA50: {pct(vs)}",
        f"- Breakout filter: {regime.get('market_filter') or 'n/a'}",
        f"- Names watched: {len(watch)}",
        f"- Open paper positions: {len(open_paper)}",
        "",
        "## Signal record",
        "",
        f"- Exited paper positions: {perf.get('exited', 0)}",
        f"- Win rate: {pct(perf.get('win_rate_pct'))}",
        f"- Average blended result: {pct(perf.get('average_result_pct'))}",
        f"- Median blended result: {pct(perf.get('median_result_pct'))}",
        "",
        "## Simulation",
        "",
        f"- Sim total result: {money(sim.get('total_usd'))}",
        f"- Sim return: {pct(sim.get('return_pct'))}",
        f"- Sim positions open: {sim.get('positions_open', 0)}",
        f"- Sim positions closed: {sim.get('positions_closed', 0)}",
        "",
        "## Real test record",
        "",
        f"- Account size: {money(test.get('account_size_usd'))}",
        f"- Orders logged: {trade.get('orders', 0)}",
        f"- Entry fills: {trade.get('entry_fills', 0)}",
        f"- Exit fills: {trade.get('exit_fills', 0)}",
        f"- IB cash: {money(dashboard.get('ib_cash_available_usd'))}",
        "",
        "## Simulation by position",
        "",
    ]
    shown = []
    for row in papers:
        if not row.sim_shares:
            continue
        if row.status == "Exited" and row.sim_result is not None:
            shown.append((row.ticker, row.status, row.sim_result))
        elif row.status in ("Open", "Half sold"):
            from src.stats import sim_unrealized

            shown.append((row.ticker, row.status, round(sim_unrealized(row), 2)))
    shown.sort(key=lambda item: item[2], reverse=True)
    if not shown:
        lines.append("No simulation results yet.")
    else:
        scale = max(abs(item[2]) for item in shown) or 1.0
        lines.append("| Ticker | Status | Sim result | |")
        lines.append("| --- | --- | ---: | --- |")
        for ticker, status, result in shown:
            lines.append(
                f"| {ticker} | {status} | {result:.2f} | `{_bar(result, scale)}` |"
            )
    lines += ["", "## Open paper positions", ""]
    if not open_paper:
        lines.append("No open paper positions.")
    else:
        lines.append("| Ticker | Status | Close | Stop | Target | Trail | Progress |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- |")
        for row in open_paper:
            span = row.target - (row.original_stop() if row.status == "Half sold" else row.stop)
            close = row.last_close or 0.0
            origin = row.original_stop() if row.status == "Half sold" else row.stop
            frac = 0.0 if span <= 0 else max(0.0, min(1.0, (close - origin) / span))
            lines.append(
                f"| {row.ticker} | {row.status} | {price(row.last_close)} | {price(row.stop)} | "
                f"{price(row.target)} | {price(row.trail)} | `{'#' * int(round(frac * 20))}` |"
            )
    lines += ["", "## Earnings radar", ""]
    if not radar:
        lines.append("None within 14 days.")
    else:
        lines.append("| Ticker | Earnings date | Days away | Open position? |")
        lines.append("| --- | --- | ---: | --- |")
        for item in radar:
            lines.append(
                f"| {item.get('Ticker','')} | {item.get('Earnings date','')} | "
                f"{item.get('Days away','')} | {item.get('Open position?','')} |"
            )
    lines += [
        "",
        "## How it works",
        "",
        "The watchlist is checked against two patterns: a 15-session breakout and an MA50 pullback.",
        "Every flag that clears the earnings filter opens a paper row. A separate simulation sizes the same flags inside a cash ledger.",
        "Real-plan share counts are filled only inside the test round, and only when the position cap, the risk cap, and the circuit breaker all still have room.",
        "Reports describe those rules. They are not instructions, and nothing in this repo sends an order.",
        "",
    ]
    text = "\n".join(lines)
    assert_factual(text)
    return text


def render_after_close(model: dict) -> str:
    session: date = model["session"]
    lines = [
        f"# Daily after-close report — {session.isoformat()}",
        "",
        "This report states what the pre-set rules say about the latest completed session.",
        "This is not investment advice. The program does not place trades.",
        "",
    ]
    actions = model.get("actions") or []
    if actions:
        lines += ["## Real-plan facts for the next session", ""]
        lines.extend(actions)
        lines.append("")
    regime = model["regime"]
    filt = regime.get("market_filter")
    if filt == "Pass":
        meaning = "The breakout filter is open: the rules allow new breakout flags. Pullbacks are not gated by this filter."
    elif filt == "Fail":
        meaning = "The breakout filter is closed: the rules do not flag new breakouts. Pullbacks are not gated by this filter."
    else:
        meaning = "The breakout filter is unavailable, so no new breakout was flagged."
    lines += [
        "## Market regime",
        "",
        f"QQQ close {price(regime.get('qqq_last_close'))}, MA50 {price(regime.get('qqq_ma50'))}, filter {filt or 'Unavailable'}.",
        meaning,
        "",
        "## Events",
        "",
    ]
    events = model.get("events") or []
    if not events:
        lines.append("No new triggers, failures, or skips today.")
    else:
        lines.extend(f"- {event}" for event in events)
    lines += ["", "## Paper positions", ""]
    changes = model.get("status_changes") or []
    resting = model.get("open_lines") or []
    if not changes and not resting:
        lines.append("No open paper positions.")
    else:
        lines.extend(f"- {line}" for line in changes + resting)
    sim = model["sim"]
    lines += [
        "",
        (
            f"Sim total result {money(sim.get('total_usd'))}, "
            f"return {pct(sim.get('return_pct'))}, "
            f"sim positions open {sim.get('positions_open', 0)}."
        ),
        "",
        "## Key news",
        "",
        model.get("news_line") or "No material headlines kept.",
        "",
        "## Theme summary",
        "",
    ]
    themes = model.get("themes") or []
    if not themes:
        lines.append("No theme moves to summarize.")
    else:
        lines.extend(f"- {line}" for line in themes)
    state = model["watch_state"]
    lines += [
        "",
        "## Watchlist state",
        "",
        (
            f"Updated {state['updated']}. Pullback Yes: {state['pullback_yes']}. "
            f"Consolidating Yes: {state['consolidating_yes']}."
        ),
    ]
    misses = model.get("near_misses") or []
    if misses:
        lines.append("Near-misses:")
        lines.extend(f"- {line}" for line in misses)
    else:
        lines.append("Near-misses: none.")
    radar = model.get("radar") or []
    upcoming = radar[:5]
    lines += [
        "",
        "## Earnings radar",
        "",
        f"{len(radar)} names report within 14 calendar days.",
    ]
    if upcoming:
        lines.extend(
            f"- {item['Ticker']} on {item['Earnings date']} ({item['Days away']} days, open position {item['Open position?']})"
            for item in upcoming
        )
    soon = [
        item
        for item in radar
        if item.get("Open position?") == "Yes" and str(item.get("Days away", "")).isdigit() and int(item["Days away"]) <= 7
    ]
    if soon:
        lines.append(
            "Open paper positions with a report inside 7 days: "
            + ", ".join(item["Ticker"] for item in soon)
            + "."
        )
    lines += ["", "## Reconciliation", ""]
    nudges = model.get("nudges") or []
    if nudges:
        lines.extend(f"- {line}" for line in nudges)
    else:
        lines.append("No reconciliation notes.")
    lines += ["", "## Data quality", ""]
    quality = model.get("data_quality") or []
    if quality:
        lines.extend(f"- {line}" for line in quality)
    else:
        lines.append("No degraded series changed a decision.")
    if model.get("volume_note"):
        lines.append(model["volume_note"])
    lines += [
        "",
        "## File confirmation",
        "",
        "Updated: "
        + ", ".join(model.get("updated_files") or []),
        "Read and not modified: data/trade_log.csv.",
        "",
        "Limits: a missing price is skipped, not filled in. Paper exits use the session close, so a live result can differ from the planned risk. Paper and sim fills assume the signal price. The breakout filter leaves some patterns unflagged when QQQ is under its MA50. Nothing here is a forecast.",
        "",
    ]
    text = "\n".join(lines)
    assert_factual(text)
    return text


def render_intraday(kind: str, session: date, flags: list[str]) -> str:
    if kind == "late":
        title = f"# Late-session heads-up — {session.isoformat()}"
        note = "Intraday only. Confirmation is about 45 minutes away."
    else:
        title = f"# Mid-session heads-up — {session.isoformat()}"
        note = "Intraday only. Flags confirm at the close."
    lines = [
        title,
        "",
        note,
        "This is not investment advice. The program does not place trades.",
        "",
    ]
    lines.extend(f"- {flag}" for flag in flags)
    lines.append("")
    text = "\n".join(lines)
    assert_factual(text)
    return text


def render_market_open(model: dict) -> str:
    session: date = model["session"]
    lines = [
        f"# Market-open report — {session.isoformat()}",
        "",
        "Intraday briefing. Triggers, target hits, and exits still confirm at the close.",
        "This is not investment advice. The program does not place trades.",
        "",
        "## Market tone",
        "",
        model.get("tone") or "Market prices were not available.",
        "",
        "## Earnings dates on the calendar",
        "",
    ]
    earnings = model.get("earnings") or []
    if not earnings:
        lines.append("No watchlist earnings date is yesterday or today. Result figures are not invented.")
    else:
        lines.extend(f"- {line}" for line in earnings)
    lines += ["", "## Paper positions", ""]
    positions = model.get("positions") or []
    if not positions:
        lines.append("No open paper positions.")
    else:
        lines.extend(f"- {line}" for line in positions)
    lines += ["", "## Watchlist movers", ""]
    movers = model.get("movers") or []
    if not movers:
        lines.append("No watchlist name is 3% or more from the prior close, or prices were unavailable.")
    else:
        lines.extend(f"- {line}" for line in movers)
    lines += ["", "## Today's earnings dates", ""]
    today = model.get("today_earnings") or []
    if not today:
        lines.append("No watchlist name has an earnings date of today. Consensus figures are not fetched.")
    else:
        lines.extend(f"- {line}" for line in today)
    lines += ["", "## Pending real-plan entries", ""]
    pending = model.get("pending") or []
    if not pending:
        lines.append("No sized plan is waiting on a fill.")
    else:
        lines.extend(f"- {line}" for line in pending)
    if model.get("cash_line"):
        lines.append(model["cash_line"])
    lines += ["", "## Overnight headlines", ""]
    lines.append(model.get("news_line") or "No headlines kept.")
    lines.append("")
    text = "\n".join(lines)
    assert_factual(text)
    return text


def render_health(day: date, failures: list[str], counts: str) -> str:
    if not failures:
        text = f"Files health check ({day.isoformat()}): all healthy\n{counts}\n"
    else:
        lines = [f"Files health check ({day.isoformat()}): failures", ""]
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
        text = "\n".join(lines)
    assert_factual(text)
    return text


def render_review(day: date, sections: list[str]) -> str:
    lines = [
        f"# Weekly watchlist review — {day.isoformat()}",
        "",
        "Membership ideas only. Nothing was added or removed.",
        "This is not investment advice. The program does not place trades.",
        "",
    ]
    lines.extend(sections)
    lines.append("")
    text = "\n".join(lines)
    assert_factual(text)
    return text


def sector_order() -> list[str]:
    return list(SECTORS)


def keep_headline(title: str) -> bool:
    return bool(title) and not has_advice_wording(title)
