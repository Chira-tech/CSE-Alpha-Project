"""app.domain.decision_record_view — §45's decision record: freeze real
model state at decision time, record a real outcome at exit."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.decision_record_view import list_decisions, record_decision_for, record_outcome_for
from app.models.decisions import Decision, Outcome
from app.models.enums import DecisionAction, ProvenanceTier
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


def _seed_known_good(db, ticker="COMB.N0000", price=Decimal(12)):
    db.add(Security(ticker=ticker, name="Commercial Bank of Ceylon PLC", archetype="bank"))
    db.add_all(
        [
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100))
    db.add(
        PriceDaily(
            ticker=ticker, date=AS_OF, close=price, adj_factor=Decimal(1),
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()


class TestRecordDecisionFor:
    def test_freezes_real_triangulation_and_ladder_state(self, db_session, monkeypatch):
        _seed_known_good(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        decision = record_decision_for(
            db_session, "COMB.N0000", DecisionAction.BUY,
            "Trading well below justified P/B and residual income anchors.",
            as_of=AS_OF, conviction_1_5=4, falsification_text="ROE falls below 12% for two quarters.",
        )

        assert decision.id is not None
        assert decision.action == DecisionAction.BUY
        assert decision.market_price_at_decision == Decimal(12)
        # Same known-good hand-worked fixture as test_valuation_view.py's
        # TestValuationSummaryFor.test_end_to_end_bank_triangulation_and_ladder:
        # docs/SYSTEM_AUDIT.md §0's Gordon-family collapse means only
        # justified P/B (15.0) counts as a triangulation anchor, blended
        # with the conservative book (NAV floor) anchor at 8.5, renormalised
        # since "intrinsic" has no anchor in this fixture (no DCF inputs
        # seeded) → 11.208333, with real dispersion between two genuinely
        # different reads.
        assert abs(decision.fv_blended - Decimal("11.208333")) < Decimal("0.001")
        assert decision.dispersion > Decimal("0.5")
        assert decision.buy_below is not None
        assert decision.fair_value is not None
        assert decision.trim_above is not None
        assert decision.fv_by_method_json is not None
        assert "Justified P/B" in decision.fv_by_method_json
        # Not-yet-built layers stay honestly None, never a fabricated number.
        assert decision.fundamental_score is None
        assert decision.timing_score is None
        assert decision.alpha is None
        assert decision.agreement_score is None
        assert decision.override_flag is None
        assert decision.config_hash is None

    def test_a_ticker_with_no_confirmed_data_still_records_a_decision(self, db_session, monkeypatch):
        """A `pass` decision on a name this system can't yet value is
        still a real decision worth recording — the frozen state is
        just honestly mostly None."""
        db_session.add(Security(ticker="UNKNOWN.N0000", name="Unknown PLC"))
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        decision = record_decision_for(
            db_session, "UNKNOWN.N0000", DecisionAction.PASS,
            "No confirmed fundamentals to value this against yet.",
            as_of=AS_OF,
        )
        assert decision.fv_blended is None
        assert decision.buy_below is None
        assert decision.market_price_at_decision is None

    def test_decisions_persist_and_list_newest_first(self, db_session, monkeypatch):
        _seed_known_good(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        d1 = record_decision_for(db_session, "COMB.N0000", DecisionAction.WATCHLIST, "First look.", as_of=AS_OF)
        d2 = record_decision_for(db_session, "COMB.N0000", DecisionAction.BUY, "Now buying.", as_of=AS_OF)

        rows = list_decisions(db_session)
        assert [r.id for r in rows] == [d2.id, d1.id]


class TestRecordOutcomeFor:
    def test_a_real_gain_computes_gross_and_net_return(self, db_session, monkeypatch):
        _seed_known_good(db_session, price=Decimal(10))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        decision = record_decision_for(db_session, "COMB.N0000", DecisionAction.BUY, "Cheap.", as_of=AS_OF)

        exit_date = AS_OF + dt.timedelta(days=180)
        outcome = record_outcome_for(db_session, decision.id, exit_date, Decimal("12"), "hit buy-below target")

        assert outcome is not None
        # (12-10)/10 = 0.20 gross; net = gross - 0.0224 (§2.1's real round-trip cost).
        assert outcome.gross_return == Decimal("0.2")
        assert outcome.net_return == Decimal("0.2") - Decimal("0.0224")
        assert outcome.holding_days == 180

    def test_cannot_record_a_second_outcome_for_the_same_decision(self, db_session, monkeypatch):
        _seed_known_good(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        decision = record_decision_for(db_session, "COMB.N0000", DecisionAction.BUY, "Cheap.", as_of=AS_OF)
        record_outcome_for(db_session, decision.id, AS_OF + dt.timedelta(days=10), Decimal("13"), "trim")

        second = record_outcome_for(db_session, decision.id, AS_OF + dt.timedelta(days=20), Decimal("14"), "exit")
        assert second is None

    def test_excursions_are_real_or_named_none_never_guessed(self, db_session, monkeypatch):
        """Real daily prices between entry and exit produce a real
        max adverse/favourable excursion; no coverage in that window
        gives (None, None), never a fabricated figure."""
        _seed_known_good(db_session, price=Decimal(10))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        decision = record_decision_for(db_session, "COMB.N0000", DecisionAction.BUY, "Cheap.", as_of=AS_OF)

        # A real dip below entry, then a real recovery above it, before exit.
        db_session.add(
            PriceDaily(
                ticker="COMB.N0000", date=AS_OF + dt.timedelta(days=5), close=Decimal("8"),
                adj_factor=Decimal(1), fetched_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        db_session.add(
            PriceDaily(
                ticker="COMB.N0000", date=AS_OF + dt.timedelta(days=10), close=Decimal("13"),
                adj_factor=Decimal(1), fetched_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        db_session.commit()

        outcome = record_outcome_for(
            db_session, decision.id, AS_OF + dt.timedelta(days=15), Decimal("12"), "exit"
        )
        assert outcome.max_adverse_excursion == Decimal("-0.2")  # (8-10)/10
        assert outcome.max_favourable_excursion == Decimal("0.3")  # (13-10)/10


class TestDeleteCascade:
    def test_deleting_a_decision_deletes_its_outcome_rather_than_orphaning_it(self, db_session, monkeypatch):
        """Real bug, found live (18 Aug 2026) while cleaning up a test
        decision against the real dev DB: SQLAlchemy's default one-to-
        one delete behaviour tries to NULL the child's foreign key,
        which fails outright since `Outcome.decision_id` is non-
        nullable. No real application code path deletes a `Decision`
        today, but the cascade must still be correct — an orphaned
        `Outcome` would be real data corruption if anything ever did."""
        _seed_known_good(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        decision = record_decision_for(db_session, "COMB.N0000", DecisionAction.BUY, "Cheap.", as_of=AS_OF)
        record_outcome_for(db_session, decision.id, AS_OF + dt.timedelta(days=10), Decimal("13"), "trim")
        outcome_id = decision.outcome.id

        db_session.delete(decision)
        db_session.commit()

        assert db_session.get(Decision, decision.id) is None
        assert db_session.get(Outcome, outcome_id) is None
