"""
`app.domain.composite_ranking_view` — the §38 composite score computed
across the whole confirmed universe and ranked. The single-ticker blend
(`composite_score_view`) has its own tests; this file covers what is new
here: the universe-wide Valuation pillar, the honestly-excluded Growth
pillar, the excluded/quarantined handling, ordering, and the TTL cache.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.composite_ranking_view import composite_ranking_for
from app.domain.cost_of_equity import CostOfEquityResult
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)
AS_OF = dt.date(2022, 6, 1)


def _fake_ke(ke=Decimal("0.15"), rf=Decimal("0.12")):
    def _fn(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=ke, risk_free_rate=rf, beta=Decimal("1.0"), erp_effective=Decimal("0.07"),
            beta_times_erp=Decimal("0.07"), size_premium=None, illiquidity_premium=None,
            implied_erp_cross_check=None, is_lower_bound=True, missing_components=(),
            note="stub",
        )
    return _fn


def _seed_security(db, ticker, name, archetype="bank", cse_sector=None):
    db.add(Security(ticker=ticker, name=name, archetype=archetype, cse_sector=cse_sector))
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
    now = dt.datetime.now(dt.timezone.utc)
    db.add(PriceDaily(ticker=ticker, date=as_of, close=price, volume=1_000_000, adj_factor=Decimal(1), fetched_at=now))
    db.add_all(
        PriceDaily(
            ticker=ticker, date=as_of - dt.timedelta(days=i), close=price, volume=1_000_000,
            adj_factor=Decimal(1), fetched_at=now,
        )
        for i in range(1, 50)
    )
    db.commit()


def _seed_full_ticker(db, ticker, name, price, cse_sector="Banks"):
    _seed_security(db, ticker, name, cse_sector=cse_sector)
    _seed_confirmed_fundamentals(db, ticker)
    _seed_shares(db, ticker)
    _seed_price(db, ticker, price)


class TestCompositeRankingFor:
    def test_no_confirmed_universe_gives_an_empty_view_not_an_error(self, db_session):
        view = composite_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert view.excluded == ()

    def test_a_draft_only_ticker_is_never_in_the_universe_at_all(self, db_session, monkeypatch):
        _seed_security(db_session, "DRAFT.N0000", "Draft Only PLC")
        db_session.add(
            Fundamental(
                ticker="DRAFT.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.AI_ASSISTED,
            )
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        seen = {r.ticker for r in view.ranked} | {r.ticker for r in view.excluded}
        assert "DRAFT.N0000" not in seen

    def test_every_row_carries_all_seven_pillars_in_spec_order(self, db_session, monkeypatch):
        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        rows = view.ranked + view.excluded
        assert len(rows) == 1
        assert [p.key for p in rows[0].pillars] == [
            "valuation", "business_quality", "growth",
            "financial_strength", "macro_sector_fit", "timing_momentum", "risk",
        ]
        for p in rows[0].pillars:
            if not p.included:
                assert p.score is None
                assert p.reason

    def test_valuation_pillar_is_blended_once_three_sector_peers_have_a_discount(
        self, db_session, monkeypatch
    ):
        # Three "Banks" names, identical confirmed fundamentals, different
        # prices -> three different discounts to the same blended fair
        # value -> a real sector peer set for the Valuation pillar.
        _seed_full_ticker(db_session, "CHEAP.N0000", "Cheap Bank", Decimal(5))
        _seed_full_ticker(db_session, "MID.N0000", "Mid Bank", Decimal(8))
        _seed_full_ticker(db_session, "DEAR.N0000", "Dear Bank", Decimal(10))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        by_ticker = {r.ticker: r for r in view.ranked}
        assert set(by_ticker) == {"CHEAP.N0000", "MID.N0000", "DEAR.N0000"}

        for r in by_ticker.values():
            val = next(p for p in r.pillars if p.key == "valuation")
            assert val.included is True
            assert val.score is not None
            assert "valuation" in r.weight_used_pct
            assert r.discount_to_fair_value_pct is not None
            # Corroboration fields track the pillars that actually fed the
            # score: count matches the included pillars, covered weight is
            # their raw §38 weights summed (<= 100).
            included = [p for p in r.pillars if p.included]
            assert r.pillars_included == len(included)
            assert r.weight_covered_pct == sum(p.weight_pct for p in included)
            assert Decimal(0) < r.weight_covered_pct <= Decimal(100)

        # Cheapest -> biggest discount -> highest Valuation percentile ->
        # ranked first (Valuation is 25% of the blend, the dominant
        # differentiator here since the other pillars are identical).
        assert [r.ticker for r in view.ranked] == ["CHEAP.N0000", "MID.N0000", "DEAR.N0000"]
        scores = [r.total_score for r in view.ranked]
        assert scores == sorted(scores, reverse=True)

    def test_growth_pillar_is_honestly_excluded_under_sparse_register_coverage(
        self, db_session, monkeypatch
    ):
        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        row = (view.ranked + view.excluded)[0]
        growth = next(p for p in row.pillars if p.key == "growth")
        assert growth.included is False
        assert "fewer than the 3" in growth.reason
        assert "fabricated 0" in growth.reason

    def test_a_confirmed_ticker_with_no_computable_pillar_lands_in_excluded_with_reasons(
        self, db_session, monkeypatch
    ):
        # One confirmed ticker, no sector peers, no price history -> no
        # pillar can be computed -> excluded, not ranked, and not a
        # fabricated 0.
        _seed_security(db_session, "LONE.N0000", "Lone PLC")
        _seed_confirmed_fundamentals(db_session, "LONE.N0000")
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert [r.ticker for r in view.excluded] == ["LONE.N0000"]
        row = view.excluded[0]
        assert row.total_score is None
        assert row.warnings
        assert all(not p.included for p in row.pillars)

    def test_a_quarantined_ticker_is_excluded_with_the_quarantine_reason(self, db_session, monkeypatch):
        from app.models.data_quality import DataAlert

        _seed_full_ticker(db_session, "BAD.N0000", "Quarantined Bank", Decimal(5))
        db_session.add(
            DataAlert(
                ticker="BAD.N0000", alert_type="reconciliation_mismatch", detail="test",
                raised_at=dt.datetime.now(dt.timezone.utc), resolved=False,
            )
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        assert view.ranked == ()
        assert [r.ticker for r in view.excluded] == ["BAD.N0000"]
        assert "quarantined" in view.excluded[0].warnings[0]

    def test_integrity_is_carried_unevaluable_on_every_row_never_applied(self, db_session, monkeypatch):
        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        view = composite_ranking_for(db_session, AS_OF)
        for r in view.ranked + view.excluded:
            assert r.integrity.evaluable is False
            assert r.integrity.vetoed is False


class TestCompositeRankingCache:
    def test_a_second_call_for_the_same_as_of_returns_the_same_object(self, db_session, monkeypatch):
        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        first = composite_ranking_for(db_session, AS_OF)
        second = composite_ranking_for(db_session, AS_OF)
        assert second is first

    def test_a_different_as_of_is_not_served_the_other_dates_cached_result(self, db_session, monkeypatch):
        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        first = composite_ranking_for(db_session, AS_OF)
        second = composite_ranking_for(db_session, AS_OF + dt.timedelta(days=1))
        assert second is not first
        assert first.as_of == AS_OF
        assert second.as_of == AS_OF + dt.timedelta(days=1)

    def test_clear_cache_forces_real_recomputation(self, db_session, monkeypatch):
        from app.domain.composite_ranking_view import clear_cache

        _seed_full_ticker(db_session, "COMB.N0000", "Commercial Bank", Decimal(5))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())

        first = composite_ranking_for(db_session, AS_OF)
        clear_cache()
        second = composite_ranking_for(db_session, AS_OF)
        assert second is not first
        assert second.as_of == first.as_of == AS_OF
