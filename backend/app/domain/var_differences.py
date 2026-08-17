"""
§30 step 2, the third and final branch: "No cointegration → VAR in
first differences." Completes the three-way estimator selection §30
step 2 names alongside `app.domain.ardl_cointegration` (the disclosed
default for this project's own mixed I(0)/I(1) short-sample data) and
`app.domain.johansen_vecm` (the "all I(1)" branch) — this is the branch
for when neither of those found a real long-run relationship to work
with: no cointegration means levels can't be modelled together directly
(a spurious-regression trap), so the model is fit on each series'
DIFFERENCES instead, where a genuine VAR is statistically valid.

SAME SIGNATURE SHAPE AS THE OTHER TWO BRANCHES, DELIBERATELY. `app.
domain.ardl_cointegration.ardl_bounds_test` and `app.domain.johansen_
vecm.fit_vecm` both take LEVEL series and handle their own required
transform internally (UECM differences internally for its bounds test;
VECM/coint_johansen work on levels by construction). This module follows
the same pattern — `fit_var_in_differences` also takes LEVEL series and
differences them itself — so a caller implementing §30 step 2's actual
three-way estimator-selection logic can route to whichever branch
applies without reshaping its own real data differently per branch.

REAL SHORT-RUN CONTENT, NOT A CONSOLATION PRIZE. A "no cointegration"
verdict means there's no long-run equilibrium to correct toward — but a
real short-run relationship (does a shock to the independent series'
own difference help predict the dependent series' own next difference?)
can still exist and still be useful. This module reports exactly that:
the coefficient on the independent series' own first lagged difference
in the dependent series' own equation, with its real p-value — the VAR-
in-differences equivalent of ARDL's ECT coefficient, except there is no
error-correction term here by construction (nothing to correct toward),
so there is no half-life to report.

Real `statsmodels.tsa.api.VAR` implementation throughout — never hand-
rolled, the same discipline every other statistical module this phase
established.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Same disclosed floor as `app.domain.ardl_cointegration.MIN_
#: OBSERVATIONS`/`app.domain.johansen_vecm.MIN_OBSERVATIONS` — applied
#: to the LEVEL series length before differencing (which then loses
#: exactly one observation), consistent across all three §30 step 2
#: branches so a caller comparing them isn't holding one to a quietly
#: different bar.
MIN_OBSERVATIONS = 50

#: Same disclosed default lag depth as `app.domain.ardl_cointegration.
#: ardl_bounds_test`'s own `lags=2` default — one project-wide default,
#: not independently chosen per branch.
DEFAULT_LAGS = 2

SIGNIFICANCE_THRESHOLD = Decimal("0.05")


@dataclass(frozen=True)
class VarDifferencesResult:
    dependent_name: str
    independent_name: str
    lags: int
    is_stable: bool
    """From the fitted VAR's own `is_stable()` check — a real, meaningful
    diagnostic here specifically: a VAR fit on genuinely differenced,
    non-cointegrated I(1) series should be stable (no remaining unit
    roots); `False` would be a real warning sign about this branch
    actually being the right one for this data, not a cosmetic detail."""

    dependent_on_independent_lag1_coefficient: Decimal
    """The coefficient on `{independent_name}`'s own first lagged
    difference in the `{dependent_name}` equation — the real short-run
    link this branch exists to report once no long-run one was found."""

    dependent_on_independent_lag1_p_value: Decimal
    significant: bool
    observation_count: int
    """Post-differencing observation count actually used by the fit —
    one fewer than the level series' own length, named explicitly rather
    than left for a caller to infer."""

    note: str


def fit_var_in_differences(
    dependent: list[Decimal],
    independent: list[Decimal],
    *,
    dependent_name: str = "y",
    independent_name: str = "x",
    lags: int = DEFAULT_LAGS,
) -> VarDifferencesResult | None:
    """§30 step 2's "no cointegration" estimator, applied to real LEVEL
    series (differenced internally — see module docstring). `dependent`
    and `independent` must already be aligned by date (see `app.domain.
    var_differences_view` for how real `macro_series` data gets aligned
    before reaching this function).

    `None` — never a number computed from too little data — below
    `MIN_OBSERVATIONS`, or when the underlying `statsmodels` fit raises
    (a real, not hypothetical, possibility on a short or near-singular
    sample, the same defensive handling `app.domain.ardl_cointegration.
    ardl_bounds_test` and `app.domain.johansen_vecm.fit_vecm` already
    apply to their own real fit failures)."""
    if len(dependent) < MIN_OBSERVATIONS:
        return None
    if len(dependent) != len(independent):
        raise ValueError("dependent and independent series must be the same length")

    import pandas as pd
    from statsmodels.tsa.api import VAR

    dep_diff = [
        float(dependent[i]) - float(dependent[i - 1]) for i in range(1, len(dependent))
    ]
    indep_diff = [
        float(independent[i]) - float(independent[i - 1]) for i in range(1, len(independent))
    ]
    df = pd.DataFrame({dependent_name: dep_diff, independent_name: indep_diff})

    try:
        model = VAR(df)
        fit = model.fit(maxlags=lags, trend="c")
    except Exception:
        return None

    lag_label = f"L1.{independent_name}"
    if dependent_name not in fit.params.columns or lag_label not in fit.params.index:
        # A real but unexpected statsmodels output shape (e.g. the fit
        # converged on fewer lags than requested and dropped L1 terms
        # entirely) — refuse rather than guess at which cell to read.
        return None

    coefficient = float(fit.params[dependent_name][lag_label])
    p_value = float(fit.pvalues[dependent_name][lag_label])
    significant = Decimal(str(round(p_value, 6))) < SIGNIFICANCE_THRESHOLD

    note = (
        f"VAR-in-differences: {independent_name}'s own first lagged difference has "
        f"coefficient {coefficient:.4f} (p={p_value:.4f}) in the {dependent_name} equation — "
        f"{'a statistically significant' if significant else 'not a statistically significant'} "
        f"short-run link at the {SIGNIFICANCE_THRESHOLD} level. No cointegrating relationship "
        "exists for this pair, so there is no error-correction term or half-life to report."
    )

    return VarDifferencesResult(
        dependent_name=dependent_name,
        independent_name=independent_name,
        lags=fit.k_ar,
        is_stable=bool(fit.is_stable()),
        dependent_on_independent_lag1_coefficient=Decimal(str(round(coefficient, 6))),
        dependent_on_independent_lag1_p_value=Decimal(str(round(p_value, 6))),
        significant=significant,
        observation_count=len(dep_diff),
        note=note,
    )
