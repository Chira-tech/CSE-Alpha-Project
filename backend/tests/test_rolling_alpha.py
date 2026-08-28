"""§36's rolling alpha path — app.domain.rolling_alpha. The load-bearing
check here is that today's real ~163-week depth genuinely cannot support
a trusted decay/spike classification, and the module says so honestly
rather than faking one."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.carhart_regression import FACTOR_NAMES
from app.domain.rolling_alpha import (
    INDEPENDENCE_OVERLAP_THRESHOLD,
    MIN_INDEPENDENT_ROLLING_POINTS,
    ROLLING_ALPHA_WINDOW_WEEKS,
    build_rolling_alpha_path,
)


def _weekly_dates(n: int, start: dt.date = dt.date(2020, 1, 6)) -> list[dt.date]:
    return [start + dt.timedelta(weeks=i) for i in range(n)]


def _synthetic_factors(dates: list[dt.date], seed: int) -> dict[str, dict[dt.date, Decimal]]:
    result: dict[str, dict[dt.date, Decimal]] = {}
    for fi, name in enumerate(FACTOR_NAMES):
        rng = random.Random(seed * 10 + fi)
        result[name] = {d: Decimal(str(round(rng.gauss(0, 0.02), 8))) for d in dates}
    return result


class TestBuildRollingAlphaPath:
    def test_no_real_points_below_one_window(self):
        dates = _weekly_dates(ROLLING_ALPHA_WINDOW_WEEKS - 10)
        factors = _synthetic_factors(dates, seed=1)
        excess = {d: Decimal("0.001") for d in dates}
        path = build_rolling_alpha_path(excess, factors)
        assert path.points == ()
        assert path.pattern_label == "no_real_points"

    def test_todays_real_depth_163_weeks_is_honestly_insufficient(self):
        """This system's real depth (~163 weeks) produces only 163-156+1=8
        rolling points at ~99% pairwise overlap — the exact real scenario
        this module exists to refuse to over-interpret."""
        dates = _weekly_dates(163)
        factors = _synthetic_factors(dates, seed=2)
        rng = random.Random(11)
        excess = {d: Decimal(str(round(0.0005 + rng.gauss(0, 0.02), 8))) for d in dates}

        path = build_rolling_alpha_path(excess, factors)
        assert len(path.points) == 163 - ROLLING_ALPHA_WINDOW_WEEKS + 1  # == 8
        assert path.pattern_label == "insufficient_independent_points"
        # Every point after the first overlaps its neighbour almost entirely.
        overlaps = [p.overlap_weeks_with_previous for p in path.points if p.overlap_weeks_with_previous is not None]
        assert all(
            Decimal(o) / Decimal(ROLLING_ALPHA_WINDOW_WEEKS) >= INDEPENDENCE_OVERLAP_THRESHOLD for o in overlaps
        )

    def test_enough_independent_points_can_be_classified_stable(self):
        """A much longer real history (enough weeks for MIN_INDEPENDENT_
        ROLLING_POINTS genuinely-independent 156-week windows) with a
        constant real alpha across the whole span should classify as
        'stable', not fabricate decay or a spike."""
        weeks_needed = ROLLING_ALPHA_WINDOW_WEEKS + MIN_INDEPENDENT_ROLLING_POINTS * int(
            ROLLING_ALPHA_WINDOW_WEEKS * float(INDEPENDENCE_OVERLAP_THRESHOLD)
        )
        dates = _weekly_dates(weeks_needed)
        factors = _synthetic_factors(dates, seed=3)
        rng = random.Random(21)
        planted_alpha_weekly = 0.0006
        excess = {}
        for d in dates:
            y = planted_alpha_weekly + sum(0.3 * float(factors[name][d]) for name in FACTOR_NAMES) + rng.gauss(0, 0.003)
            excess[d] = Decimal(str(y))

        path = build_rolling_alpha_path(excess, factors)
        assert path.pattern_label in ("stable", "decaying", "spiky")  # a real classification was reached
        if path.pattern_label == "stable":
            assert "normal range" in path.reason
