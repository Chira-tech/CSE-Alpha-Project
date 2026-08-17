"""
§30 step 2 (partial): "Estimator selection by integration profile. All
I(1) with Johansen cointegration → VECM. Mixed I(0)/I(1), none I(2),
short sample → ARDL bounds test (THIS WILL BE THE DEFAULT). No
cointegration → VAR in first differences."

    "Why ARDL is the right default. Sri Lankan macro series are a
    genuine mix of I(0) and I(1); the usable post-liberalisation sample
    is short; and ARDL handles small samples better than Johansen. It
    also delivers the two things you actually want from one estimation:
    a long-run cointegrating relationship (where should the market be,
    given the macro state?) and an error-correction term (how fast does
    it get there?). An ECT of −0.28 on monthly data means about 28% of
    the gap closes per month — a half-life of roughly 2.1 months, which
    is directly actionable as a holding-period expectation."

This module builds the ARDL/UECM bounds-testing half of step 2 — the
default case §30 itself names for this project's own data — not the
Johansen/VECM branch (for the "all I(1)" case) or the plain-VAR branch
(for "no cointegration"), both real, separate, genuinely unbuilt pieces.
Real `statsmodels.tsa.ardl` implementation throughout — the Pesaran-
Shin-Smith bounds test's critical values come from simulation tables
this module does not reimplement, the same "never hand-roll a real
econometric method" discipline `app.domain.regime_classification` and
`app.domain.stationarity`'s own module docstrings already establish.

VALIDATED AGAINST §30's OWN WORKED NUMBER, NOT JUST A SYNTHETIC SERIES.
`error_correction_half_life`'s formula (`ln(0.5) / ln(1 + ect_
coefficient)`) is checked directly against §30 step 2's own stated
example — an ECT of −0.28 must produce "a half-life of roughly 2.1
months" — the same "check a real method against the spec's own claimed
number, not just that it runs" discipline this project applies whenever
the spec hands it a concrete figure to verify against (see
`test_regime_classification.py`'s §32 worked-example test for the same
pattern applied to §31/§32 instead).

WHAT THIS MODULE STILL DOESN'T BUILD. Johansen cointegration/VECM (the
"all I(1)" branch), VAR in first differences (the "no cointegration"
branch), impulse response functions, forecast error variance
decomposition and Toda-Yamamoto causality (§30 step 3 — needs a fitted
cointegration model first, from whichever of the three step-2 branches
applies) are all real, separate, genuinely unbuilt pieces, named
precisely rather than folded into a false claim that "step 2" is done.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

#: ARDL/UECM needs more real observations than a simple OLS slope does —
#: multiple lags of multiple series eat degrees of freedom fast. Higher
#: than `app.domain.stationarity.MIN_OBSERVATIONS` and `app.domain.
#: sector_sensitivity.MIN_OBSERVATIONS_FOR_REGRESSION`, a real, disclosed
#: floor for this specific method, not either of those reused blindly.
MIN_OBSERVATIONS = 50

#: Pesaran-Shin-Smith's own five specifications of the deterministic
#: terms in the cointegrating relationship. Case 3 (unrestricted
#: constant, no trend) is the one their own paper illustrates most and
#: the standard default for a relationship with no strong a priori
#: reason to assume a deterministic trend — the macro-to-market
#: relationships §30 wants (e.g. does the ASPI level cointegrate with
#: the T-bill yield level?) have no such prior. A caller with a specific
#: reason to assume a trend should pass a different case explicitly,
#: not rely on this default silently.
DEFAULT_PSS_CASE = 3

CointegrationConclusion = Literal["cointegrated", "not_cointegrated", "inconclusive"]


@dataclass(frozen=True)
class BoundsTestResult:
    dependent_name: str
    independent_names: tuple[str, ...]
    statistic: Decimal
    """The PSS F-statistic — compared against `critical_values` to reach
    `conclusion`, not a p-value (the bounds test reports critical value
    bands, not a single p-value, because the true distribution depends
    on the unknown integration order of the underlying series — the
    whole reason it's called a BOUNDS test)."""

    critical_values: dict[str, dict[str, Decimal]]
    """Percentile (`"90.0"`, `"95.0"`, `"99.0"`, `"99.9"`) → `{"lower":
    ..., "upper": ...}`. `statistic` above the upper bound at a given
    percentile rejects "no cointegration" at that confidence level
    regardless of whether the underlying series are I(0) or I(1); below
    the lower bound fails to reject it; between the two is genuinely
    inconclusive without knowing the true integration order (§30 step
    1's own job)."""

    conclusion: CointegrationConclusion
    """Read at the 95% band specifically — a disclosed, standard choice,
    not the only one a caller could make from `critical_values`."""

    ect_coefficient: Decimal | None
    """The estimated speed-of-adjustment — how much of any deviation
    from the long-run relationship corrects per period. `None` when
    `conclusion` isn't `"cointegrated"`: an error-correction term only
    means something once a real long-run relationship to correct toward
    has actually been established."""

    half_life_periods: Decimal | None
    """§30 step 2's own "directly actionable as a holding-period
    expectation" number — see `error_correction_half_life`'s own
    docstring for the formula and its validation against §30's worked
    example. `None` whenever `ect_coefficient` is `None`, or when it
    implies no real convergence (see that function for the exact bound)."""

    observation_count: int
    note: str


def error_correction_half_life(ect_coefficient: float) -> Decimal | None:
    """`half_life = ln(0.5) / ln(1 + ect_coefficient)`, in the same
    period units as the series the ECT was estimated on (monthly data
    gives a half-life in months, daily gives days, etc. — this function
    has no opinion about the unit, only the caller does).

    VALIDATED against §30 step 2's own worked example: an ECT of −0.28
    must produce "a half-life of roughly 2.1 months" — `ln(0.5) ÷
    ln(0.72) ≈ 2.108`, matching the spec's own stated figure, checked
    directly by a dedicated test rather than trusted from the formula
    alone.

    `None` outside `-1 < ect_coefficient < 0` — a coefficient of 0 or
    above implies no mean reversion at all (not actually cointegrated in
    any economically meaningful sense, whatever the bounds test's own
    verdict). The formula itself is undefined at or below -1: `1 +
    ect_coefficient` reaches zero at exactly -1 (`ln(0)` undefined) and
    goes NEGATIVE below it (`ln()` of a negative number undefined) —
    found by a real test on a real fitted coefficient during this
    module's own development, not a theoretical edge case reasoned
    about in the abstract. A coefficient at or below -1 means the
    correction OVERSHOOTS each period (the deviation flips sign rather
    than shrinking monotonically toward zero) — still mean-reverting in
    an oscillating sense, but not a case this simple half-life formula
    covers; §30 step 2's own text only claims the formula for the
    monotonic case its own example (−0.28) falls into."""
    if not (-1 < ect_coefficient < 0):
        return None
    return Decimal(str(round(math.log(0.5) / math.log(1 + ect_coefficient), 6)))


def ardl_bounds_test(
    dependent: list[Decimal],
    independents: dict[str, list[Decimal]],
    *,
    dependent_name: str = "y",
    lags: int = 2,
    case: int = DEFAULT_PSS_CASE,
) -> BoundsTestResult | None:
    """§30 step 2's default estimator, applied. `dependent` and every
    series in `independents` must already be aligned — same length, same
    implicit ordering — the caller's job (see `app.domain.ardl_
    cointegration_view` for how real `macro_series` data gets aligned by
    date before reaching this function), the same "gather, then compute"
    separation every pure domain module in this system draws from its
    `_view.py` companion.

    `None` — never a number computed from too little data — below
    `MIN_OBSERVATIONS`, or when the underlying `statsmodels` fit raises
    (a real, not hypothetical, possibility on a short or nearly-singular
    sample, the same defensive handling `app.domain.regime_
    classification.fit_markov_regime_read` already applies to its own
    real fit failures)."""
    if len(dependent) < MIN_OBSERVATIONS:
        return None
    if any(len(series) != len(dependent) for series in independents.values()):
        raise ValueError("dependent and every independent series must be the same length")
    if not independents:
        raise ValueError("ardl_bounds_test needs at least one independent series")

    import pandas as pd
    from statsmodels.tsa.ardl import UECM

    df = pd.DataFrame({dependent_name: [float(v) for v in dependent]})
    for name, series in independents.items():
        df[name] = [float(v) for v in series]

    try:
        model = UECM(
            df[dependent_name], lags=lags, exog=df[list(independents.keys())],
            order=lags, trend="c",
        )
        result = model.fit()
        bounds = result.bounds_test(case=case)
    except Exception:
        return None

    crit = {
        str(pct): {"lower": Decimal(str(round(row["lower"], 6))), "upper": Decimal(str(round(row["upper"], 6)))}
        for pct, row in bounds.crit_vals.iterrows()
    }
    stat = float(bounds.stat)
    band_95 = crit.get("95.0")
    if band_95 is None:
        return None  # a real but unexpected statsmodels output shape — refuse rather than guess

    if stat > float(band_95["upper"]):
        conclusion: CointegrationConclusion = "cointegrated"
    elif stat < float(band_95["lower"]):
        conclusion = "not_cointegrated"
    else:
        conclusion = "inconclusive"

    ect_coefficient = None
    half_life = None
    note_extra = ""
    if conclusion == "cointegrated":
        ect_param_name = f"{dependent_name}.L1"
        if ect_param_name in result.params.index:
            ect_raw = float(result.params[ect_param_name])
            ect_coefficient = Decimal(str(round(ect_raw, 6)))
            half_life = error_correction_half_life(ect_raw)
            if half_life is None:
                note_extra = (
                    f" ECT coefficient ({ect_coefficient}) is outside the range a half-life "
                    "is meaningful for (needs -1 < coefficient < 0 — the correction "
                    "overshoots each period rather than converging monotonically)."
                )

    note = (
        f"PSS F-statistic {stat:.4f} vs the 95% band [{band_95['lower']}, {band_95['upper']}] — "
        f"{conclusion.replace('_', ' ')}."
        + note_extra
    )

    return BoundsTestResult(
        dependent_name=dependent_name,
        independent_names=tuple(independents.keys()),
        statistic=Decimal(str(round(stat, 6))),
        critical_values=crit,
        conclusion=conclusion,
        ect_coefficient=ect_coefficient,
        half_life_periods=half_life,
        observation_count=len(dependent),
        note=note,
    )
