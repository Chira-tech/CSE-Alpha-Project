"""
Bridges stored `securities`/`prices_daily`/`macro_series` rows to
`app.domain.sector_sensitivity` — the I/O layer that module deliberately
doesn't have, the same split every other `_view.py` in this system draws.

SECTOR GROUPING USES `Security.cse_sector`, NOT `gics_sector`. §33's own
illustrative table uses CSE-native industry-group names ("Banks",
"Non-bank finance", "Diversified holdings", "Hotels & travel") — the
finer `cse_sector` level `app.domain.gics` already derives the coarser
11-sector `gics_sector` FROM, not the coarse level itself. Grouping by
the 11 GICS sectors would blend, for example, banks and insurers into
one "Financials" row, exactly the kind of loss of resolution §33's own
table structure argues against.

SECTOR RETURNS ARE EQUAL-WEIGHTED, ON ADJUSTED PRICES. `PriceDaily.
adj_factor` is the cumulative total-return adjustment factor `app.
domain.corporate_actions.build_adjustment_factor_series` computes — a
raw close-to-close return series would be contaminated by unadjusted
dividends, bonus issues and splits, exactly the "adjusted total return"
distinction that module's own docstring exists to draw. Equal-weighted,
not market-cap-weighted, because this system has no live market-cap
series stored per company per day (only `FloatData`'s point-in-time
share count, not a daily series) to weight by — a real, disclosed
simplification, not something dressed up as market-cap-weighted.

THE FOUR REAL MACRO SHOCK SERIES. See `app.domain.sector_sensitivity`'s
own docstring for why only these four and not §33's full illustrative
set: policy rate CHANGE, 364-day T-bill yield CHANGE, CCPI y/y CHANGE
(each a step-function series — the shock is the day-of-change value,
present only on days the series actually moved, per `app.domain.
sector_sensitivity.MacroShockSeries`'s own "absent, not zero" rule) and
LKR/USD daily % change (a continuous series, so every day it has an
observation counts as a real, if often tiny, shock).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cbsl_parsing import (
    SERIES_CCPI_YOY,
    SERIES_POLICY_RATE,
    SERIES_TBILL_364D,
    SERIES_USD_LKR_BUY,
)
from app.domain.macro_view import series_history
from app.domain.sector_sensitivity import (
    MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE,
    MacroShockSeries,
    SectorReturns,
    SectorSensitivityRow,
    compute_sector_sensitivity_matrix,
)
from app.models.prices import PriceDaily
from app.models.securities import Security

#: How far back to look for sector/shock history — comfortably covers
#: the ~1 year `app.ingestion.company_price_history_loader` and `app.
#: ingestion.index_history_loader` backfill, with headroom rather than
#: cutting exactly at the boundary (same convention `app.domain.
#: macro_engine_view._aspi_log_returns` already uses).
DEFAULT_LOOKBACK_DAYS = 400


def _sector_groups(db: Session) -> dict[str, list[str]]:
    """Every ticker with a real `cse_sector` assigned, grouped. Not
    point-in-time filtered — sector classification is a slow-moving
    descriptive field on `Security`, not a versioned time series the way
    `Fundamental`/`CorporateAction` rows are, so there is no "as of"
    distinction to draw here that the underlying data actually supports."""
    rows = db.scalars(
        select(Security).where(Security.cse_sector.is_not(None))
    ).all()
    groups: dict[str, list[str]] = {}
    for row in rows:
        groups.setdefault(row.cse_sector, []).append(row.ticker)
    return groups


def _ticker_adjusted_returns(
    db: Session, ticker: str, as_of: dt.date, lookback_days: int
) -> dict[dt.date, Decimal]:
    """Real daily total-return series for one ticker, from adjusted
    closes (`close × adj_factor`) — see module docstring for why
    adjusted, not raw."""
    start = as_of - dt.timedelta(days=lookback_days)
    rows = db.scalars(
        select(PriceDaily)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date >= start,
            PriceDaily.date <= as_of,
            PriceDaily.close.is_not(None),
        )
        .order_by(PriceDaily.date)
    ).all()
    returns: dict[dt.date, Decimal] = {}
    prev_adj: Decimal | None = None
    for row in rows:
        adj = row.close * row.adj_factor
        if prev_adj is not None and prev_adj > 0:
            returns[row.date] = (adj - prev_adj) / prev_adj
        prev_adj = adj
    return returns


def sector_returns_for(
    db: Session, sector: str, tickers: list[str], as_of: dt.date, lookback_days: int
) -> SectorReturns:
    """Equal-weighted daily sector return — the mean of whichever
    constituents actually have a real return on a given date, not
    requiring every constituent to have traded that day (a thinly-traded
    small cap missing one day should not blank out the whole sector's
    reading for that day)."""
    per_ticker = [_ticker_adjusted_returns(db, t, as_of, lookback_days) for t in tickers]
    all_dates = sorted({d for series in per_ticker for d in series})
    returns_by_date: dict[dt.date, Decimal] = {}
    for date in all_dates:
        values = [series[date] for series in per_ticker if date in series]
        if values:
            returns_by_date[date] = sum(values, Decimal(0)) / Decimal(len(values))
    return SectorReturns(
        sector=sector, constituent_count=len(tickers), returns_by_date=returns_by_date
    )


def _step_function_shock(db: Session, series_id: str, name: str, as_of: dt.date) -> MacroShockSeries:
    """A real macro series' day-of-CHANGE values — the shock is present
    only on the date a new observation actually landed, per `app.domain.
    sector_sensitivity.MacroShockSeries`'s own "absent, not zero" rule."""
    rows = series_history(db, series_id, as_of, limit=500)
    values: dict[dt.date, Decimal] = {}
    for prev, curr in zip(rows, rows[1:]):
        values[curr.obs_date] = curr.value - prev.value
    return MacroShockSeries(name=name, values_by_date=values)


def _pct_change_shock(db: Session, series_id: str, name: str, as_of: dt.date) -> MacroShockSeries:
    rows = series_history(db, series_id, as_of, limit=500)
    values: dict[dt.date, Decimal] = {}
    for prev, curr in zip(rows, rows[1:]):
        if prev.value != 0:
            values[curr.obs_date] = (curr.value - prev.value) / prev.value
    return MacroShockSeries(name=name, values_by_date=values)


def real_macro_shocks(db: Session, as_of: dt.date) -> list[MacroShockSeries]:
    """The four real shock series this system can build today — see
    module docstring for exactly which and why not more."""
    return [
        _step_function_shock(db, SERIES_POLICY_RATE, "Policy rate change", as_of),
        _step_function_shock(db, SERIES_TBILL_364D, "364-day T-bill yield change", as_of),
        _step_function_shock(db, SERIES_CCPI_YOY, "CCPI y/y change", as_of),
        _pct_change_shock(db, SERIES_USD_LKR_BUY, "LKR/USD % change", as_of),
    ]


@dataclass(frozen=True)
class SectorSensitivityView:
    as_of: dt.date
    rows: tuple[SectorSensitivityRow, ...]
    thin_sectors: tuple[tuple[str, int], ...]
    """Sectors real enough to have a `cse_sector` assignment but with
    fewer than `app.domain.sector_sensitivity.MIN_CONSTITUENTS_FOR_
    SECTOR_ESTIMATE` real tickers — named here, not silently dropped,
    the `(sector, constituent_count)` pairs a caller needs to explain
    why a sector is missing from `rows`."""

    shocks_used: tuple[str, ...]
    warnings: tuple[str, ...]


def sector_sensitivity_matrix_for(
    db: Session, as_of: dt.date | None = None, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> SectorSensitivityView:
    """§33's matrix, live — real sector return series regressed on real
    macro shock series, per `app.domain.sector_sensitivity`'s own rules.
    Never hard-codes a relationship (§33's own explicit warning) and
    never fabricates a shock this system doesn't actually track (see
    that module's own docstring for the four it does)."""
    stamp = as_of or dt.date.today()
    groups = _sector_groups(db)

    sector_returns: list[SectorReturns] = []
    thin_sectors: list[tuple[str, int]] = []
    for sector, tickers in sorted(groups.items()):
        if len(tickers) < MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE:
            thin_sectors.append((sector, len(tickers)))
            continue
        sector_returns.append(sector_returns_for(db, sector, tickers, stamp, lookback_days))

    shocks = real_macro_shocks(db, stamp)
    rows = compute_sector_sensitivity_matrix(sector_returns, shocks)

    warnings: list[str] = []
    if not groups:
        warnings.append("No securities have a cse_sector assignment at all.")
    if not rows:
        warnings.append(
            "No sector produced any estimate — either no sector has enough real "
            "constituents/price history, or no macro shock had enough overlapping history."
        )
    warnings.append(
        "Only 4 of §33's illustrative shock columns are built (policy rate, T-bill yield, "
        "CCPI, LKR/USD) — Oil, Tourism and Fiscal expansion have no ingested source anywhere "
        "in this system."
    )

    return SectorSensitivityView(
        as_of=stamp,
        rows=tuple(rows),
        thin_sectors=tuple(thin_sectors),
        shocks_used=tuple(s.name for s in shocks),
        warnings=tuple(warnings),
    )
