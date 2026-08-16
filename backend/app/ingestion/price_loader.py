"""
Reference implementation of the fetch -> validate -> upsert pattern for one
domain (daily prices), demonstrating how every other loader (fundamentals,
corporate actions, float data) should be structured. Endpoint path and
field mapping are unverified — see the warning in app.ingestion.schemas.

Deliberately NOT wired into a scheduler yet (ROADMAP.md): running this
against the real endpoint without having confirmed the schema would risk
silently building a price series on wrong field mappings.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.schemas import TradeSummaryRow
from app.models.prices import PriceDaily

logger = logging.getLogger("cse_alpha.ingestion.price_loader")


def fetch_eod_prices(client: CseClient, as_of: dt.date) -> list[TradeSummaryRow]:
    """§52 job table: "EOD snapshot + adjustment", 15:00 daily. Path is a
    placeholder pending live confirmation."""
    payload = client.get_json("tradeSummary", params={"date": as_of.isoformat()})
    if isinstance(payload, list):
        return [TradeSummaryRow.model_validate(row) for row in payload]
    raise ShapeChangedError("expected tradeSummary to return a JSON array of rows")


def upsert_eod_prices(db: Session, as_of: dt.date, rows: list[TradeSummaryRow]) -> int:
    """Insert-or-update raw OHLCV for `as_of`. Does NOT touch `adj_factor`
    — that is rebuilt separately (and for the *whole* series, backwards)
    whenever a new confirmed corporate action lands, by
    app.jobs.rebuild_adjustment_factors (not yet implemented — Phase 1
    remaining work). Writing adj_factor here would risk it going stale the
    moment an action is confirmed after today's snapshot.
    """
    written = 0
    now = dt.datetime.now(dt.timezone.utc)
    for row in rows:
        existing = db.scalar(
            select(PriceDaily).where(PriceDaily.ticker == row.symbol, PriceDaily.date == as_of)
        )
        if existing is None:
            existing = PriceDaily(ticker=row.symbol, date=as_of, adj_factor=Decimal("1.0"))
            db.add(existing)

        existing.open = _to_decimal(row.open)
        existing.high = _to_decimal(row.high)
        existing.low = _to_decimal(row.low)
        existing.close = _to_decimal(row.close)
        existing.volume = row.volume
        existing.turnover = _to_decimal(row.turnover)
        existing.trades = row.trades
        existing.fetched_at = now
        existing.source = "cse.lk"
        written += 1

    db.commit()
    return written


def _to_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))
