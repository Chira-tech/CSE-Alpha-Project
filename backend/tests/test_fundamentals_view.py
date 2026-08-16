"""
The stored-rows -> ratio-engine bridge, and specifically that the
point-in-time rule survives the trip.

A ratio computed from a restatement the market had not yet seen is
exactly the look-ahead bias Part N #1 calls "the single most common
source of alpha that does not exist" — so it gets a test rather than a
comment.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.fundamentals_view import latest_period_line_items, ratios_for
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

TICKER = "JFP.N0000"


def _add(db, line: str, value: str, *, period_end, first_available, version=1, provenance=ProvenanceTier.REPORTED, period_type="annual"):
    db.add(
        Fundamental(
            ticker=TICKER,
            period_end=period_end,
            period_type=period_type,
            first_available_date=first_available,
            version=version,
            statement_line=line,
            value=Decimal(value),
            provenance_tier=provenance,
        )
    )


def _seed_company(db):
    db.add(Security(ticker=TICKER, name="JF Packaging PLC"))
    db.commit()


def test_ratios_computed_from_stored_rows(db_session):
    _seed_company(db_session)
    period = dt.date(2026, 3, 31)
    available = dt.date(2026, 8, 14)
    _add(db_session, "net_income", "189908", period_end=period, first_available=available)
    _add(db_session, "total_equity", "1643031", period_end=period, first_available=available)
    db_session.commit()

    period_end, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 8, 20))
    assert period_end == period
    roe = next(r for r in results if r.key == "return_on_equity")
    assert roe.computable
    assert round(roe.value, 4) == Decimal("0.1156")


def test_a_restatement_not_yet_public_does_not_change_the_ratio(db_session):
    """The company later restates net income downward. A ratio computed
    for a date BEFORE that restatement was published must use the
    original figure."""
    _seed_company(db_session)
    period = dt.date(2026, 3, 31)
    _add(db_session, "net_income", "189908", period_end=period, first_available=dt.date(2026, 8, 14))
    _add(db_session, "total_equity", "1643031", period_end=period, first_available=dt.date(2026, 8, 14))
    # restated much later
    _add(
        db_session,
        "net_income",
        "100000",
        period_end=period,
        first_available=dt.date(2026, 12, 1),
        version=2,
    )
    db_session.commit()

    _, before = ratios_for(db_session, TICKER, as_of=dt.date(2026, 9, 1))
    roe_before = next(r for r in before if r.key == "return_on_equity")
    assert round(roe_before.value, 4) == Decimal("0.1156")  # original

    _, after = ratios_for(db_session, TICKER, as_of=dt.date(2027, 1, 1))
    roe_after = next(r for r in after if r.key == "return_on_equity")
    assert round(roe_after.value, 4) == Decimal("0.0609")  # restated
    assert roe_after.value < roe_before.value


def test_nothing_visible_yet_yields_no_period_and_no_computable_ratios(db_session):
    _seed_company(db_session)
    _add(
        db_session,
        "net_income",
        "189908",
        period_end=dt.date(2026, 3, 31),
        first_available=dt.date(2026, 8, 14),
    )
    db_session.commit()

    period_end, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 1, 1))
    assert period_end is None
    assert all(not r.computable for r in results)


def test_only_the_latest_visible_period_is_used(db_session):
    """Mixing a numerator from one year with a denominator from another
    would produce a plausible-looking, meaningless ratio."""
    _seed_company(db_session)
    old, new = dt.date(2025, 3, 31), dt.date(2026, 3, 31)
    _add(db_session, "net_income", "130625", period_end=old, first_available=dt.date(2025, 8, 14))
    _add(db_session, "total_equity", "1116530", period_end=old, first_available=dt.date(2025, 8, 14))
    _add(db_session, "net_income", "189908", period_end=new, first_available=dt.date(2026, 8, 14))
    _add(db_session, "total_equity", "1643031", period_end=new, first_available=dt.date(2026, 8, 14))
    db_session.commit()

    period_end, items = latest_period_line_items(db_session, TICKER, dt.date(2026, 9, 1))
    assert period_end == new
    assert items["net_income"].value == Decimal("189908")
    assert items["total_equity"].value == Decimal("1643031")


def test_ai_assisted_input_taints_the_ratio_provenance(db_session):
    _seed_company(db_session)
    period, available = dt.date(2026, 3, 31), dt.date(2026, 8, 14)
    _add(db_session, "net_income", "189908", period_end=period, first_available=available)
    _add(
        db_session,
        "total_equity",
        "1643031",
        period_end=period,
        first_available=available,
        provenance=ProvenanceTier.AI_ASSISTED,
    )
    db_session.commit()

    _, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 9, 1))
    roe = next(r for r in results if r.key == "return_on_equity")
    assert roe.provenance is ProvenanceTier.AI_ASSISTED


def test_period_type_filter_separates_annual_from_quarterly(db_session):
    _seed_company(db_session)
    _add(
        db_session,
        "net_income",
        "50000",
        period_end=dt.date(2026, 6, 30),
        first_available=dt.date(2026, 8, 14),
        period_type="quarterly",
    )
    _add(
        db_session,
        "net_income",
        "189908",
        period_end=dt.date(2026, 3, 31),
        first_available=dt.date(2026, 8, 14),
        period_type="annual",
    )
    db_session.commit()

    annual_period, annual_items = latest_period_line_items(
        db_session, TICKER, dt.date(2026, 9, 1), period_type="annual"
    )
    assert annual_period == dt.date(2026, 3, 31)
    assert annual_items["net_income"].value == Decimal("189908")
