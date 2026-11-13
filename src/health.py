"""Report-only audit. This module never writes state files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.calendar_nyse import is_trading_day, now_et, previous_trading_day
from src.ledger import walk_ledger
from src.positions import blended_fraction, sort_paper
from src.schema import (
    PAPER_COLUMNS,
    RADAR_COLUMNS,
    REAL_COLUMNS,
    TRADE_COLUMNS,
    WATCHLIST_COLUMNS,
)
from src.sizing import sim_share_size
from src.state import (
    load_fills,
    load_json,
    load_papers,
    load_radar,
    load_real,
    load_settings,
    load_watch,
    paper_to_dict,
    rebuild_real,
    sort_watch,
    watch_to_dict,
)
from src.stats import sim_snapshot, summarize_percents
from src.views import trade_log_block


def _near(found: float | None, expected: float, tolerance: float) -> bool:
    if found is None:
        return False
    return abs(found - expected) <= tolerance


def audit(root: Path, today: date | None = None) -> tuple[list[str], str]:
    today = today or now_et().date()
    failures: list[str] = []

    required = [
        "data/summary.md",
        "data/dashboard.json",
        "data/watchlist.csv",
        "data/paper_positions.csv",
        "data/trade_log.csv",
        "data/real_positions.csv",
        "data/earnings_radar.csv",
        "data/sim_ledger.json",
        "data/deferred_bench.csv",
        "data/README.md",
        "rules.md",
        "settings.json",
    ]
    for rel in required:
        if not (root / rel).exists():
            failures.append(f"{rel}: missing")

    banner = ""
    banner_path = root / "data" / "README.md"
    if banner_path.exists():
        banner = banner_path.read_text(encoding="utf-8")
        if "paper" not in banner.lower() or "simulation" not in banner.lower():
            failures.append("data/README.md: banner does not describe paper rows and the simulation")

    def header_of(path: Path) -> list[str]:
        if not path.exists():
            return []
        first = path.read_text(encoding="utf-8").splitlines()[:1]
        return first[0].split(",") if first else []

    expected_headers = {
        "data/watchlist.csv": WATCHLIST_COLUMNS,
        "data/paper_positions.csv": PAPER_COLUMNS,
        "data/trade_log.csv": TRADE_COLUMNS,
        "data/real_positions.csv": REAL_COLUMNS,
        "data/earnings_radar.csv": RADAR_COLUMNS,
    }
    for rel, columns in expected_headers.items():
        found = header_of(root / rel)
        if found and found != columns:
            failures.append(f"{rel}: header mismatch")

    try:
        settings = load_settings(root)
    except Exception as exc:
        return failures + [f"settings.json: {exc}"], "counts unavailable"
    watch = load_watch(root) if (root / "data" / "watchlist.csv").exists() else []
    papers = load_papers(root) if (root / "data" / "paper_positions.csv").exists() else []
    fills = load_fills(root) if (root / "data" / "trade_log.csv").exists() else []
    real_rows = load_real(root) if (root / "data" / "real_positions.csv").exists() else []
    dashboard = load_json(root / "data" / "dashboard.json")
    summary = (root / "data" / "summary.md").read_text(encoding="utf-8") if (root / "data" / "summary.md").exists() else ""

    account = float(settings["account_size_usd"])
    risk = float(settings["risk_pct_per_trade"])
    max_risk = float(settings["max_total_open_risk_pct"])
    if not account > 0:
        failures.append("settings.json: account size is not positive")
    if not 0 < risk <= 0.10:
        failures.append("settings.json: risk percent is outside 0–10%")
    if int(settings["max_open_test_positions"]) < 1:
        failures.append("settings.json: max open positions is below 1")
    if not risk <= max_risk <= 0.25:
        failures.append("settings.json: max total open risk is outside risk percent–25%")
    if float(settings["circuit_breaker_usd"]) <= 0:
        failures.append("settings.json: circuit breaker is not positive")
    expected_breaker = round(account * 0.20, 2)
    if abs(float(settings["circuit_breaker_usd"]) - expected_breaker) > 0.02:
        failures.append(
            f"settings.json: circuit breaker US${settings['circuit_breaker_usd']} "
            f"vs 20% of account US${expected_breaker:.2f}"
        )
    if float(settings["sim_account_size_usd"]) <= 0:
        failures.append("settings.json: sim account is not positive")
    if not 0 < float(settings["sim_risk_pct_per_trade"]) <= 0.10:
        failures.append("settings.json: sim risk percent is outside 0–10%")
    cash = settings.get("ib_cash_available_usd")
    as_of = settings.get("ib_cash_as_of")
    round_started = today >= settings["test_round_start"]
    if cash not in (None, "") or as_of not in (None, ""):
        if cash in (None, "") or as_of in (None, ""):
            failures.append("settings.json: IB cash and its as-of date must both be present once either is set")
    elif round_started:
        failures.append("settings.json: IB cash is blank after the test round start")

    tickers = [row.ticker for row in watch]
    if any(not ticker for ticker in tickers):
        failures.append("data/watchlist.csv: blank ticker")
    if len(tickers) != len(set(tickers)):
        failures.append("data/watchlist.csv: duplicate ticker")
    for index, row in enumerate(watch, start=2):
        where = f"data/watchlist.csv row {index} {row.ticker}"
        if row.last_check is not None and row.last_price is None:
            failures.append(f"{where}: Last price is blank after a check")
        if row.consol_high is not None and row.consol_low is not None and row.consol_high < row.consol_low:
            failures.append(f"{where}: consol high is below consol low")
        if row.pullback not in ("Yes", "No", "Failed"):
            failures.append(f"{where}: Pullback? is {row.pullback}")
        if row.trigger not in ("Yes", "No", "Failed"):
            failures.append(f"{where}: Trigger? is {row.trigger}")
        if row.consolidating not in ("Yes", "No"):
            failures.append(f"{where}: Consolidating? is {row.consolidating}")
        if row.earnings and row.earnings != "N/A":
            try:
                when = date.fromisoformat(row.earnings)
            except ValueError:
                failures.append(f"{where}: earnings date is not a plain date or N/A")
            else:
                if row.last_check and when < row.last_check:
                    failures.append(f"{where}: earnings date {row.earnings} is in the past")
        if row.trigger == "Yes" or row.pullback == "Yes":
            if row.stop is None:
                failures.append(f"{where}: Yes flag without a stop")
        if row.last_price is not None and row.ma50 not in (None, 0):
            expected = (row.last_price - row.ma50) / row.ma50 * 100.0
            if not _near(row.vs_ma50_pct, expected, 0.1):
                failures.append(f"{where}: Vs MA50 % {row.vs_ma50_pct} vs {expected:.2f}")
        if row.last_price not in (None, 0) and row.consol_high is not None:
            expected = (row.consol_high - row.last_price) / row.last_price * 100.0
            if not _near(row.to_consol_high_pct, expected, 0.1):
                failures.append(f"{where}: To consol. high % {row.to_consol_high_pct} vs {expected:.2f}")
    if watch:
        ordered = sort_watch(watch)
        if [row.ticker for row in ordered] != [row.ticker for row in watch] or [
            (row.pullback, row.consolidating) for row in ordered
        ] != [(row.pullback, row.consolidating) for row in watch]:
            failures.append("data/watchlist.csv: sort order is not Pullback, Consolidating, Ticker")
        checks = {row.last_check for row in watch}
        if len(checks) > 1:
            failures.append("data/watchlist.csv: Last check is not identical on every row")
        regime = dashboard.get("market_regime") or {}
        last = regime.get("last_daily_check")
        if last:
            if len(checks) == 1:
                only = next(iter(checks))
                if only is None or only.isoformat() != last:
                    failures.append(
                        f"data/watchlist.csv: Last check {only} vs dashboard last daily check {last}"
                    )

    ordered_papers = sort_paper(papers)
    if [paper_to_dict(row) for row in ordered_papers] != [paper_to_dict(row) for row in papers]:
        # Compare status/date order rather than full dict float formatting.
        key = lambda row: (row.status, row.entry_date, row.ticker)  # noqa: E731
        if [key(row) for row in ordered_papers] != [key(row) for row in papers]:
            failures.append("data/paper_positions.csv: sort order is not status, then newest entry date")
    watch_names = {row.ticker for row in watch}
    watch_price = {row.ticker: row.last_price for row in watch}
    start = settings["test_round_start"]
    for index, pos in enumerate(papers, start=2):
        where = f"data/paper_positions.csv row {index} {pos.ticker}"
        if pos.status not in ("Open", "Half sold", "Exited", "Voided"):
            failures.append(f"{where}: status {pos.status}")
        if pos.status in ("Open", "Half sold"):
            if pos.live_price is None or pos.entry == 0:
                failures.append(f"{where}: open row missing a live price")
            elif not _near(pos.vs_entry_pct, (pos.live_price - pos.entry) / pos.entry * 100.0, 0.1):
                failures.append(f"{where}: vs Entry % does not match the live price")
            if None in (pos.entry, pos.stop, pos.target):
                failures.append(f"{where}: open row missing entry, stop, or target")
            listed = watch_price.get(pos.ticker)
            if listed is not None and pos.last_close is not None and abs(listed - pos.last_close) > 0.02:
                failures.append(f"{where}: last close {pos.last_close} vs watchlist {listed}")
            if pos.blended_pct is not None or pos.sim_result is not None:
                failures.append(f"{where}: blended result or sim result is filled while the row is open")
        if pos.status == "Exited":
            if pos.exit_price is None or pos.exit_date is None or pos.blended_pct is None:
                failures.append(f"{where}: exited row is incomplete")
            else:
                expected_vs = (pos.exit_price - pos.entry) / pos.entry * 100.0
                if not _near(pos.vs_entry_pct, expected_vs, 0.05):
                    failures.append(f"{where}: static vs Entry % {pos.vs_entry_pct} vs {expected_vs:.2f}")
                expected_blend = blended_fraction(
                    pos.entry, pos.exit_price, pos.target, pos.had_half_sale()
                ) * 100.0
                if not _near(pos.blended_pct, expected_blend, 0.05):
                    failures.append(
                        f"{where}: blended result {pos.blended_pct} vs {expected_blend:.2f}"
                    )
                if pos.sim_shares:
                    expected_sim = round(pos.sim_shares * pos.entry * (pos.blended_pct / 100.0), 2)
                    if pos.sim_result is None or abs(pos.sim_result - expected_sim) > 0.05:
                        failures.append(f"{where}: sim result {pos.sim_result} vs {expected_sim:.2f}")
        if pos.status == "Voided" and pos.sim_shares:
            failures.append(f"{where}: voided row still has sim shares")
        if pos.shares is not None and pos.entry_date < start:
            failures.append(f"{where}: plan shares are filled before the test-round start")
        if pos.buy_decision and pos.shares is None:
            failures.append(f"{where}: a recorded decision sits on an unsized row")
        if pos.ticker not in watch_names and pos.status in ("Open", "Half sold"):
            failures.append(f"{where}: open ticker is not on the watchlist")
        if pos.entry_date >= start and pos.status != "Voided":
            size = sim_share_size(
                float(settings["sim_account_size_usd"]),
                float(settings["sim_risk_pct_per_trade"]),
                float(settings["sim_concentration_ceiling_pct"]),
                pos.entry,
                pos.original_stop(),
            )
            if pos.sim_shares is None:
                if size.shares > 0 and "Sim skipped — capital cap" not in (pos.notes or ""):
                    failures.append(f"{where}: post-start row has neither sim shares nor a capital-cap stamp")
                if size.shares == 0 and "Sim skipped" not in (pos.notes or ""):
                    failures.append(f"{where}: sim size rounds to 0 without a skip stamp")
            elif pos.sim_shares != size.shares:
                failures.append(
                    f"{where}: sim shares {pos.sim_shares} vs min(risk, ceiling) {size.shares}"
                )

    walked = walk_ledger(sort_paper(papers), float(settings["sim_account_size_usd"]))
    if walked.went_negative:
        failures.append("data/sim_ledger.json: recomputed cash goes negative")
    stored = load_json(root / "data" / "sim_ledger.json")
    if stored and abs(float(stored.get("cash", walked.cash)) - walked.cash) > 0.02:
        failures.append(
            f"data/sim_ledger.json: cash {stored.get('cash')} vs recomputed {walked.cash:.2f}"
        )

    rebuilt = rebuild_real(fills, {row.ticker: row.live_price for row in real_rows})
    if [row.ticker for row in rebuilt] != [row.ticker for row in real_rows]:
        failures.append("data/real_positions.csv: tickers do not match the trade log")
    for found, expected in zip(real_rows, rebuilt):
        where = f"data/real_positions.csv {found.ticker}"
        if found.net_shares != expected.net_shares or found.bought != expected.bought or found.sold != expected.sold:
            failures.append(f"{where}: share counts do not match the trade log")
        if (found.status == "Open") != (found.net_shares > 0):
            failures.append(f"{where}: status does not match net shares")
        if expected.realized is not None and found.realized is not None and abs(found.realized - expected.realized) > 0.02:
            failures.append(f"{where}: realized {found.realized} vs {expected.realized}")
        if found.live_price is not None and found.net_shares > 0:
            market = found.net_shares * found.live_price
            if found.market_value is None or abs(found.market_value - market) > 0.02:
                failures.append(f"{where}: market value is not net shares times live price")

    for index, fill in enumerate(fills, start=2):
        where = f"data/trade_log.csv row {index}"
        if fill.day is None or not fill.ticker or fill.side not in ("Buy", "Sell"):
            failures.append(f"{where}: incomplete row")
            continue
        if fill.shares <= 0 or fill.price <= 0 or fill.commission < 0 or fill.other_costs < 0:
            failures.append(f"{where}: shares, price, or costs are out of range")
        gross = round(fill.shares * fill.price, 2)
        if abs(fill.gross - gross) > 0.001:
            failures.append(f"{where}: gross does not match shares times price")

    criteria = dashboard.get("test_round_criteria") or ""
    if "10" not in criteria or "2026-12-31" not in criteria or "20%" not in criteria:
        failures.append("data/dashboard.json: test-round criteria text is missing")
    counts = dashboard.get("paper_positions") or {}
    from src.stats import counts_by_status

    fresh_counts = counts_by_status(papers)
    for key in ("open", "half_sold", "exited", "voided"):
        if counts.get(key) != fresh_counts[key]:
            failures.append(f"data/dashboard.json: paper {key} {counts.get(key)} vs {fresh_counts[key]}")
    fresh_trade = trade_log_block(fills)
    stored_trade = dashboard.get("trade_log") or {}
    for key, value in fresh_trade.items():
        if stored_trade.get(key) != value:
            failures.append(f"data/dashboard.json: trade log {key} {stored_trade.get(key)} vs {value}")
    last_check = (dashboard.get("market_regime") or {}).get("last_daily_check")
    if last_check:
        last_day = date.fromisoformat(last_check)
        if not is_trading_day(last_day):
            failures.append(f"data/dashboard.json: last daily check {last_check} is not a session day")
        probe = today
        if not is_trading_day(probe):
            probe = previous_trading_day(today)
        # A check earlier than the latest session is fine if the engine has not run today.
        if last_day > probe:
            failures.append(f"data/dashboard.json: last daily check {last_check} is in the future")
    exited_pct = [row.blended_pct for row in papers if row.status == "Exited" and row.blended_pct is not None]
    fresh_perf = summarize_percents(exited_pct)
    stored_perf = (dashboard.get("paper_performance") or {}).get("all") or {}
    if stored_perf.get("exited") != fresh_perf["exited"]:
        failures.append("data/dashboard.json: exited count does not match paper rows")
    if fresh_perf["exited"]:
        if stored_perf.get("win_rate_pct") is None or abs(stored_perf["win_rate_pct"] - fresh_perf["win_rate_pct"]) > 0.05:
            failures.append("data/dashboard.json: win rate does not match blended results")
        if stored_perf.get("average_result_pct") is None or abs(stored_perf["average_result_pct"] - fresh_perf["average_result_pct"]) > 0.05:
            failures.append("data/dashboard.json: average result does not match blended results")
    fresh_sim = sim_snapshot(papers, float(settings["sim_account_size_usd"]))
    stored_sim = dashboard.get("sim_portfolio") or {}
    if abs(float(stored_sim.get("realized_usd") or 0) - fresh_sim["realized_usd"]) > 0.05:
        failures.append("data/dashboard.json: sim realized does not match exited sim rows")
    if abs(float(stored_sim.get("total_usd") or 0) - fresh_sim["total_usd"]) > 0.05:
        failures.append("data/dashboard.json: sim total does not match realized plus unrealized")
    sim_line = f"Sim total result: US${fresh_sim['total_usd']:.2f}"
    if summary and sim_line not in summary:
        failures.append("data/summary.md: sim total does not match the dashboard")
    if summary and "not investment advice" not in summary.lower():
        failures.append("data/summary.md: missing the not-investment-advice line")
    radar = load_radar(root) if (root / "data" / "earnings_radar.csv").exists() else []
    for item in radar:
        if item.get("Ticker") and item["Ticker"] not in summary:
            failures.append(f"data/summary.md: earnings radar missing {item['Ticker']}")

    open_paper = sum(1 for row in papers if row.status in ("Open", "Half sold"))
    counts_line = (
        f"Counts: watchlist {len(watch)}, paper open {open_paper}, "
        f"paper exited {sum(1 for row in papers if row.status == 'Exited')}, "
        f"trade log {len(fills)}, sim cash {walked.cash:.2f}"
    )
    return failures, counts_line
