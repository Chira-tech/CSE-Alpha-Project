"""§38's Macro & sector fit formula — app.domain.macro_sector_fit."""
from __future__ import annotations

from decimal import Decimal

from app.domain.macro_sector_fit import combine_macro_sector_fit, sector_fit_from_sensitivity
from app.domain.sector_sensitivity import SectorSensitivityRow, SensitivityEstimate


def _estimate(name: str, direction: str, significant: bool) -> SensitivityEstimate:
    return SensitivityEstimate(
        shock_name=name, coefficient=Decimal("0.5") if direction == "positive" else Decimal("-0.5"),
        p_value=Decimal("0.01") if significant else Decimal("0.5"),
        r_squared=Decimal("0.2"), observation_count=30, significant=significant, direction_label=direction,
    )


class TestSectorFitFromSensitivity:
    def test_transition_regime_has_no_directional_lean(self):
        row = SectorSensitivityRow(sector="Banks", constituent_count=5, estimates=(_estimate("policy_rate", "positive", True),))
        score, favorable, total, reason = sector_fit_from_sensitivity(row, "transition")
        assert score is None and favorable == 0 and total == 0
        assert "no directional lean" in reason

    def test_none_row_is_a_named_reason_not_a_crash(self):
        score, favorable, total, reason = sector_fit_from_sensitivity(None, "risk_off")
        assert score is None
        assert "too few real constituents" in reason

    def test_no_significant_shocks_gives_none_not_a_fabricated_neutral(self):
        row = SectorSensitivityRow(sector="Banks", constituent_count=5, estimates=(_estimate("policy_rate", "positive", False),))
        score, favorable, total, reason = sector_fit_from_sensitivity(row, "risk_off")
        assert score is None
        assert total == 0

    def test_hand_computed_favorable_count_in_risk_off(self):
        """Risk-Off favors POSITIVE-direction significant shocks. 2 of 3
        significant estimates are positive -> 100 * 2/3."""
        row = SectorSensitivityRow(
            sector="Banks", constituent_count=5,
            estimates=(
                _estimate("policy_rate", "positive", True),
                _estimate("tbill_yield", "positive", True),
                _estimate("ccpi", "negative", True),
                _estimate("lkr_usd", "positive", False),  # not significant -> excluded from the denominator
            ),
        )
        score, favorable, total, reason = sector_fit_from_sensitivity(row, "risk_off")
        assert favorable == 2 and total == 3
        assert score == Decimal(100) * 2 / 3
        assert reason is None

    def test_hand_computed_favorable_count_in_risk_on_is_the_opposite_direction(self):
        """Risk-On favors NEGATIVE-direction significant shocks — same
        row as above, opposite regime, opposite favorable count."""
        row = SectorSensitivityRow(
            sector="Banks", constituent_count=5,
            estimates=(
                _estimate("policy_rate", "positive", True),
                _estimate("tbill_yield", "positive", True),
                _estimate("ccpi", "negative", True),
            ),
        )
        score, favorable, total, reason = sector_fit_from_sensitivity(row, "risk_on")
        assert favorable == 1 and total == 3
        assert score == Decimal(100) / 3


class TestCombineMacroSectorFit:
    def test_all_three_components_present_gives_the_hand_computed_mean(self):
        result = combine_macro_sector_fit(
            sensitivity_component=Decimal(60), favorable_count=3, total_significant_count=5,
            sensitivity_reason=None, project_register_component=Decimal(90), sector_momentum_component=Decimal(30),
        )
        assert result.score == (Decimal(60) + Decimal(90) + Decimal(30)) / 3

    def test_missing_components_renormalize_not_zero_fill(self):
        result = combine_macro_sector_fit(
            sensitivity_component=None, favorable_count=0, total_significant_count=0,
            sensitivity_reason="no directional lean", project_register_component=Decimal(80),
            sector_momentum_component=None,
        )
        assert result.score == Decimal(80)

    def test_nothing_real_gives_none_never_a_fabricated_zero(self):
        result = combine_macro_sector_fit(
            sensitivity_component=None, favorable_count=0, total_significant_count=0,
            sensitivity_reason="x", project_register_component=None, sector_momentum_component=None,
        )
        assert result.score is None
        assert result.reason is not None
