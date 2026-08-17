"""
Proposing a §16 valuation archetype from the exchange's own GICS
classification.

Appendix P2 is explicit that this mapping is maintained as a
hand-corrected, version-controlled file — GICS misclassifies CSE
conglomerates, and the clearest proof is already in this codebase: John
Keells Holdings, Sri Lanka's largest diversified group (hotels, transport,
consumer foods, financial services, property), classifies under GICS
"Capital Goods" because that happens to be its largest segment. No single
DDM or FCFE anchor fits that company.

So this module does not assign archetypes. It PROPOSES them from the
GICS industry group already stored on each security, and — this is the
part that matters — refuses to propose one at all when the company's own
name signals it is a diversified holding rather than a single-business
company. "Refuses" here means leaving `archetype` NULL with a stated
reason, per Design Law 3 (§4): missing is displayed as missing, never
guessed into something that merely looks complete.

A HUMAN STILL HAS TO REVIEW EVERY PROPOSAL. This is a starting point
that turns "0 of 264 issuers classified" into "most of them, with the
hard cases named instead of hidden" — not a replacement for the exercise
Appendix P2 describes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ARCHETYPES = frozenset(
    {
        "bank",
        "non_bank_finance",
        "insurance",
        "diversified_holding",
        "manufacturing",
        "consumer",
        "plantation",
        "hotel",
        "telecom",
        "construction_materials",
        "power_energy",
        "property",
        "healthcare",
        "logistics",
        "other",
    }
)

# GICS industry group NAME (as the exchange publishes it via `sector_list`
# / `listBySector`, i.e. `securities.cse_sector`) -> the archetype that
# name almost always means on the CSE. This is deliberately a lookup
# table, not code that infers meaning from a group name at runtime — a
# human should be able to read this list and see exactly what mapping
# decision was made for each of the 20 published groups.
_ARCHETYPE_BY_INDUSTRY_GROUP: dict[str, str] = {
    "Banks": "bank",
    "Diversified Financials": "non_bank_finance",
    "Insurance": "insurance",
    "Food, Beverage & Tobacco": "consumer",
    "Food & Staples Retailing": "consumer",
    "Retailing": "consumer",
    "Consumer Durables & Apparel": "consumer",
    "Household & Personal Products": "consumer",
    "Health Care Equipment & Services": "healthcare",
    "Telecommunication Services": "telecom",
    "Utilities": "power_energy",
    "Energy": "power_energy",
    "Real Estate Management&Development": "property",
    "Transportation": "logistics",
    "Automobiles & Components": "manufacturing",
    "Materials": "manufacturing",
    "Capital Goods": "manufacturing",
    # Deliberately mapped to "other" rather than guessed: this group's
    # real members (printing, packaging, diversified professional
    # services) don't share a single valuation logic the way "Banks"
    # does, and "other" is an honest label for that, not a placeholder.
    "Commercial & Professional Services": "other",
}

# "Consumer Services" is CSE-specific: on this exchange it is almost
# entirely hotels and resorts, not the broad GICS category (education,
# leisure services generally) the name suggests elsewhere. Confirmed by
# reading its actual membership (32 companies, 17 Aug 2026) rather than
# assumed from the GICS name — the names read ASIAN HOTELS AND
# PROPERTIES, AITKEN SPENCE HOTEL HOLDINGS, BERUWALA RESORTS, CEYLON
# HOTELS CORPORATION, HIKKADUWA BEACH RESORT, HAYLEYS LEISURE, and so on.
# So this group gets a keyword gate rather than an unconditional mapping:
# propose "hotel" only when the company's own name says so too.
_HOTEL_INDUSTRY_GROUP = "Consumer Services"
_HOTEL_KEYWORDS = ("HOTEL", "RESORT", "LEISURE")

# A name containing one of these, with no clearer single-business keyword
# below outranking it, is a company that is very likely a diversified
# conglomerate — exactly what Appendix P2 warns GICS gets wrong. These
# never get an auto-proposed archetype.
_CONGLOMERATE_KEYWORDS = ("HOLDINGS", " GROUP ", " GROUP PLC")

# A name containing one of these overrides the GICS-derived mapping
# outright, even inside "Materials" or "Capital Goods" — the archetype
# table above has no "plantation" or "construction_materials" entry
# because no single GICS group maps to them cleanly on this exchange.
_NAME_OVERRIDES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bPLANTATIONS?\b"), "plantation"),
    (re.compile(r"\b(TEA|RUBBER|ESTATES?)\b"), "plantation"),
    (re.compile(r"\bCEMENT\b"), "construction_materials"),
)


@dataclass(frozen=True)
class ArchetypeProposal:
    archetype: str | None
    """None means "needs a human", not "no opinion could be formed" —
    `reason` always says why."""

    reason: str


def propose_archetype(name: str, cse_sector: str | None) -> ArchetypeProposal:
    """One security's proposal. Pure function, no I/O — the loader owns
    reading/writing; this owns the judgement call."""
    upper_name = f" {name.strip().upper()} "

    for pattern, archetype in _NAME_OVERRIDES:
        if pattern.search(upper_name):
            return ArchetypeProposal(archetype, f"name matches /{pattern.pattern}/")

    is_conglomerate_shaped = any(kw in upper_name for kw in _CONGLOMERATE_KEYWORDS)
    if is_conglomerate_shaped:
        return ArchetypeProposal(
            None,
            "name suggests a diversified group (Appendix P2 conglomerate warning) "
            "— needs a human to look at the actual segment mix",
        )

    if cse_sector is None:
        return ArchetypeProposal(None, "no GICS classification stored for this security")

    if cse_sector == _HOTEL_INDUSTRY_GROUP:
        if any(kw in upper_name for kw in _HOTEL_KEYWORDS):
            return ArchetypeProposal("hotel", f"GICS {cse_sector!r} + name confirms hospitality")
        return ArchetypeProposal(
            None,
            f"GICS group {cse_sector!r} is hotel-dominated on this exchange but the name "
            f"doesn't confirm it — needs a human",
        )

    archetype = _ARCHETYPE_BY_INDUSTRY_GROUP.get(cse_sector)
    if archetype is None:
        return ArchetypeProposal(None, f"no archetype mapping defined for GICS group {cse_sector!r}")
    return ArchetypeProposal(archetype, f"derived from GICS group {cse_sector!r}")
