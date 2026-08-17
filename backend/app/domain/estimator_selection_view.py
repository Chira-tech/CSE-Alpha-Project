"""
§30 step 2, assembled end to end: real stationarity assessments for both
series feed `app.domain.estimator_selection.select_estimator`'s routing
decision, which is then actually EXECUTED against real `macro_series`
data via whichever of `app.domain.johansen_vecm_view`, `app.domain.ardl_
cointegration_view`, or `app.domain.var_differences_view` applies — the
first module in this project that runs §30 step 2's full three-way
decision, not just one branch of it in isolation.

THE FALLBACK CHAIN LIVES HERE, NOT IN THE PURE ROUTER. `select_
estimator` only picks which estimator to ATTEMPT from each series' own
stationarity consensus; it can't know whether that attempt will actually
find a real cointegrating relationship. This module runs the attempt and
inspects its own real conclusion: a Johansen candidate that finds no
real cointegration, or an ARDL bounds test that concludes "not
cointegrated," both genuinely fall through to `var_in_differences_for`
— §30 step 2's own "no cointegration" branch — exactly the way a human
analyst working through the same three cases by hand would.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.ardl_cointegration_view import ArdlBoundsTestView, ardl_bounds_test_for
from app.domain.estimator_selection import EstimatorChoice, select_estimator
from app.domain.johansen_vecm_view import JohansenVecmView, johansen_vecm_for
from app.domain.stationarity_view import stationarity_for_series
from app.domain.var_differences_view import VarDifferencesView, var_in_differences_for

@dataclass(frozen=True)
class EstimatorSelectionResult:
    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    dependent_consensus: str | None
    independent_consensus: str | None
    initial_choice: EstimatorChoice
    estimator_used: str
    """The estimator whose result is actually reported — may differ from
    `initial_choice` when the initial attempt found no real cointegrating
    relationship and this module fell back to `"var_differences"`."""

    reason: str
    johansen_vecm: JohansenVecmView | None = None
    ardl_bounds_test: ArdlBoundsTestView | None = None
    var_differences: VarDifferencesView | None = None


def select_and_fit_estimator(
    db: Session,
    dependent_series_id: str,
    independent_series_id: str,
    as_of: dt.date | None = None,
) -> EstimatorSelectionResult:
    stamp = as_of or dt.date.today()

    dep_stationarity = stationarity_for_series(db, dependent_series_id, stamp)
    indep_stationarity = stationarity_for_series(db, independent_series_id, stamp)
    dep_consensus = dep_stationarity.assessment.consensus if dep_stationarity.assessment else None
    indep_consensus = indep_stationarity.assessment.consensus if indep_stationarity.assessment else None

    choice, reason = select_estimator(dep_consensus, indep_consensus)

    if choice == "insufficient_data":
        return EstimatorSelectionResult(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
            initial_choice=choice, estimator_used="insufficient_data", reason=reason,
        )

    if choice == "johansen_vecm":
        vecm_view = johansen_vecm_for(db, dependent_series_id, independent_series_id, stamp)
        if vecm_view.result is not None and vecm_view.result.johansen.conclusion == "cointegrated":
            return EstimatorSelectionResult(
                dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
                as_of=stamp, dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
                initial_choice=choice, estimator_used="johansen_vecm", reason=reason,
                johansen_vecm=vecm_view,
            )
        var_view = var_in_differences_for(db, dependent_series_id, independent_series_id, stamp)
        fallback_reason = (
            reason + " The Johansen test itself found no real cointegrating relationship, so "
            "falling back to a VAR in first differences per §30 step 2's own \"no cointegration\" branch."
        )
        return EstimatorSelectionResult(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
            initial_choice=choice, estimator_used="var_differences", reason=fallback_reason,
            johansen_vecm=vecm_view, var_differences=var_view,
        )

    # choice == "ardl_bounds_test"
    ardl_view = ardl_bounds_test_for(db, dependent_series_id, [independent_series_id], stamp)
    if ardl_view.result is not None and ardl_view.result.conclusion == "cointegrated":
        return EstimatorSelectionResult(
            dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
            as_of=stamp, dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
            initial_choice=choice, estimator_used="ardl_bounds_test", reason=reason,
            ardl_bounds_test=ardl_view,
        )
    var_view = var_in_differences_for(db, dependent_series_id, independent_series_id, stamp)
    fallback_reason = (
        reason + " The ARDL bounds test itself found no real cointegrating relationship, so "
        "falling back to a VAR in first differences per §30 step 2's own \"no cointegration\" branch."
    )
    return EstimatorSelectionResult(
        dependent_series_id=dependent_series_id, independent_series_id=independent_series_id,
        as_of=stamp, dependent_consensus=dep_consensus, independent_consensus=indep_consensus,
        initial_choice=choice, estimator_used="var_differences", reason=fallback_reason,
        ardl_bounds_test=ardl_view, var_differences=var_view,
    )
