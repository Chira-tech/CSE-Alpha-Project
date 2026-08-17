"""
§13 trend detection.

The Mann-Kendall cases below are hand-verified against the textbook
S-statistic definition (Gilbert 1987, the standard reference), not just
against this module's own output — an ROE series 11% -> 14% -> 16% -> 18%
(the example the Master Spec itself uses in §13) has S = +6 (every one
of the 6 pairs is increasing), which is what the test asserts before
checking direction/significance.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.trend_detection import (
    MIN_PERIODS_FOR_ACCELERATION,
    MIN_PERIODS_FOR_CONSISTENCY,
    MIN_PERIODS_FOR_DIRECTION,
    Direction,
    RatioSeriesPoint,
    acceleration,
    analyse_ratio_trend,
    consistency,
    mann_kendall_direction,
)


def series(*values: str, start_year: int = 2022) -> list[RatioSeriesPoint]:
    return [
        RatioSeriesPoint(period_end=dt.date(start_year + i, 3, 31), value=Decimal(v))
        for i, v in enumerate(values)
    ]


class TestMannKendallDirection:
    def test_the_specs_own_example_series_is_increasing(self):
        """§13's own illustration: "ROE moved 11% -> 14% -> 16% -> 18%
        over four years" — monotonic, so every one of C(4,2)=6 pairs is
        increasing and S=+6, the strongest possible signal at n=4."""
        result = mann_kendall_direction(series("0.11", "0.14", "0.16", "0.18"))
        assert result.direction == Direction.INCREASING
        assert result.periods_used == 4

    def test_a_monotonic_decrease_is_detected(self):
        result = mann_kendall_direction(series("0.20", "0.16", "0.12", "0.08"))
        assert result.direction == Direction.DECREASING

    def test_a_series_with_zero_net_pairwise_sign_reports_no_trend(self):
        """0.10, 0.14, 0.08, 0.12 — rank order (2nd, 4th, 1st, 3rd) is
        chosen specifically so the six pairwise signs cancel exactly:
        (a,b)+ (a,c)- (a,d)+ (b,c)- (b,d)- (c,d)+ = 0. The series has
        moved a lot but gone nowhere, which is a genuinely different fact
        from a monotonic series and must not be reported as either
        increasing or decreasing."""
        result = mann_kendall_direction(series("0.10", "0.14", "0.08", "0.12"))
        assert result.direction == Direction.NO_TREND

    def test_two_periods_is_insufficient_history(self):
        """Two points always look monotonic — that is not a trend, it is
        arithmetic, and reporting it as INCREASING would be exactly the
        false precision the whole module exists to avoid."""
        result = mann_kendall_direction(series("0.10", "0.15"))
        assert result.direction == Direction.INSUFFICIENT_HISTORY
        assert result.periods_used == 2

    def test_one_period_is_insufficient_history(self):
        result = mann_kendall_direction(series("0.10"))
        assert result.direction == Direction.INSUFFICIENT_HISTORY

    def test_empty_series_is_insufficient_history_not_an_error(self):
        result = mann_kendall_direction([])
        assert result.direction == Direction.INSUFFICIENT_HISTORY
        assert result.periods_used == 0

    def test_a_strong_long_monotonic_run_is_statistically_significant(self):
        """8 strictly increasing periods: S = C(8,2) = 28, the maximum
        possible, which should clear the 95% threshold decisively."""
        result = mann_kendall_direction(
            series("0.10", "0.11", "0.12", "0.13", "0.14", "0.15", "0.16", "0.17")
        )
        assert result.direction == Direction.INCREASING
        assert result.significant
        assert result.z_score is not None and result.z_score > Decimal("1.96")

    def test_a_short_series_can_be_directional_without_being_significant(self):
        """3 points is the minimum this module will even attempt — sign
        is reportable, but the sample is too small for 95% confidence,
        and `significant=False` must say so rather than the direction
        field alone implying more confidence than the data supports."""
        result = mann_kendall_direction(series("0.10", "0.12", "0.14"))
        assert result.direction == Direction.INCREASING
        assert not result.significant

    def test_the_minimum_constant_matches_what_the_function_enforces(self):
        assert mann_kendall_direction(series(*(["0.1"] * (MIN_PERIODS_FOR_DIRECTION - 1)))).direction == Direction.INSUFFICIENT_HISTORY


class TestAcceleration:
    def test_a_shrinking_gain_each_period_is_decelerating(self):
        """+5, +3, +1 — still improving every period, but by less each
        time. This is the shape §13 explicitly calls out as "improvement
        speeding up or fading" — a series can be `increasing` under Mann-
        Kendall while `accelerating=False` here, and both facts matter."""
        result = acceleration(series("0.10", "0.15", "0.18", "0.19"))
        assert result.accelerating is False

    def test_a_growing_gain_each_period_is_accelerating(self):
        result = acceleration(series("0.10", "0.11", "0.13", "0.16"))
        assert result.accelerating is True

    def test_below_the_minimum_periods_is_none_not_a_guess(self):
        result = acceleration(series("0.10", "0.15", "0.18"))
        assert result.accelerating is None
        assert result.periods_used < MIN_PERIODS_FOR_ACCELERATION


class TestConsistency:
    def test_a_monotonic_series_is_fully_consistent(self):
        result = consistency(series("0.10", "0.12", "0.14", "0.16"))
        assert result.fraction_same_direction == Decimal(1)

    def test_a_series_that_fights_its_own_trend_half_the_time(self):
        """Overall up (0.10 -> 0.16), but two of the four moves are down.
        A Mann-Kendall "increasing" call on this series would be numerically
        defensible and behaviourally misleading without this number
        alongside it — 0.10->0.14 (up), 0.14->0.11 (down), 0.11->0.15
        (up), 0.15->0.16 (up): 3 of 4 moves match the overall direction."""
        result = consistency(series("0.10", "0.14", "0.11", "0.15", "0.16"))
        assert result.fraction_same_direction == Decimal(3) / Decimal(4)

    def test_below_the_minimum_periods_is_none(self):
        result = consistency(series("0.10", "0.12"))
        assert result.fraction_same_direction is None
        assert result.periods_used < MIN_PERIODS_FOR_CONSISTENCY

    def test_a_flat_series_has_no_overall_direction_to_be_consistent_with(self):
        result = consistency(series("0.10", "0.12", "0.08", "0.10"))
        assert result.fraction_same_direction is None


class TestCombinedAnalysis:
    def test_unsorted_input_is_sorted_before_analysis(self):
        """A caller pulling periods from a database in an arbitrary
        order must not silently get a reversed trend."""
        out_of_order = [
            RatioSeriesPoint(dt.date(2024, 3, 31), Decimal("0.16")),
            RatioSeriesPoint(dt.date(2022, 3, 31), Decimal("0.11")),
            RatioSeriesPoint(dt.date(2023, 3, 31), Decimal("0.14")),
        ]
        result = analyse_ratio_trend("roe", out_of_order)
        assert result.first_period == dt.date(2022, 3, 31)
        assert result.last_period == dt.date(2024, 3, 31)
        assert result.direction.direction == Direction.INCREASING

    def test_the_ratio_key_is_carried_through(self):
        result = analyse_ratio_trend("roe", series("0.10", "0.12", "0.14"))
        assert result.ratio_key == "roe"

    def test_empty_history_produces_a_fully_insufficient_result_not_a_crash(self):
        result = analyse_ratio_trend("roe", [])
        assert result.direction.direction == Direction.INSUFFICIENT_HISTORY
        assert result.acceleration.accelerating is None
        assert result.consistency.fraction_same_direction is None
        assert result.first_period is None
