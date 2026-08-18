"""
§18-26 exposed for one company — the first Phase 3 endpoint that returns
an actual fair value rather than routing metadata or a discount rate.

`securities.py`'s own module docstring said, until this file existed,
that fair values and buy-below prices are "deliberately absent... Phase
2/3 (§12-26) and the engines that compute them do not exist yet." That's
now largely closed: the engines exist (`app/domain/dcf.py` through
`price_ladder.py`) and three of them — justified P/B, residual income
and, as of this session, the full multi-year FCFF DCF (`dcf`) — are
wired to live data as real triangulation anchors (`app.domain.valuation_
view`). `current_period_fcff` and `wacc` stay separate, deliberately
informational-only numbers (§18.1's FCFF formula on one undiscounted
confirmed period, and the DCF's own discount rate) — see `app.domain.
valuation_view`'s own module docstring and `dcf_for`'s docstring for the
full picture of what's real versus a named policy default within the
DCF specifically. A fourth informational number, `gordon_growth_ddm`
(§19.1), is wired the same way for a distinct reason: it runs against
genuinely real `CorporateAction` dividend rows that are, for essentially
every ticker today, real but unconfirmed — see `app.domain.valuation_
view.gordon_growth_ddm_for`'s own docstring. This endpoint is that
wiring's front door. It is still an honest partial answer, not the full
§24 triangulation: see `CompanyValuationOut.note` and ROADMAP.md's Phase
3 section for exactly which anchors are missing and why.

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
from app.domain.valuation_quarantine_view import record_sanity_result
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


class SanityOut(BaseModel):
    """TASK 0.1's plausibility gate (`app.domain.sanity`) — shown even
    when nothing failed, so a caller can see which rules were actually
    checked versus skipped for missing data (§1 law 4: never a black
    box)."""

    blocked: bool
    blocked_by: list[str]
    block_reasons: list[str]
    warned_by: list[str]
    warn_reasons: list[str]
    skipped: list[str]


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


class WACCOut(BaseModel):
    equity_weight: Decimal | None
    debt_weight: Decimal | None
    cost_of_equity: Decimal | None
    after_tax_cost_of_debt: Decimal | None
    wacc: Decimal | None
    """§18.1's FCFF discount rate — never Ke for a levered company (see
    `app.domain.wacc`'s own docstring). Informational: shown for
    transparency, not yet consumed by any live fair value."""

    warnings: list[str]


class YearProjectionOut(BaseModel):
    year: int
    revenue: Decimal
    revenue_growth: Decimal
    ebit: Decimal
    operating_margin: Decimal
    tax_rate: Decimal
    depreciation_amortisation: Decimal
    capital_expenditure: Decimal
    net_working_capital: Decimal
    change_in_net_working_capital: Decimal
    fcff: Decimal


class DCFOut(BaseModel):
    period_end: dt.date | None
    fair_value_per_share: Decimal | None
    """§18's full multi-year FCFF DCF — a genuine "intrinsic" triangulation
    anchor below when computable, not informational-only like
    `current_period_fcff`/`wacc` (see `app.domain.valuation_view.dcf_for`'s
    own docstring for exactly which inputs are real extracted figures
    versus named, disclosed "no view" policy defaults)."""

    years: list[YearProjectionOut]
    terminal_value: Decimal | None
    equity_value: Decimal | None
    enterprise_or_operating_value: Decimal | None
    implied_reinvestment_rate_terminal: Decimal | None
    model_warnings: list[str]
    """From `DCFResult.warnings` — the pure model's own validation
    warnings about the assumptions (e.g. terminal growth vs risk-free
    rate), distinct from `warnings` below (this view's data-availability
    warnings, e.g. which bridge items default to zero)."""

    warnings: list[str]


class DDMOut(BaseModel):
    as_of: dt.date
    value_per_share: Decimal | None
    """§19.1's Gordon-growth DDM — informational only, never one of
    `triangulation`'s anchors below. See `app.domain.valuation_view.
    gordon_growth_ddm_for`'s own docstring for why: the code path is
    real, wired to genuine (scraped, not fabricated) `CorporateAction`
    dividend rows, but §8/§9 means essentially every ticker has zero
    CONFIRMED dividend rows today, so `warnings` below will usually name
    that as the reason this is `None`."""

    warnings: list[str]


class HardBookOut(BaseModel):
    period_end: dt.date | None
    reported_book_value: Decimal | None
    revaluation_reserves: Decimal | None
    hard_book_value: Decimal | None
    hard_book_per_share: Decimal | None
    """§22 rule 1 — informational only, never one of `triangulation`'s
    anchors below. See `app.domain.valuation_view.hard_book_for`'s own
    docstring for why: real, tested, live-wireable code, but
    `revaluation_reserves` has verified real-world coverage on only one
    filing so far, not enough to promote to an anchor yet."""

    warnings: list[str]


class MacroSignalOut(BaseModel):
    name: str
    reading: str
    lean: str


class RegimeOut(BaseModel):
    as_of: dt.date
    label: str | None
    """One of `"risk_on"`/`"transition"`/`"risk_off"`, or `None` when no
    read was possible at all (see `warnings`). This directly drives
    `margin_of_safety.regime_pct` above (§31: "mechanically... widens
    every margin of safety") — the Ke/discount-rate and gross-exposure
    consequences §31 also names are NOT wired anywhere yet."""

    probabilities: dict[str, Decimal] | None
    signals: list[MacroSignalOut]
    statistical_observation_count: int | None
    """How many real ASPI log-return observations the Markov-switching
    fit used, when one succeeded — `None` when no statistical read exists
    (see `warnings` for why: too little history, or non-convergence)."""

    missing_signals: list[str]
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
    wacc: WACCOut
    dcf: DCFOut
    gordon_growth_ddm: DDMOut
    hard_book: HardBookOut
    regime: RegimeOut
    triangulation: TriangulationOut
    margin_of_safety: MarginOfSafetyOut
    sanity: SanityOut | None
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
            wacc=WACCOut(
                equity_weight=s.wacc.result.equity_weight if s.wacc.result else None,
                debt_weight=s.wacc.result.debt_weight if s.wacc.result else None,
                cost_of_equity=s.wacc.result.cost_of_equity if s.wacc.result else None,
                after_tax_cost_of_debt=s.wacc.result.after_tax_cost_of_debt if s.wacc.result else None,
                wacc=s.wacc.result.wacc if s.wacc.result else None,
                warnings=list(s.wacc.warnings),
            ),
            dcf=DCFOut(
                period_end=s.dcf.period_end,
                fair_value_per_share=s.dcf.fair_value_per_share,
                years=(
                    [
                        YearProjectionOut(
                            year=y.year,
                            revenue=y.revenue,
                            revenue_growth=y.revenue_growth,
                            ebit=y.ebit,
                            operating_margin=y.operating_margin,
                            tax_rate=y.tax_rate,
                            depreciation_amortisation=y.depreciation_amortisation,
                            capital_expenditure=y.capital_expenditure,
                            net_working_capital=y.net_working_capital,
                            change_in_net_working_capital=y.change_in_net_working_capital,
                            fcff=y.fcff,
                        )
                        for y in s.dcf.result.years
                    ]
                    if s.dcf.result
                    else []
                ),
                terminal_value=s.dcf.result.terminal_value if s.dcf.result else None,
                equity_value=s.dcf.result.equity_value if s.dcf.result else None,
                enterprise_or_operating_value=(
                    s.dcf.result.enterprise_or_operating_value if s.dcf.result else None
                ),
                implied_reinvestment_rate_terminal=(
                    s.dcf.result.implied_reinvestment_rate_terminal if s.dcf.result else None
                ),
                model_warnings=list(s.dcf.result.warnings) if s.dcf.result else [],
                warnings=list(s.dcf.warnings),
            ),
            gordon_growth_ddm=DDMOut(
                as_of=s.gordon_growth_ddm.as_of,
                value_per_share=(
                    s.gordon_growth_ddm.result.value_per_share if s.gordon_growth_ddm.result else None
                ),
                warnings=list(s.gordon_growth_ddm.warnings),
            ),
            hard_book=HardBookOut(
                period_end=s.hard_book.period_end,
                reported_book_value=s.hard_book.result.reported_book_value if s.hard_book.result else None,
                revaluation_reserves=s.hard_book.result.revaluation_reserves if s.hard_book.result else None,
                hard_book_value=s.hard_book.result.hard_book_value if s.hard_book.result else None,
                hard_book_per_share=s.hard_book.result.hard_book_per_share if s.hard_book.result else None,
                warnings=list(s.hard_book.warnings),
            ),
            regime=RegimeOut(
                as_of=s.regime.as_of,
                label=s.regime.result.label if s.regime.result else None,
                probabilities=(
                    {k: v for k, v in s.regime.result.probabilities.items()}
                    if s.regime.result
                    else None
                ),
                signals=[
                    MacroSignalOut(name=sig.name, reading=sig.reading, lean=sig.lean)
                    for sig in s.regime.signals
                ],
                statistical_observation_count=(
                    s.regime.statistical.observation_count if s.regime.statistical else None
                ),
                missing_signals=list(s.regime.missing_signals),
                warnings=list(s.regime.warnings),
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
            sanity=(
                SanityOut(
                    blocked=s.sanity.blocked,
                    blocked_by=list(s.sanity.blocked_by),
                    block_reasons=list(s.sanity.block_reasons),
                    warned_by=list(s.sanity.warned_by),
                    warn_reasons=list(s.sanity.warn_reasons),
                    skipped=list(s.sanity.skipped),
                )
                if s.sanity is not None
                else None
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
    if summary.sanity is not None:
        # TASK 0.1: persist the quarantine record here, on the real
        # single-company view a human actually looks at — see
        # app.domain.valuation_quarantine_view's own module docstring
        # for why this is idempotent and why it isn't ALSO called from
        # every row of a multi-ticker screen.
        record_sanity_result(db, ticker, summary.sanity)
    return CompanyValuationOut.from_summary(summary)
