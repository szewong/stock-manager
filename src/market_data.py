"""Daily bars and quotes. Primary source, then two HTTP fallbacks, then a snapshot.

No price is invented. A failed lookup returns an error string and empty bars.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from src.calendar_nyse import ET, last_completed_session, now_et
from src.rules import Bar

_UA = "stock-manager/1.0 (research; +https://localhost)"
_TIMEOUT = 15


@dataclass
class HistoryResult:
    symbol: str
    bars: list[Bar] = field(default_factory=list)
    error: str | None = None
    source: str = ""
    company: str | None = None
    quote_type: str | None = None
    volume_unknown: bool = False


@dataclass
class QuoteResult:
    symbol: str
    price: float | None = None
    previous_close: float | None = None
    error: str | None = None


@dataclass
class NewsItem:
    symbol: str
    title: str
    link: str
    source: str


class MarketData(Protocol):
    def history(self, symbol: str) -> HistoryResult: ...

    def quote(self, symbol: str) -> QuoteResult: ...

    def earnings_date(self, symbol: str, quote_type: str | None = None) -> str | None: ...

    def company_name(self, symbol: str) -> str | None: ...

    def news(self, symbols: list[str]) -> tuple[list[NewsItem], str | None]: ...


def _request(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urlopen(req, timeout=_TIMEOUT) as response:
        return response.read()


def _stamp_to_session(ts: int) -> date:
    moment = datetime.fromtimestamp(int(ts), ZoneInfo("UTC")).astimezone(ET)
    return moment.date()


def parse_yahoo_chart(payload: dict) -> tuple[list[Bar], dict]:
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        error = chart.get("error") or {}
        raise ValueError(error.get("description") or "empty chart")
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    bars: list[Bar] = []
    for index, ts in enumerate(stamps):
        close = closes[index] if index < len(closes) else None
        if close is None:
            continue
        volume = volumes[index] if index < len(volumes) else None
        bars.append(
            Bar(
                day=_stamp_to_session(ts),
                open=float(opens[index] if index < len(opens) and opens[index] is not None else close),
                high=float(highs[index] if index < len(highs) and highs[index] is not None else close),
                low=float(lows[index] if index < len(lows) and lows[index] is not None else close),
                close=float(close),
                volume=None if volume is None else float(volume),
            )
        )
    bars.sort(key=lambda bar: bar.day)
    dedup: dict[date, Bar] = {}
    for bar in bars:
        dedup[bar.day] = bar
    return [dedup[day] for day in sorted(dedup)], meta


def _parse_nasdaq_number(text: object) -> float | None:
    if text is None:
        return None
    cleaned = str(text).replace("$", "").replace(",", "").strip()
    if cleaned in ("", "N/A", "--"):
        return None
    return float(cleaned)


def parse_nasdaq_historical(payload: dict) -> list[Bar]:
    data = payload.get("data") or {}
    table = data.get("tradesTable") or data.get("table") or {}
    rows = table.get("rows") or []
    bars: list[Bar] = []
    for row in rows:
        raw_date = row.get("date") or row.get("Date")
        if not raw_date:
            continue
        try:
            day = datetime.strptime(str(raw_date).strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        close = _parse_nasdaq_number(row.get("close") or row.get("Close"))
        if close is None:
            continue
        bars.append(
            Bar(
                day=day,
                open=_parse_nasdaq_number(row.get("open") or row.get("Open")) or close,
                high=_parse_nasdaq_number(row.get("high") or row.get("High")) or close,
                low=_parse_nasdaq_number(row.get("low") or row.get("Low")) or close,
                close=close,
                volume=_parse_nasdaq_number(row.get("volume") or row.get("Volume")),
            )
        )
    bars.sort(key=lambda bar: bar.day)
    return bars


def merge_bars(primary: list[Bar], secondary: list[Bar]) -> list[Bar]:
    """Prefer primary OHLC. Fill a missing session or a missing volume from secondary."""
    combined: dict[date, Bar] = {bar.day: bar for bar in primary}
    for bar in secondary:
        current = combined.get(bar.day)
        if current is None:
            combined[bar.day] = bar
        elif current.volume is None and bar.volume is not None:
            combined[bar.day] = Bar(
                bar.day, current.open, current.high, current.low, current.close, bar.volume
            )
    if not combined:
        return []
    frame = pd.DataFrame(
        {
            "open": [combined[day].open for day in sorted(combined)],
            "high": [combined[day].high for day in sorted(combined)],
            "low": [combined[day].low for day in sorted(combined)],
            "close": [combined[day].close for day in sorted(combined)],
            "volume": [
                combined[day].volume if combined[day].volume is not None else float("nan")
                for day in sorted(combined)
            ],
        },
        index=pd.to_datetime(sorted(combined)),
    )
    bars: list[Bar] = []
    for stamp, row in frame.iterrows():
        volume = row["volume"]
        bars.append(
            Bar(
                day=stamp.date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=None if pd.isna(volume) else float(volume),
            )
        )
    return bars


def _yahoo_history(symbol: str) -> tuple[list[Bar], dict]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?interval=1d&range=2y&includeAdjustedClose=false"
    )
    payload = json.loads(_request(url).decode("utf-8"))
    return parse_yahoo_chart(payload)


def _nasdaq_history(symbol: str) -> list[Bar]:
    today = now_et().date()
    start = date(today.year - 2, today.month, min(today.day, 28))
    url = (
        "https://api.nasdaq.com/api/quote/"
        f"{symbol}/historical?assetclass=stocks"
        f"&fromdate={start.isoformat()}&todate={today.isoformat()}&limit=9999"
    )
    payload = json.loads(_request(url).decode("utf-8"))
    return parse_nasdaq_historical(payload)


def _yfinance_history(symbol: str) -> tuple[list[Bar], str | None, str | None]:
    import yfinance as yf

    frame = yf.download(
        symbol,
        period="2y",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    company = None
    quote_type = None
    if frame is None or len(frame) == 0:
        return [], company, quote_type
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    bars: list[Bar] = []
    for stamp, row in frame.iterrows():
        close = row.get("Close")
        if close is None or pd.isna(close):
            continue
        day = stamp.date() if hasattr(stamp, "date") else stamp
        volume = row.get("Volume")
        bars.append(
            Bar(
                day=day,
                open=float(row["Open"]) if not pd.isna(row.get("Open")) else float(close),
                high=float(row["High"]) if not pd.isna(row.get("High")) else float(close),
                low=float(row["Low"]) if not pd.isna(row.get("Low")) else float(close),
                close=float(close),
                volume=None if volume is None or pd.isna(volume) else float(volume),
            )
        )
    bars.sort(key=lambda bar: bar.day)
    try:
        info = yf.Ticker(symbol).info or {}
        company = info.get("shortName") or info.get("longName")
        quote_type = info.get("quoteType")
    except Exception:
        pass
    return bars, company, quote_type


def _stale(bars: list[Bar]) -> bool:
    if not bars:
        return True
    return bars[-1].day < last_completed_session()


class YFinanceClient:
    def history(self, symbol: str) -> HistoryResult:
        symbol = symbol.strip().upper()
        errors: list[str] = []
        bars: list[Bar] = []
        company = None
        quote_type = None
        source = ""
        try:
            bars, company, quote_type = _yfinance_history(symbol)
            source = "yfinance"
        except Exception as exc:  # network or parser failure
            errors.append(f"yfinance: {exc}")

        needs_fill = (not bars) or _stale(bars) or (bars and bars[-1].volume is None)
        if needs_fill:
            try:
                yahoo_bars, meta = _yahoo_history(symbol)
                company = company or meta.get("shortName") or meta.get("longName")
                quote_type = quote_type or meta.get("instrumentType")
                bars = merge_bars(bars, yahoo_bars)
                source = (source + "+yahoo").strip("+")
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"yahoo chart: {exc}")
            except Exception as exc:
                errors.append(f"yahoo chart: {exc}")

        if (not bars) or _stale(bars) or (bars and bars[-1].volume is None):
            try:
                nasdaq_bars = _nasdaq_history(symbol)
                bars = merge_bars(bars, nasdaq_bars)
                source = (source + "+nasdaq").strip("+")
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"nasdaq: {exc}")
            except Exception as exc:
                errors.append(f"nasdaq: {exc}")

        if not bars:
            quote = self.quote(symbol)
            if quote.price is not None:
                return HistoryResult(
                    symbol=symbol,
                    bars=[],
                    error="candle series unavailable; quote snapshot is not used as a daily bar",
                    source="quote",
                    company=company,
                    quote_type=quote_type,
                    volume_unknown=True,
                )
            detail = "; ".join(errors) if errors else "no data"
            return HistoryResult(symbol=symbol, error=detail, company=company, quote_type=quote_type)

        return HistoryResult(
            symbol=symbol,
            bars=bars,
            error=None,
            source=source or "unknown",
            company=company,
            quote_type=quote_type,
            volume_unknown=bars[-1].volume is None,
        )

    def quote(self, symbol: str) -> QuoteResult:
        symbol = symbol.strip().upper()
        try:
            _, meta = _yahoo_history(symbol)
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price is not None:
                return QuoteResult(
                    symbol=symbol,
                    price=float(price),
                    previous_close=None if prev is None else float(prev),
                )
        except Exception:
            pass
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = getattr(ticker, "fast_info", None)
            price = None
            prev = None
            if info is not None:
                price = getattr(info, "last_price", None) or info.get("lastPrice") if hasattr(info, "get") else None
                prev = getattr(info, "previous_close", None)
            if price is None:
                hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
                if hist is not None and len(hist):
                    price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev = float(hist["Close"].iloc[-2])
            if price is not None:
                return QuoteResult(
                    symbol=symbol,
                    price=float(price),
                    previous_close=None if prev is None else float(prev),
                )
        except Exception as exc:
            return QuoteResult(symbol=symbol, error=str(exc))
        return QuoteResult(symbol=symbol, error="quote unavailable")

    def earnings_date(self, symbol: str, quote_type: str | None = None) -> str | None:
        if quote_type and quote_type.upper() in {"ETF", "INDEX", "MUTUALFUND"}:
            return "N/A"
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol.strip().upper())
            info = {}
            try:
                info = ticker.info or {}
            except Exception:
                info = {}
            if str(info.get("quoteType", "")).upper() in {"ETF", "INDEX", "MUTUALFUND"}:
                return "N/A"
            calendar = {}
            try:
                calendar = ticker.calendar or {}
            except Exception:
                calendar = {}
            raw = None
            if isinstance(calendar, dict):
                raw = calendar.get("Earnings Date") or calendar.get("earningsDate")
            if isinstance(raw, (list, tuple)) and raw:
                raw = raw[0]
            if hasattr(raw, "date"):
                return raw.date().isoformat() if hasattr(raw, "date") and not isinstance(raw, date) else raw.isoformat()
            if isinstance(raw, date):
                return raw.isoformat()
            frame = None
            try:
                frame = ticker.earnings_dates
            except Exception:
                frame = None
            if frame is not None and len(frame):
                today = now_et().date()
                upcoming = []
                for stamp in frame.index:
                    day = stamp.date() if hasattr(stamp, "date") else stamp
                    if day >= today:
                        upcoming.append(day)
                if upcoming:
                    return min(upcoming).isoformat()
        except Exception:
            return None
        return None

    def company_name(self, symbol: str) -> str | None:
        history = self.history(symbol)
        return history.company

    def news(self, symbols: list[str]) -> tuple[list[NewsItem], str | None]:
        import xml.etree.ElementTree as ET

        items: list[NewsItem] = []
        errors = 0
        for symbol in symbols[:8]:
            url = (
                "https://feeds.finance.yahoo.com/rss/2.0/headline"
                f"?s={symbol}&region=US&lang=en-US"
            )
            try:
                payload = _request(url)
                root = ET.fromstring(payload)
            except Exception:
                errors += 1
                continue
            for node in root.findall(".//item")[:3]:
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                if title:
                    items.append(NewsItem(symbol=symbol, title=title, link=link, source="Yahoo Finance"))
        if not items and errors:
            return [], "news fetch failed"
        return items, None


def bars_for_session(bars: list[Bar], session: date) -> list[Bar] | None:
    trimmed = [bar for bar in bars if bar.day <= session]
    if not trimmed or trimmed[-1].day != session:
        return None
    return trimmed
