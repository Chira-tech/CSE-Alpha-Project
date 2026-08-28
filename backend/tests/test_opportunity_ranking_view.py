"""app.domain.opportunity_ranking_view — a real, currently-computable
subset of §40's opportunity ranking (see that module's own docstring
for exactly what's real here versus what the full spec still needs)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.opportunity_ranking_view import opportunity_ranking_for
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)
AS_OF = dt.date(2022, 6, 1)


def _fake_ke(ke, rf=Decimal("0.12")):
    def _fn(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=ke, risk_free_rate=rf, beta=Decimal("1.0"), erp_effective=Decimal("0.07"),
            beta_times_erp=Decimal("0.07"), size_premium=None, illiquidity_premium=None,
            implied_erp_cross_check=None, is_lower_bound=True, missing_components=(),
            note="stub",
        )
    return _fn


def _seed_security(db, ticker, name, archetype="bank"):
    # `opportunity_ranking_view` reads archetype from the stored
    # `Security` row (unlike `valuation_summary_for`'s own tests, which
    # pass it directly as a parameter) — must be seeded here for routing
    # to pick the same real anchors (justified P/B + residual income)
    # the hand-worked fixture values below assume.
    db.add(Security(ticker=ticker, name=name, archetype=archetype))
    db.commit()


def _seed_confirmed_fundamentals(db, ticker, total_equity=Decimal(1000), net_income=Decimal(200)):
    db.add_all(
        [
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=total_equity, provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=net_income, provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db.commit()


def _seed_shares(db, ticker, shares=100):
    db.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=shares))
    db.commit()


def _seed_price(db, ticker, price, as_of=AS_OF):
    db.add(
        PriceDaily(
            ticker=ticker, date=as_of, close=price, adj_factor=Decimal(1),
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()


class TestOpportunityRankingFor:
    def test_a_ticker_with_only_draft_fundamentals_is_excluded_from_the_universe_entirely(
        self, db_session, monkeypatch
    ):
        """§8's own rule, applied here: a ticker with nothing but
        AI-assisted/unconfirmed figures must never appear in the ranking
        at all — not ranked, not excluded-with-reason, simply not part
        of the universe this view even considers, exactly like
        `_confirmable_line_items` already treats it inside `valuation_
        summary_for` itself."""
        _seed_security(db_session, "DRAFT.N0000", "Draft Only PLC")
        db_session.add(
            Fundamental(
                ticker="DRAFT.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.AI_ASSISTED,
            )
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = opportunity_ranking_for(db_session, AS_OF)
        tickers = {c.ticker for c in view.ranked} | {c.ticker for c in view.excluded}
        assert "DRAFT.N0000" not in tickers

    def test_a_confirmed_ticker_with_a_computable_ladder_is_ranked(self, db_session, monkeypatch):
        _seed_security(db_session, "COMB.N0000", "Commercial Bank of Ceylon PLC")
        _seed_confirmed_fundamentals(db_session, "COMB.N0000")
        _seed_shares(db_session, "COMB.N0000")
        _seed_price(db_session, "COMB.N0000", Decimal(12))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = opportunity_ranking_for(db_session, AS_OF)
        assert len(view.ranked) == 1
        candidate = view.ranked[0]
        assert candidate.ticker == "COMB.N0000"
        assert candidate.price_ladder_zone == "strong_accumulate"  # matches the known-good hand-worked case
        assert candidate.gap_to_buy_below_pct is not None
        assert view.excluded == ()

    def test_two_ranked_candidates_are_sorted_by_gap_to_buy_below_ascending(self, db_session, monkeypatch):
        """The cheaper-relative-to-fair-value name (more negative gap,
        further below its own buy-below price) must sort first."""
        _seed_security(db_session, "CHEAP.N0000", "Cheap PLC")
        _seed_confirmed_fundamentals(db_session, "CHEAP.N0000")
        _seed_shares(db_session, "CHEAP.N0000")
        _seed_price(db_session, "CHEAP.N0000", Decimal(5))  # well below its own buy-below price

        _seed_security(db_session, "DEAR.N0000", "Dear PLC")
        _seed_confirmed_fundamentals(db_session, "DEAR.N0000")
        _seed_shares(db_session, "DEAR.N0000")
        _seed_price(db_session, "DEAR.N0000", Decimal(20))  # above fair value → exit zone

        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = opportunity_ranking_for(db_session, AS_OF)
        assert [c.ticker for c in view.ranked] == ["CHEAP.N0000", "DEAR.N0000"]
        assert view.ranked[0].gap_to_buy_below_pct < view.ranked[1].gap_to_buy_below_pct

    def test_a_negative_blended_fair_value_is_excluded_with_a_named_reason_not_a_fake_zone(
        self, db_session, monkeypatch
    ):
        """Real, live finding (18 Aug 2026): CBNK.N0000/EAST.N0000/
        JKH.N0000's real confirmed figures currently blend to a negative
        fair value. `compute_price_ladder` already refuses to build
        zones from a non-positive fair value — this view must surface
        that as an excluded candidate with the real warning, never as a
        ranked candidate with a nonsensical zone. Reproduced here with a
        negative net_income driving a negative residual-income anchor."""
        _seed_security(db_session, "NEG.N0000", "Negative PLC")
        _seed_confirmed_fundamentals(db_session, "NEG.N0000", total_equity=Decimal(1000), net_income=Decimal(-500))
        _seed_shares(db_session, "NEG.N0000")
        _seed_price(db_session, "NEG.N0000", Decimal(12))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = opportunity_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert len(view.excluded) == 1
        assert view.excluded[0].ticker == "NEG.N0000"
        assert view.excluded[0].price_ladder_zone is None
        assert any("fair_value must be positive" in w for w in view.excluded[0].warnings)

    def test_no_confirmed_universe_gives_an_empty_view_not_an_error(self, db_session):
        view = opportunity_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert view.excluded == ()

    def test_a_quarantined_ticker_is_excluded_with_the_quarantine_reason_not_ranked(
        self, db_session, monkeypatch
    ):
        """OI-3 (docs/audits/R1_OPEN_ISSUES.md): `is_quarantined` must
        actually gate ranking, not just a company-file badge — this is
        the regression test for that real, previously-unwired gap."""
        from app.models.data_quality import DataAlert

        _seed_security(db_session, "BAD.N0000", "Quarantined PLC")
        _seed_confirmed_fundamentals(db_session, "BAD.N0000")
        _seed_shares(db_session, "BAD.N0000")
        _seed_price(db_session, "BAD.N0000", Decimal(12))
        db_session.add(
            DataAlert(
                ticker="BAD.N0000", alert_type="reconciliation_mismatch", detail="test",
                raised_at=dt.datetime.now(dt.timezone.utc), resolved=False,
            )
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = opportunity_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert len(view.excluded) == 1
        assert view.excluded[0].ticker == "BAD.N0000"
        assert "quarantined" in view.excluded[0].warnings[0]
        assert view.excluded[0].blended_fair_value_per_share is None


class TestOpportunityRankingCache:
    """R1: this view's own real ~18-25s per-call cost (see `opportunity_
    ranking_for`'s own module-level comment) is genuinely expensive, real
    computation — the cache exists only to stop three real callers on one
    cold page load (Today, Opportunities, Macro's sector drill-down) from
    each paying it separately for what is, in practice, an identical
    result. `conftest.py`'s own autouse fixture clears this cache before
    and after every test — without it, these tests (and several others in
    this same file, all using the same `AS_OF`) would silently share
    state, which is exactly the bug that fixture exists to prevent, found
    live while building the cache, not assumed."""

    def test_a_second_call_for_the_same_as_of_returns_the_same_object_without_recomputing(
        self, db_session, monkeypatch
    ):
        _seed_security(db_session, "COMB.N0000", "Commercial Bank of Ceylon PLC")
        _seed_confirmed_fundamentals(db_session, "COMB.N0000")
        _seed_shares(db_session, "COMB.N0000")
        _seed_price(db_session, "COMB.N0000", Decimal(12))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        first = opportunity_ranking_for(db_session, AS_OF)
        second = opportunity_ranking_for(db_session, AS_OF)

        assert second is first  # the literal cached object, not just equal data

    def test_a_different_as_of_is_not_served_the_other_date_s_cached_result(self, db_session, monkeypatch):
        _seed_security(db_session, "COMB.N0000", "Commercial Bank of Ceylon PLC")
        _seed_confirmed_fundamentals(db_session, "COMB.N0000")
        _seed_shares(db_session, "COMB.N0000")
        _seed_price(db_session, "COMB.N0000", Decimal(12))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        first = opportunity_ranking_for(db_session, AS_OF)
        second = opportunity_ranking_for(db_session, AS_OF + dt.timedelta(days=1))

        assert second is not first
        assert first.as_of == AS_OF
        assert second.as_of == AS_OF + dt.timedelta(days=1)

    def test_clear_cache_forces_real_recomputation(self, db_session, monkeypatch):
        from app.domain.opportunity_ranking_view import clear_cache

        _seed_security(db_session, "COMB.N0000", "Commercial Bank of Ceylon PLC")
        _seed_confirmed_fundamentals(db_session, "COMB.N0000")
        _seed_shares(db_session, "COMB.N0000")
        _seed_price(db_session, "COMB.N0000", Decimal(12))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        first = opportunity_ranking_for(db_session, AS_OF)
        clear_cache()
        second = opportunity_ranking_for(db_session, AS_OF)

        assert second is not first
        assert second.as_of == first.as_of == AS_OF
