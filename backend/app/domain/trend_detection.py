"""
§13: "A ratio is a fact; a trajectory is an insight." Turns a ratio's
own historical values into direction, acceleration and consistency —
pure functions over `(period_end, value)` pairs, no I/O, so they can be
tested against hand-built series independently of how many real periods
happen to be sitting in the database today.

HONESTY ABOUT WHAT THIS CAN ACTUALLY SAY RIGHT NOW. §12 targets 10 years
/ minimum 8 quarters of history per company. The financial-statement
extractor (`app.domain.financial_statement_parsing`) is verified against
one real filing, and `getFinancialAnnouncement` — the only ingestion
source wired up — is a recent-filings feed, not a historical archive
(README_ENDPOINTS.md). So most tickers in this database have one period
of fundamentals, not ten years of them, and a "trend" computed from one
point is not a trend, it is a point pretending to be one.

This module therefore treats "insufficient history" as a first-class,
displayed result rather than a state that silently produces a plausible-
looking direction from too little data — the exact false-precision Part
N warns about, just relocated from valuation into trend analysis. As
more periods accumulate (the deterministic extractor runs forward every
scan), trends for a given ticker start reporting themselves without any
code change here.

MANN-KENDALL, IMPLEMENTED BY HAND. No scipy/numpy dependency exists in
this project (see requirements.txt), and the test is genuinely simple:
count how many of the pairwise later-values exceed earlier-values versus
the reverse, and use the normal approximation for significance. This is
the textbook Mann-Kendall S-statistic and its variance under the null of
no trend, not a simplification of it — the normal approximation is the
standard large-sample form, which is exactly why a minimum period count
is enforced before applying it at all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

# Below this many periods, a "trend" is indistinguishable from noise —
# §13 targets up to 10 years of quarters; this is the floor below which
# the module refuses to characterise a direction at all, not a claim that
# this many points gives strong statistical power (it doesn't — the
# normal approximation genuinely wants more like 8-10 points to be
# trustworthy, and `significant` reflects that per-series rather than
# this constant pretending otherwise).
MIN_PERIODS_FOR_DIRECTION = 3
MIN_PERIODS_FOR_ACCELERATION = 4
MIN_PERIODS_FOR_CONSISTENCY = 3

# Two-tailed 95% critical value for the standard normal — the
# conventional Mann-Kendall significance threshold.
_Z_CRITICAL_95 = Decimal("1.96")


class Direction(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    NO_TREND = "no_trend"
    INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass(frozen=True)
class RatioSeriesPoint:
    period_end: object  # dt.date — kept loose to avoid importing datetime just for typing here
    value: Decimal


@dataclass(frozen=True)
class TrendDirectionResult:
    direction: Direction
    significant: bool
    """Whether |z| exceeds the 95% critical value. A direction can be
    reported as increasing/decreasing without being `significant` — the
    sign of the slope is informative even when the sample is too small
    or too noisy to call it statistically distinguishable from no trend,
    and the UI must show both, not collapse them into one flag."""

    z_score: Decimal | None
    periods_used: int


@dataclass(frozen=True)
class AccelerationResult:
    accelerating: bool | None
    """True = the trend is speeding up, False = fading, None =
    insufficient history to say. Not a synonym for `direction` — a ratio
    can be increasing while decelerating (still improving, but by less
    each period), which is exactly the shape that later turns into a
    reversal."""

    periods_used: int


@dataclass(frozen=True)
class ConsistencyResult:
    fraction_same_direction: Decimal | None
    """Of the period-over-period moves, what fraction matched the
    series' own overall direction. 1.0 means monotonic; 0.5 means the
    series moves against its own trend as often as with it — a "trend"
    with 0.5 consistency is not a trend a reasonable person would trust."""

    periods_used: int


@dataclass(frozen=True)
class RatioTrend:
    ratio_key: str
    direction: TrendDirectionResult
    acceleration: AccelerationResult
    consistency: ConsistencyResult
    periods_used: int
    first_period: object | None
    last_period: object | None


def _sorted_values(series: list[RatioSeriesPoint]) -> list[Decimal]:
    return [p.value for p in sorted(series, key=lambda p: p.period_end)]


def mann_kendall_direction(series: list[RatioSeriesPoint]) -> TrendDirectionResult:
    """Sign and significance of the trend across the series.

    S = (# pairs later-greater-than-earlier) - (# pairs later-less-than-
    earlier), across every pair, not just consecutive points — this is
    what makes it a trend test rather than a "did it go up last period"
    check, and what makes it robust to a single noisy period the way a
    simple first-vs-last comparison is not.
    """
    values = _sorted_values(series)
    n = len(values)
    if n < MIN_PERIODS_FOR_DIRECTION:
        return TrendDirectionResult(Direction.INSUFFICIENT_HISTORY, False, None, n)

    s = 0
    for i in range(n):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    if s == 0:
        return TrendDirectionResult(Direction.NO_TREND, False, Decimal(0), n)

    # Standard Mann-Kendall variance under H0: no ties adjustment here —
    # ratios computed from real accounting figures are essentially never
    # exactly equal across periods, and this project does not carry a
    # ties-correction term it hasn't verified against a known-good
    # reference implementation. Ties, if they ever occur, make this
    # slightly conservative (a smaller |z| than the tie-corrected
    # version), which is the safe direction to be wrong in here.
    variance = Decimal(n * (n - 1) * (2 * n + 5)) / 18
    std = Decimal(str(math.sqrt(float(variance))))

    if s > 0:
        z = (Decimal(s) - 1) / std
    else:
        z = (Decimal(s) + 1) / std

    direction = Direction.INCREASING if s > 0 else Direction.DECREASING
    significant = abs(z) > _Z_CRITICAL_95
    return TrendDirectionResult(direction, significant, z, n)


def acceleration(series: list[RatioSeriesPoint]) -> AccelerationResult:
    """Sign of the average second difference — is period-over-period
    change itself growing or shrinking? Needs one more point than the
    direction test because a second derivative needs two first
    differences to compare."""
    values = _sorted_values(series)
    n = len(values)
    if n < MIN_PERIODS_FOR_ACCELERATION:
        return AccelerationResult(None, n)

    first_diffs = [values[i + 1] - values[i] for i in range(n - 1)]
    second_diffs = [first_diffs[i + 1] - first_diffs[i] for i in range(len(first_diffs) - 1)]
    avg_second_diff = sum(second_diffs) / len(second_diffs)
    if avg_second_diff == 0:
        return AccelerationResult(None, n)
    return AccelerationResult(avg_second_diff > 0, n)


def consistency(series: list[RatioSeriesPoint]) -> ConsistencyResult:
    """What fraction of period-over-period moves agree with the series'
    own overall direction (first value to last value). A high-|z| Mann-
    Kendall result from a series that zigzags 6 times against 4 is
    numerically "significant" and behaviourally untrustworthy — this is
    the number that catches that gap."""
    values = _sorted_values(series)
    n = len(values)
    if n < MIN_PERIODS_FOR_CONSISTENCY:
        return ConsistencyResult(None, n)

    overall = values[-1] - values[0]
    if overall == 0:
        return ConsistencyResult(None, n)
    overall_sign = 1 if overall > 0 else -1

    moves = [values[i + 1] - values[i] for i in range(n - 1) if values[i + 1] != values[i]]
    if not moves:
        return ConsistencyResult(None, n)

    matching = sum(1 for m in moves if (1 if m > 0 else -1) == overall_sign)
    return ConsistencyResult(Decimal(matching) / Decimal(len(moves)), n)


def analyse_ratio_trend(ratio_key: str, series: list[RatioSeriesPoint]) -> RatioTrend:
    """The combined result for one ratio's history — what a company-file
    trend badge is built from."""
    sorted_series = sorted(series, key=lambda p: p.period_end)
    return RatioTrend(
        ratio_key=ratio_key,
        direction=mann_kendall_direction(sorted_series),
        acceleration=acceleration(sorted_series),
        consistency=consistency(sorted_series),
        periods_used=len(sorted_series),
        first_period=sorted_series[0].period_end if sorted_series else None,
        last_period=sorted_series[-1].period_end if sorted_series else None,
    )
