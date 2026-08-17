"""§18 DCF and §23 reverse DCF — checked against hand-worked / closed-form
reference values, not just re-reading the module's own arithmetic back at
itself."""
from __future__ import annotations

from decimal import Decimal

from app.domain.dcf import (
    DCFAssumptions,
    compute_fcff,
    dcf_equity_value,
    implied_flat_growth_rate,
    linear_fade,
    project_cash_flows,
)


def test_linear_fade_basic():
    assert linear_fade(Decimal(10), Decimal(25), 3) == [Decimal(15), Decimal(20), Decimal(25)]


class TestComputeFCFF:
    def test_hand_worked(self):
        # 1000*(1-0.28) + 50 - 80 - 20 = 720 + 50 - 80 - 20 = 670
        result = compute_fcff(
            ebit=Decimal(1000),
            effective_tax_rate=Decimal("0.28"),
            depreciation_amortisation=Decimal(50),
            capital_expenditure=Decimal(80),
            change_in_net_working_capital=Decimal(20),
        )
        assert result == Decimal(670)

    def test_negative_change_in_working_capital_increases_fcff(self):
        """A DECREASE in net working capital (cash released, not
        absorbed) should ADD to FCFF, not subtract."""
        base = compute_fcff(Decimal(1000), Decimal("0.28"), Decimal(50), Decimal(80), Decimal(0))
        released_cash = compute_fcff(Decimal(1000), Decimal("0.28"), Decimal(50), Decimal(80), Decimal(-20))
        assert released_cash == base + 20

    def test_matches_project_cash_flows_internal_computation(self):
        """The multi-year projection calls this same function per year —
        confirm the two paths never silently diverge."""
        a = DCFAssumptions(
            base_revenue=Decimal(1000),
            revenue_growth_y1=Decimal("0.05"),
            revenue_growth_y2=Decimal("0.05"),
            revenue_growth_stage2_target=Decimal("0.05"),
            terminal_growth=Decimal("0.05"),
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
        years = project_cash_flows(a)
        y1 = years[0]
        recomputed = compute_fcff(
            y1.ebit, y1.tax_rate, y1.depreciation_amortisation,
            y1.capital_expenditure, y1.change_in_net_working_capital,
        )
        assert recomputed == y1.fcff


def test_linear_fade_zero_steps():
    assert linear_fade(Decimal(10), Decimal(25), 0) == []


def _flat_assumptions(**overrides) -> DCFAssumptions:
    base = dict(
        base_revenue=Decimal(1000),
        revenue_growth_y1=Decimal("0.05"),
        revenue_growth_y2=Decimal("0.05"),
        revenue_growth_stage2_target=Decimal("0.05"),
        terminal_growth=Decimal("0.05"),
        operating_margin_current=Decimal("0.20"),
        operating_margin_target=Decimal("0.20"),
        effective_tax_rate_current=Decimal("0.28"),
        statutory_tax_rate=Decimal("0.28"),
        depreciation_amortisation_pct_revenue=Decimal("0.04"),
        capex_pct_revenue=Decimal("0.05"),
        working_capital_pct_revenue=Decimal("0.10"),
        risk_free_rate=Decimal("0.12"),
        discount_rate=Decimal("0.15"),
        cash_and_non_operating_assets=Decimal(0),
        total_debt=Decimal(0),
        minority_interest=Decimal(0),
        pension_deficit=Decimal(0),
        diluted_shares_outstanding=Decimal(100),
    )
    base.update(overrides)
    return DCFAssumptions(**base)


class TestFlatGrowthClosedForm:
    """With every fade endpoint equal (g constant across all 10 years,
    margin/tax/capex%/WC% constant), FCFF is a pure geometric series:
    FCFF_t = revenue_t * K for a constant K, independent of the module's
    own year-by-year loop. This is an independent closed-form check, not
    a restatement of the code under test."""

    def test_year_one_fcff_hand_worked(self):
        a = _flat_assumptions()
        years = project_cash_flows(a)
        y1 = years[0]
        # revenue_1 = 1000*1.05 = 1050; ebit = 210; da=42; capex=52.5
        # nwc_1=105, nwc_0=100, Δnwc=5
        # fcff = 210*0.72 + 42 - 52.5 - 5 = 135.7
        assert y1.revenue == Decimal("1050.00")
        assert y1.ebit == Decimal("210.0000")
        assert y1.fcff == Decimal("135.70000")

    def test_all_ten_years_grow_at_constant_g(self):
        a = _flat_assumptions()
        years = project_cash_flows(a)
        assert len(years) == 10
        for i in range(1, 10):
            ratio = years[i].fcff / years[i - 1].fcff
            assert abs(ratio - Decimal("1.05")) < Decimal("0.0000001")

    def test_equity_value_matches_geometric_series_closed_form(self):
        a = _flat_assumptions()
        result = dcf_equity_value(a)

        g, r = Decimal("0.05"), Decimal("0.15")
        k = (
            Decimal("0.20") * (Decimal(1) - Decimal("0.28"))
            + Decimal("0.04")
            - Decimal("0.05")
            - Decimal("0.10") * g / (Decimal(1) + g)
        )
        fcff_1 = Decimal(1000) * (Decimal(1) + g) * k
        ratio = (Decimal(1) + g) / (Decimal(1) + r)
        pv_explicit_expected = fcff_1 / (Decimal(1) + r) * (
            (1 - ratio**10) / (1 - ratio) if ratio != 1 else Decimal(10)
        )
        # Standard growing-annuity PV: Σ_{t=1}^{10} fcff_1*ratio^(t-1) discounted once more...
        # simpler: PV = Σ fcff_t/(1+r)^t = fcff_1/(1+r) * Σ_{t=0}^{9} ratio^t
        pv_explicit_expected = (fcff_1 / (Decimal(1) + r)) * sum(ratio**t for t in range(10))

        fcff_10 = fcff_1 * (Decimal(1) + g) ** 9
        fcff_11 = fcff_10 * (Decimal(1) + g)
        terminal_value_expected = fcff_11 / (r - g)
        pv_terminal_expected = terminal_value_expected / (Decimal(1) + r) ** 10

        assert abs(result.pv_explicit_cash_flows - pv_explicit_expected) < Decimal("0.01")
        assert abs(result.terminal_value - terminal_value_expected) < Decimal("0.01")
        assert abs(result.pv_terminal_value - pv_terminal_expected) < Decimal("0.01")

        equity_expected = pv_explicit_expected + pv_terminal_expected
        assert abs(result.equity_value - equity_expected) < Decimal("0.05")
        assert abs(result.value_per_share - equity_expected / 100) < Decimal("0.001")

    def test_no_warnings_when_assumptions_are_sane(self):
        result = dcf_equity_value(_flat_assumptions())
        assert result.warnings == ()


class TestValidation:
    def test_terminal_growth_above_risk_free_warns(self):
        a = _flat_assumptions(terminal_growth=Decimal("0.20"), risk_free_rate=Decimal("0.12"))
        result = dcf_equity_value(a)
        assert any("exceeds risk_free_rate" in w for w in result.warnings)

    def test_discount_rate_at_or_below_terminal_growth_is_flagged_and_zeroed(self):
        a = _flat_assumptions(discount_rate=Decimal("0.05"), terminal_growth=Decimal("0.05"))
        result = dcf_equity_value(a)
        assert any("terminal value is undefined" in w for w in result.warnings)
        assert result.terminal_value == Decimal(0)
        assert result.implied_reinvestment_rate_terminal is None


class TestFadePath:
    def test_two_segment_fade_reaches_targets_exactly(self):
        a = _flat_assumptions(
            revenue_growth_y1=Decimal("0.10"),
            revenue_growth_y2=Decimal("0.10"),
            revenue_growth_stage2_target=Decimal("0.06"),
            terminal_growth=Decimal("0.03"),
        )
        years = project_cash_flows(a)
        growths = [y.revenue_growth for y in years]
        assert growths[0] == Decimal("0.10")
        assert growths[1] == Decimal("0.10")
        # Y3-5 fades linearly from 0.10 to 0.06
        assert growths[4] == Decimal("0.06")
        # Y6-10 fades linearly from 0.06 to 0.03, landing exactly on target at Y10
        assert growths[9] == Decimal("0.03")

    def test_capex_floored_at_depreciation_only_in_terminal_year(self):
        a = _flat_assumptions(
            capex_pct_revenue=Decimal("0.02"),
            depreciation_amortisation_pct_revenue=Decimal("0.05"),
        )
        years = project_cash_flows(a)
        # Years 1-9: capex stays at the trailing 2% (not floored)
        for y in years[:9]:
            assert y.capital_expenditure == y.revenue * Decimal("0.02")
        # Year 10: floored up to the 5% depreciation rate
        assert years[9].capital_expenditure == years[9].revenue * Decimal("0.05")


class TestReverseDCF:
    def test_round_trips_a_known_flat_growth_rate(self):
        a = _flat_assumptions(
            revenue_growth_y1=Decimal("0.08"),
            revenue_growth_y2=Decimal("0.08"),
            revenue_growth_stage2_target=Decimal("0.08"),
            terminal_growth=Decimal("0.05"),
        )
        price = dcf_equity_value(a).value_per_share

        result = implied_flat_growth_rate(a, price)
        assert result.converged
        # Note: a's terminal_growth (0.05) differs from the flat rate (0.08)
        # by construction of implied_flat_growth_rate (terminal is capped at
        # min(g, a.terminal_growth)), so at g=0.08 the solver's own internal
        # assumptions match `a` exactly and should recover 0.08 closely.
        assert abs(result.implied_flat_growth_rate - Decimal("0.08")) < Decimal("0.001")

    def test_price_out_of_range_does_not_converge(self):
        a = _flat_assumptions()
        result = implied_flat_growth_rate(a, current_price_per_share=Decimal("999999"))
        assert not result.converged
        assert result.implied_flat_growth_rate is None
