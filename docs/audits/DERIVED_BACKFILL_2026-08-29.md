# Derived line-item backfill — 2026-08-29

`derive_additional_line_items` only ever ran at ingestion time, so every row stored before it existed never got the derivation. The inputs were already in the database; the arithmetic had simply never been run over them.

Written as `ProvenanceTier.DERIVED` — computed from inputs that already pass `can_enter_valuation`, labelled as computed rather than reported, and never promoted to Reported. Each row's `first_available_date` is the LATEST of its inputs' (§6: it could not have been known before every component was public).

| line | rows | tickers |
|---|---|---|
| net_working_capital | 4819 | 196 |
| depreciation_and_amortisation | 1885 | 132 |
| change_in_net_working_capital | 1017 | 114 |
