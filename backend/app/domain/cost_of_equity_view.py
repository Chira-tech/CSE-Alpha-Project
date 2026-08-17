"""
Bridges stored prices and macro series to `app.domain.beta` and
`app.domain.cost_of_equity` — the I/O layer those two pure modules
deliberately don't have.

Point-in-time note: this reads whatever `PriceDaily`/`macro_series` rows
exist up to `as_of` without an explicit `first_available_date` filter,
because both series are same-day-public end-of-session data (see
`market_internals.py`'s own docstring on this point) — there is no
restatement risk to guard against here the way there is for fundamentals.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.beta import BetaResult, PriceSeriesPoint, compute_dimson_beta
from app.domain.cost_of_equity import CostOfEquityInputs, CostOfEquityResult, compute_cost_of_equity
from app.domain.macro import SERIES_ASPI
from app.domain.macro_view import current_spread, risk_free_observation
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily

# 60 sessions, matching Gate 1's own window (§11.1) and §17.2's "45 of
# 60" liquidity threshold for when bottom-up beta should dominate.
BETA_WINDOW_SESSIONS = 60


def beta_for(db: Session, ticker: str, as_of: dt.date | None = None) -> BetaResult:
    stamp = as_of or dt.date.today()

    stock_rows = db.execute(
        select(PriceDaily.date, PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= stamp, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(BETA_WINDOW_SESSIONS)
    ).all()
    market_rows = db.execute(
        select(MacroSeries.obs_date, MacroSeries.value)
        .where(
            MacroSeries.series_id == SERIES_ASPI,
            MacroSeries.first_available_date <= stamp,
        )
        .order_by(MacroSeries.obs_date.desc())
        .limit(BETA_WINDOW_SESSIONS)
    ).all()

    stock_series = [PriceSeriesPoint(date=d, close=c) for d, c in stock_rows]
    market_series = [PriceSeriesPoint(date=d, close=v) for d, v in market_rows]

    return compute_dimson_beta(
        stock_series, market_series, sessions_traded_in_window=len(stock_rows)
    )


def cost_of_equity_for(db: Session, ticker: str, as_of: dt.date | None = None) -> CostOfEquityResult:
    stamp = as_of or dt.date.today()

    beta_result = beta_for(db, ticker, stamp)
    rf_observation = risk_free_observation(db, stamp)
    spread = current_spread(db, stamp)

    return compute_cost_of_equity(
        CostOfEquityInputs(
            risk_free_rate=rf_observation.value if rf_observation is not None else None,
            beta=beta_result.blume_adjusted_beta,
            erp_effective=settings.erp_effective_pct,
            implied_erp_cross_check=spread.spread if spread is not None else None,
        )
    )
