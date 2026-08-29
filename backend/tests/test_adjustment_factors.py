import datetime as dt
from decimal import Decimal

from app.jobs.adjustment_factors import (
    rebuild_adjustment_factors_for_ticker,
    rebuild_all_adjustment_factors,
)
from app.models.corporate_actions import CorporateAction
from app.models.enums import CorporateActionType
from app.models.prices import PriceDaily
from app.models.securities import Security

TICKER = "SPLT.N0000"


def _seed_prices(db, prices: dict[dt.date, str]) -> None:
    db.add(Security(ticker=TICKER, name="Split Test PLC"))
    for date, close in prices.items():
        db.add(PriceDaily(ticker=TICKER, date=date, close=Decimal(close), adj_factor=Decimal("1.0"),
                          fetched_at=dt.datetime.now(dt.timezone.utc)))
    db.commit()


def _seed_split(db, ex_date: dt.date, ratio: str, *, confirmed: bool = True) -> None:
    db.add(
        CorporateAction(
            ticker=TICKER,
            type=CorporateActionType.STOCK_SPLIT,
            ex_date=ex_date,
            ratio=Decimal(ratio),
            confirmed_by="human:test" if confirmed else None,
            confirmed_at=dt.datetime.now(dt.timezone.utc) if confirmed else None,
        )
    )
    db.commit()


def test_a_confirmed_split_makes_the_pre_split_series_continuous(db_session):
    """The real CDB.N0000 shape: a 1:9 split turns 436.50 into 42.50, a
    -90% one-day 'return' that is entirely mechanical. After the rebuild,
    adjusted prices either side of the ex-date must be continuous."""
    ex = dt.date(2026, 4, 30)
    _seed_prices(db_session, {
        dt.date(2026, 4, 22): "436.50",
        ex: "42.50",
        dt.date(2026, 5, 4): "43.00",
    })
    _seed_split(db_session, ex, "9")  # 9 new shares per share held

    changed, skipped = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    db_session.commit()
    assert skipped == []
    assert changed == 1  # only the pre-split row moves off 1.0

    rows = {r.date: r for r in db_session.query(PriceDaily).all()}
    before = rows[dt.date(2026, 4, 22)]
    after = rows[ex]
    assert after.adj_factor == Decimal(1)
    adj_before = before.close * before.adj_factor
    # 436.50 / 10 = 43.65, within a whisker of the real 42.50 post-split
    # price — the point is that the -90% artefact is gone, not that the
    # market traded flat across the split.
    assert Decimal("40") < adj_before < Decimal("46")
    assert abs(adj_before - after.close) < before.close / 2


def test_an_unconfirmed_action_is_ignored(db_session):
    """§8: an unconfirmed corporate action must never move a price."""
    ex = dt.date(2026, 4, 30)
    _seed_prices(db_session, {dt.date(2026, 4, 22): "436.50", ex: "42.50"})
    _seed_split(db_session, ex, "9", confirmed=False)

    changed, _ = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    assert changed == 0
    assert all(r.adj_factor == Decimal(1) for r in db_session.query(PriceDaily).all())


def test_no_actions_leaves_every_factor_at_one(db_session):
    _seed_prices(db_session, {dt.date(2026, 4, 22): "100", dt.date(2026, 4, 23): "101"})
    changed, skipped = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    assert (changed, skipped) == (0, [])


def test_rerunning_is_idempotent(db_session):
    ex = dt.date(2026, 4, 30)
    _seed_prices(db_session, {dt.date(2026, 4, 22): "436.50", ex: "42.50"})
    _seed_split(db_session, ex, "9")

    first, _ = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    db_session.commit()
    second, _ = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    assert first == 1
    assert second == 0  # nothing left to change


def test_a_dividend_with_no_prior_day_close_is_reported_not_crashed(db_session):
    """A cash dividend needs the close the day before its ex-date to
    compute a ratio. Inside the price window with that close missing, the
    event must be REPORTED as an under-adjustment rather than crashing the
    whole ticker (which would also lose the splits we CAN compute)."""
    _seed_prices(db_session, {
        dt.date(2026, 4, 1): "100",
        dt.date(2026, 4, 20): "100",
        dt.date(2026, 4, 30): "95",
    })
    db_session.add(
        CorporateAction(
            ticker=TICKER,
            type=CorporateActionType.DIVIDEND_CASH,
            ex_date=dt.date(2026, 4, 30),
            cash_amount=None,  # amount never extracted
            confirmed_by="human:test",
            confirmed_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()

    changed, skipped = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    assert changed == 0
    assert len(skipped) == 1
    assert "2026-04-30" in skipped[0]


def test_an_action_before_the_price_history_is_not_reported_as_a_gap(db_session):
    """It affects no stored row, so dropping it is a no-op — reporting it
    would bury the real under-adjustments in noise."""
    _seed_prices(db_session, {dt.date(2026, 4, 22): "100"})
    db_session.add(
        CorporateAction(
            ticker=TICKER,
            type=CorporateActionType.DIVIDEND_CASH,
            ex_date=dt.date(2019, 1, 1),
            cash_amount=None,
            confirmed_by="human:test",
            confirmed_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()

    changed, skipped = rebuild_adjustment_factors_for_ticker(db_session, TICKER)
    assert (changed, skipped) == (0, [])


def test_rebuild_all_reports_a_summary(db_session):
    ex = dt.date(2026, 4, 30)
    _seed_prices(db_session, {dt.date(2026, 4, 22): "436.50", ex: "42.50"})
    _seed_split(db_session, ex, "9")

    summary = rebuild_all_adjustment_factors(db_session)
    assert summary["tickers_scanned"] == 1
    assert summary["tickers_changed"] == 1
    assert summary["price_rows_changed"] == 1
