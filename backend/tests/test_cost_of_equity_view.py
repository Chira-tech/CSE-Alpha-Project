"""§17.2 wired to real stored data — app.domain.cost_of_equity_view.
Exists specifically to cover `cost_of_equity_for`'s new `regime`
parameter (17 Aug) through the REAL function, not the monkeypatched
stand-in `test_valuation_view.py` uses everywhere else — a stub can't
catch a bug in the actual wiring between `regime_erp_adjustment` and
`erp_effective`.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.macro import SERIES_ASPI, SERIES_TBILL_364D
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 6, 1)


def _seed_minimal_ke_inputs(db, ticker="COMB.N0000"):
    """30 sessions of correlated stock/ASPI closes (the real minimum
    `app.domain.beta.MIN_OBSERVATIONS` needs) plus one real-shaped
    T-bill observation — the smallest real dataset `cost_of_equity_for`
    can compute a non-None Ke from."""
    db.add(Security(ticker=ticker, name="Test Bank PLC"))
    now = dt.datetime.now(dt.timezone.utc)
    base = dt.date(2026, 4, 1)
    stock_price = Decimal(100)
    aspi = Decimal(10000)
    # `app.domain.beta.compute_dimson_beta` returns None for a market
    # return series with zero variance (a singular regression) — real
    # noise, not a flat compounding rate, is needed for a real fit.
    rng = random.Random(17)
    for i in range(35):
        d = base + dt.timedelta(days=i)
        stock_price = stock_price * Decimal(str(1 + rng.gauss(0.001, 0.01)))
        aspi = aspi * Decimal(str(1 + rng.gauss(0.0008, 0.008)))
        db.add(
            PriceDaily(ticker=ticker, date=d, close=stock_price, adj_factor=Decimal(1), fetched_at=now)
        )
        db.add(
            MacroSeries(
                series_id=SERIES_ASPI, obs_date=d, first_available_date=d, value=aspi, source="cse.lk",
            )
        )
    db.add(
        MacroSeries(
            series_id=SERIES_TBILL_364D, obs_date=base, first_available_date=base,
            value=Decimal("0.1001"), source="cbsl",
        )
    )
    db.commit()


def test_no_regime_matches_prior_default_behaviour(db_session):
    _seed_minimal_ke_inputs(db_session)
    result = cost_of_equity_for(db_session, "COMB.N0000", AS_OF)
    assert result.ke is not None
    from app.config import settings

    assert result.erp_effective == settings.erp_effective_pct


def test_risk_off_regime_raises_erp_and_therefore_ke(db_session):
    _seed_minimal_ke_inputs(db_session)
    baseline = cost_of_equity_for(db_session, "COMB.N0000", AS_OF, regime=None)
    risk_off = cost_of_equity_for(db_session, "COMB.N0000", AS_OF, regime="risk_off")

    assert baseline.ke is not None and risk_off.ke is not None
    assert risk_off.erp_effective == baseline.erp_effective + Decimal("0.12")
    # §17.2: "When the regime flips toward Risk-Off, Ke rises... every
    # fair value in the system falls automatically" — checked directly.
    assert risk_off.ke > baseline.ke


def test_risk_on_regime_matches_no_regime(db_session):
    """risk_on's own regime add is 0 — a risk_on read should produce
    the identical Ke a `None` read does, not a different-but-coincidentally-
    equal number."""
    _seed_minimal_ke_inputs(db_session)
    baseline = cost_of_equity_for(db_session, "COMB.N0000", AS_OF, regime=None)
    risk_on = cost_of_equity_for(db_session, "COMB.N0000", AS_OF, regime="risk_on")
    assert risk_on.ke == baseline.ke
    assert risk_on.erp_effective == baseline.erp_effective
