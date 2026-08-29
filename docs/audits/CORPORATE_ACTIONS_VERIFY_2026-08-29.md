# Corporate-actions verification — 2026-08-29

Two independent checks. Ratio-type actions (split/bonus/consolidation) are verified against THIS SYSTEM'S OWN price history — a split is mechanical, so the real close either side of ex-date implies a ratio. Cash dividends are verified against a third party's published dividend history.

**A ratio is never derived from the price gap.** Where the declared ratio is missing, the implied gap sits at 0.95-1.00, where a 1:20 bonus and an ordinary 3% down day are indistinguishable. Those stay pending for a human.

- ratio-type confirmable: **2**, left pending: 115
- dividends confirmable: **899**, left pending: 367

## Ratio-type actions the price history confirms

| ticker | type | ex_date | declared ratio | expected px ratio | implied | note |
|---|---|---|---|---|---|---|
| UML.N0000 | stock_split | 2026-01-22 | 8 (derived) | 0.11111 | 0.10980 | ratio DERIVED as 8 from an unambiguous price gap |
| JKH.N0000 | stock_split | 2024-11-06 | 9 (derived) | 0.10000 | 0.10024 | ratio DERIVED as 9 from an unambiguous price gap |

## Left pending (with the real reason)

| ticker | type | ex_date | reason |
|---|---|---|---|
| PEG.N0000 | stock_split | 2026-09-21 | no stored close either side of ex_date |
| PLC.N0000 | bonus_issue | 2026-07-01 | no declared ratio; price gap 1.00457 does not unambiguously imply one |
| CFI.N0000 | bonus_issue | 2026-06-03 | no declared ratio; price gap 0.97543 does not unambiguously imply one |
| CIT.N0000 | bonus_issue | 2026-06-03 | no declared ratio; price gap 0.96631 does not unambiguously imply one |
| COMB.N0000 | bonus_issue | 2026-04-02 | no declared ratio; price gap 0.98776 does not unambiguously imply one |
| COMB.X0000 | bonus_issue | 2026-04-02 | no declared ratio; price gap 0.95812 does not unambiguously imply one |
| COCO.N0000 | stock_split | 2026-03-20 | no declared ratio; price gap 0.47387 does not unambiguously imply one |
| COCO.X0000 | stock_split | 2026-03-20 | no declared ratio; price gap 0.45393 does not unambiguously imply one |
| DFCC.N0000 | bonus_issue | 2026-03-09 | no declared ratio; price gap 0.95043 does not unambiguously imply one |
| NTB.N0000 | bonus_issue | 2026-03-05 | no declared ratio; price gap 0.99215 does not unambiguously imply one |
| NTB.X0000 | bonus_issue | 2026-03-05 | no declared ratio; price gap 0.94090 does not unambiguously imply one |
| TAP.N0000 | bonus_issue | 2026-02-13 | no declared ratio; price gap 0.99748 does not unambiguously imply one |
| COLO.N0000 | stock_split | 2025-10-23 | no declared ratio; price gap 0.11560 does not unambiguously imply one |
| PLC.N0000 | bonus_issue | 2025-09-30 | no declared ratio; price gap 0.98872 does not unambiguously imply one |
| WAPO.N0000 | bonus_issue | 2025-09-22 | no declared ratio; price gap 1.01175 does not unambiguously imply one |
| CFI.N0000 | bonus_issue | 2025-08-11 | no declared ratio; price gap 1.02157 does not unambiguously imply one |
| CIT.N0000 | bonus_issue | 2025-08-11 | no declared ratio; price gap 0.99101 does not unambiguously imply one |
| CHMX.N0000 | bonus_issue | 2025-07-01 | no declared ratio; price gap 1.00000 does not unambiguously imply one |
| COMB.N0000 | bonus_issue | 2025-04-01 | no declared ratio; price gap 0.97966 does not unambiguously imply one |
| COMB.X0000 | bonus_issue | 2025-04-01 | no declared ratio; price gap 0.94821 does not unambiguously imply one |
| NTB.N0000 | bonus_issue | 2025-03-06 | no declared ratio; price gap 0.98477 does not unambiguously imply one |
| NTB.X0000 | bonus_issue | 2025-03-06 | no declared ratio; price gap 0.99658 does not unambiguously imply one |
| DFCC.N0000 | bonus_issue | 2025-03-03 | no declared ratio; price gap 0.95158 does not unambiguously imply one |
| VLL.N0000 | bonus_issue | 2024-11-13 | no declared ratio; price gap 0.96429 does not unambiguously imply one |
| VLL.X0000 | bonus_issue | 2024-11-13 | no declared ratio; price gap 0.92157 does not unambiguously imply one |
| KZOO.N0000 | bonus_issue | 2024-09-20 | no declared ratio; price gap 0.98592 does not unambiguously imply one |
| WAPO.N0000 | bonus_issue | 2024-09-20 | no declared ratio; price gap 1.00746 does not unambiguously imply one |
| HBS.N0000 | bonus_issue | 2024-08-16 | no declared ratio; price gap 0.89844 does not unambiguously imply one |
| SDB.N0000 | bonus_issue | 2024-06-03 | no declared ratio; price gap 1.01538 does not unambiguously imply one |
| PINS.N0000 | bonus_issue | 2024-05-29 | no declared ratio; price gap 0.96154 does not unambiguously imply one |
| COMB.N0000 | bonus_issue | 2024-04-01 | no declared ratio; price gap 0.96142 does not unambiguously imply one |
| COMB.X0000 | bonus_issue | 2024-04-01 | no declared ratio; price gap 0.97788 does not unambiguously imply one |
| HNB.N0000 | bonus_issue | 2024-04-01 | no declared ratio; price gap 1.01252 does not unambiguously imply one |
| HNB.X0000 | bonus_issue | 2024-04-01 | no declared ratio; price gap 0.98000 does not unambiguously imply one |
| NTB.N0000 | bonus_issue | 2024-03-06 | no declared ratio; price gap 0.98529 does not unambiguously imply one |
| NTB.X0000 | bonus_issue | 2024-03-06 | no declared ratio; price gap 0.99036 does not unambiguously imply one |
| DFCC.N0000 | bonus_issue | 2024-02-29 | no declared ratio; price gap 0.94758 does not unambiguously imply one |
| CIT.N0000 | bonus_issue | 2024-01-11 | no declared ratio; price gap 1.00000 does not unambiguously imply one |
| PLC.N0000 | bonus_issue | 2024-01-08 | no declared ratio; price gap 0.99057 does not unambiguously imply one |
| COCO.N0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 0.99500 does not unambiguously imply one |
| COCO.X0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.03797 does not unambiguously imply one |
| KZOO.N0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.01852 does not unambiguously imply one |
| RAL.N0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.02083 does not unambiguously imply one |
| RHL.N0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.00000 does not unambiguously imply one |
| RHL.X0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.03448 does not unambiguously imply one |
| WAPO.N0000 | bonus_issue | 2023-09-08 | no declared ratio; price gap 1.01934 does not unambiguously imply one |
| CIND.N0000 | bonus_issue | 2023-06-30 | no declared ratio, and no stored close either side of ex_date |
| CFI.N0000 | bonus_issue | 2023-06-23 | no declared ratio, and no stored close either side of ex_date |
| CIT.N0000 | bonus_issue | 2023-06-23 | no declared ratio, and no stored close either side of ex_date |
| SUN.N0000 | bonus_issue | 2023-04-24 | no declared ratio, and no stored close either side of ex_date |
| PHAR.N0000 | stock_split | 2023-04-18 | no stored close either side of ex_date |
| COMB.N0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| COMB.X0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.N0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.X0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| SAMP.N0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.N0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.X0000 | bonus_issue | 2023-03-31 | no declared ratio, and no stored close either side of ex_date |
| NTB.N0000 | bonus_issue | 2023-03-09 | no declared ratio, and no stored close either side of ex_date |
| NTB.X0000 | bonus_issue | 2023-03-09 | no declared ratio, and no stored close either side of ex_date |
| DFCC.N0000 | bonus_issue | 2023-02-28 | no declared ratio, and no stored close either side of ex_date |
| HPWR.N0000 | bonus_issue | 2022-09-13 | no declared ratio, and no stored close either side of ex_date |
| KZOO.N0000 | bonus_issue | 2022-09-08 | no declared ratio, and no stored close either side of ex_date |
| PLC.N0000 | bonus_issue | 2022-09-08 | no declared ratio, and no stored close either side of ex_date |
| RHL.N0000 | bonus_issue | 2022-09-08 | no declared ratio, and no stored close either side of ex_date |
| RHL.X0000 | bonus_issue | 2022-09-08 | no declared ratio, and no stored close either side of ex_date |
| CFI.N0000 | bonus_issue | 2022-08-26 | no declared ratio, and no stored close either side of ex_date |
| CIT.N0000 | bonus_issue | 2022-08-26 | no declared ratio, and no stored close either side of ex_date |
| HNB.N0000 | bonus_issue | 2022-07-01 | no declared ratio, and no stored close either side of ex_date |
| HNB.X0000 | bonus_issue | 2022-07-01 | no declared ratio, and no stored close either side of ex_date |
| CPRT.N0000 | stock_split | 2022-06-02 | no declared ratio, and no stored close either side of ex_date |
| CFVF.N0000 | stock_split | 2022-05-05 | no declared ratio, and no stored close either side of ex_date |
| FCT.N0000 | stock_split | 2022-05-05 | no declared ratio, and no stored close either side of ex_date |
| HUNA.N0000 | stock_split | 2022-05-04 | no declared ratio, and no stored close either side of ex_date |
| CFVF.N0000 | stock_split | 2022-04-22 | no stored close either side of ex_date |
| FCT.N0000 | stock_split | 2022-04-22 | no stored close either side of ex_date |
| HUNA.N0000 | stock_split | 2022-04-21 | no declared ratio, and no stored close either side of ex_date |
| UAL.N0000 | stock_split | 2022-04-11 | no stored close either side of ex_date |
| COMB.N0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| COMB.X0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.N0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.X0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.N0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.X0000 | bonus_issue | 2022-03-31 | no declared ratio, and no stored close either side of ex_date |
| HUNA.N0000 | stock_split | 2022-03-22 | no stored close either side of ex_date |
| NTB.N0000 | bonus_issue | 2022-03-09 | no declared ratio, and no stored close either side of ex_date |
| NTB.X0000 | bonus_issue | 2022-03-09 | no declared ratio, and no stored close either side of ex_date |
| CCS.N0000 | stock_split | 2022-03-04 | no stored close either side of ex_date |
| DFCC.N0000 | bonus_issue | 2022-02-25 | no declared ratio, and no stored close either side of ex_date |
| PLC.N0000 | bonus_issue | 2021-12-31 | no declared ratio, and no stored close either side of ex_date |
| CFI.N0000 | bonus_issue | 2021-08-20 | no declared ratio, and no stored close either side of ex_date |
| CFI.N0000 | bonus_issue | 2021-08-20 | no declared ratio, and no stored close either side of ex_date |
| CIT.N0000 | bonus_issue | 2021-08-20 | no declared ratio, and no stored close either side of ex_date |
| CIT.N0000 | bonus_issue | 2021-08-20 | no declared ratio, and no stored close either side of ex_date |
| PLC.N0000 | bonus_issue | 2021-08-06 | no declared ratio, and no stored close either side of ex_date |
| COMB.N0000 | bonus_issue | 2021-03-31 | no declared ratio, and no stored close either side of ex_date |
| COMB.X0000 | bonus_issue | 2021-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.N0000 | bonus_issue | 2021-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.X0000 | bonus_issue | 2021-03-31 | no declared ratio, and no stored close either side of ex_date |
| VONE.N0000 | bonus_issue | 2021-03-04 | no declared ratio, and no stored close either side of ex_date |
| DFCC.N0000 | bonus_issue | 2021-03-01 | no declared ratio, and no stored close either side of ex_date |
| PLC.N0000 | bonus_issue | 2020-12-15 | no declared ratio, and no stored close either side of ex_date |
| HPWR.N0000 | bonus_issue | 2020-11-04 | no declared ratio, and no stored close either side of ex_date |
| SDB.N0000 | bonus_issue | 2020-07-16 | no declared ratio, and no stored close either side of ex_date |
| DFCC.N0000 | bonus_issue | 2020-06-25 | no declared ratio, and no stored close either side of ex_date |
| COMB.N0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| COMB.X0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| DFCC.N0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.N0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| HNB.X0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.N0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| SEYB.X0000 | bonus_issue | 2020-03-31 | no declared ratio, and no stored close either side of ex_date |
| MCPL.N0000 | bonus_issue | 2019-09-27 | no declared ratio, and no stored close either side of ex_date |
| CFI.N0000 | bonus_issue | 2019-09-20 | no declared ratio, and no stored close either side of ex_date |
| CIT.N0000 | bonus_issue | 2019-09-20 | no declared ratio, and no stored close either side of ex_date |

## Dividends left pending

| ticker | ex_date | ours | reason |
|---|---|---|---|
| UML.N0000 | 2025-11-19 | 2.0000 | third party reports 0.200 on 2025-11-19, we hold 2.0000 |
| UML.N0000 | 2025-06-30 | 2.0000 | third party reports 0.200 on 2025-06-30, we hold 2.0000 |
| JKH.N0000 | 2025-06-05 | 0.0500 | third party reports 0.500 on 2025-06-05, we hold 0.0500 |
| DFCC.N0000 | 2025-03-03 | 4.0000 | third party reports 3.89074 on 2025-03-03, we hold 4.0000 |
| PLC.N0000 | 2025-02-24 | 0.7000 | third party reports 0.66445 on 2025-02-24, we hold 0.7000 |
| PLC.N0000 | 2024-07-02 | 0.7000 | third party reports 0.66445 on 2024-07-02, we hold 0.7000 |
| CHMX.N0000 | 2024-07-01 | 2.5000 | third party reports 2.43112 on 2024-07-01, we hold 2.5000 |
| UML.N0000 | 2024-07-01 | 1.5000 | third party reports 0.150 on 2024-07-01, we hold 1.5000 |
| UML.N0000 | 2024-07-01 | 1.5000 | third party reports 0.150 on 2024-07-01, we hold 1.5000 |
| VLL.N0000 | 2024-06-11 | 0.3000 | third party reports 0.27658 on 2024-06-11, we hold 0.3000 |
| VLL.X0000 | 2024-06-11 | 0.3000 | third party reports 0.26449 on 2024-06-11, we hold 0.3000 |
| VLL.N0000 | 2024-06-10 | 0.3000 | third party reports 0.27658 on 2024-06-11, we hold 0.3000 |
| VLL.X0000 | 2024-06-10 | 0.3000 | third party reports 0.26449 on 2024-06-11, we hold 0.3000 |
| JKH.N0000 | 2024-06-03 | 0.5000 | third party reports 0.050 on 2024-06-03, we hold 0.5000 |
| COMB.N0000 | 2024-04-01 | 4.5000 | third party reports 4.40749 on 2024-04-01, we hold 4.5000 |
| COMB.X0000 | 2024-04-01 | 4.5000 | third party reports 4.39645 on 2024-04-01, we hold 4.5000 |
| COLO.N0000 | 2024-03-07 | 5.0000 | third party reports 0.500 on 2024-03-07, we hold 5.0000 |
| NTB.N0000 | 2024-03-06 | 2.5000 | third party reports 2.4435 on 2024-03-06, we hold 2.5000 |
| DFCC.N0000 | 2024-02-29 | 3.0000 | third party reports 2.87981 on 2024-02-29, we hold 3.0000 |
| JKH.N0000 | 2024-02-12 | 0.5000 | third party reports 0.050 on 2024-02-12, we hold 0.5000 |
| VLL.N0000 | 2023-11-17 | 0.2500 | third party reports 0.23049 on 2023-11-17, we hold 0.2500 |
| VLL.X0000 | 2023-11-17 | 0.2500 | third party reports 0.22041 on 2023-11-17, we hold 0.2500 |
| JKH.N0000 | 2023-11-16 | 0.5000 | third party reports 0.050 on 2023-11-16, we hold 0.5000 |
| PLC.N0000 | 2023-08-04 | 0.7000 | third party reports 0.62976 on 2023-08-04, we hold 0.7000 |
| CHMX.N0000 | 2023-07-04 | 2.5000 | third party reports 2.43112 on 2023-07-04, we hold 2.5000 |
| UML.N0000 | 2023-06-30 | 1.2500 | third party reports 0.125 on 2023-07-04, we hold 1.2500 |
| TKYO.N0000 | 2023-06-13 | 1.5000 | third party reports 1.36364 on 2023-06-13, we hold 1.5000 |
| TKYO.X0000 | 2023-06-13 | 1.5000 | third party reports 1.36364 on 2023-06-13, we hold 1.5000 |
| VLL.X0000 | 2023-06-09 | 0.1100 | third party reports 0.09698 on 2023-06-09, we hold 0.1100 |
| JKH.N0000 | 2023-06-01 | 0.5000 | third party reports 0.050 on 2023-06-01, we hold 0.5000 |
| UML.N0000 | 2023-04-06 | 1.0000 | third party reports 0.100 on 2023-04-06, we hold 1.0000 |
| COLO.N0000 | 2023-03-13 | 5.0000 | third party reports 0.500 on 2023-03-13, we hold 5.0000 |
| VLL.X0000 | 2023-02-21 | 0.1000 | third party reports 0.08816 on 2023-02-21, we hold 0.1000 |
| JKH.N0000 | 2023-02-09 | 0.5000 | third party reports 0.050 on 2023-02-09, we hold 0.5000 |
| JKH.N0000 | 2022-11-16 | 1.0000 | third party reports 0.100 on 2022-11-16, we hold 1.0000 |
| ONAL.N0000 | 2022-11-04 | 1.5000 | third party reports 2.100 on 2022-11-04, we hold 1.5000 |
| ONAL.N0000 | 2022-11-04 | 0.6000 | third party reports 2.100 on 2022-11-04, we hold 0.6000 |
| MDL.N0000 | 2022-09-23 | 0.2500 | no third-party dividend near this ex_date |
| COCO.N0000 | 2022-09-08 | 0.4100 | third party reports 0.20151 on 2022-09-08, we hold 0.4100 |
| COCO.X0000 | 2022-09-08 | 0.4100 | third party reports 0.20088 on 2022-09-08, we hold 0.4100 |
| CWL.N0000 | 2022-08-29 | 0.2000 | no third-party dividend near this ex_date |
| LIOC.N0000 | 2022-08-08 | 2.2500 | no third-party dividend near this ex_date |
| LIOC.N0000 | 2022-08-05 | 2.2500 | no third-party dividend near this ex_date |
| COOP.N0000 | 2022-08-01 | 0.1350 | no third-party dividend near this ex_date |
| CHMX.N0000 | 2022-07-01 | 2.0000 | third party reports 1.94489 on 2022-07-01, we hold 2.0000 |
| UML.N0000 | 2022-06-30 | 0.5000 | third party reports 0.050 on 2022-06-30, we hold 0.5000 |
| VLL.X0000 | 2022-06-08 | 0.1000 | third party reports 0.08816 on 2022-06-08, we hold 0.1000 |
| JKH.N0000 | 2022-06-01 | 0.5000 | third party reports 0.050 on 2022-06-01, we hold 0.5000 |
| SDB.N0000 | 2022-05-31 | 1.5000 | third party reports 1.46832 on 2022-05-31, we hold 1.5000 |
| SLTL.N0000 | 2022-05-12 | 2.0200 | no third-party dividend near this ex_date |
| HEXP.N0000 | 2022-04-11 | 0.5000 | no third-party dividend near this ex_date |
| MGT.N0000 | 2022-04-11 | 0.3000 | no third-party dividend near this ex_date |
| SINS.N0000 | 2022-04-11 | 0.2000 | no third-party dividend near this ex_date |
| COMB.N0000 | 2022-03-31 | 4.5000 | third party reports 4.08587 on 2022-03-31, we hold 4.5000 |
| COMB.X0000 | 2022-03-31 | 4.5000 | third party reports 4.02488 on 2022-03-31, we hold 4.5000 |
| HNB.N0000 | 2022-03-31 | 6.5000 | third party reports 6.05122 on 2022-03-31, we hold 6.5000 |
| HNB.X0000 | 2022-03-31 | 6.5000 | third party reports 5.94541 on 2022-03-31, we hold 6.5000 |
| SAMP.N0000 | 2022-03-31 | 4.2500 | third party reports 4.14734 on 2022-03-31, we hold 4.2500 |
| UML.N0000 | 2022-03-16 | 1.5000 | third party reports 0.150 on 2022-03-16, we hold 1.5000 |
| UAL.N0000 | 2022-03-10 | 22.0000 | third party reports 2.200 on 2022-03-10, we hold 22.0000 |
| COLO.N0000 | 2022-02-23 | 5.0000 | third party reports 0.500 on 2022-02-23, we hold 5.0000 |
| JKH.N0000 | 2022-02-07 | 0.5000 | third party reports 0.050 on 2022-02-07, we hold 0.5000 |
| VLL.N0000 | 2021-11-26 | 0.1750 | third party reports 0.16134 on 2021-11-26, we hold 0.1750 |
| VLL.X0000 | 2021-11-26 | 0.1750 | third party reports 0.15429 on 2021-11-26, we hold 0.1750 |
| JKH.N0000 | 2021-11-12 | 0.5000 | third party reports 0.050 on 2021-11-12, we hold 0.5000 |
| MCPL.N0000 | 2021-09-28 | 1.5000 | no third-party dividend near this ex_date |
| RHL.N0000 | 2021-09-24 | 0.1000 | no third-party dividend near this ex_date |
| RHL.X0000 | 2021-09-24 | 0.1000 | no third-party dividend near this ex_date |
| TKYO.N0000 | 2021-08-26 | 0.8500 | third party reports 0.77273 on 2021-08-26, we hold 0.8500 |
| TKYO.X0000 | 2021-08-26 | 0.8500 | third party reports 0.77273 on 2021-08-26, we hold 0.8500 |
| TYRE.N0000 | 2021-08-24 | 5.0000 | no third-party dividend near this ex_date |
| CTC.N0000 | 2021-08-23 | 19.0000 | no third-party dividend near this ex_date |
| KZOO.N0000 | 2021-08-23 | 0.2000 | third party reports 0.18866 on 2021-08-23, we hold 0.2000 |
| KCAB.N0000 | 2021-08-04 | 4.5000 | no third-party dividend near this ex_date |
| UML.N0000 | 2021-07-28 | 1.0000 | third party reports 0.100 on 2021-07-28, we hold 1.0000 |
| GLAS.N0000 | 2021-07-26 | 0.5800 | no third-party dividend near this ex_date |
| CIND.N0000 | 2021-07-20 | 2.0000 | third party reports 1.80093 on 2021-07-20, we hold 2.0000 |
| TKYO.N0000 | 2021-07-02 | 1.2500 | no third-party dividend near this ex_date |
| TKYO.X0000 | 2021-07-02 | 1.2500 | no third-party dividend near this ex_date |
| CHMX.N0000 | 2021-07-01 | 1.0000 | third party reports 0.97245 on 2021-07-01, we hold 1.0000 |
| DIPD.N0000 | 2021-06-30 | 0.6000 | no third-party dividend near this ex_date |
| MGT.N0000 | 2021-06-29 | 0.1000 | no third-party dividend near this ex_date |
| HAYC.N0000 | 2021-06-28 | 0.5000 | no third-party dividend near this ex_date |
| KVAL.N0000 | 2021-06-28 | 1.5000 | no third-party dividend near this ex_date |
| TPL.N0000 | 2021-06-28 | 1.5000 | no third-party dividend near this ex_date |
| DIAL.N0000 | 2021-06-25 | 0.7400 | no third-party dividend near this ex_date |
| MELS.N0000 | 2021-06-23 | 2.7500 | no third-party dividend near this ex_date |
| DIST.N0000 | 2021-06-22 | 0.7000 | no third-party dividend near this ex_date |
| VFIN.N0000 | 2021-06-14 | 6.0000 | third party reports 1.500 on 2021-06-14, we hold 6.0000 |
| UCAR.N0000 | 2021-06-11 | 14.0000 | no third-party dividend near this ex_date |
| DIMO.N0000 | 2021-06-09 | 12.5000 | no third-party dividend near this ex_date |
| RCL.N0000 | 2021-06-09 | 1.2000 | no third-party dividend near this ex_date |
| PARQ.N0000 | 2021-06-08 | 1.0500 | no third-party dividend near this ex_date |
| TILE.N0000 | 2021-06-08 | 2.2000 | no third-party dividend near this ex_date |
| JKH.N0000 | 2021-06-04 | 0.5000 | no third-party dividend near this ex_date |
| JKL.N0000 | 2021-06-03 | 2.2900 | no third-party dividend near this ex_date |
| KFP.N0000 | 2021-05-31 | 2.5000 | no third-party dividend near this ex_date |
| SDB.N0000 | 2021-05-31 | 2.2500 | third party reports 2.20247 on 2021-05-31, we hold 2.2500 |
| CTC.N0000 | 2021-05-28 | 19.0000 | no third-party dividend near this ex_date |
| CTC.N0000 | 2021-05-28 | 11.3500 | no third-party dividend near this ex_date |
| SINS.N0000 | 2021-05-28 | 0.2500 | no third-party dividend near this ex_date |
| VLL.N0000 | 2021-05-21 | 0.1250 | no third-party dividend near this ex_date |
| VLL.X0000 | 2021-05-21 | 0.1250 | no third-party dividend near this ex_date |
| HARI.N0000 | 2021-05-12 | 20.0000 | no third-party dividend near this ex_date |
| CINS.N0000 | 2021-05-06 | 40.0000 | no third-party dividend near this ex_date |
| CINS.X0000 | 2021-05-06 | 40.0000 | no third-party dividend near this ex_date |
| SLTL.N0000 | 2021-04-26 | 1.4900 | no third-party dividend near this ex_date |
| UAL.N0000 | 2021-04-09 | 14.0000 | third party reports 1.400 on 2021-04-09, we hold 14.0000 |
| MCPL.N0000 | 2021-04-08 | 0.7500 | no third-party dividend near this ex_date |
| RICH.N0000 | 2021-04-08 | 0.5000 | no third-party dividend near this ex_date |
| KGAL.N0000 | 2021-04-06 | 4.0000 | no third-party dividend near this ex_date |
| NAMU.N0000 | 2021-04-06 | 8.5000 | no third-party dividend near this ex_date |
| REXP.N0000 | 2021-04-05 | 25.0000 | no third-party dividend near this ex_date |
| COMB.N0000 | 2021-03-31 | 4.5000 | no third-party dividend near this ex_date |
| COMB.X0000 | 2021-03-31 | 4.5000 | no third-party dividend near this ex_date |
| CSD.N0000 | 2021-03-31 | 1.2000 | no third-party dividend near this ex_date |
| HNB.N0000 | 2021-03-31 | 4.5000 | no third-party dividend near this ex_date |
| HNB.X0000 | 2021-03-31 | 4.5000 | no third-party dividend near this ex_date |
| LHCL.N0000 | 2021-03-31 | 0.7500 | no third-party dividend near this ex_date |
| ETWO.N0000 | 2021-03-26 | 0.6500 | no third-party dividend near this ex_date |
| JKL.N0000 | 2021-03-25 | 1.0000 | no third-party dividend near this ex_date |
| COLO.N0000 | 2021-03-23 | 5.0000 | no third-party dividend near this ex_date |
| SINS.N0000 | 2021-03-23 | 0.3000 | no third-party dividend near this ex_date |
| CIC.N0000 | 2021-03-19 | 1.0000 | no third-party dividend near this ex_date |
| CIC.X0000 | 2021-03-19 | 1.0000 | no third-party dividend near this ex_date |
| DIPD.N0000 | 2021-03-17 | 1.0000 | no third-party dividend near this ex_date |
| HAYC.N0000 | 2021-03-17 | 1.4000 | no third-party dividend near this ex_date |
| KVAL.N0000 | 2021-03-17 | 1.0000 | no third-party dividend near this ex_date |
| MGT.N0000 | 2021-03-17 | 0.2500 | no third-party dividend near this ex_date |
| LLUB.N0000 | 2021-03-09 | 2.0000 | no third-party dividend near this ex_date |
| NTB.N0000 | 2021-03-09 | 2.0000 | third party reports 1.69945 on 2021-03-09, we hold 2.0000 |
| NTB.X0000 | 2021-03-09 | 2.0000 | third party reports 1.72249 on 2021-03-09, we hold 2.0000 |
| VONE.N0000 | 2021-03-04 | 0.5000 | no third-party dividend near this ex_date |
| LWL.N0000 | 2021-02-23 | 10.0000 | third party reports 2.000 on 2021-02-23, we hold 10.0000 |
| PARQ.N0000 | 2021-02-23 | 4.1000 | no third-party dividend near this ex_date |
| RCL.N0000 | 2021-02-23 | 11.0000 | no third-party dividend near this ex_date |
| TILE.N0000 | 2021-02-23 | 12.3000 | no third-party dividend near this ex_date |
| SUN.N0000 | 2021-02-16 | 1.0000 | no third-party dividend near this ex_date |
| VPEL.N0000 | 2021-02-16 | 0.3000 | no third-party dividend near this ex_date |
| KFP.N0000 | 2021-02-12 | 7.0000 | no third-party dividend near this ex_date |
| JKH.N0000 | 2021-02-09 | 0.5000 | no third-party dividend near this ex_date |
| LFIN.N0000 | 2021-02-02 | 12.0000 | no third-party dividend near this ex_date |
| DIMO.N0000 | 2021-01-18 | 2.5000 | no third-party dividend near this ex_date |
| CTC.N0000 | 2021-01-12 | 18.5000 | no third-party dividend near this ex_date |
| UML.N0000 | 2021-01-05 | 1.5000 | no third-party dividend near this ex_date |
| VLL.N0000 | 2021-01-04 | 0.1000 | no third-party dividend near this ex_date |
| VLL.X0000 | 2021-01-04 | 0.1000 | no third-party dividend near this ex_date |
| EBCR.N0000 | 2020-12-31 | 18.0000 | no third-party dividend near this ex_date |
| RIL.N0000 | 2020-12-22 | 0.1000 | no third-party dividend near this ex_date |
| CTHR.N0000 | 2020-12-16 | 1.4500 | no third-party dividend near this ex_date |
| KVAL.N0000 | 2020-12-09 | 1.0000 | no third-party dividend near this ex_date |
| TPL.N0000 | 2020-12-09 | 2.0000 | no third-party dividend near this ex_date |
| DIPD.N0000 | 2020-12-08 | 9.0000 | no third-party dividend near this ex_date |
| HAYC.N0000 | 2020-12-08 | 14.0000 | no third-party dividend near this ex_date |
| HEXP.N0000 | 2020-12-08 | 1.0000 | third party reports 0.33333 on 2020-12-08, we hold 1.0000 |
| SINS.N0000 | 2020-12-08 | 0.2000 | no third-party dividend near this ex_date |
| MGT.N0000 | 2020-12-07 | 0.4500 | no third-party dividend near this ex_date |
| MELS.N0000 | 2020-12-04 | 2.5000 | no third-party dividend near this ex_date |
| TYRE.N0000 | 2020-12-03 | 5.0000 | no third-party dividend near this ex_date |
| DIST.N0000 | 2020-12-01 | 0.4200 | no third-party dividend near this ex_date |
| COMD.N0000 | 2020-11-26 | 2.0000 | no third-party dividend near this ex_date |
| GRAN.N0000 | 2020-11-24 | 4.5000 | no third-party dividend near this ex_date |
| TAFL.N0000 | 2020-11-24 | 5.5000 | no third-party dividend near this ex_date |
| UCAR.N0000 | 2020-11-23 | 15.0000 | no third-party dividend near this ex_date |
| HHL.N0000 | 2020-11-23 | 0.4000 | no third-party dividend near this ex_date |
| WATA.N0000 | 2020-11-23 | 3.0000 | no third-party dividend near this ex_date |
| CTEA.N0000 | 2020-11-20 | 5.0000 | no third-party dividend near this ex_date |
| CTC.N0000 | 2020-11-19 | 19.0000 | no third-party dividend near this ex_date |
| LWL.N0000 | 2020-11-19 | 3.6000 | third party reports 0.720 on 2020-11-19, we hold 3.6000 |
| PHAR.N0000 | 2020-11-19 | 50.0000 | third party reports 2.500 on 2020-11-19, we hold 50.0000 |
| TILE.N0000 | 2020-11-19 | 3.8500 | no third-party dividend near this ex_date |
| LALU.N0000 | 2020-11-18 | 1.0000 | no third-party dividend near this ex_date |
| VPEL.N0000 | 2020-11-17 | 0.3000 | no third-party dividend near this ex_date |
| HARI.N0000 | 2020-11-16 | 30.0000 | no third-party dividend near this ex_date |
| JKH.N0000 | 2020-11-16 | 0.5000 | no third-party dividend near this ex_date |
| LITE.N0000 | 2020-11-12 | 1.0000 | no third-party dividend near this ex_date |
| LLUB.N0000 | 2020-11-10 | 3.5000 | no third-party dividend near this ex_date |
| HPWR.N0000 | 2020-11-04 | 0.7500 | third party reports 0.13755 on 2020-11-04, we hold 0.7500 |
| CTHR.N0000 | 2020-11-02 | 2.8000 | no third-party dividend near this ex_date |
| LALU.N0000 | 2020-11-02 | 1.0000 | no third-party dividend near this ex_date |
| MCPL.N0000 | 2020-10-29 | 1.5000 | no third-party dividend near this ex_date |
| TKYO.N0000 | 2020-10-23 | 1.5000 | no third-party dividend near this ex_date |
| TKYO.X0000 | 2020-10-23 | 1.5000 | no third-party dividend near this ex_date |
| PARQ.N0000 | 2020-10-16 | 2.6500 | no third-party dividend near this ex_date |
| RCL.N0000 | 2020-10-16 | 3.0000 | no third-party dividend near this ex_date |
| HAYC.N0000 | 2020-10-12 | 5.0000 | no third-party dividend near this ex_date |
| TPL.N0000 | 2020-10-12 | 2.0000 | no third-party dividend near this ex_date |
| DIPD.N0000 | 2020-10-09 | 3.0000 | no third-party dividend near this ex_date |
| MGT.N0000 | 2020-10-09 | 0.2500 | no third-party dividend near this ex_date |
| SHAW.N0000 | 2020-10-09 | 1.0000 | no third-party dividend near this ex_date |
| RICH.N0000 | 2020-10-07 | 0.5000 | no third-party dividend near this ex_date |
| CHMX.N0000 | 2020-10-02 | 2.0000 | no third-party dividend near this ex_date |
| LMF.N0000 | 2020-10-02 | 2.5000 | no third-party dividend near this ex_date |
| RWSL.N0000 | 2020-10-02 | 0.1000 | no third-party dividend near this ex_date |
| COCO.N0000 | 2020-09-29 | 0.3500 | third party reports 0.17202 on 2020-09-29, we hold 0.3500 |
| COCO.X0000 | 2020-09-29 | 0.3500 | third party reports 0.17148 on 2020-09-29, we hold 0.3500 |
| RHL.N0000 | 2020-09-29 | 0.2500 | third party reports 0.23538 on 2020-09-29, we hold 0.2500 |
| RHL.X0000 | 2020-09-29 | 0.2500 | third party reports 0.23242 on 2020-09-29, we hold 0.2500 |
| ELPL.N0000 | 2020-09-21 | 0.7500 | no third-party dividend near this ex_date |
| SOY.N0000 | 2020-09-16 | 5.5000 | no third-party dividend near this ex_date |
