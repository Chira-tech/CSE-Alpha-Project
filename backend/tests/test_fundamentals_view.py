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

from app.domain.fundamentals_view import (
    bulk_latest_line_items,
    historical_ratios_for,
    latest_period_line_items,
    ratio_trends_for,
    ratios_for,
)
from app.domain.trend_detection import Direction
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


def test_a_single_real_period_reports_insufficient_history_not_a_trend(db_session):
    """The honest baseline case for most tickers today: J.F. Packaging's
    real, verified FY2025/26 figures are the only period this system has
    ever ingested for it, via the deterministic extractor. §13's trend
    detection must say so plainly rather than reporting a direction from
    one point pretending to be a trajectory."""
    _seed_company(db_session)
    _add(db_session, "net_income", "189908", period_end=dt.date(2026, 3, 31), first_available=dt.date(2026, 8, 14))
    _add(db_session, "total_equity", "1643031", period_end=dt.date(2026, 3, 31), first_available=dt.date(2026, 8, 14))
    db_session.commit()

    trends = ratio_trends_for(db_session, TICKER, as_of=dt.date(2026, 9, 1))
    roe_trend = trends["return_on_equity"]
    assert roe_trend.periods_used == 1
    assert roe_trend.direction.direction == Direction.INSUFFICIENT_HISTORY


def test_historical_ratios_groups_by_period_across_multiple_years(db_session):
    """Synthetic multi-year series — no real filing history exists yet
    for any ticker (getFinancialAnnouncement is recent-filings only), so
    this documents the shape the trend engine will consume once the
    extractor has run across several annual reports rather than one."""
    _seed_company(db_session)
    for year, net_income, equity in (
        (2022, "100000", "1000000"),
        (2023, "130000", "1080000"),
        (2024, "160000", "1150000"),
        (2025, "189908", "1643031"),
    ):
        _add(
            db_session, "net_income", net_income,
            period_end=dt.date(year, 3, 31), first_available=dt.date(year, 8, 14),
        )
        _add(
            db_session, "total_equity", equity,
            period_end=dt.date(year, 3, 31), first_available=dt.date(year, 8, 14),
        )
    db_session.commit()

    by_period = historical_ratios_for(db_session, TICKER, as_of=dt.date(2026, 1, 1))
    assert list(by_period.keys()) == [
        dt.date(2022, 3, 31), dt.date(2023, 3, 31), dt.date(2024, 3, 31), dt.date(2025, 3, 31),
    ]
    roe_2025 = next(r for r in by_period[dt.date(2025, 3, 31)] if r.key == "return_on_equity")
    assert round(roe_2025.value, 4) == Decimal("0.1156")


def test_a_four_year_improving_roe_reports_as_increasing(db_session):
    """Rising net income against a slower-growing equity base — a real
    trend shape, and enough periods (4) for the direction test to run."""
    _seed_company(db_session)
    for year, net_income, equity in (
        (2022, "80000", "1000000"),
        (2023, "110000", "1020000"),
        (2024, "150000", "1040000"),
        (2025, "189908", "1060000"),
    ):
        _add(
            db_session, "net_income", net_income,
            period_end=dt.date(year, 3, 31), first_available=dt.date(year, 8, 14),
        )
        _add(
            db_session, "total_equity", equity,
            period_end=dt.date(year, 3, 31), first_available=dt.date(year, 8, 14),
        )
    db_session.commit()

    trends = ratio_trends_for(db_session, TICKER, as_of=dt.date(2026, 1, 1))
    roe_trend = trends["return_on_equity"]
    assert roe_trend.periods_used == 4
    assert roe_trend.direction.direction == Direction.INCREASING


def test_point_in_time_applies_to_trend_history_too(db_session):
    """A restatement filed after `as_of` must not leak into the trend any
    more than it may leak into a single-period ratio — the whole point of
    routing this through `fundamentals_as_of` rather than a raw query."""
    _seed_company(db_session)
    _add(db_session, "net_income", "100000", period_end=dt.date(2024, 3, 31), first_available=dt.date(2024, 8, 1))
    _add(db_session, "total_equity", "1000000", period_end=dt.date(2024, 3, 31), first_available=dt.date(2024, 8, 1))
    _add(db_session, "net_income", "150000", period_end=dt.date(2025, 3, 31), first_available=dt.date(2025, 8, 1))
    _add(db_session, "total_equity", "1000000", period_end=dt.date(2025, 3, 31), first_available=dt.date(2025, 8, 1))
    # A restatement of the 2024 figure, published well after both periods above.
    _add(
        db_session, "net_income", "20000", period_end=dt.date(2024, 3, 31),
        first_available=dt.date(2026, 6, 1), version=2,
    )
    db_session.commit()

    by_period = historical_ratios_for(db_session, TICKER, as_of=dt.date(2025, 9, 1))
    roe_2024 = next(r for r in by_period[dt.date(2024, 3, 31)] if r.key == "return_on_equity")
    assert roe_2024.value == Decimal("0.1")  # the original 100000/1000000, not the restated 20000


TICKER_2 = "COMB.N0000"


def _add_ticker(db, ticker, line, value, *, period_end, first_available, version=1, provenance=ProvenanceTier.REPORTED):
    db.add(
        Fundamental(
            ticker=ticker, period_end=period_end, period_type="annual",
            first_available_date=first_available, version=version,
            statement_line=line, value=Decimal(value), provenance_tier=provenance,
        )
    )


class TestBulkLatestLineItems:
    """The screener's data source — every ticker's latest visible line
    items in one query, same point-in-time and restatement discipline as
    the single-ticker path (`fundamentals_as_of`), verified independently
    rather than assumed to follow because the logic looks similar."""

    def test_multiple_tickers_each_get_their_own_latest_period(self, db_session):
        db_session.add_all([Security(ticker=TICKER, name="JF Packaging PLC"), Security(ticker=TICKER_2, name="Commercial Bank")])
        db_session.commit()
        _add_ticker(db_session, TICKER, "net_income", "200", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 1))
        _add_ticker(db_session, TICKER, "total_equity", "1000", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 1))
        _add_ticker(db_session, TICKER_2, "net_income", "5000", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 7))
        _add_ticker(db_session, TICKER_2, "total_equity", "25000", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 7))
        db_session.commit()

        result = bulk_latest_line_items(db_session, dt.date(2026, 6, 1), ("net_income", "total_equity"))

        assert set(result) == {TICKER, TICKER_2}
        period_1, items_1 = result[TICKER]
        assert period_1 == dt.date(2025, 12, 31)
        assert items_1["net_income"].value == Decimal("200")
        period_2, items_2 = result[TICKER_2]
        assert items_2["total_equity"].value == Decimal("25000")

    def test_ticker_with_no_visible_data_is_absent_not_empty(self, db_session):
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        result = bulk_latest_line_items(db_session, dt.date(2026, 6, 1), ("net_income", "total_equity"))
        assert TICKER not in result

    def test_point_in_time_excludes_future_filings(self, db_session):
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add_ticker(db_session, TICKER, "net_income", "200", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 1))
        _add_ticker(db_session, TICKER, "total_equity", "1000", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 1))
        db_session.commit()

        # as_of before the filing was public — must not see it.
        result = bulk_latest_line_items(db_session, dt.date(2026, 1, 1), ("net_income", "total_equity"))
        assert TICKER not in result

    def test_restatement_uses_highest_version_visible_by_as_of(self, db_session):
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add_ticker(db_session, TICKER, "net_income", "100", period_end=dt.date(2024, 12, 31), first_available=dt.date(2025, 3, 1))
        _add_ticker(db_session, TICKER, "total_equity", "1000", period_end=dt.date(2024, 12, 31), first_available=dt.date(2025, 3, 1))
        # Restatement, published later.
        _add_ticker(db_session, TICKER, "net_income", "80", period_end=dt.date(2024, 12, 31), first_available=dt.date(2026, 1, 1), version=2)
        db_session.commit()

        before_restatement = bulk_latest_line_items(db_session, dt.date(2025, 6, 1), ("net_income", "total_equity"))
        assert before_restatement[TICKER][1]["net_income"].value == Decimal("100")

        after_restatement = bulk_latest_line_items(db_session, dt.date(2026, 6, 1), ("net_income", "total_equity"))
        assert after_restatement[TICKER][1]["net_income"].value == Decimal("80")

    def test_picks_latest_period_end_not_all_periods_merged(self, db_session):
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add_ticker(db_session, TICKER, "net_income", "100", period_end=dt.date(2024, 12, 31), first_available=dt.date(2025, 3, 1))
        _add_ticker(db_session, TICKER, "total_equity", "1000", period_end=dt.date(2024, 12, 31), first_available=dt.date(2025, 3, 1))
        _add_ticker(db_session, TICKER, "net_income", "150", period_end=dt.date(2025, 12, 31), first_available=dt.date(2026, 3, 1))
        # total_equity NOT re-filed for 2025 in this fixture — the latest
        # period's item set should reflect only what that period actually has.
        db_session.commit()

        result = bulk_latest_line_items(db_session, dt.date(2026, 6, 1), ("net_income", "total_equity"))
        period, items = result[TICKER]
        assert period == dt.date(2025, 12, 31)
        assert items["net_income"].value == Decimal("150")
        assert "total_equity" not in items
