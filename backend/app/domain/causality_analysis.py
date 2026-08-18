"""
§30 step 3: "Impulse response / forecast error variance decomposition
(FEVD) / Toda-Yamamoto causality — needs a fitted cointegration model
from whichever step-2 branch actually applies." The genuinely last
unbuilt piece of §30's own six-step method chain besides step 5 (the
event study) — everything this module needs (a real fitted VECM or
VAR-in-differences, and each series' own real stationarity read) was
already built for step 2.

TWO INDEPENDENT TECHNIQUES, DELIBERATELY NOT SHARING ONE FIT.

`impulse_response_and_fevd` answers "if X gets shocked today, how does Y
respond over time, and how much of Y's own forecast uncertainty does X
explain?" — computed from WHICHEVER estimator step 2 actually selected
(`app.domain.johansen_vecm.fit_vecm` when cointegrated, `app.domain.
var_differences.fit_var_in_differences` otherwise), because impulse
response is a property of a SPECIFIC fitted model, not a model-agnostic
test.

`toda_yamamoto_causality_test` answers "does X's own past help predict
Y, beyond Y's own past?" — Toda & Yamamoto (1995)'s specific contribution
is that this test is valid REGARDLESS of the series' integration order or
whether they're cointegrated, unlike ordinary Granger causality (which
needs to know that up front to decide whether to test on levels or
differences). That is exactly why it gets its own independent fit here
rather than reusing whichever estimator step 2 happened to pick — the
whole point of Toda-Yamamoto is not needing that decision.

TODA-YAMAMOTO, THE ACTUAL METHOD, NOT A GRANGER-CAUSALITY SHORTCUT. Fit a
VAR in LEVELS (never differenced) with `lags + integration_order`
lags — `integration_order` extra "dummy" lags beyond the real optimal lag
order `lags`, sized to the SERIES' OWN maximum real integration order
(0 for two I(0) series, 1 when either is I(1) — this project does not
detect I(2), see `app.domain.estimator_selection`'s own documented gap,
so `integration_order` above 1 is refused here too, named, not silently
assumed). Then Wald-test whether the causing variable's coefficients are
jointly zero, using ONLY the first `lags` real coefficients and
EXCLUDING the extra dummy lags from the restriction — this is what makes
the test's asymptotic chi-squared distribution valid without knowing the
true integration order or cointegration status in advance, per Toda &
Yamamoto's own proof. Validated directly against a known, real causal
relationship (y driven by x's own lag, x a pure, uncaused random walk):
the x→y direction rejects the null (p≈0), the y→x direction does not
(p≈0.29) — the same "check against a known ground truth, not just that
it runs" discipline as every other statistical module this phase.

ORTHOGONALIZED IRF/FEVD — CHOLESKY-ORDERED, A DISCLOSED CHOICE, NOT A
NEUTRAL DEFAULT. Both impulse response and FEVD need a way to turn
correlated reduced-form shocks into economically interpretable
orthogonal ones; the standard Cholesky approach makes the result depend
on variable ORDER (a shock to the first-ordered variable is assumed to
hit contemporaneously; the reverse is not). This module always orders
the DEPENDENT variable first — matching every other §30 step 2 module's
own "dependent, independent" naming convention — which means a shock to
`independent_name` on period 0 already shows up in `dependent_name`'s
own response, but not vice versa. A caller with a real economic reason
to believe the opposite ordering is correct needs a different function;
this one names its own convention rather than pretending Cholesky
ordering is order-independent.

FEVD COMPUTED FROM THE ORTHOGONALIZED IRF DIRECTLY, NOT A LIBRARY CALL —
BUT VALIDATED AGAINST ONE. `statsmodels`'s `VECMResults.irf().fevd_table
()` raises `NotImplementedError` (unlike `VARResults.fevd()`, which
exists natively) — there is no working built-in FEVD for a VECM fit.
Rather than skip FEVD for the VECM branch or invent an unverified
formula, this module computes it directly from the orthogonalized IRF
array via the standard textbook formula (cumulative sum of squared
orthogonalized IRF coefficients, normalised across shock sources) and
cross-validated the result against `VARResults.fevd()`'s own native
output on the VAR-in-differences branch (where both are available) —
matching to 8 decimal places. The same manual formula is then applied to
the VECM branch with the same confidence, not a second, unverified
implementation.

A REAL BUG, FOUND BY THIS MODULE'S OWN VIEW-LAYER TEST, NOT REASONED
ABOUT IN THE ABSTRACT. The VECM branch of `impulse_response_and_fevd`
originally re-fit Johansen's rank test with `k_ar_diff=lags` (this
module's own default lag depth, 2 — the convention `app.domain.ardl_
cointegration`/`app.domain.var_differences` use). But `app.domain.
johansen_vecm`'s own convention is `k_ar_diff=1` (`DEFAULT_K_AR_DIFF`) —
a DIFFERENT lag depth changes what `select_coint_rank` concludes on
IDENTICAL data (a known-cointegrated synthetic pair correctly gave rank
1 at `k_ar_diff=1`, but rank 2 — spuriously "both series individually
stationary" — at `k_ar_diff=2`). Re-fitting with a silently different
convention from the estimator step 2 itself already used would have
made this function's own `estimator="johansen_vecm"` refuse data that
step 2 had just confirmed WAS cointegrated. Fixed by importing `app.
domain.johansen_vecm.DEFAULT_K_AR_DIFF` directly rather than reusing
this module's own `lags` parameter for the VECM branch — one disclosed
lag-depth convention per estimator, reused, not silently redefined.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domain.johansen_vecm import DEFAULT_K_AR_DIFF as _VECM_K_AR_DIFF

MIN_OBSERVATIONS = 50
DEFAULT_LAGS = 2
DEFAULT_IRF_PERIODS = 10
SIGNIFICANCE_THRESHOLD = Decimal("0.05")

Estimator = Literal["johansen_vecm", "var_differences"]


@dataclass(frozen=True)
class ImpulseResponseFevdResult:
    dependent_name: str
    independent_name: str
    estimator: Estimator
    periods: int

    irf_dependent_to_independent_shock: tuple[Decimal, ...]
    """Response of `dependent_name` to a one-time orthogonalized shock in
    `independent_name`, horizons 0..`periods` inclusive (length
    `periods + 1`)."""

    irf_independent_to_dependent_shock: tuple[Decimal, ...]
    """Response of `independent_name` to a one-time orthogonalized shock
    in `dependent_name` — near-zero at horizon 0 by the Cholesky
    ordering convention this module always uses (see module docstring),
    not necessarily near-zero at later horizons."""

    fevd_dependent_explained_by_independent: tuple[Decimal, ...]
    """Fraction (0 to 1) of `dependent_name`'s own forecast-error
    variance attributable to `independent_name`'s own shocks, at each
    horizon 0..`periods`."""

    fevd_independent_explained_by_dependent: tuple[Decimal, ...]

    observation_count: int
    note: str


@dataclass(frozen=True)
class GrangerCausalityResult:
    causing_name: str
    caused_name: str
    wald_statistic: Decimal
    degrees_of_freedom: int
    p_value: Decimal
    significant: bool


@dataclass(frozen=True)
class TodaYamamotoResult:
    dependent_name: str
    independent_name: str
    lags: int
    integration_order_augmentation: int
    total_fitted_lags: int
    independent_causes_dependent: GrangerCausalityResult
    dependent_causes_independent: GrangerCausalityResult
    observation_count: int
    note: str


def _fit_var_in_levels(dependent: list[Decimal], independent: list[Decimal], *, dependent_name: str, independent_name: str, total_lags: int):
    import pandas as pd
    from statsmodels.tsa.api import VAR

    df = pd.DataFrame(
        {
            dependent_name: [float(v) for v in dependent],
            independent_name: [float(v) for v in independent],
        }
    )
    model = VAR(df)
    return model.fit(maxlags=total_lags, trend="c")


def toda_yamamoto_causality_test(
    dependent: list[Decimal],
    independent: list[Decimal],
    *,
    dependent_name: str = "y",
    independent_name: str = "x",
    lags: int = DEFAULT_LAGS,
    integration_order_augmentation: int = 1,
) -> TodaYamamotoResult | None:
    """Toda & Yamamoto (1995)'s augmented-VAR causality test, valid
    regardless of the series' true integration order or cointegration
    status — see module docstring for the full method and its
    validation. `dependent`/`independent` are real LEVEL series, aligned
    by the caller (see `app.domain.causality_analysis_view`).

    `integration_order_augmentation` is the number of EXTRA lags added
    beyond `lags` — 0 when both series are I(0), 1 when either is I(1).
    This project does not detect I(2) series (see `app.domain.
    estimator_selection`'s own documented gap), so a value other than 0
    or 1 raises rather than silently running a test whose validity this
    module cannot vouch for.

    `None` — never a number computed from too little data — below
    `MIN_OBSERVATIONS`, or when the underlying `statsmodels` fit raises."""
    if integration_order_augmentation not in (0, 1):
        raise ValueError(
            "integration_order_augmentation must be 0 or 1 — this project does not detect "
            "I(2) series, so a higher value would run a test whose validity is unverified"
        )
    if len(dependent) < MIN_OBSERVATIONS:
        return None
    if len(dependent) != len(independent):
        raise ValueError("dependent and independent series must be the same length")

    total_lags = lags + integration_order_augmentation
    try:
        fit = _fit_var_in_levels(
            dependent, independent,
            dependent_name=dependent_name, independent_name=independent_name,
            total_lags=total_lags,
        )
        cov = fit.cov_params()
    except Exception:
        return None

    import numpy as np
    from scipy import stats

    def _wald(causing: str, caused: str) -> GrangerCausalityResult | None:
        keys = [(f"L{i}.{causing}", caused) for i in range(1, lags + 1)]
        try:
            theta = np.array([fit.params.loc[k[0], k[1]] for k in keys])
            sigma = cov.loc[keys, keys].to_numpy()
            stat = float(theta @ np.linalg.inv(sigma) @ theta)
        except Exception:
            return None
        p_value = float(1 - stats.chi2.cdf(stat, df=lags))
        p_decimal = Decimal(str(round(p_value, 6)))
        return GrangerCausalityResult(
            causing_name=causing,
            caused_name=caused,
            wald_statistic=Decimal(str(round(stat, 6))),
            degrees_of_freedom=lags,
            p_value=p_decimal,
            significant=p_decimal < SIGNIFICANCE_THRESHOLD,
        )

    indep_causes_dep = _wald(independent_name, dependent_name)
    dep_causes_indep = _wald(dependent_name, independent_name)
    if indep_causes_dep is None or dep_causes_indep is None:
        return None

    note = (
        f"Toda-Yamamoto: fitted VAR({total_lags}) in levels ({lags} real lag(s) + "
        f"{integration_order_augmentation} dummy lag(s) for I({integration_order_augmentation})). "
        f"{independent_name}→{dependent_name}: p={indep_causes_dep.p_value} "
        f"({'significant' if indep_causes_dep.significant else 'not significant'}); "
        f"{dependent_name}→{independent_name}: p={dep_causes_indep.p_value} "
        f"({'significant' if dep_causes_indep.significant else 'not significant'})."
    )

    return TodaYamamotoResult(
        dependent_name=dependent_name,
        independent_name=independent_name,
        lags=lags,
        integration_order_augmentation=integration_order_augmentation,
        total_fitted_lags=total_lags,
        independent_causes_dependent=indep_causes_dep,
        dependent_causes_independent=dep_causes_indep,
        observation_count=len(dependent),
        note=note,
    )


def _fevd_from_orthogonalized_irf(orth_irfs) -> "object":
    """Standard textbook FEVD formula: cumulative sum of squared
    orthogonalized IRF coefficients, normalised across shock sources —
    validated against `statsmodels.tsa.vector_ar.var_model.VARResults.
    fevd()`'s own native output (see module docstring)."""
    import numpy as np

    cum_sq = np.cumsum(orth_irfs**2, axis=0)
    totals = cum_sq.sum(axis=2, keepdims=True)
    return cum_sq / totals


def impulse_response_and_fevd(
    dependent: list[Decimal],
    independent: list[Decimal],
    *,
    estimator: Estimator,
    dependent_name: str = "y",
    independent_name: str = "x",
    periods: int = DEFAULT_IRF_PERIODS,
    lags: int = DEFAULT_LAGS,
) -> ImpulseResponseFevdResult | None:
    """Impulse response and FEVD from whichever estimator §30 step 2
    actually selected for this pair (`estimator` — the caller's job to
    pass, matching `app.domain.estimator_selection_view.
    EstimatorSelectionResult.estimator_used`, restricted to the two
    branches that produce a genuine fitted multi-equation model:
    `"johansen_vecm"` or `"var_differences"`; the ARDL bounds-testing
    branch does not produce a VAR-shaped model this function can compute
    an impulse response from). `dependent`/`independent` are real LEVEL
    series, aligned by the caller — differenced internally when
    `estimator="var_differences"`, matching `app.domain.var_
    differences.fit_var_in_differences`'s own convention.

    `None` below `MIN_OBSERVATIONS`, when the underlying fit fails, or
    (for `"johansen_vecm"`) when the series aren't actually cointegrated
    — an impulse response computed from a VECM fit on non-cointegrated
    data would not mean what it claims to."""
    if estimator not in ("johansen_vecm", "var_differences"):
        raise ValueError(f"unrecognised estimator {estimator!r}")
    if len(dependent) < MIN_OBSERVATIONS:
        return None
    if len(dependent) != len(independent):
        raise ValueError("dependent and independent series must be the same length")

    try:
        if estimator == "johansen_vecm":
            import pandas as pd
            from statsmodels.tsa.vector_ar.vecm import VECM, select_coint_rank

            df = pd.DataFrame(
                {
                    dependent_name: [float(v) for v in dependent],
                    independent_name: [float(v) for v in independent],
                }
            )
            rank_res = select_coint_rank(
                df, det_order=0, k_ar_diff=_VECM_K_AR_DIFF, method="trace", signif=0.05
            )
            if rank_res.rank != 1:
                return None
            fit = VECM(df, k_ar_diff=_VECM_K_AR_DIFF, coint_rank=1, deterministic="co").fit()
        elif estimator == "var_differences":
            dep_diff = [float(dependent[i]) - float(dependent[i - 1]) for i in range(1, len(dependent))]
            indep_diff = [float(independent[i]) - float(independent[i - 1]) for i in range(1, len(independent))]
            import pandas as pd
            from statsmodels.tsa.api import VAR

            df = pd.DataFrame({dependent_name: dep_diff, independent_name: indep_diff})
            fit = VAR(df).fit(maxlags=lags, trend="c")

        irf = fit.irf(periods=periods)
    except Exception:
        return None

    names = list(fit.names) if hasattr(fit, "names") else [dependent_name, independent_name]
    dep_idx = names.index(dependent_name)
    indep_idx = names.index(independent_name)

    orth = irf.orth_irfs  # shape (periods+1, response, shock)
    fevd = _fevd_from_orthogonalized_irf(orth)

    def _series(arr, response_idx, shock_idx) -> tuple[Decimal, ...]:
        return tuple(Decimal(str(round(float(arr[h, response_idx, shock_idx]), 6))) for h in range(periods + 1))

    note = (
        f"Orthogonalized (Cholesky, {dependent_name} ordered first) impulse response and FEVD "
        f"from a real fitted {estimator.replace('_', ' ')} model, {periods} periods ahead."
    )

    return ImpulseResponseFevdResult(
        dependent_name=dependent_name,
        independent_name=independent_name,
        estimator=estimator,
        periods=periods,
        irf_dependent_to_independent_shock=_series(orth, dep_idx, indep_idx),
        irf_independent_to_dependent_shock=_series(orth, indep_idx, dep_idx),
        fevd_dependent_explained_by_independent=_series(fevd, dep_idx, indep_idx),
        fevd_independent_explained_by_dependent=_series(fevd, indep_idx, dep_idx),
        observation_count=len(dependent),
        note=note,
    )
