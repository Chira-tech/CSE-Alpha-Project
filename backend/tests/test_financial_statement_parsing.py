"""
app.domain.financial_statement_parsing, tested against real lines
captured from J.F. Packaging PLC's FY2025/26 annual report (downloaded via
the verified `getFinancialAnnouncement` endpoint — see
app/ingestion/README_ENDPOINTS.md). Using the real, messy text — note
references, embedded dashes, parenthesised negatives, and nil markers, all
mixed together exactly as CSE printed them — rather than clean invented
examples is deliberate: this is the part of the pipeline most likely to
silently produce a wrong number if it's ever written from imagination.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.financial_statement_parsing import (
    extract_candidate_lines,
    match_canonical_label,
    normalize_label,
    split_label_and_values,
)

BALANCE_SHEET_TEXT = """\
102 J.F. PACKAGING PLC Annual Report 2025/26
STATEMENT OF FINANCIAL POSITION
Group Company
As at 31st March 2026 2025 2026 2025
Notes Rs.000 Rs.000 Rs.000 Rs.000
Assets
Non-Current Assets
Property, Plant & Equipment 11 1,025,218 891,500 694,892 691,557
Intangible Assets - CWIP 13.2 6,512 3,191 - -
Total Non-Current Assets 1,625,285 1,706,069 2,162,547 2,191,782
Current Assets
Cash and Cash Equivalents 18 82,835 123,842 40,597 29,305
Total Current Assets 2,181,825 2,016,658 1,397,287 1,261,236
Total Assets 3,807,110 3,722,727 3,559,834 3,453,018
EQUITY
Stated Capital 19 1,049,047 449,047 1,049,047 449,047
FVOCI Reserve (4,784) 160,738 - -
Total Equity 1,643,031 1,116,530 2,394,220 1,776,662
Total Non-Current Liabilities 435,498 702,359 52,089 345,694
Total Current Liabilities 1,728,581 1,903,838 1,113,525 1,330,662
Total Liabilities 2,164,079 2,606,197 1,165,614 1,676,356
Total Equity and Liabilities 3,807,110 3,722,727 3,559,834 3,453,018
"""

INCOME_STATEMENT_TEXT = """\
STATEMENT OF PROFIT OR LOSS AND OTHER
COMPREHENSIVE INCOME
Group Company
For the year ended 31st March 2026 2025 2026 2025
Notes Rs.000 Rs.000 Rs.000 Rs.000
Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137
Cost of Sales (3,335,742) (3,238,713) (1,927,694) (1,962,176)
Gross Profit 1,169,059 1,146,501 429,257 408,961
Operating Profit 524,378 607,671 291,201 351,107
Profit Before Tax 8 320,460 303,020 133,643 100,628
Income Tax Expense 9 (130,552) (172,395) (24,280) (40,169)
Profit for the Year 189,908 130,625 109,363 60,459
Total Comprehensive Income for the Year 12,566 285,660 103,623 58,412
Earnings per Share / Diluted EPS (Rs.) 10.1 1.37 1.08 0.79 0.50
"""


@pytest.mark.parametrize(
    ("line", "expected_label", "expected_statement_line", "expected_primary"),
    [
        (
            "Total Assets 3,807,110 3,722,727 3,559,834 3,453,018",
            "Total Assets",
            "total_assets",
            Decimal("3807110"),
        ),
        (
            # note reference "5" must be dropped, not read as the value
            "Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137",
            "Revenue",
            "revenue",
            Decimal("4504801"),
        ),
        (
            "Profit for the Year 189,908 130,625 109,363 60,459",
            "Profit for the Year",
            "net_income",
            Decimal("189908"),
        ),
        (
            # parenthesised = negative
            "Cost of Sales (3,335,742) (3,238,713) (1,927,694) (1,962,176)",
            "Cost of Sales",
            "cost_of_sales",
            Decimal("-3335742"),
        ),
        (
            "Total Non-Current Assets 1,625,285 1,706,069 2,162,547 2,191,782",
            "Total Non-Current Assets",
            "total_non_current_assets",
            Decimal("1625285"),
        ),
    ],
)
def test_parses_real_captured_lines(line, expected_label, expected_statement_line, expected_primary):
    result = split_label_and_values(line)
    assert result is not None
    assert result.raw_label == expected_label
    assert result.statement_line == expected_statement_line
    assert result.primary_value == expected_primary


def test_embedded_dash_in_label_is_not_mistaken_for_a_nil_value():
    """"Intangible Assets - CWIP" has a literal dash as part of the label
    text, immediately followed by a genuine note reference and then two
    real nil markers at the end — all three kinds of dash-like tokens in
    one line, and only the trailing two are values."""
    result = split_label_and_values("Intangible Assets - CWIP 13.2 6,512 3,191 - -")
    assert result is not None
    assert result.raw_label == "Intangible Assets - CWIP"
    assert result.values == (Decimal("6512"), Decimal("3191"), None, None)
    assert result.statement_line is None  # not a canonical line, and that's correct


def test_note_reference_with_decimal_point_is_dropped():
    result = split_label_and_values("Earnings per Share / Diluted EPS (Rs.) 10.1 1.37 1.08 0.79 0.50")
    assert result is not None
    assert result.values == (Decimal("1.37"), Decimal("1.08"), Decimal("0.79"), Decimal("0.50"))


@pytest.mark.parametrize(
    "line",
    [
        "STATEMENT OF FINANCIAL POSITION",
        "Group Company",
        "Notes Rs.000 Rs.000 Rs.000 Rs.000",
        "Assets",
        "",
    ],
)
def test_non_data_lines_return_none(line):
    assert split_label_and_values(line) is None


def test_extract_candidate_lines_finds_every_canonical_balance_sheet_item():
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["total_assets"] == Decimal("3807110")
    assert by_statement_line["total_current_assets"] == Decimal("2181825")
    assert by_statement_line["total_non_current_assets"] == Decimal("1625285")
    assert by_statement_line["total_equity"] == Decimal("1643031")
    assert by_statement_line["total_liabilities"] == Decimal("2164079")
    assert by_statement_line["total_current_liabilities"] == Decimal("1728581")
    assert by_statement_line["total_non_current_liabilities"] == Decimal("435498")
    assert by_statement_line["total_equity_and_liabilities"] == Decimal("3807110")
    # sanity check the accounting identity actually holds on the extracted numbers
    assert by_statement_line["total_assets"] == by_statement_line["total_equity_and_liabilities"]


def test_extract_candidate_lines_finds_every_canonical_income_statement_item():
    lines = extract_candidate_lines(INCOME_STATEMENT_TEXT)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["revenue"] == Decimal("4504801")
    assert by_statement_line["cost_of_sales"] == Decimal("-3335742")
    assert by_statement_line["gross_profit"] == Decimal("1169059")
    assert by_statement_line["operating_profit"] == Decimal("524378")
    assert by_statement_line["profit_before_tax"] == Decimal("320460")
    assert by_statement_line["income_tax_expense"] == Decimal("-130552")
    assert by_statement_line["net_income"] == Decimal("189908")
    assert by_statement_line["total_comprehensive_income"] == Decimal("12566")
    # revenue - cost of sales = gross profit, on the extracted numbers
    assert by_statement_line["revenue"] + by_statement_line["cost_of_sales"] == by_statement_line["gross_profit"]


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Total Assets", "total assets"),
        ("  Total   Equity  ", "total equity"),
        ("TOTAL LIABILITIES", "total liabilities"),
    ],
)
def test_normalize_label(raw, normalized):
    assert normalize_label(raw) == normalized


def test_match_canonical_label_is_exact_not_substring():
    """"Total Assets" and "Total Non-Current Assets" must never be
    conflated — a substring match would be a real bug here."""
    assert match_canonical_label("Total Assets") == "total_assets"
    assert match_canonical_label("Total Non-Current Assets") == "total_non_current_assets"
    assert match_canonical_label("Total Non-Current Assets") != match_canonical_label("Total Assets")


def test_match_canonical_label_unknown_returns_none():
    assert match_canonical_label("Intangible Assets - CWIP") is None
