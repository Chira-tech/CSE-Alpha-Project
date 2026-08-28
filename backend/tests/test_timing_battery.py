"""§37's timing battery — app.domain.timing_battery. Pure weighted-sum
arithmetic, hand-checkable directly (unlike a regression)."""
from __future__ import annotations

from decimal import Decimal

from app.domain.timing_battery import (
    CONTRARIAN_FUNDAMENTAL_SCORE_FLOOR,
    CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT,
    CRASH_GUARD_REV_1M_WEIGHT,
    CRASH_GUARD_VOLUME_WEIGHT,
    MOMENTUM_FAMILY_KEYS,
    SIGNAL_WEIGHTS,
    build_contrarian_check,
    compute_timing_battery,
)


class TestComputeTimingBattery:
    def test_all_signals_present_gives_the_exact_hand_computed_weighted_mean(self):
        values = {
            "week52_high_proximity": Decimal(90),
            "residual_momentum": Decimal(80),
            "mom_12_2": Decimal(70),
            "mom_6_1": Decimal(60),
            "rev_1m": Decimal(50),
            "volume_confirmation": Decimal(40),
        }
        contrarian = build_contrarian_check(
            rev_1m_bottom_decile=False, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        result = compute_timing_battery(values, {}, crash_guard_active=False, contrarian=contrarian)
        # Hand computation: 20*90 + 20*80 + 20*70 + 15*60 + 15*50 + 10*40, / 100
        expected = (Decimal(20) * 90 + Decimal(20) * 80 + Decimal(20) * 70 + Decimal(15) * 60 + Decimal(15) * 50 + Decimal(10) * 40) / 100
        assert result.composite_score == expected
        assert all(s.included for s in result.signals)

    def test_a_missing_signal_renormalizes_rather_than_counts_as_zero(self):
        """Residual momentum missing (the common real case: not enough
        real weeks for a Carhart regression yet) — the remaining 80
        points of weight must be renormalized to 100%, not silently
        treated as a 0 dragging the composite down."""
        values = {
            "week52_high_proximity": Decimal(100),
            "residual_momentum": None,
            "mom_12_2": Decimal(100),
            "mom_6_1": Decimal(100),
            "rev_1m": Decimal(100),
            "volume_confirmation": Decimal(100),
        }
        contrarian = build_contrarian_check(
            rev_1m_bottom_decile=False, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        result = compute_timing_battery(values, {"residual_momentum": "not enough real weeks"}, crash_guard_active=False, contrarian=contrarian)
        assert result.composite_score == Decimal(100)  # every included signal is 100 -> renormalized mean is still 100
        rm = next(s for s in result.signals if s.key == "residual_momentum")
        assert rm.included is False
        assert rm.reason == "not enough real weeks"

    def test_no_signals_at_all_gives_none_never_a_fabricated_zero(self):
        values = {k: None for k in SIGNAL_WEIGHTS}
        contrarian = build_contrarian_check(
            rev_1m_bottom_decile=None, business_quality_ge_70=None,
            no_integrity_red_flag=None, no_active_sector_macro_shock=None,
        )
        result = compute_timing_battery(values, {}, crash_guard_active=False, contrarian=contrarian)
        assert result.composite_score is None

    def test_crash_guard_reweighting_sums_to_100_and_scales_the_momentum_family_proportionally(self):
        assert CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT + CRASH_GUARD_REV_1M_WEIGHT + CRASH_GUARD_VOLUME_WEIGHT == 100

        values = {k: Decimal(50) for k in SIGNAL_WEIGHTS}
        contrarian = build_contrarian_check(
            rev_1m_bottom_decile=True, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        result = compute_timing_battery(values, {}, crash_guard_active=True, contrarian=contrarian)
        momentum_weights_sum = sum(s.weight_pct for s in result.signals if s.key in MOMENTUM_FAMILY_KEYS)
        assert momentum_weights_sum == CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT
        rev_1m_weight = next(s.weight_pct for s in result.signals if s.key == "rev_1m")
        assert rev_1m_weight == CRASH_GUARD_REV_1M_WEIGHT
        # Hand-checkable: within the momentum family, relative proportions
        # (20/20/20/15 of 75) are preserved under the new 25-point total.
        w52 = next(s.weight_pct for s in result.signals if s.key == "week52_high_proximity")
        mom61 = next(s.weight_pct for s in result.signals if s.key == "mom_6_1")
        assert w52 == Decimal(20) * CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT / 75
        assert mom61 == Decimal(15) * CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT / 75
        assert sum(s.weight_pct for s in result.signals) == 100

    def test_crash_guard_inactive_leaves_the_spec_weights_untouched(self):
        values = {k: Decimal(50) for k in SIGNAL_WEIGHTS}
        contrarian = build_contrarian_check(
            rev_1m_bottom_decile=False, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        result = compute_timing_battery(values, {}, crash_guard_active=False, contrarian=contrarian)
        for s in result.signals:
            assert s.weight_pct == SIGNAL_WEIGHTS[s.key]


class TestBuildContrarianCheck:
    def test_condition_4_is_always_unknown(self):
        check = build_contrarian_check(
            rev_1m_bottom_decile=True, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        assert check.no_adverse_disclosure_60d == "unknown"

    def test_all_conditions_met_is_false_whenever_any_condition_is_unknown_or_false_or_none(self):
        # Even with every OTHER condition True, condition 4 being
        # structurally "unknown" must still make the overall gate False.
        check = build_contrarian_check(
            rev_1m_bottom_decile=True, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        assert check.all_conditions_met is False

        check_with_none = build_contrarian_check(
            rev_1m_bottom_decile=None, business_quality_ge_70=True,
            no_integrity_red_flag=True, no_active_sector_macro_shock=True,
        )
        assert check_with_none.all_conditions_met is False

    def test_fundamental_score_floor_constant_matches_composite_score_pass_bar(self):
        assert CONTRARIAN_FUNDAMENTAL_SCORE_FLOOR == Decimal(70)
