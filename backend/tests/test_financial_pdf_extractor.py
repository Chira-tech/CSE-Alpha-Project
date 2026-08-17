"""
app.ingestion.financial_pdf_extractor. Real payloads verified live against
the getFinancialAnnouncement endpoint (J.F. Packaging PLC, 14 Aug 2026 —
see README_ENDPOINTS.md). The pdfplumber-facing functions are tested
against fake page objects returning the SAME real statement text used in
test_financial_statement_parsing.py (extracted from an actual downloaded
annual report), rather than a real PDF file — pdfplumber's own PDF
decoding is a well-tested upstream concern; what this codebase adds is the
page-selection and candidate-collection logic layered on top of it, which
is what these tests exercise.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
import respx

from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import (
    announcements_for_ticker,
    build_derived_fundamental_drafts,
    build_fundamental_drafts,
    classify_period_type,
    download_pdf,
    extract_financial_statement_candidates,
    fetch_recent_financial_announcements,
    ingest_financial_statement,
    ingest_financial_statements_for_known_tickers,
    resolve_first_available_date,
)
from app.ingestion.schemas import FinancialAnnouncementRow
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security
from tests.test_financial_statement_parsing import (
    BALANCE_SHEET_TEXT,
    BALANCE_SHEET_TEXT_SWAD,
    CASH_FLOW_STATEMENT_TEXT,
    CASH_FLOW_STATEMENT_TEXT_SWAD,
    INCOME_STATEMENT_TEXT,
)

REAL_FEED_ROW = {
    "id": 52726,
    "path": "cmt/upload_report_file/3399_1786715988377.pdf",
    "manualDate": 1774895400000,
    "uploadedDate": "14 Aug 2026 07:29:48 PM",
    "authorizedDate": "14 Aug 2026 08:16:24 PM",
    "fileText": "Annual Report as at 31st March 2026",
    "name": "JF PACKAGING PLC",
    "symbol": "JFP",
}

REAL_QUARTERLY_ROW = {
    "id": 52724,
    "path": "cmt/upload_report_file/3399_1786716080566.06.2026 CSE.pdf",
    "manualDate": 1782757800000,
    "uploadedDate": "14 Aug 2026 07:31:20 PM",
    "authorizedDate": None,
    "fileText": "Interim Financial Statements for the Quarter ended 30th June 2026",
    "name": "JF PACKAGING PLC",
    "symbol": "JFP",
}


@respx.mock
def test_fetch_recent_financial_announcements_parses_real_shape():
    respx.post("https://example.test/api/getFinancialAnnouncement").mock(
        return_value=httpx.Response(200, json={"reqFinancialAnnouncemnets": [REAL_FEED_ROW]})
    )
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    rows = fetch_recent_financial_announcements(client)
    client.close()

    assert len(rows) == 1
    assert rows[0].symbol == "JFP"
    assert rows[0].path == "cmt/upload_report_file/3399_1786715988377.pdf"


def test_announcements_for_ticker_matches_bare_symbol():
    rows = [FinancialAnnouncementRow.model_validate(REAL_FEED_ROW)]
    assert announcements_for_ticker(rows, "JFP.N0000") == rows
    assert announcements_for_ticker(rows, "jfp.n0000") == rows  # case-insensitive
    assert announcements_for_ticker(rows, "AAF.N0000") == []


@pytest.mark.parametrize(
    ("file_text", "expected"),
    [
        ("Annual Report as at 31st March 2026", "annual"),
        ("Interim Financial Statements for the Quarter ended 30th June 2026", "quarterly"),
        ("Some Other Filing Type", None),
        (None, None),
    ],
)
def test_classify_period_type(file_text, expected):
    assert classify_period_type(file_text) == expected


def test_resolve_first_available_date_prefers_authorized_over_uploaded():
    row = FinancialAnnouncementRow.model_validate(REAL_FEED_ROW)
    assert resolve_first_available_date(row) == dt.date(2026, 8, 14)


def test_resolve_first_available_date_falls_back_to_uploaded_when_authorized_missing():
    row = FinancialAnnouncementRow.model_validate(REAL_QUARTERLY_ROW)
    assert resolve_first_available_date(row) == dt.date(2026, 8, 14)  # from uploadedDate


@respx.mock
def test_download_pdf():
    respx.get("https://cdn.example.test/report.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 fake content")
    )
    content = download_pdf("https://cdn.example.test/report.pdf", user_agent="test-agent/1.0")
    assert content.startswith(b"%PDF")


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdf:
    def __init__(self, pages: list[_FakePage]):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_extract_financial_statement_candidates_only_reads_statement_pages():
    """A 5-page fake document: a cover page, the balance sheet, an
    unrelated notes page that happens to contain the word "Total" (the
    exact false-positive risk this filtering exists to avoid), the
    income statement, and the cash flow statement."""
    notes_page_with_a_trap = (
        "NOTES TO THE FINANCIAL STATEMENTS\n"
        "24.1 Related Party Transactions\n"
        "Total Due from Related Parties 999,999 888,888 777,777 666,666\n"
    )
    fake_pages = [
        _FakePage("J.F. PACKAGING PLC ANNUAL REPORT 2025/26\nCover page, nothing extractable here."),
        _FakePage(BALANCE_SHEET_TEXT),
        _FakePage(notes_page_with_a_trap),
        _FakePage(INCOME_STATEMENT_TEXT),
        _FakePage(CASH_FLOW_STATEMENT_TEXT),
    ]

    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    statement_lines = {line.statement_line for _, line in candidates}
    assert "total_assets" in statement_lines
    assert "net_income" in statement_lines
    assert "cash_flow_from_operations" in statement_lines
    # the trap on the (unfiltered) notes page must NOT have leaked in —
    # it isn't one of our canonical labels anyway, but this also confirms
    # the page-marker filter actually skipped that page rather than
    # merely relying on label matching to save us
    page_numbers_used = {page for page, _ in candidates}
    assert 2 not in page_numbers_used  # the notes page is index 2
    assert 0 not in page_numbers_used  # the cover page is index 0
    assert page_numbers_used == {1, 3, 4}


def test_build_fundamental_drafts_are_ai_assisted_and_unconfirmed():
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT), _FakePage(INCOME_STATEMENT_TEXT)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    drafts = build_fundamental_drafts(
        ticker="JFP.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf",
        candidates=candidates,
    )

    by_line = {d.statement_line: d for d in drafts}
    assert by_line["total_assets"].value == Decimal("3807110")
    assert by_line["net_income"].value == Decimal("189908")

    for draft in drafts:
        assert draft.provenance_tier is ProvenanceTier.AI_ASSISTED
        assert draft.confirmed_by is None
        assert draft.confirmed_at is None
        assert draft.source_snippet  # the raw line text is preserved for review
        assert draft.ticker == "JFP.N0000"
        assert draft.first_available_date == dt.date(2026, 8, 14)


def test_build_fundamental_drafts_sums_a_current_non_current_split_debt_line():
    """Swadeshi's real balance sheet prints "Interest Bearing Loans and
    Borrowings" twice — once under Non-current Liabilities (11,672,993),
    once under Current Liabilities (634,163,111) — and this must produce
    ONE draft with the SUM (645,836,104), not silently keep only the
    first occurrence and drop the much larger second one, which is what
    the ordinary "first wins" dedup rule would otherwise do."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT_SWAD)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    drafts = build_fundamental_drafts(
        ticker="SWAD.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 17),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/687_1786359392289.pdf",
        candidates=candidates,
    )

    debt_drafts = [d for d in drafts if d.statement_line == "total_interest_bearing_debt"]
    assert len(debt_drafts) == 1
    draft = debt_drafts[0]
    assert draft.value == Decimal("645836104")  # 11,672,993 + 634,163,111
    assert draft.source_page == 0  # both occurrences are on the same real page
    assert "SUM of 2 occurrences" in draft.source_snippet
    assert "11,672,993" in draft.source_snippet
    assert "634,163,111" in draft.source_snippet
    assert draft.provenance_tier is ProvenanceTier.AI_ASSISTED

    # Other lines on the same page are entirely unaffected by the special-cased key.
    assert next(d for d in drafts if d.statement_line == "total_assets").value == Decimal("3812290448")


def test_build_derived_fundamental_drafts_sums_split_depreciation_and_amortisation():
    """Swadeshi's real shape: Depreciation and Amortization printed as
    two separate lines, AND (a differently-worded, real subtotal pair)
    the working-capital change is derivable too. build_fundamental_drafts
    alone would store the raw parts only; this covers the second pass
    that also derives both combined figures other code (§18's DCF)
    expects."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(CASH_FLOW_STATEMENT_TEXT_SWAD)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    derived_drafts = build_derived_fundamental_drafts(
        ticker="SWAD.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 17),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/687_1786359392289.pdf",
        candidates=candidates,
    )

    by_line = {d.statement_line: d for d in derived_drafts}
    assert set(by_line) == {"depreciation_and_amortisation", "change_in_net_working_capital"}

    da = by_line["depreciation_and_amortisation"]
    # 34,338,325 + 1,564,379 = 35,902,704
    assert da.value == Decimal("35902704")
    assert da.source_page is None  # not from one printed line
    assert "DERIVED" in da.source_snippet
    assert "depreciation_expense" in da.source_snippet
    assert "amortisation_expense" in da.source_snippet

    wc = by_line["change_in_net_working_capital"]
    # 127,832,034 - (-124,492,704) = 252,324,738
    assert wc.value == Decimal("252324738")
    assert "operating_profit_before_working_capital_changes" in wc.source_snippet
    assert "cash_generated_from_operations" in wc.source_snippet

    for draft in derived_drafts:
        assert draft.provenance_tier is ProvenanceTier.AI_ASSISTED
        assert draft.confirmed_by is None


def test_build_derived_fundamental_drafts_never_overwrites_an_already_printed_line():
    """J.F. Packaging's real shape: the combined D&A line IS printed, so
    that one must not be derived — but working-capital change still
    derives, since J.F. Packaging never prints that combined figure
    directly either."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(CASH_FLOW_STATEMENT_TEXT)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    derived_drafts = build_derived_fundamental_drafts(
        ticker="JFP.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf",
        candidates=candidates,
    )
    assert len(derived_drafts) == 1
    draft = derived_drafts[0]
    assert draft.statement_line == "change_in_net_working_capital"
    # 681,378 - 493,497 = 187,881 — matches the 5 real component lines'
    # own hand-summed total exactly (see test_financial_statement_parsing.py)
    assert draft.value == Decimal("187881")


@respx.mock
def test_ingest_financial_statement_end_to_end(db_session):
    db_session.add(Security(ticker="JFP.N0000", name="JF Packaging PLC"))
    db_session.commit()

    respx.get("https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 fake")
    )
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    row = FinancialAnnouncementRow.model_validate(REAL_FEED_ROW)

    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT), _FakePage(INCOME_STATEMENT_TEXT)]),
    ):
        inserted = ingest_financial_statement(client, db_session, "JFP.N0000", row)
    client.close()

    assert inserted > 0
    stored = db_session.query(Fundamental).filter_by(ticker="JFP.N0000").all()
    assert len(stored) == inserted
    total_assets = next(f for f in stored if f.statement_line == "total_assets")
    assert total_assets.value == Decimal("3807110")
    assert total_assets.period_end == dt.date(2026, 3, 31)  # from manualDate
    assert total_assets.first_available_date == dt.date(2026, 8, 14)  # from authorizedDate
    assert total_assets.period_type == "annual"
    assert total_assets.provenance_tier is ProvenanceTier.AI_ASSISTED


@respx.mock
def test_ingest_financial_statement_skips_if_already_ingested(db_session):
    db_session.add(Security(ticker="JFP.N0000", name="JF Packaging PLC"))
    db_session.add(
        Fundamental(
            ticker="JFP.N0000",
            period_end=dt.date(2026, 3, 31),
            period_type="annual",
            first_available_date=dt.date(2026, 8, 14),
            version=1,
            statement_line="total_assets",
            value=Decimal("3807110"),
            provenance_tier=ProvenanceTier.AI_ASSISTED,
        )
    )
    db_session.commit()

    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    row = FinancialAnnouncementRow.model_validate(REAL_FEED_ROW)

    # No PDF-download route mocked at all — if the skip check didn't work,
    # this would raise a respx "no matching route" error.
    inserted = ingest_financial_statement(client, db_session, "JFP.N0000", row)
    client.close()
    assert inserted == 0


def test_ingest_financial_statement_skips_unrecognised_filing_type(db_session):
    db_session.add(Security(ticker="JFP.N0000", name="JF Packaging PLC"))
    db_session.commit()
    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    row = FinancialAnnouncementRow.model_validate({**REAL_FEED_ROW, "fileText": "Some Other Notice"})

    inserted = ingest_financial_statement(client, db_session, "JFP.N0000", row)
    client.close()
    assert inserted == 0


@respx.mock
def test_ingest_financial_statements_for_known_tickers_matches_and_ingests(db_session):
    db_session.add(Security(ticker="JFP.N0000", name="JF Packaging PLC"))
    db_session.add(Security(ticker="AAF.N0000", name="Asia Asset Finance PLC"))  # not in the feed
    db_session.commit()

    respx.post("https://example.test/api/getFinancialAnnouncement").mock(
        return_value=httpx.Response(200, json={"reqFinancialAnnouncemnets": [REAL_FEED_ROW]})
    )
    respx.get("https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 fake")
    )

    client = CseClient(base_url="https://example.test/api", min_seconds_between_calls=0.0)
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT)]),
    ):
        total = ingest_financial_statements_for_known_tickers(
            client, db_session, ["JFP.N0000", "AAF.N0000"]
        )
    client.close()

    assert total > 0
    assert db_session.query(Fundamental).filter_by(ticker="AAF.N0000").count() == 0
    assert db_session.query(Fundamental).filter_by(ticker="JFP.N0000").count() == total


def test_build_fundamental_drafts_deduplicates_by_statement_line():
    """If the same canonical line somehow appears twice in one run, only
    the first occurrence becomes a draft — never two conflicting rows for
    the same (ticker, period_end, statement_line)."""
    duplicated_page_text = BALANCE_SHEET_TEXT + "\n" + BALANCE_SHEET_TEXT
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(duplicated_page_text)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    drafts = build_fundamental_drafts(
        ticker="JFP.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        source_url="https://cdn.cse.lk/report.pdf",
        candidates=candidates,
    )
    statement_lines = [d.statement_line for d in drafts]
    assert len(statement_lines) == len(set(statement_lines))
