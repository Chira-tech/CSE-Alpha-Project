"""
§30 step 1: "Stationarity and break testing — ADF, Phillips-Perron,
KPSS, then Zivot-Andrews with an endogenous break. The 2022 sovereign
default is a structural break in nearly every series. Ignoring it makes
you conclude 'no cointegration' when a relationship exists in both
sub-periods."

Every test below is a real, tested library implementation — never hand-
rolled. `statsmodels.tsa.stattools.adfuller`/`kpss`/`zivot_andrews`
supply three of the four named tests; statsmodels has no native
Phillips-Perron implementation, so `arch.unitroot.PhillipsPerron`
(Kevin Sheppard's econometrics library — real, widely used in academic
and industry time-series work, unrelated to CPU architecture despite the
name) supplies the fourth. Reimplementing a unit-root test's asymptotic
distribution from scratch would be exactly the "confident, precise,
entirely fictional number" §15 warns the whole platform exists to avoid
— the same reasoning `app.domain.regime_classification`'s own module
docstring already gives for using `statsmodels`' Markov-switching
implementation rather than a hand-rolled Hamilton filter.

FOUR TESTS, TWO OPPOSITE NULL HYPOTHESES — GETTING THIS BACKWARDS IS A
REAL, EASY MISTAKE THIS MODULE EXISTS TO PREVENT. ADF, Phillips-Perron
and Zivot-Andrews all share the null hypothesis "the series has a unit
root" (non-stationary) — a LOW p-value REJECTS that null, meaning the
series IS stationary. KPSS's null is the exact opposite: "the series IS
stationary" — a LOW p-value there REJECTS stationarity, meaning the
series is NOT stationary. A single "p < 0.05 means stationary" rule
applied blindly across all four tests would silently invert KPSS's
verdict. Every function below returns a `stationarity_conclusion` field
that has already been translated through the correct direction for that
specific test, so a caller never has to remember which way a given
test's p-value points.

WHY ZIVOT-ANDREWS MATTERS SPECIFICALLY FOR THIS PROJECT. §30 step 1's
own text names the 2022 sovereign default as a real structural break
nearly every Sri Lankan macro series has lived through. An ordinary ADF/
PP/KPSS test assumes no break and can spuriously fail to reject a unit
root on a series that is actually stationary WITHIN each sub-period
either side of a real break — Zivot-Andrews searches for the single most
likely endogenous break date and tests for a unit root allowing for it,
rather than assuming the break date is known in advance or ignoring it
entirely.

WHAT THIS MODULE FEEDS, AND WHAT IT DOESN'T BUILD YET. §30 step 2
("Estimator selection by integration profile... All I(1) with Johansen
cointegration → VECM. Mixed I(0)/I(1)... → ARDL bounds test... No
cointegration → VAR in first differences") is the real, separate,
not-yet-built next step this module's output is FOR — this module
answers "is this one series stationary," not "what long-run relationship
exists between several series," which needs Johansen cointegration/VECM/
ARDL machinery this codebase does not have yet (`statsmodels.tsa.
vector_ar.vecm`/`statsmodels.tsa.ardl` are the right tools when that
work happens). Named precisely as still open, not attempted here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

StationarityConclusion = Literal["stationary", "non_stationary"]

#: Standard, disclosed convention, same as `app.domain.sector_
#: sensitivity.SIGNIFICANCE_THRESHOLD` — not derived from anything
#: Sri-Lanka-specific.
SIGNIFICANCE_THRESHOLD = Decimal("0.05")

#: A unit-root test on fewer observations than this is not refused
#: outright (unlike `app.domain.regime_classification`'s hard floor for
#: a Markov fit) but the asymptotic p-values these tests report become
#: increasingly unreliable on a short sample — 30 matches this
#: project's other established minimum-sample conventions (`app.domain.
#: beta.MIN_OBSERVATIONS`, `app.domain.sector_sensitivity.MIN_
#: OBSERVATIONS_FOR_REGRESSION`'s own smaller floor extended here since
#: a unit-root test's own asymptotics need more data than a simple OLS
#: slope does).
MIN_OBSERVATIONS = 30


@dataclass(frozen=True)
class UnitRootTestResult:
    test_name: str
    statistic: Decimal
    p_value: Decimal
    lags_used: int
    critical_values: dict[str, Decimal]
    null_hypothesis: str
    """What a LOW p-value rejects, stated in words — always read this,
    never assume "low p-value = stationary" across every test (see
    module docstring)."""

    stationarity_conclusion: StationarityConclusion
    """Already translated through this specific test's own null-
    hypothesis direction — safe to compare directly across all four
    tests' results, unlike `p_value` or `statistic` alone."""


@dataclass(frozen=True)
class ZivotAndrewsResult(UnitRootTestResult):
    break_index: int
    """The 0-indexed position in the input series Zivot-Andrews
    identified as the single most likely endogenous structural break —
    NOT a date; the caller maps this back to a real date using the same
    ordering the input series was supplied in."""


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 8)))


def adf_test(series: list[Decimal], *, regression: str = "c") -> UnitRootTestResult | None:
    """Augmented Dickey-Fuller — null hypothesis: the series has a unit
    root (non-stationary). `regression`: `"c"` (constant, the default —
    tests for stationarity around a non-zero mean) or `"ct"` (constant
    and trend). `None` below `MIN_OBSERVATIONS`."""
    if len(series) < MIN_OBSERVATIONS:
        return None

    from statsmodels.tsa.stattools import adfuller

    stat, p_value, used_lag, _nobs, crit, _icbest = adfuller(
        [float(v) for v in series], regression=regression, autolag="AIC"
    )
    rejects_null = p_value < float(SIGNIFICANCE_THRESHOLD)
    return UnitRootTestResult(
        test_name="ADF",
        statistic=_to_decimal(stat),
        p_value=_to_decimal(p_value),
        lags_used=used_lag,
        critical_values={k: _to_decimal(v) for k, v in crit.items()},
        null_hypothesis="The series has a unit root (is non-stationary).",
        stationarity_conclusion="stationary" if rejects_null else "non_stationary",
    )


def phillips_perron_test(series: list[Decimal]) -> UnitRootTestResult | None:
    """Phillips-Perron — same null hypothesis as ADF (unit root present)
    but robust to heteroskedasticity/autocorrelation in the error term
    without needing ADF's own lagged-difference terms. `None` below
    `MIN_OBSERVATIONS`."""
    if len(series) < MIN_OBSERVATIONS:
        return None

    from arch.unitroot import PhillipsPerron

    pp = PhillipsPerron([float(v) for v in series])
    rejects_null = pp.pvalue < float(SIGNIFICANCE_THRESHOLD)
    return UnitRootTestResult(
        test_name="Phillips-Perron",
        statistic=_to_decimal(pp.stat),
        p_value=_to_decimal(pp.pvalue),
        lags_used=int(pp.lags),
        critical_values={k: _to_decimal(v) for k, v in pp.critical_values.items()},
        null_hypothesis="The series has a unit root (is non-stationary).",
        stationarity_conclusion="stationary" if rejects_null else "non_stationary",
    )


def kpss_test(series: list[Decimal], *, regression: str = "c") -> UnitRootTestResult | None:
    """KPSS — null hypothesis is the OPPOSITE of ADF/PP/Zivot-Andrews:
    the series IS stationary. A low p-value here REJECTS stationarity —
    see module docstring for why this direction matters. `None` below
    `MIN_OBSERVATIONS`."""
    if len(series) < MIN_OBSERVATIONS:
        return None

    from statsmodels.tsa.stattools import kpss

    stat, p_value, lags, crit = kpss([float(v) for v in series], regression=regression, nlags="auto")
    rejects_null = p_value < float(SIGNIFICANCE_THRESHOLD)
    return UnitRootTestResult(
        test_name="KPSS",
        statistic=_to_decimal(stat),
        p_value=_to_decimal(p_value),
        lags_used=lags,
        critical_values={k: _to_decimal(v) for k, v in crit.items()},
        null_hypothesis="The series is stationary.",
        # REVERSED from ADF/PP: rejecting KPSS's null means NON-stationary.
        stationarity_conclusion="non_stationary" if rejects_null else "stationary",
    )


def zivot_andrews_test(
    series: list[Decimal], *, regression: str = "c"
) -> ZivotAndrewsResult | None:
    """Zivot-Andrews — same null hypothesis as ADF/PP (unit root
    present) but allows for ONE unknown structural break, found
    endogenously rather than assumed at a caller-supplied date. See
    module docstring for why this is the test this project's own real
    2022 sovereign-default break makes specifically relevant, not just
    included for completeness. `None` below `MIN_OBSERVATIONS`."""
    if len(series) < MIN_OBSERVATIONS:
        return None

    from statsmodels.tsa.stattools import zivot_andrews

    stat, p_value, crit, _baselag, break_idx = zivot_andrews(
        [float(v) for v in series], regression=regression
    )
    rejects_null = p_value < float(SIGNIFICANCE_THRESHOLD)
    return ZivotAndrewsResult(
        test_name="Zivot-Andrews",
        statistic=_to_decimal(stat),
        p_value=_to_decimal(p_value),
        lags_used=0,  # zivot_andrews reports a baselag, not a comparable "lags used" figure
        critical_values={k: _to_decimal(v) for k, v in crit.items()},
        null_hypothesis="The series has a unit root, even allowing for one structural break.",
        stationarity_conclusion="stationary" if rejects_null else "non_stationary",
        break_index=int(break_idx),
    )


@dataclass(frozen=True)
class StationarityAssessment:
    adf: UnitRootTestResult | None
    phillips_perron: UnitRootTestResult | None
    kpss: UnitRootTestResult | None
    zivot_andrews: ZivotAndrewsResult | None
    consensus: Literal["stationary", "non_stationary", "mixed_evidence", "insufficient_data"]
    note: str


def assess_stationarity(series: list[Decimal], *, regression: str = "c") -> StationarityAssessment:
    """Runs all four §30 step 1 tests and reports whether they agree —
    disagreement is a real, reportable finding, not noise to average
    away, the same "report the composite honestly" discipline `app.
    domain.regime_classification.classify_regime` already applies to
    blending its own two independent reads."""
    adf = adf_test(series, regression=regression)
    pp = phillips_perron_test(series)
    kp = kpss_test(series, regression=regression)
    za = zivot_andrews_test(series, regression=regression)

    results = [r for r in (adf, pp, kp, za) if r is not None]
    if not results:
        return StationarityAssessment(
            adf=None, phillips_perron=None, kpss=None, zivot_andrews=None,
            consensus="insufficient_data",
            note=f"Fewer than {MIN_OBSERVATIONS} observations — no test could run.",
        )

    conclusions = {r.stationarity_conclusion for r in results}
    if len(conclusions) == 1:
        consensus = conclusions.pop()
        note = f"All {len(results)} test(s) that could run agree: {consensus}."
    else:
        consensus = "mixed_evidence"
        summary = ", ".join(f"{r.test_name}={r.stationarity_conclusion}" for r in results)
        note = (
            f"Tests disagree — {summary}. A real, reportable finding (§30 step 1's own "
            "reasoning for testing multiple ways, not a fault in the data): KPSS and "
            "Zivot-Andrews in particular can diverge from a plain ADF/PP read exactly "
            "when a real structural break is present, which is precisely the case this "
            "project's own 2022 sovereign-default break makes likely for Sri Lankan "
            "macro series."
        )

    return StationarityAssessment(
        adf=adf, phillips_perron=pp, kpss=kp, zivot_andrews=za,
        consensus=consensus, note=note,
    )
