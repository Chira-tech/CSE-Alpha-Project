"""§22 asset-based / NAV valuation — hand-worked reference values."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.asset_based_valuation import (
    compute_hard_book,
    compute_liquidation_value,
    compute_plantation_hard_nav,
    hotel_replacement_cost_check,
    value_land,
)


class TestHardBook:
    def test_hand_worked(self):
        result = compute_hard_book(Decimal(1000), Decimal(300), Decimal(100))
        assert result.hard_book_value == Decimal(700)
        assert result.hard_book_per_share == Decimal(7)

    def test_no_shares_gives_none_per_share(self):
        result = compute_hard_book(Decimal(1000), Decimal(300))
        assert result.hard_book_per_share is None


class TestLandValuation:
    def test_independent_mark_used_when_supplied(self):
        result = value_land(
            "Estate A", Decimal(10), "acre", cost_basis_per_unit=Decimal(500),
            independent_reference_value_per_unit=Decimal(2000), reference_date=dt.date(2025, 1, 1),
        )
        assert result.basis == "independent_mark"
        assert result.total_value == Decimal(20000)

    def test_falls_back_to_cost_and_labels_it(self):
        result = value_land("Estate B", Decimal(10), "acre", cost_basis_per_unit=Decimal(500))
        assert result.basis == "cost"
        assert result.total_value == Decimal(5000)
        assert "labelled as cost" in result.note


class TestHotelReplacementCost:
    def test_discount_to_replacement_cost(self):
        result = hotel_replacement_cost_check(keys=100, enterprise_value=Decimal(1_500_000), recent_build_cost_per_key=Decimal(20_000))
        assert result.ev_per_key == Decimal(15_000)
        # (20000-15000)/20000 = 0.25
        assert result.discount_to_replacement_cost_pct == Decimal("0.25")

    def test_zero_keys_handled(self):
        result = hotel_replacement_cost_check(keys=0, enterprise_value=Decimal(100), recent_build_cost_per_key=Decimal(1))
        assert result.ev_per_key is None


class TestPlantationHardNAV:
    def test_hand_worked(self):
        result = compute_plantation_hard_nav(
            mature_hectares=Decimal(100),
            immature_hectares=Decimal(50),
            mature_value_per_hectare=Decimal(3_000_000),
            immature_value_per_hectare=Decimal(1_000_000),
            other_hard_assets=Decimal(10_000_000),
            net_debt=Decimal(5_000_000),
            recent_transaction_value_per_hectare=Decimal(2_400_000),
        )
        # mature 300M + immature 50M = 350M; blended = 350M/150 ≈ 2,333,333.33
        assert result.mature_value == Decimal(300_000_000)
        assert result.immature_value == Decimal(50_000_000)
        assert result.total_hard_nav == Decimal(355_000_000)  # 350M+10M-5M
        expected_blended = Decimal(350_000_000) / Decimal(150)
        assert abs(result.blended_value_per_hectare - expected_blended) < Decimal("0.01")
        expected_variance = (expected_blended - Decimal(2_400_000)) / Decimal(2_400_000)
        assert abs(result.variance_to_recent_transaction_pct - expected_variance) < Decimal("0.0001")

    def test_no_transaction_reference_gives_none_variance(self):
        result = compute_plantation_hard_nav(
            mature_hectares=Decimal(100), immature_hectares=Decimal(0),
            mature_value_per_hectare=Decimal(1), immature_value_per_hectare=Decimal(1),
        )
        assert result.variance_to_recent_transaction_pct is None


class TestLiquidationValue:
    def test_hand_worked_floor(self):
        result = compute_liquidation_value(
            cash_and_equivalents=Decimal(100),
            receivables=Decimal(200),
            receivables_recovery_rate=Decimal("0.80"),
            inventory=Decimal(150),
            inventory_recovery_rate=Decimal("0.50"),
            ppe_at_liquidation_value=Decimal(400),
            other_assets_at_liquidation_value=Decimal(50),
            total_liabilities=Decimal(600),
            diluted_shares_outstanding=Decimal(100),
        )
        # recoverable = 100 + 160 + 75 + 400 + 50 = 785
        assert result.recoverable_assets == Decimal("785.00")
        assert result.liquidation_equity_value == Decimal("185.00")
        assert result.liquidation_value_per_share == Decimal("1.8500")
