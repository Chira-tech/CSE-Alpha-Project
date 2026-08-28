# OI-4 full-scope re-verification sweep

Generated: 2026-08-28T05:46:57+00:00Z

Closes OI-4's own named gap (docs/audits/R1_OPEN_ISSUES.md): OI-1's sweep only ever checked 8 named statement lines with a crude `abs(value) < 100,000` filter. This sweep uses `check_magnitude_plausibility` instead — every statement line, self-scaled to each filing's own largest extracted value — so it measures the FULL scope for the first time, not a sample.

160 candidate rows across 100 distinct filings, re-verified against today's live source PDFs using today's unmodified extraction pipeline.

- **Confirmed still wrong (`stale_or_wrong`): 2** — today's pipeline produces a DIFFERENT value than what's stored. These are the real, currently-actionable rows.
- Stored value matches a fresh re-extraction (`confirmed_correct`): 153 — the stored figure IS what today's pipeline would produce (a genuine, tiny-but-real figure the magnitude check correctly left alone via `check_accounting_identities` never even needing to fire, or a value already fixed by a prior remediation pass).
- Unverifiable: 5 — network/parse failure or the line no longer matches on re-extraction; needs manual follow-up, not silently one or the other.

## Rows confirmed still wrong (act on these)

| Ticker | Line | Period | Stored | Fresh (today's pipeline) |
|---|---|---|---|---|
| AHPL.N0000 | total_interest_bearing_debt | 2022-05-23 | 52,000.0000 | 26,252,736,000 |
| AHPL.N0000 | total_interest_bearing_debt | 2023-05-23 | 48,000.0000 | 24,246,477,000 |

## Unverifiable (needs manual follow-up)

| Ticker | Line | Period | Stored | Detail |
|---|---|---|---|---|
| BFN.N0000 | income_tax_expense | 2020-03-31 | 12.0000 | current pipeline found no matching line on any primary-statement page |
| CALI.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| CALC.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| WLTH.N0000 | income_tax_expense | 2026-06-30 | 7.0000 | current pipeline found no matching line on any primary-statement page |
| CALU.U0000 | income_tax_expense | 2026-03-31 | 4.0000 | current pipeline found no matching line on any primary-statement page |