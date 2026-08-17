"""
§21: Sum-of-the-parts — "the CSE-native valuation method, because the
largest names are conglomerates."

    SOTP equity value =
            Σ (listed subsidiaries at market value × ownership %)
        +   Σ (unlisted subsidiaries at appropriate sector EV/EBITDA or EV/EBIT)
        +   Σ investment property at hard book or independent mark
        +   Σ associates at equity-method carrying value or market where listed
        +   net cash at the holding company
        -   holdco net debt
        -   holding-company discount
        ÷   shares outstanding

Pure function over caller-supplied segment values — this module does not
know where a segment's market cap, EBITDA multiple or carrying value came
from, the same separation `app.domain.dcf` draws between the discounting
arithmetic and the forecast assumptions feeding it.

"THE HOLDING-COMPANY DISCOUNT MUST BE EARNED, NOT ASSUMED" (§21). The
spec is emphatic that a flat 20% is wrong; the discount must be calibrated
to the company's own historical average discount to its own NAV, then
adjusted for three named factors. `calibrate_holding_company_discount`
takes that historical average as a required input (this module does not
compute a trailing NAV-discount time series itself — that needs a stored
history of this company's own past SOTP outputs vs its own market price,
which does not exist yet, because no SOTP has ever been computed in this
system) and the three adjustments as separate, individually visible
terms, then clamps to §21's stated "typical range 15-35%" — clamped, not
silently substituted, so a company whose calibrated discount falls
outside that range is flagged rather than quietly forced into it.

WHY THIS MODULE IS NOT WIRED TO LIVE DATA YET. A segment breakdown
(which subsidiaries a holding company owns, at what ownership %, unlisted
or listed, with what EBITDA) is not something any ingestion source in
this project extracts — it needs either segment-reporting notes from the
annual report (well beyond the extractor's verified total/subtotal-level
scope, PARAMETERS.md #9) or a maintained group-structure register this
project does not have. Built and tested against hand-worked segment
data, same as `app.domain.dcf`, ready for that data the day it exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MIN_HOLDING_COMPANY_DISCOUNT = Decimal("0.15")
MAX_HOLDING_COMPANY_DISCOUNT = Decimal("0.35")


@dataclass(frozen=True)
class ListedSubsidiary:
    name: str
    market_cap: Decimal
    ownership_pct: Decimal

    @property
    def contribution(self) -> Decimal:
        return self.market_cap * self.ownership_pct


@dataclass(frozen=True)
class UnlistedSubsidiary:
    name: str
    ebitda_or_ebit: Decimal
    multiple: Decimal
    """Sector-appropriate EV/EBITDA or EV/EBIT multiple (§21) — which one
    `ebitda_or_ebit` represents is the caller's choice; `is_ebitda_based`
    is display metadata only, not used in the arithmetic."""

    ownership_pct: Decimal = Decimal(1)
    is_ebitda_based: bool = True

    @property
    def contribution(self) -> Decimal:
        return self.ebitda_or_ebit * self.multiple * self.ownership_pct


@dataclass(frozen=True)
class InvestmentProperty:
    description: str
    hard_book_or_independent_mark: Decimal


@dataclass(frozen=True)
class Associate:
    name: str
    carrying_value_or_market: Decimal


@dataclass(frozen=True)
class SOTPInputs:
    listed_subsidiaries: tuple[ListedSubsidiary, ...] = ()
    unlisted_subsidiaries: tuple[UnlistedSubsidiary, ...] = ()
    investment_properties: tuple[InvestmentProperty, ...] = ()
    associates: tuple[Associate, ...] = ()
    net_cash_at_holdco: Decimal = Decimal(0)
    holdco_net_debt: Decimal = Decimal(0)
    diluted_shares_outstanding: Decimal = Decimal(1)


@dataclass(frozen=True)
class HoldingCompanyDiscountResult:
    historical_average_discount_to_nav: Decimal
    capital_allocation_adjustment: Decimal
    related_party_flow_adjustment: Decimal
    free_float_adjustment: Decimal
    raw_discount_pct: Decimal
    discount_pct: Decimal
    """Clamped to [15%, 35%] (§21's "typical range")."""

    was_clamped: bool
    note: str


def calibrate_holding_company_discount(
    historical_average_discount_to_nav: Decimal,
    capital_allocation_adjustment: Decimal = Decimal(0),
    related_party_flow_adjustment: Decimal = Decimal(0),
    free_float_adjustment: Decimal = Decimal(0),
) -> HoldingCompanyDiscountResult:
    """§21: calibrated to the company's own history, then adjusted for
    capital-allocation record, related-party flow intensity, and free
    float — each an explicit, separately visible term rather than folded
    into one opaque number, per the section's own "show the calibration"
    instruction."""
    raw = (
        historical_average_discount_to_nav
        + capital_allocation_adjustment
        + related_party_flow_adjustment
        + free_float_adjustment
    )
    clamped = max(MIN_HOLDING_COMPANY_DISCOUNT, min(MAX_HOLDING_COMPANY_DISCOUNT, raw))
    was_clamped = clamped != raw
    note = (
        f"Calibrated discount {raw:.1%} is outside §21's typical 15-35% range — "
        f"clamped to {clamped:.1%}. A calibration landing outside the typical range "
        "is itself worth checking, not just accepting the clamp silently."
        if was_clamped
        else "Within §21's typical 15-35% range; not clamped."
    )
    return HoldingCompanyDiscountResult(
        historical_average_discount_to_nav=historical_average_discount_to_nav,
        capital_allocation_adjustment=capital_allocation_adjustment,
        related_party_flow_adjustment=related_party_flow_adjustment,
        free_float_adjustment=free_float_adjustment,
        raw_discount_pct=raw,
        discount_pct=clamped,
        was_clamped=was_clamped,
        note=note,
    )


@dataclass(frozen=True)
class SOTPSegment:
    label: str
    value: Decimal


@dataclass(frozen=True)
class SOTPResult:
    segments: tuple[SOTPSegment, ...]
    """Every positive-side contributor, individually — the waterfall §21
    asks the interface to render ("each segment's contribution, then the
    deductions, then the discount")."""

    gross_asset_value: Decimal
    holdco_net_debt: Decimal
    nav_before_discount: Decimal
    discount: HoldingCompanyDiscountResult
    discount_amount: Decimal
    equity_value: Decimal
    value_per_share: Decimal
    warnings: tuple[str, ...]


def compute_sotp(inputs: SOTPInputs, discount: HoldingCompanyDiscountResult) -> SOTPResult:
    segments: list[SOTPSegment] = []
    for sub in inputs.listed_subsidiaries:
        segments.append(SOTPSegment(f"Listed subsidiary: {sub.name}", sub.contribution))
    for sub in inputs.unlisted_subsidiaries:
        segments.append(SOTPSegment(f"Unlisted subsidiary: {sub.name}", sub.contribution))
    for prop in inputs.investment_properties:
        segments.append(SOTPSegment(f"Investment property: {prop.description}", prop.hard_book_or_independent_mark))
    for assoc in inputs.associates:
        segments.append(SOTPSegment(f"Associate: {assoc.name}", assoc.carrying_value_or_market))
    segments.append(SOTPSegment("Net cash at holdco", inputs.net_cash_at_holdco))

    gross = sum((s.value for s in segments), Decimal(0))
    nav_before_discount = gross - inputs.holdco_net_debt

    warnings: list[str] = []
    if nav_before_discount <= 0:
        warnings.append(
            "NAV before discount is zero or negative — a holding-company discount on a "
            "non-positive NAV is not economically meaningful; discount_amount is 0 rather "
            "than making the value larger."
        )
        discount_amount = Decimal(0)
    else:
        discount_amount = nav_before_discount * discount.discount_pct

    equity_value = nav_before_discount - discount_amount
    value_per_share = (
        equity_value / inputs.diluted_shares_outstanding
        if inputs.diluted_shares_outstanding != 0
        else Decimal(0)
    )

    return SOTPResult(
        segments=tuple(segments),
        gross_asset_value=gross,
        holdco_net_debt=inputs.holdco_net_debt,
        nav_before_discount=nav_before_discount,
        discount=discount,
        discount_amount=discount_amount,
        equity_value=equity_value,
        value_per_share=value_per_share,
        warnings=tuple(warnings),
    )
