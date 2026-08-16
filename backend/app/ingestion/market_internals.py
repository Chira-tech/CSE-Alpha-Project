"""
Daily market internals from `dailyMarketSummery` into `macro_series`.

§29's variable set includes "ASPI turnover, foreign net flow,
advance-decline, market-wide earnings yield" under Market internals, and
this endpoint carries most of them. It is the source of the earnings-yield
half of the hero spread (market P/E -> 1/PE).

POINT-IN-TIME NOTE: these are end-of-session figures published the same
day, so `first_available_date` equals `obs_date`. That is genuinely true
here and must not be copy-pasted to CBSL series, where a figure for June
is typically released weeks into July — filing that under June would be
exactly the look-ahead §6 forbids.

The endpoint returns only the last couple of sessions, so this
accumulates forward like the price series. Nothing back-fills it.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.macro import (
    SERIES_ASPI,
    SERIES_FOREIGN_NET,
    SERIES_MARKET_CAP,
    SERIES_MARKET_DY,
    SERIES_MARKET_PBV,
    SERIES_MARKET_PER,
    SERIES_MARKET_TURNOVER,
    SERIES_SP_SL20,
)
from app.ingestion.cse_client import CseClient
from app.ingestion.schemas import DailyMarketSummaryRow
from app.models.macro import MacroSeries

logger = logging.getLogger("cse_alpha.ingestion.market_internals")

_SRI_LANKA_TZ = ZoneInfo("Asia/Colombo")
_SOURCE = "cse.lk"


def fetch_daily_market_summary(client: CseClient) -> list[DailyMarketSummaryRow]:
    """The endpoint returns a list of single-element lists — one wrapper
    per trading day (verified live, see README_ENDPOINTS.md)."""
    payload = client.post_json("dailyMarketSummery", body={})
    rows: list[DailyMarketSummaryRow] = []
    if not isinstance(payload, list):
        return rows
    for entry in payload:
        candidate = entry[0] if isinstance(entry, list) and entry else entry
        if not isinstance(candidate, dict):
            continue
        try:
            rows.append(DailyMarketSummaryRow.model_validate(candidate))
        except Exception:  # noqa: BLE001 — skip one malformed day, keep the rest
            logger.warning("skipping unparseable daily market summary entry")
    return rows


def _to_decimal(value: float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _series_values(row: DailyMarketSummaryRow) -> dict[str, Decimal]:
    """Only fields actually present are returned — a missing field means
    no row is written, rather than a zero being recorded (§4 Law 3)."""
    foreign_net = None
    if row.equityForeignPurchase is not None and row.equityForeignSales is not None:
        foreign_net = Decimal(str(row.equityForeignPurchase)) - Decimal(str(row.equityForeignSales))

    candidates = {
        SERIES_MARKET_PER: _to_decimal(row.per),
        SERIES_MARKET_PBV: _to_decimal(row.pbv),
        # CSE publishes dividend yield as a percentage (3.0 = 3%); stored
        # as a decimal fraction so it is directly comparable with the
        # earnings yield and the T-bill yield. Mixing the two conventions
        # is how a spread ends up wrong by 100x while still looking sane.
        SERIES_MARKET_DY: (Decimal(str(row.dy)) / 100 if row.dy is not None else None),
        SERIES_ASPI: _to_decimal(row.asi),
        SERIES_SP_SL20: _to_decimal(row.spt),
        SERIES_MARKET_TURNOVER: _to_decimal(row.marketTurnover),
        SERIES_MARKET_CAP: _to_decimal(row.marketCap),
        SERIES_FOREIGN_NET: foreign_net,
    }
    return {k: v for k, v in candidates.items() if v is not None}


def upsert_market_internals(db: Session, rows: list[DailyMarketSummaryRow]) -> int:
    """Returns the number of observations written. Existing rows are left
    alone: a published end-of-session figure does not change, and
    silently overwriting one would destroy the point-in-time record if
    the feed ever revised it."""
    written = 0
    for row in rows:
        obs_date = dt.datetime.fromtimestamp(row.tradeDate / 1000, tz=_SRI_LANKA_TZ).date()
        for series_id, value in _series_values(row).items():
            existing = db.scalar(
                select(MacroSeries).where(
                    MacroSeries.series_id == series_id, MacroSeries.obs_date == obs_date
                )
            )
            if existing is not None:
                continue
            db.add(
                MacroSeries(
                    series_id=series_id,
                    obs_date=obs_date,
                    # End-of-session figures are public the same day —
                    # true here, NOT true for CBSL series.
                    first_available_date=obs_date,
                    value=value,
                    source=_SOURCE,
                )
            )
            written += 1

    if written:
        db.commit()
    return written


def ingest_market_internals(client: CseClient, db: Session) -> int:
    return upsert_market_internals(db, fetch_daily_market_summary(client))
