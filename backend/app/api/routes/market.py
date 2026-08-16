"""
Live market overview — ASPI and the S&P/CSE sector indices.

IMPORTANT, and reflected in the response shape: this is a **live
passthrough** to the CSE API, not a query against our own point-in-time
store. Nothing here is persisted, so nothing here is subject to the §6
first_available_date discipline — which is fine for "what is the market
doing right now", and would NOT be fine as an input to any model. Every
response carries `fetched_at` and `source: "cse.lk (live)"` so a caller
can never mistake it for stored, versioned data.

When the macro engine lands (Phase 5, §29-33) these series get ingested
into `macro_series` properly, with release dates, and the hero chart
becomes the earnings-yield-minus-T-bill spread (§29) rather than a raw
index level.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.schemas import AspiData, SectorIndexRow

router = APIRouter(prefix="/market", tags=["market"])


class IndexSnapshot(BaseModel):
    value: float | None
    change: float | None
    percentage: float | None
    low: float | None = None
    high: float | None = None


class SectorSnapshot(BaseModel):
    name: str
    symbol: str | None
    index_value: float | None
    change: float | None
    percentage: float | None
    turnover_today: float | None


class MarketOverview(BaseModel):
    status: str
    aspi: IndexSnapshot | None
    sectors: list[SectorSnapshot]
    fetched_at: dt.datetime
    source: str = "cse.lk (live passthrough — not stored, not point-in-time)"


@router.get("", response_model=MarketOverview)
def market_overview() -> MarketOverview:
    try:
        with CseClient() as client:
            status_payload = client.post_json("marketStatus")
            aspi_payload = client.post_json("aspiData", model=AspiData)
            sectors_payload = client.post_json("allSectors")
    except ShapeChangedError as exc:
        # §5: a shape change must surface loudly, never as silently-wrong
        # data. 502 (not 500) because the upstream is what changed.
        raise HTTPException(502, f"CSE API response shape changed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — upstream is unofficial and fails in many ways
        raise HTTPException(502, f"CSE API unavailable: {exc}") from exc

    status = "unknown"
    if isinstance(status_payload, dict):
        status = str(status_payload.get("status", "unknown"))

    aspi = None
    if isinstance(aspi_payload, AspiData):
        aspi = IndexSnapshot(
            value=aspi_payload.value,
            change=aspi_payload.change,
            percentage=aspi_payload.percentage,
            low=aspi_payload.lowValue,
            high=aspi_payload.highValue,
        )

    sectors: list[SectorSnapshot] = []
    if isinstance(sectors_payload, list):
        for raw in sectors_payload:
            try:
                row = SectorIndexRow.model_validate(raw)
            except Exception:  # noqa: BLE001 — skip an unparseable row rather than failing the whole screen
                continue
            sectors.append(
                SectorSnapshot(
                    name=row.name,
                    symbol=row.symbol,
                    index_value=row.indexValue,
                    change=row.change,
                    percentage=row.percentage,
                    turnover_today=row.sectorTurnoverToday,
                )
            )

    return MarketOverview(
        status=status,
        aspi=aspi,
        sectors=sorted(sectors, key=lambda s: s.name),
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )
