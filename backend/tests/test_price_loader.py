"""app.ingestion.price_loader, against the verified tradeSummary shape
(README_ENDPOINTS.md) — mocked with a trimmed real captured row."""
from __future__ import annotations

import datetime as dt

import httpx
import respx

from app.ingestion.cse_client import CseClient
from app.ingestion.price_loader import fetch_eod_prices, upsert_eod_prices
from app.models.securities import Security

REAL_TRADE_SUMMARY_ROW = {
    "id": 204,
    "name": "ABANS ELECTRICALS PLC",
    "symbol": "ABAN.N0000",
    "quantity": 1,
    "percentageChange": -3.10715101667809,
    "change": -34.0,
    "price": 1060.25,
    "previousClose": 1094.25,
    "high": 1099.0,
    "low": 1060.0,
    "lastTradedTime": 1786691785346,
    "turnover": 127387.75,
    "sharevolume": 120,
    "tradevolume": 10,
    "marketCap": 5.41847124e9,
    "open": 1099.0,
    "closingPrice": 1060.25,
    "crossingVolume": 120,
    "crossingTradeVol": 10,
    "status": 0,
}


@respx.mock
def test_fetch_eod_prices_parses_real_shape():
    respx.post("https://example.test/api/tradeSummary").mock(
        return_value=httpx.Response(200, json={"reqTradeSummery": [REAL_TRADE_SUMMARY_ROW]})
    )
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    rows = fetch_eod_prices(client)
    client.close()

    assert len(rows) == 1
    assert rows[0].symbol == "ABAN.N0000"
    assert rows[0].closingPrice == 1060.25
    assert rows[0].sharevolume == 120


def test_upsert_writes_close_from_closing_price_field(db_session):
    db_session.add(Security(ticker="ABAN.N0000", name="Abans Electricals PLC"))
    db_session.commit()

    from app.ingestion.schemas import TradeSummaryRow

    row = TradeSummaryRow.model_validate(REAL_TRADE_SUMMARY_ROW)
    written = upsert_eod_prices(db_session, dt.date(2026, 8, 14), [row])
    assert written == 1

    from app.models.prices import PriceDaily

    stored = db_session.get(PriceDaily, ("ABAN.N0000", dt.date(2026, 8, 14)))
    assert stored is not None
    assert float(stored.close) == 1060.25
    assert stored.volume == 120
    assert stored.trades == 10
    assert float(stored.adj_factor) == 1.0  # untouched by this loader, by design


def test_upsert_is_idempotent_on_rerun(db_session):
    db_session.add(Security(ticker="ABAN.N0000", name="Abans Electricals PLC"))
    db_session.commit()

    from app.ingestion.schemas import TradeSummaryRow
    from app.models.prices import PriceDaily
    from sqlalchemy import select

    row = TradeSummaryRow.model_validate(REAL_TRADE_SUMMARY_ROW)
    upsert_eod_prices(db_session, dt.date(2026, 8, 14), [row])
    upsert_eod_prices(db_session, dt.date(2026, 8, 14), [row])

    count = len(list(db_session.scalars(select(PriceDaily))))
    assert count == 1
