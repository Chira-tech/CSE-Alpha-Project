"""§26 price ladder — checked against the spec's own worked example
(JKH.N0000, FV 24.00, MoS 30%, current 21.40) exactly, not approximately."""
from __future__ import annotations

from decimal import Decimal

from app.domain.price_ladder import compute_price_ladder


class TestSpecWorkedExample:
    """§26: 'JKH.N0000 Current: LKR 21.40 ... 16.80 21.40 24.00 27.60 ...
    Status: 27% above your buy-below price ... MoS: 30%.'"""

    def test_thresholds_match_worked_example_exactly(self):
        result = compute_price_ladder(Decimal("24.00"), Decimal("0.30"), Decimal("21.40"))
        assert result.buy_below_price == Decimal("16.800")
        assert result.exit_threshold == Decimal("27.6000")
        assert result.trim_threshold == Decimal("24.00")

    def test_current_price_lands_in_fair_zone(self):
        result = compute_price_ladder(Decimal("24.00"), Decimal("0.30"), Decimal("21.40"))
        assert result.current_zone == "fair"
        assert "Hold; do not add" in result.zone_meaning

    def test_gap_to_buy_below_matches_status_line(self):
        result = compute_price_ladder(Decimal("24.00"), Decimal("0.30"), Decimal("21.40"))
        # (21.40 - 16.80) / 16.80 ≈ 0.2738 → "27% above"
        expected = (Decimal("21.40") - Decimal("16.800")) / Decimal("16.800")
        assert abs(result.gap_to_buy_below_pct - expected) < Decimal("0.0001")
        assert round(result.gap_to_buy_below_pct * 100) == 27


class TestZoneBoundaries:
    def _ladder(self, price: Decimal):
        # FV=100, MoS=20% → strong_accumulate<72, accumulate[72,80),
        # fair[80,100), trim[100,115], exit>115
        return compute_price_ladder(Decimal(100), Decimal("0.20"), price)

    def test_strong_accumulate(self):
        assert self._ladder(Decimal(71)).current_zone == "strong_accumulate"

    def test_accumulate_lower_boundary_inclusive(self):
        assert self._ladder(Decimal(72)).current_zone == "accumulate"

    def test_accumulate_upper_exclusive(self):
        assert self._ladder(Decimal("79.99")).current_zone == "accumulate"

    def test_fair_lower_boundary_inclusive(self):
        assert self._ladder(Decimal(80)).current_zone == "fair"

    def test_fair_upper_exclusive(self):
        assert self._ladder(Decimal("99.99")).current_zone == "fair"

    def test_trim_lower_boundary_inclusive(self):
        assert self._ladder(Decimal(100)).current_zone == "trim"

    def test_trim_upper_boundary_inclusive(self):
        assert self._ladder(Decimal(115)).current_zone == "trim"

    def test_exit_above_upper_boundary(self):
        assert self._ladder(Decimal("115.01")).current_zone == "exit"


class TestNoCurrentPrice:
    def test_thresholds_still_computed_zone_is_none(self):
        result = compute_price_ladder(Decimal(100), Decimal("0.20"))
        assert result.current_zone is None
        assert result.gap_to_buy_below_pct is None
        assert result.buy_below_price == Decimal("80.00")


class TestNonPositiveFairValue:
    def test_warns_but_does_not_crash(self):
        result = compute_price_ladder(Decimal(0), Decimal("0.20"), Decimal(10))
        assert result.warnings
        assert result.current_zone is None
