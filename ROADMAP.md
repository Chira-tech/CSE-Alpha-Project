# Phase 1 task list — point-in-time data spine

Gate to proceed to Phase 2 (Master Spec §54): reconciliation passes 30
consecutive days.

## Done

- [x] Repo scaffold, config, DB session management
- [x] Core schema (§9) as SQLAlchemy models: `securities`, `prices_daily`,
      `corporate_actions` (+ `notes`, `rejected_by`/`rejected_at`),
      `fundamentals` (+ `source_snippet`, `confirmed_by`/`confirmed_at`),
      `float_data`, `macro_series`, `data_alerts`
- [x] Alembic migrations 0001–0004 (Timescale hypertable optional/detected)
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
- [x] Corporate-actions ingestion, pairing the "initial disclosure" and
      "(DATES)" follow-up CSE publishes for both rights issues and share
      splits — verified against three independent real events (Asia Asset
      Finance PLC rights issue; Lanka Tiles and First Capital Holdings
      sub-divisions, which use a genuinely different ratio convention from
      rights issues and are now handled correctly rather than guessed).
- [x] Human-confirm workflow API for corporate actions: list/patch/confirm
      /reject, re-validating via the same domain logic the
      adjustment-factor build itself uses.
- [x] **New this session: financial-statement extraction.** Verified the
      `getFinancialAnnouncement` endpoint live (a global recent-filings
      feed, not per-company — see README_ENDPOINTS.md), downloaded a real
      160-page annual report, and built a deterministic line-item
      extractor (`app/domain/financial_statement_parsing.py` +
      `app/ingestion/financial_pdf_extractor.py`) covering the
      totals/subtotals of the balance sheet and income statement. This is
      explicitly NOT the "LLM-assisted line-item mapping" §5 describes —
      see PARAMETERS.md #9 — but it's a genuine, tested capability rather
      than a placeholder.
- [x] Fundamentals human-confirm API: promotes AI-assisted extractions to
      Reported (§8), the workflow the `can_enter_valuation` domain rule
      always assumed existed but that, until now, nothing implemented.
- [x] EOD price ingestion, nightly reconciliation job (§7, internal
      adjusted-vs-raw check only — see PARAMETERS.md #5 for what's still
      missing), scheduler running EOD snapshot / reconciliation /
      corporate-actions scan / financial-statement scan
- [x] FastAPI app: health, securities, corporate-actions,
      fundamentals endpoints
- [x] 170 backend unit tests passing, most against real captured API/PDF
      data rather than invented fixtures
- [x] **Runnable web app.** SQLite dev mode (documented fallback —
      Postgres+Timescale remains the §51 production target, and the same
      migrations apply to both), a `python -m app.cli bootstrap` command
      that pulls the real universe and latest prices from the live CSE
      API in a single request, and the screens below. Verified end-to-end
      against real bootstrapped data and visually in a browser.
- [x] **Frontend rebuilt against the UI & Experience Specification.**
      §7.1's navigation exactly (six primary destinations, a rule, two
      advanced), §3's type scale and three-weight limit, §4's 240px rail
      / 1360px content / three elevations / motion durations, §5's number
      and direction conventions, §14's evidence panel as a right
      slide-over, and §15.1's six component states — `ErrorState`'s props
      are named after the four things §15.1 says an error must state, so
      an incomplete one doesn't type-check. 15 automated spec checks pass
      (no raw hex outside the token file, no pill buttons, no weight
      above 600, reduced-motion and colour-scheme honoured, focus rings,
      skip link, no BUY/SELL verdict, and so on).
- [x] **Market endpoint made resilient.** Was: three sequential upstream
      calls at 2s pacing (4.5s every load) that returned 502 for the
      whole screen if any one failed. Now: per-section degradation with a
      named `unavailable` list (§15.1's Partial state) and a 60s cache —
      4.5s cold, 0.2s warm.
- [x] **Fixed a real point-in-time bug found in the running app**:
      bootstrap stamped prices with `date.today()`, so ingesting on a
      Sunday filed Friday's prices under a date the market never traded.
      Session date is now derived from the feed's own timestamps
      (`infer_session_date`, modal not max so one stale row can't drag
      the session). The scheduled EOD job had the same bug and is fixed
      too. This is exactly what §6 exists to prevent.
- [x] **New this session: confirm-queue frontend** (`frontend/`) — React +
      TypeScript, two tables (corporate actions, fundamentals) wired to
      the confirm APIs above, using the UI spec's design tokens. NOT the
      Phase 2+ product frontend (screener, company file, etc.) — see
      `frontend/README.md` for the distinction. End-to-end smoke tested:
      backend served real seeded data over CORS to the dev server,
      confirming a fundamentals draft promoted it and removed it from the
      queue; confirming an incomplete rights-issue draft correctly
      refused with the exact missing-field message.

## Not done yet — next in Phase 1

- [ ] **Second data source for reconciliation** (PARAMETERS.md #5) — the
      internal adjusted-vs-raw check exists; an independent external
      cross-check does not.
- [ ] **LLM-assisted extraction** (PARAMETERS.md #9) — needs an explicit
      decision (API key, model, cost) before it's worth building; the
      deterministic extractor covers a real but limited subset of line
      items until then.
- [ ] **Financial-statement historical backfill** — `getFinancialAnnouncement`
      is a recent-filings feed only; a different, not-yet-identified
      source is needed to backfill history to the Part O #2 target
      (2015-01-01).
- [ ] **Price history is one day deep.** `bootstrap` seeds the latest
      session only; depth accumulates one day at a time from the
      scheduled EOD job. No historical price backfill source has been
      found on the CSE API — this blocks anything needing a time series
      (factor library, momentum, beta, Amihud liquidity), i.e. most of
      Phases 2 and 6. Worth solving early; a broker EOD file (the same
      second source PARAMETERS.md #5 wants) may cover both needs at once.
- [ ] **`cse_sector` and `archetype` are NULL for every company.**
      Bootstrap deliberately doesn't guess them — archetype drives the
      valuation model router (§15/§16) and a wrong one silently routes a
      bank through an industrial DCF (Part N #7). Needs a real mapping,
      hand-corrected per Appendix P2. Blocks sector-relative anything.
- [ ] **Plain bonus issue / consolidation**: still unverified after ~40
      tickers probed across two sessions — no live example of either was
      found. Share splits (which looked similar) ARE now verified.
- [ ] **`notifications`/`notifications/corporate` etc.** — exist in CSE's
      frontend code as GET calls but returned 400 live; unused, re-verify
      before building against them
- [ ] 30-day consecutive reconciliation pass — can't be "done," only
      observed once the system is running continuously against live data
- [ ] Sustained-load testing of the cse.lk client's rate limiting
- [ ] The rights-issue/split announcement-pairing heuristic
      (`_pair_rows` in corporate_actions_loader.py) is untested against a
      company with two concurrent events of the same type
- [ ] The financial-statement extractor's canonical label list
      (`CANONICAL_LABELS`) is verified against exactly one real filing —
      wording varies across companies and will need expanding as more
      real filings are processed
- [ ] `npm audit` flags a moderate-severity vulnerability in Vite's dev
      dependency chain (esbuild) affecting the dev server only, not
      production builds — low priority for an internal tool only ever run
      against localhost, but a `npm audit fix --force` (major Vite
      upgrade) should happen before this ships anywhere less trusted than
      a developer's own machine

## Explicitly deferred to later phases

Fundamental ratios, valuation models, macro/ARDL, factor library, scoring,
AI research writer, decision capture UI, frontend — all Phase 2+ per §54.
Building these against unvalidated data would produce exactly the
look-ahead-biased, false-precision numbers the spec's failure-mode register
(Part N) warns about.
