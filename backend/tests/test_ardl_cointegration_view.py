"""§30 step 2 (partial) wired to real stored data — app.domain.ardl_cointegration_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.ardl_cointegration import MIN_OBSERVATIONS
from app.domain.ardl_cointegration_view import ardl_bounds_test_for
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


class TestArdlBoundsTestFor:
    def test_no_independent_series_gives_no_result(self, db_session):
        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [], AS_OF)
        assert view.result is None
        assert any("No independent series" in w for w in view.warnings)

    def test_no_dependent_data_gives_no_result(self, db_session):
        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [INDEPENDENT_ID], AS_OF)
        assert view.result is None
        assert view.aligned_observation_count == 0

    def test_independent_series_entirely_missing_is_named(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(60)},
        )
        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [INDEPENDENT_ID], AS_OF)
        assert view.result is None
        assert any(f"No real observations of {INDEPENDENT_ID!r}" in w for w in view.warnings)

    def test_independent_observations_starting_after_dependent_ends_give_no_aligned_rows(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(60)},
        )
        # Independent series only begins well after the dependent series'
        # last observation — nothing to forward-fill onto any dependent date.
        _seed(
            db_session, INDEPENDENT_ID,
            {base + dt.timedelta(days=1000): Decimal("10")},
        )
        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [INDEPENDENT_ID], AS_OF)
        assert view.result is None
        assert view.aligned_observation_count == 0

    def test_forward_fill_aligns_a_daily_series_onto_a_weekly_one(self, db_session):
        """The dependent series is seeded daily; the independent series
        only weekly (a real T-bill-yield-style cadence) — every dependent
        date from the independent series' own first observation onward
        should still get a forward-filled value, per this module's own
        documented alignment rule."""
        base = dt.date(2025, 1, 1)
        n = 300
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(n)},
        )
        _seed(
            db_session, INDEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("10") for i in range(0, n, 7)},
        )
        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [INDEPENDENT_ID], AS_OF)
        assert view.aligned_observation_count == n

    def test_correctly_identifies_a_known_cointegrated_relationship_across_cadences(self, db_session):
        """A real, known-cointegrated pair (y = 2x + stationary noise),
        with x published only weekly and forward-filled the same way a
        real T-bill yield would be — end to end through real stored
        `macro_series` rows, real alignment, and the real bounds test,
        not a synthetic in-memory list like test_ardl_cointegration.py's
        own equivalent (that module's job; this one's job is proving the
        real plumbing gets a real known answer right)."""
        rng = random.Random(99)
        base = dt.date(2025, 1, 1)
        n = 300
        x_total = 0.0
        x_by_date: dict[dt.date, float] = {}
        for i in range(0, n, 7):
            x_total += rng.gauss(0, 1)
            x_by_date[base + dt.timedelta(days=i)] = x_total

        independent_values = {d: Decimal(str(round(v, 6))) for d, v in x_by_date.items()}
        _seed(db_session, INDEPENDENT_ID, independent_values)

        # Forward-fill x onto every day for the dependent series' own
        # noisy y = 2x + noise construction, matching what the view layer
        # itself will independently recompute.
        sorted_x_dates = sorted(x_by_date)
        dependent_values: dict[dt.date, Decimal] = {}
        idx = 0
        latest_x = None
        for i in range(n):
            d = base + dt.timedelta(days=i)
            while idx < len(sorted_x_dates) and sorted_x_dates[idx] <= d:
                latest_x = x_by_date[sorted_x_dates[idx]]
                idx += 1
            if latest_x is not None:
                y = 2.0 * latest_x + rng.gauss(0, 0.5)
                dependent_values[d] = Decimal(str(round(y, 6)))
        _seed(db_session, DEPENDENT_ID, dependent_values)

        view = ardl_bounds_test_for(db_session, DEPENDENT_ID, [INDEPENDENT_ID], AS_OF)
        assert view.aligned_observation_count >= MIN_OBSERVATIONS
        assert view.result is not None
        assert view.result.conclusion == "cointegrated"
