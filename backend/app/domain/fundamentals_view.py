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
from app.domain.trend_detection import RatioSeriesPoint, RatioTrend, analyse_ratio_trend
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


def historical_ratios_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> dict[dt.date, list[RatioResult]]:
    """Every point-in-time-visible period's ratios, keyed by period_end —
    the input `analyse_ratio_trend` (§13) needs, and the reason it lives
    next to `ratios_for` rather than in the trend module itself: this is
    the only place that owns turning stored `Fundamental` rows into
    ratios, and duplicating that logic elsewhere would risk the two
    falling out of sync.
    """
    stamp = as_of or dt.date.today()
    rows = fundamentals_as_of(db, ticker, stamp)
    if period_type is not None:
        rows = [r for r in rows if r.period_type == period_type]

    by_period: dict[dt.date, dict[str, LineItem]] = {}
    for row in rows:
        items = by_period.setdefault(row.period_end, {})
        existing = items.get(row.statement_line)
        if existing is None:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)

    return {period: compute_all(items) for period, items in sorted(by_period.items())}


def ratio_trends_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> dict[str, RatioTrend]:
    """§13's trend metadata for every ratio with at least one computed
    value across the visible history. A ratio present in only one period
    still appears here — `analyse_ratio_trend` reports
    `insufficient_history` for it explicitly rather than the ratio simply
    not showing up, which would look like an omission rather than a fact
    about the data."""
    by_period = historical_ratios_for(db, ticker, as_of, period_type)

    series_by_key: dict[str, list[RatioSeriesPoint]] = {}
    for period_end, results in by_period.items():
        for result in results:
            if result.value is None:
                continue
            series_by_key.setdefault(result.key, []).append(
                RatioSeriesPoint(period_end=period_end, value=result.value)
            )

    return {key: analyse_ratio_trend(key, series) for key, series in series_by_key.items()}
