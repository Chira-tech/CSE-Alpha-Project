"""GET /market/var-differences — API-layer wiring for §30 step 2's "no
cointegration" branch. Same reasoning as the ARDL/Johansen API tests:
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


def test_no_data_returns_200_with_honest_nulls(client):
    r = client.get(
        "/market/var-differences",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["aligned_observation_count"] == 0
    assert body["result"] is None
    assert len(body["warnings"]) >= 1


def test_real_data_returns_a_real_result(client, db_session):
    rng = random.Random(11)
    base = dt.date(2025, 1, 1)
    n = 300
    x_levels: dict[dt.date, Decimal] = {}
    total = 0.0
    for i in range(n):
        total += rng.gauss(0, 1)
        x_levels[base + dt.timedelta(days=i)] = Decimal(str(round(total, 6)))
    _seed(db_session, INDEPENDENT_ID, x_levels)

    y_level = 0.0
    y_levels: dict[dt.date, Decimal] = {}
    prev = None
    for i, (d, v) in enumerate(sorted(x_levels.items())):
        cur = float(v)
        x_diff = 0.0 if prev is None else cur - prev
        y_level += 0.5 * x_diff + rng.gauss(0, 0.3)
        y_levels[d] = Decimal(str(round(y_level, 6)))
        prev = cur
    _seed(db_session, DEPENDENT_ID, y_levels)

    r = client.get(
        "/market/var-differences",
        params={"dependent_series_id": DEPENDENT_ID, "independent_series_id": INDEPENDENT_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["aligned_observation_count"] == n
    assert body["result"] is not None
    assert body["result"]["lags"] == 2
    assert "dependent_on_independent_lag1_coefficient" in body["result"]
