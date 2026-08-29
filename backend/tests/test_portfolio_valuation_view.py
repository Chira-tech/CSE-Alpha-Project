"""app.domain.portfolio_valuation_view — connecting a real uploaded
portfolio snapshot to this system's own real valuation engine."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.portfolio_import_parsing import ParsedPortfolio, ParsedPosition
from app.domain.portfolio_import_view import store_portfolio_snapshot
from app.domain.portfolio_valuation_view import value_portfolio
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 18)


def _parsed(ticker: str, avg_price=Decimal("20.0"), quantity=Decimal("1000")):
    total_cost = avg_price * quantity
    return ParsedPortfolio(
        positions=(
            ParsedPosition(
                ticker=ticker, quantity=quantity, avg_price=avg_price, total_cost=total_cost,
                traded_price=avg_price, market_value=total_cost, unrealized_gain_loss=Decimal(0),
            ),
        ),
        stated_total_cost=total_cost, stated_total_market_value=total_cost,
        identity_check_passed=True, identity_check_note="ok",
    )


class TestValuePortfolio:
    def test_a_ticker_not_in_securities_still_gets_a_row_with_named_warnings(self, db_session):
        snapshot = store_portfolio_snapshot(db_session, _parsed("DELISTED.X0000"), source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)
        assert len(result.positions) == 1
        pos = result.positions[0]
        assert pos.ticker == "DELISTED.X0000"
        assert pos.live_current_price is None
        assert pos.blended_fair_value_per_share is None
        assert any("not in this system's own securities table" in w for w in pos.warnings)
        assert result.positions_missing_a_live_price == ("DELISTED.X0000",)
        assert result.total_live_market_value is None

    def test_a_known_ticker_with_no_real_price_history_is_named_not_silently_none(self, db_session):
        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        db_session.commit()
        snapshot = store_portfolio_snapshot(db_session, _parsed("JKH.N0000"), source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)
        pos = result.positions[0]
        assert pos.live_current_price is None
        assert any("No real live price found" in w for w in pos.warnings)

    def test_snapshot_and_live_figures_are_never_conflated(self, db_session):
        """A real held position bought at 20.0, now trading at 25.0 —
        the snapshot's own figures (as the broker reported them) and
        this system's own live figures must both be present, distinct,
        and correctly computed from the real quantity/price."""
        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add(PriceDaily(ticker="JKH.N0000", date=AS_OF, close=Decimal("25.0"), adj_factor=Decimal("1"), fetched_at=now))
        db_session.commit()

        snapshot = store_portfolio_snapshot(
            db_session, _parsed("JKH.N0000", avg_price=Decimal("20.0"), quantity=Decimal("1000")),
            source_filename="p.xlsx",
        )
        result = value_portfolio(db_session, snapshot, AS_OF)
        pos = result.positions[0]

        # Snapshot figures: unchanged from the broker's own real report.
        assert pos.snapshot_traded_price == Decimal("20.0")
        assert pos.snapshot_market_value == Decimal("20000.0")

        # Live figures: this system's own real, current computation.
        assert pos.live_current_price == Decimal("25.0")
        assert pos.live_market_value == Decimal("25000.0")
        assert pos.live_unrealized_gain_loss == Decimal("5000.0")  # 25000 - 20000 total cost

        assert result.total_live_market_value == Decimal("25000.0")
        assert result.positions_missing_a_live_price == ()

    def test_total_cost_always_sums_real_positions_regardless_of_pricing_gaps(self, db_session):
        snapshot = store_portfolio_snapshot(db_session, _parsed("NOPRICE.N0000"), source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)
        assert result.total_cost == Decimal("20000.0")

    def test_a_loss_making_holding_carries_its_real_warning_not_silence(self, db_session, monkeypatch):
        """Real bug, found live (18 Aug 2026) browser-testing the
        Portfolio screen against the real dev DB: a deeply loss-making
        holding used to blend to a NEGATIVE fair value. That artifact is
        now closed at the source — the Gordon-family anchors are
        suppressed when ROE <= g and the conservative book anchor is
        suppressed when mid-cycle ROE is negative (§27 distress) — so
        there is simply no blended fair value, and the position must
        still carry the real reason ("nothing to blend"), never
        silence. This regression exists because `value_position` once
        copied only `summary.triangulation.warnings` and not
        `summary.price_ladder.warnings`; both paths are covered now."""
        db_session.add(Security(ticker="NEG.N0000", name="Negative PLC", archetype="bank"))
        db_session.add_all(
            [
                Fundamental(
                    ticker="NEG.N0000", period_end=dt.date(2021, 12, 31), period_type="annual",
                    first_available_date=dt.date(2022, 3, 7), version=1, statement_line="total_equity",
                    value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker="NEG.N0000", period_end=dt.date(2021, 12, 31), period_type="annual",
                    first_available_date=dt.date(2022, 3, 7), version=1, statement_line="net_income",
                    value=Decimal(-500), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.add(FloatData(ticker="NEG.N0000", as_of=dt.date(2022, 1, 1), shares_issued=100))
        db_session.add(
            PriceDaily(
                ticker="NEG.N0000", date=AS_OF, close=Decimal(12), adj_factor=Decimal(1),
                fetched_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        db_session.commit()

        def _fake_ke(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
            return CostOfEquityResult(
                ke=Decimal("0.15"), risk_free_rate=Decimal("0.12"), beta=Decimal("1.0"),
                erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
                illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
                missing_components=(), note="stub",
            )

        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)

        snapshot = store_portfolio_snapshot(db_session, _parsed("NEG.N0000"), source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)
        pos = result.positions[0]

        assert pos.price_ladder_zone is None
        assert pos.blended_fair_value_per_share is None
        assert any("nothing to blend" in w for w in pos.warnings)


def test_a_quarantined_holding_shows_price_but_withholds_fair_value(db_session):
    """OI-3 (docs/audits/R1_OPEN_ISSUES.md): a quarantined ticker's real
    price/quantity/cost still show (directly observed, not model
    output), but every derived valuation field is withheld with a named
    reason — the same real gap `opportunity_ranking_view` had, closed
    the same way here."""
    from app.models.data_quality import DataAlert

    db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(
        PriceDaily(ticker="JKH.N0000", date=AS_OF, close=Decimal("25.0"), adj_factor=Decimal("1"), fetched_at=now)
    )
    db_session.add(
        DataAlert(
            ticker="JKH.N0000", alert_type="reconciliation_mismatch", detail="test",
            raised_at=now, resolved=False,
        )
    )
    db_session.commit()

    snapshot = store_portfolio_snapshot(db_session, _parsed("JKH.N0000"), source_filename="p.xlsx")
    result = value_portfolio(db_session, snapshot, AS_OF)
    pos = result.positions[0]

    # Real, directly observed figures still show.
    assert pos.live_current_price == Decimal("25.0")
    assert pos.live_market_value is not None

    # Every derived valuation field is withheld.
    assert pos.blended_fair_value_per_share is None
    assert pos.price_ladder_zone is None
    assert pos.buy_below_price is None
    assert pos.sell_above_price is None
    assert pos.margin_of_safety_pct is None

    # TASK 2.2's own exit-plan fields must be withheld too — a
    # quarantined ticker gets no exit price or overvaluation figure
    # derived from a number that failed sanity.
    assert pos.trim_above_price is None
    assert pos.overvaluation_pct is None
    assert pos.nearest_trigger_label is None
    assert pos.nearest_trigger_price is None
    assert pos.nearest_trigger_distance_pct is None
    assert pos.decision_verdict is None
    assert pos.decision_confidence is None
    assert pos.dispersion_pct is None
    assert any("quarantined" in w for w in pos.warnings)


class TestTask22ExitPlanFields:
    """TASK 2.2 (product-owner brief): trim/exit prices, overvaluation,
    nearest trigger, decision verdict, thesis status — and sorting the
    portfolio by nearest trigger rather than P&L."""

    def _fake_ke(self, db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=Decimal("0.15"), risk_free_rate=Decimal("0.12"), beta=Decimal("1.0"),
            erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
            illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
            missing_components=(), note="stub",
        )

    def _seed_healthy_bank(self, db_session, ticker, *, price=Decimal(12)):
        db_session.add(Security(ticker=ticker, name="Healthy Bank PLC", archetype="bank"))
        db_session.add_all(
            [
                Fundamental(
                    ticker=ticker, period_end=dt.date(2021, 12, 31), period_type="annual",
                    first_available_date=dt.date(2022, 3, 7), version=1, statement_line="total_equity",
                    value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker=ticker, period_end=dt.date(2021, 12, 31), period_type="annual",
                    first_available_date=dt.date(2022, 3, 7), version=1, statement_line="net_income",
                    value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100))
        db_session.add(
            PriceDaily(
                ticker=ticker, date=AS_OF, close=price, adj_factor=Decimal(1),
                fetched_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        db_session.commit()

    def test_a_real_positive_fair_value_gets_a_full_exit_plan(self, db_session, monkeypatch):
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", self._fake_ke)
        # docs/SYSTEM_AUDIT.md §0's Gordon-family collapse means this
        # fixture's real fair value is 11.208333 (justified P/B alone,
        # blended with the conservative book anchor — no DCF inputs are
        # seeded) — price 9 sits between buy-below (8.41) and the fair
        # value itself, the 'fair' zone, so this test exercises the
        # "nothing stretched" thesis-intact path deliberately, distinct
        # from the 'trim'-zone case a higher price would trigger.
        self._seed_healthy_bank(db_session, "COMB.N0000", price=Decimal(9))

        snapshot = store_portfolio_snapshot(db_session, _parsed("COMB.N0000"), source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)
        pos = result.positions[0]

        assert pos.blended_fair_value_per_share is not None
        # trim_above = fair value itself, same number as blended_fair_value_per_share.
        assert pos.trim_above_price == pos.blended_fair_value_per_share
        # sell_above (exit_threshold) = fair value x 1.15.
        assert pos.sell_above_price == pos.trim_above_price * Decimal("1.15")
        # overvaluation_pct = (price / fair value) - 1, plain arithmetic.
        expected_overvaluation = (pos.live_current_price / pos.blended_fair_value_per_share) - 1
        assert pos.overvaluation_pct == expected_overvaluation
        # A real verdict/confidence came from the same decision engine the
        # company file uses.
        assert pos.decision_verdict is not None
        assert pos.decision_confidence in ("high", "medium", "low")
        # No real attention flags on this fixture (nothing to trend on
        # with a single period) -> thesis reads intact.
        assert pos.thesis_status == "intact"
        # A real nearest trigger was found among the four ladder thresholds.
        assert pos.nearest_trigger_label in (
            "Strong accumulate", "Buy below", "Trim above", "Exit above",
        )
        assert pos.nearest_trigger_distance_pct is not None

    def test_positions_sort_by_nearest_trigger_not_by_pnl(self, db_session, monkeypatch):
        """A position sitting right on a ladder boundary must rank
        BEFORE one that has gained far more but sits well clear of any
        boundary — TASK 2.2's own rule 2."""
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", self._fake_ke)
        # ONBOUNDARY.N0000: price sits right at the fair value itself
        # (distance ~0%) — needs attention now.
        self._seed_healthy_bank(db_session, "ONBOUNDARY.N0000", price=Decimal(15))
        # BIGGAIN.N0000: a huge unrealised gain (bought at 1, now
        # trading far below every real ladder threshold) — a great P&L
        # story, but nothing urgent about it today.
        self._seed_healthy_bank(db_session, "BIGGAIN.N0000", price=Decimal(1))

        parsed = ParsedPortfolio(
            positions=(
                ParsedPosition(
                    ticker="BIGGAIN.N0000", quantity=Decimal(1000), avg_price=Decimal(1),
                    total_cost=Decimal(1000), traded_price=Decimal(1), market_value=Decimal(1000),
                    unrealized_gain_loss=Decimal(0),
                ),
                ParsedPosition(
                    ticker="ONBOUNDARY.N0000", quantity=Decimal(1000), avg_price=Decimal(15),
                    total_cost=Decimal(15000), traded_price=Decimal(15), market_value=Decimal(15000),
                    unrealized_gain_loss=Decimal(0),
                ),
            ),
            stated_total_cost=Decimal(16000), stated_total_market_value=Decimal(16000),
            identity_check_passed=True, identity_check_note="ok",
        )
        snapshot = store_portfolio_snapshot(db_session, parsed, source_filename="p.xlsx")
        result = value_portfolio(db_session, snapshot, AS_OF)

        tickers_in_order = [p.ticker for p in result.positions]
        assert tickers_in_order.index("ONBOUNDARY.N0000") < tickers_in_order.index("BIGGAIN.N0000")


class TestPortfolioValueTrend:
    def test_real_price_change_computed_from_todays_holdings_at_past_prices(self, db_session):
        """R1 T4.1.6 — real §41-lite trend: today's exact quantity,
        priced at real historical closes."""
        from app.domain.portfolio_valuation_view import portfolio_value_trend

        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add(
            PriceDaily(ticker="JKH.N0000", date=AS_OF - dt.timedelta(days=15), close=Decimal("20.0"), adj_factor=Decimal("1"), fetched_at=now)
        )
        db_session.add(
            PriceDaily(ticker="JKH.N0000", date=AS_OF, close=Decimal("25.0"), adj_factor=Decimal("1"), fetched_at=now)
        )
        db_session.commit()

        snapshot = store_portfolio_snapshot(
            db_session, _parsed("JKH.N0000", avg_price=Decimal("20.0"), quantity=Decimal("1000")),
            source_filename="p.xlsx",
        )
        result = portfolio_value_trend(db_session, snapshot, AS_OF, (15,))
        # 1000 * 25.0 vs 1000 * 20.0 -> +25%
        assert result[15] == Decimal("25")

    def test_missing_price_that_far_back_returns_none_not_a_partial_total(self, db_session):
        from app.domain.portfolio_valuation_view import portfolio_value_trend

        db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add(
            PriceDaily(ticker="JKH.N0000", date=AS_OF, close=Decimal("25.0"), adj_factor=Decimal("1"), fetched_at=now)
        )
        db_session.commit()

        snapshot = store_portfolio_snapshot(db_session, _parsed("JKH.N0000"), source_filename="p.xlsx")
        result = portfolio_value_trend(db_session, snapshot, AS_OF, (15, 30))
        assert result[15] is None
        assert result[30] is None
