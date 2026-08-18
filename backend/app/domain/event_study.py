"""
§30 step 5, the last piece of §30's own six-step method chain: "the
event study (CARs around CBSL/CCPI/IMF/budget/election dates)." The
standard MacKinlay (1997) market-model event-study methodology —
never hand-rolled: real `statsmodels.api.OLS` fits the market model, the
abnormal-return and cumulative-abnormal-return (CAR) arithmetic and the
standard-error formula are the textbook ones, not an invented variant.

THE MARKET MODEL, THE ACTUAL METHOD. For one real event date: fit
`asset_return = alpha + beta * market_return + epsilon` by OLS over a
real pre-event ESTIMATION window (never overlapping the event window —
an event's own abnormal return must not leak into the model that's
supposed to define "normal"). Then, for each day in a real EVENT window
around the event date, the Abnormal Return (AR) is the asset's actual
return minus what the fitted market model would have predicted from
that day's real market return; the Cumulative Abnormal Return (CAR) is
their sum across the event window. Significance is a real t-test:
`CAR / sqrt(event_window_length * residual_variance)`, `residual_
variance` from the ESTIMATION window's own OLS residuals — the standard
Brown & Warner (1985) / MacKinlay (1997) formula, not derived from
scratch here.

VALIDATED AGAINST A KNOWN INJECTED ABNORMAL RETURN, NOT JUST THAT IT
RUNS. A synthetic asset return series built to follow the market model
exactly, with a real, known abnormal jump added on one specific event-
window day, correctly produces a CAR close to the injected value and a
significant t-test; the same construction with NO injected jump
correctly does not reject the null (with the same caveat every other
hypothesis-testing module this phase names: a true null still rejects
by chance at roughly the stated significance rate — a specific seed
checked to land comfortably non-significant, not proof the method is
biased).

TWO SEPARATE FUNCTIONS, MATCHING TWO REAL USE CASES. `single_event_
market_model_car` computes one event's own CAR from already-split
estimation-window/event-window return series (date alignment and window-
splitting are the caller's job — see `app.domain.event_study_view`).
`aggregate_car_across_events` combines several real, independent single-
event results into the cross-sectional average CAR and t-test MacKinlay's
own methodology uses for a real study with more than one event — a
single real CBSL policy decision is weak evidence on its own; several
real decisions, aggregated, are what an actual event study reports.

WHAT §30 STEP 5 STILL DOESN'T HAVE, NAMED HONESTLY. This module computes
the real statistics once given real event dates and real return series —
it does not itself supply CCPI-release, IMF-programme-milestone, budget,
or election dates; this project has no real, structured source for any
of those yet (unlike CBSL policy RATE CHANGES, which `app.domain.event_
study_view` derives directly from already-ingested `cbsl.policy_rate`
`macro_series` observations — a real, disclosed scope boundary, not a
silent omission, matching every other §30 module's own "named precisely
what remains unbuilt" discipline).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MIN_ESTIMATION_OBSERVATIONS = 60
DEFAULT_ESTIMATION_LENGTH = 120
DEFAULT_EVENT_WINDOW = (-5, 5)
SIGNIFICANCE_THRESHOLD = Decimal("0.05")


@dataclass(frozen=True)
class SingleEventResult:
    alpha: Decimal
    beta: Decimal
    estimation_observation_count: int
    event_window_observation_count: int
    abnormal_returns: tuple[Decimal, ...]
    """One value per event-window day, in the order the caller supplied
    the event-window return series."""

    cumulative_abnormal_return: Decimal
    standard_error: Decimal
    t_statistic: Decimal
    p_value: Decimal
    significant: bool
    note: str


def single_event_market_model_car(
    estimation_asset_returns: list[Decimal],
    estimation_market_returns: list[Decimal],
    event_asset_returns: list[Decimal],
    event_market_returns: list[Decimal],
) -> SingleEventResult | None:
    """One event's own CAR from the real market model. All four series
    must already be aligned and split by the caller — the estimation
    window strictly BEFORE the event window, never overlapping (see
    module docstring for why).

    `None` — never a number computed from too little data — below
    `MIN_ESTIMATION_OBSERVATIONS`, when the event window is empty, or
    when the underlying OLS fit raises."""
    if len(estimation_asset_returns) < MIN_ESTIMATION_OBSERVATIONS:
        return None
    if len(estimation_asset_returns) != len(estimation_market_returns):
        raise ValueError("estimation asset and market return series must be the same length")
    if not event_asset_returns:
        return None
    if len(event_asset_returns) != len(event_market_returns):
        raise ValueError("event-window asset and market return series must be the same length")

    try:
        import statsmodels.api as sm

        y = [float(v) for v in estimation_asset_returns]
        x = [float(v) for v in estimation_market_returns]
        model = sm.OLS(y, sm.add_constant(x)).fit()
        alpha_hat, beta_hat = float(model.params[0]), float(model.params[1])
        residual_variance = float(model.mse_resid)
    except Exception:
        return None

    event_window_length = len(event_asset_returns)
    abnormal_returns = [
        float(a) - (alpha_hat + beta_hat * float(m))
        for a, m in zip(event_asset_returns, event_market_returns)
    ]
    car = sum(abnormal_returns)
    standard_error = (event_window_length * residual_variance) ** 0.5
    if standard_error == 0:
        return None

    t_stat = car / standard_error
    degrees_of_freedom = len(estimation_asset_returns) - 2

    from scipy import stats

    p_value = float(2 * (1 - stats.t.cdf(abs(t_stat), df=degrees_of_freedom)))
    p_decimal = Decimal(str(round(p_value, 6)))

    note = (
        f"CAR={round(car, 6)} over a {event_window_length}-day event window "
        f"(alpha={round(alpha_hat, 6)}, beta={round(beta_hat, 4)} from "
        f"{len(estimation_asset_returns)} estimation-window observations); "
        f"t={round(t_stat, 4)}, p={p_decimal} — "
        f"{'significant' if p_decimal < SIGNIFICANCE_THRESHOLD else 'not significant'} "
        f"at the {SIGNIFICANCE_THRESHOLD} level."
    )

    return SingleEventResult(
        alpha=Decimal(str(round(alpha_hat, 6))),
        beta=Decimal(str(round(beta_hat, 6))),
        estimation_observation_count=len(estimation_asset_returns),
        event_window_observation_count=event_window_length,
        abnormal_returns=tuple(Decimal(str(round(v, 6))) for v in abnormal_returns),
        cumulative_abnormal_return=Decimal(str(round(car, 6))),
        standard_error=Decimal(str(round(standard_error, 6))),
        t_statistic=Decimal(str(round(t_stat, 6))),
        p_value=p_decimal,
        significant=p_decimal < SIGNIFICANCE_THRESHOLD,
        note=note,
    )


@dataclass(frozen=True)
class AggregateEventStudyResult:
    event_count: int
    car_values: tuple[Decimal, ...]
    average_car: Decimal
    t_statistic: Decimal
    p_value: Decimal
    significant: bool
    note: str


def aggregate_car_across_events(results: list[SingleEventResult]) -> AggregateEventStudyResult | None:
    """The cross-sectional average-CAR t-test MacKinlay's own methodology
    uses to combine several real, independent single-event results —
    `t = mean(CAR) / (std(CAR) / sqrt(N))`, real sample statistics, not
    a weighted or otherwise adjusted average.

    `None` with fewer than 2 real events — a cross-sectional standard
    deviation is undefined for one observation, and reporting a "result"
    from a single event would misrepresent an event study's own point
    (statistical power from aggregating across events)."""
    if len(results) < 2:
        return None

    import statistics

    car_values = [float(r.cumulative_abnormal_return) for r in results]
    mean_car = statistics.fmean(car_values)
    stdev_car = statistics.stdev(car_values)
    if stdev_car == 0:
        return None

    n = len(car_values)
    t_stat = mean_car / (stdev_car / (n ** 0.5))

    from scipy import stats

    p_value = float(2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1)))
    p_decimal = Decimal(str(round(p_value, 6)))

    note = (
        f"Average CAR={round(mean_car, 6)} across {n} real events; "
        f"t={round(t_stat, 4)}, p={p_decimal} — "
        f"{'significant' if p_decimal < SIGNIFICANCE_THRESHOLD else 'not significant'} "
        f"at the {SIGNIFICANCE_THRESHOLD} level."
    )

    return AggregateEventStudyResult(
        event_count=n,
        car_values=tuple(r.cumulative_abnormal_return for r in results),
        average_car=Decimal(str(round(mean_car, 6))),
        t_statistic=Decimal(str(round(t_stat, 6))),
        p_value=p_decimal,
        significant=p_decimal < SIGNIFICANCE_THRESHOLD,
        note=note,
    )
