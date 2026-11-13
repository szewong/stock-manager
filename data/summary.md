# Stock watchlist

A rules record of one person's watchlist, paper positions, and an optional small test round.
This is not investment advice. The program does not place trades.
Figures below are computed from the other files in `data/`.

## Market status

- QQQ close: n/a
- QQQ MA50: n/a
- QQQ vs MA50: n/a
- Breakout filter: n/a
- Names watched: 0
- Open paper positions: 0

## Signal record

- Exited paper positions: 0
- Win rate: n/a
- Average blended result: n/a
- Median blended result: n/a

## Simulation

- Sim total result: US$0.00
- Sim return: 0.00%
- Sim positions open: 0
- Sim positions closed: 0

## Real test record

- Account size: US$750.00
- Orders logged: 0
- Entry fills: 0
- Exit fills: 0
- IB cash: n/a

## Simulation by position

No simulation results yet.

## Open paper positions

No open paper positions.

## Earnings radar

None within 14 days.

## How it works

The watchlist is checked against two patterns: a 15-session breakout and an MA50 pullback.
Every flag that clears the earnings filter opens a paper row. A separate simulation sizes the same flags inside a cash ledger.
Real-plan share counts are filled only inside the test round, and only when the position cap, the risk cap, and the circuit breaker all still have room.
Reports describe those rules. They are not instructions, and nothing in this repo sends an order.
