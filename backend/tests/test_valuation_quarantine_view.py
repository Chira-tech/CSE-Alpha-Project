"""app.domain.valuation_quarantine_view — persisting TASK 0.1's sanity
gate result as a `DataAlert`, idempotently, on the real live-view path."""
from __future__ import annotations

from decimal import Decimal

from app.domain.sanity import SanityCheckResult
from app.domain.valuation_quarantine_view import ALERT_TYPE, record_sanity_result
from app.models.data_quality import DataAlert

TICKER = "COMB.N0000"


def _blocked_result(reason: str = "roe_plausible") -> SanityCheckResult:
    return SanityCheckResult(
        fair_value=Decimal("93.06"), blocked=True, blocked_by=(reason,),
        block_reasons=(f"{reason} failed",), warned_by=(), warn_reasons=(), skipped=(),
    )


def _clean_result() -> SanityCheckResult:
    return SanityCheckResult(
        fair_value=Decimal("253.87"), blocked=False, blocked_by=(), block_reasons=(),
        warned_by=(), warn_reasons=(), skipped=(),
    )


class TestRecordSanityResult:
    def test_a_blocked_result_creates_one_open_alert(self, db_session):
        alert = record_sanity_result(db_session, TICKER, _blocked_result())

        assert alert is not None
        assert alert.ticker == TICKER
        assert alert.alert_type == ALERT_TYPE
        assert alert.resolved is False
        assert "roe_plausible" in alert.detail

    def test_a_second_blocked_call_does_not_duplicate_the_open_alert(self, db_session):
        """The real reason this must be idempotent: `valuation_summary_
        for` is a live, on-demand read hit every time a screen is viewed
        — inserting a new row on every call would flood the table for a
        ticker a user simply keeps looking at."""
        record_sanity_result(db_session, TICKER, _blocked_result())
        record_sanity_result(db_session, TICKER, _blocked_result())

        rows = db_session.query(DataAlert).filter(
            DataAlert.ticker == TICKER, DataAlert.alert_type == ALERT_TYPE
        ).all()
        assert len(rows) == 1

    def test_a_later_passing_result_auto_resolves_the_open_alert(self, db_session):
        """Self-healing: once the underlying data is fixed (a later
        confirmation, a corrected figure) and the gate now passes, the
        quarantine record should reflect that without waiting for a
        human to notice and close it by hand."""
        record_sanity_result(db_session, TICKER, _blocked_result())

        resolved = record_sanity_result(db_session, TICKER, _clean_result())

        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "system:sanity_recheck_passed"

    def test_a_clean_result_with_no_prior_alert_writes_nothing(self, db_session):
        result = record_sanity_result(db_session, TICKER, _clean_result())

        assert result is None
        assert db_session.query(DataAlert).filter(DataAlert.ticker == TICKER).count() == 0

    def test_a_new_block_after_resolution_opens_a_fresh_alert(self, db_session):
        """A resolved alert must not suppress a genuinely NEW failure —
        only an already-OPEN alert of the same type does."""
        record_sanity_result(db_session, TICKER, _blocked_result("roe_plausible"))
        record_sanity_result(db_session, TICKER, _clean_result())  # resolves it

        second = record_sanity_result(db_session, TICKER, _blocked_result("bvps_positive"))

        assert second is not None
        assert second.resolved is False
        rows = db_session.query(DataAlert).filter(
            DataAlert.ticker == TICKER, DataAlert.alert_type == ALERT_TYPE
        ).all()
        assert len(rows) == 2  # the resolved one, plus the fresh one
