"""
§17.2: Ke = Rf_LKR + β_adjusted × ERP_effective + size_premium + illiquidity_premium

Rf_LKR (10.01%) is the real, scraped 364-day primary T-bill yield used
throughout this session's macro work. Beta (1.07) is COMB.N0000's real
Blume-adjusted beta from `test_beta.py`'s own captured data — the two
modules' real outputs are chained together here, not invented figures.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.cost_of_equity import CostOfEquityInputs, compute_cost_of_equity

REAL_RF = Decimal("0.1001")  # 364-day T-bill, primary market, 12 Aug 2026 edition
REAL_BETA = Decimal("1.131218")  # COMB.N0000 Blume-adjusted, test_beta.py's real fixture


class TestFullyComputable:
    def test_ke_with_all_four_components(self):
        result = compute_cost_of_equity(
            CostOfEquityInputs(
                risk_free_rate=REAL_RF,
                beta=REAL_BETA,
                erp_effective=Decimal("0.07"),
                size_premium=Decimal("0.015"),
                illiquidity_premium=Decimal("0.01"),
            )
        )
        expected = REAL_RF + REAL_BETA * Decimal("0.07") + Decimal("0.015") + Decimal("0.01")
        assert result.ke == expected
        assert not result.is_lower_bound
        assert result.missing_components == ()

    def test_beta_times_erp_is_broken_out_separately(self):
        """§17.2: "the resulting Ke is displayed with its components
        broken out" — not just the final number."""
        result = compute_cost_of_equity(
            CostOfEquityInputs(
                risk_free_rate=REAL_RF, beta=REAL_BETA, erp_effective=Decimal("0.07"),
                size_premium=Decimal(0), illiquidity_premium=Decimal(0),
            )
        )
        assert result.beta_times_erp == REAL_BETA * Decimal("0.07")


class TestMissingPremiumsProduceALowerBound:
    def test_ke_is_computed_but_flagged_as_a_lower_bound(self):
        """size_premium and illiquidity_premium are non-negative by
        definition (0 to ~2.5%, 0 to ~3.0%) — treating them as 0 when
        genuinely unknown can only UNDERSTATE Ke, so the result must say
        so rather than looking like a complete number."""
        result = compute_cost_of_equity(
            CostOfEquityInputs(risk_free_rate=REAL_RF, beta=REAL_BETA, erp_effective=Decimal("0.07"))
        )
        assert result.ke is not None
        assert result.is_lower_bound
        assert "LOWER BOUND" in result.note
        assert len(result.missing_components) == 2

    def test_ke_still_computes_with_only_one_premium_missing(self):
        result = compute_cost_of_equity(
            CostOfEquityInputs(
                risk_free_rate=REAL_RF, beta=REAL_BETA, erp_effective=Decimal("0.07"),
                size_premium=Decimal("0.015"),
            )
        )
        assert result.ke is not None
        assert result.is_lower_bound
        assert result.missing_components == (
            "illiquidity_premium (needs Amihud percentile — needs real turnover history, "
            "confirmed unavailable this session)",
        )


class TestCannotComputeWithoutBetaOrRiskFreeRate:
    def test_no_beta_means_no_ke_at_all(self):
        result = compute_cost_of_equity(
            CostOfEquityInputs(risk_free_rate=REAL_RF, beta=None, erp_effective=Decimal("0.07"))
        )
        assert result.ke is None
        assert "beta" in result.note

    def test_no_risk_free_rate_means_no_ke_at_all(self):
        """`risk_free_observation` returning None rather than a
        substituted rate must propagate all the way through, not get
        silently defaulted to zero somewhere in the chain."""
        result = compute_cost_of_equity(
            CostOfEquityInputs(risk_free_rate=None, beta=REAL_BETA, erp_effective=Decimal("0.07"))
        )
        assert result.ke is None
        assert "risk_free_rate" in result.note

    def test_missing_beta_and_rate_are_both_named_when_both_are_missing(self):
        result = compute_cost_of_equity(
            CostOfEquityInputs(risk_free_rate=None, beta=None, erp_effective=Decimal("0.07"))
        )
        assert result.ke is None
        assert "risk_free_rate" in result.note and "beta" in result.note
        assert len(result.missing_components) == 4  # rf, beta, size, illiquidity


class TestImpliedErpIsDisplayOnly:
    def test_implied_erp_cross_check_never_substitutes_for_erp_effective(self):
        """§17.1's third reference point — passed straight through, never
        blended into the actual Ke computation."""
        result = compute_cost_of_equity(
            CostOfEquityInputs(
                risk_free_rate=REAL_RF, beta=REAL_BETA, erp_effective=Decimal("0.07"),
                size_premium=Decimal(0), illiquidity_premium=Decimal(0),
                implied_erp_cross_check=Decimal("-0.0124"),  # this session's real hero spread
            )
        )
        assert result.implied_erp_cross_check == Decimal("-0.0124")
        assert result.erp_effective == Decimal("0.07")  # untouched by the cross-check
        assert result.beta_times_erp == REAL_BETA * Decimal("0.07")  # not REAL_BETA * -0.0124
