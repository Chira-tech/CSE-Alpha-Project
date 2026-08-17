"""
Bridges stored fundamentals, ratios, cost of equity, archetype routing
and live prices to the pure §18-26 valuation modules — the I/O layer
those modules deliberately don't have, the same split
`app.domain.cost_of_equity_view` and `app.domain.fundamentals_view`
already draw for §17 and §12-13.

THE ONE RULE THIS MODULE ENFORCES THAT `app.domain.fundamentals_view`
DELIBERATELY DOESN'T. `fundamentals_view.ratios_for` intentionally shows
AI-assisted ratios (with a provenance chip, on the company file) because
a ratio is displayed there as a fact about the company, chip and all — a
FAIR VALUE is a different kind of claim. §8 is explicit: an AI-assisted
figure "cannot enter a valuation until human-confirmed and promoted to
Reported." This module re-selects line items itself
(`_confirmable_line_items`), filtered through
`app.domain.provenance.can_enter_valuation`, rather than reusing
`fundamentals_view.latest_period_line_items`, specifically so that
boundary can never be silently skipped for a number that ends up on a
price ladder. A period with only AI-assisted figures produces no
valuation here at all — `excluded_unconfirmed_lines` says which lines
were held back and why, rather than the output quietly using them anyway.

WHICH OF §18-26'S NINE MODELS THIS ACTUALLY WIRES UP, AND WHY ONLY THESE
TWO. Only justified P/B (§20.2) and residual income (§19.3) run against
live data — see `app.domain.dividend_residual_income` and
`app.domain.relative_valuation`'s own module docstrings for exactly why
DCF, DDM, SOTP and asset-based stay unwired. Cash-flow-statement
extraction is no longer a total gap (`cash_flow_from_operations` and
`depreciation_and_amortisation` are extracted — `app.domain.dcf`'s own
docstring has the detail), but capital expenditure and working-capital
components still aren't, and dividend-history/segment/external-reference
data still isn't extracted anywhere in this system either — DCF and DDM
each still need at least one input this session's cash-flow work didn't
close. Both wired models need only book value, ROE and Ke — all three
already exist by Phase 2/3's earlier work.

THE RESIDUAL INCOME FORECAST USED HERE IS DELIBERATELY THE FLAT-
PERSISTENCE CASE, NOT A FORECAST OF IMPROVEMENT. `compute_residual_
income` wants a multi-year ROE path; this system has no analyst forecast
or trend model that could honestly generate one (§13's trend detection
answers "has ROE been rising," not "will it keep rising," and most
companies have too few periods stored for that question to be
answerable at all yet). Projecting the latest confirmed ROE forward
unchanged, for one explicit year, is the standard "no view" baseline in
valuation practice — it says "if nothing changes, this is what the
company is worth today," not "we predict improvement" — and is the only
forecast this module can make without manufacturing false precision from
a single data point, exactly the failure `app.domain.trend_detection`'s
own docstring already warns about for a "trend" read off too little
history.

`settings.long_run_nominal_growth_pct` (PARAMETERS.md #11) supplies `g`
for both models — a policy default, not something computed, same
category as `erp_effective_pct`. It is clamped below the live risk-free
rate before use, per §18.2's own discipline ("never exceeds the
risk-free rate — a company growing faster than the risk-free rate
forever is worth infinity"), rather than trusted as already-safe.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.dividend_residual_income import ResidualIncomeResult, compute_residual_income
from app.domain.margin_of_safety import MarginOfSafetyResult, compute_margin_of_safety
from app.domain.point_in_time import fundamentals_as_of
from app.domain.price_ladder import PriceLadderResult, compute_price_ladder
from app.domain.provenance import can_enter_valuation
from app.domain.ratios import LineItem, compute_all
from app.domain.relative_valuation import JustifiedMultipleResult, justified_price_to_book
from app.domain.triangulation import TriangulationResult, ValuationAnchor, triangulate
from app.domain.valuation_router import RoutingDecision, route_valuation
from app.models.float_data import FloatData


def _confirmable_line_items(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[dt.date | None, dict[str, LineItem], tuple[str, ...]]:
    """The latest point-in-time-visible period's line items, restricted to
    tiers `can_enter_valuation` allows (§8). Returns
    `(period_end, items, excluded_lines)` — `excluded_lines` names any
    statement line that exists for the period but was held back because
    it is still AI-assisted/unconfirmed, so a caller can say why a figure
    is missing rather than just that it is."""
    rows = fundamentals_as_of(db, ticker, as_of)
    if not rows:
        return None, {}, ()

    latest_period = max(r.period_end for r in rows)
    items: dict[str, LineItem] = {}
    excluded: set[str] = set()
    for row in rows:
        if row.period_end != latest_period:
            continue
        if not can_enter_valuation(row.provenance_tier):
            excluded.add(row.statement_line)
            continue
        if row.statement_line not in items:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)

    return latest_period, items, tuple(sorted(excluded))


def _latest_shares_issued(db: Session, ticker: str, as_of: dt.date) -> int | None:
    row = db.scalar(
        select(FloatData)
        .where(FloatData.ticker == ticker, FloatData.as_of <= as_of)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )
    return row.shares_issued if row else None


def _steady_state_growth(risk_free_rate: Decimal | None) -> Decimal:
    """§18.2: terminal/steady-state growth "never exceeds the risk-free
    rate." Clamped here rather than trusting the configured default is
    already safe, because `settings.long_run_nominal_growth_pct` is a
    fixed policy constant while `risk_free_rate` moves with real CBSL
    data — the two could fall out of that relationship at any time."""
    g = settings.long_run_nominal_growth_pct
    if risk_free_rate is not None and g >= risk_free_rate:
        return risk_free_rate - Decimal("0.01")
    return g


@dataclass(frozen=True)
class LiveValuationInputs:
    """What was actually available for this company, before any model
    ran — so a `None` fair value downstream is traceable to a specific
    named cause rather than a dead end."""

    period_end: dt.date | None
    roe: Decimal | None
    cost_of_equity: Decimal | None
    growth_rate: Decimal
    book_value_per_share: Decimal | None
    shares_issued: int | None
    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def _gather_inputs(db: Session, ticker: str, as_of: dt.date) -> LiveValuationInputs:
    warnings: list[str] = []

    period_end, items, excluded = _confirmable_line_items(db, ticker, as_of)
    if excluded:
        warnings.append(
            f"{excluded} present for this period but still AI-assisted/unconfirmed — "
            "excluded from valuation per §8 (would show on the company file's ratio "
            "table with a provenance chip, but cannot enter a fair value)."
        )
    if period_end is None:
        warnings.append("No fundamentals visible as of this date at all.")

    roe = None
    if items:
        roe_result = next((r for r in compute_all(items) if r.key == "return_on_equity"), None)
        if roe_result is not None and roe_result.computable:
            roe = roe_result.value
        else:
            warnings.append(
                "ROE not computable from confirmed fundamentals"
                + (f" ({roe_result.note})" if roe_result and roe_result.note else ".")
            )

    ke_result = cost_of_equity_for(db, ticker, as_of)
    if ke_result.ke is None:
        warnings.append(f"Cost of equity not computable: {ke_result.note}")

    growth_rate = _steady_state_growth(ke_result.risk_free_rate)

    book_value_per_share = None
    total_equity_item = items.get("total_equity")
    shares = _latest_shares_issued(db, ticker, as_of)
    if total_equity_item is None:
        warnings.append("total_equity not available from confirmed fundamentals.")
    if shares is None:
        warnings.append("shares_issued not available (no FloatData row on or before this date).")
    if total_equity_item is not None and shares:
        book_value_per_share = total_equity_item.value / Decimal(shares)

    return LiveValuationInputs(
        period_end=period_end,
        roe=roe,
        cost_of_equity=ke_result.ke,
        growth_rate=growth_rate,
        book_value_per_share=book_value_per_share,
        shares_issued=shares,
        excluded_unconfirmed_lines=excluded,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class JustifiedPBView:
    inputs: LiveValuationInputs
    result: JustifiedMultipleResult | None
    fair_value_per_share: Decimal | None


def justified_price_to_book_for(
    db: Session, ticker: str, as_of: dt.date | None = None
) -> JustifiedPBView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(db, ticker, stamp)

    if inputs.roe is None or inputs.cost_of_equity is None:
        return JustifiedPBView(inputs, None, None)

    result = justified_price_to_book(inputs.roe, inputs.growth_rate, inputs.cost_of_equity)
    fair_value = (
        result.value * inputs.book_value_per_share
        if result.value is not None and inputs.book_value_per_share is not None
        else None
    )
    return JustifiedPBView(inputs, result, fair_value)


@dataclass(frozen=True)
class ResidualIncomeView:
    inputs: LiveValuationInputs
    result: ResidualIncomeResult | None


def residual_income_for(db: Session, ticker: str, as_of: dt.date | None = None) -> ResidualIncomeView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(db, ticker, stamp)

    if inputs.roe is None or inputs.cost_of_equity is None or inputs.book_value_per_share is None:
        return ResidualIncomeView(inputs, None)

    result = compute_residual_income(
        book_value_per_share_t0=inputs.book_value_per_share,
        cost_of_equity=inputs.cost_of_equity,
        roe_forecast_path=(inputs.roe,),
        book_value_growth_path=(inputs.growth_rate,),
        terminal_roe=inputs.roe,
        terminal_growth=inputs.growth_rate,
    )
    return ResidualIncomeView(inputs, result)


@dataclass(frozen=True)
class CompanyValuationSummary:
    ticker: str
    as_of: dt.date
    current_price: Decimal | None
    """The price actually passed in to `valuation_summary_for`, kept
    independent of `price_ladder` — a real current price should still be
    reported even when no fair value exists yet to build a ladder from.
    `price_ladder.current_price` and this field are the same value when
    `price_ladder` is not None; this one is the one that's ALWAYS
    populated whenever a price was found, which is the bug this field
    exists to prevent: a caller reading `price_ladder.current_price` and
    getting None can't tell "no price known" from "no fair value yet."""

    routing: RoutingDecision
    justified_pb: JustifiedPBView
    residual_income: ResidualIncomeView
    triangulation: TriangulationResult
    margin_of_safety: MarginOfSafetyResult
    price_ladder: PriceLadderResult | None
    note: str


def valuation_summary_for(
    db: Session, ticker: str, archetype: str | None, current_price: Decimal | None,
    as_of: dt.date | None = None,
) -> CompanyValuationSummary:
    """The full, real, end-to-end Phase 3 pipeline for one company: route
    → the two live-wireable anchors → triangulate → margin of safety →
    price ladder. Every stage is honest about what it could and couldn't
    compute — this function does not paper over a gap by skipping a
    stage silently; `note` on the result, and each sub-result's own
    fields, say what ran and what didn't.
    """
    stamp = as_of or dt.date.today()
    routing = route_valuation(archetype)
    jpb = justified_price_to_book_for(db, ticker, stamp)
    ri = residual_income_for(db, ticker, stamp)

    anchors: list[ValuationAnchor] = []
    if jpb.fair_value_per_share is not None:
        anchors.append(ValuationAnchor("Justified P/B", "relative", jpb.fair_value_per_share))
    if ri.result is not None and ri.result.value_per_share is not None:
        anchors.append(ValuationAnchor("Residual income", "intrinsic", ri.result.value_per_share))

    triangulation = triangulate(routing, tuple(anchors))

    mos = compute_margin_of_safety(
        dispersion_pct=triangulation.dispersion_pct,
        liquidity_percentile=None,  # Amihud percentile — needs turnover history, still blocked (ROADMAP Gate 1)
        regime=None,  # §29-33 regime classifier — Phase 5, not built
        integrity_score=None,  # no continuous integrity score exists anywhere in this system, by design — see margin_of_safety.py
        data_completeness_pct=None,  # not computed at the per-company level anywhere yet
    )

    ladder = None
    if triangulation.blended_fair_value_per_share is not None:
        ladder = compute_price_ladder(
            triangulation.blended_fair_value_per_share, mos.total_pct, current_price
        )

    note = (
        f"{len(anchors)} of 9 §18-26 valuation anchors were live-computable for this "
        f"company ({', '.join(a.method for a in anchors) or 'none'}) — the rest need "
        "data this system does not extract yet (see ROADMAP.md's Phase 3 section). "
        "This is real math on real stored data, not a placeholder, but it is a partial "
        "triangulation, not the full 3-5-anchor blend §24 describes."
    )

    return CompanyValuationSummary(
        ticker=ticker, as_of=stamp, current_price=current_price, routing=routing, justified_pb=jpb,
        residual_income=ri, triangulation=triangulation, margin_of_safety=mos, price_ladder=ladder,
        note=note,
    )
