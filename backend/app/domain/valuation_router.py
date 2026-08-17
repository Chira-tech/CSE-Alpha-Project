"""
§15 sector frameworks + §16 model router — the front door of Phase 3.

"Do not apply an industrial DCF to a bank. A bank's debt is its raw
material, not its financing; free cash flow to the firm is not a
meaningful concept for it. Get this wrong and the model will produce a
confident, precise, entirely fictional number. The archetype router
exists specifically to make that error impossible." (§15)

This module does NOT compute a valuation. It decides which valuation
METHODS apply to a company and which are actively wrong for it, from the
archetype already stored on the security record (`app.domain.archetype`)
and the five routing questions §16 lists. §16 is explicit that "the
router's decision, and the reason for it, is displayed on the stock
page. If a model was suppressed, the user sees which one and why" — so
every suppression here carries a stated reason, not a bare boolean.

WHAT THIS HONESTLY CANNOT ANSWER YET, AND WHY IT SAYS SO RATHER THAN
GUESSING. Two of §16's five routing questions need data this system does
not extract:

  - "Are cash flows positive and reasonably predictable?" needs CFO/FCF.
    `app.domain.financial_statement_parsing.CANONICAL_LABELS` has no
    cash-flow-statement line at all (PARAMETERS.md #9's gap).
  - "Are dividends a meaningful proxy for capacity to pay?" needs a
    dividend history. Not extracted either.
  - Distress/option-value routing needs an Altman Z-score, not computed
    (§12 lists it; the ratio engine's `NOT_YET_COMPUTABLE` tuple in
    app.domain.ratios already says why).

Substituting net income for cash flow, or a leverage ratio for a Z-score,
would be exactly the "confident, precise, entirely fictional number" §15
warns about, just moved one layer up from valuation into routing. This
module reports those three questions as `cannot_evaluate` with the
specific missing input named, the same NOT_YET_COMPUTABLE discipline the
ratio engine already applies.

What IS answerable purely from archetype, honestly: whether a company is
a financial firm (bank / non_bank_finance / insurance), whether it is a
holding company with separable segments (diversified_holding), and
whether its earnings are cyclical or commodity-linked enough to need
mid-cycle normalisation before any multiple is applied — §15's own
examples (plantations, power & energy, construction & materials) make
that a property of the archetype, not something that needs a live
computation to determine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# §15's table, page 10, transcribed exactly — the "Primary valuation"
# column becomes `primary_models`, "Metrics that are meaningless here"
# becomes `meaningless_metrics`. Kept as data, not inferred, so this can
# be read against the spec table directly rather than trusted on faith.
@dataclass(frozen=True)
class ArchetypeProfile:
    primary_models: tuple[str, ...]
    meaningless_metrics: tuple[str, ...]
    is_financial_firm: bool
    is_cyclical_or_commodity_linked: bool
    in_published_table: bool = True
    note: str = ""


_PROFILES: dict[str, ArchetypeProfile] = {
    "bank": ArchetypeProfile(
        primary_models=("Justified P/TBV from ROE", "Residual income", "Multi-stage DDM"),
        meaningless_metrics=("EV/EBIT", "EV/EBITDA", "ROIC", "Free cash flow", "Net debt multiples"),
        is_financial_firm=True,
        is_cyclical_or_commodity_linked=False,
    ),
    "non_bank_finance": ArchetypeProfile(
        primary_models=("Justified P/B", "Residual income", "DDM"),
        meaningless_metrics=("EV/EBIT", "EV/EBITDA", "ROIC", "Free cash flow", "Net debt multiples"),
        is_financial_firm=True,
        is_cyclical_or_commodity_linked=False,
    ),
    "insurance": ArchetypeProfile(
        primary_models=("Embedded value + VNB multiple (life)", "P/B and ROE (general)"),
        meaningless_metrics=("EV/EBITDA", "ROIC"),
        is_financial_firm=True,
        is_cyclical_or_commodity_linked=False,
    ),
    "diversified_holding": ArchetypeProfile(
        primary_models=("Sum-of-the-parts", "Segment-level EV/EBIT", "NAV gap"),
        meaningless_metrics=("Consolidated margins",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
        note="Consolidated margins mix unlike businesses and mean nothing (§15).",
    ),
    "manufacturing": ArchetypeProfile(
        primary_models=("FCFF DCF", "EV/EBIT vs own and sector history"),
        meaningless_metrics=("Dividend yield as a primary anchor",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
    ),
    "consumer": ArchetypeProfile(
        primary_models=("FCFF DCF", "EV/EBITDA", "P/E vs own history"),
        meaningless_metrics=("Asset-based valuation",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
    ),
    "plantation": ArchetypeProfile(
        primary_models=("Normalised mid-cycle earnings x through-cycle multiple", "Hard NAV per hectare"),
        meaningless_metrics=("Reported book value (revaluation-inflated)", "P/E in a commodity trough"),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=True,
    ),
    "hotel": ArchetypeProfile(
        primary_models=("Normalised EBITDA x EV/EBITDA", "Replacement cost per key", "Hard-book NAV"),
        meaningless_metrics=("Trailing P/E across a cycle", "Reported book equity"),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=True,
    ),
    "telecom": ArchetypeProfile(
        primary_models=("FCFF DCF", "EV/EBITDA"),
        meaningless_metrics=("Book value",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
    ),
    "construction_materials": ArchetypeProfile(
        primary_models=("FCFF DCF with explicit order-book fade", "EV/EBIT"),
        meaningless_metrics=("Dividend stability",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=True,
    ),
    "power_energy": ArchetypeProfile(
        primary_models=("Contracted-cashflow DCF", "Regulated asset base"),
        meaningless_metrics=("Growth multiples",),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=True,
        note="Regulated tariff resets and PPA-tenor cash flows, not open-market growth (§15).",
    ),
    "property": ArchetypeProfile(
        primary_models=("NAV with independent land marks", "Development DCF"),
        meaningless_metrics=("Reported P/E", "Consolidated ROIC"),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
    ),
    # Not in §15's published 12-row table. In Appendix P2's 15-archetype
    # list, so the field is real and must route somewhere, but treating
    # these as identical to a table row that does not name them would
    # misrepresent the spec as having said something it didn't.
    "healthcare": ArchetypeProfile(
        primary_models=("FCFF DCF", "EV/EBITDA"),
        meaningless_metrics=(),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
        in_published_table=False,
        note="Not a row in §15's table. Routed as an asset-light services business "
        "(closest published analogue: consumer/telecom) pending an explicit spec entry.",
    ),
    "logistics": ArchetypeProfile(
        primary_models=("FCFF DCF", "EV/EBIT"),
        meaningless_metrics=(),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
        in_published_table=False,
        note="Not a row in §15's table. Routed as a capital-intensive operating business "
        "(closest published analogue: manufacturing/industrials) pending an explicit spec entry.",
    ),
    "other": ArchetypeProfile(
        primary_models=(),
        meaningless_metrics=(),
        is_financial_firm=False,
        is_cyclical_or_commodity_linked=False,
        in_published_table=False,
        note="§15 has no archetype-specific guidance for 'other' by definition — "
        "no model is proposed rather than guessing one.",
    ),
}

# §16 firm-side vs equity-side. A financial firm's debt is its raw
# material, so these are suppressed outright regardless of what the
# archetype table's primary-models list already implies — this is the
# explicit, stated cross-check §16 asks for, not left implicit in the
# table above.
_FIRM_SIDE_MODELS = ("FCFF DCF", "EV/EBIT", "EV/EBITDA", "Sum-of-the-parts")


@dataclass(frozen=True)
class Suppression:
    model: str
    reason: str


@dataclass(frozen=True)
class UnansweredQuestion:
    question: str
    missing_input: str


@dataclass(frozen=True)
class RoutingDecision:
    archetype: str | None
    in_published_table: bool
    primary_models: tuple[str, ...]
    suppressed: tuple[Suppression, ...]
    meaningless_metrics: tuple[str, ...]
    requires_earnings_normalisation: bool
    is_financial_firm: bool
    is_holding_company: bool
    note: str
    unanswered_questions: tuple[UnansweredQuestion, ...] = field(default_factory=tuple)


def route_valuation(archetype: str | None) -> RoutingDecision:
    """The routing decision for one company. Pure function of the
    archetype already on the security record — no fundamentals, no live
    data — because §15/§16 place the decision entirely on what KIND of
    business this is, not on any single period's numbers.

    `archetype=None` means Appendix P2's mapping hasn't been proposed or
    confirmed for this security yet (`app.domain.archetype` — as of this
    module's introduction, 51 of 283 securities are in exactly that
    state, deliberately left for a human rather than guessed). Routing
    cannot proceed without it, and says so rather than defaulting to a
    generic profile that would silently apply an industrial DCF to a
    bank the moment archetype confirmation lagged behind.
    """
    unanswered = (
        UnansweredQuestion(
            "Are cash flows positive and reasonably predictable?",
            "CFO/FCF not extracted — CANONICAL_LABELS has no cash-flow-statement line (PARAMETERS.md #9)",
        ),
        UnansweredQuestion(
            "Are dividends a meaningful proxy for capacity to pay?",
            "dividend history not extracted",
        ),
        UnansweredQuestion(
            "Is the company distressed, or is equity effectively an option on recovery?",
            "Altman Z-score not computed (app.domain.ratios.NOT_YET_COMPUTABLE)",
        ),
    )

    if archetype is None:
        return RoutingDecision(
            archetype=None,
            in_published_table=False,
            primary_models=(),
            suppressed=(),
            meaningless_metrics=(),
            requires_earnings_normalisation=False,
            is_financial_firm=False,
            is_holding_company=False,
            note="No archetype confirmed for this security — routing cannot proceed "
            "without it (§15). Run `python -m app.cli archetypes` and review.",
            unanswered_questions=unanswered,
        )

    profile = _PROFILES.get(archetype)
    if profile is None:
        return RoutingDecision(
            archetype=archetype,
            in_published_table=False,
            primary_models=(),
            suppressed=(),
            meaningless_metrics=(),
            requires_earnings_normalisation=False,
            is_financial_firm=False,
            is_holding_company=False,
            note=f"Unrecognised archetype {archetype!r} — not one of Appendix P2's 15.",
            unanswered_questions=unanswered,
        )

    suppressed: list[Suppression] = []
    if profile.is_financial_firm:
        for model in _FIRM_SIDE_MODELS:
            if model not in profile.primary_models:
                suppressed.append(
                    Suppression(
                        model,
                        f"{archetype} is a financial firm (§16) — its debt is raw material, "
                        f"not financing, so firm-side free-cash-flow models are suppressed",
                    )
                )

    return RoutingDecision(
        archetype=archetype,
        in_published_table=profile.in_published_table,
        primary_models=profile.primary_models,
        suppressed=tuple(suppressed),
        meaningless_metrics=profile.meaningless_metrics,
        requires_earnings_normalisation=profile.is_cyclical_or_commodity_linked,
        is_financial_firm=profile.is_financial_firm,
        is_holding_company=(archetype == "diversified_holding"),
        note=profile.note,
        unanswered_questions=unanswered,
    )
