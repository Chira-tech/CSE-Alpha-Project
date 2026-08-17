"""§30 step 2's "no cointegration" branch wired to real stored data —
app.domain.var_differences_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.var_differences import MIN_OBSERVATIONS
from app.domain.var_differences_view import var_in_differences_for
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


class TestVarInDifferencesFor:
    def test_no_independent_data_gives_no_result(self, db_session):
        base = dt.date(2026, 1, 1)
        _seed(
            db_session, DEPENDENT_ID,
            {base + dt.timedelta(days=i): Decimal("100") for i in range(60)},
        )
        view = var_in_differences_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
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
        view = var_in_differences_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.result is None
        assert view.aligned_observation_count == 10

    def test_real_short_run_link_recovered_across_cadences(self, db_session):
        """Same real-plumbing proof as the ARDL/Johansen view tests: a
        known short-run-linked pair, with the independent series
        published only weekly and forward-filled, fitted end to end
        through real stored `macro_series` rows."""
        rng = random.Random(11)
        base = dt.date(2025, 1, 1)
        n = 300

        x_dates = [base + dt.timedelta(days=i) for i in range(0, n, 7)]
        x_levels: dict[dt.date, float] = {}
        total = 0.0
        for d in x_dates:
            total += rng.gauss(0, 1)
            x_levels[d] = total
        _seed(db_session, INDEPENDENT_ID, {d: Decimal(str(round(v, 6))) for d, v in x_levels.items()})

        sorted_x_dates = sorted(x_levels)
        y_by_date: dict[dt.date, float] = {}
        idx = 0
        latest_x = None
        prev_x = None
        y_level = 0.0
        for i in range(n):
            d = base + dt.timedelta(days=i)
            while idx < len(sorted_x_dates) and sorted_x_dates[idx] <= d:
                prev_x = latest_x
                latest_x = x_levels[sorted_x_dates[idx]]
                idx += 1
            if latest_x is not None:
                x_diff = 0.0 if prev_x is None else latest_x - prev_x
                y_level += 0.5 * x_diff + rng.gauss(0, 0.3)
                y_by_date[d] = y_level
        _seed(db_session, DEPENDENT_ID, {d: Decimal(str(round(v, 6))) for d, v in y_by_date.items()})

        view = var_in_differences_for(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert view.aligned_observation_count >= MIN_OBSERVATIONS
        assert view.result is not None
