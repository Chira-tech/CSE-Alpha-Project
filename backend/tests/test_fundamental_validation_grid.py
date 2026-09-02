"""Spec §17 — the company-wide data-integrity grid, domain + API."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.fundamental_validation_grid import validation_grid
from app.domain.fundamental_validation_view import revalidate_all
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

FAD = dt.date(2024, 6, 30)


def _annual(db, ticker, year, line, value):
    db.add(
        Fundamental(
            ticker=ticker, period_end=dt.date(year, 3, 31), period_type="annual",
            first_available_date=FAD, version=1, statement_line=line,
            value=Decimal(value), provenance_tier=ProvenanceTier.REPORTED,
        )
    )


def test_grid_marks_a_year_failed_when_a_row_failed(db_session):
    db_session.add(Security(ticker="AAA.N0000", name="Aaa PLC"))
    # 2023 balances, 2024 does not.
    _annual(db_session, "AAA.N0000", 2023, "total_assets", "50_000_000")
    _annual(db_session, "AAA.N0000", 2023, "total_liabilities", "32_000_000")
    _annual(db_session, "AAA.N0000", 2023, "total_equity", "18_000_000")
    _annual(db_session, "AAA.N0000", 2024, "total_assets", "48_000_000")  # off by 2m
    _annual(db_session, "AAA.N0000", 2024, "total_liabilities", "32_000_000")
    _annual(db_session, "AAA.N0000", 2024, "total_equity", "18_000_000")
    db_session.commit()
    revalidate_all(db_session)

    grid = validation_grid(db_session)
    row = next(s for s in grid.securities if s.ticker == "AAA.N0000")
    by_year = {c.year: c.status for c in row.years}
    assert by_year[2023] == "ok"
    assert by_year[2024] == "failed"
    assert row.failed_total == 3
    assert grid.securities_with_failures == 1
    assert grid.securities_fully_validated == 0


def test_grid_endpoint_shape(client, db_session):
    db_session.add(Security(ticker="BBB.N0000", name="Bbb PLC"))
    _annual(db_session, "BBB.N0000", 2024, "total_assets", "50_000_000")
    _annual(db_session, "BBB.N0000", 2024, "total_liabilities", "32_000_000")
    _annual(db_session, "BBB.N0000", 2024, "total_equity", "18_000_000")
    db_session.commit()
    revalidate_all(db_session)

    body = client.get("/data-health/validation").json()
    assert body["years"][0] == 2020
    assert body["total_rows_checked"] == 3
    assert body["total_rows_failed"] == 0
    row = next(s for s in body["securities"] if s["ticker"] == "BBB.N0000")
    assert {c["year"] for c in row["years"]} == set(body["years"])
