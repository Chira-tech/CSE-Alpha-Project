"""
§34: National project and outlook register — "A structured register of
confirmed Sri Lankan projects and policy programmes, each mapped to
affected tickers, because for a 12–36 month horizon these are the
concrete catalysts."

    Status ladder   Announced → MoU → financing closed →
                    under construction → operational.
                    Only "financing closed" and beyond may
                    influence a base case. Earlier stages
                    influence only the bull case.

    Source and      URL, date, human confirmation required
    confirmation    before it can affect any valuation.

Pure functions over caller-supplied project/impact data — this module
has no I/O and no opinion about where a project's status or a ticker's
quantified impact came from (see `app.domain.national_projects_view` for
the database-wired half), the same split every `_view.py` companion in
this system draws.

WHY STATUS-LADDER RANK LIVES HERE, NOT ON THE ENUM. `app.models.enums.
NationalProjectStatus`'s own docstring says so explicitly: Python enums
don't sort meaningfully by declaration order once code depends on that
ordering for a real decision (whether a project may move a base-case
forecast), so `STATUS_LADDER_ORDER` is the single source of truth for
"is financing-closed-or-later" — the same reasoning `app.domain.
provenance.WORST_FIRST` already applies to `ProvenanceTier`.

WHY `ESTIMATED`/`FORECAST` — NOT A NEW TWO-VALUE ENUM — IS §34's "E OR
F". `app.models.enums.ProvenanceTier`'s own members are literally coded
"R"/"D"/"N"/"E"/"F"/"A"/"-" (Master Spec §8). §34's "provenance-tagged E
or F" is that same scheme, restricted to exactly its two middle tiers —
recognised and reused here, not treated as a coincidence needing its own
parallel enum.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import NationalProjectImpactMetric, NationalProjectStatus, ProvenanceTier

#: Declaration order on `NationalProjectStatus` happens to match this,
#: but this tuple — not enum declaration order — is what every ranking
#: decision in this module actually reads, per this module's own
#: docstring.
STATUS_LADDER_ORDER: tuple[NationalProjectStatus, ...] = (
    NationalProjectStatus.ANNOUNCED,
    NationalProjectStatus.MOU,
    NationalProjectStatus.FINANCING_CLOSED,
    NationalProjectStatus.UNDER_CONSTRUCTION,
    NationalProjectStatus.OPERATIONAL,
)

_STATUS_RANK = {status: i for i, status in enumerate(STATUS_LADDER_ORDER)}

#: §34: "Only 'financing closed' and beyond may influence a base case."
BASE_CASE_MINIMUM_STATUS = NationalProjectStatus.FINANCING_CLOSED

#: §34's own restriction on the provenance tag a quantified impact may
#: carry — a project's IMPACT is always an estimate or a forecast, never
#: a `REPORTED`/`DERIVED`/`NORMALISED` figure (those tiers describe
#: extracted financial-statement data, a different kind of claim
#: entirely) and never `AI_ASSISTED`/`UNAVAILABLE` (§34 requires the
#: assumption to be stated, which those two tiers are not compatible
#: with — see `app.domain.provenance` for what each tier means
#: elsewhere in this system).
ALLOWED_IMPACT_PROVENANCE_TAGS: frozenset[ProvenanceTier] = frozenset(
    {ProvenanceTier.ESTIMATED, ProvenanceTier.FORECAST}
)


def status_rank(status: NationalProjectStatus) -> int:
    return _STATUS_RANK[status]


def may_influence_base_case(status: NationalProjectStatus, *, is_confirmed: bool) -> bool:
    """§34: "financing closed" and beyond, AND confirmed — "human
    confirmation required before it can affect any valuation" is a
    blanket rule applying regardless of case, not only to the bull case."""
    return is_confirmed and status_rank(status) >= status_rank(BASE_CASE_MINIMUM_STATUS)


def may_influence_bull_case(status: NationalProjectStatus, *, is_confirmed: bool) -> bool:
    """§34: "Earlier stages influence only the bull case" — read as ANY
    confirmed status may influence a bull case (base-case-eligible
    projects are a fortiori bull-case-eligible too; the bull case is the
    superset, not a separate, disjoint set of only the earlier stages).
    Still requires confirmation — see `may_influence_base_case`'s own
    docstring for why that gate is never waived for either case."""
    return is_confirmed


def validate_impact_provenance_tag(tag: ProvenanceTier) -> None:
    """Raises `ValueError` for anything outside §34's own "E or F"
    restriction. A validation function rather than a boolean predicate,
    matching this project's established style for a check whose failure
    needs an explanit message (see `app.domain.corporate_actions.
    price_ratio_for_event`'s own validation-by-exception pattern) —
    the API layer's confirm endpoint is this function's real caller."""
    if tag not in ALLOWED_IMPACT_PROVENANCE_TAGS:
        raise ValueError(
            f"provenance_tag must be ESTIMATED ('E') or FORECAST ('F') per §34 — got "
            f"{tag.name} ('{tag.value}'). A quantified project impact is always an estimate "
            "or a forecast, never a REPORTED/DERIVED/NORMALISED extracted figure, and never "
            "AI_ASSISTED/UNAVAILABLE (§34 requires the assumption to be stated)."
        )


@dataclass(frozen=True)
class TickerImpact:
    """The subset of `app.models.national_projects.NationalProjectTickerImpact`
    this module's pure functions actually need — decoupled from the ORM
    row shape so these functions stay testable without a database, the
    same split `app.domain.dividend_residual_income` draws from
    `app.models.corporate_actions.CorporateAction`."""

    impact_metric: NationalProjectImpactMetric
    quantified_impact_pct: Decimal | None


def net_revenue_growth_adjustment(impacts: list[TickerImpact]) -> Decimal | None:
    """Sums whichever `REVENUE`-metric impacts have a real quantified
    percentage into one net adjustment — §18.2's own words for DCF
    revenue growth Y1-2: "Trailing 3-year CAGR, adjusted by sector macro
    sensitivity (§33) AND ANY CONFIRMED PROJECT IN THE REGISTER (§34)."
    This function does not itself check confirmation or base-case
    eligibility — its caller (`app.domain.national_projects_view`) is
    expected to have already filtered to `may_influence_base_case`-
    eligible impacts before calling this, the same "gather, then sum"
    separation `app.domain.dcf`'s own `compute_fcff` draws from whatever
    filtered the inputs to it.

    `MARGIN`-metric impacts are deliberately excluded from this sum —
    they answer a different question (§18.2's operating margin
    assumption, not revenue growth) and mixing the two into one number
    would misrepresent a margin effect as a growth effect. `None` when no
    REVENUE-metric impact has a real quantified percentage at all (as
    opposed to `Decimal(0)`, which would claim "confirmed projects exist
    and their net effect is exactly zero" — a different, stronger claim
    this function never makes without real inputs to back it)."""
    revenue_pcts = [
        impact.quantified_impact_pct
        for impact in impacts
        if impact.impact_metric == NationalProjectImpactMetric.REVENUE
        and impact.quantified_impact_pct is not None
    ]
    if not revenue_pcts:
        return None
    return sum(revenue_pcts, Decimal(0))
