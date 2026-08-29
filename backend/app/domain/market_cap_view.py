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
from app.models.securities import Security


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


#: Share classes that hold a claim on the SAME shareholders' equity, and
#: must therefore all be counted when turning a company-wide figure into a
#: per-share one. `rights` is deliberately excluded — a rights line
#: (AAF.R0000) is a tradeable entitlement, not issued share capital, and
#: adding it would understate book value per share. `unit` lines
#: (CALC/CALI/CALU) are standalone closed-end funds with no sibling class,
#: so they are unaffected either way.
_EQUITY_CLAIM_INSTRUMENTS = ("ordinary", "non_voting")


def latest_shares_issued_all_classes(db: Session, ticker: str, as_of: dt.date) -> int | None:
    """Total shares issued across every equity class of the SAME ISSUER.

    A REAL BUG THIS CLOSES, found live (29 Aug 2026): `total_equity` on a
    `.X0000` non-voting row is the WHOLE company's equity — a bank does not
    publish a separate balance sheet per share class — but
    `latest_shares_issued` returned only that class's own share count. For
    HNB.X0000 that divided 281,085,275,000 of real equity by 117,103,990
    non-voting shares, giving a book value of 2,400/share against a true
    ~487 (281bn over 577m total shares). Its fair value came out at 1,240
    against a 330 price, and the ticker was reported as
    `strong_accumulate` — the single most dangerous shape of error this
    project exists to prevent, since it is confident, precise and entirely
    wrong. Every one of the 20 dual-listed `.X0000` tickers was overstated
    by its own class-to-total share ratio.

    Deliberately a SEPARATE function rather than a change to
    `latest_shares_issued`: market capitalisation of one listed line is
    genuinely that line's own shares times its own price (see
    `market_cap_for` and `app.jobs.market_cap_reconciliation`, which
    reconciles against the exchange's own per-line published figure), so
    that caller must keep the per-class count. Only per-share figures
    derived from company-wide fundamentals need this one.
    """
    security = db.get(Security, ticker)
    if security is None or security.issuer_code is None:
        return latest_shares_issued(db, ticker, as_of)
    siblings = db.scalars(
        select(Security.ticker).where(
            Security.issuer_code == security.issuer_code,
            Security.instrument_type.in_(_EQUITY_CLAIM_INSTRUMENTS),
        )
    ).all()
    if not siblings:
        return latest_shares_issued(db, ticker, as_of)
    total = 0
    found = False
    for sibling in siblings:
        shares = latest_shares_issued(db, sibling, as_of)
        if shares:
            total += shares
            found = True
    return total if found else None


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
