"""Task 9 (brief §9) — the paper portfolio: real friction (limit x
1.0112 + Amihud slippage), real tax (the configured CGT parameter, §0.5
D2 — 0% now, unconfirmed, read from System settings, never hardcoded),
15% dividend WHT. Runs in parallel with normal platform use once gates
pass, not as a delay after the build (§0.5 D3). Promotion to live
capital blocked until 2 quarters AND 8 positions AND live-vs-backtest
ratio >= 0.5 — all three, no partial credit. Not yet implemented."""
