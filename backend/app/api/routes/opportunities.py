"""
§40's opportunity ranking, exposed — see `app.domain.opportunity_
ranking_view`'s own module docstring for exactly what's real here
(gap to buy-below price, from the real price ladder) versus what the
full spec still needs (the §38 composite score, §39 fusion, Carhart
certification, the timing battery — none of which exist yet).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.opportunity_ranking_view import OpportunityCandidate, opportunity_ranking_for

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


class OpportunityCandidateOut(BaseModel):
    ticker: str
    name: str
    archetype: str | None
    current_price: Decimal | None
    blended_fair_value_per_share: Decimal | None
    margin_of_safety_pct: Decimal
    price_ladder_zone: str | None
    buy_below_price: Decimal | None
    gap_to_buy_below_pct: Decimal | None
    dispersion_pct: Decimal | None
    verdict: str
    decision_confidence: str
    warnings: list[str]

    @classmethod
    def from_candidate(cls, c: OpportunityCandidate) -> "OpportunityCandidateOut":
        return cls(
            ticker=c.ticker, name=c.name, archetype=c.archetype, current_price=c.current_price,
            blended_fair_value_per_share=c.blended_fair_value_per_share,
            margin_of_safety_pct=c.margin_of_safety_pct, price_ladder_zone=c.price_ladder_zone,
            buy_below_price=c.buy_below_price, gap_to_buy_below_pct=c.gap_to_buy_below_pct,
            dispersion_pct=c.dispersion_pct, verdict=c.verdict,
            decision_confidence=c.decision_confidence, warnings=list(c.warnings),
        )


class OpportunityRankingOut(BaseModel):
    as_of: dt.date
    ranked: list[OpportunityCandidateOut]
    excluded: list[OpportunityCandidateOut]


@router.get("", response_model=OpportunityRankingOut)
def opportunity_ranking(db: Session = Depends(get_db)) -> OpportunityRankingOut:
    view = opportunity_ranking_for(db)
    return OpportunityRankingOut(
        as_of=view.as_of,
        ranked=[OpportunityCandidateOut.from_candidate(c) for c in view.ranked],
        excluded=[OpportunityCandidateOut.from_candidate(c) for c in view.excluded],
    )
