"""Task 7 (brief §7) — a playbook's status transitions
(Registered -> Backtested -> HoldoutReplayed -> Shadow -> Validated /
AwaitingHistory / Retired). PB-04 Regime Rotation is expected to reach
`AWAITING_HISTORY` and stop there (§0.5 D1(e)) — this module is what
would hold that state, not something to work around by tuning PB-04
until it passes (brief §11's own explicit "do not" list). Not yet
implemented."""
