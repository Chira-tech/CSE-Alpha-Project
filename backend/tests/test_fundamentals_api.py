"""The fundamentals confirm-queue API (Master Spec §8: AI-assisted values
"cannot enter a valuation until human-confirmed and promoted to
Reported")."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

TICKER = "JFP.N0000"


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="JF Packaging PLC"))
    db.commit()


def _seed_ai_assisted(db, **overrides) -> Fundamental:
    defaults = dict(
        ticker=TICKER,
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        version=1,
        statement_line="total_assets",
        value=Decimal("3807110"),
        currency="LKR",
        provenance_tier=ProvenanceTier.AI_ASSISTED,
        restated_flag=False,
        source_snippet="Total Assets 3,807,110 3,722,727 3,559,834 3,453,018",
        confirmed_by=None,
        confirmed_at=None,
    )
    defaults.update(overrides)
    row = Fundamental(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_list_defaults_to_pending_ai_assisted_only(db_session, client):
    _seed_security(db_session)
    _seed_ai_assisted(db_session)
    _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        value=Decimal("189908"),
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    response = client.get("/fundamentals")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    rows = body["items"]
    assert len(rows) == 1
    assert rows[0]["statement_line"] == "total_assets"
    assert rows[0]["provenance_tier"] == "A"


def test_confirm_promotes_to_reported(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session)

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 200
    body = response.json()
    assert body["provenance_tier"] == "R"
    assert body["confirmed_by"] == "analyst"
    assert body["value"] == "3807110.0000"
    # version and first_available_date must be untouched by confirmation
    assert body["version"] == 1
    assert body["first_available_date"] == "2026-08-14"


def test_confirm_with_correction_updates_value_without_bumping_version(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session, value=Decimal("999999"))  # extractor picked the wrong column

    response = client.post(
        f"/fundamentals/{row.id}/confirm",
        json={"actor": "analyst", "correction": {"value": "3807110"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["value"]) == Decimal("3807110")
    assert body["version"] == 1  # a correction to OUR extraction is not a restatement


def test_cannot_confirm_twice(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session)
    client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "someone-else"})
    assert response.status_code == 409


def test_cannot_confirm_a_row_that_is_already_reported(db_session, client):
    """Only the AI-assisted -> Reported promotion goes through this
    endpoint; a genuinely Reported row was never a draft in the first
    place and has nothing to be "confirmed" into."""
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session, provenance_tier=ProvenanceTier.REPORTED)

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 409
    assert "AI-assisted" in response.json()["detail"]


def test_get_unknown_id_404s(client):
    response = client.get("/fundamentals/999999")
    assert response.status_code == 404


def test_list_pending_only_false_returns_everything(db_session, client):
    _seed_security(db_session)
    _seed_ai_assisted(db_session)
    _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    response = client.get("/fundamentals", params={"pending_only": False})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_is_paged_with_a_default_limit_of_20(db_session, client):
    _seed_security(db_session)
    for i in range(25):
        _seed_ai_assisted(db_session, statement_line=f"line_{i:02d}")

    response = client.get("/fundamentals")
    body = response.json()
    assert body["total"] == 25
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 20


def test_list_second_page_via_offset(db_session, client):
    _seed_security(db_session)
    for i in range(25):
        _seed_ai_assisted(db_session, statement_line=f"line_{i:02d}")

    response = client.get("/fundamentals", params={"limit": 20, "offset": 20})
    body = response.json()
    assert body["total"] == 25
    assert body["offset"] == 20
    assert len(body["items"]) == 5  # the remainder, not a short page error


def test_confirm_batch_promotes_every_valid_id(db_session, client):
    _seed_security(db_session)
    rows = [_seed_ai_assisted(db_session, statement_line=f"line_{i}") for i in range(3)]

    response = client.post(
        "/fundamentals/confirm-batch",
        json={"actor": "analyst", "ids": [r.id for r in rows]},
    )
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["confirmed"]) == sorted(r.id for r in rows)
    assert body["failed"] == []

    for r in rows:
        db_session.refresh(r)
        assert r.provenance_tier == ProvenanceTier.REPORTED
        assert r.confirmed_by == "analyst"


def test_confirm_batch_reports_bad_ids_without_failing_the_good_ones(db_session, client):
    _seed_security(db_session)
    good = _seed_ai_assisted(db_session, statement_line="total_assets")
    already_confirmed = _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        confirmed_by="someone-else",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
        provenance_tier=ProvenanceTier.REPORTED,
    )

    response = client.post(
        "/fundamentals/confirm-batch",
        json={"actor": "analyst", "ids": [good.id, already_confirmed.id, 999999]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == [good.id]
    failed_ids = {f["id"] for f in body["failed"]}
    assert failed_ids == {already_confirmed.id, 999999}
