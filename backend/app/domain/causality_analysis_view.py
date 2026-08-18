"""
Bridges stored `macro_series` rows to `app.domain.causality_analysis` —
the I/O layer that module deliberately doesn't have. Same real cross-
cadence alignment as every other §30 step 2/3 view module, via `app.
domain.series_alignment.forward_filled_independent`.

IMPULSE RESPONSE/FEVD REUSES WHICHEVER ESTIMATOR STEP 2 ALREADY PICKED —
NOT A SEPARATE DECISION. `impulse_response_fevd_for` calls `app.domain.
estimator_selection_view.select_and_fit_estimator` first and only
proceeds when it actually landed on `"johansen_vecm"` or `"var_
differences"` (never `"ardl_bounds_test"` or `"insufficient_data"` —
the ARDL branch doesn't produce a VAR-shaped fitted model this function
can compute an impulse response from, and `app.domain.causality_
analysis.impulse_response_and_fevd` is deliberately restricted to the
two branches that do). This is a real, disclosed scope boundary, not an
oversight: a pair step 2 routes to ARDL bounds testing does not get an
impulse response from this module at all.

TODA-YAMAMOTO CAUSALITY RUNS INDEPENDENTLY OF STEP 2'S OWN CHOICE — see
`app.domain.causality_analysis`'s own module docstring for why: the
whole point of the method is not needing to know cointegration status
up front. This view still needs each series' own real stationarity
consensus (to size the augmentation correctly), reusing `app.domain.
stationarity_view.stationarity_for_series` and `app.domain.estimator_
selection.select_estimator`'s own consensus-to-augmentation mapping
logic (I(1) -> augmentation 1, I(0) -> augmentation 0, anything else ->
refuse) rather than inventing a second one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.causality_analysis import (
    DEFAULT_IRF_PERIODS,
    DEFAULT_LAGS,
    ImpulseResponseFevdResult,
    MIN_OBSERVATIONS,
    TodaYamamotoResult,
    impulse_response_and_fevd,
    toda_yamamoto_causality_test,
)
from app.domain.estimator_selection_view import select_and_fit_estimator
from app.domain.macro_view import series_history
from app.domain.series_alignment import forward_filled_independent
from app.domain.stationarity_view import stationarity_for_series

DEFAULT_LOOKBACK_LIMIT = 400


def _aligned_series(
    db: Session, dependent_series_id: str, independent_series_id: str, stamp: dt.date, limit: int
) -> tuple[list[Decimal], list[Decimal], int, list[str]]:
    """Shared alignment step both view functions below need — returns
    `(dependent_values, independent_values, aligned_count, warnings)`."""
    dependent_rows = series_history(db, dependent_series_id, stamp, limit=limit)
    dependent_dates = [r.obs_date for r in dependent_rows]
    dependent_values = {r.obs_date: r.value for r in dependent_rows}

    warnings: list[str] = []
    independent_rows = series_history(db, independent_series_id, stamp, limit=limit)
    if not independent_rows:
        warnings.append(f"No real observations of {independent_series_id!r} available at all.")
        aligned_independent: dict[dt.date, Decimal] = {}
    else:
        aligned_independent = forward_filled_independent(dependent_dates, independent_rows)

    usable_dates = [d for d in dependent_dates if d in aligned_independent]
    dependent_series = [dependent_values[d] for d in usable_dates]
    independent_series = [aligned_independent[d] for d in usable_dates]
    return dependent_series, independent_series, len(usable_dates), warnings


@dataclass(frozen=True)
class ImpulseResponseFevdView:
    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    estimator_used: str | None
    """The estimator step 2's own selection actually landed on —
    `None` when that selection didn't reach `"johansen_vecm"` or
    `"var_differences"` (e.g. it picked ARDL, or had insufficient data),
    in which case `result` is also `None`."""

    result: ImpulseResponseFevdResult | None
    warnings: tuple[str, ...]


def impulse_response_fevd_for(
    db: Session,
    dependent_series_id: str,
    independent_series_id: str,
    as_of: dt.date | None = None,
    *,
    periods: int = DEFAULT_IRF_PERIODS,
    limit: int = DEFAULT_LOOKBACK_LIMIT,
) -> ImpulseResponseFevdView:
    stamp = as_of or dt.date.today()
    selection = select_and_fit_estimator(db, dependent_series_id, independent_series_id, stamp)

    if selection.estimator_used not in ("johansen_vecm", "var_differences"):
        return ImpulseResponseFevdView(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=0, estimator_used=None, result=None,
            warnings=(
                f"§30 step 2's own estimator selection landed on {selection.estimator_used!r} for "
                "this pair, not a VAR-shaped fit — no impulse response/FEVD to compute. "
                f"Reason: {selection.reason}",
            ),
        )

    dependent_series, independent_series, aligned_count, warnings = _aligned_series(
        db, dependent_series_id, independent_series_id, stamp, limit
    )
    if aligned_count < MIN_OBSERVATIONS:
        warnings.append(
            f"Only {aligned_count} aligned observations available as of {stamp} — below the "
            f"{MIN_OBSERVATIONS} minimum this needs to run at all."
        )
        return ImpulseResponseFevdView(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=aligned_count,
            estimator_used=selection.estimator_used, result=None, warnings=tuple(warnings),
        )

    result = impulse_response_and_fevd(
        dependent_series, independent_series,
        estimator=selection.estimator_used, dependent_name="y", independent_name="x", periods=periods,
    )
    if result is None:
        warnings.append("The impulse response/FEVD fit itself could not produce a result on this real data.")

    return ImpulseResponseFevdView(
        dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
        as_of=stamp, aligned_observation_count=aligned_count,
        estimator_used=selection.estimator_used, result=result, warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class TodaYamamotoView:
    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    dependent_consensus: str | None
    independent_consensus: str | None
    result: TodaYamamotoResult | None
    warnings: tuple[str, ...]


def _augmentation_for(dependent_consensus: str | None, independent_consensus: str | None) -> int | None:
    """`app.domain.estimator_selection.select_estimator`'s own
    consensus-reading logic, reused for a different purpose (sizing the
    Toda-Yamamoto augmentation) rather than reimplemented: `None` for
    anything ambiguous or unmeasured, 1 when either series is I(1), 0
    when both are confirmed I(0)."""
    if dependent_consensus is None or independent_consensus is None:
        return None
    if dependent_consensus in ("insufficient_data", "mixed_evidence"):
        return None
    if independent_consensus in ("insufficient_data", "mixed_evidence"):
        return None
    if dependent_consensus == "non_stationary" or independent_consensus == "non_stationary":
        return 1
    return 0


def toda_yamamoto_for(
    db: Session,
    dependent_series_id: str,
    independent_series_id: str,
    as_of: dt.date | None = None,
    *,
    lags: int = DEFAULT_LAGS,
    limit: int = DEFAULT_LOOKBACK_LIMIT,
) -> TodaYamamotoView:
    stamp = as_of or dt.date.today()

    dep_stationarity = stationarity_for_series(db, dependent_series_id, stamp)
    indep_stationarity = stationarity_for_series(db, independent_series_id, stamp)
    dep_consensus = dep_stationarity.assessment.consensus if dep_stationarity.assessment else None
    indep_consensus = indep_stationarity.assessment.consensus if indep_stationarity.assessment else None

    augmentation = _augmentation_for(dep_consensus, indep_consensus)

    dependent_series, independent_series, aligned_count, warnings = _aligned_series(
        db, dependent_series_id, independent_series_id, stamp, limit
    )

    if augmentation is None:
        warnings.append(
            "Each series' own real integration order is unknown or genuinely ambiguous — refusing "
            "to guess how many dummy lags Toda-Yamamoto needs rather than risk an invalid test."
        )
        return TodaYamamotoView(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=aligned_count,
            dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
            result=None, warnings=tuple(warnings),
        )

    if aligned_count < MIN_OBSERVATIONS:
        warnings.append(
            f"Only {aligned_count} aligned observations available as of {stamp} — below the "
            f"{MIN_OBSERVATIONS} minimum this needs to run at all."
        )
        return TodaYamamotoView(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=aligned_count,
            dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
            result=None, warnings=tuple(warnings),
        )

    result = toda_yamamoto_causality_test(
        dependent_series, independent_series,
        dependent_name="y", independent_name="x", lags=lags,
        integration_order_augmentation=augmentation,
    )
    if result is None:
        warnings.append("The Toda-Yamamoto fit itself could not produce a result on this real data.")

    return TodaYamamotoView(
        dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
        as_of=stamp, aligned_observation_count=aligned_count,
        dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
        result=result, warnings=tuple(warnings),
    )
