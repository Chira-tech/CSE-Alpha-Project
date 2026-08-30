"""
Data health — UI & Experience Specification screen 9, and the visible face
of Master Spec §8 (freshness) and §50 (monitoring).

The spec is blunt that this deserves a real screen rather than an admin
afterthought, because "this queue is where data quality is actually
maintained." For Phase 1 that means: how much data do we actually have,
how stale is it, what's quarantined, and how much is sitting unreviewed.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.corporate_actions import CorporateAction
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.registry import IssuerRegistry
from app.models.securities import Security


router = APIRouter(prefix="/data-health", tags=["data-health"])


class QuarantinedTicker(BaseModel):
    ticker: str
    alert_type: str
    detail: str
    raised_at: dt.datetime


class TickerPendingCount(BaseModel):
    ticker: str
    count: int


class UniverseIntegrityMetrics(BaseModel):
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 7 — the weekly-tracked
    numbers that turn "measurable progress" from theoretical into visible.
    Every figure is a cheap aggregate query; the proxy nature of a couple
    of them is named, not hidden."""

    issuers_total: int
    issuers_with_a_primary_line: int
    """Issuers with at least one non-delisted ordinary or non-voting
    line — the resolvable ones. The rest render identity only."""
    issuers_high_confidence_binding: int
    """Issuers with exactly one non-delisted ordinary voting line — no
    tie-break needed, so the binding is HIGH confidence."""
    lines_unknown_instrument_type: int
    open_alerts_by_type: dict[str, int]
    quarantined_line_count: int
    """Distinct lines with at least one unresolved DataAlert — the real
    "excluded from every model right now" count. A rising number early in
    the rollout is detection working; watch it after remediation."""
    market_cap_identity_pass_pct: Decimal | None
    """Of lines with a published market cap on file, the share with no
    open `market_cap_mismatch` alert."""
    price_ratio_actions_confirmed_pct: Decimal | None
    """Of price-ratio corporate actions (bonus / split / consolidation /
    rights), the share that are confirmed (so a factor is applied)."""
    median_price_staleness_days: int | None


class DataHealth(BaseModel):
    securities_count: int
    issuer_count: int
    """Distinct issuers behind those lines. Lower than `securities_count`
    because banks in particular list voting and non-voting lines
    separately."""

    registry_issuers: int
    registry_delisted: int
    registry_unknown_status: int
    """Known to the exchange, not trading, and not flagged delisted —
    debt-only issuers, suspensions and merely-illiquid names, which this
    source cannot tell apart. Reported rather than assumed either way."""

    price_rows: int
    price_rows: int
    latest_price_date: dt.date | None
    price_feed_age_days: int | None
    securities_with_no_price: int

    corporate_actions_total: int
    corporate_actions_pending: int
    corporate_actions_confirmed: int
    corporate_actions_rejected: int

    fundamentals_total: int
    fundamentals_pending_confirmation: int
    fundamentals_confirmed: int

    fundamentals_confirmed_last_7d: int
    corporate_actions_confirmed_last_7d: int
    """Rolling 7-day confirm counts — the burn-down signal the redesign
    doc (§3.6) asks for on this screen: "Queue: 340 → 12 this week" is
    only legible if the rate things are being cleared is visible next to
    the backlog size."""

    quarantined: list[QuarantinedTicker]
    universe_integrity: UniverseIntegrityMetrics

    fundamentals_pending_by_ticker: list[TickerPendingCount]
    """R1 T4.1.5: top tickers by pending-figure count — a real, cheap
    proxy for "where confirming pays off most", NOT the brief's own
    literal "unblocks fair value for N companies" framing. That framing
    needs a full per-ticker valuation pass (the same ~30s-for-the-
    universe cost `app.domain.opportunity_ranking_view`'s own docstring
    already measures) to state truthfully — too slow to run on every
    load of a screen meant to be readable in under two minutes, and a
    stale/wrong "unblocks N" claim would be exactly the kind of
    confident-but-unverified number this project avoids everywhere else.
    Named here as a real, disclosed scope decision, not silently
    downgraded."""


def _universe_integrity_metrics(db: Session) -> UniverseIntegrityMetrics:
    from decimal import Decimal

    today = dt.date.today()

    issuer_codes = [
        c for (c,) in db.execute(select(func.distinct(Security.issuer_code))).all() if c is not None
    ]
    active_equity = db.execute(
        select(Security.issuer_code, Security.instrument_type).where(
            Security.delisting_date.is_(None),
            Security.instrument_type.in_(("ordinary", "non_voting")),
        )
    ).all()
    by_issuer: dict[str, list[str]] = {}
    for code, it in active_equity:
        by_issuer.setdefault(code, []).append(it)
    with_primary = sum(1 for c in issuer_codes if by_issuer.get(c))
    high_conf = sum(1 for c in issuer_codes if by_issuer.get(c, []).count("ordinary") == 1)

    unknown_type = db.scalar(
        select(func.count()).select_from(Security).where(
            Security.instrument_type.is_(None) | (Security.instrument_type == "unknown")
        )
    ) or 0

    open_by_type = {
        t: c
        for t, c in db.execute(
            select(DataAlert.alert_type, func.count())
            .where(DataAlert.resolved.is_(False))
            .group_by(DataAlert.alert_type)
        ).all()
    }
    quarantined_lines = db.scalar(
        select(func.count(func.distinct(DataAlert.ticker))).where(DataAlert.resolved.is_(False))
    ) or 0

    lines_with_mcap = db.scalar(
        select(func.count(func.distinct(FloatData.ticker))).where(FloatData.published_market_cap.is_not(None))
    ) or 0
    mcap_fail = open_by_type.get("market_cap_mismatch", 0)
    mcap_pass_pct = (
        (Decimal(lines_with_mcap - mcap_fail) / Decimal(lines_with_mcap) * 100).quantize(Decimal("0.1"))
        if lines_with_mcap
        else None
    )

    price_ratio_types = ("bonus_issue", "stock_split", "consolidation", "rights_issue")
    pr_total = db.scalar(
        select(func.count()).select_from(CorporateAction).where(CorporateAction.type.in_(price_ratio_types))
    ) or 0
    pr_confirmed = db.scalar(
        select(func.count())
        .select_from(CorporateAction)
        .where(CorporateAction.type.in_(price_ratio_types), CorporateAction.confirmed_by.is_not(None))
    ) or 0
    pr_pct = (
        (Decimal(pr_confirmed) / Decimal(pr_total) * 100).quantize(Decimal("0.1")) if pr_total else None
    )

    last_dates = [
        d
        for (d,) in db.execute(
            select(func.max(PriceDaily.date)).where(PriceDaily.close.is_not(None)).group_by(PriceDaily.ticker)
        ).all()
        if d is not None
    ]
    if last_dates:
        ages = sorted((today - d).days for d in last_dates)
        median_stale = ages[len(ages) // 2]
    else:
        median_stale = None

    return UniverseIntegrityMetrics(
        issuers_total=len(issuer_codes),
        issuers_with_a_primary_line=with_primary,
        issuers_high_confidence_binding=high_conf,
        lines_unknown_instrument_type=unknown_type,
        open_alerts_by_type=open_by_type,
        quarantined_line_count=quarantined_lines,
        market_cap_identity_pass_pct=mcap_pass_pct,
        price_ratio_actions_confirmed_pct=pr_pct,
        median_price_staleness_days=median_stale,
    )


@router.get("", response_model=DataHealth)
def data_health(db: Session = Depends(get_db)) -> DataHealth:
    securities_count = db.scalar(select(func.count()).select_from(Security)) or 0
    price_rows = db.scalar(select(func.count()).select_from(PriceDaily)) or 0
    latest_price_date = db.scalar(select(func.max(PriceDaily.date)))

    # Age is computed against the latest date we HAVE, not against
    # "expected" — the UI shows the number and lets a human judge it, per
    # §8's rule that stale data is labelled plainly rather than silently
    # rendered as current.
    age_days = (dt.date.today() - latest_price_date).days if latest_price_date else None

    tickers_with_price = select(PriceDaily.ticker).distinct().subquery()
    securities_with_no_price = (
        db.scalar(
            select(func.count())
            .select_from(Security)
            .where(Security.ticker.not_in(select(tickers_with_price.c.ticker)))
        )
        or 0
    )

    issuer_count = (
        db.scalar(select(func.count(func.distinct(Security.issuer_code)))) or 0
    )
    registry_issuers = db.scalar(select(func.count()).select_from(IssuerRegistry)) or 0
    registry_delisted = (
        db.scalar(
            select(func.count()).select_from(IssuerRegistry).where(IssuerRegistry.delisted.is_(True))
        )
        or 0
    )
    registry_trading = (
        db.scalar(
            select(func.count())
            .select_from(IssuerRegistry)
            .where(IssuerRegistry.currently_trading.is_(True))
        )
        or 0
    )

    ca_total = db.scalar(select(func.count()).select_from(CorporateAction)) or 0
    ca_confirmed = (
        db.scalar(
            select(func.count()).select_from(CorporateAction).where(CorporateAction.confirmed_by.is_not(None))
        )
        or 0
    )
    ca_rejected = (
        db.scalar(
            select(func.count()).select_from(CorporateAction).where(CorporateAction.rejected_by.is_not(None))
        )
        or 0
    )

    f_total = db.scalar(select(func.count()).select_from(Fundamental)) or 0
    f_pending = (
        db.scalar(
            select(func.count())
            .select_from(Fundamental)
            .where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
        )
        or 0
    )
    f_confirmed = (
        db.scalar(
            select(func.count()).select_from(Fundamental).where(Fundamental.confirmed_by.is_not(None))
        )
        or 0
    )

    week_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    f_confirmed_7d = (
        db.scalar(
            select(func.count())
            .select_from(Fundamental)
            .where(Fundamental.confirmed_at.is_not(None), Fundamental.confirmed_at >= week_ago)
        )
        or 0
    )
    ca_confirmed_7d = (
        db.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(CorporateAction.confirmed_at.is_not(None), CorporateAction.confirmed_at >= week_ago)
        )
        or 0
    )

    alerts = db.scalars(
        select(DataAlert).where(DataAlert.resolved.is_(False)).order_by(DataAlert.raised_at.desc())
    ).all()

    f_pending_by_ticker = db.execute(
        select(Fundamental.ticker, func.count())
        .where(Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED, Fundamental.confirmed_by.is_(None))
        .group_by(Fundamental.ticker)
        .order_by(func.count().desc())
        .limit(8)
    ).all()

    return DataHealth(
        securities_count=securities_count,
        issuer_count=issuer_count,
        registry_issuers=registry_issuers,
        registry_delisted=registry_delisted,
        registry_unknown_status=max(registry_issuers - registry_trading - registry_delisted, 0),
        price_rows=price_rows,
        latest_price_date=latest_price_date,
        price_feed_age_days=age_days,
        securities_with_no_price=securities_with_no_price,
        corporate_actions_total=ca_total,
        corporate_actions_pending=ca_total - ca_confirmed - ca_rejected,
        corporate_actions_confirmed=ca_confirmed,
        corporate_actions_rejected=ca_rejected,
        fundamentals_total=f_total,
        fundamentals_pending_confirmation=f_pending,
        fundamentals_confirmed=f_confirmed,
        fundamentals_confirmed_last_7d=f_confirmed_7d,
        corporate_actions_confirmed_last_7d=ca_confirmed_7d,
        fundamentals_pending_by_ticker=[
            TickerPendingCount(ticker=t, count=c) for t, c in f_pending_by_ticker
        ],
        quarantined=[
            QuarantinedTicker(
                ticker=a.ticker, alert_type=a.alert_type, detail=a.detail, raised_at=a.raised_at
            )
            for a in alerts
        ],
        universe_integrity=_universe_integrity_metrics(db),
    )
