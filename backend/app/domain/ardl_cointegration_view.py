"""
Bridges stored `macro_series` rows to `app.domain.ardl_cointegration` —
the I/O layer that module deliberately doesn't have.

ALIGNMENT ACROSS DIFFERENT PUBLICATION CADENCES, FORWARD-FILLED, NOT
INTERSECTED — via `app.domain.series_alignment.forward_filled_independent`,
shared with `app.domain.johansen_vecm_view` (§30 step 2's other real
multi-series estimator), not reimplemented per module. The dependent
series (e.g. ASPI, published daily) and an independent series (e.g. the
364-day T-bill yield, published on auction days — weekly) don't share
observation dates. Intersecting on exact dates would throw away nearly
all of the daily series' real information for no good reason; instead,
for every date the dependent series has a real observation, the shared
helper takes whichever independent-series value was MOST RECENTLY
PUBLISHED on or before that date — genuinely "as of that date," the same
point-in-time principle `app.domain.macro_engine_view._latest_and_
window_ago` and `app.domain.macro_view.spread_history`'s own pairing
logic already use for exactly this kind of cross-cadence alignment.

TESTED ON LEVELS, LIKE `app.domain.stationarity_view`, FOR THE SAME
REASON. §30 step 2's actual question is about the long-run relationship
between series LEVELS (does the ASPI level track the T-bill yield
level?), not their day-to-day changes.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.ardl_cointegration import (
    MIN_OBSERVATIONS,
    BoundsTestResult,
    ardl_bounds_test,
)
from app.domain.macro_view import series_history
from app.domain.series_alignment import forward_filled_independent

DEFAULT_LOOKBACK_LIMIT = 400


@dataclass(frozen=True)
class ArdlBoundsTestView:
    dependent_series_id: str
    independent_series_ids: tuple[str, ...]
    as_of: dt.date
    aligned_observation_count: int
    result: BoundsTestResult | None
    warnings: tuple[str, ...]


def ardl_bounds_test_for(
    db: Session,
    dependent_series_id: str,
    independent_series_ids: list[str],
    as_of: dt.date | None = None,
    *,
    limit: int = DEFAULT_LOOKBACK_LIMIT,
) -> ArdlBoundsTestView:
    """§30 step 2's default estimator, live, on real `macro_series`
    LEVEL data — the dependent series' own real observation dates anchor
    the alignment, with every independent series forward-filled onto
    them (see module docstring). Never fabricates a result: `result` is
    `None` when fewer aligned observations exist than `app.domain.ardl_
    cointegration.MIN_OBSERVATIONS` needs, or when the underlying fit
    genuinely fails — the same "None, named" discipline every other
    live-wired view in this system uses."""
    stamp = as_of or dt.date.today()
    dependent_rows = series_history(db, dependent_series_id, stamp, limit=limit)
    dependent_dates = [r.obs_date for r in dependent_rows]
    dependent_values = {r.obs_date: r.value for r in dependent_rows}

    aligned_independents: dict[str, dict[dt.date, Decimal]] = {}
    warnings: list[str] = []
    for series_id in independent_series_ids:
        rows = series_history(db, series_id, stamp, limit=limit)
        if not rows:
            warnings.append(f"No real observations of {series_id!r} available at all.")
            continue
        aligned_independents[series_id] = forward_filled_independent(dependent_dates, rows)

    # Keep only dependent dates where EVERY independent series has a
    # real (forward-filled) value — an ARDL fit needs a complete row per
    # observation, not a partially-missing one silently zero-filled.
    usable_dates = [
        d
        for d in dependent_dates
        if all(d in aligned_independents.get(sid, {}) for sid in independent_series_ids)
    ]

    if len(usable_dates) < MIN_OBSERVATIONS or not independent_series_ids:
        if not independent_series_ids:
            warnings.append("No independent series supplied.")
        else:
            warnings.append(
                f"Only {len(usable_dates)} aligned observations available as of {stamp} — "
                f"below the {MIN_OBSERVATIONS} minimum the bounds test needs to run at all."
            )
        return ArdlBoundsTestView(
            dependent_series_id=dependent_series_id,
            independent_series_ids=tuple(independent_series_ids),
            as_of=stamp, aligned_observation_count=len(usable_dates),
            result=None, warnings=tuple(warnings),
        )

    dependent_series = [dependent_values[d] for d in usable_dates]
    independents = {
        sid: [aligned_independents[sid][d] for d in usable_dates] for sid in independent_series_ids
    }
    result = ardl_bounds_test(dependent_series, independents, dependent_name="y")
    if result is None:
        warnings.append(
            "The bounds test itself could not produce a result on this real, aligned data "
            "(a genuine fit failure — not enough variation, near-singular data, or a similar "
            "real numerical issue, not a data-availability gap)."
        )

    return ArdlBoundsTestView(
        dependent_series_id=dependent_series_id,
        independent_series_ids=tuple(independent_series_ids),
        as_of=stamp, aligned_observation_count=len(usable_dates),
        result=result, warnings=tuple(warnings),
    )
