# Rules

These are the standing rules for the watchlist and the paper record. Change a number only when that change is made on purpose in `settings.json`. The program applies the rules and reports what they say. It does not place trades, and it does not tell anyone what to do with a position.

Percent columns in the CSVs are percentage points (`8.00` means 8%). Rates in `settings.json` are fractions (`0.02` means 2%).

## Breakout

A breakout is a quiet base followed by a close that leaves it.

- The base is the 15 sessions before the session just closed. Its range is `(high − low) / midpoint`, and the base qualifies at 8% or less.
- The close must be above that base high, above the 50-session average, and above the 100-session average.
- Volume on that session must be at least 1.5 times the average volume of the prior 20 sessions. Missing volume means the breakout is not verified, so it is not flagged.
- New breakouts are flagged only when QQQ's own close is above QQQ's 50-session average. Pullbacks ignore that filter.
- The watchlist's 15-day range and Consolidating flag use the last 15 sessions including the latest close. That display window is not the breakout base. The base excludes the latest session so a close can sit above the base high.
- If the close falls under the stored base low on any of the next 5 sessions, the breakout flag becomes Failed. After those 5 sessions the flag stays Yes until it fails. There is no third state.
- A new breakout writes `Triggered YYYY-MM-DD` plus the base high and low into Notes.

## Pullback

A pullback tags the 50-session average and closes back above it with room to spare.

- The latest close is at least 0.5% above the 50-session average. The 0.5% test applies on the flag day only.
- At least one of the last 3 session lows is at or under the average plus 1%.
- If any of those 3 sessions closed below the average, the pattern is a snap-back, not a pullback, even when a later low tagged the average. That is a near-miss.
- A tag that closes less than 0.5% above the average is also a near-miss.
- A Yes flag becomes Failed when the close is below the 50-session average.

## Earnings

A new flag is skipped when the next earnings date falls on the signal day or on any of the next 5 calendar days. A date after a report does not skip. `N/A` (used for ETFs) never skips. An unknown date does not skip either; Notes get `earnings date unknown`. An existing position is never skipped because of earnings.

## One row when both fire

If breakout and pullback both flag on the same day, one paper row is opened. The setup label is Breakout and the stop is the breakout base low.

## Stops and the real plan

- Breakout stop = base low. Pullback stop = the 50-session average.
- Plan shares = `floor(account × risk % / (entry − stop))`, and also no more than `floor(account / entry)`.
- If one share costs more than the account, the flag and the paper row still exist, shares stay blank, and Notes get `Affordability: single share exceeds account — paper only`.
- If the risk formula rounds to zero shares, shares stay blank and Notes say the one share would risk more than the trade budget.
- Plan shares are filled only for triggers on or after the test-round start date. Earlier rows stay blank and are not sized later.
- Before filling shares, count open test positions (entry on or after the start date, shares filled, status Open or Half sold) and add up planned risk, using the capped share count times `(entry − stop)`. The caps are 3 open positions and 6% of the account. If the new plan would exceed either cap, shares stay blank and Notes get `Guardrail — paper only`. The flag and the paper row still exist.
- Circuit breaker: if realized plus unrealized result on real positions is at or below −20% of the account, new plan shares stay blank and Notes get `Circuit breaker — paper only`. Open positions are still tracked. The dollar field in settings is that 20% amount at the current account size.

## Exits on paper

- Entry is the trigger session's close. Target is `entry + 2 × (entry − stop)` using the original stop. The trail reference is the 20-session average.
- When the session high reaches the target, status becomes Half sold, the recorded stop moves to the entry, and the original stop stays in Notes.
- A Half sold row exits when the close is below the 20-session average, including on the half-sale day itself.
- An Open row exits when the close is below its stop.
- The blended result is `(exit − entry) / entry` when nothing was exited at the target. When half was exited at the target first, it is the average of the target result and the final exit result.
- The plain vs-entry figure on an exited row is only the final exit versus the entry. Performance stats use the blended result.

## Real-plan constraints

These do not change flags or paper rows.

- A 1-share plan exits the whole position at the target. A plan of 2 or more uses `floor(shares / 2)` for the partial.
- The documented next-session entry is at the price actually paid. Stop and target do not move. Full planned size stays within the risk budget at or under `stop + risk budget / planned shares`. The plan is unused above the stop–target midpoint, at or below the stop, or when one share would risk more than the trade budget. Between the full-size limit and the midpoint, the share count is cut. A price above the stop and below the signal is not a reason to increase the size.
- A GTC limit at the target is the documented way to carry out the target exit. Stops in this system are judged on the close. They are not live stop orders.
- Reports state these as facts of the plan.

## Simulation

The sim account is US$100,000, with 2% risk and a 25% concentration ceiling at entry. It starts on the test-round start date.

- Sim shares are the smaller of `floor(sim account × sim risk % / (entry − stop))` and `floor(ceiling % × sim account / entry)`.
- When the ceiling cuts the size, Notes record the trim.
- The position is funded only when its cost fits sim cash. Otherwise sim shares stay blank and Notes get `Sim skipped — capital cap` with the cost and the cash that was available.
- Cash starts at the sim account size. It falls by `sim shares × entry` and rises by half-sale proceeds (`sim shares × target / 2`) and by the remaining shares times the exit price. On one date the order is half sales, then exits, then entries, in file order. Cash is not allowed to go negative.
- The real-plan caps, the circuit breaker, and the gap rule do not apply to the sim.
- Sim result, written at exit, is `sim shares × entry × blended result` (the blended figure as a fraction). Judge the sim on return percent.

## Watchlist

Ten themes: Biotech & healthcare; Chips & AI compute; AI infrastructure, data centres & networking; Software, security & platforms; Power, nuclear & grid; Big Tech, consumer & index; Financials; Energy; Defense & aerospace; Minerals & metals.

A name is added only when that is asked for. The weekly review may propose additions and structural removals. It does not change the list. Nothing is removed for one bad week, or while a paper position in that name is open.

## Test round

The round ends at the first 10 closed real trades or on 2026-12-31, whichever comes first. The stored criteria live in `data/dashboard.json`. Beating QQQ over that window is the score for the round, not a view on holding QQQ.

## Data

A missing price, average, or date is left missing. If a ticker cannot be fetched, its row stays as it was and the report says so. Unknown volume is the word `Unknown`.

## Reports

The after-close report is written on every session day. Mid-session and late-session notes are written only when something is flagged. Wording stays factual.
