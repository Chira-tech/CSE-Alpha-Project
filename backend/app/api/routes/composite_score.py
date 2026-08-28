"""
§38's composite investment score, exposed for one company — a real,
honestly PARTIAL implementation. See `app.domain.composite_score`'s
module docstring for the full methodology (percentile-rank whatever has
a genuinely rankable input, renormalize among whichever pillars end up
computable, never fold the integrity veto into the number) and
`app.domain.composite_score_view`'s own docstring for the real, measured
cost reason Valuation and Growth are still shown as evidence rather than
ranked — the other two once-unbuilt pillars, Macro & sector fit and
Timing & momentum, are real and folded in as of this session (see
`app.domain.macro_sector_fit`/`app.domain.timing_battery`).

Returns 404 for an unknown ticker, same convention as `securities.py`
and `valuation.py`.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.composite_score_view import CompositeScoreView, PillarScore, composite_score_for
from app.domain.timing_battery import TimingBatteryResult
from app.models.securities import Security

router = APIRouter(prefix="/composite-score", tags=["composite-score"])


class PillarScoreOut(BaseModel):
    key: str
    label: str
    weight_pct: Decimal
    score: Decimal | None
    included: bool
    reason: str | None

    @classmethod
    def from_pillar(cls, p: PillarScore) -> "PillarScoreOut":
        return cls(
            key=p.key, label=p.label, weight_pct=p.weight_pct,
            score=p.score, included=p.included, reason=p.reason,
        )


class IntegrityOut(BaseModel):
    evaluable: bool
    vetoed: bool
    reason: str


class ValuationEvidenceOut(BaseModel):
    """Real Valuation-pillar figures, shown but not ranked — see
    `app.domain.composite_score_view`'s own docstring for exactly why."""

    blended_fair_value_per_share: Decimal | None
    dispersion_pct: Decimal | None
    margin_of_safety_pct: Decimal | None
    price_ladder_zone: str | None
    current_price: Decimal | None
    regime_label: str | None


class GrowthTrendOut(BaseModel):
    ratio_key: str
    direction: str
    significant: bool
    accelerating: bool | None
    fraction_same_direction: Decimal | None
    periods_used: int


class ProjectImpactOut(BaseModel):
    project_id: int
    impact_metric: str
    quantified_impact_pct: Decimal | None
    notes: str | None


class TimingSignalOut(BaseModel):
    key: str
    value: Decimal | None
    weight_pct: Decimal
    included: bool
    reason: str | None


class ContrarianCheckOut(BaseModel):
    rev_1m_bottom_decile: bool | None
    business_quality_ge_70: bool | None
    no_integrity_red_flag: bool | None
    no_adverse_disclosure_60d: str
    no_active_sector_macro_shock: bool | None
    all_conditions_met: bool


class TimingBatteryOut(BaseModel):
    signals: list[TimingSignalOut]
    crash_guard_active: bool
    contrarian: ContrarianCheckOut

    @classmethod
    def from_result(cls, r: TimingBatteryResult) -> "TimingBatteryOut":
        return cls(
            signals=[
                TimingSignalOut(key=s.key, value=s.value, weight_pct=s.weight_pct, included=s.included, reason=s.reason)
                for s in r.signals
            ],
            crash_guard_active=r.crash_guard_active,
            contrarian=ContrarianCheckOut(
                rev_1m_bottom_decile=r.contrarian.rev_1m_bottom_decile,
                business_quality_ge_70=r.contrarian.business_quality_ge_70,
                no_integrity_red_flag=r.contrarian.no_integrity_red_flag,
                no_adverse_disclosure_60d=r.contrarian.no_adverse_disclosure_60d,
                no_active_sector_macro_shock=r.contrarian.no_active_sector_macro_shock,
                all_conditions_met=r.contrarian.all_conditions_met,
            ),
        )


class CompositeScoreOut(BaseModel):
    ticker: str
    as_of: dt.date
    pillars: list[PillarScoreOut]
    total_score: Decimal | None
    weight_used_pct: dict[str, Decimal]
    is_partial: bool
    integrity: IntegrityOut
    valuation_evidence: ValuationEvidenceOut
    growth_ratio_trends: list[GrowthTrendOut]
    growth_project_impacts: list[ProjectImpactOut]
    timing_battery: TimingBatteryOut

    @classmethod
    def from_view(cls, v: CompositeScoreView) -> "CompositeScoreOut":
        s = v.valuation_summary
        return cls(
            ticker=v.ticker,
            as_of=v.as_of,
            pillars=[PillarScoreOut.from_pillar(p) for p in v.pillars],
            total_score=v.total_score,
            weight_used_pct=v.weight_used_pct,
            is_partial=v.is_partial,
            integrity=IntegrityOut(
                evaluable=v.integrity.evaluable, vetoed=v.integrity.vetoed, reason=v.integrity.reason,
            ),
            valuation_evidence=ValuationEvidenceOut(
                blended_fair_value_per_share=(
                    s.triangulation.blended_fair_value_per_share if s else None
                ),
                dispersion_pct=s.triangulation.dispersion_pct if s else None,
                margin_of_safety_pct=s.margin_of_safety.total_pct if s else None,
                price_ladder_zone=s.price_ladder.current_zone if s and s.price_ladder else None,
                current_price=s.current_price if s else None,
                regime_label=(
                    s.regime.result.label
                    if s and s.regime.result is not None
                    else None
                ),
            ),
            growth_ratio_trends=[
                GrowthTrendOut(
                    ratio_key=t.ratio_key,
                    direction=t.direction.direction.value,
                    significant=t.direction.significant,
                    accelerating=t.acceleration.accelerating,
                    fraction_same_direction=t.consistency.fraction_same_direction,
                    periods_used=t.periods_used,
                )
                for t in v.growth_ratio_trends.values()
            ],
            growth_project_impacts=[
                ProjectImpactOut(
                    project_id=i.project_id,
                    impact_metric=i.impact_metric,
                    quantified_impact_pct=i.quantified_impact_pct,
                    notes=i.notes,
                )
                for i in v.growth_project_impacts
            ],
            timing_battery=TimingBatteryOut.from_result(v.timing_battery),
        )


@router.get("/{ticker}", response_model=CompositeScoreOut)
def get_composite_score(ticker: str, db: Session = Depends(get_db)) -> CompositeScoreOut:
    if db.get(Security, ticker) is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker!r}")
    view = composite_score_for(db, ticker)
    assert view is not None  # the 404 above already ruled out the only case this returns None
    return CompositeScoreOut.from_view(view)
