"""§35's real HML_hard factor wired end to end — app.domain.factor_library_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.factor_library_view import DEFAULT_LOOKBACK_DAYS, hml_hard_for
from app.domain.portfolio_sort import MIN_TICKERS
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 18)
PERIOD_END = dt.date(2025, 12, 31)
FIRST_AVAILABLE = dt.date(2026, 3, 1)


def _seed_full_ticker(
    db, ticker: str, *, shares: int, total_equity: Decimal,
    start_price: Decimal, end_price: Decimal,
):
    """Every real input HML_hard needs: shares_issued, a confirmed
    total_equity (no revaluation_reserves line — hard book equals
    reported book for this fixture), and real prices at both the
    formation date and as_of."""
    now = dt.datetime.now(dt.timezone.utc)
    formation = AS_OF - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)
    db.add(Security(ticker=ticker, name=ticker))
    db.add(FloatData(ticker=ticker, as_of=dt.date(2026, 1, 1), shares_issued=shares))
    db.add(Fundamental(
        ticker=ticker, period_end=PERIOD_END, period_type="annual",
        first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
        value=total_equity, provenance_tier=ProvenanceTier.REPORTED,
    ))
    db.add(PriceDaily(ticker=ticker, date=formation, close=start_price, adj_factor=Decimal("1"), fetched_at=now))
    db.add(PriceDaily(ticker=ticker, date=AS_OF, close=end_price, adj_factor=Decimal("1"), fetched_at=now))
    db.commit()


class TestHmlHardFor:
    def test_no_data_gives_no_result(self, db_session):
        view = hml_hard_for(db_session, AS_OF)
        assert view.result is None
        assert view.included_ticker_count == 0

    def test_a_ticker_missing_each_real_input_is_named_not_silently_dropped(self, db_session):
        now = dt.datetime.now(dt.timezone.utc)
        formation = AS_OF - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)

        # NO_FLOAT: has fundamentals + prices, but no FloatData at all.
        db_session.add(Security(ticker="NOFLOAT.N0000", name="No Float"))
        db_session.add(Fundamental(
            ticker="NOFLOAT.N0000", period_end=PERIOD_END, period_type="annual",
            first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
            value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
        ))
        db_session.add(PriceDaily(ticker="NOFLOAT.N0000", date=formation, close=Decimal(100), adj_factor=Decimal("1"), fetched_at=now))
        db_session.add(PriceDaily(ticker="NOFLOAT.N0000", date=AS_OF, close=Decimal(110), adj_factor=Decimal("1"), fetched_at=now))

        # NO_BOOK: has FloatData + prices, but no confirmed fundamentals.
        db_session.add(Security(ticker="NOBOOK.N0000", name="No Book"))
        db_session.add(FloatData(ticker="NOBOOK.N0000", as_of=dt.date(2026, 1, 1), shares_issued=1000))
        db_session.add(PriceDaily(ticker="NOBOOK.N0000", date=formation, close=Decimal(100), adj_factor=Decimal("1"), fetched_at=now))
        db_session.add(PriceDaily(ticker="NOBOOK.N0000", date=AS_OF, close=Decimal(110), adj_factor=Decimal("1"), fetched_at=now))
        db_session.commit()

        view = hml_hard_for(db_session, AS_OF)
        reasons = dict(view.excluded)
        assert "NOFLOAT.N0000" in reasons and "market cap" in reasons["NOFLOAT.N0000"]
        assert "NOBOOK.N0000" in reasons and "hard book" in reasons["NOBOOK.N0000"]
        assert view.included_ticker_count == 0

    def test_a_full_real_universe_produces_a_real_sort_result(self, db_session):
        """12 real tickers, every one with all three real inputs — two
        per each of the six final S/B x L/M/H buckets by construction
        (style ratios chosen as a fraction of each ticker's own market
        cap, so the size split doesn't drag every small ticker into one
        style tercile the way a size-independent book value would),
        enough to clear MIN_TICKERS and produce a genuine, fully-
        populated 2x3 sort."""
        assert MIN_TICKERS == 12
        # Twelve pairwise-distinct style ratios, two per size group in
        # each of low/mid/high, plus a small per-ticker share-count
        # offset so real market caps aren't perfectly tied within each
        # size group — verified directly (a scratch run against `app.
        # domain.portfolio_sort.two_by_three_sort` before this fixture
        # was written) to avoid landing exactly on a percentile-boundary
        # tie, which `_percentile`'s own nearest-rank combined with a
        # strict "> p70"/size "<= median" test can otherwise turn into a
        # real, degenerate all-in-one-bucket split — a property of that
        # boundary rule worth designing the fixture around, not a bug
        # this test exists to probe.
        style_ratios = [
            Decimal("0.03"), Decimal("0.06"), Decimal("0.28"), Decimal("0.33"),
            Decimal("0.58"), Decimal("0.63"),
        ]
        for i in range(12):
            small = i < 6
            shares = (10_000 + i) if small else (10_000_000 + i)
            price = Decimal("100")
            cap = Decimal(shares) * price
            style_ratio = style_ratios[i % 6]
            total_equity = style_ratio * cap
            end_price = price * (Decimal("1.1") if i % 3 == 0 else Decimal("1.02"))
            _seed_full_ticker(
                db_session, f"T{i}.N0000",
                shares=shares, total_equity=total_equity,
                start_price=price, end_price=end_price,
            )

        view = hml_hard_for(db_session, AS_OF)
        assert view.included_ticker_count == 12
        assert view.excluded == ()
        assert view.result is not None
        assert sum(view.result.portfolio_counts.values()) == 12
        assert all(count > 0 for count in view.result.portfolio_counts.values())
