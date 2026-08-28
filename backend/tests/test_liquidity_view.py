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


class TestUniversePercentilesSharing:
    """The SECOND half of the "89 seconds for 9 positions" fix class,
    found live (20 Aug 2026): sharing `universe_ratios` alone still left
    `percentile_rank` — an O(n²) full universe re-ranking — running fresh
    on every call. Profiled live: 1,526 calls in one real `/opportunities`
    request, ~24 of its ~25 real seconds. `universe_percentiles` is the
    fix — the same "caller computes once, threads it through" shape as
    `universe_ratios` itself."""

    def test_a_precomputed_universe_percentiles_dict_is_used_directly(self, db_session, monkeypatch):
        """Proves `universe_percentiles`, when supplied, is trusted as-is
        — the function never needs to (and must not) call `percentile_
        rank` again to get the same answer."""
        import app.domain.liquidity_view as liquidity_view_module

        def fail_if_called(*args, **kwargs):
            raise AssertionError("percentile_rank must not be called when universe_percentiles is supplied")

        monkeypatch.setattr(liquidity_view_module, "percentile_rank", fail_if_called)

        result = liquidity_percentile_for(
            db_session, "ANY.N0000", AS_OF,
            universe_percentiles={"ANY.N0000": Decimal("42")},
        )
        assert result == Decimal("42")

    def test_a_ticker_absent_from_the_precomputed_dict_is_none(self, db_session):
        result = liquidity_percentile_for(
            db_session, "MISSING.N0000", AS_OF,
            universe_percentiles={"OTHER.N0000": Decimal("10")},
        )
        assert result is None

    def test_percentile_rank_runs_once_across_many_tickers_when_shared(self, db_session, monkeypatch):
        """The actual regression this fix closes: `opportunity_ranking_
        for`'s own shape (percentile_rank computed once, threaded through
        every one of several per-ticker calls) must call the expensive
        O(n²) function exactly once, not once per ticker."""
        import app.domain.liquidity as liquidity_module
        import app.domain.liquidity_view as liquidity_view_module

        call_count = 0
        real_percentile_rank = liquidity_module.percentile_rank

        def counting_percentile_rank(ratios):
            nonlocal call_count
            call_count += 1
            return real_percentile_rank(ratios)

        monkeypatch.setattr(liquidity_view_module, "percentile_rank", counting_percentile_rank)

        ratios = {f"T{i}.N0000": Decimal(i + 1) for i in range(20)}
        # The correct usage: compute once, thread the RESULT through.
        universe_percentiles = counting_percentile_rank(ratios)
        for i in range(20):
            liquidity_percentile_for(
                db_session, f"T{i}.N0000", AS_OF,
                universe_ratios=ratios, universe_percentiles=universe_percentiles,
            )

        assert call_count == 1
