"""
§38 — the composite investment score. Pure combinators only; see
`app.domain.composite_score_view` for the DB-wired per-ticker aggregator
that actually calls the ratio/valuation/liquidity/national-projects
machinery this module blends together.

WHAT THIS IS, PRECISELY. §38 names 7 weighted pillars (Valuation 25,
Business quality 25, Growth 15, Financial strength 10, Macro & sector fit
10, Timing & momentum 10, Risk 5) plus a hard integrity veto never folded
into the number. It names WHAT feeds each pillar and its weight, but not
HOW to turn a raw ratio/valuation-gap/liquidity-ratio into a 0-100 point
value — that normalization is a real judgment call the spec leaves open.

THE METHOD CHOSEN, AND WHY. Percentile-rank whatever has a genuinely
rankable continuous quantity, reusing `app.domain.sector_percentiles.
sector_percentiles_for_ratio` (already tested, already the real §12
machinery) rather than inventing a new scale — that function is generic
over any (ratio_key, values_by_ticker) pair, not just the 13 ratios in
`app.domain.ratios`, so the view layer reuses it unmodified for other
percentile-rankable quantities too. Whatever has NO defensible rank yet
— a real, measured constraint, not a design gap — because ranking it
needs an expensive universe-wide pass this project already knows costs
~30s at current data volume, and redoing that on every single-ticker
request would be a real latency regression, not something to eat
silently, stays OUT of the numeric blend entirely and is reported as
real evidence instead. Two pillars (Valuation, Growth) are excluded from
the number for exactly this reason today — see `app.domain.
composite_score_view`'s own module docstring for the real universe-pass
cost that still blocks them and the shared-cache pattern (`app.domain.
opportunity_ranking_view`'s own) that will unblock them next, once
built. Macro & sector fit (`app.domain.macro_sector_fit`) and Timing &
momentum (`app.domain.timing_battery`) are, as of this session, real and
wired — see those modules' own docstrings for their real methodology
(a direction-count formula for the former, since §33's own sensitivity
estimates are deliberately magnitude-free; §37's literal weighted
battery, gated on a real Carhart regression this system's real 3-year
price history now supports, for the latter).

RENORMALIZATION. `total_score` is the weighted mean of whichever
pillars ARE numerically computable for this ticker, weights renormalized
among them — the exact same idea `app.domain.triangulation.triangulate`
already uses for missing anchor categories (see that function's own
`present_weight_sum` renormalization), not a fresh convention invented
here. Zero computable pillars -> `total_score=None`, never a fabricated
0 (§1, law 4).

INTEGRITY IS NEVER IN THIS MODULE'S OUTPUT AT ALL. §11.1's own words:
"If integrity is a scored input, a sufficiently attractive valuation will
always outvote it." `app.domain.coverage_gates.evaluate_gate3_integrity`
already exists as a hard boolean gate for exactly this reason — this
module has no function that touches it, deliberately; the view layer
reports integrity as a wholly separate field, matching `app.domain.
margin_of_safety.quality_integrity_component`'s own established
precedent for keeping a veto-shaped input out of a weighted sum.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PillarSpec:
    key: str
    label: str
    weight_pct: Decimal
    always_excluded_reason: str | None
    """Set for a pillar that is NEVER part of the numeric blend today,
    regardless of what data exists for a given ticker — as opposed to a
    pillar that's merely missing FOR THIS TICKER (which gets its own,
    per-call reason from the view layer, not this fixed one)."""


#: §38's own literal 7-row table. Order matches the spec's own listing.
PILLAR_SPECS: tuple[PillarSpec, ...] = (
    PillarSpec("valuation", "Valuation", Decimal(25), None),
    PillarSpec("business_quality", "Business quality", Decimal(25), None),
    PillarSpec("growth", "Growth", Decimal(15), None),
    PillarSpec("financial_strength", "Financial strength", Decimal(10), None),
    PillarSpec("macro_sector_fit", "Macro & sector fit", Decimal(10), None),
    PillarSpec("timing_momentum", "Timing & momentum", Decimal(10), None),
    PillarSpec("risk", "Risk", Decimal(5), None),
)

PILLAR_SPECS_BY_KEY: dict[str, PillarSpec] = {p.key: p for p in PILLAR_SPECS}

#: §12's ratios that speak to profitability and cash-earnings quality —
#: §38's own "gross profitability, margin stability, cash conversion"
#: wording for the Business quality pillar. Deliberately excludes the
#: three leverage/solvency ratios (those are Financial strength's own
#: inputs, below) and `effective_tax_rate` (belongs to neither pillar's
#: theme).
BUSINESS_QUALITY_RATIO_KEYS: tuple[str, ...] = (
    "return_on_equity",
    "return_on_assets",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "gross_profitability",
    "cash_conversion",
    "operating_cash_flow_margin",
    "sloan_accrual_ratio",
)

#: §38's own "Net debt/EBITDA, coverage, ... refinancing cliff" wording —
#: net_debt_to_ebitda and interest_coverage are both still in `app.domain.
#: ratios.NOT_YET_COMPUTABLE`, so only these three are real today.
FINANCIAL_STRENGTH_RATIO_KEYS: tuple[str, ...] = (
    "current_ratio",
    "liabilities_to_equity",
    "equity_ratio",
)

#: Ratios in `FINANCIAL_STRENGTH_RATIO_KEYS` where a LOWER raw value is
#: the financially STRONGER position, so this pillar (unlike `app.domain.
#: sector_percentiles`'s own deliberately neutral ranking) inverts the
#: percentile before averaging it in. Disclosed explicitly, once, here —
#: not a silent sign flip buried in the aggregator.
FINANCIAL_STRENGTH_INVERT: frozenset[str] = frozenset({"liabilities_to_equity"})


def mean_of_available(values: list[Decimal | None]) -> Decimal | None:
    """Mean of whichever entries aren't `None` — `None` itself (never 0)
    when every entry is `None`, since a pillar built from zero real
    ratios is not computable, not a real average of nothing."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, Decimal(0)) / len(present)


def renormalize(pillar_scores: dict[str, Decimal | None]) -> tuple[Decimal | None, dict[str, Decimal]]:
    """Weighted mean of whichever pillars are non-`None`, weights
    renormalized among them — the exact renormalization
    `app.domain.triangulation.triangulate` already applies to its own
    missing anchor categories, reused here rather than reinvented.
    Valuation and Growth — excluded by design today, a real cost
    constraint rather than a per-ticker gap, see module docstring — are
    never passed in here at all; the view layer keeps them entirely out
    of `pillar_scores`, so their weight is never part of
    `present_weight_sum` to begin with. Every OTHER pillar (including
    Macro & sector fit and Timing & momentum, now real) passes through
    this same renormalization when it's missing for a given ticker's own
    real data, same as any other pillar.

    Returns `(total_score, weight_used_by_pillar)` — the second element
    lets a caller show exactly how much each included pillar actually
    counted for, the same "never one opaque number" discipline `app.
    domain.national_projects_view`'s own adjustment function already
    applies to its own blended figure.
    """
    included = {k: v for k, v in pillar_scores.items() if v is not None}
    if not included:
        return None, {}

    raw_weight = {k: PILLAR_SPECS_BY_KEY[k].weight_pct for k in included}
    present_weight_sum = sum(raw_weight.values())
    if present_weight_sum == 0:
        return None, {}

    weight_used = {k: (raw_weight[k] / present_weight_sum) * Decimal(100) for k in included}
    total = sum((weight_used[k] / Decimal(100)) * included[k] for k in included)
    return total, weight_used
