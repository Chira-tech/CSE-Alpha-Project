"""POST/GET /decisions, POST /decisions/{id}/outcomes — API-layer
wiring for the real §45 decision record."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)


def _seed_priceable_ticker(db, ticker="COMB.N0000", price=Decimal(12)):
    db.add(Security(ticker=ticker, name="Commercial Bank of Ceylon PLC", archetype="bank"))
    db.add_all(
        [
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100))
    db.add(
        PriceDaily(
            ticker=ticker, date=dt.date.today(), close=price, adj_factor=Decimal(1),
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()


def _fake_ke(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
    return CostOfEquityResult(
        ke=Decimal("0.15"), risk_free_rate=Decimal("0.12"), beta=Decimal("1.0"),
        erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
        illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
        missing_components=(), note="stub",
    )


def test_empty_list_before_any_decision(client):
    r = client.get("/decisions")
    assert r.status_code == 200
    assert r.json() == []


def test_record_a_real_decision_freezes_real_state(client, db_session, monkeypatch):
    _seed_priceable_ticker(db_session)
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)

    r = client.post(
        "/decisions",
        json={
            "ticker": "COMB.N0000", "action": "buy",
            "reasoning_text": "Trading well below blended fair value.",
            "conviction_1_5": 4, "falsification_text": "ROE falls below 12%.",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["ticker"] == "COMB.N0000"
    assert body["action"] == "buy"
    assert Decimal(body["market_price_at_decision"]) == Decimal(12)
    assert Decimal(body["fv_blended"]) is not None
    assert body["fundamental_score"] is None  # not built yet — honestly absent, not zero
    assert body["outcome"] is None

    listed = client.get("/decisions").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_record_a_real_outcome_computes_net_return(client, db_session, monkeypatch):
    _seed_priceable_ticker(db_session, price=Decimal(10))
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)

    created = client.post(
        "/decisions",
        json={"ticker": "COMB.N0000", "action": "buy", "reasoning_text": "Cheap."},
    ).json()

    r = client.post(
        f"/decisions/{created['id']}/outcomes",
        json={"exit_date": str(dt.date.today()), "exit_price": "12", "exit_trigger": "hit target"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["outcome"] is not None
    assert Decimal(body["outcome"]["gross_return"]) == Decimal("0.2")


def test_a_second_outcome_on_the_same_decision_is_rejected(client, db_session, monkeypatch):
    _seed_priceable_ticker(db_session)
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)
    created = client.post(
        "/decisions", json={"ticker": "COMB.N0000", "action": "buy", "reasoning_text": "Cheap."}
    ).json()
    client.post(
        f"/decisions/{created['id']}/outcomes",
        json={"exit_date": str(dt.date.today()), "exit_price": "13", "exit_trigger": "trim"},
    )
    r = client.post(
        f"/decisions/{created['id']}/outcomes",
        json={"exit_date": str(dt.date.today()), "exit_price": "14", "exit_trigger": "exit"},
    )
    assert r.status_code == 409


def test_unknown_decision_id_gives_404(client):
    assert client.get("/decisions/999").status_code == 404
    r = client.post(
        "/decisions/999/outcomes",
        json={"exit_date": str(dt.date.today()), "exit_price": "1", "exit_trigger": "x"},
    )
    assert r.status_code == 404
