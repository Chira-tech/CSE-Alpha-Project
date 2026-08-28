"""§35's weekly factor return series builder — app.domain.factor_series_view.

The load-bearing test here is `test_bulk_market_cap_matches_the_trusted_
slow_path` — the whole computational-feasibility argument for bulk-
loading instead of calling `market_cap_for`/`hard_book_for` once per
ticker per week rests on the fast path agreeing with the slow, already-
trusted one, not just on the builder running without crashing.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.cbsl_parsing import SERIES_TBILL_91D
from app.domain.factor_series import (
    SERIES_FACTOR_HML_HARD, SERIES_FACTOR_LIQ, SERIES_FACTOR_MKT_RF, SERIES_FACTOR_MOM, SERIES_FACTOR_SMB,
)
from app.domain.factor_series_view import _market_cap, _load_price_history, _load_shares_issued, rebuild_factor_series
from app.domain.market_cap_view import market_cap_for
from app.domain.portfolio_sort import MIN_TICKERS
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily
from app.models.securities import Security

START = dt.date(2026, 1, 5)   # a Monday, formation baseline
AS_OF = dt.date(2026, 1, 26)  # three real weeks later


def _seed_universe(db, n: int = 12) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    style_ratios = [Decimal("0.03"), Decimal("0.06"), Decimal("0.28"), Decimal("0.33"), Decimal("0.58"), Decimal("0.63")]
    for i in range(n):
        ticker = f"T{i}.N0000"
        small = i < n // 2
        shares = (10_000 + i) if small else (10_000_000 + i)
        price = Decimal("100")
        cap = Decimal(shares) * price
        total_equity = style_ratios[i % 6] * cap

        db.add(Security(ticker=ticker, name=ticker))
        db.add(FloatData(ticker=ticker, as_of=dt.date(2025, 12, 1), shares_issued=shares))
        db.add(Fundamental(
            ticker=ticker, period_end=dt.date(2025, 9, 30), period_type="quarterly",
            first_available_date=dt.date(2025, 11, 1), version=1, statement_line="total_equity",
            value=total_equity, provenance_tier=ProvenanceTier.REPORTED,
        ))
        # Weekly-spaced real prices, drifting a little differently per ticker
        # so weekly returns aren't all identical (which would make every
        # bucket average to the same return and hide a real construction bug).
        d = START
        week = 0
        while d <= AS_OF:
            drift = Decimal("1.00") + (Decimal("0.01") if (i + week) % 2 == 0 else Decimal("-0.005"))
            week_price = price * (drift ** week)
            db.add(PriceDaily(ticker=ticker, date=d, close=week_price, adj_factor=Decimal("1"), volume=10_000, fetched_at=now))
            d += dt.timedelta(days=7)
            week += 1
    db.add(MacroSeries(
        series_id=SERIES_TBILL_91D, obs_date=START, first_available_date=START, value=Decimal("0.10"), source="manual",
    ))
    db.commit()


class TestRebuildFactorSeries:
    def test_no_data_produces_no_rows(self, db_session):
        summary = rebuild_factor_series(db_session, as_of=AS_OF)
        assert summary.formation_dates_attempted == 0
        assert all(v == 0 for v in summary.rows_written.values())

    def test_a_real_universe_writes_real_weekly_rows(self, db_session):
        assert MIN_TICKERS == 12
        _seed_universe(db_session, n=12)

        summary = rebuild_factor_series(db_session, as_of=AS_OF)
        assert summary.formation_dates_attempted >= 1
        # MKT-RF, SMB and HML_hard need only market cap + a weekly return +
        # (for HML_hard) hard book -- all real and present in this fixture.
        assert summary.rows_written[SERIES_FACTOR_MKT_RF] >= 1
        assert summary.rows_written[SERIES_FACTOR_SMB] >= 1
        assert summary.rows_written[SERIES_FACTOR_HML_HARD] >= 1

        rows = db_session.query(MacroSeries).filter(MacroSeries.series_id == SERIES_FACTOR_MKT_RF).all()
        assert len(rows) >= 1
        for row in rows:
            assert row.value is not None
            assert row.source == "computed:factor_series_view"
            assert row.first_available_date == row.obs_date

    def test_rerunning_overwrites_rather_than_duplicates(self, db_session):
        _seed_universe(db_session, n=12)
        rebuild_factor_series(db_session, as_of=AS_OF)
        first_count = db_session.query(MacroSeries).filter(MacroSeries.series_id == SERIES_FACTOR_MKT_RF).count()

        rebuild_factor_series(db_session, as_of=AS_OF)
        second_count = db_session.query(MacroSeries).filter(MacroSeries.series_id == SERIES_FACTOR_MKT_RF).count()
        assert second_count == first_count  # same weeks, not doubled

    def test_bulk_market_cap_matches_the_trusted_slow_path(self, db_session):
        """The load-bearing cross-check this whole module's performance
        argument rests on: the bulk in-memory `_market_cap` helper must
        agree with `market_cap_view.market_cap_for`'s own real, trusted,
        DB-querying computation for the same ticker/date."""
        _seed_universe(db_session, n=12)
        price_history = _load_price_history(db_session)
        shares_issued = _load_shares_issued(db_session)

        for ticker in ("T0.N0000", "T7.N0000"):
            for as_of in (START, START + dt.timedelta(days=14), AS_OF):
                bulk = _market_cap(price_history[ticker], shares_issued[ticker], as_of)
                slow = market_cap_for(db_session, ticker, as_of)
                assert bulk == slow, f"{ticker}@{as_of}: bulk={bulk} slow={slow}"

    def test_on_progress_can_stop_the_build_early(self, db_session):
        _seed_universe(db_session, n=12)
        calls: list[tuple[int, int, str]] = []

        def stop_after_one(done, total, message):
            calls.append((done, total, message))
            return done < 1

        summary = rebuild_factor_series(db_session, as_of=AS_OF, on_progress=stop_after_one)
        assert len(calls) == 1
        assert any("stopped early" in w for w in summary.warnings)
