"""
Shared real-return computation for `_view.py` modules that need one
ticker's own daily total-return series from stored `prices_daily` rows —
extracted here once a second module (`app.domain.event_study_view`, §30
step 5) needed the exact same real, adjusted-price return calculation
`app.domain.sector_sensitivity_view` had already built, rather than
duplicated a second time.

ADJUSTED PRICES, NOT RAW CLOSES. `PriceDaily.adj_factor` is the
cumulative total-return adjustment factor `app.domain.corporate_actions.
build_adjustment_factor_series` computes — a raw close-to-close return
series would be contaminated by unadjusted dividends, bonus issues and
splits. See `app.domain.sector_sensitivity_view`'s own module docstring
for the fuller "adjusted total return" reasoning this module reuses
rather than restates.

`cumulative_adjusted_return` ADDS A SECOND REAL SHAPE — one total return
over a whole real holding period rather than a daily series — needed
once `app.domain.factor_library_view` (§35's own portfolio-sort
factors) needed a real formation-to-current-date return per ticker, not
a day-by-day series to average or regress on.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prices import PriceDaily


def ticker_adjusted_returns(
    db: Session, ticker: str, as_of: dt.date, lookback_days: int
) -> dict[dt.date, Decimal]:
    """Real daily total-return series for one ticker, from adjusted
    closes (`close × adj_factor`). Simple (not log) returns, matching
    `app.domain.sector_sensitivity_view`'s own original convention."""
    start = as_of - dt.timedelta(days=lookback_days)
    rows = db.scalars(
        select(PriceDaily)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date >= start,
            PriceDaily.date <= as_of,
            PriceDaily.close.is_not(None),
        )
        .order_by(PriceDaily.date)
    ).all()
    returns: dict[dt.date, Decimal] = {}
    prev_adj: Decimal | None = None
    for row in rows:
        adj = row.close * row.adj_factor
        if prev_adj is not None and prev_adj > 0:
            returns[row.date] = (adj - prev_adj) / prev_adj
        prev_adj = adj
    return returns


def cumulative_adjusted_return(
    db: Session, ticker: str, start: dt.date, end: dt.date
) -> Decimal | None:
    """The single total return over `[start, end]` — `(end_adj_close ÷
    start_adj_close) − 1` — for a real formation-period holding return
    (§35.1's own MOM/SMB/HML construction all need one), not a daily
    series. Uses the real adjusted close nearest to (on or before) each
    endpoint, the same "most recently available" point-in-time
    convention `app.domain.series_alignment.forward_filled_independent`
    already uses elsewhere in this system for a different real pairing
    problem. `None` when either endpoint has no real price on or before
    it, or when `start`'s own adjusted close is exactly zero (a real,
    if pathological, guard against a division by zero)."""
    start_row = db.scalar(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= start, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    end_row = db.scalar(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= end, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    if start_row is None or end_row is None:
        return None
    start_adj = start_row.close * start_row.adj_factor
    end_adj = end_row.close * end_row.adj_factor
    if start_adj == 0:
        return None
    return (end_adj / start_adj) - 1
