"""§20 justified multiples — hand-worked reference values."""
from __future__ import annotations

from decimal import Decimal

from app.domain.relative_valuation import (
    compare_to_justified,
    justified_ev_to_ebit,
    justified_price_to_book,
    justified_price_to_earnings,
    justified_price_to_sales,
)


class TestJustifiedPE:
    def test_hand_worked(self):
        # 0.5 * 1.05 / 0.10 = 5.25
        result = justified_price_to_earnings(Decimal("0.5"), Decimal("0.05"), Decimal("0.15"))
        assert result.value == Decimal("5.25")

    def test_none_when_ke_at_or_below_growth(self):
        result = justified_price_to_earnings(Decimal("0.5"), Decimal("0.15"), Decimal("0.15"))
        assert result.value is None
        assert "Ke" in result.note


class TestJustifiedPB:
    def test_hand_worked(self):
        # (0.20 - 0.05) / (0.15 - 0.05) = 1.5
        result = justified_price_to_book(Decimal("0.20"), Decimal("0.05"), Decimal("0.15"))
        assert result.value == Decimal("1.5")


class TestJustifiedEvEbit:
    def test_hand_worked(self):
        # (1-0.28) * (1 - 0.05/0.20) / (0.15-0.05) = 0.72*0.75/0.10 = 5.4
        result = justified_ev_to_ebit(Decimal("0.28"), Decimal("0.05"), Decimal("0.20"), Decimal("0.15"))
        assert result.value == Decimal("5.4")

    def test_none_without_roic(self):
        result = justified_ev_to_ebit(Decimal("0.28"), Decimal("0.05"), None, Decimal("0.15"))
        assert result.value is None
        assert "NOT_YET_COMPUTABLE" in result.note


class TestJustifiedPS:
    def test_hand_worked(self):
        # 0.10 * 0.5 * 1.05 / 0.10 = 0.525
        result = justified_price_to_sales(Decimal("0.10"), Decimal("0.5"), Decimal("0.05"), Decimal("0.15"))
        assert result.value == Decimal("0.525")


class TestCompareToJustified:
    def test_trading_below_justified_reads_cheap(self):
        justified = justified_price_to_earnings(Decimal("0.5"), Decimal("0.05"), Decimal("0.15"))
        comparison = compare_to_justified(justified, Decimal("4.0"))
        assert comparison.read_as_cheap is True
        expected_discount = (Decimal("5.25") - Decimal("4.0")) / Decimal("5.25")
        assert abs(comparison.discount_to_justified_pct - expected_discount) < Decimal("0.0001")

    def test_trading_above_justified_reads_expensive(self):
        justified = justified_price_to_earnings(Decimal("0.5"), Decimal("0.05"), Decimal("0.15"))
        comparison = compare_to_justified(justified, Decimal("8.0"))
        assert comparison.read_as_cheap is False

    def test_missing_trading_value_is_none_not_crash(self):
        justified = justified_price_to_earnings(Decimal("0.5"), Decimal("0.05"), Decimal("0.15"))
        comparison = compare_to_justified(justified, None)
        assert comparison.read_as_cheap is None
        assert comparison.discount_to_justified_pct is None
