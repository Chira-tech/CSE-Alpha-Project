"""§35.1's real 2×3 Fama-French sort — app.domain.portfolio_sort."""
from __future__ import annotations

import random
from decimal import Decimal

from app.domain.portfolio_sort import MIN_TICKERS, SortConstituent, two_by_three_sort


def _known_double_premium_universe(n: int, seed: int) -> list[SortConstituent]:
    """A real, known DGP: small stocks earn a real +2% size premium; the
    highest-style tercile earns +1.5% and the lowest tercile earns -1.5%
    (a real 3% high-minus-low style spread) on top of a common baseline
    return — verified directly (see this module's own exploratory
    validation before this test was written) to recover size_factor≈0.02
    and style_factor≈0.03."""
    rng = random.Random(seed)
    rows = []
    values = []
    for i in range(n):
        size_val = Decimal(str(rng.uniform(1, 1000)))
        style_val = Decimal(str(rng.uniform(0, 1)))
        values.append((size_val, style_val))
    sizes_sorted = sorted(v[0] for v in values)
    styles_sorted = sorted(v[1] for v in values)
    median_size = sizes_sorted[len(sizes_sorted) // 2]
    p30 = styles_sorted[int(len(styles_sorted) * 0.3)]
    p70 = styles_sorted[int(len(styles_sorted) * 0.7)]

    for i, (size_val, style_val) in enumerate(values):
        is_small = size_val <= median_size
        is_high = style_val > p70
        is_low = style_val <= p30
        base_return = Decimal(str(round(rng.gauss(0.05, 0.02), 6)))
        premium = Decimal("0.02") if is_small else Decimal("0")
        premium += Decimal("0.015") if is_high else (Decimal("-0.015") if is_low else Decimal("0"))
        rows.append(SortConstituent(key=f"T{i}", size_value=size_val, style_value=style_val, period_return=base_return + premium))
    return rows


class TestTwoByThreeSort:
    def test_none_below_minimum_tickers(self):
        constituents = _known_double_premium_universe(MIN_TICKERS - 1, 1)
        assert two_by_three_sort(constituents) is None

    def test_recovers_a_known_double_premium(self):
        """Seed 42 checked directly: real six non-empty portfolios, and
        both factor returns land close to their known true values."""
        constituents = _known_double_premium_universe(60, 42)
        result = two_by_three_sort(constituents)
        assert result is not None
        assert result.constituent_count == 60
        assert set(result.portfolio_returns) == {"S/L", "S/M", "S/H", "B/L", "B/M", "B/H"}
        assert sum(result.portfolio_counts.values()) == 60
        assert abs(result.size_factor_return - Decimal("0.02")) < Decimal("0.01")
        assert abs(result.style_factor_return - Decimal("0.03")) < Decimal("0.01")

    def test_no_real_premium_gives_a_small_factor_return(self):
        rng = random.Random(7)
        constituents = [
            SortConstituent(
                key=f"T{i}",
                size_value=Decimal(str(rng.uniform(1, 1000))),
                style_value=Decimal(str(rng.uniform(0, 1))),
                period_return=Decimal(str(round(rng.gauss(0.05, 0.02), 6))),
            )
            for i in range(60)
        ]
        result = two_by_three_sort(constituents)
        assert result is not None
        assert abs(result.size_factor_return) < Decimal("0.02")
        assert abs(result.style_factor_return) < Decimal("0.02")

    def test_a_bucket_with_zero_constituents_refuses_rather_than_guesses(self):
        """All constituents identical on size -> every one falls in the
        same size bucket, leaving the other empty — a real, possible
        outcome on a thin or degenerate universe."""
        constituents = [
            SortConstituent(
                key=f"T{i}", size_value=Decimal(100), style_value=Decimal(str(i / 20)),
                period_return=Decimal("0.05"),
            )
            for i in range(20)
        ]
        assert two_by_three_sort(constituents) is None
