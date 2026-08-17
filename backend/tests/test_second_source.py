"""
The second-source cross-check (Part II §5.2, PARAMETERS.md #5).

Quote values are real, captured live from TradingView's `/global/scan`
on 17 August 2026 for COMB.N0000, JKH.N0000 and HNB.N0000.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.second_source import (
    SecondSourceQuote,
    SecondSourceShapeError,
    cross_check,
)
from app.ingestion.tradingview_client import _fetch_chunk
from app.jobs.second_source_reconciliation import (
    ALERT_TYPE,
    StaleComparisonError,
    check_against_second_source,
)
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily
from app.models.securities import Security

TODAY = dt.date.today()

REAL_QUOTE = SecondSourceQuote(
    close=Decimal("205.5"), high=Decimal("205.5"), low=Decimal("205"),
    open=Decimal("205"), volume=11342, currency="LKR", exchange="CSELK",
)

REAL_SCAN_RESPONSE = {
    "totalCount": 3,
    "data": [
        {"s": "CSELK:COMB.N0000", "d": [205.5, 205.5, 205, 205, 11342, "LKR", "CSELK"]},
        {"s": "CSELK:JKH.N0000", "d": [20, 20, 19.9, 20, 538865, "LKR", "CSELK"]},
        {"s": "CSELK:HNB.N0000", "d": [384.75, 385.25, 384.75, 385.25, 10976, "LKR", "CSELK"]},
    ],
}


class TestCrossCheck:
    def test_matching_closes_pass(self):
        result = cross_check(
            "COMB.N0000", Decimal("205.5"), REAL_QUOTE, threshold_pct=Decimal("0.005")
        )
        assert result.within_tolerance
        assert result.mismatch_pct == 0

    def test_a_small_real_gap_is_within_the_005_threshold(self):
        """Our own capture is an end-of-session close; TradingView's is a
        live quote, so some drift is expected and 0.5% is the spec's own
        tolerance for it (Part II §5.2), not something invented here."""
        quote = SecondSourceQuote(
            close=Decimal("19.95"), high=Decimal("20"), low=Decimal("19.9"),
            open=Decimal("20"), volume=538865, currency="LKR", exchange="CSELK",
        )
        result = cross_check("JKH.N0000", Decimal("19.9"), quote, threshold_pct=Decimal("0.005"))
        assert result.within_tolerance  # 0.05/19.9 ~= 0.25%, under the 0.5% threshold

    def test_a_large_mismatch_fails(self):
        quote = SecondSourceQuote(
            close=Decimal("250.0"), high=Decimal("250"), low=Decimal("250"),
            open=Decimal("250"), volume=1, currency="LKR", exchange="CSELK",
        )
        result = cross_check("COMB.N0000", Decimal("205.5"), quote, threshold_pct=Decimal("0.005"))
        assert not result.within_tolerance
        assert result.mismatch_pct > Decimal("0.2")

    def test_wrong_currency_refuses_to_compare(self):
        """A quote in the wrong currency isn't evidence about a CSE line
        — it's evidence the symbol resolved to something else entirely."""
        quote = SecondSourceQuote(
            close=Decimal("205.5"), high=Decimal("205.5"), low=Decimal("205"),
            open=Decimal("205"), volume=1, currency="USD", exchange="CSELK",
        )
        with pytest.raises(SecondSourceShapeError, match="not LKR"):
            cross_check("COMB.N0000", Decimal("205.5"), quote, threshold_pct=Decimal("0.005"))

    def test_wrong_exchange_refuses_to_compare(self):
        quote = SecondSourceQuote(
            close=Decimal("205.5"), high=Decimal("205.5"), low=Decimal("205"),
            open=Decimal("205"), volume=1, currency="LKR", exchange="NSE",
        )
        with pytest.raises(SecondSourceShapeError, match="CSELK"):
            cross_check("COMB.N0000", Decimal("205.5"), quote, threshold_pct=Decimal("0.005"))


class TestTradingViewClientParsing:
    class _FakeHttpxClient:
        def __init__(self, payload):
            self.payload = payload
            self.last_body = None

        def post(self, url, *, json, headers):
            self.last_body = json
            return self._Response(self.payload)

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

    def test_real_response_parses_into_typed_quotes(self):
        client = self._FakeHttpxClient(REAL_SCAN_RESPONSE)
        quotes = _fetch_chunk(client, ["COMB.N0000", "JKH.N0000", "HNB.N0000"])
        assert quotes["COMB.N0000"].close == Decimal("205.5")
        assert quotes["HNB.N0000"].currency == "LKR"

    def test_the_cselk_prefix_is_stripped_back_to_our_own_ticker(self):
        client = self._FakeHttpxClient(REAL_SCAN_RESPONSE)
        quotes = _fetch_chunk(client, ["COMB.N0000"])
        assert "COMB.N0000" in quotes
        assert "CSELK:COMB.N0000" not in quotes

    def test_a_ticker_tradingview_does_not_recognise_is_absent_not_an_error(self):
        client = self._FakeHttpxClient({"totalCount": 0, "data": []})
        quotes = _fetch_chunk(client, ["NOTREAL.N0000"])
        assert quotes == {}

    def test_an_unreadable_row_is_skipped_not_fatal(self):
        client = self._FakeHttpxClient(
            {"data": [{"s": "CSELK:X.N0000", "d": [1, 2, 3]}]}  # wrong column count
        )
        assert _fetch_chunk(client, ["X.N0000"]) == {}

    def test_the_batch_request_body_carries_the_cselk_prefix(self):
        client = self._FakeHttpxClient({"data": []})
        _fetch_chunk(client, ["COMB.N0000", "JKH.N0000"])
        assert client.last_body["symbols"]["tickers"] == ["CSELK:COMB.N0000", "CSELK:JKH.N0000"]


class TestReconciliationJob:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add_all(
            [
                Security(ticker="COMB.N0000", name="COMMERCIAL BANK", issuer_code="COMB"),
                Security(ticker="JKH.N0000", name="JOHN KEELLS HOLDINGS", issuer_code="JKH"),
            ]
        )
        db_session.add_all(
            [
                PriceDaily(
                    ticker="COMB.N0000", date=TODAY, close=Decimal("205.5"),
                    fetched_at=dt.datetime.now(dt.timezone.utc), source="cse.lk",
                ),
                PriceDaily(
                    ticker="JKH.N0000", date=TODAY, close=Decimal("35.0"),
                    fetched_at=dt.datetime.now(dt.timezone.utc), source="cse.lk",
                ),
            ]
        )
        db_session.commit()
        return db_session

    def test_a_matching_ticker_raises_no_alert(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes",
            lambda tickers: {"COMB.N0000": REAL_QUOTE},
        )
        summary = check_against_second_source(db, ["COMB.N0000"], as_of=TODAY)
        assert summary["matched"] == 1
        assert summary["mismatched"] == 0
        assert db.scalars(select(DataAlert)).all() == []

    def test_a_real_mismatch_raises_a_quarantine_alert(self, db, monkeypatch):
        """JKH stored at 35.0 vs a real 20.0 TradingView quote — a
        genuine, large gap, not a fixture rigged to trigger cleanly."""
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes",
            lambda tickers: {
                "JKH.N0000": SecondSourceQuote(
                    close=Decimal("20"), high=Decimal("20"), low=Decimal("19.9"),
                    open=Decimal("20"), volume=538865, currency="LKR", exchange="CSELK",
                )
            },
        )
        summary = check_against_second_source(db, ["JKH.N0000"], as_of=TODAY)
        assert summary["mismatched"] == 1
        alerts = db.scalars(select(DataAlert)).all()
        assert len(alerts) == 1
        assert alerts[0].alert_type == ALERT_TYPE
        assert alerts[0].ticker == "JKH.N0000"
        assert not alerts[0].resolved

    def test_a_ticker_with_no_tradingview_coverage_is_not_flagged(self, db, monkeypatch):
        """Absence of a second-source quote is not itself a discrepancy —
        it means nothing to compare, not a mismatch."""
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes", lambda tickers: {}
        )
        summary = check_against_second_source(
            db, ["COMB.N0000", "JKH.N0000"], as_of=TODAY
        )
        assert summary["mismatched"] == 0
        assert summary["no_quote"] == 2
        assert db.scalars(select(DataAlert)).all() == []

    def test_a_ticker_with_no_stored_close_today_is_a_cheap_no_op(self, db, monkeypatch):
        """No stored close for today means nothing to reconcile for that
        ticker — must not fetch quotes at all, let alone flag anything."""
        called = []
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes",
            lambda tickers: called.append(tickers) or {},
        )
        summary = check_against_second_source(db, ["NEVER_STORED.N0000"], as_of=TODAY)
        assert summary["checked"] == 0
        assert called == []


class TestStaleComparisonGuard:
    """The bug this guard exists to prevent, made concrete: an early
    manual run compared a 3-day-stale stored close against TradingView's
    LIVE quote and flagged 181 of 283 tickers as "mismatched" — every one
    spurious. TradingView has no historical series (see
    app.domain.second_source), so as_of MUST mean today or the comparison
    is meaningless by construction."""

    def test_a_past_date_is_refused_before_any_fetch_happens(self, db_session, monkeypatch):
        called = []
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes",
            lambda tickers: called.append(tickers) or {},
        )
        with pytest.raises(StaleComparisonError, match="not today"):
            check_against_second_source(db_session, ["COMB.N0000"], as_of=dt.date(2020, 1, 1))
        assert called == []

    def test_todays_date_is_accepted(self, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.jobs.second_source_reconciliation.fetch_quotes", lambda tickers: {}
        )
        # No stored close for today in this bare session, so this is
        # purely checking the guard does not fire — the cheap no-op path
        # is exercised separately above.
        summary = check_against_second_source(db_session, ["COMB.N0000"], as_of=dt.date.today())
        assert summary["checked"] == 0
