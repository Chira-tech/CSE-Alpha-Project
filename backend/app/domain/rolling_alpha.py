"""
§36's "rolling 36-month alpha path" — decaying alpha is a warning, spiky
alpha is usually a data error. DO NOT FAKE A PATH OUT OF ~37 MONTHS OF
REAL DATA.

36 months ~ 156 weeks — the SAME length as `app.domain.carhart_
regression`'s own primary regression window. Sliding a 156-week window
weekly across this system's real ~163-week depth produces at most
`163 - 156 + 1 = 8` endpoints, and each neighbouring pair shares AT
LEAST 155 of 156 real observations — one week's difference. Movement
between two such adjacent points would be almost entirely the effect of
that one changed week, not a real decay or spike signal §36 is asking
this path to detect. Classifying shape from points this dependent on
each other would be presenting noise as a real finding.

THE HONEST RULE: compute whatever real points genuinely exist (0-8
today, growing by roughly one more every real week going forward, since
this system's own forward price capture is already running), each
carrying its own `overlap_weeks_with_previous` so a caller can SEE how
dependent neighbouring points really are — never hidden. Only classify
the shape `"decaying"`/`"spiky"`/`"stable"` once
`MIN_INDEPENDENT_ROLLING_POINTS` (6) real points exist with pairwise
overlap below `INDEPENDENCE_OVERLAP_THRESHOLD` (50%) — a bar today's
real depth genuinely cannot meet (8 points at 156-week spacing over 163
weeks have ~99% pairwise overlap, nowhere close). Until then,
`pattern_label = "insufficient_independent_points"`, and the real (if
thin and highly-overlapping) points are still returned rather than
withheld — the same "never a fabricated 0, but never silently withheld
either" logic `app.domain.composite_score.renormalize` already applies
to a missing pillar, applied here to a missing PATH instead of a score.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domain.carhart_regression import PRIMARY_WINDOW_WEEKS, fit_carhart_dimson

ROLLING_ALPHA_WINDOW_WEEKS = PRIMARY_WINDOW_WEEKS
MIN_INDEPENDENT_ROLLING_POINTS = 6
INDEPENDENCE_OVERLAP_THRESHOLD = Decimal("0.5")

PatternLabel = Literal["decaying", "spiky", "stable", "insufficient_independent_points", "no_real_points"]


@dataclass(frozen=True)
class RollingAlphaPoint:
    window_end_date: dt.date
    alpha_annualized: Decimal | None
    alpha_tstat: Decimal | None
    overlap_weeks_with_previous: int | None
    """`None` for the first (oldest) point — there is no previous point
    to overlap with."""


@dataclass(frozen=True)
class RollingAlphaPath:
    points: tuple[RollingAlphaPoint, ...]
    pattern_label: PatternLabel
    reason: str


def build_rolling_alpha_path(
    weekly_excess_returns: dict[dt.date, Decimal],
    weekly_factor_returns: dict[str, dict[dt.date, Decimal]],
    *, window_weeks: int = ROLLING_ALPHA_WINDOW_WEEKS,
) -> RollingAlphaPath:
    """One `RollingAlphaPoint` per real weekly date that has at least
    `window_weeks` of real history behind it, each computed by re-running
    `fit_carhart_dimson` on that specific trailing window (real,
    independent-of-the-final-full-sample-window regressions, not a
    derived interpolation) — see module docstring for why the SHAPE
    classification is gated separately from simply having any points at
    all."""
    common_dates = sorted(
        set(weekly_excess_returns) & set.intersection(*(set(s) for s in weekly_factor_returns.values()))
    ) if weekly_factor_returns else []

    if len(common_dates) < window_weeks:
        return RollingAlphaPath(
            points=(), pattern_label="no_real_points",
            reason=f"only {len(common_dates)} real overlapping week(s), need at least {window_weeks} for even one real window",
        )

    points: list[RollingAlphaPoint] = []
    prev_window_dates: set[dt.date] | None = None
    for end_idx in range(window_weeks - 1, len(common_dates)):
        window_dates = common_dates[end_idx - window_weeks + 1 : end_idx + 1]
        window_end = window_dates[-1]

        excess_slice = {d: weekly_excess_returns[d] for d in window_dates}
        factor_slice = {name: {d: series[d] for d in window_dates if d in series} for name, series in weekly_factor_returns.items()}

        result = fit_carhart_dimson(excess_slice, factor_slice, window_weeks=window_weeks)
        overlap = None
        if prev_window_dates is not None:
            overlap = len(prev_window_dates & set(window_dates))
        points.append(
            RollingAlphaPoint(
                window_end_date=window_end,
                alpha_annualized=result.alpha_annualized if not result.insufficient_data else None,
                alpha_tstat=result.alpha_tstat if not result.insufficient_data else None,
                overlap_weeks_with_previous=overlap,
            )
        )
        prev_window_dates = set(window_dates)

    # A REAL greedy independence selection, not a filter on adjacent-week
    # overlap. `overlap_weeks_with_previous` (stored on each point, always
    # measured against the immediately-preceding WEEKLY point) exists so a
    # caller can see how much a week-to-week neighbour changed — but since
    # a new point is computed every single week, that overlap is ~99%
    # for EVERY pair regardless of how much total history exists, and
    # filtering on it would never select anything no matter the real
    # depth. Independence instead means "low overlap with the last point
    # actually kept for classification" — walk the dense weekly points in
    # order, keep the first, then keep the next one only once its window
    # has drifted far enough from the last KEPT window's own dates.
    window_dates_by_point: dict[dt.date, set[dt.date]] = {}
    for end_idx in range(window_weeks - 1, len(common_dates)):
        window_dates_by_point[common_dates[end_idx]] = set(common_dates[end_idx - window_weeks + 1: end_idx + 1])

    independent_points: list[RollingAlphaPoint] = []
    last_kept_dates: set[dt.date] | None = None
    for p in points:
        this_dates = window_dates_by_point[p.window_end_date]
        if last_kept_dates is None or len(this_dates & last_kept_dates) / window_weeks < float(INDEPENDENCE_OVERLAP_THRESHOLD):
            independent_points.append(p)
            last_kept_dates = this_dates

    if len(independent_points) < MIN_INDEPENDENT_ROLLING_POINTS:
        return RollingAlphaPath(
            points=tuple(points),
            pattern_label="insufficient_independent_points",
            reason=(
                f"{len(points)} real rolling point(s) exist, but only {len(independent_points)} are "
                f"reasonably independent (pairwise overlap < {INDEPENDENCE_OVERLAP_THRESHOLD:.0%}) — "
                f"need at least {MIN_INDEPENDENT_ROLLING_POINTS} to trust a decay/spike shape rather than "
                f"one changed week's noise. Real points shown regardless."
            ),
        )

    alphas = [float(p.alpha_annualized) for p in independent_points if p.alpha_annualized is not None]
    if len(alphas) < 2:
        return RollingAlphaPath(
            points=tuple(points), pattern_label="insufficient_independent_points",
            reason="enough independent points exist, but too few produced a real (non-noise) alpha to classify a shape",
        )

    first_half = alphas[: len(alphas) // 2]
    second_half = alphas[len(alphas) // 2:]
    mean_first = sum(first_half) / len(first_half)
    mean_second = sum(second_half) / len(second_half)
    stdev = (sum((a - sum(alphas) / len(alphas)) ** 2 for a in alphas) / len(alphas)) ** 0.5

    if stdev > 0 and abs(mean_second - mean_first) > 2 * stdev:
        label: PatternLabel = "spiky"
        reason = f"alpha swings by more than 2 real standard deviations across the path (stdev={stdev:.4f})"
    elif mean_second < mean_first * 0.5 and mean_first > 0:
        label = "decaying"
        reason = f"real alpha fell from a mean of {mean_first:.4f} to {mean_second:.4f} across the path"
    else:
        label = "stable"
        reason = f"real alpha stayed within a normal range across the path (mean={sum(alphas)/len(alphas):.4f}, stdev={stdev:.4f})"

    return RollingAlphaPath(points=tuple(points), pattern_label=label, reason=reason)
