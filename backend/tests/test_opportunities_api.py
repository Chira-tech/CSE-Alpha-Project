"""GET /opportunities — API-layer wiring for the real opportunity
ranking view. Same reasoning as every other API test in this system:
catches a Pydantic-serialization bug at the domain-to-API boundary.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.cost_of_equity import CostOfEquityResult
from app.domain import valuation_view
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)


def test_empty_universe_gives_empty_lists_not_an_error(client):
    r = client.get("/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert body["ranked"] == []
    assert body["excluded"] == []


def test_a_confirmed_ticker_with_a_computable_ladder_is_ranked(client, db_session, monkeypatch):
    db_session.add(Security(ticker="COMB.N0000", name="Commercial Bank of Ceylon PLC", archetype="bank"))
    db_session.add_all(
        [
            Fundamental(
                ticker="COMB.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker="COMB.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db_session.add(FloatData(ticker="COMB.N0000", as_of=dt.date(2022, 1, 1), shares_issued=100))
    db_session.add(
        PriceDaily(
            ticker="COMB.N0000", date=dt.date.today(), close=Decimal(12), adj_factor=Decimal(1),
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()

    def _fake_ke(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=Decimal("0.15"), risk_free_rate=Decimal("0.12"), beta=Decimal("1.0"),
            erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
            illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
            missing_components=(), note="stub",
        )

    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)

    r = client.get("/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert len(body["ranked"]) == 1
    candidate = body["ranked"][0]
    assert candidate["ticker"] == "COMB.N0000"
    assert candidate["price_ladder_zone"] == "strong_accumulate"
    assert Decimal(candidate["gap_to_buy_below_pct"]) is not None
    assert body["excluded"] == []
