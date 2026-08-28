# OI-4 full-scope re-verification sweep

Generated: 2026-08-28T01:21:55+00:00Z

Closes OI-4's own named gap (docs/audits/R1_OPEN_ISSUES.md): OI-1's sweep only ever checked 8 named statement lines with a crude `abs(value) < 100,000` filter. This sweep uses `check_magnitude_plausibility` instead — every statement line, self-scaled to each filing's own largest extracted value — so it measures the FULL scope for the first time, not a sample.

235 candidate rows across 142 distinct filings, re-verified against today's live source PDFs using today's unmodified extraction pipeline.

- **Confirmed still wrong (`stale_or_wrong`): 19** — today's pipeline produces a DIFFERENT value than what's stored. These are the real, currently-actionable rows.
- Stored value matches a fresh re-extraction (`confirmed_correct`): 211 — the stored figure IS what today's pipeline would produce (a genuine, tiny-but-real figure the magnitude check correctly left alone via `check_accounting_identities` never even needing to fire, or a value already fixed by a prior remediation pass).
- Unverifiable: 5 — network/parse failure or the line no longer matches on re-extraction; needs manual follow-up, not silently one or the other.

## Rows confirmed still wrong (act on these)

| Ticker | Line | Period | Stored | Fresh (today's pipeline) |
|---|---|---|---|---|
| LOFC.N0000 | depreciation_expense | 2014-06-30 | 1,682.0000 | -1,682,000 |
| SCAP.N0000 | total_comprehensive_income | 2021-06-30 | 3.0000 | 21,884,617 |
| RFL.N0000 | revenue | 2017-03-31 | 1.0000 | 125,333,863 |
| RFL.N0000 | revenue | 2021-03-31 | 1.0000 | 14,024,885 |
| RFL.N0000 | revenue | 2022-03-31 | 4.0000 | 47,564,705 |
| RFL.N0000 | revenue | 2023-03-31 | 1.0000 | 122,303,385 |
| MHDL.N0000 | interest_expense | 2024-03-31 | 8.0000 | -135,251,134 |
| RIL.N0000 | net_income | 2018-12-31 | 15,000.0000 | 80,015,000 |
| CHMX.N0000 | revenue | 2018-06-30 | 1,000.0000 | 107,573,000 |
| RHTL.N0000 | total_interest_bearing_debt | 2013-03-31 | 1,000.0000 | 296,711,000 |
| HUNA.N0000 | revenue | 2022-03-31 | 2.0000 | 225,748,672 |
| REEF.N0000 | revenue | 2015-12-31 | 3,000.0000 | 323,398,000 |
| STAF.N0000 | net_income | 2020-12-31 | 1,000.0000 | 21,000 |
| LLUB.N0000 | interest_expense | 2015-09-30 | 3,000.0000 | -33,000 |
| LLUB.N0000 | interest_expense | 2016-03-31 | 1,000.0000 | -21,000 |
| LLUB.N0000 | interest_expense | 2016-06-30 | 1,000.0000 | 0 |
| JKL.N0000 | net_income | 2024-07-29 | 2.0000 | 3,405 |
| PHAR.N0000 | revenue | 2013-03-31 | 9.0000 | 90,472,176 |
| RWSL.N0000 | profit_before_tax | 2025-03-31 | 4.0000 | 494,721,426 |

## Unverifiable (needs manual follow-up)

| Ticker | Line | Period | Stored | Detail |
|---|---|---|---|---|
| BFN.N0000 | income_tax_expense | 2020-03-31 | 12.0000 | current pipeline found no matching line on any primary-statement page |
| CALI.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| CALC.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| WLTH.N0000 | income_tax_expense | 2026-06-30 | 7.0000 | current pipeline found no matching line on any primary-statement page |
| CALU.U0000 | income_tax_expense | 2026-03-31 | 4.0000 | current pipeline found no matching line on any primary-statement page |