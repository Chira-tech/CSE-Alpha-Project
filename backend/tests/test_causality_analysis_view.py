"""§30 step 3 wired to real stored data — app.domain.causality_analysis_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.causality_analysis import MIN_OBSERVATIONS
from app.domain.causality_analysis_view import impulse_response_fevd_for, toda_yamamoto_for
from app.models.macro import MacroSeries

DEPENDENT_ID = "cse.aspi"
INDEPENDENT_ID = "cbsl.tbill_364d"
AS_OF = dt.date(2026, 8, 18)


def _seed(db, series_id: str, values: dict[dt.date, Decimal]):
    db.add_all(
        MacroSeries(series_id=series_id, obs_date=d, first_available_date=d, value=v, source="test")
        for d, v in values.items()
    )
    db.commit()


def _seed_known_cointegrated_pair(db, seed: int = 1, n: int = 300):
    """Seed 1, not 42: checked directly against the real DB round-trip
    (rounded-to-6-decimal-places storage, exactly as `app.domain.macro_
    view.series_history` returns it) to reliably give Johansen rank 1 —
    seed 42 gives rank 2 through this exact real pipeline (spuriously
    "both series individually stationary," which `app.domain.johansen_
    vecm.fit_vecm` itself correctly refuses to fit a VECM against) even
    though it gives rank 1 in `test_johansen_vecm.py`'s own pure,
    unrounded in-memory construction — real floating-point sensitivity
    near Johansen's own rank-selection boundary, not a bug in either
    test, but a reason to verify a synthetic seed against the ACTUAL
    path a test exercises rather than assume it carries over."""
    rng = random.Random(seed)
    base = dt.date(2025, 1, 1)
    x_total = 0.0
    dependent_values: dict[dt.date, Decimal] = {}
    independent_values: dict[dt.date, Decimal] = {}
    for i in range(n):
        x_total += rng.gauss(0, 1)
        d = base + dt.timedelta(days=i)
        independent_values[d] = Decimal(str(round(x_total, 6)))
        dependent_values[d] = Decimal(str(round(2.0 * x_total + rng.gauss(0, 0.5), 6)))
    _seed(db, DEPENDENT_ID, dependent_values)
    _seed(db, INDEPENDENT_ID, independent_values)


def _seed_independent_walks(db, seed: int = 7, n: int = 300):
    rng = random.Random(seed)
    base = dt.date(2025, 1, 1)
    tx, ty = 0.0, 0.0
    dependent_values: dict[dt.date, Decimal] = {}
    independent_values: dict[dt.date, Decimal] = {}
    for i in range(n):
        tx += rng.gauss(0, 1)
        ty += rng.gauss(0, 1)
        d = base + dt.timedelta(days=i)
        independent_values[d] = Decimal(str(round(tx, 6)))
        dependent_values[d] = Decimal(str(round(ty, 6)))
    _seed(db, DEPENDENT_ID, dependent_values)
    _seed(db, INDEPENDENT_ID, independent_values)


class TestImpulseResponseFevdFor:
    def test_no_data_gives_no_result(self, db_session):
        view = impulse_response_fevd_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.result is None
        assert view.estimator_used is None

    def test_known_cointegrated_pair_uses_johansen_vecm(self, db_session):
        _seed_known_cointegrated_pair(db_session)
        view = impulse_response_fevd_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.estimator_used == "johansen_vecm"
        assert view.result is not None
        assert view.result.estimator == "johansen_vecm"
        assert view.aligned_observation_count >= MIN_OBSERVATIONS

    def test_independent_walks_fall_back_to_var_differences(self, db_session):
        _seed_independent_walks(db_session)
        view = impulse_response_fevd_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.estimator_used == "var_differences"
        assert view.result is not None
        assert view.result.estimator == "var_differences"


class TestTodaYamamotoFor:
    def test_no_data_gives_no_result(self, db_session):
        view = toda_yamamoto_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.result is None
        assert view.dependent_consensus is None

    def test_known_cointegrated_i1_pair_runs_the_real_test(self, db_session):
        """Both series here are I(1) (a real, live-derived stationarity
        read), so the view should correctly size augmentation=1 and
        produce a real result — not necessarily a specific causal
        direction (this DGP has no true causal asymmetry, only a
        contemporaneous relationship), just a genuine, non-None result."""
        _seed_known_cointegrated_pair(db_session)
        view = toda_yamamoto_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.dependent_consensus == "non_stationary"
        assert view.independent_consensus == "non_stationary"
        assert view.result is not None
        assert view.result.integration_order_augmentation == 1
