"""
§18.1's discount rate for an FCFF projection — WACC, not Ke.

    Kd (pre-tax)    = interest_expense ÷ total_interest_bearing_debt
    Kd (after-tax)  = Kd (pre-tax) × (1 - effective_tax_rate)
    We              = market value of equity ÷ (market value of equity + book value of debt)
    Wd              = book value of debt ÷ (market value of equity + book value of debt)
    WACC            = We × Ke + Wd × Kd (after-tax)

WHY THIS MODULE EXISTS AT ALL, RATHER THAN JUST REUSING Ke. §18.1's FCFF
is an UNLEVERED cash flow — it belongs to both debt and equity holders
before either is paid, which is exactly why interest expense is never
subtracted in its formula (`app.domain.dcf.compute_fcff`). Discounting
that unlevered cash flow at Ke (a LEVERED, equity-only required return)
is a real methodological error, not a rounding-level simplification —
it systematically misprices any company with debt on its balance sheet,
understating the true discount rate for a levered firm and therefore
overstating its DCF value. §18.1 itself is explicit that FCFE (discounted
at Ke) is the archetype-specific alternative for financials and
companies "where leverage is being actively changed" — not the default
for an ordinary operating company like the one this module was built
for. This module exists so `app.domain.dcf`'s FCFF path never has to
make that substitution silently.

MARKET VALUE OF EQUITY, BOOK VALUE OF DEBT — STATED, NOT HIDDEN. Textbook
WACC wants the MARKET value of both. Equity's market value is directly
observable (shares outstanding × price) and used here. Debt's market
value generally is NOT observable for a CSE-listed company's bank loans
and private notes — no public bond market exists to mark them to — so
book value (the balance-sheet carrying amount) is the standard practical
proxy, used explicitly rather than pretending a market figure exists.

WHY A MISSING COST OF DEBT IS NEVER TREATED AS ZERO. Every other "missing
component" pattern in this codebase (`app.domain.cost_of_equity`'s size
and illiquidity premiums) can safely default a gap to zero because the
missing term is additive and non-negative — a missing premium can only
UNDERSTATE the result, the safe direction. A missing cost of debt is
different: it is a WEIGHTED AVERAGE term, and treating it as zero when
the company genuinely has debt (a positive `Wd`) would pull WACC DOWN
toward `We × Ke` alone — understating the discount rate and therefore
OVERSTATING every DCF value built on it, the dangerous direction. So a
company with debt but no computable cost of debt gets no WACC at all
here, not a lower-bound one — see `compute_wacc`'s own docstring.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostOfDebtResult:
    pre_tax_cost_of_debt: Decimal | None
    after_tax_cost_of_debt: Decimal | None
    note: str


def compute_cost_of_debt(
    interest_expense: Decimal | None,
    total_interest_bearing_debt: Decimal | None,
    effective_tax_rate: Decimal | None,
) -> CostOfDebtResult:
    if interest_expense is None or total_interest_bearing_debt is None:
        return CostOfDebtResult(
            None, None, "Missing interest_expense or total_interest_bearing_debt."
        )
    if total_interest_bearing_debt <= 0:
        return CostOfDebtResult(
            None, None, "Not meaningful without positive total_interest_bearing_debt."
        )
    pre_tax = interest_expense / total_interest_bearing_debt

    if effective_tax_rate is None:
        return CostOfDebtResult(
            pre_tax, None,
            "Pre-tax cost of debt computed; effective_tax_rate unavailable, so the "
            "after-tax figure §18.1's WACC actually needs is not.",
        )
    after_tax = pre_tax * (Decimal(1) - effective_tax_rate)
    return CostOfDebtResult(
        pre_tax, after_tax,
        "Kd (pre-tax) = interest expense ÷ total interest-bearing debt; "
        "after-tax = Kd × (1 - effective tax rate).",
    )


@dataclass(frozen=True)
class WACCResult:
    market_value_of_equity: Decimal | None
    book_value_of_debt: Decimal | None
    equity_weight: Decimal | None
    debt_weight: Decimal | None
    cost_of_equity: Decimal | None
    after_tax_cost_of_debt: Decimal | None
    wacc: Decimal | None
    missing_components: tuple[str, ...]
    note: str


def compute_wacc(
    shares_outstanding: Decimal | None,
    current_price: Decimal | None,
    total_interest_bearing_debt: Decimal | None,
    cost_of_equity: Decimal | None,
    after_tax_cost_of_debt: Decimal | None,
) -> WACCResult:
    """Unlike `app.domain.cost_of_equity.compute_cost_of_equity`, this
    never returns a "lower bound" partial result — see the module
    docstring for why a missing cost of debt can't be safely defaulted
    to zero the way a missing risk premium can. WACC here is either
    computed in full or not returned at all.
    """
    missing: list[str] = []

    market_value_of_equity = None
    if shares_outstanding is None or current_price is None:
        missing.append("market value of equity (needs shares_outstanding and current_price)")
    else:
        market_value_of_equity = shares_outstanding * current_price

    if total_interest_bearing_debt is None:
        missing.append("total_interest_bearing_debt")
    if cost_of_equity is None:
        missing.append("cost_of_equity")
    if after_tax_cost_of_debt is None:
        missing.append("after_tax_cost_of_debt")

    if market_value_of_equity is None or total_interest_bearing_debt is None or cost_of_equity is None:
        return WACCResult(
            market_value_of_equity, total_interest_bearing_debt, None, None,
            cost_of_equity, after_tax_cost_of_debt, None, tuple(missing),
            f"Cannot compute WACC — missing: {', '.join(missing)}.",
        )

    total_capital = market_value_of_equity + total_interest_bearing_debt
    if total_capital <= 0:
        return WACCResult(
            market_value_of_equity, total_interest_bearing_debt, None, None,
            cost_of_equity, after_tax_cost_of_debt, None, tuple(missing),
            "Not meaningful — market value of equity plus debt is zero or negative.",
        )

    equity_weight = market_value_of_equity / total_capital
    debt_weight = total_interest_bearing_debt / total_capital

    if after_tax_cost_of_debt is None:
        # debt_weight > 0 here (total_interest_bearing_debt was required
        # to be > None and total_capital > 0 above) — a genuinely levered
        # company with no computable cost of debt. See module docstring:
        # defaulting the missing term to zero would UNDERSTATE WACC and
        # OVERSTATE every DCF value built on it, so this returns no WACC
        # at all rather than a falsely-precise partial one.
        return WACCResult(
            market_value_of_equity, total_interest_bearing_debt, equity_weight, debt_weight,
            cost_of_equity, None, None, tuple(missing),
            f"Debt weight is {debt_weight:.1%} of capital but after-tax cost of debt is "
            "unavailable — cannot compute WACC without it. Treating it as zero would "
            "understate the discount rate and overstate every DCF value built on it, "
            "so no WACC is returned rather than a falsely precise one.",
        )

    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt
    return WACCResult(
        market_value_of_equity, total_interest_bearing_debt, equity_weight, debt_weight,
        cost_of_equity, after_tax_cost_of_debt, wacc, (),
        "WACC = equity_weight × Ke + debt_weight × after-tax Kd.",
    )
