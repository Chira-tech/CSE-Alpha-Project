"""GET /market/estimator-selection — API-layer wiring for §30 step 2
assembled end to end. Same reasoning as the other §30 step 2 API tests:
catches a Pydantic-serialization bug at the domain-to-API boundary.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.models.macro import MacroSeries

DEPENDENT_ID = "cse.aspi"
INDEPENDENT_ID = "cbsl.tbill_364d"


def _seed(db, series_id: str, values: dict[dt.date, Decimal]):
    db.add_all(
        MacroSeries(series_id=series_id, obs_date=d, first_available_date=d, value=v, source="test")
        for d, v in values.items()
    )
    db.commit()


def test_no_data_returns_200_with_insufficient_data(client):
    r = client.get(
        "/market/estimator-selection",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimator_used"] == "insufficient_data"
    assert body["dependent_consensus"] is None
    assert body["johansen_vecm"] is None
    assert body["ardl_bounds_test"] is None
    assert body["var_differences"] is None


def test_known_cointegrated_i1_pair_selects_johansen_vecm(client, db_session):
    # Seed 1, not 42 — checked directly to reliably give Johansen rank 1
    # through this real DB round-trip (see test_estimator_selection_view.py
    # for the full reasoning; seed 42 gives rank 2 here).
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

    r = client.get(
        "/market/estimator-selection",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dependent_consensus"] == "non_stationary"
    assert body["estimator_used"] == "johansen_vecm"
    assert body["johansen_vecm"] is not None
    assert body["johansen_vecm"]["johansen"]["conclusion"] == "cointegrated"
    assert body["ardl_bounds_test"] is None
    assert body["var_differences"] is None
