"""
§24: Triangulation — "three to five anchors per company, blended by
archetype."

    Archetype                    Intrinsic  Asset/SOTP  Relative  Note
    Operating co., stable earnings   0.45      0.15       0.40    DCF-led
    Conglomerate / holding           0.20      0.55       0.25    SOTP-led
    Bank / finance                   0.40      0.35       0.25    Equity-side only
    Cyclical (hotels, plantations,   0.30      0.35       0.35    All earnings mid-cycle
      construction)
    Property                         0.25      0.55       0.20    NAV-led
    Insurance                        0.45      0.35       0.20    Embedded-value led

    FV_blended = Σ (w_i × FV_i)
    dispersion = (max FV_i - min FV_i) ÷ mean FV_i

"DISPERSION IS A SIGNAL, NOT AN INCONVENIENCE" (§24) — "when three
independent methods land within 8% of each other, you understand the
business. When they span 45%, you do not... Dispersion therefore feeds
directly into the margin-of-safety calculation in §25." `dispersion_pct`
here is exactly the number `app.domain.margin_of_safety`'s dispersion
component reads.

THE SIX-ROW TABLE VS APPENDIX P2's FIFTEEN ARCHETYPES. §24's table groups
archetypes into six triangulation categories, not the fifteen §16's model
router already distinguishes. Rather than hand-coding a second,
potentially-inconsistent archetype→category list, `triangulation_
category_for_archetype` derives the category from the `RoutingDecision`
`app.domain.valuation_router.route_valuation` already computes — its
`is_financial_firm`, `is_holding_company` and `requires_earnings_
normalisation` flags map directly onto "Bank/finance", "Conglomerate/
holding" and "Cyclical" respectively, so the two modules can never
silently disagree about which bucket an archetype falls into. Only
"Insurance" and "Property" need the raw archetype name, because neither
has a dedicated boolean on `RoutingDecision` (insurance IS a financial
firm per that flag, same as a bank, so it needs its own explicit check
first; property has none of the three flags set, the same as an
ordinary operating company, so it too needs an explicit check before
falling through to "Operating").
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal

from app.domain.valuation_router import RoutingDecision


@dataclass(frozen=True)
class TriangulationWeights:
    category: str
    intrinsic_weight: Decimal
    asset_sotp_weight: Decimal
    relative_weight: Decimal
    note: str


TRIANGULATION_WEIGHTS: dict[str, TriangulationWeights] = {
    "operating": TriangulationWeights("operating", Decimal("0.45"), Decimal("0.15"), Decimal("0.40"), "DCF-led"),
    "conglomerate_holding": TriangulationWeights(
        "conglomerate_holding", Decimal("0.20"), Decimal("0.55"), Decimal("0.25"), "SOTP-led"
    ),
    "bank_finance": TriangulationWeights(
        "bank_finance", Decimal("0.40"), Decimal("0.35"), Decimal("0.25"), "Equity-side only"
    ),
    "cyclical": TriangulationWeights(
        "cyclical", Decimal("0.30"), Decimal("0.35"), Decimal("0.35"), "All earnings mid-cycle"
    ),
    "property": TriangulationWeights("property", Decimal("0.25"), Decimal("0.55"), Decimal("0.20"), "NAV-led"),
    "insurance": TriangulationWeights(
        "insurance", Decimal("0.45"), Decimal("0.35"), Decimal("0.20"), "Embedded-value led"
    ),
}


def triangulation_category_for_archetype(routing: RoutingDecision) -> str | None:
    """`None` when the archetype isn't confirmed, isn't one of Appendix
    P2's 15, or (rare) isn't in §24's published table at all — the same
    honesty `RoutingDecision.in_published_table` already tracks."""
    if routing.archetype is None or not routing.in_published_table:
        return None
    if routing.archetype == "insurance":
        return "insurance"
    if routing.is_financial_firm:
        return "bank_finance"
    if routing.is_holding_company:
        return "conglomerate_holding"
    if routing.archetype == "property":
        return "property"
    if routing.requires_earnings_normalisation:
        return "cyclical"
    return "operating"


ANCHOR_CATEGORIES = ("intrinsic", "asset_sotp", "relative")


@dataclass(frozen=True)
class ValuationAnchor:
    method: str
    """Human-readable label — "FCFF DCF", "Residual income", "Justified
    P/B" — shown next to the number, per this project's "never a bare
    figure" convention."""

    category: str
    """One of `ANCHOR_CATEGORIES`."""

    fair_value_per_share: Decimal


@dataclass(frozen=True)
class TriangulationResult:
    triangulation_category: str | None
    weights: TriangulationWeights | None
    category_averages: dict[str, Decimal]
    """Only the categories that actually have >=1 anchor."""

    missing_categories: tuple[str, ...]
    blended_fair_value_per_share: Decimal | None
    dispersion_pct: Decimal | None
    """(max FV - min FV) ÷ mean FV across every individual anchor supplied
    (not the 3 category averages) — §24's own framing is about how much
    the underlying METHODS disagree, not how much the 3 blended buckets
    disagree."""

    warnings: tuple[str, ...]


def triangulate(routing: RoutingDecision, anchors: tuple[ValuationAnchor, ...]) -> TriangulationResult:
    warnings: list[str] = []
    category = triangulation_category_for_archetype(routing)
    weights = TRIANGULATION_WEIGHTS.get(category) if category else None

    if category is None or weights is None:
        return TriangulationResult(
            triangulation_category=category,
            weights=None,
            category_averages={},
            missing_categories=ANCHOR_CATEGORIES,
            blended_fair_value_per_share=None,
            dispersion_pct=None,
            warnings=(
                f"No §24 triangulation row for archetype {routing.archetype!r} — "
                "cannot blend (§15/§16's own routing already explains why, if archetype "
                "is set but unrecognised or not in the published table).",
            ),
        )

    by_category: dict[str, list[Decimal]] = {c: [] for c in ANCHOR_CATEGORIES}
    for anchor in anchors:
        if anchor.category not in by_category:
            warnings.append(f"Anchor {anchor.method!r} has unknown category {anchor.category!r} — ignored.")
            continue
        by_category[anchor.category].append(anchor.fair_value_per_share)

    category_averages = {
        cat: (sum(values, Decimal(0)) / len(values)) for cat, values in by_category.items() if values
    }
    missing = tuple(c for c in ANCHOR_CATEGORIES if c not in category_averages)

    raw_weight_by_category = {
        "intrinsic": weights.intrinsic_weight,
        "asset_sotp": weights.asset_sotp_weight,
        "relative": weights.relative_weight,
    }
    present_weight_sum = sum(raw_weight_by_category[c] for c in category_averages)

    if not category_averages:
        warnings.append("No anchors supplied at all — nothing to blend.")
        blended = None
    elif present_weight_sum == 0:
        warnings.append("Every supplied category has zero weight for this archetype — cannot blend.")
        blended = None
    else:
        if missing:
            warnings.append(
                f"No anchors for {missing} — weights renormalised among "
                f"{tuple(category_averages)} rather than silently treating the "
                "missing category's fair value as zero."
            )
        blended = sum(
            (raw_weight_by_category[c] / present_weight_sum) * category_averages[c]
            for c in category_averages
        )

    all_values = [a.fair_value_per_share for a in anchors]
    dispersion: Decimal | None = None
    if len(all_values) >= 2:
        mean_value = Decimal(str(statistics.mean(all_values)))
        if mean_value != 0:
            dispersion = (max(all_values) - min(all_values)) / mean_value
        else:
            warnings.append("Mean of anchor fair values is zero — dispersion undefined.")
    else:
        warnings.append(f"Only {len(all_values)} anchor(s) supplied — dispersion needs at least 2.")

    return TriangulationResult(
        triangulation_category=category,
        weights=weights,
        category_averages=category_averages,
        missing_categories=missing,
        blended_fair_value_per_share=blended,
        dispersion_pct=dispersion,
        warnings=tuple(warnings),
    )
