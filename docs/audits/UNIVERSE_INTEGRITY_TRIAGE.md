# Universe Integrity — Phase 1 Triage

Generated: 2026-08-30T10:20:38+00:00Z · DB: `sqlite+pysqlite:///./devdb.sqlite`

Report-only. Every number below is reproducible by re-running `python -m scripts.audit_universe_integrity` from `backend/`. Nothing was written; no ticker was quarantined. This is the measurement the rollout's Phase 2 acts on.

- Listed lines scanned: **294**
- Distinct issuers: **273**
- Issuers with no ordinary/non-voting line at all: **3** — CALC, CALI, CALU

## Triage buckets

| Bucket | Lines | Example |
|---|---|---|
| Unresolved / unknown line type | 0 | — |
| Wrong line bound (nil-paid rights fingerprint) | 0 | — |
| Rights-price incoherent (wrong line suspected) | 0 | — |
| Market-cap identity fail | 5 | ABL.N0000 |
| Implausible implied multiple | 0 | — |
| Unexplained price discontinuity | 47 | AAIC.N0000 |
| Rights line not reaped | 0 | — |
| Stale price | 0 | — |
| Sector model routing gap | 58 | AFS.N0000 |
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

### Unexplained price discontinuity — 47

- AAIC.N0000 moved +116% in one session on 2024-09-28 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- ABL.N0000 moved +918% in one session on 2024-07-15 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- ACME.N0000 moved +49% in one session on 2026-02-06 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- AFS.N0000 moved -81% in one session on 2024-01-26 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- ASPH.N0000 moved +33% in one session on 2023-07-11 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- BIL.N0000 moved +33% in one session on 2024-12-02 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- BOGA.N0000 moved +30% in one session on 2025-08-12 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- BRWN.N0000 moved -38% in one session on 2026-04-14 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- CALF.N0000 moved +49% in one session on 2026-02-09 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- CALI.U0000 moved +31% in one session on 2024-02-16 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- CFVF.N0000 moved -32% in one session on 2026-07-19 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- COCO.N0000 moved +31% in one session on 2025-11-10 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- COCO.X0000 moved -55% in one session on 2026-03-23 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- COMD.N0000 moved +34% in one session on 2025-07-24 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- CONN.N0000 moved +36% in one session on 2025-03-03 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- CPRT.N0000 moved +42% in one session on 2024-08-15 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- DOCK.N0000 moved +57% in one session on 2025-07-02 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- FCT.N0000 moved +30% in one session on 2025-09-18 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- HARI.N0000 moved +34% in one session on 2024-09-04 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- HDFC.N0000 moved +31% in one session on 2025-01-02 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- JETS.N0000 moved +39% in one session on 2025-07-17 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LGL.N0000 moved +65% in one session on 2025-09-08 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LGL.X0000 moved +56% in one session on 2025-09-08 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LIOC.N0000 moved +75% in one session on 2026-01-07 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LMF.N0000 moved +821% in one session on 2024-09-08 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LOFC.N0000 moved +31% in one session on 2024-09-16 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LPL.N0000 moved +58% in one session on 2025-09-08 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LPL.X0000 moved +63% in one session on 2025-09-08 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LPRT.N0000 moved +33% in one session on 2026-03-25 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- LUMX.N0000 moved +46% in one session on 2026-02-05 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- MERC.N0000 moved +125% in one session on 2025-10-13 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- MSL.N0000 moved +41% in one session on 2024-06-06 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- NEH.N0000 moved +60% in one session on 2024-01-12 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- RCL.N0000 moved -33% in one session on 2025-07-27 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- RICH.N0000 moved -35% in one session on 2026-03-15 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- SCAP.N0000 moved +41% in one session on 2023-09-30 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- SEMB.N0000 moved +43% in one session on 2025-10-09 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- SEMB.X0000 moved +33% in one session on 2023-07-06 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- SHL.N0000 moved +47% in one session on 2026-03-10 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- SING.N0000 moved +54% in one session on 2023-08-23 with no corporate action recorded for that date — a split not applied, a decimal shift, or a wrong-line swap rather than a real move.
- … and 7 more

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

## Currently-open DataAlerts (the enforcing side, already live)

| alert_type | open |
|---|---|
| valuation_sanity_block | 8 |
| second_source_mismatch | 5 |
| market_cap_mismatch | 5 |

The buckets above that map to a `DataAlert.alert_type` (`market_cap_mismatch`, `rights_price_incoherent`, `wrong_line_fingerprint`, `implausible_multiple`, `price_discontinuity`) become blocking quarantine rows once `app.jobs.scheduler`'s `universe_integrity_checks` job runs; the rest are report-only signals for a human worklist.
