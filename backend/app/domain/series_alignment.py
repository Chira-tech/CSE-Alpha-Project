"""
Shared point-in-time alignment helper for §30 step 2's two real multi-
series estimators — `app.domain.ardl_cointegration_view` (the ARDL
bounds-testing default) and `app.domain.johansen_vecm_view` (the "all
I(1)" branch) — both of which need two real `macro_series` streams lined
up despite genuinely different real publication cadences (e.g. the ASPI,
daily, against the 364-day T-bill yield, published on auction days).
Extracted here rather than duplicated across both `_view.py` modules once
the second one needed the exact same logic the first had already solved.

FORWARD-FILLED, NOT INTERSECTED — see the function docstring below for
the full reasoning; this is the same point-in-time "as of" principle
`app.domain.macro_engine_view`/`app.domain.macro_view` already use for
their own cross-cadence pairing.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal


def forward_filled_independent(
    dependent_dates: list[dt.date], independent_rows: list
) -> dict[dt.date, Decimal]:
    """For each date in `dependent_dates`, the independent series' own
    most-recently-published value on or before that date — genuinely
    "as of that date," not an exact-date intersection (which would throw
    away nearly all of a higher-frequency dependent series' real
    information for no good reason). A dependent date that predates
    every independent observation is simply absent from the returned
    dict — never backfilled from a later value, which would leak
    future information into the past."""
    independent_sorted = sorted(independent_rows, key=lambda r: r.obs_date)
    aligned: dict[dt.date, Decimal] = {}
    idx = 0
    latest_value: Decimal | None = None
    for date in dependent_dates:
        while idx < len(independent_sorted) and independent_sorted[idx].obs_date <= date:
            latest_value = independent_sorted[idx].value
            idx += 1
        if latest_value is not None:
            aligned[date] = latest_value
    return aligned
