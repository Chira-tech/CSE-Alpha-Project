"""
§17.2: Ke = Rf_LKR + β_adjusted × ERP_effective + size_premium + illiquidity_premium

"Whichever route, the resulting Ke is displayed with its components
broken out" — this module's whole output is that breakdown, never a
single number standing alone. Pure function: every component is supplied
by the caller, so this module has no I/O and no opinion about where
Rf_LKR or beta came from.

TWO OF THE FOUR TERMS ARE NOT YET COMPUTABLE, AND Ke SAYS SO RATHER THAN
SILENTLY TREATING THEM AS ZERO. `size_premium` needs free-float market
cap deciles (free float isn't ingested — the same Gate 2 gap this project
has documented since early in Phase 1). `illiquidity_premium` needs the
Amihud percentile (needs real turnover history, confirmed blocked this
session — see ROADMAP.md's Gate 1 investigation). Both premiums are
non-negative by construction ("0 to ~2.5%", "0 to ~3.0%"), so treating a
missing one as 0 is not a neutral placeholder — it can only ever
UNDERSTATE Ke, never overstate it. `is_lower_bound` says so explicitly,
and `missing_components` names exactly what would need to exist to close
the gap, the same NOT_YET_COMPUTABLE discipline `app.domain.ratios`
already applies to individual ratios.

ERP_EFFECTIVE IS A POLICY PARAMETER, NOT SOMETHING COMPUTED. §17.1: "the
implied ERP is reverse-engineered from current ASPI earnings yield as a
third reference point" — that figure already exists in this system as
§29's hero spread (`app.domain.macro_view.current_spread`) and is passed
in here as `implied_erp_cross_check` for display alongside the
configured value, never as a silent substitute for it. `settings.erp_effective_pct`
(PARAMETERS.md #10) is an explicit, provisional default pending the
quarterly review against Damodaran's country dataset §17.1 itself calls
for — this system has no live access to that dataset, so pretending a
precise, sourced figure exists here would be worse than a stated
placeholder.

§17.2's "REGIME LINKAGE" — CLOSING THE LOOP §31's REGIME CLASSIFIER
OPENED (17 Aug). §17.2's own text: "The equity risk premium and the
risk-free rate are both regime-conditional inputs supplied by the macro
engine (§31). When the regime flips toward Risk-Off, Ke rises, and every
fair value in the system falls automatically, overnight, without anyone
forming an opinion." `regime_erp_adjustment` below is where that link
lives — added to `erp_effective` by the caller (`app.domain.cost_of_
equity_view.cost_of_equity_for`), never inside `compute_cost_of_equity`
itself, which stays pure arithmetic over whatever `erp_effective` it's
handed, the same separation `app.domain.dcf`'s `dcf_equity_value` draws
from `app.domain.valuation_view.dcf_for`'s assumption-building.

`Rf_LKR` IS DELIBERATELY NOT SEPARATELY REGIME-ADJUSTED, even though
§17.2 lists it alongside ERP as "regime-conditional". `Rf_LKR` is already
a live, real 364-day T-bill observation
(`app.domain.macro_view.risk_free_observation`) — a Risk-Off regime's
own defining signature (§31: "rising yields") is already reflected
organically in that live number. Adding a SEPARATE regime premium on top
of an already-regime-reflecting live rate would double-count the same
information once as "the observed rate" and again as "a regime
adjustment to the observed rate" — precisely the "double-count trap"
§17.1 itself names for the ERP/country-risk relationship, recognised
here in a different place in the same formula.

THE MAGNITUDE IS A DISCLOSED REUSE, NOT AN INDEPENDENTLY INVENTED
NUMBER. §17.2's own prose is qualitative only ("Ke rises") — it gives no
separate numeric table for how much, unlike §25's margin-of-safety
regime add, which IS fully specified (Risk-On +0% / Transition +5% /
Risk-Off +12%). Rather than inventing a second, unrelated regime-
sensitivity scale with no textual basis, `regime_erp_adjustment` reuses
`app.domain.margin_of_safety.REGIME_MOS_PCT` exactly — the one regime-
sensitivity scale this spec actually commits to a number for. This is a
disclosed policy choice (PARAMETERS.md #16), not a spec-mandated figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.margin_of_safety import REGIME_MOS_PCT


def regime_erp_adjustment(regime: str | None) -> Decimal:
    """`regime` is one of `"risk_on"`/`"transition"`/`"risk_off"` (`app.
    domain.regime_classification.RegimeLabel`) or `None` when no regime
    read exists yet — see module docstring for the reasoning and the
    exact numbers reused. `None` regime gives a zero adjustment, the
    same "no information changes the baseline" default this project uses
    throughout, never a guessed direction."""
    if regime is None:
        return Decimal(0)
    return REGIME_MOS_PCT.get(regime, Decimal(0))


@dataclass(frozen=True)
class CostOfEquityInputs:
    risk_free_rate: Decimal | None
    """Rf_LKR — the 364-day T-bill primary yield (§17.1 Route A). None
    means not yet observed (`app.domain.macro_view.risk_free_observation`
    returns None rather than substituting a shorter tenor) — Ke cannot be
    computed without it, the same as a missing beta."""

    beta: Decimal | None
    """Dimson-Blume adjusted beta (`app.domain.beta`). None means not yet
    computable for this security — Ke cannot be computed at all without
    it, unlike the two premium terms below."""

    erp_effective: Decimal
    size_premium: Decimal | None = None
    illiquidity_premium: Decimal | None = None
    implied_erp_cross_check: Decimal | None = None
    """§17.1's third reference point — the ASPI earnings-yield-minus-Rf
    spread, read as an implied ERP rather than a "cheap/expensive"
    signal. Display-only: never substituted for `erp_effective`."""


@dataclass(frozen=True)
class CostOfEquityResult:
    ke: Decimal | None
    risk_free_rate: Decimal | None
    beta: Decimal | None
    erp_effective: Decimal
    beta_times_erp: Decimal | None
    size_premium: Decimal | None
    illiquidity_premium: Decimal | None
    implied_erp_cross_check: Decimal | None
    is_lower_bound: bool
    missing_components: tuple[str, ...]
    note: str


def compute_cost_of_equity(inputs: CostOfEquityInputs) -> CostOfEquityResult:
    missing: list[str] = []

    if inputs.risk_free_rate is None:
        missing.append(
            "risk_free_rate (app.domain.macro_view.risk_free_observation — no 364-day "
            "T-bill yield observed yet)"
        )
    if inputs.beta is None:
        missing.append("beta (app.domain.beta — insufficient trading history for this security)")
    if inputs.size_premium is None:
        missing.append("size_premium (needs free-float market cap decile — free float not ingested)")
    if inputs.illiquidity_premium is None:
        missing.append(
            "illiquidity_premium (needs Amihud percentile — needs real turnover history, "
            "confirmed unavailable this session)"
        )

    if inputs.risk_free_rate is None or inputs.beta is None:
        blocking = [
            name for name, present in (("risk_free_rate", inputs.risk_free_rate), ("beta", inputs.beta))
            if present is None
        ]
        return CostOfEquityResult(
            ke=None,
            risk_free_rate=inputs.risk_free_rate,
            beta=inputs.beta,
            erp_effective=inputs.erp_effective,
            beta_times_erp=None,
            size_premium=inputs.size_premium,
            illiquidity_premium=inputs.illiquidity_premium,
            implied_erp_cross_check=inputs.implied_erp_cross_check,
            is_lower_bound=False,
            missing_components=tuple(missing),
            note=f"Cannot compute Ke without {' and '.join(blocking)} — every other "
            f"component is displayable but the formula has no result without it.",
        )

    beta_times_erp = inputs.beta * inputs.erp_effective
    ke = (
        inputs.risk_free_rate
        + beta_times_erp
        + (inputs.size_premium or Decimal(0))
        + (inputs.illiquidity_premium or Decimal(0))
    )

    size_or_illiquidity_missing = inputs.size_premium is None or inputs.illiquidity_premium is None
    note = (
        "Ke omits size_premium and/or illiquidity_premium — both are non-negative by "
        "definition (§17.2: 0 to ~2.5% and 0 to ~3.0%), so this Ke is a LOWER BOUND, "
        "not a complete estimate. A missing premium understates required return; it never "
        "overstates it."
        if size_or_illiquidity_missing
        else "All four components present."
    )

    return CostOfEquityResult(
        ke=ke,
        risk_free_rate=inputs.risk_free_rate,
        beta=inputs.beta,
        erp_effective=inputs.erp_effective,
        beta_times_erp=beta_times_erp,
        size_premium=inputs.size_premium,
        illiquidity_premium=inputs.illiquidity_premium,
        implied_erp_cross_check=inputs.implied_erp_cross_check,
        is_lower_bound=size_or_illiquidity_missing,
        missing_components=tuple(missing),
        note=note,
    )
