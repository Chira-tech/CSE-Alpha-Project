"""GET /composite-score/{ticker} — the API-layer wiring for §38's
composite score. Only the route was untested before this; the domain
logic itself (app.domain.composite_score / composite_score_view) already
has its own dedicated test modules. Exists mainly to catch the same class
of dict/enum-serialization bug test_valuation_api.py exists to catch at
the domain-to-API boundary.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.macro import MacroSeries
from app.models.securities import Security


def test_unknown_ticker_returns_404(client):
    r = client.get("/composite-score/NOPE.N0000")
    assert r.status_code == 404


def test_fresh_ticker_with_no_data_still_returns_200_honestly_partial(client, db_session):
    db_session.add(Security(ticker="FRESH.N0000", name="Fresh PLC"))
    db_session.commit()

    r = client.get("/composite-score/FRESH.N0000")
    assert r.status_code == 200
    body = r.json()

    assert body["ticker"] == "FRESH.N0000"
    assert body["is_partial"] is True
    # Every declared pillar key must be present, in order, even when nothing
    # about it is computable yet — a reviewer should see the full pillar
    # set and why each one is or isn't included, not a silently short list.
    pillar_keys = {p["key"] for p in body["pillars"]}
    assert pillar_keys == {
        "valuation", "business_quality", "growth",
        "financial_strength", "macro_sector_fit", "timing_momentum", "risk",
    }
    for p in body["pillars"]:
        if not p["included"]:
            assert p["score"] is None
            assert p["reason"]
    # §38's own discipline: Valuation and Growth are evidence, never ranked.
    valuation_pillar = next(p for p in body["pillars"] if p["key"] == "valuation")
    assert valuation_pillar["included"] is False


def test_regime_label_reaches_the_response_as_a_plain_string(client, db_session):
    """A real (non-None) regime result reaches `valuation_evidence.regime_label`
    correctly — `RegimeResult.label` is already a plain str on the domain
    side (see test_valuation_api.py's identical check on GET /valuation),
    not a `RegimeLabel` enum with a `.value` to unwrap. Confirming this
    against a live ticker, not just a no-data one, is the whole point:
    a fresh ticker never reaches this line at all."""
    db_session.add(Security(ticker="MACRO2.N0000", name="Macro Test PLC 2"))
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

    r = client.get("/composite-score/MACRO2.N0000")
    assert r.status_code == 200
    assert r.json()["valuation_evidence"]["regime_label"] == "risk_off"
