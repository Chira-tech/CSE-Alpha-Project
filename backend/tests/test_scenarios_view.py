"""§23 wired to live data — `app.domain.scenarios_view`. Reuses the same
fixture builders `test_valuation_view.py` already established for
`dcf_for` (Swadeshi-shaped, hand-verified WACC=0.1344) so the base case
this module builds Bear/Base/Bull variants of is the SAME known-good DCF
that module's own test suite already checks in isolation."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.scenarios_view import (
    _percentile,
    _yoy_growth_series,
    monte_carlo_for,
    scenario_set_for,
    sensitivity_tornado_for,
)
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)
AS_OF = dt.date(2022, 6, 1)


def _fake_ke(ke: Decimal | None, rf: Decimal | None = Decimal("0.12")):
    def _fn(db, ticker, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=ke, risk_free_rate=rf, beta=Decimal("1.0"), erp_effective=Decimal("0.07"),
            beta_times_erp=Decimal("0.07"), size_premium=None, illiquidity_premium=None,
            implied_erp_cross_check=None, is_lower_bound=True, missing_components=(),
            note="stub",
        )
    return _fn


def _seed_dcf_ready_company(db, ticker="SWAD.N0000"):
    db.add(Security(ticker=ticker, name="Swadeshi Industrial Works PLC"))
    lines = {
        "revenue": Decimal(10000),
        "operating_profit": Decimal(1000),
        "profit_before_tax": Decimal(900),
        "income_tax_expense": Decimal(-252),
        "depreciation_and_amortisation": Decimal(50),
        "capital_expenditure": Decimal(-80),
        "net_working_capital": Decimal(500),
        "total_interest_bearing_debt": Decimal(500),
        "interest_expense": Decimal(50),
    }
    db.add_all(
        Fundamental(
            ticker=ticker, period_end=PERIOD_END, period_type="annual",
            first_available_date=FIRST_AVAILABLE, version=1, statement_line=line,
            value=value, provenance_tier=ProvenanceTier.REPORTED,
        )
        for line, value in lines.items()
    )
    db.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100))
    db.commit()


class TestPercentile:
    def test_single_value_returns_itself_for_any_percentile(self):
        assert _percentile([Decimal("0.10")], 25) == Decimal("0.10")
        assert _percentile([Decimal("0.10")], 75) == Decimal("0.10")

    def test_hand_worked_interpolation(self):
        values = [Decimal("0"), Decimal("10"), Decimal("20"), Decimal("30")]
        # k = 0.25*3 = 0.75 -> between index 0 (0) and 1 (10), frac 0.75 -> 7.5
        assert _percentile(values, 25) == Decimal("7.5")
        # k = 0.75*3 = 2.25 -> between index 2 (20) and 3 (30), frac 0.25 -> 22.5
        assert _percentile(values, 75) == Decimal("22.5")


class TestYoyGrowthSeries:
    def test_skips_non_positive_pairs(self):
        history = [
            (dt.date(2019, 12, 31), Decimal(-100)),
            (dt.date(2020, 12, 31), Decimal(100)),
            (dt.date(2021, 12, 31), Decimal(110)),
        ]
        # First pair has a non-positive value -> skipped; second pair: 110/100-1=0.10
        assert _yoy_growth_series(history) == [Decimal("0.10")]


class TestScenarioSetFor:
    def test_no_dcf_gives_no_scenario_set(self, db_session, monkeypatch):
        db_session.add(Security(ticker="EMPTY.N0000", name="Empty PLC"))
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = scenario_set_for(db_session, "EMPTY.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is None
        assert view.warnings

    def test_thin_history_collapses_to_a_point_estimate_but_still_computes_real_bear_base_bull(
        self, db_session, monkeypatch
    ):
        """Only one confirmed period exists for this ticker — fewer than
        the 2 year-over-year observations §23's percentile construction
        needs. Growth/margin P25/P75 must honestly collapse to the
        base-case point rather than invent a spread, but Bear/Base/Bull
        must still be three REAL, DISTINCT DCF re-runs (via the WACC/
        terminal-growth shifts alone) — not a degenerate no-op."""
        _seed_dcf_ready_company(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = scenario_set_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)

        assert view.result is not None
        assert "collapse" in view.distribution_note
        # Real, distinct DCF re-runs — bear strictly below base strictly
        # below bull, driven by the real WACC +150bp/-100bp shifts alone.
        assert view.result.bear_value_per_share < view.result.base_value_per_share
        assert view.result.base_value_per_share < view.result.bull_value_per_share

    def test_deep_enough_history_computes_real_percentiles(self, db_session, monkeypatch):
        _seed_dcf_ready_company(db_session)
        # A second, earlier confirmed revenue period -> one real YoY growth
        # observation exists, but §23's percentile construction wants at
        # least 2 to avoid a degenerate single-point "distribution" —
        # add a third period so 2 real growth observations exist.
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=dt.date(2019, 12, 31), period_type="annual",
                    first_available_date=dt.date(2020, 3, 1), version=1, statement_line="revenue",
                    value=Decimal(8000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker="SWAD.N0000", period_end=dt.date(2020, 12, 31), period_type="annual",
                    first_available_date=dt.date(2021, 3, 1), version=1, statement_line="revenue",
                    value=Decimal(9000), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = scenario_set_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is not None
        assert "real year-over-year" in view.distribution_note
        assert view.result.bear_value_per_share < view.result.bull_value_per_share


class TestSensitivityTornadoFor:
    def test_bars_are_sorted_widest_spread_first(self, db_session, monkeypatch):
        _seed_dcf_ready_company(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = sensitivity_tornado_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert len(view.bars) == 4
        spreads = [bar.spread for bar in view.bars]
        assert spreads == sorted(spreads, reverse=True)


class TestMonteCarloFor:
    def test_no_dcf_gives_no_result(self, db_session, monkeypatch):
        db_session.add(Security(ticker="EMPTY.N0000", name="Empty PLC"))
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = monte_carlo_for(db_session, "EMPTY.N0000", current_price=Decimal(20), as_of=AS_OF, draws=100)
        assert view.result is None
        assert view.warnings

    def test_a_single_confirmed_period_still_runs_a_real_but_degenerate_bootstrap(
        self, db_session, monkeypatch
    ):
        """Only one confirmed period exists, so there are 0 YoY GROWTH
        observations but exactly 1 MARGIN observation (this period's own
        operating_profit/revenue) — the margin input still has something
        real to bootstrap from, so this must run, not report 'nothing to
        bootstrap.' Every draw picks the same single margin value, so the
        distribution is a real point mass (p10 == p50 == p90), which is
        the honestly-disclosed degenerate case, not a fabricated spread."""
        _seed_dcf_ready_company(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = monte_carlo_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF, draws=100)
        assert view.result is not None
        assert view.result.p10 == view.result.p50 == view.result.p90

    def test_with_history_runs_a_real_reproducible_bootstrap(self, db_session, monkeypatch):
        _seed_dcf_ready_company(db_session)
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=dt.date(2020, 12, 31), period_type="annual",
                    first_available_date=dt.date(2021, 3, 1), version=1, statement_line="revenue",
                    value=Decimal(9000), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.commit()
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = monte_carlo_for(
            db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF, draws=200, seed=42
        )
        assert view.result is not None
        assert view.result.draws == 200
        assert view.result.p10 <= view.result.p50 <= view.result.p90
