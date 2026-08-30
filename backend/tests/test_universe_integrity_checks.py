"""
`app.jobs.universe_integrity_checks` — the enforcing nightly sweep for
`docs/CSE_Universe_Integrity_Rollout.md` Phase 2. Uses the AAF rights
issue as the worked example, the same real known-wrong case the spec is
built around.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import universe_integrity as ui
from app.jobs.universe_integrity_checks import check_ticker, run_nightly_universe_integrity
from app.models.corporate_actions import CorporateAction, CorporateActionType
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 30)
FETCHED = dt.datetime(2026, 8, 30, 15, 0, tzinfo=dt.timezone.utc)


def _price(db, ticker, date, close):
    db.add(PriceDaily(ticker=ticker, date=date, close=Decimal(str(close)), fetched_at=FETCHED, source="cse.lk"))


def _aaf_rights_issue(db, *, ex_date=dt.date(2026, 8, 15)):
    db.add(
        CorporateAction(
            ticker="AAF.N0000",
            ex_date=ex_date,
            type=CorporateActionType.RIGHTS_ISSUE,
            ratio=Decimal("4") / Decimal("11"),
            subscription_price=Decimal("33.30"),
            cum_rights_price=Decimal("49.10"),
            terp=Decimal("44.89"),
            confirmed_by="analyst",
            confirmed_at=FETCHED,
        )
    )


def test_ordinary_line_bound_to_the_rights_price_is_quarantined(db_session):
    db_session.add(Security(ticker="AAF.N0000", name="Asia Asset Finance PLC", instrument_type="ordinary"))
    _aaf_rights_issue(db_session)
    # The bound "price" series is sitting at the nil-paid rights level.
    _price(db_session, "AAF.N0000", AS_OF, "11.30")
    db_session.commit()

    raised = check_ticker(db_session, "AAF.N0000", AS_OF)
    db_session.commit()

    types = {a.alert_type for a in raised}
    assert ui.ALERT_RIGHTS_PRICE_INCOHERENT in types  # 11.30 <= 33.30 subscription
    assert ui.ALERT_WRONG_LINE_FINGERPRINT in types   # 11.30 + 33.30 ≈ TERP 44.89


def test_ordinary_line_at_the_real_price_is_clean(db_session):
    db_session.add(Security(ticker="AAF.N0000", name="Asia Asset Finance PLC", instrument_type="ordinary"))
    _aaf_rights_issue(db_session)
    _price(db_session, "AAF.N0000", AS_OF, "49.10")
    db_session.commit()

    raised = check_ticker(db_session, "AAF.N0000", AS_OF)
    assert raised == []


def test_alerts_are_idempotent_and_self_heal(db_session):
    db_session.add(Security(ticker="AAF.N0000", name="Asia Asset Finance PLC", instrument_type="ordinary"))
    _aaf_rights_issue(db_session)
    _price(db_session, "AAF.N0000", AS_OF, "11.30")
    db_session.commit()

    check_ticker(db_session, "AAF.N0000", AS_OF)
    db_session.commit()
    check_ticker(db_session, "AAF.N0000", AS_OF)  # second run
    db_session.commit()
    open_rows = db_session.query(DataAlert).filter(
        DataAlert.alert_type == ui.ALERT_RIGHTS_PRICE_INCOHERENT, DataAlert.resolved.is_(False)
    ).all()
    assert len(open_rows) == 1  # not spammed

    # The data is fixed (rebound to the real price) — the alert resolves itself.
    db_session.query(PriceDaily).filter(PriceDaily.ticker == "AAF.N0000").delete()
    _price(db_session, "AAF.N0000", AS_OF, "49.10")
    db_session.commit()
    check_ticker(db_session, "AAF.N0000", AS_OF)
    db_session.commit()
    still_open = db_session.query(DataAlert).filter(
        DataAlert.alert_type == ui.ALERT_RIGHTS_PRICE_INCOHERENT, DataAlert.resolved.is_(False)
    ).count()
    assert still_open == 0


def test_unexplained_price_discontinuity_is_flagged(db_session):
    db_session.add(Security(ticker="ABL.N0000", name="Amana Bank PLC", instrument_type="ordinary"))
    _price(db_session, "ABL.N0000", dt.date(2026, 8, 27), "10.00")
    _price(db_session, "ABL.N0000", dt.date(2026, 8, 28), "95.00")  # +850%, no CA
    _price(db_session, "ABL.N0000", AS_OF, "96.00")
    db_session.commit()

    raised = check_ticker(db_session, "ABL.N0000", AS_OF)
    db_session.commit()
    assert any(a.alert_type == ui.ALERT_PRICE_DISCONTINUITY for a in raised)


def test_discontinuity_on_a_corporate_action_date_is_not_flagged(db_session):
    db_session.add(Security(ticker="ABL.N0000", name="Amana Bank PLC", instrument_type="ordinary"))
    db_session.add(
        CorporateAction(
            ticker="ABL.N0000", ex_date=dt.date(2026, 8, 28), type=CorporateActionType.STOCK_SPLIT,
            ratio=Decimal("10"), confirmed_by="a", confirmed_at=FETCHED,
        )
    )
    _price(db_session, "ABL.N0000", dt.date(2026, 8, 27), "100.00")
    _price(db_session, "ABL.N0000", dt.date(2026, 8, 28), "10.00")  # 1→10 split, expected
    _price(db_session, "ABL.N0000", AS_OF, "10.50")
    db_session.commit()

    raised = check_ticker(db_session, "ABL.N0000", AS_OF)
    assert not any(a.alert_type == ui.ALERT_PRICE_DISCONTINUITY for a in raised)


def test_expired_rights_line_is_reaped(db_session):
    db_session.add(
        Security(ticker="AAF.R0000", name="Asia Asset Finance PLC", instrument_type="rights")
    )
    _price(db_session, "AAF.R0000", dt.date(2026, 7, 1), "15.40")  # last trade ~60 days ago
    db_session.commit()

    check_ticker(db_session, "AAF.R0000", AS_OF)
    db_session.commit()

    sec = db_session.get(Security, "AAF.R0000")
    assert sec.delisting_date == dt.date(2026, 7, 1)
    assert (
        db_session.query(DataAlert)
        .filter(DataAlert.alert_type == ui.ALERT_RIGHTS_LINE_EXPIRED, DataAlert.resolved.is_(False))
        .count()
        == 1
    )


def test_run_nightly_returns_a_result_per_ticker(db_session):
    db_session.add_all(
        [
            Security(ticker="AAF.N0000", name="AAF", instrument_type="ordinary"),
            Security(ticker="COMB.N0000", name="COMB", instrument_type="ordinary"),
        ]
    )
    _price(db_session, "COMB.N0000", AS_OF, "200.00")
    db_session.commit()

    results = run_nightly_universe_integrity(db_session, ["AAF.N0000", "COMB.N0000"], AS_OF)
    assert set(results) == {"AAF.N0000", "COMB.N0000"}
