"""CSE tick size + the E2 tolerance fraction (`app.domain.tick_size`)."""
from __future__ import annotations

from decimal import Decimal

from app.domain.tick_size import price_tolerance_fraction, tick_size


class TestTickSize:
    def test_ten_cents_at_or_below_a_hundred(self):
        assert tick_size(Decimal("1.60")) == Decimal("0.10")
        assert tick_size(Decimal("100")) == Decimal("0.10")

    def test_twenty_five_cents_above_a_hundred(self):
        assert tick_size(Decimal("100.25")) == Decimal("0.25")
        assert tick_size(Decimal("343.75")) == Decimal("0.25")


class TestToleranceFraction:
    def test_tick_term_wins_on_a_cheap_line(self):
        # 1.60: two 0.10 ticks / 1.60 = 12.5%, above a 5% floor.
        assert price_tolerance_fraction(Decimal("1.60"), pct_floor=Decimal("0.05")) == Decimal("0.125")

    def test_floor_wins_once_the_price_is_more_than_a_few_rupees(self):
        assert price_tolerance_fraction(Decimal("118.25"), pct_floor=Decimal("0.05")) == Decimal("0.05")

    def test_a_non_positive_price_falls_back_to_the_floor(self):
        assert price_tolerance_fraction(Decimal("0"), pct_floor=Decimal("0.01")) == Decimal("0.01")
