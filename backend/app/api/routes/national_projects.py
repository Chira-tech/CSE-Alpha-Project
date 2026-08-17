"""
Master Spec §34: the national project and outlook register. Unlike
`corporate_actions.py`, there is no ingestion scraper feeding this queue
— §34's own examples ("cyclone reconstruction allocation," "the IMF
programme's structural benchmarks") are the kind of thing an analyst
reads about and enters directly, not something a CSE API endpoint
publishes in a structured form. So this router adds a genuine create
endpoint corporate_actions.py doesn't need, alongside the same list /
get / patch-draft / confirm / reject shape that module already
established for a §7/§8-style confirm queue.

Same discipline as corporate_actions.py: no endpoint that silently
accepts a partial update to an already-confirmed row. A reviewer
confirms a fully-formed project or rejects it; fixing something wrong
goes through the draft-mutation endpoints first.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.national_projects import (
    may_influence_base_case,
    may_influence_bull_case,
    validate_impact_provenance_tag,
)
from app.models.enums import (
    NationalProjectFinancingSource,
    NationalProjectImpactMetric,
    NationalProjectStatus,
    NationalProjectTransmissionChannel,
    ProvenanceTier,
)
from app.models.national_projects import NationalProject, NationalProjectTickerImpact

router = APIRouter(prefix="/national-projects", tags=["national-projects"])


class TickerImpactIn(BaseModel):
    ticker: str
    transmission_channel: NationalProjectTransmissionChannel
    impact_metric: NationalProjectImpactMetric
    quantified_impact_pct: Decimal | None = None
    impact_description: str = Field(min_length=1)
    provenance_tag: ProvenanceTier


class TickerImpactOut(BaseModel):
    id: int
    project_id: int
    ticker: str
    transmission_channel: NationalProjectTransmissionChannel
    impact_metric: NationalProjectImpactMetric
    quantified_impact_pct: Decimal | None
    impact_description: str
    provenance_tag: ProvenanceTier

    @classmethod
    def from_model(cls, row: NationalProjectTickerImpact) -> "TickerImpactOut":
        return cls(
            id=row.id, project_id=row.project_id, ticker=row.ticker,
            transmission_channel=row.transmission_channel, impact_metric=row.impact_metric,
            quantified_impact_pct=row.quantified_impact_pct,
            impact_description=row.impact_description, provenance_tag=row.provenance_tag,
        )


class NationalProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    sponsor: str | None = None
    sector: str | None = None
    financing_source: NationalProjectFinancingSource | None = None
    capex_lkr: Decimal | None = None
    capex_usd: Decimal | None = None
    phase_start_date: dt.date | None = None
    phase_expected_completion_date: dt.date | None = None
    status: NationalProjectStatus = NationalProjectStatus.ANNOUNCED
    source_url: str | None = None
    source_date: dt.date | None = None
    notes: str | None = None
    impacts: list[TickerImpactIn] = []


class NationalProjectDraftUpdate(BaseModel):
    """Every field optional, matching `corporate_actions.py`'s own
    `DraftUpdate` — a reviewer patches only what needs fixing. Does NOT
    touch `impacts` — those are added/removed through their own
    endpoints below, so a single PATCH can't silently drop a
    previously-entered impact by omitting it."""

    name: str | None = None
    sponsor: str | None = None
    sector: str | None = None
    financing_source: NationalProjectFinancingSource | None = None
    capex_lkr: Decimal | None = None
    capex_usd: Decimal | None = None
    phase_start_date: dt.date | None = None
    phase_expected_completion_date: dt.date | None = None
    status: NationalProjectStatus | None = None
    source_url: str | None = None
    source_date: dt.date | None = None
    notes: str | None = None


class ReviewRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)


class NationalProjectOut(BaseModel):
    id: int
    name: str
    sponsor: str | None
    sector: str | None
    financing_source: NationalProjectFinancingSource | None
    capex_lkr: Decimal | None
    capex_usd: Decimal | None
    phase_start_date: dt.date | None
    phase_expected_completion_date: dt.date | None
    status: NationalProjectStatus
    source_url: str | None
    source_date: dt.date | None
    notes: str | None
    confirmed_by: str | None
    confirmed_at: dt.datetime | None
    rejected_by: str | None
    rejected_at: dt.datetime | None
    may_influence_base_case: bool
    may_influence_bull_case: bool
    impacts: list[TickerImpactOut]

    @classmethod
    def from_model(cls, row: NationalProject) -> "NationalProjectOut":
        return cls(
            id=row.id, name=row.name, sponsor=row.sponsor, sector=row.sector,
            financing_source=row.financing_source, capex_lkr=row.capex_lkr,
            capex_usd=row.capex_usd, phase_start_date=row.phase_start_date,
            phase_expected_completion_date=row.phase_expected_completion_date,
            status=row.status, source_url=row.source_url, source_date=row.source_date,
            notes=row.notes, confirmed_by=row.confirmed_by, confirmed_at=row.confirmed_at,
            rejected_by=row.rejected_by, rejected_at=row.rejected_at,
            may_influence_base_case=may_influence_base_case(
                row.status, is_confirmed=row.is_confirmed
            ),
            may_influence_bull_case=may_influence_bull_case(
                row.status, is_confirmed=row.is_confirmed
            ),
            impacts=[TickerImpactOut.from_model(i) for i in row.impacts],
        )


def _get_or_404(db: Session, project_id: int) -> NationalProject:
    row = db.get(NationalProject, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no national project with id {project_id}")
    return row


def _require_draft(row: NationalProject) -> None:
    if row.confirmed_by is not None:
        raise HTTPException(409, "cannot modify an already-confirmed national project")
    if row.rejected_by is not None:
        raise HTTPException(409, "cannot modify a rejected national project")


@router.get("", response_model=list[NationalProjectOut])
def list_national_projects(
    ticker: str | None = None,
    pending_only: bool = True,
    db: Session = Depends(get_db),
) -> list[NationalProjectOut]:
    """Default view is the confirm queue, same convention as
    `GET /corporate-actions`. `ticker` filters to projects with at least
    one impact row naming that ticker."""
    stmt = select(NationalProject).order_by(NationalProject.id.desc())
    if pending_only:
        stmt = stmt.where(
            NationalProject.confirmed_by.is_(None), NationalProject.rejected_by.is_(None)
        )
    rows = db.scalars(stmt).all()
    if ticker is not None:
        rows = [r for r in rows if any(i.ticker == ticker for i in r.impacts)]
    return [NationalProjectOut.from_model(r) for r in rows]


@router.get("/{project_id}", response_model=NationalProjectOut)
def get_national_project(project_id: int, db: Session = Depends(get_db)) -> NationalProjectOut:
    return NationalProjectOut.from_model(_get_or_404(db, project_id))


@router.post("", response_model=NationalProjectOut, status_code=201)
def create_national_project(
    body: NationalProjectCreate, db: Session = Depends(get_db)
) -> NationalProjectOut:
    """Always creates an unconfirmed draft, regardless of what `status`
    is set to — §34's blanket rule is that human confirmation is
    required before ANY entry, at any status, can affect a valuation, so
    there is no "pre-confirmed" creation path."""
    row = NationalProject(
        name=body.name, sponsor=body.sponsor, sector=body.sector,
        financing_source=body.financing_source, capex_lkr=body.capex_lkr,
        capex_usd=body.capex_usd, phase_start_date=body.phase_start_date,
        phase_expected_completion_date=body.phase_expected_completion_date,
        status=body.status, source_url=body.source_url, source_date=body.source_date,
        notes=body.notes,
    )
    db.add(row)
    db.flush()  # assigns row.id for the impacts' foreign key below
    for impact in body.impacts:
        db.add(
            NationalProjectTickerImpact(
                project_id=row.id, ticker=impact.ticker,
                transmission_channel=impact.transmission_channel,
                impact_metric=impact.impact_metric,
                quantified_impact_pct=impact.quantified_impact_pct,
                impact_description=impact.impact_description,
                provenance_tag=impact.provenance_tag,
            )
        )
    db.commit()
    db.refresh(row)
    return NationalProjectOut.from_model(row)


@router.patch("/{project_id}/draft", response_model=NationalProjectOut)
def update_draft(
    project_id: int, patch: NationalProjectDraftUpdate, db: Session = Depends(get_db)
) -> NationalProjectOut:
    row = _get_or_404(db, project_id)
    _require_draft(row)

    updates = patch.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return NationalProjectOut.from_model(row)


@router.post("/{project_id}/impacts", response_model=TickerImpactOut, status_code=201)
def add_impact(
    project_id: int, impact: TickerImpactIn, db: Session = Depends(get_db)
) -> TickerImpactOut:
    row = _get_or_404(db, project_id)
    _require_draft(row)

    impact_row = NationalProjectTickerImpact(
        project_id=project_id, ticker=impact.ticker,
        transmission_channel=impact.transmission_channel, impact_metric=impact.impact_metric,
        quantified_impact_pct=impact.quantified_impact_pct,
        impact_description=impact.impact_description, provenance_tag=impact.provenance_tag,
    )
    db.add(impact_row)
    db.commit()
    db.refresh(impact_row)
    return TickerImpactOut.from_model(impact_row)


@router.delete("/{project_id}/impacts/{impact_id}", status_code=204)
def remove_impact(project_id: int, impact_id: int, db: Session = Depends(get_db)) -> None:
    row = _get_or_404(db, project_id)
    _require_draft(row)

    impact_row = db.get(NationalProjectTickerImpact, impact_id)
    if impact_row is None or impact_row.project_id != project_id:
        raise HTTPException(404, f"no impact with id {impact_id} on project {project_id}")
    db.delete(impact_row)
    db.commit()


@router.post("/{project_id}/confirm", response_model=NationalProjectOut)
def confirm_draft(
    project_id: int, body: ReviewRequest, db: Session = Depends(get_db)
) -> NationalProjectOut:
    row = _get_or_404(db, project_id)
    if row.confirmed_by is not None:
        raise HTTPException(409, "already confirmed")
    if row.rejected_by is not None:
        raise HTTPException(409, "cannot confirm an already-rejected national project")

    for impact in row.impacts:
        try:
            validate_impact_provenance_tag(impact.provenance_tag)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    row.confirmed_by = body.actor
    row.confirmed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(row)
    return NationalProjectOut.from_model(row)


@router.post("/{project_id}/reject", response_model=NationalProjectOut)
def reject_draft(
    project_id: int, body: ReviewRequest, db: Session = Depends(get_db)
) -> NationalProjectOut:
    row = _get_or_404(db, project_id)
    if row.confirmed_by is not None:
        raise HTTPException(409, "cannot reject an already-confirmed national project")
    if row.rejected_by is not None:
        raise HTTPException(409, "already rejected")

    row.rejected_by = body.actor
    row.rejected_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(row)
    return NationalProjectOut.from_model(row)
