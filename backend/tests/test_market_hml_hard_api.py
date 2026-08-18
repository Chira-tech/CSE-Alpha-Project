"""GET /market/factors/hml-hard — API-layer wiring for §35's HML_hard
factor. Same reasoning as the other §30/§35 API tests: catches a
Pydantic-serialization bug at the domain-to-API boundary (the nested
`excluded` list-of-pairs shape and the `portfolio_returns`/`portfolio_
counts` dicts in particular).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.factor_library_view import DEFAULT_LOOKBACK_DAYS
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date.today()
PERIOD_END = dt.date(2025, 12, 31)
FIRST_AVAILABLE = dt.date(2026, 3, 1)


def _seed_full_ticker(db, ticker, *, shares, total_equity, start_price, end_price):
    now = dt.datetime.now(dt.timezone.utc)
    formation = AS_OF - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)
    db.add(Security(ticker=ticker, name=ticker))
    db.add(FloatData(ticker=ticker, as_of=dt.date(2026, 1, 1), shares_issued=shares))
    db.add(Fundamental(
        ticker=ticker, period_end=PERIOD_END, period_type="annual",
        first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
        value=total_equity, provenance_tier=ProvenanceTier.REPORTED,
    ))
    db.add(PriceDaily(ticker=ticker, date=formation, close=start_price, adj_factor=Decimal("1"), fetched_at=now))
    db.add(PriceDaily(ticker=ticker, date=AS_OF, close=end_price, adj_factor=Decimal("1"), fetched_at=now))
    db.commit()


def test_no_data_returns_200_with_honest_empty_state(client):
    r = client.get("/market/factors/hml-hard")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is None
    assert body["included_ticker_count"] == 0


def test_a_full_real_universe_returns_a_real_result(client, db_session):
    style_ratios = [
        Decimal("0.03"), Decimal("0.06"), Decimal("0.28"), Decimal("0.33"),
        Decimal("0.58"), Decimal("0.63"),
    ]
    for i in range(12):
        small = i < 6
        shares = (10_000 + i) if small else (10_000_000 + i)
        price = Decimal("100")
        cap = Decimal(shares) * price
        total_equity = style_ratios[i % 6] * cap
        end_price = price * (Decimal("1.1") if i % 3 == 0 else Decimal("1.02"))
        _seed_full_ticker(
            db_session, f"T{i}.N0000", shares=shares, total_equity=total_equity,
            start_price=price, end_price=end_price,
        )

    r = client.get("/market/factors/hml-hard")
    assert r.status_code == 200
    body = r.json()
    assert body["included_ticker_count"] == 12
    assert body["excluded"] == []
    assert body["result"] is not None
    assert sum(body["result"]["portfolio_counts"].values()) == 12
