"""§30 step 2's routing rule: app.domain.estimator_selection."""
from __future__ import annotations

from app.domain.estimator_selection import select_estimator


class TestSelectEstimator:
    def test_both_non_stationary_selects_johansen_vecm(self):
        choice, reason = select_estimator("non_stationary", "non_stationary")
        assert choice == "johansen_vecm"
        assert "I(1)" in reason

    def test_mixed_stationary_and_non_stationary_selects_ardl(self):
        choice, reason = select_estimator("stationary", "non_stationary")
        assert choice == "ardl_bounds_test"
        choice2, _ = select_estimator("non_stationary", "stationary")
        assert choice2 == "ardl_bounds_test"

    def test_both_stationary_selects_ardl_not_a_missing_case(self):
        choice, reason = select_estimator("stationary", "stationary")
        assert choice == "ardl_bounds_test"
        assert "bounds test" in reason

    def test_either_series_none_is_insufficient_data(self):
        choice, reason = select_estimator(None, "non_stationary")
        assert choice == "insufficient_data"
        assert "dependent series" in reason
        choice2, reason2 = select_estimator("non_stationary", None)
        assert choice2 == "insufficient_data"
        assert "independent series" in reason2

    def test_either_series_insufficient_data_propagates(self):
        choice, _ = select_estimator("insufficient_data", "non_stationary")
        assert choice == "insufficient_data"

    def test_either_series_mixed_evidence_refuses_rather_than_guesses(self):
        choice, reason = select_estimator("mixed_evidence", "non_stationary")
        assert choice == "insufficient_data"
        assert "ambiguous" in reason
        choice2, _ = select_estimator("stationary", "mixed_evidence")
        assert choice2 == "insufficient_data"
