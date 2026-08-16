# Phase 1 task list — point-in-time data spine

Gate to proceed to Phase 2 (Master Spec §54): reconciliation passes 30
consecutive days.

## Done

- [x] Repo scaffold, config, DB session management
- [x] Core schema (§9) as SQLAlchemy models: `securities`, `prices_daily`,
      `corporate_actions` (+ `notes` for scraped source text),
      `fundamentals`, `float_data`, `macro_series`, `data_alerts`
- [x] Alembic migrations (0001 initial schema, 0002 corporate_actions.notes;
      Timescale hypertable optional/detected)
- [x] Corporate-action math: TERP, cumulative total-return adjustment
      factor series (§7, §P1) — pure functions, unit tested
- [x] Coverage gate logic: Gate 1 liquidity, Gate 2 structural, Gate 3
      integrity veto (§11.1) — pure functions, unit tested
- [x] Point-in-time query helper (§6) — tested against a restatement
      scenario
- [x] Provenance tier enum + "weakest wins" rule (§8)
- [x] cse.lk client: rate-limited (≥2s), exponential backoff, circuit
      breaker, schema-validated, identifying user-agent (§5) — **and now
      verified against the live API**: every endpoint is POST (not GET),
      with a hard split between JSON-body endpoints and
      form-urlencoded endpoints, plus real 204-No-Content handling. See
      `backend/app/ingestion/README_ENDPOINTS.md` for the full trace.
- [x] Real endpoint verification (was the top item in "not done yet" —
      now done): probed marketStatus, tradeSummary, todaySharePrice,
      topGainers, topLooses, aspiData, dailyMarketSummery,
      companyInfoSummery, detailedTrades, getAnnouncementByCompany,
      getAnnouncementById, getGeneralAnnouncementById against
      www.cse.lk/api directly, confirmed via the site's own Next.js
      client code (`apiService` in its JS bundle), and rebuilt
      `app/ingestion/schemas.py` from the real response shapes rather
      than the spec's (correct-endpoint-name, wrong-HTTP-method) guess.
- [x] Corporate-actions ingestion (`app/ingestion/corporate_actions_loader.py`):
      fetches a company's announcement list, classifies categories against
      Master Spec §7 action types, fetches detail with the verified
      getAnnouncementById → getGeneralAnnouncementById fallback, and
      writes DRAFT rows (confirmed_by always None) — verified end-to-end
      against real captured cash-dividend and rights-issue payloads.
      Bonus-issue/stock-split/consolidation handling is present but
      explicitly marked unverified (no live example was captured this
      session) — see README_ENDPOINTS.md "Known gaps".
- [x] EOD price ingestion (`app/ingestion/price_loader.py`) rebuilt against
      the verified `tradeSummary` shape
- [x] Nightly reconciliation job (§7): independent adjusted-vs-raw total
      return cross-check with ticker quarantine on >0.5% mismatch
- [x] Scheduler (`app/jobs/scheduler.py`): EOD snapshot (15:00),
      reconciliation (15:05), corporate-actions scan (16:00) wired with
      APScheduler per the §52 job table shape
- [x] FastAPI skeleton with health + securities read endpoints
- [x] 76 unit tests passing, several against real captured API payloads
      rather than invented fixtures

## Not done yet — next in Phase 1

- [ ] **PDF financial-statement extraction → human confirmation queue**
      (§5, §8 tier `A`) — no work done yet
- [ ] **Human-confirm UI/workflow** for the corporate-actions draft queue
      — the data model and ingestion exist; nothing yet lets a person
      review a draft and set `confirmed_by`/`confirmed_at`. Right now
      that would have to be done directly against the DB.
- [ ] **Bonus issue / stock split / consolidation** — get a real example
      of each and correct `corporate_actions_loader.build_draft`'s
      generic handling once seen (currently unverified per README_ENDPOINTS.md)
- [ ] **Rights-issue subscription price**: the initial "RightsIssue"
      disclosure (subscription price) and the "(DATES)" follow-up
      (ex-date) are two separate announcements for the same event: the
      loader currently drafts each independently rather than correlating
      them, so a rights-issue draft from the dates record alone is
      missing `subscription_price` (flagged in `notes`, not silently
      wrong, but incomplete)
- [ ] **`notifications`/`notifications/corporate` etc.** — these exist in
      CSE's own frontend code as GET-based calls but returned 400 live;
      not used by anything in this codebase, re-verify before building
      against them
- [ ] Second data source integration (see PARAMETERS.md #5)
- [ ] 30-day consecutive reconciliation pass — can't be "done," only
      observed once the system is running continuously against live data
- [ ] Sustained-load testing of the cse.lk client's rate limiting (this
      session made ~40 manually-paced requests total, not a realistic
      load test)

## Explicitly deferred to later phases

Fundamental ratios, valuation models, macro/ARDL, factor library, scoring,
AI research writer, decision capture UI, frontend — all Phase 2+ per §54.
Building these against unvalidated data would produce exactly the
look-ahead-biased, false-precision numbers the spec's failure-mode register
(Part N) warns about.
