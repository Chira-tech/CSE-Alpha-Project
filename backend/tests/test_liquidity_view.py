"""app.domain.liquidity_view wired to real stored data."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.liquidity import MIN_OBSERVATIONS
from app.domain.liquidity_view import (
    liquidity_percentile_for,
    liquidity_snapshot_for,
    universe_amihud_ratios,
)
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


class TestLiquiditySnapshotFor:
    """Found live (30 Aug 2026) auditing real ranked "opportunities":
    the ranking had no liquidity check at all, so a stock trading a few
    thousand rupees a day could rank as a top "Accumulate" purely on
    discount-to-book. This is the real-data half of the fix."""

    def test_a_real_median_and_day_count_over_the_window(self, db_session):
        base = AS_OF - dt.timedelta(days=59)
        # 60 real trading days, close=100 flat, volume varies so the
        # median is unambiguous (sorted: ..., 1000, 2000, 3000, ...).
        closes = [Decimal(100)] * 60
        volumes = list(range(1000, 61000, 1000))
        _seed_ticker(db_session, "REAL.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "REAL.N0000", AS_OF)

        assert snap.days_traded_60d == 60
        # median volume = 30500 (60 even values) -> turnover = 100 * 30500
        assert snap.median_daily_turnover_60d_lkr == Decimal("3050000")
        assert snap.days_of_real_history_available == 60

    def test_a_ticker_with_no_real_trading_gets_the_honest_zero_snapshot(self, db_session):
        db_session.add(Security(ticker="DEAD.N0000", name="DEAD.N0000"))
        db_session.commit()

        snap = liquidity_snapshot_for(db_session, "DEAD.N0000", AS_OF)

        assert snap.days_traded_60d == 0
        assert snap.median_daily_turnover_60d_lkr == Decimal(0)
        assert snap.days_of_real_history_available == 0

    def test_real_history_available_is_capped_at_the_window_even_with_deeper_data(self, db_session):
        base = AS_OF - dt.timedelta(days=399)  # far deeper than the 60-day window
        closes = [Decimal(100)] * 400
        volumes = [1000] * 400
        _seed_ticker(db_session, "LONGHISTORY.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "LONGHISTORY.N0000", AS_OF)
        assert snap.days_of_real_history_available == 60

    def test_real_history_available_reflects_a_real_recent_listing_or_shallow_capture(self, db_session):
        """Found live (30 Aug 2026): this system's own forward-captured
        price history doesn't span 60 real SESSION ROWS for any ticker
        yet, including the exchange's own most liquid names. A caller
        needs this real figure to tell "this stock genuinely doesn't
        trade" apart from "not enough real sessions exist yet to judge
        that"."""
        base = AS_OF - dt.timedelta(days=19)
        closes = [Decimal(100)] * 20
        volumes = [50_000_000] * 20  # genuinely liquid, just newly on file
        _seed_ticker(db_session, "RECENT.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "RECENT.N0000", AS_OF)
        assert snap.days_of_real_history_available == 20
        assert snap.days_traded_60d == 20

    def test_zero_volume_sessions_are_not_counted_as_traded_days(self, db_session):
        """A stored row with volume=0 (a session with no real trade, but
        a placeholder row on file) must not count toward days_traded —
        it isn't a real trading day."""
        base = AS_OF - dt.timedelta(days=9)
        closes = [Decimal(100)] * 10
        volumes = [0, 0, 0, 0, 0, 0, 0, 0, 500, 500]
        _seed_ticker(db_session, "MOSTLYDEAD.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "MOSTLYDEAD.N0000", AS_OF)
        assert snap.days_traded_60d == 2

    def test_only_counts_the_most_recent_60_real_sessions_not_a_calendar_span(self, db_session):
        """A ticker with real sessions on EVERY calendar day for 100
        real days must only count the most recent 60 real SESSION rows
        — not all 100, and not filtered by a calendar cutoff either
        (the real bug this whole fix closes: "60" means 60 real
        sessions, never 60 calendar days)."""
        base = AS_OF - dt.timedelta(days=99)
        closes = [Decimal(100)] * 100
        volumes = [1000] * 100
        _seed_ticker(db_session, "LONGRUNNING.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "LONGRUNNING.N0000", AS_OF)
        assert snap.days_traded_60d == 60
        assert snap.days_of_real_history_available == 60

    def test_sessions_older_than_the_real_stale_cutoff_do_not_count_as_current_liquidity(self, db_session):
        """A ticker whose only real trading happened over six months ago
        has gone quiet — its old sessions must not be resurrected as
        "the last 60" just because nothing more recent exists on file."""
        base = AS_OF - dt.timedelta(days=200)
        closes = [Decimal(100)] * 20
        volumes = [50_000_000] * 20  # would be very liquid, if current
        _seed_ticker(db_session, "GONEQUIET.N0000", closes, volumes, base)

        snap = liquidity_snapshot_for(db_session, "GONEQUIET.N0000", AS_OF)
        assert snap.days_traded_60d == 0
        assert snap.days_of_real_history_available == 0


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
