"""
Master Spec §52 job table: "EOD snapshot + adjustment", 15:00 daily.

Reference implementation of the fetch -> validate -> upsert pattern,
verified against the live cse.lk API on 16 Aug 2026 (POST tradeSummary with
JSON body `{}` — see app.ingestion.cse_client and README_ENDPOINTS.md).
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.cse_client import CseClient
from app.ingestion.schemas import TradeSummaryResponse, TradeSummaryRow
from app.models.prices import PriceDaily

logger = logging.getLogger("cse_alpha.ingestion.price_loader")

_SRI_LANKA_TZ = ZoneInfo("Asia/Colombo")


def infer_session_date(rows: list[TradeSummaryRow]) -> dt.date | None:
    """The trading date these prices actually belong to, derived from the
    feed's own `lastTradedTime` rather than assumed to be today.

    This matters more than it looks. `tradeSummary` always returns the
    LAST COMPLETED session, so ingesting on a Sunday (or a public
    holiday, or before the market opens) and stamping the rows with
    today's date silently files Friday's prices under Sunday — a
    fabricated observation on a date the market never traded. Master Spec
    §6's whole point is that a record's date must be the date the market
    could actually have seen it; getting this wrong corrupts every return
    calculation built on top of the series.

    Uses the modal date across all rows, not the max: a single stale or
    mis-stamped row shouldn't drag the whole session's date with it.
    Returns None if no row carries a timestamp, and the caller must then
    decide explicitly rather than guessing.
    """
    dates = [
        dt.datetime.fromtimestamp(r.lastTradedTime / 1000, tz=_SRI_LANKA_TZ).date()
        for r in rows
        if r.lastTradedTime
    ]
    if not dates:
        return None
    return collections.Counter(dates).most_common(1)[0][0]


def fetch_eod_prices(client: CseClient) -> list[TradeSummaryRow]:
    response = client.post_json("tradeSummary", model=TradeSummaryResponse, body={})
    assert isinstance(response, TradeSummaryResponse)  # narrows for type checkers
    return response.reqTradeSummery


def upsert_eod_prices(db: Session, as_of: dt.date, rows: list[TradeSummaryRow]) -> int:
    """Insert-or-update raw OHLCV for `as_of`. Does NOT touch `adj_factor`
    — that is rebuilt separately (and for the *whole* series, backwards)
    whenever a new confirmed corporate action lands, by
    app.jobs.rebuild_adjustment_factors (not yet implemented — Phase 1
    remaining work per ROADMAP.md). Writing adj_factor here would risk it
    going stale the moment an action is confirmed after today's snapshot.
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
        existing.close = _to_decimal(row.closingPrice if row.closingPrice is not None else row.price)
        existing.volume = row.sharevolume
        existing.turnover = _to_decimal(row.turnover)
        existing.trades = row.tradevolume
        existing.fetched_at = now
        existing.source = "cse.lk"
        written += 1

    db.commit()
    return written


def _to_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))
