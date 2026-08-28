# R1 Data Integrity Audit

Generated: 2026-08-23T03:41:47+00:00Z · DB: `sqlite+pysqlite:///./devdb.sqlite`

Every number below is reproducible by re-running `python -m scripts.audit_data_integrity` from `backend/` against this same database — nothing here is hand-typed.

**🔴 T1.2's automated reconciliation sample hit a 10.0% mismatch rate — 5× the brief's own 2% stop-the-release threshold, on its first run.** Investigating the mismatches by hand surfaced a systemic bug (a note-reference footnote number stored as the real figure) already live in 396 confirmed `Fundamental` rows across ~88 tickers. Full writeup, measured blast radius, and a proposed (not yet executed) remediation path: **[`R1_OPEN_ISSUES.md`, OI-1](./R1_OPEN_ISSUES.md#oi-1-critical-blocking--note-reference-number-extraction-bug-live-in-confirmed-data)**. Per the brief's own rule, this blocks the release until resolved.

## Summary

| Domain | Status |
|---|---|
| Prices | 🟢 green |
| Corporate actions | 🟢 green |
| Financial statements | 🔴 red — see OI-1 |
| Macro | 🟢 green |
| Synthetic data sweep | 🟢 green |
| Reconciliation with source (T1.2) | 🔴 red — see OI-1 |

## Prices

- Distinct tickers with any price row: **290** of 290 securities
- Tickers with < 500 sessions of history: **21**
- Rows with `close` NULL: **0**, zero: **0**, negative: **0**
- Trading-day-gap sessions (> 3 consecutive sessions missed, real `cse.aspi` calendar where covered — 2025-08-20 to 2026-08-18, 241 real sessions — weekday proxy outside that window, no CSE holiday calendar exists in this system): **594 gap-events across 107 tickers**

**Top 15 tickers by row count:**

| Ticker | First date | Last date | Rows | Gap events |
|---|---|---|---|---|
| BIL.N0000 | 2023-07-04 | 2026-08-21 | 761 | 0 |
| SAMP.N0000 | 2023-07-04 | 2026-08-21 | 759 | 0 |
| SCAP.N0000 | 2023-07-04 | 2026-08-21 | 759 | 0 |
| CALT.N0000 | 2023-07-04 | 2026-08-21 | 758 | 0 |
| LIOC.N0000 | 2023-07-04 | 2026-08-21 | 756 | 0 |
| AAIC.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| BRWN.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| CFVF.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| DIPD.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| HNB.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| PLR.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| RCL.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| SLTL.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| TJL.N0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |
| TKYO.X0000 | 2023-07-04 | 2026-08-21 | 755 | 0 |

**Worst 10 tickers by gap-event count:**

| Ticker | Gap events |
|---|---|
| SFCL.N0000 | 34 |
| HARI.N0000 | 30 |
| PARA.N0000 | 23 |
| ATLL.N0000 | 22 |
| CPRT.N0000 | 22 |
| CIT.N0000 | 21 |
| LAMB.N0000 | 20 |
| MAL.X0000 | 18 |
| LPRT.N0000 | 17 |
| OFEQ.N0000 | 17 |

- `median_spread_pct_20d` (named in the brief): **this column does not exist anywhere in this schema.** The real, closest equivalent this system computes is the Amihud illiquidity percentile (`app.domain.liquidity_view.liquidity_percentile_for`), computed on read from `prices_daily.turnover`/`volume`, not stored as a column — there is nothing to report coverage of under the brief's own field name without inventing a column that was never built. `turnover` itself (a real value from the cse.lk EOD feed, not a close×volume approximation) is populated on 133760 of 199992 price rows.

## Corporate actions

- Total rows: **343**
- Status: confirmed **98**, rejected **5**, awaiting confirmation **240** (`total - confirmed - rejected`, the exact formula `app.api.routes.data_health.get_data_health` uses for the Today tab's own count)

**By type:**

| Type | Count |
|---|---|
| bonus_issue | 11 |
| dividend_cash | 305 |
| rights_issue | 17 |
| stock_split | 10 |

- Rows with no `source_url`: **0**

**Today-tab figure reconciliation:** the running app's own `GET /data-health` (`corporate_actions_pending`) computes `240` from this exact database using this exact formula, because it is literally the same query. The brief's reference figure ("240") is from an earlier point in time — real data grows forward every session (a real, expected divergence, not a defect) — the number this report and the live app agree on **today** is **240**.

## Financial statements

- Companies with >=1 full annual statement set (total_assets, total_equity, total_liabilities, net_income): **130**
- Companies with zero statement rows at all: **7** of 290

**Line-item count by provenance tier:**

| Tier | Count |
|---|---|
| A | 35073 |
| R | 70545 |

**Today-tab figure reconciliation:** `GET /data-health`'s `fundamentals_pending_confirmation` computes `35073` from this exact database with the exact same filter (`provenance_tier == AI_ASSISTED AND confirmed_by IS NULL`) this report just ran. Same conclusion as corporate actions above: the number now is the real, current, verified figure — **35073** — not the brief's earlier reference point.

**Top 15 companies by count of figures awaiting confirmation:**

| Ticker | Awaiting |
|---|---|
| VLL.N0000 | 896 |
| VLL.X0000 | 896 |
| TRAN.N0000 | 827 |
| UDPL.N0000 | 770 |
| RICH.N0000 | 682 |
| VPEL.N0000 | 607 |
| OSEA.N0000 | 581 |
| UCAR.N0000 | 574 |
| CITH.N0000 | 525 |
| SINS.N0000 | 520 |
| NAMU.N0000 | 484 |
| RCH.N0000 | 484 |
| TSML.N0000 | 453 |
| JKH.N0000 | 439 |
| KCAB.N0000 | 434 |

## Macro

**Every macro series stored:**

| Series | Observations | First | Last | Age (days) | Source |
|---|---|---|---|---|---|
| cbsl.awpr | 532 | 2024-05-10 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.ccpi_yoy | 342 | 2023-07-04 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.ncpi_yoy | 400 | 2023-07-04 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.policy_rate | 224 | 2025-09-10 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.srr | 741 | 2023-07-04 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.tbill_182d | 165 | 2023-06-27 | 2026-08-19 | 4 | cbsl.gov.lk daily indicators 2026-08-19 |
| cbsl.tbill_182d_secondary | 469 | 2023-07-05 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.tbill_364d | 165 | 2023-06-27 | 2026-08-19 | 4 | cbsl.gov.lk daily indicators 2026-08-19 |
| cbsl.tbill_364d_secondary | 374 | 2023-07-05 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.tbill_91d | 165 | 2023-06-27 | 2026-08-19 | 4 | cbsl.gov.lk daily indicators 2026-08-19 |
| cbsl.tbill_91d_secondary | 481 | 2023-07-05 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.usd_lkr_tt_buying | 741 | 2023-07-04 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cbsl.usd_lkr_tt_selling | 741 | 2023-07-04 | 2026-08-20 | 3 | cbsl.gov.lk daily indicators 2026-08-20 |
| cse.aspi | 241 | 2025-08-20 | 2026-08-18 | 5 | cse.lk:chartData(pc) |
| cse.foreign_net_flow | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.market_cap | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.market_dy | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.market_pbv | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.market_per | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.market_turnover | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| cse.sp_sl20 | 2 | 2026-08-17 | 2026-08-18 | 5 | cse.lk |
| factor.hml_hard | 163 | 2023-07-11 | 2026-08-18 | 5 | computed:factor_series_view |
| factor.liq | 159 | 2023-08-08 | 2026-08-18 | 5 | computed:factor_series_view |
| factor.mkt_rf | 163 | 2023-07-11 | 2026-08-18 | 5 | computed:factor_series_view |
| factor.mom | 112 | 2024-07-02 | 2026-08-18 | 5 | computed:factor_series_view |
| factor.smb | 163 | 2023-07-11 | 2026-08-18 | 5 | computed:factor_series_view |

- No series is stale (> 90 days old) — all 26 series are current as of this run.

**What the regime classifier actually needs, vs. what exists (feeds T2.1 directly):**

| Series | Needed for | Present? | Observations |
|---|---|---|---|
| cse.aspi | statistical Markov-regime fit — needs >=60 daily observations | yes | 241 |
| cbsl.policy_rate | composite read, signal 1 | yes | 224 |
| cbsl.tbill_364d | composite read, signal 2 (+ §17.2 Ke) | yes | 165 |
| cbsl.ccpi_yoy | composite read, signal 3 | yes | 342 |
| cbsl.usd_lkr_tt_buying | composite read, signal 4 (LKR/USD trend) | yes | 741 |
| cse.market_per | the §29 hero spread (equity earnings yield leg) | yes | 2 |

## Synthetic data sweep

- Codebase grep for fixture/demo/seed/mock/dummy/fake identifiers outside `tests/`: **0 hits**

- Canary fixture tickers (THIRD.N0000, FIXTURE.N0000, DEMO.N0000, TEST.N0000) present in the audited database: **0**

- **Structural isolation, not just a filter**: every DB-touching backend test (`tests/conftest.py::db_session`) runs against a fresh `sqlite:///:memory:` engine created directly from `Base.metadata`, entirely independent of `settings.database_url` — a test can never write to the database this audit just queried, by construction, not by a filter that could be forgotten on one query path. This is a stronger guarantee than the brief's own literal ask ("excluded by an explicit filter"), so no such filter exists to point to — the isolation is architectural. The canary check above is the closest thing to the brief's own literal CI assertion, and is now wired into this reusable script so it reruns on every future audit.

## Reconciliation with source (T1.2)

Sampled **20** tickers (fixed seed=42), one figure each (revenue/net_income/total_equity, in that priority order, whichever exists with a real `source_url`). Each figure was independently re-verified by downloading the actual filing PDF at its stored `source_url` **right now** and rerunning this project's own production extraction pipeline against it fresh — not a cached copy, not the value trusted from ingestion time.

- Match: **16**  ·  Mismatch: **2**  ·  Unverifiable: **2**
- Mismatch rate (of checked, excluding unverifiable): **10.0%**

| Ticker | Line | Period | Stored | Re-extracted | Outcome | Detail |
|---|---|---|---|---|---|---|
| CFVF.N0000 | net_income | 2026-03-31 | 2,105,169,000.0000 | 2,105,169,000 | match |  |
| AGST.N0000 | net_income | 2015-03-31 | 212,593,026.0000 | — | unverifiable | ReadTimeout: The read operation timed out |
| KFP.N0000 | revenue | 2026-01-27 | 2,227,656,000.0000 | 2,227,656,000 | match |  |
| HPFL.N0000 | revenue | 2022-03-31 | 223,736,214.0000 | 223,736,214 | match |  |
| HAYC.N0000 | revenue | 2026-06-30 | 13,681,703,000.0000 | — | unverifiable | ConnectTimeout: _ssl.c:1064: The handshake operation timed out |
| COCO.N0000 | revenue | 2026-06-30 | 3,768,619,000.0000 | 3,768,619,000 | match |  |
| CDB.X0000 | revenue | 2026-06-30 | 8,857,102,000.0000 | 8,857,102,000 | match |  |
| WATA.N0000 | revenue | 2026-03-31 | 6,501,765,000.0000 | 6,501,765,000 | match |  |
| CALT.N0000 | net_income | 2026-03-31 | -231,308,334.0000 | -231,308,334 | match |  |
| RENU.N0000 | revenue | 2025-03-31 | 8.0000 | 261,589,819 | mismatch | stored=8.0000 vs re-extracted=261589819 |
| AINS.N0000 | net_income | 2026-06-30 | 9.0000 | 22,889,584 | mismatch | stored=9.0000 vs re-extracted=22889584 |
| AHUN.N0000 | revenue | 2026-03-31 | 52,349,252,000.0000 | 52,349,252,000 | match |  |
| CARG.N0000 | revenue | 2026-06-30 | 76,133,133,000.0000 | 76,133,133,000 | match |  |
| HAPU.N0000 | revenue | 2025-09-30 | 1,305,613,000.0000 | 1,305,613,000 | match |  |
| HHL.N0000 | revenue | 2025-12-31 | 35,008,957,000.0000 | 35,008,957,000 | match |  |
| TESS.X0000 | revenue | 2030-09-30 | 2,030,254.0000 | 2,030,254 | match |  |
| AGST.X0000 | net_income | 2015-03-31 | 212,593,026.0000 | 212,593,026 | match |  |
| EDEN.N0000 | revenue | 2026-06-30 | 1,135,305,000.0000 | 1,135,305,000 | match |  |
| RCL.N0000 | revenue | 2026-03-31 | 218,097,000.0000 | 218,097,000 | match |  |
| HARI.N0000 | revenue | 2026-06-30 | 1,928,084,000.0000 | 1,928,084,000 | match |  |

## Prioritised defect list

- **[RED] Financial statements / Reconciliation — OI-1** — Mismatch rate 10.0% exceeds the 2% stop-the-release threshold; root cause is a note-reference-token extraction bug live in 396 confirmed `Fundamental` rows across ~88 tickers (measured, see R1_OPEN_ISSUES.md OI-1). A related independent finding: `is_quarantined`/`DataAlert` do not actually gate `opportunity_ranking_view` or `portfolio_valuation_view` despite their own docstrings claiming they do.
  - Proposed fix: see R1_OPEN_ISSUES.md OI-1's 5-step remediation path (revert erroneous confirmations, full re-verification sweep, a tested parsing fix, re-sweep, fix the quarantine gap). Not yet executed — needs sign-off given scale (88 real companies' live data).
  - Estimate: re-verification sweep ~30-45 min background; parsing fix + tests ~1 day; full remediation ~1-2 days.
- **[AMBER] Prices** — 21 tickers have under 500 sessions of price history.
  - Proposed fix: Expected for recently-listed or not-yet-backfilled names (see ROADMAP's asymmetric backfill note) — verify none are supposed-to-be-backfilled tickers that silently failed.
  - Estimate: 0.5 day to triage the list
- **[AMBER] Financial statements** — 7 listed securities have zero extracted statement rows.
  - Proposed fix: Expected for names `getFinancialAnnouncement`'s recent-filings feed hasn't surfaced yet (ROADMAP's own documented gap — it's a recent-filings feed, not a historical archive). Cross-check the list against securities with a listing_date recent enough to explain it; anything older is worth a targeted extraction attempt.
  - Estimate: 1 day to triage
