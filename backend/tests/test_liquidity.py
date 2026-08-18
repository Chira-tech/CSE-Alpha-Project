"""app.domain.liquidity — real Amihud illiquidity ratio, percentile
ranking, and the shared liquidity-percentile interpolation rule §17.2's
Ke illiquidity premium and §25's MoS liquidity component both consume.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.liquidity import (
    ILLIQUIDITY_PREMIUM_CAP,
    MIN_OBSERVATIONS,
    amihud_illiquidity_ratio,
    illiquidity_premium_from_percentile,
    liquidity_percentile_band,
    percentile_rank,
)


class TestAmihudIlliquidityRatio:
    def test_none_below_minimum_observations(self):
        returns = [Decimal("0.01")] * (MIN_OBSERVATIONS - 1)
        turnovers = [Decimal("1000000")] * (MIN_OBSERVATIONS - 1)
        assert amihud_illiquidity_ratio(returns, turnovers) is None

    def test_mismatched_lengths_raises(self):
        try:
            amihud_illiquidity_ratio([Decimal("0.01")] * 30, [Decimal("1")] * 29)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_zero_turnover_days_are_excluded_not_averaged_as_infinite(self):
        """A real untraded day (turnover=0) must not blow up the ratio
        or silently count toward the minimum — it's excluded entirely."""
        returns = [Decimal("0.01")] * MIN_OBSERVATIONS + [Decimal("0.5")]
        turnovers = [Decimal("1000000")] * MIN_OBSERVATIONS + [Decimal("0")]
        result = amihud_illiquidity_ratio(returns, turnovers)
        assert result is not None
        # Hand-worked: every real day has ratio 0.01/1,000,000 = 1e-8.
        assert result == Decimal("0.01") / Decimal("1000000")

    def test_a_hand_worked_known_ratio(self):
        returns = [Decimal("0.02"), Decimal("0.04")] + [Decimal("0")] * (MIN_OBSERVATIONS - 2)
        turnovers = [Decimal("1000"), Decimal("2000")] + [Decimal("1000")] * (MIN_OBSERVATIONS - 2)
        result = amihud_illiquidity_ratio(returns, turnovers)
        # (0.02/1000 + 0.04/2000 + 0*(MIN_OBSERVATIONS-2)) / MIN_OBSERVATIONS
        expected = (Decimal("0.02") / Decimal("1000") + Decimal("0.04") / Decimal("2000")) / Decimal(MIN_OBSERVATIONS)
        assert result == expected

    def test_a_thinly_traded_high_impact_stock_ranks_more_illiquid(self):
        """The real, intuitive check: a stock whose price moves a lot on
        very little rupee turnover has a HIGHER Amihud ratio (less
        liquid) than one that moves little on heavy turnover."""
        thin_returns = [Decimal("0.05")] * MIN_OBSERVATIONS
        thin_turnovers = [Decimal("10000")] * MIN_OBSERVATIONS
        heavy_returns = [Decimal("0.001")] * MIN_OBSERVATIONS
        heavy_turnovers = [Decimal("50000000")] * MIN_OBSERVATIONS
        thin_ratio = amihud_illiquidity_ratio(thin_returns, thin_turnovers)
        heavy_ratio = amihud_illiquidity_ratio(heavy_returns, heavy_turnovers)
        assert thin_ratio is not None and heavy_ratio is not None
        assert thin_ratio > heavy_ratio


class TestPercentileRank:
    def test_empty_input(self):
        assert percentile_rank({}) == {}

    def test_single_key_gets_the_neutral_midpoint(self):
        assert percentile_rank({"A": Decimal("0.001")}) == {"A": Decimal(50)}

    def test_lower_amihud_ratio_gets_a_higher_percentile(self):
        """HIGHER percentile = MORE liquid, the opposite direction from
        the raw ratio — see module docstring."""
        ranks = percentile_rank({
            "MOST_LIQUID": Decimal("0.0001"),
            "MIDDLE": Decimal("0.001"),
            "LEAST_LIQUID": Decimal("0.01"),
        })
        assert ranks["MOST_LIQUID"] > ranks["MIDDLE"] > ranks["LEAST_LIQUID"]
        assert ranks["MOST_LIQUID"] == Decimal(100)
        assert ranks["LEAST_LIQUID"] == Decimal(0)

    def test_hand_worked_four_key_ranking(self):
        ranks = percentile_rank({"A": Decimal(4), "B": Decimal(3), "C": Decimal(2), "D": Decimal(1)})
        # D has the lowest (best) ratio -> most liquid -> percentile 100.
        # A has the highest (worst) ratio -> least liquid -> percentile 0.
        assert ranks["D"] == Decimal(100)
        assert ranks["C"] == Decimal(100) * Decimal(2) / Decimal(3)
        assert ranks["B"] == Decimal(100) * Decimal(1) / Decimal(3)
        assert ranks["A"] == Decimal(0)


class TestLiquidityPercentileBand:
    def test_none_propagates(self):
        assert liquidity_percentile_band(None, Decimal("0.10")) is None

    def test_top_quartile_gives_zero(self):
        assert liquidity_percentile_band(Decimal(80), Decimal("0.10")) == Decimal(0)
        assert liquidity_percentile_band(Decimal(75), Decimal("0.10")) == Decimal(0)

    def test_bottom_quartile_gives_the_full_cap(self):
        assert liquidity_percentile_band(Decimal(20), Decimal("0.10")) == Decimal("0.10")
        assert liquidity_percentile_band(Decimal(25), Decimal("0.10")) == Decimal("0.10")

    def test_midpoint_gives_half_the_cap(self):
        assert liquidity_percentile_band(Decimal(50), Decimal("0.10")) == Decimal("0.05")

    def test_different_caps_scale_proportionally_at_the_same_percentile(self):
        """The shared interpolation shape at the same percentile, two
        different real consumers' own caps (§25's 10% vs §17.2's 3%)."""
        mos_value = liquidity_percentile_band(Decimal(50), Decimal("0.10"))
        ke_value = liquidity_percentile_band(Decimal(50), ILLIQUIDITY_PREMIUM_CAP)
        assert mos_value == Decimal("0.05")
        assert ke_value == Decimal("0.015")


class TestIlliquidityPremiumFromPercentile:
    def test_none_propagates(self):
        assert illiquidity_premium_from_percentile(None) is None

    def test_matches_section_172s_own_stated_range(self):
        """§17.2: "illiquidity_premium: 0 to ~3.0%.\""""
        most_liquid = illiquidity_premium_from_percentile(Decimal(100))
        least_liquid = illiquidity_premium_from_percentile(Decimal(0))
        assert most_liquid == Decimal(0)
        assert least_liquid == ILLIQUIDITY_PREMIUM_CAP == Decimal("0.03")
