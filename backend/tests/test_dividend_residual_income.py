"""§19 dividend and residual income models — checked against hand-worked
reference numbers."""
from __future__ import annotations

from decimal import Decimal

from app.domain.dividend_residual_income import (
    DDMStage,
    check_gordon_growth_eligibility,
    compute_multi_stage_ddm,
    compute_residual_income,
    gordon_growth_value,
    sustainable_payout_ratio,
)


class TestSustainablePayout:
    def test_hand_worked(self):
        # 1 - g/ROE = 1 - 0.10/0.20 = 0.5
        assert sustainable_payout_ratio(Decimal("0.10"), Decimal("0.20")) == Decimal("0.5")

    def test_none_when_roe_not_positive(self):
        assert sustainable_payout_ratio(Decimal("0.10"), Decimal("0")) is None
        assert sustainable_payout_ratio(Decimal("0.10"), Decimal("-0.05")) is None

    def test_clipped_to_zero_and_one(self):
        # g > roe → negative raw value, clipped to 0
        assert sustainable_payout_ratio(Decimal("0.30"), Decimal("0.10")) == Decimal("0")
        # g very negative → raw > 1, clipped to 1
        assert sustainable_payout_ratio(Decimal("-1.00"), Decimal("0.10")) == Decimal("1")


class TestGordonGrowth:
    def test_hand_worked(self):
        # V0 = D1/(Ke-g) = 5/(0.15-0.05) = 50
        result = gordon_growth_value(Decimal(5), Decimal("0.15"), Decimal("0.05"))
        assert result.value_per_share == Decimal("50")

    def test_undefined_when_growth_at_or_above_ke(self):
        result = gordon_growth_value(Decimal(5), Decimal("0.10"), Decimal("0.10"))
        assert result.value_per_share is None

    def test_eligibility_all_pass(self):
        payouts = (Decimal("0.40"), Decimal("0.42"), Decimal("0.41"), Decimal("0.43"), Decimal("0.40"))
        elig = check_gordon_growth_eligibility(payouts, Decimal("0.05"), Decimal("0.15"), True)
        assert elig.eligible
        assert elig.payout_stable is True
        assert elig.reasons == ()

    def test_eligibility_fails_on_unstable_payout(self):
        payouts = (Decimal("0.10"), Decimal("0.50"), Decimal("0.20"), Decimal("0.45"), Decimal("0.15"))
        elig = check_gordon_growth_eligibility(payouts, Decimal("0.05"), Decimal("0.15"), True)
        assert not elig.eligible
        assert elig.payout_stable is False

    def test_eligibility_insufficient_history(self):
        elig = check_gordon_growth_eligibility((Decimal("0.4"), Decimal("0.4")), Decimal("0.05"), Decimal("0.15"), True)
        assert elig.payout_stable is None
        assert not elig.eligible


class TestMultiStageDDM:
    def test_hand_worked_single_stage_plus_terminal(self):
        stages = (DDMStage(years=2, eps_growth=Decimal("0.10"), target_payout_ratio=Decimal("0.30")),)
        result = compute_multi_stage_ddm(
            base_eps=Decimal(10),
            roe=Decimal("0.20"),
            stages=stages,
            terminal_growth=Decimal("0.05"),
            terminal_payout_ratio=Decimal("0.30"),
            cost_of_equity=Decimal("0.15"),
        )
        assert len(result.years) == 2
        y1, y2 = result.years
        assert y1.eps == Decimal("11.000")
        assert y1.dividend_per_share == Decimal("3.3000")
        assert not y1.payout_was_capped
        assert y2.eps == Decimal("12.1000")
        assert y2.dividend_per_share == Decimal("3.63000")

        expected_pv_explicit = Decimal("3.3000") / Decimal("1.15") + Decimal("3.63000") / Decimal("1.15") ** 2
        assert abs(result.pv_explicit_dividends - expected_pv_explicit) < Decimal("0.0001")

        expected_terminal_value = (Decimal("12.1000") * Decimal("1.05") * Decimal("0.30")) / Decimal("0.10")
        assert abs(result.terminal_value - expected_terminal_value) < Decimal("0.0001")
        expected_pv_terminal = expected_terminal_value / Decimal("1.15") ** 2
        assert abs(result.pv_terminal_value - expected_pv_terminal) < Decimal("0.0001")

        assert result.value_per_share is not None
        expected_value = expected_pv_explicit + expected_pv_terminal
        assert abs(result.value_per_share - expected_value) < Decimal("0.0001")
        assert result.warnings == ()

    def test_dividend_capacity_capped_by_sustainable_payout(self):
        # Target payout 0.80 but sustainable = 1 - 0.10/0.20 = 0.50 → capped.
        stages = (DDMStage(years=1, eps_growth=Decimal("0.10"), target_payout_ratio=Decimal("0.80")),)
        result = compute_multi_stage_ddm(
            base_eps=Decimal(10),
            roe=Decimal("0.20"),
            stages=stages,
            terminal_growth=Decimal("0.02"),
            terminal_payout_ratio=Decimal("0.80"),
            cost_of_equity=Decimal("0.15"),
        )
        y1 = result.years[0]
        assert y1.payout_was_capped
        assert y1.payout_ratio_used == Decimal("0.5")

    def test_terminal_undefined_when_ke_at_or_below_terminal_growth(self):
        stages = (DDMStage(years=1, eps_growth=Decimal("0.05"), target_payout_ratio=Decimal("0.30")),)
        result = compute_multi_stage_ddm(
            base_eps=Decimal(10),
            roe=Decimal("0.20"),
            stages=stages,
            terminal_growth=Decimal("0.15"),
            terminal_payout_ratio=Decimal("0.30"),
            cost_of_equity=Decimal("0.15"),
        )
        assert result.terminal_value == Decimal(0)
        assert any("terminal value undefined" in w for w in result.warnings)


class TestResidualIncome:
    def test_hand_worked_terminal_roe_equals_ke_zeroes_terminal(self):
        result = compute_residual_income(
            book_value_per_share_t0=Decimal(100),
            cost_of_equity=Decimal("0.15"),
            roe_forecast_path=(Decimal("0.20"),),
            book_value_growth_path=(Decimal("0.05"),),
            terminal_roe=Decimal("0.15"),
            terminal_growth=Decimal("0.03"),
        )
        y1 = result.years[0]
        assert y1.beginning_book_value == Decimal(100)
        # RI_1 = (0.20 - 0.15) * 100 = 5
        assert y1.residual_income == Decimal("5.00")
        assert y1.ending_book_value == Decimal("105.00")

        expected_pv_explicit = Decimal("5.00") / Decimal("1.15")
        assert abs(result.pv_explicit_residual_income - expected_pv_explicit) < Decimal("0.0001")
        # terminal_roe == ke → terminal residual income is exactly 0
        assert result.terminal_residual_income_value == Decimal(0)

        expected_value = Decimal(100) + expected_pv_explicit
        assert abs(result.value_per_share - expected_value) < Decimal("0.0001")

    def test_mismatched_path_lengths_returns_warning_not_crash(self):
        result = compute_residual_income(
            book_value_per_share_t0=Decimal(100),
            cost_of_equity=Decimal("0.15"),
            roe_forecast_path=(Decimal("0.20"), Decimal("0.18")),
            book_value_growth_path=(Decimal("0.05"),),
            terminal_roe=Decimal("0.15"),
            terminal_growth=Decimal("0.03"),
        )
        assert result.value_per_share is None
        assert "must be the same length" in result.warnings[0]

    def test_terminal_undefined_when_ke_at_or_below_terminal_growth(self):
        result = compute_residual_income(
            book_value_per_share_t0=Decimal(100),
            cost_of_equity=Decimal("0.10"),
            roe_forecast_path=(Decimal("0.20"),),
            book_value_growth_path=(Decimal("0.05"),),
            terminal_roe=Decimal("0.18"),
            terminal_growth=Decimal("0.10"),
        )
        assert result.terminal_residual_income_value == Decimal(0)
        assert any("terminal residual income value undefined" in w for w in result.warnings)

    def test_higher_roe_produces_higher_value_all_else_equal(self):
        low = compute_residual_income(
            Decimal(100), Decimal("0.15"), (Decimal("0.12"),), (Decimal("0.05"),), Decimal("0.15"), Decimal("0.03")
        )
        high = compute_residual_income(
            Decimal(100), Decimal("0.15"), (Decimal("0.25"),), (Decimal("0.05"),), Decimal("0.15"), Decimal("0.03")
        )
        assert high.value_per_share > low.value_per_share
