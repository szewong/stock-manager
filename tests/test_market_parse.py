"""Parsers for the HTTP fallbacks. No network."""

from src.market_data import merge_bars, parse_nasdaq_historical, parse_yahoo_chart
from src.rules import Bar
from datetime import date


def test_yahoo_chart_parser_uses_the_exchange_date():
    # 2026-11-20 14:30 UTC is 09:30 ET on the same calendar day.
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"shortName": "Example", "instrumentType": "EQUITY"},
                    "timestamp": [1763649000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10],
                                "high": [12],
                                "low": [9],
                                "close": [11],
                                "volume": [1000],
                            }
                        ]
                    },
                }
            ]
        }
    }
    bars, meta = parse_yahoo_chart(payload)
    assert meta["shortName"] == "Example"
    assert len(bars) == 1
    assert bars[0].close == 11
    assert bars[0].volume == 1000


def test_merge_fills_missing_volume_and_sessions():
    primary = [Bar(date(2026, 11, 19), 1, 1, 1, 1, None)]
    secondary = [
        Bar(date(2026, 11, 19), 9, 9, 9, 9, 50),
        Bar(date(2026, 11, 20), 2, 3, 1, 2, 80),
    ]
    merged = merge_bars(primary, secondary)
    assert merged[0].close == 1
    assert merged[0].volume == 50
    assert merged[1].day == date(2026, 11, 20)


def test_nasdaq_historical_parser():
    payload = {
        "data": {
            "tradesTable": {
                "rows": [
                    {
                        "date": "11/20/2026",
                        "open": "$10.00",
                        "high": "$12.00",
                        "low": "$9.50",
                        "close": "$11.25",
                        "volume": "1,500",
                    }
                ]
            }
        }
    }
    bars = parse_nasdaq_historical(payload)
    assert bars[0].day == date(2026, 11, 20)
    assert bars[0].close == 11.25
    assert bars[0].volume == 1500
