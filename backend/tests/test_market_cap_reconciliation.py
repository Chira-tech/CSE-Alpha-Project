"""app.jobs.market_cap_reconciliation — TASK 0.1's nightly universe-wide
market-cap cross-check, distinct from the live per-company sanity gate
(app.domain.sanity) but sharing the same real, independently-published
`FloatData.published_market_cap` figure."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.jobs.market_cap_reconciliation import ALERT_TYPE, check_ticker
from app.models.data_quality import DataAlert
from app.models.float_data import FloatData
from app.models.prices import PriceDaily
from app.models.securities import Security

TICKER = "COMB.N0000"
AS_OF = dt.date(2026, 8, 18)


def _seed(db, *, shares=1000, close=Decimal("200.00"), published_mcap=Decimal("200000")):
    db.add(Security(ticker=TICKER, name="Commercial Bank of Ceylon PLC"))
    db.add(
        PriceDaily(
            ticker=TICKER, date=AS_OF, close=close,
            fetched_at=dt.datetime(2026, 8, 18, 15, 0, tzinfo=dt.timezone.utc), source="cse.lk",
        )
    )
    db.add(
        FloatData(
            ticker=TICKER, as_of=AS_OF, shares_issued=shares, published_market_cap=published_mcap
        )
    )
    db.commit()


class TestCheckTicker:
    def test_reconciling_market_cap_raises_no_alert(self, db_session):
        _seed(db_session)  # 1000 * 200 = 200,000, matches published exactly

        assert check_ticker(db_session, TICKER, AS_OF) is None
        assert db_session.query(DataAlert).count() == 0

    def test_mismatch_beyond_two_percent_raises_an_alert(self, db_session):
        _seed(db_session, published_mcap=Decimal("400000"))  # local = 200,000, 2x off

        alert = check_ticker(db_session, TICKER, AS_OF)

        assert alert is not None
        assert alert.ticker == TICKER
        assert alert.alert_type == ALERT_TYPE
        assert alert.resolved is False

    def test_a_second_check_does_not_duplicate_the_open_alert(self, db_session):
        _seed(db_session, published_mcap=Decimal("400000"))
        check_ticker(db_session, TICKER, AS_OF)

        check_ticker(db_session, TICKER, AS_OF)

        rows = db_session.query(DataAlert).filter(DataAlert.alert_type == ALERT_TYPE).all()
        assert len(rows) == 1

    def test_missing_published_market_cap_is_skipped_not_alerted(self, db_session):
        db_session.add(Security(ticker=TICKER, name="Commercial Bank of Ceylon PLC"))
        db_session.add(
            PriceDaily(
                ticker=TICKER, date=AS_OF, close=Decimal("200.00"),
                fetched_at=dt.datetime(2026, 8, 18, 15, 0, tzinfo=dt.timezone.utc), source="cse.lk",
            )
        )
        db_session.add(FloatData(ticker=TICKER, as_of=AS_OF, shares_issued=1000))  # no published_market_cap
        db_session.commit()

        assert check_ticker(db_session, TICKER, AS_OF) is None
        assert db_session.query(DataAlert).count() == 0

    def test_a_later_reconciling_check_auto_resolves_the_open_alert(self, db_session):
        _seed(db_session, published_mcap=Decimal("400000"))
        check_ticker(db_session, TICKER, AS_OF)

        # A later FloatData snapshot corrects the published figure.
        db_session.add(
            FloatData(
                ticker=TICKER, as_of=AS_OF + dt.timedelta(days=1),
                shares_issued=1000, published_market_cap=Decimal("200000"),
            )
        )
        db_session.commit()

        result = check_ticker(db_session, TICKER, AS_OF + dt.timedelta(days=1))

        assert result is None
        open_alerts = db_session.query(DataAlert).filter(
            DataAlert.alert_type == ALERT_TYPE, DataAlert.resolved.is_(False)
        ).count()
        assert open_alerts == 0
