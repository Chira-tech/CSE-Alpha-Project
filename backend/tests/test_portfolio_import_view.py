"""app.domain.portfolio_import_view — real snapshot storage and lookup."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.portfolio_import_parsing import ParsedPortfolio, ParsedPosition
from app.domain.portfolio_import_view import (
    latest_snapshot,
    list_snapshots,
    store_portfolio_snapshot,
    unrecognized_tickers,
)
from app.models.securities import Security


def _sample_parsed(ticker: str = "JKH.N0000") -> ParsedPortfolio:
    return ParsedPortfolio(
        positions=(
            ParsedPosition(
                ticker=ticker, quantity=Decimal("1000"), avg_price=Decimal("20.224"),
                total_cost=Decimal("20224.0"), traded_price=Decimal("20.0"),
                market_value=Decimal("20000.0"), unrealized_gain_loss=Decimal("-448.0"),
            ),
        ),
        stated_total_cost=Decimal("20224.0"), stated_total_market_value=Decimal("20000.0"),
        identity_check_passed=True, identity_check_note="ok",
    )


class TestStorePortfolioSnapshot:
    def test_stores_a_real_snapshot_and_its_positions(self, db_session):
        snapshot = store_portfolio_snapshot(db_session, _sample_parsed(), source_filename="Portfolio.xlsx")
        assert snapshot.id is not None
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0].ticker == "JKH.N0000"
        assert snapshot.identity_check_passed is True

    def test_two_uploads_create_two_separate_snapshots_neither_overwritten(self, db_session):
        first = store_portfolio_snapshot(db_session, _sample_parsed(), source_filename="Portfolio (1).xlsx")
        second = store_portfolio_snapshot(db_session, _sample_parsed("CBNK.N0000"), source_filename="Portfolio (2).xlsx")
        assert first.id != second.id
        all_snapshots = list_snapshots(db_session)
        assert len(all_snapshots) == 2
        # The first snapshot's own positions are untouched by the second upload.
        assert all_snapshots[-1].positions[0].ticker in ("JKH.N0000", "CBNK.N0000")


class TestLatestSnapshot:
    def test_none_with_no_uploads(self, db_session):
        assert latest_snapshot(db_session) is None

    def test_returns_the_most_recently_uploaded_one(self, db_session):
        store_portfolio_snapshot(
            db_session, _sample_parsed(), source_filename="old.xlsx",
            uploaded_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        store_portfolio_snapshot(
            db_session, _sample_parsed("CBNK.N0000"), source_filename="new.xlsx",
            uploaded_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
        )
        latest = latest_snapshot(db_session)
        assert latest is not None
        assert latest.source_filename == "new.xlsx"


class TestUnrecognizedTickers:
    def test_names_a_real_held_ticker_this_system_does_not_recognise(self, db_session):
        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        db_session.commit()
        snapshot = store_portfolio_snapshot(
            db_session, _sample_parsed("DELISTED.X0000"), source_filename="Portfolio.xlsx"
        )
        assert unrecognized_tickers(db_session, snapshot) == ["DELISTED.X0000"]

    def test_empty_when_every_ticker_is_known(self, db_session):
        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        db_session.commit()
        snapshot = store_portfolio_snapshot(db_session, _sample_parsed(), source_filename="Portfolio.xlsx")
        assert unrecognized_tickers(db_session, snapshot) == []
