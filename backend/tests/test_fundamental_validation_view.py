"""The data-integrity sweep and the valuation-engine gate —
`app.domain.fundamental_validation_view` + `app.domain.point_in_time.
fundamentals_as_of`'s `exclude_validation_failed`.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.fundamental_validation_view import (
    failed_fundamental_ids,
    revalidate_all,
)
from app.domain.point_in_time import fundamentals_as_of
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental

PERIOD_END = dt.date(2024, 3, 31)
FAD = dt.date(2024, 6, 30)
AS_OF = dt.date(2024, 9, 1)


def _line(db, ticker, line, value, *, tier=ProvenanceTier.REPORTED):
    db.add(
        Fundamental(
            ticker=ticker, period_end=PERIOD_END, period_type="annual",
            first_available_date=FAD, version=1, statement_line=line,
            value=Decimal(value), provenance_tier=tier,
        )
    )


def test_a_balancing_filing_is_all_passed_and_stays_in_the_engine_view(db_session):
    _line(db_session, "AAA.N0000", "total_assets", "50_000_000")
    _line(db_session, "AAA.N0000", "total_liabilities", "32_000_000")
    _line(db_session, "AAA.N0000", "total_equity", "18_000_000")
    db_session.commit()

    summary = revalidate_all(db_session)
    assert summary.rows_failed == 0
    assert summary.rows_passed == 3

    rows = fundamentals_as_of(db_session, "AAA.N0000", AS_OF)
    assert {r.statement_line for r in rows} == {
        "total_assets", "total_liabilities", "total_equity"
    }


def test_a_failing_filing_drops_the_bad_lines_from_the_engine_view(db_session):
    _line(db_session, "BBB.N0000", "total_assets", "48_000_000")  # off by 2,000,000
    _line(db_session, "BBB.N0000", "total_liabilities", "32_000_000")
    _line(db_session, "BBB.N0000", "total_equity", "18_000_000")
    # an unrelated, self-consistent line on the same filing
    _line(db_session, "BBB.N0000", "revenue", "10_000_000")
    _line(db_session, "BBB.N0000", "cost_of_sales", "-6_000_000")
    _line(db_session, "BBB.N0000", "gross_profit", "4_000_000")
    db_session.commit()

    summary = revalidate_all(db_session)
    assert summary.rows_failed == 3  # the three balance-sheet lines

    # The valuation engine's view no longer contains the failed lines...
    engine_rows = {r.statement_line for r in fundamentals_as_of(db_session, "BBB.N0000", AS_OF)}
    assert engine_rows == {"revenue", "cost_of_sales", "gross_profit"}

    # ...but a display caller can still see everything.
    all_rows = {
        r.statement_line
        for r in fundamentals_as_of(db_session, "BBB.N0000", AS_OF, exclude_validation_failed=False)
    }
    assert "total_assets" in all_rows


def test_failed_fundamental_ids_lists_only_failing_rows(db_session):
    _line(db_session, "CCC.N0000", "total_assets", "48_000_000")
    _line(db_session, "CCC.N0000", "total_liabilities", "32_000_000")
    _line(db_session, "CCC.N0000", "total_equity", "18_000_000")
    db_session.commit()
    revalidate_all(db_session)

    ids = [r.id for r in db_session.query(Fundamental).all()]
    failed = failed_fundamental_ids(db_session, ids)
    assert len(failed) == 3
    assert failed == set(ids)


def test_the_sweep_is_idempotent(db_session):
    _line(db_session, "DDD.N0000", "total_assets", "50_000_000")
    _line(db_session, "DDD.N0000", "total_liabilities", "32_000_000")
    _line(db_session, "DDD.N0000", "total_equity", "18_000_000")
    db_session.commit()

    first = revalidate_all(db_session)
    second = revalidate_all(db_session)
    assert first.as_dict() == second.as_dict()


def test_a_row_never_swept_is_treated_as_not_failed(db_session):
    # No revalidate_all() call — the gate must not hide a row just
    # because it has no validation record yet.
    _line(db_session, "EEE.N0000", "total_assets", "50_000_000")
    db_session.commit()
    rows = fundamentals_as_of(db_session, "EEE.N0000", AS_OF)
    assert [r.statement_line for r in rows] == ["total_assets"]
