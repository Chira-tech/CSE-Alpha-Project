"""app.domain.price_returns — real adjusted-return computation shared
across §30/§33/§35's own view modules. No dedicated test file existed
before this one; `ticker_adjusted_returns` had only ever been exercised
indirectly through its callers' own tests."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.price_returns import cumulative_adjusted_return, ticker_adjusted_returns
from app.models.prices import PriceDaily

TICKER = "COMB.N0000"


def _seed(db, rows: list[tuple[dt.date, Decimal, Decimal]]):
    now = dt.datetime.now(dt.timezone.utc)
    db.add_all(
        PriceDaily(ticker=TICKER, date=d, close=c, adj_factor=af, fetched_at=now)
        for d, c, af in rows
    )
    db.commit()


class TestTickerAdjustedReturns:
    def test_hand_worked_two_day_return(self, db_session):
        _seed(db_session, [
            (dt.date(2026, 1, 1), Decimal("100"), Decimal("1")),
            (dt.date(2026, 1, 2), Decimal("110"), Decimal("1")),
        ])
        returns = ticker_adjusted_returns(db_session, TICKER, dt.date(2026, 1, 2), 30)
        assert returns == {dt.date(2026, 1, 2): Decimal("0.1")}

    def test_adj_factor_is_applied_not_just_close(self, db_session):
        """A real corporate action's own adjustment factor must change
        the computed return, not just the raw close-to-close move."""
        _seed(db_session, [
            (dt.date(2026, 1, 1), Decimal("100"), Decimal("1")),
            (dt.date(2026, 1, 2), Decimal("50"), Decimal("2")),  # a real 2-for-1 split, adj_factor doubles
        ])
        returns = ticker_adjusted_returns(db_session, TICKER, dt.date(2026, 1, 2), 30)
        # adjusted close: 100*1=100 -> 50*2=100, a real 0% total return, not a spurious -50%.
        assert returns == {dt.date(2026, 1, 2): Decimal("0")}


class TestCumulativeAdjustedReturn:
    def test_none_when_the_ticker_only_starts_trading_after_the_window(self, db_session):
        """The only real way to be missing a `start` price while `end`
        is still in range: the ticker's own first real observation
        falls strictly after `start` but on or before `end` — a real,
        reachable case (a newer listing), unlike a missing `end` price
        with a present `start` price, which is impossible whenever
        `start <= end` (any real row on or before `start` is also on or
        before `end`)."""
        _seed(db_session, [(dt.date(2026, 6, 1), Decimal("100"), Decimal("1"))])
        assert cumulative_adjusted_return(db_session, TICKER, dt.date(2026, 1, 1), dt.date(2026, 6, 1)) is None

    def test_none_with_no_real_data_at_all(self, db_session):
        assert cumulative_adjusted_return(db_session, TICKER, dt.date(2026, 1, 1), dt.date(2026, 6, 1)) is None

    def test_hand_worked_cumulative_return(self, db_session):
        _seed(db_session, [
            (dt.date(2026, 1, 1), Decimal("100"), Decimal("1")),
            (dt.date(2026, 6, 1), Decimal("125"), Decimal("1")),
        ])
        result = cumulative_adjusted_return(db_session, TICKER, dt.date(2026, 1, 1), dt.date(2026, 6, 1))
        assert result == Decimal("0.25")

    def test_uses_the_most_recent_real_price_on_or_before_each_endpoint(self, db_session):
        """Neither endpoint date itself has a real observation — the
        function correctly falls back to the most recent real price on
        or before each, the same point-in-time convention used
        elsewhere in this system."""
        _seed(db_session, [
            (dt.date(2025, 12, 30), Decimal("100"), Decimal("1")),  # nearest real price before Jan 1
            (dt.date(2026, 5, 29), Decimal("150"), Decimal("1")),  # nearest real price before Jun 1
        ])
        result = cumulative_adjusted_return(db_session, TICKER, dt.date(2026, 1, 1), dt.date(2026, 6, 1))
        assert result == Decimal("0.5")

    def test_adj_factor_is_applied(self, db_session):
        _seed(db_session, [
            (dt.date(2026, 1, 1), Decimal("100"), Decimal("1")),
            (dt.date(2026, 6, 1), Decimal("55"), Decimal("2")),  # a real 2-for-1 split along the way
        ])
        result = cumulative_adjusted_return(db_session, TICKER, dt.date(2026, 1, 1), dt.date(2026, 6, 1))
        # adjusted: 100*1=100 -> 55*2=110, a real +10% total return.
        assert result == Decimal("0.1")
