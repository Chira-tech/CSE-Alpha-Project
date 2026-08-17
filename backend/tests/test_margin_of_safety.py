"""§25 margin of safety — hand-worked components and bounding."""
from __future__ import annotations

from decimal import Decimal

from app.domain.margin_of_safety import (
    compute_margin_of_safety,
    data_completeness_component,
    dispersion_component,
    liquidity_component,
    quality_integrity_component,
    regime_component,
)


class TestDispersionComponent:
    def test_hand_worked_under_cap(self):
        result = dispersion_component(Decimal("0.20"))
        assert result == Decimal("0.10")  # 0.20 * 0.5

    def test_capped_at_15_pct(self):
        result = dispersion_component(Decimal("0.50"))
        assert result == Decimal("0.15")

    def test_none_passthrough(self):
        assert dispersion_component(None) is None


class TestLiquidityComponent:
    def test_top_quartile_is_zero(self):
        assert liquidity_component(Decimal(90)) == Decimal(0)
        assert liquidity_component(Decimal(75)) == Decimal(0)

    def test_bottom_quartile_is_cap(self):
        assert liquidity_component(Decimal(10)) == Decimal("0.10")
        assert liquidity_component(Decimal(25)) == Decimal("0.10")

    def test_midpoint_interpolation(self):
        # percentile 50 is exactly between the 25/75 anchors → half the cap
        result = liquidity_component(Decimal(50))
        assert result == Decimal("0.05")


class TestRegimeComponent:
    def test_named_regimes(self):
        assert regime_component("risk_on") == Decimal("0.00")
        assert regime_component("transition") == Decimal("0.05")
        assert regime_component("risk_off") == Decimal("0.12")

    def test_none_and_unknown(self):
        assert regime_component(None) is None
        assert regime_component("not_a_regime") is None


class TestQualityIntegrityComponent:
    def test_hand_worked_capped(self):
        # (0.70 - 0.65) * 4 = 0.20 → capped at 0.08
        assert quality_integrity_component(Decimal("0.65")) == Decimal("0.08")

    def test_exactly_at_cap_boundary(self):
        # (0.70 - 0.68) * 4 = 0.08 exactly
        assert quality_integrity_component(Decimal("0.68")) == Decimal("0.08")

    def test_above_threshold_floored_at_zero(self):
        assert quality_integrity_component(Decimal("0.75")) == Decimal(0)

    def test_none_passthrough(self):
        assert quality_integrity_component(None) is None


class TestDataCompletenessComponent:
    def test_hand_worked_capped(self):
        # (0.90 - 0.85) * 5 = 0.25 → capped at 0.10
        assert data_completeness_component(Decimal("0.85")) == Decimal("0.10")

    def test_under_cap(self):
        # (0.90 - 0.89) * 5 = 0.05
        assert data_completeness_component(Decimal("0.89")) == Decimal("0.05")

    def test_full_completeness_floored_at_zero(self):
        assert data_completeness_component(Decimal("0.95")) == Decimal(0)


class TestComputeMarginOfSafety:
    def test_hand_worked_all_present(self):
        result = compute_margin_of_safety(
            dispersion_pct=Decimal("0.10"),
            liquidity_percentile=Decimal(50),
            regime="transition",
            integrity_score=Decimal("0.65"),
            data_completeness_pct=Decimal("0.85"),
        )
        # base .10 + dispersion .05 + liquidity .05 + regime .05 + quality .08 + completeness .10 = .43
        assert result.total_pct == Decimal("0.43")
        assert not result.was_bounded
        assert not result.is_lower_bound
        assert result.missing_components == ()

    def test_all_missing_gives_base_only_and_lower_bound(self):
        result = compute_margin_of_safety(None, None, None, None, None)
        assert result.total_pct == Decimal("0.10")
        assert result.is_lower_bound
        assert len(result.missing_components) == 5
        assert "LOWER BOUND" in result.note

    def test_extreme_inputs_clamp_to_55_pct_ceiling(self):
        result = compute_margin_of_safety(
            dispersion_pct=Decimal("1.0"),
            liquidity_percentile=Decimal(0),
            regime="risk_off",
            integrity_score=Decimal(0),
            data_completeness_pct=Decimal(0),
        )
        assert result.total_pct == Decimal("0.55")
        assert result.was_bounded

    def test_total_never_below_base_even_with_partial_missing(self):
        result = compute_margin_of_safety(
            dispersion_pct=None, liquidity_percentile=None, regime=None,
            integrity_score=None, data_completeness_pct=None,
        )
        assert result.total_pct >= Decimal("0.10")
