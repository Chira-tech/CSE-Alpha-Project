# SYSTEM_AUDIT.md

STEP 1 deliverable of `CSE_Alpha_Engine_System_Wide_Valuation_Upgrade.md`
(§31 Phase 1, §49 STEP 1). Audited 29 Aug 2026 against the live codebase
and the live dev database, not from memory.

**Scale:** 87 domain modules (~20,000 LOC) under `backend/app/domain/`,
61 API endpoints, 18 tables, 1,398 passing tests.

Every figure below was re-queried against `backend/devdb.sqlite` while
writing this document. Several numbers quoted earlier in development were
stale and are corrected here.

---

## 0. The headline finding, because it changes the plan

**The upgrade brief's own §1.1 example already identifies the single most
important defect, and it is deeper than the brief states.** The brief
notes DPL's output as:

    Justified P/B: 12.52
    Residual Income: 12.52      <- identical
    FCFF DCF: 50.99
    Triangulated Blend: 22.70

Those first two are not coincidentally equal. Proved algebraically and
confirmed live on every company tested (COMB, HNB, RIL all return a ratio
of exactly 1.05000 = 1+g):

    JPE_fv = (1 - g/ROE)(1+g)/(Ke-g) x EPS,   EPS = ROE x BVPS exactly
           = (ROE-g)(1+g)/(Ke-g) x BVPS
           = JPB_fv x (1+g)

Justified P/B, justified P/E and residual income (under this system's
flat-ROE baseline) are **one Gordon model wearing three hats**. Residual
income is called with `roe_forecast_path=(roe,)` and `terminal_roe=roe`,
which collapses it onto justified P/B exactly.

**Consequence for the upgrade:** §20's dispersion metric and any
"dynamic weights" scheme (§10-13) will produce confident-looking
agreement that is pure arithmetic unless the Gordon family is treated as
ONE model contributing ONE weight. Measured on the live universe: of 56
valued tickers, 43 sit at 1-10% dispersion and 12 under 1% — almost all
of that spread is the `(1+g)` factor, not model disagreement. Exactly one
ticker (DPL) shows >50%, because it is the only one where a structurally
different model (FCFF DCF) currently contributes.

This is already disclosed at runtime: `relative_valuation_for` emits a
warning on every valuation that computes justified P/E, and
`test_justified_pe_is_exactly_justified_pb_times_one_plus_g` pins the
identity.

---

## 1. Inventory — what already exists

The brief is written as though most of this must be built. Much of it
exists. Mapping each brief requirement to the live module:

| Brief section | Requirement | Status | Where |
|---|---|---|---|
| §2 | Archetype-aware valuation | **EXISTS** | `archetype.py` (15 Appendix-P2 archetypes), `valuation_router.py` |
| §3 | Formal routing engine | **PARTIAL** | `valuation_router.py` returns applicable/suppressed models each with a stated reason; has **no** status enum, weight, data-completeness or model-confidence |
| §4 Layer A | Asset / NAV | **PARTIAL** | `asset_based_valuation.py` (hard book, land marks, liquidation floor) is real and tested but **informational only** — not a triangulation anchor (PARAMETERS #15). **Haircut framework does not exist.** |
| §5 Layer B | Normalized earnings | **NOT BUILT** | no normalization module anywhere |
| §6 Layer C | DCF + reverse DCF | **PARTIAL** | `dcf.py` (525 loc) has three-stage FCFF/FCFE, terminal value, equity bridge, and a reverse-DCF bisection solver. Reverse-DCF **outputs** (required CAGR / terminal margin / ROIC / FCFF) are not surfaced |
| §7 | DCF confidence score | **NOT BUILT** | — |
| §8 Layer D | Peer relative valuation | **PARTIAL** | `relative_valuation.py` computes *justified* multiples (fundamental, not peer). `sector_percentiles.py` does real sector-relative ranking but is wired to the composite score, not to valuation |
| §14-16 | Buy / sell price | **EXISTS** | `price_ladder.py` — five zones, tested against §26's own worked example to the cent |
| §19 | Margin of safety | **EXISTS** | `margin_of_safety.py` — 5 components, each clamped to its stated range |
| §20 | Dispersion | **EXISTS but misleading** | `triangulation.py.dispersion_pct` — see §0 above |
| §21 | Data quality affects recommendation | **PARTIAL** | `sanity.py` plausibility gate, `provenance.py` §8 tiers, `valuation_quarantine_view.py` |
| §22 | Coverage gates | **EXISTS, fails closed** | `coverage_gates.py` — all three gates implemented and tested. Gate 2 always fails with *"free float unknown — no shareholding disclosure ingested"*: `securities` has **no free-float column at all**, so the caller can only pass `None`. The gate is correct; the data source is missing |
| §23 | Missing data never becomes a fake number | **EXISTS — core discipline** | every view returns `None` with a named reason; CI guard `check-no-zone-fallback.mjs` |
| §24 | Historical financial data engine | **EXISTS** | `fundamentals` table (113,801 rows), `point_in_time.py` |
| §25 | Trend metrics | **EXISTS** | `trend_detection.py` — Mann-Kendall, acceleration, consistency |
| §26 | Turnaround detection | **NOT BUILT** | — |
| §27 | Distress detection | **NOT BUILT** | Altman Z is in `ratios.NOT_YET_COMPUTABLE` |
| §28 | Sector-aware ratios | **EXISTS** | `sector_percentiles.py` |
| §29 | Scoring independent of valuation | **EXISTS** | `composite_score.py` — 7 pillars; valuation deliberately shown as evidence, not blended |
| §30 | Recommendation logic | **PARTIAL** | price-ladder zone is the recommendation; no separate quality/valuation/risk composition |
| §42 | No look-ahead bias | **EXISTS — core discipline** | `point_in_time.py`, `first_available_date` on every row |
| §45 | Opportunity ranking | **PARTIAL** | `opportunity_ranking_view.py` ranks by gap-to-buy-below, a disclosed proxy for §40's risk-adjusted return |

### Pipeline (source → function → output)

```
cse.lk / CDN PDFs
  → ingestion/financial_pdf_extractor.py  → fundamentals (113,801 rows)
  → ingestion/price_loader.py             → prices_daily (200,817 rows;
                                            110,350 now carry adj_factor != 1)
  → ingestion/corporate_actions_loader.py → corporate_actions (1,810)
  → ingestion/cbsl_*                      → macro_series

fundamentals ─ point_in_time ─ provenance(§8) ─→ valuation_view._confirmable_line_items
                                                   ├→ ratios.py            → composite_score
                                                   ├→ cost_of_equity ─ beta ─ regime
                                                   ├→ justified_pb / residual_income / relative
                                                   ├→ dcf_for ← wacc
                                                   └→ triangulation → margin_of_safety → price_ladder
                                                                            ↓
                                              opportunity_ranking_view → /opportunities
```

---

## 2. Known limitations (measured today, not assumed)

| # | Limitation | Evidence |
|---|---|---|
| L1 | Gordon family is one model, not three | §0 above |
| L2 | Only **56 of 283** tickers produce a fair value | live `opportunity_ranking_for` run |
| L3 | FCFF DCF runs for a **single-digit** number of tickers. `operating_profit` is missing for 211/294 and `capital_expenditure` for 199/294 — but **that headline overstates the fixable gap**, see L3a | re-queried 29 Aug |
| L3a | **59 of the 294 are banks, finance companies or insurers, and correctly have neither line.** `valuation_router` already lists "Free cash flow" among their `meaningless_metrics`, so an FCFF DCF is never routed to them; chasing these lines for financials would be building toward a model that must not run. A further 58 have no archetype (L4), so their routing is blocked regardless. The **real target is the 177 non-financial tickers**, of which only **28 have both lines** — 113 are missing each. That, not 211, is the number to move | measured by archetype 29 Aug |
| L4 | **58 of 294** tickers have no archetype, which blocks §16 routing entirely by design | `securities.archetype IS NULL` |
| L5 | SOTP unwired — no segment/ownership data source exists | `_NOT_YET_BUILT` |
| L6 | Gate 2 can never pass: `securities` has **no free-float column**, and no shareholding-disclosure ingestion exists. Gate 3 likewise has no Beneish/audit/related-party source | `coverage_gates.py` |
| L7 | 41 tickers produce a **negative or zero** fair value; 19 withheld by the plausibility gate; 17 quarantined | live run |
| L8 | Confirm queue now holds **15,119** unconfirmed rows — up from 7,198, because the 29 Aug reconcile sweep re-extracted filings under the new label variants and created 7,921 fresh drafts. Growth is expected, not regression, but it must be worked down | `fundamentals.confirmed_at IS NULL` |
| L11 | **580** corporate actions still pending confirmation | `corporate_actions.confirmed_at IS NULL` |
| L9 | Depreciation is taken from the first matching page, which on some filings is a parent/segment column rather than consolidated | verified on JKH |
| L10 | Peer-relative valuation does not exist as a valuation layer | §8 above |

---

## 3. What the brief asks for that is genuinely NEW work

In dependency order (which differs slightly from §49's STEP list, for the
reason given):

1. **Model metadata on routing** (§3) — status enum, `data_completeness`,
   `model_confidence`, `recommended_weight`, `contribution`. This is the
   spine everything else hangs off, and `valuation_router.py` already has
   the archetype logic to attach it to.
2. **Collapse the Gordon family to one weighted contribution** (§0/§20).
   Must come before dynamic weights, or the weights will be wrong.
3. **Normalized earnings engine** (§5) — genuinely absent; needs the
   5-10y history that `fundamentals` already holds.
4. **Adjusted/conservative NAV with sector-aware haircuts** (§4) — the
   valuation math exists; the haircut framework does not.
5. **DCF confidence + reverse-DCF outputs** (§6/§7).
6. **Peer relative valuation as a layer** (§8) — `sector_percentiles.py`
   is reusable for this.
7. **Turnaround (§26) and distress (§27) detection.**
8. **Recommendation composition** (§30) — quality / valuation / risk /
   data-quality kept separate.

### Prerequisite that gates items 3-6

`operating_profit` and `capital_expenditure` extraction — but scoped to
the **177 non-financial tickers** (L3a), where only 28 currently have
both. A normalized-earnings engine over 5-10 years of history, or a DCF
confidence score built on FCFF stability, cannot be computed for
companies whose income-statement and cash-flow lines are not extracted.

**A tempting shortcut that was tested and rejected.** `operating_profit`
looks derivable from lines already confirmed, via the standard EBIT
identity `operating_profit = profit_before_tax + interest_expense`, which
would have newly covered 53 of the 113 missing tickers at zero
extraction cost. It was validated against the 190 real rows that carry
all three figures, and it fails:

| | within 1% | within 10% | median error |
|---|---|---|---|
| annual (n=80) | 1% | 25% | −6.0% |
| quarterly (n=110) | 2% | 19% | +19.1% |

with a p10/p90 spread of −90% to +234%, overstating in 111 of 190 cases
— the direction that inflates FCFF and therefore fair value. A figure
that wrong in the unsafe direction, while looking exactly as precise as
a reported one, is precisely what §23 and this codebase's own
"never a fabricated number" rule exist to prevent. **Not implemented.**
(The check also surfaced that `interest_expense` carries mixed signs —
median −0.05× |PBT| — a separate data-quality issue worth its own pass.)

So extraction is the only sound lever. This module's standing rule is
that a canonical label is added only after being seen on a real filing,
never guessed. The gap is therefore **measured** rather than patched
speculatively:
`scripts/measure_unmatched_labels.py` re-parses filings already on file,
collects every label that parses as a line item but matches no canonical
key, and ranks those wordings by how many distinct companies print them.
Wordings used by many companies are worth adding; a wording used by one
is that company's own phrasing and stays unmatched.

---

## 4. Principles this codebase already enforces, which the upgrade must not regress

- **Never a fabricated number.** Every view returns `None` with a named
  reason instead of a plausible-looking default. §23 of the brief asks
  for exactly this; it is already the project's strongest discipline and
  has its own CI guard.
- **§8 provenance gate.** Nothing unconfirmed reaches a fair value.
- **§6 point-in-time.** Every query filters `first_available_date <= t`.
- **Directionally safe defaults.** Where a figure must be defaulted, it
  is defaulted in the direction that *understates* value (missing cost of
  debt, missing D&A), and says so.
- **Disclosed, not silent.** Deviations from spec numbers are recorded in
  `PARAMETERS.md` with the measurement that justified them.
