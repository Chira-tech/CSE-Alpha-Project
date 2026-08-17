"""
§22: Asset-based and NAV valuation — "necessary for plantations, property
and hotels, and dangerous, because reported book value in these sectors
is inflated by property revaluation."

Four independent tools, each a direct rule from §22, each a pure function
over caller-supplied figures (this module extracts nothing and has no
opinion about where a revaluation-reserve figure or a per-acre reference
price came from):

  - `compute_hard_book` — strip revaluation reserves from equity; both
    figures always returned side by side, never one alone (§22 rule 1).
  - `value_land` — an independent per-acre/per-perch mark where supplied,
    otherwise cost, EXPLICITLY LABELLED as cost rather than silently
    presented as if it were a current mark (§22 rule 2: "where not
    obtainable, it stays at cost and is labelled").
  - `hotel_replacement_cost_check` — EV per key against recent build cost
    per key (§22 rule 3).
  - `compute_plantation_hard_nav` — hard NAV per hectare, mature and
    immature split, cross-checked against a recent estate transaction
    price when one is supplied (§22 rule 4).
  - `compute_liquidation_value` — "an absolute floor for distressed
    names — a genuine margin-of-safety anchor, not a target" (§22 rule 5).

WHY THIS IS NOT WIRED TO LIVE DATA YET. Every one of these needs a figure
this system doesn't extract or source anywhere: a revaluation-reserve
line item (the extractor pulls total equity, not its components — see
`app.domain.financial_statement_parsing`), an independent per-acre land
reference (no external land-valuation source is ingested), a recent
build-cost-per-key benchmark, a recent estate-transaction price, or a
liquidation-basis (as opposed to book-basis) mark on PP&E. None of these
is a gap this project can close by parsing more of the same PDFs harder —
they are genuinely external reference data. Built and tested against
hand-worked figures, same discipline as every other Phase 3 module here,
ready for whichever of these five inputs gets a real source first.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal


# --- Hard book (§22 rule 1) -------------------------------------------


@dataclass(frozen=True)
class HardBookResult:
    reported_book_value: Decimal
    revaluation_reserves: Decimal
    hard_book_value: Decimal
    hard_book_per_share: Decimal | None
    note: str = (
        "Hard book strips revaluation reserves on land and buildings from reported "
        "equity — both figures are shown side by side, never hard book alone (§22)."
    )


def compute_hard_book(
    reported_book_value: Decimal,
    revaluation_reserves: Decimal,
    diluted_shares_outstanding: Decimal | None = None,
) -> HardBookResult:
    hard = reported_book_value - revaluation_reserves
    per_share = (
        hard / diluted_shares_outstanding
        if diluted_shares_outstanding not in (None, Decimal(0))
        else None
    )
    return HardBookResult(reported_book_value, revaluation_reserves, hard, per_share)


# --- Land marks (§22 rule 2) -------------------------------------------


@dataclass(frozen=True)
class LandValuationResult:
    description: str
    area: Decimal
    area_unit: str
    value_per_unit_used: Decimal
    total_value: Decimal
    basis: str
    """`"independent_mark"` or `"cost"` — always stated, never left for
    the reader to infer from the number alone."""

    reference_date: dt.date | None
    note: str


def value_land(
    description: str,
    area: Decimal,
    area_unit: str,
    cost_basis_per_unit: Decimal,
    independent_reference_value_per_unit: Decimal | None = None,
    reference_date: dt.date | None = None,
) -> LandValuationResult:
    """§22 rule 2: mark at an independent reference where obtainable;
    otherwise stay at cost and LABEL it as cost — the label is the point,
    not an afterthought, because a cost-basis land value silently
    presented like a fresh mark is exactly the kind of understated-then-
    revalued number that makes a later "surprise" NAV jump look like new
    information when it's actually stale accounting catching up."""
    if independent_reference_value_per_unit is not None:
        value_per_unit = independent_reference_value_per_unit
        basis = "independent_mark"
        note = (
            f"Marked at an independent reference of {value_per_unit} per {area_unit}"
            + (f" as of {reference_date}." if reference_date else ", date not supplied.")
        )
    else:
        value_per_unit = cost_basis_per_unit
        basis = "cost"
        note = (
            f"No independent reference obtainable — held at cost ({value_per_unit} per "
            f"{area_unit}), labelled as cost per §22 rather than presented as a current mark."
        )
    return LandValuationResult(
        description, area, area_unit, value_per_unit, area * value_per_unit, basis, reference_date, note
    )


# --- Hotel replacement-cost cross-check (§22 rule 3) --------------------


@dataclass(frozen=True)
class HotelReplacementCostCheck:
    keys: int
    enterprise_value: Decimal
    ev_per_key: Decimal | None
    recent_build_cost_per_key: Decimal
    discount_to_replacement_cost_pct: Decimal | None
    """(build cost - EV per key) ÷ build cost — positive means the market
    is pricing the hotel below what it would cost to build today."""

    note: str


def hotel_replacement_cost_check(
    keys: int, enterprise_value: Decimal, recent_build_cost_per_key: Decimal
) -> HotelReplacementCostCheck:
    if keys <= 0:
        return HotelReplacementCostCheck(
            keys, enterprise_value, None, recent_build_cost_per_key, None,
            "keys must be positive — cannot compute EV per key.",
        )
    ev_per_key = enterprise_value / keys
    discount = (
        (recent_build_cost_per_key - ev_per_key) / recent_build_cost_per_key
        if recent_build_cost_per_key > 0
        else None
    )
    return HotelReplacementCostCheck(
        keys, enterprise_value, ev_per_key, recent_build_cost_per_key, discount,
        "§22 rule 3: EV per key against recent build cost per key.",
    )


# --- Plantation hard NAV (§22 rule 4) ------------------------------------


@dataclass(frozen=True)
class PlantationNAVResult:
    mature_hectares: Decimal
    immature_hectares: Decimal
    mature_value: Decimal
    immature_value: Decimal
    other_hard_assets: Decimal
    net_debt: Decimal
    total_hard_nav: Decimal
    blended_value_per_hectare: Decimal | None
    recent_transaction_value_per_hectare: Decimal | None
    variance_to_recent_transaction_pct: Decimal | None
    note: str


def compute_plantation_hard_nav(
    mature_hectares: Decimal,
    immature_hectares: Decimal,
    mature_value_per_hectare: Decimal,
    immature_value_per_hectare: Decimal,
    other_hard_assets: Decimal = Decimal(0),
    net_debt: Decimal = Decimal(0),
    recent_transaction_value_per_hectare: Decimal | None = None,
) -> PlantationNAVResult:
    """§22 rule 4: "hard NAV per planted hectare, split mature and
    immature, cross-checked against recent estate transactions.\""""
    mature_value = mature_hectares * mature_value_per_hectare
    immature_value = immature_hectares * immature_value_per_hectare
    total_hectares = mature_hectares + immature_hectares
    total_hard_nav = mature_value + immature_value + other_hard_assets - net_debt

    blended = (mature_value + immature_value) / total_hectares if total_hectares > 0 else None

    variance = None
    if blended is not None and recent_transaction_value_per_hectare not in (None, Decimal(0)):
        variance = (blended - recent_transaction_value_per_hectare) / recent_transaction_value_per_hectare

    return PlantationNAVResult(
        mature_hectares, immature_hectares, mature_value, immature_value,
        other_hard_assets, net_debt, total_hard_nav, blended,
        recent_transaction_value_per_hectare, variance,
        "§22 rule 4: hard NAV per planted hectare, mature/immature split, "
        "cross-checked against recent estate transactions where supplied.",
    )


# --- Liquidation value floor (§22 rule 5) -------------------------------


@dataclass(frozen=True)
class LiquidationValueResult:
    recoverable_assets: Decimal
    total_liabilities: Decimal
    liquidation_equity_value: Decimal
    liquidation_value_per_share: Decimal | None
    note: str = (
        "§22 rule 5: liquidation value as an absolute floor for distressed names — "
        "a genuine margin-of-safety anchor, not a target."
    )


def compute_liquidation_value(
    cash_and_equivalents: Decimal,
    receivables: Decimal,
    receivables_recovery_rate: Decimal,
    inventory: Decimal,
    inventory_recovery_rate: Decimal,
    ppe_at_liquidation_value: Decimal,
    other_assets_at_liquidation_value: Decimal,
    total_liabilities: Decimal,
    diluted_shares_outstanding: Decimal | None = None,
) -> LiquidationValueResult:
    """Forced-sale recovery, not book value: receivables and inventory
    are haircut by their own recovery rates rather than counted at face,
    and PP&E enters at a liquidation-basis mark the caller supplies
    (never book value — book value is precisely the number a forced sale
    does not realise)."""
    recoverable = (
        cash_and_equivalents
        + receivables * receivables_recovery_rate
        + inventory * inventory_recovery_rate
        + ppe_at_liquidation_value
        + other_assets_at_liquidation_value
    )
    equity_value = recoverable - total_liabilities
    per_share = (
        equity_value / diluted_shares_outstanding
        if diluted_shares_outstanding not in (None, Decimal(0))
        else None
    )
    return LiquidationValueResult(recoverable, total_liabilities, equity_value, per_share)
