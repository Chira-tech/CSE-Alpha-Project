"""§30 step 2, the "no cointegration" branch: app.domain.var_differences."""
from __future__ import annotations

import random
from decimal import Decimal

from app.domain.var_differences import MIN_OBSERVATIONS, fit_var_in_differences


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


def _walk_with_a_real_lagged_short_run_link(n: int, seed: int) -> tuple[list[Decimal], list[Decimal]]:
    """x is a random walk; y's own DIFFERENCE responds to x's own
    lagged difference (a real, known short-run relationship with no
    long-run cointegration between the levels — the exact case this
    branch exists for)."""
    rng = random.Random(seed)
    x_levels = [0.0]
    for _ in range(n - 1):
        x_levels.append(x_levels[-1] + rng.gauss(0, 1))
    x_diffs = [x_levels[i] - x_levels[i - 1] for i in range(1, n)]

    y_levels = [0.0]
    prev_y_diff = 0.0
    for i in range(1, n):
        x_lag1 = x_diffs[i - 2] if i >= 2 else 0.0
        y_diff = 0.5 * x_lag1 + rng.gauss(0, 0.3)
        y_levels.append(y_levels[-1] + y_diff)
    return [Decimal(str(v)) for v in y_levels], [Decimal(str(v)) for v in x_levels]


class TestFitVarInDifferences:
    def test_none_below_minimum_observations(self):
        y, x = _independent_random_walks(MIN_OBSERVATIONS - 1, 1)
        assert fit_var_in_differences(y, x) is None

    def test_mismatched_lengths_raises(self):
        y, x = _independent_random_walks(100, 1)
        try:
            fit_var_in_differences(y, x[:-1])
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_observation_count_is_one_less_than_the_level_series(self):
        y, x = _independent_random_walks(200, 3)
        result = fit_var_in_differences(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.observation_count == 199

    def test_recovers_a_known_real_short_run_lagged_relationship(self):
        y, x = _walk_with_a_real_lagged_short_run_link(300, 11)
        result = fit_var_in_differences(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        # True coefficient is 0.5 — a real fit on 300 real observations
        # should recover something reasonably close, not exact.
        assert abs(result.dependent_on_independent_lag1_coefficient - Decimal("0.5")) < Decimal("0.2")
        assert result.significant is True
        assert result.lags == 2

    def test_no_relationship_between_independent_walks_is_not_significant(self):
        y, x = _independent_random_walks(300, 7)
        result = fit_var_in_differences(y, x, dependent_name="y", independent_name="x")
        assert result is not None
        assert result.significant is False
