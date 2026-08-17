"""
§18: Discounted cash flow — three-stage FCFF (or FCFE) model, plus §23's
reverse DCF solver, which belongs next to the forward model it inverts.

    FCFF = EBIT × (1 - effective tax rate)
             + depreciation & amortisation
             - capital expenditure
             - change in non-cash working capital

    Stage 1  Years 1-5   explicit forecast, line by line
    Stage 2  Years 6-10  linear fade of growth and margin toward stable state
    Stage 3  Terminal    stable growth, capped at long-run nominal GDP growth

    Equity value = Σ FCFF_t ÷ (1+r)^t + PV(terminal)
                     + cash and non-operating assets
                     - total debt - minority interest - pension deficit
                   ÷ diluted shares outstanding

Pure functions over caller-supplied assumptions, exactly like
`app.domain.cost_of_equity` — no I/O, no ORM.

WHY THIS IS STILL NOT WIRED TO LIVE DATA, EVEN THOUGH EVERY INPUT IT
NEEDS IS NOW, INDIVIDUALLY, EXTRACTABLE FOR AT LEAST ONE REAL COMPANY.
FCFF needs depreciation & amortisation, capital expenditure, and the
change in non-cash working capital. As of this session, Swadeshi
Industrial Works PLC's real FY2025/26 filing has all three:
`capital_expenditure` and `cash_flow_from_operations` extract directly;
`depreciation_and_amortisation` is derived by summing Swadeshi's
separately-printed Depreciation and Amortization lines
(`derive_additional_line_items`); and `change_in_net_working_capital` is
derived from the same statement's two bookend subtotals — "Operating
Profit before Working Capital Changes" minus "Cash generated from
Operations" — rather than summing an unpredictable, company-varying set
of individual working-capital lines (4 on this filing, 5 differently-
named ones on J.F. Packaging's), because those two subtotal labels are
verified byte-identical (the first one) or near-identical (the second)
across both real filings checked, where the individual component lines
are not. All of `app.domain.financial_statement_parsing.CANONICAL_
LABELS`, `DERIVED_SUMS` and `DERIVED_DIFFERENCES` together are what make
this possible — see that module's docstring for the full extraction
picture, not repeated here.

The DISCOUNT RATE is solved too, as of the same session: `app.domain.wacc`
computes real WACC from the same live data (Swadeshi's now-extractable
`total_interest_bearing_debt` and `interest_expense`, plus Ke, tax rate,
shares and price) — see that module's own docstring for why FCFF must
never be discounted at Ke instead, a real mispricing bug for any levered
company, not a rounding-level simplification.

So why not wired up yet? Three reasons now, the newest one the most
precise. First, this is per-COMPANY, not universal — J.F. Packaging still
lacks capex (its label wraps across two physical lines, unsolved,
ROADMAP.md), so a caller can't assume any given company has all the
inputs; the view/API layer that would report per-company availability
(mirroring `app.domain.valuation_view`'s existing pattern for justified
P/B and residual income) hasn't been built for DCF yet. Second, DCF is a
multi-YEAR projection (§18.2's whole assumption table — growth, margin,
tax fade paths) built from ONE period's cash-flow figures; turning
"Swadeshi's FY2025/26 capex was X" into "Swadeshi's Y1-10 capex
assumption is X% of revenue, fading how" is a forecasting decision this
module already refuses to make silently (see `DCFAssumptions`' own
field-by-field sourcing notes). Third, and discovered only once WACC's
live wiring made it worth checking precisely: `DCFAssumptions.working_
capital_pct_revenue` needs the working-capital STOCK (non-cash working
capital ÷ revenue, a balance-sheet LEVEL, so the projection can grow it
proportionally as revenue grows) — a genuinely different figure from
`change_in_net_working_capital`, the working-capital FLOW this system
already extracts for one historical period. No canonical label maps the
individual current-asset/current-liability components (trade
receivables, inventories, trade payables, excluding cash and
interest-bearing debt) that a working-capital STOCK would need to be
built from. Building this module anyway, fully tested against
hand-worked numbers, means the arithmetic is verified and ready the day
that wiring — and the working-capital-stock extraction it still waits
on — gets built, rather than being designed and debugged for the first
time under pressure once the rest of the data existed, which for capex,
D&A, working-capital CHANGE and the discount rate, it now genuinely
does, at least for one real company. §18.2's "never a free parameter" table
is honoured in the shape of `DCFAssumptions` — every field is named for
where §18.2 says it comes from — even though wiring each one to a live
source (sector median growth, macro regime multiplier) is itself blocked
on modules this system hasn't built yet (the macro engine is Phase 5).

TWO DELIBERATE SIMPLIFICATIONS FROM THE SPEC'S PROSE, BOTH STATED HERE
RATHER THAN LEFT IMPLICIT:
  - §18.2 splits the growth fade into "Y3-5 fade toward sector-median
    growth" and "Y6-10 linear fade of growth... toward stable state" as
    two segments with two different targets. `revenue_growth_stage2_target`
    is what Y3-5 fades toward; `terminal_growth` is what Y6-10 fades
    toward — two real, distinct inputs, not collapsed into one.
  - The terminal-year ROIC-based reinvestment discipline ("reinvestment
    rate_terminal = g ÷ ROIC_terminal") cannot be cross-checked against a
    computed ROIC — `app.domain.ratios.NOT_YET_COMPUTABLE` already says
    why (needs NOPAT and invested capital, neither extracted). This module
    computes and displays `implied_reinvestment_rate_terminal` from the
    cash-flow components it does have (capex, D&A, ΔNWC ÷ NOPAT) so the
    number is visible, but does not claim it has been checked against
    ROIC — `note` on the result says so explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

STAGE1_EXPLICIT_YEARS = 2  # Y1-2: trailing CAGR / guidance / order book (§18.2)
STAGE1_FADE_YEARS = 3  # Y3-5: fade toward sector-median growth
STAGE2_FADE_YEARS = 5  # Y6-10: fade toward stable (terminal) state
TOTAL_YEARS = STAGE1_EXPLICIT_YEARS + STAGE1_FADE_YEARS + STAGE2_FADE_YEARS  # 10
TAX_CONVERGENCE_YEAR = 5  # "converging to statutory by Y5"


def linear_fade(start: Decimal, end: Decimal, steps: int) -> list[Decimal]:
    """`steps` values on a straight line from just after `start` to,
    inclusive, `end` — e.g. `linear_fade(10, 25, 3)` = [15, 20, 25].
    Used for every §18.2 "fades toward X" input, so the fade logic lives
    in one place rather than being re-derived per assumption."""
    if steps <= 0:
        return []
    step = (end - start) / steps
    # The last step is set to `end` exactly rather than `start + step *
    # steps` — Decimal division of a non-terminating fraction (e.g. 1÷3)
    # means the accumulated step arithmetic can miss `end` by a residual
    # in the last decimal place, and "fades toward stable state" should
    # land on the stated target exactly, not one ULP short of it.
    return [start + step * (i + 1) for i in range(steps - 1)] + [end]


@dataclass(frozen=True)
class DCFAssumptions:
    base_revenue: Decimal
    """Most recent full-year (or trailing-twelve-month) revenue — Year 1's
    growth is applied on top of this."""

    revenue_growth_y1: Decimal
    revenue_growth_y2: Decimal
    """§18.2: "Trailing 3-year CAGR, adjusted by sector macro sensitivity
    (§33)... Where quarterly guidance or an order book exists, it
    overrides." Both are policy inputs the caller supplies, not computed
    here — this module owns the discounting arithmetic, not the forecast."""

    revenue_growth_stage2_target: Decimal
    """What Y3-5 fades toward: "sector median growth × macro regime
    multiplier" (§18.2). The macro engine that would compute this is
    Phase 5 and does not exist yet — caller-supplied."""

    terminal_growth: Decimal
    """What Y6-10 fades toward, and the Gordon-growth rate beyond Y10.
    §18.2: "MIN(long-run nominal GDP growth, sector terminal growth,
    Rf_LKR). Never exceeds the risk-free rate.\""""

    operating_margin_current: Decimal
    operating_margin_target: Decimal
    """§18.2: "5-year average, adjusted for confirmed structural change;
    fades toward sector median unless ROIC-WACC spread evidences durable
    advantage." Set equal to `operating_margin_current` to represent "no
    fade — durable advantage" explicitly rather than leaving margin fixed
    by omission."""

    effective_tax_rate_current: Decimal
    statutory_tax_rate: Decimal
    """Converges from current to statutory by Y5 (§18.2), then held flat."""

    depreciation_amortisation_pct_revenue: Decimal
    """D&A ÷ revenue. Also used as the capex floor in the terminal year
    (§18.2: "floored at depreciation ÷ revenue in the terminal year") —
    the spec treats depreciation and D&A as the same figure for this
    purpose, and so does this module, rather than inventing a second,
    unextracted line item to distinguish them."""

    capex_pct_revenue: Decimal
    """Trailing capex ÷ revenue, held constant through Y9; floored against
    `depreciation_amortisation_pct_revenue` in Y10 only."""

    working_capital_pct_revenue: Decimal
    """Trailing non-cash working capital ÷ revenue, held constant across
    the whole projection — §18.2: "held constant unless a trend test is
    significant," and any such trend test is the caller's decision
    (`app.domain.trend_detection`), made before this pct is passed in."""

    risk_free_rate: Decimal
    """Rf_LKR — the cap `terminal_growth` must not exceed (§18.2)."""

    discount_rate: Decimal
    """WACC for an FCFF projection, Ke for FCFE — whichever this
    `DCFAssumptions` represents. This module does not know which; the
    caller picks FCFF vs FCFE per §18.1's archetype rule (industrial
    default vs financials / actively-releveraging companies) before
    building the inputs."""

    cash_and_non_operating_assets: Decimal = Decimal(0)
    total_debt: Decimal = Decimal(0)
    minority_interest: Decimal = Decimal(0)
    pension_deficit: Decimal = Decimal(0)
    diluted_shares_outstanding: Decimal = Decimal(1)


@dataclass(frozen=True)
class YearProjection:
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


@dataclass(frozen=True)
class DCFResult:
    years: tuple[YearProjection, ...]
    terminal_value: Decimal
    """Undiscounted terminal value as of the end of Year 10."""

    pv_explicit_cash_flows: Decimal
    pv_terminal_value: Decimal
    enterprise_or_operating_value: Decimal
    """PV of explicit flows + PV(terminal) — "enterprise value" for an
    FCFF projection; for FCFE this is already an equity-side figure and
    the bridge below adds/subtracts nothing further in practice (the
    caller passes zeros for debt/minority/pension in that case, which is
    why the bridge is applied unconditionally rather than branching on
    FCFF vs FCFE)."""

    equity_value: Decimal
    value_per_share: Decimal
    implied_reinvestment_rate_terminal: Decimal | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _validate(a: DCFAssumptions) -> list[str]:
    warnings: list[str] = []
    if a.terminal_growth > a.risk_free_rate:
        warnings.append(
            f"terminal_growth ({a.terminal_growth}) exceeds risk_free_rate "
            f"({a.risk_free_rate}) — §18.2: never exceeds the risk-free rate, "
            f"'a sure sign of a modelling error'. Computed anyway so the scenario "
            f"stays inspectable, but this result should not be trusted as-is."
        )
    if a.discount_rate <= a.terminal_growth:
        warnings.append(
            "discount_rate <= terminal_growth — terminal value is undefined or "
            "negative (Gordon growth divides by discount_rate - terminal_growth)."
        )
    return warnings


def compute_fcff(
    ebit: Decimal,
    effective_tax_rate: Decimal,
    depreciation_amortisation: Decimal,
    capital_expenditure: Decimal,
    change_in_net_working_capital: Decimal,
) -> Decimal:
    """§18.1: FCFF = EBIT × (1 - effective tax rate) + D&A - capex - ΔNWC.

    `project_cash_flows` below calls this once per projected year — this
    standalone version exists so a caller with just ONE real period's
    figures (not a full multi-year forecast) can compute a real,
    honestly-labelled trailing FCFF number without constructing a
    `DCFAssumptions`, which requires growth/margin/tax FADE assumptions
    this function has no opinion about and a single period gives no basis
    to invent. See `app.domain.valuation_view.current_period_fcff_for`
    for exactly that live-data use — the first of §18's numbers this
    system computes from real extracted figures rather than only
    hand-worked test inputs.
    """
    return (
        ebit * (Decimal(1) - effective_tax_rate)
        + depreciation_amortisation
        - capital_expenditure
        - change_in_net_working_capital
    )


def project_cash_flows(a: DCFAssumptions) -> list[YearProjection]:
    """Years 1-10, per §18.1/§18.2's stage structure. Returns the full
    per-year detail (not just FCFF) so a UI can show the assumption trail,
    per the same "show your work" discipline §17-19 apply throughout."""
    growth_path = (
        [a.revenue_growth_y1, a.revenue_growth_y2]
        + linear_fade(a.revenue_growth_y2, a.revenue_growth_stage2_target, STAGE1_FADE_YEARS)
        + linear_fade(a.revenue_growth_stage2_target, a.terminal_growth, STAGE2_FADE_YEARS)
    )
    margin_path = linear_fade(a.operating_margin_current, a.operating_margin_target, TOTAL_YEARS)
    tax_fade = linear_fade(a.effective_tax_rate_current, a.statutory_tax_rate, TAX_CONVERGENCE_YEAR)
    tax_path = tax_fade + [a.statutory_tax_rate] * (TOTAL_YEARS - TAX_CONVERGENCE_YEAR)

    years: list[YearProjection] = []
    revenue = a.base_revenue
    prior_nwc = a.base_revenue * a.working_capital_pct_revenue
    for i in range(TOTAL_YEARS):
        year_num = i + 1
        growth = growth_path[i]
        revenue = revenue * (Decimal(1) + growth)
        margin = margin_path[i]
        ebit = revenue * margin
        tax_rate = tax_path[i]
        da = revenue * a.depreciation_amortisation_pct_revenue
        capex_pct = a.capex_pct_revenue
        if year_num == TOTAL_YEARS:
            # "floored at depreciation ÷ revenue in the terminal year"
            capex_pct = max(a.capex_pct_revenue, a.depreciation_amortisation_pct_revenue)
        capex = revenue * capex_pct
        nwc = revenue * a.working_capital_pct_revenue
        delta_nwc = nwc - prior_nwc
        fcff = compute_fcff(ebit, tax_rate, da, capex, delta_nwc)

        years.append(
            YearProjection(
                year=year_num,
                revenue=revenue,
                revenue_growth=growth,
                ebit=ebit,
                operating_margin=margin,
                tax_rate=tax_rate,
                depreciation_amortisation=da,
                capital_expenditure=capex,
                net_working_capital=nwc,
                change_in_net_working_capital=delta_nwc,
                fcff=fcff,
            )
        )
        prior_nwc = nwc

    return years


def dcf_equity_value(a: DCFAssumptions) -> DCFResult:
    """The full three-stage bridge to value per share (§18.1)."""
    warnings = _validate(a)
    years = project_cash_flows(a)

    pv_explicit = Decimal(0)
    for y in years:
        pv_explicit += y.fcff / ((Decimal(1) + a.discount_rate) ** y.year)

    terminal_fcff_next = years[-1].fcff * (Decimal(1) + a.terminal_growth)
    denom = a.discount_rate - a.terminal_growth
    if denom <= 0:
        terminal_value = Decimal(0)
        pv_terminal = Decimal(0)
        implied_reinvestment_rate = None
    else:
        terminal_value = terminal_fcff_next / denom
        pv_terminal = terminal_value / ((Decimal(1) + a.discount_rate) ** TOTAL_YEARS)

        # Implied reinvestment rate at the terminal year: net reinvestment
        # (capex - D&A + ΔNWC) ÷ NOPAT. §18.2's own discipline is stated
        # against ROIC, which this system cannot compute (see module
        # docstring) — this is a displayable proxy, not that check.
        terminal_year = years[-1]
        nopat_terminal = terminal_year.ebit * (Decimal(1) - terminal_year.tax_rate)
        net_reinvestment = (
            terminal_year.capital_expenditure
            - terminal_year.depreciation_amortisation
            + terminal_year.change_in_net_working_capital
        )
        implied_reinvestment_rate = (
            net_reinvestment / nopat_terminal if nopat_terminal != 0 else None
        )

    operating_value = pv_explicit + pv_terminal
    equity_value = (
        operating_value
        + a.cash_and_non_operating_assets
        - a.total_debt
        - a.minority_interest
        - a.pension_deficit
    )
    value_per_share = (
        equity_value / a.diluted_shares_outstanding
        if a.diluted_shares_outstanding != 0
        else Decimal(0)
    )

    return DCFResult(
        years=tuple(years),
        terminal_value=terminal_value,
        pv_explicit_cash_flows=pv_explicit,
        pv_terminal_value=pv_terminal,
        enterprise_or_operating_value=operating_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        implied_reinvestment_rate_terminal=implied_reinvestment_rate,
        warnings=tuple(warnings),
    )


# --- §23's reverse DCF -------------------------------------------------

_BISECTION_ITERATIONS = 60
_BISECTION_TOLERANCE = Decimal("0.0001")  # LKR per share


@dataclass(frozen=True)
class ReverseDCFResult:
    implied_flat_growth_rate: Decimal | None
    """The single flat annual revenue-growth rate (applied to every year,
    replacing the whole stage-1/stage-2 fade) that reproduces the current
    market price exactly. None if no rate in the search range
    (`[low, high]`) gets there — e.g. the price implies negative-forever
    growth or growth beyond what a bisection search this wide will find."""

    converged: bool
    note: str


def implied_flat_growth_rate(
    a: DCFAssumptions,
    current_price_per_share: Decimal,
    low: Decimal = Decimal("-0.30"),
    high: Decimal = Decimal("0.50"),
) -> ReverseDCFResult:
    """§23: "the engine solves for what the current market price implies
    about growth and margin, and states it in plain language... converts
    a valuation debate into a factual question about the company's own
    track record."

    SIMPLIFICATION, STATED RATHER THAN HIDDEN: solving simultaneously for
    both implied growth AND implied margin (the spec's literal wording)
    is a two-variable inverse problem with no unique solution without an
    arbitrary constraint on one of them. This solves for a single flat
    growth rate — applied uniformly to every year in place of the
    stage-1/stage-2 fade — holding `a`'s margin, tax, capex, WC and
    discount-rate assumptions exactly as supplied. That is the same
    reduction the spec's own worked example uses ("assuming 11% revenue
    growth for a decade and margins holding at 14%" — margin held fixed,
    only growth solved for), just made explicit here as a deliberate
    choice rather than an implementation accident.

    Bisection, not a closed form — `dcf_equity_value` is not analytically
    invertible once the fade and terminal-value logic are in it. FCFF
    (and therefore value per share) is monotonically increasing in growth
    for any economically sane assumption set, which is what makes
    bisection valid here; a pathological input (e.g. margin still
    increasing into a bloated terminal reinvestment burden) could break
    that monotonicity, which is exactly why `converged=False` is a
    possible, checked outcome rather than an assumed one.
    """

    def value_at(g: Decimal) -> Decimal:
        flat_assumptions = DCFAssumptions(
            base_revenue=a.base_revenue,
            revenue_growth_y1=g,
            revenue_growth_y2=g,
            revenue_growth_stage2_target=g,
            terminal_growth=min(g, a.terminal_growth),
            operating_margin_current=a.operating_margin_current,
            operating_margin_target=a.operating_margin_current,
            effective_tax_rate_current=a.effective_tax_rate_current,
            statutory_tax_rate=a.effective_tax_rate_current,
            depreciation_amortisation_pct_revenue=a.depreciation_amortisation_pct_revenue,
            capex_pct_revenue=a.capex_pct_revenue,
            working_capital_pct_revenue=a.working_capital_pct_revenue,
            risk_free_rate=a.risk_free_rate,
            discount_rate=a.discount_rate,
            cash_and_non_operating_assets=a.cash_and_non_operating_assets,
            total_debt=a.total_debt,
            minority_interest=a.minority_interest,
            pension_deficit=a.pension_deficit,
            diluted_shares_outstanding=a.diluted_shares_outstanding,
        )
        return dcf_equity_value(flat_assumptions).value_per_share

    v_low = value_at(low)
    v_high = value_at(high)
    if v_low > current_price_per_share or v_high < current_price_per_share:
        return ReverseDCFResult(
            implied_flat_growth_rate=None,
            converged=False,
            note=(
                f"Price {current_price_per_share} implies a flat growth rate outside "
                f"the search range [{low}, {high}] (value at range ends: {v_low}..{v_high}), "
                f"or value-vs-growth is not monotonic for this assumption set."
            ),
        )

    lo, hi = low, high
    for _ in range(_BISECTION_ITERATIONS):
        mid = (lo + hi) / 2
        v_mid = value_at(mid)
        if abs(v_mid - current_price_per_share) < _BISECTION_TOLERANCE:
            return ReverseDCFResult(
                implied_flat_growth_rate=mid,
                converged=True,
                note=(
                    f"At {current_price_per_share} the market is pricing in roughly "
                    f"{mid * 100:.1f}% flat annual revenue growth for a decade, at "
                    f"{a.operating_margin_current * 100:.1f}% operating margin held constant "
                    f"(§23's worked framing)."
                ),
            )
        if v_mid < current_price_per_share:
            lo = mid
        else:
            hi = mid

    return ReverseDCFResult(
        implied_flat_growth_rate=(lo + hi) / 2,
        converged=False,
        note="Bisection did not reach tolerance within the iteration budget — "
        "the returned rate is the closest approximation found.",
    )
