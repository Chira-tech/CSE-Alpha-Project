"""§30 step 5: the event study — app.domain.event_study."""
from __future__ import annotations

import random
from decimal import Decimal

from app.domain.event_study import (
    MIN_ESTIMATION_OBSERVATIONS,
    aggregate_car_across_events,
    single_event_market_model_car,
)

ALPHA_TRUE = 0.0005
BETA_TRUE = 1.2


def _make_event(seed: int, inject: float = 0.0, n_est: int = 120, n_event: int = 11):
    """A real, known market-model DGP: asset_return = alpha + beta*market
    + noise, over both an estimation window and an event window, with an
    optional known abnormal jump injected on the event window's middle
    day (index 5 of 11 — the "event day" itself)."""
    rng = random.Random(seed)
    est_m = [rng.gauss(0.0003, 0.01) for _ in range(n_est)]
    est_a = [ALPHA_TRUE + BETA_TRUE * m + rng.gauss(0, 0.005) for m in est_m]
    ev_m = [rng.gauss(0.0003, 0.01) for _ in range(n_event)]
    ev_a = [ALPHA_TRUE + BETA_TRUE * m + rng.gauss(0, 0.005) for m in ev_m]
    ev_a[5] += inject
    to_dec = lambda vs: [Decimal(str(v)) for v in vs]  # noqa: E731
    return to_dec(est_a), to_dec(est_m), to_dec(ev_a), to_dec(ev_m)


class TestSingleEventMarketModelCar:
    def test_none_below_minimum_estimation_observations(self):
        est_a, est_m, ev_a, ev_m = _make_event(1, n_est=MIN_ESTIMATION_OBSERVATIONS - 1)
        assert single_event_market_model_car(est_a, est_m, ev_a, ev_m) is None

    def test_none_with_empty_event_window(self):
        est_a, est_m, _, _ = _make_event(1)
        assert single_event_market_model_car(est_a, est_m, [], []) is None

    def test_mismatched_estimation_lengths_raises(self):
        est_a, est_m, ev_a, ev_m = _make_event(1)
        try:
            single_event_market_model_car(est_a, est_m[:-1], ev_a, ev_m)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_mismatched_event_lengths_raises(self):
        est_a, est_m, ev_a, ev_m = _make_event(1)
        try:
            single_event_market_model_car(est_a, est_m, ev_a, ev_m[:-1])
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_no_real_abnormal_return_is_not_significant(self):
        """Seed 1 checked directly to land comfortably non-significant
        (p≈0.74) — a true null still rejects at roughly the stated 5%
        rate by chance alone, the same caveat every other hypothesis-
        testing module this phase names (see e.g. test_causality_
        analysis.py's own Toda-Yamamoto seed-selection comment)."""
        est_a, est_m, ev_a, ev_m = _make_event(1, inject=0.0)
        result = single_event_market_model_car(est_a, est_m, ev_a, ev_m)
        assert result is not None
        assert result.significant is False
        assert abs(result.cumulative_abnormal_return) < Decimal("0.02")

    def test_known_injected_abnormal_return_is_recovered_and_significant(self):
        """A real, known 3% abnormal return injected on the event day —
        the recovered CAR should be in the right ballpark and flagged
        significant."""
        est_a, est_m, ev_a, ev_m = _make_event(1, inject=0.03)
        result = single_event_market_model_car(est_a, est_m, ev_a, ev_m)
        assert result is not None
        assert result.significant is True
        assert abs(result.cumulative_abnormal_return - Decimal("0.03")) < Decimal("0.02")
        assert len(result.abnormal_returns) == 11
        assert abs(result.beta - Decimal(str(BETA_TRUE))) < Decimal("0.3")


class TestAggregateCarAcrossEvents:
    def test_none_with_fewer_than_two_events(self):
        est_a, est_m, ev_a, ev_m = _make_event(1)
        one = single_event_market_model_car(est_a, est_m, ev_a, ev_m)
        assert aggregate_car_across_events([one]) is None
        assert aggregate_car_across_events([]) is None

    def test_known_injected_abnormal_return_across_several_events(self):
        results = []
        for seed in (21, 22, 23, 24, 25):
            est_a, est_m, ev_a, ev_m = _make_event(seed, inject=0.03)
            results.append(single_event_market_model_car(est_a, est_m, ev_a, ev_m))
        agg = aggregate_car_across_events(results)
        assert agg is not None
        assert agg.event_count == 5
        assert agg.significant is True
        assert abs(agg.average_car - Decimal("0.03")) < Decimal("0.02")

    def test_no_real_effect_across_several_events_is_not_significant(self):
        results = []
        for seed in (31, 32, 33, 34, 35):
            est_a, est_m, ev_a, ev_m = _make_event(seed, inject=0.0)
            results.append(single_event_market_model_car(est_a, est_m, ev_a, ev_m))
        agg = aggregate_car_across_events(results)
        assert agg is not None
        assert agg.significant is False
