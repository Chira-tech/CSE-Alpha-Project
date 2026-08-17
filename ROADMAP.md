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
      integrity veto (§11.1) — pure functions, unit tested. **Still not
      wired to any real data anywhere in the app** (`grep` for the
      `evaluate_gate*` functions outside `coverage_gates.py` itself
      returns nothing) — checked deliberately on 17 Aug rather than
      assumed, because all three sounded like they might finally be
      unblockable now that real price and sector history exist. They
      aren't, and the specific reason for each is worth recording:
      - **Gate 1 (liquidity)**: needs median 60-day *turnover* (Rs
        traded), not volume. The per-company price backfill
        (`companyChartDataByStock`) has no turnover field at all — only
        high/low/close/volume — so real turnover history is only as deep
        as forward capture has run (currently 1-2 sessions). Computing it
        as `close × volume` was considered and rejected: on a day with
        one trade it matches exactly (verified: ABAN.N0000, price=1085,
        quantity=9, turnover=9765.0 = 1085×9 precisely), but on a
        multi-trade day at varying prices it silently diverges from the
        true volume-weighted figure — exactly the "looks precise, isn't"
        number this project has avoided everywhere else, just not built
        this time either.
      - **Gate 2 (structural)**: still needs free float, which needs
        quarterly shareholding disclosures (§5) — not ingested.
      - **Gate 3 (integrity)**: still needs Beneish M-Score, related-party
        revenue/receivables %, audit opinion and auditor-change data — none
        extracted; `app.domain.ratios.NOT_YET_COMPUTABLE` already lists
        `beneish_m` and `sloan_accrual_ratio` for the same underlying
        reason (no cash-flow-statement line in `CANONICAL_LABELS`).
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
- [x] **Trend detection (§13)** — `app/domain/trend_detection.py`,
      surfaced as a "Trend (§13)" column on the company file's ratio
      table. Direction (Mann-Kendall, implemented by hand — no
      scipy/numpy dependency exists in this project), acceleration
      (second-difference sign) and consistency (fraction of moves
      matching the series' overall direction) for any ratio's history.
      - **Honest about the real state of the data**: §12 targets 10
        years / 8 quarters of history per company; `getFinancialAnnouncement`
        (the only ingestion source wired up) is a recent-filings feed,
        not a historical archive, so most tickers have exactly ONE period
        stored. Below 3 periods the module reports
        `insufficient_history` rather than a direction from a single
        point pretending to be a trajectory — verified against J.F.
        Packaging's real, single, confirmed period, which is today's
        actual baseline case, not a contrived edge case.
      - The Mann-Kendall cases are hand-verified against the textbook
        S-statistic (not just against the module's own output) — the
        spec's own worked example, "ROE moved 11% → 14% → 16% → 18%",
        is one of the test fixtures.
      - `direction` and `significant` are reported separately: a 3-period
        series can be directionally informative without clearing 95%
        confidence, and collapsing the two into one flag would either
        hide the direction or overstate the confidence.
- [x] **Model router (§15/§16)** — `app/domain/valuation_router.py`,
      the front door of Phase 3. Does NOT compute a valuation; decides
      which valuation METHODS apply to a company and which are actively
      wrong for it, from the archetype already on the security record.
      Every suppression carries a stated reason, per §16's own
      requirement ("the user sees which one and why").
      - All 15 Appendix P2 archetypes route to something; the 12 with a
        published §15 table row are marked as such, and the 3 that
        aren't (healthcare, logistics, other) say so explicitly rather
        than borrowing a neighbouring row's guidance silently.
      - **The case the whole module is built around**: a bank never gets
        a firm-side model. FCFF DCF, EV/EBIT, EV/EBITDA and
        sum-of-the-parts are suppressed outright for bank/non_bank_finance
        /insurance, with the reason stated ("a bank's debt is its raw
        material, not its financing").
      - `archetype=None` blocks routing entirely rather than defaulting
        to a generic profile — the failure mode that would otherwise
        silently apply an industrial DCF to a bank the moment archetype
        confirmation lagged behind. Verified live: JKH.N0000 (flagged
        for manual review by the conglomerate-name guard, §16's earlier
        commit) correctly returns no routing at all.
      - **Two of §16's five routing questions, and distress/option-value
        routing, are honestly reported as unanswerable** rather than
        answered from a substitute proxy: "are cash flows predictable"
        needs CFO/FCF (not extracted — no cash-flow-statement line exists
        in `CANONICAL_LABELS`, PARAMETERS.md #9's gap), "are dividends a
        meaningful proxy" needs a dividend history (not extracted), and
        distress routing needs an Altman Z-score (not computed). Treating
        net income as a stand-in for cash flow, or a leverage ratio as a
        stand-in for a Z-score, would be exactly the "confident, precise,
        entirely fictional number" §15 warns the whole router exists to
        prevent — just relocated from valuation into routing.
- [x] **Cost of equity (§17.2)** — `app/domain/beta.py`,
      `app/domain/cost_of_equity.py`, `app/domain/cost_of_equity_view.py`.
      The first genuine Phase 3 valuation NUMBER (not just routing), and
      the discount rate every DCF/DDM/residual-income anchor still to be
      built will need.
      - **Dimson-corrected, Blume-adjusted beta from real data** — the
        Dimson multi-lag OLS regression is implemented by hand (no
        scipy/numpy dependency in this project, same constraint as
        `trend_detection.py`'s Mann-Kendall). Verified against real
        matched COMB.N0000 + ASPI return series.
      - **Checked against CSE's own published beta, and the two
        genuinely disagree.** `companyInfoSummery.reqSymbolBetaInfo` was
        already modelled in the schema and its own docstring predicted
        exactly why: an uncorrected OLS beta is "severely downward
        biased... the single most common technical error in
        frontier-market factor work." For COMB.N0000 over the real
        backfilled year: naive same-day OLS = 0.96, Dimson-corrected =
        1.10 (moved UP, as the correction predicts), Blume-adjusted =
        1.07. CSE's own published figure is 0.79 — further away, not
        closer, because the two are not measuring the same thing (a
        different window, frequency, or the "TRI" total-return basis the
        field name implies). Neither is ground truth; both are now
        stored and shown side by side (`published_beta_asi`,
        migration 0010) rather than one silently overwriting the other.
      - **Found and fixed a real bug while adding that storage**:
        `security_enrichment.py`'s own module docstring had claimed
        since it was written that per-company enrichment covers "CSE's
        own published beta" — it never actually wrote it anywhere. No
        new API call needed; the field was arriving in every enrichment
        response the whole time and simply wasn't kept.
      - **Ke omits two of its four components, and says so rather than
        treating them as zero.** `size_premium` needs free-float market
        cap deciles (free float still not ingested); `illiquidity_premium`
        needs the Amihud percentile (confirmed blocked this session — see
        Gate 1's investigation above). Both are non-negative by
        definition (§17.2: "0 to ~2.5%", "0 to ~3.0%"), so a missing one
        can only understate Ke, never overstate it — every Ke this
        system produces is explicitly labelled a LOWER BOUND until both
        exist.
      - `ERP_effective` is a stated, provisional POLICY parameter
        (PARAMETERS.md #10, config default 7.0%), not something computed
        — this system has no live access to Damodaran's country dataset,
        which §17.1 says the figure should be reviewed against. §17.1's
        "third reference point" — the ASPI-implied ERP — IS live (it is
        §29's hero spread, read as an ERP estimate) and is shown
        alongside the configured value, never substituted for it.
      - Verified end-to-end in the browser: COMB.N0000, a real bank,
        shows Ke=16.86% built from a real Rf (10.01%, the CBSL-scraped
        364-day T-bill), a real beta (0.978), the configured ERP, and an
        implied-ERP cross-check (-1.24pp) that matches this session's
        real hero spread reading exactly — and the routing section
        directly above it correctly names Residual Income and DDM, the
        exact models this Ke is for, as this bank's primary anchors.
- [x] **First screener column — ROE, sortable, on Companies.** §54's
      Phase 2 "ranked screener UI" starting point, scoped honestly: not
      §40's full opportunity ranking (needs a composite score this
      system doesn't have — Phase 6/7), a real sortable column over what
      §12's ratio engine already computes.
      - `app.domain.fundamentals_view.bulk_latest_line_items` computes
        every ticker's latest point-in-time-visible fundamentals in ONE
        query rather than 284 per-ticker lookups — the same discipline
        `list_securities` already applies to prices ("done as a subquery
        rather than N+1"), now extended to fundamentals.
      - Nulls sort last regardless of direction — a company with no
        fundamentals is a gap, not "the worst ROE," and ranking it as if
        it were would be exactly the confident-looking-but-wrong number
        this project avoids everywhere else. Verified live: with three
        real tickers seeded, descending sort correctly orders
        16.7% → 15.7% → 6.0% with the other 281 tickers (no ingested
        fundamentals) honestly last, each showing "Data unavailable".
      - Deliberately reuses `app.domain.fundamentals_view.ratios_for`'s
        display convention (shows AI-assisted with a provenance chip),
        NOT `app.domain.valuation_view`'s stricter confirmed-only filter
        — a screener ratio is a displayed fact with its trust level
        shown, same as the company file's own ratio table; only an
        actual fair value needs §8's confirmed-only gate.

## Phase 3 — valuation engine, price ladder, margin-of-safety engine

Gate to proceed (Master Spec §54): "Fair values reproduce hand-worked
reference cases exactly." Every module below is checked against that
literal bar — hand-worked numbers, not just the module's own output read
back at itself — including transcribing §26's own JKH.N0000 worked
example (fair value 24.00, MoS 30%, current price 21.40) directly into
`test_price_ladder.py` and confirming every threshold and the "27% above
your buy-below price" status line to the cent/percentage-point.

- [x] **§18 DCF** (`app/domain/dcf.py`) — three-stage FCFF/FCFE, terminal
      value, the full equity-value bridge, and §23's reverse-DCF solver
      (bisection on a flat growth rate). 12 tests, including an
      independent closed-form geometric-series cross-check of the whole
      equity bridge (not a restatement of the module's own year-by-year
      loop).
- [x] **§19 dividend and residual income** (`app/domain/dividend_
      residual_income.py`) — Gordon growth with its 3-part eligibility
      gate, multi-stage DDM with the sustainable-payout dividend-capacity
      cap, and residual income. 15 tests.
- [x] **§20 relative valuation** (`app/domain/relative_valuation.py`) —
      all four justified multiples (P/E, P/B, EV/EBIT, P/S). 9 tests.
- [x] **§21 sum-of-the-parts** (`app/domain/sotp.py`) — segment waterfall
      plus the holding-company-discount calibration §21 insists "must be
      earned, not assumed" (historical average + three named, separately
      visible adjustments, clamped to the stated 15-35% typical range).
      6 tests.
- [x] **§22 asset-based / NAV valuation** (`app/domain/asset_based_
      valuation.py`) — hard book (both figures always shown, never hard
      book alone), land marks (independent reference or explicitly-
      labelled cost, never silently one or the other), hotel replacement-
      cost cross-check, plantation hard NAV per hectare, liquidation
      value floor. 9 tests.
- [x] **§23 scenarios and simulation** (`app/domain/scenarios.py`) —
      deterministic bear/base/bull construction from a historical growth/
      margin distribution using §23's own stated deltas (WACC +150bp/
      -100bp, terminal growth -100bp for bear), a sensitivity tornado,
      and a Monte Carlo overlay (empirical bootstrap over each company's
      own historical values, per §23's "not assumed normal" — this
      project has no scipy/numpy, same constraint `trend_detection.py`
      already documented). 8 tests, including a reproducible-with-seed
      check and percentiles verified monotonic.
- [x] **§24 triangulation** (`app/domain/triangulation.py`) — the
      6-archetype weighted blend, with the archetype→triangulation-
      category mapping DERIVED from `app.domain.valuation_router`'s
      already-computed `RoutingDecision` flags rather than a second,
      independently-maintained archetype list that could silently
      disagree with the router. A missing anchor category renormalises
      the remaining weights rather than treating the gap as zero value.
      16 tests.
- [x] **§25 margin of safety** (`app/domain/margin_of_safety.py`) — all
      five components, each clamped to its own stated range (the
      arithmetic only reconciles with §25's worked numbers if the range
      column is read as a post-formula clamp, e.g. an integrity_score of
      50 raw-computes to 80% before capping at 8% — stated explicitly in
      the module docstring since the spec doesn't spell this out).
      19 tests.
- [x] **§26 the price ladder** (`app/domain/price_ladder.py`) — the five
      zones. 13 tests.

**WHICH OF THESE ARE ALREADY WIREABLE TO LIVE DATA, AND WHY MOST AREN'T
YET.** Residual income and justified P/B are the two models this system
can run today without new ingestion work — both need only book value
(extracted since Phase 1), ROE (already computed by `app.domain.ratios`)
and Ke (already built, §17.2). Every other model is genuinely blocked on
data this project does not extract or source anywhere, named per module
rather than glossed over:
  - DCF/DDM need D&A, capex, working-capital deltas, and dividend
    history — none extracted (PARAMETERS.md #9's cash-flow-statement gap,
    plus a distinct, newly-named dividend-history gap).
  - SOTP needs a segment/group-structure breakdown — no ingestion source
    provides one.
  - Asset-based valuation needs a revaluation-reserve line item, an
    independent land reference, a build-cost benchmark, and a recent
    estate-transaction price — all genuinely external reference data.
  - The margin-of-safety engine's quality/integrity component needs a
    continuous 0-100 integrity score that **does not exist anywhere in
    this system by design** — §11.1 requires Gate 3 to be a hard pass/
    fail veto specifically so "a sufficiently attractive valuation will
    always outvote it" can't happen; `quality_integrity_component`
    returns `None` (a lower-bound MoS, never silently zero) until a
    genuinely separate continuous score is built for this different
    purpose.
  - §20.1's three comparison frames and its cross-sectional P/B
    regression, and §23's archetype-specific bear stress / confirmed-
    project bull uplift, are corpus-level or macro-engine-dependent
    (Phase 5) — named as gaps in each module's own docstring rather than
    faked with single-company data.

All nine modules are pure functions over caller-supplied inputs — no I/O,
same discipline as `app.domain.cost_of_equity` and `app.domain.ratios` —
so each is ready to wire up the moment its blocking data source exists,
without touching the arithmetic that's already tested today. 107 new
tests; full suite 611 passed.

- [x] **Justified P/B and residual income wired to live data**
      (`app/domain/valuation_view.py`, `GET /valuation/{ticker}`). The
      two models above that need only book value, ROE and Ke — all
      already extracted or computed — now run against a real company's
      stored fundamentals rather than only caller-supplied test inputs.
      Enforces §8 explicitly: re-selects line items filtered through
      `can_enter_valuation` rather than reusing `fundamentals_view`'s
      ratio-display selection, so an AI-assisted figure can be shown as a
      ratio on the company file but still cannot reach a fair value.
      Residual income's one-year forecast is deliberately flat
      persistence of the latest confirmed ROE (the "no view" baseline),
      not a fabricated improvement trajectory. New policy default
      `settings.long_run_nominal_growth_pct` (PARAMETERS.md #11).
      - **Found and fixed a real bug on the first live request against
        this endpoint, not in a fixture.** Bootstrapped real data for
        COMB.N0000 (real close 205.75, 17 Aug) and hit
        `GET /valuation/COMB.N0000` for the first time — `current_price`
        came back `null` despite the real price being on file, because
        the response derived it from `price_ladder.current_price`, and
        `price_ladder` is `None` whenever no fair value exists yet to
        build a ladder from (true for nearly every ticker today, since
        almost none have a confirmed fundamentals period). Fixed by
        carrying `current_price` on `CompanyValuationSummary`
        independently of whether a ladder could be built. A fixture-only
        test suite would not have caught this — the existing
        "no confirmed data" test exercised the exact code path but wasn't
        asserting on `current_price` — which is the reason this project
        keeps checking new endpoints against one real bootstrapped
        request before calling a feature done.

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

### §31 regime classifier — the first real piece of Phase 4's macro engine

Phase 4 (§29-39: macro/ARDL, factor library, scoring, AI research
writer, decision capture UI) had nothing built at all until this
entry — the ROADMAP's own "Explicitly deferred" section below has been
updated to stop bundling "macro/ARDL" as one untouched block, because
part of it genuinely isn't untouched anymore.

- [x] **§31's regime classifier is live** — `app.domain.regime_
      classification` (pure) + `app.domain.macro_engine_view.regime_for`
      (wired to real `macro_series` data), consumed by `margin_of_
      safety.regime_pct` on every `GET /valuation/{ticker}` call (§31:
      "mechanically... widens every margin of safety"). New real
      dependencies: `statsmodels`/`numpy`/`pandas`/`scipy` — never
      hand-rolled; ADF/KPSS-class stationarity work and Markov
      regime-switching are real, tested library implementations, not
      reimplemented from scratch.
      - TWO INDEPENDENT READS, matching §30 step 4's own wording
        ("Markov switching... augmented with a macro composite z-score"):
        a genuine `statsmodels.tsa.regime_switching.markov_regression.
        MarkovRegression` fit on real ASPI daily log returns (`app.
        domain.index_history_loader`'s ~1-year backfill is the only
        series in this system's macro layer with plausible year-long
        depth), refusing to trust a fit below 60 observations OR one the
        EM optimiser didn't actually converge on (`mle_retvals
        ['converged']` — a real, observed failure mode caught while
        testing a 3-regime fit, not a hypothetical one guarded
        speculatively); and a rule-based composite reading §31's own
        signature table and §32's own worked-example logic directly off
        whatever of §29's ~14 named signal types this system actually has
        real coverage of today — five: the policy rate, the 364-day
        T-bill yield, CCPI y/y, the LKR/USD rate (all via `app.domain.
        cbsl_parsing`, whose own backfill-to-2013 job above hasn't been
        run yet, so live coverage today is whatever the daily capture job
        accumulates going forward) and §29's own hero spread. Both reads,
        when both exist, blend 50/50 — an explicit, disclosed weight, not
        a formally optimised one.
      - Statistical regimes are unlabelled by statsmodels itself — ranked
        here by `mean ÷ √variance` (a Sharpe-like measure, chosen because
        §30 names BOTH returns and volatility, not mean alone) to assign
        `risk_on`/`transition`/`risk_off`.
      - Validated against §36's own bar ("regime classifier correctly
        labels known historical periods") using a synthetic two-regime
        series (150 days bull, 100 days bear, seeded) — the fit correctly
        ranks the bull regime above the bear regime and reads the
        current (final-day) state as `risk_off` with >80% confidence.
      - The Ke/discount-rate-raising and gross-exposure-capping
        consequences §31 also names are NOT wired anywhere yet — named
        precisely as the next piece, not silently attempted here.
      - 38 new tests (`test_regime_classification.py`,
        `test_macro_engine_view.py`, plus 3 new `test_valuation_api.py`
        tests — the first end-to-end `GET /valuation/{ticker}` API tests
        this project has had; `test_valuation_view.py` only exercised the
        domain layer directly, which can't catch a Pydantic
        serialization bug at the domain-to-API boundary, and one very
        nearly shipped here — a `Literal["risk_on", ...]`-keyed dict
        round-tripping through JSON). Full suite: 742 passed.
      - **Named precisely, not silently skipped — the rest of §30's
        six-step method chain**: stationarity/break testing (ADF,
        Phillips-Perron, KPSS, Zivot-Andrews) as a standalone reusable
        module; Johansen cointegration / VECM / ARDL bounds testing (the
        actual long-run macro-to-market relationship — `statsmodels.tsa.
        ardl.ARDL`/`UECM.bounds_test` are the right tool, not built);
        impulse response functions, FEVD, Toda-Yamamoto causality (need
        the cointegration model first); the event study (CARs around
        CBSL/CCPI/IMF/budget/election dates); §34's national project
        register (a structured, human-confirmed data table, not an
        econometric method). **§33's sector sensitivity matrix is no
        longer on this list — see the next entry.** None of the
        remaining items is faked by returning a plausible number from a
        formula that isn't actually the named method.

### §33 sector sensitivity matrix — the second real piece of Phase 4's macro engine

- [x] **§33's sector sensitivity matrix is live** — `app.domain.sector_
      sensitivity` (pure) + `app.domain.sector_sensitivity_view` (wired
      to real `securities`/`prices_daily`/`macro_series` data), exposed
      on the new `GET /market/sector-sensitivity`. §33's own explicit
      warning — "the platform must populate it from its own estimation
      and never hard-code it" — is honoured literally: every cell is a
      real `statsmodels.OLS` regression of one sector's real daily
      return series on one real macro shock series, or absent entirely
      when there isn't enough real overlapping history to estimate from.
      - **Sector grouping uses `Security.cse_sector`** (the CSE's own
        industry-group names — "Banks", "Diversified Financials" —
        matching §33's own illustrative row labels), not the coarser
        11-sector `gics_sector` `app.domain.gics` derives FROM it, which
        would blend distinct sectors §33's own table keeps separate.
      - **Sector returns are equal-weighted, on adjusted prices**
        (`close × adj_factor` — the same total-return adjustment `app.
        domain.corporate_actions` computes, never raw close, which would
        be contaminated by unadjusted dividends/bonus issues/splits).
        Equal-, not cap-weighted — a real, disclosed simplification: this
        system stores no daily market-cap series to weight by, only
        `FloatData`'s point-in-time share count.
      - **Only 4 of §33's 5 illustrative shock columns are real** —
        policy rate change, 364-day T-bill yield change, CCPI y/y
        change, and LKR/USD % change, all from real `app.domain.
        cbsl_parsing`-sourced series. Oil (Brent), tourist arrivals/
        earnings and fiscal spending are NOT ingested anywhere in this
        system, so "Oil spike"/"Tourism rebound"/"Fiscal expansion"
        columns are never built — named absent, never proxied or
        simulated.
      - **No qualitative +/++/−/−− scale**, deliberately unlike §33's
        own illustrative presentation — a real OLS coefficient, p-value
        and R² are reported instead, with only a `"positive"`/
        `"negative"`/`"not_significant"` label derived from sign and a
        standard, disclosed p<0.05 threshold. A magnitude gradation
        (`+` vs `++`) would need a threshold comparable across shocks
        measured in wildly different units (a T-bill yield change in
        fraction-points vs. an LKR/USD move in percent) this module has
        no real basis for — exactly the "confident, precise, entirely
        fictional" symbol §15 warns against.
      - **A sector with fewer than 3 real constituent tickers is
        excluded from the matrix entirely, named in a separate
        `thin_sectors` list rather than silently dropped** — reusing
        `app.domain.gics`'s own stated reasoning ("ranking a company
        against two peers produces a percentile that is technically
        computable and practically meaningless"), not inventing a new
        threshold independently.
      - 16 new tests across `test_sector_sensitivity.py` (hand-worked
        OLS recovery of known positive/negative sensitivities, and
        correct "not significant" detection on pure noise),
        `test_sector_sensitivity_view.py` (equal-weighting correctness,
        adjusted-vs-raw-price correctness, step-function vs pct-change
        shock construction, full DB-to-matrix wiring) and
        `test_market_sector_sensitivity_api.py` (the API-layer
        serialization check the DCF/regime work already showed is worth
        having separately from domain-layer tests — `thin_sectors:
        list[list[object]]` in particular is an unusual enough Pydantic
        shape to verify directly rather than assume). Full suite: 760
        passed.

## Not done yet — next in Phase 1

- [x] **A genuine external second source, for TODAY'S close** —
      `app/jobs/second_source_reconciliation.py`, `python -m app.cli
      second-source-check`. TradingView carries a live quote for every
      CSE line (`CSELK:<ticker>`, matching our own symbols exactly) via
      `/global/scan` — the one path scanner.tradingview.com's own
      robots.txt allows (`Disallow: /` with `Allow: /global/scan`); the
      per-symbol quote page endpoint a browser actually calls is under
      the blanket disallow and is deliberately NOT used. A mismatch
      >0.5% (same threshold as the internal check, Part II §5.2) raises
      the same `DataAlert`/quarantine mechanism.
      - **Found a real, severe pre-existing bug while building this**:
        `price_loader.upsert_eod_prices` wrote `close=0.00` for every
        security whenever it ran during market hours. `closingPrice` is
        the literal float `0.0` — not null — until the session settles,
        and `row.closingPrice if row.closingPrice is not None else
        row.price` treats `0.0` as present. Caught live: ABAN.N0000
        mid-session, `marketStatus` "Regular Trading", closingPrice=0.0
        alongside a genuine price=1085.0. Fixed to fall back to the live
        `price` whenever `closingPrice` is `None` OR `0`; no CSE equity
        is genuinely priced at zero, so this is safe, not merely
        convenient. This was corrupting every mid-session capture,
        silently, before today.
      - **Only ever compares today.** TradingView's own chart renders no
        historical candles for CSE symbols at any timeframe — live quote
        only — so `check_against_second_source` raises
        `StaleComparisonError` rather than silently comparing a past
        close against a live figure. Found by making exactly that
        mistake in a manual test run: comparing a 3-day-stale stored
        close against today's live quote flagged 181 of 283 tickers as
        "mismatched", every one spurious.
      - Scheduled at 15:07 Colombo, after both the EOD snapshot and the
        internal reconciliation — running it mid-session compares two
        still-moving live quotes and produces drift, not a real signal.
      - **Does not solve independent historical depth.** See
        PARAMETERS.md #5: live capture risk is materially reduced,
        historical backtest risk is not.
- [ ] **LLM-assisted extraction** (PARAMETERS.md #9) — needs an explicit
      decision (API key, model, cost) before it's worth building; the
      deterministic extractor covers a real but limited subset of line
      items until then.
- [x] **Financial-statement historical backfill — the "not-yet-identified
      source" above is `/api/financials`, found 17 Aug.**
      `app/ingestion/financial_reports_archive_loader.py`,
      `python -m app.cli backfill-financials`. Found the same way as
      sectors, the registry and per-company prices this session: opening
      the CSE's own new company-profile page (Financials tab) and reading
      `performance.getEntriesByType('resource')` in the live page, not
      guessing endpoint names.
      - Verified against COMB.N0000: **16 annual + 59 quarterly filings,
        catalogued back to 2012** — `getFinancialAnnouncement` only ever
        offers the single most recent filing platform-wide.
      - **The catalogue is more complete than the CDN, and the loader
        says so rather than treating it as a bug.** Every 2018-and-
        earlier annual report for COMB.N0000 is listed but 403s on
        download; 2019 onward is clean. `unavailable` and `failed` are
        counted separately in the summary for exactly this reason.
      - **`uploadedDate` is trusted as `first_available_date` on real
        evidence, not a default.** `authorizedDate` (the more obviously
        correct field, already used by `getFinancialAnnouncement`)
        exists only on 2024+ filings here. Every one of 60 real
        (period_end, uploadedDate) pairs back to 2012 shows a distinct,
        plausible disclosure lag (38-92 days) — a bulk migration backfill
        would instead stamp every old row with one shared date, and it
        doesn't.
      - **Amendments are modelled as real restatements, not collisions.**
        COMB.N0000 has both an original and an "Amended" annual report
        for the same FY2022 and FY2021 periods. Processed oldest-first,
        `version` increments per distinct source PDF already on file for
        that (ticker, period_end, period_type) — the amendment becomes
        `version=2` with its own later `first_available_date`, preserving
        the fact that the market saw the original figures first.
        Idempotency is checked per exact source PDF, deliberately
        separate from that versioning logic, so a re-run never
        re-downloads a file it already has but still correctly processes
        a genuinely new amendment for an already-seen period.
      - Reuses the existing single-filing extractor
        (`financial_pdf_extractor.py`) unchanged — same deterministic
        line-item extraction, same accounting-identity check, same
        AI-assisted provenance requiring human confirmation before any
        figure enters a ratio (§8). This is a new SOURCE of filings, not
        a new extraction method, and PARAMETERS.md #9's coverage gap
        (still no cash-flow-statement line) now compounds across many
        more real periods per company rather than the one filing it was
        verified against.
      - Not scheduled as a recurring job, unlike the daily
        `financial_statement_scan`: a full company's history is 75+
        paced requests on its own, and running that weekly across ~283
        companies would be a genuinely heavy, inappropriate load on an
        unofficial endpoint (§5). Run explicitly, `--ticker`/`--limit`
        at a time, the same way `backfill-prices` is.
- [x] **Per-company price history — reverses the "confirmed unsolvable"
      finding above.** That conclusion tested `chartData` (param
      `chartId`) against every security id and got `[]` for all of them.
      It was the wrong endpoint. `companyChartDataByStock` (param
      `stockId`, a DIFFERENT id space from `allSecurityCode`'s `id`)
      returns a genuine ~241-session daily series per line — high, low,
      close, volume — and was found the same way sectors and CBSL were:
      opening the CSE's own "Company Data" page and reading its network
      calls, not by guessing endpoint names.
      - Verified exact against `companyInfoSummery`'s independently
        fetched hiTrade/lowTrade/closingPrice/tdyShareVolume for
        COMB.N0000 on 2026-08-14, not just internally consistent.
      - Full 283-ticker backfill run 17 Aug 2026: **65,211 rows written,
        0 failures, 0 missing ids.** `app.domain.company_price_history`
        records that ~1-in-4 tickers trigger a close-outside-its-own-range
        warning (2,058 across 115 tickers, concentrated in thinly-traded
        small caps) — the guard drops only the contradicted bound and
        keeps the close, so nothing was silently fabricated.
      - Fills gaps only: never overwrites a date the daily EOD job already
        captured live, never touches today's still-forming session.
        Scheduled weekly (Saturday 07:00 Colombo) as a standing repair.
      - **Still does not satisfy PARAMETERS.md #5** — it is cse.lk, the
        same institution as every other price figure here, not an
        independent second source. That decision is unchanged.
      - Unblocks the factor library, momentum, Dimson beta and Amihud
        liquidity — most of Phases 2 and 6 — which is the part that was
        genuinely blocked and no longer is.
- [x] **`cse_sector` is now populated from the exchange's own GICS
      publication — 257 of 283 lines (90.8%).** This reverses a
      conclusion recorded twice in this file ("confirmed not available
      from the API at all"). It was wrong: `sector_list` and
      `listBySector` do exactly this. They were missing from the endpoint
      inventory because that inventory was derived from the site's
      JavaScript; they were found instead by opening the CSE's own GICS
      Classification page and reading the network calls it makes.
      - 20 GICS industry groups, plus the ASPI and S&P SL20 mixed into
        the same list with `indexCode: null` — filtered out, or every
        listed company files under "ALL SHARE PRICE INDEX".
      - The 11-level GICS sector above each group is derived from the
        code's first two digits (4010 -> 40 -> Financials). That is the
        standard's own hierarchy, not an inference about the company, and
        it gives §12's percentiles a wider fallback when an industry group
        is too thin to rank against — Sri Lanka has one listed automobile
        company and two telecoms.
      - The 26 uncovered lines stay NULL rather than going in an "Other"
        bucket, which would let them rank in a sector they were never
        classified into.
      - Hand-set classifications are preserved on refresh (`sector_source`
        distinguishes them), per Appendix P2.

- [x] **`archetype` now has a proposal engine — 232 of 283 securities
      (82%)** (`app.domain.archetype`, `python -m app.cli archetypes`).
      GICS is not the archetype the valuation router (§16) needs, and the
      clearest proof is in the data: **John Keells Holdings classifies as
      "Capital Goods"** — Sri Lanka's largest diversified conglomerate,
      with hotels, transport, consumer foods, financial services and
      property, filed under whichever industry group its largest segment
      falls into. So this does not assign archetypes from GICS blindly.
      - A lookup table maps each of the 20 GICS industry groups to its
        CSE-typical archetype, EXCEPT "Consumer Services" — verified by
        reading its real 32 members (ASIAN HOTELS AND PROPERTIES, BERUWALA
        RESORTS, CEYLON HOTELS CORPORATION, ...), it is hotel-dominated on
        this exchange specifically, so it only proposes "hotel" when the
        company's own name confirms it.
      - Any name containing HOLDINGS or GROUP is refused outright and
        left for a human — this is the check that keeps John Keells
        Holdings NULL rather than "manufacturing". A clear single-business
        keyword (PLANTATIONS, TEA, CEMENT) still overrides it, because a
        plantation holding company is functionally a plantation company.
      - No GICS group maps to "plantation" or "construction_materials" at
        all — the name overrides are the ONLY route to those two
        archetypes, and real ones (AGALAWATTE PLANTATIONS, BOGAWANTALAWA
        TEA ESTATES, TOKYO CEMENT) verify correctly.
      - `archetype_source` (migration 0009) mirrors `sector_source`: a
        hand-corrected value is never silently overwritten by a re-run.
      - **The 51 left NULL are named with a reason**, not hidden — the
        CLI prints them. This is the Appendix P2 review exercise made
        tractable, not a replacement for it: every one of the 232
        proposals still needs a human to confirm, and the 51 genuinely
        need one to decide.
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
- [x] **Instrument types and issuer identity** (`app/domain/instrument_type.py`,
      migration 0006). The universe comes from `tradeSummary`, which
      returns every traded LINE, not every company. Of 283 lines: 262
      ordinary, **18 non-voting** (COMB.X0000, HNB.X0000, SEYB.X0000, ...),
      2 closed-end fund units, 1 rights line. So **283 lines are 264
      issuers**, and every earlier statement of "~283 listed companies"
      in this repo was overstating the universe by 19.
      - Commercial Bank was in the universe twice. Beyond looking wrong on
        a screen, the §27.1/§39.1 concentration caps (10%/6%/3% by tier)
        would have counted one bank as two positions — a single-issuer
        limit silently evaded.
      - Fundamentals belong to the ISSUER: COMB.N0000 and COMB.X0000 share
        one set of accounts, one ROE, one book value. `issuer_code` is now
        stored and indexed so they attach once.
      - Fund units and rights lines are not equity at all — a P/E or ROE
        for them is a category error, not an imprecise number. **Gate 2
        now rejects non-common-equity outright**, and returns that as the
        single reason rather than adding it to a list of ordinary gate
        failures, which would imply the instrument might qualify once the
        data improves.
      - Verified against the exchange's own ISINs (LK0053N00005 /
        LK0053X00004) and `companyInfoSummery` (COMB.X0000: 97,325,945
        shares; COMB.N0000: 1,556,530,602).
      - Surfaced in the UI: the Companies list counts "283 lines · 264
        issuers" and tags non-ordinary lines; a company file with siblings
        says so and cross-links them.

- [x] **§7 survivorship — materially improved via a newly found endpoint.**
      `allSecurityCode`'s `active` flag is useless (it is `1` for all 327
      rows and never carries a 0 — an earlier note here wrongly called it
      "the only endpoint that distinguishes inactive listings"). But
      **`cntSecurity`**, previously in the inventory and never probed,
      turns out to be the exchange's own issuer registry: 369 issuers
      against the 264 that trade, with a `deleted` flag on 11 of them.
      - Verifiable delistings, not noise: DFCC Vardhana Bank (merged into
        DFCC Bank), Commercial Leasing Company, Associated Motorways,
        Ceylon Oxygen.
      - Kept in its own `issuer_registry` table, not folded into
        `securities`: the registry is issuer-level (`COMB`, not
        `COMB.N0000`), so writing it into a line-level table would mean
        inventing suffixes the exchange never published. Joins via
        `securities.issuer_code` from migration 0006.
      - `delisted` and `currently_trading` are separate columns because
        they are separate facts — Bank of Ceylon is neither delisted nor
        trading as equity, since it lists only debentures.
      - Surfaced on Data health with the limits stated in the UI itself.

- [ ] **Survivorship is improved, not closed.** 11 delistings across the
      exchange's entire history is implausibly few, so the flag is a
      partial record. 94 issuers are neither trading nor flagged and this
      source cannot separate debt-only issuers from suspensions from
      merely-illiquid names. No delisting DATE is published anywhere;
      `securities.delisting_date` stays NULL, and `first_seen`/`last_seen`
      only bound it by observation. Crucially, a truly unbiased backtest
      also needs the delisted companies' PRICE HISTORY, which remains
      unavailable — so this records that they existed without yet
      removing the bias.
- [ ] **Plain bonus issue / consolidation**: still unverified after ~40
      tickers probed across two sessions — no live example of either was
      found. Share splits (which looked similar) ARE now verified.
- [ ] **`notifications`/`notifications/corporate` etc.** — exist in CSE's
      frontend code as GET calls but returned 400 live; unused, re-verify
      before building against them
- [ ] 30-day consecutive reconciliation pass — can't be "done," only
      observed once the system is running continuously against live data
- [ ] Sustained-load testing of the cse.lk client's rate limiting
- [ ] **Tested, and the concurrent-event case genuinely mispairs — a real,
      now-tracked limitation, not fixed.** `_pair_rows` sorts each side
      chronologically and pairs index-wise; no real example of two
      concurrent same-type events has ever been captured live, so
      `TestPairRowsWithConcurrentEvents` in `test_corporate_actions_loader.py`
      builds synthetic rows (clearly marked as such — this file's only
      non-real-capture fixtures) for two scenarios. Sequential,
      non-overlapping events pair correctly, confirming the heuristic's
      core assumption holds for every case actually observed so far. But
      interleaved events — company files rights issue A, then rights
      issue B, and B's "(DATES)" follow-up is processed before A's —
      genuinely cross-pair A's initial with B's dates and vice versa.
      Not fixed here: a real correlating field between an initial
      disclosure and its own dates follow-up (e.g. a shared parent-
      announcement id) would be needed, and guessing at one without a
      live example to verify against would just trade an untested
      assumption for an unverified fix — exactly what this project
      avoids everywhere else.
- [ ] The financial-statement extractor's canonical label list
      (`CANONICAL_LABELS`) is now verified against TWO real filings, not
      one (17 Aug, see the cash-flow entries below) — every cash-flow
      line's wording differed completely between the two, confirming
      wording genuinely does vary company to company as this item always
      warned. Balance-sheet/income-statement labels are still verified
      against only the original J.F. Packaging filing. Still an open
      item at 2 of ~286 companies checked, not closed — real progress,
      not a solved problem
- [x] **Cash-flow-statement extraction — the long-tracked PARAMETERS.md
      #9 gap is partially closed, verified against a real filing, not
      guessed.** Freshly downloaded J.F. Packaging PLC's real FY2025/26
      annual report (17 Aug, the same filing this extractor was
      originally verified against — "FY2025/26" is the year ending 31
      March 2026) specifically to inspect its statement of cash flow,
      which no ingestion source had ever scanned before (`_STATEMENT_
      PAGE_MARKERS` only listed the balance sheet and income statement
      headers).
      - Three real, single-line, unwrapped lines now extract cleanly:
        `cash_flow_from_operations`, `net_cash_from_investing_
        activities`, `net_cash_from_financing_activities`, plus
        `net_increase_in_cash` and `depreciation_and_amortisation`.
      - **Found and fixed a real, generalisable formatting gap along the
        way**: the D&A line's note reference is "11/13" (two notes,
        slash-separated — PPE note 11 + intangibles note 13), which the
        existing note-reference pattern (dot-separated only, e.g. "6.1",
        "20.1.2") didn't match, so "11/13" was being read as part of the
        label instead of stripped. Fixed by widening the regex to accept
        `/` as well as `.` — a slash never appears in a real Rs.000
        value, so this is safe, not a guess.
      - **A new, real, precisely-named limitation replaces a vague one**:
        capital expenditure's real label ("Purchase & Construction of
        Property, Plant & Equipment & Intangible Assets") wraps across
        two physical lines on the real statement, and this extractor
        works line by line with no label-continuation logic. Not solved
        here — a merge heuristic guessed at without more real wrapped-
        label examples to verify against would trade one gap for an
        unverified one. DCF (`app/domain/dcf.py`) therefore still can't
        run against live data: it now has D&A but still needs capex and
        the working-capital delta.
      - Added a fourth accounting-identity check (`check_accounting_
        identities`): CFO + investing + financing = net change in cash —
        verified to hold exactly on the real extracted figures
        (174,382 + (-244,852) + 12,302 = -58,168, matching the filed
        "Net Increase/(Decrease) in Cash" line precisely), the same
        "independent arithmetic check catches wrong extraction" pattern
        the three existing identities already use.
      - **Three §12 ratios moved from `NOT_YET_COMPUTABLE` to real,
        tested `DEFINITIONS`**: cash conversion, operating cash flow
        margin, and the Sloan accrual ratio — the only three ratios in
        that list that needed CFO and nothing else. Hand-verified against
        the same real J.F. Packaging figures (cash conversion 91.82%,
        operating cash flow margin 3.87%, Sloan accrual ratio 0.41%).
        Piotroski's remaining gap shrank from three missing inputs to two
        (total debt, share count — no longer CFO).
      - §16's cash-flow routing question is now honestly *half*-answered
        rather than fully blocked: CFO's sign is knowable per period, but
        "reasonably predictable" is a multi-period judgement most
        companies can't support yet with only one confirmed fundamentals
        period on file — `app.domain.valuation_router` says so precisely
        rather than either fully answering or fully blocking the question.
      - 8 new/updated tests across `test_financial_statement_parsing.py`,
        `test_financial_pdf_extractor.py` and `test_ratios.py`, all
        against the real captured text and real hand-computed values.
        Full suite: 637 passed.
      - **Immediately checked against a SECOND, independent real filing
        rather than trusting one company's wording to generalise —
        Swadeshi Industrial Works PLC's FY2025/26 statement of cash
        flows, a different company, different sector, same day.** It
        didn't generalise: every one of `cash_flow_from_operations`,
        `net_cash_from_investing_activities`, `net_cash_from_financing_
        activities` and `net_increase_in_cash` is worded completely
        differently on this filing, now stored as a second real variant
        per key rather than assumed. This also closes part of a second,
        much older tracked item: "the canonical label list is verified
        against exactly one real filing" — it's now two, independently.
        **Genuinely new capability, not just a second data point**:
        Swadeshi's capex line ("Acquisition of Property, Plant and
        Equipment") does NOT wrap the way J.F. Packaging's does, so
        `capital_expenditure` is now a real canonical key — the first
        time this extractor has ever pulled a capex figure. It is
        PP&E-only (Swadeshi reports intangible-asset capex as a separate
        line this key deliberately excludes, a stated incompleteness).
        The CFO + investing + financing identity was re-verified on this
        fully independent filing too: -189,662,124 + -146,776,935 +
        194,330,142 = -142,108,917, exactly matching the filed line.
        **At the time, honestly, no single company had every input DCF
        needs**: Swadeshi's capex was extractable but its D&A is reported
        as two separate lines (Depreciation, Amortization) this extractor
        had no logic to sum into one canonical figure — a second,
        precisely-named limitation next to J.F. Packaging's capex-
        wrapping one. Closed the same session, see the next entry.
        2 new tests against this second real filing's real text and real
        figures. Full suite: 639 passed.
- [x] **Split-line depreciation & amortisation now sums correctly —
      Swadeshi becomes the first real company with BOTH capex and D&A
      simultaneously extractable, two of DCF's three cash-flow inputs.**
      `derive_additional_line_items` (`app/domain/financial_statement_
      parsing.py`) sums Swadeshi's real, separately-printed `Depreciation`
      (34,338,325) and `Amortization` (1,564,379) figures into the same
      `depreciation_and_amortisation` = 35,902,704 that J.F. Packaging's
      combined line already produces directly — one canonical concept,
      two real shapes, converging without either caller needing to know
      which shape a given filing used.
      - Deliberately a SEPARATE small function (`DERIVED_SUMS`, a data
        table, not a hardcoded branch) rather than folded into the label-
        matching logic — matching text to a canonical key and summing
        already-matched canonical keys are different operations, and
        keeping them apart means a third derived concept later is a new
        dict entry, not new control flow.
      - Never overwrites an already-printed combined line (J.F.
        Packaging's own figure always wins over any hypothetical
        component sum) and never produces a partial sum (only one of the
        two components present understates the real figure while looking
        exactly as precise as a genuine one) — both real failure modes,
        both tested.
      - Wired into ingestion as a second pass, `build_derived_
        fundamental_drafts`: a derived draft has no single printed
        `source_page`/`source_snippet` of its own, so its snippet cites
        both real component values explicitly ("DERIVED... sum of
        depreciation_expense = 34,338,325; amortisation_expense =
        1,564,379...") rather than pretending to quote one line CSE
        printed — a reviewer confirming it needs to check two figures
        against the source PDF, not one, and the draft says so.
      - Verified against the real downloaded PDF end-to-end, not just
        the trimmed test fixture: `capital_expenditure` and the derived
        `depreciation_and_amortisation` both come back correctly from
        the same live extraction run.
      - **Still, honestly, not the finish line for DCF**: the change in
        non-cash working capital remains the one true blocker for every
        company checked so far. The real component lines exist on both
        statements (trade receivables/payables/inventory movements), but
        they're an unpredictable, company-varying SET (J.F. Packaging has
        5 such lines, Swadeshi has 4, and the exact components differ —
        "Amounts due from Related Parties" vs "Advances and Prepayments")
        rather than two fixed, known labels — a genuinely different,
        larger design problem than the D&A sum. At the time, correctly
        not attempted without more real examples — closed the same
        session by finding a different angle on the SAME two real
        filings rather than needing a third; see the next entry.
      - 6 new tests (the derive function directly, plus the ingestion-
        level draft-building pass on both real filings' shapes). Full
        suite: 645 passed.
- [x] **Working-capital delta derived too — Swadeshi becomes the first
      real company with ALL THREE of DCF's cash-flow inputs individually
      extractable.** The insight that unblocked this: rather than
      summing the unpredictable, company-varying SET of individual
      working-capital lines (already ruled out, above), use the
      statement's own two BOOKEND SUBTOTALS instead — "Operating Profit
      before Working Capital Changes" (the subtotal before any
      working-capital line item) and "Cash generated from Operations"
      (the subtotal after all of them, before tax and interest). Checked
      against both real filings already on hand, no new download needed:
      the first label is verified BYTE-IDENTICAL on J.F. Packaging PLC
      and Swadeshi Industrial Works PLC, real, confirmed reusable
      wording rather than a hopeful guess; the second needed a second
      variant, same as every other cash-flow line here.
      - `change_in_net_working_capital` = operating_profit_before_
        working_capital_changes − cash_generated_from_operations — the
        sign §18's DCF convention wants (an INCREASE in working capital
        is POSITIVE and reduces FCFF when subtracted), derived directly
        rather than computed the other way and negated.
      - Verified against J.F. Packaging's real figures — 681,378 -
        493,497 = 187,881 — exactly matching the independently hand-
        summed total of its own 5 real working-capital component lines
        (inventories, receivables, payables, amounts due from/to related
        parties), a genuine cross-check that the subtotal-based
        shortcut gives the identical answer the harder line-by-line sum
        would have, not just a plausible-looking one.
      - `derive_additional_line_items` generalised from sums-only
        (`DERIVED_SUMS`) to also support differences (`DERIVED_
        DIFFERENCES`), still one small function driven by two data
        tables rather than per-concept branches — a third derived shape
        later (a ratio, say) would still be a clean, small addition.
      - Verified end-to-end against the real downloaded PDF a second
        time, not just the test fixtures: `capital_expenditure` = real,
        `depreciation_and_amortisation` (derived) = 35,902,704,
        `change_in_net_working_capital` (derived) = 252,324,738, all
        three from one live extraction run on Swadeshi's real filing.
      - **Still not the same as DCF being wired to live data** —
        `app/domain/dcf.py`'s own docstring is explicit about the
        remaining gap: DCF is a multi-year forecast built from
        assumptions (§18.2's growth/margin/tax fade paths), and having
        one period's real capex/D&A/ΔNWC figures is not the same as
        having a designed way to turn them into a 10-year projection.
        That wiring is real, separate, not-yet-built work now, genuinely
        no longer a data-availability gap for at least this one company.
      - 4 new tests for the difference-derivation logic directly, plus
        both existing real-filing fixtures extended with their full real
        working-capital sections (rather than trimmed vacuum text) and
        every existing assertion on them re-checked against the new
        lines. Full suite: 649 passed.
- [x] **A real, live FCFF number — the first of §18's figures wired to
      live data, and a small, honestly-scoped step short of a full DCF.**
      `app.domain.dcf.compute_fcff` extracted as its own standalone pure
      function from the formula that was previously only inline inside
      `project_cash_flows`' multi-year loop (both paths now call the
      same function — a regression test confirms they can never silently
      diverge) — because a caller with just ONE real period's figures
      needed a way to compute FCFF without constructing a full
      `DCFAssumptions`, which requires multi-year growth/margin/tax fade
      assumptions a single period gives no honest basis to invent.
      - `app.domain.valuation_view.current_period_fcff_for` wires it to
        live data: fetches the same §8-confirmed line items the rest of
        this module already respects (`operating_profit` as an EBIT
        proxy — stated explicitly as an approximation, since this
        extractor has no separate canonical `ebit` line to compare it
        against — `depreciation_and_amortisation`, `capital_
        expenditure`, `change_in_net_working_capital`, plus the
        already-built `effective_tax_rate` ratio), and computes a real
        FCFF figure the moment all five are present and confirmed for
        one company.
      - **A real sign-convention bug caught before it shipped, not after
        — the value this whole increment exists to demonstrate.**
        `capital_expenditure` is extracted NEGATIVE (the cash-flow
        statement's own printed convention, a cash outflow), but
        `compute_fcff` expects the POSITIVE magnitude it subtracts.
        Passing the raw stored value straight through would have added
        capex to FCFF instead of subtracting it — silently overstating
        FCFF by roughly twice the real capex figure, on every company
        this ever ran against, and it would have looked completely
        plausible on screen. Caught by writing the test FIRST against a
        known hand-worked answer (670, the same case already verified
        directly against `compute_fcff` in `test_dcf.py`) rather than
        writing the wiring and trusting it; a dedicated regression test
        now asserts the flipped-sign answer (730) is specifically wrong.
      - Deliberately informational only, NOT fed into `valuation_
        summary_for`'s triangulation anchors: an undiscounted single
        period's cash flow is not a per-share fair value, and treating
        it as one would be exactly the "confident, precise, entirely
        fictional number" §15 warns the whole valuation engine exists to
        prevent. `app.domain.dcf`'s own module docstring is explicit
        that turning this into an actual DCF fair value still needs the
        multi-year forecast wiring — real, separate, not-yet-built work,
        genuinely no longer a data-availability gap but not "DCF is
        live" either.
      - Exposed on `GET /valuation/{ticker}` as `current_period_fcff`.
      - 7 new tests: `compute_fcff`'s own hand-worked case, a working-
        capital-sign sanity check, and a cross-check against `project_
        cash_flows`' internal computation (`test_dcf.py`); the live-
        wiring hand-worked case, the sign-flip regression at the view
        layer, a missing-inputs case, and a §8 confirmation-filtering
        case (`test_valuation_view.py`). Full suite: 656 passed.
- [x] **WACC, live — §18.1's actual FCFF discount rate, not Ke.** Went
      looking for a real debt line specifically to unlock this, and
      found one on Swadeshi's real balance sheet: "Interest Bearing
      Loans and Borrowings" — but it prints TWICE, byte-identically,
      once under Non-current Liabilities (11,672,993) and once under
      Current Liabilities (634,163,111), the standard maturity-split
      presentation. The existing "first match wins, drop the rest" dedup
      rule would have silently kept only the smaller non-current portion
      and discarded the much larger current one — genuinely wrong, not
      just incomplete.
      - New capability: `SUM_ACROSS_OCCURRENCES`, an explicit allowlist
        of canonical keys where every occurrence on a statement should
        be SUMMED rather than deduplicated to the first — deliberately
        an allowlist, not a default, because most repeated matches on a
        real page genuinely are a bug worth catching (the page-marker
        filter's whole purpose), not something to paper over. Verified
        end-to-end against the real downloaded PDF: 11,672,993 +
        634,163,111 = 645,836,104, with a `source_snippet` that cites
        both contributing values, not just the total.
      - `interest_expense` also now extracts, from the cash-flow
        statement's own "Finance Costs" accrual line (deliberately not
        "Finance Costs Paid" — a real, differently-worded line on the
        same statement — because WACC's cost of debt wants the period's
        expense, not the cash actually disbursed).
      - New module `app/domain/wacc.py`: cost of debt (pre- and after-
        tax) and WACC itself, with a real, deliberate departure from
        `app.domain.cost_of_equity`'s missing-component pattern — a
        missing cost of debt is NEVER treated as zero the way a missing
        risk premium safely can be, because zero would pull WACC down
        toward `We × Ke` alone, UNDERSTATING the discount rate and
        therefore OVERSTATING every DCF value built on it, the dangerous
        direction rather than the safe one. A levered company with no
        computable cost of debt gets no WACC at all, not a falsely-
        precise lower-bound one.
      - Wired live via `app.domain.valuation_view.wacc_for`, exposed on
        `GET /valuation/{ticker}` as `wacc` — informational, same as
        `current_period_fcff`, not yet consumed by any live fair value.
      - **A third, newly-precise DCF blocker surfaced while checking
        whether this closed the loop, and it's now named exactly rather
        than left vague.** `DCFAssumptions.working_capital_pct_revenue`
        needs the working-capital STOCK (a balance-sheet level, so a
        multi-year projection can grow it proportionally with revenue)
        — a genuinely different figure from `change_in_net_working_
        capital`, the working-capital CHANGE (a flow, for one historical
        period) this system already extracts. No canonical label maps
        the individual current-asset/current-liability components
        (trade receivables, inventories, trade payables — excluding
        cash and interest-bearing debt) a stock figure would need to be
        built from. `app/domain/dcf.py`'s own module docstring has the
        complete, current state of every DCF input, not repeated here.
      - 13 new tests across `test_financial_statement_parsing.py` (the
        duplicate-occurrence extraction, `interest_expense`),
        `test_financial_pdf_extractor.py` (the sum-across-occurrences
        draft-building pass, verified against the real balance sheet),
        `test_wacc.py` (cost of debt, WACC itself, and the specific
        regression that WACC must land strictly between Kd and Ke for a
        levered company — never silently equal to Ke), and
        `test_valuation_view.py` (the live-wiring hand-worked case).
        Full suite: 669 passed.
- [x] **Working-capital STOCK now extractable too — the third DCF
      blocker named above is closed, and a real double-counting bug was
      found and fixed along the way.** `derive_additional_line_items`
      gained a third derivation shape: rather than a fixed 2-key sum or
      difference, `net_working_capital` sums whichever of a frozenset of
      current-asset canonical keys (trade receivables, inventories,
      advances and prepayments, related-party trade/non-trade amounts —
      company-varying, unlike the byte-identical subtotal labels the
      working-capital CHANGE derivation reuses) are actually present,
      minus whichever current-liability keys are present, and only fires
      when at least one of each side exists. Verified on both real
      filings with genuinely different component sets — J.F. Packaging's
      (inventories, trade receivables, 4 related-party lines, trade
      payables, 2 related-party liability lines) and Swadeshi's
      (inventories, trade receivables, advances and prepayments, trade
      payables) — each cross-checked against that company's own Total
      Current Assets/Liabilities minus its known non-operating items
      (cash, tax, debt, overdraft), not just internally self-consistent.
      `net_working_capital` = 1,120,077,705 for Swadeshi from this
      session's live extraction run.
      - **A real bug, not a hypothetical, found by re-running the full
        extraction against J.F. Packaging's actual 160-page PDF rather
        than trusting the unit-test fixtures alone**: `total_
        interest_bearing_debt` came back as 2,696,038 — exactly DOUBLE
        the correct 1,348,019. Root cause: J.F. Packaging's Note 25 page
        is subtitled "25.1. Financial Instruments - Statement of
        Financial Position", which contains the literal phrase "statement
        of financial position" — one of the primary-statement-page
        markers — so the page-marker filter let the notes page through,
        and the note's verbatim reprint of the same two debt figures got
        summed a second time by `SUM_ACROSS_OCCURRENCES`, exactly the
        kind of double-count that filter exists to prevent in the other
        direction. This is precisely why unit-test fixtures are not
        enough: no hand-written fixture had ever included a notes page
        that reprints a statement figure under a subheading matching the
        page-marker text, because it wasn't an obvious case to think of
        in advance — only running the real, complete document surfaced
        it.
      - **Fix**: a new unconditional exclusion — any page whose text
        contains "notes to the" is never treated as a primary statement
        page, checked before any positive marker, regardless of which
        marker also matches (`_NOTES_PAGE_MARKER`, `_is_primary_
        statement_page`). Verified against both companies' real PDFs
        after the fix: J.F. Packaging's debt now correctly returns
        1,348,019 from page 103 alone; Swadeshi's returns 645,836,104
        (11,672,993 non-current + 634,163,111 current, both genuinely on
        the balance sheet page, not a notes-page artifact), while
        Swadeshi's own three notes pages that separately mention
        "Interest Bearing Loans and Borrowings" (its Note 15) are
        correctly excluded.
      - `interest_expense` also now recognizes J.F. Packaging's own
        cash-flow-statement wording, "Interest Expense" — a real,
        different label from Swadeshi's "Finance Costs", verified against
        J.F. Packaging's real PDF.
      - `app/domain/dcf.py`'s module docstring updated: the working-
        capital-stock gap it named is closed; `working_capital_pct_
        revenue` could now be computed live for both companies as
        `net_working_capital ÷ revenue`, though that division is not yet
        wired into the view layer (same two structural reasons as capex/
        D&A/WACC — see the docstring).
      - New regression test using the real J.F. Packaging note text as
        its fixture, so this exact failure mode can never silently
        regress: `test_a_notes_page_whose_own_subheading_names_a_
        primary_statement_is_still_excluded`. Full suite: 676 passed.
- [x] **The full multi-year §18 FCFF DCF is live — `app.domain.valuation_
      view.dcf_for` — and joins residual income as a genuine "intrinsic"
      §24 triangulation anchor, the first §18-26 model added as an anchor
      since justified P/B and residual income at the very start of this
      wiring effort.** Every remaining gap named in the WACC/working-
      capital-stock entries above is now either closed or converted into
      a named, disclosed policy default — never a silent guess, following
      §18.2's own "never a free parameter" rule exactly:
      - `base_revenue`, `operating_margin_current` (EBIT proxy ÷
        revenue), `effective_tax_rate_current`, D&A%, capex% and
        working-capital% of revenue are all real ratios of one confirmed
        period's extracted figures.
      - `operating_margin_target` = `operating_margin_current` — reusing
        `DCFAssumptions`' own pre-existing "no fade, durable advantage,
        stated explicitly" convention, not a new invention.
      - `revenue_growth_y1`/`revenue_growth_y2` use a REAL trailing
        revenue CAGR (`_trailing_cagr`, annualised by actual elapsed
        days, not assumed whole years) whenever at least two confirmed
        revenue periods exist for the ticker; today, with only one
        verified period per company, they fall back to the same
        steady-state `g` used for stage-2/terminal growth — a disclosed
        "no growth view" default, flagged in `warnings` either way so a
        caller can tell the two apart.
      - `revenue_growth_stage2_target` and `terminal_growth` both reuse
        `_steady_state_growth` (`settings.long_run_nominal_growth_pct`,
        PARAMETERS.md #11, risk-free-rate-capped) — the SAME sourced
        policy figure residual income's own terminal assumption already
        uses, not a sector-median figure this system has no source for
        (still genuinely Phase 5).
      - `statutory_tax_rate` uses a NEW, real, verified figure — Sri
        Lanka's actual current standard corporate income tax rate, 30%,
        per Inland Revenue Department notice PN/IT/2025-01 (26 March
        2025) — `settings.statutory_corporate_tax_rate_pct`,
        PARAMETERS.md #12. Unlike `erp_effective_pct`/`long_run_nominal_
        growth_pct`, this is not a provisional placeholder for lack of a
        source; it is a cited, currently-correct rate, with its own
        disclosed limitation (concessionary sector rates — 15% service
        exports, 14% goods exports/education/healthcare, 40% gambling/
        liquor — that this system doesn't route to yet, so 30% is a real
        overstatement of the true rate for any company in one of those
        sectors).
      - `discount_rate` = the already-live WACC (`wacc_for`), `risk_free_
        rate` = the already-live risk-free observation — WACC is now
        genuinely CONSUMED, not only displayed.
      - `total_debt` = the real, extracted `total_interest_bearing_debt`.
      - Two bridge items — `minority_interest`, `pension_deficit` —
        still default to zero and are NOT extracted anywhere in this
        system. This is the DANGEROUS direction (can only overstate
        equity value for a company that actually carries either), so
        `dcf_for` flags it explicitly in `warnings` on every single call,
        the same discipline `app.domain.wacc`'s missing-cost-of-debt rule
        already established, rather than silently zeroing and moving on.
        `cash_and_non_operating_assets` also defaults to zero but in the
        SAFE direction (can only understate equity value), so it is
        flagged but not treated as equally concerning.
      - 12 new tests in `test_valuation_view.py`: trailing-CAGR unit
        tests (including the "fewer than 2 periods → None, not a
        fabricated number" case), a full hand-worked cross-check against
        `dcf_equity_value` called directly with the same real figures
        (the same "cross-check against the module's own computation"
        pattern already used for FCFF), a case proving real trailing
        CAGR is preferred over the steady-state fallback the moment a
        second confirmed period exists, a missing-`net_working_capital`
        regression, and an end-to-end test proving DCF actually joins
        residual income inside the "intrinsic" triangulation bucket
        rather than merely computing a number nobody consumes. Full
        suite: 686 passed.
- [x] **The full multi-year DCF verified genuinely end-to-end against
      Swadeshi's real FY2025/26 filing — through the actual ingestion
      pipeline, a simulated §8 confirm, and `dcf_for` — not just unit
      tests with hand-typed fixtures.** Re-downloaded the real PDF,
      re-ran `extract_financial_statement_candidates` →
      `build_fundamental_drafts` → `build_derived_fundamental_drafts`
      (the actual production functions), and found ANOTHER real gap:
      `income_tax_expense` came back `None`. Root cause: Swadeshi prints
      "Income Tax (Expense) / Reversal" — the loss-period alternative
      folded into the label itself — not the plain "Income Tax Expense"
      wording J.F. Packaging's filing uses, which is all the canonical
      label recognised. Every other DCF input (revenue, operating
      profit, D&A, capex, working capital, debt, interest) extracted
      correctly; this one line, needed for `effective_tax_rate` and
      therefore both WACC's cost of debt and the DCF's own tax path,
      silently didn't. Fixed by adding the real wording as a second
      verified variant, with a permanent regression test
      (`test_extract_candidate_lines_finds_swadeshis_income_tax_expense_
      variant_wording`) using the real page-26 text as its fixture.
      After the fix, promoted every extracted draft to `REPORTED`
      provenance with `confirmed_by` set (simulating the human §8
      confirm-queue action a real reviewer would take) in a throwaway
      in-memory DB, seeded the real disclosed share count (149,333 —
      "Total number of shares issued," Investor's Information, page 67,
      cross-checked against the disclosed Float Adjusted Market
      Capitalization: 67,082 public shares × Rs 15,000 last-traded price
      ≈ Rs 1,006,205,754, matching the filing's own figure exactly), and
      called `dcf_for` for real.
      - **The result: a real, mechanically complete 10-year projection
        and a NEGATIVE fair value per share (~Rs -13,273).** Not a bug —
        Swadeshi's real FY2025/26 operating margin is 1.55%
        (`operating_profit ÷ revenue` = 71,835,851 ÷ 4,649,049,764), held
        flat for all 10 years per `operating_margin_target`'s own "no
        fade" convention, and that thin margin combined with real
        working capital (~24% of revenue) and capex (~3% of revenue)
        produces negative unlevered FCFF in every single projected year.
        The real effective tax rate for this specific year is unusually
        high (93.84% — `22,646,628 ÷ 24,132,651`, likely a one-off
        deferred-tax item, not a durable rate) and correctly fades
        toward the real 30% statutory rate by Year 5 per the tax-fade
        path, but the margin has no such correction under this project's
        current "flat, no-view" convention, so it dominates the result.
        This is the DCF being honest about what one real, thin-margin
        year looks like held flat for a decade — exactly the kind of
        result a human reviewer is supposed to interrogate (is FY2025/26
        an anomalous down year, and does a multi-period history exist to
        check?) rather than a reason to distrust the arithmetic.
      - Ke/WACC used a clearly-labelled STAND-IN in this verification
        run only (`app.domain.cost_of_equity_view.cost_of_equity_for`
        needs real T-bill and beta series this throwaway script didn't
        seed) — every OTHER figure in the run (revenue, margin, tax,
        D&A, capex, working capital, debt, shares) is Swadeshi's real,
        extracted, now-confirmed FY2025/26 data, the same "cross-check
        against real figures, not synthetic ones" discipline this whole
        session has followed throughout.
      - Confirms `dcf_for`'s directional-safety warnings fire correctly
        on a real company too: `minority_interest`/`pension_deficit`
        zero-defaults and the "no growth view" fallback all appeared in
        `warnings` exactly as designed.
      - 1 new regression test. Full suite: 699 passed.
- [x] **§22 rule 1's hard book value wired to live data — `app.domain.
      valuation_view.hard_book_for`, the fifth live §18-26 number.**
      `revaluation_reserves` (a new canonical label, sought out
      specifically in the sectors §22 names — "plantations, property and
      hotels" — rather than reused from J.F. Packaging/Swadeshi, which
      are unlikely to carry a material one) was originally researched by
      a subagent that hit its own session usage limit mid-task; its
      findings across real filings were recovered and re-verified
      directly before wiring:
      - Kelani Valley Plantations PLC's real Statement of Financial
        Position has NO revaluation-related equity line at all — a real,
        verified zero, not an extraction gap: Sri Lanka's regional
        plantation companies hold estate land on 99-year government
        leases from the 1992 privatisation, not freehold, so there is
        nothing to revalue.
      - Asian Hotels and Properties PLC (owns Cinnamon Grand Colombo)
        prints a single combined line, "Other components of equity" —
        re-verified end-to-end 17 Aug against its actual currently-public
        FY2023/24 filing (an earlier draft of this research cited a later
        report and figures that could not be found or reproduced;
        corrected rather than left standing) — extracts correctly through
        the real pipeline with no notes-page or double-count issue. Its
        own Note 23 breaks the combined figure into a Revaluation Reserve
        plus a smaller Other Capital Reserve, confirming it's a real,
        revaluation-dominated proxy, never presented as an exact figure.
      - Galadari Hotels (Lanka) PLC prints a genuinely pure, standalone
        "Revaluation reserve" line — added as a verified wording for a
        4-column filing, but Galadari's OWN filing is 2-column and not
        yet extractable through this pipeline for an unrelated,
        pre-existing reason (`DEFAULT_EXPECTED_VALUE_COLUMNS`'s own
        "KNOWN LIMITATION").
      - `hard_book_for` computes a result whenever `total_equity` exists,
        even with no `revaluation_reserves` line found — absence is
        usually the real, correct case (Kelani Valley Plantations proves
        it) — but ALWAYS flags the ambiguity in `warnings`, because a
        missing line could ALSO mean a real reserve this extractor hasn't
        matched yet, which would silently OVERSTATE hard book if trusted
        without comment — the same "flag the dangerous-direction default
        every time" discipline `app.domain.wacc`'s missing-cost-of-debt
        rule and `dcf_for`'s missing-`minority_interest`/`pension_
        deficit` warnings already established.
      - Kept informational only, like `wacc`/`current_period_fcff`/
        `gordon_growth_ddm` — NOT a §24 triangulation anchor, even though
        §24's own weight table gives asset-based methods real weight for
        property/plantation/hotel archetypes (0.55 for `"property"`).
        Reason: `revaluation_reserves` has verified nonzero real-world
        coverage on exactly one filing so far, and even that one is a
        combined proxy, not a pure figure — not enough evidence to
        promote to an anchor without risking exactly the "confident,
        precise, entirely fictional number" §15 warns against.
      - The other four §22 tools (`value_land`, `hotel_replacement_
        cost_check`, `compute_plantation_hard_nav`, `compute_liquidation_
        value`) remain correctly unwired — they need independent
        external reference data (land valuations, hotel build-cost
        benchmarks, estate transaction prices, a liquidation-basis PP&E
        mark) no source in this project provides.
      - New `GET /valuation/{ticker}` field `hard_book`. 6 new tests
        across `test_financial_statement_parsing.py` (the real AHPL
        extraction, using the real re-verified page-164 text as its
        fixture) and `test_valuation_view.py` (hand-worked with and
        without a real reserve, missing-total_equity, §8 exclusion).
        Full suite: 704 passed.
- [x] **`npm audit` vulnerability fixed** — Vite 5.4→8.2.1 and
      `@vitejs/plugin-react` 4.3→6.0.5 (the version that actually declares
      a `vite@^8` peer dependency, so the upgrade doesn't leave an
      ERESOLVE warning behind). Verified beyond "it installed": clean
      `tsc --noEmit`, a successful production build, and the dev server
      loaded in a real browser with zero console errors post-upgrade.
      `npm audit`: 0 vulnerabilities (was 2).
- [x] **§19.1 Gordon-growth DDM wired to a real, if currently empty,
      confirmed-dividend pipeline — the fourth live §18-26 number, and a
      genuinely different kind of "real but empty" from anything wired
      so far.** `dividend_residual_income.py`'s own module docstring used
      to say "dividend history is not extracted anywhere in this
      system" — that was true when it was written and is now precisely
      half corrected. `app.ingestion.corporate_actions_loader` already
      scrapes real per-share cash dividend declarations from real CSE
      announcements into `CorporateAction` rows (`ex_date`, `cash_
      amount`, type `DIVIDEND_CASH`) — that ingestion gap was closed
      back in Phase 1. What was never wired is the LAST mile: §8/§9
      treats a `CorporateAction` as "the highest-consequence data in the
      system" and the loader never auto-confirms one (`confirmed_by`/
      `confirmed_at` start `None`, always); only a human confirm-queue
      workflow, not yet built, sets them. So the live dev database has
      zero CONFIRMED dividend rows for any ticker today — expected, not
      a bug, and the reason `gordon_growth_ddm.result` will read `None`
      for essentially every real ticker until that workflow exists.
      - New `app.domain.valuation_view._confirmed_dividends_as_of`:
        §8/§9's provenance gate applied to `CorporateAction` rather than
        `Fundamental` — `confirmed_by is not None` (a binary state, this
        table has no AI-assisted tier the way `Fundamental` does) rather
        than a `can_enter_valuation` tier check, point-in-time visible
        via `ex_date <= as_of` (this table has no `first_available_date`
        column to run through `fundamentals_as_of`, but gating on
        `ex_date` is conservative in the same direction — CSE announces
        a dividend before the ex-date, so this can only make a row
        visible as late as or later than the market itself priced it in,
        never earlier).
      - New `_trailing_dividend_per_share`: sums `cash_amount` across
        every confirmed dividend whose `ex_date` falls in the trailing
        twelve months of `as_of`, deliberately a TTM sum rather than
        just the single most recent payment — a CSE company routinely
        pays an interim AND a final dividend in the same year, and
        picking only "the most recent one" would over- or under-state
        the annual rate purely depending on where `as_of` falls in the
        cycle. Returns `None` (not zero) when no confirmed dividend
        falls in that window, even if older confirmed rows exist further
        back — a >12-month-old payment is stale as a "what does this
        company currently pay" estimate, and using it unqualified would
        misrepresent stale history as current, exactly what §15 warns
        the whole engine exists never to do.
      - New `gordon_growth_ddm_for` calls the real, already-tested
        `app.domain.dividend_residual_income.gordon_growth_value` (§19.1,
        `V0 = D1 / (Ke - g)`), reusing `cost_of_equity_for` for Ke and
        this module's own existing `_steady_state_growth(risk_free_
        rate)` for `g` — no new policy number invented. D1 is derived
        from the real trailing D0 via Gordon growth's own `D1 = D0(1+g)`
        identity (this system has no dividend-growth forecast any more
        than it has an ROE-improvement forecast — same absence
        `_steady_state_growth`'s docstring already explains), not a
        second invented growth assumption layered on top of the first.
        `check_gordon_growth_eligibility` (the five-year-payout-
        stability/maturity gate) is deliberately not run — this system
        tracks neither input yet, and the result is informational only
        regardless, so there is no eligibility gate left to skip.
      - Wired into `CompanyValuationSummary.gordon_growth_ddm` and `GET
        /valuation/{ticker}` as `gordon_growth_ddm` — informational only,
        same status as `current_period_fcff` and `wacc`, NEVER a
        triangulation anchor: a Gordon-growth DDM built on zero confirmed
        dividend history in production is not ready to move a price
        ladder, the same reasoning that keeps the other two informational.
      - 12 new tests in `test_valuation_view.py`: the §8 confirm/point-
        in-time gate on `CorporateAction` rows (confirmed-but-future-
        ex-date correctly excluded, unconfirmed row correctly excluded,
        ordering), the TTM summation logic on hand-worked numbers
        (single payment, interim+final summed, a stale payment outside
        the window correctly excluded even with newer confirmed history
        nearby), and the full `gordon_growth_ddm_for` wiring: a
        hand-worked single-dividend case (D0=2.00, g=0.05, Ke=0.15 →
        D1=2.10, V0=21.0), a hand-worked two-dividend case (D0=2.50 →
        V0=26.25), the "zero confirmed dividends" named-reason case (the
        expected common case today), the unconfirmed-row §8 regression,
        the stale-history case, and the missing-Ke case. Full suite: 688
        passed.

## Explicitly deferred to later phases

The earnings integrity veto (§14 — needs CFO, related-party revenue,
auditor and director-dealings data this system does not extract), §27
execution reality (needs a live order-book feed, 15-minute cadence — not
part of Phase 3's own gate per Master Spec §54's build-sequence table),
factor library, scoring, AI research writer, decision capture UI — all
Phase 4+ per §54. Fundamental ratios (§12), trend detection (§13), the
model router (§15/§16), and valuation MATH (DCF, DDM, residual income,
SOTP, relative valuation, asset-based, scenarios, triangulation, margin
of safety, the price ladder — §17-26) are no longer in this list — see
above. **Macro/ARDL (§29-34) is also no longer a single untouched
block** — §31's regime classifier and §33's sector sensitivity matrix
are both live (see those two entries above); §30's other five method-
chain steps and §34's national project register remain genuinely
unbuilt, named precisely in the same sections rather than left as one
vague "macro/ARDL" line item. Building the still-deferred items against
unvalidated data, or against inputs this system doesn't actually have,
would produce exactly the look-ahead-biased, false-precision numbers the
spec's failure-mode register (Part N) warns about.
