# Phase 1 task list — point-in-time data spine

Gate to proceed to Phase 2 (Master Spec §54): reconciliation passes 30
consecutive days.

## Done

- [x] Repo scaffold, config, DB session management
- [x] Core schema (§9) as SQLAlchemy models: `securities`, `prices_daily`,
      `corporate_actions` (+ `notes`, `rejected_by`/`rejected_at`),
      `fundamentals` (+ `source_snippet`, `confirmed_by`/`confirmed_at`),
      `float_data`, `macro_series`, `data_alerts`
- [x] Alembic migrations 0001–0005 (Timescale hypertable optional/detected)
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
- [x] 276 backend unit tests passing, most against real captured API/PDF
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
- [x] **Per-company enrichment** (`app/ingestion/security_enrichment.py`,
      `python -m app.cli enrich`): ISIN, listing date and shares issued
      from `companyInfoSummery`, verified against real companies (Abans
      listed 1984-01-01, Asia Asset Finance ISIN LK0406N00005). These fill
      columns Gate 2 (§11.1) needs in order to run at all. Never
      overwrites a hand-set value; never sets sector/archetype; never
      derives free float from foreign holding — migration 0005 makes
      `public_float_pct` nullable instead, and Gate 2 now treats an
      unknown float as "cannot evaluate" rather than silently passing,
      which is the behaviour a hard gate must have.
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

## Phase 2 — fundamental engine (started)

- [x] **Always-on worker** (`python -m app.worker`). Holds the §52
      schedule; kept out of the API process so `uvicorn --reload` can't
      skip or double-fire jobs. **Caught a real timezone bug doing this:**
      `CronTrigger` resolves its timezone at construction, defaulting to
      the *host's* zone — on this machine (Australia/Perth, +08:00) the
      "15:00 EOD snapshot" was scheduled for 12:30 Colombo, i.e. two hours
      before the CSE closes, so it would have captured a mid-session price
      and stored it as the close. Every trigger is now explicitly
      Colombo-timed, with tests pinning it.
- [x] **Ratio engine** (`app/domain/ratios.py`, §12): 10 ratios computable
      from the line items the extractor actually pulls — ROE, ROA, gross
      and operating and net margin, Novy-Marx gross profitability, current
      ratio, liabilities/equity, equity ratio, effective tax rate. Pure
      functions, verified against J.F. Packaging PLC's real FY2025/26
      statements with hand-computed expected values.
      - Ratios inherit the weakest provenance of their inputs (§8).
      - Non-positive denominators return "not meaningful" rather than a
        number: negative equity yields a *positive* ROE arithmetically,
        which would rank the most distressed company top of a screen.
      - The leverage ratio is named `liabilities_to_equity`, NOT
        debt/equity — total liabilities includes payables and deferred
        tax, and the conventional name would invite a wrong comparison.
      - The 10 §12 ratios that need line items we don't extract (ROIC,
        Piotroski, Altman Z", Beneish, cash conversion, ...) are declared
        with exactly what each is missing, so the UI states the gap.
- [x] Ratios surfaced on the company file with provenance chips, correct
      units (§5.1: `1.38×`, `40.1%`), and evidence-panel drill-down.
- [x] **Found and fixed a data-corruption bug in the PDF extractor.**
      On J.F. Packaging's *interim* statements (but not its annual report)
      pdfplumber emitted `4 ,453,103` — a space between the leading digit
      and the first comma group. The line still tokenised, the stray `4`
      looked exactly like a note reference, the note-reference rule
      dropped it, and Total Assets was stored as 453,103 instead of
      4,453,103 — wrong by four billion rupees and entirely plausible on
      screen. Fixed three ways: repair split thousands before tokenising;
      tighten the number pattern so a comma-leading fragment is never a
      valid figure; and add **accounting-identity checks** (assets =
      equity + liabilities, current + non-current = total, revenue −
      cost of sales = gross profit, ...) that run before anything is
      stored and stamp a prominent warning onto every draft from a filing
      that doesn't balance. The identity check catches this class of
      corruption independently of the regex.

## Phase 5 groundwork — the hero variable

- [x] **§29's hero spread is live**: equity earnings yield (1 ÷ market
      P/E, from CSE's `dailyMarketSummery`) minus the 364-day T-bill
      yield. The spec calls this "the single most powerful macro variable
      in the system" and puts it on the home screen — it is now there,
      with a zero-baseline sparkline and an accessible data table (§15.2).
      Current reading: **−1.43pp**, i.e. equities yielding *less* than
      risk-free bills — the "equity as bond substitute" condition §29 is
      built around.
- [x] `macro_series` is finally used: market P/E, PBV, dividend yield,
      ASPI, S&P SL20, turnover, market cap and foreign net flow captured
      daily (`capture-market`, and a scheduled job at 15:02 Colombo).
- [x] Unit discipline enforced at the edge: CSE publishes dividend yield
      as a percentage, the T-bill CLI takes `--percent`, and everything is
      stored as a decimal fraction. Mixing the two conventions would give
      a spread wrong by 100× that still looks like a plausible number, so
      there is a test asserting both yields stay fractions.
- [x] Point-in-time pairing: `spread_history` pairs each market
      observation with the T-bill rate that was *public on that date*,
      not the latest one — otherwise every rate change would silently
      rewrite history.

### The T-bill rate is now scraped, not entered by hand

**Superseded by the CBSL scraper below.** The manual `record-macro`
command still exists and is still the right tool for a series CBSL
doesn't publish daily, but the risk-free rate no longer needs it.

### (Historical note) The T-bill rate was entered by hand

CBSL publishes on JavaScript-rendered pages, so automated collection is a
real integration (§5 lists it as "API + scrape, release-calendar driven")
rather than a fetch. Until that exists:

```bash
python -m app.cli record-macro --series cbsl.tbill_364d \
  --value 10.2 --percent --date 2026-08-12 --source "CBSL weekly auction"
```

It lands in the same point-in-time series as everything else, carries
`source`, and the UI states plainly that it was entered manually. A
hard-coded constant pretending to be live data would not be acceptable;
a dated, sourced manual observation is.

### CBSL scraper — built

- [x] **CBSL Daily Economic Indicators scraper.** The pages are Drupal
      views rendered client-side, so the data isn't in the HTML — but the
      view (`daily_economic_indicators` over `/en/views/ajax`) lists PDF
      editions at a fully predictable URL, archived back to **2013**:
      `daily_economic_indicators_YYYYMMDD_e.pdf`.
- [x] Parses 13 series per edition: 91/182/364-day T-bill yields (primary
      AND secondary market, kept separate — §17.2 wants the primary
      auction), policy rate, SRR, AWPR, CCPI and NCPI year-on-year, and
      USD/LKR TT buying/selling.
- [x] **The risk-free rate is now real**, and it corrected the manual
      estimate: the hero spread moved from −1.43pp (hand-entered 10.2%)
      to −1.24pp (actual 10.01% primary-market 364-day yield).
- [x] Honours CBSL's published `robots.txt` `Crawl-delay: 10` exactly —
      not the 2s used for CSE. A full backfill to 2013 would take many
      hours, and that is the correct trade, not something to tune around.
- [x] Three dates per observation, all different and all real: the
      T-bill columns are dated 1–2 days before the edition that carries
      them, and the edition footer says "Published on" the day AFTER its
      cover date. Only `first_available_date` gates point-in-time queries.

- [ ] **Backfill to 2013 not yet run.** The machinery works; at 10s per
      request it is a long unattended job. `python -m app.cli cbsl
      --start 2013-01-01` would do it, ideally in chunks.
- [ ] Other CBSL series in §29's set (reserves, M2b, private credit,
      trade balance, tourist arrivals) are NOT in the daily PDF — they
      come from monthly/weekly publications that need their own parsers.

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
- [ ] **Price history is one day deep — now confirmed unsolvable from the
      CSE API.** A full sweep of the site's own endpoint list (see the
      inventory in README_ENDPOINTS.md) found `chartData`, which returns
      up to ~1 year of daily points but **for the ASPI index only** —
      every per-company id returns `[]`. `companyInfoSummery`'s
      hi/lo/volume fields are period aggregates, not a series. So there is
      no per-company historical price source on the public API, and this
      genuinely blocks the factor library, momentum, Dimson beta and
      Amihud liquidity — most of Phases 2 and 6. **A broker EOD file is
      now the only identified route**, and it would also satisfy
      PARAMETERS.md #5's second-source requirement: one decision, two
      blockers cleared.
- [ ] **`cse_sector` and `archetype` — confirmed not available from the
      API at all.** No endpoint carries company→sector membership
      (`allSectors` gives index levels only). This matches Appendix P2,
      which says the archetype mapping is maintained as a hand-corrected
      version-controlled file. Needs a deliberate mapping exercise, not
      more API work. Blocks sector-relative percentiles (§12) and the
      valuation model router (§16).
- [x] **ASPI daily history captured — 239 closes, Aug 2025 to Aug 2026**
      (`python -m app.cli backfill-index`). The only genuine historical
      series on the public CSE API. 1 year is still well short of what
      regime estimation wants, but it is a year more than the forward-only
      capture had.
      - **Reading it naively would have been wrong on 38% of days.** The
        feed's `v` is the official close only on points stamped after the
        14:30 close; points stamped 08:16 carry a provisional level,
        wrong by up to 0.55% (20-50 index points). The published `pc` is
        reliable in both cases, so the close is recovered exactly as
        `v[i]/(1+pc[i]/100)`.
      - **Verified against an independent institution**, not just internal
        consistency: CBSL prints the ASPI in its daily PDF and matched the
        recovery to 0.00 points on every testable date while disagreeing
        with the raw `v` by 19.79-48.90. Those CBSL figures are the
        expected values in `tests/test_index_history.py`.
      - `source` distinguishes the two readings
        (`cse.lk:chartData` vs `cse.lk:chartData(pc)`) — 106 direct, 133
        recovered — so a later reader can tell which rows rest on the
        identity. Across the full year the two independent routes never
        disagreed on a single post-close day.
      - Surfaced on the Macro screen as a year-long line with its axis
        range stated in the caption. §17 forbids "charts without a zero
        baseline where one is meaningful" — zero is NOT meaningful for an
        index level, and a zero-based axis would flatten a real 15%
        drawdown into nothing, so the range is stated explicitly instead,
        which is what that anti-pattern is actually protecting against.
        The caption also says how many closes were reconstructed and why.
      - Scheduled weekly (Saturday 06:00 Colombo) rather than daily: the
        same-day close already arrives via `capture-market`, and existing
        rows are never overwritten, so the job only repairs gaps. **That
        makes ASPI history self-healing for up to a year** — unlike
        prices, where a missed day is gone for good.
- [ ] **`allSecurityCode`** exposes an `active` flag per security — the
      only endpoint found that distinguishes inactive listings, relevant
      to §7's survivorship requirement. No delisting date, and not yet
      used by any loader.
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
