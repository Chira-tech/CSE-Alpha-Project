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
    ratio_series_by_key,
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


def test_ratio_series_by_key_exposes_the_raw_points_a_trend_verdict_is_reduced_from(db_session):
    """R1 T4.3.1: the company-file ratio card grid draws its own real
    numeric path ("11 -> 14 -> 16 -> 18") from this — a separate function
    from `ratio_trends_for`'s reduced direction/significance verdict, but
    built from the exact same `historical_ratios_for` call so the two can
    never disagree about which periods or values went into a ratio."""
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

    series = ratio_series_by_key(db_session, TICKER, as_of=dt.date(2026, 1, 1))
    roe_series = series["return_on_equity"]
    assert [p.period_end for p in roe_series] == [
        dt.date(2022, 3, 31), dt.date(2023, 3, 31), dt.date(2024, 3, 31), dt.date(2025, 3, 31),
    ]
    assert round(roe_series[0].value, 2) == Decimal("0.08")
    assert round(roe_series[-1].value, 4) == Decimal("0.1792")


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


class TestBulkLatestLineItemsAnnualisesNetIncome:
    """The real bug, found live (20 Aug 2026): this function used to hand
    back a quarter's raw cumulative `net_income` as-is — exactly the COMB
    "sell a healthy bank" bug `app.domain.ttm` closed for `latest_period_
    line_items`, just never ported to this bulk (screener/sector-
    percentile) path. Fixture values are COMB.N0000's own real, confirmed
    numbers (18 Aug 2026), same as `test_ttm.py`'s own — the real
    reconciliation this fix depends on, not an invented example."""

    def _seed(self, db, *, current_provenance=ProvenanceTier.REPORTED):
        db.add(Security(ticker=TICKER_2, name="Commercial Bank"))
        db.commit()
        db.add_all(
            [
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2025, 6, 30), version=1,
                    statement_line="net_income", value=Decimal("31165447000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 12, 31), period_type="annual",
                    first_available_date=dt.date(2025, 12, 31), version=1,
                    statement_line="net_income", value=Decimal("60937517000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2026, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2026, 6, 30), version=1,
                    statement_line="net_income", value=Decimal("35423054000"),
                    provenance_tier=current_provenance,
                ),
            ]
        )
        db.commit()

    def test_the_latest_quarters_raw_figure_is_replaced_by_its_ttm_annualised_value(self, db_session):
        self._seed(db_session)
        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("net_income",))
        period, items = result[TICKER_2]
        assert period == dt.date(2026, 6, 30)
        # NOT 35,423,054,000 (the raw H1 2026 cumulative figure) —
        # FY2025 + H1 2026 - H1 2025, COMB's own real TTM net income.
        assert items["net_income"].value == Decimal("65195124000")

    def test_an_unconfirmed_latest_quarter_is_left_as_is_not_annualised(self, db_session):
        """§8: TTM only ever reasons over confirmed periods — annualising
        an AI-assisted figure could silently pair a not-yet-reviewed
        number with confirmed history. Left exactly as extracted, same as
        `latest_period_line_items` does."""
        self._seed(db_session, current_provenance=ProvenanceTier.AI_ASSISTED)
        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("net_income",))
        _period, items = result[TICKER_2]
        assert items["net_income"].value == Decimal("35423054000")

    def test_no_confirmed_annual_history_drops_the_item_rather_than_using_the_raw_figure(self, db_session):
        """Real, live shape: a company with exactly one confirmed
        quarterly period and nothing else to annualise against — must be
        DROPPED, never silently left at its un-annualised cumulative
        value (the exact original bug)."""
        db_session.add(Security(ticker=TICKER_2, name="Commercial Bank"))
        db_session.commit()
        db_session.add(
            Fundamental(
                ticker=TICKER_2, period_end=dt.date(2026, 6, 30), period_type="quarterly",
                first_available_date=dt.date(2026, 6, 30), version=1,
                statement_line="net_income", value=Decimal("35423054000"),
                provenance_tier=ProvenanceTier.REPORTED,
            )
        )
        db_session.commit()

        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("net_income",))
        _period, items = result[TICKER_2]
        assert "net_income" not in items

    def test_an_annual_latest_period_is_used_directly_no_adjustment(self, db_session):
        db_session.add(Security(ticker=TICKER_2, name="Commercial Bank"))
        db_session.commit()
        db_session.add(
            Fundamental(
                ticker=TICKER_2, period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1,
                statement_line="net_income", value=Decimal("60937517000"),
                provenance_tier=ProvenanceTier.REPORTED,
            )
        )
        db_session.commit()

        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("net_income",))
        _period, items = result[TICKER_2]
        assert items["net_income"].value == Decimal("60937517000")


class TestBulkLatestLineItemsAlsoAnnualisesGrossProfit:
    """`gross_profit` carries the identical flow-over-stock risk as
    `net_income` — `gross_profitability` (§12's Novy-Marx measure) is
    gross profit ÷ total assets, the same shape as return_on_assets.
    Verified live against 5 real quarterly-period tickers in the dev
    database (ABAN.N0000, ACL.N0000, ACME.N0000, AFS.N0000, AGPL.N0000 —
    20 Aug 2026), every one showing a raw single-quarter gross_profit
    read directly against total_assets before this fix existed."""

    def _seed(self, db, *, current_provenance=ProvenanceTier.REPORTED):
        db.add(Security(ticker=TICKER_2, name="Commercial Bank"))
        db.commit()
        db.add_all(
            [
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2025, 6, 30), version=1,
                    statement_line="gross_profit", value=Decimal("100000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 12, 31), period_type="annual",
                    first_available_date=dt.date(2025, 12, 31), version=1,
                    statement_line="gross_profit", value=Decimal("400000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2026, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2026, 6, 30), version=1,
                    statement_line="gross_profit", value=Decimal("120000"),
                    provenance_tier=current_provenance,
                ),
            ]
        )
        db.commit()

    def test_the_latest_quarters_raw_gross_profit_is_replaced_by_its_ttm_value(self, db_session):
        self._seed(db_session)
        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("gross_profit",))
        period, items = result[TICKER_2]
        assert period == dt.date(2026, 6, 30)
        # FY2025 (400000) + H1 2026 (120000) - H1 2025 (100000) = 420000 —
        # NOT 120000, the raw un-annualised H1 2026 cumulative figure.
        assert items["gross_profit"].value == Decimal("420000")

    def test_an_unconfirmed_latest_quarter_gross_profit_is_left_as_is(self, db_session):
        self._seed(db_session, current_provenance=ProvenanceTier.AI_ASSISTED)
        result = bulk_latest_line_items(db_session, dt.date(2026, 8, 18), ("gross_profit",))
        _period, items = result[TICKER_2]
        assert items["gross_profit"].value == Decimal("120000")

    def test_net_income_and_gross_profit_are_annualised_independently(self, db_session):
        """The two flow lines must not interfere with each other — a real
        risk once the special-case for `net_income` alone became a loop
        over multiple lines."""
        self._seed(db_session)
        db_session.add_all(
            [
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2025, 6, 30), version=1,
                    statement_line="net_income", value=Decimal("31165447000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2025, 12, 31), period_type="annual",
                    first_available_date=dt.date(2025, 12, 31), version=1,
                    statement_line="net_income", value=Decimal("60937517000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=TICKER_2, period_end=dt.date(2026, 6, 30), period_type="quarterly",
                    first_available_date=dt.date(2026, 6, 30), version=1,
                    statement_line="net_income", value=Decimal("35423054000"),
                    provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.commit()

        result = bulk_latest_line_items(
            db_session, dt.date(2026, 8, 18), ("net_income", "gross_profit")
        )
        _period, items = result[TICKER_2]
        assert items["net_income"].value == Decimal("65195124000")
        assert items["gross_profit"].value == Decimal("420000")


class TestLatestPeriodLineItemsAlsoAnnualisesGrossProfit:
    """The same fix, ported through the shared `_annualise_flow_lines_in_
    place` helper, must land identically on the per-ticker path
    (`ratios_for`'s own data source) — the two must never again silently
    disagree, which is the entire reason this logic now lives in one
    shared place instead of two copies."""

    def test_gross_profitability_uses_the_annualised_figure_not_the_raw_quarter(self, db_session):
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add(db_session, "gross_profit", "100000", period_end=dt.date(2025, 6, 30),
             first_available=dt.date(2025, 6, 30), period_type="quarterly")
        _add(db_session, "gross_profit", "400000", period_end=dt.date(2025, 12, 31),
             first_available=dt.date(2025, 12, 31), period_type="annual")
        _add(db_session, "gross_profit", "120000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        _add(db_session, "total_assets", "2100000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        db_session.commit()

        period_end, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 8, 18))
        assert period_end == dt.date(2026, 6, 30)
        gp = next(r for r in results if r.key == "gross_profitability")
        # 420000 / 2100000 = 0.2 — NOT 120000 / 2100000 (0.0571...), the
        # raw un-annualised H1 2026 figure.
        assert round(gp.value, 4) == Decimal("0.2000")

    def test_gross_margin_uses_the_raw_period_figure_not_the_annualised_one(self, db_session):
        """The real regression this fix found live (20 Aug 2026): once
        `gross_profit` gets annualised for `gross_profitability`, a
        SAME-period ratio like `gross_margin` (gross profit ÷ revenue,
        both flows from the identical quarter) must still see the RAW
        H1 2026 gross_profit — pairing the annualised figure against
        revenue's still-raw, single-quarter value would overstate
        gross_margin by roughly the same factor annualisation corrects
        for on the other side (confirmed live: ACME.N0000's real
        gross_margin read as 47166.0000 under the broken version of this
        fix)."""
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add(db_session, "gross_profit", "100000", period_end=dt.date(2025, 6, 30),
             first_available=dt.date(2025, 6, 30), period_type="quarterly")
        _add(db_session, "gross_profit", "400000", period_end=dt.date(2025, 12, 31),
             first_available=dt.date(2025, 12, 31), period_type="annual")
        _add(db_session, "gross_profit", "120000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        _add(db_session, "revenue", "300000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        _add(db_session, "total_assets", "2100000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        db_session.commit()

        period_end, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 8, 18))
        assert period_end == dt.date(2026, 6, 30)

        # gross_profitability: the ANNUALISED view (420000 / 2100000 = 0.2).
        gp = next(r for r in results if r.key == "gross_profitability")
        assert round(gp.value, 4) == Decimal("0.2000")

        # gross_margin: the RAW view (120000 / 300000 = 0.4) — NOT
        # 420000 / 300000 (1.4), the mismatched, broken-fix value.
        gm = next(r for r in results if r.key == "gross_margin")
        assert round(gm.value, 4) == Decimal("0.4000")

    def test_net_margin_uses_the_raw_period_figure_not_the_annualised_one(self, db_session):
        """Same regression, same fix, for `net_income` ÷ `revenue` (net_
        margin) alongside `return_on_equity` (net_income ÷ total_equity,
        the ratio that correctly DOES want the annualised figure)."""
        db_session.add(Security(ticker=TICKER, name="JF Packaging PLC"))
        db_session.commit()
        _add(db_session, "net_income", "31165447000", period_end=dt.date(2025, 6, 30),
             first_available=dt.date(2025, 6, 30), period_type="quarterly")
        _add(db_session, "net_income", "60937517000", period_end=dt.date(2025, 12, 31),
             first_available=dt.date(2025, 12, 31), period_type="annual")
        _add(db_session, "net_income", "35423054000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        _add(db_session, "revenue", "100000000000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        _add(db_session, "total_equity", "364000000000", period_end=dt.date(2026, 6, 30),
             first_available=dt.date(2026, 6, 30), period_type="quarterly")
        db_session.commit()

        period_end, results = ratios_for(db_session, TICKER, as_of=dt.date(2026, 8, 18))
        assert period_end == dt.date(2026, 6, 30)

        # return_on_equity: the ANNUALISED view (65195124000 / 364000000000).
        roe = next(r for r in results if r.key == "return_on_equity")
        assert round(roe.value, 4) == round(Decimal("65195124000") / Decimal("364000000000"), 4)

        # net_margin: the RAW view (35423054000 / 100000000000) — NOT the
        # annualised figure over the same raw revenue.
        nm = next(r for r in results if r.key == "net_margin")
        assert round(nm.value, 4) == round(Decimal("35423054000") / Decimal("100000000000"), 4)
        assert nm.value != roe.value


class TestAllSectorPercentilesAlsoScopesEachRatioCorrectly:
    """The same raw-vs-TTM correctness must hold at the sector-percentile
    layer too — it computes the identical full ratio set, universe-wide,
    from `bulk_raw_latest_line_items` rather than `ratios_for`'s own
    single-ticker fetch, but must reach the same per-ratio result."""

    def test_gross_margin_and_gross_profitability_percentiles_use_their_own_correct_view(
        self, db_session
    ):
        from app.domain.sector_percentiles_view import all_sector_percentiles

        db_session.add_all(
            [
                Security(ticker=TICKER, name="JF Packaging PLC", cse_sector="Manufacturing"),
                Security(ticker=TICKER_2, name="Commercial Bank", cse_sector="Manufacturing"),
            ]
        )
        db_session.commit()

        def add(ticker, line, value, *, period_end, period_type):
            db_session.add(
                Fundamental(
                    ticker=ticker, period_end=period_end, period_type=period_type,
                    first_available_date=period_end, version=1,
                    statement_line=line, value=Decimal(value),
                    provenance_tier=ProvenanceTier.REPORTED,
                )
            )

        for ticker, base in ((TICKER, 100000), (TICKER_2, 50000)):
            add(ticker, "gross_profit", base, period_end=dt.date(2025, 6, 30), period_type="quarterly")
            add(ticker, "gross_profit", base * 4, period_end=dt.date(2025, 12, 31), period_type="annual")
            add(ticker, "gross_profit", base + 20000, period_end=dt.date(2026, 6, 30), period_type="quarterly")
            add(ticker, "revenue", base * 3, period_end=dt.date(2026, 6, 30), period_type="quarterly")
            add(ticker, "total_assets", base * 15, period_end=dt.date(2026, 6, 30), period_type="quarterly")
        db_session.commit()

        percentiles = all_sector_percentiles(db_session, dt.date(2026, 8, 18))
        # Both ratios must be present for both tickers — if the merge were
        # wrong (e.g. everything computed from one shared view, or the
        # opposite view picked per ratio), at least one of these would
        # either be missing or silently implausible (a margin > 1, or a
        # gross-profitability figure equal to the raw-quarter one).
        for ticker in (TICKER, TICKER_2):
            assert "gross_margin" in percentiles[ticker]
            assert "gross_profitability" in percentiles[ticker]
