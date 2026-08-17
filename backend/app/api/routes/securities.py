"""
Company list and company file.

WHAT IS DELIBERATELY ABSENT: composite scores, fair values, buy-below
prices, coverage tiers. Those are Phase 2/3 (§12-26) and the engines that
compute them do not exist yet. The UI spec's anti-pattern list is explicit
that "placeholder or lorem content in any shipped state" is forbidden
because "a fake number that reaches a user once destroys trust
permanently" — so rather than emitting a null score the UI might render as
"0", this API doesn't expose those fields at all, and the company file
returns an explicit `not_yet_built` list the UI renders as a plain
statement of what the system cannot yet tell you.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.fundamentals_view import ratios_for
from app.domain.ratios import NOT_YET_COMPUTABLE
from app.jobs.reconciliation import is_quarantined
from app.models.corporate_actions import CorporateAction
from app.models.enums import ProvenanceTier
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
    not_yet_built: list[str]


# Kept in one place so the company file and any future screen tell the
# user the same story about what this system can't do yet.
_NOT_YET_BUILT = [
    "Fair value and buy-below price (Phase 3 — valuation engine, Master Spec §16-26)",
    "Composite score (Phase 2 — §38; needs the full ratio set plus sector-relative percentiles)",
    "Coverage tier (Phase 2 — §11; the gate logic exists but needs liquidity history and free float)",
    "Trend direction and sector percentiles (Phase 2 — §13; needs several periods of history)",
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
    items: list[SecurityListItem] = []
    for security, price in db.execute(stmt).all():
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
        not_yet_built=_NOT_YET_BUILT,
    )
