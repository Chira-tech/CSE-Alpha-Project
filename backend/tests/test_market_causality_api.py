"""GET /market/impulse-response-fevd and GET /market/toda-yamamoto —
API-layer wiring for §30 step 3. Same reasoning as the other §30
API tests: catches a Pydantic-serialization bug at the domain-to-API
boundary.
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


def _seed_known_cointegrated_pair(db, seed: int = 1, n: int = 300):
    """Seed 1: verified to reliably give Johansen rank 1 through this
    real DB round-trip — see test_estimator_selection_view.py."""
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


def test_impulse_response_fevd_no_data_returns_200_with_honest_nulls(client):
    r = client.get(
        "/market/impulse-response-fevd",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimator_used"] is None
    assert body["result"] is None


def test_impulse_response_fevd_known_cointegrated_pair_returns_a_real_result(client, db_session):
    _seed_known_cointegrated_pair(db_session)
    r = client.get(
        "/market/impulse-response-fevd",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimator_used"] == "johansen_vecm"
    assert body["result"] is not None
    assert body["result"]["estimator"] == "johansen_vecm"
    assert len(body["result"]["irf_dependent_to_independent_shock"]) == body["result"]["periods"] + 1


def test_toda_yamamoto_no_data_returns_200_with_honest_nulls(client):
    r = client.get(
        "/market/toda-yamamoto",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is None
    assert body["dependent_consensus"] is None


def test_toda_yamamoto_known_i1_pair_returns_a_real_result(client, db_session):
    _seed_known_cointegrated_pair(db_session)
    r = client.get(
        "/market/toda-yamamoto",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dependent_consensus"] == "non_stationary"
    assert body["result"] is not None
    assert body["result"]["integration_order_augmentation"] == 1
    assert "wald_statistic" in body["result"]["independent_causes_dependent"]
