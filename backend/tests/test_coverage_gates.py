"""Master Spec §11 / §11.1 — coverage tier classification."""
from __future__ import annotations

from decimal import Decimal

from app.domain.coverage_gates import (
    Gate1Inputs,
    Gate2Inputs,
    Gate3Inputs,
    classify_coverage_tier,
    evaluate_gate1_liquidity,
    evaluate_gate2_structural,
    evaluate_gate3_integrity,
    gate1_liquidity_reason,
)
from app.models.enums import CoverageTier


def _clean_gate2() -> Gate2Inputs:
    return Gate2Inputs(
        free_float_pct=Decimal("0.30"),
        on_watch_list=False,
        trading_suspended=False,
        months_listed=60,
        market_cap_lkr=Decimal("5000000000"),
        consecutive_quarters_history=20,
    )


def _clean_gate3() -> Gate3Inputs:
    return Gate3Inputs(
        qualified_audit_opinion=False,
        going_concern_emphasis=False,
        auditor_change_and_cfo_departure_same_12m=False,
        beneish_m_score=Decimal("-2.5"),
        related_party_revenue_or_receivables_pct=Decimal("0.05"),
    )


def _clean_gate1() -> Gate1Inputs:
    return Gate1Inputs(
        median_daily_turnover_60d_lkr=Decimal("5000000"),
        days_traded_last_60=58,
        amihud_illiquidity_percentile=Decimal("0.40"),
        position_value_lkr=Decimal("1000000"),
        adv_20d_lkr=Decimal("10000000"),
    )


def test_gate1_passes_when_all_thresholds_met():
    result = evaluate_gate1_liquidity(_clean_gate1())
    assert result.passed
    assert result.reasons_failed == ()


def test_gate1_fails_on_low_turnover():
    inputs = Gate1Inputs(
        median_daily_turnover_60d_lkr=Decimal("500000"),  # below LKR 2.0m default
        days_traded_last_60=58,
        amihud_illiquidity_percentile=Decimal("0.40"),
        position_value_lkr=Decimal("1000000"),
        adv_20d_lkr=Decimal("10000000"),
    )
    result = evaluate_gate1_liquidity(inputs)
    assert not result.passed
    assert any("turnover" in reason for reason in result.reasons_failed)


def test_gate1_fails_when_position_too_large_vs_adv():
    inputs = Gate1Inputs(
        median_daily_turnover_60d_lkr=Decimal("5000000"),
        days_traded_last_60=58,
        amihud_illiquidity_percentile=Decimal("0.40"),
        position_value_lkr=Decimal("2000000"),
        adv_20d_lkr=Decimal("5000000"),  # 40% of ADV > 15% cap
    )
    result = evaluate_gate1_liquidity(inputs)
    assert not result.passed
    assert any("ADV" in reason for reason in result.reasons_failed)


class TestGate1LiquidityReason:
    """The position-independent half of Gate 1, used by `app.domain.
    opportunity_ranking_view` to keep a real, unbuyable-at-any-size stock
    from ranking as a "buy" purely on discount-to-book — found live (30
    Aug 2026) auditing real ranked candidates: LVEN.N0000 was trading
    LKR 5,199/day, far below this gate's real LKR 2,000,000 bar, and
    still surfaced as a top "Accumulate" purely on discount-to-book."""

    def test_passes_when_both_real_thresholds_are_met(self):
        assert gate1_liquidity_reason(Decimal("5000000"), 58, days_of_real_history_available=60) is None

    def test_fails_on_low_turnover_with_the_real_numbers_named(self):
        reason = gate1_liquidity_reason(Decimal("5199"), 58, days_of_real_history_available=60)
        assert reason is not None
        assert "5,199" in reason
        assert "2,000,000" in reason

    def test_fails_on_too_few_days_traded_with_the_real_numbers_named(self):
        reason = gate1_liquidity_reason(Decimal("5000000"), 6, days_of_real_history_available=60)
        assert reason is not None
        assert "6 of the last 60" in reason
        assert "45" in reason

    def test_names_both_reasons_when_both_fail(self):
        reason = gate1_liquidity_reason(Decimal("0"), 0, days_of_real_history_available=60)
        assert reason is not None
        assert "turnover" in reason
        assert "traded" in reason

    def test_does_not_evaluate_the_amihud_or_position_impact_checks(self):
        """A stock with real turnover and real trading days must pass
        this specific check regardless of how idiosyncratically illiquid
        it might be by other measures — those two checks need inputs
        (a universe-wide Amihud scan, a hypothetical position size) this
        function deliberately doesn't take, per its own docstring."""
        assert gate1_liquidity_reason(Decimal("2000001"), 45, days_of_real_history_available=60) is None

    def test_skips_the_days_traded_check_when_not_enough_real_history_exists_yet(self):
        """Found live (30 Aug 2026) applying this very fix: EVERY real
        ticker in the dev universe, including SAMP.N0000 and JKH.N0000
        (the exchange's own most liquid names, turnover in the tens of
        millions of rupees a day), topped out at 40-41 real trading days
        in the trailing 60 calendar days — this system's own forward-
        captured price history doesn't span 45 real trading days for
        ANYONE yet. A stock that traded every single one of the (few)
        real days on file must not be failed for not having MORE real
        days than the system itself has been running."""
        reason = gate1_liquidity_reason(Decimal("50000000"), 40, days_of_real_history_available=41)
        assert reason is None

    def test_still_fails_on_turnover_even_when_the_days_traded_check_is_skipped(self):
        reason = gate1_liquidity_reason(Decimal("5199"), 40, days_of_real_history_available=41)
        assert reason is not None
        assert "turnover" in reason
        assert "traded" not in reason

    def test_evaluates_days_traded_once_real_history_reaches_the_real_60_day_window(self):
        reason = gate1_liquidity_reason(Decimal("5000000"), 6, days_of_real_history_available=60)
        assert reason is not None
        assert "traded" in reason


def test_gate2_fails_when_free_float_is_unknown_rather_than_passing():
    """A hard gate must never pass on absent evidence. `None` means the
    shareholding disclosure hasn't been ingested, not that the float is
    fine — treating it as a pass would let a company through Gate 2 on
    data nobody has."""
    inputs = Gate2Inputs(
        free_float_pct=None,
        on_watch_list=False,
        trading_suspended=False,
        months_listed=60,
        market_cap_lkr=Decimal("5000000000"),
        consecutive_quarters_history=20,
    )
    result = evaluate_gate2_structural(inputs)
    assert not result.passed
    assert any("free float unknown" in reason for reason in result.reasons_failed)


def test_gate2_fails_when_market_cap_is_unknown():
    inputs = Gate2Inputs(
        free_float_pct=Decimal("0.30"),
        on_watch_list=False,
        trading_suspended=False,
        months_listed=60,
        market_cap_lkr=None,
        consecutive_quarters_history=20,
    )
    result = evaluate_gate2_structural(inputs)
    assert not result.passed
    assert any("market cap unknown" in reason for reason in result.reasons_failed)


def test_gate2_fails_on_watch_list():
    inputs = Gate2Inputs(
        free_float_pct=Decimal("0.30"),
        on_watch_list=True,
        trading_suspended=False,
        months_listed=60,
        market_cap_lkr=Decimal("5000000000"),
        consecutive_quarters_history=20,
    )
    result = evaluate_gate2_structural(inputs)
    assert not result.passed
    assert "on CSE Watch List" in result.reasons_failed


def test_gate3_beneish_veto():
    inputs = Gate3Inputs(
        qualified_audit_opinion=False,
        going_concern_emphasis=False,
        auditor_change_and_cfo_departure_same_12m=False,
        beneish_m_score=Decimal("-1.0"),  # above the -1.78 threshold
        related_party_revenue_or_receivables_pct=Decimal("0.05"),
    )
    result = evaluate_gate3_integrity(inputs)
    assert not result.passed
    assert any("Beneish" in reason for reason in result.reasons_failed)


def test_gate3_clean_company_passes():
    result = evaluate_gate3_integrity(_clean_gate3())
    assert result.passed


def test_classification_core_when_everything_passes():
    classification = classify_coverage_tier(
        data_completeness_pct=Decimal("0.95"),
        quarters_of_history=20,
        gate1=evaluate_gate1_liquidity(_clean_gate1()),
        gate2=evaluate_gate2_structural(_clean_gate2()),
        gate3=evaluate_gate3_integrity(_clean_gate3()),
    )
    assert classification.tier is CoverageTier.CORE


def test_classification_excluded_on_integrity_veto_even_if_liquid_and_structurally_sound():
    """§11.1: "If integrity is a scored input, a sufficiently attractive
    valuation will always outvote it." This test is the guarantee that a
    stock cannot buy its way out of the veto via good liquidity/structure."""
    bad_gate3 = evaluate_gate3_integrity(
        Gate3Inputs(
            qualified_audit_opinion=True,
            going_concern_emphasis=False,
            auditor_change_and_cfo_departure_same_12m=False,
            beneish_m_score=Decimal("-2.5"),
            related_party_revenue_or_receivables_pct=Decimal("0.05"),
        )
    )
    classification = classify_coverage_tier(
        data_completeness_pct=Decimal("0.95"),
        quarters_of_history=20,
        gate1=evaluate_gate1_liquidity(_clean_gate1()),
        gate2=evaluate_gate2_structural(_clean_gate2()),
        gate3=bad_gate3,
    )
    assert classification.tier is CoverageTier.EXCLUDED


def test_classification_watch_when_only_liquidity_fails():
    thin_gate1 = evaluate_gate1_liquidity(
        Gate1Inputs(
            median_daily_turnover_60d_lkr=Decimal("500000"),
            days_traded_last_60=58,
            amihud_illiquidity_percentile=Decimal("0.40"),
            position_value_lkr=Decimal("1000000"),
            adv_20d_lkr=Decimal("10000000"),
        )
    )
    classification = classify_coverage_tier(
        data_completeness_pct=Decimal("0.95"),
        quarters_of_history=20,
        gate1=thin_gate1,
        gate2=evaluate_gate2_structural(_clean_gate2()),
        gate3=evaluate_gate3_integrity(_clean_gate3()),
    )
    assert classification.tier is CoverageTier.WATCH


def test_classification_insufficient_overrides_everything():
    bad_gate3 = evaluate_gate3_integrity(
        Gate3Inputs(
            qualified_audit_opinion=True,
            going_concern_emphasis=False,
            auditor_change_and_cfo_departure_same_12m=False,
            beneish_m_score=Decimal("-2.5"),
            related_party_revenue_or_receivables_pct=Decimal("0.05"),
        )
    )
    classification = classify_coverage_tier(
        data_completeness_pct=Decimal("0.10"),
        quarters_of_history=2,
        gate1=None,
        gate2=evaluate_gate2_structural(_clean_gate2()),
        gate3=bad_gate3,
    )
    assert classification.tier is CoverageTier.INSUFFICIENT
