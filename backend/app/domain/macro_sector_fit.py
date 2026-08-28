"""
§38's Macro & sector fit pillar, the pure formula half — §38's own
table: "Sector sensitivity to the current regime, project-register
exposure, sector momentum." See `app.domain.macro_sector_fit_view` for
the DB-wired aggregator that supplies each real component this module
combines.

WHY A DIRECTION-COUNT FORMULA, NOT A MAGNITUDE-WEIGHTED ONE. `app.
domain.sector_sensitivity.SensitivityEstimate.direction_label` is
DELIBERATELY magnitude-free — `"positive"`/`"negative"`/
`"not_significant"` only, that module's own docstring explaining why an
OLS coefficient's magnitude isn't comparable across differently-scaled
shock series (a policy-rate coefficient and a CCPI coefficient live on
different scales; averaging or weighting them together would need an
undisclosed, invented normalization). So this formula counts, rather
than weights: `favorable_significant_shock_count ÷
total_significant_shock_count` — of the shocks THIS sector has a real,
statistically significant reading on, what fraction currently lean the
way this regime rewards. Neutral, un-invented, and honest about exactly
what it does and doesn't claim.

FAVORABLE DIRECTION REUSES REGIME_CLASSIFICATION'S OWN ESTABLISHED
POLARITY, NOT A FRESH ONE. `app.domain.regime_classification`'s real,
already-shipped signals (policy rate direction, T-bill yield, CCPI,
LKR/USD) all share one polarity: a RISING reading leans Risk-Off, a
FALLING one leans Risk-On (§32's own worked example: "Policy rate
direction: Tightened... Risk-Off"; "T-bill yields: Risen... Risk-Off —
the equity hurdle just rose"). All four of §33's own real, ingested
shock series (see `sector_sensitivity_view.real_macro_shocks`) are
exactly these same four signals — so "a positive sector-sensitivity
coefficient to this shock" means "this sector's return rises WITH the
shock," and a Risk-Off regime rewards a sector whose return rises with a
rising (Risk-Off-leaning) shock: `favorable = (regime=='risk_off' and
coefficient>0) or (regime=='risk_on' and coefficient<0)`. `Transition`
carries no directional lean by construction (§31's own regime read:
genuinely two-sided, "the probability matters more than the label") —
scored `None`, not an invented halfway value.

SCORE IS `None`, NEVER A FABRICATED NEUTRAL 50, WHEN NOTHING REAL IS
COUNTABLE — zero significant shocks for this sector, or a Transition/
unknown regime. Matches `app.domain.composite_score.mean_of_available`'s
own "None when nothing is real to average" rule exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.sector_sensitivity import SectorSensitivityRow

_FAVORABLE_IN_RISK_OFF = "risk_off"
_FAVORABLE_IN_RISK_ON = "risk_on"


def sector_fit_from_sensitivity(
    row: SectorSensitivityRow | None, regime_label: str | None,
) -> tuple[Decimal | None, int, int, str | None]:
    """`(sensitivity_component, favorable_count, total_significant_count,
    reason_if_none)`. `row=None` (this ticker's sector was too thin for
    §33's own matrix — see `SectorSensitivityView.thin_sectors`) or a
    `Transition`/unknown regime both produce `(None, 0, 0, reason)`."""
    if regime_label not in (_FAVORABLE_IN_RISK_OFF, _FAVORABLE_IN_RISK_ON):
        return None, 0, 0, f"no directional lean for regime={regime_label!r} (Transition or unknown)"
    if row is None:
        return None, 0, 0, "this ticker's sector has too few real constituents for §33's own sensitivity matrix"

    significant = [e for e in row.estimates if e.significant]
    if not significant:
        return None, 0, 0, "no shock has a statistically significant sensitivity estimate for this sector"

    favorable = 0
    for estimate in significant:
        is_positive = estimate.direction_label == "positive"
        if regime_label == _FAVORABLE_IN_RISK_OFF and is_positive:
            favorable += 1
        elif regime_label == _FAVORABLE_IN_RISK_ON and not is_positive:
            favorable += 1

    score = Decimal(100) * Decimal(favorable) / Decimal(len(significant))
    return score, favorable, len(significant), None


@dataclass(frozen=True)
class MacroSectorFitScore:
    sensitivity_component: Decimal | None
    favorable_significant_shock_count: int
    total_significant_shock_count: int
    sensitivity_reason: str | None
    project_register_component: Decimal | None
    sector_momentum_component: Decimal | None
    score: Decimal | None
    reason: str | None


def combine_macro_sector_fit(
    sensitivity_component: Decimal | None,
    favorable_count: int,
    total_significant_count: int,
    sensitivity_reason: str | None,
    project_register_component: Decimal | None,
    sector_momentum_component: Decimal | None,
) -> MacroSectorFitScore:
    """Mean of whichever of the three real components exist for this
    ticker — the exact `app.domain.composite_score.mean_of_available`
    logic, restated here (that function isn't imported directly to avoid
    a cross-module dependency for one shared three-line mean; both
    independently implement the identical "never a fabricated 0" rule)."""
    present = [
        v for v in (sensitivity_component, project_register_component, sector_momentum_component) if v is not None
    ]
    score = sum(present, Decimal(0)) / len(present) if present else None
    reason = None if present else "none of the three real components (sensitivity, project register, sector momentum) were computable"
    return MacroSectorFitScore(
        sensitivity_component=sensitivity_component,
        favorable_significant_shock_count=favorable_count,
        total_significant_shock_count=total_significant_count,
        sensitivity_reason=sensitivity_reason,
        project_register_component=project_register_component,
        sector_momentum_component=sector_momentum_component,
        score=score, reason=reason,
    )
