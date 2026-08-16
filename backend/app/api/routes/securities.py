"""
Minimal read endpoints. Deliberately not building a screener/ranking API
yet (Phase 2, per ROADMAP.md) — this exists so the data layer is reachable
and testable end to end during Phase 1, matching the UI spec's own
philosophy of "every number is a door": even at this stage, a ticker should
resolve to something inspectable rather than nothing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.reconciliation import is_quarantined
from app.models.securities import Security

router = APIRouter(prefix="/securities", tags=["securities"])


@router.get("")
def list_securities(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Security).order_by(Security.ticker)).all()
    return [
        {
            "ticker": s.ticker,
            "name": s.name,
            "cse_sector": s.cse_sector,
            "archetype": s.archetype,
        }
        for s in rows
    ]


@router.get("/{ticker}")
def get_security(ticker: str, db: Session = Depends(get_db)) -> dict:
    security = db.get(Security, ticker)
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker!r}")
    return {
        "ticker": security.ticker,
        "name": security.name,
        "cse_sector": security.cse_sector,
        "archetype": security.archetype,
        "listing_date": security.listing_date,
        "delisting_date": security.delisting_date,
        "quarantined": is_quarantined(db, ticker),
    }
