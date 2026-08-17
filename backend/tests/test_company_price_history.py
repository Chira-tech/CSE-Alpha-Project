"""
Per-company price history from `companyChartDataByStock`.

Bars below are real rows captured live from COMB.N0000 (stockId 208) on
17 August 2026. The 2026-08-14 figures — h=205.0, l=203.0, p=204.5,
q=190303 — were cross-checked against `companyInfoSummery`'s
independently-fetched hiTrade/lowTrade/closingPrice/tdyShareVolume for
the same ticker and matched exactly; that is what makes this endpoint
trustworthy rather than merely plausible.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.company_price_history import CompanyPriceHistoryError, parse_bars
from app.ingestion.company_price_history_loader import (
    SOURCE,
    backfill_company_price_history,
    fetch_stock_id_map,
    upsert_company_price_history,
)
from app.models.prices import PriceDaily
from app.models.securities import Security


def millis(date: str) -> int:
    d = dt.date.fromisoformat(date)
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)


REAL_PAYLOAD = {
    "chartData": [
        {"h": 202.75, "l": 200.0, "o": None, "s": 1, "q": 155248, "p": 201.0, "c": None, "pc": None, "t": millis("2026-08-11"), "n": None, "id": 208},
        {"h": 203.0, "l": 202.25, "o": None, "s": 2, "q": 27666, "p": 203.0, "c": None, "pc": None, "t": millis("2026-08-12"), "n": None, "id": 208},
        {"h": 204.5, "l": 202.5, "o": None, "s": 3, "q": 109570, "p": 203.0, "c": None, "pc": None, "t": millis("2026-08-13"), "n": None, "id": 208},
        {"h": 205.0, "l": 203.0, "o": None, "s": 4, "q": 190303, "p": 204.5, "c": None, "pc": None, "t": millis("2026-08-14"), "n": None, "id": 208},
    ]
}


class TestParsing:
    def test_real_bars_match_the_independently_verified_close(self):
        """204.5 is companyInfoSummery's closingPrice for COMB.N0000 on
        2026-08-14, fetched separately from this endpoint."""
        bars, warnings = parse_bars(REAL_PAYLOAD)
        by_date = {b.date: b for b in bars}
        bar = by_date[dt.date(2026, 8, 14)]
        assert bar.close == Decimal("204.5")
        assert bar.high == Decimal("205.0")
        assert bar.low == Decimal("203.0")
        assert bar.volume == 190303
        assert warnings == []

    def test_bars_are_sorted_by_date(self):
        shuffled = {"chartData": list(reversed(REAL_PAYLOAD["chartData"]))}
        bars, _ = parse_bars(shuffled)
        assert [b.date for b in bars] == sorted(b.date for b in bars)

    def test_missing_chartdata_key_raises(self):
        with pytest.raises(CompanyPriceHistoryError, match="chartData"):
            parse_bars({"nope": []})

    def test_non_object_payload_raises(self):
        with pytest.raises(CompanyPriceHistoryError):
            parse_bars([1, 2, 3])

    def test_duplicate_dates_raise(self):
        dupe = {"chartData": REAL_PAYLOAD["chartData"] + [REAL_PAYLOAD["chartData"][0]]}
        with pytest.raises(CompanyPriceHistoryError, match="duplicate dates"):
            parse_bars(dupe)

    def test_a_null_low_drops_only_that_field_not_the_whole_day(self):
        """Real data: JKH.N0000 on 2025-10-23 has l=null with h and p both
        present. Discarding the whole year over one missing field on one
        day would be a worse outcome than keeping a day with no low. A
        field the source itself sent as null is not a parse failure, so
        this is silent rather than a warning — `DailyBar.low is None` is
        how a caller sees it, exactly like every other missing figure in
        this system (Design Law 3: missing is displayed as missing)."""
        row = {
            "h": 21.7, "l": None, "o": None, "s": 1, "q": 6169523, "p": 21.3,
            "c": None, "pc": None, "t": millis("2025-10-23"), "n": None, "id": 297,
        }
        bars, _ = parse_bars({"chartData": [row]})
        assert len(bars) == 1
        assert bars[0].low is None
        assert bars[0].high == Decimal("21.7")
        assert bars[0].close == Decimal("21.3")

    def test_close_outside_the_days_own_range_drops_the_offending_field(self):
        """A close outside [low, high] is not physically possible for a
        genuine day-bar - never seen across a full year of COMB.N0000, but
        the module that found ASPI's silent 38% error rate does not get
        to trust a new endpoint blindly. The close (the figure a return
        series actually needs) is kept; the contradicted bound is not."""
        bad = {
            "chartData": [
                {"h": 200.0, "l": 195.0, "o": None, "s": 1, "q": 100, "p": 250.0,
                 "c": None, "pc": None, "t": millis("2026-08-14"), "n": None, "id": 208}
            ]
        }
        bars, warnings = parse_bars(bad)
        assert bars[0].close == Decimal("250.0")
        assert bars[0].high is None
        assert any("exceeds high" in w for w in warnings)

    def test_negative_volume_drops_the_bar(self):
        bad = {
            "chartData": [
                {"h": 200.0, "l": 195.0, "o": None, "s": 1, "q": -5, "p": 198.0,
                 "c": None, "pc": None, "t": millis("2026-08-14"), "n": None, "id": 208}
            ]
        }
        bars, warnings = parse_bars(bad)
        assert bars == []
        assert any("negative volume" in w for w in warnings)


class TestUpsert:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker="COMB.N0000", name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        return db_session

    def test_backfilled_rows_are_written(self, db):
        bars, _ = parse_bars(REAL_PAYLOAD)
        written = upsert_company_price_history(
            db, "COMB.N0000", bars, today=dt.date(2026, 8, 17)
        )
        assert written == 4
        row = db.get(PriceDaily, ("COMB.N0000", dt.date(2026, 8, 14)))
        assert row.close == Decimal("204.5")
        assert row.source == SOURCE
        assert row.open is None  # never fabricated

    def test_a_date_already_captured_live_is_never_overwritten(self, db):
        """The daily EOD job observed this session directly at the close
        (§6). A same-institution resample must not replace it, even with
        an identical-looking number."""
        db.add(
            PriceDaily(
                ticker="COMB.N0000",
                date=dt.date(2026, 8, 14),
                close=Decimal("999.99"),
                fetched_at=dt.datetime.now(dt.timezone.utc),
                source="cse.lk",
            )
        )
        db.commit()
        bars, _ = parse_bars(REAL_PAYLOAD)
        upsert_company_price_history(db, "COMB.N0000", bars, today=dt.date(2026, 8, 17))
        assert db.get(PriceDaily, ("COMB.N0000", dt.date(2026, 8, 14))).close == Decimal("999.99")

    def test_todays_bar_is_never_backfilled(self, db):
        """Before the 14:30 close today's bar is still forming, and this
        loader has no post-close signal to tell settled from in-progress
        the way the ASPI loader does. It defers to the EOD job entirely."""
        bars, _ = parse_bars(REAL_PAYLOAD)
        written = upsert_company_price_history(
            db, "COMB.N0000", bars, today=dt.date(2026, 8, 14)
        )
        assert written == 3
        assert db.get(PriceDaily, ("COMB.N0000", dt.date(2026, 8, 14))) is None

    def test_rerunning_is_idempotent(self, db):
        bars, _ = parse_bars(REAL_PAYLOAD)
        upsert_company_price_history(db, "COMB.N0000", bars, today=dt.date(2026, 8, 17))
        second = upsert_company_price_history(db, "COMB.N0000", bars, today=dt.date(2026, 8, 17))
        assert second == 0


class TestStockIdSpace:
    class _Client:
        def __init__(self, payload):
            self.payload = payload

        def get_json(self, path):
            assert path == "allSecurityCode"
            return self.payload

    def test_the_id_space_is_read_from_allSecurityCode_not_guessed(self):
        """This is a THIRD id space, distinct from cntSecurity's
        issuer-level securityId and chartData's index-only chartId.
        Conflating any of them sends the request to the wrong line."""
        mapping = fetch_stock_id_map(
            self._Client([{"id": 208, "symbol": "COMB.N0000", "name": "X", "active": 1}])
        )
        assert mapping == {"COMB.N0000": 208}

    def test_an_unusable_payload_raises(self):
        with pytest.raises(CompanyPriceHistoryError):
            fetch_stock_id_map(self._Client([]))


class TestBackfillSweep:
    class _FakeClient:
        def __init__(self, ids, bars_by_id, fail_ids=frozenset()):
            self.ids = ids
            self.bars_by_id = bars_by_id
            self.fail_ids = fail_ids

        def get_json(self, path):
            return [{"id": v, "symbol": k, "name": k, "active": 1} for k, v in self.ids.items()]

        def post_form(self, path, data):
            stock_id = data["stockId"]
            if stock_id in self.fail_ids:
                raise RuntimeError("simulated upstream failure")
            return {"chartData": self.bars_by_id.get(stock_id, [])}

    @pytest.fixture()
    def db(self, db_session):
        db_session.add_all(
            [
                Security(ticker="COMB.N0000", name="A", issuer_code="COMB"),
                Security(ticker="BAD.N0000", name="B", issuer_code="BAD"),
                Security(ticker="NOID.N0000", name="C", issuer_code="NOID"),
            ]
        )
        db_session.commit()
        return db_session

    def test_one_failing_ticker_does_not_abort_the_sweep(self, db):
        """~283 unofficial-upstream calls: a mid-sweep failure that
        discarded everything already fetched would make the command
        practically unusable."""
        client = self._FakeClient(
            ids={"COMB.N0000": 208, "BAD.N0000": 500},
            bars_by_id={208: REAL_PAYLOAD["chartData"]},
            fail_ids={500},
        )
        summary = backfill_company_price_history(
            client, db, ["COMB.N0000", "BAD.N0000", "NOID.N0000"]
        )
        assert summary["failed"] == 1
        assert summary["no_stock_id"] == 1
        assert summary["rows_written"] > 0
        assert db.get(PriceDaily, ("COMB.N0000", dt.date(2026, 8, 11))) is not None
