"""
Golden regression set — `docs/CSE_Universe_Integrity_Rollout.md` Part 6.

Real securities pinned as permanent known-answer tests so the AAF class of
bug (a company bound to the wrong listed line, then published as a
maximum-conviction verdict) can never come back silently. Most cases
assert over functions that ALREADY exist and are ALREADY correct — the
value is that the assertion is now pinned; a regression turns red here
instead of shipping.

Case 1 (AAF during the 2026 rights issue) is the highest-value test in
this file: a real, verified, known-wrong-answer scenario. Never delete it.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain import universe_integrity as ui
from app.domain.corporate_actions import (
    ActionKind,
    CorporateActionEvent,
    build_adjustment_factor_series,
    compute_terp,
)
from app.domain.instrument_type import (
    COMMON_EQUITY,
    InstrumentType,
    classify,
    is_common_equity,
    is_primary_line,
    issuer_code,
)
from app.domain.valuation_router import route_valuation


# --------------------------------------------------------------------------
# Case 1 — AAF.N0000 during the 2026 rights issue
# --------------------------------------------------------------------------
class TestCase1_AAFRightsIssue:
    def test_the_ordinary_and_rights_lines_classify_distinctly(self):
        assert classify("AAF.N0000") is InstrumentType.ORDINARY
        assert classify("AAF.R0000") is InstrumentType.RIGHTS
        assert issuer_code("AAF.N0000") == issuer_code("AAF.R0000") == "AAF"

    def test_only_the_ordinary_line_is_investable_equity(self):
        assert is_common_equity("AAF.N0000") is True
        assert is_primary_line("AAF.N0000") is True
        assert is_common_equity("AAF.R0000") is False
        assert is_primary_line("AAF.R0000") is False

    def test_terp_and_rights_factor_match_the_spec(self):
        # 4-for-11 at 33.30, cum-price 49.10.
        terp = compute_terp(Decimal("11"), Decimal("4"), Decimal("49.10"), Decimal("33.30"))
        assert terp == pytest.approx(Decimal("44.89"), abs=Decimal("0.01"))
        factor = terp / Decimal("49.10")
        assert factor == pytest.approx(Decimal("0.9142"), abs=Decimal("0.0005"))

    def test_price_at_the_rights_level_fails_both_wrong_line_detectors(self):
        # The bound "price" is 11.30 — the nil-paid rights level.
        assert ui.check_rights_price_coherence("AAF.N0000", Decimal("11.30"), Decimal("33.30")) is not None
        f = ui.check_nil_paid_fingerprint("AAF.N0000", Decimal("11.30"), Decimal("33.30"), Decimal("44.89"))
        assert f is not None and f.check == ui.ALERT_WRONG_LINE_FINGERPRINT

    def test_market_cap_identity_catches_the_4x_error(self):
        # 11.30 x 124,195,533 = 1.40bn vs exchange-published 6.1bn.
        f = ui.check_market_cap_identity("AAF.N0000", Decimal("11.30"), 124_195_533, Decimal("6_100_000_000"))
        assert f is not None and f.check == "market_cap_mismatch"

    def test_the_real_ordinary_price_is_clean_on_every_detector(self):
        assert ui.check_rights_price_coherence("AAF.N0000", Decimal("49.10"), Decimal("33.30")) is None
        assert ui.check_nil_paid_fingerprint("AAF.N0000", Decimal("49.10"), Decimal("33.30"), Decimal("44.89")) is None


# --------------------------------------------------------------------------
# Cases 2–3 — non-voting and preference lines
# --------------------------------------------------------------------------
class TestCase2And3_ShareClasses:
    def test_non_voting_is_investable_but_not_the_primary_line(self):
        assert classify("COMB.X0000") is InstrumentType.NON_VOTING
        assert is_common_equity("COMB.X0000") is True   # valued, but as its own line
        assert is_primary_line("COMB.X0000") is False   # never the row a company view leads with

    def test_preference_is_never_the_issuers_equity(self):
        assert classify("LOLC.P0000") is InstrumentType.PREFERENCE
        assert InstrumentType.PREFERENCE not in COMMON_EQUITY
        assert is_common_equity("LOLC.P0000") is False

    def test_debentures_units_warrants_are_never_equity(self):
        assert is_common_equity("BOC.D0000") is False
        assert is_common_equity("CALC.U0000") is False
        assert is_common_equity("XXXX.W0000") is False


# --------------------------------------------------------------------------
# Cases 4–5 — bonus and consolidation adjustment
# --------------------------------------------------------------------------
class TestCase4And5_AdjustmentFactors:
    _DATES = [dt.date(2024, 1, 1), dt.date(2024, 6, 1), dt.date(2024, 12, 1)]

    def test_bonus_issue_shrinks_pre_ex_prices(self):
        # 1-for-1 bonus ex 2024-06-01: pre-ex prices multiplied by 1/2.
        events = [
            CorporateActionEvent(
                ex_date=dt.date(2024, 6, 1),
                kind=ActionKind.BONUS_ISSUE,
                new_shares_per_held_share=Decimal("1"),
            )
        ]
        factors = build_adjustment_factor_series(self._DATES, events)
        assert factors[dt.date(2024, 1, 1)] == Decimal("0.5")   # before ex — adjusted
        assert factors[dt.date(2024, 12, 1)] == Decimal("1")    # after ex — untouched

    def test_consolidation_grows_pre_ex_prices(self):
        # 5-to-1 consolidation ex 2024-06-01: pre-ex prices multiplied by 5.
        events = [
            CorporateActionEvent(
                ex_date=dt.date(2024, 6, 1),
                kind=ActionKind.CONSOLIDATION,
                old_shares_per_new_share=Decimal("5"),
            )
        ]
        factors = build_adjustment_factor_series(self._DATES, events)
        assert factors[dt.date(2024, 1, 1)] == Decimal("5")
        assert factors[dt.date(2024, 12, 1)] == Decimal("1")


# --------------------------------------------------------------------------
# Case 8 — model family routes by archetype, no industrial DCF on a lender
# --------------------------------------------------------------------------
class TestCase8_SectorModelRouting:
    def test_a_bank_is_a_financial_firm_with_firm_side_dcf_suppressed(self):
        d = route_valuation("bank")
        assert d.is_financial_firm is True
        firm_side = {"FCFF DCF", "EV/EBIT", "EV/EBITDA", "Sum-of-the-parts"}
        assert firm_side.isdisjoint(d.primary_models)

    def test_a_finance_company_is_also_a_financial_firm(self):
        assert route_valuation("non_bank_finance").is_financial_firm is True

    def test_a_manufacturer_is_not_a_financial_firm(self):
        d = route_valuation("manufacturing")
        assert d.is_financial_firm is False

    def test_no_archetype_refuses_to_route_rather_than_guessing(self):
        d = route_valuation(None)
        assert d.primary_models == ()
        assert "archetype" in d.note.lower()

    def test_universe_integrity_flags_the_unrouted_case(self):
        assert ui.check_sector_model_routed("X.N0000", None, None) is not None
        assert ui.check_sector_model_routed("COMB.N0000", "bank", "bank") is None


# --------------------------------------------------------------------------
# Cases 9–10 — fiscal-period alignment and currency
#
# These pin the SCHEMA support that makes the right behaviour possible;
# the deeper TTM-stitching and single-conversion behaviour are covered by
# `test_ttm.py` / the valuation suite. Named here rather than silently
# omitted (spec: disclosed, not hidden).
# --------------------------------------------------------------------------
class TestCase9And10_PeriodAndCurrency:
    def test_security_carries_a_fiscal_year_end_so_non_march_reporters_are_representable(self):
        from app.models.securities import Security

        s = Security(ticker="XYZ.N0000", name="Dec year-end Co", fiscal_year_end="12-31")
        assert s.fiscal_year_end == "12-31"

    def test_fundamentals_carry_a_currency_so_a_usd_reporter_is_representable(self):
        from app.models.fundamentals import Fundamental

        f = Fundamental(
            ticker="XYZ.N0000", period_end=dt.date(2025, 12, 31), period_type="annual",
            first_available_date=dt.date(2026, 3, 1), version=1, statement_line="revenue",
            value=Decimal("1"), currency="USD",
        )
        assert f.currency == "USD"


# --------------------------------------------------------------------------
# Case 11 — HDFC.N0000, FY trailing net loss on a declining earnings trend
#
# The second confirmed real case (2026-08-31): a "Strong Accumulate" at
# composite 65.9/100 published on a company with a FY2025 net loss and a
# multi-year declining earnings trend. The verdict must be capped.
# --------------------------------------------------------------------------
class TestCase11_NegativeEarningsTrendVerdictCap:
    def test_check8_fires_on_a_trailing_loss_and_declining_trend(self):
        f = ui.check_profitability_trend_consistency(
            "HDFC.N0000", Decimal("-93000000"), True, trend_periods=5
        )
        assert f is not None
        assert f.severity == "soft"
        assert f.check == ui.ALERT_NEGATIVE_EARNINGS_TREND
        assert ui.ALERT_NEGATIVE_EARNINGS_TREND in ui.SOFT_ALERT_TYPES  # → PROVISIONAL, not QUARANTINED

    def test_security_status_caps_the_verdict_at_hold(self, db_session):
        from app.domain.security_status_view import SecurityStatus, security_status_for
        from app.models.enums import ProvenanceTier
        from app.models.fundamentals import Fundamental
        from app.models.prices import PriceDaily
        from app.models.securities import Security

        as_of = dt.date(2026, 8, 31)
        db_session.add(Security(ticker="HDFC.N0000", name="HDFC Bank of Sri Lanka",
                                issuer_code="HDFC", instrument_type="ordinary"))
        db_session.add(PriceDaily(ticker="HDFC.N0000", date=as_of - dt.timedelta(days=1),
                                  close=Decimal("40"), source="cse.lk",
                                  fetched_at=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc)))
        for year, ni in ((2021, "900000000"), (2022, "500000000"), (2023, "120000000"),
                         (2024, "-15000000"), (2025, "-93000000")):
            db_session.add(Fundamental(
                ticker="HDFC.N0000", period_end=dt.date(year, 12, 31), period_type="annual",
                first_available_date=dt.date(year + 1, 3, 1), version=1,
                statement_line="net_income", value=Decimal(ni),
                provenance_tier=ProvenanceTier.REPORTED,
            ))
        db_session.commit()

        v = security_status_for(db_session, "HDFC.N0000", as_of=as_of)
        assert v.status is SecurityStatus.PROVISIONAL
        assert v.verdict_cap == "hold"
        assert v.blockers == ()  # not quarantined — the valuation may still be shown


# --------------------------------------------------------------------------
# Case 6 — a suspended security
#
# Spec Part 6 case 6: a suspended (or delisted) line is QUARANTINED and
# drops out of the ranking entirely — the exchange has halted trading, so
# there is no live price to rank on. `securities.trading_status` carries
# the state; `scripts.backfill_trading_status` derives it.
# --------------------------------------------------------------------------
class TestCase6_SuspendedSecurityIsQuarantined:
    def test_suspended_status_is_quarantined_and_excluded_from_ranking(self, db_session):
        from app.domain.security_status_view import SecurityStatus, security_status_for
        from app.jobs.reconciliation import is_quarantined
        from app.models.prices import PriceDaily
        from app.models.securities import Security

        as_of = dt.date(2026, 8, 31)
        db_session.add(Security(ticker="SUSP.N0000", name="Suspended Co",
                                issuer_code="SUSP", instrument_type="ordinary",
                                trading_status="suspended"))
        db_session.add(PriceDaily(ticker="SUSP.N0000", date=as_of - dt.timedelta(days=200),
                                  close=Decimal("8.00"), source="cse.lk",
                                  fetched_at=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc)))
        db_session.commit()

        v = security_status_for(db_session, "SUSP.N0000", as_of=as_of)
        assert v.status is SecurityStatus.QUARANTINED
        assert any("suspended" in b for b in v.blockers)
        # is_quarantined is the gate both ranking views call to drop a name.
        assert is_quarantined(db_session, "SUSP.N0000") is True

    def test_an_active_line_is_not_quarantined_by_status(self, db_session):
        from app.jobs.reconciliation import is_quarantined
        from app.models.securities import Security

        db_session.add(Security(ticker="LIVE.N0000", name="Trading Co",
                                issuer_code="LIVE", instrument_type="ordinary",
                                trading_status="active"))
        db_session.commit()
        assert is_quarantined(db_session, "LIVE.N0000") is False


# --------------------------------------------------------------------------
# Case 7 — an illiquid name whose last trade is weeks old
#
# Out of numeric order because it needs the same DB fixture as case 11.
# Spec Part 6 case 7: a name that has not traded in over a month is
# PROVISIONAL (not quarantined) and the staleness is surfaced as a named
# soft flag rather than the stale price being served as if it were live.
# --------------------------------------------------------------------------
class TestCase7_IlliquidStalePriceIsProvisional:
    def test_a_month_old_last_trade_makes_the_name_provisional(self, db_session):
        from app.domain.security_status_view import SecurityStatus, security_status_for
        from app.models.prices import PriceDaily
        from app.models.securities import Security

        as_of = dt.date(2026, 8, 31)
        db_session.add(Security(ticker="THIN.N0000", name="Thinly Traded PLC",
                                issuer_code="THIN", instrument_type="ordinary"))
        db_session.add(PriceDaily(ticker="THIN.N0000", date=as_of - dt.timedelta(days=35),
                                  close=Decimal("12.50"), source="cse.lk",
                                  fetched_at=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc)))
        db_session.commit()

        v = security_status_for(db_session, "THIN.N0000", as_of=as_of)
        assert v.status is SecurityStatus.PROVISIONAL
        assert v.blockers == ()  # not quarantined
        assert any("stale" in f.lower() and "35 days" in f for f in v.soft_flags)
        assert v.verdict_cap is None  # staleness alone does not cap at Hold
