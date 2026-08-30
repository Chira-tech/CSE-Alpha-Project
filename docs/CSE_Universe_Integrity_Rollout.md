# Universe-Wide Data Integrity & Security Resolution — Rollout Spec

**Premise: AAF is not a bug, it's a sample.** Nothing about the AAF failure was AAF-specific. The pipeline bound a company to a price series with no independent check that the binding was correct, then published a maximum-conviction verdict on top of it. Every one of the ~300 CSE lines runs through that same code path. The only reason you caught AAF is that you happened to look.

This spec turns that one catch into a system that catches all of them, forever, without you looking.

Companion to `aaf-factcheck-and-company-page-redesign.md`. Prepared 2026-08-30.

---

## Part 0 — The ten failure classes

Before designing anything, name what can go wrong. Each of these silently produces a confident wrong number, and each needs its own universe-wide detector.

| # | Failure class | What it looks like | Confirmed in your system? |
|---|---|---|---|
| 1 | **Wrong listed line** | Valuing the rights/non-voting/preference line as if it were the ordinary voting equity | ✅ Confirmed (AAF) |
| 2 | **Corporate actions not applied** | Adjustment factor 1.0 despite rights/bonus/split on file | ✅ Confirmed (AAF, and it's global) |
| 3 | **Units / scale mismatch** | LKR vs LKR'000 vs LKR mn mixed across sources; column says "M", value is raw rupees | ⚠️ Suspected (AAF statement lines) |
| 4 | **Share-count vintage** | Today's price × last year's share count; pre-rights count with post-rights price | ⚠️ Suspected (AAF) |
| 5 | **Missing cost of equity** | CoE-dependent models unavailable, engine falls back silently | ✅ Confirmed (AAF, likely universe-wide) |
| 6 | **Wrong model family for sector** | Industrial DCF applied to banks/LFCs | ⚠️ Check routing table |
| 7 | **Fiscal period misalignment** | March, June, December year-ends stitched into one "TTM" | ⚠️ Likely |
| 8 | **Unconfirmed statement lines** | Pending-review data feeding published valuations | ✅ Confirmed |
| 9 | **Consolidated vs standalone** | Group revenue against parent-only equity | ⚠️ Likely |
| 10 | **Stale / illiquid price** | Last trade weeks old, treated as live | ✅ Confirmed (sidebar: "EOD prices 7d ago") |

Classes 1–4 corrupt the *inputs*. Classes 5–7 corrupt the *model*. Classes 8–10 corrupt the *confidence*. All three groups need gates, and they need to be separate gates — a stale price is a different problem from a wrong security.

**Rough scale estimate (to be measured, not assumed):** on the CSE at any given time, a meaningful minority of issuers carry a second line — non-voting, preference, or a temporary rights line during an offer. Add the names with a corporate action in the last 24 months and you are plausibly looking at **10–25% of the universe** carrying at least one of failure classes 1–2. Phase 1 below measures this number precisely before you fix anything.

---

## Part 1 — Layer 1: The canonical security master

The root cause is that your data model almost certainly has one row per *company*. The exchange has one row per *line*. That mismatch is where AAF died.

### 1.1 Schema

Model the line as the first-class object, and the issuer as its parent.

```sql
CREATE TABLE issuer (
  issuer_id        TEXT PRIMARY KEY,
  legal_name       TEXT NOT NULL,
  cse_issuer_code  TEXT UNIQUE,
  sector_code      TEXT NOT NULL,       -- drives model routing
  gics_like_bucket TEXT NOT NULL,       -- BANK | LFC | DIVERSIFIED | MANUFACTURING | ...
  reporting_ccy    TEXT NOT NULL DEFAULT 'LKR',
  fiscal_year_end  INT  NOT NULL        -- month, 1-12. AAF = 3
);

CREATE TABLE listed_line (
  line_id          TEXT PRIMARY KEY,
  issuer_id        TEXT NOT NULL REFERENCES issuer,
  symbol           TEXT NOT NULL UNIQUE,   -- 'AAF.N0000'
  isin             TEXT,
  line_type        TEXT NOT NULL,          -- see enum below
  status           TEXT NOT NULL,          -- ACTIVE | SUSPENDED | DELISTED | TEMPORARY
  is_primary       BOOLEAN NOT NULL DEFAULT FALSE,
  underlying_line  TEXT REFERENCES listed_line(line_id),  -- rights/warrants -> ordinary
  listed_date      DATE,
  expiry_date      DATE,                   -- rights lines expire; this is why they must not persist
  shares_in_issue  BIGINT,
  shares_asof      DATE NOT NULL,          -- vintage. non-negotiable.
  source           TEXT NOT NULL,
  retrieved_at     TIMESTAMPTZ NOT NULL
);

-- Exactly one primary line per issuer, enforced by the database, not by convention.
CREATE UNIQUE INDEX one_primary_per_issuer
  ON listed_line(issuer_id) WHERE is_primary;
```

`line_type` enum: `ORD_VOTING`, `ORD_NONVOTING`, `PREFERENCE`, `RIGHTS_NILPAID`, `WARRANT`, `DEBENTURE`, `UNIT_TRUST`, `UNKNOWN`.

### 1.2 Deriving line type — do not hardcode from guesses

CSE symbols encode line type in the suffix, but **build the suffix map from the CSE's own published security master, not from assumption.** Any symbol whose suffix isn't in the confirmed map gets `line_type = UNKNOWN`, which is a blocking state, not a default-to-ordinary.

```
classify(symbol):
    suffix = symbol.split('.')[1]
    if suffix in CONFIRMED_SUFFIX_MAP:  return CONFIRMED_SUFFIX_MAP[suffix]
    return UNKNOWN     # -> blocks valuation, raises a confirm-queue item
```

`UNKNOWN` must be loud. The AAF failure was a silent default; every silent default in this pipeline is a future AAF.

### 1.3 Primary line resolution — deterministic, auditable

```
resolve_primary_line(issuer):
    active = lines(issuer) where status = ACTIVE

    # Rights, warrants, preference and debentures are NEVER the issuer's equity.
    eligible = active where line_type in (ORD_VOTING, ORD_NONVOTING)

    voting = eligible where line_type = ORD_VOTING
    if len(voting) == 1:  return voting[0], confidence = HIGH
    if len(voting) >  1:  return max(voting, key=turnover_12m), confidence = LOW, queue_for_review()

    nonvoting = eligible where line_type = ORD_NONVOTING
    if len(nonvoting) == 1: return nonvoting[0], confidence = MEDIUM, flag = 'NO_VOTING_LINE'

    return None, confidence = NONE, BLOCK
```

Three rules that would each have saved you on AAF, independently:

1. **A rights line can never be primary.** It's excluded by type before anything else runs.
2. **Rights lines expire.** They must be reaped daily on `expiry_date`, not left to linger and be re-picked next quarter.
3. **`confidence` travels with the binding** all the way to the UI. A LOW-confidence binding cannot produce a Strong Accumulate.

---

## Part 2 — Layer 2: The validation gate

The security master fixes the *known* bug. This layer catches the ones you haven't found yet. The principle: **never trust a single binding — triangulate.**

Seven checks. Each is cheap, each runs over the entire universe nightly, and each is shown below with the AAF worked example so you can verify the detector before trusting it.

### Check 1 — Market cap identity ⭐ *build this first*

The single highest-value check in this document. One join, catches most of class 1, 3 and 4 at once.

```
| price × shares_in_issue − exchange_published_market_cap | / exchange_market_cap  ≤  0.02
```

> **AAF:** 11.30 × 124,195,533 = **LKR 1.40 bn** vs exchange-published **LKR 6.1 bn** → off by **4.35x** → **FAIL**.

This one check, running any night in the last two months, would have quarantined AAF before the verdict was ever published. Ship it this week even if you ship nothing else.

### Check 2 — Rights-price coherence

If an open rights issue exists, the market price of the underlying must exceed the subscription price. Rights are always priced at a discount; a market price below the subscription price is arithmetically near-impossible in a live offer.

```
if open_rights_issue(issuer):  assert price > subscription_price
```

> **AAF:** 11.30 < 33.30 → **FAIL**.

### Check 3 — Nil-paid rights fingerprint

The detector that pinpoints *which* wrong line you've grabbed. If the bound series behaves like a nil-paid right, it is one.

```
implied_terp   = bound_price + subscription_price
implied_cum    = (15 × implied_terp − 4 × subscription_price) / 11     # generalises to (N_old+N_new)/N_old
flag if implied_cum falls inside the issuer's plausible price range
```

> **AAF:** 11.30 + 33.30 = 44.60 implied TERP; the confirmed TERP from a ~49.10 cum-price is 44.89. **Match within 0.6%** → conclusively the rights line.
> The earlier 15.40 row implies a cum-price of ~54.30 — also inside range. Two independent hits.

Generalised TERP, for the engine:

```
TERP = (N_old × P_cum + N_new × Subscription) / (N_old + N_new)
```

### Check 4 — Implied multiple plausibility band

Guard against valuations that have never existed for a solvent company in that sector.

```
fail if  P/B < 0.40 and ROE > 15%          # deep discount + high returns = data error, not opportunity
fail if  P/E < 2.0  and net_profit > 0
fail if  P/B > 15   or  P/E > 200
```

> **AAF at 11.30:** P/B = 11.30 / 35.12 = **0.32x** with ROE **24.3%** → **FAIL**. A Fitch A+(lka) lender earning 24% has never traded at a third of book.

Sector-specific bands, calibrated from your own history once you have clean data. Wide enough to never fire on a real opportunity, narrow enough to catch a 4x error.

### Check 5 — Cross-vendor triangulation

Hold at least one independent price source. Flag divergence > 10%; quarantine > 25%.

> **AAF:** app 11.30 vs external 49–58 → **FAIL by ~340%**.

Vendors legitimately disagree by 10–15% on a thin market (different snapshot times, pre- vs post-rights share counts). They do not disagree by 4x. Set the threshold to catch magnitude errors, not noise.

### Check 6 — Price continuity vs corporate action calendar

```
if |return_1d| > 30% and no corporate_action on that date:  quarantine
if corporate_action on date and adjustment_factor == 1.0:   quarantine   # class 2, universe-wide
```

The second line is the one that catches your global adjustment-factor bug on every name at once.

### Check 7 — Units and magnitude sanity

For every statement line, assert the value sits in a plausible band relative to its siblings.

```
assert total_equity      < total_assets
assert total_equity      > 0
assert 0.02 < equity/assets < 0.98        # any leveraged lender outside this is a units error
assert net_profit        < revenue × 1.5
assert |value| not within 1000x or 1e6x of a sibling in a different unit
```

> **AAF (suspected):** a `total_equity` reading ~45.7bn against total assets of 53.8bn implies an 85% equity ratio for a 4.5x-levered finance company. Actual equity is **4.78 bn**. Either a units error or assets mapped onto the equity field.

---

## Part 3 — Layer 3: The corporate actions engine

Class 2 is global — adjustment factor 1.0 on every row means every moving average, every momentum signal, every "P/E vs 5-year average", and every backtest in your system is wrong for any name that has ever had a corporate action.

### 3.1 Factor formulas

Convention: multiply all prices **before** the ex-date by the cumulative factor to make history comparable with today.

| Action | Factor applied to pre-ex prices |
|---|---|
| Rights issue | `TERP / P_cum`, where `TERP = (N_old·P_cum + N_new·Sub) / (N_old + N_new)` |
| Bonus issue | `N_old / (N_old + N_new)` |
| Share split (1→k) | `1 / k` |
| Consolidation (k→1) | `k` |
| Cash dividend (total-return series only) | `(P_cum − D) / P_cum` |
| Capital reduction | `(P_cum − cash_returned) / P_cum` |

> **AAF rights, 4-for-11 at 33.30, cum-price 49.10:**
> TERP = (11 × 49.10 + 4 × 33.30) / 15 = 673.30 / 15 = **44.89**
> Factor = 44.89 / 49.10 = **0.9142** — applied to every AAF price before the ex-date.

### 3.2 Non-negotiable properties

- **Cumulative.** A price from 2019 carries the product of every factor since. Store the cumulative factor per (line, date), not just the event factor.
- **Idempotent.** Re-running the adjuster must not double-apply. Adjust on read from a raw immutable price table; never mutate raw prices in place.
- **Reproducible.** `raw_close`, `cumulative_factor`, `adjusted_close` all stored, so any number on screen can be traced back to an exchange print.
- **Share counts adjust too.** A rights issue changes the denominator. Store `shares_in_issue` as a dated time series, and always join price to the share count *effective on that date* — this is the fix for failure class 4.

> **AAF pro-forma:** equity 4,775m + 1,504m = **6,279m**; shares 124,195,533 + 45,162,012 = **169,357,545**; BVPS = **LKR 37.08**; ROE on the enlarged base ≈ **16.6%** vs 21.8% before. Your engine must model this — a rights issue mechanically dilutes ROE until the capital is deployed, and any model feeding on trailing 24% is overstating the company.

---

## Part 4 — Layer 4: Quarantine and verdict blocking

A failed check must never silently degrade the answer. It changes the *state* of the security.

| State | Meaning | What the system may publish |
|---|---|---|
| `CLEAN` | All checks pass | Full valuation + verdict |
| `PROVISIONAL` | Soft failures only (unconfirmed lines, stale price, LOW-confidence binding) | Valuation, marked provisional. **No Strong Accumulate, no Strong Sell.** |
| `QUARANTINED` | Any hard check failed | Facts and raw data only. **No fair value, no verdict, no scoreboard rank.** |
| `UNRESOLVED` | No primary line, or `line_type = UNKNOWN` | Company page renders identity only |

**Quarantined names drop out of the Opportunities ranking entirely** rather than ranking on bad data. That is the whole point — a 4x-wrong price doesn't produce a mediocre rank, it produces a #1 rank, because the ranking rewards apparent cheapness. **Data errors preferentially surface at the top of your buy list.** Any name in your current top 20 with a suspiciously large upside is a quarantine candidate until proven otherwise.

Replace the verdict with the blockers themselves: *"No verdict — 2 blockers: listed line unresolved, cost of equity unavailable."* More useful than a confident wrong answer, and it turns the confirm queue into a prioritised worklist instead of an undifferentiated pile.

---

## Part 5 — The rollout

Sequenced so you learn the size of the problem before committing to fixes, and so nothing user-facing changes until you've seen the diff.

### Phase 0 — Ingest the security master *(1–2 days)*
Load every CSE line into `listed_line`. Confirm the suffix→type map against the exchange's own file. Backfill `shares_in_issue` as a dated series. **Exit criterion:** every symbol in your price table maps to exactly one `line_id`, and every issuer has exactly one primary line or is explicitly `UNRESOLVED`.

### Phase 1 — Dry run, report only *(1 day, no user-facing change)*
Run all seven checks across the full universe in report-only mode. Change nothing. Produce a triage table:

| Bucket | Names | Example | Remediation |
|---|---|---|---|
| Wrong line bound | ? | AAF | Rebind to primary line, refetch history |
| Corporate action unadjusted | ? | | Run adjuster, rebuild derived series |
| Market-cap identity fail | ? | | Investigate — usually line or share count |
| Units suspect | ? | | Re-map statement lines |
| Stale > 7d | ? | | Refetch or mark PROVISIONAL |
| CoE unavailable | ? | | Build CoE service (see Phase 3) |
| Sector model mismatch | ? | | Fix routing table |

**This table is the actual deliverable of the rollout.** Everything after it is execution. It also tells you whether this is a 20-name problem or a 200-name problem — decide effort after you know.

### Phase 2 — Enforce the gate *(1 day)*
Turn the checks from report-only into blocking. Expect the Opportunities board to shrink, possibly a lot. **That shrinkage is the product working**, not a regression — a smaller board of names you can trust beats a full board you can't.

### Phase 3 — Fix by bucket, largest first
1. Rebind wrong lines and refetch their full history
2. Run the corporate-action adjuster universe-wide; rebuild all derived series (MAs, momentum, historical multiples)
3. Build the cost-of-equity service — one shared, versioned, dated input (CBSL risk-free + Sri Lanka ERP + beta), because CoE is missing *universe-wide*, not just on AAF, and every financial-sector valuation is blocked on it
4. Fix statement-line units and the sector model routing table
5. Work the confirm queue by bucket with bulk actions

### Phase 4 — Recompute and diff *(the important one)*
Recompute the universe and publish a **before/after verdict diff**: every name whose score or verdict changed, with the reason. This is your evidence the fix worked, and your check that it didn't break something else. Expect meaningful churn — several current Strong Buys will evaporate, exactly as AAF's did.

### Phase 5 — Make it permanent
- Checks run as a **gate on every nightly load**, not as an ad-hoc script. A load that fails the gate does not publish.
- Golden regression set (Part 6) runs in CI on every engine change.
- Data health page shows universe-wide pass rates over time.

---

## Part 6 — Golden regression set

Pin real securities as permanent test cases so this class of bug can never come back silently. Each is a known-answer test.

| # | Case | Must assert |
|---|---|---|
| 1 | **AAF.N0000 during the 2026 rights issue** | Binds to the ordinary voting line, not the rights line; price ≈ 49, not 11.30; rights factor 0.9142 applied |
| 2 | Issuer with a non-voting line | Binds to voting; non-voting valued separately, never merged |
| 3 | Issuer with a preference line | Preference never treated as equity of the issuer |
| 4 | Issuer post-bonus issue | Pre-ex prices adjusted; no phantom price gap |
| 5 | Issuer post-consolidation | Factor > 1 applied correctly; share count series steps at the right date |
| 6 | Suspended security | `QUARANTINED`, excluded from ranking |
| 7 | Illiquid name, last trade > 30d | `PROVISIONAL`, staleness surfaced inline |
| 8 | Bank vs LFC vs manufacturer | Each routes to its correct model family; no industrial DCF on a lender |
| 9 | Non-March fiscal year end | TTM stitching aligns periods correctly |
| 10 | Company reporting in USD | Currency converted once, at the right date, not twice |

Case 1 is the highest-value test you own — it's a real, verified, known-wrong-answer scenario. Never delete it.

---

## Part 7 — Metrics

Put these on the Data health page and track them weekly. This is how "measurable progress" becomes visible instead of theoretical.

| Metric | Target |
|---|---|
| Issuers with a resolved primary line | 100% |
| Bindings at HIGH confidence | > 95% |
| Passing market-cap identity (±2%) | > 98% |
| Corporate actions with an applied factor | 100% |
| Names in `QUARANTINED` | Trending down; never silently zero |
| Universe with CoE available | 100% (currently near 0) |
| Median price staleness | < 1 trading day |
| Confirm queue depth | Trending down week over week |

One inversion worth internalising: **a rising quarantine count is good news early on.** It means detection is working. The number to watch is quarantine count *after* Phase 3 — that's the one that should fall.

---

## Part 8 — The principle underneath all of it

Your system's job is not to have an opinion on every one of the ~300 CSE names. It's to have a *trustworthy* opinion on the subset where the data supports one, and to say plainly where it doesn't.

AAF had four separate signals screaming that something was wrong — a multi-line banner, a missing cost of equity, fourteen unconfirmed statement lines, and an unapplied corporate action. The system saw all four and published **Strong Accumulate** anyway. Not because any single component was badly written, but because nothing in the architecture had the authority to say *no*.

This rollout gives it that authority. Everything else here is plumbing.

---

## Build order, if you only do three things

1. **Check 1 — market cap identity.** One join. Catches most magnitude errors across the whole universe. Ship it this week.
2. **Exclude non-ordinary line types from primary binding.** Ten lines of code. Makes the AAF class of failure structurally impossible.
3. **Block the verdict when cost of equity is unavailable.** Stops the engine publishing confident numbers it cannot support — universe-wide, today.

Those three are a few days of work and remove the majority of the risk. The rest is thoroughness.

*Companion to `aaf-factcheck-and-company-page-redesign.md`, `portfolio-page-redesign-spec.md`, and `scoreboard-queue-redesign-spec.md`.*
