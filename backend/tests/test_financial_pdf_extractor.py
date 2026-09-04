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

from app.domain.financial_statement_parsing import check_accounting_identities
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import (
    _is_primary_statement_page,
    announcements_for_ticker,
    build_derived_fundamental_drafts,
    build_fundamental_drafts,
    classify_period_type,
    download_pdf,
    extract_financial_statement_candidates,
    fetch_recent_financial_announcements,
    ingest_financial_statement,
    ingest_financial_statements_for_known_tickers,
    refresh_stale_fundamentals,
    resolve_first_available_date,
)
from app.ingestion.schemas import FinancialAnnouncementRow
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security
from tests.test_financial_statement_parsing import (
    BALANCE_SHEET_TEXT,
    BALANCE_SHEET_TEXT_ECL,
    BALANCE_SHEET_TEXT_NTB_DOUBLED,
    BALANCE_SHEET_TEXT_PAP,
    BALANCE_SHEET_TEXT_SWAD,
    CASH_FLOW_STATEMENT_TEXT,
    CASH_FLOW_STATEMENT_TEXT_SWAD,
    INCOME_STATEMENT_TEXT,
    SHOT_BALANCE_SHEET_TEXT,
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


def test_a_real_split_leading_digit_pair_is_reconciled_end_to_end():
    """eChannelling PLC's real genuinely-2-column filing — see
    `BALANCE_SHEET_TEXT_ECL`'s own docstring for the live bug. Proves the
    full pipeline (per-page column-count detection, the alt-values
    candidate, and the accounting-identity reconciliation) works
    together through the actual public entry point, not just each piece
    in isolation."""
    fake_pages = [_FakePage(BALANCE_SHEET_TEXT_ECL)]

    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    by_key = {line.statement_line: line.primary_value for _page, line in candidates}
    assert by_key["total_current_liabilities"] == Decimal("219185791")
    assert by_key["total_liabilities"] == Decimal("238125232")
    # unaffected lines still read exactly as printed
    assert by_key["total_assets"] == Decimal("789451516")
    assert by_key["total_equity"] == Decimal("551326283")


def test_a_component_line_with_no_sibling_identity_is_reconciled_via_magnitude_plausibility():
    """Serendib Hotels PLC's real genuine balance sheet — see
    `SHOT_BALANCE_SHEET_TEXT`'s own docstring for the live bug. `total_
    assets` has an accounting identity to reconcile against (already
    proven end-to-end by the eChannelling test above); `inventories` and
    `trade_receivables` do not — no identity in this module sums current-
    asset components — so this proves the SECOND, complementary pass
    (`reconcile_magnitude_implausible_values`) through the actual public
    entry point, not just in isolation."""
    fake_pages = [_FakePage(SHOT_BALANCE_SHEET_TEXT)]

    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    by_key = {line.statement_line: line.primary_value for _page, line in candidates}
    # scaled to real LKR ("Rs.'000" declared on this real page, ×1,000):
    assert by_key["inventories"] == Decimal("37890000")
    assert by_key["trade_receivables"] == Decimal("306895000")
    # identity-reconciled lines on the SAME page still work too:
    assert by_key["total_assets"] == Decimal("4995225000")


def _seed_jfp_security(db_session):
    if db_session.get(Security, "JFP.N0000") is None:
        db_session.add(Security(ticker="JFP.N0000", name="JF PACKAGING PLC"))
        db_session.commit()


def test_refresh_stale_fundamentals_repairs_a_row_a_since_fixed_bug_left_wrong(db_session):
    """The real HNB/CALH/COCR shape, reproduced with a controlled
    fixture: a `total_assets` row stored wrong (as if a since-fixed
    split-leading-digit bug had dropped its own leading digit — 807,110
    instead of the real 3,807,110, thousands), sitting next to correct
    total_equity/total_liabilities rows. Today's extractor, re-run
    against the identical statement text, reads `total_assets` correctly
    (3,807,110,000 — see BALANCE_SHEET_TEXT's own real J.F. Packaging
    figures), and the fresh reading now balances the identity that the
    stale stored value failed — so it should be applied."""
    _seed_jfp_security(db_session)
    period_end = dt.date(2026, 3, 31)
    stale = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_assets",
        value=Decimal("807110000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
        source_url="https://cdn.example.test/jfp.pdf", source_snippet="stale, wrong",
    )
    equity = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_equity",
        value=Decimal("1643031000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
    )
    liabilities = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_liabilities",
        value=Decimal("2164079000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
    )
    db_session.add_all([stale, equity, liabilities])
    db_session.commit()
    stale_id = stale.id

    fake_pages = [_FakePage(BALANCE_SHEET_TEXT)]
    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        result = refresh_stale_fundamentals(db_session, "JFP.N0000", period_end, "annual", b"irrelevant-bytes")

    assert result.still_failing is False
    assert result.updated == ("total_assets",)
    assert result.unchanged == 2  # equity and liabilities already matched
    assert result.skipped_confirmed == 0

    db_session.expire_all()
    refreshed = db_session.get(Fundamental, stale_id)
    assert refreshed.value == Decimal("3807110000")
    assert "RE-EXTRACTED" in refreshed.source_snippet
    assert refreshed.provenance_tier == ProvenanceTier.AI_ASSISTED  # still needs human confirmation
    assert refreshed.confirmed_by is None


def test_refresh_stale_fundamentals_never_touches_an_already_confirmed_row(db_session):
    """§8's confirm-queue discipline, extended to this new write path: a
    row a human already promoted to Reported must never be silently
    rewritten by an automated re-extraction, even one that's actually
    correct — a restatement pathway is a different, separate concern."""
    _seed_jfp_security(db_session)
    period_end = dt.date(2026, 3, 31)
    confirmed_wrong = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_assets",
        value=Decimal("807110000"), provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )
    equity = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_equity",
        value=Decimal("1643031000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
    )
    liabilities = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_liabilities",
        value=Decimal("2164079000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
    )
    db_session.add_all([confirmed_wrong, equity, liabilities])
    db_session.commit()
    confirmed_id = confirmed_wrong.id

    fake_pages = [_FakePage(BALANCE_SHEET_TEXT)]
    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        result = refresh_stale_fundamentals(db_session, "JFP.N0000", period_end, "annual", b"irrelevant-bytes")

    assert result.updated == ()
    assert result.skipped_confirmed == 1

    db_session.expire_all()
    untouched = db_session.get(Fundamental, confirmed_id)
    assert untouched.value == Decimal("807110000")  # still wrong, deliberately not fixed here


def test_refresh_stale_fundamentals_refuses_to_apply_a_fresh_reading_that_still_fails(db_session):
    """Re-extracting is a candidate, not a fix in itself — if the fresh
    reading STILL doesn't balance (a different bug, or the same one not
    actually fixed for this filing), nothing gets written, matching the
    same acceptance bar `reconcile_ambiguous_values_via_identities`
    already established elsewhere in this module."""
    _seed_jfp_security(db_session)
    period_end = dt.date(2026, 3, 31)
    stale = Fundamental(
        ticker="JFP.N0000", period_end=period_end, period_type="annual",
        first_available_date=period_end, version=1, statement_line="total_assets",
        value=Decimal("807110000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
    )
    db_session.add(stale)
    db_session.commit()
    stale_id = stale.id

    # No statement pages at all in this "PDF" — nothing to re-extract.
    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf([])):
        result = refresh_stale_fundamentals(db_session, "JFP.N0000", period_end, "annual", b"irrelevant-bytes")

    assert result.still_failing is True
    assert result.updated == ()

    db_session.expire_all()
    untouched = db_session.get(Fundamental, stale_id)
    assert untouched.value == Decimal("807110000")  # unchanged


def test_a_statement_page_with_no_detectable_unit_declaration_is_skipped_entirely():
    """A REAL bug fix's own regression test: a page that otherwise looks
    exactly like a real statement page (right marker text, right label/
    value shape) but whose unit declaration ("Rs.'000"/"Rs.", etc.) got
    lost — a genuinely possible pdfplumber extraction artifact, since
    header rows and body rows aren't visually distinguished in the raw
    text stream — must be refused entirely rather than silently treated
    as full-value (which is exactly the 1000x error this fix exists to
    prevent, just moved to a different trigger)."""
    page_with_no_unit_declared = (
        "STATEMENT OF FINANCIAL POSITION\n"
        "Group Company\n"
        "As at 31st March 2026 2025 2026 2025\n"
        "Total Assets 3,807,110 3,722,727 3,559,834 3,453,018\n"
    )
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(page_with_no_unit_declared)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")
    assert candidates == []


def test_a_notes_page_whose_own_subheading_names_a_primary_statement_is_still_excluded():
    """A REAL bug, caught against the real downloaded PDF, not a
    fixture: J.F. Packaging PLC's real Note 25 ("Financial Instruments")
    is subtitled "25.1. Financial Instruments - Statement of Financial
    Position" — the note's OWN heading contains a `_STATEMENT_PAGE_
    MARKERS` phrase, so before this test existed the note page passed
    the marker filter, and its exact reprint of the real balance-sheet
    debt figures got counted as a SECOND genuine occurrence of
    `total_interest_bearing_debt`, silently doubling it (1,348,019
    became 2,696,038). This is the real note text, trimmed to the part
    that reproduces the trap."""
    real_note_25_excerpt = (
        "142 J.F. PACKAGING PLC Annual Report 2025/26\n"
        "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS\n"
        "25. FINANCIAL INSTRUMENTS\n"
        "25.1. Financial Instruments - Statement of Financial Position\n"
        "The Financial instruments recognised in the statement of financial position are as follows:\n"
        "Interest Bearing Borrowings 20 352,950 641,967 12,451 317,819\n"
        "Interest Bearing Borrowings 20 995,069 1,207,155 727,256 970,612\n"
    )
    fake_pages = [_FakePage(BALANCE_SHEET_TEXT), _FakePage(real_note_25_excerpt)]

    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    debt_candidates = [line for _page, line in candidates if line.statement_line == "total_interest_bearing_debt"]
    assert len(debt_candidates) == 2  # only the balance sheet's own two, not the note's reprint too
    page_numbers_used = {page for page, _ in candidates}
    assert 1 not in page_numbers_used  # the notes page (index 1) must be fully excluded


def test_a_joint_venture_summarised_statement_note_is_excluded_not_read_as_the_real_one():
    """A REAL bug, found live tracing HNB.N0000's real ~15x net_income
    error (27 Aug 2026, docs/audits/R1_VALIDATION.md's own named, unfixed
    finding): HNB's real FY2024 annual report has a note — "34 (d)
    Summarised Statement Of Profit Or Loss Of Joint Venture - Acuity
    Partners (Pvt) Ltd and its Subsidiaries" (real page 403, trimmed
    below to the part that reproduces the trap) — printing a miniature
    income statement for its OWN joint venture, using the exact same
    canonical labels ("Profit for the year", "Revenue", ...) HNB's real
    consolidated statement uses. It does NOT contain "notes to the" (a
    continuation page deep inside note 34, not the notes section's own
    opening header) and appears BEFORE HNB's real income statement in
    page order, so before this fix, "first occurrence wins" kept the
    joint venture's own (much smaller) net_income as if it were HNB's."""
    real_jv_note_excerpt = (
        "34 (d) Summarised Statement Of Profit Or Loss Of Joint Venture - Acuity Partners "
        "(Pvt) Ltd and its Subsidiaries\n"
        "For the year ended 31st December 2024 2023\n"
        "Rs 000 Rs 000\n"
        "Revenue 6,591,946 4,637,650\n"
        "Profit before tax 4,295,411 2,291,697\n"
        "Profit for the year 3,179,557 2,016,451\n"
    )
    fake_pages = [_FakePage(real_jv_note_excerpt), _FakePage(INCOME_STATEMENT_TEXT)]

    with patch("app.ingestion.financial_pdf_extractor.pdfplumber.open", return_value=_FakePdf(fake_pages)):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    net_income_candidates = [line for _page, line in candidates if line.statement_line == "net_income"]
    assert len(net_income_candidates) == 1  # only the real income statement's own, not the JV note's
    page_numbers_used = {page for page, _ in candidates}
    assert 0 not in page_numbers_used  # the JV note page (index 0) must be fully excluded


def test_a_real_primary_statement_pages_own_footer_does_not_exclude_it():
    """A REAL bug, found live in the SAME HNB.N0000 investigation
    (27 Aug 2026) as the joint-venture note above, tracing why fixing
    that alone still wasn't enough: HNB's own REAL primary income
    statement page (its genuine "STATEMENT OF PROFIT OR LOSS AND OTHER
    COMPREHENSIVE INCOME") was ALSO being excluded — by the original
    "notes to the" marker firing on this completely ordinary FOOTER line
    every real primary statement page in this filing carries (verified:
    real page 290, line 39 of 41 — the real page's last real line before
    a trailing blank one): "The notes to the financial statements from
    pages 298 to 466 form an integral part of these financial
    statements." That's routine boilerplate on a genuine primary
    statement page, not a notes-section header — the fix scopes the
    `_NOTES_PAGE_MARKERS` check to the page's own first `_NOTES_MARKER_
    SEARCH_LINES` lines, where a real notes-section header (or a real
    "Summarised Statement of..." sub-schedule heading) always actually
    lives, so this footer sentence deep in the page body no longer
    counts."""
    real_hnb_income_statement_excerpt = (
        "STATEMENT OF PROFIT OR LOSS AND\n"
        "OTHER COMPREHENSIVE INCOME\n"
        "Bank Group\n"
        "For the year ended 31st December 2024 2023 2024 2023\n"
        "Note Rs 000 Rs 000 Rs 000 Rs 000\n"
        "PROFIT FOR THE YEAR 41,341,793 20,353,118 44,839,632 23,606,491\n"
        "Other comprehensive income that will not be reclassified to profit or loss\n"
        "in subsequent periods\n"
        "Change in fair value of investments in equity instruments 3,043,986 3,398,710 3,042,939 3,399,392\n"
        "Total comprehensive income for the year 44,560,831 23,755,335 48,459,534 26,986,121\n"
        "The notes to the financial statements from pages 298 to 466 form an integral "
        "part of these financial statements.\n"
    )
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(real_hnb_income_statement_excerpt)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    net_income_candidates = [line for _page, line in candidates if line.statement_line == "net_income"]
    assert len(net_income_candidates) == 1
    assert net_income_candidates[0].primary_value == Decimal("41341793000")  # scaled from Rs'000


def test_a_genuine_notes_section_header_is_still_excluded_by_the_scoped_check():
    """Regression guard: scoping the check to the page's own first lines
    must not weaken the ORIGINAL real case this marker exists for — a
    genuine notes-section header still sits well within that window on
    every real fixture checked."""
    assert not _is_primary_statement_page(
        "142 J.F. PACKAGING PLC Annual Report 2025/26\n"
        "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS\n"
        "25. FINANCIAL INSTRUMENTS\n"
    )


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
    # JFP's real statement declares "Rs.000" — every value scaled ×1000
    # to real LKR (see app.domain.financial_statement_parsing.
    # detect_unit_scale). 3,807,110 and 189,908 are the raw printed
    # figures; the true LKR values are 1000x larger.
    assert by_line["total_assets"].value == Decimal("3807110000")
    assert by_line["net_income"].value == Decimal("189908000")

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
    # own hand-summed total exactly (see test_financial_statement_parsing.py).
    # JFP's real statement declares "Rs.000", so the derived draft is
    # also scaled ×1000 to real LKR, same as every directly-extracted line.
    assert draft.value == Decimal("187881000")


def test_full_extraction_and_derivation_pass_on_jfps_real_balance_sheet_and_cash_flow():
    """Both real pages together: total_interest_bearing_debt SUMS across
    its two real occurrences (build_fundamental_drafts's job) while
    net_working_capital and change_in_net_working_capital are DERIVED
    (build_derived_fundamental_drafts's job) — the full real pipeline for
    every §18 DCF input this session ever unlocked, on one real filing."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT), _FakePage(CASH_FLOW_STATEMENT_TEXT)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    direct = build_fundamental_drafts(
        ticker="JFP.N0000", period_end=dt.date(2026, 3, 31), period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf",
        candidates=candidates,
    )
    derived = build_derived_fundamental_drafts(
        ticker="JFP.N0000", period_end=dt.date(2026, 3, 31), period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        source_url="https://cdn.cse.lk/cmt/upload_report_file/3399_1786715988377.pdf",
        candidates=candidates,
    )

    by_line = {d.statement_line: d for d in direct}
    # JFP's real statement declares "Rs.000" — every value scaled ×1000
    # to real LKR; raw printed figures were 352,950 + 995,069 = 1,348,019.
    assert by_line["total_interest_bearing_debt"].value == Decimal("1348019000")
    # capex is deliberately NOT here — J.F. Packaging's real capex label
    # wraps across two physical lines on its cash-flow statement, still
    # unsolved (see this project's own documented limitation).
    assert "capital_expenditure" not in by_line

    derived_by_line = {d.statement_line: d for d in derived}
    assert derived_by_line["net_working_capital"].value == Decimal("1647203000")
    assert derived_by_line["change_in_net_working_capital"].value == Decimal("187881000")


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
    # JFP's real statement declares "Rs.000" — scaled ×1000 to real LKR.
    assert total_assets.value == Decimal("3807110000")
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


def test_ntbs_real_character_doubled_balance_sheet_page_now_produces_drafts():
    """A REAL bug, found live (18 Aug 2026): NTB.N0000's real interim
    statement for the six months ended 30 June 2026 has its page 4 (the
    real Statement of Financial Position) rendered with every bold-text
    character glyph doubled — before `repair_character_doubling` existed,
    this page's own doubled title never matched `_STATEMENT_PAGE_MARKERS`
    and was silently skipped, 0 drafts for NTB's newest quarter. Using
    the FULL, real, un-repaired page text captured directly from the real
    downloaded PDF (BALANCE_SHEET_TEXT_NTB_DOUBLED) end-to-end through the
    real page-selection + extraction pipeline, not a hand-simplified
    example."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT_NTB_DOUBLED)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    by_line = {line.statement_line: line.primary_value for _page, line in candidates if line.statement_line}
    assert by_line["total_assets"] == Decimal("923175159000")  # LKR '000 -> real LKR
    assert by_line["total_liabilities"] == Decimal("819246480000")
    assert by_line["total_equity"] == Decimal("103928679000")
    assert by_line["total_equity_and_liabilities"] == Decimal("923175159000")

    # Independent arithmetic check on the recovered figures — the same
    # check that would have caught a bad de-doubling immediately, exactly
    # as it caught the original split-thousands bug.
    identities = check_accounting_identities(
        {k: v for k, v in by_line.items() if v is not None}
    )
    assert identities  # at least one identity was checkable
    assert all(c.passed for c in identities)


def test_paps_real_bare_lkr_balance_sheet_now_produces_drafts():
    """A REAL bug, found live (18 Aug 2026): Panasian Power PLC's
    (PAP.N0000) real interim statement for the quarter ended 30 June 2026
    produced 0 drafts. Its real Statement of Financial Position page (a
    genuine primary-statement-marker match) declared its units as a bare
    "LKR LKR LKR LKR" — no "'000" suffix — which `detect_unit_scale`
    refused to recognise as either a thousands or a full-value scale
    before this fix, so the page was skipped entirely despite being
    otherwise fully extractable. Using the FULL, real, un-simplified page
    text captured directly from the real downloaded PDF
    (BALANCE_SHEET_TEXT_PAP), including its own real split-thousands
    space artifacts, end-to-end through the real pipeline."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(BALANCE_SHEET_TEXT_PAP)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    by_line = {line.statement_line: line.primary_value for _page, line in candidates if line.statement_line}
    # PAP's real statement declares bare "LKR" (full value, scale=1) —
    # unlike every "Rs.'000"/"LKR '000" filing seen so far, these are NOT
    # scaled ×1000.
    assert by_line["total_assets"] == Decimal("9828732284")
    assert by_line["total_equity"] == Decimal("3127275067")
    assert by_line["total_liabilities"] == Decimal("6701457217")
    assert by_line["total_equity_and_liabilities"] == Decimal("9828732284")

    identities = check_accounting_identities({k: v for k, v in by_line.items() if v is not None})
    assert identities
    # The two balance-sheet footing identities pass — the page extracts
    # cleanly at scale 1.
    by_name = {c.name: c for c in identities}
    assert by_name["assets = equity + liabilities"].passed
    assert by_name["assets = equity and liabilities"].passed
    # The "owners equity + NCI = total equity" identity added 4 Sep 2026
    # correctly FLAGS this fixture: PAP's `equity attributable to owners`
    # line is mis-read here (2,254,148,208 against a real 3,054,148,208 =
    # total_equity - NCI), off by exactly 800m. That is the identity
    # doing its job — the gate drops the bad line and `_gather_inputs`
    # falls back to total_equity - NCI.
    assert not by_name["owners equity + NCI = total equity"].passed


def test_a_genuinely_scanned_pdf_with_no_text_layer_produces_zero_drafts_not_a_crash():
    """A genuine, real, unfixable limitation — NOT a bug: Panasian Power
    PLC's (PAP.N0000) real interim statement for the quarter ended 31
    March 2026 downloads successfully but `pdfplumber.extract_text()`
    returns an empty string on every one of its 15 real pages (a scanned
    PDF with no embedded text layer at all — see
    app.ingestion.financial_reports_archive_loader.ingest_archived_
    report's own docstring for the full finding). No extraction-logic fix
    can recover text that was never encoded in the file; OCR is out of
    scope. This must produce 0 drafts cleanly, never a crash and never a
    fabricated figure."""
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage("") for _ in range(15)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")
    assert candidates == []


def test_paps_real_statement_of_comprehensive_income_title_is_recognised():
    """PAP's income statement is titled "STATEMENT OF COMPREHENSIVE
    INCOME" — no "profit or loss" wording at all, a real, genuinely
    different title from every filing checked so far (J.F. Packaging's
    own equivalent page already matches the existing "statement of
    profit or loss" marker)."""
    pap_income_statement_excerpt = (
        "PANASIAN POWER PLC\n"
        "INTERIM CONDENSED FINANCIAL STATEMENTS - QUARTER ENDED 30 JUNE 2026\n"
        "PROVISIONAL FINANCIAL STATEMENTS\n"
        "STATEMENT OF COMPREHENSIVE INCOME\n"
        "Group Company\n"
        "LKR LKR LKR LKR\n"
        "Total comprehensive income for the period 151,627,495 72,111,211 (6,370,264) 1,955,469\n"
    )
    with patch(
        "app.ingestion.financial_pdf_extractor.pdfplumber.open",
        return_value=_FakePdf([_FakePage(pap_income_statement_excerpt)]),
    ):
        candidates = extract_financial_statement_candidates(b"irrelevant-bytes")

    by_line = {line.statement_line: line.primary_value for _page, line in candidates if line.statement_line}
    assert by_line["total_comprehensive_income"] == Decimal("151627495")


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
