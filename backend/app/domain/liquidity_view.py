"""
Bridges stored `prices_daily`/`securities` rows to `app.domain.
liquidity` — the I/O layer that module deliberately doesn't have.

ADJUSTED RETURNS, RAW TURNOVER — A DELIBERATE, DISCLOSED PAIRING, NOT AN
INCONSISTENCY. The return series reuses `app.domain.price_returns.
ticker_adjusted_returns` (adjusted for splits/dividends via `PriceDaily.
adj_factor`) so a corporate action doesn't masquerade as a genuine price-
impact event. Turnover is computed as RAW `close × volume` on the SAME
dates — the actual rupee value that changed hands that day, which a
total-return adjustment factor has no bearing on (nobody traded an
"adjusted" number of rupees). Both real, both from the same real
`prices_daily` rows, deliberately not adjusted the same way because they
answer different questions.

THE UNIVERSE FOR RANKING IS "EVERY TICKER WITH ENOUGH REAL DATA TO
COMPUTE A REAL RATIO" — not filtered to any coverage tier or archetype.
A name too thin to rank against would be exactly the wrong one to
silently drop from the ranking that's supposed to identify it as thin.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.liquidity import amihud_illiquidity_ratio, percentile_rank
from app.domain.price_returns import ticker_adjusted_returns
from app.models.prices import PriceDaily
from app.models.securities import Security

DEFAULT_LOOKBACK_DAYS = 400


def _ticker_turnovers(db: Session, ticker: str, as_of: dt.date, lookback_days: int) -> dict[dt.date, Decimal]:
    """Real raw turnover (`close × volume`) per date — see module
    docstring for why this is deliberately NOT adjusted like the return
    series it gets paired with."""
    start = as_of - dt.timedelta(days=lookback_days)
    rows = db.scalars(
        select(PriceDaily)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date >= start,
            PriceDaily.date <= as_of,
            PriceDaily.close.is_not(None),
            PriceDaily.volume.is_not(None),
        )
        .order_by(PriceDaily.date)
    ).all()
    return {row.date: row.close * row.volume for row in rows}


def _ticker_amihud_ratio(
    db: Session, ticker: str, as_of: dt.date, lookback_days: int
) -> Decimal | None:
    returns = ticker_adjusted_returns(db, ticker, as_of, lookback_days)
    turnovers = _ticker_turnovers(db, ticker, as_of, lookback_days)
    common_dates = sorted(set(returns) & set(turnovers))
    if not common_dates:
        return None
    return amihud_illiquidity_ratio(
        [returns[d] for d in common_dates], [turnovers[d] for d in common_dates]
    )


def universe_amihud_ratios(
    db: Session, as_of: dt.date, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> dict[str, Decimal]:
    """Real Amihud ratio for every real ticker with enough real data to
    compute one — see `app.domain.liquidity.MIN_OBSERVATIONS`. A ticker
    with too little real data is simply absent from the returned dict,
    not defaulted to any value."""
    tickers = db.scalars(select(Security.ticker)).all()
    ratios: dict[str, Decimal] = {}
    for ticker in tickers:
        ratio = _ticker_amihud_ratio(db, ticker, as_of, lookback_days)
        if ratio is not None:
            ratios[ticker] = ratio
    return ratios


def liquidity_percentile_for(
    db: Session, ticker: str, as_of: dt.date | None = None, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> Decimal | None:
    """This ticker's own real liquidity percentile within the real
    universe (0-100, HIGHER = MORE liquid — see `app.domain.liquidity`'s
    own docstring). `None` when this ticker itself doesn't have enough
    real data to rank, regardless of how many other tickers do."""
    stamp = as_of or dt.date.today()
    ratios = universe_amihud_ratios(db, stamp, lookback_days)
    return percentile_rank(ratios).get(ticker)
