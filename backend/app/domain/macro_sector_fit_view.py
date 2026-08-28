"""
§38's Macro & sector fit pillar, DB-wired — wires §33's real sector
sensitivity matrix (`app.domain.sector_sensitivity_view`), §31's real
regime read (`app.domain.macro_engine_view.regime_for`), §34's real
confirmed project register (`app.domain.national_projects_view`,
REUSED UNCHANGED — the exact function `app.domain.composite_score_view`
already calls for the Growth pillar's own evidence), and a new, real
sector-momentum figure into `app.domain.macro_sector_fit`'s pure
combinator.

SECTOR MOMENTUM: sum of `app.domain.sector_sensitivity_view.
sector_returns_for`'s own real daily equal-weighted sector return series
over `SECTOR_MOMENTUM_LOOKBACK_DAYS`, squashed the same disclosed
`tanh`-based way `app.domain.timing_battery_view` already uses for its
own return-based signals — see that module's own docstring for why a
full cross-sectional percentile rank (the more faithful, but heavier,
alternative) is deliberately deferred rather than half-built here too.

PROJECT-REGISTER EXPOSURE reuses `confirmed_base_case_revenue_growth_
adjustment_for`'s own real percentage adjustment (already the exact
figure powering the Growth pillar's own evidence in `composite_score_
view`), squashed the same way.
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.macro_engine_view import regime_for
from app.domain.macro_sector_fit import MacroSectorFitScore, combine_macro_sector_fit, sector_fit_from_sensitivity
from app.domain.national_projects_view import confirmed_base_case_revenue_growth_adjustment_for
from app.domain.sector_sensitivity import SectorSensitivityRow
from app.domain.sector_sensitivity_view import SectorSensitivityView, sector_returns_for, sector_sensitivity_matrix_for
from app.models.securities import Security

SECTOR_MOMENTUM_LOOKBACK_DAYS = 90
_MOMENTUM_SCALE = Decimal("0.15")
_PROJECT_ADJUSTMENT_SCALE = Decimal("0.03")


def _tanh_squash(value: Decimal, scale: Decimal) -> Decimal:
    x = float(value) / float(scale)
    return Decimal(str(round(50.0 + 50.0 * math.tanh(x), 4)))


def _row_for_sector(view: SectorSensitivityView, sector: str | None) -> SectorSensitivityRow | None:
    if sector is None:
        return None
    return next((r for r in view.rows if r.sector == sector), None)


def macro_sector_fit_for(
    db: Session, ticker: str, as_of: dt.date | None = None, *,
    sector_sensitivity_view: SectorSensitivityView | None = None,
    regime_label: str | None = None,
) -> MacroSectorFitScore:
    """§38's Macro & sector fit for one real ticker. `sector_sensitivity_
    view`/`regime_label` are optional shared-computation params — both
    are genuinely expensive universe-wide passes (a full §33 matrix
    rebuild; a Markov regime fit), so a caller iterating many tickers
    (e.g. `app.domain.composite_score_view`'s own universe pass) should
    compute each ONCE and pass it to every per-ticker call, the same
    shared-pass pattern `app.domain.opportunity_ranking_view` already
    establishes — computed fresh here only when not supplied, so a
    single-ticker caller still gets a real answer without extra plumbing."""
    stamp = as_of or dt.date.today()

    if sector_sensitivity_view is None:
        sector_sensitivity_view = sector_sensitivity_matrix_for(db, stamp)
    if regime_label is None:
        regime_view = regime_for(db, stamp)
        regime_label = regime_view.result.label if regime_view.result is not None else None

    security = db.get(Security, ticker)
    sector = security.cse_sector if security is not None else None
    row = _row_for_sector(sector_sensitivity_view, sector)

    sensitivity_component, favorable, total, sensitivity_reason = sector_fit_from_sensitivity(row, regime_label)

    adjustment, _contributing = confirmed_base_case_revenue_growth_adjustment_for(db, ticker, stamp)
    project_component = _tanh_squash(adjustment, _PROJECT_ADJUSTMENT_SCALE) if adjustment is not None else None

    momentum_component: Decimal | None = None
    if sector is not None:
        sector_tickers = [
            t for (t,) in db.query(Security.ticker).filter(Security.cse_sector == sector).all()
        ]
        sector_returns = sector_returns_for(db, sector, sector_tickers, stamp, SECTOR_MOMENTUM_LOOKBACK_DAYS)
        if sector_returns.returns_by_date:
            total_return = sum(sector_returns.returns_by_date.values(), Decimal(0))
            momentum_component = _tanh_squash(total_return, _MOMENTUM_SCALE)

    return combine_macro_sector_fit(
        sensitivity_component=sensitivity_component, favorable_count=favorable, total_significant_count=total,
        sensitivity_reason=sensitivity_reason, project_register_component=project_component,
        sector_momentum_component=momentum_component,
    )
