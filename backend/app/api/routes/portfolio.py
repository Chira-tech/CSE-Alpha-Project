"""
A real, user-uploaded CDS/broker portfolio export becomes this system's
own real record of "what do I currently hold" — see `app/models/
portfolio.py`'s own module docstring for the full scope: this is the
narrow, real, immediately useful slice of Master Spec §41's eventual
portfolio engine (current holdings from a real file), not the full
transaction-log/realised-P&L/thesis-drift engine Phase 8 still owns.

FILE UPLOAD, THE FIRST IN THIS SYSTEM. `UploadFile` streams the real
bytes the user's browser sends; nothing here trusts the filename or
content type beyond using the filename for a human-readable label on the
stored snapshot. The file itself is parsed, not executed or evaluated —
`app.ingestion.portfolio_import.read_portfolio_workbook` uses openpyxl's
own real `.xlsx` reader, the same real, respected library every other
real file format in this system is read with real libraries (pdfplumber
for PDFs, httpx for HTTP) rather than a hand-rolled parser.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.portfolio_import_parsing import parse_portfolio_export
from app.domain.portfolio_import_view import (
    latest_snapshot,
    list_snapshots,
    store_portfolio_snapshot,
    unrecognized_tickers,
)
from app.domain.portfolio_valuation_view import value_portfolio
from app.ingestion.portfolio_import import read_portfolio_workbook
from app.models.portfolio import PortfolioSnapshot

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


class PositionOut(BaseModel):
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
    traded_price: Decimal | None
    market_value: Decimal | None
    unrealized_gain_loss: Decimal | None

    @classmethod
    def from_model(cls, row) -> "PositionOut":
        return cls(
            ticker=row.ticker, quantity=row.quantity, avg_price=row.avg_price,
            total_cost=row.total_cost, traded_price=row.traded_price,
            market_value=row.market_value, unrealized_gain_loss=row.unrealized_gain_loss,
        )


class SnapshotSummaryOut(BaseModel):
    """Metadata only, no positions — the light-weight shape for listing
    upload history."""

    id: int
    uploaded_at: dt.datetime
    source_filename: str
    position_count: int
    stated_total_cost: Decimal | None
    stated_total_market_value: Decimal | None
    identity_check_passed: bool
    identity_check_note: str

    @classmethod
    def from_model(cls, snapshot: PortfolioSnapshot) -> "SnapshotSummaryOut":
        return cls(
            id=snapshot.id, uploaded_at=snapshot.uploaded_at, source_filename=snapshot.source_filename,
            position_count=len(snapshot.positions), stated_total_cost=snapshot.stated_total_cost,
            stated_total_market_value=snapshot.stated_total_market_value,
            identity_check_passed=snapshot.identity_check_passed,
            identity_check_note=snapshot.identity_check_note,
        )


class SnapshotDetailOut(SnapshotSummaryOut):
    positions: list[PositionOut]
    unrecognized_tickers: list[str]
    """Real held tickers this system's own `securities` table doesn't
    currently carry — named, never silently dropped."""


def _detail_out(db: Session, snapshot: PortfolioSnapshot) -> SnapshotDetailOut:
    summary = SnapshotSummaryOut.from_model(snapshot)
    return SnapshotDetailOut(
        **summary.model_dump(),
        positions=[PositionOut.from_model(p) for p in snapshot.positions],
        unrecognized_tickers=unrecognized_tickers(db, snapshot),
    )


@router.post("/upload", response_model=SnapshotDetailOut)
async def upload_portfolio(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> SnapshotDetailOut:
    """Every upload creates a new, permanent snapshot — never overwrites
    an earlier one (see `app/models/portfolio.py`'s own docstring)."""
    file_bytes = await file.read()
    try:
        rows = read_portfolio_workbook(file_bytes)
    except Exception as exc:  # noqa: BLE001 — openpyxl raises several distinct exception types on a bad file
        raise HTTPException(400, f"could not read this file as a real .xlsx workbook: {exc}") from exc

    parsed = parse_portfolio_export(rows)
    if parsed is None:
        raise HTTPException(
            422,
            "this file doesn't match a recognised portfolio export shape — no row with the "
            "expected column headers (Security, Quantity, Avg Price, Total Cost, ...) was found",
        )

    snapshot = store_portfolio_snapshot(db, parsed, source_filename=file.filename or "upload.xlsx")
    return _detail_out(db, snapshot)


@router.get("/holdings", response_model=SnapshotDetailOut | None)
def current_holdings(db: Session = Depends(get_db)) -> SnapshotDetailOut | None:
    """The most recently uploaded real snapshot — "what do I currently
    hold." `None` (not an empty snapshot) when nothing has ever been
    uploaded."""
    snapshot = latest_snapshot(db)
    return _detail_out(db, snapshot) if snapshot is not None else None


@router.get("/snapshots", response_model=list[SnapshotSummaryOut])
def snapshots(db: Session = Depends(get_db)) -> list[SnapshotSummaryOut]:
    return [SnapshotSummaryOut.from_model(s) for s in list_snapshots(db)]


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetailOut)
def snapshot_detail(snapshot_id: int, db: Session = Depends(get_db)) -> SnapshotDetailOut:
    snapshot = db.get(PortfolioSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, f"no portfolio snapshot with id {snapshot_id}")
    return _detail_out(db, snapshot)


class ValuedPositionOut(BaseModel):
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
    snapshot_traded_price: Decimal | None
    snapshot_market_value: Decimal | None
    snapshot_unrealized_gain_loss: Decimal | None
    live_current_price: Decimal | None
    live_market_value: Decimal | None
    live_unrealized_gain_loss: Decimal | None
    blended_fair_value_per_share: Decimal | None
    price_ladder_zone: str | None
    buy_below_price: Decimal | None
    margin_of_safety_pct: Decimal | None
    dispersion_pct: Decimal | None
    warnings: list[str]


class ValuedPortfolioOut(BaseModel):
    """This system's own real valuation engine, run against a real
    uploaded portfolio's own real holdings — see `app.domain.portfolio_
    valuation_view`'s own docstring for the full "snapshot vs live,
    never conflated" reasoning. A position this system can't yet value
    (an unrecognised ticker, no real price history, no confirmed
    fundamentals) still appears, with its own `warnings` naming why."""

    snapshot_id: int
    as_of: dt.date
    positions: list[ValuedPositionOut]
    total_cost: Decimal
    total_live_market_value: Decimal | None
    positions_missing_a_live_price: list[str]


@router.get("/holdings/valued", response_model=ValuedPortfolioOut | None)
def current_holdings_valued(db: Session = Depends(get_db)) -> ValuedPortfolioOut | None:
    """The latest real snapshot, run through this system's own real
    valuation engine for every position. `None` when nothing has ever
    been uploaded."""
    snapshot = latest_snapshot(db)
    if snapshot is None:
        return None
    result = value_portfolio(db, snapshot)
    return ValuedPortfolioOut(
        snapshot_id=result.snapshot_id, as_of=result.as_of,
        positions=[
            ValuedPositionOut(
                ticker=p.ticker, quantity=p.quantity, avg_price=p.avg_price, total_cost=p.total_cost,
                snapshot_traded_price=p.snapshot_traded_price, snapshot_market_value=p.snapshot_market_value,
                snapshot_unrealized_gain_loss=p.snapshot_unrealized_gain_loss,
                live_current_price=p.live_current_price, live_market_value=p.live_market_value,
                live_unrealized_gain_loss=p.live_unrealized_gain_loss,
                blended_fair_value_per_share=p.blended_fair_value_per_share,
                price_ladder_zone=p.price_ladder_zone, buy_below_price=p.buy_below_price,
                margin_of_safety_pct=p.margin_of_safety_pct, dispersion_pct=p.dispersion_pct,
                warnings=list(p.warnings),
            )
            for p in result.positions
        ],
        total_cost=result.total_cost, total_live_market_value=result.total_live_market_value,
        positions_missing_a_live_price=list(result.positions_missing_a_live_price),
    )
