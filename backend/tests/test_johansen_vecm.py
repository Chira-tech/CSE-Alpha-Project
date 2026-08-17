"""§30 step 2, the "all I(1)" branch: app.domain.johansen_vecm."""
from __future__ import annotations

import random
from decimal import Decimal

from app.domain.johansen_vecm import (
    MIN_OBSERVATIONS,
    fit_vecm,
    johansen_cointegration_test,
)


def _cointegrated_pair(n: int, seed: int) -> tuple[list[Decimal], list[Decimal]]:
    """The same known-cointegrated construction test_ardl_cointegration.py
    uses: y = 2x + stationary noise."""
    rng = random.Random(seed)
    x_vals = []
    total = 0.0
    for _ in range(n):
        total += rng.gauss(0, 1)
        x_vals.append(total)
    y_vals = [2.0 * x + rng.gauss(0, 0.5) for x in x_vals]
    return [Decimal(str(v)) for v in y_vals], [Decimal(str(v)) for v in x_vals]


def _independent_random_walks(n: int, seed: int) -> tuple[list[Decimal], list[Decimal]]:
    rng = random.Random(seed)
    x_vals, y_vals = [], []
    tx, ty = 0.0, 0.0
    for _ in range(n):
        tx += rng.gauss(0, 1)
        ty += rng.gauss(0, 1)
        x_vals.append(tx)
        y_vals.append(ty)
    return [Decimal(str(v)) for v in y_vals], [Decimal(str(v)) for v in x_vals]


class TestJohansenCointegrationTest:
    def test_none_below_minimum_observations(self):
        y, x = _cointegrated_pair(MIN_OBSERVATIONS - 1, 1)
        assert johansen_cointegration_test(y, x) is None

    def test_mismatched_lengths_raises(self):
        y, x = _cointegrated_pair(100, 1)
        try:
            johansen_cointegration_test(y, x[:-1])
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_correctly_identifies_a_known_cointegrated_pair(self):
        y, x = _cointegrated_pair(300, 42)
        result = johansen_cointegration_test(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.conclusion == "cointegrated"
        assert result.selected_rank == 1
        assert result.observation_count == 300

    def test_correctly_identifies_independent_random_walks_as_not_cointegrated(self):
        y, x = _independent_random_walks(300, 7)
        result = johansen_cointegration_test(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.conclusion == "not_cointegrated"
        assert result.selected_rank == 0

    def test_critical_values_include_the_standard_percentile_bands(self):
        y, x = _cointegrated_pair(300, 42)
        result = johansen_cointegration_test(y, x)
        assert result is not None
        assert result.trace_critical_values
        assert "95.0" in result.trace_critical_values[0]


class TestFitVecm:
    def test_none_below_minimum_observations(self):
        y, x = _cointegrated_pair(MIN_OBSERVATIONS - 1, 1)
        assert fit_vecm(y, x) is None

    def test_known_cointegrated_pair_produces_a_real_negative_alpha_and_a_recovered_beta(self):
        """The known DGP is y = 2x + noise, so the fitted cointegrating
        vector should recover something close to beta=2, and the
        dependent series' own alpha should be negative (mean-reverting)."""
        y, x = _cointegrated_pair(300, 42)
        result = fit_vecm(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.johansen.conclusion == "cointegrated"
        assert result.alpha_dependent is not None
        assert result.alpha_dependent < Decimal("0")
        assert result.beta is not None
        assert abs(result.beta - Decimal("2")) < Decimal("0.5")
        if result.alpha_dependent > Decimal("-1"):
            assert result.half_life_periods is not None
            assert result.half_life_periods > Decimal("0")
        else:
            assert result.half_life_periods is None

    def test_independent_random_walks_give_no_fit(self):
        y, x = _independent_random_walks(300, 7)
        result = fit_vecm(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.johansen.conclusion == "not_cointegrated"
        assert result.alpha_dependent is None
        assert result.alpha_independent is None
        assert result.beta is None
        assert result.half_life_periods is None
        assert "No cointegrating relationship" in result.note
