"""
§23: Scenarios and simulation, wired to live data — the same "bridge
layer" split `app.domain.valuation_view` already draws between pure
domain math and the DB-touching I/O that feeds it, applied here to
`app.domain.scenarios` specifically rather than folded into `valuation_
view` itself (that module is already the longest in this project; §23 is
a genuinely separate concern from §18-22's anchors — a caller wants a
Bear/Base/Bull READ of a DCF that's already computed, not a sixth anchor).

BUILT DIRECTLY ON `valuation_view.dcf_for`'S OWN BASE-CASE ASSUMPTIONS,
NOT A SECOND DERIVATION. §23's own construction rule is explicit: "Base
= assumptions as derived in §18.2." `dcf_for` already IS that derivation
— real trailing-CAGR growth, real margins, real WACC, all real-vs-
disclosed-default per that function's own docstring. Re-deriving a
second base case here (a second query, a second set of ratios) risks
silently drifting from the DCF anchor already shown elsewhere on the
same company file, which would misrepresent "Base" as agreeing with the
DCF anchor when it might not. `DCFView.assumptions` exists specifically
so this module can reuse the exact same object instead.

HISTORICAL GROWTH/MARGIN PERCENTILES, HONESTLY SCOPED TO WHAT LITTLE
HISTORY EXISTS. §23's own bear/bull construction wants the 25th/75th
percentile of a company's OWN historical growth and margin. This system
does not yet have deep confirmed history for any real company (see
`dcf_for`'s own docstring on `_trailing_cagr` needing as few as 2 periods
to run at all) — `_growth_and_margin_distribution` below computes REAL
percentiles (linear-interpolated, `_percentile`) whenever at least 2 real
year-over-year observations exist. When fewer than 2 exist (the common
case today), the distribution honestly collapses to a single point (both
P25 and P75 equal the one real base-case number) rather than a
fabricated spread — Bear/Bull dispersion in that case still comes from
the discount-rate and terminal-growth shifts §23's own table specifies
unconditionally, which is real dispersion, not none. Every
`ScenarioSetView` names which of these two cases applied via
`distribution_note`.

WHAT §23 ASKS FOR THIS SYSTEM STILL CANNOT SUPPLY, NAMED HONESTLY. The
bear scenario's archetype-specific stress and the bull scenario's
confirmed-project-register uplift both need the macro engine / national
project register wiring `app.domain.scenarios`'s own module docstring
already names as absent for THOSE two specific deltas — `build_scenario_
set` is called here with both left at their default (0), so `ScenarioSet.
note` (surfaced on `ScenarioSetView.note` unchanged) already carries that
disclosure; nothing new needs inventing here.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.dcf import DCFAssumptions
from app.domain.scenarios import (
    HistoricalGrowthMarginDistribution,
    MonteCarloInput,
    MonteCarloResult,
    ScenarioSet,
    TornadoBar,
    build_scenario_set,
    run_monte_carlo,
    sensitivity_tornado,
)
from app.domain.valuation_view import (
    DCFView,
    _confirmed_statement_line_history,
    dcf_for,
)

# §23's own illustrative tornado shock sizes — a methodology choice (how
# big a stress to apply per assumption when charting "which one moves the
# valuation most"), the same category of policy constant as `app.domain.
# scenarios.BEAR_DISCOUNT_RATE_DELTA` next to it, not a fact about any one
# company. ±100bp on the discount rate/terminal growth (the standard rate
# shock this project already uses for the Bear scenario itself) and
# ±200bp on growth/margin (double the rate shock, since a revenue growth
# or margin assumption typically moves fair value more per basis point of
# input than the discount rate does — an illustrative choice, not a
# calibrated one).
TORNADO_DELTAS: dict[str, Decimal] = {
    "discount_rate": Decimal("0.01"),
    "terminal_growth": Decimal("0.01"),
    "revenue_growth_y1": Decimal("0.02"),
    "operating_margin_current": Decimal("0.02"),
}


def _percentile(values: list[Decimal], p: int) -> Decimal:
    """Linear-interpolated percentile over an already-real (not assumed
    normal) sample — the standard method, applied here rather than a
    parametric fit because this project has no statistics dependency for
    one (see `app.domain.trend_detection`'s own "no scipy/numpy" note,
    the same constraint `app.domain.scenarios`'s own Monte Carlo overlay
    already works within via bootstrap resampling instead of a fitted
    distribution)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (Decimal(p) / Decimal(100)) * Decimal(len(ordered) - 1)
    floor_idx = int(k)
    ceil_idx = min(floor_idx + 1, len(ordered) - 1)
    frac = k - floor_idx
    return ordered[floor_idx] + (ordered[ceil_idx] - ordered[floor_idx]) * frac


def _yoy_growth_series(history: list[tuple[dt.date, Decimal]]) -> list[Decimal]:
    """One growth observation per adjacent pair of confirmed periods —
    `None`-filtering the same non-positive guard `_trailing_cagr` already
    applies (a loss-to-profit swing has no meaningful growth rate)."""
    growths: list[Decimal] = []
    for (_, prev), (_, curr) in zip(history, history[1:]):
        if prev > 0 and curr > 0:
            growths.append(curr / prev - Decimal(1))
    return growths


def _margin_series(
    revenue_history: list[tuple[dt.date, Decimal]], margin_by_period: dict[dt.date, Decimal]
) -> list[Decimal]:
    return [
        margin_by_period[period_end] / revenue
        for period_end, revenue in revenue_history
        if period_end in margin_by_period and revenue > 0
    ]


@dataclass(frozen=True)
class DistributionInputs:
    distribution: HistoricalGrowthMarginDistribution
    growth_observation_count: int
    margin_observation_count: int
    note: str


def _growth_and_margin_distribution(
    db: Session, ticker: str, as_of: dt.date, base: DCFAssumptions
) -> DistributionInputs:
    revenue_history = _confirmed_statement_line_history(db, ticker, "revenue", as_of)
    op_profit_history = dict(_confirmed_statement_line_history(db, ticker, "operating_profit", as_of))

    growths = _yoy_growth_series(revenue_history)
    margins = _margin_series(revenue_history, op_profit_history)

    notes: list[str] = []
    if len(growths) >= 2:
        growth_p25, growth_p75 = _percentile(growths, 25), _percentile(growths, 75)
        notes.append(
            f"Growth P25/P75 from {len(growths)} real year-over-year confirmed-revenue "
            "observations."
        )
    else:
        growth_p25 = growth_p75 = base.revenue_growth_y1
        notes.append(
            "Fewer than 2 year-over-year growth observations exist yet for this ticker — "
            "growth P25/P75 both collapse to the same base-case growth rate rather than a "
            "fabricated spread; Bear/Bull dispersion still comes from the real WACC/"
            "terminal-growth shifts §23 specifies unconditionally."
        )

    if len(margins) >= 2:
        margin_p25, margin_p75 = _percentile(margins, 25), _percentile(margins, 75)
        notes.append(f"Margin P25/P75 from {len(margins)} real confirmed operating-margin observations.")
    else:
        margin_p25 = margin_p75 = base.operating_margin_current
        notes.append(
            "Fewer than 2 operating-margin observations exist yet for this ticker — margin "
            "P25/P75 both collapse to the base-case margin, same reasoning as growth above."
        )

    return DistributionInputs(
        distribution=HistoricalGrowthMarginDistribution(
            growth_p25=growth_p25, growth_p75=growth_p75, margin_p25=margin_p25, margin_p75=margin_p75,
        ),
        growth_observation_count=len(growths),
        margin_observation_count=len(margins),
        note=" ".join(notes),
    )


@dataclass(frozen=True)
class ScenarioSetView:
    period_end: dt.date | None
    result: ScenarioSet | None
    distribution_note: str | None
    warnings: tuple[str, ...]


def scenario_set_for(
    db: Session,
    ticker: str,
    current_price: Decimal | None,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> ScenarioSetView:
    stamp = as_of or dt.date.today()
    dcf_view: DCFView = dcf_for(
        db, ticker, current_price, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if dcf_view.assumptions is None:
        return ScenarioSetView(
            dcf_view.period_end, None, None,
            dcf_view.warnings + (
                "Scenarios need a computable base-case DCF first (§23: 'Base = assumptions as "
                "derived in §18.2') — see the warnings above for why the DCF itself isn't "
                "computable for this company yet.",
            ),
        )

    dist = _growth_and_margin_distribution(db, ticker, stamp, dcf_view.assumptions)
    result = build_scenario_set(dcf_view.assumptions, dist.distribution)
    return ScenarioSetView(dcf_view.period_end, result, dist.note, dcf_view.warnings)


@dataclass(frozen=True)
class TornadoView:
    period_end: dt.date | None
    bars: tuple[TornadoBar, ...]
    warnings: tuple[str, ...]


def sensitivity_tornado_for(
    db: Session,
    ticker: str,
    current_price: Decimal | None,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> TornadoView:
    stamp = as_of or dt.date.today()
    dcf_view = dcf_for(
        db, ticker, current_price, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if dcf_view.assumptions is None:
        return TornadoView(dcf_view.period_end, (), dcf_view.warnings + ("No base-case DCF to perturb.",))

    bars = sensitivity_tornado(dcf_view.assumptions, TORNADO_DELTAS)
    return TornadoView(dcf_view.period_end, bars, dcf_view.warnings)


@dataclass(frozen=True)
class MonteCarloView:
    period_end: dt.date | None
    result: MonteCarloResult | None
    warnings: tuple[str, ...]


def monte_carlo_for(
    db: Session,
    ticker: str,
    current_price: Decimal | None,
    as_of: dt.date | None = None,
    *,
    draws: int = 10_000,
    seed: int | None = None,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> MonteCarloView:
    """§23's 10,000-draw bootstrap overlay, run over whichever of
    revenue-growth/operating-margin have at least one real confirmed
    historical observation for this ticker. A field with only ONE real
    observation still runs — the bootstrap just draws that same value
    every time (a real point-mass distribution, not a fabricated spread;
    `result.note` from `run_monte_carlo` already discloses "empirical
    bootstrap," which is honest even when the empirical sample has one
    point in it)."""
    stamp = as_of or dt.date.today()
    dcf_view = dcf_for(
        db, ticker, current_price, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if dcf_view.assumptions is None:
        return MonteCarloView(dcf_view.period_end, None, dcf_view.warnings + ("No base-case DCF to simulate.",))

    revenue_history = _confirmed_statement_line_history(db, ticker, "revenue", stamp)
    op_profit_history = dict(_confirmed_statement_line_history(db, ticker, "operating_profit", stamp))
    growths = tuple(_yoy_growth_series(revenue_history))
    margins = tuple(_margin_series(revenue_history, op_profit_history))

    inputs: list[MonteCarloInput] = []
    if growths:
        inputs.append(MonteCarloInput("revenue_growth_y1", growths))
        inputs.append(MonteCarloInput("revenue_growth_y2", growths))
    if margins:
        inputs.append(MonteCarloInput("operating_margin_current", margins))

    if not inputs:
        return MonteCarloView(
            dcf_view.period_end, None,
            dcf_view.warnings + (
                "No confirmed revenue or operating-margin history at all for this ticker — "
                "Monte Carlo has nothing to bootstrap from.",
            ),
        )

    result = run_monte_carlo(dcf_view.assumptions, tuple(inputs), current_price, draws=draws, seed=seed)
    return MonteCarloView(dcf_view.period_end, result, dcf_view.warnings)
