"""GET /valuation/{ticker} — the full API-layer wiring, not just the
domain functions test_valuation_view.py already covers. Exists mainly to
catch Pydantic-serialization bugs at the domain-to-API boundary (a
dict-key-type mismatch, a missing field on `from_summary`, ...) that a
purely domain-level test can't see, since it never actually constructs
the response model.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.macro import MacroSeries
from app.models.securities import Security


def test_unknown_ticker_returns_404(client):
    r = client.get("/valuation/NOPE.N0000")
    assert r.status_code == 404


def test_fresh_ticker_with_no_data_still_returns_200_with_honest_nulls(client, db_session):
    db_session.add(Security(ticker="FRESH.N0000", name="Fresh PLC"))
    db_session.commit()

    r = client.get("/valuation/FRESH.N0000")
    assert r.status_code == 200
    body = r.json()

    assert body["ticker"] == "FRESH.N0000"
    assert body["regime"]["label"] is None
    assert body["regime"]["probabilities"] is None
    assert body["regime"]["signals"] == []
    assert len(body["regime"]["missing_signals"]) > 0
    assert len(body["regime"]["warnings"]) > 0
    assert body["dcf"]["fair_value_per_share"] is None
    assert body["hard_book"]["hard_book_value"] is None
    assert body["gordon_growth_ddm"]["value_per_share"] is None


def test_regime_signals_surface_through_the_full_response(client, db_session):
    """A real (if partial) regime read reaches the HTTP response with
    correctly-typed fields — specifically the `probabilities` dict,
    whose keys are `RegimeLabel` (a `Literal[str]`) on the domain side
    and must round-trip through Pydantic/JSON as plain strings without
    error."""
    db_session.add(Security(ticker="MACRO.N0000", name="Macro Test PLC"))
    db_session.add_all(
        [
            MacroSeries(
                series_id="cbsl.policy_rate", obs_date=dt.date(2026, 5, 1),
                first_available_date=dt.date(2026, 5, 1), value=Decimal("0.0775"), source="manual",
            ),
            MacroSeries(
                series_id="cbsl.policy_rate", obs_date=dt.date(2026, 7, 1),
                first_available_date=dt.date(2026, 7, 1), value=Decimal("0.0875"), source="manual",
            ),
        ]
    )
    db_session.commit()

    r = client.get("/valuation/MACRO.N0000")
    assert r.status_code == 200
    body = r.json()
    assert body["regime"]["label"] == "risk_off"
    # Decimal fields serialize as JSON strings (FastAPI's default Decimal
    # encoding), not floats — compared via Decimal(), not a literal 1.0.
    assert Decimal(body["regime"]["probabilities"]["risk_off"]) == Decimal(1)
    assert any(s["name"] == "Policy rate direction" for s in body["regime"]["signals"])
