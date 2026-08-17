"""
§26: The price ladder — "five zones, derived, auditable, and they move
when the inputs move."

    Zone                Formula                                    Meaning
    Strong accumulate   < FV × (1 - MoS - 0.08)                     Materially below your required entry.
                                                                     Size toward the upper end of the tier cap.
    Accumulate          FV × (1 - MoS - 0.08) to FV × (1 - MoS)     Your limit-price band. This is the
                                                                     number you asked for.
    Fair                FV × (1 - MoS) to FV                        Reasonably priced. Hold; do not add.
    Trim                FV to FV × 1.15                             Begin scaling out. Continue only while
                                                                     momentum and thesis remain intact.
    Exit                > FV × 1.15                                 Valuation stretched. Redeploy — capital
                                                                     has an opportunity cost.

§26's own worked example (JKH.N0000, FV 24.00, MoS 30%) is transcribed
directly into this module's tests as the reference case: buy-below =
24.00 × 0.70 = 16.80, stretch = 24.00 × 1.15 = 27.60, and at a current
price of 21.40 the status line reads "27% above your buy-below price" —
(21.40 - 16.80) ÷ 16.80 ≈ 27.4%. Every one of those figures is checked
exactly, not approximately, in `test_price_ladder.py`.

Pure function over `fair_value` (from `app.domain.triangulation`) and
`margin_of_safety_pct` (from `app.domain.margin_of_safety`) — this is the
last stage of the Phase 3 pipeline those two modules feed into, mirroring
the dependency chain §24 → §25 → §26 draws in the spec itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ACCUMULATE_BAND_WIDTH = Decimal("0.08")
TRIM_MULTIPLIER = Decimal("1.15")

ZONE_MEANINGS: dict[str, str] = {
    "strong_accumulate": "Materially below your required entry. Size toward the upper end of the tier cap.",
    "accumulate": "Your limit-price band. This is the number you asked for.",
    "fair": "Reasonably priced. Hold; do not add.",
    "trim": "Begin scaling out. Continue only while momentum and thesis remain intact.",
    "exit": "Valuation stretched. Redeploy — capital has an opportunity cost.",
}


@dataclass(frozen=True)
class PriceLadderResult:
    fair_value: Decimal
    margin_of_safety_pct: Decimal
    strong_accumulate_threshold: Decimal
    """Below this: Strong accumulate."""

    buy_below_price: Decimal
    """FV × (1 - MoS) — the top of the Accumulate band, "the number you
    asked for" (§26)."""

    trim_threshold: Decimal
    """= `fair_value` itself — above this: Trim."""

    exit_threshold: Decimal
    """FV × 1.15 — above this: Exit."""

    current_price: Decimal | None
    current_zone: str | None
    zone_meaning: str | None
    gap_to_buy_below_pct: Decimal | None
    """(current - buy_below) ÷ buy_below — positive means current price
    is above your buy-below price (§26's own "27% above your buy-below
    price" framing); negative means it's already inside or below the buy
    zone."""

    warnings: tuple[str, ...]


def compute_price_ladder(
    fair_value: Decimal,
    margin_of_safety_pct: Decimal,
    current_price: Decimal | None = None,
) -> PriceLadderResult:
    warnings: list[str] = []
    if fair_value <= 0:
        warnings.append("fair_value must be positive — zones are not meaningful for a non-positive fair value.")

    strong_accumulate_threshold = fair_value * (Decimal(1) - margin_of_safety_pct - ACCUMULATE_BAND_WIDTH)
    buy_below_price = fair_value * (Decimal(1) - margin_of_safety_pct)
    trim_threshold = fair_value
    exit_threshold = fair_value * TRIM_MULTIPLIER

    zone: str | None = None
    gap: Decimal | None = None
    if current_price is not None and fair_value > 0:
        if current_price < strong_accumulate_threshold:
            zone = "strong_accumulate"
        elif current_price < buy_below_price:
            zone = "accumulate"
        elif current_price < trim_threshold:
            zone = "fair"
        elif current_price <= exit_threshold:
            zone = "trim"
        else:
            zone = "exit"
        gap = (current_price - buy_below_price) / buy_below_price if buy_below_price != 0 else None

    return PriceLadderResult(
        fair_value=fair_value,
        margin_of_safety_pct=margin_of_safety_pct,
        strong_accumulate_threshold=strong_accumulate_threshold,
        buy_below_price=buy_below_price,
        trim_threshold=trim_threshold,
        exit_threshold=exit_threshold,
        current_price=current_price,
        current_zone=zone,
        zone_meaning=ZONE_MEANINGS.get(zone) if zone else None,
        gap_to_buy_below_pct=gap,
        warnings=tuple(warnings),
    )
