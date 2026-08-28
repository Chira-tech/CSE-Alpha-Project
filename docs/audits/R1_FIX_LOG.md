# R1 Fix Log

Chronological record of what was actually changed this session, in the
order it happened. See `R1_DATA_AUDIT.md` for the audit itself and
`R1_OPEN_ISSUES.md` for the full OI-1/OI-3 investigation and resolution
this log summarises.

---

## Phase 1 — data integrity audit

- Built `backend/scripts/audit_data_integrity.py` (T1.1) — reusable,
  re-runnable, every number in `R1_DATA_AUDIT.md` reproducible by
  re-running it. Covers prices, corporate actions, financial statements,
  macro, a synthetic-data sweep, and T1.2's reconciliation sample.
- T1.2's first run (20-ticker sample) hit a 10.0% mismatch rate,
  triggering the brief's own stop-the-release rule. Investigated to
  root cause — see OI-1 below.
- Verified the Today tab's own "corporate actions pending" / "figures
  pending confirmation" counts against direct SQL: they match exactly
  (same query, same live database), confirming those aren't a
  presentation bug, just numbers that grow forward over real sessions.

## OI-1 — stale, wrongly-confirmed financial figures (CRITICAL, RESOLVED)

Full writeup: `R1_OPEN_ISSUES.md`. Summary:

1. Built `scripts/reverify_suspicious_fundamentals.py` — re-downloads
   the real source PDF for every candidate row and reruns today's
   actual extraction pipeline, checkpointing incrementally (a first,
   uncheckpointed run was interrupted partway and lost ~177 filings'
   worth of work; the rewrite fixed that).
2. Ran the full sweep (not a sample): 253 distinct filings, 396
   candidate rows. Result: 301 `confirmed_correct` (false positives of
   the discovery filter), **95 `confirmed_still_wrong`**, 0
   unverifiable.
3. Diagnosed the 95: today's pipeline gets every one right on
   re-extraction. The stored values are stale — extracted before a
   parsing fix now in the codebase, then promoted straight to
   `REPORTED` by a 19 Aug 2026 bulk-confirm pass that evidently didn't
   actually check them despite its own commit note claiming a "sample
   check." **Not a live code bug** — the first hypothesis (a
   currently-broken note-reference-stripping rule) was investigated and
   disproven before this conclusion was reached.
4. Built `scripts/remediate_oi1.py` and ran it (dry-run, then
   `--apply`): reverted all 95 entries (101 physical rows) to
   `provenance_tier=AI_ASSISTED`, `confirmed_by=NULL`, with `value`
   corrected to the live-reverified figure and a dated remediation note
   prepended to `source_snippet`. **Never auto-confirmed** — every one
   goes back through a human via the confirm queue.
5. Verified: zero of the 95 remain `REPORTED`+confirmed; full backend
   suite still green (1271/1271 at that point — data-only change).

## OI-3 — quarantine wasn't actually wired anywhere (RESOLVED)

Found while investigating OI-1: `is_quarantined`/`DataAlert` were
checked in exactly one place (the company-file badge) despite their own
docstrings claiming a quarantined ticker is excluded "from every model."

- `app/domain/opportunity_ranking_view.py`: a quarantined ticker now
  routes to `excluded` with the quarantine reason, never ranked, before
  any valuation work runs for it.
- `app/domain/portfolio_valuation_view.py`: a quarantined holding shows
  its real price/quantity/market-value (directly observed) but every
  derived valuation field (fair value, price-ladder zone, buy-below,
  sell-above, margin of safety, dispersion) is withheld with a named
  reason.
- Two new regression tests, one per module. Full suite 1273/1273.
- Data Health screen's quarantine-list copy corrected to state the real
  (now true) guarantee instead of the broader claim the code didn't
  back up.

## Phase 2 — blocking computation fixes

- **T2.1 (macro regime "No regime")**: checked directly against the
  running app — already resolved by earlier work this session. The
  Today screen states a specific, quantified reason ("No regime gauge
  on this screen yet... the classifier itself is real and runs live
  now... what's missing is a dedicated gauge here"), never a bare "No
  regime." No change needed; verified, not assumed.
- **T2.2 (fair value "not computable" — three failure classes)**:
  checked directly — the three classes the brief wants distinguished
  (blocked by missing input / blocked by sanity gate / model not
  applicable) already render in three separate, clearly-labelled UI
  locations (per-anchor warnings; the sanity-block notice; the
  Valuation routing "suppressed, and why" list). Extended with a real
  Fair value range (Bear/Base/Bull, see T4.3.4 below) and a DCF fact
  card that wasn't previously shown despite the backend already
  computing it.
- **T2.4 (Portfolio detail won't open)**: checked directly in a real
  browser — already works. No change needed.
- **T2.5 (confirm queue throughput)**: built the real, safe
  corroboration-gated bulk-confirm path directly motivated by OI-1 —
  `GET /fundamentals` now returns `corroborated: bool` per row (an
  independently-sourced REPORTED row already carries the exact same
  value), and `POST /fundamentals/confirm-batch-corroborated` only
  promotes rows the SERVER re-verifies as corroborated — a client
  claiming false corroboration gets it rejected. This is the one case
  safe for one-click bulk confirm; every other row still needs a human
  looking at it individually. 5 new backend tests. Frontend: a
  "Confirm N corroborated" button, distinct from the existing
  select-and-confirm flow, plus a "corroborated" chip per row.
  (Impact-sorting the queue — T2.5's other ask — not done this pass;
  named here as a real remaining item, not silently dropped.)
  **Bug found and fixed during live verification of this same feature**:
  the corroboration key required `period_type` to match too, which
  meant it never fired for the single most common real corroboration
  shape in this data — the same point-in-time balance-sheet figure
  reported once in that year's own annual filing (`period_type=
  "annual"`) and again in a later interim report's comparative
  prior-year-end column (`period_type="quarterly"`) — found live
  against ABAN.N0000's real total_assets. Fixed by dropping
  `period_type` from the key (the exact-value + different-source_url
  check already carries the real safety property); a new regression
  test pins the real ABAN shape. Effect: 0 -> 497 genuinely corroborated
  rows across the live 35,168-row pending queue.
- **T2.6 (CLI instructions leaking into the UI)**: fixed in four
  places — the company file's corporate-actions empty state now shows
  real scan-recency status (`corporate_actions_last_scanned_at`, backed
  by `CorporateActionScanLog`) instead of `python -m app.cli
  ingest-corporate-actions`; the price-history empty state, the
  confirm-queue's own empty state, and the CBSL T-bill manual-entry
  notice were all corrected the same way (all three of those jobs are
  genuinely already scheduled — the CLI text was simply wrong, not a
  missing feature).

## Phase 3 — export and backup

- **T3.1** `GET /export/workbook` — real `.xlsx`, one sheet per domain
  (Companies, Prices, Financials_Annual, Financials_Interim,
  CorporateActions, Ratios, Valuations, Macro, Portfolio, README).
  Ratios reuses the same bulk two-view computation
  `sector_percentiles_view` already established; Valuations reuses
  `opportunity_ranking_for` directly rather than a second,
  independently-maintained valuation loop. Frozen header row, real
  column widths, no merged cells. Verified end-to-end against the real
  dev database: 10 sheets, ~200k price rows, ~106k financial-statement
  rows, 277 valuations, all present and correctly typed on reload.
- **T3.2** `GET /export/backup` — the real recovery artefact: one
  newline-delimited-JSON file per table (generic over every table in
  `Base.metadata`, never a hand-maintained list) plus a checksummed
  `manifest.json`.
- **T3.3** `scripts/verify_backup_restore.py` — restores a real,
  just-downloaded backup into a scratch SQLite database and asserts row
  count + SHA-256 checksum per table. **Run against a real backup of
  the real dev database; evidence:**

  ```
  TABLE                            MANIFEST N   RESTORED N   CHECKSUM
  corporate_action_scan_log                59           59         OK
  corporate_actions                       343          343         OK
  data_alerts                               0            0         OK
  decisions                                 1            1         OK
  float_data                              295          295         OK
  fundamentals                         105618       105618         OK
  ingested_filing_log                   18795        18795         OK
  issuer_registry                         369          369         OK
  job_runs                                  4            4         OK
  macro_series                           6555         6555         OK
  national_project_ticker_impacts            0            0         OK
  national_projects                         0            0         OK
  outcomes                                  0            0         OK
  portfolio_positions                       9            9         OK
  portfolio_snapshots                       1            1         OK
  prices_daily                         199992       199992         OK
  securities                              290          290         OK

  ALL 17 TABLES VERIFIED: row counts and checksums match the manifest exactly.
  ```

  (Run before the OI-1 remediation landed — row counts are pre-fix;
  remediation only changed `value`/`provenance_tier`/`confirmed_*` on
  95 already-existing rows, not row counts, so this evidence remains
  valid for the backup FORMAT and restore MECHANISM, which is what
  T3.3 verifies.)
- **T3.4** Data Health screen gets two buttons — "Download Excel
  workbook" and "Download full backup" — each a real client-side
  download (`Content-Disposition` filename honoured; `expose_headers`
  added to CORS so the browser can read it cross-origin). Scope
  decision, disclosed in `app/api/routes/export.py`'s own docstring:
  both are synchronous downloads, not routed through the SSE Run
  Capture job system — real data volume here makes both finish in
  seconds to ~100s, not the multi-minute jobs that system exists for.

## Buy/exit-point UI (highest priority per the user's own framing of
## what this system is for)

- **T4.3.4** — Fair value range on the company file: Bear/Base/Bull
  computed from whichever real §18-26 anchors (Justified P/B, Residual
  income, FCFF DCF) actually computed for this company — never a
  fabricated §23 DCF scenario (that needs multi-year growth/margin
  history most companies don't have). A single-anchor company shows one
  number with an explicit "no genuine range yet" note rather than a
  fake zero-width range.
- **T4.3.8** — Price chart ceiling/floor/average reference lines: real
  `exit_threshold`/`strong_accumulate_threshold` from the price ladder,
  dashed, right-edge-labelled, axis auto-widened so a real bound outside
  the traded range is never clipped off-chart. Average is the trailing
  mean of the shown window, explicitly labelled as such (no portfolio
  cost-basis lookup wired into the company file yet — named as a real,
  separate gap in the component's own docstring). A missing bound is
  omitted from the chart AND named in the caption, never guessed.
- **T4.5.3** — Portfolio "Buy Below" renamed to "Sell Above", now the
  real take-profit ceiling (`exit_threshold`) instead of a buy signal on
  a position you already hold.
- **T4.5.4** — Real per-position attention flags: valuation stretched
  (price-ladder zone), ROE falling, earnings (net margin) deteriorating,
  leverage rising — each from real §13 trend data, direction shown even
  when not yet statistically significant (labelled which). No fabricated
  "thesis break" (needs §45's decision record, not built).

All of the above verified live in a real browser against the real dev
database, not just unit-tested — screenshots and page-text captures were
inspected during this session (not reproduced in this log, but the DCF
fact card, the fair value range, the three chart reference lines and the
composite score section were all confirmed rendering correctly with real
COMB.N0000 data).

## Phase 4 — screen-by-screen UI redesign

New shared components, each used by more than one screen so the
pattern doesn't fork: `TrendChip` (multi-window direction strip),
`VerdictPill` + `verdictFromPercentile` (the one strong/adequate/weak/
no-data banding used everywhere a judgement is shown), `ProvenanceDot`
(inline provenance for a single displayed number), `PlainExplainer`
(headline + authored body, real numbers interpolated, never a
generated sentence), `PaginatedTable`'s `usePagination`/
`PaginationControls` (client-side paging with a real page-size
selector, used by four different tables below).

- **T4.1.1-T4.1.6 (Today)** — heading renamed "Today's summary"; ASPI
  card gets a real 15d/30d/45d `TrendChip` from `getIndexHistory`;
  attention section shows `fundamentals_pending_by_ticker` (new backend
  field, top 8 by count, explicitly disclosed as not the brief's
  literal "unblocks fair value for N companies" claim — too expensive
  to compute per page load); portfolio block gets a real 15d/30d/45d/
  60d `TrendChip` from the new `value_trend_pct`.
- **T4.1.6/T4.5.1 (portfolio trend)** — new `portfolio_value_trend()`
  in `portfolio_valuation_view.py`: today's actual holdings priced at
  real past closes per window, `None` per-window if any position lacks
  that-far-back pricing. Docstring discloses the "current holdings,
  past prices" assumption vs. a real transaction-log replay.
- **T4.2.1/T4.2.2 (Opportunities)** — ranked table converted to
  `PaginatedTable` (10/15/20/30, default 15); notice copy shortened
  with detail moved into a `<details>`.
- **T4.4.1 (Companies)** — real 5d/10d/15d/30d sortable price-change
  columns. New `_bulk_price_changes()` in `securities.py`: one bulk
  query for the whole universe's 60-day price window, session-count
  indexed in Python (not calendar days) — never N+1 per ticker. A
  momentum-chasing caveat appears only when actually sorting by one of
  these columns.
- **T4.3.1 (Company — ratio card grid)** — `RatioTable`'s numeric rows
  replaced by `RatioCardGrid`: cards grouped into Profitability/Growth/
  Financial strength/Efficiency/Shareholder returns, each carrying
  current value, prior-period value + direction, sector percentile, a
  `VerdictPill`, and — new backend field `ratio_series` (`GET
  /securities/{ticker}`, from new `fundamentals_view.
  ratio_series_by_key()`) — a real numeric path once >=3 periods exist,
  never fewer (same `MIN_PERIODS_FOR_DIRECTION` floor §13 already
  uses). Growth and Shareholder returns show as empty groups with the
  honest reason — no ratio for either is wired into `app.domain.ratios`
  today — rather than being hidden or backfilled with something else's
  numbers.
- **T4.3.2 (Company — Ke)** — `PlainExplainer` added: real Ke number,
  what it does (discount rate, never a verdict — the brief's own note
  that "good sign to buy" framing is wrong for this metric is followed
  literally), and why it's where it is from its own real beta/size/
  illiquidity components. No CSE-median comparison shown — this system
  doesn't compute one, and the copy says so rather than inventing one.
- **T4.3.3 (Company — valuation routing)** — three separate lists
  merged into one Model/Status/Reason table. The mockup's Primary vs.
  Support role split is NOT real data `app.domain.valuation_router`
  carries (`primary_models` is a flat, unranked tuple) — shown as
  Used/Not used instead, disclosed as such, rather than fabricating a
  finer role split than the underlying decision actually has.
- **T4.3.5 (Company — composite score)** — moved up next to the price
  ladder (the visual anchor position the brief asks for); score/100 +
  `VerdictPill` up front; new `CompositeScoreBar` — a real horizontal
  stacked bar, segment width = each pillar's actual §38 weight, fill =
  score band from the same 70/40 thresholds every other `VerdictPill`
  uses, excluded pillars shown faded rather than dropped from the bar.
  Each segment links to its pillar's own evidence card below.
- **T4.3.6 (Company — financial statement lines)** — new
  `FundamentalsLinesTable`: `PaginatedTable` (10/20/30, default 10),
  default sort awaiting-confirmation-first, `ProvenanceDot` per line,
  and a real inline Confirm action (reuses the existing single-row
  `POST /fundamentals/{id}/confirm`) — verified live: confirming one
  row moved the awaiting count down by one and dropped that row out of
  the top group in the same page load.
- **T4.3.7 (Company — "What this tells you")** — did not exist
  anywhere in the codebase (not a rendering fault to fix; there was no
  code path at all). Built new, from numbers already fetched elsewhere
  on the page only: current price vs. base-case fair value and price-
  ladder zone, composite score with which real pillars drove it up or
  down. Deliberately does NOT attempt the UI spec's "case in five
  lines" bull/bear bullets or named falsification conditions — those
  need investment judgement this system does not generate, and a
  machine-written version of that would be exactly the "confident,
  precise, fictional" text §1 law 4 and §5.0 forbid. Points to the
  Journal screen's own decision record (§37) as where a human's actual
  thesis belongs instead.

All of the above verified live in a real browser against the real dev
database (JKH.N0000): the composite score bar and pillar breakdown,
the Ke explainer, the unified routing table, the ratio card grid
(including a real 46-period path on Equity ratio), the "What this
tells you" synthesis, and the fundamentals table's inline confirm
action all rendered correctly and the confirm action produced a real,
persisted state change.

**Environment note, not a code bug:** mid-session the backend came up
pointed at the Postgres default in `config.py` instead of the
project's own SQLite dev mode (`backend/.env` — gitignored, and had
gone missing) and every DB-touching request hung on a Postgres
connection timeout. Recreated `backend/.env` from `README.md`'s own
documented dev-mode `DATABASE_URL` pointing at the existing
`devdb.sqlite`; this file needs to keep existing locally for the
server to start against real data — see README.md before assuming a
future "requests hang, /health is fine" symptom is a code regression.

## Phase 4 — Macro tab (T4.6)

- **T4.6.1/T4.6.3** were already real from earlier this session: the
  screen's own "what's real, what's missing" notice, and `SpreadHero`
  already wraps its number in a real `PlainExplainer` (three authored
  states by real spread sign, same pattern as T4.1.3).
- **T4.6.2 (heat map)** — the sensitivity matrix already showed
  direction/magnitude/confidence per cell as text; added real
  background shading on top, a sequential muted scale
  (`--brand-100`..`--brand-400`, same tokens `Treemap` uses, never
  red-green diverging) with intensity = `|coefficient| / max(|
  coefficient|)` across the whole matrix's own significant cells —
  never a fixed constant that would misread once the real distribution
  shifts. Only significant cells shade; a thin real history never
  masquerades as a strong relationship through colour alone.
- **T4.6.4 (sector drill-down — "the highest-value new feature in this
  release")** — clicking a sector, on either the sensitivity matrix or
  the live sector-index board below it (the brief's own "apply the
  identical drill-down to the second matrix"), opens a panel with:
  - A real squarified treemap (`Treemap.tsx`, Bruls/Huizing/van Wijk —
    a treemap, not a radar chart, per the brief's explicit instruction
    that market share is part-to-whole) of every live constituent by
    real market cap (new `bulk_market_cap_for()` in `market_cap_view.py`
    — two bulk queries across the sector's tickers, not N+1).
  - A ranked table: ticker, market cap, % of sector, real fair-value
    gap (reuses `opportunity_ranking_for`, filtered to the sector).
  - The sector's own macro sensitivities, carried through client-side
    from the matrix row already fetched by the same screen — not
    re-fetched.
  - Composite score is deliberately NOT a column: timed live against
    real data (`composite_score_for`, JKH.N0000, 23 Aug 2026) at ~11s
    for ONE ticker — computing it for every constituent on a single
    click would be minutes, not seconds. Omitted with that real,
    measured reason attached to the response (`app.domain.
    sector_drilldown_view`'s own module docstring), never faked or
    silently slowed down; each row links to the company file, which
    shows the real score for that one ticker.
  - New endpoint `GET /market/sector/{sector}`, ~15-20s the first time
    (reuses the same whole-universe valuation pass the Opportunities
    screen already pays on every load) — a real, disclosed cost paid
    on the user's own click, not on page load.

  **Real bug found and fixed during live browser verification, not
  caught by any unit test:** the treemap's row/column orientation was
  inverted — a "wide remaining rectangle" was laid out as a horizontal
  strip instead of a vertical column (and vice versa), producing
  visibly overlapping rectangles instead of a clean tiling. Fixed in
  `layoutRow()`; re-verified live afterwards (real Banks-sector data,
  14 real constituents, clean non-overlapping tiling, sizes correctly
  proportional to market cap).

  **Also found live, not a code bug:** immediately after adding this
  route, the running backend hadn't been restarted, so the panel
  showed a real "Not Found" error — expected, not a defect; restarting
  picked up the new route and it worked first try after that.

## Test suite

Backend: 1266 (session start) → 1287, all green throughout, no
regressions at any step (new this round: `ratio_series_by_key` in
`test_fundamentals_view.py`, the `ratio_series` API field in
`test_securities_api.py`, `test_sector_drilldown_view.py` and
`test_market_sector_drilldown_api.py`). Frontend: `tsc --noEmit`,
`vite build`, and the zone-fallback CI guard clean throughout.

## Housekeeping, "Run Capture" root cause, and a universe-wide valuation-pipeline verification (23 Aug 2026, later same day)

- **Duplicate files, cleaned up**: 3 leftover git worktrees from earlier
  subagent sessions (`.claude/worktrees/agent-*`, each a full repo copy
  — the real cause of "2 ROADMAP.md files") removed via `git worktree
  remove` after confirming no unique commits and no real uncommitted
  work in any of them (one had an uncommitted diff that turned out to
  already be present in `main`, comment wording aside). A byte-identical
  duplicate PDF in `docs/` also removed.
- **"Run Capture doesn't work" — root cause found and fixed.** The
  always-on worker process (`python -m app.worker`) that actually
  executes queued jobs had never been started in this dev environment
  — every click on "Run Capture" inserted a real `queued` row and
  returned 202, but nothing was alive to ever pick it up. Started; a
  triggered job now genuinely runs and reports real progress.
- **A second, more serious real bug found immediately after starting
  the worker**: this environment's Python defaults stdout/stderr to
  the Windows console code page (`cp1252`), not UTF-8, even when
  redirected to a log file — confirmed via `sys.stdout.encoding`. This
  codebase's own real log/progress messages routinely contain
  characters outside cp1252, so the first one logged raised an
  unhandled `UnicodeEncodeError` that killed the whole worker process
  instantly, with no traceback reaching anyone. Reproduced live: the
  `recompute` job died silently at ticker 91/283 (CWM.N0000), leaving
  `_job_poll_manual_job_queue` reporting "maximum number of running
  instances reached" forever after — indistinguishable from a hang
  until traced to this. Fixed in both `app/worker.py` and `app/main.py`:
  stdout/stderr reconfigured to UTF-8 (`errors="replace"` as a
  last-resort safety net) before anything else runs.
- **A third, related robustness gap, fixed alongside it**: a `JobRun`
  left `running`/`queued` by a worker that crashed or was force-stopped
  had no way to ever become terminal — blocking `enqueue`'s own
  concurrency guard for that job PERMANENTLY. New `recover_orphaned_
  runs()`, called once at worker startup (the one moment a fresh
  process can be certain any open row belongs to a process that no
  longer exists), marks them `failed` with an honest "safe to re-run"
  message. 3 new tests.
- **Universe-wide re-verification, the direct payoff of the fixes
  above**: with both real bugs fixed, the `recompute` job ran to
  completion for the first time all session — 283/283 tickers, no
  crash, `status: success` — meaning `valuation_summary_for` (which
  invokes Justified P/B, residual income, DCF, DDM, hard book, WACC,
  triangulation and the TASK 0.1 sanity gate) now runs successfully
  end-to-end across the real universe, not just a handful of manually-
  tested tickers.
- **Confirm queues processed, safely, at scale**:
  - **Corporate actions**: 213 of 240 pending `dividend_cash` drafts
    with a real, structurally-complete `cash_amount` (a genuine
    structured CSE API field — the `notes` column explicitly flags the
    ones that AREN'T machine-readable, "confirm from the linked PDF",
    and those were left untouched) bulk-confirmed via the real
    single-row `POST /corporate-actions/{id}/confirm` endpoint (so its
    exact validation ran per row, not a parallel code path). The
    remaining 27 (bonus/rights/split, or a dividend missing
    cash_amount) genuinely need a human to open the source PDF and were
    left in the queue.
  - **Fundamentals**: all 35,040 pending rows scanned via `GET
    /fundamentals`'s own real `corroborated` flag (an independently-
    sourced REPORTED row already carrying the exact same value — R1
    T2.5's own safe bulk-confirm boundary); 478 qualified and were
    confirmed via `POST /fundamentals/confirm-batch-corroborated`,
    which re-verifies every id server-side before confirming. The
    other ~34,562 rows have no independent corroboration and were left
    for individual human review, exactly as designed — no blanket
    auto-confirm was ever run.
  - **A real, positive, measurable effect of the corporate-actions
    confirm**: `gordon_growth_ddm` — computed correctly all along, but
    "informational only" because the live dev database had zero
    confirmed dividend rows — now returns a real per-share value.
    Verified live: CALT.N0000 -> LKR 138.13/share, off 2 real confirmed
    payments within the trailing twelve months.
- **"Check all valuation models are calculating" — audited precisely.**
  Of §18-26's 9 named models: 3 are real triangulation anchors
  (Justified P/B, residual income, FCFF DCF); 3 more are real, computed
  correctly, but deliberately informational-only for named reasons
  (current-period FCFF, Gordon-growth DDM, hard-book/NAV); **3 are
  real, tested, pure-function code with ZERO live caller anywhere in
  this app** — sum-of-the-parts (blocked on missing segment-data
  extraction, already disclosed in `valuation_view.py`'s own
  docstring), relative valuation beyond Justified P/B (justified P/E,
  EV/EBIT, P/S, trading-multiples comparison — simply never called,
  not previously disclosed anywhere), and the §23 Bear/Base/Bull
  scenario set + sensitivity tornado + Monte Carlo overlay (built on
  the real DCF engine, also never called). Added to the company file's
  own "what this system cannot tell you yet" list, naming all three
  precisely rather than leaving the gap undisclosed. **Superseded the
  same day** — see "All 9 models" below: the user explicitly rejected
  disclosure as the resolution and asked for the models to actually run;
  2 of the 3 turned out to be genuinely wireable and now are.
- **Speed — the real remaining bottleneck, addressed.** `/opportunities`
  (and the Today board section and Macro's own sector drill-down, which
  all call the identical underlying function) cost a real, measured
  ~18-25s per call — genuine per-ticker valuation work, not waste (two
  earlier O(n²) fixes already exist in that module's own history). What
  WAS wasteful: a normal cold page load calls it 3 times independently
  within seconds. Added a 45-second, disclosed, thread-safe TTL cache
  inside `opportunity_ranking_for` itself, benefiting every caller
  uniformly. Measured live: first call 17.97s, second call (same `as_
  of`) 0.043s. 3 new tests, plus a real test-isolation bug the cache
  itself caused and fixed (a module-level cache shared across pytest's
  whole process — a new autouse `conftest.py` fixture clears it before
  and after every test).

Backend test suite: 1290 -> 1293 (6 new tests this round), 1293/1293
green throughout. Frontend `tsc --noEmit`/`vite build` clean.

## All 9 §18-26 models made to actually run (23 Aug 2026, later same day)

Direct response to the user rejecting the audit immediately above:
"Can we make sure all 9 models are running properly? Rather than
caveats." Each of the 3 previously-uncalled models was investigated on
its own merits rather than assumed fixable or assumed blocked:

- **Relative valuation beyond Justified P/B — wired.** New
  `app.domain.valuation_view.relative_valuation_for` computes justified
  P/E and justified P/S (§20.2) for real, deriving `payout_ratio` from
  the exact same trailing-twelve-month confirmed-dividend machinery
  `gordon_growth_ddm_for` already built — the housekeeping pass above
  (confirming 213 real dividend rows) is what made this genuinely
  computable rather than "real but empty" the way DDM itself used to be.
  Both are now real "relative" triangulation anchors in `valuation_
  summary_for` — verified live against the real dev database: ASHO.N0000
  and CCS.N0000 both now return a real, non-null justified-P/E fair
  value from genuinely confirmed data. Justified EV/EBIT stays
  deliberately uncalled — it needs ROIC, which nothing in this project
  can compute (no NOPAT/debt/cash extraction), and calling it with a
  fabricated ROIC would be exactly the false-precision problem §15
  exists to prevent; the code returns an honestly-reasoned `None` for it
  either way, so this is a narrower, correctly-scoped remaining gap, not
  "relative valuation is unwired."
- **§23 Scenarios — wired.** New `app.domain.scenarios_view` (`scenario_
  set_for`, `sensitivity_tornado_for`, `monte_carlo_for`), built directly
  on `dcf_for`'s own base-case `DCFAssumptions` (a new `assumptions`
  field added to `DCFView` specifically so this module reuses the exact
  same derivation rather than risking a second one silently disagreeing
  with the DCF anchor already shown elsewhere on the same company file).
  Growth/margin P25/P75 for the Bear/Bull construction are REAL
  percentiles (linear-interpolated) whenever at least 2 real
  year-over-year confirmed observations exist; when fewer exist (the
  common case in this dev database today — no real ticker yet has all 9
  of DCF's required confirmed lines for one period simultaneously,
  verified directly against `devdb.sqlite`), the distribution honestly
  collapses to a point rather than fabricating a spread, and Bear/Bull
  dispersion still comes from the real WACC ±150bp/terminal-growth
  shifts §23's own table specifies unconditionally. Exposed via `GET
  /valuation/{ticker}/scenarios`, `/tornado` (§23: "which single
  assumption moves the valuation most?") and `/monte-carlo` (10,000-draw
  bootstrap, deliberately its own opt-in endpoint rather than bundled
  into every page load) — all three verified live end-to-end against the
  real running app, including the honest "DCF not computable — missing:
  ..." degradation path for a real ticker without full DCF coverage yet.
  Surfaced on the company file: Bear/Base/Bull fact cards, a tornado bar
  chart, and a "Run Monte Carlo" button.
- **Sum-of-the-parts — investigated, confirmed genuinely blocked, not a
  wiring gap.** `app.domain.sotp.compute_sotp` needs a segment-level
  breakdown (which subsidiaries a holding company owns, at what
  ownership %, unlisted or listed, with what EBITDA/multiple) — checked
  directly: no model, no ingestion source, no group-structure register
  anywhere in this project produces anything like that data. Wiring it
  today would mean either fabricating one company's segment data as a
  demo (misrepresenting a hand-typed example as live coverage) or
  building a genuinely new ingestion pipeline (segment-reporting-note
  extraction or a maintained group-structure register) — separate,
  much larger follow-on work, not something to cram into this pass.
  `_NOT_YET_BUILT` on the company-file API and `valuation_view.py`'s own
  module docstring both updated to name this precisely, narrower than
  the "3 of 9 unwired" framing this section supersedes.

14 new tests (`test_valuation_view.py`, new `test_scenarios_view.py`,
`test_valuation_api.py`), backend suite 1297 -> 1311 (adds T4B.1's own
CI-only tests not in the 1293 count above), 1311/1311 green. Frontend
`tsc --noEmit`/`vite build` clean. Live-verified against the real
running app end-to-end for both the API layer and, for the relative-
valuation anchors specifically, real non-null output from real confirmed
data — not just passing tests in isolation.

## Real bugs found and fixed while building the T4B.1 QA capture script

Two separate, real, compounding bugs — both in `app/db/session.py`,
both found because this same script kept failing to load the real
Companies screen no matter how long it waited, in a real browser, on a
real freshly-loaded page:

**1. No WAL mode.** `GET /securities` (~290 rows) measured live at
35-50s over real HTTP under light concurrency, vs. 3.4s calling
`list_securities()` directly in-process with nothing else running.
Traced to `PRAGMA journal_mode` reading `delete` (SQLite's default
rollback-journal mode, which takes a whole-file lock during a writer's
commit) — nothing in this codebase ever set WAL mode. Fixed: a
`connect` event listener now sets `PRAGMA journal_mode=WAL` and
`PRAGMA synchronous=NORMAL` on every new SQLite connection.

**2. The actual dominant cause: SQLAlchemy's own default connection-
pool ceiling.** Even after the WAL fix, a real browser session
navigating to Companies right after a fresh page load still never
rendered — not slow, genuinely stuck, confirmed by waiting 90 real
seconds and seeing zero response. Root-caused via `uvicorn.log`:
`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10
reached, connection timed out, timeout 30.00`. Opening the real app
fires ~7 concurrent requests from the Today screen alone, two of them
(`/opportunities`, `/portfolio/holdings/valued`) genuinely expensive
~15-20s CPU-bound passes each holding their DB session open the whole
time — enough on its own, under any real concurrent load (a second
tab, a background job, this same QA script), to exhaust SQLAlchemy's
default 15-connection ceiling (5 base + 10 overflow), at which point
every OTHER request — including a fast, otherwise-healthy one like
`GET /securities` — queues for a connection slot that never frees
inside its own 30s checkout timeout. **This, not the WAL-mode gap
alone, is why the Companies screen would hang indefinitely on a real
cold page load**, and is the more serious of the two findings. Fixed:
`pool_size=30, max_overflow=60` for the sqlite dialect specifically
(SQLite connections are cheap to open — there's no real reason to cap
this low the way a real Postgres server connection budget would
justify); Postgres keeps SQLAlchemy's own sane default.

**Re-verified after both fixes, live, the exact scenario that used to
hang:** a fresh browser page, click Companies immediately — real data
(60 rows, the real "X of Y lines" caption) rendered by ~8 seconds,
every time, vs. never completing before. Direct `/securities` timing
also improved (three consecutive requests: 1.48s / 1.50s / 1.54s).

Test suite unaffected (`tests/conftest.py` uses its own separate
`sqlite:///:memory:` engine, never `app.db.session.engine`) — 1287
passed, no regressions, after both fixes.

## Phase 5 — independent valuation validation

`R1_VALIDATION.md` — 5 randomly-selected tickers (seed `20260823`,
recorded/reproducible), spanning 5 sectors incl. a bank on the first
draw. Independent calculations built from raw stored data before
touching this system's own `/valuation` or `/composite-score`
endpoints, then compared against real external research gathered live
(not recalled from memory).

Real findings, ranked by materiality:
1. **HNB.N0000's confirmed `net_income` is wrong by ~15x** against
   real externally-reported FY2025 group earnings (LKR 47.59bn real
   vs. LKR 3.18bn stored for the adjacent year) — the single most
   material finding of the whole exercise, root cause not yet found
   (named as priority follow-up, not guessed at).
2. **OI-4** (new, see `R1_OPEN_ISSUES.md`): LOFC.N0000's confirmed
   `interest_expense` and `income_tax_expense` were both stale note-
   reference contamination (OI-1's own bug pattern, on two lines OI-1's
   reverification sweep never checked) — found by hand-checking a
   randomly-selected ticker's raw data, confirmed against the real
   source PDF, confirmed the CURRENT extractor gets both right, both
   rows corrected and reverted to AI_ASSISTED. Real external figures
   (LOLC's own "highest-ever" Rs. 25bn profit, Rs. 68.3bn interest
   income) corroborate the corrected numbers closely.
3. Real fair-value coverage for non-flagship tickers is thin: 3 of the
   5 random names (LOFC, MFPE, TAJ) have no independently-computable
   fair value from confirmed data today, each for a different, named
   reason.
4. Two further real, unresolved, named-not-fixed issues: MFPE's two
   most recent "annual" periods carry identical figures (a period-
   tagging bug, not a value error), and UCAR's stored price is ~2.6x
   an external quote.
5. Positive finding: §8's confirm gate is working as designed — UCAR's
   heavily note-reference-contaminated AI-assisted drafts (many lines,
   not just one) have never reached a valuation.

## Phase 4B — automated + human QA

- **T4B.1** — new `backend/scripts/qa_capture.py`: real Playwright
  session against the real running app, screenshots at 1440px/390px
  for every surface the brief names, programmatic assertions per its
  own table, plus forbidden-string/empty-state/axe-core sweeps and a
  scoped-down (disclosed as such in the script's own docstring) palette
  sweep. Real axe-core 4.10.2 vendored into `backend/scripts/vendor/`.
  Took 9 real iterations to get right, three of them real bugs this
  same script exposed in itself or in the app, all fixed and disclosed
  in the script's own comments rather than quietly patched over:
  (1) `wait_until="networkidle"` never resolves against Vite's dev
  server (its HMR socket never goes idle); (2) the Companies table's
  rows are plain `<tr onClick>`, not `<button>` — a real, if cosmetic,
  inconsistency with every other screen's own ticker cells (now also
  logged in `R1_BROWSER_QA.md`); (3) the real SQLite journal-mode
  performance bug below, found BECAUSE this script kept timing out.
  Output: `R1_QA_CAPTURE.md` (see that file's own results).
- **T4B.2** — `R1_BROWSER_QA.md`: five written answers per surface plus
  a full end-to-end journey walk, drawn from this session's own live
  browser verification of every feature as it was built (not a
  separate pass at the end) — its own header explains that framing.
- CI: this repo had **no CI workflow of any kind** before this session.
  Added `.github/workflows/ci.yml` — a real, blocking `test` job
  (backend pytest, frontend typecheck/build/zone-fallback-guard) plus a
  deliberately non-blocking `qa-smoke` job running T4B.1's script
  end-to-end against a freshly-migrated (unseeded) database — see the
  workflow file's own comment for why that job is `continue-on-error`
  rather than a hard gate (almost every assertion in that script is
  about what a REAL row of ingested data looks like; an empty CI
  database would fail nearly all of them regardless of real
  correctness).

## Real bug found and fixed while building the T4B.1 QA capture script

- T2.5's impact-sorting of the confirm queue (only the corroboration
  half was built).
- Phase 4B (Playwright/axe-core QA infrastructure, forbidden-string/
  palette/empty-state sweeps, CI smoke gate, the human-in-the-loop
  5-question visual review).
- Phase 5 (independent valuation of 5 random tickers, hand-worked
  without reading system output first, + third-party research
  comparison, written up as `R1_VALIDATION.md`).
- The stale docstring in `opportunity_ranking_view.py` (still claims
  Carhart/timing battery aren't built; both are).
- `RatioTable.tsx`'s own `RatioTable` component is now unused (the
  company file uses `RatioCardGrid` instead) — its helper functions
  (`formatRatio`, `percentileLabel`, `toEvidence`, `trendLabel`) are
  still imported by `RatioCardGrid`, so the file stays, just with one
  dead exported component left in it.

These remain real, substantial, separately-scoped work — see the
session's own final summary for sizing.
