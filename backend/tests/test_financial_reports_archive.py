"""
Per-company historical financial-statement archive from `/api/financials`.

The archive shape below is a trimmed real capture from COMB.N0000 on
17 August 2026 — an original and an "Amended" annual report for the same
FY2022 period, exactly as the exchange actually returned it.
"""
from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal

import httpx
import pytest

from app.domain.financial_statement_parsing import ExtractedLine
from app.ingestion.financial_reports_archive_loader import (
    _already_ingested_by_source,
    _extract_with_timeout,
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


class TestMaxPerTypeBreadthFirstMode:
    """`--recent N` (`max_per_type` here) — a full-depth universe sweep
    run alphabetically can spend an entire ~50-minute run on one
    filing-heavy company before reaching the next ticker at all; this
    mode reaches every ticker's current period first."""

    def _fake_client(self, ids_downloaded: list[str]):
        class FakeClient:
            def post_form(self, path, model, data):
                return model(
                    infoAnnualData=[
                        CompanyArchiveReportFile(
                            id=i, path=f"cmt/upload_report_file/{i}.pdf",
                            manualDate=1_000_000_000_000 + i, uploadedDate=1_000_000_000_000 + i,
                        )
                        for i in range(1, 6)  # 5 annual filings, ids 1..5, oldest to newest
                    ],
                    infoQuarterlyData=[],
                )

        def fake_download(url, *, user_agent, timeout=60.0):
            ids_downloaded.append(url)
            return b"%PDF-1.4 fake"

        return FakeClient(), fake_download

    def test_max_per_type_keeps_only_the_most_recent_filings(self, db_session, monkeypatch):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        ids_downloaded: list[str] = []
        client, fake_download = self._fake_client(ids_downloaded)
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fake_download
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [],
        )

        ingest_report_archive_for_ticker(client, db_session, TICKER, max_per_type=2)

        # Only the two NEWEST of the five catalogued annual filings (ids 4, 5).
        assert len(ids_downloaded) == 2
        assert ids_downloaded[0].endswith("4.pdf")
        assert ids_downloaded[1].endswith("5.pdf")

    def test_max_per_type_none_still_sweeps_everything(self, db_session, monkeypatch):
        """The default (no `--recent`) is unchanged — full history, same
        as before this option existed."""
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        ids_downloaded: list[str] = []
        client, fake_download = self._fake_client(ids_downloaded)
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fake_download
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [],
        )

        ingest_report_archive_for_ticker(client, db_session, TICKER)

        assert len(ids_downloaded) == 5


class TestReconcileAddsMissingLinesWithoutTouchingExisting:
    """`--reconcile` — the real gap it closes: `_VARIANCE_PCT_RE` (app.
    domain.financial_statement_parsing) fixed a corrupted-label bug that
    silently dropped `revenue`/`net_income` on any statement with an
    embedded "Change %" column, verified on Hikkaduwa Beach Resort PLC's
    and Amãna Bank PLC's real filings — but every filing already ingested
    before that fix landed still only has whatever partial set of lines
    the OLD parser could reach, because the ordinary (non-reconcile) path
    skips a filing outright the moment it has ANY row on file. These
    tests simulate exactly that: an old, incomplete first pass, then a
    reconcile pass with a "fixed" extractor that now finds more."""

    _OLD_PASS_LINE = ExtractedLine(
        raw_label="Total Assets", statement_line="total_assets",
        values=(Decimal("100"),), raw_text="Total Assets 100",
    )
    _NEW_PASS_LINES = [
        ExtractedLine(
            raw_label="Total Assets", statement_line="total_assets",
            values=(Decimal("100"),), raw_text="Total Assets 100",
        ),
        ExtractedLine(
            raw_label="Revenue from contracts with customers", statement_line="revenue",
            values=(Decimal("5000"),), raw_text="Revenue from contracts with customers 5000",
        ),
    ]

    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        return db_session

    def _report(self):
        return CompanyArchiveReportFile(
            id=9, path="cmt/upload_report_file/9.pdf",
            manualDate=1774895400000, uploadedDate=1779964134895,
        )

    def _ingest_old_pass(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"%PDF-1.4 fake",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, self._OLD_PASS_LINE)],
        )
        inserted = ingest_archived_report(None, db, TICKER, self._report(), period_type="quarterly")
        assert inserted == 1

    def test_without_reconcile_an_already_ingested_filing_is_still_skipped(self, db, monkeypatch):
        """The default behaviour is unchanged by this refactor."""
        self._ingest_old_pass(db, monkeypatch)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("download_pdf must not be called for an already-ingested filing")

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf", fail_if_called
        )
        second = ingest_archived_report(None, db, TICKER, self._report(), period_type="quarterly")
        assert second == 0
        assert db.query(Fundamental).filter_by(ticker=TICKER).count() == 1

    def test_reconcile_adds_the_newly_extractable_line(self, db, monkeypatch):
        self._ingest_old_pass(db, monkeypatch)
        original_row = db.query(Fundamental).filter_by(
            ticker=TICKER, statement_line="total_assets"
        ).one()
        original_id, original_value = original_row.id, original_row.value

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, line) for line in self._NEW_PASS_LINES],
        )
        inserted = ingest_archived_report(
            None, db, TICKER, self._report(), period_type="quarterly", reconcile=True
        )
        assert inserted == 1  # only the genuinely new line, not total_assets again

        rows = {r.statement_line: r for r in db.query(Fundamental).filter_by(ticker=TICKER).all()}
        assert set(rows) == {"total_assets", "revenue"}

        # The original row is untouched — same id, same value.
        assert rows["total_assets"].id == original_id
        assert rows["total_assets"].value == original_value

        # The new row shares the original's version/restated_flag — this
        # is a deeper read of the SAME filing, not a new one.
        assert rows["revenue"].version == rows["total_assets"].version == 1
        assert rows["revenue"].restated_flag is False
        assert rows["revenue"].source_url == rows["total_assets"].source_url
        assert rows["revenue"].value == Decimal("5000")

    def test_reconcile_never_touches_an_already_confirmed_row(self, db, monkeypatch):
        """The entire point: a human reviewer's confirmation must never
        be silently discarded just because a parser improvement landed
        later, even if the "fixed" extractor now reads a DIFFERENT value
        for that same line (simulating some other, unrelated parser
        change) — reconcile must still leave it exactly alone."""
        self._ingest_old_pass(db, monkeypatch)
        confirmed = db.query(Fundamental).filter_by(
            ticker=TICKER, statement_line="total_assets"
        ).one()
        confirmed.confirmed_by = "reviewer@example.com"
        confirmed.confirmed_at = dt.datetime.now(tz=dt.timezone.utc)
        confirmed.provenance_tier = ProvenanceTier.REPORTED
        db.commit()
        confirmed_id = confirmed.id

        different_total_assets = ExtractedLine(
            raw_label="Total Assets", statement_line="total_assets",
            values=(Decimal("999"),), raw_text="Total Assets 999",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, different_total_assets), (0, self._NEW_PASS_LINES[1])],
        )
        inserted = ingest_archived_report(
            None, db, TICKER, self._report(), period_type="quarterly", reconcile=True
        )
        assert inserted == 1  # only revenue — total_assets already exists for this source_url

        still_confirmed = db.get(Fundamental, confirmed_id)
        assert still_confirmed.value == Decimal("100")  # untouched, not overwritten to 999
        assert still_confirmed.confirmed_by == "reviewer@example.com"
        assert still_confirmed.provenance_tier == ProvenanceTier.REPORTED
        assert db.query(Fundamental).filter_by(ticker=TICKER, statement_line="total_assets").count() == 1

    def test_reconcile_finds_nothing_new_returns_zero_without_duplicating_the_log(self, db, monkeypatch):
        self._ingest_old_pass(db, monkeypatch)
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, self._OLD_PASS_LINE)],  # same as before, nothing new
        )
        inserted = ingest_archived_report(
            None, db, TICKER, self._report(), period_type="quarterly", reconcile=True
        )
        assert inserted == 0
        assert db.query(IngestedFilingLog).filter_by(ticker=TICKER).count() == 1  # not duplicated

    def test_reconcile_on_a_never_ingested_filing_behaves_like_a_normal_ingest(self, db, monkeypatch):
        """`--reconcile` on a filing that was never processed at all must
        not skip or behave any differently from an ordinary first pass."""
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"%PDF-1.4 fake",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, line) for line in self._NEW_PASS_LINES],
        )
        inserted = ingest_archived_report(
            None, db, TICKER, self._report(), period_type="quarterly", reconcile=True
        )
        assert inserted == 2
        assert db.query(Fundamental).filter_by(ticker=TICKER).count() == 2


class TestExtractionTimeoutDoesNotHangTheBatch:
    """A real, live bug, not a hypothetical one: BALA.N0000's actual
    FY2024 annual report hung a reconcile sweep for 20+ minutes of
    continuous CPU burn with zero progress — confirmed independently of
    this pipeline's own code (even a bare pdfplumber `page.extract_text()`
    call on that exact file hangs). One pathological PDF must not be able
    to block an entire universe-wide sweep forever."""

    def test_a_hanging_extraction_raises_timeouterror_instead_of_blocking(self, monkeypatch):
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader._EXTRACTION_TIMEOUT_SECONDS", 0.05
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: time.sleep(1.0) or [],
        )
        with pytest.raises(TimeoutError):
            _extract_with_timeout(b"irrelevant")

    def test_a_fast_extraction_returns_normally(self, monkeypatch):
        line = ExtractedLine(
            raw_label="Total Assets", statement_line="total_assets",
            values=(Decimal("100"),), raw_text="Total Assets 100",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [(0, line)],
        )
        result = _extract_with_timeout(b"irrelevant")
        assert result == [(0, line)]

    def test_a_hanging_filing_is_caught_and_counted_not_fatal_to_the_rest_of_the_sweep(
        self, db_session, monkeypatch
    ):
        """End-to-end, through the same sweep function a real backfill
        run uses: one stuck filing must not stop the others in the same
        ticker's archive from being processed."""
        db_session.add(Security(ticker=TICKER, name="COMMERCIAL BANK", issuer_code="COMB"))
        db_session.commit()
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader._EXTRACTION_TIMEOUT_SECONDS", 0.05
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"%PDF-1.4 fake",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: time.sleep(1.0) or [],
        )

        class FakeClient:
            def post_form(self, path, model, data):
                return model(
                    infoAnnualData=[
                        CompanyArchiveReportFile(
                            id=1, path="stuck.pdf",
                            manualDate=1356819000000, uploadedDate=1362614400000,
                        )
                    ],
                    infoQuarterlyData=[],
                )

        summary = ingest_report_archive_for_ticker(FakeClient(), db_session, TICKER)
        assert summary == {"drafted": 0, "unavailable": 0, "failed": 1}


# Real, verbatim first-page text from MAHARAJA FOODS PLC's (MFPE.N0000)
# real errata filing (https://cdn.cse.lk/cmt/upload_report_file/
# 3178_1761103331773.pdf, downloaded live 27 Aug 2026) — the exact real
# case that surfaced this bug: this filing's own catalogue `manualDate`
# (22 Oct 2025) is the errata's OWN submission date, not the 31 March
# 2025 period end its own cover letter names, which created a phantom
# second "annual" period with every figure identical to the original.
ERRATA_FIRST_PAGE_TEXT_MFPE = """\
22nd October, 2025
Ms. Nilupa Perera,
Chief Regulatory officer,
Colombo Stock Exchange,
#04 - 01 West Block,
World trade Centre, Echelon Square,
Colombo 01.
Dear Madam,
MAHARAJA FOODS PLC (PQ00296080) - ERRATA – CORRECTION TO THE NET
ASSET VALUE (NAV) RATIOS NEED TO BE INCLUDED UNDER THE BALANCE
SHEET IN THE FINANCIAL STATEMENTS FOR THE YEAR ENDED 31ST MARCH
2025.
This Errata is issued to correct net asset value (NAV) ratios need to be included under the
balance sheet in the Financial Statements for the year ended 31st March 2025.
This correction does not impact the financial figures or other"""


class TestErrataAnnouncementsAreSkipped:
    """REAL BUG, found live (27 Aug 2026) tracing MFPE.N0000's real
    duplicate-period contamination (named but not fixed in
    docs/audits/R1_VALIDATION.md): a CSE "ERRATA" announcement's own
    catalogue `manualDate` does not reliably carry the period it's
    correcting, so ingesting it as an ordinary filing creates a phantom
    second period with figures identical to the original. Skipped
    outright rather than guessing the real period from the errata's own
    free-text explanation — see `ingest_archived_report`'s own comment
    for why that's a less certain signal than every other date this
    pipeline already trusts."""

    @pytest.fixture()
    def db(self, db_session):
        db_session.add(Security(ticker="MFPE.N0000", name="MAHARAJA FOODS PLC", issuer_code="MFPE"))
        db_session.commit()
        return db_session

    def test_a_real_errata_filing_is_skipped_not_ingested(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"irrelevant - _first_page_text is mocked below",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader._first_page_text",
            lambda pdf_bytes: ERRATA_FIRST_PAGE_TEXT_MFPE,
        )

        def fail_if_called(pdf_bytes):
            raise AssertionError("an errata filing must be skipped before real extraction ever runs")

        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            fail_if_called,
        )

        report = CompanyArchiveReportFile(
            id=99001, path="cmt/upload_report_file/3178_1761103331773.pdf",
            manualDate=1761091200000,  # 2025-10-22 — the errata's OWN date, not the real period
            uploadedDate=1761103331773,
        )
        inserted = ingest_archived_report(None, db, "MFPE.N0000", report, period_type="annual")
        assert inserted == 0
        # No phantom period created — neither a Fundamental row nor an
        # IngestedFilingLog entry, so a LATER, real filing for the true
        # period is never blocked by this one having been "processed."
        assert db.query(Fundamental).filter_by(ticker="MFPE.N0000").count() == 0
        assert db.query(IngestedFilingLog).filter_by(ticker="MFPE.N0000").count() == 0

    def test_an_ordinary_filing_with_no_errata_mention_is_unaffected(self, db, monkeypatch):
        """The regression guard: this fix must change nothing for the
        overwhelming majority of filings that are never an errata."""
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.download_pdf",
            lambda url, *, user_agent, timeout=60.0: b"irrelevant - mocked below",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader._first_page_text",
            lambda pdf_bytes: "MAHARAJA FOODS PLC\nAnnual Report 2024/2025\n",
        )
        monkeypatch.setattr(
            "app.ingestion.financial_reports_archive_loader.extract_financial_statement_candidates",
            lambda pdf_bytes: [
                (10, ExtractedLine(
                    raw_label="Revenue", statement_line="revenue",
                    values=(Decimal("630360999"),), raw_text="Revenue 630,360,999",
                )),
            ],
        )
        report = CompanyArchiveReportFile(
            id=99002, path="cmt/upload_report_file/3178_1761015331527.pdf",
            manualDate=1743379800000, uploadedDate=1761015331527,
        )
        inserted = ingest_archived_report(None, db, "MFPE.N0000", report, period_type="annual")
        assert inserted == 1
        assert db.query(Fundamental).filter_by(ticker="MFPE.N0000", statement_line="revenue").count() == 1
