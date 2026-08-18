"""app.domain.liquidity_view wired to real stored data."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.liquidity import MIN_OBSERVATIONS
from app.domain.liquidity_view import liquidity_percentile_for, universe_amihud_ratios
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 18)


def _seed_ticker(db, ticker: str, closes: list[Decimal], volumes: list[int], base: dt.date):
    now = dt.datetime.now(dt.timezone.utc)
    db.add(Security(ticker=ticker, name=ticker))
    db.add_all(
        PriceDaily(
            ticker=ticker, date=base + dt.timedelta(days=i), close=c,
            volume=v, adj_factor=Decimal("1"), fetched_at=now,
        )
        for i, (c, v) in enumerate(zip(closes, volumes))
    )
    db.commit()


class TestUniverseAmihudRatios:
    def test_no_price_data_gives_an_empty_universe(self, db_session):
        assert universe_amihud_ratios(db_session, AS_OF) == {}

    def test_a_thin_ticker_and_a_liquid_ticker_rank_as_expected(self, db_session):
        n = MIN_OBSERVATIONS + 5
        base = dt.date(2026, 1, 1)

        # THIN.N0000: a real, meaningful price move on tiny volume every day.
        thin_closes = [Decimal(100) * (Decimal("1.05") ** i) for i in range(n)]
        thin_volumes = [50] * n
        _seed_ticker(db_session, "THIN.N0000", thin_closes, thin_volumes, base)

        # LIQUID.N0000: a tiny price move on huge volume every day.
        liquid_closes = [Decimal(100) * (Decimal("1.001") ** i) for i in range(n)]
        liquid_volumes = [5_000_000] * n
        _seed_ticker(db_session, "LIQUID.N0000", liquid_closes, liquid_volumes, base)

        ratios = universe_amihud_ratios(db_session, AS_OF)
        assert set(ratios) == {"THIN.N0000", "LIQUID.N0000"}
        assert ratios["THIN.N0000"] > ratios["LIQUID.N0000"]

        thin_pct = liquidity_percentile_for(db_session, "THIN.N0000", AS_OF)
        liquid_pct = liquidity_percentile_for(db_session, "LIQUID.N0000", AS_OF)
        assert liquid_pct > thin_pct
        assert liquid_pct == Decimal(100)
        assert thin_pct == Decimal(0)

    def test_a_ticker_with_too_little_history_is_absent_not_defaulted(self, db_session):
        base = dt.date(2026, 1, 1)
        closes = [Decimal(100)] * (MIN_OBSERVATIONS - 5)
        volumes = [1000] * (MIN_OBSERVATIONS - 5)
        _seed_ticker(db_session, "TOOTHIN.N0000", closes, volumes, base)

        assert universe_amihud_ratios(db_session, AS_OF) == {}
        assert liquidity_percentile_for(db_session, "TOOTHIN.N0000", AS_OF) is None
