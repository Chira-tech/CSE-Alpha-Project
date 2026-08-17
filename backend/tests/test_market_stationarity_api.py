"""GET /market/stationarity — API-layer wiring for §30 step 1."""
from __future__ import annotations


def test_no_data_returns_200_with_honest_nulls(client):
    r = client.get("/market/stationarity", params={"series_id": "cbsl.tbill_364d"})
    assert r.status_code == 200
    body = r.json()
    assert body["observation_count"] == 0
    assert body["adf"] is None
    assert body["consensus"] is None
    assert len(body["warnings"]) == 1
