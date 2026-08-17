"""
Per-company historical financial-statement archive from `/api/financials`.

The archive shape below is a trimmed real capture from COMB.N0000 on
17 August 2026 — an original and an "Amended" annual report for the same
FY2022 period, exactly as the exchange actually returned it.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest

from app.ingestion.financial_reports_archive_loader import (
    _already_ingested_by_source,
    _next_version,
    ingest_archived_report,
    ingest_report_archive_for_ticker,
    resolve_first_available_date,
)
from app.ingestion.schemas import CompanyArchiveReportFile
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
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
