"""
Master Spec §45's decision record, exposed. See `app.domain.decision_
record_view`'s own module docstring for exactly what gets frozen for
real today versus stays honestly `None` because the layer that would
compute it doesn't exist yet.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.decision_record_view import (
    get_decision,
    list_decisions,
    record_decision_for,
    record_outcome_for,
)
from app.models.decisions import Decision, Outcome
from app.models.enums import DecisionAction

router = APIRouter(prefix="/decisions", tags=["decisions"])


class OutcomeOut(BaseModel):
    id: int
    exit_date: dt.date
    exit_price: Decimal
    exit_trigger: str
    gross_return: Decimal
    net_return: Decimal
    holding_days: int
    max_adverse_excursion: Decimal | None
    max_favourable_excursion: Decimal | None
    attribution_json: dict | None

    @classmethod
    def from_model(cls, o: Outcome) -> "OutcomeOut":
        return cls(
            id=o.id, exit_date=o.exit_date, exit_price=o.exit_price, exit_trigger=o.exit_trigger,
            gross_return=o.gross_return, net_return=o.net_return, holding_days=o.holding_days,
            max_adverse_excursion=o.max_adverse_excursion,
            max_favourable_excursion=o.max_favourable_excursion, attribution_json=o.attribution_json,
        )


class DecisionOut(BaseModel):
    id: int
    ticker: str
    timestamp: dt.datetime
    config_hash: str | None
    action: DecisionAction
    size_pct: Decimal | None
    limit_price: Decimal | None
    conviction_1_5: int | None
    reasoning_text: str
    falsification_text: str | None
    fundamental_score: Decimal | None
    pillar_scores_json: dict | None
    integrity_flags_json: dict | None
    fv_by_method_json: dict | None
    fv_blended: Decimal | None
    dispersion: Decimal | None
    mos_components_json: dict | None
    buy_below: Decimal | None
    fair_value: Decimal | None
    trim_above: Decimal | None
    timing_score: Decimal | None
    timing_branch: str | None
    timing_signals_json: dict | None
    macro_regime: str | None
    macro_prob: Decimal | None
    sector_fit: Decimal | None
    alpha: Decimal | None
    alpha_tstat: Decimal | None
    betas_json: dict | None
    residual_vol: Decimal | None
    market_price_at_decision: Decimal | None
    data_completeness_pct: Decimal | None
    agreement_score: Decimal | None
    override_flag: bool | None
    outcome: OutcomeOut | None

    @classmethod
    def from_model(cls, d: Decision) -> "DecisionOut":
        return cls(
            id=d.id, ticker=d.ticker, timestamp=d.timestamp, config_hash=d.config_hash,
            action=d.action, size_pct=d.size_pct, limit_price=d.limit_price,
            conviction_1_5=d.conviction_1_5, reasoning_text=d.reasoning_text,
            falsification_text=d.falsification_text, fundamental_score=d.fundamental_score,
            pillar_scores_json=d.pillar_scores_json, integrity_flags_json=d.integrity_flags_json,
            fv_by_method_json=d.fv_by_method_json, fv_blended=d.fv_blended, dispersion=d.dispersion,
            mos_components_json=d.mos_components_json, buy_below=d.buy_below, fair_value=d.fair_value,
            trim_above=d.trim_above, timing_score=d.timing_score, timing_branch=d.timing_branch,
            timing_signals_json=d.timing_signals_json, macro_regime=d.macro_regime,
            macro_prob=d.macro_prob, sector_fit=d.sector_fit, alpha=d.alpha,
            alpha_tstat=d.alpha_tstat, betas_json=d.betas_json, residual_vol=d.residual_vol,
            market_price_at_decision=d.market_price_at_decision,
            data_completeness_pct=d.data_completeness_pct, agreement_score=d.agreement_score,
            override_flag=d.override_flag,
            outcome=OutcomeOut.from_model(d.outcome) if d.outcome is not None else None,
        )


class RecordDecisionRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    action: DecisionAction
    reasoning_text: str = Field(min_length=1)
    size_pct: Decimal | None = None
    limit_price: Decimal | None = None
    conviction_1_5: int | None = Field(default=None, ge=1, le=5)
    falsification_text: str | None = None


class RecordOutcomeRequest(BaseModel):
    exit_date: dt.date
    exit_price: Decimal
    exit_trigger: str = Field(min_length=1, max_length=100)


@router.post("", response_model=DecisionOut, status_code=201)
def create_decision(body: RecordDecisionRequest, db: Session = Depends(get_db)) -> DecisionOut:
    decision = record_decision_for(
        db, body.ticker, body.action, body.reasoning_text,
        size_pct=body.size_pct, limit_price=body.limit_price,
        conviction_1_5=body.conviction_1_5, falsification_text=body.falsification_text,
    )
    return DecisionOut.from_model(decision)


@router.get("", response_model=list[DecisionOut])
def list_all_decisions(db: Session = Depends(get_db)) -> list[DecisionOut]:
    return [DecisionOut.from_model(d) for d in list_decisions(db)]


@router.get("/{decision_id}", response_model=DecisionOut)
def get_one_decision(decision_id: int, db: Session = Depends(get_db)) -> DecisionOut:
    decision = get_decision(db, decision_id)
    if decision is None:
        raise HTTPException(404, f"no decision with id {decision_id}")
    return DecisionOut.from_model(decision)


@router.post("/{decision_id}/outcomes", response_model=DecisionOut, status_code=201)
def create_outcome(
    decision_id: int, body: RecordOutcomeRequest, db: Session = Depends(get_db)
) -> DecisionOut:
    decision = get_decision(db, decision_id)
    if decision is None:
        raise HTTPException(404, f"no decision with id {decision_id}")
    if decision.outcome is not None:
        raise HTTPException(409, "this decision already has an outcome recorded")
    if decision.market_price_at_decision is None:
        raise HTTPException(
            422,
            "no real market price was captured at decision time — nothing to compute a return from",
        )
    record_outcome_for(db, decision_id, body.exit_date, body.exit_price, body.exit_trigger)
    db.refresh(decision)
    return DecisionOut.from_model(decision)
