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

    def test_a_negative_blended_fair_value_carries_its_real_warning_not_silence(self, db_session, monkeypatch):
        """Real bug, found live (18 Aug 2026) browser-testing the
        Portfolio screen against the real dev DB: CBNK.N0000's real
        confirmed figures blend to a negative fair value, and
        `app.domain.price_ladder.compute_price_ladder` already refuses
        to build a zone from it — but `value_position` only ever copied
        `summary.triangulation.warnings` into the position's own
        `warnings`, never `summary.price_ladder.warnings`, so the real,
        already-computed "fair_value must be positive" explanation
        silently never reached the position at all. The Opportunities
        screen (a different call site reading the same `valuation_
        summary_for` output) already surfaced this correctly, which is
        how the gap was found — comparing what the two screens showed
        for the same real ticker."""
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
        assert any("fair_value must be positive" in w for w in pos.warnings)


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
    assert pos.dispersion_pct is None
    assert any("quarantined" in w for w in pos.warnings)


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
