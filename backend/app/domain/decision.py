"""
§29-30 / §38 / §45: the final decision — one verdict, one confidence
grade, and the three price levels a human actually acts on (where to
buy, where to take profit, where to get out).

Everything upstream of this module (routing, the anchors, triangulation,
margin of safety, the price ladder, the plausibility gate) is the
WORKING. This module turns that working into the ANSWER, and does the
one thing the raw price-ladder zone never did: it attaches a confidence
grade and lets that grade GATE the verdict. The system-wide valuation
upgrade doc is explicit about why (§29, §30, principle 12): "a high DCF
cannot automatically create a Strong Buy", "data quality must constrain
recommendation confidence", quality/valuation must be separable. A
thin-data name and a deeply-covered one must not be graded by the same
one-line rule.

PURE — no database, no I/O. `app.domain.valuation_view` gathers every
input (it already computes all of them for other reasons) and passes a
`DecisionInputs` in, exactly the split `app.domain.sanity` and
`app.domain.price_ladder` already use.

THE CONFIDENCE LADDER. Start at `"high"`; each trigger below drops it
one rung (`high -> medium -> low`), and the lowest rung any trigger
reaches is the result:

  medium if:  fewer than 3 triangulation anchors
              OR triangulation dispersion > 35%
              OR ROE is a mid-cycle median over only 3-4 years
  low if:     fewer than 2 anchors
              OR dispersion > 60%
              OR ROE is a single period only (no cycle to normalise over)
              OR the plausibility gate raised a WARN (not a block)

THE VERDICT, AND HOW CONFIDENCE GATES IT. The price-ladder zone maps to
a raw verdict (`strong_accumulate -> Strong Buy`, `accumulate -> Buy`,
`fair -> Hold`, `trim -> Trim`, `exit -> Sell`). Then:

  - `low` confidence caps any BUY-SIDE verdict at `Accumulate` — never
    `Buy`, never `Strong Buy` — with the capped reason shown. Sell-side
    verdicts (`Trim`, `Sell`) are NOT capped: a weak, expensive, badly-
    covered name is still a sell.
  - `medium` confidence caps `Strong Buy` at `Buy`.

BLOCKED AND ABSENT CASES ARE STILL DIRECTIONAL WHERE THEY CAN BE. If the
plausibility gate blocked the fair value, the old behaviour was to emit
nothing. But a fair value that came out far ABOVE price and got blocked
(`fv/price > 5`) is a probable data error -> `Insufficient data`; one
that came out far BELOW price and got blocked (`fv/price < 0.2`) still
means "our numbers say this is very expensive" -> `Sell`, low
confidence. Only the genuinely ambiguous middle is `Withheld`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

VERDICTS = (
    "Strong Buy",
    "Buy",
    "Accumulate",
    "Hold",
    "Trim",
    "Sell",
    "Insufficient data",
    "Withheld",
)

_ZONE_TO_VERDICT = {
    "strong_accumulate": "Strong Buy",
    "accumulate": "Buy",
    "fair": "Hold",
    "trim": "Trim",
    "exit": "Sell",
}

_BUY_SIDE = {"Strong Buy", "Buy", "Accumulate"}

_DISPERSION_MEDIUM = Decimal("0.35")
_DISPERSION_LOW = Decimal("0.60")
_BLOCKED_CHEAP_RATIO = Decimal("0.2")
_BLOCKED_RICH_RATIO = Decimal("5.0")


@dataclass(frozen=True)
class PricePoint:
    label: str
    price: Decimal
    pct_from_current: Decimal | None
    """(price - current_price) / current_price. Negative on `buy_point`
    means the stock must fall this far to reach your entry; positive on
    the sell points means this much upside remains to that level."""


@dataclass(frozen=True)
class DecisionInputs:
    blended_fair_value: Decimal | None
    current_price: Decimal | None
    zone: str | None
    """`price_ladder.current_zone` — `None` when no positive ladder was
    built."""

    buy_below_price: Decimal | None
    take_profit_price: Decimal | None
    """= the fair value itself (`price_ladder.trim_threshold`)."""

    strong_sell_price: Decimal | None
    """= `price_ladder.exit_threshold` (fair value x 1.15)."""

    anchor_count: int
    dispersion_pct: Decimal | None
    roe_confidence: str
    """`"high"` / `"medium"` / `"low"` / `"none"` from
    `LiveValuationInputs.roe_confidence`."""

    sanity_blocked: bool
    sanity_warned: bool
    sanity_block_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionResult:
    verdict: str
    confidence: str
    """`"high"` / `"medium"` / `"low"`."""

    buy_point: PricePoint | None
    take_profit_point: PricePoint | None
    strong_sell_point: PricePoint | None
    rationale: tuple[str, ...]
    confidence_factors: tuple[str, ...]
    """Every trigger that moved the confidence grade — so the grade is
    never a bare label."""


def _pct_from(current: Decimal | None, price: Decimal | None) -> Decimal | None:
    if current is None or price is None or current == 0:
        return None
    return (price - current) / current


def _grade_confidence(inp: DecisionInputs) -> tuple[str, list[str]]:
    factors: list[str] = []
    rung = 2  # 2=high, 1=medium, 0=low

    if inp.anchor_count < 2:
        rung = min(rung, 0)
        factors.append(f"only {inp.anchor_count} triangulation anchor(s)")
    elif inp.anchor_count < 3:
        rung = min(rung, 1)
        factors.append(f"only {inp.anchor_count} triangulation anchors")

    if inp.dispersion_pct is not None:
        if inp.dispersion_pct > _DISPERSION_LOW:
            rung = min(rung, 0)
            factors.append(f"anchors disagree by {inp.dispersion_pct:.0%} (>60%)")
        elif inp.dispersion_pct > _DISPERSION_MEDIUM:
            rung = min(rung, 1)
            factors.append(f"anchors disagree by {inp.dispersion_pct:.0%} (>35%)")

    if inp.roe_confidence in ("low", "none"):
        rung = min(rung, 0)
        factors.append("ROE is a single period, not a mid-cycle figure")
    elif inp.roe_confidence == "medium":
        rung = min(rung, 1)
        factors.append("ROE normalised over only 3-4 years")

    if inp.sanity_warned:
        rung = min(rung, 0)
        factors.append("plausibility gate raised a caution")

    grade = {2: "high", 1: "medium", 0: "low"}[rung]
    if not factors:
        factors.append("3+ independent anchors, tight agreement, mid-cycle ROE")
    return grade, factors


def compute_decision(inp: DecisionInputs) -> DecisionResult:
    confidence, confidence_factors = _grade_confidence(inp)
    rationale: list[str] = []

    buy_point = (
        PricePoint("Buy below", inp.buy_below_price, _pct_from(inp.current_price, inp.buy_below_price))
        if inp.buy_below_price is not None
        else None
    )
    take_profit_point = (
        PricePoint(
            "Take profit (fair value)",
            inp.take_profit_price,
            _pct_from(inp.current_price, inp.take_profit_price),
        )
        if inp.take_profit_price is not None
        else None
    )
    strong_sell_point = (
        PricePoint(
            "Strong sell", inp.strong_sell_price, _pct_from(inp.current_price, inp.strong_sell_price)
        )
        if inp.strong_sell_price is not None
        else None
    )

    # --- No fair value at all -------------------------------------------
    if inp.blended_fair_value is None:
        rationale.append(
            "No triangulated fair value could be computed from confirmed data — no buy or "
            "sell level is offered rather than a guessed one."
        )
        return DecisionResult(
            "Insufficient data", "low", None, None, None,
            tuple(rationale), tuple(confidence_factors),
        )

    # --- Blocked by the plausibility gate -----------------------------
    if inp.sanity_blocked:
        ratio = (
            inp.blended_fair_value / inp.current_price
            if inp.current_price not in (None, Decimal(0))
            else None
        )
        for r in inp.sanity_block_reasons:
            rationale.append(r)
        if ratio is not None and ratio < _BLOCKED_CHEAP_RATIO:
            rationale.append(
                f"Fair value is only {ratio:.0%} of the current price even after being "
                "withheld as implausibly low — the directional read is still that this is "
                "very expensive on our numbers."
            )
            return DecisionResult(
                "Sell", "low", None, take_profit_point, strong_sell_point,
                tuple(rationale), tuple(confidence_factors),
            )
        if ratio is not None and ratio > _BLOCKED_RICH_RATIO:
            rationale.append(
                f"Fair value is {ratio:.1f}x the current price — almost certainly a data "
                "error (share count, units, or a mis-mapped line), not a real opportunity."
            )
            return DecisionResult(
                "Insufficient data", "low", None, None, None,
                tuple(rationale), tuple(confidence_factors),
            )
        rationale.append(
            "Fair value exists but failed the plausibility gate — withheld pending a data "
            "check; no actionable level offered."
        )
        return DecisionResult(
            "Withheld", "low", None, None, None,
            tuple(rationale), tuple(confidence_factors),
        )

    # --- Normal path: zone -> verdict --------------------------------
    if inp.zone is None:
        rationale.append(
            "A positive fair value exists but no current price was available to place it "
            "on the ladder."
        )
        return DecisionResult(
            "Insufficient data", confidence, buy_point, take_profit_point, strong_sell_point,
            tuple(rationale), tuple(confidence_factors),
        )

    verdict = _ZONE_TO_VERDICT.get(inp.zone, "Hold")
    rationale.append(
        f"Current price is in the '{inp.zone.replace('_', ' ')}' band of the price ladder."
    )

    if confidence == "low" and verdict in _BUY_SIDE and verdict != "Accumulate":
        rationale.append(
            f"Verdict capped at 'Accumulate' (raw read was '{verdict}') — low confidence: "
            + "; ".join(confidence_factors)
            + ". Size small if at all."
        )
        verdict = "Accumulate"
    elif confidence == "medium" and verdict == "Strong Buy":
        rationale.append(
            "Verdict capped at 'Buy' (raw read was 'Strong Buy') — medium confidence: "
            + "; ".join(confidence_factors)
            + "."
        )
        verdict = "Buy"

    if buy_point is not None and buy_point.pct_from_current is not None:
        if buy_point.pct_from_current >= 0:
            # buy-below sits AT or ABOVE the current price → entry is live
            rationale.append(
                f"Trading at or below your buy-below of {buy_point.price:.2f} "
                f"({buy_point.pct_from_current:.0%} of headroom) — entry available."
            )
        else:
            # current price is above the buy-below → must fall to reach entry
            rationale.append(
                f"Needs to fall {abs(buy_point.pct_from_current):.0%} to reach your "
                f"buy-below of {buy_point.price:.2f}."
            )
    if take_profit_point is not None and take_profit_point.pct_from_current is not None:
        rationale.append(
            f"Take profit around {take_profit_point.price:.2f} "
            f"({take_profit_point.pct_from_current:+.0%}); strong sell above "
            f"{strong_sell_point.price:.2f}."
            if strong_sell_point is not None
            else f"Take profit around {take_profit_point.price:.2f}."
        )

    return DecisionResult(
        verdict, confidence, buy_point, take_profit_point, strong_sell_point,
        tuple(rationale), tuple(confidence_factors),
    )
