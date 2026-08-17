"""§34's national project register confirm-queue API."""
from __future__ import annotations

import datetime as dt

from app.models.securities import Security

TICKER = "SWAD.N0000"


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="Swadeshi Industrial Works PLC"))
    db.commit()


def _create_payload(**overrides):
    payload = {
        "name": "Cyclone reconstruction allocation",
        "sponsor": "Ministry of Public Administration",
        "sector": "Construction & materials",
        "financing_source": "state",
        "capex_lkr": "5000000000",
        "capex_usd": None,
        "phase_start_date": "2026-06-01",
        "phase_expected_completion_date": "2027-12-31",
        "status": "financing_closed",
        "source_url": "https://example.gov.lk/cyclone-reconstruction",
        "source_date": "2026-06-01",
        "notes": "Test fixture.",
        "impacts": [],
    }
    payload.update(overrides)
    return payload


def _impact_payload(**overrides):
    payload = {
        "ticker": TICKER,
        "transmission_channel": "materials_supplier",
        "impact_metric": "revenue",
        "quantified_impact_pct": "0.015",
        "impact_description": "Reconstruction demand adds an estimated 1.5% to revenue over FY27.",
        "provenance_tag": "E",
    }
    payload.update(overrides)
    return payload


def test_create_defaults_to_unconfirmed_draft(client, db_session):
    _seed_security(db_session)
    r = client.post("/national-projects", json=_create_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["confirmed_by"] is None
    assert body["rejected_by"] is None
    assert body["status"] == "financing_closed"
    assert body["may_influence_base_case"] is False  # not confirmed yet


def test_create_with_inline_impacts(client, db_session):
    _seed_security(db_session)
    payload = _create_payload(impacts=[_impact_payload()])
    r = client.post("/national-projects", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert len(body["impacts"]) == 1
    assert body["impacts"][0]["ticker"] == TICKER


def test_list_defaults_to_pending_only(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()
    client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})
    other = client.post("/national-projects", json=_create_payload(name="Another project")).json()

    r = client.get("/national-projects")
    ids = [p["id"] for p in r.json()]
    assert other["id"] in ids
    assert created["id"] not in ids

    r_all = client.get("/national-projects", params={"pending_only": False})
    ids_all = [p["id"] for p in r_all.json()]
    assert created["id"] in ids_all
    assert other["id"] in ids_all


def test_list_filters_by_ticker(client, db_session):
    _seed_security(db_session)
    _seed_security(db_session, ticker="OTHER.N0000")
    with_impact = client.post(
        "/national-projects", json=_create_payload(impacts=[_impact_payload()])
    ).json()
    without_impact = client.post(
        "/national-projects", json=_create_payload(name="No impact yet")
    ).json()

    r = client.get("/national-projects", params={"ticker": TICKER})
    ids = [p["id"] for p in r.json()]
    assert with_impact["id"] in ids
    assert without_impact["id"] not in ids


def test_get_unknown_project_404s(client, db_session):
    r = client.get("/national-projects/999999")
    assert r.status_code == 404


def test_patch_draft(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()
    r = client.patch(
        f"/national-projects/{created['id']}/draft",
        json={"status": "under_construction", "notes": "Updated."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "under_construction"
    assert r.json()["notes"] == "Updated."


def test_patch_confirmed_project_is_rejected(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()
    client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})

    r = client.patch(f"/national-projects/{created['id']}/draft", json={"notes": "too late"})
    assert r.status_code == 409


def test_add_and_remove_impact(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()

    r = client.post(f"/national-projects/{created['id']}/impacts", json=_impact_payload())
    assert r.status_code == 201
    impact_id = r.json()["id"]

    got = client.get(f"/national-projects/{created['id']}").json()
    assert len(got["impacts"]) == 1

    r_del = client.delete(f"/national-projects/{created['id']}/impacts/{impact_id}")
    assert r_del.status_code == 204

    got_after = client.get(f"/national-projects/{created['id']}").json()
    assert got_after["impacts"] == []


def test_confirm_requires_e_or_f_provenance(client, db_session):
    """§34: "provenance-tagged E or F" — reusing ProvenanceTier directly
    means the DB column structurally accepts any of the 7 tiers, so this
    is exactly the case the domain-layer validation exists to catch at
    confirm time, not silently accept."""
    _seed_security(db_session)
    payload = _create_payload(impacts=[_impact_payload(provenance_tag="R")])
    created = client.post("/national-projects", json=payload).json()

    r = client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})
    assert r.status_code == 422
    assert "ESTIMATED" in r.json()["detail"] or "FORECAST" in r.json()["detail"]


def test_confirm_succeeds_with_valid_provenance_and_reflects_eligibility(client, db_session):
    _seed_security(db_session)
    payload = _create_payload(status="financing_closed", impacts=[_impact_payload()])
    created = client.post("/national-projects", json=payload).json()

    r = client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})
    assert r.status_code == 200
    body = r.json()
    assert body["confirmed_by"] == "analyst"
    assert body["may_influence_base_case"] is True
    assert body["may_influence_bull_case"] is True


def test_early_stage_confirmed_project_only_influences_bull_case(client, db_session):
    _seed_security(db_session)
    payload = _create_payload(status="announced", impacts=[_impact_payload()])
    created = client.post("/national-projects", json=payload).json()
    r = client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})
    body = r.json()
    assert body["may_influence_base_case"] is False
    assert body["may_influence_bull_case"] is True


def test_confirm_twice_is_rejected(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()
    client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst"})
    r = client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst2"})
    assert r.status_code == 409


def test_reject_then_confirm_is_rejected(client, db_session):
    _seed_security(db_session)
    created = client.post("/national-projects", json=_create_payload()).json()
    client.post(f"/national-projects/{created['id']}/reject", json={"actor": "analyst"})
    r = client.post(f"/national-projects/{created['id']}/confirm", json={"actor": "analyst2"})
    assert r.status_code == 409
