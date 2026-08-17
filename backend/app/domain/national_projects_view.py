"""
Bridges stored `national_projects`/`national_project_ticker_impacts` rows
to `app.domain.national_projects` — the I/O layer that module
deliberately doesn't have, the same split every `_view.py` companion in
this system draws.

POINT-IN-TIME NOTE. A project's influence on a valuation should begin
only once it was ACTUALLY confirmed by `as_of`, not backdated to when it
was first drafted or to its own `source_date` — the same reasoning
`app.domain.valuation_view._confirmed_dividends_as_of` already applies
to `CorporateAction.ex_date`, adapted here to `NationalProject.
confirmed_at` specifically, because confirmation (not the underlying
event) is what §34 says gates influence on any valuation. Filtered in
Python after a single query rather than a DB-level date-cast, because
this table is expected to stay small (a curated, human-entered register,
not a scraped high-volume feed) — the same "gather, then filter" shape
`app.domain.national_projects.net_revenue_growth_adjustment` already
assumes of its caller.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.national_projects import (
    TickerImpact,
    may_influence_base_case,
    net_revenue_growth_adjustment,
)
from app.models.enums import NationalProjectImpactMetric
from app.models.national_projects import NationalProject, NationalProjectTickerImpact


def confirmed_base_case_impacts_for(
    db: Session, ticker: str, as_of: dt.date
) -> list[NationalProjectTickerImpact]:
    """Every real, confirmed, base-case-eligible impact row for one
    ticker, point-in-time visible as of `as_of` — the ORM rows
    themselves (not yet converted to the domain layer's decoupled
    `TickerImpact`), so a caller that wants the project name/source for
    display still can."""
    rows = db.scalars(
        select(NationalProjectTickerImpact)
        .join(NationalProject, NationalProjectTickerImpact.project_id == NationalProject.id)
        .where(
            NationalProjectTickerImpact.ticker == ticker,
            NationalProject.confirmed_by.is_not(None),
            NationalProject.rejected_by.is_(None),
        )
    ).all()
    return [
        row
        for row in rows
        if row.project.confirmed_at is not None
        and row.project.confirmed_at.date() <= as_of
        and may_influence_base_case(row.project.status, is_confirmed=True)
    ]


def confirmed_base_case_revenue_growth_adjustment_for(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[Decimal | None, list[NationalProjectTickerImpact]]:
    """§18.2's own words for DCF revenue growth Y1-2: "Trailing 3-year
    CAGR, adjusted by sector macro sensitivity (§33) and any confirmed
    project in the register (§34)." Returns `(adjustment, contributing_
    impacts)` — the second element lets a caller name exactly which
    projects contributed, rather than presenting one opaque number.
    `adjustment` is `None` (not `0`) when no confirmed base-case-eligible
    REVENUE impact exists for this ticker — see `net_revenue_growth_
    adjustment`'s own docstring for why that distinction is load-bearing.
    """
    impacts = confirmed_base_case_impacts_for(db, ticker, as_of)
    domain_impacts = [TickerImpact(i.impact_metric, i.quantified_impact_pct) for i in impacts]
    adjustment = net_revenue_growth_adjustment(domain_impacts)
    if adjustment is None:
        return None, []
    contributing = [
        i
        for i in impacts
        if i.impact_metric == NationalProjectImpactMetric.REVENUE
        and i.quantified_impact_pct is not None
    ]
    return adjustment, contributing
