"""GET /market/event-study — API-layer wiring for §30 step 5. Same
reasoning as the other §30 API tests: catches a Pydantic-serialization
bug at the domain-to-API boundary.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.models.macro import MacroSeries
from app.models.prices import PriceDaily

TICKER = "COMB.N0000"


def _weekdays(start: dt.date, n: int) -> list[dt.date]:
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += dt.timedelta(days=1)
    return dates


def test_no_data_returns_200_with_honest_empty_state(client):
    r = client.get("/market/event-study", params={"ticker": TICKER})
    assert r.status_code == 200
    body = r.json()
    assert body["events"] == []
    assert body["aggregate"] is None


def test_unsupported_event_type_returns_422(client):
    r = client.get(
        "/market/event-study", params={"ticker": TICKER, "event_type": "ccpi_release"}
    )
    assert r.status_code == 422


def test_known_injected_reaction_returns_a_real_result(client, db_session):
    rng = random.Random(1)
    n = 200
    dates = _weekdays(dt.date(2025, 10, 1), n)
    alpha, beta = 0.0003, 1.1
    market_returns = {d: rng.gauss(0.0003, 0.01) for d in dates}
    asset_returns = {d: alpha + beta * market_returns[d] + rng.gauss(0, 0.004) for d in dates}
    event_date = dates[150]
    asset_returns[event_date] += 0.04

    now = dt.datetime.now(dt.timezone.utc)
    price = 100.0
    price_rows = []
    for d in dates:
        price *= 1 + asset_returns[d]
        price_rows.append(
            PriceDaily(ticker=TICKER, date=d, close=Decimal(str(round(price, 4))), adj_factor=Decimal("1"), fetched_at=now)
        )
    db_session.add_all(price_rows)

    level = 10000.0
    aspi_rows = []
    for d in dates:
        level *= 1 + market_returns[d]
        aspi_rows.append(
            MacroSeries(series_id="cse.aspi", obs_date=d, first_available_date=d, value=Decimal(str(round(level, 4))), source="test")
        )
    db_session.add_all(aspi_rows)
    db_session.add_all([
        MacroSeries(series_id="cbsl.policy_rate", obs_date=dates[0], first_available_date=dates[0], value=Decimal("9.0"), source="test"),
        MacroSeries(series_id="cbsl.policy_rate", obs_date=event_date, first_available_date=event_date, value=Decimal("9.25"), source="test"),
    ])
    db_session.commit()

    r = client.get("/market/event-study", params={"ticker": TICKER})
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["result"] is not None
    assert body["events"][0]["result"]["significant"] is True
