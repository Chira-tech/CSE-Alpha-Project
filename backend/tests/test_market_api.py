"""
Market overview endpoint.

The behaviour that matters most here isn't the happy path — it's that one
failing upstream call degrades ONE section rather than killing the whole
screen (UI spec §15.1's Partial state), because the CSE API is unofficial
and fails in assorted ways.
"""
from __future__ import annotations

import httpx
import pytest
import respx

import app.api.routes.market as market_module
from app.config import settings

BASE = "https://www.cse.lk/api"

ASPI_PAYLOAD = {
    "id": 36972259,
    "value": 21623.17,
    "lowValue": 21539.0,
    "highValue": 21675.45,
    "change": 84.17,
    "percentage": 0.3907795162263801,
    "timestamp": 1786699620393,
}

SECTORS_PAYLOAD = [
    {
        "sectorId": 223,
        "symbol": "EGY",
        "name": "Energy",
        "indexName": "S&P/CSE Energy Industry Group Index",
        "indexValue": 2843.96,
        "change": -3.6,
        "percentage": -0.126,
        "sectorTurnoverToday": 4999126,
    },
    {
        "sectorId": 224,
        "symbol": "MAT",
        "name": "Materials",
        "indexValue": 3036.67,
        "change": -10.69,
        "percentage": -0.35,
        "sectorTurnoverToday": 126025090.6,
    },
]


@pytest.fixture(autouse=True)
def _clear_cache_and_speed_up(monkeypatch):
    """Production settings that are correct but hostile to a test suite:
    a 60s response cache (makes tests order-dependent), >=2s pacing
    between calls, and up to 4 retries with exponential backoff on a 5xx.
    Left alone, the failure-path tests take over a minute. Reset the
    cache and collapse pacing/retries per test — the retry behaviour
    itself is covered in test_cse_client.py, not here."""
    market_module._cache = None
    monkeypatch.setattr(settings, "cse_min_seconds_between_calls", 0.0)
    monkeypatch.setattr(settings, "cse_max_retries", 1)
    yield
    market_module._cache = None


@respx.mock
def test_happy_path_returns_all_three_sections(client):
    respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(200, json={"status": "Market Closed"}))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(200, json=ASPI_PAYLOAD))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(200, json=SECTORS_PAYLOAD))

    body = client.get("/market").json()
    assert body["status"] == "Market Closed"
    assert body["aspi"]["value"] == 21623.17
    assert [s["name"] for s in body["sectors"]] == ["Energy", "Materials"]  # sorted by name
    assert body["unavailable"] == []
    assert body["cached"] is False


@respx.mock
def test_one_failing_upstream_degrades_only_its_own_section(client):
    """The whole point: ASPI down must not take the sector board with it."""
    respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(200, json={"status": "Open"}))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(500))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(200, json=SECTORS_PAYLOAD))

    response = client.get("/market")
    assert response.status_code == 200  # NOT a 502 for the whole screen
    body = response.json()

    assert body["aspi"] is None
    assert len(body["sectors"]) == 2  # still delivered
    assert body["status"] == "Open"

    sections = {u["section"] for u in body["unavailable"]}
    assert "All Share Price Index" in sections
    # The reason must be human-actionable, not a stack trace (§15.1).
    reason = next(u["reason"] for u in body["unavailable"] if u["section"] == "All Share Price Index")
    assert "could not be reached" in reason
    assert "Traceback" not in reason


@respx.mock
def test_shape_change_is_reported_distinctly_from_unreachable(client):
    """§5 requires alerting on shape change rather than only on HTTP error
    — the two need different fixes, so they must read differently."""
    respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(200, json={"status": "Open"}))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(200, json={"renamed": 1}))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(200, json=SECTORS_PAYLOAD))

    body = client.get("/market").json()
    reason = next(u["reason"] for u in body["unavailable"] if u["section"] == "All Share Price Index")
    assert "shape" in reason


@respx.mock
def test_everything_down_still_returns_200_with_all_sections_flagged(client):
    respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(500))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(500))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(500))

    response = client.get("/market")
    assert response.status_code == 200
    body = response.json()
    assert body["aspi"] is None
    assert body["sectors"] == []
    assert len(body["unavailable"]) == 3


@respx.mock
def test_a_single_unparseable_sector_row_does_not_lose_the_others(client):
    respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(200, json={"status": "Open"}))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(200, json=ASPI_PAYLOAD))
    respx.post(f"{BASE}/allSectors").mock(
        return_value=httpx.Response(200, json=[SECTORS_PAYLOAD[0], {"no_name_field": True}])
    )

    body = client.get("/market").json()
    assert [s["name"] for s in body["sectors"]] == ["Energy"]


@respx.mock
def test_second_call_is_served_from_cache(client):
    status = respx.post(f"{BASE}/marketStatus").mock(
        return_value=httpx.Response(200, json={"status": "Open"})
    )
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(200, json=ASPI_PAYLOAD))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(200, json=SECTORS_PAYLOAD))

    first = client.get("/market").json()
    second = client.get("/market").json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert status.call_count == 1  # upstream hit once, not twice


@respx.mock
def test_a_fully_failed_response_is_not_cached(client):
    """Otherwise a transient outage would be pinned for the full TTL and
    the screen would stay broken after the upstream recovered."""
    status = respx.post(f"{BASE}/marketStatus").mock(return_value=httpx.Response(500))
    respx.post(f"{BASE}/aspiData").mock(return_value=httpx.Response(500))
    respx.post(f"{BASE}/allSectors").mock(return_value=httpx.Response(500))

    client.get("/market")
    client.get("/market")
    assert status.call_count == 2  # tried again rather than serving a cached failure
