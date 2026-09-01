# Data Health: Diagnosis, Experiment Protocol, and Redesign

Worked from the real Confirm Queue / Data health export of 2026-09-01, not from a screenshot. Every number below is yours.

Goal, restated as a testable target: **every figure in the system agrees with an independent source within a stated tolerance, and every figure that cannot be checked is labelled as such rather than counted as correct or as broken.**

Method constraints you set, adopted verbatim: one variable per change, universe-wide metrics only, no fix that is really a patch for a single ticker.

---

## 0. Calibrate the instrument before running any experiment

Two of your headline numbers are almost certainly measuring the wrong thing:

- **Market-cap identity pass: 50.0%**
- **Price-ratio actions confirmed: 15.1%**

Both are two-way rates (pass or fail). Neither has a slot for *not evaluable*. That is the same denominator bug already found in the composite score, where unmeasured pillars scored zero instead of being excluded. A line with no published market cap, or no share count, or no price on the comparison date, is currently indistinguishable from a line that genuinely disagrees.

**E0 must run before anything else, and it changes no data at all.** Split every rate three ways:

```
pass            checked, agrees within tolerance
fail            checked, disagrees
not_evaluable   could not be checked, with a reason code
```

Until this lands, no other experiment is interpretable, because you cannot tell whether a metric moved because the data improved or because the coverage changed. Calibrate, then measure.

---

## 1. The finding that matters most

**Ten of your twenty-five open alerts point the same direction, and that is not what random error looks like.**

Second-source mismatches, all five:

| Ticker | Stored close (2026-08-28) | External quote (live) | Difference |
|---|---|---|---|
| CITW.N0000 | 1.60 | 1.70 | stored lower by 6.25% |
| RGEM.N0000 | 118.25 | 136.00 | stored lower by 15.01% |
| SFCL.N0000 | 343.75 | 362.00 | stored lower by 5.31% |
| SHOT.N0000 | 15.80 | 17.00 | stored lower by 7.59% |
| WIND.N0000 | 38.90 | 41.00 | stored lower by 5.40% |

Market-cap mismatches, all five:

| Ticker | Published market cap | Price × shares | Difference |
|---|---|---|---|
| AFSL.N0000 | 6,956,635,342 | 6,566,061,536 | computed lower by 5.95% |
| AFS.N0000 | 1,062,600,000 | 1,036,035,000 | computed lower by 2.56% |
| AEL.N0000 | 77,000,000,000 | 74,700,000,000 | computed lower by 3.08% |
| ACME.N0000 | 2,926,000,000 | 2,859,500,000 | computed lower by 2.33% |
| ABL.N0000 | 14,662,526,640 | 14,331,792,956 | computed lower by 2.31% |

**Ten out of ten have the stored value below the external value.** If these were independent random errors, all ten landing on one side has roughly a 1-in-500 chance (two-tailed sign test). They are not ten separate problems.

**Hypothesis H1: both checks compare a stale stored snapshot against a live external value.** Your latest price date is 2026-08-28 and the feed is four days old. If the market drifted up over that window, every stored close sits below every live quote, and every price×shares sits below every current published market cap. The magnitudes fit: market-cap gaps cluster at 2.3% to 3.1%, which is a few days of drift, not a wrong share count. A genuinely wrong share count produces large arbitrary errors, not a tight cluster just above a 2% threshold.

This single hypothesis, if true, accounts for 10 of 25 open alerts and most of the 50% market-cap pass rate. It is a comparison-design defect, not a data defect.

**Falsifier, and this is the important half:** after switching both checks to same-date comparison, the residual mismatches must become sign-balanced, roughly half above and half below. If they are still all one way, H1 is wrong and you have a real systematic scaling error, which is a much more serious finding.

**Residual prediction:** AFSL should survive the fix. At 5.95% it is twice the size of the cluster, and it independently trips `share_count_reconciles` in the valuation sanity block. That makes it the one name in this batch with a probable genuine share-count problem, and the right place to look once the noise is gone.

---

## 2. The second finding: tolerance is defined on the wrong quantity

**CITW is flagged for a 6.25% error. That error is exactly one price tick.** Stored 1.60, external 1.70. On a stock priced at 1.60, the minimum increment *is* roughly 6% of the price. The check cannot tell a real disagreement from the smallest possible legal price change.

A percentage-only tolerance is meaningless at the bottom of the price range and far too loose at the top. Two corrections, both of which apply universe-wide rather than to CITW:

```
tolerance = max(percentage_floor, N × tick_size(price_band))
```

And more fundamentally, for the market-cap check: **validate the quantity you actually care about, not a downstream product of it.**

You are not trying to verify market capitalisation. You are trying to verify the share count. Market cap moves every single day; share count moves a handful of times a year. Comparing market caps means price timing contaminates every measurement. Comparing implied share counts removes the confound entirely:

```
implied_shares = published_market_cap / published_price_same_date
check:           |implied_shares - stored_shares| / stored_shares  ≤  0.5%
```

Same underlying question, one fewer moving part. This is the single cleanest change on the list.

---

## 3. The third finding: a check that is measuring an empty table

Seven price-discontinuity quarantines, every one of them reading *"no corporate action anywhere near that date"*:

TAP +464%, LIOC +75%, RCL +63%, SHL +47%, SEMB +43%, BIL +32%, DOCK +31%.

And in the sidebar, in the smallest text on the page: **"Corporate actions: never succeeded."**

The check is not detecting bad prices. It is detecting that the corporate actions table was never populated. Of course there is no action near the date. There are barely any actions at all, and the 1,230 confirmed ones came from some path other than the job that is supposed to maintain them.

This is the highest-leverage single change available, and it requires no code: **run the corporate actions feed, then re-run the discontinuity check completely unchanged.** Changing the check at the same time would confound the result, and that is precisely the trap to avoid here.

The same sidebar carries two more never-run jobs, and one of them quietly undermines the valuation engine.

---

## 4. The fourth finding: a green number that is not green

**"Cost of equity available (proxy): 98.3%"** sits beside **"CBSL macro series: never run."**

Both are true, and together they mean the opposite of what the tile implies. Coverage is 98.3% *of a proxy*, which is to say a constant standing in for a real per-name cost of equity. The CBSL risk-free feed that a real number requires has never executed once.

At a glance, 98.3% reads as solved. In substance, every financial-sector fair value in the system currently rests on a placeholder. The tile is not lying, but it is the single most misleading element on the page, and the fix is partly a labelling fix: a proxy value should render in the blocked state, not as a healthy percentage.

Worth measuring when the real feed lands: not just coverage, but **how far fair values move when the proxy is replaced.** A large universe-wide shift is the proof that the proxy was materially wrong. A small one means the proxy was adequate and you have learned something useful either way.

---

## 5. The fifth finding: the page contradicts itself about freshness

Three numbers for one question, on one screen:

| Where | What it says |
|---|---|
| Coverage tile | Feed age: 4 days |
| Universe integrity tile | Median price staleness: 4 days |
| Sidebar | EOD prices: 9d ago |

Four days and nine days cannot both be right for the same feed. They are almost certainly two different quantities wearing one label: *how old is the newest data* versus *when did the job last succeed*. Both matter, and conflating them is how a silently failing job hides behind fresh-looking data.

Separately, "days ago" is the wrong unit. Your latest price is 2026-08-28, a Friday. Monday 2026-08-31 was a trading day and it is missing. A count of calendar days cannot tell you that. **Count missing trading days against the exchange calendar**, so a weekend reads as healthy and a missed Monday reads as a gap.

One more labelling collision: "Suspended / delisted lines: 0" sits a few centimetres from "Flagged delisted: 11". Different scopes, same words.

---

## 6. The sixth finding: non-voting lines fail structurally

Two of the eight valuation sanity blocks are `.X` lines: **NTB.X0000** and **COMB.X0000**, both failing `fv_within_5x_price`.

Non-voting shares trade at a persistent discount to voting shares. If fair value is computed from issuer-level fundamentals and then compared against a non-voting line's price, the comparison is wrong by the size of that discount for every `.X` line in the universe, permanently.

The diagnostic is a cohort split, not a ticker investigation: **block rate for `.X` lines versus `.N` lines.** If `.X` fails at a materially higher rate, this is a class defect and the fix is per-class share counts and prices, applied everywhere at once.

This also feeds back into section 2. You hold 294 lines behind 273 issuers, so 21 issuers carry a second line. The exchange publishes market cap per *issuer*, while price × shares is computed per *line*. For every multi-line issuer that comparison cannot balance by construction. Cohort split again: single-line versus multi-line pass rates.

---

## 7. Tolerance policy

You asked for accuracy within a small tolerance, so the tolerances need stating explicitly rather than living as magic numbers in the checks.

| Check | Compare | Tolerance | Reasoning |
|---|---|---|---|
| Price vs second source | Same-date close to same-date close | `max(1.0%, 2 ticks)` | Cross-source noise on thin CSE names exceeds 0.5%. Tick floor stops low-price false positives. |
| Share count | Implied shares vs stored shares | 0.5% | Share counts are near-static. A tight tolerance is meaningful here. |
| Market cap identity | Issuer level, summed across lines | 2.0% | Retained, but only as a secondary check once share count passes. |
| Corporate action ratio | Observed price gap vs expected ratio | 3.0% | Ex-date opening auctions are noisy. |
| Statement line vs filing | Reported figure to reported figure | 0.1% | Two sources reading the same filing should agree almost exactly. Any gap is a parsing error. |
| ROE plausibility | Computed | -50% to +60% | Yours already. Keep. |
| Fair value vs price | Ratio | 0.2x to 5x | Yours already. Keep, but split by line class first. |

The principle underneath the table: **set the tolerance on the quantity being validated, at the granularity it actually varies.** A percentage on a low-priced stock, or a daily tolerance on a slow-moving quantity, measures the wrong thing no matter how carefully it is tuned.

---

## 8. The experiment ledger

Rules, in force for every change:

1. **One variable per deploy.** If two things change, the result explains nothing.
2. **Pre-register the prediction and the falsifier** before deploying, not after seeing the result.
3. **The metric is a universe-wide rate or a cohort split.** Never "did TAP get fixed".
4. **Name the cohort and its size before writing the fix.** If you cannot state how many lines a change affects, you are about to patch one ticker.
5. **A change that moves no universe-wide metric is an anecdote**, logged as such, not counted as a fix.
6. **Record before and after in the ledger**, including the experiments that failed. The rejected hypotheses are worth as much as the accepted ones.

| ID | Hypothesis | Single variable changed | Primary metric | Falsifier |
|---|---|---|---|---|
| **E0** | Pass rates conflate "fail" with "cannot evaluate" | Metric definition only, no data change | Three-way split published for all 8 checks | If not_evaluable is near zero everywhere, rates were honest and E0 changes nothing |
| **E1** | Stale-vs-live comparison drives second-source alerts | External quote pulled for the stored close's own date | Alert count, **and sign balance of residuals** | Residuals still all one direction, meaning a real scaling error |
| **E2** | Percentage-only tolerance false-positives at low prices | Tolerance becomes `max(1.0%, 2 ticks)` | Alert count **split by price decile** | Drops spread evenly across deciles rather than concentrating in the cheapest |
| **E3** | Market-cap check is contaminated by price timing | Compare implied share count instead of market cap | Pass / fail / not-evaluable across all 294 lines | Pass rate stays near 50%, meaning share counts really are wrong |
| **E4** | Multi-line issuers fail by construction | Aggregate to issuer level for multi-line issuers only | Pass rate, single-line cohort vs multi-line cohort | Both cohorts fail at the same rate |
| **E5** | Discontinuity alerts are a missing CA table, not bad prices | Corporate actions feed runs. **Check itself untouched.** | Discontinuity alert count, and share of price gaps now matched to an action | Alerts persist after the table is populated, meaning the prices really are broken |
| **E6** | The CoE proxy materially distorts fair values | CBSL feed runs, real CoE replaces proxy | Share of names with a real CoE, **and the distribution of fair-value change** | Fair values barely move, meaning the proxy was adequate |
| **E7** | Non-voting lines fail valuation sanity structurally | Per-class share count and price | Block rate, `.X` cohort vs `.N` cohort | Both classes block at the same rate |
| **E8** | Freshness is two quantities under one label | Split into data-date and last-successful-run, counted in trading days | Zero contradictory freshness figures on screen; missing trading days visible | The two numbers were always equal and the sidebar was simply stale |

Run in that order. E0 first because it calibrates the instrument. E5 early because it is free and unblocks seven quarantines. E1 and E3 before E4 and E7, because the staleness confound has to be removed before any cohort split can be read cleanly.

---

## 9. Redesign

The current page is roughly twenty-five stat tiles at identical visual weight, interleaved with explanatory prose, ending in a flat quarantine table. Three consequences:

- **50.0% and 98.3% and 0 all look the same.** Nothing on the page encodes "this one is failing".
- **Cause and effect are separated.** The fact that explains seven quarantines ("Corporate actions: never succeeded") sits in sidebar footnote text, while the seven quarantines sit 3,000 pixels away.
- **Nothing is tracked over time**, despite the page's own copy promising weekly-tracked numbers. You cannot tell whether things are improving.

### 9.1 The right form is a table, not a tile grid

More than about seven classes that all carry meaning is a table, by the same rule that governs any dense comparison. You have eight checks. A grid of equal tiles is the wrong container for eight things that need comparing on the same axes.

**The check ledger becomes the page's centre:**

| Check | Pass | Fail | Not evaluable | 14-day trend | Blocking | Action |
|---|---|---|---|---|---|---|

One row per check, one sparkline per row, status colour on the row rather than a wall of coloured tiles. Sortable by failure count, so the worst check is one click from the top.

### 9.2 Lead with blockers, and connect them to what they cause

Above the ledger, a short list of things that are stopping work, each linked to its downstream damage:

```
Corporate actions feed has never succeeded
  causing  7 quarantined lines flagged as price discontinuities
  action   Run feed  ›

CBSL macro series has never run
  causing  cost of equity served from a proxy on 98.3% of names
  action   Run feed  ›

Price feed 4 days old, 1 trading day missing (Mon 31 Aug)
  causing  10 of 25 open alerts, stale-vs-live comparison artefacts
  action   Run capture  ›
```

Causal linking is the largest usability gain available here. Every alert should name the upstream condition that produced it, because that is what turns a list of symptoms into a queue of decisions.

### 9.3 Group the worklist by cause, never by ticker

The quarantine table today is one row per ticker, which invites exactly the ticker-by-ticker fixation you want to avoid. Group by alert type, show the cohort size, and attach one action to the whole group:

```
price_discontinuity          7 lines    blocked on the CA feed        [Run feed]
second_source_mismatch       5 lines    all stored below external     [Re-check same-date]
market_cap_mismatch          5 lines    4 clustered at 2.3-3.1%       [Switch to share count]
valuation_sanity_block       8 lines    2 are non-voting lines        [Split by class]
```

The UI enforces the discipline. If the only affordance is a group action, you cannot accidentally spend an afternoon on one ticker.

### 9.4 Put the experiment log on the page

Unusual for a dashboard, correct for this one. A short table of the last changes, each with its metric before and after, turns the page from a status board into a lab notebook and makes the one-variable rule visible rather than aspirational.

### 9.5 Freshness as a calendar strip

Replace "4 days" with thirty cells, one per exchange trading day, filled where data exists and hollow where it does not. A weekend is not a gap. A missing Monday is, and it should be impossible to miss.

### 9.6 Visual language

Direction, in three words: quiet instrument panel. Trust-first, so the design dials sit low: symmetric and tabular rather than expressive, motion limited to state changes, density high but hierarchical.

Carrying over the contrast-validated dark tokens from the company page work: near-black surfaces, one accent, colour reserved strictly for state. Two additions specific to this page:

- **Amber for blocked, never red.** A feed that has not run is not an error, it is unfinished work, and it must not look like a failure.
- **A fourth status: not evaluable.** Rendered in muted grey with a hollow track. This is the visual counterpart of the E0 fix, and without it the redesign quietly reintroduces the same conflation in pixels.

Prose moves into tooltips and expandable notes. The explanatory writing on the current page is good, and it belongs one click away rather than between the numbers.

---

## 10. Build order

> **Status 2026-09-01:** steps 1–2 (the "instrument first" phase) shipped. `GET /data-health`
> now returns a `check_ledger` — every universe-wide check as pass / fail / not-evaluable with
> reason codes, `checkable_pct` and `pass_pct_of_checkable` — and the freshness metrics are split
> into `price_data_age_trading_days` (weekday sessions; a weekend is not a gap),
> `missing_trading_days` (the actual missed weekday dates) and `price_capture_last_success_at`
> (from `JobRun`). `market_cap_identity_pass_pct` / `price_ratio_actions_confirmed_pct` are now
> `passed ÷ (passed + failed)`, derived from the ledger so they can't diverge. The Data Health
> screen renders the ledger as a table and shows the CoE tile as a proxy-only caution while
> `capture_macro` has never succeeded. First real numbers: market-cap identity is **3.4%
> checkable** (the "50% pass" was 5 of 10 lines), corporate-action ratio is **91.4% of reviewed**
> (was reported ~15%), price-discontinuity is 0% checkable (`corporate_action_table_unpopulated`).
>
> **E3 (step 7) code shipped ahead of its feed run.** `float_data.published_price` (migration
> 0022) now captures `reqSymbolInfo.lastTradedPrice` from the same payload as `marketCap` and
> `quantityIssued`; the ledger has a new `share_count_identity` check —
> `implied_shares = published_market_cap ÷ published_price`, tolerance 0.5%. Until
> `enrich_securities` re-runs it reports **not-evaluable** for every line
> (`no_published_price_captured` on the 10 with a market cap, `no_published_market_cap` on the
> rest) — the honest E0 state, not a pass. **Pre-registered prediction:** after enrichment
> re-runs, the market-cap fails that cluster at 2.3–3.1% (ABL, ACME, AEL, AFS) mostly clear on
> `share_count_identity` because both inputs come from one self-consistent payload, while AFSL
> (5.95%, independently flagged by `share_count_reconciles`) stays a fail. **Falsifier:** if the
> share-count check still fails at a similar rate and sign, the errors are real share counts, a
> more serious finding than stale-price noise.
>
>
> **E4 + E7 diagnostics shipped** (steps 8–9's first half — "the diagnostic is a cohort split,
> not a ticker investigation"). Each identity check now carries a `cohorts` breakdown by issuer
> line count (E4), and `valuation_sanity` carries one by share class (E7), each a full
> pass/fail/not-evaluable split. First reads: **`.X` non-voting lines block the valuation
> sanity gate at ~10% (2 of 20) vs ~2.2% (6 of 270) for `.N`** — a ~4.5× rate difference, which
> is the class-defect signal E7 predicts (fair value from issuer-level fundamentals compared
> against a persistently-discounted non-voting price). The E4 issuer-multiplicity split is in
> place but not yet informative: only 1 of the 42 multi-line lines is even checkable — the rest
> have no published market cap on file, the same coverage gap E3 is blocked on.
>
> Steps 3–4 (run the CA and CBSL feeds — E5, E6) and the E1/E2/E4/E7 *fixes* (as opposed to the
> diagnostics now in place) are next.

**Instrument first**

1. E0, three-way split on every rate. No data changes. Nothing else is interpretable until this is done.
2. Split the freshness metrics, count in trading days.

**Free wins, no code**

3. Run the corporate actions feed, re-run the discontinuity check untouched (E5).
4. Run the CBSL feed, replace the proxy, measure how far fair values move (E6).

**Check redesign, one variable at a time**

5. Same-date comparison for second source (E1).
6. Tick-aware tolerance (E2).
7. Share-count comparison replacing market-cap comparison (E3).
8. Issuer-level aggregation for multi-line issuers (E4).
9. Per-class handling for non-voting lines (E7).

**Then the page**

10. Blocker list with causal links.
11. Check ledger table with trends.
12. Worklist grouped by cause with group actions.
13. Trading-day calendar strip.
14. Experiment log.

---

## 11. The one number to watch

Not the quarantine count, which should rise while detection improves. Not the alert count, which falls for good and bad reasons alike.

**Watch the share of the universe that is *checkable*.** Pass rate is a statement about your data. Coverage is a statement about how much of your data you have any right to an opinion on. A system at 95% pass on 40% coverage knows less than one at 80% pass on 95% coverage, and only the second one can honestly claim integrity.

*Fifth in the series with `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `aaf-factcheck-and-company-page-redesign.md`, `cse-universe-integrity-rollout.md`, and `company-page-and-homepage-redesign.md`.*
