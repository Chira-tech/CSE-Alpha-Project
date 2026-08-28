"""GET /market/sector/{sector} — R1 T4.6.4's drill-down. Same reasoning
as test_market_sector_sensitivity_api.py: a Pydantic-serialization test
at the API boundary, not a re-test of `sector_drilldown_view`'s own
logic (see `test_sector_drilldown_view.py` for that)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.float_data import FloatData
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 20)


def test_unknown_sector_returns_404(client):
    r = client.get("/market/sector/Nonexistent%20Sector")
    assert r.status_code == 404


def test_known_sector_returns_real_companies_and_discloses_the_omitted_composite_score(client, db_session):
    db_session.add(Security(ticker="A.N0000", name="A PLC", cse_sector="Banks"))
    db_session.add(FloatData(ticker="A.N0000", as_of=AS_OF, shares_issued=1000))
    db_session.add(PriceDaily(ticker="A.N0000", date=AS_OF, close=Decimal("10.00"), fetched_at=dt.datetime(2026, 8, 20, 10, 0)))
    db_session.commit()

    r = client.get("/market/sector/Banks")
    assert r.status_code == 200
    body = r.json()
    assert body["sector"] == "Banks"
    assert len(body["companies"]) == 1
    assert body["companies"][0]["ticker"] == "A.N0000"
    assert Decimal(body["companies"][0]["market_cap"]) == Decimal("10000.00")
    assert "composite score" in body["composite_score_omitted_reason"].lower()
