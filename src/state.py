"""Load and save the file store. Derived files are rewritten, not hand-edited."""

from __future__ import annotations

import csv
import json
import os
from datetime import date
from pathlib import Path

from src.positions import PaperPosition, money
from src.schema import (
    BENCH_COLUMNS,
    DEFAULT_SETTINGS,
    PAPER_COLUMNS,
    RADAR_COLUMNS,
    REAL_COLUMNS,
    TEST_ROUND_CRITERIA,
    TRADE_COLUMNS,
    WATCHLIST_COLUMNS,
)

ROOT_ENV = "STOCK_MANAGER_ROOT"


def repo_root() -> Path:
    override = os.environ.get(ROOT_ENV)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1]


def _blank(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _num(value: float | None, places: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{places}f}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value if value is not None else "") for key, value in row.items()} for row in reader]


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _parse_float(text: str) -> float | None:
    text = (text or "").strip()
    if text == "" or text == "Unknown":
        return None
    return float(text)


def _parse_int(text: str) -> int | None:
    text = (text or "").strip()
    if text == "":
        return None
    return int(float(text))


def _parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if text == "" or text.upper() == "N/A":
        return None
    return date.fromisoformat(text)


class WatchRow:
    def __init__(self) -> None:
        self.ticker = ""
        self.company = ""
        self.theme = ""
        self.pullback = "No"
        self.consolidating = "No"
        self.trigger = "No"
        self.stop: float | None = None
        self.shares: int | None = None
        self.last_price: float | None = None
        self.ma50: float | None = None
        self.ma100: float | None = None
        self.consol_high: float | None = None
        self.consol_low: float | None = None
        self.range_pct_points: float | None = None
        self.volume_vs_avg = ""
        self.last_check: date | None = None
        self.notes = ""
        self.earnings = ""
        self.vs_ma50_pct: float | None = None
        self.to_consol_high_pct: float | None = None

    def recompute_distances(self) -> None:
        if self.last_price is not None and self.ma50 not in (None, 0):
            self.vs_ma50_pct = (self.last_price - self.ma50) / self.ma50 * 100.0
        else:
            self.vs_ma50_pct = None
        if self.last_price not in (None, 0) and self.consol_high is not None:
            self.to_consol_high_pct = (self.consol_high - self.last_price) / self.last_price * 100.0
        else:
            self.to_consol_high_pct = None


def sort_watch(rows: list[WatchRow]) -> list[WatchRow]:
    pull = {"Yes": 0, "No": 1, "Failed": 2}
    consol = {"Yes": 0, "No": 1}
    return sorted(
        rows,
        key=lambda row: (pull.get(row.pullback, 9), consol.get(row.consolidating, 9), row.ticker),
    )


def watch_from_dict(raw: dict[str, str]) -> WatchRow:
    row = WatchRow()
    row.ticker = raw.get("Ticker", "").strip()
    row.company = raw.get("Company", "").strip()
    row.theme = raw.get("Theme", "").strip()
    row.pullback = raw.get("Pullback?", "").strip() or "No"
    row.consolidating = raw.get("Consolidating?", "").strip() or "No"
    row.trigger = raw.get("Trigger?", "").strip() or "No"
    row.stop = _parse_float(raw.get("Stop", ""))
    row.shares = _parse_int(raw.get("Shares", ""))
    row.last_price = _parse_float(raw.get("Last price", ""))
    row.ma50 = _parse_float(raw.get("MA50", ""))
    row.ma100 = _parse_float(raw.get("MA100", ""))
    row.consol_high = _parse_float(raw.get("Consol. high", ""))
    row.consol_low = _parse_float(raw.get("Consol. low", ""))
    row.range_pct_points = _parse_float(raw.get("15-day range %", ""))
    row.volume_vs_avg = raw.get("Volume vs 20-day avg", "").strip()
    row.last_check = _parse_date(raw.get("Last check", ""))
    row.notes = raw.get("Notes", "").strip()
    row.earnings = raw.get("Earnings Date", "").strip()
    row.vs_ma50_pct = _parse_float(raw.get("Vs MA50 %", ""))
    row.to_consol_high_pct = _parse_float(raw.get("To consol. high %", ""))
    return row


def watch_to_dict(row: WatchRow) -> dict[str, str]:
    row.recompute_distances()
    volume = row.volume_vs_avg
    if volume not in ("", "Unknown"):
        try:
            volume = f"{float(volume):.2f}"
        except ValueError:
            pass
    return {
        "Ticker": row.ticker,
        "Company": row.company,
        "Theme": row.theme,
        "Pullback?": row.pullback,
        "Consolidating?": row.consolidating,
        "Trigger?": row.trigger,
        "Stop": _num(row.stop),
        "Shares": "" if row.shares is None else str(int(row.shares)),
        "Last price": _num(row.last_price),
        "MA50": _num(row.ma50),
        "MA100": _num(row.ma100),
        "Consol. high": _num(row.consol_high),
        "Consol. low": _num(row.consol_low),
        "15-day range %": _num(row.range_pct_points),
        "Volume vs 20-day avg": volume,
        "Last check": "" if row.last_check is None else row.last_check.isoformat(),
        "Notes": row.notes,
        "Earnings Date": row.earnings,
        "Vs MA50 %": _num(row.vs_ma50_pct),
        "To consol. high %": _num(row.to_consol_high_pct),
    }


def paper_from_dict(raw: dict[str, str]) -> PaperPosition:
    return PaperPosition(
        ticker=raw.get("Ticker", "").strip(),
        last_close=_parse_float(raw.get("Last close", "")),
        live_price=_parse_float(raw.get("Live price", "")),
        vs_entry_pct=_parse_float(raw.get("vs Entry %", "")),
        setup=raw.get("Setup", "").strip(),
        entry_date=_parse_date(raw.get("Entry date", "")) or date.min,
        entry=_parse_float(raw.get("Entry", "")) or 0.0,
        stop=_parse_float(raw.get("Stop", "")) or 0.0,
        target=_parse_float(raw.get("Target (2R)", "")) or 0.0,
        trail=_parse_float(raw.get("Trail stop (MA20)", "")),
        status=raw.get("Status", "").strip(),
        exit_date=_parse_date(raw.get("Exit date", "")),
        exit_price=_parse_float(raw.get("Exit price", "")),
        blended_pct=_parse_float(raw.get("Blended result %", "")),
        shares=_parse_int(raw.get("Shares", "")),
        notes=raw.get("Notes", "").strip(),
        sim_shares=_parse_int(raw.get("Sim Shares", "")),
        sim_result=_parse_float(raw.get("Sim result (US$)", "")),
        buy_decision=raw.get("Buy decision", "").strip(),
    )


def paper_to_dict(pos: PaperPosition) -> dict[str, str]:
    return {
        "Ticker": pos.ticker,
        "Last close": _num(pos.last_close),
        "Live price": _num(pos.live_price),
        "vs Entry %": _num(pos.vs_entry_pct),
        "Setup": pos.setup,
        "Entry date": "" if pos.entry_date == date.min else pos.entry_date.isoformat(),
        "Entry": _num(pos.entry),
        "Stop": _num(pos.stop),
        "Target (2R)": _num(pos.target),
        "Trail stop (MA20)": _num(pos.trail),
        "Status": pos.status,
        "Exit date": "" if pos.exit_date is None else pos.exit_date.isoformat(),
        "Exit price": _num(pos.exit_price),
        "Blended result %": _num(pos.blended_pct),
        "Shares": "" if pos.shares is None else str(int(pos.shares)),
        "Notes": pos.notes,
        "Sim Shares": "" if pos.sim_shares is None else str(int(pos.sim_shares)),
        "Sim result (US$)": _num(pos.sim_result),
        "Buy decision": pos.buy_decision,
    }


class Fill:
    def __init__(self) -> None:
        self.day: date | None = None
        self.ticker = ""
        self.side = ""
        self.shares = 0
        self.price = 0.0
        self.signal_price: float | None = None
        self.commission = 0.0
        self.other_costs = 0.0
        self.setup = ""
        self.notes = ""

    @property
    def gross(self) -> float:
        return money(self.shares * self.price)


def fill_from_dict(raw: dict[str, str]) -> Fill:
    fill = Fill()
    fill.day = _parse_date(raw.get("Date", ""))
    fill.ticker = raw.get("Ticker", "").strip()
    fill.side = raw.get("Buy/Sell", "").strip()
    fill.shares = _parse_int(raw.get("Shares", "")) or 0
    fill.price = _parse_float(raw.get("Price", "")) or 0.0
    fill.signal_price = _parse_float(raw.get("Signal price", ""))
    fill.commission = _parse_float(raw.get("Commission", "")) or 0.0
    fill.other_costs = _parse_float(raw.get("Other costs", "")) or 0.0
    fill.setup = raw.get("Setup", "").strip()
    fill.notes = raw.get("Notes", "").strip()
    return fill


def fill_to_dict(fill: Fill) -> dict[str, str]:
    return {
        "Date": "" if fill.day is None else fill.day.isoformat(),
        "Ticker": fill.ticker,
        "Buy/Sell": fill.side,
        "Shares": str(int(fill.shares)),
        "Price": _num(fill.price),
        "Signal price": _num(fill.signal_price),
        "Gross amount": _num(fill.gross),
        "Commission": _num(fill.commission),
        "Other costs": _num(fill.other_costs),
        "Setup": fill.setup,
        "Notes": fill.notes,
    }


class RealRow:
    def __init__(self) -> None:
        self.ticker = ""
        self.status = ""
        self.net_shares = 0
        self.avg_cost: float | None = None
        self.cost_basis: float | None = None
        self.live_price: float | None = None
        self.market_value: float | None = None
        self.unrealized: float | None = None
        self.unrealized_pct: float | None = None
        self.bought = 0
        self.sold = 0
        self.realized: float | None = None
        self.total: float | None = None
        self.last_activity: date | None = None
        self.setup = ""


def real_to_dict(row: RealRow) -> dict[str, str]:
    return {
        "Ticker": row.ticker,
        "Status": row.status,
        "Net shares": str(int(row.net_shares)),
        "Avg cost": _num(row.avg_cost),
        "Cost basis": _num(row.cost_basis),
        "Live price": _num(row.live_price),
        "Market value": _num(row.market_value),
        "Unrealized P&L": _num(row.unrealized),
        "Unrealized %": _num(row.unrealized_pct),
        "Bought (shares)": str(int(row.bought)),
        "Sold (shares)": str(int(row.sold)),
        "Realized P&L": _num(row.realized),
        "Total P&L": _num(row.total),
        "Last activity": "" if row.last_activity is None else row.last_activity.isoformat(),
        "Setup (latest)": row.setup,
    }


def real_from_dict(raw: dict[str, str]) -> RealRow:
    row = RealRow()
    row.ticker = raw.get("Ticker", "").strip()
    row.status = raw.get("Status", "").strip()
    row.net_shares = _parse_int(raw.get("Net shares", "")) or 0
    row.avg_cost = _parse_float(raw.get("Avg cost", ""))
    row.cost_basis = _parse_float(raw.get("Cost basis", ""))
    row.live_price = _parse_float(raw.get("Live price", ""))
    row.market_value = _parse_float(raw.get("Market value", ""))
    row.unrealized = _parse_float(raw.get("Unrealized P&L", ""))
    row.unrealized_pct = _parse_float(raw.get("Unrealized %", ""))
    row.bought = _parse_int(raw.get("Bought (shares)", "")) or 0
    row.sold = _parse_int(raw.get("Sold (shares)", "")) or 0
    row.realized = _parse_float(raw.get("Realized P&L", ""))
    row.total = _parse_float(raw.get("Total P&L", ""))
    row.last_activity = _parse_date(raw.get("Last activity", ""))
    row.setup = raw.get("Setup (latest)", "").strip()
    return row


def rebuild_real(fills: list[Fill], prices: dict[str, float | None]) -> list[RealRow]:
    grouped: dict[str, list[tuple[int, Fill]]] = {}
    for index, fill in enumerate(fills):
        grouped.setdefault(fill.ticker, []).append((index, fill))
    rows: list[RealRow] = []
    for ticker in sorted(grouped):
        lots = grouped[ticker]
        bought = sum(fill.shares for _, fill in lots if fill.side == "Buy")
        sold = sum(fill.shares for _, fill in lots if fill.side == "Sell")
        net = bought - sold
        buy_gross = sum(fill.shares * fill.price for _, fill in lots if fill.side == "Buy")
        sell_gross = sum(fill.shares * fill.price for _, fill in lots if fill.side == "Sell")
        commission = sum(fill.commission for _, fill in lots)
        other = sum(fill.other_costs for _, fill in lots)
        avg = (buy_gross / bought) if bought else None
        realized = sell_gross - (avg or 0.0) * sold - commission - other
        live = prices.get(ticker)
        row = RealRow()
        row.ticker = ticker
        row.net_shares = net
        row.bought = bought
        row.sold = sold
        row.avg_cost = None if avg is None else money(avg)
        row.cost_basis = money(net * avg) if avg is not None and net > 0 else money(0.0)
        row.realized = money(realized)
        row.status = "Open" if net > 0 else "Closed"
        if net > 0 and live is not None:
            row.live_price = money(live)
            row.market_value = money(net * live)
            row.unrealized = money(row.market_value - (row.cost_basis or 0.0))
            basis = row.cost_basis or 0.0
            row.unrealized_pct = (row.unrealized / basis * 100.0) if basis else None
            row.total = money(row.realized + row.unrealized)
        elif net <= 0:
            row.live_price = money(live) if live is not None else None
            row.market_value = money(0.0)
            row.unrealized = money(0.0)
            row.unrealized_pct = 0.0
            row.total = row.realized
        else:
            row.live_price = None
            row.market_value = None
            row.unrealized = None
            row.unrealized_pct = None
            row.total = None
        dated = [(fill.day, index, fill) for index, fill in lots if fill.day is not None]
        if dated:
            _, _, latest = max(dated, key=lambda item: (item[0], item[1]))
            row.last_activity = latest.day
            row.setup = latest.setup
        rows.append(row)
    return rows


def real_total_pnl(rows: list[RealRow]) -> float | None:
    total = 0.0
    for row in rows:
        if row.total is None:
            return None
        total += row.total
    return round(total, 2)


def load_settings(root: Path | None = None) -> dict:
    path = (root or repo_root()) / "settings.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    merged["test_round_start"] = date.fromisoformat(str(merged["test_round_start"]))
    merged["round_end_date"] = date.fromisoformat(str(merged["round_end_date"]))
    flag = merged.get("flag_rules_effective_date")
    merged["flag_rules_effective_date"] = date.fromisoformat(flag) if flag else None
    return merged


def load_watch(root: Path) -> list[WatchRow]:
    return [watch_from_dict(raw) for raw in _read_csv(root / "data" / "watchlist.csv") if raw.get("Ticker")]


def save_watch(root: Path, rows: list[WatchRow]) -> None:
    _write_csv(
        root / "data" / "watchlist.csv",
        WATCHLIST_COLUMNS,
        [watch_to_dict(row) for row in sort_watch(rows)],
    )


def load_papers(root: Path) -> list[PaperPosition]:
    rows = []
    for raw in _read_csv(root / "data" / "paper_positions.csv"):
        if raw.get("Ticker"):
            rows.append(paper_from_dict(raw))
    return rows


def save_papers(root: Path, rows: list[PaperPosition]) -> None:
    from src.positions import sort_paper

    _write_csv(
        root / "data" / "paper_positions.csv",
        PAPER_COLUMNS,
        [paper_to_dict(row) for row in sort_paper(rows)],
    )


def load_fills(root: Path) -> list[Fill]:
    fills = []
    for raw in _read_csv(root / "data" / "trade_log.csv"):
        if raw.get("Ticker") or raw.get("Date"):
            fills.append(fill_from_dict(raw))
    return fills


def save_fills(root: Path, fills: list[Fill]) -> None:
    _write_csv(root / "data" / "trade_log.csv", TRADE_COLUMNS, [fill_to_dict(fill) for fill in fills])


def save_real(root: Path, rows: list[RealRow]) -> None:
    _write_csv(root / "data" / "real_positions.csv", REAL_COLUMNS, [real_to_dict(row) for row in rows])


def load_real(root: Path) -> list[RealRow]:
    return [real_from_dict(raw) for raw in _read_csv(root / "data" / "real_positions.csv") if raw.get("Ticker")]


def save_radar(root: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(root / "data" / "earnings_radar.csv", RADAR_COLUMNS, rows)


def load_radar(root: Path) -> list[dict[str, str]]:
    return [row for row in _read_csv(root / "data" / "earnings_radar.csv") if row.get("Ticker")]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def settings_document() -> dict:
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def empty_dashboard() -> dict:
    settings = DEFAULT_SETTINGS
    return {
        "test_round": {
            "account_size_usd": settings["account_size_usd"],
            "risk_pct": settings["risk_pct_per_trade"],
            "risk_per_trade_usd": round(
                settings["account_size_usd"] * settings["risk_pct_per_trade"], 2
            ),
            "test_round_start": settings["test_round_start"],
            "round_end_date": settings["round_end_date"],
            "round_end_closed_trades": settings["round_end_closed_trades"],
            "max_open_positions": settings["max_open_test_positions"],
            "max_total_open_risk_pct": settings["max_total_open_risk_pct"],
            "circuit_breaker_usd": settings["circuit_breaker_usd"],
            "circuit_breaker_pct": settings["circuit_breaker_pct"],
        },
        "market_regime": {
            "qqq_last_close": None,
            "qqq_ma50": None,
            "market_filter": None,
            "last_daily_check": None,
        },
        "paper_positions": {"open": 0, "half_sold": 0, "exited": 0, "voided": 0},
        "trade_log": {
            "orders": 0,
            "entry_fills": 0,
            "exit_fills": 0,
            "total_commissions": 0.0,
            "total_other_costs": 0.0,
            "net_cash_flow": 0.0,
        },
        "earnings_radar": [],
        "test_round_criteria": TEST_ROUND_CRITERIA,
        "paper_performance": {
            "all": {
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
            },
            "by_setup": {},
            "by_rules_date": {},
        },
        "sim_portfolio": {
            "positions_open": 0,
            "positions_closed": 0,
            "realized_usd": 0.0,
            "unrealized_usd": 0.0,
            "total_usd": 0.0,
            "return_pct": 0.0,
        },
    }


def empty_ledger() -> dict:
    cash = float(DEFAULT_SETTINGS["sim_account_size_usd"])
    return {"starting_cash": cash, "cash": cash, "events": []}


def write_seed(root: Path) -> None:
    """Create the empty store. Does not overwrite settings, rules, or README."""
    data = root / "data"
    reports = root / "reports"
    data.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    _write_csv(data / "watchlist.csv", WATCHLIST_COLUMNS, [])
    _write_csv(data / "paper_positions.csv", PAPER_COLUMNS, [])
    _write_csv(data / "trade_log.csv", TRADE_COLUMNS, [])
    _write_csv(data / "real_positions.csv", REAL_COLUMNS, [])
    _write_csv(data / "earnings_radar.csv", RADAR_COLUMNS, [])
    _write_csv(data / "deferred_bench.csv", BENCH_COLUMNS, [])
    write_json(data / "dashboard.json", empty_dashboard())
    write_json(data / "sim_ledger.json", empty_ledger())
    from src.report import build_summary

    (data / "summary.md").write_text(
        build_summary(empty_dashboard(), [], [], []),
        encoding="utf-8",
    )
    gitkeep = reports / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")
