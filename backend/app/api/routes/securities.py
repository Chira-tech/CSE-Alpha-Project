"""
Company list and company file.

WHAT IS DELIBERATELY STILL ABSENT HERE, AND WHAT ISN'T ANY MORE: composite
scores, coverage tiers, and most of §18-26's valuation math (DCF, DDM,
SOTP, asset-based) are still not exposed — the engines exist
(`app/domain/dcf.py` etc.) but aren't wired to live data (ROADMAP.md's
Phase 3 section). Fair value and a buy-below price are no longer
categorically absent: `GET /valuation/{ticker}` (`app/api/routes/
valuation.py`) now returns a real, partial triangulation (justified P/B
and residual income, §20.2/§19.3) for a company with confirmed
fundamentals — kept as a separate endpoint rather than added to
`SecurityDetail` below, so this route's own contract doesn't change
underneath existing callers. The UI spec's anti-pattern list is explicit
that "placeholder or lorem content in any shipped state" is forbidden
because "a fake number that reaches a user once destroys trust
permanently" — so rather than emitting a null score the UI might render as
"0", this API doesn't expose composite-score/coverage-tier fields at all
yet, and the company file returns an explicit `not_yet_built` list the UI
renders as a plain statement of what the system cannot yet tell you.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.fundamentals_view import ratio_trends_for, ratios_for
from app.domain.ratios import NOT_YET_COMPUTABLE
from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.valuation_router import route_valuation
from app.jobs.reconciliation import is_quarantined
from app.models.corporate_actions import CorporateAction
from app.models.enums import ProvenanceTier
from app.domain.fundamentals_view import bulk_latest_line_items
from app.domain.ratios import DEFINITIONS_BY_KEY, compute_ratio
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

router = APIRouter(prefix="/securities", tags=["securities"])


class SecurityListItem(BaseModel):
    ticker: str
    name: str
    instrument_type: str | None
    """`tradeSummary` lists every traded LINE, not every company — 18 of
    the 283 are non-voting lines of a company whose voting line is also
    listed, and three are not equity at all. Exposed so the UI can say so
    rather than implying 283 distinct businesses."""

    issuer_code: str | None
    cse_sector: str | None
    archetype: str | None
    last_close: Decimal | None
    last_price_date: dt.date | None
    turnover: Decimal | None
    volume: int | None
    quarantined: bool
    return_on_equity: Decimal | None
    """§12's ROE (`app.domain.ratios`), from the latest fundamentals
    period visible as of today, computed in bulk for the whole list
    (`bulk_latest_line_items`) rather than a per-company lookup —
    §54's Phase 2 "ranked screener UI" starting point: the first ratio
    made sortable across the universe rather than only shown one company
    at a time on its own file. Almost every ticker will be null today —
    most have no ingested fundamentals at all yet — and that is the
    correct, honest state, not a bug in this column."""
    return_on_equity_provenance: ProvenanceTier | None
    """Same tier this ratio would show as a chip on the company file
    (§8) — an AI-assisted ROE is real, screenable data, just not yet
    confirmed; the chip says which."""


class PricePoint(BaseModel):
    date: dt.date
    close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: int | None
    turnover: Decimal | None
    adj_factor: Decimal


class CorporateActionSummary(BaseModel):
    id: int
    ex_date: dt.date
    type: str
    confirmed: bool
    rejected: bool


class FundamentalSummary(BaseModel):
    id: int
    period_end: dt.date
    period_type: str
    statement_line: str
    value: Decimal
    provenance_tier: ProvenanceTier
    confirmed: bool


class RatioOut(BaseModel):
    key: str
    label: str
    formula: str
    unit: str
    value: Decimal | None
    provenance: ProvenanceTier | None
    inputs_used: list[str]
    missing_inputs: list[str]
    note: str | None


class UncomputableRatioOut(BaseModel):
    key: str
    label: str
    missing_inputs: list[str]


class SuppressionOut(BaseModel):
    model: str
    reason: str


class UnansweredQuestionOut(BaseModel):
    question: str
    missing_input: str


class CostOfEquityOut(BaseModel):
    """§17.2, with every component broken out — never just the final Ke."""

    ke: Decimal | None
    risk_free_rate: Decimal | None
    beta: Decimal | None
    erp_effective: Decimal
    beta_times_erp: Decimal | None
    size_premium: Decimal | None
    illiquidity_premium: Decimal | None
    implied_erp_cross_check: Decimal | None
    is_lower_bound: bool
    missing_components: list[str]
    note: str


class ValuationRoutingOut(BaseModel):
    """§15/§16. Never a valuation — only which methods apply to this
    company and which are actively wrong for it, and why."""

    in_published_table: bool
    primary_models: list[str]
    suppressed: list[SuppressionOut]
    meaningless_metrics: list[str]
    requires_earnings_normalisation: bool
    is_financial_firm: bool
    is_holding_company: bool
    note: str
    unanswered_questions: list[UnansweredQuestionOut]


class RatioTrendOut(BaseModel):
    ratio_key: str
    direction: str
    significant: bool
    accelerating: bool | None
    fraction_same_direction: Decimal | None
    periods_used: int
    first_period: dt.date | None
    last_period: dt.date | None


class SecurityDetail(BaseModel):
    ticker: str
    name: str
    instrument_type: str | None
    issuer_code: str | None
    sibling_tickers: list[str] = []
    """Other listed lines of the same issuer. Non-empty means this
    company's fundamentals are shared with another ticker."""

    isin: str | None
    cse_sector: str | None
    archetype: str | None
    listing_date: dt.date | None
    delisting_date: dt.date | None
    fiscal_year_end: str | None
    shares_issued: int | None
    shares_issued_as_of: dt.date | None
    public_float_pct: Decimal | None
    quarantined: bool
    price_history: list[PricePoint]
    corporate_actions: list[CorporateActionSummary]
    fundamentals: list[FundamentalSummary]
    ratio_period_end: dt.date | None
    ratios: list[RatioOut]
    ratios_not_yet_computable: list[UncomputableRatioOut]
    ratio_trends: list[RatioTrendOut]
    valuation_routing: ValuationRoutingOut
    cost_of_equity: CostOfEquityOut
    not_yet_built: list[str]


# Kept in one place so the company file and any future screen tell the
# user the same story about what this system can't do yet.
_NOT_YET_BUILT = [
    "Fair value and buy-below price (Phase 3 — the model router (§16) now runs and names which "
    "methods apply, and cost of equity (§17.2) is now computed, but the DCF/DDM/residual-income/"
    "SOTP math itself, §18-24, is not built)",
    "Composite score (Phase 2 — §38; needs the full ratio set plus sector-relative percentiles)",
    "Coverage tier (Phase 2 — §11; the gate logic exists but needs liquidity history and free float)",
    "Sector-relative percentiles (Phase 2 — §12; trend DIRECTION now runs per company (§13), but "
    "ranking a ratio against its sector needs a full-universe computation not yet built)",
    "Earnings integrity veto (§14 — Beneish M-Score, Sloan accrual ratio, related-party revenue, "
    "auditor tier and director dealings all need statement lines this system does not yet extract)",
    "Macro regime and sector fit (Phase 5 — macro engine, §29-33)",
    "Research note (Phase 7 — AI research writer, §44)",
]


@router.get("", response_model=list[SecurityListItem])
def list_securities(
    search: str | None = Query(None, description="case-insensitive match on ticker or name"),
    limit: int = Query(500, le=1000),
    db: Session = Depends(get_db),
) -> list[SecurityListItem]:
    """Every listed company (§10: "analyse everything"), with its most
    recent stored close. Companies with no price row yet are still
    returned — with nulls, never a zero — so the universe is always
    complete and gaps are visible rather than hidden."""
    # Most recent price date per ticker, then join back for that row's
    # values. Done as a subquery rather than N+1 per-ticker lookups.
    latest = (
        select(PriceDaily.ticker, func.max(PriceDaily.date).label("max_date"))
        .group_by(PriceDaily.ticker)
        .subquery()
    )
    stmt = (
        select(Security, PriceDaily)
        .outerjoin(latest, latest.c.ticker == Security.ticker)
        .outerjoin(
            PriceDaily,
            (PriceDaily.ticker == latest.c.ticker) & (PriceDaily.date == latest.c.max_date),
        )
        .order_by(Security.ticker)
        .limit(limit)
    )
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Security.ticker).like(pattern) | func.lower(Security.name).like(pattern)
        )

    quarantined_tickers = _quarantined_set(db)
    # One bulk query for the whole list, not 500 per-ticker lookups —
    # the same discipline the price join above already applies.
    roe_line_items = bulk_latest_line_items(
        db, dt.date.today(), ("net_income", "total_equity")
    )
    roe_definition = DEFINITIONS_BY_KEY["return_on_equity"]

    items: list[SecurityListItem] = []
    for security, price in db.execute(stmt).all():
        _, line_items = roe_line_items.get(security.ticker, (None, {}))
        roe_result = compute_ratio(roe_definition, line_items) if line_items else None

        items.append(
            SecurityListItem(
                ticker=security.ticker,
                name=security.name,
                instrument_type=security.instrument_type,
                issuer_code=security.issuer_code,
                cse_sector=security.cse_sector,
                archetype=security.archetype,
                last_close=price.close if price else None,
                last_price_date=price.date if price else None,
                turnover=price.turnover if price else None,
                volume=price.volume if price else None,
                quarantined=security.ticker in quarantined_tickers,
                return_on_equity=roe_result.value if roe_result else None,
                return_on_equity_provenance=roe_result.provenance if roe_result else None,
            )
        )
    return items


def _quarantined_set(db: Session) -> set[str]:
    """One query for the whole list rather than is_quarantined() per row."""
    from app.models.data_quality import DataAlert

    rows = db.execute(
        select(DataAlert.ticker).where(DataAlert.resolved.is_(False)).distinct()
    ).all()
    return {t for (t,) in rows}


@router.get("/{ticker}", response_model=SecurityDetail)
def get_security(ticker: str, db: Session = Depends(get_db)) -> SecurityDetail:
    security = db.get(Security, ticker)
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker!r}")

    prices = db.scalars(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker)
        .order_by(PriceDaily.date.desc())
        .limit(400)  # a backfilled year is ~241 trading days; leaves headroom
        # for forward capture before this needs raising again
    ).all()

    actions = db.scalars(
        select(CorporateAction)
        .where(CorporateAction.ticker == ticker)
        .order_by(CorporateAction.ex_date.desc())
    ).all()

    fundamentals = db.scalars(
        select(Fundamental)
        .where(Fundamental.ticker == ticker)
        .order_by(Fundamental.period_end.desc(), Fundamental.statement_line)
    ).all()

    latest_float = db.scalar(
        select(FloatData)
        .where(FloatData.ticker == ticker)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )

    ratio_period_end, ratio_results = ratios_for(db, ticker)
    ratio_trends = ratio_trends_for(db, ticker)
    routing = route_valuation(security.archetype)
    ke_result = cost_of_equity_for(db, ticker)

    siblings = (
        db.scalars(
            select(Security.ticker)
            .where(Security.issuer_code == security.issuer_code, Security.ticker != ticker)
            .order_by(Security.ticker)
        ).all()
        if security.issuer_code
        else []
    )

    return SecurityDetail(
        ticker=security.ticker,
        name=security.name,
        instrument_type=security.instrument_type,
        issuer_code=security.issuer_code,
        sibling_tickers=list(siblings),
        isin=security.isin,
        cse_sector=security.cse_sector,
        archetype=security.archetype,
        listing_date=security.listing_date,
        delisting_date=security.delisting_date,
        fiscal_year_end=security.fiscal_year_end,
        shares_issued=latest_float.shares_issued if latest_float else None,
        shares_issued_as_of=latest_float.as_of if latest_float else None,
        public_float_pct=latest_float.public_float_pct if latest_float else None,
        quarantined=is_quarantined(db, ticker),
        price_history=[
            PricePoint(
                date=p.date,
                close=p.close,
                open=p.open,
                high=p.high,
                low=p.low,
                volume=p.volume,
                turnover=p.turnover,
                adj_factor=p.adj_factor,
            )
            # oldest-first is what a chart wants
            for p in reversed(prices)
        ],
        corporate_actions=[
            CorporateActionSummary(
                id=a.id,
                ex_date=a.ex_date,
                type=a.type.value,
                confirmed=a.is_confirmed,
                rejected=a.is_rejected,
            )
            for a in actions
        ],
        fundamentals=[
            FundamentalSummary(
                id=f.id,
                period_end=f.period_end,
                period_type=f.period_type,
                statement_line=f.statement_line,
                value=f.value,
                provenance_tier=f.provenance_tier,
                confirmed=f.confirmed_by is not None,
            )
            for f in fundamentals
        ],
        ratio_period_end=ratio_period_end,
        ratios=[
            RatioOut(
                key=r.key,
                label=r.label,
                formula=r.formula,
                unit=str(r.unit),
                value=r.value,
                provenance=r.provenance,
                inputs_used=list(r.inputs_used),
                missing_inputs=list(r.missing_inputs),
                note=r.note,
            )
            for r in ratio_results
        ],
        ratios_not_yet_computable=[
            UncomputableRatioOut(key=key, label=label, missing_inputs=list(needs))
            for key, label, needs in NOT_YET_COMPUTABLE
        ],
        ratio_trends=[
            RatioTrendOut(
                ratio_key=t.ratio_key,
                direction=t.direction.direction.value,
                significant=t.direction.significant,
                accelerating=t.acceleration.accelerating,
                fraction_same_direction=t.consistency.fraction_same_direction,
                periods_used=t.periods_used,
                first_period=t.first_period,
                last_period=t.last_period,
            )
            for t in ratio_trends.values()
        ],
        valuation_routing=ValuationRoutingOut(
            in_published_table=routing.in_published_table,
            primary_models=list(routing.primary_models),
            suppressed=[SuppressionOut(model=s.model, reason=s.reason) for s in routing.suppressed],
            meaningless_metrics=list(routing.meaningless_metrics),
            requires_earnings_normalisation=routing.requires_earnings_normalisation,
            is_financial_firm=routing.is_financial_firm,
            is_holding_company=routing.is_holding_company,
            note=routing.note,
            unanswered_questions=[
                UnansweredQuestionOut(question=q.question, missing_input=q.missing_input)
                for q in routing.unanswered_questions
            ],
        ),
        cost_of_equity=CostOfEquityOut(
            ke=ke_result.ke,
            risk_free_rate=ke_result.risk_free_rate,
            beta=ke_result.beta,
            erp_effective=ke_result.erp_effective,
            beta_times_erp=ke_result.beta_times_erp,
            size_premium=ke_result.size_premium,
            illiquidity_premium=ke_result.illiquidity_premium,
            implied_erp_cross_check=ke_result.implied_erp_cross_check,
            is_lower_bound=ke_result.is_lower_bound,
            missing_components=list(ke_result.missing_components),
            note=ke_result.note,
        ),
        not_yet_built=_NOT_YET_BUILT,
    )
