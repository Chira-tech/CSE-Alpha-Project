# Phase 1 task list — point-in-time data spine

Gate to proceed to Phase 2 (Master Spec §54): reconciliation passes 30
consecutive days.

## Done

- [x] Repo scaffold, config, DB session management
- [x] Core schema (§9) as SQLAlchemy models: `securities`, `prices_daily`,
      `corporate_actions` (+ `notes`, `rejected_by`/`rejected_at`),
      `fundamentals`, `float_data`, `macro_series`, `data_alerts`
- [x] Alembic migrations (0001 initial schema, 0002 corporate_actions.notes,
      0003 corporate_actions rejection columns; Timescale hypertable
      optional/detected)
- [x] Corporate-action math: TERP, cumulative total-return adjustment
      factor series (§7, §P1) — pure functions, unit tested
- [x] Coverage gate logic: Gate 1 liquidity, Gate 2 structural, Gate 3
      integrity veto (§11.1) — pure functions, unit tested
- [x] Point-in-time query helper (§6) — tested against a restatement
      scenario
- [x] Provenance tier enum + "weakest wins" rule (§8)
- [x] cse.lk client verified against the live API: every endpoint is POST
      (not GET), with a hard split between JSON-body and form-urlencoded
      endpoints, plus real 204-No-Content handling. Full trace in
      `backend/app/ingestion/README_ENDPOINTS.md`.
- [x] Corporate-actions ingestion (`app/ingestion/corporate_actions_loader.py`):
      fetches announcements, classifies categories, fetches detail with
      the verified getAnnouncementById → getGeneralAnnouncementById
      fallback, and writes DRAFT rows (confirmed_by always None).
      **Now pairs the "initial disclosure" and "(DATES)" follow-up
      announcements** CSE publishes for both rights issues and share
      splits — verified against three independent real events (Asia Asset
      Finance PLC rights issue, Lanka Tiles and First Capital Holdings
      sub-divisions). The two action types use genuinely different ratio
      conventions (rights: new-per-held; splits: before:after) and this
      is now handled correctly, with its own tests, rather than guessed.
- [x] Human-confirm workflow API (`app/api/routes/corporate_actions.py`):
      list the pending queue, view/patch/confirm/reject a draft. Confirm
      re-uses the same domain validation the adjustment-factor build
      itself would apply (`app.domain.corporate_actions.price_ratio_for_event`),
      so a bad draft fails loudly at review time, not at 3am in the
      nightly batch. Reject is a distinct state from confirm (separate
      `rejected_by`/`rejected_at` columns) — deliberately not a shared
      status field, so nothing that filters on "is this confirmed" can
      accidentally include a rejected row.
- [x] EOD price ingestion (`app/ingestion/price_loader.py`) verified shape
- [x] Nightly reconciliation job (§7): independent adjusted-vs-raw total
      return cross-check with ticker quarantine on >0.5% mismatch
- [x] Scheduler (`app/jobs/scheduler.py`): EOD snapshot (15:00),
      reconciliation (15:05), corporate-actions scan (16:00)
- [x] FastAPI app: health, securities, corporate-actions endpoints
- [x] 103 unit tests passing, many against real captured API payloads
      rather than invented fixtures

## Not done yet — next in Phase 1

- [ ] **PDF financial-statement extraction → human confirmation queue**
      (§5, §8 tier `A`) — no work done yet
- [ ] **Confirm-queue frontend** — the API exists; there's no UI yet.
      Fine for now (can be driven via curl/httpie), but not a real
      workflow for daily use.
- [ ] **Plain bonus issue / consolidation**: still unverified — no live
      example of either was captured (sub-division/share-split, which
      looks similar, IS now verified and handled correctly — see
      README_ENDPOINTS.md). Treat any bonus_issue/consolidation draft as
      needing full manual reconstruction from the source PDF until a real
      example is found and the loader is corrected against it.
- [ ] **`notifications`/`notifications/corporate` etc.** — exist in CSE's
      frontend code as GET calls but returned 400 live; not used by
      anything here, re-verify before building against them
- [ ] Second data source integration (see PARAMETERS.md #5)
- [ ] 30-day consecutive reconciliation pass — can't be "done," only
      observed once the system is running continuously against live data
- [ ] Sustained-load testing of the cse.lk client's rate limiting (this
      session made ~60 manually-paced requests total across two
      verification passes, not a realistic load test)
- [ ] The rights-issue/split pairing heuristic (`_pair_rows` in
      corporate_actions_loader.py) assumes at most one overlapping event
      per type per company — untested against a company with two
      concurrent rights issues, for instance

## Explicitly deferred to later phases

Fundamental ratios, valuation models, macro/ARDL, factor library, scoring,
AI research writer, decision capture UI, frontend — all Phase 2+ per §54.
Building these against unvalidated data would produce exactly the
look-ahead-biased, false-precision numbers the spec's failure-mode register
(Part N) warns about.
