"""GET /portfolio/holdings/valued — API-layer wiring for the real
portfolio valuation view. Same reasoning as every other API test in
this system: catches a Pydantic-serialization bug at the domain-to-API
boundary.
"""
from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

from app.models.prices import PriceDaily
from app.models.securities import Security

HEADER = [
    "Security", "Quantity", "Cleared Balance", "Available Balance",
    "Unsettled Buy", "Unsettled Sell", "Holding % (Quantity)", "Avg Price",
    "B.E.S Price", "Total Cost", "Traded Price", "Market Value",
    "Holding % (Market Value)", "Sales Commission", "Sales Proceeds",
    "Unrealized Gain / (Loss)", "Unrealized Gain/Loss %", "Unr Today Gain/(Loss)",
]


def _build_xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Portfolio (TEST ACCOUNT) - EQUITY"])
    ws.append([])
    ws.append(HEADER)
    ws.append([
        "JKH.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 100.0, 20.0, 20.2,
        20000.0, 20.0, 20000.0, 100.0, 224.0, 19776.0, 0.0, 0.0, 0.0,
    ])
    ws.append([
        "Total", None, None, None, None, None, None, None, None,
        20000.0, None, 20000.0, None, 224.0, 19776.0, 0.0, None, 0.0,
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_none_before_any_upload(client):
    r = client.get("/portfolio/holdings/valued")
    assert r.status_code == 200
    assert r.json() is None


def test_a_real_uploaded_position_gets_valued(client, db_session):
    db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(PriceDaily(ticker="JKH.N0000", date=dt.date.today(), close=Decimal("25.0"), adj_factor=Decimal("1"), fetched_at=now))
    db_session.commit()

    client.post(
        "/portfolio/upload",
        files={"file": ("Portfolio.xlsx", _build_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    r = client.get("/portfolio/holdings/valued")
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert len(body["positions"]) == 1
    pos = body["positions"][0]
    assert pos["ticker"] == "JKH.N0000"
    assert Decimal(pos["snapshot_traded_price"]) == Decimal("20")
    assert Decimal(pos["live_current_price"]) == Decimal("25")
    assert Decimal(pos["live_market_value"]) == Decimal("25000")
    assert Decimal(body["total_live_market_value"]) == Decimal("25000")

    # Redesign additions — present and well-typed, and every pre-existing
    # field the TodayScreen contract depends on is still there.
    assert "value_trend_pct" in body  # unchanged, still consumed by Today
    assert isinstance(body["value_series"], list)
    assert isinstance(pos["sparkline"], list)
    rollups = body["rollups"]
    assert isinstance(rollups["sector_allocation"], list)
    assert "portfolio_beta" in rollups
    assert "beta_coverage_pct" in rollups
    assert "trailing_dividend_income" in rollups
    assert rollups["dividend_positions_counted"] == 0
    assert rollups["unpriced_position_count"] == 0
