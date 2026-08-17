"""
§18-26 exposed for one company — the first Phase 3 endpoint that returns
an actual fair value rather than routing metadata or a discount rate.

`securities.py`'s own module docstring said, until this file existed,
that fair values and buy-below prices are "deliberately absent... Phase
2/3 (§12-26) and the engines that compute them do not exist yet." That's
now only half true: the engines exist (`app/domain/dcf.py` through
`price_ladder.py`) and two of them — justified P/B and residual income —
are wired to live data as full triangulation anchors
(`app.domain.valuation_view`). A third live number, `current_period_
fcff`, is now real too (§18.1's FCFF formula on one confirmed period) but
deliberately informational only, never an anchor — see `app.domain.
valuation_view.current_period_fcff_for`'s own docstring for why. This
endpoint is that wiring's front door. It is still an honest partial
answer, not the full §24 triangulation: see `CompanyValuationOut.note`
and ROADMAP.md's Phase 3 section for exactly which anchors are missing
and why.

Returns 404 for an unknown ticker, same convention as `securities.py`'s
company-file route. Does NOT require `archetype` to be set on the
security — `route_valuation(None)` already reports that as an explicit,
displayed reason rather than failing, and this endpoint passes that
straight through rather than special-casing it.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.valuation_view import CompanyValuationSummary, valuation_summary_for
from app.models.prices import PriceDaily
from app.models.securities import Security

router = APIRouter(prefix="/valuation", tags=["valuation"])


class AnchorOut(BaseModel):
    method: str
    category: str
    fair_value_per_share: Decimal


class TriangulationOut(BaseModel):
    triangulation_category: str | None
    anchors: list[AnchorOut]
    missing_categories: list[str]
    blended_fair_value_per_share: Decimal | None
    dispersion_pct: Decimal | None
    warnings: list[str]


class MarginOfSafetyOut(BaseModel):
    base_pct: Decimal
    dispersion_pct: Decimal | None
    liquidity_pct: Decimal | None
    regime_pct: Decimal | None
    quality_integrity_pct: Decimal | None
    data_completeness_pct: Decimal | None
    total_pct: Decimal
    is_lower_bound: bool
    missing_components: list[str]
    note: str


class PriceLadderOut(BaseModel):
    fair_value: Decimal
    margin_of_safety_pct: Decimal
    strong_accumulate_threshold: Decimal
    buy_below_price: Decimal
    trim_threshold: Decimal
    exit_threshold: Decimal
    current_price: Decimal | None
    current_zone: str | None
    zone_meaning: str | None
    gap_to_buy_below_pct: Decimal | None


class RoutingOut(BaseModel):
    archetype: str | None
    in_published_table: bool
    primary_models: list[str]
    note: str


class CurrentPeriodFCFFOut(BaseModel):
    period_end: dt.date | None
    fcff: Decimal | None
    """§18.1's FCFF formula on ONE real confirmed period — informational
    only, never a per-share fair value (see `app.domain.valuation_view.
    current_period_fcff_for`'s own docstring for why this is never one
    of `triangulation`'s anchors below)."""

    warnings: list[str]


class CompanyValuationOut(BaseModel):
    ticker: str
    as_of: dt.date
    current_price: Decimal | None
    routing: RoutingOut
    justified_price_to_book_fair_value: Decimal | None
    justified_price_to_book_warnings: list[str]
    residual_income_fair_value: Decimal | None
    residual_income_warnings: list[str]
    current_period_fcff: CurrentPeriodFCFFOut
    triangulation: TriangulationOut
    margin_of_safety: MarginOfSafetyOut
    price_ladder: PriceLadderOut | None
    note: str

    @classmethod
    def from_summary(cls, s: CompanyValuationSummary) -> "CompanyValuationOut":
        t = s.triangulation
        mos = s.margin_of_safety
        return cls(
            ticker=s.ticker,
            as_of=s.as_of,
            current_price=s.current_price,
            routing=RoutingOut(
                archetype=s.routing.archetype,
                in_published_table=s.routing.in_published_table,
                primary_models=list(s.routing.primary_models),
                note=s.routing.note,
            ),
            justified_price_to_book_fair_value=s.justified_pb.fair_value_per_share,
            justified_price_to_book_warnings=list(s.justified_pb.inputs.warnings),
            residual_income_fair_value=(
                s.residual_income.result.value_per_share if s.residual_income.result else None
            ),
            residual_income_warnings=list(s.residual_income.inputs.warnings),
            current_period_fcff=CurrentPeriodFCFFOut(
                period_end=s.current_period_fcff.period_end,
                fcff=s.current_period_fcff.fcff,
                warnings=list(s.current_period_fcff.warnings),
            ),
            triangulation=TriangulationOut(
                triangulation_category=t.triangulation_category,
                anchors=[],  # anchors themselves aren't retained on TriangulationResult — see category_averages
                missing_categories=list(t.missing_categories),
                blended_fair_value_per_share=t.blended_fair_value_per_share,
                dispersion_pct=t.dispersion_pct,
                warnings=list(t.warnings),
            ),
            margin_of_safety=MarginOfSafetyOut(
                base_pct=mos.base_pct,
                dispersion_pct=mos.dispersion_pct,
                liquidity_pct=mos.liquidity_pct,
                regime_pct=mos.regime_pct,
                quality_integrity_pct=mos.quality_integrity_pct,
                data_completeness_pct=mos.data_completeness_pct,
                total_pct=mos.total_pct,
                is_lower_bound=mos.is_lower_bound,
                missing_components=list(mos.missing_components),
                note=mos.note,
            ),
            price_ladder=(
                PriceLadderOut(
                    fair_value=s.price_ladder.fair_value,
                    margin_of_safety_pct=s.price_ladder.margin_of_safety_pct,
                    strong_accumulate_threshold=s.price_ladder.strong_accumulate_threshold,
                    buy_below_price=s.price_ladder.buy_below_price,
                    trim_threshold=s.price_ladder.trim_threshold,
                    exit_threshold=s.price_ladder.exit_threshold,
                    current_price=s.price_ladder.current_price,
                    current_zone=s.price_ladder.current_zone,
                    zone_meaning=s.price_ladder.zone_meaning,
                    gap_to_buy_below_pct=s.price_ladder.gap_to_buy_below_pct,
                )
                if s.price_ladder
                else None
            ),
            note=s.note,
        )


@router.get("/{ticker}", response_model=CompanyValuationOut)
def get_valuation(ticker: str, db: Session = Depends(get_db)) -> CompanyValuationOut:
    security = db.get(Security, ticker)
    if security is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker!r}")

    latest_price = db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )

    summary = valuation_summary_for(db, ticker, security.archetype, latest_price)
    return CompanyValuationOut.from_summary(summary)
