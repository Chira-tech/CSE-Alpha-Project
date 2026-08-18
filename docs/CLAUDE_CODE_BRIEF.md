# Work Brief — CSE Alpha Engine

**For: Claude Code.** Execute in the order given. Do not skip P0.

Each task has a **Plain English** block (for the product owner) and a
**Spec** block (for you). Acceptance criteria are testable — write the test
before the fix where one is named.

Reference: `Master Specification v2.0` section numbers appear as §N.

---

## Part 0 — Read this first: the single root cause

**Plain English.** Twelve things look broken. Eleven of them are the same
thing wearing different hats: **the database only has enough data for two
companies.** Composite score, coverage tier, sector percentiles, integrity
veto, price ladder, macro sector fit — none of these are missing features.
They are all features that *cannot run until more companies have financial
statements loaded*. Fixing the data breadth switches most of them on at once.

The exception is the one real bug, which is P0 below.

**Spec.** Do not build new analytics until Part 5 (data breadth) is done.
Building more analytics on a 2-company universe produces code you cannot
test and metrics that cannot be computed. The correct order is:
P0 correctness → P1 operability → P2 UI → P3 data breadth → analytics.

---

## P0 — A wrong number is on screen right now

### TASK 0.1 · COMB.N0000 fair value is almost certainly broken

**Plain English.** The screen currently shows Commercial Bank at LKR 205.75
with a fair value of LKR 93.06 — and labels it **Exit**. That is telling you
to sell a large, liquid bank because it is supposedly worth less than half
what it trades at. A result like that on a major bank is not an insight; it
is a broken input. If you acted on it you could sell a good holding for no
reason. **This is the most dangerous kind of failure a system like this can
have: not a crash, but a confident wrong answer.**

Most likely causes, in order of probability:

1. **Voting vs non-voting shares.** COMB has two share classes. If share
   count is total-issued but price is the voting line (or vice versa),
   per-share value is wrong by roughly the class ratio.
2. **Book value per share wrong** — total equity divided by the wrong share
   count, or equity taken in thousands while shares are in millions.
3. **ROE below cost of equity.** With Rf at ~10.2%, Ke for a bank lands near
   17%. If the extracted ROE is understated, residual income goes negative
   and the model correctly returns a sub-book value — from a wrong input.
4. **Statement units mismatch** — LKR '000 vs LKR mn between line items.

**Spec.**

Add `api/valuation/sanity.py` with a plausibility gate that runs on **every**
valuation before it is persisted or displayed:

```python
SANITY_RULES = [
    # (name, predicate, severity)
    ("fv_within_5x_price",      lambda v, ctx: 0.2 <= v / ctx.price <= 5.0,     "block"),
    ("bvps_positive",           lambda v, ctx: ctx.bvps > 0,                     "block"),
    ("share_count_reconciles",  lambda v, ctx: abs(ctx.mcap / (ctx.price * ctx.shares) - 1) < 0.02, "block"),
    ("roe_plausible",           lambda v, ctx: -0.5 < ctx.roe < 0.6,             "block"),
    ("units_consistent",        lambda v, ctx: ctx.equity / ctx.total_assets < 1.0, "block"),
    ("fv_within_2x_price",      lambda v, ctx: 0.5 <= v / ctx.price <= 2.0,     "warn"),
]
```

Behaviour on failure:

- **block** → do **not** publish a fair value or a price ladder for that
  ticker. Persist a `valuation_quarantine` row with the failed rule and the
  offending input values. UI shows: *"Fair value withheld — share count does
  not reconcile against market cap. Check: voting vs non-voting share
  classes."* This obeys §1 law 3 (never invent) and law 4 (never a black box).
- **warn** → publish, but attach a visible caution chip and the rule name.

Then fix COMB specifically:

- Add `share_class` and `shares_outstanding_by_class` to the securities table.
- Add a `units` field on every extracted statement line (`LKR`, `LKR_000`,
  `LKR_mn`) and normalise on read, never on write.
- Add the market-cap cross-check as a nightly data-quality check
  (Phase 1 guide §9): `mcap / (price × shares)` outside 0.98–1.02 → alert.

**Acceptance:**
- `test_sanity_blocks_implausible_bank_valuation` — a fixture with COMB's
  numbers returns *no* fair value and *no* ladder, plus a named reason.
- `test_sanity_allows_ntb` — NTB at 1.11× price publishes normally.
- No ticker in the live UI shows a ladder without passing all `block` rules.

---

### TASK 0.2 · Never display a zone derived from a withheld valuation

**Plain English.** Right now if the fair value is wrong, the zone label
("Exit", "Fair") is wrong with it — and the zone is what a person actually
reads. The label must disappear whenever the number behind it is not
trustworthy.

**Spec.** `zone` becomes `Optional[str]`. Null zone renders as the literal
string `Not yet valued` with a `why` tooltip. No placeholder zero anywhere
(§1 law 3). Grep guard in CI: no component may render `zone ?? 'Fair'` or
any default-substitution on a valuation field.

---

## P1 — You cannot see the worker, and cannot run it yourself

### TASK 1.1 · Manual "Run Capture" control

**Plain English.** You want a button, low in the left sidebar, that fetches
fresh data on demand instead of waiting for the scheduled run. You also want
to *see* it working — right now the app gives no sign that anything is
happening behind the scenes.

Important constraint: the capture takes minutes, not seconds (286 tickers at
≥2s pacing is ~10 minutes). So the button must **start a background job and
return immediately**, then stream progress. A button that freezes the page
for ten minutes is worse than no button.

**Spec.**

Backend — `api/jobs/`:

```python
# jobs/registry.py
JOBS = {
  "capture_prices":    {"label": "EOD prices",        "est_seconds": 45},
  "capture_orderbook": {"label": "Order book spread", "est_seconds": 600},
  "capture_market":    {"label": "Market P/E + ASPI", "est_seconds": 20},
  "capture_macro":     {"label": "CBSL macro series", "est_seconds": 30},
  "capture_filings":   {"label": "New filings",       "est_seconds": 120},
  "recompute":         {"label": "Rebuild valuations","est_seconds": 60},
  "capture_all":       {"label": "Full capture",      "est_seconds": 900},
}
```

```sql
CREATE TABLE job_runs (
  id            bigserial PRIMARY KEY,
  job           text NOT NULL,
  trigger       text NOT NULL,          -- 'manual' | 'scheduled'
  status        text NOT NULL,          -- queued|running|success|failed|cancelled
  started_at    timestamptz,
  finished_at   timestamptz,
  progress_pct  numeric DEFAULT 0,
  progress_note text,
  rows_written  int DEFAULT 0,
  error         text,
  config_hash   text
);
CREATE UNIQUE INDEX one_running_per_job ON job_runs (job)
  WHERE status IN ('queued','running');   -- concurrency guard, enforced by DB
```

Endpoints:

| Method | Path | Behaviour |
|---|---|---|
| `POST` | `/api/jobs/{job}/run` | Enqueue. Returns `202 {run_id}`. Returns `409` if already running — never queue a duplicate. |
| `GET` | `/api/jobs/status` | All jobs: last run, current status, progress, next scheduled time |
| `GET` | `/api/jobs/{run_id}/stream` | SSE stream of progress + log lines |
| `POST` | `/api/jobs/{run_id}/cancel` | Cooperative cancel; scraper checks a flag between tickers |

Execution rules — these are not optional:

1. Run in the **worker process**, never in the API request handler.
2. Keep the ≥2s pacing and the circuit breaker. A manual trigger does **not**
   get to go faster. Rate-limit manual runs to **once per 15 minutes per job**;
   the UI shows the cooldown remaining rather than erroring.
3. Every run writes a `job_runs` row whether it succeeds or fails.
4. `capture_all` runs sub-jobs sequentially and reports which one it is on.

Frontend — sidebar, bottom section, below a divider:

```
─────────────────────────
DATA
  ● Prices        2m ago
  ● Order book    4h ago
  ▲ Macro         3d ago      ← ochre when older than expected
  ● Filings       1d ago

  [ Run Capture ▸ ]
  Last full run: today 06:00
```

- `Run Capture` opens a small menu: individual jobs plus **Run everything**.
- While running, the button becomes a progress bar with the current note
  (*"Prices · 148 / 286 tickers"*) and a **Cancel** link.
- Progress uses the existing SSE stream. On completion, invalidate the query
  cache so the screens refresh with new data — do **not** force a page reload.
- Freshness dots use `--pos` / `--caution` / `--neg` tokens with a glyph, per
  UI spec §2.3 — colour is never the only signal.

**Acceptance:**
- `test_manual_run_returns_202_and_run_id`
- `test_concurrent_run_returns_409` — second POST while running is rejected
- `test_manual_run_respects_pacing` — assert ≥2s between outbound calls even
  when manually triggered
- `test_cooldown_enforced` — second manual run within 15 min returns 429 with
  `retry_after`
- E2E: click Run Capture → progress appears within 2s → page never blocks

---

### TASK 1.2 · Data Health screen (UI spec §13, Screen 9)

**Plain English.** The button tells you *that* something ran. This screen
tells you whether the data is any good. It is the screen you check when a
number looks wrong.

**Spec.** New route `/data`. Four panels:

1. **Source freshness** — per source: last successful fetch, expected
   interval, row count, status. Ochre when stale (§5.4).
2. **Job history** — last 20 `job_runs`, with duration, rows written, errors.
3. **Quarantine** — tickers excluded by reconciliation or by the new
   `valuation_quarantine` (Task 0.1), each with its reason and a re-check
   button.
4. **Coverage counters** — the single most useful number in the whole app
   right now:

```
286 listed
 ├─ 2    have financial statements loaded     ← the actual bottleneck
 ├─ 2    have a triangulated fair value
 ├─ 0    have a composite score
 └─ 284  awaiting statement extraction
```

Put this counter block on the **Today** screen too, until it reads above 150.
It reframes every "missing feature" as a progress bar, which is the honest
representation.

---

## P2 — UI fixes you asked for

### TASK 2.1 · Pagination

**Plain English.** Lists should show a manageable chunk with a "show more"
button, not everything at once and not just two rows.

**Spec.**

| Surface | Page size | Control |
|---|---|---|
| Today → Ranked opportunities | **5** | `Show 5 more` — appends, does not paginate away |
| Opportunities tab | **20** | `Show 20 more`, sorted best rank first |
| Company → price history | **10 days** | `Show 10 more` — appends older rows |

Rules: server-side `limit`/`offset` on all three; never `Load more` that
re-fetches rows already shown; preserve scroll position on append; when
fewer rows exist than the page size, state it plainly (*"2 of 2 companies
currently rankable — 284 awaiting data"*) rather than showing an empty-looking
list. That message is important: it stops a data gap looking like a bug.

---

### TASK 2.2 · Portfolio — exit price and overvaluation

**Plain English.** For shares you already own, you want the screen to answer
two questions directly: *what price should I sell at*, and *is the market
price currently too high?*

**Spec.** Extend the portfolio row. All fields already exist in the engine
(`decision.py`) — this is display work, not new maths.

```
Holding      Cost    Now     P&L      Zone    Exit plan            Thesis
COMB.N0000   184.20  205.75  +11.7%   Trim    Trim from 210.00     intact
                                              Exit above 241.50
                                              14% above fair value
```

Per holding show:

- `trim_above` = fair value (start scaling out)
- `exit_above` = fair value × 1.15 (stretch)
- **Overvaluation** = `(price / fair_value) - 1`, worded plainly:
  *"14% above fair value"* / *"22% below fair value"*
- **Nearest exit trigger** from `exit_triggers()` (§28) — which of the five
  is closest and how far away
- Thesis status from the drift monitor (§42): intact / weakening / broken

Two rules:

1. If the ticker is in valuation quarantine (Task 0.1), show
   *"Exit plan unavailable — fair value withheld"*. **Never** show an exit
   price derived from a number that failed sanity.
2. Sort the portfolio by **nearest trigger**, not by P&L. What needs
   attention first is not the same as what has gained most.

---

## P3 — The unblock: data breadth

### TASK 3.1 · Get statements loaded for 150+ companies

**Plain English.** This is the bottleneck behind almost everything else on
your list. Until companies have financial statements in the database, the
system cannot compute ratios, cannot rank them against their sector, cannot
run the integrity checks, and cannot value them. Nothing else you build will
help until this is done.

Realistically this is the boring, heavy part — extracting numbers from PDF
annual reports and confirming them. Budget for it honestly: roughly 8 minutes
per filing, and you want two annual reports plus four quarters for the top
150 names. That is real work, not a weekend.

**Spec.** Build the extraction pipeline from Phase 1 guide §10:

1. `capture_filings` job downloads filing PDFs, hashes, stores locally, and
   records `announce_datetime` as `first_available_date` (the PIT anchor).
2. `pdfplumber` table extraction → candidate line items.
3. LLM maps candidates to a **fixed chart of accounts** (~60 line items,
   plus banking and insurance variants). Returns value + page number +
   verbatim snippet + confidence. Written with provenance `A`.
4. **Confirmation queue UI** — side-by-side page image and extracted value,
   one keystroke to confirm. This screen is where data quality actually
   happens; make it fast to use.
5. Promotion to provenance `R` on confirm. **An `A`-tier value must never
   enter a valuation** (§8).

Prioritise the queue: coverage tier, then market cap, then recency. Start
with the top 50 by market cap — that is where your capital can actually go.

**Acceptance:**
- `test_ai_tier_cannot_enter_valuation` — a valuation attempted on unconfirmed
  data raises, and does not silently skip the line
- `test_units_normalised_on_read` — LKR '000 and LKR mn statements produce
  identical ratios
- Coverage counter on Data Health reads ≥150 with statements

---

### TASK 3.2 · Full-universe computations (unblocks 4 list items)

**Plain English.** Some numbers can only be worked out by comparing every
company at once — for example "is this ROE good *for a bank*". These simply
cannot exist while only two companies have data. Once Task 3.1 is done, this
switches on sector percentiles, coverage tiers, the composite score and the
integrity veto together.

**Spec.** Nightly batch, in this order:

1. `liquidity_metrics` — 60-day turnover, days traded, Amihud,
   `median_spread_pct_20d` (needs the order-book job running daily; this is
   the input you cannot backfill)
2. `coverage` — the three gates → tier (§11)
3. `sector_percentiles` — every ratio ranked within archetype, winsorised
   1%/99% (§12)
4. `integrity` — Beneish, Sloan, related-party, auditor flags → veto (§14)
5. `composite` — pillars, regime tilt, veto applied (§38)

Guard: each step **skips gracefully** with a named reason when its inputs are
missing, and records that reason. The UI then says *why* a score is missing
instead of showing a blank.

---

### TASK 3.3 · The hero spread

**Plain English.** The main chart on the home screen compares what shares
earn against what a Treasury bill pays. It needs a market-wide P/E, which
needs earnings for most of the market — so it is blocked by Task 3.1 too.

**Spec.** `capture_market` already exists. After Task 3.1:

- `market_earnings_yield` = aggregate normalised earnings ÷ aggregate market
  cap, computed over the **Core tier only** (not all 286 — illiquid junk
  distorts it).
- Spread = `market_earnings_yield − rf_364d`, series stored daily.
- **Until ≥100 Core names have earnings, do not draw the chart.** Show:
  *"Hero spread available once 100 Core companies have earnings loaded —
  currently 2."* A spread computed from two banks is not a market signal, and
  drawing it would be worse than drawing nothing.

---

### TASK 3.4 · Regime gauge on the home screen

**Plain English.** The regime classifier already works — you can see it in
the Journal. What is missing is the dashboard gauge showing recommended
exposure and sector tilts.

**Spec.** Two parts, and be honest about which is which:

**Buildable now** — the gauge itself: three-segment arc, probability needle,
recommended gross exposure from the regime band (§31), current vs recommended
exposure from the portfolio. Risk-Off renders **slate, not red** (UI spec §2.3).

**Not buildable yet** — the ARDL error-correction half-life and per-sector
tilts need a longer macro history than the database holds. Do not fake these.
Render the panel with a stated requirement:
*"Error-correction half-life needs 60+ months of macro history — currently 8.
Accumulating."* Add a months-of-history counter so the wait is visible.

---

### TASK 3.5 · Per-company macro sensitivity (`sector_fit`)

**Plain English.** The system knows how a *sector* reacts to interest rates
or currency moves. It does not yet know how *one company* reacts — a company
that exports and a company that imports sit in the same sector but move in
opposite directions.

**Spec.** Compute `sector_fit` per ticker from company-specific exposures,
not sector membership alone:

```
sector_fit = w1 · sector_beta_to_current_regime      (from §33 matrix)
           + w2 · fx_exposure_score                  (unhedged FX debt ÷ total debt,
                                                      export revenue share)
           + w3 · rate_sensitivity                   (net debt / EBITDA, floating share)
           + w4 · project_register_exposure          (§34, confirmed projects only)
```

Blocked on §34 project register and on FX/segment lines from statements —
both from Task 3.1. Until then `sector_fit` is `None` and the composite
re-weights the remaining pillars rather than scoring a missing input as zero.
**Scoring a missing input as zero is a silent lie**; re-weighting is honest.

---

## Part 4 — Order of work

```
Week 1   0.1  sanity gate + COMB fix        ← wrong number on screen
         0.2  null zone handling
         1.1  Run Capture button + jobs
         1.2  Data Health screen

Week 2   2.1  pagination (5 / 20 / 10)
         2.2  portfolio exit prices
         3.3  hero-spread gate message
         3.4  regime gauge (buildable half)

Week 3+  3.1  statement extraction  ← THE BOTTLENECK. Start the confirmation
              queue immediately and work it daily.
         3.2  full-universe batch (switches on 4 items at once)
         3.5  sector_fit
```

---

## Part 5 — Standing rules for every task above

These come from `Master Specification v2.0` §1 and are non-negotiable.

1. **Never display a number you cannot defend.** Withheld beats wrong. Every
   gap states its own reason and what would fill it.
2. **Never substitute a default** for a missing valuation field. No `?? 0`,
   no `?? 'Fair'`. CI greps for this.
3. **AI-extracted values cannot enter a calculation** until human-confirmed.
4. **Manual triggers do not bypass rate limits.** Same pacing, same circuit
   breaker, plus a cooldown.
5. **Missing inputs re-weight the composite; they never score as zero.**
6. **No verdict field, no BUY button** — including in the new portfolio exit
   panel. It shows prices and triggers, never an instruction.
7. Every new number added to the UI carries a provenance chip and an
   `as of` timestamp.
