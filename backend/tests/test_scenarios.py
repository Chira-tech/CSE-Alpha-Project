"""§23 scenarios and simulation — bear/base/bull construction, tornado,
Monte Carlo."""
from __future__ import annotations

from decimal import Decimal

from app.domain.dcf import DCFAssumptions, dcf_equity_value
from app.domain.scenarios import (
    HistoricalGrowthMarginDistribution,
    MonteCarloInput,
    build_scenario_set,
    run_monte_carlo,
    sensitivity_tornado,
)


def _base() -> DCFAssumptions:
    return DCFAssumptions(
        base_revenue=Decimal(1000),
        revenue_growth_y1=Decimal("0.08"),
        revenue_growth_y2=Decimal("0.08"),
        revenue_growth_stage2_target=Decimal("0.06"),
        terminal_growth=Decimal("0.04"),
        operating_margin_current=Decimal("0.20"),
        operating_margin_target=Decimal("0.20"),
        effective_tax_rate_current=Decimal("0.28"),
        statutory_tax_rate=Decimal("0.28"),
        depreciation_amortisation_pct_revenue=Decimal("0.04"),
        capex_pct_revenue=Decimal("0.05"),
        working_capital_pct_revenue=Decimal("0.10"),
        risk_free_rate=Decimal("0.12"),
        discount_rate=Decimal("0.15"),
        diluted_shares_outstanding=Decimal(100),
    )


class TestBuildScenarioSet:
    def test_bear_and_bull_use_distribution_percentiles(self):
        base = _base()
        dist = HistoricalGrowthMarginDistribution(
            growth_p25=Decimal("0.02"), growth_p75=Decimal("0.12"),
            margin_p25=Decimal("0.15"), margin_p75=Decimal("0.25"),
        )
        result = build_scenario_set(base, dist)

        assert result.bear.revenue_growth_y1 == Decimal("0.02")
        assert result.bear.operating_margin_current == Decimal("0.15")
        assert result.bear.discount_rate == base.discount_rate + Decimal("0.015")
        assert result.bear.terminal_growth == base.terminal_growth - Decimal("0.010")

        assert result.bull.revenue_growth_y1 == Decimal("0.12")
        assert result.bull.operating_margin_current == Decimal("0.25")
        assert result.bull.discount_rate == base.discount_rate - Decimal("0.010")

        assert result.base is base

    def test_bear_less_than_base_less_than_bull(self):
        base = _base()
        dist = HistoricalGrowthMarginDistribution(
            growth_p25=Decimal("0.02"), growth_p75=Decimal("0.12"),
            margin_p25=Decimal("0.15"), margin_p75=Decimal("0.25"),
        )
        result = build_scenario_set(base, dist)
        assert result.bear_value_per_share < result.base_value_per_share < result.bull_value_per_share

    def test_default_deltas_note_the_missing_macro_and_project_data(self):
        base = _base()
        dist = HistoricalGrowthMarginDistribution(Decimal("0.02"), Decimal("0.12"), Decimal("0.15"), Decimal("0.25"))
        result = build_scenario_set(base, dist)
        assert "macro engine" in result.note
        assert "project register" in result.note


class TestSensitivityTornado:
    def test_larger_delta_field_ranks_first(self):
        base = _base()
        # A huge discount-rate swing should dominate a tiny WC swing.
        bars = sensitivity_tornado(
            base,
            {"discount_rate": Decimal("0.05"), "working_capital_pct_revenue": Decimal("0.001")},
        )
        assert bars[0].assumption_name == "discount_rate"
        assert bars[0].spread > bars[1].spread

    def test_spread_matches_direct_computation(self):
        base = _base()
        bars = sensitivity_tornado(base, {"discount_rate": Decimal("0.01")})
        bar = bars[0]

        import dataclasses
        low = dcf_equity_value(dataclasses.replace(base, discount_rate=base.discount_rate - Decimal("0.01"))).value_per_share
        high = dcf_equity_value(dataclasses.replace(base, discount_rate=base.discount_rate + Decimal("0.01"))).value_per_share
        assert bar.low_value_per_share == low
        assert bar.high_value_per_share == high
        assert bar.spread == abs(high - low)
        # Lower discount rate → higher value (well-known DCF direction).
        assert low > high


class TestMonteCarlo:
    def test_reproducible_with_seed(self):
        base = _base()
        inputs = (MonteCarloInput("discount_rate", (Decimal("0.13"), Decimal("0.15"), Decimal("0.17"))),)
        r1 = run_monte_carlo(base, inputs, draws=200, seed=42)
        r2 = run_monte_carlo(base, inputs, draws=200, seed=42)
        assert r1.p10 == r2.p10
        assert r1.p50 == r2.p50
        assert r1.p90 == r2.p90

    def test_percentiles_are_monotonic(self):
        base = _base()
        inputs = (
            MonteCarloInput("discount_rate", (Decimal("0.12"), Decimal("0.15"), Decimal("0.18"))),
            MonteCarloInput("revenue_growth_y1", (Decimal("0.02"), Decimal("0.08"), Decimal("0.14"))),
        )
        result = run_monte_carlo(base, inputs, draws=500, seed=7)
        assert result.p10 <= result.p25 <= result.p50 <= result.p75 <= result.p90

    def test_probability_exact_at_degenerate_single_value_distribution(self):
        base = _base()
        # A single-valued "distribution" collapses every draw to the same
        # deterministic value — probability must be exactly 0 or 1.
        point_value = dcf_equity_value(base).value_per_share
        inputs = (MonteCarloInput("discount_rate", (base.discount_rate,)),)

        below = run_monte_carlo(base, inputs, current_price_per_share=point_value - 1, draws=50, seed=1)
        assert below.probability_fair_value_exceeds_price == Decimal(1)

        above = run_monte_carlo(base, inputs, current_price_per_share=point_value + 1, draws=50, seed=1)
        assert above.probability_fair_value_exceeds_price == Decimal(0)
