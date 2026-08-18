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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.point_in_time import fundamentals_as_of
from app.domain.provenance import can_enter_valuation
from app.domain.ratios import LineItem, RatioResult, compute_all
from app.domain.trend_detection import RatioSeriesPoint, RatioTrend, analyse_ratio_trend
from app.domain.ttm import trailing_twelve_months
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
    net_income_period_type: str | None = None
    for row in rows:
        if row.period_end != latest_period:
            continue
        # fundamentals_as_of already resolves restatement versions; if the
        # same line still appears twice, prefer the higher version.
        existing = items.get(row.statement_line)
        if existing is None:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)
            if row.statement_line == "net_income":
                net_income_period_type = row.period_type

    # Same real P0 fix as `app.domain.valuation_view._confirmable_line_
    # items` — see `app.domain.ttm`'s own module docstring. Only applied
    # when the line is itself already confirmed: an AI-assisted
    # `net_income` is intentionally shown here as-is (this function,
    # unlike the valuation one, deliberately displays AI-assisted ratios
    # with their own chip rather than withholding them), and `trailing_
    # twelve_months` only ever reasons over CONFIRMED periods — mixing
    # an unconfirmed current period with a confirmed-period TTM
    # computation could silently pair mismatched dates, exactly what
    # this function's own docstring says never to do.
    if (
        "net_income" in items
        and net_income_period_type is not None
        and can_enter_valuation(items["net_income"].provenance)
    ):
        ttm_net_income = trailing_twelve_months(
            db, ticker, "net_income", as_of,
            current_period_end=latest_period, current_period_type=net_income_period_type,
            current_value=items["net_income"].value,
        )
        if ttm_net_income is not None:
            items["net_income"] = LineItem(
                value=ttm_net_income, provenance=items["net_income"].provenance
            )
        else:
            del items["net_income"]

    return latest_period, items


def bulk_latest_line_items(
    db: Session, as_of: dt.date, statement_lines: tuple[str, ...]
) -> dict[str, tuple[dt.date, dict[str, LineItem]]]:
    """The same point-in-time-and-restatement-version rule
    `fundamentals_as_of` applies per ticker, but for EVERY ticker in one
    query rather than one call per ticker — the single-query discipline
    `app.api.routes.securities.list_securities` already applies to
    prices ("done as a subquery rather than N+1 per-ticker lookups"),
    now extended to fundamentals so a screener column can exist without
    284 round trips. Only fetches the named `statement_lines`, not every
    line on file, since a screener typically wants one or two ratios'
    worth of inputs, not a full statement.

    Returns `{ticker: (latest_period_end, {statement_line: LineItem})}` —
    tickers with nothing point-in-time-visible are simply absent, not
    present with an empty dict, so a caller's `.get(ticker)` naturally
    distinguishes "no data" from "data with a gap."
    """
    rows = db.scalars(
        select(Fundamental).where(
            Fundamental.statement_line.in_(statement_lines),
            Fundamental.first_available_date <= as_of,
        )
    ).all()

    # ticker -> period_end -> statement_line -> highest-version row visible by as_of
    by_ticker: dict[str, dict[dt.date, dict[str, Fundamental]]] = {}
    for row in rows:
        by_period = by_ticker.setdefault(row.ticker, {})
        by_line = by_period.setdefault(row.period_end, {})
        existing = by_line.get(row.statement_line)
        if existing is None or row.version > existing.version:
            by_line[row.statement_line] = row

    result: dict[str, tuple[dt.date, dict[str, LineItem]]] = {}
    for ticker, by_period in by_ticker.items():
        latest_period = max(by_period)
        items = {
            line: LineItem(value=f.value, provenance=f.provenance_tier)
            for line, f in by_period[latest_period].items()
        }
        result[ticker] = (latest_period, items)
    return result


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
