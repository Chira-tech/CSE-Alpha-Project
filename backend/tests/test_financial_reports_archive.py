"""
Per-company historical financial-statement archive from `/api/financials`.

The archive shape below is a trimmed real capture from COMB.N0000 on
17 August 2026 — an original and an "Amended" annual report for the same
FY2022 period, exactly as the exchange actually returned it.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest

from app.ingestion.financial_reports_archive_loader import (
    _already_ingested_by_source,
    _next_version,
    _resolve_download_url,
    ingest_archived_report,
    ingest_report_archive_for_ticker,
    resolve_first_available_date,
)
from app.ingestion.schemas import CompanyArchiveReportFile
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.ingestion_log import IngestedFilingLog
from app.models.securities import Security

TICKER = "COMB.N0000"

# Real, trimmed: FY2022 original then its amendment, both from the live
# 17 Aug 2026 capture of /api/financials for COMB.N0000.
ORIGINAL_2022 = CompanyArchiveReportFile(
    id=42000, path="cmt/upload_report_file/369_1678262400000.pdf",
    manualDate=1671817800000,  # 2022-12-30 (period end)
    uploadedDate=1678262400000,  # 2023-03-08
    authorizedDate=None,
)
AMENDED_2022 = CompanyArchiveReportFile(
    id=43000, path="cmt/upload_report_file/369_1680307200000.pdf",
    manualDate=1671817800000,  # same period end
    uploadedDate=1680307200000,  # 2023-04-01, three weeks later
    authorizedDate=None,
)
RECENT_WITH_AUTHORIZATION = CompanyArchiveReportFile(
    id=50738, path="cmt/upload_report_file/369_1773048532050.pdf",
    manualDate=1767119400000,
    uploadedDate=1773048532050,
    authorizedDate=1773051442930,
)


class TestDateResolution:
    def test_authorized_date_is_preferred_when_present(self):
        d = resolve_first_available_date(RECENT_WITH_AUTHORIZATION)
        assert d == dt.date(2026, 3, 9)

    def test_uploaded_date_is_the_fallback_for_every_older_filing(self):
        """No `authorizedDate` at all on this one — real shape for every
        filing older than ~2024, verified live across COMB.N0000's full
        history, not a hypothetical gap."""
        d = resolve_first_available_date(ORIGINAL_2022)
        assert d == dt.date(2023, 3, 8)

    def test_missing_both_dates_resolves_to_none_not_a_guess(self):
        blank = CompanyArchiveReportFile(id=1, path="x.pdf")
        assert resolve_first_available_date(blank) is None


class TestRestatementVersioning:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        return db_session

    def test_a_periods_first_filing_is_version_1(self, db):
        assert _next_version(db, TICKER, dt.date(2022, 12, 30), "annual") == 1

    def test_the_second_filing_for_the_same_period_is_version_2(self, db):
        """This is the real case: COMB.N0000 filed an original and then
        an "Amended" FY2022 annual report. The market saw the original
        first — silently overwriting it, or refusing to record the
        amendment, would both lose real information."""
        db.add(
            Fundamental(
                ticker=TICKER, period_end=dt.date(2022, 12, 30), period_type="annual",
                first_available_date=dt.date(2023, 3, 8), version=1,
                statement_line="net_income", value=100, currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED, source_url="https://cdn.cse.lk/original.pdf",
            )
        )
        db.commit()
        assert _next_version(db, TICKER, dt.date(2022, 12, 30), "annual") == 2

    def test_a_different_period_is_unaffected_by_an_existing_one(self, db):
        db.add(
            Fundamental(
                ticker=TICKER, period_end=dt.date(2022, 12, 30), period_type="annual",
                first_available_date=dt.date(2023, 3, 8), version=1,
                statement_line="net_income", value=100, currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED, source_url="https://cdn.cse.lk/original.pdf",
            )
        )
        db.commit()
        assert _next_version(db, TICKER, dt.date(2023, 12, 30), "annual") == 1


class TestIdempotency:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        return db_session

    def test_the_exact_same_source_pdf_is_not_reprocessed(self, db):
        db.add(
            Fundamental(
                ticker=TICKER, period_end=dt.date(2022, 12, 30), period_type="annual",
                first_available_date=dt.date(2023, 3, 8), version=1,
                statement_line="net_income", value=100, currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED, source_url="https://cdn.cse.lk/cmt/upload_report_file/369_1678262400000.pdf",
            )
        )
        db.commit()
        assert _already_ingested_by_source(
            db, TICKER, "https://cdn.cse.lk/cmt/upload_report_file/369_1678262400000.pdf"
        )

    def test_a_different_source_pdf_for_the_same_period_is_not_blocked(self, db):
        """The amendment must NOT be treated as already-ingested just
        because the original for the same period exists — idempotency is
        per-file, restatement-detection is a separate concern."""
        db.add(
            Fundamental(
                ticker=TICKER, period_end=dt.date(2022, 12, 30), period_type="annual",
                first_available_date=dt.date(2023, 3, 8), version=1,
                statement_line="net_income", value=100, currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED, source_url="https://cdn.cse.lk/cmt/upload_report_file/369_1678262400000.pdf",
            )
        )
        db.commit()
        assert not _already_ingested_by_source(
            db, TICKER, "https://cdn.cse.lk/cmt/upload_report_file/369_1680307200000.pdf"
        )


class TestZeroDraftFilingsAreRecordedAsIngested:
    """A REAL, structural bug, found live (18 Aug 2026), independent of
    any specific ticker: `ingest_archived_report` only recorded that a
    filing had been processed by inserting `Fundamental` rows carrying
    its `source_url` — and only did that when `drafts` was non-empty. A
    filing that legitimately produces 0 real drafts (a real, confirmed
    case: PAP.N0000's 31 March 2026 interim statement, a genuinely
    scanned PDF with no text layer — see app.ingestion.financial_pdf_
    extractor's test suite) left no trace anywhere that it had ever been
    attempted, so a naive retry would re-download and re-parse the
    identical PDF from scratch, forever. See IngestedFilingLog's own
    docstring for the full finding."""

    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        return db_session

    def _mock_a_textless_pdf(self, monkeypatch):
        """Mirrors what a genuinely scanned, textless real PDF produces
        end-to-end: `download_pdf` succeeds, but `extract_financial_
        statement_candidates` finds nothing extractable on any page."""
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"%PDF-1.4 fake, no real text layer",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [],
        )

    def test_a_zero_draft_filing_is_recorded_in_the_ingested_filing_log(self, db, monkeypatch):
        self._mock_a_textless_pdf(monkeypatch)
        report = CompanyArchiveReportFile(
            id=1, path="scanned.pdf", manualDate=1774895400000, uploadedDate=1779964134895,
        )
        inserted = ingest_archived_report(None, db, TICKER, report, period_type="quarterly")
        assert inserted == 0
        # No Fundamental row exists — this is exactly the real gap that
        # left the OLD idempotency check blind to this filing.
        assert db.query(Fundamental).filter_by(ticker=TICKER).count() == 0

        log_entry = db.query(IngestedFilingLog).filter_by(ticker=TICKER).one()
        # cmt/-normalized (see _resolve_download_url) — "scanned.pdf"
        # doesn't itself carry cmt/, so it's added before the file is
        # ever requested.
        assert log_entry.source_url == "https://cdn.cse.lk/cmt/scanned.pdf"
        assert log_entry.drafted_count == 0
        assert log_entry.period_type == "quarterly"

    def test_a_zero_draft_filing_is_not_reprocessed_on_retry(self, db, monkeypatch):
        """The actual fix, proven end-to-end: a second real attempt at
        the SAME filing must not re-download or re-parse it — it must be
        recognised as already (genuinely) tried."""
        self._mock_a_textless_pdf(monkeypatch)
        report = CompanyArchiveReportFile(
            id=1, path="scanned.pdf", manualDate=1774895400000, uploadedDate=1779964134895,
        )
        first = ingest_archived_report(None, db, TICKER, report, period_type="quarterly")
        assert first == 0

        # Simulate a fresh retry: download_pdf would now raise if called
        # again, proving the skip actually short-circuits before any
        # network access, not just returning 0 after redundant work.
        def fail_if_called(*args, **kwargs):
            raise AssertionError("download_pdf should not be called again for an already-tried filing")

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fail_if_called
        )
        second = ingest_archived_report(None, db, TICKER, report, period_type="quarterly")
        assert second == 0
        assert db.query(IngestedFilingLog).filter_by(ticker=TICKER).count() == 1  # not duplicated

    def test_already_ingested_by_source_checks_the_log_table_too(self, db):
        """Direct unit coverage of the idempotency check's new second
        branch, independent of the full `ingest_archived_report` flow."""
        assert not _already_ingested_by_source(db, TICKER, "https://cdn.cse.lk/scanned.pdf")
        db.add(
            IngestedFilingLog(
                ticker=TICKER,
                source_url="https://cdn.cse.lk/scanned.pdf",
                period_end=dt.date(2026, 3, 31),
                period_type="quarterly",
                drafted_count=0,
                processed_at=dt.datetime(2026, 8, 18, tzinfo=dt.timezone.utc),
            )
        )
        db.commit()
        assert _already_ingested_by_source(db, TICKER, "https://cdn.cse.lk/scanned.pdf")

    def test_a_filing_with_real_drafts_is_also_logged(self, db, monkeypatch):
        """The log records EVERY processed filing, not only the zero-
        draft ones — a successful filing gets both a `Fundamental` row
        (unchanged behaviour) AND a log entry (new)."""
        from app.domain.financial_statement_parsing import ExtractedLine

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"%PDF-1.4 fake",
        )
        line = ExtractedLine(
            raw_label="Total Assets", statement_line="total_assets",
            values=(Decimal("100"),), raw_text="Total Assets 100",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, line)],
        )
        report = CompanyArchiveReportFile(
            id=2, path="real.pdf", manualDate=1774895400000, uploadedDate=1779964134895,
        )
        inserted = ingest_archived_report(None, db, TICKER, report, period_type="quarterly")
        assert inserted == 1
        assert db.query(Fundamental).filter_by(ticker=TICKER).count() == 1
        log_entry = db.query(IngestedFilingLog).filter_by(ticker=TICKER).one()
        assert log_entry.drafted_count == 1


class TestUnavailableFilesAreCountedNotFatal:
    """The real, verified constraint: COMB.N0000's catalogue lists 16
    annual reports back to 2012, but every one from 2018 and earlier
    403s from the CDN. This is the module's normal operating condition
    for most companies' pre-2019 history, not an edge case."""

    def test_a_403_is_counted_as_unavailable_not_raised_to_the_caller(
        self, db_session, monkeypatch
    ):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()

        def fake_download(url, *, user_agent, timeout=60.0):
            raise httpx.HTTPStatusError(
                "403", request=httpx.Request("GET", url),
                response=httpx.Response(403, request=httpx.Request("GET", url)),
            )

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fake_download
        )

        class FakeClient:
            def post_form(self, path, model, data):
                return model(
                    infoAnnualData=[
                        CompanyArchiveReportFile(
                            id=1, path="old.pdf", manualDate=1356819000000,
                            uploadedDate=1362614400000,
                        )
                    ],
                    infoQuarterlyData=[],
                )

        summary = ingest_report_archive_for_ticker(FakeClient(), db_session, TICKER)
        assert summary == {"drafted": 0, "unavailable": 1, "failed": 0}

    def test_ingest_archived_report_itself_reraises_the_http_error(self, db_session, monkeypatch):
        """The per-file function surfaces the error; only the sweep
        function (`ingest_report_archive_for_ticker`) is responsible for
        catching it and continuing to the next file."""
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()

        def fake_download(url, *, user_agent, timeout=60.0):
            raise httpx.HTTPStatusError(
                "403", request=httpx.Request("GET", url),
                response=httpx.Response(403, request=httpx.Request("GET", url)),
            )

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fake_download
        )
        report = CompanyArchiveReportFile(
            id=1, path="old.pdf", manualDate=1356819000000, uploadedDate=1362614400000,
        )
        with pytest.raises(httpx.HTTPStatusError):
            ingest_archived_report(None, db_session, TICKER, report, period_type="annual")


class TestCmtUrlNormalization:
    """Real bug, found live: `/api/financials`'s own `path` for every
    filing older than some CDN reorganization still points at the
    pre-move location and 403s, but the SAME file id 200s the instant
    `cmt/` is inserted — confirmed against all 8 of COMB.N0000's real
    pre-2019 annual reports and 8 of AAF.N0000's, 16 for 16. This used
    to be recorded (README_ENDPOINTS.md, this module's own docstring) as
    a genuine, permanent CDN gap; it wasn't."""

    def test_a_path_without_cmt_is_normalized_with_the_literal_path_as_fallback(self):
        primary, fallback = _resolve_download_url("upload_report_file/369_1372043496.pdf")
        assert primary == "https://cdn.cse.lk/cmt/upload_report_file/369_1372043496.pdf"
        assert fallback == "https://cdn.cse.lk/upload_report_file/369_1372043496.pdf"

    def test_a_path_already_carrying_cmt_has_no_fallback_to_try(self):
        primary, fallback = _resolve_download_url("cmt/upload_report_file/369_1773048532050.pdf")
        assert primary == "https://cdn.cse.lk/cmt/upload_report_file/369_1773048532050.pdf"
        assert fallback is None

    def test_a_403_on_the_normalized_url_falls_back_to_the_literal_path_and_succeeds(
        self, db_session, monkeypatch
    ):
        """The mechanism, proven independent of which URL shape reality
        happens to favour: if the FIRST attempt 403s, the second is
        actually tried, and a real draft lands from whichever one
        works."""
        from app.domain.financial_statement_parsing import ExtractedLine

        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()

        def fake_download(url, *, user_agent, timeout=60.0):
            if "/cmt/" in url:
                raise httpx.HTTPStatusError(
                    "403", request=httpx.Request("GET", url),
                    response=httpx.Response(403, request=httpx.Request("GET", url)),
                )
            return b"%PDF-1.4 fake"

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fake_download
        )
        line = ExtractedLine(
            raw_label="Total Assets", statement_line="total_assets",
            values=(Decimal("100"),), raw_text="Total Assets 100",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(1, line)],
        )
        report = CompanyArchiveReportFile(
            id=1, path="upload_report_file/369_1372043496.pdf",
            manualDate=1356819000000, uploadedDate=1362614400000,
        )

        inserted = ingest_archived_report(None, db_session, TICKER, report, period_type="annual")

        assert inserted == 1
        row = db_session.query(Fundamental).filter_by(ticker=TICKER).one()
        # Recorded against the URL that actually served the file, not
        # the dead one — provenance should point somewhere real.
        assert row.source_url == "https://cdn.cse.lk/upload_report_file/369_1372043496.pdf"
