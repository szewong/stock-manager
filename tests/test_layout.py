"""The committed store matches the schemas and the confirmed settings."""

import json
from pathlib import Path

from src.health import audit
from src.schema import (
    BENCH_COLUMNS,
    DEFAULT_SETTINGS,
    PAPER_COLUMNS,
    RADAR_COLUMNS,
    REAL_COLUMNS,
    TRADE_COLUMNS,
    WATCHLIST_COLUMNS,
)

ROOT = Path(__file__).resolve().parents[1]


def _header(rel: str) -> list[str]:
    line = (ROOT / rel).read_text(encoding="utf-8").splitlines()[0]
    return line.split(",")


def test_settings_match_the_confirmed_values():
    stored = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    assert stored == DEFAULT_SETTINGS
    assert stored["timezone"] == "America/New_York"
    assert stored["account_size_usd"] == 750
    assert stored["risk_pct_per_trade"] == 0.02
    assert stored["test_round_start"] == "2026-11-19"
    assert stored["round_end_date"] == "2026-12-31"
    assert stored["round_end_closed_trades"] == 10
    assert stored["sim_account_size_usd"] == 100000
    assert stored["sim_concentration_ceiling_pct"] == 0.25
    assert stored["circuit_breaker_usd"] == 150
    assert stored["circuit_breaker_pct"] == 0.2


def test_headers_and_a_healthy_empty_store(monkeypatch):
    assert _header("data/watchlist.csv") == WATCHLIST_COLUMNS
    assert _header("data/paper_positions.csv") == PAPER_COLUMNS
    assert _header("data/trade_log.csv") == TRADE_COLUMNS
    assert _header("data/real_positions.csv") == REAL_COLUMNS
    assert _header("data/earnings_radar.csv") == RADAR_COLUMNS
    assert _header("data/deferred_bench.csv") == BENCH_COLUMNS
    assert (ROOT / "data" / "watchlist.csv").read_text(encoding="utf-8").count("\n") == 1
    monkeypatch.setenv("STOCK_MANAGER_NOW", "2026-11-13T12:00:00")
    monkeypatch.setenv("STOCK_MANAGER_ROOT", str(ROOT))
    failures, counts = audit(ROOT)
    assert failures == []
    assert "watchlist 0" in counts
