"""§30 step 1 wired to real stored data — app.domain.stationarity_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.stationarity_view import stationarity_for_series
from app.models.macro import MacroSeries

SERIES_ID = "cbsl.tbill_364d"
AS_OF = dt.date(2026, 8, 18)


def _seed_series(db, values: dict[dt.date, Decimal], series_id: str = SERIES_ID):
    db.add_all(
        MacroSeries(series_id=series_id, obs_date=d, first_available_date=d, value=v, source="cbsl")
        for d, v in values.items()
    )
    db.commit()


class TestStationarityForSeries:
    def test_no_data_gives_no_assessment(self, db_session):
        view = stationarity_for_series(db_session, SERIES_ID, AS_OF)
        assert view.assessment is None
        assert view.observation_count == 0
        assert any("Only 0 real observations" in w for w in view.warnings)

    def test_too_few_observations_gives_no_assessment(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed_series(db_session, {base + dt.timedelta(days=i): Decimal("0.10") for i in range(10)})
        view = stationarity_for_series(db_session, SERIES_ID, AS_OF)
        assert view.assessment is None
        assert view.observation_count == 10

    def test_real_random_walk_shaped_series_is_assessed_as_non_stationary(self, db_session):
        """A T-bill yield that drifts like a real interest rate series
        typically does (persistent, slow-moving) — a random-walk shape,
        the same known-non-stationary construction test_stationarity.py
        itself validates each test against."""
        rng = random.Random(11)
        base = dt.date(2025, 1, 1)
        level = 0.10
        values = {}
        for i in range(200):
            level += rng.gauss(0, 0.001)
            values[base + dt.timedelta(days=i)] = Decimal(str(round(level, 6)))
        _seed_series(db_session, values)

        view = stationarity_for_series(db_session, SERIES_ID, AS_OF)
        assert view.assessment is not None
        assert view.observation_count == 200
        assert view.assessment.consensus in ("non_stationary", "mixed_evidence")
