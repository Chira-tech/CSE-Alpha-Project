"""
§35.1's factor construction, the pure arithmetic half — series-id
constants for where these live in `macro_series` (see `app.domain.
factor_series_view` for the DB-wired weekly builder that actually
populates them) plus the two pieces `app.domain.portfolio_sort.
two_by_three_sort` doesn't already give for free.

WHY SMB/HML_hard/MOM/LIQ NEED NO NEW SORT LOGIC HERE. `two_by_three_sort`
already IS the Fama-French 2x3 construction — feed it
`(size_value, style_value, period_return)` per ticker for one formation
week and it returns the fully-computed size- and style-shaped factor
returns. SMB, HML_hard, MOM and LIQ are that same sort, given a
different `style_value` per ticker per week (book-to-market for HML_hard,
prior-return for MOM, Amihud illiquidity for LIQ) — see `app.domain.
factor_series_view` for exactly how each `style_value` gets built from
real per-ticker data. This module holds only what's genuinely new:
MKT-RF (a value-weighted average, not a sort at all) and MOM's own
style-value construction (the "skip the most recent month" windowing
§35.1 specifies, which is unique to momentum among the four sorted
factors).

MOM'S WEEKLY-CADENCE SUBSTITUTION FOR "SKIP THE MOST RECENT MONTH",
DISCLOSED. §35.1: "prior 12-month return skipping the most recent
month (t-12 to t-2)." This system's factor series is built on a WEEKLY
formation cadence (see factor_series_view's own docstring for why:
that's the finest grain ~163 real weeks of price history can support a
meaningful re-estimation over). `skip_weeks=4` / `lookback_weeks=52` is
a disclosed weeks-for-months substitution, not calendar-month
arithmetic — the same kind of real, named substitution `app.domain.
factor_library_view.hml_hard_for` already makes for its own formation
convention.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

#: Where each factor's weekly return series lives in `macro_series`.
SERIES_FACTOR_MKT_RF = "factor.mkt_rf"
SERIES_FACTOR_SMB = "factor.smb"
SERIES_FACTOR_HML_HARD = "factor.hml_hard"
SERIES_FACTOR_MOM = "factor.mom"
SERIES_FACTOR_LIQ = "factor.liq"

ALL_FACTOR_SERIES_IDS: tuple[str, ...] = (
    SERIES_FACTOR_MKT_RF, SERIES_FACTOR_SMB, SERIES_FACTOR_HML_HARD, SERIES_FACTOR_MOM, SERIES_FACTOR_LIQ,
)

#: Reuses `app.domain.portfolio_sort.MIN_TICKERS`'s own floor and
#: reasoning — MKT-RF isn't a 2x3 sort, but a value-weighted average of
#: too few real constituents is exactly the same kind of thin-data
#: number that floor exists to refuse.
MIN_TICKERS_FOR_MKT = 12

MOM_SKIP_WEEKS_DEFAULT = 4
MOM_LOOKBACK_WEEKS_DEFAULT = 52


@dataclass(frozen=True)
class MarketWeightedInput:
    ticker: str
    market_cap: Decimal
    period_return: Decimal


def value_weighted_return(constituents: list[MarketWeightedInput]) -> Decimal | None:
    """MKT for one formation period — free-float(-proxy) value-weighted
    average return of the investable universe. Returns MKT, not MKT-RF;
    the caller subtracts that period's risk-free rate (see
    `factor_series_view.rebuild_factor_series`).

    `None` — never a number from too little or too degenerate real data
    — below `MIN_TICKERS_FOR_MKT`, or when total market cap is not
    strictly positive (a real cap of zero/negative is a data error, not
    something to divide by)."""
    if len(constituents) < MIN_TICKERS_FOR_MKT:
        return None
    total_cap = sum((c.market_cap for c in constituents), Decimal(0))
    if total_cap <= 0:
        return None
    return sum((c.market_cap * c.period_return for c in constituents), Decimal(0)) / total_cap


def _most_recent_on_or_before(
    closes: list[tuple[dt.date, Decimal]], as_of: dt.date
) -> tuple[dt.date, Decimal] | None:
    """`closes` must be sorted ascending by date. Same "most recent real
    observation on or before this date" convention `app.domain.
    price_returns.cumulative_adjusted_return` uses — restated here as a
    pure, DB-free helper since this module never touches the database
    (the caller is responsible for supplying an already-sorted, already
    bulk-loaded series; see `factor_series_view`)."""
    dates = [d for d, _ in closes]
    idx = bisect.bisect_right(dates, as_of) - 1
    if idx < 0:
        return None
    return closes[idx]


def mom_style_value(
    closes: list[tuple[dt.date, Decimal]],
    as_of: dt.date,
    *,
    skip_weeks: int = MOM_SKIP_WEEKS_DEFAULT,
    lookback_weeks: int = MOM_LOOKBACK_WEEKS_DEFAULT,
) -> Decimal | None:
    """§35.1's MOM style-value for one ticker at one formation date:
    cumulative return from `as_of - lookback_weeks` to `as_of -
    skip_weeks` — i.e. the most recent `skip_weeks` are deliberately
    excluded, the momentum literature's own short-term-reversal guard
    (see §37's own REV_1M signal, which exists precisely because that
    most-recent window behaves oppositely to the momentum window it's
    excluded from here).

    `closes` is one ticker's own sorted `(date, adjusted_close)` series
    — `adjusted_close` already includes `adj_factor`, matching every
    other return calculation in this codebase. `None` when either
    endpoint has no real observation on or before it, or when the start
    close is not strictly positive."""
    end_date = as_of - dt.timedelta(weeks=skip_weeks)
    start_date = as_of - dt.timedelta(weeks=lookback_weeks)

    start = _most_recent_on_or_before(closes, start_date)
    end = _most_recent_on_or_before(closes, end_date)
    if start is None or end is None:
        return None
    _, start_close = start
    _, end_close = end
    if start_close <= 0:
        return None
    return (end_close / start_close) - 1
