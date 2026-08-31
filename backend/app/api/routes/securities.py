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
from app.domain.fundamentals_view import ratio_series_by_key, ratio_trends_for, ratios_for
from app.domain.ratios import NOT_YET_COMPUTABLE
from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.security_status_view import security_status_for
from app.domain.valuation_router import route_valuation
from app.jobs.reconciliation import is_quarantined
from app.models.corporate_action_scan_log import CorporateActionScanLog
from app.models.corporate_actions import CorporateAction
from app.models.enums import ProvenanceTier
from app.domain.fundamentals_view import bulk_latest_line_items
from app.domain.ratios import DEFINITIONS_BY_KEY, compute_ratio
from app.domain.sector_percentiles_view import all_sector_percentiles, sector_percentiles_for
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
    return_on_equity_sector_percentile: Decimal | None
    """§12's sector-relative percentile (`app.domain.sector_percentiles`)
    — 0-100, ascending, ranked within `cse_sector` (falling back to the
    wider `gics_sector` when the narrow group is too thin). `None` when
    ROE itself isn't computable OR the sector is too thin at both levels
    to rank meaningfully — the screener never guesses a rank from too
    few peers."""
    price_change_5d_pct: Decimal | None
    price_change_10d_pct: Decimal | None
    price_change_15d_pct: Decimal | None
    price_change_30d_pct: Decimal | None
    """R1 T4.4.1: real trading-session price appreciation, RAW stored
    close (not adjustment-factor-adjusted — same convention `Price
    HistoryChart` already uses and discloses, since most tickers still
    carry `adj_factor=1.0`). `None` when fewer than that many real
    sessions of history exist for this ticker, never a change computed
    from less history than the window claims."""


class PricePoint(BaseModel):
    date: dt.date
    close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: int | None
    turnover: Decimal | None
    adj_factor: Decimal


class PriceHistoryPage(BaseModel):
    """One page of a ticker's daily price rows, most-recent-first. Backs
    the company file's price-history table (a separate concern from
    `SecurityDetail.price_history`, which stays oldest-first and fully
    loaded up to its own cap for the chart above the table) — that table
    can be a year-plus of daily rows, so it is paged with SQL LIMIT/OFFSET
    rather than shipping every row and slicing client-side."""

    items: list[PricePoint]
    total: int
    """Total sessions stored for this ticker, independent of `limit` —
    lets the UI show "1-5 of 241" and disable Next past the last page."""
    limit: int
    offset: int


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


class RatioSeriesPointOut(BaseModel):
    period_end: dt.date
    value: Decimal


class RatioPercentileOut(BaseModel):
    """§12's sector-relative percentile — see `app.domain.
    sector_percentiles`'s own module docstring for the grouping,
    winsorization and ranking-direction rules."""

    ratio_key: str
    percentile: Decimal | None
    group_label: str | None
    group_size: int
    used_wider_sector: bool
    reason: str | None


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
    status: str
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 4 — clean /
    provisional / quarantined / unresolved. Drives what the company page
    may publish: a quarantined name shows facts only, a provisional one
    shows a valuation but no maximum-conviction verdict, an unresolved one
    shows identity only."""
    blockers: list[str]
    """Why the name is quarantined or unresolved — the sentences that
    replace the verdict. Empty when `status` is clean/provisional."""
    soft_flags: list[str]
    """Why the name is provisional — shown as caution, valuation still
    published. Empty when `status` is clean."""
    primary_line_ticker: str | None
    primary_line_confidence: str
    verdict_cap: str | None
    """`docs/CSE_Universe_Integrity_Rollout.md` §Check 8 — `"hold"` when a
    trailing net loss on a declining earnings trend means no Buy-side
    verdict may be shown for this name, whatever the fair-value models
    output. `null` otherwise."""
    price_history: list[PricePoint]
    corporate_actions: list[CorporateActionSummary]
    corporate_actions_last_scanned_at: dt.datetime | None
    """R1 T2.6: `app.jobs.scheduler._job_corporate_actions_scan` runs this
    ticker through `CorporateActionScanLog` automatically (daily, §52) —
    there is no manual step for a user to run. `None` means the scheduled
    sweep genuinely hasn't reached this ticker yet, not that scanning
    isn't running; the frontend states which, rather than ever printing
    the CLI command a human operator would use to run it by hand."""
    fundamentals: list[FundamentalSummary]
    ratio_period_end: dt.date | None
    ratios: list[RatioOut]
    ratios_not_yet_computable: list[UncomputableRatioOut]
    ratio_trends: list[RatioTrendOut]
    ratio_percentiles: list[RatioPercentileOut]
    ratio_series: dict[str, list[RatioSeriesPointOut]]
    """R1 T4.3.1: the raw `(period_end, value)` history behind each
    ratio's `ratio_trends` verdict, oldest first — enough for the
    company-file ratio card to draw its own path where >=3 periods
    exist, without duplicating `ratio_trends_for`'s own point-in-time
    selection logic on the frontend."""
    valuation_routing: ValuationRoutingOut
    cost_of_equity: CostOfEquityOut
    not_yet_built: list[str]


# Kept in one place so the company file and any future screen tell the
# user the same story about what this system can't do yet.
_NOT_YET_BUILT = [
    "Coverage tier (Phase 2 — §11; the gate logic — all three gates plus the tier classifier —"
    " exists and is unit-tested, but is not wired to any real data anywhere in the app. Gate 2"
    " is the hard blocker: `public_float_pct` is 0/284 populated — the quarterly shareholding"
    " disclosures §5 names as its source are not ingested by anything in this system. Gate 3 has"
    " a second, structural gap even where Gate 2 wasn't the issue: `classify_coverage_tier`"
    " has no 'unevaluable' path for the integrity gate, only pass/fail, so wiring it today"
    " would mean fabricating a False for red flags that were never actually checked — exactly"
    " what `app.domain.composite_score_view`'s own separate, honest `integrity.evaluable=False`"
    " field exists to avoid. Both are real, separate pieces of work, not a wiring afternoon.)",
    "Earnings integrity veto (§14 — Beneish M-Score, Sloan accrual ratio, related-party revenue, "
    "auditor tier and director dealings all need statement lines this system does not yet extract)",
    "Research note (Phase 7 — AI research writer, §44)",
    "Sum-of-the-parts (§21, `app.domain.sotp`) is the one §18-26 valuation model still genuinely "
    "unwired, as of 23 Aug 2026 — every other named model (justified P/B, residual income, FCFF "
    "DCF, justified P/E, justified P/S, Gordon-growth DDM, hard book/NAV, current-period FCFF, "
    "and §23's Bear/Base/Bull scenario set with its sensitivity tornado and Monte Carlo overlay) "
    "now has a real live caller against real data — see `GET /valuation/{ticker}`, "
    "`/valuation/{ticker}/scenarios`, `/tornado` and `/monte-carlo`. SOTP is a genuinely "
    "different class of gap from those: it needs a segment-level breakdown (which subsidiaries "
    "a holding company owns, at what ownership %, unlisted or listed, with what EBITDA) that no "
    "ingestion source in this project produces at all, not a confirmation-workflow gap like "
    "Gordon-growth DDM's dividends were before 23 Aug — see `app.domain.valuation_view`'s own "
    "module docstring for the full picture.",
]
# Removed 18 Aug 2026: "Fair value and buy-below price" and a blanket
# "Macro regime ... not built" both used to be here — found stale, live,
# browser-testing this exact page against real data: justified P/B and
# residual income (§20.2/§19.3) have been wired up as real triangulation
# anchors since much earlier this session, and the price ladder (§25-26)
# right above this list on the same page already shows a real, computed
# fair value and buy-below price for any company with enough confirmed
# data — this list was directly contradicting its own page.
#
# Removed 23 Aug 2026, same reason, checked the same way (live against
# real data, not assumed): "Sector-relative percentiles" — `app.domain.
# sector_percentiles`/`sector_percentiles_view` are real and wired; the
# ratio table two sections above this one already renders a real
# percentile per ratio (`ratio_percentiles`, `sector_percentiles_for`).
# "Composite score" — `app.domain.composite_score`/`composite_score_view`
# are real, tested and live at `GET /composite-score/{ticker}`, and the
# company file's new Composite score (§38) section above renders it
# directly, disclosing its own genuine partiality (5 of 7 pillars
# blended; Valuation and Growth permanently shown as evidence only, a
# real measured latency cost — see that module's own docstring) inline,
# the same "state the gap on the page that has it, not in a generic
# list" pattern the two removals above already established. Per-ticker
# macro sector fit and the timing battery/Carhart certification the old
# composite-score entry named as blockers are also both real and folded
# into that same section now — see `app.domain.macro_sector_fit`,
# `app.domain.timing_battery` and `app.domain.carhart_regression`.
#
# Removed 23 Aug 2026, same reason: "Per-ticker macro sector fit" — the
# per-COMPANY score this entry said "isn't computed yet" is exactly
# `app.domain.macro_sector_fit.macro_sector_fit_for`, real and wired into
# the same Composite score (§38) section as its own pillar. What is
# genuinely still true and NOT restored here: §45's decision record has a
# `sector_fit` column that Journal still never populates at decision
# time — a real, separate capture-time gap, distinct from "does a
# per-ticker score exist at all," which is what this line used to claim.


_PRICE_CHANGE_WINDOWS = (5, 10, 15, 30)
# 30 trading sessions is genuinely ~6 calendar weeks with weekends and
# CSE holidays folded in — a real, generous buffer, not a guess.
_PRICE_CHANGE_LOOKBACK_DAYS = 60


def _bulk_price_changes(db: Session, as_of: dt.date) -> dict[str, dict[int, Decimal | None]]:
    """R1 T4.4.1. One bulk query for real session-level closes across the
    whole universe in the trailing window, not 290 per-ticker lookups —
    the same discipline every other bulk read on this page already
    applies. Windows are real trading SESSIONS (this ticker's own actual
    stored rows), not calendar days — a ticker's own session list is
    cheaply available here (unlike `portfolio_value_trend`'s multi-
    ticker case, which has no single shared session index), so the more
    precise session-count form is used rather than a calendar-day
    approximation."""
    since = as_of - dt.timedelta(days=_PRICE_CHANGE_LOOKBACK_DAYS)
    rows = db.execute(
        select(PriceDaily.ticker, PriceDaily.date, PriceDaily.close).where(
            PriceDaily.date >= since, PriceDaily.date <= as_of, PriceDaily.close.is_not(None)
        )
    ).all()

    by_ticker: dict[str, list[tuple[dt.date, Decimal]]] = {}
    for ticker, date, close in rows:
        by_ticker.setdefault(ticker, []).append((date, close))

    result: dict[str, dict[int, Decimal | None]] = {}
    for ticker, points in by_ticker.items():
        points.sort(key=lambda p: p[0])
        latest_close = points[-1][1]
        changes: dict[int, Decimal | None] = {}
        for window in _PRICE_CHANGE_WINDOWS:
            idx = len(points) - 1 - window
            if idx < 0 or points[idx][1] == 0:
                changes[window] = None
                continue
            then_close = points[idx][1]
            changes[window] = (latest_close - then_close) / then_close * Decimal(100)
        result[ticker] = changes
    return result


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
    # One universe-wide pass, not one per row — same discipline as the
    # ROE bulk fetch just above.
    percentiles = all_sector_percentiles(db)
    price_changes = _bulk_price_changes(db, dt.date.today())

    items: list[SecurityListItem] = []
    for security, price in db.execute(stmt).all():
        _, line_items = roe_line_items.get(security.ticker, (None, {}))
        roe_result = compute_ratio(roe_definition, line_items) if line_items else None
        roe_percentile = percentiles.get(security.ticker, {}).get("return_on_equity")
        changes = price_changes.get(security.ticker, {})

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
                return_on_equity_sector_percentile=(
                    roe_percentile.percentile if roe_percentile else None
                ),
                price_change_5d_pct=changes.get(5),
                price_change_10d_pct=changes.get(10),
                price_change_15d_pct=changes.get(15),
                price_change_30d_pct=changes.get(30),
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


@router.get("/{ticker}/prices", response_model=PriceHistoryPage)
def get_security_prices(
    ticker: str,
    limit: int = Query(5, ge=1, le=50, description="page size — the UI offers 5/10/25/50"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PriceHistoryPage:
    """Paged, most-recent-first, for the company file's price-history
    table. `total` comes from a separate `COUNT(*)`, and rows come from a
    single `LIMIT/OFFSET` query — a ticker with a year-plus of daily rows
    never has more than `limit` of them loaded from the database for one
    request, unlike `SecurityDetail.price_history` above (capped at 400,
    all loaded at once, and kept only to feed the chart)."""
    if db.get(Security, ticker) is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker!r}")

    total = (
        db.scalar(select(func.count()).select_from(PriceDaily).where(PriceDaily.ticker == ticker))
        or 0
    )

    rows = db.scalars(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker)
        .order_by(PriceDaily.date.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return PriceHistoryPage(
        items=[
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
            for p in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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

    corporate_actions_last_scanned_at = db.scalar(
        select(CorporateActionScanLog.last_scanned_at).where(CorporateActionScanLog.ticker == ticker)
    )

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
    ratio_percentiles = sector_percentiles_for(db, ticker)
    ratio_series = ratio_series_by_key(db, ticker)
    routing = route_valuation(security.archetype)
    ke_result = cost_of_equity_for(db, ticker)
    _status = security_status_for(db, ticker)

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
        status=_status.status.value,
        blockers=list(_status.blockers),
        soft_flags=list(_status.soft_flags),
        primary_line_ticker=_status.primary_line_ticker,
        primary_line_confidence=_status.primary_line_confidence.value,
        verdict_cap=_status.verdict_cap,
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
        corporate_actions_last_scanned_at=corporate_actions_last_scanned_at,
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
        ratio_percentiles=[
            RatioPercentileOut(
                ratio_key=p.ratio_key,
                percentile=p.percentile,
                group_label=p.group_label,
                group_size=p.group_size,
                used_wider_sector=p.used_wider_sector,
                reason=p.reason,
            )
            for p in ratio_percentiles.values()
        ],
        ratio_series={
            key: [RatioSeriesPointOut(period_end=pt.period_end, value=pt.value) for pt in series]
            for key, series in ratio_series.items()
        },
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
