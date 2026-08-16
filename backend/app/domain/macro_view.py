"""
Reads `macro_series` and assembles §29's hero spread.

Kept apart from app.domain.macro so that module stays pure arithmetic and
testable without a database.

The point-in-time rule is the whole reason this is careful: the T-bill
yield and the market P/E come from different sources with different
release cadences (T-bill auctions are weekly, market P/E is daily), so
pairing them means finding the T-bill observation that was actually
PUBLISHED on or before the market observation's date. Pairing a Monday
earnings yield with Wednesday's auction result would be a small,
invisible look-ahead — and §29 makes this spread the most consequential
number in the system, so a subtle error here propagates everywhere.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.macro import (
    RISK_FREE_PREFERENCE,
    SERIES_MARKET_PER,
    EquityTbillSpread,
    compute_spread,
)
from app.models.macro import MacroSeries


def latest_observation(
    db: Session, series_id: str, as_of: dt.date | None = None
) -> MacroSeries | None:
    """Most recent observation of `series_id` that was publicly available
    on `as_of` — filtered on first_available_date, never obs_date (§6)."""
    stmt = select(MacroSeries).where(MacroSeries.series_id == series_id)
    if as_of is not None:
        stmt = stmt.where(MacroSeries.first_available_date <= as_of)
    return db.scalar(stmt.order_by(MacroSeries.obs_date.desc()).limit(1))


def series_history(
    db: Session, series_id: str, as_of: dt.date | None = None, limit: int = 500
) -> list[MacroSeries]:
    stmt = select(MacroSeries).where(MacroSeries.series_id == series_id)
    if as_of is not None:
        stmt = stmt.where(MacroSeries.first_available_date <= as_of)
    rows = db.scalars(stmt.order_by(MacroSeries.obs_date.desc()).limit(limit)).all()
    return list(reversed(rows))  # ascending, as a chart wants


def risk_free_observation(db: Session, as_of: dt.date | None = None) -> MacroSeries | None:
    """§17.1 Route A: the 364-day T-bill yield. Returns None rather than
    falling back to a shorter tenor or a hard-coded figure — the cost of
    equity is built on this, and a silently substituted rate would make
    every fair value in the system wrong in a way nothing else would
    catch."""
    for series_id in RISK_FREE_PREFERENCE:
        observation = latest_observation(db, series_id, as_of)
        if observation is not None:
            return observation
    return None


def current_spread(db: Session, as_of: dt.date | None = None) -> EquityTbillSpread | None:
    per_row = latest_observation(db, SERIES_MARKET_PER, as_of)
    tbill_row = risk_free_observation(db, as_of)
    if per_row is None or tbill_row is None:
        return None

    return compute_spread(
        obs_date=per_row.obs_date,
        market_per=per_row.value,
        tbill_yield=tbill_row.value,
        tbill_obs_date=tbill_row.obs_date,
        tbill_source=tbill_row.source,
    )


def spread_history(db: Session, as_of: dt.date | None = None, limit: int = 500) -> list[EquityTbillSpread]:
    """One spread per market observation, each paired with the T-bill
    yield that was public on that date — not the latest one. Using
    today's rate against a historical earnings yield would rewrite
    history every time the rate moved."""
    per_rows = series_history(db, SERIES_MARKET_PER, as_of, limit)
    if not per_rows:
        return []

    tbill_rows = []
    for series_id in RISK_FREE_PREFERENCE:
        tbill_rows = series_history(db, series_id, as_of, limit)
        if tbill_rows:
            break
    if not tbill_rows:
        return []

    results: list[EquityTbillSpread] = []
    for per_row in per_rows:
        applicable = [t for t in tbill_rows if t.first_available_date <= per_row.obs_date]
        if not applicable:
            continue  # no rate was public yet — omit rather than guess
        tbill = applicable[-1]
        spread = compute_spread(
            obs_date=per_row.obs_date,
            market_per=per_row.value,
            tbill_yield=tbill.value,
            tbill_obs_date=tbill.obs_date,
            tbill_source=tbill.source,
        )
        if spread is not None:
            results.append(spread)
    return results


def record_observation(
    db: Session,
    *,
    series_id: str,
    obs_date: dt.date,
    value: Decimal,
    first_available_date: dt.date | None = None,
    source: str,
) -> MacroSeries:
    """Insert or update one observation. Used by the manual-entry CLI for
    CBSL series until a scraper exists.

    `first_available_date` defaults to `obs_date`, which is right for
    same-day figures (a T-bill auction result is public the day of the
    auction) but wrong for lagged releases like CCPI — hence it being an
    explicit parameter rather than always inferred.
    """
    available = first_available_date or obs_date
    existing = db.scalar(
        select(MacroSeries).where(
            MacroSeries.series_id == series_id, MacroSeries.obs_date == obs_date
        )
    )
    if existing is not None:
        existing.value = value
        existing.first_available_date = available
        existing.source = source
        db.commit()
        return existing

    row = MacroSeries(
        series_id=series_id,
        obs_date=obs_date,
        first_available_date=available,
        value=value,
        source=source,
    )
    db.add(row)
    db.commit()
    return row
