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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.corroboration_view import corroborated_ids
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
    corroborated: bool
    """R1 T2.5: `True` when an INDEPENDENTLY-SOURCED (different
    `source_url`) row already carries `REPORTED` provenance for this same
    (ticker, period_end, statement_line) with the EXACT same
    value — e.g. a later annual report's own comparative column reprinting
    a prior year's figure. This is corroboration, not a guess: two
    independent documents agreeing on the same number. The only case a
    bulk confirm may fire on without a human looking at each individual
    value (see `confirm-batch-corroborated` below) — added directly
    because the 19 Aug 2026 bulk-confirm pass that caused OI-1 (see
    ROADMAP.md / docs/audits/R1_OPEN_ISSUES.md) had no such check at all."""

    @classmethod
    def from_model(cls, row: Fundamental, corroborated: bool = False) -> "FundamentalOut":
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
            corroborated=corroborated,
        )


class FundamentalsPage(BaseModel):
    """One page of the confirm queue, most-recent-period-first. Backs the
    Fundamentals tab's own table — the real backfill (P1.1-era session)
    grew the pending queue past 11,000 rows, so this is paged with SQL
    LIMIT/OFFSET rather than the whole queue shipped and sliced client-
    side (the same real problem `GET /securities/{ticker}/prices` was
    already fixed for)."""

    items: list[FundamentalOut]
    total: int
    limit: int
    offset: int


class ValueCorrection(BaseModel):
    """A reviewer may correct a mis-extracted value before confirming —
    e.g. the extractor picked the wrong column. This is still not a
    restatement (§6), so it does not bump `version`."""

    value: Decimal


class ConfirmRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    correction: ValueCorrection | None = None


class ConfirmBatchRequest(BaseModel):
    """The Fundamentals tab's own "select all, confirm multiples" —
    deliberately no per-row `correction` here: a reviewer who needs to
    fix a value before confirming uses the single-row Confirm, which
    still supports that. This is for the rows a reviewer already looked
    at and trusts as extracted."""

    actor: str = Field(min_length=1, max_length=100)
    ids: list[int] = Field(min_length=1, max_length=200)


class ConfirmBatchFailure(BaseModel):
    id: int
    reason: str


class ConfirmBatchResult(BaseModel):
    confirmed: list[int]
    failed: list[ConfirmBatchFailure]
    """One bad id (already confirmed by someone else since the page was
    loaded, not AI-assisted, unknown) never aborts the rest of the batch
    — the same "one bad row doesn't abort the sweep" discipline every
    ingestion loop in this codebase already follows, reported back per-id
    rather than silently skipped."""


def _get_or_404(db: Session, fundamental_id: int) -> Fundamental:
    row = db.get(Fundamental, fundamental_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no fundamental with id {fundamental_id}")
    return row


@router.get("", response_model=FundamentalsPage)
def list_fundamentals(
    ticker: str | None = None,
    pending_only: bool = True,
    limit: int = Query(20, ge=1, le=200, description="page size — the Fundamentals tab defaults to 20"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> FundamentalsPage:
    """Default view is the confirm queue: AI-assisted rows not yet
    confirmed. Pass `pending_only=false` for everything, e.g. to inspect
    a company's full reported history.

    Paged with SQL LIMIT/OFFSET, same shape and same real reason as
    `GET /securities/{ticker}/prices`: a real backfill grew this queue
    past 11,000 pending rows, and shipping the whole thing to render a
    20-row page client-side is exactly the mistake that endpoint was
    already fixed for.
    """
    filters = []
    if ticker is not None:
        filters.append(Fundamental.ticker == ticker)
    if pending_only:
        filters.append(Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED)
        filters.append(Fundamental.confirmed_by.is_(None))

    total = db.scalar(select(func.count()).select_from(Fundamental).where(*filters)) or 0

    rows = db.scalars(
        select(Fundamental)
        .where(*filters)
        .order_by(Fundamental.period_end.desc(), Fundamental.statement_line)
        .limit(limit)
        .offset(offset)
    ).all()

    corroborated = corroborated_ids(db, rows) if pending_only else set()

    return FundamentalsPage(
        items=[FundamentalOut.from_model(r, corroborated=r.id in corroborated) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


class QueueBucket(BaseModel):
    key: str
    count: int


class FundamentalsQueueSummary(BaseModel):
    """Queue-wide shape of the pending confirm backlog — what the redesign
    doc (§3.2) calls "classify by type, not FIFO". Lets the Confirm queue
    screen show WHERE the backlog is (which line items, which periods,
    which tickers) and how OLD it is, rather than only its total size.

    Computed over the whole pending set, not the current page — so it is
    deliberately a separate endpoint from the paged `GET /fundamentals`,
    the same split `GET /data-health` already uses for its own counts.
    """

    pending_total: int
    by_statement_line: list[QueueBucket]
    by_period_type: list[QueueBucket]
    by_ticker: list[QueueBucket]
    """Top tickers by pending-figure count (at most 10)."""

    oldest_pending_first_available: dt.date | None
    pending_filed_over_a_year_ago: int
    """Pending figures whose FILING is more than a year old — a real
    "old, still-unreviewed data" signal (§18: staleness is surfaced, not
    hidden). This is filing age (`first_available_date`), NOT time-sat-in-
    queue: nothing records when a row entered the queue, so this is the
    honest available proxy, named as such rather than dressed up as a
    queue-wait age."""

    corroborated_pending: int
    """How many pending figures the nightly `auto_confirm_corroborated_
    fundamentals` job would clear on its next run — an independently-
    sourced REPORTED row already carries the exact same value."""


@router.get("/summary", response_model=FundamentalsQueueSummary)
def fundamentals_queue_summary(db: Session = Depends(get_db)) -> FundamentalsQueueSummary:
    from app.domain.corroboration_view import all_corroborated_pending_ids

    pending = (
        Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
        Fundamental.confirmed_by.is_(None),
    )

    total = db.scalar(select(func.count()).select_from(Fundamental).where(*pending)) or 0

    def _buckets(column, limit: int | None) -> list[QueueBucket]:
        stmt = (
            select(column, func.count())
            .where(*pending)
            .group_by(column)
            .order_by(func.count().desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [QueueBucket(key=str(k), count=c) for k, c in db.execute(stmt).all()]

    oldest = db.scalar(select(func.min(Fundamental.first_available_date)).where(*pending))
    a_year_ago = dt.date.today() - dt.timedelta(days=365)
    older_than_year = (
        db.scalar(
            select(func.count())
            .select_from(Fundamental)
            .where(*pending, Fundamental.first_available_date < a_year_ago)
        )
        or 0
    )

    return FundamentalsQueueSummary(
        pending_total=total,
        by_statement_line=_buckets(Fundamental.statement_line, 12),
        by_period_type=_buckets(Fundamental.period_type, None),
        by_ticker=_buckets(Fundamental.ticker, 10),
        oldest_pending_first_available=oldest,
        pending_filed_over_a_year_ago=older_than_year,
        corroborated_pending=len(all_corroborated_pending_ids(db)),
    )


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


@router.post("/confirm-batch", response_model=ConfirmBatchResult)
def confirm_fundamentals_batch(
    body: ConfirmBatchRequest, db: Session = Depends(get_db)
) -> ConfirmBatchResult:
    """The Fundamentals tab's own bulk "select all, confirm multiples" —
    same promotion the single-row endpoint does, exactly the same
    validation per row, just applied to a whole page's worth of ids in
    one request instead of N round trips. See `ConfirmBatchResult`'s own
    docstring for why one bad id doesn't fail the batch.
    """
    confirmed: list[int] = []
    failed: list[ConfirmBatchFailure] = []

    for fundamental_id in body.ids:
        row = db.get(Fundamental, fundamental_id)
        if row is None:
            failed.append(ConfirmBatchFailure(id=fundamental_id, reason="no fundamental with this id"))
            continue
        if row.confirmed_by is not None:
            failed.append(ConfirmBatchFailure(id=fundamental_id, reason="already confirmed"))
            continue
        if row.provenance_tier != ProvenanceTier.AI_ASSISTED:
            failed.append(
                ConfirmBatchFailure(
                    id=fundamental_id,
                    reason=f"not AI-assisted (tier {row.provenance_tier.value})",
                )
            )
            continue

        row.provenance_tier = ProvenanceTier.REPORTED
        row.confirmed_by = body.actor
        row.confirmed_at = dt.datetime.now(dt.timezone.utc)
        assert can_enter_valuation(row.provenance_tier)  # the whole point of this endpoint
        confirmed.append(fundamental_id)

    db.commit()
    return ConfirmBatchResult(confirmed=confirmed, failed=failed)


@router.post("/confirm-batch-corroborated", response_model=ConfirmBatchResult)
def confirm_fundamentals_batch_corroborated(
    body: ConfirmBatchRequest, db: Session = Depends(get_db)
) -> ConfirmBatchResult:
    """R1 T2.5's real, safe bulk-confirm path — the ONE case the brief
    permits one-click confirmation without a human individually reviewing
    every value: an INDEPENDENTLY-SOURCED row already carries REPORTED
    provenance for the exact same figure (see `FundamentalOut.
    corroborated`'s own docstring for why this is corroboration, not an
    assumption). Every id is re-verified against the database HERE,
    server-side — a client claiming a row is corroborated when it isn't
    gets it rejected into `failed`, exactly like every other validation
    this batch endpoint already enforces; the corroboration flag returned
    by `GET /fundamentals` is a UI hint, never trusted as the actual gate.
    `confirmed_by` is stamped with a distinct, searchable marker so this
    action is never confused in an audit trail with a genuine per-row
    human review."""
    rows = [db.get(Fundamental, i) for i in body.ids]
    real_rows = [r for r in rows if r is not None and r.provenance_tier == ProvenanceTier.AI_ASSISTED
                 and r.confirmed_by is None]
    corroborated = corroborated_ids(db, real_rows)

    confirmed: list[int] = []
    failed: list[ConfirmBatchFailure] = []

    for fundamental_id, row in zip(body.ids, rows):
        if row is None:
            failed.append(ConfirmBatchFailure(id=fundamental_id, reason="no fundamental with this id"))
            continue
        if row.confirmed_by is not None:
            failed.append(ConfirmBatchFailure(id=fundamental_id, reason="already confirmed"))
            continue
        if row.provenance_tier != ProvenanceTier.AI_ASSISTED:
            failed.append(
                ConfirmBatchFailure(id=fundamental_id, reason=f"not AI-assisted (tier {row.provenance_tier.value})")
            )
            continue
        if fundamental_id not in corroborated:
            failed.append(
                ConfirmBatchFailure(
                    id=fundamental_id,
                    reason="no independently-sourced REPORTED row with the same value exists — "
                    "not corroborated, use the per-row Confirm instead",
                )
            )
            continue

        row.provenance_tier = ProvenanceTier.REPORTED
        row.confirmed_by = f"{body.actor} (corroborated bulk confirm)"
        row.confirmed_at = dt.datetime.now(dt.timezone.utc)
        assert can_enter_valuation(row.provenance_tier)
        confirmed.append(fundamental_id)

    db.commit()
    return ConfirmBatchResult(confirmed=confirmed, failed=failed)
