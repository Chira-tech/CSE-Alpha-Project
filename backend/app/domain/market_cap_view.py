"""
Bridges stored `float_data`/`prices_daily` rows to `app.domain.
market_cap` — the I/O layer that module deliberately doesn't have.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.market_cap import market_cap
from app.models.float_data import FloatData
from app.models.prices import PriceDaily


def latest_shares_issued(db: Session, ticker: str, as_of: dt.date) -> int | None:
    """The most recent real, point-in-time-visible `FloatData.shares_
    issued` for this ticker on or before `as_of` — extracted here from
    `app.domain.valuation_view`'s own original private copy once a
    second real consumer (market cap here) needed the exact same lookup,
    rather than a second independent copy of the same query."""
    row = db.scalar(
        select(FloatData)
        .where(FloatData.ticker == ticker, FloatData.as_of <= as_of)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )
    return row.shares_issued if row else None


def _latest_close(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    row = db.scalar(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    return row.close if row else None


def published_market_cap_for(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    """CSE's OWN independently-published market cap on or before `as_of`
    — see `app.models.float_data.FloatData.published_market_cap`'s own
    docstring and `app.domain.sanity.SanityContext.mcap`'s docstring for
    why TASK 0.1's plausibility gate needs this specific figure rather
    than `market_cap_for` (which is computed locally from `price x
    shares` and would be a tautological check against itself)."""
    row = db.scalar(
        select(FloatData)
        .where(FloatData.ticker == ticker, FloatData.as_of <= as_of)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )
    return row.published_market_cap if row else None


def bulk_market_cap_for(
    db: Session, tickers: tuple[str, ...], as_of: dt.date | None = None
) -> dict[str, Decimal | None]:
    """R1 T4.6.4's sector drill-down needs every constituent's market cap
    at once — this is `market_cap_for`'s same real "full-shares-issued
    price proxy" (see that function's own docstring), but as two bulk
    queries across the whole ticker set instead of two round trips PER
    ticker, the same discipline `app.api.routes.securities._bulk_price_
    changes` already applies. A ticker missing either input is `None`,
    never a value computed from a partial one."""
    stamp = as_of or dt.date.today()
    if not tickers:
        return {}

    float_rows = db.execute(
        select(FloatData.ticker, FloatData.as_of, FloatData.shares_issued).where(
            FloatData.ticker.in_(tickers), FloatData.as_of <= stamp
        )
    ).all()
    latest_shares: dict[str, tuple[dt.date, int]] = {}
    for ticker, as_of_row, shares in float_rows:
        current = latest_shares.get(ticker)
        if current is None or as_of_row > current[0]:
            latest_shares[ticker] = (as_of_row, shares)

    price_rows = db.execute(
        select(PriceDaily.ticker, PriceDaily.date, PriceDaily.close).where(
            PriceDaily.ticker.in_(tickers), PriceDaily.date <= stamp, PriceDaily.close.is_not(None)
        )
    ).all()
    latest_close: dict[str, tuple[dt.date, Decimal]] = {}
    for ticker, date, close in price_rows:
        current = latest_close.get(ticker)
        if current is None or date > current[0]:
            latest_close[ticker] = (date, close)

    result: dict[str, Decimal | None] = {}
    for ticker in tickers:
        shares_entry = latest_shares.get(ticker)
        price_entry = latest_close.get(ticker)
        if shares_entry is None or price_entry is None:
            result[ticker] = None
        else:
            result[ticker] = market_cap(shares_entry[1], price_entry[1])
    return result


def market_cap_for(db: Session, ticker: str, as_of: dt.date | None = None) -> Decimal | None:
    """This ticker's own real market cap (a disclosed full-shares-issued
    proxy for free-float market cap — see `app.domain.market_cap`'s own
    docstring), from the most recent real point-in-time `shares_issued`
    and the most recent real close on or before `as_of`. `None` — never
    a value computed from a missing input — whenever either real figure
    is unavailable."""
    stamp = as_of or dt.date.today()
    shares = latest_shares_issued(db, ticker, stamp)
    price = _latest_close(db, ticker, stamp)
    if shares is None or price is None:
        return None
    return market_cap(shares, price)
