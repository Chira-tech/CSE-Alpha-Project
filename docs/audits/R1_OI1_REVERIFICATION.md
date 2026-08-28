# OI-1 full re-verification sweep

Generated: 2026-08-23T05:13:51+00:00Z

396 candidate rows across 253 distinct filings, re-verified against today's live source PDFs using today's unmodified extraction pipeline.

- **Confirmed still wrong (`stale_or_wrong`): 95** — today's pipeline produces a DIFFERENT value than what's stored. These are the real, currently-actionable rows.
- Stored value matches a fresh re-extraction (`confirmed_correct`): 301 — the stored figure IS what today's pipeline would produce; not a bug, a false positive of the crude `< 100000` magnitude filter that found the candidate set.
- Unverifiable: 0 — network/parse failure or the line no longer matches on re-extraction; needs manual follow-up, not silently one or the other.

## Rows confirmed still wrong (act on these)

| Ticker | Line | Period | Stored | Fresh (today's pipeline) |
|---|---|---|---|---|
| LGL.N0000 | total_assets | 2026-06-30 | 4,000.0000 | 8,030,860,000 |
| LGL.X0000 | total_assets | 2026-06-30 | 4,000.0000 | 8,030,860,000 |
| COCR.N0000 | revenue | 2015-03-31 | 31.0000 | 11,901,147,537 |
| AFSL.N0000 | total_comprehensive_income | 2018-03-31 | 9.0000 | 3,965,752 |
| AFSL.N0000 | total_comprehensive_income | 2018-03-31 | 9.0000 | 3,965,752 |
| BIL.N0000 | total_comprehensive_income | 2017-06-30 | 5,000.0000 | 76,062,000 |
| CALF.N0000 | total_liabilities | 2014-09-30 | 7.0000 | 71,743,335 |
| CALF.N0000 | total_liabilities | 2017-06-30 | 8.0000 | 55,818,730 |
| CALF.N0000 | total_liabilities | 2018-09-30 | 9.0000 | 53,995,494 |
| AAF.N0000 | profit_before_tax | 2018-12-31 | 8.0000 | 2,804,091 |
| AAF.R0000 | profit_before_tax | 2018-12-31 | 8.0000 | 2,804,091 |
| AAF.N0000 | profit_before_tax | 2021-09-30 | 7.0000 | 623,760 |
| AAF.R0000 | profit_before_tax | 2021-09-30 | 7.0000 | 623,760 |
| MEL.N0000 | revenue | 2024-03-31 | 6.0000 | 20,656,000 |
| MEL.N0000 | revenue | 2025-03-31 | 6.0000 | 17,860,000 |
| RFL.N0000 | revenue | 2024-03-31 | 5.0000 | 1 |
| RFL.N0000 | total_assets | 2024-03-31 | 7.0000 | 731,015,579 |
| RFL.N0000 | total_equity | 2024-03-31 | 5.0000 | 511,807,720 |
| RFL.N0000 | total_liabilities | 2024-03-31 | 2.0000 | 219,207,859 |
| RFL.N0000 | revenue | 2025-03-31 | 5.0000 | 2 |
| RFL.N0000 | total_assets | 2025-03-31 | 7.0000 | 753,250,955 |
| RFL.N0000 | total_equity | 2025-03-31 | 5.0000 | 524,044,933 |
| RFL.N0000 | total_liabilities | 2025-03-31 | 2.0000 | 229,206,022 |
| MHDL.N0000 | revenue | 2026-06-30 | 1,000.0000 | 82,699,000 |
| BRR.N0000 | profit_before_tax | 2019-03-31 | 19.0000 | 17,454,654 |
| BRR.N0000 | profit_before_tax | 2020-03-31 | 19.0000 | 4,490,289 |
| AINS.N0000 | net_income | 2025-12-31 | 9.0000 | 230,818,306 |
| AINS.N0000 | net_income | 2026-03-31 | 9.0000 | 5,572,134 |
| AINS.N0000 | net_income | 2026-06-30 | 9.0000 | 22,889,584 |
| FCT.N0000 | profit_before_tax | 2025-03-31 | 11,000.0000 | 4,472,066,000 |
| SINH.N0000 | profit_before_tax | 2026-03-31 | 3.0000 | 1,167,443 |
| CWL.N0000 | revenue | 2025-06-30 | 1.0000 | 74,958,461 |
| CWL.N0000 | revenue | 2026-06-30 | 2.0000 | 48,693,076 |
| PLR.N0000 | revenue | 2026-03-31 | 4.0000 | 11,031,333,018 |
| EML.N0000 | revenue | 2025-12-31 | 5.0000 | 88,749,414 |
| AFS.N0000 | total_assets | 2023-03-31 | 2.0000 | 53,291,662 |
| AFS.N0000 | total_liabilities | 2023-03-31 | 1.0000 | 78,905,706 |
| AFS.N0000 | revenue | 2023-03-31 | 16.0000 | 289,663,882 |
| CBNK.N0000 | total_assets | 2025-09-30 | 8,000.0000 | 8,479,398,000 |
| CBNK.N0000 | total_liabilities | 2025-09-30 | 7,000.0000 | 6,512,434,000 |
| CBNK.N0000 | total_equity | 2025-09-30 | 1,000.0000 | 1,966,964,000 |
| CALC.U0000 | total_liabilities | 2026-03-31 | 1.0000 | 2,746,306 |
| CALU.U0000 | profit_before_tax | 2026-03-31 | 1.0000 | 27,748,895 |
| CALU.U0000 | total_comprehensive_income | 2026-03-31 | 1.0000 | 27,748,895 |
| CCS.N0000 | total_equity | 2014-03-31 | 1.0000 | 216 |
| CCS.N0000 | profit_before_tax | 2014-06-30 | 4,000.0000 | 16,441,000 |
| CCS.N0000 | revenue | 2016-07-21 | 1,000.0000 | 279,427,000 |
| CCS.N0000 | profit_before_tax | 2017-06-30 | 9,000.0000 | 99,168,000 |
| CCS.N0000 | net_income | 2019-07-30 | 4,000.0000 | 12,085,000 |
| CCS.N0000 | net_income | 2020-07-23 | 6,000.0000 | 2,039,000 |
| CCS.N0000 | net_income | 2022-07-15 | 9,000.0000 | 19,277,000 |
| CCS.N0000 | net_income | 2023-07-18 | 3,000.0000 | 22,174,000 |
| CCS.N0000 | profit_before_tax | 2023-07-18 | 4,000.0000 | 15,337,000 |
| KFP.N0000 | profit_before_tax | 2026-07-27 | 1,000.0000 | 9,474,000 |
| KFP.N0000 | net_income | 2026-07-27 | 1,000.0000 | 3,596,000 |
| CHMX.N0000 | profit_before_tax | 2018-06-30 | 5,000.0000 | 6,269,000 |
| CHMX.N0000 | net_income | 2021-06-30 | 2,000.0000 | 802,000 |
| AMSL.N0000 | revenue | 2021-03-31 | 3.1000 | 4,229,712,085 |
| AMSL.N0000 | profit_before_tax | 2021-03-31 | 5.0000 | 708,765,307 |
| GHLL.N0000 | revenue | 2025-12-31 | 24.0000 | 348,619,278 |
| MARA.N0000 | revenue | 2025-03-31 | 5.0000 | 960,193,755 |
| MARA.N0000 | revenue | 2026-03-31 | 5.0000 | 883,191,942 |
| TAJ.N0000 | revenue | 2024-03-31 | 5.0000 | 3,728,162,471 |
| TAJ.N0000 | revenue | 2025-03-31 | 5.0000 | 3,472,131,181 |
| TANG.N0000 | revenue | 2026-06-30 | 1,000.0000 | 75,649,000 |
| WAPO.N0000 | revenue | 2024-03-31 | 13.0000 | 32,031,268 |
| WAPO.N0000 | revenue | 2025-03-31 | 14.0000 | 78,264,218 |
| CTLD.N0000 | revenue | 2019-03-31 | 6,000.0000 | 594,634,000 |
| CTLD.N0000 | revenue | 2021-03-31 | 6,000.0000 | 347,468,000 |
| CTLD.N0000 | revenue | 2022-03-31 | 6,000.0000 | 146,783,000 |
| CTLD.N0000 | revenue | 2023-03-31 | 6,000.0000 | 349,472,000 |
| CTLD.N0000 | revenue | 2025-06-30 | 8,000.0000 | 7,743,000 |
| CTLD.N0000 | revenue | 2026-03-31 | 6,000.0000 | 283,243,000 |
| CSD.N0000 | total_comprehensive_income | 2024-03-31 | 6,000.0000 | 9,173,000 |
| LWL.N0000 | revenue | 2026-06-30 | 1,000.0000 | 978,398,000 |
| ASHO.N0000 | profit_before_tax | 2021-03-31 | 1.0000 | 9,075,722 |
| ASHO.N0000 | revenue | 2026-03-31 | 5.0000 | 19,330,408,115 |
| ASHO.N0000 | profit_before_tax | 2026-03-31 | 10.0000 | 4,407,909,933 |
| BALA.N0000 | revenue | 2014-12-31 | 23.0000 | 3,002,155,618 |
| BALA.N0000 | revenue | 2015-12-31 | 6.0000 | 2,413,054,604 |
| BALA.N0000 | revenue | 2015-12-31 | 6.0000 | 2,413,054,604 |
| BALA.N0000 | revenue | 2016-12-31 | 6.0000 | 2,266,656,524 |
| BALA.N0000 | revenue | 2016-12-31 | 6.0000 | 2,266,656,524 |
| BALA.N0000 | revenue | 2019-12-31 | 5.0000 | 2,572,830,353 |
| BALA.N0000 | revenue | 2020-12-31 | 5.0000 | 3,573,075,557 |
| BALA.N0000 | net_income | 2024-03-31 | 1,000.0000 | 67,733,000 |
| HOPL.N0000 | revenue | 2026-03-31 | 4,000.0000 | 3,950,039,000 |
| HOPL.N0000 | profit_before_tax | 2026-03-31 | 9,000.0000 | 216,310,000 |
| KAHA.N0000 | revenue | 2025-03-31 | 5,000.0000 | 6,790,324,000 |
| KAHA.N0000 | operating_profit | 2025-03-31 | 7,000.0000 | 692,996,000 |
| KAHA.N0000 | revenue | 2026-06-30 | 9,000.0000 | 57,987,000 |
| MAL.N0000 | revenue | 2025-12-31 | 6.0000 | 8,605,507,470 |
| MAL.X0000 | revenue | 2025-12-31 | 6.0000 | 8,605,507,470 |
| MASK.N0000 | revenue | 2024-03-31 | 6,000.0000 | 6,328,771,000 |
| JINS.N0000 | profit_before_tax | 2026-06-30 | 2,000.0000 | 71,483,000 |

## Unverifiable (needs manual follow-up)

| Ticker | Line | Period | Stored | Detail |
|---|---|---|---|---|