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
