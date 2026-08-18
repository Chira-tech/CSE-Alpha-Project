"""§30 step 2 assembled end to end — app.domain.estimator_selection_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.estimator_selection_view import select_and_fit_estimator
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


class TestSelectAndFitEstimator:
    def test_no_data_at_all_is_insufficient_data(self, db_session):
        result = select_and_fit_estimator(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert result.estimator_used == "insufficient_data"
        assert result.dependent_consensus is None
        assert result.independent_consensus is None

    def test_known_cointegrated_i1_pair_selects_johansen_vecm(self, db_session):
        """Two real random-walk-shaped I(1) series with a genuine
        cointegrating relationship — §30 step 2's "all I(1)" case,
        routed all the way through to a real VECM fit. Seed 1, not 42:
        checked directly to reliably give Johansen rank 1 through this
        real DB round-trip — seed 42 gives rank 2 here (spuriously "both
        series individually stationary," which `fit_vecm` itself
        correctly refuses to fit a VECM against), a real floating-point
        sensitivity near Johansen's own rank-selection boundary."""
        rng = random.Random(1)
        base = dt.date(2025, 1, 1)
        n = 300
        x_total = 0.0
        dependent_values: dict[dt.date, Decimal] = {}
        independent_values: dict[dt.date, Decimal] = {}
        for i in range(n):
            x_total += rng.gauss(0, 1)
            d = base + dt.timedelta(days=i)
            independent_values[d] = Decimal(str(round(x_total, 6)))
            dependent_values[d] = Decimal(str(round(2.0 * x_total + rng.gauss(0, 0.5), 6)))
        _seed(db_session, DEPENDENT_ID, dependent_values)
        _seed(db_session, INDEPENDENT_ID, independent_values)

        result = select_and_fit_estimator(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert result.dependent_consensus == "non_stationary"
        assert result.independent_consensus == "non_stationary"
        assert result.initial_choice == "johansen_vecm"
        assert result.estimator_used == "johansen_vecm"
        assert result.johansen_vecm is not None
        assert result.johansen_vecm.result is not None
        assert result.johansen_vecm.result.johansen.conclusion == "cointegrated"
        assert result.var_differences is None

    def test_independent_random_walks_fall_back_to_var_differences(self, db_session):
        """Two real I(1) series with NO real cointegrating relationship
        — Johansen is attempted (both series non-stationary), finds
        nothing, and this module falls back to VAR-in-differences per
        §30 step 2's own "no cointegration" branch."""
        rng = random.Random(7)
        base = dt.date(2025, 1, 1)
        n = 300
        tx, ty = 0.0, 0.0
        dependent_values: dict[dt.date, Decimal] = {}
        independent_values: dict[dt.date, Decimal] = {}
        for i in range(n):
            tx += rng.gauss(0, 1)
            ty += rng.gauss(0, 1)
            d = base + dt.timedelta(days=i)
            independent_values[d] = Decimal(str(round(tx, 6)))
            dependent_values[d] = Decimal(str(round(ty, 6)))
        _seed(db_session, DEPENDENT_ID, dependent_values)
        _seed(db_session, INDEPENDENT_ID, independent_values)

        result = select_and_fit_estimator(db_session, DEPENDENT_ID, INDEPENDENT_ID, AS_OF)
        assert result.dependent_consensus == "non_stationary"
        assert result.independent_consensus == "non_stationary"
        assert result.initial_choice == "johansen_vecm"
        assert result.estimator_used == "var_differences"
        assert result.johansen_vecm is not None
        assert result.var_differences is not None
        assert "no real, usable cointegrating relationship" in result.reason
