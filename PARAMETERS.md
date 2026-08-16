# Open parameters (Master Spec Part O)

The spec lists eight decisions (Part O) that must be made before Phase 1
and that materially change the build; #9 below was added during the
build itself once it became a real, concrete choice rather than an
abstract one. To keep moving, each has been given a **default** below so
the code has concrete numbers to work with. Most of these live in
`backend/app/config.py` as named settings, so changing one is a config
edit, not a refactor — #9 in particular is an architectural choice, not a
config value. **Treat every value here as provisional until you confirm it.**

| # | Question | Default chosen | Rationale / what changes if you pick differently |
|---|---|---|---|
| 1 | Capital base | **LKR 25,000,000** | Mid-point of the capacity curve the spec describes (LKR 5m–200m). Sets `MAX_POSITION_PCT_OF_ADV`, liquidity gate thresholds, and position caps in §11.1/§27.1. If your real capital is under ~10m, the liquidity gate (median daily turnover ≥ LKR 2.0m) should probably tighten; if it's over ~100m, it should loosen and the concentration caps matter much more. |
| 2 | Historical data depth | **2015-01-01** as the earliest point-in-time backfill target | Matches the spec's own estimate ("2015-onward may be clean, earlier patchy," Part O #2). Backtests before this date are not attempted. |
| 3 | Broker execution | **Manual** (system computes the entry ladder and displays it; no order is ever placed programmatically) | Consistent with Design Law 6 (§4) — no BUY button, no write access to order flow, ever. This is not really an open question given the design laws; it's fixed regardless of broker API availability. |
| 4 | Tax treatment | **Not modelled yet** — `net_return` in the decision/outcome record is post-fee, pre-tax | Sri Lankan capital-gains treatment depends on your residency and holding structure. Flagged as a TODO on the `outcomes` table rather than guessed. |
| 5 | Second data source | **Still not identified for PRICES.** (Note: CBSL is now scraped for macro series, but that is a different need — it cross-checks nothing about share prices.) — corrected 16 Aug: an earlier version of this row claimed a pluggable `SecondarySource` interface existed; it doesn't. `app/jobs/reconciliation.py` only does the adjusted-vs-raw *internal* cross-check §7 requires (comparing our own stored `adj_factor` against an independent recomputation from our own confirmed corporate actions) — there is no cross-check against an independent second source of prices at all yet. | This is a real operational risk per §5 ("the single biggest operational fragility") and Part II §5.2 ("nightly cross-check against a second source... discrepancy >0.5% quarantines the ticker"). A single unofficial cse.lk endpoint remains a single point of failure until this exists. Cheapest option per the spec: a broker EOD file. |
| 6 | Dividend policy | **Total return** (dividends reinvested in the adjustment-factor series; DDM/FCFE anchors weighted per archetype table in §24, not overridden toward income) | If you're optimising for income rather than total return, the triangulation weights in §24 would need a distinct "income" profile. Not built. |
| 7 | Concentration appetite | **8–15 positions**, tier caps 10% / 6% / 3% (Tier 1/2/3) | Taken directly from §27.1 and §39.1 defaults. |
| 8 | Sector exclusions | **None encoded** | No sectors/structures are hard-excluded beyond the integrity and structural gates (§11.1). Add tickers or `cse_sector` values to `EXCLUDED_SECTORS` / `EXCLUDED_TICKERS` in config when you have a list. |
| 9 | LLM-assisted financial-statement extraction | **Not wired in** — `app/domain/financial_statement_parsing.py` does deterministic (regex/heuristic) extraction of a specific subset of line items instead; see its module docstring and README_ENDPOINTS.md gap #7 | Master Spec §5 calls for "PDF table extraction -> LLM-assisted line-item mapping." Actually calling an LLM needs an API key, a model choice, and a cost budget — none of which should be decided silently in code. The deterministic extractor covers total/subtotal-level balance sheet and income statement lines only (verified against one real filing); anything more (segment data, cash flow statement, note-level detail, or companies whose statements don't match the verified 4-column format) needs either broader deterministic rules or the LLM step this row is tracking. |

## Other defaults baked into Phase 1 code (not in Part O, but worth flagging)

- **Reporting lag defaults** (§6): 90 days for quarterlies, 180 days for
  audited annuals, per-company override via `securities.reporting_lag_days`.
- **Annual factor formation date**: 30 September (§6, §35.1) — not editable
  per-company, this is a market-wide convention in the spec.
- **cse.lk rate limiting**: minimum 2 seconds between calls, exponential
  backoff, circuit breaker after 5 consecutive failures (§5, "the single
  biggest operational fragility"). Configurable but defaults are deliberately
  conservative.
- **Reconciliation mismatch threshold**: 0.5%, matching §7 exactly.
