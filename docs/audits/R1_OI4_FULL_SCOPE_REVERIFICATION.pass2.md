# OI-4 full-scope re-verification sweep

Generated: 2026-08-28T05:25:10+00:00Z

Closes OI-4's own named gap (docs/audits/R1_OPEN_ISSUES.md): OI-1's sweep only ever checked 8 named statement lines with a crude `abs(value) < 100,000` filter. This sweep uses `check_magnitude_plausibility` instead — every statement line, self-scaled to each filing's own largest extracted value — so it measures the FULL scope for the first time, not a sample.

216 candidate rows across 125 distinct filings, re-verified against today's live source PDFs using today's unmodified extraction pipeline.

- **Confirmed still wrong (`stale_or_wrong`): 58** — today's pipeline produces a DIFFERENT value than what's stored. These are the real, currently-actionable rows.
- Stored value matches a fresh re-extraction (`confirmed_correct`): 153 — the stored figure IS what today's pipeline would produce (a genuine, tiny-but-real figure the magnitude check correctly left alone via `check_accounting_identities` never even needing to fire, or a value already fixed by a prior remediation pass).
- Unverifiable: 5 — network/parse failure or the line no longer matches on re-extraction; needs manual follow-up, not silently one or the other.

## Rows confirmed still wrong (act on these)

| Ticker | Line | Period | Stored | Fresh (today's pipeline) |
|---|---|---|---|---|
| COCR.N0000 | inventories | 2020-09-30 | 7,612.0000 | 90,007,612 |
| RFL.N0000 | inventories | 2021-03-31 | 9.0000 | 904,865 |
| RFL.N0000 | revaluation_reserves | 2025-03-31 | 3.0000 | 319,516,164 |
| PACK.N0000 | revenue | 2023-03-31 | 1.0000 | 13,451,044,424 |
| AGPL.N0000 | inventories | 2024-09-30 | 9,000.0000 | 994,639,000 |
| AGPL.N0000 | inventories | 2025-09-30 | 9,000.0000 | 960,957,000 |
| AGPL.N0000 | inventories | 2026-03-31 | 8,000.0000 | 874,447,000 |
| CINS.N0000 | trade_payables | 2015-12-31 | 27,000.0000 | 274,479,612,000 |
| CINS.X0000 | trade_payables | 2015-12-31 | 27,000.0000 | 274,479,612,000 |
| CINS.N0000 | trade_payables | 2019-12-31 | 28,000.0000 | 288,282,036,000 |
| CINS.X0000 | trade_payables | 2019-12-31 | 28,000.0000 | 288,282,036,000 |
| CINS.N0000 | trade_payables | 2023-12-31 | 28,000.0000 | 2,814,488,422,000 |
| CINS.X0000 | trade_payables | 2023-12-31 | 28,000.0000 | 2,814,488,422,000 |
| CHMX.N0000 | revenue | 2026-03-31 | 2,000.0000 | 267,624,000 |
| HAYL.N0000 | revenue | 2021-03-31 | 2,000.0000 | 241,275,661,000 |
| RHTL.N0000 | trade_payables | 2021-03-31 | 4.0000 | 44,233,782 |
| RHTL.N0000 | trade_receivables | 2021-03-31 | 1.0000 | 16,396,281 |
| SHOT.N0000 | inventories | 2020-03-31 | 3,000.0000 | 37,890,000 |
| SHOT.N0000 | total_interest_bearing_debt | 2020-03-31 | 1,000.0000 | 128,237,000 |
| SHOT.N0000 | trade_payables | 2020-03-31 | 3,000.0000 | 343,044,000 |
| SHOT.N0000 | trade_receivables | 2020-03-31 | 3,000.0000 | 306,895,000 |
| SHOT.X0000 | inventories | 2020-03-31 | 3,000.0000 | 37,890,000 |
| SHOT.X0000 | total_interest_bearing_debt | 2020-03-31 | 1,000.0000 | 128,237,000 |
| SHOT.X0000 | trade_payables | 2020-03-31 | 3,000.0000 | 343,044,000 |
| SHOT.X0000 | trade_receivables | 2020-03-31 | 3,000.0000 | 306,895,000 |
| SHOT.N0000 | amortisation_expense | 2021-06-30 | 2,000.0000 | 602,000 |
| SHOT.X0000 | amortisation_expense | 2021-06-30 | 2,000.0000 | 602,000 |
| ONAL.N0000 | trade_payables | 2024-03-31 | 1.0000 | 109,488,202 |
| ONAL.N0000 | trade_receivables | 2024-03-31 | 7.0000 | 79,027,391 |
| ABAN.N0000 | trade_payables | 2013-03-31 | 3.0000 | 324,493,222 |
| AHPL.N0000 | inventories | 2022-05-23 | 20,000.0000 | 20,204,587,000 |
| AHPL.N0000 | revaluation_reserves | 2022-05-23 | 25,000.0000 | 2,523,093,391,000 |
| AHPL.N0000 | trade_payables | 2022-05-23 | 29,000.0000 | 291,020,667,000 |
| AHPL.N0000 | trade_receivables | 2022-05-23 | 21,000.0000 | 21,487,899,000 |
| AHPL.N0000 | inventories | 2023-05-23 | 19,000.0000 | 19,414,597,000 |
| AHPL.N0000 | revaluation_reserves | 2023-05-23 | 23,000.0000 | 2,320,613,338,000 |
| AHPL.N0000 | trade_payables | 2023-05-23 | 27,000.0000 | 271,230,136,000 |
| AHPL.N0000 | trade_receivables | 2023-05-23 | 20,000.0000 | 20,600,760,000 |
| CFVF.N0000 | profit_before_tax | 2026-03-31 | 12,000.0000 | 123,547,964,000 |
| CFVF.N0000 | trade_payables | 2026-03-31 | 32,000.0000 | 323,723,163,000 |
| CFVF.N0000 | trade_receivables | 2026-03-31 | 21,000.0000 | 212,339,875,000 |
| KZOO.N0000 | gross_profit | 2019-09-30 | 1,000.0000 | 51,000 |
| KZOO.N0000 | revenue | 2019-09-30 | 1,000.0000 | 51,000 |
| LPRT.N0000 | revaluation_reserves | 2025-03-31 | 1,000.0000 | 1,217,232,000 |
| PHAR.N0000 | amortisation_expense | 2013-03-31 | 6.0000 | 600,000 |
| PHAR.N0000 | trade_payables | 2013-03-31 | 8.0000 | 86,892,877 |
| GEST.N0000 | inventories | 2024-03-31 | 1.0000 | 123,768,257 |
| GEST.N0000 | trade_payables | 2024-03-31 | 1.0000 | 133,135,196 |
| GEST.N0000 | trade_receivables | 2024-03-31 | 3.0000 | 328,456,373 |
| GEST.N0000 | inventories | 2025-03-31 | 3.0000 | 347,398,929 |
| GEST.N0000 | trade_payables | 2025-03-31 | 2.0000 | 210,902,661 |
| GEST.N0000 | trade_receivables | 2025-03-31 | 4.0000 | 468,210,485 |
| JINS.N0000 | income_tax_expense | 2019-12-31 | 1,000.0000 | -131,077,000 |
| VFIN.N0000 | income_tax_expense | 2025-03-31 | 21,000.0000 | 25,621,000 |
| VFIN.N0000 | interest_expense | 2026-03-31 | 12,200.0000 | 28,512,200.0 |
| VFIN.N0000 | income_tax_expense | 2026-03-31 | 21,000.0000 | 29,221,000 |
| CDB.N0000 | inventories | 2016-09-30 | 26,632.0000 | 326,632 |
| CDB.X0000 | inventories | 2016-09-30 | 26,632.0000 | 326,632 |

## Unverifiable (needs manual follow-up)

| Ticker | Line | Period | Stored | Detail |
|---|---|---|---|---|
| BFN.N0000 | income_tax_expense | 2020-03-31 | 12.0000 | current pipeline found no matching line on any primary-statement page |
| CALI.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| CALC.U0000 | income_tax_expense | 2026-06-30 | 4.0000 | current pipeline found no matching line on any primary-statement page |
| WLTH.N0000 | income_tax_expense | 2026-06-30 | 7.0000 | current pipeline found no matching line on any primary-statement page |
| CALU.U0000 | income_tax_expense | 2026-03-31 | 4.0000 | current pipeline found no matching line on any primary-statement page |