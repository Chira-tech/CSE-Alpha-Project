"""Master Spec §7 nightly reconciliation job."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.jobs.reconciliation import is_quarantined, reconcile_ticker
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType
from app.models.prices import PriceDaily
from app.models.securities import Security


def _seed_security(db, ticker="JKH.N0000"):
    db.add(Security(ticker=ticker, name="Sample Holdings PLC"))
    db.commit()


def test_reconciliation_passes_when_adj_factor_matches_confirmed_action(db_session):
    ticker = "JKH.N0000"
    _seed_security(db_session, ticker)
    ex_date = dt.date(2024, 6, 1)
    day_before = ex_date - dt.timedelta(days=1)
    now = dt.datetime.now(dt.timezone.utc)

    # 1:1 bonus, correctly reflected in stored adj_factor (0.5 before, 1.0 on/after)
    db_session.add_all(
        [
            PriceDaily(
                ticker=ticker, date=day_before, close=Decimal("100.00"), adj_factor=Decimal("0.5"), fetched_at=now
            ),
            PriceDaily(
                ticker=ticker, date=ex_date, close=Decimal("50.00"), adj_factor=Decimal("1.0"), fetched_at=now
            ),
            CorporateAction(
                ticker=ticker,
                ex_date=ex_date,
                type=DbActionType.BONUS_ISSUE,
                ratio=Decimal("1"),
                confirmed_by="analyst",
                confirmed_at=now,
            ),
        ]
    )
    db_session.commit()

    alert = reconcile_ticker(db_session, ticker)
    assert alert is None
    assert not is_quarantined(db_session, ticker)


def test_reconciliation_fails_and_quarantines_on_stale_adj_factor(db_session):
    """The corporate action is confirmed, but the stored adj_factor on the
    price row was never rebuilt to reflect it (e.g. the rebuild job hadn't
    run yet), so an independent recomputation from raw prices + the
    confirmed action disagrees sharply — this is exactly the scenario §7
    exists to catch.
    """
    ticker = "JKH.N0000"
    _seed_security(db_session, ticker)
    ex_date = dt.date(2024, 6, 1)
    day_before = ex_date - dt.timedelta(days=1)
    now = dt.datetime.now(dt.timezone.utc)

    db_session.add_all(
        [
            PriceDaily(
                ticker=ticker,
                date=day_before,
                close=Decimal("100.00"),
                adj_factor=Decimal("1.0"),  # WRONG: should be 0.5, action not reflected
                fetched_at=now,
            ),
            PriceDaily(
                ticker=ticker, date=ex_date, close=Decimal("50.00"), adj_factor=Decimal("1.0"), fetched_at=now
            ),
            CorporateAction(
                ticker=ticker,
                ex_date=ex_date,
                type=DbActionType.BONUS_ISSUE,
                ratio=Decimal("1"),
                confirmed_by="analyst",  # confirmed in the CA table...
                confirmed_at=now,
            ),
        ]
    )
    db_session.commit()

    alert = reconcile_ticker(db_session, ticker)
    assert alert is not None
    assert alert.alert_type == "reconciliation_mismatch"
    assert is_quarantined(db_session, ticker)


def test_unconfirmed_corporate_action_is_ignored_by_reconciliation(db_session):
    """An action still awaiting human confirmation must not be treated as
    ground truth by the reconciliation job — otherwise a bad scrape could
    quarantine a perfectly fine ticker, or worse, validate a wrong
    adj_factor against an equally-wrong unconfirmed action."""
    ticker = "JKH.N0000"
    _seed_security(db_session, ticker)
    ex_date = dt.date(2024, 6, 1)
    day_before = ex_date - dt.timedelta(days=1)
    now = dt.datetime.now(dt.timezone.utc)

    db_session.add_all(
        [
            PriceDaily(
                ticker=ticker, date=day_before, close=Decimal("100.00"), adj_factor=Decimal("1.0"), fetched_at=now
            ),
            PriceDaily(
                ticker=ticker, date=ex_date, close=Decimal("50.00"), adj_factor=Decimal("1.0"), fetched_at=now
            ),
            CorporateAction(
                ticker=ticker,
                ex_date=ex_date,
                type=DbActionType.BONUS_ISSUE,
                ratio=Decimal("1"),
                confirmed_by=None,  # NOT confirmed
                confirmed_at=None,
            ),
        ]
    )
    db_session.commit()

    # Both adj_factors are 1.0 and the (ignored, unconfirmed) event would
    # otherwise force a 0.5 recompute for day_before -> should reconcile
    # cleanly against "no confirmed events" rather than flag a mismatch
    # against an action nobody has signed off on.
    alert = reconcile_ticker(db_session, ticker)
    assert alert is None


def test_a_confirmed_dividend_with_no_close_before_ex_does_not_abort_the_sweep(db_session):
    """Regression, 3 Sep 2026: a confirmed cash dividend whose ex-date
    predates our price history (so there is no close on the day before
    it) made `price_ratio_for_event` raise `ValueError`, which propagated
    out of `run_nightly_reconciliation`'s loop and killed the reconciliation
    for EVERY ticker. The recomputation must use the same `usable_events`
    filter the stored-factor builder uses and simply exclude that event."""
    from app.jobs.reconciliation import run_nightly_reconciliation

    ticker = "DIV.N0000"
    _seed_security(db_session, ticker)
    now = dt.datetime.now(dt.timezone.utc)

    # Price history starts 2024; the dividend's ex-date is 2019.
    db_session.add_all(
        [
            PriceDaily(ticker=ticker, date=dt.date(2024, 1, 2), close=Decimal("80.00"),
                       adj_factor=Decimal("1.0"), fetched_at=now),
            PriceDaily(ticker=ticker, date=dt.date(2024, 1, 3), close=Decimal("81.00"),
                       adj_factor=Decimal("1.0"), fetched_at=now),
            CorporateAction(
                ticker=ticker, ex_date=dt.date(2019, 5, 10),
                type=DbActionType.DIVIDEND_CASH, cash_amount=Decimal("2.50"),
                confirmed_by="analyst", confirmed_at=now,
            ),
        ]
    )
    db_session.commit()

    # Neither call raises; the pre-history dividend affects no stored date.
    assert reconcile_ticker(db_session, ticker) is None
    results = run_nightly_reconciliation(db_session, [ticker])
    assert results == {ticker: None}
