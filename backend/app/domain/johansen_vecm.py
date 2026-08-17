"""
§30 step 2, the remaining branch: "All I(1) with Johansen cointegration
→ VECM." — the second of the three estimators §30 step 2 names
("Mixed I(0)/I(1), none I(2), short sample → ARDL bounds test [THIS WILL
BE THE DEFAULT]. No cointegration → VAR in first differences" are the
other two; see `app.domain.ardl_cointegration`'s own module docstring
for the ARDL branch, already built, and its own explanation of why ARDL
is this project's disclosed default rather than Johansen/VECM despite
Johansen/VECM being the "textbook" choice for two genuinely I(1) series).

SCOPE: THE SAME TWO-SERIES CASE `app.domain.ardl_cointegration` ITSELF
COMMITS TO, FOR THE SAME REASON. A general N-variable Johansen/VECM
system is real and buildable, but §30's own worked description is a
two-series relationship (a market series against one macro series) —
building unused N-variable generality ahead of a real need would be
exactly the kind of premature complexity this project's whole build
discipline avoids. A caller with a genuine need for a 3+ variable system
should build that as its own explicit extension, not have it silently
assumed here.

Real `statsmodels.tsa.vector_ar.vecm` implementation throughout —
`coint_johansen`/`select_coint_rank` for the rank test, `VECM` for the
fit — the same "never hand-roll a real econometric method" discipline
`app.domain.ardl_cointegration` and `app.domain.stationarity` already
established. The Johansen trace test's critical values, like the PSS
bounds test's, come from tables this module does not reimplement.

CASE CHOICE MATCHES ARDL'S OWN, NOT COINCIDENTALLY. Johansen's own
five-case deterministic-term table (Case I: no deterministic terms
... Case V: intercept and trend, both unrestricted) is the same table
Pesaran-Shin-Smith's own bounds test reuses for its five cases —
`DEFAULT_DET_ORDER = 0` (a constant term) with `DEFAULT_VECM_
DETERMINISTIC = "co"` (constant OUTSIDE the cointegrating relation,
unrestricted) is Johansen's own "Case III," the same economic case
`app.domain.ardl_cointegration.DEFAULT_PSS_CASE = 3` (unrestricted
constant, no trend) commits to for the ARDL branch — one disclosed
default reused across both estimators, not two independently-invented
ones that happen to differ.

THE SPEED-OF-ADJUSTMENT / HALF-LIFE MATH IS REUSED FROM ARDL, NOT
REDERIVED. A VECM's alpha coefficient for the dependent series' own
equation plays exactly the same "how fast does the gap close" role as
the ARDL branch's ECT coefficient, under the same sign convention and
the same mathematical domain (`-1 < alpha < 0` for a half-life to be
meaningful) — so `error_correction_half_life` is imported directly from
`app.domain.ardl_cointegration` rather than duplicated, and its own
validation against §30 step 2's worked example (an ECT of −0.28 → "a
half-life of roughly 2.1 months") already covers this module's use of
the same formula.

A RANK OTHER THAN 1 IS REFUSED, NOT CLAMPED. For a two-variable system,
Johansen's cointegration rank can only be sensibly 0 (no cointegration)
or 1 (exactly one cointegrating relationship) — a rank of 2 would mean
both series are individually stationary, which contradicts the "all
I(1)" premise this branch of §30 step 2 exists for, and would indicate
either a misapplied estimator or genuinely unusual data. `fit_vecm`
reports this honestly rather than guessing at what a rank-2 result would
even mean for a single cointegrating relationship.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domain.ardl_cointegration import error_correction_half_life

#: Same disclosed floor as `app.domain.ardl_cointegration.
#: MIN_OBSERVATIONS` — both estimators are answering the same kind of
#: question on the same kind of short Sri Lankan macro sample.
MIN_OBSERVATIONS = 50

DEFAULT_DET_ORDER = 0
DEFAULT_VECM_DETERMINISTIC = "co"
DEFAULT_K_AR_DIFF = 1

JohansenConclusion = Literal["cointegrated", "not_cointegrated"]


@dataclass(frozen=True)
class JohansenTestResult:
    dependent_name: str
    independent_name: str
    trace_statistics: tuple[Decimal, ...]
    """One trace statistic per rank hypothesis actually tested
    (`select_coint_rank` tests sequentially — r=0, then r<=1, and so
    on — stopping at the first hypothesis it fails to reject), in that
    order."""

    trace_critical_values: tuple[dict[str, Decimal], ...]
    """Percentile (`"90.0"`, `"95.0"`, `"99.0"` — Johansen's own table
    has three bands, not PSS's four) → critical value, one dict per
    entry in `trace_statistics`, same ordering."""

    selected_rank: int
    """`select_coint_rank`'s own selected rank at the 5% level — this
    module reads the library's own sequential-testing decision rather
    than re-deriving one from `trace_statistics` by hand."""

    conclusion: JohansenConclusion
    observation_count: int
    note: str


@dataclass(frozen=True)
class VecmFitResult:
    johansen: JohansenTestResult
    """The rank test this fit is conditioned on — always present, even
    when the fit itself didn't happen (see `alpha_dependent`)."""

    alpha_dependent: Decimal | None
    """Speed-of-adjustment for the DEPENDENT series' own equation — the
    direct VECM analogue of `app.domain.ardl_cointegration.
    BoundsTestResult.ect_coefficient`, same sign convention, same
    domain. `None` whenever `johansen.conclusion` isn't `"cointegrated"`,
    `johansen.selected_rank != 1`, or the underlying fit fails."""

    alpha_independent: Decimal | None
    """Speed-of-adjustment for the INDEPENDENT series' own equation —
    reported alongside `alpha_dependent` because a genuinely small value
    here (the independent series barely reacts to deviations from the
    long-run relationship) is itself informative: it says the
    independent series is closer to weakly exogenous, i.e. more the
    "driver" of the relationship than the "follower.\""""

    beta: Decimal | None
    """The cointegrating vector's own coefficient on the independent
    series, normalized so the dependent series' own coefficient is 1 —
    i.e. the estimated long-run relationship is `dependent ≈ beta *
    independent`."""

    half_life_periods: Decimal | None
    """Computed from `alpha_dependent` via `app.domain.ardl_
    cointegration.error_correction_half_life` — see that function's own
    docstring for the formula, its domain, and its validation against
    §30's worked example."""

    note: str


def johansen_cointegration_test(
    dependent: list[Decimal],
    independent: list[Decimal],
    *,
    dependent_name: str = "y",
    independent_name: str = "x",
    det_order: int = DEFAULT_DET_ORDER,
    k_ar_diff: int = DEFAULT_K_AR_DIFF,
) -> JohansenTestResult | None:
    """`None` — never a number computed from too little data — below
    `MIN_OBSERVATIONS`, or when the underlying `statsmodels` call raises
    (a real, not hypothetical, possibility on a short or near-singular
    sample, the same defensive handling `app.domain.ardl_cointegration.
    ardl_bounds_test` already applies to its own real fit failures)."""
    if len(dependent) < MIN_OBSERVATIONS:
        return None
    if len(dependent) != len(independent):
        raise ValueError("dependent and independent series must be the same length")

    import pandas as pd
    from statsmodels.tsa.vector_ar.vecm import coint_johansen, select_coint_rank

    df = pd.DataFrame(
        {
            dependent_name: [float(v) for v in dependent],
            independent_name: [float(v) for v in independent],
        }
    )

    try:
        jres = coint_johansen(df.values, det_order, k_ar_diff)
        rank_res = select_coint_rank(
            df, det_order=det_order, k_ar_diff=k_ar_diff, method="trace", signif=0.05
        )
    except Exception:
        return None

    pct_labels = ("90.0", "95.0", "99.0")
    trace_statistics = tuple(
        Decimal(str(round(float(s), 6))) for s in jres.trace_stat
    )
    trace_critical_values = tuple(
        {
            label: Decimal(str(round(float(v), 6)))
            for label, v in zip(pct_labels, row)
        }
        for row in jres.trace_stat_crit_vals
    )

    rank = int(rank_res.rank)
    conclusion: JohansenConclusion = "cointegrated" if rank >= 1 else "not_cointegrated"
    note = (
        f"Johansen trace test selects cointegration rank {rank} at the 5% level — "
        f"{conclusion.replace('_', ' ')}."
    )

    return JohansenTestResult(
        dependent_name=dependent_name,
        independent_name=independent_name,
        trace_statistics=trace_statistics,
        trace_critical_values=trace_critical_values,
        selected_rank=rank,
        conclusion=conclusion,
        observation_count=len(dependent),
        note=note,
    )


def fit_vecm(
    dependent: list[Decimal],
    independent: list[Decimal],
    *,
    dependent_name: str = "y",
    independent_name: str = "x",
    k_ar_diff: int = DEFAULT_K_AR_DIFF,
    deterministic: str = DEFAULT_VECM_DETERMINISTIC,
) -> VecmFitResult | None:
    """§30 step 2's "all I(1)" estimator, applied. `dependent` and
    `independent` must already be aligned (see `app.domain.johansen_
    vecm_view` for how real `macro_series` data gets aligned by date
    before reaching this function — the same "gather, then compute"
    separation every pure domain module in this system draws from its
    `_view.py` companion).

    `None` only when `johansen_cointegration_test` itself returns `None`
    (too little data, or the rank test itself failed) — once a real
    `JohansenTestResult` exists, a `VecmFitResult` is always returned,
    with `alpha_dependent`/`alpha_independent`/`beta`/`half_life_
    periods` left `None` and `note` naming exactly why whenever no
    cointegrating relationship exists to fit a VECM against, the
    selected rank isn't the single relationship this two-series case
    expects, or the fit itself fails."""
    johansen = johansen_cointegration_test(
        dependent, independent,
        dependent_name=dependent_name, independent_name=independent_name,
        k_ar_diff=k_ar_diff,
    )
    if johansen is None:
        return None

    if johansen.conclusion != "cointegrated":
        return VecmFitResult(
            johansen=johansen, alpha_dependent=None, alpha_independent=None,
            beta=None, half_life_periods=None,
            note=johansen.note + " No cointegrating relationship to fit a VECM against.",
        )

    if johansen.selected_rank != 1:
        return VecmFitResult(
            johansen=johansen, alpha_dependent=None, alpha_independent=None,
            beta=None, half_life_periods=None,
            note=(
                johansen.note
                + f" Selected rank {johansen.selected_rank} is not the single cointegrating "
                "relationship this two-series case expects — refusing to fit rather than guess."
            ),
        )

    import pandas as pd
    from statsmodels.tsa.vector_ar.vecm import VECM

    df = pd.DataFrame(
        {
            dependent_name: [float(v) for v in dependent],
            independent_name: [float(v) for v in independent],
        }
    )

    try:
        vecm = VECM(df, k_ar_diff=k_ar_diff, coint_rank=1, deterministic=deterministic)
        fit = vecm.fit()
    except Exception:
        return VecmFitResult(
            johansen=johansen, alpha_dependent=None, alpha_independent=None,
            beta=None, half_life_periods=None,
            note=johansen.note + " The VECM fit itself failed on this real data.",
        )

    alpha_dep_raw = float(fit.alpha[0, 0])
    alpha_indep_raw = float(fit.alpha[1, 0])
    beta_dep_raw = float(fit.beta[0, 0])
    beta_indep_raw = float(fit.beta[1, 0])
    if beta_dep_raw == 0:
        return VecmFitResult(
            johansen=johansen, alpha_dependent=None, alpha_independent=None,
            beta=None, half_life_periods=None,
            note=(
                johansen.note
                + " The fitted cointegrating vector's own dependent-series coefficient is "
                "exactly zero — the long-run relationship can't be normalized against it."
            ),
        )
    beta_normalized = -beta_indep_raw / beta_dep_raw

    half_life = error_correction_half_life(alpha_dep_raw)
    note = (
        johansen.note
        + f" VECM speed-of-adjustment on {dependent_name}: {alpha_dep_raw:.4f}."
    )
    if half_life is None and alpha_dep_raw < 0:
        note += (
            " Outside the range a half-life is meaningful for (needs -1 < coefficient < 0 — "
            "the correction overshoots each period rather than converging monotonically)."
        )

    return VecmFitResult(
        johansen=johansen,
        alpha_dependent=Decimal(str(round(alpha_dep_raw, 6))),
        alpha_independent=Decimal(str(round(alpha_indep_raw, 6))),
        beta=Decimal(str(round(beta_normalized, 6))),
        half_life_periods=half_life,
        note=note,
    )
