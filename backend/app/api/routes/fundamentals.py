"""
Master Spec §8: an AI-assisted figure "must show the source snippet.
Cannot enter a valuation until human-confirmed and promoted to Reported."
The extraction pipeline (app.ingestion.financial_pdf_extractor) and the
domain rule for what AI-assisted provenance means
(app.domain.provenance.can_enter_valuation) existed before this queue did
— nothing actually implemented the promotion. This is that.

Confirming does NOT bump `version` — see the model's docstring for why:
promotion is "we now trust our own extraction," not "the company restated
this number." `first_available_date` is likewise never touched by
confirmation.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.provenance import can_enter_valuation
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


class FundamentalOut(BaseModel):
    id: int
    ticker: str
    period_end: dt.date
    period_type: str
    first_available_date: dt.date
    version: int
    statement_line: str
    value: Decimal
    currency: str
    provenance_tier: ProvenanceTier
    restated_flag: bool
    source_url: str | None
    source_page: int | None
    source_snippet: str | None
    confirmed_by: str | None
    confirmed_at: dt.datetime | None

    @classmethod
    def from_model(cls, row: Fundamental) -> "FundamentalOut":
        return cls(
            id=row.id,
            ticker=row.ticker,
            period_end=row.period_end,
            period_type=row.period_type,
            first_available_date=row.first_available_date,
            version=row.version,
            statement_line=row.statement_line,
            value=row.value,
            currency=row.currency,
            provenance_tier=row.provenance_tier,
            restated_flag=row.restated_flag,
            source_url=row.source_url,
            source_page=row.source_page,
            source_snippet=row.source_snippet,
            confirmed_by=row.confirmed_by,
            confirmed_at=row.confirmed_at,
        )


class ValueCorrection(BaseModel):
    """A reviewer may correct a mis-extracted value before confirming —
    e.g. the extractor picked the wrong column. This is still not a
    restatement (§6), so it does not bump `version`."""

    value: Decimal


class ConfirmRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    correction: ValueCorrection | None = None


def _get_or_404(db: Session, fundamental_id: int) -> Fundamental:
    row = db.get(Fundamental, fundamental_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no fundamental with id {fundamental_id}")
    return row


@router.get("", response_model=list[FundamentalOut])
def list_fundamentals(
    ticker: str | None = None,
    pending_only: bool = True,
    db: Session = Depends(get_db),
) -> list[FundamentalOut]:
    """Default view is the confirm queue: AI-assisted rows not yet
    confirmed. Pass `pending_only=false` for everything, e.g. to inspect
    a company's full reported history."""
    stmt = select(Fundamental).order_by(Fundamental.period_end.desc(), Fundamental.statement_line)
    if ticker is not None:
        stmt = stmt.where(Fundamental.ticker == ticker)
    if pending_only:
        stmt = stmt.where(
            Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
            Fundamental.confirmed_by.is_(None),
        )
    rows = db.scalars(stmt).all()
    return [FundamentalOut.from_model(r) for r in rows]


@router.get("/{fundamental_id}", response_model=FundamentalOut)
def get_fundamental(fundamental_id: int, db: Session = Depends(get_db)) -> FundamentalOut:
    return FundamentalOut.from_model(_get_or_404(db, fundamental_id))


@router.post("/{fundamental_id}/confirm", response_model=FundamentalOut)
def confirm_fundamental(
    fundamental_id: int, body: ConfirmRequest, db: Session = Depends(get_db)
) -> FundamentalOut:
    row = _get_or_404(db, fundamental_id)

    if row.confirmed_by is not None:
        raise HTTPException(409, "already confirmed")
    if row.provenance_tier != ProvenanceTier.AI_ASSISTED:
        raise HTTPException(
            409,
            f"only AI-assisted rows go through this confirm step (this row is {row.provenance_tier.value}); "
            "Reported/Derived/Normalised rows don't need promotion",
        )

    if body.correction is not None:
        row.value = body.correction.value

    row.provenance_tier = ProvenanceTier.REPORTED
    row.confirmed_by = body.actor
    row.confirmed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(row)

    assert can_enter_valuation(row.provenance_tier)  # the whole point of this endpoint
    return FundamentalOut.from_model(row)
