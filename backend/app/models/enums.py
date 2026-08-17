from __future__ import annotations

import enum


class ProvenanceTier(str, enum.Enum):
    """Master Spec §8. Ordered worst-to-best is NOT the enum order below —
    ordering for the "inherits the weakest provenance" rule lives in
    app.domain.provenance.WORST_FIRST, because Python enums don't sort
    meaningfully by declaration order once you rely on that for logic."""

    REPORTED = "R"
    DERIVED = "D"
    NORMALISED = "N"
    ESTIMATED = "E"
    FORECAST = "F"
    AI_ASSISTED = "A"
    UNAVAILABLE = "-"


class CoverageTier(str, enum.Enum):
    """Master Spec §11. Assigned by the gate pipeline in
    app.domain.coverage_gates, never hand-set."""

    CORE = "core"
    WATCH = "watch"
    EXCLUDED = "excluded"
    INSUFFICIENT = "insufficient"


class CorporateActionType(str, enum.Enum):
    """Master Spec §7."""

    DIVIDEND_CASH = "dividend_cash"
    BONUS_ISSUE = "bonus_issue"
    RIGHTS_ISSUE = "rights_issue"
    STOCK_SPLIT = "stock_split"
    CONSOLIDATION = "consolidation"
    DELISTING = "delisting"
    SUSPENSION = "suspension"


class NationalProjectStatus(str, enum.Enum):
    """Master Spec §34's own status ladder, in order — Python enums
    don't sort meaningfully by declaration order once code relies on
    that, so `app.domain.national_projects.STATUS_LADDER_ORDER` is the
    real source of truth for "is this status financing-closed-or-later",
    the same separation `ProvenanceTier`'s own docstring establishes for
    provenance ordering. Declared in ladder order here anyway, purely for
    a human reading the enum, not for any code to depend on."""

    ANNOUNCED = "announced"
    MOU = "mou"
    FINANCING_CLOSED = "financing_closed"
    UNDER_CONSTRUCTION = "under_construction"
    OPERATIONAL = "operational"


class NationalProjectFinancingSource(str, enum.Enum):
    """§34: "whether state, FDI or PPP"."""

    STATE = "state"
    FDI = "fdi"
    PPP = "ppp"


class NationalProjectTransmissionChannel(str, enum.Enum):
    """§34: "Explicit mapping with the transmission channel — contractor,
    materials supplier, financier, landlord, beneficiary of demand"."""

    CONTRACTOR = "contractor"
    MATERIALS_SUPPLIER = "materials_supplier"
    FINANCIER = "financier"
    LANDLORD = "landlord"
    BENEFICIARY_OF_DEMAND = "beneficiary_of_demand"


class NationalProjectImpactMetric(str, enum.Enum):
    """§34's "quantified impact" is "estimated revenue or margin effect"
    — this says which of the two a given `NationalProjectTickerImpact`
    row's `quantified_impact_pct` applies to, so the same numeric field
    is never ambiguous about what it's a percentage OF."""

    REVENUE = "revenue"
    MARGIN = "margin"
