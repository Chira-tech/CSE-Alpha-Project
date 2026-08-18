"""app.domain.market_cap_view wired to real stored data."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.market_cap_view import latest_shares_issued, market_cap_for
from app.models.float_data import FloatData
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 18)


def _seed_security(db, ticker="COMB.N0000"):
    db.add(Security(ticker=ticker, name="Commercial Bank of Ceylon PLC"))
    db.commit()


class TestLatestSharesIssued:
    def test_picks_latest_not_future(self, db_session):
        """Moved from test_valuation_view.py once app.domain.market_cap_
        view needed the exact same lookup a second time — see that
        module's own docstring. Uses its own local as_of (2022-06-01,
        matching the original test's own point-in-time boundary) rather
        than this file's module-level AS_OF (2026), which would leave no
        real "future" row to exclude."""
        as_of = dt.date(2022, 6, 1)
        _seed_security(db_session)
        db_session.add_all(
            [
                FloatData(ticker="COMB.N0000", as_of=dt.date(2021, 1, 1), shares_issued=90),
                FloatData(ticker="COMB.N0000", as_of=dt.date(2022, 1, 1), shares_issued=100),
                FloatData(ticker="COMB.N0000", as_of=dt.date(2023, 1, 1), shares_issued=110),  # after as_of
            ]
        )
        db_session.commit()
        assert latest_shares_issued(db_session, "COMB.N0000", as_of) == 100


class TestMarketCapFor:
    def test_none_without_shares_issued(self, db_session):
        _seed_security(db_session)
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add(PriceDaily(ticker="COMB.N0000", date=AS_OF, close=Decimal("100"), adj_factor=Decimal("1"), fetched_at=now))
        db_session.commit()
        assert market_cap_for(db_session, "COMB.N0000", AS_OF) is None

    def test_none_without_a_real_price(self, db_session):
        _seed_security(db_session)
        db_session.add(FloatData(ticker="COMB.N0000", as_of=AS_OF, shares_issued=1000))
        db_session.commit()
        assert market_cap_for(db_session, "COMB.N0000", AS_OF) is None

    def test_hand_worked_market_cap(self, db_session):
        _seed_security(db_session)
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add(FloatData(ticker="COMB.N0000", as_of=dt.date(2026, 1, 1), shares_issued=1_000_000))
        db_session.add(PriceDaily(ticker="COMB.N0000", date=AS_OF, close=Decimal("205.75"), adj_factor=Decimal("1"), fetched_at=now))
        db_session.commit()
        assert market_cap_for(db_session, "COMB.N0000", AS_OF) == Decimal("205750000.00")
