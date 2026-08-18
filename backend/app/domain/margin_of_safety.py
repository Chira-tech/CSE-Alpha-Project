"""
§25: Margin of safety — "computed, never habitual. A flat '20% margin of
safety' is a superstition."

    Component            Rule                                          Range
    Base                 Fixed                                         10%
    Dispersion            (max FV - min FV) ÷ mean FV × 0.5             0-15%
    Liquidity             Amihud percentile mapped: top quartile → 0%,  0-10%
                           bottom quartile → 10%
    Regime                 Risk-On 0% / Transition +5% / Risk-Off +12%  0-12%
    Quality / integrity    (70 - integrity_score) × 4, floored at 0     0-8%
    Data completeness      (90 - completeness_%) × 5, floored at 0      0-10%

    MoS_total = base + dispersion + liquidity + regime + quality + completeness
                bounded 10% to 55%

Pure function over the six components — each independently computed
elsewhere in this system (or not yet computable, see below) and fed in
here. This module's only job is the arithmetic and the bounding, exactly
mirroring `app.domain.cost_of_equity`'s split between "the formula" and
"where each term comes from."

TWO FORMULAS' NUMBERS ONLY MAKE SENSE AS PERCENTAGE-POINT ARITHMETIC
THAT'S ALREADY BEEN CLAMPED TO THE STATED RANGE — STATED HERE RATHER THAN
LEFT FOR THE READER TO DISCOVER BY SURPRISE. §25's own worked numbers
(quality/integrity "0-8%", data completeness "0-10%") only reconcile with
their formulas if the Range column is a clamp applied AFTER the formula,
not a separate constraint — e.g. an integrity_score of 50 gives
`(70-50)×4 = 80` (percentage points), which is obviously not an 80%
margin-of-safety component; it is a component that formula-produces 80
and the Range column then caps at 8. Every component below is computed
exactly this way: raw formula, then clamped to its stated range.

QUALITY/INTEGRITY DOES NOT EXIST AS A CONTINUOUS SCORE IN THIS SYSTEM,
AND THAT IS A DELIBERATE CHOICE MADE ELSEWHERE, NOT A GAP IN THIS MODULE.
§11.1's Gate 3 (`app.domain.coverage_gates.evaluate_gate3_integrity`) is
"a hard veto and must never be folded into a weighted score... 'If
integrity is a scored input, a sufficiently attractive valuation will
always outvote it.'" So no 0-100 continuous integrity score is computed
anywhere in this codebase, by design — Gate 3 only ever answers pass/
fail. §25's use is a genuinely different question (pricing residual
integrity concern INTO a name that already cleared the Gate 3 veto, not
deciding capital eligibility), so it isn't in tension with §11.1's
reasoning, but this system still has no score to feed it. `integrity_
score=None` is therefore the honest default until such a score exists —
this component is NOT_YET_COMPUTABLE in exactly the sense
`app.domain.ratios.NOT_YET_COMPUTABLE` uses that phrase, and is treated
the same way `app.domain.cost_of_equity` treats a missing size or
illiquidity premium: omitted from the sum, named in `missing_components`,
and `is_lower_bound=True` on the result — a missing component can only
ever REDUCE the computed margin of safety below what it should be, never
inflate it, so a result built on a gap is a floor, not a complete number.

LIQUIDITY'S QUARTILE MAPPING NEEDS AN INTERPOLATION RULE §25 DOESN'T
STATE, SO ONE IS CHOSEN AND NAMED. §25 gives two anchor points only (top
quartile → 0%, bottom quartile → 10%); `liquidity_component` interpolates
linearly between the 25th and 75th percentile boundaries and holds flat
outside them — a provisional, explicit choice, same discipline as
PARAMETERS.md's own defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.liquidity import liquidity_percentile_band

BASE_MOS_PCT = Decimal("0.10")

DISPERSION_MULTIPLIER = Decimal("0.5")
DISPERSION_CAP = Decimal("0.15")

LIQUIDITY_CAP = Decimal("0.10")

REGIME_MOS_PCT: dict[str, Decimal] = {
    "risk_on": Decimal("0.00"),
    "transition": Decimal("0.05"),
    "risk_off": Decimal("0.12"),
}

QUALITY_INTEGRITY_THRESHOLD = Decimal("0.70")
QUALITY_INTEGRITY_MULTIPLIER = Decimal(4)
QUALITY_INTEGRITY_CAP = Decimal("0.08")

DATA_COMPLETENESS_THRESHOLD = Decimal("0.90")
DATA_COMPLETENESS_MULTIPLIER = Decimal(5)
DATA_COMPLETENESS_CAP = Decimal("0.10")

TOTAL_MOS_FLOOR = Decimal("0.10")
TOTAL_MOS_CEILING = Decimal("0.55")


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def dispersion_component(dispersion_pct: Decimal | None) -> Decimal | None:
    """§25: (max FV - min FV) ÷ mean FV × 0.5, capped at 15%.
    `dispersion_pct` is exactly `app.domain.triangulation.TriangulationResult.
    dispersion_pct` — this is that number's second use, per §24's own
    "dispersion therefore feeds directly into the margin-of-safety
    calculation.\""""
    if dispersion_pct is None:
        return None
    return _clamp(dispersion_pct * DISPERSION_MULTIPLIER, Decimal(0), DISPERSION_CAP)


def liquidity_component(liquidity_percentile: Decimal | None) -> Decimal | None:
    """`liquidity_percentile` is 0-100, HIGHER = MORE liquid (the top
    quartile of a liquidity ranking, not of the Amihud illiquidity ratio
    itself, which runs the opposite direction). The interpolation rule
    itself now lives in `app.domain.liquidity.liquidity_percentile_band`
    — extracted once `app.domain.cost_of_equity`'s own illiquidity_
    premium (§17.2: "0 to ~3.0%, mapped from the Amihud percentile")
    needed the exact same shape with a different cap, rather than
    re-deriving it a second time."""
    return liquidity_percentile_band(liquidity_percentile, LIQUIDITY_CAP)


def regime_component(regime: str | None) -> Decimal | None:
    """`regime` is one of `"risk_on"`, `"transition"`, `"risk_off"` —
    §29-33's regime classifier (§31, Phase 5 — live since 18 Aug 2026,
    wired into `GET /valuation/{ticker}` via `app.domain.macro_engine_
    view.regime_for`, see ROADMAP.md's "§31 regime classifier" entry).
    Still `None` here only when the regime read itself is unavailable
    (e.g. genuinely insufficient real market data), not because this
    component is unbuilt."""
    if regime is None:
        return None
    return REGIME_MOS_PCT.get(regime)


def quality_integrity_component(integrity_score: Decimal | None) -> Decimal | None:
    """`integrity_score` is a 0-1 fraction (0.70 = "70"), for consistency
    with every other percentage in this codebase. See module docstring:
    this is `None` by default across the whole system today — no
    continuous integrity score is computed anywhere, deliberately."""
    if integrity_score is None:
        return None
    raw = (QUALITY_INTEGRITY_THRESHOLD - integrity_score) * QUALITY_INTEGRITY_MULTIPLIER
    return _clamp(raw, Decimal(0), QUALITY_INTEGRITY_CAP)


def data_completeness_component(completeness_pct: Decimal | None) -> Decimal | None:
    """`completeness_pct` is the same 0-1 fraction
    `app.domain.coverage_gates.classify_coverage_tier` already takes."""
    if completeness_pct is None:
        return None
    raw = (DATA_COMPLETENESS_THRESHOLD - completeness_pct) * DATA_COMPLETENESS_MULTIPLIER
    return _clamp(raw, Decimal(0), DATA_COMPLETENESS_CAP)


@dataclass(frozen=True)
class MarginOfSafetyResult:
    base_pct: Decimal
    dispersion_pct: Decimal | None
    liquidity_pct: Decimal | None
    regime_pct: Decimal | None
    quality_integrity_pct: Decimal | None
    data_completeness_pct: Decimal | None
    total_pct: Decimal
    was_bounded: bool
    is_lower_bound: bool
    missing_components: tuple[str, ...]
    note: str


def compute_margin_of_safety(
    dispersion_pct: Decimal | None,
    liquidity_percentile: Decimal | None,
    regime: str | None,
    integrity_score: Decimal | None,
    data_completeness_pct: Decimal | None,
) -> MarginOfSafetyResult:
    dispersion = dispersion_component(dispersion_pct)
    liquidity = liquidity_component(liquidity_percentile)
    regime_pct = regime_component(regime)
    quality = quality_integrity_component(integrity_score)
    completeness = data_completeness_component(data_completeness_pct)

    named = {
        "dispersion": dispersion,
        "liquidity": liquidity,
        "regime": regime_pct,
        "quality_integrity": quality,
        "data_completeness": completeness,
    }
    missing = tuple(name for name, value in named.items() if value is None)

    raw_total = BASE_MOS_PCT + sum((v for v in named.values() if v is not None), Decimal(0))
    total = _clamp(raw_total, TOTAL_MOS_FLOOR, TOTAL_MOS_CEILING)
    was_bounded = total != raw_total

    is_lower_bound = bool(missing)
    note_parts = []
    if was_bounded:
        note_parts.append(f"Raw total {raw_total:.1%} bounded to §25's 10%-55% range.")
    if is_lower_bound:
        note_parts.append(
            f"Missing component(s) {missing} treated as 0 rather than guessed — every "
            "component here is non-negative by construction, so a missing one can only "
            "REDUCE this total below what it should be. This result is a LOWER BOUND on "
            "the required margin of safety, not a complete figure."
        )
    note = " ".join(note_parts) or "All five components present; not bounded."

    return MarginOfSafetyResult(
        base_pct=BASE_MOS_PCT,
        dispersion_pct=dispersion,
        liquidity_pct=liquidity,
        regime_pct=regime_pct,
        quality_integrity_pct=quality,
        data_completeness_pct=completeness,
        total_pct=total,
        was_bounded=was_bounded,
        is_lower_bound=is_lower_bound,
        missing_components=missing,
        note=note,
    )
