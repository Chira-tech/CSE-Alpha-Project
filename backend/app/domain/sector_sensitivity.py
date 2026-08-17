"""
§33: Sector sensitivity matrix — "Estimated live from the regressions in
§30 step 6. The structure below is illustrative of the shape of the
output — the platform must populate it from its own estimation and never
hard-code it, because these relationships shift."

§30 step 6: "Sector sensitivity matrix — regress each sector's excess
return on macro shocks. The practical output that drives sector tilt
(§33)."

WHICH SHOCKS THIS ACTUALLY REGRESSES ON, AND WHY NOT §33'S FULL
ILLUSTRATIVE COLUMN SET. §33's own table shows five example shock
columns: Rate cut, LKR depreciation, Oil spike, Tourism rebound, Fiscal
expansion — explicitly labelled illustrative, not a fixed schema. This
module regresses on whatever real macro shock series a caller supplies
(`app.domain.sector_sensitivity_view` builds these from real
`macro_series` data: policy rate change, 364-day T-bill yield change,
CCPI change, LKR/USD change — real proxies for "Rate cut"/"LKR
depreciation", roughly). Oil (Brent), tourist arrivals/earnings, and
fiscal spending are NOT ingested anywhere in this system, so "Oil
spike"/"Tourism rebound"/"Fiscal expansion" columns are never built here
— not simulated, not proxied, just absent, the same honesty
`app.domain.regime_classification`'s own composite read already applies
to §29's un-ingested blocks.

NO QUALITATIVE +/++/−/−− SCALE, DELIBERATELY, UNLIKE §33'S OWN
ILLUSTRATIVE PRESENTATION. §33's worked table uses symbols like "++" and
"−−" to convey both direction and rough magnitude. This module reports a
real OLS coefficient, its p-value and R² instead, and derives only
`"positive"`/`"negative"`/`"not_significant"` from the SIGN and a
standard, disclosed significance threshold (p < 0.05) — never a
magnitude gradation, because a magnitude threshold that means anything
comparably across shock series measured in wildly different units
(a T-bill yield change in fraction-points vs. an LKR/USD move in percent)
is not something this module has a real basis for, and inventing one
would be exactly the "confident, precise, entirely fictional" symbol
§15 warns against — a caller wanting a visual +/− ladder can derive one
from the real coefficients/percentiles across sectors, which this module
does not attempt.

MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE REUSES `app.domain.gics`'s OWN
REASONING, NOT A NEW THRESHOLD. That module's docstring: "Sri Lanka has
three listed telecoms and one automobile company; ranking a company
against two peers produces a percentile that is technically computable
and practically meaningless." A sector return built from one or two
constituents has the identical problem — this module's threshold is set
to match, not invented independently.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

#: Matches app.domain.gics's own "two peers is meaningless" reasoning —
#: see module docstring.
MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE = 3

#: A regression on fewer paired (sector-return, shock) observations than
#: this is not refused outright (unlike the Markov fit's hard floor) but
#: IS a real, disclosed data point — see `SensitivityEstimate.
#: observation_count`, always returned so a caller can judge a 35-
#: observation estimate differently from a 250-observation one. Below
#: this floor, no estimate is attempted at all: an OLS line through fewer
#: than 20 points is not a regression, it's a coincidence.
MIN_OBSERVATIONS_FOR_REGRESSION = 20

#: Standard, disclosed convention — not derived from anything CSE-
#: specific. A caller who wants a stricter bar can filter on `p_value`
#: directly; `significant`/`direction_label` exist for a quick read.
SIGNIFICANCE_THRESHOLD = Decimal("0.05")


@dataclass(frozen=True)
class MacroShockSeries:
    name: str
    """Human-readable — "Policy rate change", "LKR/USD % change" — shown
    as the matrix's column header."""

    values_by_date: dict[dt.date, Decimal]
    """The shock's own daily value on each date it has one — a level
    CHANGE (not a level), already computed by the caller (see `app.
    domain.sector_sensitivity_view` for exactly how each real shock
    series is built). Dates with no observation are simply absent, not
    zero — a step-function series like the policy rate should not be
    silently treated as "zero shock" on every day it didn't move, which
    would dilute a real regression with thousands of fabricated
    zero-shock non-events."""


@dataclass(frozen=True)
class SectorReturns:
    sector: str
    constituent_count: int
    """How many real tickers contributed to this sector's return series
    — shown even when below `MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE`, so a
    caller can see WHY a sector was excluded, not just that it was."""

    returns_by_date: dict[dt.date, Decimal]
    """Equal-weighted daily sector return, already computed by the
    caller (see `app.domain.sector_sensitivity_view` for the real
    adjusted-price computation)."""


@dataclass(frozen=True)
class SensitivityEstimate:
    shock_name: str
    coefficient: Decimal
    """OLS slope — sector return's sensitivity to a one-unit move in the
    shock series, in the shock's own units."""

    p_value: Decimal
    r_squared: Decimal
    observation_count: int
    significant: bool
    """`p_value < SIGNIFICANCE_THRESHOLD` — computed once here so every
    caller uses the same disclosed bar rather than re-deriving it."""

    direction_label: str
    """One of `"positive"`, `"negative"`, `"not_significant"` — see
    module docstring for why there is no magnitude gradation."""


@dataclass(frozen=True)
class SectorSensitivityRow:
    sector: str
    constituent_count: int
    estimates: tuple[SensitivityEstimate, ...] = field(default_factory=tuple)
    """One entry per shock series that had enough paired observations to
    estimate — a shock this sector had too little overlapping data for
    is simply absent from this tuple, not present with a fabricated
    estimate."""


def estimate_sensitivity(
    returns_by_date: dict[dt.date, Decimal], shock: MacroShockSeries
) -> SensitivityEstimate | None:
    """A single sector-return-on-shock OLS regression, real statsmodels
    output, on whatever dates both series actually have a value for.
    `None` — never a number computed from too little data — below
    `MIN_OBSERVATIONS_FOR_REGRESSION` paired points, or when the shock
    series has zero variance over the overlapping window (a constant
    regressor has no slope to estimate)."""
    paired = [
        (shock.values_by_date[d], returns_by_date[d])
        for d in returns_by_date
        if d in shock.values_by_date
    ]
    if len(paired) < MIN_OBSERVATIONS_FOR_REGRESSION:
        return None

    # Imported lazily — same reasoning as app.domain.regime_
    # classification.fit_markov_regime_read: a real but sizeable
    # dependency this module is one of only two current consumers of.
    import numpy as np
    import statsmodels.api as sm

    x = np.array([float(p[0]) for p in paired])
    y = np.array([float(p[1]) for p in paired])
    if np.std(x) == 0:
        return None

    model = sm.OLS(y, sm.add_constant(x)).fit()
    if len(model.params) < 2:
        return None  # a degenerate fit (e.g. perfectly collinear) — real, not hypothetical

    coefficient = Decimal(str(round(float(model.params[1]), 8)))
    p_value = Decimal(str(round(float(model.pvalues[1]), 6)))
    r_squared = Decimal(str(round(float(model.rsquared), 6)))
    significant = p_value < SIGNIFICANCE_THRESHOLD

    if not significant:
        direction = "not_significant"
    elif coefficient > 0:
        direction = "positive"
    else:
        direction = "negative"

    return SensitivityEstimate(
        shock_name=shock.name,
        coefficient=coefficient,
        p_value=p_value,
        r_squared=r_squared,
        observation_count=len(paired),
        significant=significant,
        direction_label=direction,
    )


def compute_sector_sensitivity_matrix(
    sector_returns: list[SectorReturns], shocks: list[MacroShockSeries]
) -> list[SectorSensitivityRow]:
    """§30 step 6 / §33, assembled: one row per sector with enough real
    constituents, one estimate per shock with enough real overlapping
    history — never a hard-coded relationship, per §33's own explicit
    warning. Sectors below `MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE` are
    OMITTED entirely (not returned with an empty/fabricated row) — see
    `app.domain.sector_sensitivity_view` for where the thin-sector list
    itself is surfaced instead, the same "excluded, named" pattern
    `app.domain.valuation_view._confirmable_line_items` uses for
    unconfirmed fundamentals.
    """
    rows: list[SectorSensitivityRow] = []
    for sr in sector_returns:
        if sr.constituent_count < MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE:
            continue
        estimates = tuple(
            est
            for shock in shocks
            if (est := estimate_sensitivity(sr.returns_by_date, shock)) is not None
        )
        rows.append(
            SectorSensitivityRow(
                sector=sr.sector, constituent_count=sr.constituent_count, estimates=estimates
            )
        )
    return rows
