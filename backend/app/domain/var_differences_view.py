"""
Bridges stored `macro_series` rows to `app.domain.var_differences` — the
I/O layer that module deliberately doesn't have. Same real cross-cadence
alignment as `app.domain.ardl_cointegration_view`/`app.domain.johansen_
vecm_view`, via the shared `app.domain.series_alignment.forward_filled_
independent` helper — the third of §30 step 2's three view modules, all
built to the same pattern for the same reason: real levels forward-filled
onto whichever series publishes more often, "never fabricate a result on
too little data" as the shared discipline.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.macro_view import series_history
from app.domain.series_alignment import forward_filled_independent
from app.domain.var_differences import (
    MIN_OBSERVATIONS,
    VarDifferencesResult,
    fit_var_in_differences,
)

DEFAULT_LOOKBACK_LIMIT = 400


@dataclass(frozen=True)
class VarDifferencesView:
    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    result: VarDifferencesResult | None
    warnings: tuple[str, ...]


def var_in_differences_for(
    db: Session,
    dependent_series_id: str,
    independent_series_id: str,
    as_of: dt.date | None = None,
    *,
    limit: int = DEFAULT_LOOKBACK_LIMIT,
) -> VarDifferencesView:
    """§30 step 2's "no cointegration" estimator, live, on real
    `macro_series` LEVEL data (differenced internally by `app.domain.
    var_differences.fit_var_in_differences` — see that module's own
    docstring for why it takes levels like the other two branches
    rather than pre-differenced input). `result` is `None` — never a
    fabricated short-run coefficient — when fewer aligned observations
    exist than `MIN_OBSERVATIONS` needs, or the underlying fit fails."""
    stamp = as_of or dt.date.today()
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

    if len(usable_dates) < MIN_OBSERVATIONS:
        warnings.append(
            f"Only {len(usable_dates)} aligned observations available as of {stamp} — "
            f"below the {MIN_OBSERVATIONS} minimum this estimator needs to run at all."
        )
        return VarDifferencesView(
            dependent_series_id=dependent_series_id,
            independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=len(usable_dates),
            result=None, warnings=tuple(warnings),
        )

    dependent_series = [dependent_values[d] for d in usable_dates]
    independent_series = [aligned_independent[d] for d in usable_dates]
    result = fit_var_in_differences(
        dependent_series, independent_series, dependent_name="y", independent_name="x"
    )
    if result is None:
        warnings.append(
            "The VAR fit itself could not produce a result on this real, aligned data "
            "(a genuine numerical failure, not a data-availability gap)."
        )

    return VarDifferencesView(
        dependent_series_id=dependent_series_id,
        independent_series_id=independent_series_id,
        as_of=stamp, aligned_observation_count=len(usable_dates),
        result=result, warnings=tuple(warnings),
    )
