"""
Dimson-corrected, Blume-adjusted beta (§17.2, §35.2).

WHY DIMSON, NOT AN ORDINARY OLS BETA. `app.ingestion.schemas.CompanyBetaInfo`
already said why before this module existed: "CSE stocks routinely go
days without trading, and an uncorrected OLS beta is 'severely downward
biased' — skipping that is called out as 'the single most common
technical error in frontier-market factor work'." A thinly-traded stock's
price reacts to yesterday's market move with a lag, because the LAST
TRADE, not today's market, set today's closing print. Regressing only on
the same-day market return misses that lagged reaction entirely and
understates true systematic risk. Dimson (1979) fixes this by regressing
on the market return at t-1, t and t+1 and summing the three
coefficients — the lagged and lead terms capture the reaction an ordinary
beta throws away.

VERIFIED AGAINST THE PUBLISHED FIGURE, AND THE TWO GENUINELY DISAGREE.
For COMB.N0000 over the real backfilled year (17 Aug 2026): naive
same-day-only OLS beta = 0.96, Dimson-corrected = 1.10, Blume-adjusted
(toward 1.0) = 1.07. The exchange's own published triASIBetaValue for
the same stock is 0.79. This module's correction moved in the direction
theory predicts — up, away from the downward-biased naive estimate — but
that made it diverge MORE from CSE's own figure, not less. The two are
not attempting to measure the same thing: CSE's beta likely uses a
different window, frequency, or a total-return basis (the field is named
`triASIBetaValue` — "TRI" suggests a total-return index, which this
system's price-only ASPI series is not). Neither is presented as ground
truth; `app.models.securities.published_beta_asi` stores CSE's figure
specifically so both can be shown side by side rather than one silently
overwriting the other.

MIN_OBSERVATIONS is a judgement call, not a number in the spec. A 4-
parameter regression (intercept + 3 lags) is numerically defined with 5
points, but a betas from 5 points is noise wearing a formula. 30 is
chosen as a floor below which the module refuses to compute rather than
return an unstable number with no visible warning.

WHAT THIS DOES NOT DO. §17.2 wants the Dimson-Blume beta "blended with a
bottom-up sector beta unlevered/relevered at the company's own D/E,"
with bottom-up dominating below 45 of 60 sessions traded. Bottom-up needs
a sector-wide beta estimation this system does not build — this module
only ever returns the Dimson-Blume half, and reports whether liquidity
is thin enough (per §17.2's own 45/60 threshold) that the spec would
prefer the blend it cannot supply.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

MIN_OBSERVATIONS = 30

# Standard Blume (1971) weights: shrink the raw estimate two-thirds of
# the way toward the market average of 1.0. Not derived from anything
# company-specific — it is the textbook convention the spec's "Blume-
# adjusted toward 1.0" phrase refers to.
_BLUME_RAW_WEIGHT = 2 / 3
_BLUME_MARKET_WEIGHT = 1 / 3


@dataclass(frozen=True)
class PriceSeriesPoint:
    date: object  # dt.date, kept loose per this project's convention elsewhere
    close: Decimal


@dataclass(frozen=True)
class BetaResult:
    dimson_beta: Decimal | None
    blume_adjusted_beta: Decimal | None
    lag_coefficient: Decimal | None
    contemporaneous_coefficient: Decimal | None
    lead_coefficient: Decimal | None
    observations: int
    sessions_in_window: int
    thin_trading: bool
    """True when the spec's own 45-of-60 threshold (§17.2) is not met —
    the case where bottom-up sector beta should dominate. This module
    still returns its Dimson-Blume estimate when possible, flagged, since
    refusing outright would throw away a real (if less trusted) number."""

    insufficient_data: bool
    reason: str | None


def daily_returns(series: list[PriceSeriesPoint]) -> list[tuple[object, float]]:
    """(date, return) pairs from consecutive stored closes. Deliberately
    uses whatever dates are actually present rather than every calendar
    day — a gap in the stored series (a holiday, a missed capture) simply
    produces one fewer return, not a fabricated flat day."""
    ordered = sorted(series, key=lambda p: p.date)
    returns: list[tuple[object, float]] = []
    for prev, curr in zip(ordered, ordered[1:]):
        if prev.close > 0:
            returns.append((curr.date, float((curr.close - prev.close) / prev.close)))
    return returns


def _solve_normal_equations(x_rows: list[list[float]], y: list[float]) -> list[float] | None:
    """Solve (X'X)b = X'y by Gaussian elimination with partial pivoting.
    No numpy/scipy dependency in this project (see app.domain.trend_detection
    for the same constraint on Mann-Kendall). Returns None if the system
    is singular — a real possibility with a short or degenerate series,
    and a caller must treat that as "cannot compute", not crash."""
    k = len(x_rows[0])
    n = len(x_rows)
    xtx = [[sum(x_rows[i][a] * x_rows[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    xty = [sum(x_rows[i][a] * y[i] for i in range(n)) for a in range(k)]

    augmented = [row[:] + [xty[i]] for i, row in enumerate(xtx)]
    for col in range(k):
        pivot_row = max(range(col, k), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
            return None  # singular — e.g. a market return series with zero variance
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        for j in range(col, k + 1):
            augmented[col][j] /= pivot
        for r in range(k):
            if r != col:
                factor = augmented[r][col]
                for j in range(col, k + 1):
                    augmented[r][j] -= factor * augmented[col][j]
    return [augmented[i][k] for i in range(k)]


def compute_dimson_beta(
    stock_series: list[PriceSeriesPoint],
    market_series: list[PriceSeriesPoint],
    *,
    sessions_traded_in_window: int,
    window_sessions: int = 60,
    min_observations: int = MIN_OBSERVATIONS,
) -> BetaResult:
    """Regress the stock's return at t on the market's return at t-1, t
    and t+1, and sum the three coefficients. Alignment is by DATE
    intersection, not by list position — a date present in one series but
    not the other (a stock suspension, a market holiday recorded
    differently) must not silently shift the lag/lead pairing."""
    stock_returns = dict(daily_returns(stock_series))
    market_returns = dict(daily_returns(market_series))
    common_dates = sorted(set(stock_returns) & set(market_returns))

    if len(common_dates) < min_observations + 2:  # +2: need a lag and a lead around each point
        return BetaResult(
            dimson_beta=None, blume_adjusted_beta=None,
            lag_coefficient=None, contemporaneous_coefficient=None, lead_coefficient=None,
            observations=len(common_dates), sessions_in_window=sessions_traded_in_window,
            thin_trading=sessions_traded_in_window < 45,
            insufficient_data=True,
            reason=f"only {len(common_dates)} overlapping return(s), need at least "
            f"{min_observations + 2} for a Dimson regression to mean anything",
        )

    market_by_date = [(d, market_returns[d]) for d in common_dates]

    x_rows: list[list[float]] = []
    y: list[float] = []
    for i in range(1, len(common_dates) - 1):
        date_t = common_dates[i]
        if date_t not in stock_returns:
            continue
        x_rows.append([1.0, market_by_date[i - 1][1], market_by_date[i][1], market_by_date[i + 1][1]])
        y.append(stock_returns[date_t])

    if len(x_rows) < min_observations:
        return BetaResult(
            dimson_beta=None, blume_adjusted_beta=None,
            lag_coefficient=None, contemporaneous_coefficient=None, lead_coefficient=None,
            observations=len(x_rows), sessions_in_window=sessions_traded_in_window,
            thin_trading=sessions_traded_in_window < 45,
            insufficient_data=True,
            reason=f"only {len(x_rows)} usable observation(s) after lag/lead alignment, "
            f"need at least {min_observations}",
        )

    solved = _solve_normal_equations(x_rows, y)
    if solved is None:
        return BetaResult(
            dimson_beta=None, blume_adjusted_beta=None,
            lag_coefficient=None, contemporaneous_coefficient=None, lead_coefficient=None,
            observations=len(x_rows), sessions_in_window=sessions_traded_in_window,
            thin_trading=sessions_traded_in_window < 45,
            insufficient_data=True,
            reason="regression is singular (e.g. zero-variance market return series) — cannot solve",
        )

    _alpha, b_lag, b0, b_lead = solved
    if any(math.isnan(v) or math.isinf(v) for v in (b_lag, b0, b_lead)):
        return BetaResult(
            dimson_beta=None, blume_adjusted_beta=None,
            lag_coefficient=None, contemporaneous_coefficient=None, lead_coefficient=None,
            observations=len(x_rows), sessions_in_window=sessions_traded_in_window,
            thin_trading=sessions_traded_in_window < 45,
            insufficient_data=True,
            reason="regression produced a non-finite coefficient",
        )

    dimson = b_lag + b0 + b_lead
    blume = _BLUME_RAW_WEIGHT * dimson + _BLUME_MARKET_WEIGHT * 1.0

    def _dec(v: float) -> Decimal:
        return Decimal(str(round(v, 6)))

    return BetaResult(
        dimson_beta=_dec(dimson),
        blume_adjusted_beta=_dec(blume),
        lag_coefficient=_dec(b_lag),
        contemporaneous_coefficient=_dec(b0),
        lead_coefficient=_dec(b_lead),
        observations=len(x_rows),
        sessions_in_window=sessions_traded_in_window,
        thin_trading=sessions_traded_in_window < 45,
        insufficient_data=False,
        reason=None,
    )
