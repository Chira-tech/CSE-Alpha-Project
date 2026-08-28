"""
§36's Carhart certification, DB-wired — pulls one real ticker's weekly
returns, §35's five persisted factor series (`app.domain.factor_series_
view`), and the weekly risk-free rate, and regresses via `app.domain.
carhart_regression.fit_carhart_dimson`.

BOTH SIDES OF THE REGRESSION ARE EXCESS RETURNS, STANDARD CAPM/CARHART
CONVENTION. The persisted `"factor.mkt_rf"` series already IS the market
factor net of the risk-free rate (see `factor_series_view.rebuild_
factor_series`'s own construction: `mkt - rf`), so this module's own
`"MKT"` regressor input is that series directly, unchanged. The
dependent variable is built to match: `ticker_return[t] - rf[t]`, never
the raw ticker return. SMB/HML_hard/MOM/LIQ are already zero-cost,
self-financing long-short spreads and need no risk-free adjustment on
either side — the same convention `app.domain.factor_series`'s own
module docstring establishes for how they're built.

WEEKLY TICKER RETURNS AT THE SAME REAL FORMATION DATES §35's FACTOR
SERIES USES, NOT AN INDEPENDENTLY-CHOSEN CADENCE. Reads the real
`obs_date`s already stored for `SERIES_FACTOR_MKT_RF` (any one factor
series carries the same real weekly calendar every other one does — see
`rebuild_factor_series`'s own single shared `formation_dates` loop) and
computes this ticker's own real return between each consecutive pair via
`app.domain.price_returns.cumulative_adjusted_return` — the same
adjusted-close convention every other return calculation in this system
already uses.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.carhart_regression import DimsonFactorRegressionResult, fit_carhart_dimson, portfolio_beta_alert
from app.domain.factor_series import (
    ALL_FACTOR_SERIES_IDS,
    SERIES_FACTOR_HML_HARD,
    SERIES_FACTOR_LIQ,
    SERIES_FACTOR_MKT_RF,
    SERIES_FACTOR_MOM,
    SERIES_FACTOR_SMB,
)
from app.domain.factor_series_view import weekly_risk_free_rate
from app.domain.price_returns import cumulative_adjusted_return
from app.models.macro import MacroSeries

_SERIES_TO_FACTOR_NAME = {
    SERIES_FACTOR_MKT_RF: "MKT",
    SERIES_FACTOR_SMB: "SMB",
    SERIES_FACTOR_HML_HARD: "HML_hard",
    SERIES_FACTOR_MOM: "MOM",
    SERIES_FACTOR_LIQ: "LIQ",
}


@dataclass(frozen=True)
class CarhartCertificationView:
    ticker: str | None
    """`None` for a portfolio-level certification (see
    `portfolio_carhart_for`) rather than a single ticker."""
    as_of: dt.date
    regression: DimsonFactorRegressionResult
    portfolio_beta_alerts: tuple[str, ...]
    factor_series_available_weeks: int
    warnings: tuple[str, ...]


def _load_factor_series(db: Session, as_of: dt.date) -> dict[str, dict[dt.date, Decimal]]:
    rows = db.execute(
        select(MacroSeries.series_id, MacroSeries.obs_date, MacroSeries.value)
        .where(MacroSeries.series_id.in_(ALL_FACTOR_SERIES_IDS), MacroSeries.first_available_date <= as_of)
        .order_by(MacroSeries.series_id, MacroSeries.obs_date)
    ).all()
    result: dict[str, dict[dt.date, Decimal]] = {name: {} for name in _SERIES_TO_FACTOR_NAME.values()}
    for series_id, obs_date, value in rows:
        result[_SERIES_TO_FACTOR_NAME[series_id]][obs_date] = value
    return result


def _weekly_excess_returns_for_ticker(
    db: Session, ticker: str, formation_dates: list[dt.date]
) -> dict[dt.date, Decimal]:
    excess: dict[dt.date, Decimal] = {}
    for prev, curr in zip(formation_dates, formation_dates[1:]):
        r = cumulative_adjusted_return(db, ticker, prev, curr)
        rf = weekly_risk_free_rate(db, curr)
        if r is not None and rf is not None:
            excess[curr] = r - rf
    return excess


def carhart_certification_for(db: Session, ticker: str, as_of: dt.date | None = None) -> CarhartCertificationView:
    """§36 for one real ticker, over whatever real weekly window §35's
    persisted factor series and this ticker's own real price history
    both cover, up to `as_of`."""
    stamp = as_of or dt.date.today()
    factor_series = _load_factor_series(db, stamp)
    formation_dates = sorted(factor_series["MKT"].keys())

    warnings: list[str] = []
    if not formation_dates:
        warnings.append("no real §35 factor series available at all — run rebuild_factor_series first")

    excess_returns = _weekly_excess_returns_for_ticker(db, ticker, formation_dates)
    regression = fit_carhart_dimson(excess_returns, factor_series)
    alerts = portfolio_beta_alert(regression.betas) if not regression.insufficient_data else ()

    return CarhartCertificationView(
        ticker=ticker, as_of=stamp, regression=regression, portfolio_beta_alerts=alerts,
        factor_series_available_weeks=len(formation_dates), warnings=tuple(warnings),
    )


def portfolio_carhart_for(
    db: Session, holdings: list[tuple[str, Decimal]], as_of: dt.date | None = None
) -> CarhartCertificationView:
    """§36's own "run the same regression on your live portfolio's own
    return stream" — `holdings` is `[(ticker, weight), ...]`, weights
    need not sum to 1 (renormalized here); the portfolio's weekly excess
    return at each formation week is the weighted mean of each held
    ticker's own real excess return that week, using only tickers with a
    real return for that specific week (a ticker missing a week's real
    price is simply excluded from that week's weighted mean, not
    fabricated as zero)."""
    stamp = as_of or dt.date.today()
    factor_series = _load_factor_series(db, stamp)
    formation_dates = sorted(factor_series["MKT"].keys())

    weight_sum = sum((w for _, w in holdings), Decimal(0))
    warnings: list[str] = []
    if weight_sum <= 0:
        warnings.append("portfolio weights sum to zero or less — cannot build a weighted return")
        return CarhartCertificationView(
            ticker=None, as_of=stamp,
            regression=fit_carhart_dimson({}, factor_series), portfolio_beta_alerts=(),
            factor_series_available_weeks=len(formation_dates), warnings=tuple(warnings),
        )

    per_ticker_excess = {
        ticker: _weekly_excess_returns_for_ticker(db, ticker, formation_dates) for ticker, _w in holdings
    }
    portfolio_excess: dict[dt.date, Decimal] = {}
    for date in formation_dates[1:]:
        present = [(w, per_ticker_excess[t][date]) for t, w in holdings if date in per_ticker_excess[t]]
        if not present:
            continue
        present_weight = sum((w for w, _ in present), Decimal(0))
        if present_weight <= 0:
            continue
        portfolio_excess[date] = sum((w * r for w, r in present), Decimal(0)) / present_weight

    regression = fit_carhart_dimson(portfolio_excess, factor_series)
    alerts = portfolio_beta_alert(regression.betas) if not regression.insufficient_data else ()
    return CarhartCertificationView(
        ticker=None, as_of=stamp, regression=regression, portfolio_beta_alerts=alerts,
        factor_series_available_weeks=len(formation_dates), warnings=tuple(warnings),
    )
