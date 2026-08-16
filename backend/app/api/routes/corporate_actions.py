"""
Master Spec §5: corporate actions are ingested via "Scrape + mandatory
human confirm queue." Until now that queue had no interface at all — a
human would have had to query the database directly. This is the minimal
API for it: list drafts, view one, confirm it (only after the reviewer
has actually filled in every field the adjustment-factor math needs), or
reject it (soft — the row is kept for audit, just marked so it's excluded
from the queue and from any future draft for the same event).

Deliberately NOT a general-purpose CRUD API: there is no "edit" endpoint
that silently accepts partial updates. A reviewer confirms a fully-formed
action or rejects it; anything in between (fixing a wrong ratio) goes
through `PATCH .../draft` first, then `POST .../confirm` — two explicit
steps, because Master Spec §7 treats this table as "the highest-
consequence data in the system" and a UI that makes editing and
confirming the same click is exactly how that consequence gets realised
by accident.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.corporate_actions import (
    ActionKind,
    CorporateActionEvent,
    price_ratio_for_event,
)
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType

router = APIRouter(prefix="/corporate-actions", tags=["corporate-actions"])

_DB_TO_DOMAIN_KIND = {
    DbActionType.DIVIDEND_CASH: ActionKind.DIVIDEND_CASH,
    DbActionType.BONUS_ISSUE: ActionKind.BONUS_ISSUE,
    DbActionType.STOCK_SPLIT: ActionKind.STOCK_SPLIT,
    DbActionType.CONSOLIDATION: ActionKind.CONSOLIDATION,
    DbActionType.RIGHTS_ISSUE: ActionKind.RIGHTS_ISSUE,
}


class CorporateActionOut(BaseModel):
    id: int
    ticker: str
    ex_date: dt.date
    type: DbActionType
    ratio: Decimal | None
    cash_amount: Decimal | None
    subscription_price: Decimal | None
    cum_rights_price: Decimal | None
    terp: Decimal | None
    source_url: str | None
    notes: str | None
    confirmed_by: str | None
    confirmed_at: dt.datetime | None
    rejected_by: str | None
    rejected_at: dt.datetime | None

    @classmethod
    def from_model(cls, row: CorporateAction) -> "CorporateActionOut":
        return cls(
            id=row.id,
            ticker=row.ticker,
            ex_date=row.ex_date,
            type=row.type,
            ratio=row.ratio,
            cash_amount=row.cash_amount,
            subscription_price=row.subscription_price,
            cum_rights_price=row.cum_rights_price,
            terp=row.terp,
            source_url=row.source_url,
            notes=row.notes,
            confirmed_by=row.confirmed_by,
            confirmed_at=row.confirmed_at,
            rejected_by=row.rejected_by,
            rejected_at=row.rejected_at,
        )


class DraftUpdate(BaseModel):
    """Every field is optional so a reviewer can patch just what's wrong
    (e.g. fill in a rights issue's cum_rights_price, which this system
    deliberately never auto-populates — see build_rights_issue_draft's
    docstring) without having to resupply the rest."""

    ratio: Decimal | None = None
    cash_amount: Decimal | None = None
    subscription_price: Decimal | None = None
    cum_rights_price: Decimal | None = None
    notes: str | None = None


class ReviewRequest(BaseModel):
    """Shared body for both confirm and reject — `actor` becomes
    confirmed_by or rejected_by depending on which endpoint is called."""

    actor: str = Field(min_length=1, max_length=100)


def _get_or_404(db: Session, action_id: int) -> CorporateAction:
    row = db.get(CorporateAction, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no corporate action with id {action_id}")
    return row


def _validate_confirmable(row: CorporateAction) -> None:
    """Mirrors app.domain.corporate_actions.price_ratio_for_event's own
    validation (missing/zero/negative fields raise ValueError there) so a
    row that would blow up the adjustment-factor build at 3am during the
    nightly batch instead fails loudly, with a clear message, at
    confirm-time — this is the whole point of a confirm step existing.
    """
    kind = _DB_TO_DOMAIN_KIND.get(row.type)
    if kind is None:
        return  # delisting/suspension aren't price-ratio events; nothing to validate

    if kind is ActionKind.DIVIDEND_CASH:
        if row.cash_amount is None:
            raise HTTPException(422, "cash_amount is required to confirm a cash dividend")
        if row.cash_amount <= 0:
            raise HTTPException(422, "cash_amount must be positive")
        # The full price_ratio_for_event check (cash_amount implausibly
        # large relative to price) needs that day's close, which isn't
        # known until the adjustment-factor build runs against real price
        # history — deferred to app.jobs.reconciliation, which quarantines
        # the ticker rather than silently applying a bad ratio (§7).
        return

    if kind in (ActionKind.BONUS_ISSUE, ActionKind.STOCK_SPLIT):
        if row.ratio is None:
            raise HTTPException(422, "ratio (new shares per held share) is required to confirm this action")
        event = CorporateActionEvent(ex_date=row.ex_date, kind=kind, new_shares_per_held_share=row.ratio)
        try:
            price_ratio_for_event(event)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return

    if kind is ActionKind.CONSOLIDATION:
        if row.ratio is None:
            raise HTTPException(422, "ratio (old shares per new share) is required to confirm this action")
        return

    if kind is ActionKind.RIGHTS_ISSUE:
        missing = [
            name
            for name, value in (
                ("ratio", row.ratio),
                ("subscription_price", row.subscription_price),
                ("cum_rights_price", row.cum_rights_price),
            )
            if value is None
        ]
        if missing:
            raise HTTPException(
                422,
                "rights issue is missing required fields before it can be confirmed: "
                + ", ".join(missing)
                + ". cum_rights_price is never auto-populated — it must be the market close the "
                "day before ex_date, entered by the reviewer.",
            )
        return


@router.get("", response_model=list[CorporateActionOut])
def list_corporate_actions(
    ticker: str | None = None,
    pending_only: bool = True,
    db: Session = Depends(get_db),
) -> list[CorporateActionOut]:
    """Default view is the confirm queue: drafts that are neither
    confirmed nor rejected. Pass `pending_only=false` to see everything,
    e.g. for an audit trail."""
    stmt = select(CorporateAction).order_by(CorporateAction.ex_date.desc())
    if ticker is not None:
        stmt = stmt.where(CorporateAction.ticker == ticker)
    if pending_only:
        stmt = stmt.where(CorporateAction.confirmed_by.is_(None), CorporateAction.rejected_by.is_(None))
    rows = db.scalars(stmt).all()
    return [CorporateActionOut.from_model(r) for r in rows]


@router.get("/{action_id}", response_model=CorporateActionOut)
def get_corporate_action(action_id: int, db: Session = Depends(get_db)) -> CorporateActionOut:
    return CorporateActionOut.from_model(_get_or_404(db, action_id))


@router.patch("/{action_id}/draft", response_model=CorporateActionOut)
def update_draft(action_id: int, patch: DraftUpdate, db: Session = Depends(get_db)) -> CorporateActionOut:
    """Edit an unconfirmed draft's fields. Refuses to touch a row that's
    already confirmed — correcting a confirmed action is a new decision
    (reject it and let ingestion redraft, or handle out of band), not a
    silent edit of a row whose confirmation someone already relied on."""
    row = _get_or_404(db, action_id)
    if row.confirmed_by is not None:
        raise HTTPException(409, "cannot edit an already-confirmed corporate action")
    if row.rejected_by is not None:
        raise HTTPException(409, "cannot edit a rejected corporate action")

    updates = patch.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return CorporateActionOut.from_model(row)


@router.post("/{action_id}/confirm", response_model=CorporateActionOut)
def confirm_draft(action_id: int, body: ReviewRequest, db: Session = Depends(get_db)) -> CorporateActionOut:
    row = _get_or_404(db, action_id)
    if row.confirmed_by is not None:
        raise HTTPException(409, "already confirmed")
    if row.rejected_by is not None:
        raise HTTPException(409, "cannot confirm an already-rejected corporate action")

    _validate_confirmable(row)

    row.confirmed_by = body.actor
    row.confirmed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(row)
    return CorporateActionOut.from_model(row)


@router.post("/{action_id}/reject", response_model=CorporateActionOut)
def reject_draft(action_id: int, body: ReviewRequest, db: Session = Depends(get_db)) -> CorporateActionOut:
    """Soft reject: marks the row (via rejected_by/rejected_at, kept
    strictly separate from confirmed_by/confirmed_at — see the model's
    docstring for why) so it drops out of the pending queue without
    deleting it, and so a future ingestion run does NOT redraft the same
    event — `_already_drafted` in corporate_actions_loader keys on
    (ticker, ex_date, type) regardless of confirmation/rejection status."""
    row = _get_or_404(db, action_id)
    if row.confirmed_by is not None:
        raise HTTPException(409, "cannot reject an already-confirmed corporate action")
    if row.rejected_by is not None:
        raise HTTPException(409, "already rejected")

    row.rejected_by = body.actor
    row.rejected_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(row)
    return CorporateActionOut.from_model(row)
