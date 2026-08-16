"""
Master Spec §5: pacing, retries, circuit breaker, schema-change detection —
each requirement gets its own test rather than trusting one integration
test to exercise all of them.
"""
from __future__ import annotations

import time

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.ingestion.circuit_breaker import CircuitBreaker
from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.circuit_breaker import CircuitOpenError


class _MarketStatus(BaseModel):
    status: str


@pytest.fixture()
def fast_client():
    """Same client, but with pacing turned down to keep the test suite
    fast — the pacing *mechanism* is tested separately with real timing."""
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    yield client
    client.close()


@respx.mock
def test_valid_response_validates_against_model(fast_client):
    respx.get("https://example.test/api/marketStatus").mock(
        return_value=httpx.Response(200, json={"status": "Open"})
    )
    result = fast_client.get_json("marketStatus", model=_MarketStatus)
    assert isinstance(result, _MarketStatus)
    assert result.status == "Open"


@respx.mock
def test_shape_change_raises_instead_of_returning_bad_data(fast_client):
    """This is the whole point of §5's "alert on shape change, not just
    HTTP error" requirement: a 200 with a renamed field must not silently
    produce a validated-looking-but-wrong object."""
    respx.get("https://example.test/api/marketStatus").mock(
        return_value=httpx.Response(200, json={"statusCode": "Open"})  # field renamed
    )
    with pytest.raises(ShapeChangedError):
        fast_client.get_json("marketStatus", model=_MarketStatus)


@respx.mock
def test_retries_on_5xx_then_succeeds(fast_client):
    route = respx.get("https://example.test/api/marketStatus")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"status": "Open"}),
    ]
    result = fast_client.get_json("marketStatus", model=_MarketStatus)
    assert result.status == "Open"
    assert route.call_count == 2


@respx.mock
def test_circuit_opens_after_threshold_and_blocks_further_calls():
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=999)
    client = CseClient(
        base_url="https://example.test/api", min_seconds_between_calls=0.0, circuit_breaker=breaker, max_retries=1
    )
    respx.get("https://example.test/api/marketStatus").mock(return_value=httpx.Response(500))

    for _ in range(2):
        with pytest.raises(Exception):
            client.get_json("marketStatus", model=_MarketStatus)

    with pytest.raises(CircuitOpenError):
        client.get_json("marketStatus", model=_MarketStatus)
    client.close()


def test_pacing_enforces_minimum_gap_between_calls():
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.2)
    with respx.mock:
        respx.get("https://example.test/api/x").mock(return_value=httpx.Response(200, json={}))
        start = time.monotonic()
        client.get_json("x")
        client.get_json("x")
        elapsed = time.monotonic() - start
    assert elapsed >= 0.2
    client.close()


@respx.mock
def test_post_json_sends_json_body_not_query_params(fast_client):
    """Verified live behaviour (README_ENDPOINTS.md): no-parameter list
    endpoints like tradeSummary/marketStatus are POST with a JSON body."""
    route = respx.post("https://example.test/api/marketStatus").mock(
        return_value=httpx.Response(200, json={"status": "Market Closed"})
    )
    result = fast_client.post_json("marketStatus", model=_MarketStatus, body={})
    assert result.status == "Market Closed"
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("application/json")


@respx.mock
def test_post_form_sends_urlencoded_body_not_json(fast_client):
    """Verified live behaviour: parameterised endpoints (companyInfoSummery,
    getAnnouncementByCompany, ...) require form-urlencoded — a JSON body
    against them returns 400 "symbol parameter is missing" even with the
    right field name, so this content-type distinction is load-bearing."""
    route = respx.post("https://example.test/api/companyInfoSummery").mock(
        return_value=httpx.Response(200, json={"reqSymbolInfo": {"symbol": "AAF.N0000", "name": "Asia Asset"}})
    )
    fast_client.post_form("companyInfoSummery", data={"symbol": "AAF.N0000"})
    request = route.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.content == b"symbol=AAF.N0000"


@respx.mock
def test_post_form_returns_none_on_204_when_allowed(fast_client):
    """Verified live behaviour: getAnnouncementById returns 204 for an
    announcementId belonging to the "general announcement" family instead
    — this must surface as None, not an exception, so the loader can fall
    back to getGeneralAnnouncementById."""
    respx.post("https://example.test/api/getAnnouncementById").mock(return_value=httpx.Response(204))
    result = fast_client.post_form("getAnnouncementById", data={"announcementId": 19806}, allow_empty=True)
    assert result is None


@respx.mock
def test_post_form_204_without_allow_empty_raises(fast_client):
    respx.post("https://example.test/api/getAnnouncementById").mock(return_value=httpx.Response(204))
    with pytest.raises(ShapeChangedError):
        fast_client.post_form("getAnnouncementById", data={"announcementId": 1})
