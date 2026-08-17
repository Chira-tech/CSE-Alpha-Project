"""§21 sum-of-the-parts — hand-worked waterfall."""
from __future__ import annotations

from decimal import Decimal

from app.domain.sotp import (
    Associate,
    InvestmentProperty,
    ListedSubsidiary,
    SOTPInputs,
    UnlistedSubsidiary,
    calibrate_holding_company_discount,
    compute_sotp,
)


class TestHoldingCompanyDiscount:
    def test_within_range_not_clamped(self):
        result = calibrate_holding_company_discount(Decimal("0.20"))
        assert result.discount_pct == Decimal("0.20")
        assert not result.was_clamped

    def test_adjustments_sum_before_clamping(self):
        result = calibrate_holding_company_discount(
            Decimal("0.18"),
            capital_allocation_adjustment=Decimal("0.02"),
            related_party_flow_adjustment=Decimal("0.03"),
            free_float_adjustment=Decimal("-0.01"),
        )
        assert result.raw_discount_pct == Decimal("0.22")
        assert result.discount_pct == Decimal("0.22")

    def test_clamped_below_minimum(self):
        result = calibrate_holding_company_discount(Decimal("0.05"))
        assert result.discount_pct == Decimal("0.15")
        assert result.was_clamped

    def test_clamped_above_maximum(self):
        result = calibrate_holding_company_discount(Decimal("0.50"))
        assert result.discount_pct == Decimal("0.35")
        assert result.was_clamped


class TestComputeSOTP:
    def test_hand_worked_waterfall(self):
        inputs = SOTPInputs(
            listed_subsidiaries=(ListedSubsidiary("Sub A", Decimal(1000), Decimal("0.60")),),
            unlisted_subsidiaries=(
                UnlistedSubsidiary("Sub B", Decimal(100), Decimal(6), Decimal("0.80")),
            ),
            investment_properties=(InvestmentProperty("Land X", Decimal(200)),),
            associates=(Associate("Assoc C", Decimal(50)),),
            net_cash_at_holdco=Decimal(30),
            holdco_net_debt=Decimal(80),
            diluted_shares_outstanding=Decimal(100),
        )
        discount = calibrate_holding_company_discount(Decimal("0.20"))
        result = compute_sotp(inputs, discount)

        # Listed: 1000*0.60=600; Unlisted: 100*6*0.80=480; property 200;
        # associate 50; net cash 30 → gross = 1360
        assert result.gross_asset_value == Decimal("1360")
        assert result.nav_before_discount == Decimal("1280")  # 1360-80
        assert result.discount_amount == Decimal("256.00")  # 1280*0.20
        assert result.equity_value == Decimal("1024.00")
        assert result.value_per_share == Decimal("10.2400")
        assert len(result.segments) == 5
        assert result.warnings == ()

    def test_negative_nav_zeroes_discount_and_warns(self):
        inputs = SOTPInputs(
            listed_subsidiaries=(ListedSubsidiary("Sub A", Decimal(100), Decimal("0.10")),),
            holdco_net_debt=Decimal(500),
            diluted_shares_outstanding=Decimal(100),
        )
        discount = calibrate_holding_company_discount(Decimal("0.20"))
        result = compute_sotp(inputs, discount)
        assert result.nav_before_discount < 0
        assert result.discount_amount == Decimal(0)
        assert result.equity_value == result.nav_before_discount
        assert any("not economically meaningful" in w for w in result.warnings)
