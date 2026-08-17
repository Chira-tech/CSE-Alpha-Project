"""GET /market/sector-sensitivity — API-layer wiring for §33's matrix.
Same reasoning as test_valuation_api.py: catches a Pydantic-serialization
bug at the domain-to-API boundary that a purely domain-level test can't
see. `thin_sectors: list[list[object]]` in particular is an unusual
enough Pydantic shape to be worth a direct check, not just an assumption.
"""
from __future__ import annotations

from app.models.securities import Security


def test_no_sectors_returns_200_with_honest_empty_state(client):
    r = client.get("/market/sector-sensitivity")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["thin_sectors"] == []
    assert len(body["shocks_used"]) == 4
    assert any("No securities have a cse_sector" in w for w in body["warnings"])


def test_thin_sector_reported_with_correct_shape(client, db_session):
    db_session.add(Security(ticker="A.N0000", name="A PLC", cse_sector="Banks"))
    db_session.add(Security(ticker="B.N0000", name="B PLC", cse_sector="Banks"))
    db_session.commit()

    r = client.get("/market/sector-sensitivity")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["thin_sectors"] == [["Banks", 2]]
