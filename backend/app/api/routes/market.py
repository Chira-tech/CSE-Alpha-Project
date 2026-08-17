"""
Live market overview — ASPI and the S&P/CSE sector indices.

IMPORTANT, and reflected in the response shape: this is a **live
passthrough** to the CSE API, not a query against our own point-in-time
store. Nothing here is persisted, so nothing here is subject to the §6
first_available_date discipline — which is fine for "what is the market
doing right now", and would NOT be fine as an input to any model. Every
response carries `fetched_at` and a `source` note so a caller can never
mistake it for stored, versioned data.

Two behaviours worth knowing about:

1. PARTIAL RESPONSES, NOT ALL-OR-NOTHING. Each upstream call is made
   independently and a failure degrades that section only — the response
   carries an `unavailable` list naming what couldn't be fetched and why.
   UI spec §15.1 requires a Partial state that "renders what exists,
   marks what does not"; returning 502 for the whole screen because one
   of three endpoints hiccuped is exactly the all-or-nothing failure that
   rule exists to prevent.

2. SHORT-LIVED CACHE. Master Spec §5 requires >=2s pacing between calls,
   so three sequential fetches cost ~4.5s wall-clock. Without a cache
   every page load (and every React StrictMode double-render in dev) pays
   that again and hammers an unofficial endpoint we're meant to treat
   gently. 60s matches the spirit of §52's 5-minute price cadence while
   keeping the screen feeling live.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.macro import SERIES_ASPI, SERIES_MARKET_PER
from app.domain.macro_view import (
    current_spread,
    latest_observation,
    risk_free_observation,
    series_history,
    spread_history,
)
from app.domain.sector_sensitivity_view import sector_sensitivity_matrix_for
from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.schemas import AspiData, SectorIndexRow

logger = logging.getLogger("cse_alpha.api.market")

router = APIRouter(prefix="/market", tags=["market"])

_CACHE_TTL_SECONDS = 60.0


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


class UnavailableSection(BaseModel):
    section: str
    reason: str


class MarketOverview(BaseModel):
    status: str | None
    aspi: IndexSnapshot | None
    sectors: list[SectorSnapshot]
    unavailable: list[UnavailableSection]
    fetched_at: dt.datetime
    cached: bool = False
    source: str = "cse.lk (live passthrough — not stored, not point-in-time)"


_cache: tuple[float, MarketOverview] | None = None
_cache_lock = threading.Lock()


def _describe(exc: Exception) -> str:
    """A reason string a human can act on, not a stack trace (§15.1)."""
    if isinstance(exc, ShapeChangedError):
        return (
            "the CSE API returned a response shape this system doesn't recognise — "
            "the upstream feed has likely changed and the loader needs updating"
        )
    return f"the CSE API could not be reached ({type(exc).__name__})"


def _build_overview() -> MarketOverview:
    status: str | None = None
    aspi: IndexSnapshot | None = None
    sectors: list[SectorSnapshot] = []
    unavailable: list[UnavailableSection] = []

    with CseClient() as client:
        try:
            payload = client.post_json("marketStatus")
            if isinstance(payload, dict):
                status = str(payload.get("status", "unknown"))
        except Exception as exc:  # noqa: BLE001 — unofficial upstream, many failure modes
            logger.warning("marketStatus unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="Market status", reason=_describe(exc)))

        try:
            payload = client.post_json("aspiData", model=AspiData)
            if isinstance(payload, AspiData):
                aspi = IndexSnapshot(
                    value=payload.value,
                    change=payload.change,
                    percentage=payload.percentage,
                    low=payload.lowValue,
                    high=payload.highValue,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("aspiData unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="All Share Price Index", reason=_describe(exc)))

        try:
            payload = client.post_json("allSectors")
            if isinstance(payload, list):
                for raw in payload:
                    try:
                        row = SectorIndexRow.model_validate(raw)
                    except Exception:  # noqa: BLE001 — skip one bad row, keep the rest
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("allSectors unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="Sector indices", reason=_describe(exc)))

    return MarketOverview(
        status=status,
        aspi=aspi,
        sectors=sorted(sectors, key=lambda s: s.name),
        unavailable=unavailable,
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )


class SpreadPoint(BaseModel):
    obs_date: dt.date
    earnings_yield: Decimal
    tbill_yield: Decimal
    spread: Decimal


class SpreadOut(BaseModel):
    """§29's hero variable. `available` is False when either input is
    missing, with `missing` naming which — never a zero or a stale
    figure, because the cost of equity and the regime read are both
    built on this."""

    available: bool
    missing: list[str]
    obs_date: dt.date | None = None
    market_per: Decimal | None = None
    earnings_yield: Decimal | None = None
    tbill_yield: Decimal | None = None
    tbill_obs_date: dt.date | None = None
    tbill_source: str | None = None
    spread: Decimal | None = None
    history: list[SpreadPoint] = []


@router.get("/spread", response_model=SpreadOut)
def equity_tbill_spread(db: Session = Depends(get_db)) -> SpreadOut:
    current = current_spread(db)
    if current is None:
        missing: list[str] = []
        if latest_observation(db, SERIES_MARKET_PER) is None:
            missing.append("market P/E (run `python -m app.cli capture-market`)")
        if risk_free_observation(db) is None:
            missing.append(
                "364-day T-bill yield (run `python -m app.cli cbsl --days 10`)"
            )
        return SpreadOut(available=False, missing=missing)

    return SpreadOut(
        available=True,
        missing=[],
        obs_date=current.obs_date,
        market_per=current.market_per,
        earnings_yield=current.earnings_yield,
        tbill_yield=current.tbill_yield,
        tbill_obs_date=current.tbill_obs_date,
        tbill_source=current.tbill_source,
        spread=current.spread,
        history=[
            SpreadPoint(
                obs_date=p.obs_date,
                earnings_yield=p.earnings_yield,
                tbill_yield=p.tbill_yield,
                spread=p.spread,
            )
            for p in spread_history(db)
        ],
    )


class IndexPoint(BaseModel):
    obs_date: dt.date
    value: Decimal
    source: str


class IndexHistoryOut(BaseModel):
    """ASPI closing levels. `recovered` counts the rows whose close was
    reconstructed from the feed's percentage change rather than read
    directly — see `app.domain.index_history` for why that distinction
    is load-bearing rather than cosmetic."""

    series_id: str
    points: list[IndexPoint]
    recovered: int


@router.get("/index-history", response_model=IndexHistoryOut)
def index_history(db: Session = Depends(get_db)) -> IndexHistoryOut:
    rows = series_history(db, SERIES_ASPI, limit=400)
    return IndexHistoryOut(
        series_id=SERIES_ASPI,
        points=[
            IndexPoint(obs_date=r.obs_date, value=r.value, source=r.source) for r in rows
        ],
        recovered=sum(1 for r in rows if r.source.endswith("(pc)")),
    )


class SensitivityEstimateOut(BaseModel):
    shock_name: str
    coefficient: Decimal
    p_value: Decimal
    r_squared: Decimal
    observation_count: int
    significant: bool
    direction_label: str


class SectorSensitivityRowOut(BaseModel):
    sector: str
    constituent_count: int
    estimates: list[SensitivityEstimateOut]


class SectorSensitivityOut(BaseModel):
    """§33's sector sensitivity matrix — a real, estimated regression of
    each sector's daily return on real macro shock series, never a
    hard-coded relationship (§33's own explicit warning). See
    `app.domain.sector_sensitivity`'s own module docstring for exactly
    which shocks are real and why §33's own illustrative Oil/Tourism/
    Fiscal columns aren't among them."""

    as_of: dt.date
    rows: list[SectorSensitivityRowOut]
    thin_sectors: list[list[object]]
    """`[sector, constituent_count]` pairs for a sector with a real
    `cse_sector` assignment but too few real tickers to estimate from —
    named, not silently dropped."""

    shocks_used: list[str]
    warnings: list[str]


@router.get("/sector-sensitivity", response_model=SectorSensitivityOut)
def sector_sensitivity(db: Session = Depends(get_db)) -> SectorSensitivityOut:
    view = sector_sensitivity_matrix_for(db)
    return SectorSensitivityOut(
        as_of=view.as_of,
        rows=[
            SectorSensitivityRowOut(
                sector=row.sector,
                constituent_count=row.constituent_count,
                estimates=[
                    SensitivityEstimateOut(
                        shock_name=e.shock_name,
                        coefficient=e.coefficient,
                        p_value=e.p_value,
                        r_squared=e.r_squared,
                        observation_count=e.observation_count,
                        significant=e.significant,
                        direction_label=e.direction_label,
                    )
                    for e in row.estimates
                ],
            )
            for row in view.rows
        ],
        thin_sectors=[[sector, count] for sector, count in view.thin_sectors],
        shocks_used=list(view.shocks_used),
        warnings=list(view.warnings),
    )


@router.get("", response_model=MarketOverview)
def market_overview(refresh: bool = False) -> MarketOverview:
    """`refresh=true` bypasses the cache — for an explicit user-initiated
    refresh. Never auto-refresh on a timer: UI spec §17 forbids
    "auto-refresh that moves content under the cursor"."""
    global _cache

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    with _cache_lock:
        if not refresh and _cache is not None:
            cached_at, cached_value = _cache
            if now - cached_at < _CACHE_TTL_SECONDS:
                return cached_value.model_copy(update={"cached": True})

    overview = _build_overview()

    # Only cache a response that actually got something — otherwise a
    # transient outage would be pinned for the full TTL.
    if overview.aspi is not None or overview.sectors:
        with _cache_lock:
            _cache = (now, overview)

    return overview
