"""GET /market/johansen-vecm — API-layer wiring for §30 step 2's "all
I(1)" branch. Same reasoning as test_market_cointegration_api.py: catches
a Pydantic-serialization bug at the domain-to-API boundary (the nested
`trace_critical_values` list-of-dicts shape in particular).
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


def test_no_data_returns_200_with_honest_nulls(client):
    r = client.get(
        "/market/johansen-vecm",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["aligned_observation_count"] == 0
    assert body["result"] is None
    assert len(body["warnings"]) >= 1


def test_known_cointegrated_relationship_returns_a_real_result(client, db_session):
    rng = random.Random(123)
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
        "/market/johansen-vecm",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["aligned_observation_count"] == n
    assert body["result"] is not None
    assert body["result"]["johansen"]["conclusion"] == "cointegrated"
    assert body["result"]["alpha_dependent"] is not None
    assert Decimal(body["result"]["alpha_dependent"]) < Decimal("0")
    assert "95.0" in body["result"]["johansen"]["trace_critical_values"][0]
