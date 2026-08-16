# Phase 1 task list — point-in-time data spine

Gate to proceed to Phase 2 (Master Spec §54): reconciliation passes 30
consecutive days.

## Done in this session

- [x] Repo scaffold, config, DB session management
- [x] Core schema (§9) as SQLAlchemy models: `securities`, `prices_daily`,
      `corporate_actions`, `fundamentals`, `float_data`, `macro_series`,
      `data_alerts`
- [x] Alembic migration wired up (Timescale hypertable optional/detected)
- [x] Corporate-action math: TERP, cumulative total-return adjustment factor
      series (§7, §P1) — pure functions, unit tested
- [x] Coverage gate logic: Gate 1 liquidity, Gate 2 structural, Gate 3
      integrity veto (§11.1) — pure functions, unit tested
- [x] cse.lk client: rate-limited (≥2s), exponential backoff, circuit
      breaker, schema-validated responses, identifying user-agent (§5)
- [x] Provenance tier enum + rule that a derived value inherits the worst
      provenance of its inputs (§8)
- [x] FastAPI skeleton with health + securities read endpoints
- [x] Nightly reconciliation job skeleton (§7) — total-return-from-adjusted
      vs total-return-from-raw-plus-actions cross-check, quarantine on >0.5%
      mismatch

## Not done yet — next in Phase 1

- [ ] Real cse.lk endpoint mapping (marketStatus, tradeSummary,
      todaySharePrice, detailedTrades, companyInfoSummery, announcements) —
      client is built generically; endpoint paths need confirming against
      the live API since they're undocumented and may have shifted since
      the spec was written
- [ ] PDF financial-statement extraction → human confirmation queue (§5, §8
      tier `A`)
- [ ] Corporate-actions scrape from CSE announcements + mandatory human
      confirm UI (currently: model + math exist, ingestion source doesn't)
- [ ] Second data source integration (see PARAMETERS.md #5)
- [ ] Scheduler wiring (APScheduler) for the job table in §52
- [ ] 30-day consecutive reconciliation pass — can't be "done," only
      observed once the system is running against live data

## Explicitly deferred to later phases

Fundamental ratios, valuation models, macro/ARDL, factor library, scoring,
AI research writer, decision capture UI, frontend — all Phase 2+ per §54.
Building these against unvalidated data would produce exactly the
look-ahead-biased, false-precision numbers the spec's failure-mode register
(Part N) warns about.
