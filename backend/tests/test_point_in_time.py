"""
Master Spec §6: "All models query on first_available_date <= t, never
period_end <= t." This is the test that would catch the single most common
source of manufactured backtest alpha (Part N failure mode #1) if it were
ever reintroduced.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.point_in_time import fundamentals_as_of
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security


def _make_security(db, ticker="SAMP.N0000"):
    db.add(Security(ticker=ticker, name="Sample PLC"))
    db.commit()
    return ticker


def test_restated_value_not_visible_before_its_own_first_available_date(db_session):
    ticker = _make_security(db_session)

    original = Fundamental(
        ticker=ticker,
        period_end=dt.date(2024, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2024, 6, 1),
        version=1,
        statement_line="net_income",
        value=Decimal("1000000"),
        provenance_tier=ProvenanceTier.REPORTED,
    )
    restated = Fundamental(
        ticker=ticker,
        period_end=dt.date(2024, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2024, 11, 1),  # restated much later
        version=2,
        statement_line="net_income",
        value=Decimal("800000"),  # restated downward
        provenance_tier=ProvenanceTier.REPORTED,
        restated_flag=True,
    )
    db_session.add_all([original, restated])
    db_session.commit()

    # A backtest formed on 1 September 2024 must see only the original
    # value — the restatement wasn't public yet.
    as_of_sept = fundamentals_as_of(db_session, ticker, dt.date(2024, 9, 1))
    assert len(as_of_sept) == 1
    assert as_of_sept[0].value == Decimal("1000000")
    assert as_of_sept[0].version == 1

    # After the restatement's own first_available_date, the newer version
    # is what's visible — never both, never silently the old one.
    as_of_december = fundamentals_as_of(db_session, ticker, dt.date(2024, 12, 1))
    assert len(as_of_december) == 1
    assert as_of_december[0].value == Decimal("800000")
    assert as_of_december[0].version == 2


def test_nothing_visible_before_any_first_available_date(db_session):
    ticker = _make_security(db_session)
    db_session.add(
        Fundamental(
            ticker=ticker,
            period_end=dt.date(2024, 3, 31),
            period_type="annual",
            first_available_date=dt.date(2024, 6, 1),
            version=1,
            statement_line="net_income",
            value=Decimal("1000000"),
            provenance_tier=ProvenanceTier.REPORTED,
        )
    )
    db_session.commit()

    as_of_january = fundamentals_as_of(db_session, ticker, dt.date(2024, 1, 1))
    assert as_of_january == []


def test_statement_line_filter(db_session):
    ticker = _make_security(db_session)
    db_session.add_all(
        [
            Fundamental(
                ticker=ticker,
                period_end=dt.date(2024, 3, 31),
                period_type="annual",
                first_available_date=dt.date(2024, 6, 1),
                version=1,
                statement_line="net_income",
                value=Decimal("1000000"),
                provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker,
                period_end=dt.date(2024, 3, 31),
                period_type="annual",
                first_available_date=dt.date(2024, 6, 1),
                version=1,
                statement_line="revenue",
                value=Decimal("5000000"),
                provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db_session.commit()

    rows = fundamentals_as_of(db_session, ticker, dt.date(2024, 7, 1), statement_line="revenue")
    assert len(rows) == 1
    assert rows[0].statement_line == "revenue"
