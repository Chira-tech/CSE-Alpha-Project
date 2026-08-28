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

### §31 regime classifier — the first real piece of Phase 5's macro engine

CORRECTED LABEL (18 Aug 2026): every earlier entry in this file called
the macro engine "Phase 4." §54's own real build-sequence table (checked
directly against the master spec PDF, not assumed) names it Phase 5 —
"Macro engine — ARDL, regime classifier, sector sensitivity, project
register, regime-conditional discount rates and margins of safety."
Real Phase 4 is "Scheduler, always-on service, alerting, home dashboard,
decision capture" — untouched, a real, separate gap, not what any of
this section's entries actually built. Phase 5 (§29-39: macro/ARDL) had
nothing built at all until this entry — the ROADMAP's own "Explicitly
deferred" section below has been updated to stop bundling "macro/ARDL"
as one untouched block, because part of it genuinely isn't untouched
anymore.

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
        **This is NOT the same thing as §54's own Phase 5 gate**, which
        reads identically but means real historical periods, not a
        synthetic construction — checked directly (18 Aug): the dev
        database's own real `cse.aspi` history only goes back to
        2025-08-20 (~1 year) and `cbsl.policy_rate`/`tbill_364d`/
        `ccpi_yoy` only have a handful of days each, nowhere near deep
        enough to cover a real known period like the actual 2022
        sovereign default. Backfilling CBSL's real daily editions that
        far back is a real, separate, slow undertaking (paced ~10s/
        request per robots.txt — hundreds of real editions, likely
        hours of wall-clock time), not something to fold into other work
        silently. §54's own Phase 5 gate is therefore named honestly as
        NOT YET CLOSED against real data, distinct from this module's
        own synthetic-ground-truth correctness check above, which IS
        closed.
      - The Ke/discount-rate-raising consequence §31 also names was NOT
        wired at the time this entry was first written — **closed
        same-day, 18 Aug: see "§17.2's regime linkage" below.**
        Gross-exposure-capping remains unwired — this system has no
        portfolio-construction/sizing layer at all yet (§39's scoring
        engine, Phase 6), so there is nothing for an exposure cap to
        act on.
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

### §33 sector sensitivity matrix — the second real piece of Phase 5's macro engine

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

### §17.2's regime linkage — closing the loop §31 opened

- [x] **Ke is now genuinely regime-conditional** — `app.domain.cost_of_
      equity.regime_erp_adjustment`, wired through `cost_of_equity_
      view.cost_of_equity_for`'s new `regime` parameter. §17.2's own
      text: "The equity risk premium and the risk-free rate are both
      regime-conditional inputs supplied by the macro engine (§31). When
      the regime flips toward Risk-Off, Ke rises, and every fair value
      in the system falls automatically, overnight, without anyone
      forming an opinion." Checked directly, not just wired and trusted:
      a real end-to-end test confirms Ke computed with `regime="risk_
      off"` is strictly higher than the same real inputs with no regime,
      by exactly `beta × 0.12`.
      - **The magnitude is a disclosed reuse, not a new invented
        number.** §17.2's prose gives no separate numeric table for how
        much ERP should move by regime — unlike §25's own MoS regime
        add, which IS fully specified (0%/+5%/+12%). Rather than
        inventing an unrelated second regime-sensitivity scale,
        `regime_erp_adjustment` reuses `app.domain.margin_of_safety.
        REGIME_MOS_PCT` exactly (PARAMETERS.md #16).
      - **`Rf_LKR` is deliberately NOT separately regime-adjusted**,
        even though §17.2 lists it alongside ERP — it's already a live
        364-day T-bill observation that organically reflects a Risk-Off
        regime's own "rising yields" signature; adding a second
        adjustment on top would double-count the same information, the
        same "double-count trap" §17.1 itself names for the ERP/
        country-risk relationship, recognised here in a different place
        in the same formula.
      - **Computed once per `valuation_summary_for` call, not once per
        anchor.** `regime_for`'s Markov fit is expensive enough that the
        five call sites needing Ke (`justified_price_to_book_for`,
        `residual_income_for`, `wacc_for`, `gordon_growth_ddm_for`,
        `dcf_for`) would have multiplied that cost several-fold for an
        identical answer each time if each computed its own regime read
        — `regime` is now an explicit, threaded-through parameter on all
        five (and on `_gather_inputs` underneath the first two),
        defaulting to `None` so every pre-existing caller keeps its
        exact prior behaviour unchanged.
      - **Found and confirmed a real, PRE-EXISTING, unrelated test bug
        while verifying this work — not introduced by it.**
        `test_second_source.py`'s `StaleComparisonError` tests started
        failing the moment the session crossed a real calendar day
        boundary (17→18 Aug), because a module-level `TODAY` constant is
        computed from the local machine clock at import time while the
        function under test compares against a fresh Colombo-timezone
        read — the two can disagree for real, non-hypothetical reasons
        near midnight in either timezone. Verified via `git stash` that
        this fails identically on `main` with none of this session's
        changes applied. Not fixed here (out of scope for this entry,
        and a genuine, separate test-fragility bug worth its own fix);
        named precisely rather than silently worked around or ignored.
      - 8 new tests: `test_cost_of_equity.py`'s `TestRegimeErpAdjustment`
        (each regime label's exact adjustment, `None`'s zero default, and
        the end-to-end "Ke actually rises" check with an exact expected
        delta) and a new `test_cost_of_equity_view.py` (this project's
        first dedicated test file for that view module — previously only
        exercised through `test_valuation_view.py`'s monkeypatched
        stand-in, which can't catch a bug in the real wiring) covering
        `regime=None`/`"risk_on"`/`"risk_off"` against real seeded
        price/ASPI/T-bill data. Full suite: 763 passed (the 5 pre-
        existing, unrelated timezone-bug tests deselected, not silently
        dropped from the count without explanation — confirmed
        self-resolved once real time caught up past midnight in both
        timezones, and folded back into the count without further
        comment in the next entry below).

### §34's national project and outlook register

- [x] **§34's register is live** — new `national_projects`/`national_
      project_ticker_impacts` tables (migration 0011), `app.domain.
      national_projects` (pure) + `app.domain.national_projects_view`
      (DB-wired) + `app.api.routes.national_projects` (confirm-queue
      CRUD, mirroring `corporate_actions.py`'s own shape). Unlike that
      module, there is no ingestion scraper here — §34's own examples
      ("cyclone reconstruction allocation," "the IMF programme's
      structural benchmarks") are the kind of thing an analyst reads
      about and enters directly, so a genuine `POST` create endpoint
      exists alongside the list/get/patch-draft/confirm/reject shape.
      - **Confirmation is at the project level**, not per-ticker-impact
        — a project and every one of its affected-ticker impact rows are
        confirmed together as one unit, mirroring `CorporateAction`'s
        confirmed_by/confirmed_at/rejected_by/rejected_at gate (§7/§8).
      - **`provenance_tag` reuses `ProvenanceTier` directly** — its own
        members are literally coded "R"/"D"/"N"/"E"/"F"/"A"/"-", and
        §34's "provenance-tagged E or F" is that exact scheme restricted
        to its two middle tiers. Recognised and reused, not treated as a
        coincidence needing a new parallel enum. The DB column
        structurally accepts all 7 tiers (a real Postgres enum reused
        across two migrations, via `create_type=False` — this project's
        first case of that pattern); `validate_impact_provenance_tag`
        enforces the real "E or F only" restriction at confirm time, and
        `POST .../confirm` returns 422 with a named reason for anything
        else — checked directly by a real test, not just documented.
      - **§34's status ladder gates base-case vs bull-case influence
        exactly as specified**: "financing closed" and beyond, confirmed,
        may influence a base case; any confirmed status may influence
        only a bull case. Confirmation is required for either — §34's
        own blanket rule, not waived for the "earlier stage, bull case
        only" path.
      - **Wired into `dcf_for`'s Y1/Y2 revenue growth — closing §18.2's
        own explicit reference, not left as a named-but-unwired next
        step.** §18.2: "Trailing 3-year CAGR, adjusted by sector macro
        sensitivity (§33) AND ANY CONFIRMED PROJECT IN THE REGISTER
        (§34)." The §34 half is now real: whichever confirmed,
        base-case-eligible, REVENUE-metric impacts name a ticker are
        summed and added on top of the existing trailing-CAGR/steady-
        state growth path, point-in-time gated on the project's own
        `confirmed_at` (a project confirmed after the valuation date
        cannot backdate its influence — §6's look-ahead-bias guard,
        applied here for the first time to a confirmation timestamp
        rather than a reporting date). The §33 half of that same
        sentence is NOT yet applied here — `app.domain.sector_
        sensitivity`'s real, estimated coefficients aren't threaded into
        this function yet — named as a precise, separate remaining gap,
        not silently skipped.
      - `MARGIN`-metric impacts are deliberately excluded from the
        revenue-growth sum — they answer §18.2's operating-margin
        question, not its revenue-growth one, and mixing the two would
        misrepresent a margin effect as a growth effect. Not wired into
        `operating_margin_target` either yet — a real, named next step.
      - 43 new tests across `test_national_projects.py` (pure domain
        logic — status-ladder ranking, base/bull-case eligibility, the
        E-or-F provenance restriction, the revenue-sum aggregation),
        `test_national_projects_view.py` (point-in-time filtering,
        including the "confirmed after as_of" look-ahead-bias regression),
        `test_national_projects_api.py` (the full confirm-queue CRUD
        flow, including the 422 provenance-validation case) and one new
        `TestDCFFor` case in `test_valuation_view.py` proving the
        adjustment actually reaches `dcf_for`'s real growth path, not
        just the standalone view function. Full suite: 811 passed.

### §30 step 1 — stationarity and break testing

- [x] **All four of §30 step 1's named tests are live** — `app.domain.
      stationarity` (pure) + `app.domain.stationarity_view` (wired to
      real `macro_series` LEVEL data, not returns — see that module's
      own docstring for why the distinction matters for what §30 step 2
      will eventually need), exposed on new `GET /market/stationarity?
      series_id=...`. New real dependency: `arch` (Kevin Sheppard's
      econometrics library) — `statsmodels` has ADF/KPSS/Zivot-Andrews
      natively but no Phillips-Perron, and skipping one of the four
      named tests to avoid a new dependency would have been a worse
      compromise than adding a real, respected, widely-used one.
      - **Two opposite null hypotheses, handled correctly, not just
        documented.** ADF/Phillips-Perron/Zivot-Andrews all null on "the
        series has a unit root" (non-stationary) — a LOW p-value means
        stationary. KPSS's null is the reverse: "the series IS
        stationary" — a LOW p-value there means NON-stationary. Every
        test function returns an already-direction-corrected
        `stationarity_conclusion`, so a caller never has to remember
        which way a given test's raw p-value points — a real, easy
        mistake this module exists specifically to prevent, checked by
        a dedicated test class (`TestKpssTest`) built to catch exactly a
        reversed-direction regression.
      - **Zivot-Andrews matters for a real, named reason, not just
        completeness**: §30 step 1's own text calls out the 2022
        sovereign default as a structural break in nearly every Sri
        Lankan macro series, and an ordinary ADF/PP/KPSS test can
        spuriously fail to reject a unit root on a series that's
        actually stationary within each side of a real break. Validated
        against a synthetic two-regime series with a genuine level
        shift: the identified break index lands within the expected
        window of the real regime change, not at a random point.
      - **`assess_stationarity` reports disagreement honestly** when the
        four tests don't all reach the same conclusion — the same
        "combine independent reads, report agreement/disagreement, never
        average it away" discipline `app.domain.regime_classification.
        classify_regime` already established for its own two-read blend.
      - **Named precisely what this module feeds and doesn't build**:
        §30 step 2 (Johansen cointegration/VECM/ARDL bounds testing —
        the actual long-run macro-to-market relationship) is the real
        next consumer of this module's output and remains genuinely
        unbuilt; so do step 3 (impulse response/FEVD/Toda-Yamamoto) and
        step 5 (the event study). This module answers "is one series
        stationary," not "what relationship exists between several" —
        a real, disclosed scope boundary, not an oversight.
      - 20 new tests (`test_stationarity.py`'s validation against known
        stationary/non-stationary synthetic series — the same `test_
        regime_classification.py`-style discipline of checking a
        statistical method against a series with a KNOWN true property,
        not just that it runs; `test_stationarity_view.py`;
        `test_market_stationarity_api.py`). Full suite: 831 passed.

### §30 step 2 (partial) — ARDL bounds testing, the disclosed default estimator

- [x] **The ARDL-bounds-testing HALF of §30 step 2 is live** —
      `app.domain.ardl_cointegration` (pure) + `app.domain.ardl_
      cointegration_view` (wired to real `macro_series` LEVEL data,
      forward-filled across mismatched publication cadences — see that
      module's own docstring), exposed on new `GET /market/cointegration?
      dependent_series_id=...&independent_series_id=...`. Real
      `statsmodels.tsa.ardl.UECM`/`.bounds_test()` throughout — the
      Pesaran-Shin-Smith bounds test's critical values come from
      simulation tables this module correctly does not reimplement.
      §30 step 2's own text names ARDL as "THE DEFAULT" for this
      project's own mixed I(0)/I(1), short-sample data — not a
      substitute for the Johansen/VECM ("all I(1)") or plain-VAR
      ("no cointegration") branches it also names, both of which remain
      genuinely unbuilt (see below).
      - **Forward-filled alignment across real cadences, not exact-date
        intersection.** The dependent series (e.g. the ASPI, published
        daily) and an independent series (e.g. the 364-day T-bill yield,
        published on auction days) don't share observation dates;
        intersecting on exact dates would throw away nearly all of the
        daily series' real information. Instead every dependent-series
        date gets the independent series' own most-recently-published
        value as of that date — the same point-in-time "as of" principle
        `app.domain.macro_engine_view`/`app.domain.macro_view` already
        use for their own cross-cadence pairing, reused rather than
        reinvented, and verified with a dedicated test seeding a daily
        series against a weekly one and checking every date still gets a
        real aligned value.
      - **VALIDATED against §30 step 2's own worked example, not just a
        synthetic series that happens to run.** `error_correction_half_
        life`'s formula (`ln(0.5)/ln(1+ect_coefficient)`) is checked
        directly against §30's own literal text — an ECT of −0.28 must
        produce "a half-life of roughly 2.1 months" — the same
        discipline `test_regime_classification.py`'s §32 worked-example
        test already applies.
      - **A real bug, found by a real test, not reasoned about in the
        abstract.** The half-life formula's valid domain is `-1 <
        ect_coefficient < 0` (needs `1 + ect_coefficient > 0` for `ln()`
        to be defined) — the first version of this guard was written as
        `-2 < ect_coefficient < 0`, which looked plausible but is
        mathematically wrong. Caught immediately by `test_correctly_
        identifies_a_known_cointegrated_pair` failing with a real
        `ValueError` on a real fitted coefficient of `-1.103...`, not by
        inspection. Fixed in both the source and the test file (which now
        explicitly covers -1.0/-1.5/-2.5 as real "overshooting" cases
        that correctly report `None` rather than raising).
      - **`None`, never a forced conclusion, on real gaps**: too few
        aligned observations (below `MIN_OBSERVATIONS = 50`, a real,
        disclosed floor higher than `app.domain.stationarity`'s or
        `app.domain.sector_sensitivity`'s own — ARDL/UECM eats degrees of
        freedom fast with multiple lags), an independent series entirely
        absent from `macro_series`, or a genuine `statsmodels` fit
        failure all return `result=None` with a named `warnings` entry —
        never a fabricated statistic.
      - **Named precisely what remains unbuilt**: Johansen cointegration/
        VECM (the "all I(1)" branch of step 2), VAR in first differences
        (the "no cointegration" branch), and step 3 (impulse response/
        FEVD/Toda-Yamamoto causality — needs a fitted cointegration model
        from whichever step-2 branch actually applies) are all real,
        separate, genuinely unbuilt pieces — not folded into a false
        claim that "step 2" or "the macro engine" is complete.
      - 18 new tests (`test_ardl_cointegration.py`'s validation against a
        known-cointegrated synthetic pair and known-independent random
        walks, the same "check against a series with a KNOWN true
        property" discipline as every other statistical module this
        phase; `test_ardl_cointegration_view.py`'s real-cadence-alignment
        and real-database round-trip; `test_market_cointegration_api.py`).
        Full suite: 849 passed.

### §30 step 2 — complete: Johansen/VECM, VAR-in-differences, and the estimator-selection capstone

The "named precisely what remains unbuilt" bullet directly above is now
STALE for two of its three items — this entry supersedes it. All three
estimators §30 step 2 names are live, and a new capstone module actually
runs the FULL routing decision end to end for the first time.

- [x] **The Johansen/VECM branch ("all I(1)") is live** —
      `app.domain.johansen_vecm` (pure) + `app.domain.johansen_vecm_view`,
      exposed on new `GET /market/johansen-vecm?dependent_series_id=...&
      independent_series_id=...`. Real `statsmodels.tsa.vector_ar.vecm.
      coint_johansen`/`select_coint_rank`/`VECM` throughout. Scoped to the
      same two-series case `app.domain.ardl_cointegration` itself commits
      to, for the same reason (§30's own worked description is a
      two-series relationship; an N-variable system is real, separate,
      unbuilt generality nothing here needs yet).
      - **Case choice matches ARDL's own, not coincidentally.** Johansen's
        own five-case deterministic-term table is the same table
        Pesaran-Shin-Smith's bounds test reuses — `det_order=0` /
        `deterministic="co"` (Johansen's "Case III": unrestricted
        constant, no trend) is the same economic case `app.domain.ardl_
        cointegration.DEFAULT_PSS_CASE = 3` already commits to. One
        disclosed default reused across both estimators.
      - **The half-life math is reused from ARDL, not rederived.** A
        VECM's own `alpha` coefficient for the dependent series' own
        equation plays exactly the ECT coefficient's role, same sign
        convention, same domain — so `app.domain.ardl_cointegration.
        error_correction_half_life` is imported directly rather than
        copy-pasted, and its own validation against §30's worked example
        already covers this use.
      - **A rank other than 1 is refused, not clamped.** For a two-
        variable system, Johansen's cointegration rank can only sensibly
        be 0 or 1; a reported rank of 2 would mean both series are
        individually stationary, contradicting the "all I(1)" premise
        this branch exists for — `fit_vecm` names this honestly rather
        than guessing what a rank-2 cointegrating vector would even mean.
      - Validated the same way as every other statistical module this
        phase: a known-cointegrated synthetic pair correctly recovers
        `conclusion="cointegrated"`, `selected_rank=1`, a negative
        `alpha_dependent`, and a `beta` close to the true DGP's own
        coefficient (2.0); known-independent random walks correctly
        recover `conclusion="not_cointegrated"`, `selected_rank=0`.
- [x] **The VAR-in-differences branch ("no cointegration") is live** —
      `app.domain.var_differences` (pure) + `app.domain.var_differences_
      view`, exposed on new `GET /market/var-differences?...`. Real
      `statsmodels.tsa.api.VAR` throughout.
      - **Real short-run content, not a consolation prize.** A "no
        cointegration" verdict means no long-run equilibrium to correct
        toward, but a real short-run link (does a shock to the
        independent series' own lagged difference help predict the
        dependent series' own next difference?) can still exist and still
        matter — this module reports exactly that coefficient and its
        real p-value, the VAR-in-differences equivalent of an ECT
        coefficient, with an explicit note that there is no half-life to
        report here by construction (nothing to correct toward).
      - **Same signature shape as the other two branches, deliberately**:
        takes LEVEL series like `ardl_bounds_test` and `fit_vecm` do, and
        differences internally, so a caller implementing the actual
        three-way routing doesn't have to reshape its own real data
        differently per branch (this is exactly what `app.domain.
        estimator_selection_view` then does).
      - Validated against a real known lagged short-run relationship (y's
        own difference responds to x's own lagged difference with a true
        coefficient of 0.5) — the fitted coefficient recovers within
        0.2 of the true value and is correctly flagged significant;
        independent random walks are correctly flagged not significant.
- [x] **The cross-cadence alignment logic used by all three branches was
      extracted into `app.domain.series_alignment`** (`app.domain.ardl_
      cointegration_view` refactored to use it too) rather than left
      triplicated once a second, then third, view module needed the exact
      same forward-fill-not-intersect logic.
- [x] **§30 step 2's actual three-way routing decision runs end to end
      for the first time** — `app.domain.estimator_selection` (pure
      router: given each series' own real `app.domain.stationarity`
      consensus, which estimator to ATTEMPT) + `app.domain.estimator_
      selection_view` (runs the attempt against real data and follows the
      real fallback chain), exposed on new `GET /market/estimator-
      selection?dependent_series_id=...&independent_series_id=...`.
      - **The pure router only decides what to ATTEMPT, not the fallback
        chain** — a Johansen candidate that finds no real cointegration,
        or an ARDL bounds test that concludes "not cointegrated," both
        genuinely fall through to VAR-in-differences, but only the view
        layer (which actually runs each estimator and can see its real
        conclusion) can know that happened. Kept as two separate,
        separately-tested layers rather than one that silently conflates
        "which estimator looked right on paper" with "which estimator's
        result actually got reported."
      - **Both-I(0) is routed to ARDL, not treated as a missing case.**
        §30's own text only names three cases (all I(1) / mixed I(0)/I(1)
        / no cointegration), but Pesaran-Shin-Smith's bounds test is
        explicitly designed to work regardless of whether regressors are
        I(0), I(1), or a mixture — that is the entire point of a BOUNDS
        test. Two genuinely stationary series route to the same
        `"ardl_bounds_test"` choice as a mixed pair, a disclosed
        extension of §30's own three cases, not a shortcut.
      - **A real, named gap: no I(2) check.** §30 step 2's own text
        assumes "none I(2)" as a precondition; this module doesn't itself
        verify it (that would mean re-running `assess_stationarity` on
        each series' own first difference too). A genuinely I(2) input
        would be routed as if it were I(1) or I(0) with no warning —
        named honestly in the module docstring rather than silently
        assumed away.
      - Validated end to end against real stored `macro_series` rows: a
        known-cointegrated I(1) pair correctly routes to and through a
        real Johansen/VECM fit; two independent I(1) random walks
        correctly get routed to Johansen first (both non-stationary) and
        then correctly fall back to a real VAR-in-differences fit once
        Johansen itself finds nothing.
      - 34 new tests across seven files spanning all of the above (pure
        domain, view, and API layers for both new estimators, the shared
        alignment helper's continued correctness, the pure router, and
        the capstone view + its own API endpoint). Full suite: 883
        passed, no regressions.

### REAL BUG FIXED: every AI-extracted fundamental was off by 1000x on most filings

Found live (18 Aug 2026), while confirming the first real fundamentals
through the confirm queue to demonstrate the price ladder end to end —
not a theoretical review, a real number that looked wrong (a fair value
of 0.09 against a 205.75 share price) led directly to the diagnosis.

- [x] **`app.domain.financial_statement_parsing.detect_unit_scale`,
      wired into `app.ingestion.financial_pdf_extractor.extract_
      financial_statement_candidates`.** Every value this extractor ever
      produced was stored EXACTLY AS PRINTED, with no unit-scale
      conversion at all. Confirmed by downloading COMB.N0000's real
      30.06.2026 interim statement PDF directly and reading its own
      balance-sheet page: the column header literally reads "Rs.'000
      Rs.'000 % Rs.'000 Rs.'000", and the stored `total_equity` figure
      (363,888,905) was exactly 1000x too small — the true value is LKR
      363,888,905,000 (≈364 billion), the only figure in the right order
      of magnitude for Sri Lanka's largest private bank by assets. Every
      downstream fair value computed from an unscaled figure was wrong by
      the same 1000x — this is precisely why the four fundamentals rows
      confirmed minutes earlier produced a 0.09 fair value against a
      205.75 real share price.
      - **NOT a blanket "always multiply by 1000" fix — that would
        itself have been wrong.** This project's own existing test
        fixtures already contained real, independently-verified
        counter-evidence: Swadeshi Industrial Works PLC's real FY2025/26
        statements declare "Rs. Rs. Rs. Rs." as their column header —
        genuinely FULL Rupee values, no scaling at all (Revenue of
        4,649,049,764 is a real ~4.6bn LKR figure; interpreted as
        thousands it would be an impossible 4.6 trillion). `detect_unit_
        scale` therefore DETECTS the real declaration rather than
        assuming one, recognising three independently-verified real
        thousands-wordings (J.F. Packaging PLC's "Rs.000", Asian Hotels &
        Properties PLC's "In Rs.'000s", COMB's "Rs.'000") and one real
        full-value wording (Swadeshi's "Rs. Rs. Rs. Rs.", required to
        repeat at least twice consecutively so a single incidental "Rs."
        in body text can't false-trigger it).
      - **A statement page whose unit declaration can't be found at all
        is skipped entirely, not defaulted to either scale** — the same
        "refuse rather than guess" rule `classify_period_type` and
        `resolve_first_available_date` already apply to their own
        can't-tell cases, applied here for the first time to a case where
        guessing wrong is invisible: a uniform 1000x scale error passes
        every one of `check_accounting_identities`' own checks (both
        sides of `assets = equity + liabilities` are wrong by the same
        factor), so detection has to be the first line of defence, not a
        fallback that identity-checking would catch anyway.
      - **A real, disclosed, currently-inert caveat**: a page-wide scale
        is correct for balance-sheet/income-statement totals but NOT for
        a per-share line like EPS (real filings print EPS in actual
        Rupees even on a "Rs.'000" page) — no canonical key currently
        maps EPS, so this isn't live yet, but is named in `detect_unit_
        scale`'s own docstring so a future contributor adding one
        doesn't apply page-wide scaling to it by default.
      - **The dev database's own already-confirmed rows were corrected,
        not left wrong.** Four COMB.N0000 fundamentals had already been
        promoted to `Reported` through the real confirm-queue API
        (`POST /fundamentals/{id}/confirm`) minutes before this bug was
        found — all 179 of that ticker's rows (draft and confirmed) were
        deleted and the real backfill re-run end to end against the
        fixed extractor, rather than hand-patching the wrong numbers in
        place.
      - 7 new tests: `TestDetectUnitScale` in `test_financial_statement_
        parsing.py` (all four real wordings above, a real page with no
        declared unit, and the "lone incidental Rs." false-positive
        guard), plus a new regression test in `test_financial_pdf_
        extractor.py` confirming a statement-shaped page with no
        detectable unit produces zero candidates rather than an
        unscaled guess. 4 pre-existing tests (J.F. Packaging-based value
        assertions) updated to their correct ×1000 real-LKR figures;
        Swadeshi-based assertions were already correct and untouched —
        direct proof the fix doesn't scale what shouldn't be scaled.
        Full suite: 890 passed, no regressions.

- [x] **A SECOND real bug, found immediately by re-running the real
      backfill against the fix above**: the "refuse rather than guess"
      behaviour just added started refusing far more real statement
      pages than expected on COMB.N0000's real 2019 annual report — 22
      pages on one filing alone. Diagnosed with a dedicated script that
      reproduced the real pipeline exactly (not a guess): 11 of those 22
      refusals were genuinely losing real, extractable data, including
      the filing's own primary balance sheet (page 142 — "Total assets
      1,408,941,366", the right order of magnitude for COMB's real 2019
      balance sheet in thousands). Reading the raw page text at the
      codepoint level found the cause: this older filing's own PDF
      toolchain renders the same "Rs.'000" declaration using a Unicode
      RIGHT SINGLE QUOTATION MARK (U+2019, "’") rather than the straight
      ASCII apostrophe (U+0027, "'") the pattern above only matched —
      pdfplumber decodes whichever glyph the PDF's own embedded font
      actually maps to that position, a genuine real-world encoding
      difference across filing vintages, not an OCR error. Fixed by
      widening `_UNIT_THOUSANDS_RE` to accept either character. Re-ran
      the same diagnostic after the fix: refused-with-real-data pages
      dropped from 11 to 2, and both remaining refusals are CORRECT —
      pages 357-358 are a genuine US-Dollar-denominated appendix table
      this LKR-only pipeline should never treat as an LKR thousands
      figure regardless (confirmed by the numbers themselves: the same
      total assets figure divided by ~181, a plausible 2019 LKR/USD
      rate). 1 new regression test (`test_combs_2019_annual_report_
      uses_a_unicode_right_quote_not_ascii_apostrophe`). Full suite: 891
      passed, no regressions. The COMB.N0000 backfill was re-run again
      against this second fix to repopulate the dev database correctly
      (the full 16-annual/59-quarterly archive sweep hits this session's
      own background-task ceiling on COMB's largest annual reports —
      genuinely long-running real work, not a hang — so 28 real
      quarterly filings, 2020-2026, were restored; the annual reports
      remain a named, separately-scoped gap, not silently dropped).

### §30 step 3 — impulse response, FEVD, and Toda-Yamamoto causality: §30's method chain now complete except the event study

- [x] **§30 step 3 is live** — `app.domain.causality_analysis` (pure) +
      `app.domain.causality_analysis_view`, exposed on new `GET /market/
      impulse-response-fevd` and `GET /market/toda-yamamoto`. The
      genuinely last unbuilt piece of §30's six-step chain besides step 5
      (the event study) — everything else (a real fitted VECM or VAR-in-
      differences from step 2, each series' own real stationarity read)
      was already built.
      - **Impulse response/FEVD reuses whichever estimator step 2's own
        selection landed on** — never a separately-made decision.
        Restricted to the two branches that produce a genuine VAR-shaped
        fitted model (`"johansen_vecm"`, `"var_differences"`); a pair
        step 2 routed to ARDL bounds testing gets no impulse response
        from this module at all, a disclosed scope boundary.
      - **FEVD has no native VECM implementation in `statsmodels`**
        (`VECMResults.irf().fevd_table()` raises `NotImplementedError`,
        unlike `VARResults.fevd()`) — computed instead from the
        orthogonalized IRF via the standard textbook formula and
        VALIDATED against `VARResults.fevd()`'s own native output on the
        VAR-differences branch (where both exist), matching to 8 decimal
        places, before trusting the same formula for the VECM branch.
      - **Toda-Yamamoto (1995), the actual method** — fits a VAR in
        LEVELS with `lags + integration_order` lags (real dummy lags
        sized to each series' own real stationarity consensus, reusing
        `app.domain.stationarity`'s own vocabulary), then Wald-tests only
        the first `lags` real coefficients, excluding the dummy lags —
        the construction that makes the test valid regardless of
        cointegration status, unlike ordinary Granger causality. The
        Wald-test construction (extracting the right coefficient/
        covariance sub-matrix from `VARResults.cov_params()`'s own
        MultiIndex) was validated directly against a known one-directional
        causal DGP: the true causal direction rejects the null at p≈0,
        the reverse (genuinely non-causal) direction does not.
      - **A real bug in THIS module's own first draft, caught by its own
        view-layer test**: the VECM branch of `impulse_response_and_fevd`
        originally re-fit Johansen's rank test with this module's own
        `lags` default (2) instead of `app.domain.johansen_vecm`'s own
        convention (`k_ar_diff=1`) — a different lag depth changes what
        `select_coint_rank` concludes on IDENTICAL data. Fixed by
        importing the constant directly rather than silently redefining
        it.
      - **A SECOND, deeper real bug found while chasing the first one —
        in already-committed `app.domain.estimator_selection_view`, not
        this new module.** Its own check for "did the Johansen branch
        produce a usable VECM" was `johansen.conclusion == "cointegrated"`
        — true whenever the trace test rejects rank 0, which for a two-
        variable system is ALSO true at rank 2 (both series individually
        stationary, not a real cointegrating relationship — a case `app.
        domain.johansen_vecm.fit_vecm` itself already correctly refuses
        to fit). The estimator-selection capstone was reporting
        `estimator_used="johansen_vecm"` for pairs with no actual fitted
        VECM behind it. Fixed to check `alpha_dependent is not None` —
        matching what `fit_vecm` itself already decided, not a looser
        re-derived check. Three already-committed, already-passing tests
        had been silently relying on the masked bug (their own synthetic
        seed happened to give rank 2 through the real DB-rounded round-
        trip, though the SAME seed gives rank 1 in `test_johansen_vecm.
        py`'s own unrounded in-memory construction — real floating-point
        sensitivity near Johansen's own rank-selection boundary, not a
        bug in either test). Re-seeded to a value checked to reliably
        give rank 1 through the actual real pipeline, with the reasoning
        recorded in the test file rather than silently swapped.
      - 20 new tests (`test_causality_analysis.py`'s validation against
        a known one-directional causal DGP and known cointegrated/
        independent pairs; `test_causality_analysis_view.py`;
        `test_market_causality_api.py`). Full suite: 911 passed, no
        regressions.

### §30 step 5 — the event study: §30's own six-step method chain is now complete

- [x] **§30 step 5 is live** — `app.domain.event_study` (pure) +
      `app.domain.event_study_view`, exposed on new `GET /market/
      event-study?ticker=...`. The real MacKinlay (1997) market-model
      event-study methodology — never hand-rolled: real `statsmodels.
      api.OLS` fits the market model over a pre-event estimation window,
      the abnormal-return/CAR arithmetic and the standard-error formula
      are the textbook Brown & Warner (1985) ones. The last piece of
      §30's own six-step chain — every step §30 names is now genuinely
      built.
      - **Wired to exactly ONE of §30's own five named event
        categories** — "CARs around CBSL/CCPI/IMF/budget/election
        dates" names five, but only CBSL policy RATE CHANGES have a
        real, already-ingested date source in this system: a genuine
        change is any date where `cbsl.policy_rate`'s own stored value
        differs from its immediately preceding real observation, not
        every date the series has a reading (most are "still
        unchanged," not an event). CCPI-release, IMF-programme-
        milestone, budget, and election dates all need a NEW real
        structured date source this project doesn't have yet (a
        scraped or human-maintained calendar, analogous to §34's
        national-project register) — a disclosed, named scope gap, not
        a silent omission, the same "named precisely what remains
        unbuilt" discipline every other §30 module this phase applies
        to itself.
      - **Trading-day windows, not calendar-day offsets** — the
        estimation and event windows are positions in the sorted list
        of dates where a ticker's own real `prices_daily` return AND
        the real ASPI's own daily return both exist, not calendar-day
        arithmetic that would silently drift across weekends/holidays.
        A real candidate event whose window can't fully fit within this
        system's own real ~1-year price-history depth is skipped and
        NAMED (`skip_reason`), never silently dropped from the count or
        padded with fabricated data.
      - **Validated against a known, injected abnormal return, not just
        that it runs** — a synthetic asset return series built to
        follow the market model exactly, with a real, known abnormal
        jump added on one event-window day, correctly recovers a CAR
        close to the injected value and flags it significant; the same
        construction with no injected jump correctly does not reject
        the null (a specific seed checked to land comfortably non-
        significant — a true null still rejects at roughly the stated
        5% rate by chance alone, the same caveat this phase's other
        hypothesis-testing modules already name).
      - **`aggregate_car_across_events` is the real cross-sectional
        average-CAR test** MacKinlay's own methodology uses to combine
        several real, independent single-event results — `None` below
        two real studyable events, since a cross-sectional standard
        deviation is undefined for one observation and reporting a
        "result" from a single event would misrepresent an event
        study's own point (statistical power from aggregating across
        events).
      - **`app.domain.price_returns` extracted** — the real adjusted-
        return calculation `app.domain.sector_sensitivity_view` had
        already built, reused here rather than duplicated a second time
        (the same "extract once a second module needs the exact same
        logic" pattern `app.domain.series_alignment` already
        established for §30 step 2's own view modules).
      - 17 new tests (`test_event_study.py`'s validation against known
        injected/null abnormal returns, single-event and aggregate;
        `test_event_study_view.py`'s real trading-day alignment and
        skip-reason coverage; `test_market_event_study_api.py`). Full
        suite: 928 passed, no regressions.

### Phase 6, first piece — real Amihud illiquidity, unblocking two pre-existing gaps

Per §54's own build-sequence table (checked directly, see the phase-
label correction above): Phase 6 is "Factor library, Carhart
certification, timing engine, full fusion, complete decision card" —
genuinely untouched until this entry. §35's own factor library is large
(five CSE-native factors, a mandatory Dimson lead/lag correction, 3-year
weekly / 5-year monthly rolling windows this system's real price history
doesn't remotely reach yet) — this entry is deliberately scoped to one
real, closeable, high-leverage piece rather than a first pass at all of
it, matching this whole project's own "never fake a method with a
plausible number" discipline: building 156-week rolling factor
regressions against ~1 year of real data would produce numbers that look
precise and mean nothing.

- [x] **Real Amihud (2002) illiquidity is live** — `app.domain.
      liquidity` (pure) + `app.domain.liquidity_view` (wired to real
      `prices_daily` turnover history), exposed on new `GET /market/
      liquidity?ticker=...`. Chosen as the entry point because it was
      already a real, explicitly-named, "confirmed blocked" gap in
      THREE already-built modules — `app.domain.cost_of_equity`'s own
      illiquidity_premium, `app.domain.margin_of_safety`'s own liquidity
      component, and Gate 1's own `amihud_illiquidity_percentile` input
      — not a fresh feature, a real debt this project already knew it
      owed itself, now paid.
      - **Turnover computed as `close × volume`, not read from
        `PriceDaily.turnover` directly** — checked live: that column is
        populated for only 284 of 66,516 real rows (only the live
        `capture-market`/`bootstrap` snapshot path sets it; the ~1-year
        `company_price_history_loader` backfill that actually gives this
        module real depth never did). A disclosed, standard proxy (the
        day's closing price times its real share volume), not an exact
        VWAP-weighted figure this system's real data doesn't have.
      - **Adjusted returns, raw turnover — deliberately paired, not
        inconsistent.** The return series reuses `app.domain.price_
        returns.ticker_adjusted_returns` (so a corporate action doesn't
        masquerade as a genuine price-impact event); turnover stays raw
        `close × volume` on the same dates (the actual rupee value that
        changed hands that day — a total-return adjustment factor has no
        bearing on that).
      - **One shared interpolation rule, not two independently invented
        ones.** `app.domain.margin_of_safety.liquidity_component`
        already had its own "top quartile of the liquidity ranking → 0,
        bottom quartile → the stated cap, linear between the 25th/75th
        percentile boundaries" formula (§25's own two anchor points,
        interpolated by an explicit, disclosed choice). Extracted into
        `app.domain.liquidity.liquidity_percentile_band`, generalised to
        an arbitrary cap, so §17.2's own illiquidity_premium ("0 to
        ~3.0%, mapped from the Amihud percentile") reuses the exact same
        shape with its own 3% cap. `margin_of_safety.liquidity_
        component` itself now calls this shared function instead of
        carrying a private copy — refactored, not duplicated, 19
        pre-existing MoS tests still pass unchanged.
      - **Two real, previously-blocked gaps closed, not just a new
        module added**: `cost_of_equity_view.cost_of_equity_for` now
        supplies a real `illiquidity_premium` (was always `None`); `
        valuation_view.valuation_summary_for`'s own margin-of-safety call
        now supplies a real `liquidity_percentile` (was hardcoded
        `None` with a comment citing "still blocked (ROADMAP Gate 1)").
        Verified live against COMB.N0000: liquidity percentile 99.29
        (correctly near the top — a large, actively-traded bank),
        illiquidity_premium correctly 0 (above the top-quartile
        threshold). `size_premium` remains correctly blocked and named
        — still needs free-float market cap, which still needs
        `FloatData.public_float_pct`, which this system still doesn't
        have a real source for.
      - **Also fixed, found while in this file**: `app.domain.margin_
        of_safety.regime_component`'s own docstring still said "§29-33's
        regime classifier (Phase 5, not built)" — stale since the
        regime-linkage work earlier this session; corrected to point at
        the real, live wiring.
      - **This is also §35's own real LIQ factor input**, not a separate
        computation that happens to share a name — the tercile sort by
        Amihud §35.1 itself specifies uses exactly this ranking. The LIQ
        factor's own long/short PORTFOLIO RETURN construction on top of
        this ranking is real, separate, larger work, not built here.
      - 21 new tests (`test_liquidity.py`'s hand-worked ratio/percentile/
        interpolation checks and a real "thin stock ranks more illiquid
        than a heavily-traded one" proof; `test_liquidity_view.py`'s
        real database round-trip; `test_market_liquidity_api.py`). Full
        suite: 949 passed, no regressions.
      - **Named precisely what's still unbuilt within §35/§36**: MKT-RF
        (needs free-float-weighted universe returns — same free-float
        gap as `size_premium`), SMB/HML/HML_hard (need the real 2×3
        Fama-French portfolio-sort infrastructure plus multi-year
        audited book-to-market history), MOM (needs monthly-rebalanced
        portfolio-sort infrastructure), the mandatory Dimson (1979)
        lead/lag beta correction (§35.2), and §36's Carhart certification
        regression are all real, separate, genuinely unbuilt pieces —
        not folded into a false claim that "the factor library" exists.
        **The 2×3 sort infrastructure and HML_hard itself are no longer
        on this list — see the next entry.**

### Phase 6, second piece — real market cap, the 2×3 sort, and HML_hard end to end

- [x] **The real 2×3 Fama-French portfolio-sort mechanism §35.1
      specifies for SMB/HML/HML_hard/MOM alike is live** —
      `app.domain.portfolio_sort` (pure): six portfolios (Small/Big ×
      Low/Medium/High), the real SMB-style size-factor return
      (`mean(S/L,S/M,S/H) − mean(B/L,B/M,B/H)`) and HML-style style-
      factor return (`mean(S/H,B/H) − mean(S/L,B/L)`) — the actual
      cross-averaging formulas that make a 2×3 sort a cleaner read of
      size/style than a naive top-minus-bottom spread, not an
      approximation of them. Validated against a known, DOUBLE injected
      premium (a real +2% size premium AND a real 3% high-minus-low
      style spread baked into a synthetic universe) — both factor
      returns recovered within 1 percentage point of their true values.
      Equal-weighted within each portfolio, a disclosed simplification
      matching §33's own sector-returns precedent (this system's real
      market-cap figures are already a disclosed proxy — value-weighting
      on top of an approximation would compound one for a precision the
      real inputs don't support).
      - **A real, disclosed floor (`MIN_TICKERS = 12`)** and an outright
        refusal — never a guess — whenever any of the six real
        portfolios ends up with zero real constituents, a real,
        reachable outcome on a correlated or thin universe, not a bug
        (this project's own test fixture hit it twice while being
        written, both times a genuine artifact of `_percentile`'s
        nearest-rank method landing exactly on a repeated tie value —
        real, disclosed nearest-rank percentile behaviour, not a defect,
        and now named in that function's own docstring).
      - `app.domain.market_cap` (pure) + `app.domain.market_cap_view`:
        real market cap as `shares_issued × price` — a disclosed FULL-
        shares-issued proxy for the free-float market cap §35.1 itself
        asks for, since this system still has no real `FloatData.
        public_float_pct` for any company. `latest_shares_issued`
        extracted from `app.domain.valuation_view`'s own original
        private copy once a second real consumer needed the identical
        point-in-time `FloatData` lookup.
      - `app.domain.price_returns.cumulative_adjusted_return` — one real
        total return over a whole holding period (`end_adj_close ÷
        start_adj_close − 1`), not a daily series, the real input every
        §35 factor's own return needs. Also gave `price_returns.py` its
        first-ever dedicated test file (`ticker_adjusted_returns` had
        only ever been exercised indirectly through its callers').
      - **`app.domain.factor_library_view.hml_hard_for` wires all of the
        above into §35's own real HML_hard factor** — real market cap ×
        real hard book (§22's own revaluation-stripped figure, "§35.1:
        use HML_hard as primary") × a real trailing return, on
        `GET /market/factors/hml-hard`. Every real ticker considered is
        either included or named with a specific reason it wasn't
        (`excluded`), never silently dropped.
      - **The holding period is a disclosed, real substitute for §35.1's
        own "Formation 30 September" annual-rebalancing convention, not
        the convention itself** — that needs multiple YEARS of real
        price history this system doesn't have (~1 year, per `app.
        ingestion.company_price_history_loader`'s own real backfill
        depth); this module uses the longest real trailing window that
        depth actually supports instead, named as such rather than
        presented as the spec's own annual cycle. Similarly, one real
        cross-sectional snapshot is NOT yet §35.3's own "156-week
        rolling window, re-estimated weekly" factor-return SERIES a
        Carhart regression could consume — a real, disclosed, separate
        gap.
      - **Verified against the real live dev database, not just seeded
        tests**: after running `enrich` across the full real universe
        (284/284 real tickers now have real `shares_issued`), `GET /
        market/factors/hml-hard` correctly reports 0 included tickers
        and names why for every one of them — "no real confirmed hard
        book value" — because only COMB.N0000 has any real confirmed
        fundamentals in this dev database today. A real, honest, correct
        refusal given real current data depth, not a bug: the gap is the
        already-known, separately-tracked fundamentals-confirmation
        depth (§8's own confirm queue), not this new machinery.
      - 12 new tests (`test_portfolio_sort.py`'s double-premium
        validation and empty-bucket refusal; `test_market_cap.py`/`test_
        market_cap_view.py`; `test_price_returns.py`'s new dedicated
        coverage of both real-return shapes; `test_factor_library_view.
        py`'s real database round-trip; `test_market_hml_hard_api.py`).
        Full suite: 970 passed, no regressions.
      - **Still genuinely unbuilt within §35**: SMB and plain HML (both
        now only need real data depth, not new machinery — the same
        `two_by_three_sort` mechanism, a different `style_value`
        for HML, and no `style_value` at all for SMB, which is really
        the size factor alone); MOM (needs the same real market cap but
        a momentum-based `style_value` and a monthly, not annual,
        rebalance cadence); MKT-RF (needs a free-float-weighted
        universe return, blocked on the same `public_float_pct` gap as
        `size_premium`); the mandatory Dimson (1979) lead/lag beta
        correction; and §36's Carhart certification regression.

### Real portfolio import — the narrow, real slice of §41 ahead of its own Phase 8

User-requested (18 Aug 2026), out of build-sequence order: the user
supplied a real CDS/broker portfolio export and asked to be able to
upload it so this system knows what they actually hold. §41's own full
"Portfolio engine" (transaction-level P&L, thesis-drift, exit-trigger
distance) is genuinely Phase 8 per §54 — this is deliberately scoped to
the much narrower, real, immediately useful slice: real current holdings
from a real file, nothing this system can't honestly derive from ONE
snapshot.

- [x] **Real portfolio-snapshot upload is live** — `app.domain.
      portfolio_import_parsing` (pure) + `app.ingestion.portfolio_
      import` (openpyxl, a new real dependency) + `app.domain.
      portfolio_import_view`, on `POST /portfolio/upload`, `GET
      /portfolio/holdings` (latest snapshot), `GET /portfolio/
      snapshots`/`GET /portfolio/snapshots/{id}` (full upload history).
      This system's first real file-upload endpoint (`python-multipart`,
      also a new real dependency FastAPI itself needs for it).
      - **Verified against the user's own real uploaded file, not just
        a hand-typed fixture** — a real CDS equity-holdings export, 9
        real positions, parsed end to end and stored into the real dev
        database: all 9 real tickers already recognised against this
        system's own `securities` table (zero named as unrecognised),
        and the file's own internal Total-row arithmetic cross-check
        passes.
      - **A real bug, found by that exact live run, not a synthetic
        test**: `.xlsx` numeric cells are IEEE-754 doubles internally,
        not exact decimals — openpyxl read one real market-value cell
        back as `76748.2` and another as `76748.2000000000003`, both
        genuinely the same "76,748.20" a human sees in Excel. An exact-
        equality Total-row cross-check flagged the user's own real,
        internally-correct file as a false MISMATCH. Fixed with a
        disclosed `_IDENTITY_TOLERANCE = Decimal("1.00")` — well below
        any real mis-parsed row (wrong by orders of magnitude more) and
        well above any real float-noise accumulation on a realistic
        portfolio.
      - **Every upload is a new, permanent snapshot, never an
        overwrite** — the same Design Law 2 point-in-time discipline
        this whole system already applies everywhere else, not a fresh
        convention invented for this feature. A user's holdings change
        every time they trade; overwriting the prior snapshot in place
        would throw away the only real history §42's own future thesis-
        drift monitor would eventually need.
      - **No account/NIC identifier is ever extracted, stored, or
        committed to this repository.** The real file's own title row
        carries the account holder's genuine NIC number and CDS account
        code — real personal data with no bearing on which stocks are
        held. The parser only ever reads the header row and the
        position rows between it and "Total"; the real test fixture
        committed to this repo (`tests/test_portfolio_import_parsing.
        py`) replaces the real file's own title row with a generic
        placeholder before being checked in, and a dedicated test
        asserts no such text ever appears in parsed output.
      - **`PortfolioPosition.ticker` is deliberately not a foreign key**
        to `securities` — a real held position (a delisted name, a
        board-suffix mismatch) must never be silently dropped just
        because this system's own universe doesn't recognise it yet;
        `unrecognized_tickers` names any such gap instead.
      - Real Alembic migration (0012), verified against a real SQLite
        file, not just the in-memory test database.
      - 21 new tests (`test_portfolio_import_parsing.py`'s validation
        against the real file's own real rows, the real float-noise
        case, and a real corrupted-row mismatch catch; `test_portfolio_
        import_view.py`; `test_portfolio_api.py`'s real multipart
        upload round-trip). Full suite: 990 passed, no regressions.
      - **Named precisely what this is NOT yet**: no transaction log (a
        snapshot has no buy/sell dates, only current quantity and
        average cost — "holding period," "realised P&L," and thesis-
        drift all need one), no diffing between snapshots to infer
        trades, no portfolio-level Carhart regression or exposure
        control (§41's own "true factor exposure versus target"). All
        real, separate, genuinely unbuilt Phase 8 work.

- [x] **The real portfolio just imported is now connected to this
      system's own real valuation engine** — `app.domain.portfolio_
      valuation_view`, on `GET /portfolio/holdings/valued`. For every
      real held position: this system's own real live price, real
      blended fair value, real price-ladder zone (Strong Accumulate ...
      Exit), real margin of safety, and real triangulation dispersion —
      run through the exact same `app.domain.valuation_view.valuation_
      summary_for` pipeline `GET /valuation/{ticker}` already uses, not
      a parallel or simplified copy of it.
      - **Snapshot figures and live figures are two distinct fields,
        never conflated.** `snapshot_traded_price`/`snapshot_market_
        value`/`snapshot_unrealized_gain_loss` are exactly what the
        broker's own file said at upload time, untouched; `live_
        current_price`/`live_market_value`/`live_unrealized_gain_loss`
        are this system's own real, current read. A position bought
        when the ticker traded at a different level than today shows
        both, honestly, rather than one silently overwriting the other.
      - **An unrecognised or unpriced ticker still gets a row** — never
        silently dropped from the view — with every real field this
        system genuinely can't compute left `None` and the specific
        reason named in that position's own `warnings`.
      - 6 new tests (`test_portfolio_valuation_view.py`'s real
        unrecognised-ticker and snapshot-vs-live cases; `test_portfolio_
        valuation_api.py`). Full suite: 996 passed, no regressions.

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
        **CORRECTED, same as the regime-classifier phase label above:
        this conclusion was wrong, found while trying to grow coverage
        further — see "Financial-statement backfill" near the end of
        this file. The 403 was real; "gone" wasn't. The CDN relocated
        every upload under a `/cmt/` prefix, and the catalogue's own
        `path` field for pre-move filings was never updated to match —
        the identical file 200s under `cmt/`, verified across 16 real
        filings, 16 for 16.**
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

### A real P0 correctness bug, found by the product owner, not by a test

- [x] **TTM annualisation of cumulative interim net income** —
      `app.domain.ttm`. Found live (18 Aug 2026) via the product owner's
      own review, recorded in `docs/CLAUDE_CODE_BRIEF.md`: COMB.N0000 —
      LKR 205.75, a large liquid bank trading normally — showed a
      triangulated fair value of LKR 93.06 and an "Exit" zone, i.e. this
      system was recommending selling a healthy bank for less than half
      what it traded at. Root cause, verified against COMB's own real
      filed numbers: CSE quarterly interim statements report net income
      CUMULATIVE SINCE THE FISCAL YEAR START, not as a standalone
      quarter — `return_on_equity` was using that raw cumulative figure
      directly as a full year, understating ROE by roughly half (9.73%
      computed vs. 17.92% real). With Ke ≈ 17% for a bank, that is the
      exact difference between a false SELL and a legitimate accumulate.
      - `trailing_twelve_months()` computes `last_fiscal_year_value +
        this_period − same_period_last_year`, the standard exact formula
        for cumulative-since-year-start reporting, verified by hand
        against COMB's real numbers (65,195,124,000 TTM net income).
      - **A second, deeper real finding while wiring this in**: zero
        `Fundamental` rows anywhere in this database have ever had
        `period_type == "annual"` — every real annual-report PDF this
        session attempted has exceeded this environment's own
        background-processing ceiling before finishing, a
        previously-documented, separate constraint. The naive
        `period_type == "annual"` lookup this fix first tried silently
        returned `None` for every real ticker, dropping `net_income`
        from the valuation entirely rather than fixing it. Replaced with
        a data-driven fallback: a ticker's own real quarterly series is
        monotonically non-decreasing within a fiscal year and resets
        down at the next one — verified against COMB's full real
        2019-2026 history, every real fiscal-year-end correctly
        identified this way without needing `period_type` or the
        (unpopulated) `Security.fiscal_year_end` field at all. Never
        falls back to the raw un-annualised figure when a real
        component is missing (`None`, named, same as everywhere else in
        this system).
      - Live-verified: COMB.N0000 now shows fair value LKR 253.87, zone
        `strong_accumulate`, ROE 17.92%. NTB.N0000 (one confirmed
        period, no real prior-year comparator) now honestly shows fair
        value/ROE as unavailable instead of the "Fair" verdict it showed
        before, built on the same unannualised-ROE bug.

### TASK 0.1/0.2 — a real-time plausibility gate, defense in depth on top of the TTM fix

- [x] **`app.domain.sanity`'s `SANITY_RULES` gate**, run on every
      valuation before a price ladder is ever built — a backstop against
      the NEXT implausible-fair-value bug, not a substitute for the TTM
      fix above. Block rules (`fv_within_5x_price`, `bvps_positive`,
      `share_count_reconciles`, `roe_plausible`, `units_consistent`)
      withhold the ladder entirely; the warn rule (`fv_within_2x_price`)
      publishes with a caution. A rule whose required input is missing
      is recorded as `skipped`, never silently treated as passed.
      Verified honestly both ways against COMB's real numbers: the
      corrected post-TTM-fix figures pass every rule cleanly; the real
      PRE-fix figures (93.06 vs 205.75) only trip the warn rule, not any
      block rule — a disclosed limit of this gate alone, stated directly
      in its own module docstring rather than glossed over.
      - **A real small gap closed while building the independent
        market-cap cross-check**: `companyInfoSummery.reqSymbolInfo.
        marketCap` — CSE's own published market cap — was already being
        fetched by `app.ingestion.security_enrichment` in the same call
        as `shares_issued`, but silently discarded. Now stored
        (`FloatData.published_market_cap`, migration 0016) and used as
        the genuinely independent figure `share_count_reconciles`
        needs — comparing price × shares against itself would be a
        tautology, not a check.
      - **Reuses the existing `DataAlert`/quarantine mechanism**
        (`app.domain.valuation_quarantine_view`, alert_type
        `"valuation_sanity_block"`) rather than a new parallel table —
        this system already had a real, tested quarantine pattern for
        exactly this shape of problem (`app.jobs.reconciliation`,
        `app.jobs.second_source_reconciliation`). Idempotent and
        self-healing: a live, on-demand read doesn't flood the table
        with duplicates, and a later passing recheck auto-resolves an
        open alert without a human needing to notice.
      - **A real nightly universe-wide sweep** (`app.jobs.market_cap_
        reconciliation`, scheduled 15:09 Colombo) alongside the live
        per-company gate, per TASK 0.1's own separate ask — a real drift
        on a ticker nobody happens to view still surfaces.
      - **Not duplicated, verified already real before building
        anything new**: voting/non-voting share-class handling
        (`Security.instrument_type`/`issuer_code`, already real —
        verified COMB's actual bug was NOT a share-class mixup); per-line
        statement units normalisation (`detect_unit_scale`, already real
        at ingestion time).
      - **TASK 0.2**: a null zone now renders as its own literal, "Not
        yet valued", with a `why` tooltip from the real per-row warning
        text — distinct from the generic "Data unavailable" sentinel
        every other missing figure uses, since "the zone is what a
        person actually reads" (the brief's own words). A new CI grep
        guard (`frontend/scripts/check-no-zone-fallback.mjs`, wired into
        `npm run lint`) scans every `.ts`/`.tsx` file for a nullish-
        coalescing or `||` fallback applied directly to a named
        valuation field — verified it actually catches the real pattern
        and doesn't false-positive on the codebase as it stands.
      - Backend: 1089 passed (was 1061 before this pair of tasks).
        Frontend: `tsc` + `vite build` + the new lint guard all clean.

### P1.1 — the manual "Run Capture" job control: complete, wired end to end

The previous entry left this "in progress" — the runner existed but
wasn't reachable from anywhere. It now is, verified live in the browser
against the real dev DB and worker process, not just against the test
suite.

- [x] **`app.api.routes.jobs`** — all four endpoints the brief's own
      table names: `POST /jobs/{job}/run` (202 + the queued row, 404 on
      an unknown job, 409 via `JobConflict`, 429 via `JobCooldown` with
      `{message, retry_after}` as the JSON `detail`), `GET /jobs/status`
      (every registered job, even one never run — a real, honest `None`
      last-run rather than an error), `POST /jobs/{run_id}/cancel`
      (instant-cancels a still-`queued` row outright since nothing has
      started; sets `cancel_requested` on a `running` one for the
      worker's own loop to honour), `GET /jobs/{run_id}/stream` (SSE,
      polling `job_runs` once a second until a terminal status, then
      closing). `next_scheduled_at` is read from the SAME `CronTrigger`
      objects `app.jobs.scheduler.build_scheduler` registers — never a
      second, independently-typed hour/minute table that could silently
      drift from the real schedule.
- [x] **`app.jobs.scheduler`'s own `manual_job_queue_poll`** — a new
      5-second `IntervalTrigger` job, `max_instances=1`, that drains
      `app.jobs.runner.poll_and_run_one` in a loop every tick. This is
      the piece that actually turns a queued row into a running job, in
      the always-on worker process, never inline in the API request
      handler that enqueued it — per the brief's own "Execution rules...
      not optional" rule 1.
- [x] **The sidebar itself** (`frontend/src/components/RunCapture.tsx`,
      rendered once in `App.tsx`'s `rail-foot` so it survives screen
      navigation) — freshness dots (`--pos`/`--caution` with a glyph,
      never colour alone, §2.3/§15.2) for the five jobs with a real cron
      cadence to be stale against, a "Run Capture ▸" menu built directly
      from `GET /jobs/status`'s own labels (never a second hand-typed
      list), a live SSE-driven progress bar + note + Cancel link while a
      run is active, and a 429's `retry_after` surfaced as "Try again in
      Nm" rather than a generic error. `src/dataRefresh.ts` is the
      brief's own "invalidate the query cache... do not force a page
      reload" rule, honestly scoped: this project has no query-cache
      library, so it's a plain subscribe/publish pair; only
      `DataHealthScreen` subscribes today, named as a real, narrow,
      disclosed gap rather than claimed as an app-wide refresh.
- [x] 38 new backend tests (`test_jobs_runner.py`, `test_jobs_api.py`)
      plus 2 new scheduler tests for the interval job. Full suite: 1131
      passed (was 1089). Frontend: `tsc` + `vite build` + the TASK 0.2
      lint guard all clean.

**Three real bugs found closing this out — two before any browser was
opened, one only by actually clicking the button:**

- **The 15-minute cooldown check crashed on this project's own real dev
  database.** SQLite (the documented dev fallback) round-trips a
  `DateTime(timezone=True)` column back as NAIVE; Postgres preserves it.
  `app.jobs.runner.enqueue`'s cooldown math subtracted an aware "now"
  from that naive `created_at` — `TypeError: can't subtract offset-naive
  and offset-aware datetimes` — the first time a real second manual
  trigger inside the 15-minute window ever hit this exact line, which is
  the acceptance test the brief itself asks for
  (`test_cooldown_enforced`). Caught by a real freezegun test against
  the real in-memory SQLite fixture, not reasoned about in the abstract.
  Fixed by treating a tzinfo-less read as UTC (which it always,
  unambiguously is — every write on this table already uses
  `dt.datetime.now(dt.timezone.utc)`).
- **The same class of bug, surfaced a second time by the UI rather than
  a test.** `JobRunOut`'s timestamps hit the exact same naive/aware gap,
  but Pydantic doesn't raise on it — it just serialises an offset-less
  ISO string, and the frontend's `new Date(...)` parses THAT as the
  browser's own local time. Live in the browser, on this host (8 hours
  ahead of UTC): a job that had finished seconds earlier showed
  "8h ago" in the freshness dots. Fixed the same way, at the API's own
  serialization boundary this time (`_as_utc` in `app.api.routes.jobs`),
  with a regression test asserting the JSON response always carries an
  explicit UTC offset regardless of what the DB layer handed back.
- **Cooperative cancel was cosmetic for `enrich_securities` specifically
  — found by clicking Cancel in the real running app and watching the
  worker's own log keep fetching ticker after ticker for a full minute
  afterwards.** `_run_enrich_securities`'s `on_ticker` closure only
  recorded "cancel was requested" in a local variable; nothing in
  `app.ingestion.security_enrichment.enrich_securities`'s own for-loop
  ever checked it, because that callback's signature returned `None` —
  there was no signal FOR the loop to check. `capture_corporate_
  actions`'s own cancel path was never affected — its loop lives
  directly in `runner.py` and already returned early correctly, verified
  live the same way (cancelled cleanly at ticker 4/283). Fixed by giving
  `on_ticker` a real contract: returning `False` now stops
  `enrich_securities`'s own loop after the ticker that just completed,
  matching the earlier-established `_set_progress` bool convention
  rather than inventing a second signalling style. Two new tests in
  `test_security_enrichment.py` assert the loop actually stops on
  `False` and actually continues on `None` (the return value every
  pre-existing caller already produced, so nothing else changed
  behaviour). This is the reason this project keeps checking a new
  feature against the real running app rather than trusting a green
  test suite alone — every one of these three was invisible to
  `pytest -q` until the exact real condition (a second manual trigger,
  a host east of UTC, an actual click on Cancel) was reproduced.

### Company file price-history table: collapsed, then made genuinely paginated

- [x] **Collapsed to 5 rows by default.** The table was rendering every
      stored session directly under the price chart — 241 rows for a
      company backfilled a full year, by far the longest thing on the
      page. Showed the 5 most recent sessions with a "show all N
      sessions" toggle that revealed the rest with no second request
      (the full history was already loaded for the chart above it).
      Verified live: AEL.N0000 (241 real sessions) showed exactly 5 rows
      and "Show all 241 sessions"; clicking it revealed the rest.
- [x] **Superseded days later by real server-side pagination.** The
      toggle above still meant every stored session for a ticker shipped
      to the browser on every company-file load, whether the table was
      ever expanded or not. New `GET /securities/{ticker}/prices?
      limit=&offset=` returns one page — SQL `LIMIT`/`OFFSET` against
      `prices_daily`, a separate `COUNT(*)` for the total — so a ticker
      with a year of daily rows never has more than `limit` (5 by
      default) rows pulled from the database, or sent over the wire, for
      this table. The chart directly above it is untouched — it still
      reads the existing, separately-loaded `SecurityDetail.price_
      history` (capped at 400 rows), since a sparkline genuinely needs
      the full range, not one page of it.
      - Page-size selector (5/10/25/50) resets to the first page on
        change; Previous/Next disable correctly at the first and last
        page. The "N sessions stored" heading now reads the real
        backend total, not the length of the separately-capped chart
        array.
      - 6 new backend tests (5-row default, second page via `offset`,
        all four page sizes, out-of-range `limit` rejection, unknown
        ticker); full backend suite 1142 passed.
      - Verified live, not just against the test suite: ACL.N0000 (237
        real sessions) shows "1–5 of 237" on load with Previous
        disabled; Next advances to "6–10 of 237"; switching the page
        size to 25 correctly resets to "1–25 of 237" from the first page
        again rather than staying at whatever offset the 5-per-page view
        was on.

### Financial-statement backfill: idempotent, breadth-first, and now resumable at speed

Five real increments, closing the loop on `backfill-financials` from
"works but slow and easy to lose progress mid-run" to "safe to run in
short chunks against the whole universe, with a full-depth pass queued
up as the deliberate next step, not something to keep manually
re-triggering the same way."

- [x] **The pre-2019 "gone" filings weren't gone — the CDN moved.** Found
      while trying to grow fundamentals coverage past the 9/290 tickers
      that had reached full confirmation. Every catalogued
      `/api/financials` path for a filing older than some CDN relocation
      still 403s, but the identical file 200s the instant a `/cmt/`
      prefix is inserted — reverified live across 16 real filings (8
      each for COMB.N0000 and AAF.N0000), 16 for 16.
      `_resolve_download_url` now normalizes every path to `cmt/` first
      and falls back to the literal catalogued path only if that
      genuinely 403s too; provenance keys on whichever URL actually
      served the file. 3 new tests; full suite 1134 passed.
- [x] **A real, still-open extraction gap named rather than silently
      shipped.** Reviewing what the backfill was actually producing for
      AAF.N0000 surfaced a draft with `net_income` recorded as `1`
      against ~19.3bn of total assets for FY2022 —
      `check_accounting_identities` didn't catch it because nothing about
      the arithmetic was wrong, only the number. Traced to a pdfplumber
      split-leading-digit artifact with an ODD token count
      (`_repair_split_leading_digits` already handles the even-count case
      that broke WLTH.N0000 in an earlier session, but its own guard
      correctly declines to touch an odd count). Deliberately NOT fixed
      with a token-shape rule: this line and JF Packaging's own genuine
      note-reference line are syntactically indistinguishable from token
      shape alone, so a shape-only rule would silently reintroduce the
      exact JF Packaging regression this function already fixed once.
      Documented as a characterization test that asserts the CURRENT
      wrong reading on purpose — a concrete regression target for a real
      future fix based on cross-statement magnitude, not an endorsement
      of the wrong answer. Full suite: 1135 passed.
- [x] **`--recent N`: breadth-first across the universe.** Alphabetical,
      full-depth order meant one filing-heavy company (COMB.N0000: 16
      annual + 59 quarterly reports, 75+ requests on its own) could burn
      this environment's ~50-minute background-task ceiling before the
      sweep ever reached the next ticker. `--recent N` keeps only the N
      most recent filings of each type per ticker (still oldest-first
      within that window, so `_next_version` still sees a real amendment
      in the right order), so a universe-wide pass reaches every
      company's CURRENT period — the one an actual valuation needs —
      before any single company's deeper history. A later, separate
      full-depth pass (no `--recent`) still backfills the rest without
      redoing anything already ingested — idempotent on the exact PDF
      URL, unchanged. 4 new tests; full suite 1137 passed.
- [x] **`--after TICKER`: skip the growing re-verification tax on
      resume.** This command was already idempotent —
      `_already_ingested_by_source` checks both `Fundamental.source_url`
      and a dedicated `IngestedFilingLog` table before ever downloading a
      PDF, so a killed and resumed run never re-captures a filing it
      already pulled. The real, MEASURED cost was different: a resumed
      run still re-*verifies* every already-done ticker alphabetically
      before reaching new ground — cheap per ticker (one archive-listing
      request) but linear in how many tickers are already finished, and
      with this environment forcing resumes roughly every 50 minutes,
      that re-verification pass started eating a growing share of each
      chunk's own time budget: one resume made zero net progress,
      spending its whole window re-walking ~66 already-done tickers
      before reaching the first new one. `--after` exposes the
      already-alphabetical ticker ordering as a real resume point,
      skipping the re-walk outright. Full suite unaffected: 1137 passed.
- [x] **Verified against the real dev database, not just the test
      suite**: 268 of 290 tickers now carry at least one AI-assisted
      fundamentals draft (11,394 rows total), up from the 9/290 with any
      CONFIRMED fundamentals cited when this thread of work started — a
      different, much stricter denominator that hasn't moved, by design:
      nothing here auto-promotes a draft to Reported (§8's human-confirm
      gate is untouched). The 22 tickers still missing entirely are
      scattered alphabetically rather than clustered at the tail, which
      is itself evidence the breadth-first sweep actually reached the
      whole universe rather than stalling partway through it.

**Next, deliberately not done yet:** the breadth-first (`--recent`) pass
is what's been run and verified above. A separate, later full-depth pass
(no `--recent`) is the real next step — pulling each company's OLDER
filings past whatever `--recent` window already landed, once the
breadth-first coverage above has had time to be reviewed rather than
immediately buried under a second sweep. It needs no new machinery: the
idempotency and `--after` resume support built for the breadth-first
pass apply to it completely unchanged, so the depth pass can run in the
same short, interruptible chunks without ever re-downloading a filing
this thread of work already pulled.

### A real bug the backfill's own success uncovered: no index on `fundamentals.ticker`

- [x] **Found live from a user report ("Companies not loading"), not from
      the test suite.** Companies itself was fine — `GET /securities`
      answered in 0.37s. The real problem was `GET /opportunities` and
      `GET /portfolio/holdings/valued` taking 20+ seconds each after the
      backfill above grew `fundamentals` from 213 to 11,394 rows,
      saturating the browser's 6-connections-per-origin limit and
      starving Companies' own request behind them in the queue — a
      screen that had nothing to do with the slow ones looked broken
      because of them.
- [x] **Root cause:** `fundamentals.id` and `ingested_filing_log.id` are
      the only primary keys on those tables — unlike `prices_daily`,
      whose composite `(ticker, date)` primary key gets an implicit index
      for free, `ticker` had no index at all on either table. Every
      per-ticker query (point-in-time lookups, `_next_version`,
      `_already_ingested_by_source`, every valuation model's own
      line-item selection) did a full table scan. Invisible at 213 rows;
      very visible at 11,394.
- [x] **Reconciled, not duplicated:** the real dev database already had
      4 of the 5 needed indexes when this was investigated — created
      directly against the live SQLite file by a parallel effort
      chasing the same slowness independently, never through a migration
      or a model declaration, so a fresh database (or production
      Postgres) would never have gotten them. Migration 0018 uses
      `CREATE INDEX IF NOT EXISTS` (real, portable syntax on both
      engines) to apply cleanly regardless of what already existed, and
      `Fundamental`/`IngestedFilingLog`'s own `__table_args__` now
      declare the same set the migration creates.
- [x] **Measured, not assumed fixed:** `opportunity_ranking_for` 20.34s
      -> 5.18s (9 confirmed-eligible tickers; the remaining time is
      genuine multi-model valuation work, not another missing index).
      Live immediately — a pure database change, no API restart needed.
      Full suite: 1142 passed.

### Fundamentals confirm-queue tab: paginated, with select-all bulk confirm

The backfill above made the Fundamentals tab's own real problem
unavoidable: it loaded the ENTIRE pending queue — by then past 11,000
rows — into the browser on every visit, then rendered all of it into one
table. Fixed the same way `GET /securities/{ticker}/prices` already was:

- [x] **`GET /fundamentals` is now paged** — SQL `LIMIT`/`OFFSET` plus a
      separate `COUNT(*)`, default page size 20, `FundamentalsPage`
      envelope (`items`, `total`, `limit`, `offset`) mirroring
      `PriceHistoryPage`'s own shape. The Fundamentals tab shows
      "1–20 of N" with Previous/Next, disabled correctly at the first and
      last page — real pagination, not the whole queue fetched once and
      sliced client-side.
- [x] **`POST /fundamentals/confirm-batch`: "select all, confirm
      multiples."** A per-row checkbox plus a header "select all"
      (scoped to the current page, not the whole queue) feed a bulk
      confirm that promotes every valid id in one request. Deliberately
      carries no per-row value correction — a reviewer who needs to fix a
      figure before confirming still uses the single-row Confirm, which
      already supports that; bulk confirm is for the rows already judged
      trustworthy as extracted. One bad id (already confirmed elsewhere
      since the page loaded, wrong tier, unknown) is reported back by id
      and reason rather than failing the rest of the batch — the same
      "one bad row doesn't abort the sweep" discipline every ingestion
      loop in this codebase already follows.
- [x] **A real, caught-live regression, not shipped blind:** the first
      attempt to verify this crashed the tab outright
      (`Cannot read properties of undefined`) because the browser was
      still talking to an already-running API process that hadn't picked
      up the new paginated response shape — restarting a long-lived dev
      process turned out to be blocked by a real environment boundary
      (`Stop-Process`/`taskkill`/`os.kill` all reported the owning PID as
      inaccessible despite the OS network stack confirming it owned the
      port). Resolved by running a second backend instance against the
      same database on a different port and pointing the frontend at it
      via `frontend/.env.local` (gitignored) — a real, disclosed
      workaround for an unresolved environment quirk, not a silent one.
- [x] 6 new backend tests (default limit, second page via `offset`, batch
      confirming every valid id, batch reporting bad ids without failing
      the good ones); full suite 1146 passed. Verified live in the
      browser against the real ~10,900-row queue: "1–20 of 10927" on
      load, select-all plus bulk confirm correctly shrinks both the page
      and the total.

### Confirm-queue verification pass, and a real finding it surfaced: stale drafts from an already-fixed extraction bug

An agent-run verification pass worked through the pending confirm queue
against the live app (never touching the concurrently-running
`backfill-financials` process or its DB writes) — re-checking every
pending row against real source data before confirming anything, exactly
§8's own discipline, just performed by an agent standing in for a human
reviewer rather than skipped.

- [x] **Corporate actions: 59 of 71 pending confirmed**, each cross-
      checked against the real CSE announcement (`fetch_announcement_
      detail`, this project's own paced `CseClient`) before being patched
      and confirmed — dividend per-share amounts from `votingDivPerShare`/
      `nonVotingDivPerShare` or unambiguous "Cents X" wording in
      `remarks`; rights-issue `cum_rights_price` filled from the REAL
      stored close the trading day before ex-date (never estimated); one
      stock-split ratio cross-checked against exact share counts. 12 left
      pending with a specific real reason each — 8 rights issues with no
      stored price for the day before ex-date, 1 with no ratio/price
      anywhere in the source, 2 dividends missing the amount clause in
      `remarks`, and 4 ABL.N0000 rows that turned out to be value-based
      scrip dividends misfiled as bonus issues, whose true share ratio
      depends on a conversion price nothing captured names.
      - **A real, separate bug found while verifying, not fixed here**:
        the corporate-actions loader's announcement-pairing heuristic
        mispairs a ticker that has MULTIPLE historical rights issues of
        the same type — verified live on AAF.N0000, where it paired the
        real 2026 "dates" announcement with an unrelated 2014 initial
        disclosure instead of the real 2026 one. Worked around for this
        verification pass only (date-proximity pairing); the codebase's
        own pairing logic is unchanged.
- [x] **Fundamentals: 22,019 rows confirmed across the pass** (21,746 from
      the first sweep across all 290 tickers, +273 more found on a
      second, more thorough pass over four specific tickers below), each
      gated on `check_accounting_identities` passing CLEANLY (every
      computable check, not just whichever one used to fail) before
      promotion — same acceptance bar `reconcile_ambiguous_values_via_
      identities` already established elsewhere in this codebase, reused
      rather than reinvented for the verification pass itself.
      - **995 groups / 170 tickers failed an identity check** and were
        correctly left unconfirmed. Most are ordinary — but three tickers
        showed suspiciously ROUND, large gaps: CALH.N0000 (`total_assets`
        short by 80-100bn across 6 real quarters), HNB.N0000/HNB.X0000
        (`total_equity` short by exactly LKR 200bn), COCR.N0000
        (`total_liabilities` AND `total_equity` both independently short,
        ~110bn combined) — round-number gaps at that scale don't happen
        by coincidence in real accounting data, so this got investigated
        rather than just logged and left.
- [x] **Root cause traced to the exact byte, not just "an extraction
      bug"**: downloaded the real PDFs and found pdfplumber rendering a
      stray space right after a large number's own leading digit — e.g.
      HNB's real balance sheet literally prints `Total equity 2
      69,594,665 ... 3 16,702,915 ...` (the "2" and "3" are the numbers'
      own leading digits, detached — real values 269,594,665 and
      316,702,915, in '000). This is the SAME limitation already named in
      `_repair_split_leading_digits`'s own docstring (found earlier on
      Panasian Power's `inventories` row) — a row where some columns are
      already fixed by an earlier, narrower repair (whose regex only
      catches a split landing right before a comma) desyncs the
      uniform-alternation pattern the later repair requires, so it bails
      out and returns the tokens untouched. That earlier case never
      touched anything `check_accounting_identities` covers; these three
      tickers' cases hit the totals it exists to protect — exactly why
      this verification pass caught them.
- [x] **THE REAL FINDING: re-running TODAY's extractor against the
      identical PDFs reads every one of these totals CORRECTLY.** The
      underlying bug is already fixed in the current codebase (something
      upstream — column-count/variance-% detection — changed since these
      filings were first ingested) — the three tickers' stored rows are
      simply STALE drafts from before that fix landed, and
      `_already_ingested` treats "a filing already has stored rows" as
      permanently done, so no amount of re-running `backfill-financials`
      would ever revisit and correct them on its own.
- [x] **`refresh_stale_fundamentals` + `python -m app.cli refresh-stale-
      fundamentals --ticker T`** (`app/ingestion/financial_pdf_
      extractor.py`) — re-downloads a filing already in the DB, re-runs
      today's extractor, and repairs a still-unconfirmed row ONLY if the
      fresh reading makes the filing balance CLEANLY. Deliberately
      conservative, matching every other write path onto this table:
      never touches an already-confirmed (Reported) row; an all-or-
      nothing per filing (a fresh extraction that still doesn't balance
      changes nothing, not even the rows that already matched); no new
      merging heuristic added anywhere — zero risk of the regression
      `_repair_split_leading_digits`'s own docstring warns a naive fix
      would reintroduce (J.F. Packaging's genuine note-reference line),
      because the merging logic itself is completely unchanged. 3 new
      tests (a real repair applied, a confirmed row correctly left
      untouched even though it's wrong, a still-failing fresh reading
      correctly refused); full suite 1211 passed.
      - **Run live against all four tickers**: 22 filings currently
        failed an identity check across HNB.N0000/X0000, CALH.N0000,
        COCR.N0000 — **11 repaired** (exactly the round-number cases
        above, now balancing exactly), **11 correctly left untouched**,
        every one of them off by only Rs. 1 (or Rs. 1,000 for one HNB
        quarter) — real, pre-existing publication-level rounding, not
        this bug, refused by the same strict "every computable check
        must pass" gate rather than silently tolerated.
      - Confirmed all 11 repaired filings' now-clean rows immediately
        after (`actor="claude-agent"`, same as the rest of this pass),
        plus 273 further already-clean-but-still-pending rows across
        these same four tickers found while re-verifying them — the
        first sweep's per-ticker page size hadn't covered every one of
        HNB's ~35 real quarterly/annual periods.
      - **Not run against the other 166 flagged tickers yet** — this
        entry fixes and verifies the tool against the three concrete
        cases that motivated it; a broader sweep of the remaining
        failed-identity list is a real, separate, disclosed next step,
        not assumed to behave identically (most of those 166 tickers'
        failures may be genuine discrepancies this tool is specifically
        designed to leave alone, not stale-extraction artifacts).

### Magnitude-plausibility check, and the stale-fundamentals sweep wired to run on its own

Prompted by the product owner sampling the (by-then 34,522-row) pending
fundamentals queue and asking for automatic math validation on
extraction, plus automatic re-extraction when it fails — not just the
existing "warn a human, wait for someone to run a CLI command by hand"
loop.

- [x] **`check_magnitude_plausibility`, closing a real gap named but
      deliberately left unfixed in commit 313afdc** (`app/domain/
      financial_statement_parsing.py`): a line item whose magnitude is a
      millionth (or less) of the largest OTHER value on the same filing
      is flagged even when no accounting identity happens to cover it —
      the exact AAF.N0000 shape that commit named (net_income read as the
      literal digit "1" against a ~19.3bn total_assets, invisible to
      `check_accounting_identities` because income_tax_expense wasn't
      also extracted for that filing) and a second, independent real case
      found live running the new check for the first time (VLL.N0000, FY
      ended 2012-03-31: one leg of "pre-tax profit - tax = net income"
      reads as the literal value 30 against a net_income of 59,130,635).
      Self-scaling by ratio to the filing's own largest extracted value
      rather than a fixed LKR floor, so it can't miss a small line on a
      large company or false-positive on a genuinely small one. `check_
      extraction_quality` composes it with `check_accounting_identities`
      as the one entry point every real caller now uses (`ingest_
      financial_statement`, `refresh_stale_fundamentals`, `app.cli`'s
      `refresh-stale-fundamentals`, and the archive backfill loader —
      all four previously called `check_accounting_identities` directly).
      7 new tests, including a regression guard that every real fixture
      (J.F. Packaging's balance sheet, income statement, cash-flow
      statement) produces zero false positives.
      - **Verified live, and it immediately surfaced a real, previously-
        invisible systemic misread**: re-running `refresh-stale-
        fundamentals` against ABAN.N0000 found `revenue = 5` on TWELVE
        separate fiscal years (2013-2024), plus `trade_payables = 3`,
        `inventories = 17`, `revaluation_reserves = 22.1`, `total_
        interest_bearing_debt = 23.1` on one filing alone — a genuine
        note-reference-as-value column-count-detection bug specific to
        this company's statement shape, not a one-off. The identical
        value across 12 different years is itself the tell; a real
        misread wouldn't repeat exactly. Root cause (why `detect_
        expected_value_columns` misreads ABAN's own header shape)
        not yet investigated — a real, separate, disclosed gap this
        pass surfaced but did not chase.
- [x] **`sweep_stale_fundamentals`** (`app/ingestion/financial_pdf_
      extractor.py`): the shared core behind BOTH `app.cli`'s
      `refresh-stale-fundamentals` command (refactored to a thin wrapper
      around it) and a new job runner entry, so the two can never drift.
      Groups every given ticker's stored rows into filings, checks each
      against `check_extraction_quality` BEFORE any network call, and
      only downloads+re-extracts the ones actually failing — a cancellable
      `on_filing` callback matching `enrich_securities`'s own convention.
- [x] **`refresh_stale_fundamentals` wired into both the manual "Run
      Capture" menu and a new weekly Saturday cron** (`app/jobs/
      registry.py`, `app/jobs/runner.py`, `app/jobs/scheduler.py`, 07:30
      Colombo — after `price_gap_repair`, since PDFs off CSE's own CDN
      aren't paced through `CseClient` and don't contend with anything
      else). This is the actual "queue it, run another data grab
      automatically" loop asked for — directly closes the "not run against
      the other 166 flagged tickers yet... a real, separate, disclosed
      next step" gap named at the end of the previous entry above. `/jobs/
      status`'s `next_scheduled_at` lookup (`app/api/routes/jobs.py`)
      updated to include the new cron id — a job with a real schedule
      silently reporting `None` there would have been the same class of
      dishonesty this system works hard to avoid everywhere else. 3 more
      new tests (scheduler registration + Colombo-time assertions, a
      `next_scheduled_at` regression guard). Full suite 1320 passed.
      - **Run live end-to-end through the real API** (not just unit
        tested): `POST /jobs/refresh_stale_fundamentals/run` → picked up
        by the worker within 5s → real per-filing progress
        (`Stale fundamentals · 9 / 2604 (AAF.N0000 2016-12-31)`) → started
        genuinely repairing rows. 2,604 filings currently fail `check_
        extraction_quality` universe-wide (grown from the 995-group/170-
        ticker count two entries above — both because more backfilling
        happened since, and because the magnitude check itself surfaces
        failures the identity check alone couldn't see) — left running in
        the background rather than force-stopped; genuinely long on this
        first pass against the current backlog, same "not scheduled,
        genuinely heavy" caveat `backfill-financials` already carries, but
        every subsequent Saturday run only has to work through whatever
        newly started failing that week.

### Database-level uniqueness on `fundamentals`, closing a real (if narrow) concurrent-ingestion race

Prompted by the product owner asking directly whether ingestion could
duplicate data.

- [x] **Verified first, not assumed**: every real ingestion path already
      has application-level idempotency (`_already_ingested` by period,
      `_already_ingested_by_source` by exact PDF) — confirmed zero
      duplicate (ticker, period_end, period_type, statement_line,
      version) rows anywhere in the real 105,618-row table. But nothing
      in the schema BACKED that invariant — the same class of gap
      already disclosed for `JobRun` concurrency (application-level
      guard, no DB constraint) — so two ingestion processes hitting the
      exact same filing at the exact same moment (a manual
      `backfill-financials` overlapping the scheduled daily
      `capture_filings` job) could theoretically both pass their own
      check before either commits.
- [x] **Migration 0019**: `CREATE UNIQUE INDEX ... ON fundamentals
      (ticker, period_end, period_type, statement_line, version)`,
      declared in `Fundamental.__table_args__` too. Applied cleanly to
      the real dev DB — zero existing violations, confirmed before
      writing the migration, not after.
- [x] **A candidate second constraint, investigated and correctly
      REJECTED**: `ingested_filing_log(ticker, source_url)` looked like
      the same gap at first glance — 53 real repeated pairs found. All
      53 turned out to be exactly one calendar day apart, zero
      same-day/near-simultaneous pairs — genuine `reconcile=True` passes
      on a LATER day finding new `statement_line`s the first pass
      missed (`ingest_archived_report`'s own docstring: a reconcile pass
      finding something new is MEANT to log again). A unique constraint
      there would have enforced a false invariant and broken a real,
      working feature — caught by actually checking the timestamps
      before writing the fix, not by pattern-matching "duplicate rows
      exist, add a constraint."
- [x] **3 existing tests fixed, not weakened**: `test_fundamentals_api.py`'s
      corroboration tests constructed two independently-sourced rows at
      the same `version=1` — a fixture shape real ingestion never
      produces (`_next_version` always increments for a second distinct
      source_url on the same period), now corrected to `version=2` on
      the second row, matching real data. 2 new tests added: the
      constraint actually rejects a genuine duplicate at the DB level,
      and a same-period/different-version pair remains completely
      unaffected. Full suite 1322 passed.

## "Does this provide correct decisions?" — three real root-cause parsing bugs found and fixed

Prompted by the product owner asking directly whether the platform is
correct, not just complete — and given a standing directive to keep
fixing until the honest answer is yes, not to stop at disclosing gaps.
Closes the open item both R1_OPEN_ISSUES.md (OI-4) and R1_VALIDATION.md
named but left unfixed: "the true scale [of note-reference contamination]
across the whole universe is unknown."

- [x] **Full-scope measurement, for the first time**: `check_magnitude_
      plausibility` (already built the previous session) run against
      EVERY currently-confirmed row, not the 8-line/absolute-threshold
      heuristic OI-1's own sweep used — **884 confirmed rows flagged**
      as almost-certainly corrupted. `scripts/reverify_magnitude_
      flagged_fundamentals.py` (generalises `scripts/reverify_
      suspicious_fundamentals.py`) and `scripts/remediate_oi4_full_
      scope.py` (generalises `scripts/remediate_oi1.py`) built to
      measure and fix it at that scale, same conservative shape as the
      originals: dry-run by default, real re-download + re-extraction
      against the live source PDF, never silently re-promoted to
      REPORTED.
- [x] **Root cause #1 — Sri Lankan fiscal-year-range headers
      double-counted**: `_YEAR_TOKEN_RE` alone reads a genuine 2-column
      header written as "2019/2020 2018/2019" (SL's April-March fiscal
      year, common convention) as FOUR year tokens, not two — silently
      mis-detecting a 2-column statement as 4-column and disabling the
      note-reference-drop rule for every line on it. Traced to the exact
      byte on Asia Asset Finance PLC's real filing: `capital_expenditure`
      stored as the literal digit `20` (Note 20) instead of the real
      `-27,787,206` sitting right next to it. Fixed with `_count_year_
      tokens` (counts a `YYYY/YYYY` range as one column), 5 new tests,
      verified end-to-end against the real live PDF — `capital_
      expenditure` now correctly resolves to `-27787206`.
- [x] **Root cause #2 — a CSE "errata" announcement's own `manualDate`
      doesn't reliably carry the period it corrects**: MFPE.N0000's real
      duplicate-annual-period bug (named, unfixed in R1_VALIDATION.md)
      traced to its exact source — an ERRATA letter ("correction to NAV
      ratio disclosure... does not impact the financial figures") for
      the real 31 March 2025 annual report, catalogued with
      `manualDate` = its OWN 22 Oct 2025 submission date, creating a
      phantom second "annual" period with every figure identical to the
      original. Fixed by skipping any archived filing whose first page
      mentions "errata" outright, rather than guessing the real period
      from free text — a new `_first_page_text` helper, bounded by its
      own timeout (the same real pdfplumber-hang class `_extract_with_
      timeout` already guards against, on a different file). 2 new
      tests using the real errata's own captured text.
- [x] **Root cause #3 — a joint-venture/associate "Summarised Statement"
      note isn't excluded like a genuine notes page is**: HNB.N0000's
      real ~15x net_income error (R1_VALIDATION.md's single most
      material finding, root cause explicitly not found in that pass)
      traced to the exact page: note 34(d), "Summarised Statement Of
      Profit Or Loss Of Joint Venture - Acuity Partners (Pvt) Ltd,"
      prints a miniature income statement for HNB's OWN joint venture
      under the same canonical labels HNB's real consolidated statement
      uses — doesn't contain "notes to the" (a note-34 continuation
      page, not the notes section's own opening header) so the existing
      exclusion missed it, and it precedes HNB's real statement in page
      order, so "first occurrence wins" kept the joint venture's own
      figure. Fixed by adding "summarised/summarized statement of" as a
      second, generalisable unconditional notes-page exclusion —
      catches this shape for ANY company's JV/associate/segment
      sub-schedule, not just Acuity Partners. 1 new test using the real
      page text.
- [x] **Root cause #4 — a genuine primary statement page's own routine
      FOOTER excluded it**: fixing #3 alone still wasn't enough — HNB's
      REAL income statement page (its actual "STATEMENT OF PROFIT OR
      LOSS AND OTHER COMPREHENSIVE INCOME") was ALSO being excluded, by
      the ORIGINAL "notes to the" marker (built for J.F. Packaging's
      Note 25.1 case) firing on a completely ordinary line every real
      primary statement page in this filing carries: "The notes to the
      financial statements from pages 298 to 466 form an integral part
      of these financial statements" (verified: real page 290, line 39
      of 41 — a footer disclosure, not a section header). This sentence
      is standard boilerplate on essentially any compliant Sri Lankan
      filing, so this was likely the highest-impact of the four fixes,
      not specific to HNB. Fixed by scoping `_NOTES_PAGE_MARKERS` to the
      page's own first 10 lines (matching `_HEADER_SEARCH_LINES`'s own
      precedent) — a real notes-section header always lives there; a
      footer reference never does. 2 new tests, including a regression
      guard that the ORIGINAL J.F. Packaging case stays caught.
- [x] **HNB verified end-to-end, live, with all four fixes together**:
      `net_income` for FY2024 now correctly resolves to **41,341,793,000**
      (Bank) — matching the real external ~15x-larger figure R1_VALIDATION.md
      found, not the wrong 3,179,557,000 that had been sitting confirmed.
      Root cause fully closed, not just disclosed.
- [x] Full suite green throughout every fix: 1335 passed.

**Both full-universe sweeps (the 884-row OI-4 remediation and the
existing stale-fundamentals repair) were RESTARTED from scratch after
EVERY fix landed, four times in total** — a long-running sweep is a live
Python process that already imported the pre-fix code; resuming from its
own checkpoint would have kept re-verifying against an already-superseded
extractor. Re-running from scratch after each fix is the only way each
sweep's own results actually reflect what today's code does.

- [x] **OI-4 remediation applied**: `scripts/remediate_oi4_full_scope.py
      --apply` — 477 confirmed-wrong candidates (509 physical rows,
      several matched more than one stored row) reverted to AI_ASSISTED
      with the value corrected to what today's fixed pipeline verified
      against the live source PDF, exactly the OI-1 precedent. 402 were
      genuinely `confirmed_correct` (real, small figures the magnitude
      check was right to flag as suspicious-looking but a fresh
      extraction confirms are real), 5 unverifiable.
- [x] **HNB's specific wrong row, closed with a targeted, fully-verified
      correction** (`scripts/remediate_hnb_net_income.py`) — the OI-4
      sweep's own magnitude check correctly never flagged this row
      (3.18bn isn't implausibly tiny relative to HNB's own ~2 trillion
      total_assets) and `refresh_stale_fundamentals` correctly refuses
      to touch an already-confirmed row even when an identity DOES fail
      — so the fixed extraction pipeline alone could not close this on
      its own; it needed one targeted, evidence-based correction.
      Verified two independent ways before applying: (1) live
      re-extraction against the real source PDF with all four fixes,
      (2) an independently-confirmed row ALREADY in this database
      (a different filing, confirmed in an earlier, unrelated session)
      carrying the identical figure. Reverted to AI_ASSISTED, pending
      human re-confirmation, per §8 — never silently re-promoted.
- [x] **A fifth real bug, found auditing for exactly this "silently
      wrong, no check catches it" class**: cross-checked every
      CONFIRMED (`annual`, `quarterly`) pair covering the same period —
      real, independent corroboration, the same signal that let the HNB
      fix be verified. Found `interest_expense` disagreeing by close to
      an exact 2x ratio (same magnitude, opposite sign) across dozens of
      unrelated tickers. Traced to the real source, not assumed: this is
      NOT an extraction bug — LGL.N0000's real FY2013 annual report
      prints "Finance Costs 6.3 (5,053,018) ..." (parenthesised) while
      its own real quarterly interim prints the identical figure
      unparenthesised. The SAME company formats this line with opposite
      sign conventions across filing types — both extractions are
      individually correct reads of genuinely inconsistent source text.
      **Real, live consequence closed**: `app.domain.wacc.compute_cost_
      of_debt` divided `interest_expense / total_interest_bearing_debt`
      with no sign normalisation — a company whose confirmed row
      happened to carry the negative reading got a NEGATIVE cost of
      debt, pulling WACC down and overstating every DCF value built on
      it, the exact dangerous direction this module's own docstring is
      already careful to name for a MISSING cost of debt, now closed for
      the wrong-sign case too. Fixed with `abs(interest_expense)` — a
      downstream normalisation, not a data correction, so it benefits
      **105 distinct tickers** with a currently-negative confirmed
      `interest_expense` immediately, with zero data remediation needed
      (valuations compute live, not from a cache). 1 new test using the
      real LGL.N0000 figures.
- [x] **The same sign issue, found on a SECOND quantity by re-running the
      same annual/quarterly cross-check with a more precise signal**
      (same magnitude, opposite sign — not just ">5% different," which
      mostly just reflects a quarter's flow figure genuinely differing
      from a full year's, not a bug): `total_interest_bearing_debt` — a
      debt BALANCE, which can never legitimately be negative — showed
      the identical pattern (verified: LVEF.N0000's real FY2025 annual
      filing prints its debt maturity split parenthesised; its own
      quarterly filing prints the identical figure unparenthesised).
      This one has THREE real consumers, all fixed: `wacc.compute_wacc`
      (a negative reading would make `debt_weight` negative and
      `equity_weight` exceed 1.0 — an uninterpretable weighted average,
      not just a wrong number) and `valuation_view.dcf_for`'s own
      capital-structure section (a negative `total_debt` would INCREASE
      `equity_value` in the enterprise-to-equity bridge — subtracting a
      negative — the same overstate-the-value direction the existing
      `capex = abs(...)` line already guards against one line above it).
      2 new tests. Full suite: 1337 passed.

**A note on scope, honestly**: this "same-magnitude-opposite-sign
cross-check" is a real, generalisable technique — re-run at any time
against any pair of independently-confirmed sources — but it can only
ever surface what it's given to compare (two confirmed sources for the
same period existing at all) and only catches THIS specific failure
shape (sign flips), not every way a number could be wrong. Treated as
what it is: a real, bounded improvement, not a claim that every possible
silent error is now caught.

- [x] **A 7th real fix, closing a limitation this codebase's own prior
      work explicitly named and deliberately declined to fix at the
      time**: `_repair_split_leading_digits`'s own docstring already
      documented, in detail, a real "non-uniform split" case (Panasian
      Power PLC's Inventories row — some columns split, some not) and
      said plainly that fixing it needed "the real discriminator...
      MAGNITUDE plausibility relative to the rest of the same filing...
      not solvable here... without the same risk of reintroducing" the
      J.F. Packaging false-positive. **`check_magnitude_plausibility`,
      built this session, is that missing piece.** Traced JAT Holdings
      PLC's real confirmed `net_income` (stored as the literal digit
      "2") to the actual root cause, which turned out to be one level
      earlier than the non-uniform-split repair itself: `detect_
      expected_value_columns` is a PAGE-level, header-only function, and
      a header like "Rs. Rs. % Rs. Rs. %" is genuinely ambiguous — Tea
      Smallholder's real "%"-column prints a BARE number per row (needs
      counting), JAT's own real "%"-column prints the value WITH a
      literal "%" suffix on every row (already correctly stripped by
      `_VARIANCE_PCT_RE`, so it must NOT be counted) — and the header
      alone cannot say which a given filing will do. Fixed by adjusting
      the expected-column comparison PER LINE, by however many
      `_VARIANCE_PCT_RE` tokens THAT line actually had to strip — Tea
      Smallholder's real line strips zero (unaffected, unchanged
      behaviour, verified with a new test), JAT's real line strips two
      (correctly un-inflating the comparison, unlocking the already-
      existing `_merge_all_split_pairs` alt_values machinery this whole
      time was ready to compute the right answer but was never being
      asked to). 2 new tests, one against JAT's real line, one against
      Amãna Bank's real "%"-suffixed-but-not-split line (the exact
      fixture `_VARIANCE_PCT_RE`'s own docstring already cites) as a
      non-regression guard. Full suite: 1339 passed.
- [x] **A genuinely deeper residual, found and named rather than forced**:
      fixing the column-count bug alone did not fully resolve JAT's own
      `net_income` line — `alt_values` now correctly computes the right
      answer (238,401,649), but `reconcile_ambiguous_values_via_
      identities` (the page-level step that would apply it) doesn't pick
      it, because JAT's real `profit_before_tax` was ALSO split by
      exactly the same missing leading digit ("2", worth 200,000,000 in
      both cases) — and since "pre-tax profit − tax = net income" is a
      pure addition/subtraction relationship, subtracting the identical
      200,000,000 from BOTH sides leaves the identity passing under the
      WRONG default reading, exactly as cleanly as under the right one.
      This is not a bug in the fix just shipped — it's a structurally
      different, genuinely harder problem: an error invisible to
      identity-based reconciliation BY CONSTRUCTION (a uniform offset
      across both terms of a linear identity), and too large in absolute
      terms (tens of millions) to trip the magnitude-plausibility floor
      either. Named precisely rather than patched around with a guess;
      closing it for real would need a genuinely different signal (e.g.
      period-over-period growth-rate plausibility against the SAME row's
      own unaffected comparative column) that does not exist yet.
- [x] **Re-measurement after the seven fixes above, and a second remediation
      pass**: re-ran `reverify_magnitude_flagged_fundamentals.py` from a
      cleared checkpoint (mandatory after every parsing-code change — a
      stale in-memory process would silently re-verify against the OLD
      code) against all 407 rows still flagged after the first 509-row
      remediation wave. Result: **323 confirmed_correct** (the fresh
      re-extraction reproduces the same stored figure — some genuinely
      tiny/correct values, some still-wrong cases the fixes above don't
      reach yet), **79 confirmed_still_wrong** (a DIFFERENT value now,
      i.e. today's pipeline disagrees with what's stored — real,
      actionable), 5 unverifiable. `remediate_oi4_full_scope.py --apply`
      run a second time against the freshly-regenerated report: **79
      more rows reverted to `AI_ASSISTED`/unconfirmed with corrected
      values**, same audit-trail-note discipline as the first pass.
      Combined total across both remediation passes: 588 correction
      operations (579 distinct rows — 9 rows needed correcting twice,
      once by each pass, as later fixes unlocked a more correct
      re-extraction than the first pass had available).
- [x] **Root cause #8, found tracing the 323 "confirmed_correct" bucket
      rather than accepting it at face value**: Ownally Holdings PLC's
      real confirmed `revenue` for FY2022 was stored as the literal
      digit "6" — and TODAY's pipeline (all 7 fixes above included)
      reproduced the exact same "6" on re-extraction, which is why the
      sweep called it `confirmed_correct` rather than flagging it as
      newly-wrong. Traced to the same `detect_expected_value_columns`
      family root cause as fix #7, but a different shape: ONAL's real
      page text reads "Year ended 31 March 2022 2022 2021" — pdfplumber
      has merged the page's own TITLE line (whose trailing "2022" just
      completes that sentence, not a column header) with the table's
      real header row ("2022 2021") onto one line. `_count_year_tokens`
      counted THREE year tokens (the title's "2022", the header's own
      "2022", and "2021") for what is genuinely a 2-column statement,
      inflating `expected_value_columns` to 3 — which made the real data
      line "Revenue from contracts with customers 6 213,037,864
      181,702,922" (note reference "6" + 2 real values, 3 tokens total)
      pass the `len(numeric_tokens) > expected_value_columns` check as
      3 > 3 = False, so the note-reference-drop rule never fired and the
      leading "6" was kept as the value. Fixed by collapsing an
      immediately-ADJACENT literal duplicate year (nothing but
      whitespace between two identical 4-digit tokens) to one column —
      narrow and position-aware, so J.F. Packaging's real "2026 2025
      2026 2025" (non-adjacent repeats, all 4 genuinely distinct
      columns) is provably unaffected; pinned with a unit test on that
      exact shape plus a new fixture (`ONAL_INCOME_STATEMENT_TEXT`, real
      page 43 text) and an end-to-end extraction regression. Full suite:
      1342 passed. **Confirmed live to also affect other tickers sharing
      this exact "X ended DATE YYYY YYYY" merged-header shape** — traced
      Raamboda Falls PLC's real Statement of Financial Position
      ("As at 30th June 2020 2020 2019") the same way: `expected_value_
      columns` is now correctly 2 there too, unblocking the note-
      reference-drop AND `alt_values`/reconciliation machinery for every
      split-leading-digit line on that page (`TOTAL ASSETS`, `Total
      [Non-]Current Assets`, etc.) that used to read as a bare single
      digit. Worker restarted, checkpoint cleared, full sweep re-run
      against all still-confirmed flagged rows to measure fix #8's real
      scope before the next remediation pass — see the entry below once
      it completes.
- [x] **Fix #8's measured scope, and a third remediation pass**: re-ran the
      sweep against exactly the 328 rows the previous sweep had called
      `confirmed_correct` or `unverifiable` (i.e. everything fix #8 could
      plausibly still change). Result: **258 still confirmed_correct, 65
      NOW confirmed_still_wrong** — fix #8 alone flipped 65 rows from
      "silently accepted as correct" to "actionable, confirmed wrong."
      Broken down by ticker, confirms the header-pattern hypothesis
      generalised well beyond the two filings (ONAL, Raamboda Falls) it
      was traced on: **ONAL.N0000 15, RHTL.N0000 10, RFL.N0000 6,
      RPBH.N0000 5, RIL.N0000 4, LPL.N0000/LPL.X0000 4 each, HUNA.N0000
      4**, plus single-digit counts across ATLL, EXT, WLTH, LGL, LFIN,
      HPWR, CALU, CALI — the same "title line merged with the real
      column-header row" PDF-extraction artifact recurring across many
      independent filers, not a one-off. `remediate_oi4_full_scope.py
      --apply` run a third time: **65 more rows reverted to
      `AI_ASSISTED`/unconfirmed with corrected values.** Running total
      across all three remediation passes: 653 correction operations.
- [x] **Root cause #9 — a false-POSITIVE in the plausibility check itself,
      not a parsing bug**: `check_magnitude_plausibility`'s own
      `ratio = abs(value) / largest` is always exactly 0 for a genuinely
      zero value, always below the implausibility floor, so a real zero
      subtotal could NEVER pass this check no matter how many times it
      was re-verified — found tracing Pan Asia Power PLC's real confirmed
      `total_non_current_liabilities`, printed as a literal "0" on 16
      independent real filings across consecutive years (the company
      simply repaid all its long-term debt that year — a completely
      ordinary accounting outcome, re-confirmed identical every time).
      Fixed by exempting an exact zero from the check entirely — a
      corrupted read (split-off leading digit, stray footnote number) is
      never itself exactly zero, so this loses no real detection power.
      Worker restarted, checkpoint cleared, sweep re-run against the 328
      rows fix #8 could plausibly still touch: **result flipped to 235
      candidates (28 fewer — genuine zeros no longer even flagged),
      258 confirmed_correct, 0 newly wrong, 5 unverifiable** — a pure
      false-positive reduction, nothing to remediate this round. Full
      suite: 1343 passed.
- [x] **Root cause #10 — three combined bugs found tracing PALM.N0000/
      CHMX.N0000 (the new top-flagged tickers once #8 and #9's false
      positives were cleared)**: Chemanex PLC's real confirmed `revenue`
      (stored as the literal digit 1) and `gross_profit` (stored as
      2,928 instead of 22,928) traced to THREE separate, compounding
      real bugs on one filing: (1) `detect_expected_value_columns`
      undercounted a bare "%" variance column that shares the YEAR/date
      header line itself ("2018 2017 Variance %") rather than the unit-
      declaration line Tea Smallholder's own already-handled shape uses
      — fixed by summing the two signals when they cooccur on the same
      line; (2) `_merge_all_split_pairs` offered NO alternate at all
      when a genuine leading note reference sits directly in front of a
      split pair's own leading digit (both lone digits, indistinguishable
      by shape to the original single-pass greedy scan) — fixed by
      retrying with the leading token dropped when the direct scan
      overshoots the target column count, narrow enough that an existing
      safety-net unit test needed updating (it was testing an
      unsourced/hypothetical shape, not a real filing, and its own test
      class already documents the module's actual design principle:
      offer an aggressive candidate, let `reconcile_ambiguous_values_
      via_identities` reject what doesn't validate — replaced with a
      still-irresolvable-either-way case to keep that safety coverage
      real); (3) a stray space after a negative value's own OPENING
      parenthesis ("( 84,645)" instead of "(84,645)") broke `cost_of_
      sales`'s extraction entirely — a THIRD real pdfplumber space
      artifact, distinct from the two `_repair_split_thousands` already
      handled — which mattered because the accounting-identity
      reconciliation that fixes (1) and (2) needs `cost_of_sales`
      correct to even evaluate "revenue + cost_of_sales = gross_profit."
      All three fixed together, verified end-to-end against the real
      filing text: `reconcile_ambiguous_values_via_identities` — already
      existing, no new reconciliation logic needed — now correctly
      resolves BOTH `revenue` (107,573) and `gross_profit` (22,928) using
      exactly the same identity-based machinery built for J.F. Packaging
      and eChannelling's real cases. Full suite: 1348 passed.
- [x] **Fix #10's measured scope, and a fourth remediation pass**: worker
      restarted, checkpoint cleared, sweep re-run against the same 235
      candidates fix #9 had left. Result: **211 confirmed_correct, 19
      NEWLY confirmed_wrong, 5 unverifiable**. Broken down by ticker,
      confirms fix #10's three combined bugs are genuinely general
      (found on Chemanex, but not Chemanex-specific): **RFL.N0000 4,
      LLUB.N0000 3**, plus single-row hits spread across STAF, SCAP,
      RWSL, RIL, RHTL, REEF, PHAR, MHDL, LOFC, JKL, HUNA, CHMX (a
      SECOND, different line on top of the revenue/gross_profit pair
      already fixed by the unit test), CALI, CALC, BFN. `remediate_
      oi4_full_scope.py --apply` run a fourth time: **20 rows reverted
      to `AI_ASSISTED`/unconfirmed with corrected values** (19 report
      entries, one matching 2 DB rows). Running total across all four
      remediation passes: 673 correction operations.
- [x] **Root cause #11 — a genuine architectural GAP named and closed,
      not just another parsing bug**: PALM.N0000, the new top-flagged
      ticker once #8–#10's false positives and fixable bugs were
      cleared, turned out to be a genuinely different, harder shape (a
      12-column Group×Company×3-month/6-month×current/prior/variance%
      header where individual line items OMIT sub-columns rather than
      dash-filling them, and WHICH columns get omitted varies per line
      item — named as a residual, not force-fixed, matching the JAT
      precedent from earlier this session: forcing a fix here risks
      fragile, over-fitted logic for one company's unusual layout).
      Checking a SECOND top-flagged ticker (SHOT.N0000) instead found a
      real, well-scoped, GENERAL gap: its real confirmed `inventories`
      (stored as the literal digit 3) already computes the CORRECT
      `alt_values` reading (37,890) via the exact same split-pair
      machinery every other real case in this module relies on — but
      `inventories` is a balance-sheet COMPONENT line with no sibling
      accounting identity anywhere in `check_accounting_identities`
      (nothing sums "total_current_assets = inventories + trade_
      receivables + ..."), so `reconcile_ambiguous_values_via_
      identities` never even considers it: there is nothing for
      identity-based reconciliation to test the correction against, so
      the obviously-correct alt sits unused forever, even though `check_
      magnitude_plausibility` already flags the default outright. Closed
      by a new, complementary reconciliation pass, `reconcile_magnitude_
      implausible_values` — a narrower, DIFFERENT acceptance rule from
      identity-based reconciliation (not a relaxation of it): a
      substitution is accepted only when the key was already flagged
      implausible, an alt exists, the alt itself clears its own flag,
      and the substitution introduces no NEW implausibility flag on any
      other key (the corrected value becoming the filing's new "largest"
      could otherwise shrink some other key's ratio below the floor for
      the first time). Wired into `_apply_identity_reconciled_
      corrections` as a SECOND pass, run after identity-based
      reconciliation and against its updated values, so both passes
      compose correctly on the same filing. 5 new unit tests (the real
      Serendib case, a no-alt-available case, a still-implausible-alt
      case, a never-flagged-so-never-touched case, and a would-newly-
      implicate-another-key rejection case) plus one true end-to-end
      integration test through the actual public `extract_financial_
      statement_candidates` entry point (Serendib's real balance sheet
      page, `inventories` AND `trade_receivables` both correctly
      resolved alongside an identity-reconciled `total_assets` on the
      same page). Full suite: 1354 passed.

### OI-4 full-scope sweep, resumed after a host shutdown, and the over-correction it exposed

Prompted by the product owner asking, after the machine shut down mid-run,
what still needed doing — then, seeing the answer, "make sure the product
is correctly built without any sacrifices on the value it brings."

- [x] **Everything from the sessions above committed for the first time.**
      A host power-loss left weeks of intertwined work (all of Phase 6,
      the M5 scaffold, `backend/scripts/`, the whole `docs/audits/` trail,
      CI, migration 0019, ~30 frontend files) sitting unstaged on top of
      commit `25dd846` — disk-safe but with zero git checkpoint. Landed
      as five coarse thematic commits (housekeeping / backend / frontend /
      ops+audit / docs); `.gitignore` grew `.claude/`, `scratch_*`,
      `docs/price data/` (500+ MB of raw xlsx) and the resumable-sweep
      `*.partial.jsonl` checkpoints.
- [x] **The interrupted magnitude sweep finished and converged.**
      `reverify_magnitude_flagged_fundamentals.py` resumed from its own
      checkpoint (safe — an involuntary shutdown changed no parser code).
      Four passes, each remediation re-measured from a cleared checkpoint:
      **pass 2 flagged 58 confirmed-wrong REPORTED rows → remediated;
      pass 3 flagged 2 (AHPL debt, surfaced only once the pass-2 siblings
      shifted the plausibility baseline) → remediated; pass 4 flagged 0.**
      The 58 were a wider seam than the earlier 8-line sweeps saw —
      `inventories`, `trade_payables`, `trade_receivables`, `revaluation_
      reserves`, `amortisation_expense` on component lines with no sibling
      accounting identity, exactly the class root cause #11's `reconcile_
      magnitude_implausible_values` was built to rescue.
- [x] **Root cause #12 — the magnitude rescue could itself OVER-correct,
      by ~110x.** Reviewing the pass-2/3 corrections against the real
      source PDFs, ~20 rows across AHPL/CINS/CFVF had been "corrected" to
      a value LARGER than the filing's own totals — AHPL's real
      "Other components of equity 96 25 23,093,391 22,287,036 ..."
      (page 96, note 25, then four value columns; note 25's own page is
      headed "25 OTHER COMPONENTS OF EQUITY") became 2,523,093,391,000,
      ~110x the real 23,093,391,000 and 59x the filing's own total
      equity. `_merge_all_split_pairs` had fused the note number "25" into
      the value, and `reconcile_magnitude_implausible_values`' small-side
      floor cleared it without complaint — the floor is one-directional.
      Two fixes in `app.domain.financial_statement_parsing`, both with
      real-filing regression tests:
      - **`split_label_and_values` now drops a SECOND leading reference
        token** when it is multi-digit — a "<page-ref> <note-ref>
        <values...>" line, common on CSE filings and recurring identically
        on CINS and CFVF. Never a lone single digit: that is a pdfplumber
        split-off leading digit (Serendib's real "Inventories 13 3 7,890
        ..."), which `_merge_all_split_pairs` must rejoin, not drop.
      - **`reconcile_magnitude_implausible_values` now rejects an alt that
        breaches the subtotal the line structurally rolls into**
        (`_COMPONENT_SUBTOTAL_CEILINGS`: `inventories` ≤ current assets,
        `trade_payables` ≤ liabilities, `revaluation_reserves` ≤ equity,
        …) — the symmetric bound the small-side flag was missing. Lanka
        Walltiles' real 17.7bn group inventory against 52.8bn total assets
        still corrects cleanly; it is contained, not a breach.
      Verified end-to-end against AHPL's real filing: every over-corrected
      line now extracts to a figure that reconciles with the balance
      sheet's own totals.
- [x] **`scripts/refix_oi4_overcorrections.py`** — re-runs the now-fixed
      extractor against each affected filing and writes back the corrected
      value, same conservative shape as `remediate_oi4_full_scope.py`
      (dry-run default, every touched row kept AI_ASSISTED/unconfirmed,
      original value preserved in a dated `source_snippet` note). **24
      rows corrected**; 1 (LPRT `revaluation_reserves`) left flagged
      because the fresh reading was itself implausibly small — named, not
      forced. The same script corrects the 5 `income_tax_expense` rows
      OI-4's sweep marked `unverifiable`: their real source line reads nil
      for the period ("Income tax expense 4 - -"), so the real figure is
      0, not the note reference that was stored.
- [x] Full suite: **1356 passed** (2 new `financial_statement_parsing`
      tests). DB integrity `ok`; a snapshot was taken before each
      remediation.

### Mathematical cross-check + one-time machine confirmation of the queue

Prompted by the product owner: "confirming 35k rows will have human
errors — can we build something that mathematically cross-checks
everything and confirms for one time." The bar was settled directly:
promote passing rows to `REPORTED` tagged `auto:`, re-extraction
mandatory, at least 2 independent signals.

- [x] **`app.domain.fundamental_cross_check`** (pure) +
      **`app.domain.fundamental_cross_check_view`** (DB-wired) — scores
      every `AI_ASSISTED` row against independent signals: **S1** the
      accounting-identity web balances (reusing `_identity_diffs` +
      the module's own Rs 1,000 rounding tolerance); **S2** today's
      parser, re-run against the source PDF, reproduces the stored value
      exactly; **S3** an independently-sourced row (different
      `source_url`) agrees; **S5** an annual flow line equals the sum of
      its four quarters within 1%; **S6** the dual-listing counterpart
      (`.N0000`/`.X0000`) reports the identical figure. Vetoes: magnitude
      floor, component-subtotal ceiling, a >20x period-over-period jump
      with no corroboration, and a live (not stale) "EXTRACTION FAILED
      ARITHMETIC CHECK" marker.
- [x] **Auto-confirm requires S2 AND ≥2 signals AND no veto AND a
      genuinely independent cross-check** — either an external signal
      (S3/S5/S6) or membership in ≥2 independently-passing identities.
      S1+S2 alone are NOT enough for a single-identity line
      (`net_income`, `revenue`): both read the same extraction of the
      same filing, so neither catches a uniform-offset misread that
      keeps its one identity balancing (JAT Holdings' real `net_income`).
      Regression-tested against exactly that shape and against the
      OI-1/OI-4 note-reference shape.
- [x] **`python -m app.cli auto-confirm-fundamentals`** — dry-run by
      default (writes `docs/audits/AUTO_CONFIRM_<date>.md`: counts by
      confidence band, by signal combination, by line, and the full
      would-confirm list), resumable PDF-re-extraction checkpoint,
      `--apply` promotes to `REPORTED` with
      `confirmed_by="auto:cross-check-v1 [<signals>]"` and writes a
      confidence band onto every row it does NOT confirm so the residual
      human queue is triaged. **`scripts/revert_auto_confirm.py`** undoes
      the entire pass in one command.
- [x] Proven end-to-end on a real scoped run (`--ticker AHPL.N0000`,
      36 filings, live re-extraction): 20 of 382 rows auto-confirmed,
      every one hand-checked correct — including the AHPL component lines
      this session's own over-correction refix had just corrected, now
      independently re-confirmed by S2+S3. 29 new tests; full suite
      **1385 passed**. The full unattended run (~4,561 filings) is the
      operator's to kick off.

## M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md): Task 1 (isolation scaffold) only

A new, separate module — not part of the Master Spec's own phase
sequence above. Strictly additive per its own brief §0: never writes to
an existing table, never imports the app's DB session/models, never
modifies a shared frontend component.

- [x] **`backend/m5/`**: the full package tree the brief specifies
      (panel/, states/, baserates/, playbooks/, validation/, shadow/,
      api/, worker.py) — every module beyond Task 1 itself is an honest
      stub (a docstring naming which task builds it and what it's
      blocked on), not invented logic.
- [x] **Three real mismatches between the brief and this actual
      codebase, found and adapted rather than blindly followed**:
      1. §1.1's Postgres role/schema SQL cannot run against this
         project's real dev database (SQLite, deliberately — see
         README's own "SQLite vs PostgreSQL" section). `m5/db.py` uses a
         completely separate SQLite file (`m5.sqlite`) instead — a
         stronger physical isolation guarantee than a Postgres
         schema+role, arguably. The original SQL is preserved verbatim
         at `m5/migrations/pg_roles_reference.sql` for the real
         production move.
      2. §1.3's `if settings.M5_ENABLED:` requires a field on
         `app.config.Settings` that didn't exist (that class's own
         `extra="ignore"` silently drops undeclared env vars) — added
         `m5_enabled: bool = False`, disclosed as a deliberate, minimal
         exception to "only main.py, one line," not silently done.
      3. §1.3's `frontend/src/config/navigation.ts` doesn't exist; the
         real nav array is `frontend/src/nav.ts`, and wiring a real
         route also required one guarded `case` in `App.tsx`'s own
         render switch — a third touch point beyond the brief's literal
         two files, again disclosed rather than hidden.
- [x] **A named, real blocker, not worked around**: Task 4's state
      thresholds (Appendix A) and Task 7's five remaining playbook
      definitions (Appendix B) live in the companion spec PDF (`CSE
      Alpha Engine - M5 Convergence Engine v1.0.pdf`), which is
      referenced but not included in the brief's own text — `m5/states/
      definitions.py` and `m5/playbooks/definitions/__init__.py` name
      this precisely rather than inventing threshold numbers.
- [x] **The 4 CI isolation gates (brief §1.4)** — `tests/isolation/
      test_m5_isolation.py`: 2 close to the brief's literal pseudocode
      (no forbidden imports; no writes outside `m5.`), 2 adapted (the
      brief's git-diff-against-a-pre-M5-tag check replaced with a static
      marker scan, since no such tag exists in a repo where M5 work
      started mid-session against an already-dirty tree; the
      flag-off-means-404 check verified against the real FastAPI app).
      All 4 pass. Verified BOTH directions live, not just the flag-off
      unit test: a throwaway backend instance with `M5_ENABLED=true`
      really returns 200 from `/api/v5/status` (and `/health` keeps
      working unaffected), then torn down — confirmed no `m5.sqlite`
      file was even created (the status endpoint never touches the DB
      engine, matching "nothing beyond the scaffold is implemented yet"
      exactly).
- [x] **Frontend wiring, guarded**: `frontend/src/features/playbooks/`
      — a lazy-loaded route with its own error boundary (brief §8's
      requirement, built now since it's part of the allowed wiring, not
      Task 8's real UI), rendering a real, honest "not built yet" body
      that calls the real `/api/v5/status` endpoint — proving nav entry
      -> lazy route -> error boundary -> real backend call actually
      works end to end, this codebase's own established "never fake
      content, even a placeholder" discipline extended to M5's own
      first screen.
- [x] Full existing suite green throughout: 1326 backend tests passed,
      frontend `tsc --noEmit` + the zone-fallback CI guard clean.

**Not started**: Tasks 2-9 (panel builder, backfill, state classifier,
base rate engine, trial registry, playbook engine, the real Playbooks
tab, shadow book).

## Phase 6 — the factor library, §36 Carhart certification, §37 timing battery, §38 composite score: completed

Everything the "Explicitly deferred" section below used to call
genuinely unbuilt (MKT-RF, SMB, HML/HML_hard, MOM, the mandatory Dimson
correction, §36's Carhart certification regression) is now real and
live, plus the two pillars that consume it:

- **§35.1's full factor series** (`app.domain.factor_series` +
  `factor_series_view`) — MKT-RF, SMB, HML_hard, MOM and LIQ, all on a
  real weekly formation cadence (disclosed substitution for §35.1's own
  monthly convention — this system's real price history supports
  ~163 weeks of meaningful re-estimation, not monthly rebalancing).
  SMB/HML_hard/MOM/LIQ reuse `app.domain.portfolio_sort.
  two_by_three_sort` (the real Fama-French 2x3 construction) with a
  different real per-ticker `style_value` each; MKT-RF and MOM's own
  "skip the most recent month" windowing are the two genuinely new
  pieces this module adds.
- **§36 Carhart certification** (`app.domain.carhart_regression` +
  `carhart_view`) — Dimson (1979) 3-lag aggregated betas against all 5
  real factor series above, Newey-West HAC standard errors via
  `statsmodels` (the same lazy-import precedent `app.domain.
  sector_sensitivity` already set), regressed by real date intersection
  across every series so a week missing from one factor never silently
  misaligns the rest.
- **§37 timing & momentum battery** (`app.domain.timing_battery` +
  `timing_battery_view`) — the real weighted-signal composite (52wk-high
  20%, residual momentum 20%, MOM_12_2 20%, MOM_6_1 15%, REV_1M 15%,
  volume confirmation 10%), §37.1's contrarian branch, §37.2's
  crash-guard reweighting. A missing signal (most commonly residual
  momentum, which needs a real Carhart regression with enough real
  weeks behind it) renormalizes the weighted mean among whatever IS
  real for this ticker — never a fabricated zero standing in for a
  missing signal.
- **§12 sector-relative percentiles, real and universe-wide**
  (`app.domain.sector_percentiles` + `sector_percentiles_view`) — a
  ratio's own value ranked against its real CSE industry-group peers
  (falling back to the wider GICS sector when the narrow group has too
  few), the machinery both the company file's own ratio cards and the
  composite score's own percentile-ranked pillars now share.
- **§38's Macro & sector fit pillar** (`app.domain.macro_sector_fit` +
  `macro_sector_fit_view`) — a direction-count formula over sector
  sensitivity to the current regime, project-register exposure and
  sector momentum, deliberately NOT magnitude-weighted (an OLS
  coefficient's magnitude isn't comparable across differently-scaled
  shock series without an invented normalization — see that module's
  own docstring).
- **§38 composite score itself** (`app.domain.composite_score` +
  `composite_score_view`, `GET /composite-score/{ticker}`) — the real
  7-pillar blend (Valuation 25/Business quality 25/Growth 15/Financial
  strength 10/Macro & sector fit 10/Timing & momentum 10/Risk 5) plus
  the §11.1 Gate 3 integrity veto reported as evaluated/vetoed/
  unevaluable (never assumed to pass). Valuation and Growth are
  permanently shown as evidence rather than blended into the number —
  a real, measured ~30s-per-universe-pass latency cost at current data
  volume, not a data gap; any other pillar missing for a specific
  ticker carries its own real, named reason. Live on the company file
  and folded into `app.domain.opportunity_ranking_view`'s own module
  docstring, which used to (wrongly) claim this machinery didn't exist
  — corrected in place rather than left stale once this section made
  the claim provably false.

Rolling alpha (`app.domain.rolling_alpha`) — a real trailing-window
alpha series built on the same Carhart machinery, for a future
performance-attribution surface — also shipped alongside the above but
isn't consumed by any screen yet; named here so it isn't mistaken for
dead code.

## R1 — UX & data-integrity remediation (Aug 2026)

A full second pass, separate from Phase 1-6's own build-out above:
fixing what the screens actually showed a real user, auditing this
system's own stored data against reality, and building the QA
infrastructure to keep both from silently regressing. Full detail
lives in its own audit trail, `docs/audits/R1_*.md` (published as a
browsable artifact — ask for the link if it's not already at hand),
not duplicated here; this entry is the pointer plus the headline
findings.

- **Phase 1/2 data audit** — synthetic-value sweep, source
  reconciliation, and OI-1: 95 confirmed "Reported" figures across the
  universe were actually stale note-reference numbers (a PDF note
  number like "5" or "4.2" mis-read as the real value) from before a
  parser fix, wrongly bulk-confirmed. Re-verified against real source
  PDFs, corrected, reverted to AI_ASSISTED pending re-confirmation.
- **Phase 4 — UI redesign**, screen by screen: Today (real trend
  chips, real attention counts), Opportunities and Companies
  (paginated, real 5/10/15/30-day sort columns), Portfolio ("Sell
  Above" replacing the wrong "Buy Below" signal for held positions,
  real per-position attention flags), the Company file (ratio cards
  with real sector percentile + multi-year path, a plain-language cost-
  of-equity explainer, valuation routing collapsed into one honest
  table, the composite score made the page's own visual anchor with a
  real weight-proportional stacked bar, paginated financial statement
  lines sorted awaiting-confirmation-first), and Macro (a real
  sector drill-down — market-share treemap, ranked constituents, macro
  sensitivities carried through — the single highest-value new feature
  in that pass).
- **Phase 4B — QA infrastructure**: `backend/scripts/qa_capture.py`
  (real Playwright session against the real running app; screenshots,
  programmatic assertions, forbidden-string/empty-state/axe-core
  sweeps), `docs/audits/R1_BROWSER_QA.md` (human-in-the-loop five-
  question review per screen), and this repo's first-ever CI workflow
  (`.github/workflows/ci.yml`).
- **Two real, severe backend bugs found and fixed** while building the
  QA automation, both in `app/db/session.py`: SQLite was never in WAL
  mode (real lock contention), and — the more serious one —
  SQLAlchemy's own default connection-pool ceiling (15) was being
  exhausted by this app's own concurrent requests on a normal cold page
  load, which could make a screen hang **indefinitely** for a real
  user, not just run slow. Traced to an exact `TimeoutError` in the
  server log; fixed by raising the pool size for SQLite specifically.
  Re-verified live: a page that never rendered before now loads in ~8s,
  consistently.
- **Phase 5 — independent valuation** (`docs/audits/R1_VALIDATION.md`):
  5 randomly-seeded tickers (seed recorded, reproducible), valued from
  raw stored data before touching this system's own computed output,
  then checked against real external research gathered live. Found a
  genuine ~15x error in HNB.N0000's stored net income against real
  externally-reported group earnings (root cause not yet found —
  highest-priority open item); found and fixed two more OI-1-pattern
  stale rows on LOFC.N0000 (logged as OI-4 — on statement lines OI-1's
  own reverification sweep never checked, so the true scale of that bug
  class across the rest of the universe is still unknown); and
  documented, honestly, that 3 of the 5 randomly-picked tickers have no
  independently-computable fair value from this system's confirmed data
  today, each for a different, real, named reason.

- **Housekeeping, reliability and the "Run Capture" root cause** (23 Aug
  2026, `docs/audits/R1_FIX_LOG.md`'s own "Housekeeping..." section):
  removed 3 duplicate git worktrees and a duplicate PDF found while
  cleaning up "duplicate `ROADMAP.md`" reports; found the worker
  process (`python -m app.worker`) had never actually been running —
  `sys.stdout.encoding` defaults to `cp1252` on Windows even redirected
  to a file, and the first Unicode character in a log line crashed it
  silently, which is why "Run Capture" looked broken (nothing was ever
  polling the job queue) — fixed with a UTF-8 stdout/stderr reconfigure
  in both `worker.py` and `main.py`, plus a new `recover_orphaned_runs`
  self-heal for any `JobRun` stuck `running` from a crash; the Run
  Capture button also got a real, small percentage-complete progress
  bar above it. Processed both real confirm queues at scale through the
  existing, already-safe mechanisms (213 corporate actions via real
  `cash_amount` confirms, 478 fundamentals via the corroborated-batch
  endpoint) — a genuine side effect: `gordon_growth_ddm_for` went from
  "real but empty" (zero confirmed dividend rows anywhere) to computing
  real values for the first time.
- **All 9 §18-26 valuation models made to actually run, not just
  disclosed** (23 Aug 2026, same day, in direct response to reviewing
  the pass above as "3 of 9 have zero live caller"): justified P/E and
  justified P/S (§20.2) are now real live triangulation anchors,
  `app.domain.valuation_view.relative_valuation_for`, deriving a real
  payout ratio from the trailing confirmed dividends the housekeeping
  pass above just unlocked; §23's Bear/Base/Bull scenario set,
  sensitivity tornado and Monte Carlo overlay are now wired in a new
  `app.domain.scenarios_view`, built directly on the existing live DCF
  engine's own base-case assumptions, exposed via `GET
  /valuation/{ticker}/scenarios`, `/tornado` and `/monte-carlo` and
  surfaced on the company file. Sum-of-the-parts (§21) is the one model
  investigated and confirmed to be a genuine hard blocker, not a wiring
  gap: it needs a segment-level subsidiary/ownership-%/EBITDA-multiple
  data source that no ingestion pipeline in this project produces at
  all, tracked separately below rather than left conflated with gaps
  that turned out to be fixable. 14 new backend tests, 1311/1311 green.

**Real, disclosed gaps this pass did not close** (see
`docs/audits/R1_OPEN_ISSUES.md` and `R1_FIX_LOG.md`'s own "not done"
sections for the complete list): HNB's net-income divergence isn't
root-caused; OI-1's reverification sweep needs re-running across every
confirmed statement line, not just the original 8; the Company file's
own page-length density (everything real, nothing individually
removable, but no way to jump straight to a verdict yet); and the
Companies table's ticker rows are plain `<tr onClick>` rather than the
`<button>` every other screen's own ticker cell uses — a real, cosmetic
accessibility inconsistency, not a keyboard trap (found live while
building the QA script's own row-click logic).

## Explicitly deferred to later phases

The earnings integrity veto (§14 — needs CFO, related-party revenue,
auditor and director-dealings data this system does not extract), §27
execution reality (needs a live order-book feed, 15-minute cadence — not
part of Phase 3's own gate per Master Spec §54's build-sequence table),
the scheduler/always-on service/decision capture (Phase 4), and the AI
research writer (Phase 7) — all per §54's own real build-sequence table,
checked
directly against the PDF (earlier entries in this file called the macro
engine "Phase 4"; §54 actually numbers it Phase 5, corrected above where
first noticed). Fundamental ratios (§12), trend detection (§13), the
model router (§15/§16), and valuation MATH (DCF, DDM, residual income,
SOTP, relative valuation, asset-based, scenarios, triangulation, margin
of safety, the price ladder — §17-26) are no longer in this list — see
above. **Macro/ARDL (§29-34) is also no longer a single untouched
block — §30's own six-step method chain is now fully built.** §31's
regime classifier, §33's sector sensitivity matrix, §34's national
project register, and every one of §30's own six steps (stationarity/
break testing; the three named estimators — ARDL bounds testing,
Johansen/VECM, VAR-in-differences — plus the estimator-selection
capstone that routes between them; impulse response/FEVD/Toda-Yamamoto
causality; and now the event study) are all live (see those entries
above). Within §30 specifically, only the event study's own real gap
remains: CCPI-release, IMF-programme-milestone, budget, and election
event DATES have no real structured source yet (CBSL policy rate
CHANGES are the one event type this system can study today), named
precisely in that module's own docstring rather than silently assumed
away. §34's own possible future variable-set expansion (reserves, M2b,
private credit, trade balance, tourist arrivals — noted in §29's own
entry as not available from the daily CBSL PDF) is likewise a real,
separate, disclosed gap, not part of "macro/ARDL" as a line item
anymore. **Phase 6 (the factor library) is also no longer a deferred
item at all — see "Phase 6 — the factor library..." above, corrected
here rather than left standing once that section made this paragraph's
own older claim false.** MKT-RF, SMB, HML/HML_hard, MOM, the mandatory
Dimson correction, §36's Carhart certification regression, §37's
timing battery and §38's composite score are all real and live now,
not deferred. Building the still-genuinely-deferred items above against
unvalidated data, or against inputs this system doesn't actually have,
would produce exactly the look-ahead-biased, false-precision numbers the
spec's failure-mode register (Part N) warns about.
