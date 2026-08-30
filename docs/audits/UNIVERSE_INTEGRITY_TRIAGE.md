# Universe Integrity — Phase 1 Triage

Generated: 2026-08-30T11:22:36+00:00Z · DB: `sqlite+pysqlite:///./devdb.sqlite`

Report-only. Every number below is reproducible by re-running `python -m scripts.audit_universe_integrity` from `backend/`. Nothing was written; no ticker was quarantined. This is the measurement the rollout's Phase 2 acts on.

- Listed lines scanned: **294**
- Distinct issuers: **273**
- Issuers with no ordinary/non-voting line at all: **3** — CALC, CALI, CALU

## Triage buckets

| Bucket | Count | Example |
|---|---|---|
| Unresolved / unknown line type | 0 | — |
| Wrong line bound (nil-paid rights fingerprint) | 0 | — |
| Rights-price incoherent (wrong line suspected) | 0 | — |
| Market-cap identity fail | 5 | ABL.N0000 |
| Implausible implied multiple | 0 | — |
| Rights line not reaped | 0 | — |
| Stale price | 0 | — |
| Sector model routing gap | 58 | AFS.N0000 |
| Price discontinuity — at a raw/adjusted feed join, near a split | 36 events / 34 lines | ACL.N0000 |
| Price discontinuity — decimal / units artefact (~10x, no action) | 1 events / 1 lines | ABL.N0000 |
| Price discontinuity — genuinely unexplained (quarantines) | 327 events / 42 lines | AAIC.N0000 |
| Cost of equity unavailable (proxy: financial line, no beta) | 0 | — |

## Detail, per bucket

### Unresolved / unknown line type — 0

_None._

### Wrong line bound (nil-paid rights fingerprint) — 0

_None._

### Rights-price incoherent (wrong line suspected) — 0

_None._

### Market-cap identity fail — 5

- ABL.N0000: price × shares (14,331,792,956) disagrees with the exchange's own published market cap (14,662,526,640) by 2.3% — outside the 2% band. Usually a wrong share class, a stale share count, or a units error.
- ACME.N0000: price × shares (2,859,500,000) disagrees with the exchange's own published market cap (2,926,000,000) by 2.3% — outside the 2% band. Usually a wrong share class, a stale share count, or a units error.
- AEL.N0000: price × shares (74,700,000,000) disagrees with the exchange's own published market cap (77,000,000,000) by 3.0% — outside the 2% band. Usually a wrong share class, a stale share count, or a units error.
- AFS.N0000: price × shares (1,036,035,000) disagrees with the exchange's own published market cap (1,062,600,000) by 2.5% — outside the 2% band. Usually a wrong share class, a stale share count, or a units error.
- AFSL.N0000: price × shares (6,566,061,536) disagrees with the exchange's own published market cap (6,956,635,342) by 5.6% — outside the 2% band. Usually a wrong share class, a stale share count, or a units error.

### Implausible implied multiple — 0

_None._

### Rights line not reaped — 0

_None._

### Stale price — 0

_None._

### Sector model routing gap — 58

- AFS.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- ASIR.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- AUTO.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- BPPL.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- BREW.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CALC.U0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CALH.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CALI.U0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CALT.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CALU.U0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CFLB.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CFVF.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CIC.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CIC.X0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CINS.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CINS.X0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- COLO.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- COOP.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CSLK.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- CTHR.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- EML.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- EXT.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- FCT.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- GREG.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- HBS.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- HHL.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- HUNA.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- INME.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- JAT.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- JETS.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- JFP.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- JXG.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- KPHL.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LAMB.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LCBF.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LGIL.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LION.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LOLC.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LPRT.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- LUMX.N0000 has no archetype — its valuation cannot be routed to the correct model family for its sector.
- … and 18 more

### Price discontinuity — near a corporate action — 36 events across 34 lines

A >30% one-day move within 5 days of a confirmed corporate action (mostly stock splits). Spot-checking several against the raw rows: the jump sits on the boundary where this system's forward-captured EOD feed (`market_time_sales_export`) meets the backfilled chart history (`companyChartDataByStock`), and a stock split fell in that same window. On the checked names the chart-history side already reads at the POST-split level on the ex_date (ACL, APLA, COCO) with no pre-split close visible — i.e. that endpoint appears to return split-adjusted history, which is then stitched raw against the unadjusted EOD feed. The move is real; the artefact is two price sources with different adjustment conventions joined without reconciliation. Remediation: verify the `companyChartDataByStock` adjustment convention, reconcile it at the join, then rebuild the derived series — NOT an ex_date correction (the ex_dates check out).

- MERC.N0000 2025-12-17 -100%
- YORK.N0000 2026-01-09 -99%
- CPRT.N0000 2026-04-20 -99%
- NAMU.N0000 2026-03-09 -92%
- LMF.N0000 2024-01-17 -91%
- CDB.X0000 2026-04-30 -90%
- CDB.N0000 2026-04-30 -90%
- KCAB.N0000 2025-12-29 -90%
- JKH.N0000 2024-11-06 -90%
- APLA.N0000 2025-12-29 -90%
- SIGV.N0000 2026-01-14 -90%
- UML.N0000 2026-01-22 -89%
- COLO.N0000 2025-10-23 -88%
- CWM.N0000 2026-02-06 -81%
- WATA.N0000 2025-03-03 -80%
- BFL.N0000 2025-12-26 -80%
- CIC.N0000 2025-10-22 -80%
- HHL.N0000 2025-05-07 -80%
- CIC.X0000 2025-10-22 -80%
- CHL.X0000 2026-03-05 -79%
- HPWR.N0000 2026-01-08 -78%
- WAPO.N0000 2026-03-23 -77%
- CHL.N0000 2026-03-05 -76%
- GREG.N0000 2026-05-19 -75%
- SUN.N0000 2025-02-19 -75%
- DOCK.N0000 2025-12-05 -70%
- ACL.N0000 2025-12-29 -67%
- JINS.N0000 2026-04-09 -64%
- ACME.N0000 2026-02-05 -59%
- COCO.X0000 2026-03-23 -55%
- COCO.N0000 2026-03-23 -53%
- LCEY.N0000 2025-12-16 -53%
- YORK.N0000 2026-01-13 +50%
- ACME.N0000 2026-02-06 +49%
- HARI.N0000 2024-09-04 +34%
- KZOO.N0000 2026-03-04 -33%

### Price discontinuity — decimal / units artefact — 1 events across 1 lines

A ~10x or ~0.1x one-day jump with no corporate action anywhere near — a decimal shift or a units error in the price feed, not a market move. Remediation: correct the raw price row(s) at source and re-ingest.

- ABL.N0000 2024-07-15 +918%

### Price discontinuity — genuinely unexplained — 327 events across 42 lines

A >30% one-day move with no corporate action nearby and no round-number signature. On the CSE many of these are real moves in very thin small-caps; each still needs a human eye before it is trusted. THIS is the bucket the enforcing job quarantines on.

- TAP.N0000 2026-01-16 +464%
- SCAP.N0000 2024-07-13 +137%
- MERC.N0000 2025-10-13 +125%
- AAIC.N0000 2024-09-28 +116%
- TAP.N0000 2026-01-15 -82%
- AFS.N0000 2024-01-26 -81%
- LIOC.N0000 2026-01-07 +75%
- SCAP.N0000 2025-03-23 +75%
- LGL.N0000 2025-09-08 +65%
- LPL.X0000 2025-09-08 +63%
- BRWN.N0000 2026-04-15 +63%
- RCL.N0000 2025-07-28 +63%
- ASPH.N0000 2026-07-08 +60%
- NEH.N0000 2024-01-12 +60%
- LPL.N0000 2025-09-08 +58%
- SCAP.N0000 2024-07-15 -58%
- DOCK.N0000 2025-07-02 +57%
- LGL.X0000 2025-09-08 +56%
- SING.N0000 2023-08-23 +54%
- AAIC.N0000 2024-09-30 -53%
- ASPH.N0000 2023-10-12 +50%
- ASPH.N0000 2023-10-16 +50%
- ASPH.N0000 2023-10-19 +50%
- ASPH.N0000 2023-10-31 +50%
- ASPH.N0000 2023-11-13 +50%
- ASPH.N0000 2023-11-24 +50%
- ASPH.N0000 2023-12-13 +50%
- ASPH.N0000 2024-09-04 +50%
- SEMB.X0000 2023-10-12 +50%
- SEMB.X0000 2023-11-17 +50%
- SEMB.X0000 2023-11-24 +50%
- SEMB.X0000 2023-12-07 +50%
- SEMB.X0000 2023-12-22 +50%
- SEMB.X0000 2023-12-28 +50%
- SEMB.X0000 2024-01-26 +50%
- SEMB.X0000 2024-01-30 +50%
- SEMB.X0000 2024-02-02 +50%
- SEMB.X0000 2024-02-14 +50%
- SEMB.X0000 2024-02-20 +50%
- SEMB.X0000 2024-02-27 +50%
- … and 287 more

## Currently-open DataAlerts (the enforcing side, already live)

| alert_type | open |
|---|---|
| valuation_sanity_block | 8 |
| second_source_mismatch | 5 |
| market_cap_mismatch | 5 |

The buckets above that map to a `DataAlert.alert_type` (`market_cap_mismatch`, `rights_price_incoherent`, `wrong_line_fingerprint`, `implausible_multiple`, `price_discontinuity`) become blocking quarantine rows once `app.jobs.scheduler`'s `universe_integrity_checks` job runs; the rest are report-only signals for a human worklist.
