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
import statistics
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.liquidity import amihud_illiquidity_ratio, percentile_rank
from app.domain.price_returns import ticker_adjusted_returns
from app.models.prices import PriceDaily
from app.models.securities import Security

DEFAULT_LOOKBACK_DAYS = 400
GATE1_WINDOW_SESSIONS = 60
"""§11.1 Gate 1's own window — matches `Gate1Inputs.median_daily_
turnover_60d_lkr`/`days_traded_last_60`'s naming, but as real TRADING
SESSIONS, not calendar days. A REAL bug in this module's own first
version, found live (30 Aug 2026) applying this exact liquidity gate to
the real dev universe: treating "60" as 60 CALENDAR days made
`days_traded_last_60 >= 45` mathematically impossible for any real
5-day-trading-week stock to ever clear — a 60-calendar-day span
contains at most ~43 weekdays before subtracting a single holiday, so
EVERY real ticker failed, including SAMP.N0000 and JKH.N0000, the
exchange's own two most liquid names (turnover in the tens of millions
of rupees a day). "60d" in standard equity-liquidity usage (a "50-day
moving average" means 50 TRADING days, universally) means the last 60
real sessions the stock traded ON, not 60 calendar days regardless of
weekends — corrected here to count backward through real stored
sessions instead of a calendar cutoff."""

STALE_HISTORY_CUTOFF_DAYS = 180
"""A real, disclosed outer bound on `liquidity_snapshot_for`'s own
session-counting fix above: without SOME calendar bound, a ticker that
stopped trading entirely 2 years ago would still report its old
sessions as "the last 60," reading as currently liquid when it is
anything but. Six months is generous relative to Gate 1's own ~60-
session/~3-month target window — long enough that a stock genuinely
still trading normally is never caught by it, short enough that a
stock that has gone quiet is not read as liquid from stale history."""


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


@dataclass(frozen=True)
class LiquiditySnapshot:
    median_daily_turnover_60d_lkr: Decimal
    """Median of REAL raw turnover (close x volume) over the real
    TRADED sessions among the trailing `GATE1_WINDOW_SESSIONS` real
    session ROWS on file (not a calendar-day cutoff — see that
    constant's own docstring for why) — §11.1 Gate 1's own named input.
    A session with no real trading at all (volume 0) is not counted as
    a zero-turnover session; it simply isn't in the sample, the same
    "real data only, never a synthetic zero" discipline this project
    applies everywhere else — a company that trades rarely should show
    a small SAMPLE, not a median dragged toward zero by manufactured
    non-trading sessions."""

    days_traded_60d: int
    """Real sessions with volume > 0 among the same trailing
    `GATE1_WINDOW_SESSIONS` real session rows — the actual §11.1 Gate 1
    fact this represents ("traded 6 of the last 60 real sessions")."""

    days_of_real_history_available: int
    """How many real session ROWS this ticker actually has on file
    (on or before `as_of`), capped at `GATE1_WINDOW_SESSIONS` — NOT
    assumed to always equal the full window. A ticker with 20 real
    session rows on file (a genuinely recent listing, or a system whose
    own forward capture hasn't run long enough yet) reports 20 here,
    never a manufactured 60 — a caller (`app.domain.coverage_gates.
    gate1_liquidity_reason`) needs this figure to tell "this stock
    genuinely doesn't trade often" apart from "not enough real sessions
    exist yet to judge that"."""


def liquidity_snapshot_for(
    db: Session, ticker: str, as_of: dt.date, *, window_sessions: int = GATE1_WINDOW_SESSIONS
) -> LiquiditySnapshot:
    """Never `None` — a ticker with zero real session rows on file gets
    the real, honest `(0, 0, 0)` snapshot rather than an absence a
    caller would have to special-case. `(0, 0)` fails §11.1 Gate 1's own
    thresholds exactly the same way a thin-but-nonzero snapshot does,
    through the same comparison, which is the correct, uniform
    treatment — a stock that never traded is not a special case of
    illiquidity, it is the most extreme real case of it.

    Windowed by real SESSION ROWS, not a calendar-day cutoff — see
    `GATE1_WINDOW_SESSIONS`'s own docstring for the real bug this
    closes (a 60-CALENDAR-day window can never contain 45 real trading
    days for a normal 5-day week, so every real ticker failed the
    days-traded check unconditionally under the first version of this
    function). Also bounded by `STALE_HISTORY_CUTOFF_DAYS`: a ticker
    whose real sessions are all older than that is not "liquid based on
    history," it has gone quiet — resurrecting six-month-old trading as
    "current" liquidity would be a different, real mistake in the other
    direction from the calendar-day bug this function already fixes."""
    rows = db.scalars(
        select(PriceDaily)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date <= as_of,
            PriceDaily.date >= as_of - dt.timedelta(days=STALE_HISTORY_CUTOFF_DAYS),
            PriceDaily.close.is_not(None),
        )
        .order_by(PriceDaily.date.desc())
        .limit(window_sessions)
    ).all()
    days_available = len(rows)

    traded_rows = [r for r in rows if r.volume and r.volume > 0]
    if not traded_rows:
        return LiquiditySnapshot(
            median_daily_turnover_60d_lkr=Decimal(0), days_traded_60d=0,
            days_of_real_history_available=days_available,
        )
    turnovers = [row.close * row.volume for row in traded_rows]
    return LiquiditySnapshot(
        median_daily_turnover_60d_lkr=Decimal(str(statistics.median(turnovers))),
        days_traded_60d=len(traded_rows),
        days_of_real_history_available=days_available,
    )


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
    db: Session,
    ticker: str,
    as_of: dt.date | None = None,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    universe_ratios: dict[str, Decimal] | None = None,
    universe_percentiles: dict[str, Decimal] | None = None,
) -> Decimal | None:
    """This ticker's own real liquidity percentile within the real
    universe (0-100, HIGHER = MORE liquid — see `app.domain.liquidity`'s
    own docstring). `None` when this ticker itself doesn't have enough
    real data to rank, regardless of how many other tickers do.

    `universe_ratios` — the caller's job to supply, not this function's
    to fetch, exactly the same convention `app.domain.cost_of_equity_
    view.cost_of_equity_for`'s own `regime` parameter already
    established for the identical reason: `universe_amihud_ratios`
    scans every real ticker's full real price history and is market-
    wide, not company-specific — identical across every call within one
    valuation run. A real profiling run (18 Aug 2026) found this
    function recomputing it from scratch 6 times over inside a single
    `app.domain.valuation_view.valuation_summary_for` call, and 54 times
    across one 9-position real portfolio view — over 89 seconds total
    for what should be one real computation. Defaults to `None` (compute
    fresh) so every existing caller that doesn't pass one keeps its
    exact prior behaviour.

    `universe_percentiles` — A SECOND, SEPARATE REAL BUG THE FIRST FIX
    DIDN'T CLOSE, FOUND LIVE (20 Aug 2026): sharing `universe_ratios`
    stopped `universe_amihud_ratios` itself from being recomputed, but
    every call here still ran `percentile_rank(ratios)` — an O(n²) full
    universe-wide RE-RANKING — from scratch every time, on the exact same
    `ratios` dict. Profiled live: 1,526 calls in one `/opportunities`
    request (6 per ticker × 254 confirmed tickers), 61+ million inner
    comparisons, ~24 of the endpoint's ~25 real seconds. `percentile_rank`
    is a pure function of `ratios` alone — identical across every one of
    those 1,526 calls — so the fix is the same shape as `universe_ratios`
    itself: the caller computes `percentile_rank` ONCE and threads the
    RESULT through here, skipping the O(n²) work entirely when supplied.
    Defaults to `None` (compute fresh) so every existing caller that
    doesn't pass one keeps its exact prior behaviour."""
    stamp = as_of or dt.date.today()
    if universe_percentiles is not None:
        return universe_percentiles.get(ticker)
    ratios = universe_ratios if universe_ratios is not None else universe_amihud_ratios(db, stamp, lookback_days)
    return percentile_rank(ratios).get(ticker)
