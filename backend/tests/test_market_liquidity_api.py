"""GET /market/liquidity — API-layer wiring for real Amihud illiquidity.
Same reasoning as the other §30 API tests: catches a Pydantic-
serialization bug at the domain-to-API boundary.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.liquidity import MIN_OBSERVATIONS
from app.models.prices import PriceDaily
from app.models.securities import Security


def _seed_ticker(db, ticker: str, closes: list[Decimal], volumes: list[int], base: dt.date):
    now = dt.datetime.now(dt.timezone.utc)
    db.add(Security(ticker=ticker, name=ticker))
    db.add_all(
        PriceDaily(
            ticker=ticker, date=base + dt.timedelta(days=i), close=c,
            volume=v, adj_factor=Decimal("1"), fetched_at=now,
        )
        for i, (c, v) in enumerate(zip(closes, volumes))
    )
    db.commit()


def test_unknown_ticker_returns_200_with_honest_nulls(client):
    r = client.get("/market/liquidity", params={"ticker": "NOPE.N0000"})
    assert r.status_code == 200
    body = r.json()
    assert body["amihud_ratio"] is None
    assert body["liquidity_percentile"] is None
    assert body["implied_ke_illiquidity_premium"] is None


def test_a_real_liquid_ticker_gets_a_real_result(client, db_session):
    n = MIN_OBSERVATIONS + 5
    base = dt.date(2026, 1, 1)
    closes = [Decimal(100) * (Decimal("1.001") ** i) for i in range(n)]
    volumes = [5_000_000] * n
    _seed_ticker(db_session, "LIQUID.N0000", closes, volumes, base)

    thin_closes = [Decimal(100) * (Decimal("1.05") ** i) for i in range(n)]
    thin_volumes = [50] * n
    _seed_ticker(db_session, "THIN.N0000", thin_closes, thin_volumes, base)

    r = client.get("/market/liquidity", params={"ticker": "LIQUID.N0000"})
    assert r.status_code == 200
    body = r.json()
    assert body["universe_size"] == 2
    assert body["amihud_ratio"] is not None
    assert body["liquidity_percentile"] == "100"
    assert body["implied_ke_illiquidity_premium"] == "0"
