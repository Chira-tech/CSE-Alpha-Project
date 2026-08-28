"""
§36's Carhart certification, the pure regression half — Dimson (1979)
3-lag aggregated betas against §35's own 5 real factor series (MKT, SMB,
HML_hard, MOM, LIQ), Newey-West HAC standard errors, on real weekly data.
See `app.domain.carhart_view` for the DB-wired aggregator that pulls a
real ticker's weekly returns and the real factor series this module
regresses against.

WHY STATSMODELS HERE, NOT `app.domain.beta.py`'s HAND-ROLLED SOLVER.
`beta.py`'s own module docstring is explicit that this project avoids a
numpy/scipy dependency for its OWN single-factor case — but Newey-West
HAC standard errors have no simple closed form worth hand-deriving
(unlike Dimson's own three-lag OLS point estimate, which `beta.py`
already proves is a solvable normal-equations problem). `app.domain.
sector_sensitivity.py`'s own module reaches for the identical lazy
`statsmodels` import once HAC-adjacent inference is needed — this module
follows that same precedent, not a fresh dependency decision.

THE DIMSON DESIGN MATRIX, EXTENDED FROM ONE FACTOR TO FIVE. `beta.py`
regresses on the market's own return at t-1/t/t+1 (4 parameters:
intercept + 3 lags). This module regresses a ticker's weekly excess
return on FIVE factors' returns, each at t-1/t/t+1 (16 parameters:
intercept + 5 factors x 3 lags) — same alignment discipline `beta.py`
already establishes (regress by real DATE intersection across every
series, never by list position, so a week missing from one factor series
doesn't silently shift another factor's lag/lead pairing).

ONE FULL-SAMPLE REGRESSION, NEVER LABELLED "ROLLING." §35.3 wants a
156-week window re-estimated weekly — this system's real depth (~163
weeks as of this module's own build) supports at most one clean window,
not a genuine re-estimated series. `window_weeks_used = min(156,
weeks_available)` and `rolling_reestimation_supported` is always
`False` today — see `app.domain.rolling_alpha` for how the "rolling
36-month alpha path" §36 also asks for is handled honestly given the
same real depth limit.

GATING, NOT A CONFIDENT NUMBER FROM TOO LITTLE OR TOO NOISY DATA.
`MIN_OBSERVATIONS_FOR_CARHART = 80`: the 16-parameter design matrix
needs a real observations-per-parameter floor to mean anything — 5 per
parameter (a standard OLS rule of thumb) gives 80, well above `beta.py`'s
own `MIN_OBSERVATIONS = 30` for its 4-parameter case, in the same
"MIN_OBSERVATIONS is a judgement call, not a number in the spec" spirit
that module's own docstring already names. `alpha_is_noise` is `True`
when EITHER `|t-stat| < ALPHA_TSTAT_EVIDENCE_THRESHOLD` (1.5, §36's own
literal bar) OR `r_squared < R_SQUARED_NOISE_THRESHOLD` (0.15, §36's own
literal bar) — an OR, disclosed as such, since either failure alone is
real reason not to trust the alpha as evidence, matching `app.domain.
composite_score.py`'s own "never present a number you don't trust as
confident" discipline.

A REAL, ADDITIONAL STATISTICAL RISK THIS SCOPE MUST DISCLOSE:
COLLINEARITY. Two real, distinct sources, both worth naming rather than
conflated into one number: (1) STRUCTURAL — each factor's own lag/
contemporaneous/lead columns are the SAME series shifted by one week
three times, so a Dimson design is mechanically more collinear than a
plain single-lag OLS even with perfectly independent factors (verified
directly: 5 independently-drawn synthetic series with zero real
correlation still produce a condition number around 70 purely from this
structure — see `tests/test_carhart_regression.py`'s own noiseless
recovery test); (2) REAL cross-factor correlation, since all five
factors are built from `two_by_three_sort` on the SAME thin ~290-ticker
universe (see `app.domain.factor_series_view`'s own module docstring),
with genuine potential for overlapping constituents between, say,
HML_hard and MOM. `collinearity_warning` fires from the design matrix's
condition number (`numpy.linalg.cond`) only above `COLLINEARITY_
CONDITION_NUMBER_THRESHOLD` (100 — set above the ~70 structural baseline
so this flags GENUINE additional cross-factor collinearity, not just the
Dimson design's own unavoidable shape) — disclosed, not blocking, the
same "name a real risk rather than silently absorb it" discipline
`sector_sensitivity.py`'s own docstring already models for its own
regressions.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

FACTOR_NAMES: tuple[str, ...] = ("MKT", "SMB", "HML_hard", "MOM", "LIQ")

MIN_OBSERVATIONS_FOR_CARHART = 80
ALPHA_TSTAT_EVIDENCE_THRESHOLD = Decimal("1.5")
R_SQUARED_NOISE_THRESHOLD = Decimal("0.15")
NEWEY_WEST_LAGS = 4
SIGNIFICANCE_THRESHOLD = Decimal("0.05")  # matches app.domain.sector_sensitivity's own constant
COLLINEARITY_CONDITION_NUMBER_THRESHOLD = Decimal("100")
PRIMARY_WINDOW_WEEKS = 156

#: §36's own literal portfolio-level alert bars.
PORTFOLIO_BETA_HML_ALERT = Decimal("1.2")
PORTFOLIO_BETA_MOM_ALERT = Decimal("0.8")

WEEKS_PER_YEAR = Decimal(52)


@dataclass(frozen=True)
class FactorBeta:
    factor_name: str
    beta_true: Decimal
    """`lag_coefficient + contemporaneous_coefficient + lead_coefficient`
    — Dimson's own aggregated beta."""
    lag_coefficient: Decimal
    contemporaneous_coefficient: Decimal
    lead_coefficient: Decimal
    t_stat: Decimal
    """Newey-West HAC t-statistic on `beta_true` — computed via the
    linear combination's own HAC variance (sum of the three coefficients'
    HAC covariance block), not the naive sum of three individual
    t-stats, which would ignore their real covariance."""
    p_value: Decimal
    significant: bool


@dataclass(frozen=True)
class DimsonFactorRegressionResult:
    alpha_annualized: Decimal | None
    alpha_tstat: Decimal | None
    alpha_is_noise: bool
    alpha_noise_reasons: tuple[str, ...]
    betas: tuple[FactorBeta, ...]
    r_squared: Decimal | None
    residual_volatility_annualized: Decimal | None
    residuals_by_date: tuple[tuple[dt.date, Decimal], ...]
    """The fitted regression's own residual at each real used date —
    §37's own Residual momentum signal is "t-12 to t-2 momentum computed
    on Carhart residuals, not raw returns" (stripping the factor-driven
    component to leave stock-specific drift), and this is that series.
    Empty when `insufficient_data`."""
    observation_count: int
    window_weeks_used: int
    rolling_reestimation_supported: bool
    newey_west_lags: int
    collinearity_warning: str | None
    insufficient_data: bool
    reason: str | None


def _empty_result(observation_count: int, reason: str) -> DimsonFactorRegressionResult:
    return DimsonFactorRegressionResult(
        alpha_annualized=None, alpha_tstat=None, alpha_is_noise=True, alpha_noise_reasons=(reason,),
        betas=(), r_squared=None, residual_volatility_annualized=None, residuals_by_date=(),
        observation_count=observation_count, window_weeks_used=0, rolling_reestimation_supported=False,
        newey_west_lags=NEWEY_WEST_LAGS, collinearity_warning=None, insufficient_data=True, reason=reason,
    )


def fit_carhart_dimson(
    excess_returns: dict[dt.date, Decimal],
    factor_returns: dict[str, dict[dt.date, Decimal]],
    *, window_weeks: int = PRIMARY_WINDOW_WEEKS,
) -> DimsonFactorRegressionResult:
    """Regresses `excess_returns` (a ticker's own weekly return minus
    that week's risk-free rate — the caller builds this, see
    `app.domain.carhart_view`) on all five factors' returns at t-1/t/t+1,
    real-date-aligned, using at most the most recent `window_weeks` real
    weeks common to every series involved.

    `insufficient_data=True` (never a fabricated number) below
    `MIN_OBSERVATIONS_FOR_CARHART`, or when the design matrix is
    singular (e.g. a factor with zero variance over the window)."""
    missing_factors = [name for name in FACTOR_NAMES if name not in factor_returns]
    if missing_factors:
        return _empty_result(0, f"missing factor series: {', '.join(missing_factors)}")

    common_dates = sorted(
        set(excess_returns) & set.intersection(*(set(factor_returns[f]) for f in FACTOR_NAMES))
    )
    if window_weeks > 0:
        common_dates = common_dates[-(window_weeks + 2):]  # +2: need a real lag and lead around each usable point

    if len(common_dates) < MIN_OBSERVATIONS_FOR_CARHART + 2:
        return _empty_result(
            len(common_dates),
            f"only {len(common_dates)} real overlapping week(s) across the ticker and all 5 factors, "
            f"need at least {MIN_OBSERVATIONS_FOR_CARHART + 2}",
        )

    import numpy as np
    import statsmodels.api as sm

    rows: list[list[float]] = []
    y: list[float] = []
    used_dates: list[dt.date] = []
    for i in range(1, len(common_dates) - 1):
        date_t = common_dates[i]
        if date_t not in excess_returns:
            continue
        row = [1.0]
        ok = True
        for name in FACTOR_NAMES:
            series = factor_returns[name]
            d_lag, d_0, d_lead = common_dates[i - 1], date_t, common_dates[i + 1]
            if d_lag not in series or d_0 not in series or d_lead not in series:
                ok = False
                break
            row.extend([float(series[d_lag]), float(series[d_0]), float(series[d_lead])])
        if not ok:
            continue
        rows.append(row)
        y.append(float(excess_returns[date_t]))
        used_dates.append(date_t)

    if len(rows) < MIN_OBSERVATIONS_FOR_CARHART:
        return _empty_result(
            len(rows), f"only {len(rows)} real usable observation(s) after lag/lead alignment, "
            f"need at least {MIN_OBSERVATIONS_FOR_CARHART}",
        )

    X = np.array(rows)
    Y = np.array(y)

    cond = Decimal(str(round(float(np.linalg.cond(X)), 2)))
    collinearity_warning = (
        f"design matrix condition number {cond} exceeds {COLLINEARITY_CONDITION_NUMBER_THRESHOLD} — "
        f"beyond the ~70 baseline a Dimson 3-lag design has even for independent factors — real cross-"
        f"factor correlation on this thin universe, individual betas may be unstable"
        if cond > COLLINEARITY_CONDITION_NUMBER_THRESHOLD else None
    )

    try:
        ols_fit = sm.OLS(Y, X).fit()
        model = ols_fit.get_robustcov_results(cov_type="HAC", maxlags=NEWEY_WEST_LAGS)
    except Exception as exc:  # noqa: BLE001 — a real, possible numerical failure (e.g. singular matrix), not hypothetical
        return _empty_result(len(rows), f"regression failed to solve: {exc}")

    params = model.params
    if len(params) != 1 + 3 * len(FACTOR_NAMES) or any(np.isnan(params)) or any(np.isinf(params)):
        return _empty_result(len(rows), "regression produced a degenerate or non-finite result")

    def _dec(v: float) -> Decimal:
        return Decimal(str(round(v, 8)))

    alpha_weekly = params[0]
    alpha_annualized = _dec(alpha_weekly * float(WEEKS_PER_YEAR))
    # HAC variance of the intercept alone (its own diagonal cov entry).
    alpha_se = float(model.cov_params()[0, 0]) ** 0.5
    alpha_tstat = _dec(alpha_weekly / alpha_se) if alpha_se > 0 else None

    betas: list[FactorBeta] = []
    cov = model.cov_params()
    for fi, name in enumerate(FACTOR_NAMES):
        idx = 1 + fi * 3  # lag, 0, lead
        lag_c, c0, lead_c = params[idx], params[idx + 1], params[idx + 2]
        beta_true = lag_c + c0 + lead_c
        # Variance of a sum of 3 coefficients = sum of their pairwise HAC covariances.
        block = cov[idx:idx + 3, idx:idx + 3]
        var_sum = float(np.sum(block))
        se = var_sum**0.5 if var_sum > 0 else None
        t_stat = (beta_true / se) if se else 0.0
        # Two-sided p-value from the t-distribution using the model's own residual df.
        from scipy import stats as _stats  # lazy — statsmodels already depends on scipy
        p_value = float(2 * (1 - _stats.t.cdf(abs(t_stat), df=model.df_resid))) if se else 1.0
        betas.append(
            FactorBeta(
                factor_name=name, beta_true=_dec(beta_true),
                lag_coefficient=_dec(lag_c), contemporaneous_coefficient=_dec(c0), lead_coefficient=_dec(lead_c),
                t_stat=_dec(t_stat), p_value=Decimal(str(round(p_value, 6))),
                significant=Decimal(str(round(p_value, 6))) < SIGNIFICANCE_THRESHOLD,
            )
        )

    r_squared = _dec(ols_fit.rsquared)
    residual_std_weekly = float(np.std(ols_fit.resid, ddof=len(params)))
    residual_vol_annualized = _dec(residual_std_weekly * (float(WEEKS_PER_YEAR) ** 0.5))
    residuals_by_date = tuple(
        (used_dates[i], _dec(float(ols_fit.resid[i]))) for i in range(len(used_dates))
    )

    noise_reasons: list[str] = []
    if alpha_tstat is None or abs(alpha_tstat) < ALPHA_TSTAT_EVIDENCE_THRESHOLD:
        noise_reasons.append(f"|alpha t-stat| < {ALPHA_TSTAT_EVIDENCE_THRESHOLD}")
    if r_squared < R_SQUARED_NOISE_THRESHOLD:
        noise_reasons.append(f"R-squared < {R_SQUARED_NOISE_THRESHOLD}")

    window_weeks_used = len(used_dates)
    return DimsonFactorRegressionResult(
        alpha_annualized=alpha_annualized, alpha_tstat=alpha_tstat,
        alpha_is_noise=bool(noise_reasons), alpha_noise_reasons=tuple(noise_reasons),
        betas=tuple(betas), r_squared=r_squared, residual_volatility_annualized=residual_vol_annualized,
        residuals_by_date=residuals_by_date,
        observation_count=len(rows), window_weeks_used=window_weeks_used,
        rolling_reestimation_supported=False, newey_west_lags=NEWEY_WEST_LAGS,
        collinearity_warning=collinearity_warning, insufficient_data=False, reason=None,
    )


def portfolio_beta_alert(betas: tuple[FactorBeta, ...]) -> tuple[str, ...]:
    """§36's own portfolio-level rule: "If aggregate beta_HML > 1.2 or
    beta_MOM > 0.8, you have accidentally become a single-factor fund."
    Applied here to any `DimsonFactorRegressionResult.betas` — a
    per-ticker call as easily as `app.domain.carhart_view.portfolio_
    carhart_for`'s own portfolio-level aggregate."""
    alerts: list[str] = []
    by_name = {b.factor_name: b for b in betas}
    hml = by_name.get("HML_hard")
    if hml is not None and hml.beta_true > PORTFOLIO_BETA_HML_ALERT:
        alerts.append(f"beta_HML_hard={hml.beta_true} exceeds {PORTFOLIO_BETA_HML_ALERT} — single-factor concentration risk")
    mom = by_name.get("MOM")
    if mom is not None and mom.beta_true > PORTFOLIO_BETA_MOM_ALERT:
        alerts.append(f"beta_MOM={mom.beta_true} exceeds {PORTFOLIO_BETA_MOM_ALERT} — single-factor concentration risk")
    return tuple(alerts)
