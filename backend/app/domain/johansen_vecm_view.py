"""
Bridges stored `macro_series` rows to `app.domain.johansen_vecm` — the
I/O layer that module deliberately doesn't have. Mirrors `app.domain.
ardl_cointegration_view` almost exactly (same real cross-cadence
alignment via `app.domain.series_alignment.forward_filled_independent`,
same "never fabricate a result" discipline) because both view modules
answer the same underlying question — is there a real long-run
relationship between these two real series — through §30 step 2's two
different named estimators.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.johansen_vecm import MIN_OBSERVATIONS, VecmFitResult, fit_vecm
from app.domain.macro_view import series_history
from app.domain.series_alignment import forward_filled_independent

DEFAULT_LOOKBACK_LIMIT = 400


@dataclass(frozen=True)
class JohansenVecmView:
    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    result: VecmFitResult | None
    warnings: tuple[str, ...]


def johansen_vecm_for(
    db: Session,
    dependent_series_id: str,
    independent_series_id: str,
    as_of: dt.date | None = None,
    *,
    limit: int = DEFAULT_LOOKBACK_LIMIT,
) -> JohansenVecmView:
    """§30 step 2's "all I(1)" estimator, live, on real `macro_series`
    LEVEL data. `result` is `None` — never a fabricated fit — when fewer
    aligned observations exist than `app.domain.johansen_vecm.
    MIN_OBSERVATIONS` needs, or the underlying rank test itself fails;
    once real data clears that bar, `result` is always populated (see
    `app.domain.johansen_vecm.fit_vecm`'s own docstring — a non-
    cointegrated or fit-failure outcome still returns a `VecmFitResult`
    with a named `note`, not `None`)."""
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
            f"below the {MIN_OBSERVATIONS} minimum the Johansen test needs to run at all."
        )
        return JohansenVecmView(
            dependent_series_id=dependent_series_id,
            independent_series_id=independent_series_id,
            as_of=stamp, aligned_observation_count=len(usable_dates),
            result=None, warnings=tuple(warnings),
        )

    dependent_series = [dependent_values[d] for d in usable_dates]
    independent_series = [aligned_independent[d] for d in usable_dates]
    result = fit_vecm(dependent_series, independent_series, dependent_name="y", independent_name="x")
    if result is None:
        warnings.append(
            "The Johansen rank test itself could not produce a result on this real, aligned "
            "data (a genuine numerical failure, not a data-availability gap)."
        )

    return JohansenVecmView(
        dependent_series_id=dependent_series_id,
        independent_series_id=independent_series_id,
        as_of=stamp, aligned_observation_count=len(usable_dates),
        result=result, warnings=tuple(warnings),
    )
