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
