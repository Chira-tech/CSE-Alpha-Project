"""
§35's real HML_hard factor, wired end to end — the first of §35's five
named factors this system can compute from real, already-built data:
real market cap (`app.domain.market_cap_view`, a disclosed full-shares-
issued proxy for free float), real hard book value (`app.domain.
valuation_view.hard_book_for`, §22's own revaluation-stripped figure —
"§35.1: HML_hard... use as primary" says to prefer exactly this over
plain reported book), and a real holding-period return (`app.domain.
price_returns.cumulative_adjusted_return`), fed into the real 2×3 sort
(`app.domain.portfolio_sort.two_by_three_sort`).

THE HOLDING PERIOD IS A DISCLOSED REAL SUBSTITUTE FOR §35.1's OWN
CONVENTION, NOT THE CONVENTION ITSELF. §35.1: "Formation 30 September"
— an annual portfolio formed once a year and held to the next formation
date, which needs multiple YEARS of real price history to compute even
one real annual holding-period return per ticker, let alone the 156-week
rolling estimation window §35.3 asks for. This system's own real price
depth is ~1 year (`app.ingestion.company_price_history_loader`'s own
backfill). This module therefore uses the longest real trailing holding
period this system's own real data actually supports — `as_of` minus
`lookback_days` (default 365, clamped to whatever real depth exists) to
`as_of` — a real, disclosed substitute for the spec's own annual-
formation convention, not a silent stand-in presented as the real thing.
A single real cross-section like this is also NOT §35.3's own "156-week
rolling window, re-estimated weekly" — it's one real snapshot, useful for
seeing whether the construction and the real data behind it work end to
end, not yet a real factor RETURN SERIES a Carhart regression could use.

BOOK-TO-MARKET, NOT MARKET-TO-BOOK. `style_value` is `hard_book_value ÷
market_cap` — HIGHER means cheaper relative to hard book (a real "value"
stock in the Fama-French sense), matching §35.1's own B/M convention
(not the more commonly quoted P/B, its reciprocal).

A REAL TICKER IS INCLUDED ONLY WHEN ALL THREE REAL INPUTS EXIST FOR IT —
market cap, a real confirmed hard book figure, AND a real return over
the full window. `excluded` names every real ticker considered but left
out, and why, rather than silently shrinking the universe.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.market_cap_view import market_cap_for
from app.domain.portfolio_sort import MIN_TICKERS, SortConstituent, TwoByThreeSortResult, two_by_three_sort
from app.domain.price_returns import cumulative_adjusted_return
from app.domain.valuation_view import hard_book_for
from app.models.securities import Security

DEFAULT_LOOKBACK_DAYS = 365


@dataclass(frozen=True)
class HmlHardView:
    as_of: dt.date
    formation_date: dt.date
    included_ticker_count: int
    excluded: tuple[tuple[str, str], ...]
    """`(ticker, reason)` pairs — every real ticker considered but left
    out of the sort, named, not silently dropped."""

    result: TwoByThreeSortResult | None
    warnings: tuple[str, ...]


def hml_hard_for(
    db: Session, as_of: dt.date | None = None, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> HmlHardView:
    stamp = as_of or dt.date.today()
    formation = stamp - dt.timedelta(days=lookback_days)

    tickers = db.scalars(select(Security.ticker)).all()
    constituents: list[SortConstituent] = []
    excluded: list[tuple[str, str]] = []

    for ticker in tickers:
        cap = market_cap_for(db, ticker, stamp)
        if cap is None or cap <= 0:
            excluded.append((ticker, "no real market cap (needs both real shares_issued and a real price)"))
            continue

        hard_book_view = hard_book_for(db, ticker, stamp)
        if hard_book_view.result is None:
            excluded.append((ticker, "no real confirmed hard book value"))
            continue
        book_value = hard_book_view.result.hard_book_value
        if book_value <= 0:
            excluded.append((ticker, "hard book value is zero or negative — a real B/M ratio isn't meaningful"))
            continue

        period_return = cumulative_adjusted_return(db, ticker, formation, stamp)
        if period_return is None:
            excluded.append((ticker, "no real price on or before both the formation date and as_of"))
            continue

        style_value = book_value / cap
        constituents.append(
            SortConstituent(key=ticker, size_value=cap, style_value=style_value, period_return=period_return)
        )

    warnings: list[str] = []
    if len(constituents) < MIN_TICKERS:
        warnings.append(
            f"Only {len(constituents)} real tickers have all three real inputs (market cap, hard book, "
            f"a real return over the window) — below the {MIN_TICKERS} minimum the 2x3 sort needs to run."
        )
        return HmlHardView(
            as_of=stamp, formation_date=formation, included_ticker_count=len(constituents),
            excluded=tuple(excluded), result=None, warnings=tuple(warnings),
        )

    result = two_by_three_sort(constituents)
    if result is None:
        warnings.append(
            "The 2x3 sort itself could not produce a result on this real data (likely a real "
            "empty portfolio bucket — see app.domain.portfolio_sort's own docstring)."
        )

    return HmlHardView(
        as_of=stamp, formation_date=formation, included_ticker_count=len(constituents),
        excluded=tuple(excluded), result=result, warnings=tuple(warnings),
    )
