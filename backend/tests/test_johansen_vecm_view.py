"""§30 step 2's "all I(1)" branch wired to real stored data —
app.domain.johansen_vecm_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.johansen_vecm import MIN_OBSERVATIONS
from app.domain.johansen_vecm_view import johansen_vecm_for
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


class TestJohansenVecmFor:
    def test_no_independent_data_gives_no_result(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(60)},
        )
        view = johansen_vecm_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.result is None
        assert any(f"No real observations of {INDEPENDENT_ID!r}" in w for w in view.warnings)

    def test_too_few_aligned_observations_gives_no_result(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(10)},
        )
        _seed(
            db_session, INDEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("10") for i in range(10)},
        )
        view = johansen_vecm_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.result is None
        assert view.aligned_observation_count == 10

    def test_correctly_identifies_a_known_cointegrated_relationship_across_cadences(self, db_session):
        """Same real-plumbing proof as test_ardl_cointegration_view.py's
        own equivalent: a known-cointegrated pair, with the independent
        series published only weekly and forward-filled, fitted end to
        end through real stored `macro_series` rows."""
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

        view = johansen_vecm_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.aligned_observation_count >= MIN_OBSERVATIONS
        assert view.result is not None
        assert view.result.johansen.conclusion == "cointegrated"
        assert view.result.alpha_dependent is not None
        assert view.result.alpha_dependent < Decimal("0")
