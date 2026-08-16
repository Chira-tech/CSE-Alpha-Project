"""
The human-confirm workflow API (Master Spec §5: "mandatory human confirm
queue"). Before this, a draft could only be reviewed by querying the
database directly.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType
from app.models.securities import Security

TICKER = "AAF.N0000"


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="Asia Asset Finance PLC"))
    db.commit()


def _seed_draft(db, **overrides) -> CorporateAction:
    defaults = dict(
        ticker=TICKER,
        ex_date=dt.date(2026, 7, 24),
        type=DbActionType.DIVIDEND_CASH,
        cash_amount=None,
        confirmed_by=None,
        confirmed_at=None,
        notes="Cash dividend, source: 'test fixture'.",
    )
    defaults.update(overrides)
    row = CorporateAction(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_list_defaults_to_pending_only(db_session, client):
    _seed_security(db_session)
    _seed_draft(db_session, cash_amount=Decimal("0.70"))
    _seed_draft(
        db_session,
        ex_date=dt.date(2020, 1, 1),
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
        cash_amount=Decimal("1.00"),
    )

    response = client.get("/corporate-actions")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["confirmed_by"] is None


def test_list_pending_only_false_returns_everything(db_session, client):
    _seed_security(db_session)
    _seed_draft(db_session, cash_amount=Decimal("0.70"))
    _seed_draft(
        db_session,
        ex_date=dt.date(2020, 1, 1),
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
        cash_amount=Decimal("1.00"),
    )

    response = client.get("/corporate-actions", params={"pending_only": False})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_confirm_requires_cash_amount_for_dividend(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=None)

    response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 422
    assert "cash_amount" in response.json()["detail"]


def test_patch_then_confirm_dividend(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=None)

    patch_response = client.patch(f"/corporate-actions/{draft.id}/draft", json={"cash_amount": "0.70"})
    assert patch_response.status_code == 200
    assert Decimal(patch_response.json()["cash_amount"]) == Decimal("0.70")

    confirm_response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert confirm_response.status_code == 200
    body = confirm_response.json()
    assert body["confirmed_by"] == "analyst"
    assert body["confirmed_at"] is not None


def test_confirm_rights_issue_requires_all_three_fields(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(
        db_session,
        type=DbActionType.RIGHTS_ISSUE,
        ratio=Decimal("0.36363636"),
        subscription_price=None,
        cum_rights_price=None,
    )

    response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "subscription_price" in detail
    assert "cum_rights_price" in detail


def test_confirm_rights_issue_succeeds_once_fully_populated(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(
        db_session,
        type=DbActionType.RIGHTS_ISSUE,
        ratio=Decimal("0.36363636"),
        subscription_price=Decimal("33.30"),
        cum_rights_price=None,
    )

    # cum_rights_price is never auto-populated — reviewer must supply it
    # from the market close the day before ex_date.
    patch_response = client.patch(f"/corporate-actions/{draft.id}/draft", json={"cum_rights_price": "95.00"})
    assert patch_response.status_code == 200

    confirm_response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert confirm_response.status_code == 200


def test_cannot_confirm_twice(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=Decimal("0.70"))
    client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})

    response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "someone-else"})
    assert response.status_code == 409


def test_reject_removes_from_pending_queue_without_deleting(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=None)

    reject_response = client.post(f"/corporate-actions/{draft.id}/reject", json={"actor": "analyst"})
    assert reject_response.status_code == 200
    assert reject_response.json()["rejected_by"] == "analyst"

    pending = client.get("/corporate-actions").json()
    assert pending == []

    everything = client.get("/corporate-actions", params={"pending_only": False}).json()
    assert len(everything) == 1


def test_cannot_confirm_a_rejected_row(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=Decimal("0.70"))
    client.post(f"/corporate-actions/{draft.id}/reject", json={"actor": "analyst"})

    response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 409


def test_cannot_reject_a_confirmed_row(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=Decimal("0.70"))
    client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})

    response = client.post(f"/corporate-actions/{draft.id}/reject", json={"actor": "someone-else"})
    assert response.status_code == 409


def test_cannot_edit_a_confirmed_row(db_session, client):
    _seed_security(db_session)
    draft = _seed_draft(db_session, cash_amount=Decimal("0.70"))
    client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})

    response = client.patch(f"/corporate-actions/{draft.id}/draft", json={"cash_amount": "9.99"})
    assert response.status_code == 409


def test_get_unknown_id_404s(client):
    response = client.get("/corporate-actions/999999")
    assert response.status_code == 404


def test_confirm_bonus_issue_validates_via_domain_price_ratio(db_session, client):
    """The confirm endpoint reuses app.domain.corporate_actions.price_ratio_for_event
    for validation, so a nonsensical ratio is rejected with the same
    message the adjustment-factor build itself would raise."""
    _seed_security(db_session)
    draft = _seed_draft(db_session, type=DbActionType.BONUS_ISSUE, ratio=None, cash_amount=None)

    response = client.post(f"/corporate-actions/{draft.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 422
    assert "ratio" in response.json()["detail"]
