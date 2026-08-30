"""
`app.domain.universe_integrity` — the pure data-integrity detectors from
`docs/CSE_Universe_Integrity_Rollout.md`. Pure predicates, no DB, so these
are plain input→finding checks. The AAF worked examples from the spec are
used as fixtures so the detectors are verified against a real, known-wrong
case.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import universe_integrity as ui


class TestInstrumentType:
    def test_unknown_type_is_a_hard_finding(self):
        f = ui.check_instrument_type_known("SIC.N0000", None)
        assert f is not None and f.severity == "hard"

    def test_known_type_is_clean(self):
        assert ui.check_instrument_type_known("COMB.N0000", "ordinary") is None


class TestRightsLineExpired:
    def test_rights_line_stale_past_the_window_is_flagged(self):
        f = ui.check_rights_line_expired(
            "AAF.R0000", "rights", dt.date(2026, 8, 1), dt.date(2026, 8, 30)
        )
        assert f is not None and f.check == ui.ALERT_RIGHTS_LINE_EXPIRED and f.severity == "soft"

    def test_recently_traded_rights_line_is_left_alone(self):
        assert (
            ui.check_rights_line_expired(
                "AAF.R0000", "rights", dt.date(2026, 8, 25), dt.date(2026, 8, 30)
            )
            is None
        )

    def test_non_rights_line_is_never_flagged(self):
        assert (
            ui.check_rights_line_expired(
                "AAF.N0000", "ordinary", dt.date(2020, 1, 1), dt.date(2026, 8, 30)
            )
            is None
        )


class TestMarketCapIdentity:
    def test_aaf_worked_example_fails(self):
        # spec §Check 1: 11.30 x 124,195,533 = 1.40bn vs published 6.1bn
        f = ui.check_market_cap_identity(
            "AAF.N0000", Decimal("11.30"), 124_195_533, Decimal("6_100_000_000")
        )
        assert f is not None and f.check == "market_cap_mismatch" and f.severity == "hard"

    def test_reconciling_within_2pct_is_clean(self):
        f = ui.check_market_cap_identity(
            "COMB.N0000", Decimal("100"), 1_000_000, Decimal("100_500_000")
        )
        assert f is None

    def test_missing_input_is_skipped_not_failed(self):
        assert ui.check_market_cap_identity("X.N0000", None, 1_000, Decimal("1")) is None
        assert ui.check_market_cap_identity("X.N0000", Decimal("1"), None, Decimal("1")) is None
        assert ui.check_market_cap_identity("X.N0000", Decimal("1"), 1_000, None) is None


class TestRightsPriceCoherence:
    def test_aaf_price_below_subscription_fails(self):
        # spec §Check 2: 11.30 < 33.30
        f = ui.check_rights_price_coherence("AAF.N0000", Decimal("11.30"), Decimal("33.30"))
        assert f is not None and f.check == ui.ALERT_RIGHTS_PRICE_INCOHERENT

    def test_price_above_subscription_is_clean(self):
        assert ui.check_rights_price_coherence("AAF.N0000", Decimal("49.10"), Decimal("33.30")) is None


class TestNilPaidFingerprint:
    def test_aaf_11_30_matches_the_terp_and_is_flagged(self):
        # spec §Check 3: 11.30 + 33.30 = 44.60 implied cum; confirmed TERP 44.89
        f = ui.check_nil_paid_fingerprint(
            "AAF.N0000", Decimal("11.30"), Decimal("33.30"), Decimal("44.89")
        )
        assert f is not None and f.check == ui.ALERT_WRONG_LINE_FINGERPRINT

    def test_the_real_ordinary_price_does_not_fingerprint(self):
        # 49.10 + 33.30 = 82.40, nowhere near TERP 44.89
        assert (
            ui.check_nil_paid_fingerprint(
                "AAF.N0000", Decimal("49.10"), Decimal("33.30"), Decimal("44.89")
            )
            is None
        )


class TestImpliedMultipleBand:
    def test_cheap_and_high_roe_fails(self):
        # spec §Check 4: P/B 0.32 with ROE 24.3%
        f = ui.check_implied_multiple_band(
            "AAF.N0000", Decimal("0.32"), Decimal("12"), Decimal("0.243"), Decimal("500")
        )
        assert f is not None and f.check == ui.ALERT_IMPLAUSIBLE_MULTIPLE

    def test_low_pe_on_a_profitable_company_fails(self):
        f = ui.check_implied_multiple_band(
            "X.N0000", Decimal("1.5"), Decimal("1.2"), Decimal("0.4"), Decimal("100")
        )
        assert f is not None

    def test_ordinary_multiples_are_clean(self):
        assert (
            ui.check_implied_multiple_band(
                "COMB.N0000", Decimal("1.4"), Decimal("8"), Decimal("0.17"), Decimal("1000")
            )
            is None
        )


class TestPriceDiscontinuity:
    def test_large_move_with_no_action_fails(self):
        f = ui.check_price_discontinuity("ABL.N0000", Decimal("9.18"), dt.date(2024, 7, 15), False)
        assert f is not None and f.check == ui.ALERT_PRICE_DISCONTINUITY

    def test_large_move_on_a_corporate_action_date_is_clean(self):
        assert (
            ui.check_price_discontinuity("X.N0000", Decimal("-0.5"), dt.date(2024, 1, 1), True) is None
        )

    def test_ordinary_move_is_clean(self):
        assert ui.check_price_discontinuity("X.N0000", Decimal("0.04"), dt.date(2024, 1, 1), False) is None


class TestReportOnlyChecks:
    def test_stale_price_flags_past_threshold(self):
        f = ui.check_price_staleness("X.N0000", 30)
        assert f is not None and f.severity == "soft" and f.check == "stale_source"

    def test_fresh_price_is_clean(self):
        assert ui.check_price_staleness("X.N0000", 3) is None

    def test_no_archetype_is_a_routing_gap(self):
        f = ui.check_sector_model_routed("X.N0000", None, None)
        assert f is not None and f.check == "sector_model_unrouted"

    def test_coe_needed_but_missing(self):
        f = ui.check_cost_of_equity_available("X.N0000", True, None)
        assert f is not None
        assert ui.check_cost_of_equity_available("X.N0000", True, Decimal("0.15")) is None
        assert ui.check_cost_of_equity_available("X.N0000", False, None) is None


def test_alert_type_sets_are_disjoint_and_cover_the_new_checks():
    assert ui.HARD_ALERT_TYPES.isdisjoint(ui.SOFT_ALERT_TYPES)
    for t in (
        ui.ALERT_RIGHTS_PRICE_INCOHERENT,
        ui.ALERT_WRONG_LINE_FINGERPRINT,
        ui.ALERT_IMPLAUSIBLE_MULTIPLE,
        ui.ALERT_PRICE_DISCONTINUITY,
    ):
        assert t in ui.HARD_ALERT_TYPES
    assert ui.ALERT_RIGHTS_LINE_EXPIRED in ui.SOFT_ALERT_TYPES
