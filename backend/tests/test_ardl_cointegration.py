"""§30 step 2 (partial): ARDL bounds testing — app.domain.ardl_cointegration."""
from __future__ import annotations

import random
from decimal import Decimal

from app.domain.ardl_cointegration import (
    MIN_OBSERVATIONS,
    ardl_bounds_test,
    error_correction_half_life,
)


class TestErrorCorrectionHalfLife:
    def test_matches_section_30s_own_worked_example(self):
        """§30 step 2's own text: "An ECT of -0.28 on monthly data means
        about 28% of the gap closes per month - a half-life of roughly
        2.1 months." Checked directly against the spec's own claimed
        number, not just that the formula runs."""
        result = error_correction_half_life(-0.28)
        assert result is not None
        assert abs(result - Decimal("2.1")) < Decimal("0.05")

    def test_none_for_non_negative_coefficient(self):
        """A coefficient >= 0 implies no mean reversion at all."""
        assert error_correction_half_life(0.0) is None
        assert error_correction_half_life(0.1) is None

    def test_none_for_oscillating_correction(self):
        """A coefficient at or below -1 means the correction overshoots
        each period (deviation flips sign) rather than converging
        monotonically — a real edge case found via a real fitted
        coefficient during this module's own development, not a
        theoretical one: `1 + coefficient` goes to zero or negative,
        making `ln()` undefined."""
        assert error_correction_half_life(-1.0) is None
        assert error_correction_half_life(-1.5) is None
        assert error_correction_half_life(-2.5) is None

    def test_fast_reversion_gives_a_short_half_life(self):
        result = error_correction_half_life(-0.9)
        assert result is not None
        assert result < Decimal("1")


def _cointegrated_pair(n: int, seed: int) -> tuple[list[Decimal], list[Decimal]]:
    """A real, known-cointegrated pair: y = 2x + stationary noise, so y
    and x share a common stochastic trend and any deviation between them
    is mean-reverting."""
    rng = random.Random(seed)
    x_vals = []
    total = 0.0
    for _ in range(n):
        total += rng.gauss(0, 1)
        x_vals.append(total)
    y_vals = [2.0 * x + rng.gauss(0, 0.5) for x in x_vals]
    return [Decimal(str(v)) for v in y_vals], [Decimal(str(v)) for v in x_vals]


def _independent_random_walks(n: int, seed: int) -> tuple[list[Decimal], list[Decimal]]:
    """Two genuinely independent random walks — known NOT cointegrated,
    the classic spurious-regression trap this test exists to catch."""
    rng = random.Random(seed)
    x_vals, y_vals = [], []
    tx, ty = 0.0, 0.0
    for _ in range(n):
        tx += rng.gauss(0, 1)
        ty += rng.gauss(0, 1)
        x_vals.append(tx)
        y_vals.append(ty)
    return [Decimal(str(v)) for v in y_vals], [Decimal(str(v)) for v in x_vals]


class TestArdlBoundsTest:
    def test_none_below_minimum_observations(self):
        y, x = _cointegrated_pair(MIN_OBSERVATIONS - 1, 1)
        assert ardl_bounds_test(y, {"x": x}) is None

    def test_mismatched_lengths_raises(self):
        y, x = _cointegrated_pair(100, 1)
        try:
            ardl_bounds_test(y, {"x": x[:-1]})
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_no_independents_raises(self):
        y, _ = _cointegrated_pair(100, 1)
        try:
            ardl_bounds_test(y, {})
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_correctly_identifies_a_known_cointegrated_pair(self):
        y, x = _cointegrated_pair(300, 42)
        result = ardl_bounds_test(y, {"x": x}, dependent_name="y")
        assert result is not None
        assert result.conclusion == "cointegrated"
        assert result.observation_count == 300
        # A real long-run relationship should produce a real, negative
        # (mean-reverting) ECT coefficient.
        assert result.ect_coefficient is not None
        assert result.ect_coefficient < Decimal("0")
        # A half-life is only reported for monotonic reversion
        # (-1 < coefficient < 0) — an overshooting/oscillating fit
        # (coefficient <= -1, a real possibility on a strongly-fitted
        # synthetic series) correctly reports None instead, per
        # error_correction_half_life's own documented domain.
        if result.ect_coefficient > Decimal("-1"):
            assert result.half_life_periods is not None
            assert result.half_life_periods > Decimal("0")
        else:
            assert result.half_life_periods is None

    def test_correctly_identifies_independent_random_walks_as_not_cointegrated(self):
        y, x = _independent_random_walks(300, 7)
        result = ardl_bounds_test(y, {"x": x}, dependent_name="y")
        assert result is not None
        assert result.conclusion in ("not_cointegrated", "inconclusive")
        # Whichever it is, no cointegrating relationship was established,
        # so there is nothing to report an ECT/half-life for.
        if result.conclusion != "cointegrated":
            assert result.ect_coefficient is None
            assert result.half_life_periods is None

    def test_critical_values_include_the_standard_percentile_bands(self):
        y, x = _cointegrated_pair(300, 42)
        result = ardl_bounds_test(y, {"x": x}, dependent_name="y")
        assert result is not None
        assert "95.0" in result.critical_values
        assert result.critical_values["95.0"]["lower"] < result.critical_values["95.0"]["upper"]
