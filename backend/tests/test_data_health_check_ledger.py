"""`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` E0 + §5 — the check
ledger's three-way split and the trading-day freshness metrics.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from freezegun import freeze_time

from app.api.routes.data_health import _check_ledger, _weekdays_in
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as ActionType
from app.models.data_quality import DataAlert
from app.models.float_data import FloatData
from app.models.job_run import JobRun
from app.models.prices import PriceDaily
from app.models.securities import Security

NOW = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)


class TestWeekdaysIn:
    def test_friday_to_tuesday_skips_the_weekend(self):
        got = _weekdays_in(dt.date(2026, 8, 28), dt.date(2026, 9, 1))
        assert got == [dt.date(2026, 8, 31), dt.date(2026, 9, 1)]

    def test_friday_to_sunday_is_empty(self):
        assert _weekdays_in(dt.date(2026, 8, 28), dt.date(2026, 8, 30)) == []

    def test_inverted_range_is_empty(self):
        assert _weekdays_in(dt.date(2026, 9, 1), dt.date(2026, 8, 1)) == []


class TestCheckLedgerThreeWaySplit:
    def _seed(self, db):
        # 3 lines. One has a full market-cap triple that reconciles, one
        # has a triple that does NOT, one has no published market cap.
        for t in ("AAA.N0000", "BBB.N0000", "CCC.N0000"):
            db.add(Security(ticker=t, name=t, issuer_code=t[:3], instrument_type="ordinary"))
        db.add(FloatData(ticker="AAA.N0000", as_of=dt.date(2026, 8, 1),
                         published_market_cap=Decimal("1000"), shares_issued=100))
        db.add(FloatData(ticker="BBB.N0000", as_of=dt.date(2026, 8, 1),
                         published_market_cap=Decimal("1000"), shares_issued=100))
        db.add(PriceDaily(ticker="AAA.N0000", date=dt.date(2026, 8, 28),
                          close=Decimal("10"), fetched_at=NOW))   # 10*100 = 1000 -> pass
        db.add(PriceDaily(ticker="BBB.N0000", date=dt.date(2026, 8, 28),
                          close=Decimal("20"), fetched_at=NOW))   # 20*100 = 2000 -> fail
        db.commit()

    def test_market_cap_identity_splits_pass_fail_not_evaluable(self, db_session):
        self._seed(db_session)
        rows = {r.check: r for r in _check_ledger(db_session)}
        mci = rows["market_cap_identity"]
        assert (mci.passed, mci.failed, mci.not_evaluable) == (1, 1, 1)
        assert mci.not_evaluable_reasons == {"no_published_market_cap": 1}
        assert mci.passed + mci.failed + mci.not_evaluable == mci.scope_total == 3
        assert mci.pass_pct_of_checkable == Decimal("50.0")   # 1 of 2, NOT 1 of 3
        assert mci.checkable_pct == Decimal("66.7")
        assert mci.blocking is True

    def test_price_discontinuity_is_not_evaluable_when_ca_feed_never_ran(self, db_session):
        self._seed(db_session)
        db_session.add(DataAlert(ticker="AAA.N0000", alert_type="price_discontinuity",
                                 detail="x", raised_at=NOW))
        db_session.commit()
        disc = {r.check: r for r in _check_ledger(db_session)}["price_discontinuity"]
        # No successful capture_corporate_actions JobRun -> the check is
        # reading an empty calendar, so the open alert is not-evaluable,
        # not a fail.
        assert disc.failed == 0
        assert disc.not_evaluable == disc.scope_total
        assert "corporate_action_table_unpopulated" in disc.not_evaluable_reasons

    def test_price_discontinuity_counts_fails_once_the_ca_feed_has_run(self, db_session):
        self._seed(db_session)
        db_session.add(DataAlert(ticker="AAA.N0000", alert_type="price_discontinuity",
                                 detail="x", raised_at=NOW))
        db_session.add(JobRun(job="capture_corporate_actions", trigger="scheduled",
                              status="success", finished_at=NOW, created_at=NOW))
        db_session.commit()
        disc = {r.check: r for r in _check_ledger(db_session)}["price_discontinuity"]
        assert disc.failed == 1

    def test_second_source_records_no_passes_only_fails_and_not_evaluable(self, db_session):
        self._seed(db_session)
        db_session.add(DataAlert(ticker="AAA.N0000", alert_type="second_source_mismatch",
                                 detail="x", raised_at=NOW))
        db_session.commit()
        ss = {r.check: r for r in _check_ledger(db_session)}["second_source_price"]
        assert ss.passed == 0 and ss.failed == 1
        assert ss.not_evaluable == 2
        assert "check_records_no_passes" in ss.not_evaluable_reasons

    def test_share_count_identity_is_not_evaluable_without_a_published_price(self, db_session):
        # _seed gives AAA/BBB a market cap but no published_price.
        self._seed(db_session)
        sci = {r.check: r for r in _check_ledger(db_session)}["share_count_identity"]
        assert sci.passed == 0 and sci.failed == 0
        assert sci.not_evaluable_reasons.get("no_published_price_captured") == 2
        assert sci.not_evaluable_reasons.get("no_published_market_cap") == 1

    def test_share_count_identity_passes_and_fails_at_half_a_percent(self, db_session):
        for t in ("PASS.N0000", "FAIL.N0000"):
            db_session.add(Security(ticker=t, name=t, issuer_code=t[:4], instrument_type="ordinary"))
        # implied = 1_000_000_000 / 10 = 100_000_000
        db_session.add(FloatData(ticker="PASS.N0000", as_of=dt.date(2026, 8, 19),
                                 published_market_cap=Decimal("1000000000"),
                                 published_price=Decimal("10"), shares_issued=100_000_000))
        # implied = 1_000_000_000 / 10 = 100_000_000 vs stored 98_000_000 → 2% off → fail
        db_session.add(FloatData(ticker="FAIL.N0000", as_of=dt.date(2026, 8, 19),
                                 published_market_cap=Decimal("1000000000"),
                                 published_price=Decimal("10"), shares_issued=98_000_000))
        db_session.commit()
        sci = {r.check: r for r in _check_ledger(db_session)}["share_count_identity"]
        assert sci.passed == 1 and sci.failed == 1
        assert sci.pass_pct_of_checkable == Decimal("50.0")

    def test_corporate_action_ratio_treats_pending_as_not_evaluable(self, db_session):
        self._seed(db_session)
        db_session.add_all([
            CorporateAction(ticker="AAA.N0000", type=ActionType.BONUS_ISSUE,
                            ex_date=dt.date(2026, 1, 1), confirmed_by="human"),
            CorporateAction(ticker="BBB.N0000", type=ActionType.STOCK_SPLIT,
                            ex_date=dt.date(2026, 2, 1), rejected_by="human"),
            CorporateAction(ticker="CCC.N0000", type=ActionType.RIGHTS_ISSUE,
                            ex_date=dt.date(2026, 3, 1)),  # pending
        ])
        db_session.commit()
        car = {r.check: r for r in _check_ledger(db_session)}["corporate_action_ratio"]
        assert (car.passed, car.failed, car.not_evaluable) == (1, 1, 1)
        assert car.pass_pct_of_checkable == Decimal("50.0")   # 1 confirmed / 2 reviewed
        assert "ca_feed_never_succeeded" in car.not_evaluable_reasons


class TestCohortSplits:
    def test_valuation_sanity_splits_block_rate_by_share_class(self, db_session):
        # 2 voting + 2 non-voting lines; one of each is blocked.
        for t in ("COMB.N0000", "HNB.N0000", "COMB.X0000", "HNB.X0000"):
            db_session.add(Security(ticker=t, name=t, issuer_code=t.split(".")[0],
                                    instrument_type="ordinary" if ".N" in t else "non_voting"))
        db_session.add(DataAlert(ticker="COMB.N0000", alert_type="valuation_sanity_block",
                                 detail="x", raised_at=NOW))
        db_session.add(DataAlert(ticker="COMB.X0000", alert_type="valuation_sanity_block",
                                 detail="x", raised_at=NOW))
        db_session.commit()
        vs = {r.check: r for r in _check_ledger(db_session)}["valuation_sanity"]
        assert vs.cohorts is not None
        assert vs.cohorts["voting (.N)"].failed == 1
        assert vs.cohorts["voting (.N)"].not_evaluable == 1
        assert vs.cohorts["non_voting (.X)"].failed == 1
        assert vs.cohorts["non_voting (.X)"].not_evaluable == 1

    def test_identity_checks_split_by_issuer_line_count(self, db_session):
        # SOLO has one line; PAIR has two.
        db_session.add(Security(ticker="SOLO.N0000", name="Solo", issuer_code="SOLO",
                                instrument_type="ordinary"))
        db_session.add(Security(ticker="PAIR.N0000", name="Pair N", issuer_code="PAIR",
                                instrument_type="ordinary"))
        db_session.add(Security(ticker="PAIR.X0000", name="Pair X", issuer_code="PAIR",
                                instrument_type="non_voting"))
        db_session.commit()
        mci = {r.check: r for r in _check_ledger(db_session)}["market_cap_identity"]
        assert mci.cohorts is not None
        assert mci.cohorts["single_line_issuer"].not_evaluable == 1   # SOLO
        assert mci.cohorts["multi_line_issuer"].not_evaluable == 2    # PAIR.N + PAIR.X


class TestFreshnessSplit:
    @freeze_time("2026-09-01")  # a Tuesday
    def test_missing_monday_is_flagged_weekend_is_not(self, db_session, client):
        db_session.add(Security(ticker="JKH.N0000", name="JKH"))
        db_session.add(PriceDaily(ticker="JKH.N0000", date=dt.date(2026, 8, 28),  # Friday
                                  close=Decimal("20"), fetched_at=NOW))
        db_session.add(JobRun(job="capture_prices", trigger="scheduled", status="success",
                              finished_at=dt.datetime(2026, 8, 28, 15, tzinfo=dt.timezone.utc),
                              created_at=NOW))
        db_session.commit()

        h = client.get("/data-health").json()
        # Fri -> Tue: Mon 31 Aug and Tue 1 Sep are weekday sessions; the
        # newest row is Friday, so both are missing.
        assert h["price_data_age_trading_days"] == 2
        assert "2026-08-31" in h["missing_trading_days"]
        assert "2026-08-29" not in h["missing_trading_days"]  # a Saturday
        assert h["price_capture_last_success_at"] is not None
        assert h["macro_feed_last_success_at"] is None
