"""
Per-company enrichment from companyInfoSummery.

Fixture below is a real captured response (ACCESS ENGINEERING PLC,
AEL.N0000, 16 Aug 2026), trimmed to the fields this loader reads.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from app.ingestion.cse_client import CseClient
from app.ingestion.security_enrichment import (
    enrich_securities,
    fetch_company_info,
    parse_issue_date,
)
from app.models.float_data import FloatData
from app.models.securities import Security

BASE = "https://example.test/api"

REAL_INFO = {
    "reqSymbolBetaInfo": {
        "securityId": 2065,
        "triASIBetaValue": 1.42,
        "betaValueSPSL": 1.51,
        "triASIBetaPeriod": "2026",
        "quarter": 1,
    },
    "reqSymbolInfo": {
        "id": 2065,
        "symbol": "AEL.N0000",
        "name": "ACCESS ENGINEERING PLC",
        "isin": "LK0421N00000",
        "issueDate": "12/JAN/2012",
        "quantityIssued": 1000000000,
        "parValue": 1.0,
        "lastTradedPrice": 76.8,
        "marketCap": 7.68e10,
        "foreignHoldings": 50000000,
        "foreignPercentage": 5.0,
    },
}


def _client() -> CseClient:
    return CseClient(base_url=BASE, min_seconds_between_calls=0.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12/JAN/2012", dt.date(2012, 1, 12)),
        ("01/DEC/1984", dt.date(1984, 12, 1)),
        (None, None),
        ("", None),
        ("not a date", None),
    ],
)
def test_parse_issue_date(text, expected):
    assert parse_issue_date(text) == expected


@respx.mock
def test_fetch_parses_the_real_shape():
    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    info = fetch_company_info(client, "AEL.N0000")
    client.close()

    assert info is not None
    assert info.reqSymbolInfo.isin == "LK0421N00000"
    assert info.reqSymbolInfo.quantityIssued == 1_000_000_000
    assert info.reqSymbolBetaInfo is not None
    assert info.reqSymbolBetaInfo.betaValueSPSL == 1.51


@respx.mock
def test_enriches_isin_listing_date_and_shares(db_session):
    db_session.add(Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"))
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    result = enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    assert result["enriched"] == 1
    security = db_session.get(Security, "AEL.N0000")
    assert security.isin == "LK0421N00000"
    assert security.listing_date == dt.date(2012, 1, 12)

    floats = db_session.query(FloatData).filter_by(ticker="AEL.N0000").all()
    assert len(floats) == 1
    assert floats[0].shares_issued == 1_000_000_000
    # E3 — the exchange's own price and market cap, from this same
    # payload, so the identity check can isolate the share count.
    assert float(floats[0].published_price) == pytest.approx(76.8)
    assert float(floats[0].published_market_cap) == pytest.approx(7.68e10)

    # CSE's own published beta — the module docstring has claimed this
    # was captured since the file was written; it wasn't actually stored
    # until now. `app.domain.beta` uses this as an independent
    # cross-check on its own Dimson-Blume computation.
    assert float(security.published_beta_asi) == pytest.approx(1.42)
    assert float(security.published_beta_sp_sl20) == pytest.approx(1.51)
    assert security.published_beta_period == "2026 Q1"


@respx.mock
def test_published_beta_is_refreshed_every_run_unlike_isin(db_session):
    """Unlike ISIN or listing date, this genuinely changes quarter to
    quarter — re-running enrichment must pick up a new value, not treat
    the first one as permanent."""
    db_session.add(
        Security(
            ticker="AEL.N0000", name="ACCESS ENGINEERING PLC",
            published_beta_asi="1.00", published_beta_period="2025 Q4",
        )
    )
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    security = db_session.get(Security, "AEL.N0000")
    assert float(security.published_beta_asi) == pytest.approx(1.42)
    assert security.published_beta_period == "2026 Q1"


@respx.mock
def test_public_float_is_left_null_not_derived_from_foreign_percentage(db_session):
    """foreignPercentage (5%) is NOT free float — a family-controlled
    company can be 95% domestic and still have a 10% float. Recording it
    as float would be inventing data (Design Law 3)."""
    db_session.add(Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"))
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    row = db_session.query(FloatData).filter_by(ticker="AEL.N0000").one()
    assert row.public_float_pct is None


@respx.mock
def test_never_overwrites_a_value_already_set(db_session):
    """A human may have corrected archetype/ISIN by hand; a re-run must
    not clobber it."""
    db_session.add(
        Security(
            ticker="AEL.N0000",
            name="ACCESS ENGINEERING PLC",
            isin="HAND-SET-ISIN",
            listing_date=dt.date(2000, 1, 1),
            archetype="construction_materials",
        )
    )
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    security = db_session.get(Security, "AEL.N0000")
    assert security.isin == "HAND-SET-ISIN"
    assert security.listing_date == dt.date(2000, 1, 1)
    assert security.archetype == "construction_materials"


@respx.mock
def test_never_sets_sector_or_archetype(db_session):
    """Neither exists on the CSE API, and a wrong archetype silently
    routes a bank through an industrial DCF (Part N #7)."""
    db_session.add(Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"))
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    security = db_session.get(Security, "AEL.N0000")
    assert security.archetype is None
    assert security.cse_sector is None


@respx.mock
def test_one_failing_company_does_not_abort_the_sweep(db_session):
    db_session.add_all(
        [
            Security(ticker="BAD.N0000", name="Bad"),
            Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"),
        ]
    )
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery", data={"symbol": "BAD.N0000"}).mock(
        return_value=httpx.Response(500)
    )
    respx.post(f"{BASE}/companyInfoSummery", data={"symbol": "AEL.N0000"}).mock(
        return_value=httpx.Response(200, json=REAL_INFO)
    )

    client = CseClient(base_url=BASE, min_seconds_between_calls=0.0, max_retries=1)
    result = enrich_securities(client, db_session, ["BAD.N0000", "AEL.N0000"])
    client.close()

    assert result["failed"] == 1
    assert result["enriched"] == 1  # the good one still landed
    assert db_session.get(Security, "AEL.N0000").isin == "LK0421N00000"


@respx.mock
def test_on_ticker_returning_false_actually_stops_the_sweep(db_session):
    """Real bug, caught live in the browser: an earlier version of
    `app.jobs.runner._run_enrich_securities` only RECORDED a cancel
    request in a local variable without this function itself ever
    checking it — clicking Cancel in the sidebar set `cancel_requested`
    in the database correctly, but the worker kept fetching ticker after
    ticker to the end of the universe regardless, because nothing in
    this loop actually broke on it. `on_ticker` returning `False` must
    stop the sweep after the ticker that just completed, not just be
    observed."""
    db_session.add_all(
        [
            Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"),
            Security(ticker="BAD.N0000", name="Never Reached"),
        ]
    )
    db_session.commit()
    respx.post(f"{BASE}/companyInfoSummery", data={"symbol": "AEL.N0000"}).mock(
        return_value=httpx.Response(200, json=REAL_INFO)
    )
    # No mock registered for BAD.N0000 — respx raises if this is ever
    # actually requested, which is exactly the assertion this test needs.

    client = _client()
    calls: list[str] = []

    def on_ticker(i: int, n: int, ticker: str) -> bool:
        calls.append(ticker)
        return False  # stop after the very first ticker

    result = enrich_securities(client, db_session, ["AEL.N0000", "BAD.N0000"], on_ticker=on_ticker)
    client.close()

    assert calls == ["AEL.N0000"]
    assert result["enriched"] == 1
    assert db_session.get(Security, "BAD.N0000").isin is None


@respx.mock
def test_on_ticker_returning_none_does_not_stop_the_sweep(db_session):
    """The signal is opt-in: every pre-existing caller (`app.cli`, every
    test above) never returns anything from its callback, and must keep
    sweeping every ticker exactly as before."""
    db_session.add_all(
        [
            Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"),
            Security(ticker="AEL2.N0000", name="Also Reached"),
        ]
    )
    db_session.commit()
    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))

    client = _client()
    calls: list[str] = []
    result = enrich_securities(
        client, db_session, ["AEL.N0000", "AEL2.N0000"],
        on_ticker=lambda i, n, ticker: calls.append(ticker),  # returns None
    )
    client.close()

    assert calls == ["AEL.N0000", "AEL2.N0000"]
    assert result["enriched"] == 2


@respx.mock
def test_rerun_does_not_duplicate_the_float_snapshot(db_session):
    db_session.add(Security(ticker="AEL.N0000", name="ACCESS ENGINEERING PLC"))
    db_session.commit()

    respx.post(f"{BASE}/companyInfoSummery").mock(return_value=httpx.Response(200, json=REAL_INFO))
    client = _client()
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    enrich_securities(client, db_session, ["AEL.N0000"], as_of=dt.date(2026, 8, 16))
    client.close()

    assert db_session.query(FloatData).filter_by(ticker="AEL.N0000").count() == 1
