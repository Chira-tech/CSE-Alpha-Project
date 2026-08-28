# CLAUDE_CODE_BRIEF_M5.md

**Module:** M5 — Convergence Engine & Playbook System
**Companion spec:** `CSE Alpha Engine - M5 Convergence Engine v1.0.pdf`
**Design system:** `CSE Alpha Engine - UI and Experience Specification v1.0.pdf`
**Date:** 21 August 2026

---

## 0. READ THIS FIRST — THE PRIME DIRECTIVE

This module is **strictly additive**. The existing CSE Alpha Engine is running and must not
be disturbed in any way.

**Hard rules. Violating any of these fails the task.**

1. **No file outside `backend/m5/`, `frontend/src/features/playbooks/`, and the two
   allowlisted config lines in §1.3 may be modified.** If you believe an existing file must
   change, STOP and raise it rather than changing it.
2. **M5 never writes to any existing table.** All writes go to the `m5` schema.
3. **M5 never modifies a shared frontend component.** It imports design tokens and
   primitives read-only.
4. **M5 can only narrow the investable set, never widen it.** Every entry condition
   includes "all existing gates and vetoes pass". M5 has no power to unlock anything.
5. **M5 emits candidates. It never captures a decision, sizes an order, or places a trade.**
   It hands off to the existing Decision Card.
6. **With `M5_ENABLED=false`, the application must be byte-identical in behaviour to today.**

---

## 0.5 DECISIONS TAKEN — 21 Aug 2026 (these override the PDF spec)

### D1 · Panel history starts ~2020. This shrinks the grid.

Clean statements go back to roughly 2020, giving ~6.5 years. Recomputed effective sample:

```
130 names × 6.5 years                = 845 non-overlapping stock-years
÷ cross-sectional correlation (~16 effective clusters)
                                     ≈ 104 effective observations (12m horizon)
spread across 12 primary states      ≈ 6–9 per state  ← BELOW the display floor of 8
```

**Four consequences. Implement all of them.**

**(a) Collapse the primary grid from 4×3 to 3×3 (12 states → 9).**
Merge `Fair` and `Rich` into a single `Not cheap` level. You never buy those states, so
splitting them burns sample on cells you will never act on.

```
VALUATION GAP (revised)
  Deep        price ÷ fv ≤ 0.70
  Moderate    0.70 – 0.90
  Not cheap   > 0.90          ← replaces Fair + Rich
```

**(b) 6-month becomes the PRIMARY validation horizon; 12-month is secondary.**
Halving the horizon roughly doubles non-overlapping windows (13 vs 6.5), lifting effective
N to ~13–18 per state. Compute and display both. Promotion gates read 6m where 12m is
insufficient, and the playbook card must state which horizon validated it.
Bootstrap `block_months` still always equals the horizon under test.

**(c) Max stacked modifiers drops from 2 to 1** until panel depth ≥ 8 years equivalent.
Make this a config value `M5_MAX_MODIFIERS` that auto-relaxes to 2 when the panel crosses
the threshold. The refusal message stays the same.

**(d) Asymmetric backfill — go deeper on the large caps.**
Backfill the top ~60 names by market cap to 2015–2017 where annual reports exist, and the
remainder to 2020. An unbalanced panel is fine; the base rate engine must handle it and
must report per-state date coverage. This buys back regime observations cheaply.

**(e) PB-04 Regime Rotation cannot be validated yet.** A 2020 start contains roughly two
regime turns. Register it, run it, and expect it to return `InsufficientEvidence` at the
gate stage. **Do not tune it to pass.** Mark it `AWAITING_HISTORY` and revisit in 2028.

**(f) Reordering: Task 2 (forward panel) is now higher priority than Task 3 (backfill).**
With a shallow history, forward accumulation is the binding constraint on this module's
future value. Every week the snapshot is not running is a week of proprietary data
permanently lost. Ship Task 2 first, then backfill in the background.

### D2 · CGT on listed shares = 0% (exempt), unconfirmed

Set `TAX_CGT_LISTED = 0.0` with `TAX_CGT_LISTED_CONFIRMED = false`.

Three requirements:

1. The System settings page shows an **unconfirmed** badge with the date the assumption
   was set. Reuse the existing provenance badge styling (`Estimated` treatment).
2. **Every playbook gate report runs twice** — once at 0% and once at 15% — and the card
   displays both net expectancies. If a playbook passes at 0% and fails at 15%, render
   `⌁ TAX-SENSITIVE` on the card. Expect PB-03 Catalyst Convergence to trip this.
3. Dividend withholding tax at **15% is confirmed and separate** — apply it to all
   dividend income. This materially affects PB-06 Dividend Reset; do not skip it because
   CGT is zero.

### D3 · Shadow book = 2 quarters, plus a zero-cost holdout that runs first

Historical data **cannot** substitute for the shadow book, and the distinction matters:

| | Uses historical data | Measures |
|---|---|---|
| **Backtest** (Gates 1–10) | Yes | Whether the edge existed |
| **Holdout replay** (new — see below) | Yes | Whether the edge survives out-of-sample and realistic fills |
| **Shadow book** (2 quarters) | **No** | Whether *live implementation* matches backtest — signal latency, actual fills, real depth, your own behaviour |

A backtest always fills you at the price you assumed. That assumption is where backtested
strategies die, and only forward operation exposes it.

**Add Task 8b — Holdout replay.** Costs no calendar time and recovers most of the value early:

- Physically withhold the **most recent 6 months** of `m5.panel` from all development.
  Enforce with a `M5_HOLDOUT_AFTER` date in config that the backtester refuses to cross.
- After gates pass, replay those 6 months day-by-day as if live: signals generated on
  point-in-time data only, fills modelled against **actual recorded order book depth**,
  full friction, slippage and dividend WHT.
- A playbook that passes the backtest but degrades more than 40% in holdout replay does
  not advance to shadow.

**The 2-quarter shadow then runs in parallel with normal platform use**, not as a delay
after the build. Nothing is waiting on it except promotion to live capital.

---

## 1. TASK 1 — ISOLATION SCAFFOLD

**Goal:** prove the module cannot touch anything before writing any logic.

### 1.1 Database

```sql
CREATE SCHEMA IF NOT EXISTS m5;

CREATE ROLE m5_reader NOLOGIN;
GRANT USAGE ON SCHEMA public TO m5_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO m5_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO m5_reader;
-- explicitly NO insert/update/delete on public

CREATE ROLE m5_writer NOLOGIN;
GRANT ALL ON SCHEMA m5 TO m5_writer;

CREATE ROLE m5_service LOGIN PASSWORD :'m5_pw';
GRANT m5_reader, m5_writer TO m5_service;

ALTER ROLE m5_service SET statement_timeout = '30s';
ALTER ROLE m5_service SET lock_timeout = '5s';
```

The M5 service connects **only** as `m5_service`. It never uses the application's
primary connection string. Use a separate env var `M5_DATABASE_URL`.

### 1.2 File tree to create

```
backend/
  m5/
    __init__.py
    config.py            # M5-only settings, reads M5_* env vars
    db.py                # m5_service engine; NEVER imports app.db
    panel/
      builder.py         # Task 2
      backfill.py        # Task 3
    states/
      classifier.py      # Task 4
      definitions.py     # thresholds from Appendix A
    baserates/
      engine.py          # Task 5
      bootstrap.py
      nulls.py
    playbooks/
      registry.py        # Task 7
      definitions/       # one file per playbook, PB01..PB06
      evaluator.py
      lifecycle.py
    validation/
      trials.py          # Task 6
      walkforward.py
      dsr.py
      gates.py
    shadow/
      book.py            # Task 9
    api/
      router.py          # mounted at /api/v5
      schemas.py
    worker.py            # separate process, separate queue
    migrations/
frontend/
  src/features/playbooks/
    index.tsx            # lazy-loaded route
    LiveTab.tsx
    BaseRatesTab.tsx
    StudioTab.tsx
    TrackRecordTab.tsx
    components/
      StateGrid.tsx
      BaseRateCard.tsx
      TrialCounter.tsx
    api.ts
    types.ts
tests/
  m5/
  isolation/
```

### 1.3 The only two allowlisted edits to existing files

```
1. backend/app/main.py
   ONE line, guarded:
     if settings.M5_ENABLED:
         from m5.api.router import router as m5_router
         app.include_router(m5_router, prefix="/api/v5")

2. frontend/src/config/navigation.ts
   ONE conditional entry appended to the rail array, guarded by
   import.meta.env.VITE_M5_ENABLED
```

Nothing else. If anything else appears to need editing, stop and report.

### 1.4 CI gates to add (these are the deliverable, not an afterthought)

```python
# tests/isolation/test_m5_isolation.py

def test_m5_never_imports_app_write_paths():
    """No module under backend/m5/ may import the app's DB session,
    ORM models, or any repository/service that writes."""
    forbidden = ["app.db", "app.models", "app.repositories",
                 "app.services.write", "app.session"]
    for py in Path("backend/m5").rglob("*.py"):
        src = py.read_text()
        for f in forbidden:
            assert f"import {f}" not in src and f"from {f}" not in src, \
                f"{py} imports forbidden write path {f}"

def test_m5_contains_no_public_schema_writes():
    pattern = re.compile(
        r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(public\.)?(?!m5\.)",
        re.IGNORECASE)
    for py in Path("backend/m5").rglob("*.py"):
        assert not pattern.search(py.read_text()), f"{py} writes outside m5"

def test_only_allowlisted_existing_files_modified():
    """git diff against the pre-M5 tag must touch only m5 paths
    plus the two allowlisted lines."""
    ...

def test_app_unchanged_with_flag_off():
    """With M5_ENABLED=false the full existing suite passes and
    /api/v5/* returns 404."""
    ...
```

**Acceptance:** all four pass. Existing suite green with flag off and flag on.

---

## 2. TASK 2 — PANEL SNAPSHOT BUILDER

**Goal:** one nightly read from production into `m5.panel`. Everything downstream reads
only from here.

### 2.1 Schema

Use the full column list in the spec §2.3. Key points:

```sql
CREATE TABLE m5.panel (
  ticker            text        NOT NULL,
  as_of             date        NOT NULL,
  config_hash       text        NOT NULL,
  -- ... all valuation / fundamental / price / liquidity / macro / risk
  --     / catalyst columns per spec §2.3 ...

  -- FORWARD OUTCOMES — populated retrospectively ONLY
  fwd_ret_3m        numeric,
  fwd_ret_6m        numeric,
  fwd_ret_12m       numeric,
  fwd_ret_24m       numeric,
  fwd_excess_sector_3m  numeric,
  fwd_excess_sector_6m  numeric,
  fwd_excess_sector_12m numeric,
  fwd_excess_sector_24m numeric,
  fwd_excess_market_12m numeric,
  fwd_mae_12m       numeric,
  fwd_mfe_12m       numeric,
  months_to_fv_convergence integer,
  converged_flag    boolean,

  PRIMARY KEY (ticker, as_of)
);

-- THE MOST IMPORTANT OBJECT IN THE MODULE
CREATE VIEW m5.panel_pit AS
  SELECT ticker, as_of, config_hash,
         /* every non-fwd_ column, listed explicitly — do NOT use * */
  FROM m5.panel;

REVOKE ALL ON m5.panel FROM m5_service;
GRANT SELECT ON m5.panel_pit TO m5_service;
-- raw table access granted only to the baserates and backtest roles
```

### 2.2 Builder job

- Runs **after** the existing nightly batch signals completion. Subscribe to its
  completion event or poll a sentinel; do not run on a fixed timer that could overlap.
- Single transaction, read-only against `public`.
- Target < 10 minutes for the full universe.
- Idempotent: re-running for the same `as_of` upserts within `m5` only.
- Logs to its own stream. A failure alerts but **never** retries into market hours.

### 2.3 Forward-fill job

A separate weekly job populates `fwd_*` for rows whose horizon has now elapsed. It is the
only job with write access to those columns.

**Acceptance:** builder completes in < 10 min; zero queries against `public` during
market hours; selecting a `fwd_` column through `panel_pit` raises an error;
re-running produces no duplicate rows.

---

## 3. TASK 3 — HISTORICAL BACKFILL

Reconstruct `m5.panel` backwards as far as point-in-time data allows.

- Every row must respect `first_available_date`. Never use a fundamental value dated
  after the panel row's `as_of`.
- Where the valuation engine was not running historically, **re-run it** against
  point-in-time inputs at each historical date to generate `fv_blended`. This is
  expensive and it is the whole point — it is what creates the proprietary panel.
- Where inputs are insufficient, write NULL and set a `reconstructed_quality` flag.
  **Never impute.**

**Acceptance:** hand-verify 20 randomly chosen rows against source filings. Any row where
a value was available to the model before it was available to the market is a
blocking bug.

---

## 4. TASK 4 — STATE CLASSIFIER

Implement Appendix A exactly. Pure functions, no I/O, fully unit-tested against
**hand-worked reference values** — not against the code's own output.

```python
def classify_primary(row) -> PrimaryState:   # one of 12
def apply_modifiers(state, modifiers) -> StateKey
```

Enforce the two-modifier limit in the **query layer**, not the UI:

```python
if len(modifiers) > 2:
    raise TooManyModifiers(
        "Maximum 2 modifiers. Additional slicing reduces effective "
        "sample size below the reliability threshold."
    )
```

**Acceptance:** every panel row maps to exactly one primary state; a third modifier is
rejected with that message; unit tests use hand-computed expected values.

---

## 5. TASK 5 — BASE RATE ENGINE

Compute the statistics in spec §4.1 for every state and permitted state+modifier combo.

### 5.1 Block bootstrap — do not substitute a simpler method

```python
def block_bootstrap(panel, state_key, horizon, n_reps=2000,
                    block_months=12):
    """Resample contiguous 12-month blocks with replacement.
    Within each sampled block take ALL observations in the state,
    preserving cross-sectional correlation."""
```

`block_months` must always equal the forward horizon being tested.

### 5.2 Effective N

Estimate via variance inflation factor: the N that would produce the observed bootstrap
interval width under independence. **Store and display both effective and naive N.**

### 5.3 Matched null

Random draws from the investable universe over identical calendar windows, matched on
sector and size decile, 2,000 reps. Every base rate response object **must** carry its
null. Make it a required field on the Pydantic schema so it cannot be omitted:

```python
class BaseRateResponse(BaseModel):
    hit_rate: float
    hit_rate_ci: tuple[float, float]
    median_excess: float
    # ...
    n_effective: int
    n_naive: int
    null: MatchedNull          # REQUIRED — no Optional
```

### 5.4 Gating

```python
if n_effective < 8:
    return InsufficientEvidence(
        n_effective=n_effective,
        required=8,
        projected_date=estimate_when_threshold_met(state_key)
    )
```

**Acceptance:** bootstrap intervals are 2–4× wider than naive binomial on the same data;
cells below n_eff 8 return `InsufficientEvidence` with a projected date; no code path
can return a base rate without a null.

---

## 6. TASK 6 — TRIAL REGISTRY & VALIDATION HARNESS

### 6.1 Append-only registry

```sql
CREATE TABLE m5.trials (
  trial_id uuid PRIMARY KEY,
  registered_at timestamptz NOT NULL DEFAULT now(),
  hypothesis_name text NOT NULL,
  mechanism_text text NOT NULL CHECK (length(mechanism_text) >= 200),
  closing_mechanism text NOT NULL CHECK (closing_mechanism IN
    ('scheduled_release','regime_turn','liquidity_revival',
     'corporate_action','capitulation_exhaustion')),
  conditions_json jsonb NOT NULL,
  prior_json jsonb NOT NULL,
  result_json jsonb,
  outcome text,
  counted_in_dsr boolean NOT NULL DEFAULT true
);

CREATE RULE m5_trials_no_update AS ON UPDATE TO m5.trials
  WHERE OLD.result_json IS NOT NULL DO INSTEAD NOTHING;
CREATE RULE m5_trials_no_delete AS ON DELETE TO m5.trials
  DO INSTEAD NOTHING;
```

`result_json` may be written **once**, when the test completes. Everything else is
immutable from insert. `mechanism_text` has a 200-character floor at the database level —
this is deliberate friction, not a UI nicety.

### 6.2 Walk-forward

```python
def purged_walkforward(panel, horizon_months, n_folds=5,
                       embargo_months=1):
    """Purge length ALWAYS equals horizon_months. No exceptions,
    no parameter to shorten it."""
```

### 6.3 DSR

Reads the live trial count from `m5.trials` where `counted_in_dsr`. There is no
parameter to exclude a trial.

### 6.4 The ten gates

Implement spec §7.4 as ten independent boolean functions returning
`(passed, actual_value, threshold, explanation)`. The report card shows all ten,
each pass or fail, with the failing gate named in plain language.

**Acceptance:** update/delete on a completed trial silently no-ops; a hypothesis with
< 200 chars of mechanism is rejected at insert; DSR changes when a trial is added;
all ten gates individually unit-tested.

---

## 7. TASK 7 — PLAYBOOK ENGINE

Implement PB-01 … PB-06 from Appendix B. **Register all six in `m5.trials` with their
mechanisms BEFORE running any backtest.** This ordering is the point of the exercise.

Each playbook is a declarative definition, not imperative code:

```python
PB02 = Playbook(
    id="PB-02",
    name="Post-Capitulation Value",
    closing_mechanism="capitulation_exhaustion",
    mechanism_text="""Retail selling on the CSE is indiscriminate...""",
    entry=All(
        ValuationGap(Deep),
        FundamentalTrajectory(in_=[Stable, Improving]),
        PriceStructure(transitioning_to=Basing),
        PillarD(clean=True),
        NotMacroAttributable(lookback_days=60),
        NoNewLow(sessions=20),
        VolumeDeclining(),
        # NON-NEGOTIABLE, present on every playbook:
        ExistingGatesPass(),
        NetExpectedReturnAboveFloor(),
    ),
    exit=Any(
        FairValueReached(),
        ThesisBreak(),
        MaxHoldMonths(12),
        BasingBroken(),
    ),
    target_hold_months=9, max_hold_months=12,
    prior=Prior(hit_rate=0.58, payoff=2.0, confidence=3),
)
```

`ExistingGatesPass()` and `NetExpectedReturnAboveFloor()` must be present on every
playbook. Add a test asserting this for all definitions.

**Acceptance:** all six registered before testing; each produces a ten-gate report card;
**expect 2–4 to fail — that is a passing outcome for this task, not a problem to fix.**
Do not tune a failing playbook to make it pass; each tuning attempt is a new trial.

---

## 8. TASK 8 — PLAYBOOKS TAB

Follow spec Part 9 precisely. Design system rules:

- Import tokens from the existing theme file. **Define no new colours.**
- Reuse: valuation bar, metric tile, score chip, provenance badge, data table,
  staleness banner. Do not fork them.
- Three new components only: `StateGrid`, `BaseRateCard`, `TrialCounter`.
- Route is lazy-loaded and wrapped in an error boundary. If `/api/v5` is unreachable the
  tab shows a fallback; **nothing else in the app is affected**.

### Non-negotiable UI invariants (add tests)

```
✓ A base rate never renders without its matched null adjacent,
  at equal visual weight
✓ Effective N and naive N both always visible
✓ Cells below n_eff 8 render with count only, no statistics
✓ Trial counter and DSR haircut visible on all four tabs
✓ Studio blocks submission without ≥200 chars of mechanism
✓ Studio shows the DSR haircut increase BEFORE registration
✓ Failed hypotheses shown by default in Track Record
✓ No component emits an order, a size, or a decision — the only
  action is "Open Decision Card →"
✓ Every chart legible in greyscale (CI snapshot test)
✓ Empty state on Live reads: "No setups firing. Most days are
  correctly quiet."
```

### Copy

Use the table in spec §9.7 verbatim. The word **BUY** appears nowhere. Never write
"predicts", "signals", "recommends", or "high confidence".

---

## 9. TASK 9 — SHADOW BOOK

Paper portfolio taking every Validated playbook's signals with **real** friction:

```
entry_cost   = limit × 1.0112 + amihud_slippage(size, adv)
exit_cost    = same
tax          = configured CGT parameter  (see System settings —
               do NOT hardcode; the listed-share treatment is
               unresolved and is a three-way parameter)
```

Track live-vs-backtest ratio from position one. Nothing promotes to live before
**2 quarters AND 8 positions AND ratio ≥ 0.5**.

**Acceptance:** shadow returns are materially below gross backtest (if they are not,
there is a bug); promotion is blocked until all three conditions hold.

---

## 10. GLOBAL ACCEPTANCE CHECKLIST

Before calling this done:

- [ ] `M5_ENABLED=false` → app identical to pre-M5, full suite green, `/api/v5` 404
- [ ] `git diff` touches only `m5` paths + the 2 allowlisted lines
- [ ] No `m5/` module imports an app write path (CI)
- [ ] No `INSERT/UPDATE/DELETE` against `public` in `m5/` (CI)
- [ ] `m5_service` has no write grant on `public` (verify in psql)
- [ ] `panel_pit` cannot expose a `fwd_` column
- [ ] 20 backfilled rows hand-verified against source filings
- [ ] Bootstrap intervals 2–4× naive binomial
- [ ] Every base rate carries its null (schema-enforced)
- [ ] Trial registry rejects update and delete
- [ ] DSR consumes live trial count with no exclusion path
- [ ] All six playbooks registered before testing; 2–4 failed
- [ ] Every playbook definition includes `ExistingGatesPass()`
- [ ] Primary grid is 3×3 (9 states), `Not cheap` replaces Fair + Rich
- [ ] 6m is the primary validation horizon; both 6m and 12m displayed
- [ ] `M5_MAX_MODIFIERS = 1`, auto-relaxing at the panel-depth threshold
- [ ] Top ~60 names backfilled deeper than the rest; coverage reported per state
- [ ] PB-04 returns `AWAITING_HISTORY`, not a tuned pass
- [ ] Task 2 shipped before Task 3
- [ ] Every gate report runs at both 0% and 15% CGT; `TAX-SENSITIVE` flag renders
- [ ] Dividend WHT 15% applied everywhere
- [ ] `M5_HOLDOUT_AFTER` enforced; backtester cannot read past it
- [ ] Holdout replay uses recorded order book depth for fills
- [ ] Greyscale snapshot tests pass on all charts
- [ ] No new colour tokens introduced
- [ ] No shared component modified
- [ ] Shadow book applies real friction and tax
- [ ] Nothing in M5 can emit an order

---

## 11. IF YOU GET STUCK

**Do not** work around the isolation constraints. If a task appears to require modifying
an existing file, writing to an existing table, or granting M5 write access, **stop and
report the blocker**. Every one of those constraints is load-bearing, and a workaround
that "just gets it working" defeats the entire purpose of building this as a separate
module.

**Do not** tune a failing playbook until it passes. Each attempt is a new trial and
inflates the DSR haircut for every playbook in the system. A playbook that fails its
gates has told you something true.

**Do not** shorten the purge, relax the effective-N thresholds, or add an option to
exclude a trial from the DSR count. Those three parameters are the entire reason this
module can be trusted.
