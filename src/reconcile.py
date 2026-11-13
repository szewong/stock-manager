"""Read-only comparison of a broker activity CSV with the trade log.

PDF files are not parsed. Missing columns are reported, not guessed.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from src.state import load_fills


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _parse_date(text: str) -> date | None:
    text = (text or "").strip().strip(",")
    if not text:
        return None
    token = text.split(" ")[0].split(",")[0].strip()
    if len(token) >= 10 and token[4] == "-" and token[7] == "-":
        try:
            return date.fromisoformat(token[:10])
        except ValueError:
            return None
    parts = token.replace("-", "/").split("/")
    if len(parts) == 3:
        try:
            if len(parts[0]) == 4:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
        except ValueError:
            return None
    return None


def _num(text: str) -> float | None:
    cleaned = (text or "").replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()
    if cleaned in ("", "--"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _side(text: str) -> str | None:
    token = (text or "").strip().upper()
    if token in {"BUY", "BOT", "B"}:
        return "entry"
    if token in {"SELL", "SLD", "S"}:
        return "exit"
    return None


def _rows_from_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    sample = text.splitlines()
    if not sample:
        return [], ["statement file is empty"]
    # Interactive Brokers multi-section activity files repeat a header per section.
    if sample[0].split(",")[0].strip() in {"Trades", "Statement", "Positions"} or (
        len(sample) > 1 and "DataDiscriminator" in sample[0]
    ):
        return _ib_sections(text)
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader], []


def _ib_sections(text: str) -> tuple[list[dict[str, str]], list[str]]:
    notes: list[str] = []
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    section = ""
    for raw in csv.reader(text.splitlines()):
        if not raw or not any(cell.strip() for cell in raw):
            continue
        kind = raw[0].strip()
        if len(raw) < 3:
            continue
        marker = raw[1].strip()
        if marker == "Header":
            section = kind
            header = [cell.strip() for cell in raw[2:]]
            continue
        if marker != "Data" or not header:
            continue
        values = raw[2:]
        record = {header[i]: values[i].strip() if i < len(values) else "" for i in range(len(header))}
        record["_section"] = section
        rows.append(record)
    if not rows:
        notes.append("no Data rows found in the statement")
    return rows, notes


_ALIASES = {
    "symbol": ("symbol", "ticker", "underlying"),
    "date": ("date", "tradedate", "date/time", "datetime", "trade date"),
    "side": ("buy/sell", "side", "action", "code"),
    "shares": ("quantity", "shares", "qty"),
    "price": ("price", "tradeprice", "t. price", "trade price"),
    "commission": ("commission", "ibcommission", "comm/fee", "comm"),
    "fees": ("fees", "tax", "taxes", "other fees"),
}


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    folded = {key.lower().strip(): value for key, value in row.items()}
    for name in names:
        if name in folded and folded[name] != "":
            return folded[name]
    return ""


def parse_statement(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        return {"error": "PDF statements are not parsed. Export the same statement as CSV."}
    if not path.exists():
        return {"error": f"No statement file at {path}. Export the activity statement as CSV and pass that path. Figures are not guessed."}
    try:
        raw_rows, notes = _rows_from_csv(path)
    except Exception as exc:
        return {"error": f"Could not read {path.name}: {exc}. Figures are not guessed."}
    trades = []
    positions = []
    for row in raw_rows:
        section = row.get("_section", "Trades")
        symbol = _pick(row, _ALIASES["symbol"]).upper()
        if not symbol or symbol in {"TOTAL", "SUBTOTAL"}:
            continue
        if section.lower().startswith("position") or "quantity" in {k.lower() for k in row} and "price" not in {k.lower() for k in row}:
            qty = _num(_pick(row, _ALIASES["shares"]))
            if qty is not None:
                positions.append({"symbol": symbol, "shares": qty})
            continue
        side = _side(_pick(row, _ALIASES["side"]))
        when = _parse_date(_pick(row, _ALIASES["date"]))
        shares = _num(_pick(row, _ALIASES["shares"]))
        price = _num(_pick(row, _ALIASES["price"]))
        if side and when and shares is not None and price is not None:
            trades.append(
                {
                    "date": when,
                    "symbol": symbol,
                    "side": side,
                    "shares": abs(int(round(shares))),
                    "price": round(price, 2),
                    "commission": abs(_num(_pick(row, _ALIASES["commission"])) or 0.0),
                    "fees": abs(_num(_pick(row, _ALIASES["fees"])) or 0.0),
                }
            )
        elif section.lower().startswith("position"):
            qty = _num(_pick(row, _ALIASES["shares"]))
            if qty is not None:
                positions.append({"symbol": symbol, "shares": qty})
    return {"trades": trades, "positions": positions, "notes": notes, "error": None}


def _side_label(side: str) -> str:
    return "entry" if side == "Buy" else "exit"


def reconcile_statement(root: Path, statement: Path, today: date | None = None) -> str:
    today = today or date.today()
    if today.month == 1:
        target_year, target_month = today.year - 1, 12
    else:
        target_year, target_month = today.year, today.month - 1
    parsed = parse_statement(statement)
    if parsed.get("error") and not statement.exists():
        return parsed["error"]
    if parsed.get("error"):
        return parsed["error"]

    statement_trades = parsed["trades"]
    if statement_trades:
        target_year = statement_trades[0]["date"].year
        target_month = statement_trades[0]["date"].month
    month_name = date(target_year, target_month, 1).strftime("%B %Y")
    end = _month_end(target_year, target_month)
    fills = [
        fill
        for fill in load_fills(root)
        if fill.day and fill.day.year == target_year and fill.day.month == target_month
    ]
    # Holdings through month-end, from the whole log.
    nets: dict[str, int] = {}
    for fill in load_fills(root):
        if fill.day and fill.day <= end:
            sign = 1 if fill.side == "Buy" else -1
            nets[fill.ticker] = nets.get(fill.ticker, 0) + sign * fill.shares
    open_during = bool(fills) or any(shares > 0 for shares in nets.values())
    if not open_during and not statement_trades:
        return f"No real executions to reconcile for {month_name}."

    log_key = {}
    for fill in fills:
        key = (fill.day, fill.ticker, _side_label(fill.side), int(fill.shares), round(fill.price, 2))
        log_key[key] = log_key.get(key, 0) + 1
    stmt_key = {}
    for trade in statement_trades:
        if trade["date"].year != target_year or trade["date"].month != target_month:
            continue
        key = (trade["date"], trade["symbol"], trade["side"], trade["shares"], trade["price"])
        stmt_key[key] = stmt_key.get(key, 0) + 1

    mismatches = []
    for key, count in sorted(log_key.items(), key=lambda item: (item[0][0], item[0][1])):
        other = stmt_key.get(key, 0)
        if other != count:
            day, ticker, side, shares, price = key
            mismatches.append(
                f"{ticker} {day.isoformat()} {side} {shares} @ {price:.2f}: log {count}, statement {other}"
            )
    for key, count in sorted(stmt_key.items(), key=lambda item: (item[0][0], item[0][1])):
        if key not in log_key:
            day, ticker, side, shares, price = key
            mismatches.append(
                f"{ticker} {day.isoformat()} {side} {shares} @ {price:.2f}: log 0, statement {count}"
            )

    log_comm = round(sum(fill.commission for fill in fills), 2)
    stmt_comm = round(sum(trade["commission"] for trade in statement_trades if trade["date"].year == target_year and trade["date"].month == target_month), 2)
    log_fees = round(sum(fill.other_costs for fill in fills), 2)
    stmt_fees = round(sum(trade["fees"] for trade in statement_trades if trade["date"].year == target_year and trade["date"].month == target_month), 2)
    if abs(log_comm - stmt_comm) > 0.05:
        mismatches.append(f"commissions: log US${log_comm:.2f}, statement US${stmt_comm:.2f}")
    if abs(log_fees - stmt_fees) > 0.05:
        mismatches.append(f"other costs: log US${log_fees:.2f}, statement US${stmt_fees:.2f}")

    if parsed["positions"]:
        stmt_pos = {}
        for item in parsed["positions"]:
            stmt_pos[item["symbol"]] = stmt_pos.get(item["symbol"], 0) + int(round(item["shares"]))
        symbols = set(nets) | set(stmt_pos)
        for symbol in sorted(symbols):
            log_shares = nets.get(symbol, 0)
            other = stmt_pos.get(symbol, 0)
            if log_shares != other:
                mismatches.append(f"holding {symbol}: log {log_shares}, statement {other}")
    else:
        mismatches.append("Month-end positions were not in the file; holdings were not compared.")

    notes = list(parsed.get("notes") or [])
    notes.append("Cash identity was not in the file; it was not guessed.")
    header = f"Reconciliation — {month_name}"
    if any(not line.startswith("Month-end") and not line.startswith("Cash identity") for line in mismatches):
        # Position/cash gaps are disclosures, not by themselves a mismatch of orders,
        # but a missing positions section is called out. Order mismatches set the verdict.
        order_issues = [line for line in mismatches if not line.startswith("Month-end") and not line.startswith("Cash")]
        fee_issues = [line for line in mismatches if line.startswith("commissions") or line.startswith("other costs") or line.startswith("holding")]
        verdict = "Discrepancies found" if order_issues or fee_issues else "Reconciled — log matches statement"
    else:
        verdict = "Reconciled — log matches statement" if not any(line.startswith("holding") for line in mismatches) else "Discrepancies found"
    # If the only extra lines are the two disclosures, call it reconciled when orders match.
    substantive = [
        line
        for line in mismatches
        if not line.startswith("Month-end") and not line.startswith("Cash identity")
    ]
    if not substantive:
        verdict = "Reconciled — log matches statement"
    else:
        verdict = "Discrepancies found"
    lines = [header, verdict, ""]
    if substantive:
        lines.extend(f"- {line}" for line in substantive)
    else:
        lines.append("Orders, commissions, and other costs match within tolerance.")
    lines.extend(notes)
    lines.append("Record-keeping only. No order was placed.")
    return "\n".join(lines) + "\n"
