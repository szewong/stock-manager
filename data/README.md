# Paper positions

Each row is one triggered setup tracked on paper. The signal columns are not a holding and not shares owned.

`Shares` is the real test plan only: the share count the account's own rules produced for the small test round. Blank means the row is paper only. Real executions live in `trade_log.csv`. `real_positions.csv` is rebuilt from that log; if the two disagree, the log wins.

`Sim Shares` and `Sim result (US$)` are the simulation only. The same setup is sized on the settings sim account, then trimmed to the concentration ceiling, and funded only when the cost fits sim cash. Otherwise those columns stay blank and Notes say the capital cap skipped it.

The program does not place trades. Nothing in this folder is an order.
