"""
Bridges stored `Fundamental` rows to the pure ratio engine.

Kept separate from app.domain.ratios so that module stays free of ORM
types and remains directly testable against hand-computed figures.

The point-in-time rule applies here as everywhere: line items are
selected through `first_available_date <= as_of`, never `period_end`
(§6). A ratio computed from a restatement the market hadn't seen yet is
the exact look-ahead bias Part N #1 calls the most common source of alpha
that does not exist.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.domain.point_in_time import fundamentals_as_of
from app.domain.ratios import LineItem, RatioResult, compute_all
from app.models.fundamentals import Fundamental


def latest_period_line_items(
    db: Session, ticker: str, as_of: dt.date, period_type: str | None = None
) -> tuple[dt.date | None, dict[str, LineItem]]:
    """Line items for the most recent period visible on `as_of`.

    Returns (period_end, items). Mixing periods would produce ratios whose
    numerator and denominator come from different dates — so this picks a
    single period and works only within it, even if that means fewer
    computable ratios.
    """
    rows: list[Fundamental] = fundamentals_as_of(db, ticker, as_of)
    if period_type is not None:
        rows = [r for r in rows if r.period_type == period_type]
    if not rows:
        return None, {}

    latest_period = max(r.period_end for r in rows)
    items: dict[str, LineItem] = {}
    for row in rows:
        if row.period_end != latest_period:
            continue
        # fundamentals_as_of already resolves restatement versions; if the
        # same line still appears twice, prefer the higher version.
        existing = items.get(row.statement_line)
        if existing is None:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)

    return latest_period, items


def ratios_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> tuple[dt.date | None, list[RatioResult]]:
    stamp = as_of or dt.date.today()
    period_end, items = latest_period_line_items(db, ticker, stamp, period_type)
    return period_end, compute_all(items)
