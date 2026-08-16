# Open parameters (Master Spec Part O)

The spec lists eight decisions that must be made before Phase 1 and that
materially change the build. To keep moving, each has been given a **default**
below so the code has concrete numbers to work with. None of these are
hard-coded as magic numbers in the codebase — they all live in
`backend/app/config.py` as named settings, so changing one is a config edit,
not a refactor. **Treat every value here as provisional until you confirm it.**

| # | Question | Default chosen | Rationale / what changes if you pick differently |
|---|---|---|---|
| 1 | Capital base | **LKR 25,000,000** | Mid-point of the capacity curve the spec describes (LKR 5m–200m). Sets `MAX_POSITION_PCT_OF_ADV`, liquidity gate thresholds, and position caps in §11.1/§27.1. If your real capital is under ~10m, the liquidity gate (median daily turnover ≥ LKR 2.0m) should probably tighten; if it's over ~100m, it should loosen and the concentration caps matter much more. |
| 2 | Historical data depth | **2015-01-01** as the earliest point-in-time backfill target | Matches the spec's own estimate ("2015-onward may be clean, earlier patchy," Part O #2). Backtests before this date are not attempted. |
| 3 | Broker execution | **Manual** (system computes the entry ladder and displays it; no order is ever placed programmatically) | Consistent with Design Law 6 (§4) — no BUY button, no write access to order flow, ever. This is not really an open question given the design laws; it's fixed regardless of broker API availability. |
| 4 | Tax treatment | **Not modelled yet** — `net_return` in the decision/outcome record is post-fee, pre-tax | Sri Lankan capital-gains treatment depends on your residency and holding structure. Flagged as a TODO on the `outcomes` table rather than guessed. |
| 5 | Second data source | **Not yet identified** — reconciliation job is built against a pluggable `SecondarySource` interface with a stub implementation that always reports "unavailable" | This is a real operational risk per §5 ("the single biggest operational fragility"). Ingestion runs, but the nightly reconciliation test will flag every ticker as unverified against a second source until one is wired in. Cheapest option per the spec: a broker EOD file. |
| 6 | Dividend policy | **Total return** (dividends reinvested in the adjustment-factor series; DDM/FCFE anchors weighted per archetype table in §24, not overridden toward income) | If you're optimising for income rather than total return, the triangulation weights in §24 would need a distinct "income" profile. Not built. |
| 7 | Concentration appetite | **8–15 positions**, tier caps 10% / 6% / 3% (Tier 1/2/3) | Taken directly from §27.1 and §39.1 defaults. |
| 8 | Sector exclusions | **None encoded** | No sectors/structures are hard-excluded beyond the integrity and structural gates (§11.1). Add tickers or `cse_sector` values to `EXCLUDED_SECTORS` / `EXCLUDED_TICKERS` in config when you have a list. |

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
