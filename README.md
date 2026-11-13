# Stock manager

A rules-based watchlist and paper-trading record. It checks a list of names against a breakout rule and a pullback rule, keeps a paper row for every flag, and sizes the same flags on a simulated cash account. An optional small test round can also compute a real-plan share count. The person who owns the account places every trade. This program never does.

Reports describe what the pre-set rules say (`meets the breakout rule; plan entry X, stop Y, target Z`). They are not investment advice.

This repository holds personal trading state: the watchlist, paper rows, the fill log, and the reports. Treat that as private information even though the repo is public. Do not commit broker passwords, statement account numbers, or API keys.

## Install

Python 3.11 or newer.

```bash
pip install -r requirements.txt
python -m pytest
```

Run every command from the repo root. Prices come from Yahoo Finance via `yfinance`, then a direct chart request, then Nasdaq's historical API. If those fail, the ticker is skipped. No price is filled in.

`STOCK_MANAGER_NOW` (ISO timestamp, interpreted in America/New_York if it has no zone) overrides the clock for a replay. `STOCK_MANAGER_ROOT` points the commands at another copy of the file store.

## Commands

Session-day commands do nothing on weekends and NYSE holidays (exit 0, no output, no file changes). After-close also waits until 16:05 ET, because it needs the official close.

| Command | What it does |
| --- | --- |
| `python -m src.cli after-close` | The daily engine. Fetches data, updates paper rows, the sim ledger, and the derived files, writes `reports/YYYY-MM-DD-after-close.md`, and prints that report. |
| `python -m src.cli after-close --session-date YYYY-MM-DD` | Same engine for one completed session, ignoring the clock. |
| `python -m src.cli midday` | Read-only. Prints a short heads-up when a level is close. Prints `NO_FLAGS` when nothing is. |
| `python -m src.cli late` | Same check, worded as the late-session pass. |
| `python -m src.cli market-open` | Read-only morning briefing on every session day. |
| `python -m src.cli health-check` | Audits the files and changes nothing. |
| `python -m src.cli reconcile path/to/statement.csv` | Read-only compare of an activity CSV with the fill log. PDF is not parsed. |
| `python -m src.cli watchlist-review` | Membership proposals only. The list is not edited. |
| `python -m src.cli add-ticker SYM "Chips & AI compute"` | Fetches a baseline and appends one name when the series includes the last completed session. |
| `python -m src.cli record-fill --date YYYY-MM-DD --ticker SYM --side Buy --shares N --price PX --commission 0 --other-costs 0` | Appends one fill that already happened and rebuilds `real_positions.csv`. `--side` is the log label `Buy` or `Sell`. `--signal-price` is required when no paper row matches. |
| `python -m src.cli is-trading-day` | Exit 0 when today's ET date is an NYSE session, otherwise exit 1. |

The fill-log column is named `Buy/Sell` because those are the two labels a broker confirmation uses. Reports do not use those words as instructions.

## File map

| Path | Role |
| --- | --- |
| `rules.md` | The standing rules, in short form. |
| `settings.json` | Account, sim, and rule parameters. |
| `data/watchlist.csv` | Names under review. Empty until one is added. |
| `data/paper_positions.csv` | One row per flagged setup. See `data/README.md`. |
| `data/trade_log.csv` | Fills the account holder reports. The daily check never writes this file. |
| `data/real_positions.csv` | Derived from the fill log. |
| `data/dashboard.json` | Derived counts, the market filter, and the test-round criteria. |
| `data/summary.md` | Derived front page. |
| `data/earnings_radar.csv` | Derived. Names with an earnings date inside 14 days. |
| `data/sim_ledger.json` | Derived sim cash ledger. |
| `data/deferred_bench.csv` | Overflow names. The review does not write it on its own. |
| `reports/` | Dated copies of command output. |
| `src/` | The engine. `tests/` covers the rule math with synthetic bars. |

Derived files are rebuilt by the engine, by `add-ticker`, and by `record-fill`. Edit settings and report fills through the commands.

## Clock

Times below are America/New_York. This repo does not install a scheduler.

| Check | When |
| --- | --- |
| Market open | 11:00, weekdays that are sessions |
| Mid-session | 13:14 |
| Late session | 15:15 |
| After close | 17:14 |
| Health check | Sunday 09:14 |
| Watchlist review | Sunday 10:14 |
| Statement reconcile | the 3rd of the month, 10:14, for the prior month |

NYSE full-day holidays for 2026 and 2027 are coded in `src/calendar_nyse.py`. An early close is still a session.

## Limits

- The breakout base is the 15 sessions before the latest bar. The stored 15-day range includes the latest bar. Both are described in `rules.md`.
- After five sessions the breakout flag stays Yes until a close under the base low during that window marks it Failed.
- Headlines, when a feed answers, are a short Yahoo Finance RSS pull. Consensus estimates and earnings results are not fetched; the report says so instead of inventing them.
- The weekly review audits names already on the list. It does not propose new companies, because it does not query a market-cap universe.
- A skipped plan is recorded by editing the paper row (status `Voided`, with the reason in Notes). There is no separate void command yet.
- Broker PDFs are not parsed. Activity CSV is.
