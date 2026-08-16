"""Master Spec §8: "A composite score inherits the weakest provenance among
its material inputs." Reported is best, Unavailable is worst; AI-assisted
sits just above Unavailable because it cannot enter a valuation until a
human promotes it to Reported (§8 table, "AI-assisted" row)."""
from __future__ import annotations

from app.models.enums import ProvenanceTier

# Best to worst, left to right. This ordering is the single source of truth
# for "weakest of" logic — do not rely on enum declaration order elsewhere.
WORST_FIRST: tuple[ProvenanceTier, ...] = (
    ProvenanceTier.UNAVAILABLE,
    ProvenanceTier.AI_ASSISTED,
    ProvenanceTier.FORECAST,
    ProvenanceTier.ESTIMATED,
    ProvenanceTier.NORMALISED,
    ProvenanceTier.DERIVED,
    ProvenanceTier.REPORTED,
)
_RANK = {tier: i for i, tier in enumerate(WORST_FIRST)}


def weakest(tiers: list[ProvenanceTier]) -> ProvenanceTier:
    if not tiers:
        raise ValueError("weakest() requires at least one provenance tier")
    return min(tiers, key=lambda t: _RANK[t])


def can_enter_valuation(tier: ProvenanceTier) -> bool:
    """§8: AI-assisted figures "cannot enter a valuation until human-
    confirmed and promoted to Reported." Unavailable obviously cannot
    either."""
    return tier not in (ProvenanceTier.AI_ASSISTED, ProvenanceTier.UNAVAILABLE)
