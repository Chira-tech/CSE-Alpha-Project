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
    check_accounting_identities,
    derive_additional_line_items,
    detect_unit_scale,
    extract_candidate_lines,
    match_canonical_label,
    normalize_label,
    split_label_and_values,
)

# Full real text from page 103 of J.F. Packaging PLC's FY2025/26 annual
# report — expanded from an earlier trimmed version once
# `net_working_capital` needed the individual current-asset/current-
# liability component lines (inventories, receivables, related-party
# amounts, payables) rather than just the totals, and WACC needed to see
# that "Interest Bearing Borrowings" ALSO prints twice on this statement
# (a different real wording from Swadeshi's "Interest Bearing Loans and
# Borrowings", both mapping to `total_interest_bearing_debt`).
BALANCE_SHEET_TEXT = """\
102 J.F. PACKAGING PLC Annual Report 2025/26
STATEMENT OF FINANCIAL POSITION
Group Company
As at 31st March 2026 2025 2026 2025
Notes Rs.000 Rs.000 Rs.000 Rs.000
Assets
Non-Current Assets
Property, Plant & Equipment 11 1,025,218 891,500 694,892 691,557
Right of Use the Asset 12 26,748 45,080 17,917 28,667
Intangible Assets - CWIP 13.2 6,512 3,191 - -
Intangible Assets - Goodwill 13.3 210,662 210,662 - -
Investments in Subsidiaries 14.1 - - 1,424,939 1,424,939
Equity Investments at FVOCI 14.2 318,542 555,636 - -
Deferred Tax Assets 21 37,603 - 24,799 46,619
Total Non-Current Assets 1,625,285 1,706,069 2,162,547 2,191,782
Current Assets
Inventories 15 868,087 814,803 546,299 536,974
Trade and Other Receivables 16 1,126,517 930,751 548,012 428,763
Amounts Due from Related Parties - Trade 24.1.1 97,932 94,265 63,506 70,363
Amounts Due from Related Parties - Non Trade 24.1.2 1,113 47,268 196,764 193,334
Income Tax Receivable 2,109 2,497 2,109 2,497
Investments at Amortised Cost 17 3,232 3,232 - -
Cash and Cash Equivalents 18 82,835 123,842 40,597 29,305
Total Current Assets 2,181,825 2,016,658 1,397,287 1,261,236
Total Assets 3,807,110 3,722,727 3,559,834 3,453,018
EQUITY
Stated Capital 19 1,049,047 449,047 1,049,047 449,047
Revaluation Reserve 205,755 205,755 188,700 188,700
FVOCI Reserve (4,784) 160,738 - -
Retained Earnings 393,013 300,990 1,156,473 1,138,915
Total Equity 1,643,031 1,116,530 2,394,220 1,776,662
Non-Current Liabilities
Interest Bearing Borrowings 20 352,950 641,967 12,451 317,819
Deferred Tax Liabilities 21 - 3,597 - -
Retirement Benefit Obligations 22 82,548 56,795 39,638 27,875
Total Non-Current Liabilities 435,498 702,359 52,089 345,694
LIABILITIES
Current Liabilities
Interest Bearing Borrowings 20 995,069 1,207,155 727,256 970,612
Trade and Other Payables 23 434,334 401,458 190,813 160,264
Amounts Due to Related Parties - Trade 24.2.1 8,740 8,757 2,196 9,077
Amounts Due to Related Parties - Non Trade 24.2.2 3,372 6,193 - 746
Income Tax Payable 34,110 44,480 - -
Bank Overdraft 18 252,956 235,795 193,260 189,963
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

# Real text from page 105 of J.F. Packaging PLC's FY2025/26 annual
# report, downloaded fresh (17 Aug 2026) specifically to verify cash-flow
# extraction — the first real cash-flow-statement page this project has
# ever read (PARAMETERS.md #9's long-tracked gap). Trimmed to the
# canonical-line-bearing rows, PLUS (added when change_in_net_working_
# capital was built) the full real working-capital section between
# "Operating Profit before Working Capital Changes" and "Cash generated
# from Operations" — deliberately kept complete rather than trimmed
# further, so the derivation is tested in the presence of the same noisy,
# individually-uncanonicalised component lines the real statement has,
# not in an artificially clean vacuum. The financing detail lines are
# still trimmed; they aren't mapped to any canonical key either way.
CASH_FLOW_STATEMENT_TEXT = """\
104 J.F. PACKAGING PLC Annual Report 2025/26
STATEMENT OF CASH FLOW
Group Company
For the year ended 31st March 2026 2025 2026 2025
Notes Rs.000 Rs.000 Rs.000 Rs.000
Cash Flows from Operating Activities
Profit before Taxation 8 320,460 303,020 133,643 100,628
Adjustment for;
Depreciation / Amortization 11/13 111,039 90,999 69,986 71,765
Right of Use Asset - Amortisation 12 19,842 19,783 10,750 10,797
Interest Expense 7 199,024 264,108 135,194 206,751
Lease Interest 7 9,019 11,855 7,328 9,320
Unrealized (Gain) on Translation of Foreign Currency (2,556) 4,894 1,040 (238)
Gain on Disposal of Property, Plant & Equipment 6.1 - (1,267) - (1,103)
Interest Income 7 (3,308) (2,840) (5,922) (1,852)
Dividend Income 6.1 - - (101,026) (145,278)
Defined Benefit Plan Cost - Retiring Gratuity 22 14,452 10,872 7,584 5,579
Provision/(Reversal) of Impairment of Trade Debtors 16.1 2,684 (1,266) 4,180 3,533
Trade Receivable Write Off 16.1 - (69,797) - (53,054)
Provision/(Reversal) for Obsolete Inventories 15.1 14,474 15,836 24,135 (1,257)
Inventory Write Off 15.1 (3,752) (2,048) - -
Operating Profit before Working Capital Changes 681,378 644,149 286,892 205,591
(Increase)/Decrease in Inventories (64,006) (90,776) (33,459) (87,091)
(Increase)/Decrease in Trade and Other Receivables (198,061) 55,279 (123,429) 108,757
(Increase)/Decrease in Amounts due from Related Parties 42,489 6,768 3,427 (16,704)
Increase/(Decrease) in Trade and Other Payables 34,535 31,907 28,642 12,631
Increase/(Decrease) in Amounts due to Related Parties (2,838) (999) (7,627) (6,515)
Cash generated from/ (Used in) Operations 493,497 646,328 154,446 216,669
Income Tax Paid (105,484) (153,380) - -
Interest Paid (199,024) (264,108) (135,194) (206,751)
Retiring Gratuity Paid 22 (5,588) (4,761) (4,021) (2,393)
Lease interest paid 20.1.2 (9,019) (11,855) (7,328) (9,320)
Net Cash Flow from/ (used in) Operating Activities 174,382 212,224 7,903 (1,795)
Cash Flows from Investing Activities
Net Cash Flow generated from / (Used in) Investing Activities (244,852) (226,684) 33,545 57,031
Cash Flow from Financing Activities
Net Cash Flow generated from / (Used in) Financing Activities 12,302 (8,713) (33,451) (66,166)
Net Increase/(Decrease) in Cash & Cash Equivalents during the year (58,168) (23,173) 7,997 (10,930)
"""

# Real text from page 30 of Swadeshi Industrial Works PLC's FY2025/26
# annual report, downloaded 17 Aug 2026 specifically to check whether
# J.F. Packaging's cash-flow wording generalised — deliberately a
# different company, a different sector (manufacturing, not packaging),
# with different auditors and formatting. It didn't generalise: every
# line below is worded differently from the JFP equivalent, and this
# statement's capex line — unlike JFP's — does NOT wrap across two
# lines, which is what makes `capital_expenditure` extractable at all.
# Real text from page 26 of Swadeshi Industrial Works PLC's FY2025/26
# annual report, downloaded fresh (17 Aug 2026) specifically because
# `income_tax_expense` was found MISSING when the full multi-year DCF
# was verified end-to-end against this real filing for the first time —
# Swadeshi prints this line as "Income Tax (Expense) / Reversal", not
# J.F. Packaging's plain "Income Tax Expense", carrying the loss-period
# alternative inline in the label itself rather than as a separate line.
# Group/Company columns kept exactly as printed (this extractor reads
# the first, Group/consolidated, column — see `primary_value`), because
# trimming to only the Group column would hide the real ambiguity a
# label-matcher has to resolve on an unmodified real page.
INCOME_STATEMENT_TEXT_SWAD = """\
STATEMENT OF PROFIT OR LOSS
Year Ended 31st March 2026
Group Company
Notes 2026 2025 2026 2025
Rs. Rs. Rs. Rs.
Revenue 6 4,649,049,764 4,473,404,964 4,645,451,221 4,470,354,600
Cost of Sales (2,427,514,294) (2,153,213,142) (2,427,528,873) (2,156,923,193)
Gross Profit 2,221,535,470 2,320,191,822 2,217,922,348 2,313,431,407
Other Operating Income 7 18,912,472 15,706,083 18,902,472 9,645,459
Administrative Expenses (856,728,254) (836,863,985) (855,352,517) (834,164,710)
Selling and Distribution Expenses (1,311,883,837) (1,455,986,817) (1,311,862,794) (1,452,860,738)
Operating Profit 71,835,851 43,047,103 69,609,509 36,051,418
Finance Income 8 1,131,707 2,517,152 1,131,707 2,517,152
Finance Cost 8.1 (48,834,907) (42,281,947) (48,834,907) (42,281,947)
Profit Before Tax 9 24,132,651 3,282,308 21,906,309 (3,713,377)
Income Tax (Expense) / Reversal 10 (22,646,628) 338,664 (21,980,129) 338,664
Profit for the Year 1,486,023 3,620,972 (73,820) (3,374,713)
Earnings Per Share - Basic 11 10.00 24.37 (0.49) (22.60)
"""

CASH_FLOW_STATEMENT_TEXT_SWAD = """\
STATEMENT OF CASH FLOWS
Year Ended 31st March 2026
Group Company
2026 2025 2026 2025
Cash Flows From Operating Activities Notes Rs. Rs. Rs. Rs.
Profit Before Income Tax 24,132,651 3,282,308 21,906,309 (3,713,377)
Depreciation 12 34,338,325 38,227,897 34,338,326 38,227,897
Amortization 13 1,564,379 1,139,229 1,564,379 1,139,229
Bad Debt Provision Reversal/Charged 17 10,218,182 10,656,882 (13,401) 8,177,011
Finance Income 8 (1,131,707) (2,517,152) (1,131,707) (2,517,152)
Finance Costs 8.1 48,834,907 42,281,947 48,834,907 42,281,947
Provision for Retirement Benefit Liability 21.1 18,057,721 14,805,014 18,057,721 14,805,014
Provision for Slow Moving Inventories 16 116,331 4,511,951 116,331 4,511,951
Profit from Disposal of Property, Plant & Equipment (8,298,755) - (8,298,755) -
Operating Profit before Working Capital Changes 127,832,034 112,388,076 116,120,943 103,248,395
(Increase) / Decrease in Inventories (15,638,710) 59,264,037 (15,638,716) 59,264,037
Decrease / (Increase) in Trade and Other Receivables 48,278,354 (122,363,080) 56,443,222 (112,295,153)
Decrease / (Increase) in Advances and Prepayments (145,301,689) 126,136,164 (145,301,689) 126,136,164
Increase / (Decrease) in Trade and Other Payables (139,662,695) (24,599,591) (139,378,767) (25,163,627)
Cash Generated from Operations (124,492,704) 150,825,606 (127,755,005) 151,189,817
Finance Costs Paid 8.1 (48,834,907) (42,281,947) (48,834,907) (42,281,947)
Defined Benefit Plan Costs Paid 21.1 (3,546,400) (1,416,547) (3,546,400) (1,416,547)
Income Tax Paid (12,788,113) (52,940,812) (12,788,112) (52,940,812)
Net Cash from / Used in Operating Activities (189,662,124) 54,186,300 (192,924,424) 54,550,510
Cash Flows from / (Used in) Investing Activities
Acquisition of Property, Plant and Equipment 12 (141,619,562) (78,624,298) (141,619,561) (78,624,298)
Net Cash Flows (Used in) / from Investing Activities (146,776,935) (76,107,146) (146,776,934) (76,107,146)
Cash Flows from / (Used in) Financing Activities
Net Cash Flows from /(Used in) Financing Activities 194,330,142 156,730,560 194,330,142 156,730,560
Net (Decrease) / Increase in Cash and Cash Equivalents (142,108,917) 134,809,715 (145,371,216) 135,173,925
"""

# Real text from page 28 of Swadeshi Industrial Works PLC's FY2025/26
# annual report — downloaded a third time (17 Aug) specifically to look
# for a debt line, since WACC's cost-of-debt weighting needs total
# interest-bearing debt and neither company's cash-flow statement names
# it directly. Found "Interest Bearing Loans and Borrowings" printed
# TWICE, byte-identically — once under Non-current Liabilities, once
# under Current Liabilities, the standard maturity-split presentation —
# which is exactly the case `SUM_ACROSS_OCCURRENCES` exists for.
BALANCE_SHEET_TEXT_SWAD = """\
STATEMENT OF FINANCIAL POSITION
As at 31st March 2026
Group Company
2026 2025 2026 2025
ASSETS Notes Rs. Rs. Rs. Rs.
Non-current Asset
Property, Plant and Equipment 12 2,214,025,283 2,096,679,899 2,050,725,281 1,933,379,899
Right of Use Assets 12 26,815,050 - 26,815,050 -
Intangible Assets 13 15,469,862 2,446,406 15,469,862 2,446,406
Investments in Subsidiaries 14 - - 58,141,639 58,888,472
2,256,310,195 2,099,126,305 2,151,151,832 1,994,714,777
Current Assets
Inventories 16 608,398,860 592,876,477 608,398,860 592,876,477
Trade and Other Receivables 17 645,602,031 704,098,568 626,811,209 683,241,031
Advances and Prepayments 18 243,913,244 98,611,555 243,913,244 98,611,555
Cash and Bank Balances 23 58,066,118 66,727,253 54,293,586 66,217,019
1,555,980,253 1,462,313,853 1,533,416,899 1,440,946,082
Total Assets 3,812,290,448 3,561,440,158 3,684,568,731 3,435,660,859
EQUITY AND LIABILITIES
Equity
Stated Capital 19 150,634,670 150,634,670 150,634,670 150,634,670
Retained Earnings 537,599,349 534,484,630 507,276,576 505,729,335
Revaluation Reserve 20 1,387,693,521 1,361,883,345 1,286,968,337 1,261,158,162
Equity attributable to Equity holders of the parent 2,075,927,540 2,047,002,645 1,944,879,583 1,917,522,167
Non-controlling Interests 13,396,256 13,403,890 - -
Total Equity 2,089,323,796 2,060,406,535 1,944,879,583 1,917,522,167
Non-current Liabilities
Interest Bearing Loans and Borrowings 15 11,672,993 - 11,672,993 -
Deferred Tax Liabilities 10 577,984,927 563,619,591 529,000,188 514,634,854
Retirement Benefit Liability 21 105,453,691 93,578,173 105,453,691 93,578,173
695,111,611 657,197,764 646,126,872 608,213,027
Current Liabilities
Trade and Other Payables 22 377,836,430 517,499,123 446,567,737 585,946,502
Income Tax Payable 15,855,500 8,502,558 12,831,428 6,144,984
Interest Bearing Loans and Borrowings 15 634,163,111 317,834,179 634,163,111 317,834,179
1,027,855,041 843,835,860 1,093,562,276 909,925,665
Total Equity and Liabilities 3,812,290,448 3,561,440,158 3,684,568,731 3,435,660,859
"""

# Real text from page 164 of Asian Hotels and Properties PLC's FY2023/24
# annual report (downloaded 17 Aug from https://cdn.cse.lk/cmt/
# upload_report_file/690_1716340840640.pdf — its most recent currently-
# public annual report), sought out specifically for §22 rule 1's hard-
# book input (revaluation reserves), deliberately from the sector §22
# itself names ("plantations, property and hotels") rather than reusing
# J.F. Packaging/Swadeshi, neither of which is likely to carry a
# material revaluation reserve. AHPL (owns Cinnamon Grand Colombo) prints
# a single COMBINED line, "Other components of equity" — not a pure
# revaluation-reserve figure (its own Note 23 breaks this down into a
# Revaluation Reserve plus a smaller Other Capital Reserve), used as the
# best genuinely available real proxy — see `app.domain.financial_
# statement_parsing.CANONICAL_LABELS`' own comment and `app.domain.
# valuation_view.hard_book_for`'s docstring for the full picture,
# including two other real companies checked: Kelani Valley Plantations
# PLC, which genuinely has NO such line at all (99-year government
# leases, nothing to revalue — real, not a gap), and Galadari Hotels
# (Lanka) PLC, whose real "Revaluation reserve" line is pure but whose
# 2-column filing shape isn't extractable through this pipeline for an
# unrelated, pre-existing reason.
BALANCE_SHEET_TEXT_AHPL = """\
STATEMENT OF FINANCIAL POSITION
GROUP COMPANY
As at 31st March 2024 2023 2024 2023
In Rs.'000s Note
ASSETS
Non current assets
Property, plant and equipment 12 39,773,775 37,685,819 35,187,698 33,620,536
Total non current assets 46,236,276 44,230,736 38,352,277 36,949,791
Current assets
Total current assets 2,145,026 1,680,911 1,213,271 976,209
Total assets 48,381,302 45,911,647 39,565,548 37,926,000
EQUITY & LIABILITIES
Equity
Stated capital 22 3,345,117 3,345,117 3,345,117 3,345,117
Revenue reserves 4,851,535 4,916,727 3,359,649 3,498,432
Other components of equity 23 21,752,125 20,613,338 21,142,080 20,112,228
Equity attributable to equity holders of the parent 29,948,777 28,875,182 27,846,846 26,955,777
Non-controlling interest 3,600,350 3,362,706 - -
Total equity 33,549,127 32,237,888 27,846,846 26,955,777
Total liabilities 14,832,175 13,673,759 11,718,702 10,970,223
Total equity and liabilities 48,381,302 45,911,647 39,565,548 37,926,000
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
    # working-capital STOCK components (net_working_capital's inputs)
    assert by_statement_line["inventories"] == Decimal("868087")
    assert by_statement_line["trade_receivables"] == Decimal("1126517")
    assert by_statement_line["amounts_due_from_related_parties_trade"] == Decimal("97932")
    assert by_statement_line["amounts_due_from_related_parties_non_trade"] == Decimal("1113")
    assert by_statement_line["trade_payables"] == Decimal("434334")
    assert by_statement_line["amounts_due_to_related_parties_trade"] == Decimal("8740")
    assert by_statement_line["amounts_due_to_related_parties_non_trade"] == Decimal("3372")


def test_extract_candidate_lines_finds_both_occurrences_of_jfps_split_debt_line():
    """"Interest Bearing Borrowings" — a real, different wording from
    Swadeshi's "Interest Bearing Loans and Borrowings" — ALSO prints
    twice on J.F. Packaging's real balance sheet, confirming the
    current/non-current maturity split isn't a Swadeshi-specific quirk."""
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT)
    debt_lines = [l for l in lines if l.statement_line == "total_interest_bearing_debt"]
    assert len(debt_lines) == 2
    assert {l.primary_value for l in debt_lines} == {Decimal("352950"), Decimal("995069")}


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


def test_extract_candidate_lines_finds_swadeshis_income_tax_expense_variant_wording():
    """Regression for a real gap found 17 Aug while verifying the full
    multi-year DCF end-to-end against Swadeshi's real filing: every
    other required DCF input extracted correctly, but `income_tax_
    expense` — and therefore `effective_tax_rate`, WACC's cost of debt,
    and the DCF itself — silently came back `None` because the real
    printed label is "Income Tax (Expense) / Reversal", not the plain
    "Income Tax Expense" wording J.F. Packaging's filing uses."""
    lines = extract_candidate_lines(INCOME_STATEMENT_TEXT_SWAD)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["revenue"] == Decimal("4649049764")
    assert by_statement_line["operating_profit"] == Decimal("71835851")
    assert by_statement_line["profit_before_tax"] == Decimal("24132651")
    assert by_statement_line["income_tax_expense"] == Decimal("-22646628")
    assert by_statement_line["net_income"] == Decimal("1486023")
    # profit_before_tax + income_tax_expense = net_income, on the real
    # extracted figures — the same accounting identity
    # check_accounting_identities enforces, checked here directly against
    # the values this specific label variant produced.
    assert (
        by_statement_line["profit_before_tax"] + by_statement_line["income_tax_expense"]
        == by_statement_line["net_income"]
    )


def test_extract_candidate_lines_finds_every_canonical_cash_flow_item():
    lines = extract_candidate_lines(CASH_FLOW_STATEMENT_TEXT)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["cash_flow_from_operations"] == Decimal("174382")
    assert by_statement_line["depreciation_and_amortisation"] == Decimal("111039")
    assert by_statement_line["net_cash_from_investing_activities"] == Decimal("-244852")
    assert by_statement_line["net_cash_from_financing_activities"] == Decimal("12302")
    assert by_statement_line["net_increase_in_cash"] == Decimal("-58168")
    assert by_statement_line["operating_profit_before_working_capital_changes"] == Decimal("681378")
    assert by_statement_line["cash_generated_from_operations"] == Decimal("493497")
    assert by_statement_line["interest_expense"] == Decimal("199024")
    # CFO + investing + financing = net change in cash, on the extracted numbers
    assert (
        by_statement_line["cash_flow_from_operations"]
        + by_statement_line["net_cash_from_investing_activities"]
        + by_statement_line["net_cash_from_financing_activities"]
        == by_statement_line["net_increase_in_cash"]
    )


def test_extract_candidate_lines_finds_every_canonical_item_on_a_second_independent_filing():
    """Swadeshi Industrial Works PLC — a different company, different
    wording throughout, verified independently of J.F. Packaging PLC.
    Existing purely to check the first filing's wording didn't
    accidentally generalise (it didn't — every line here is a distinct
    canonical variant from JFP's), and to confirm `capital_expenditure`
    extracts correctly where the label doesn't wrap."""
    lines = extract_candidate_lines(CASH_FLOW_STATEMENT_TEXT_SWAD)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["cash_flow_from_operations"] == Decimal("-189662124")
    assert by_statement_line["capital_expenditure"] == Decimal("-141619562")
    assert by_statement_line["net_cash_from_investing_activities"] == Decimal("-146776935")
    assert by_statement_line["net_cash_from_financing_activities"] == Decimal("194330142")
    assert by_statement_line["net_increase_in_cash"] == Decimal("-142108917")
    assert by_statement_line["depreciation_expense"] == Decimal("34338325")
    assert by_statement_line["amortisation_expense"] == Decimal("1564379")
    assert by_statement_line["operating_profit_before_working_capital_changes"] == Decimal("127832034")
    assert by_statement_line["cash_generated_from_operations"] == Decimal("-124492704")
    assert by_statement_line["interest_expense"] == Decimal("48834907")
    # the combined line itself was never printed on this statement
    assert "depreciation_and_amortisation" not in by_statement_line


def test_extract_candidate_lines_finds_both_occurrences_of_a_split_maturity_debt_line():
    """`extract_candidate_lines` itself doesn't dedupe or sum — that's
    `build_fundamental_drafts`'s job (see test_financial_pdf_extractor.py)
    — this only confirms BOTH real occurrences of "Interest Bearing Loans
    and Borrowings" are found as separate candidates, byte-identical
    label, different real values."""
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT_SWAD)
    debt_lines = [l for l in lines if l.statement_line == "total_interest_bearing_debt"]
    assert len(debt_lines) == 2
    assert {l.primary_value for l in debt_lines} == {Decimal("11672993"), Decimal("634163111")}

    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}
    assert by_statement_line["inventories"] == Decimal("608398860")
    assert by_statement_line["trade_receivables"] == Decimal("645602031")
    assert by_statement_line["advances_and_prepayments"] == Decimal("243913244")
    assert by_statement_line["trade_payables"] == Decimal("377836430")


def test_extract_candidate_lines_finds_ahpls_combined_revaluation_reserve_proxy():
    """§22 rule 1's hard-book input, verified against a real filing in
    the sector §22 itself names ("plantations, property and hotels")
    rather than reused from J.F. Packaging/Swadeshi. Confirms the single
    occurrence extracted is the correct one (page 164's real value,
    21,752,125 — Group, 2024) — not a notes-page duplicate — and that
    every other canonical line on the same real page still extracts
    correctly alongside it."""
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT_AHPL)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["revaluation_reserves"] == Decimal("21752125")
    assert by_statement_line["total_equity"] == Decimal("33549127")
    assert by_statement_line["total_assets"] == Decimal("48381302")
    assert by_statement_line["total_liabilities"] == Decimal("14832175")
    assert by_statement_line["total_equity_and_liabilities"] == Decimal("48381302")


class TestDeriveAdditionalLineItems:
    def test_sums_split_depreciation_and_amortisation(self):
        """Swadeshi's real figures: 34,338,325 + 1,564,379 = 35,902,704."""
        derived = derive_additional_line_items(
            {"depreciation_expense": Decimal("34338325"), "amortisation_expense": Decimal("1564379")}
        )
        assert derived == {"depreciation_and_amortisation": Decimal("35902704")}

    def test_never_overwrites_an_already_extracted_combined_line(self):
        """J.F. Packaging's shape: the combined line IS present, and must
        win over any (here, absent) component sum rather than being
        silently replaced."""
        derived = derive_additional_line_items({"depreciation_and_amortisation": Decimal("111039")})
        assert derived == {}

    def test_does_not_produce_a_partial_sum(self):
        """Only depreciation known, amortisation missing — a partial sum
        would understate the real combined figure while looking exactly
        as precise as a genuine one."""
        derived = derive_additional_line_items({"depreciation_expense": Decimal("34338325")})
        assert derived == {}

    def test_empty_input_derives_nothing(self):
        assert derive_additional_line_items({}) == {}

    def test_derives_change_in_net_working_capital_from_the_two_bookend_subtotals(self):
        """J.F. Packaging's real figures: 681,378 - 493,497 = 187,881 —
        independently matches the hand-summed total of all 5 real
        working-capital component lines on that statement (inventories,
        receivables, payables, amounts due from/to related parties), a
        cross-check performed when this derivation was designed, not
        re-asserted here since the two subtotals already encode it."""
        derived = derive_additional_line_items(
            {
                "operating_profit_before_working_capital_changes": Decimal("681378"),
                "cash_generated_from_operations": Decimal("493497"),
            }
        )
        assert derived == {"change_in_net_working_capital": Decimal("187881")}

    def test_working_capital_derivation_handles_a_negative_subtotal(self):
        """Swadeshi's real figures: cash_generated_from_operations is
        itself negative (-124,492,704) — the subtraction must still give
        the correct sign, not accidentally cancel or double-negate."""
        derived = derive_additional_line_items(
            {
                "operating_profit_before_working_capital_changes": Decimal("127832034"),
                "cash_generated_from_operations": Decimal("-124492704"),
            }
        )
        assert derived["change_in_net_working_capital"] == Decimal("252324738")

    def test_working_capital_derivation_never_overwrites_a_directly_extracted_value(self):
        derived = derive_additional_line_items(
            {
                "change_in_net_working_capital": Decimal("999"),
                "operating_profit_before_working_capital_changes": Decimal("681378"),
                "cash_generated_from_operations": Decimal("493497"),
            }
        )
        assert "change_in_net_working_capital" not in derived

    def test_both_derived_concepts_can_apply_at_once(self):
        """Swadeshi's real shape: both split D&A and the two WC subtotals
        are present on the same filing — both derivations should fire
        together, independently."""
        derived = derive_additional_line_items(
            {
                "depreciation_expense": Decimal("34338325"),
                "amortisation_expense": Decimal("1564379"),
                "operating_profit_before_working_capital_changes": Decimal("127832034"),
                "cash_generated_from_operations": Decimal("-124492704"),
            }
        )
        assert derived == {
            "depreciation_and_amortisation": Decimal("35902704"),
            "change_in_net_working_capital": Decimal("252324738"),
        }

    def test_derives_net_working_capital_from_jfp_shaped_components(self):
        """J.F. Packaging's real component set: inventories, trade
        receivables, related-party amounts (trade + non-trade) on the
        asset side; trade payables and related-party amounts on the
        liability side. 2,093,649 - 446,446 = 1,647,203."""
        derived = derive_additional_line_items(
            {
                "inventories": Decimal("868087"),
                "trade_receivables": Decimal("1126517"),
                "amounts_due_from_related_parties_trade": Decimal("97932"),
                "amounts_due_from_related_parties_non_trade": Decimal("1113"),
                "trade_payables": Decimal("434334"),
                "amounts_due_to_related_parties_trade": Decimal("8740"),
                "amounts_due_to_related_parties_non_trade": Decimal("3372"),
            }
        )
        assert derived == {"net_working_capital": Decimal("1647203")}

    def test_derives_net_working_capital_from_swad_shaped_components(self):
        """Swadeshi's real, genuinely different component set: no
        related-party amounts at all, "Advances and Prepayments" instead
        — confirms this isn't hardcoded to J.F. Packaging's specific
        five-component shape. 1,497,914,135 - 377,836,430 = 1,120,077,705."""
        derived = derive_additional_line_items(
            {
                "inventories": Decimal("608398860"),
                "trade_receivables": Decimal("645602031"),
                "advances_and_prepayments": Decimal("243913244"),
                "trade_payables": Decimal("377836430"),
            }
        )
        assert derived == {"net_working_capital": Decimal("1120077705")}

    def test_net_working_capital_needs_at_least_one_of_each_side(self):
        """All-assets-no-liabilities would look like a real net figure
        while actually being gross assets alone — must not derive."""
        derived = derive_additional_line_items({"inventories": Decimal("1000")})
        assert "net_working_capital" not in derived

    def test_net_working_capital_never_overwrites_a_directly_extracted_value(self):
        derived = derive_additional_line_items(
            {
                "net_working_capital": Decimal("999"),
                "inventories": Decimal("1000"),
                "trade_payables": Decimal("400"),
            }
        )
        assert "net_working_capital" not in derived


def test_identities_pass_on_the_second_independent_cash_flow_filing():
    """The CFO + investing + financing identity, re-verified on a
    completely independent real filing — not just re-checking the same
    JFP numbers a second way."""
    checks = check_accounting_identities(_values(CASH_FLOW_STATEMENT_TEXT_SWAD))
    identity = next(c for c in checks if c.name == "CFO + investing + financing = net change in cash")
    assert identity.passed


def test_dual_note_reference_with_slash_is_dropped():
    """"11/13" (PPE note 11 + intangibles note 13, a real formatting
    quirk on the cash-flow statement's D&A line) must be dropped the same
    way a dot-separated note reference already is — not mistaken for a
    value, and not left stuck to the label."""
    result = split_label_and_values("Depreciation / Amortization 11/13 111,039 90,999 69,986 71,765")
    assert result is not None
    assert result.raw_label == "Depreciation / Amortization"
    assert result.values == (Decimal("111039"), Decimal("90999"), Decimal("69986"), Decimal("71765"))


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


# --- regression: the split-thousands corruption -------------------------
#
# Real lines from J.F. Packaging PLC's June 2026 INTERIM statements, where
# pdfplumber emitted a space between the leading digit and the first comma
# group ("4 ,453,103"). The same company's annual report renders cleanly,
# so this only surfaced on live data.
#
# Left unhandled the line still tokenised: the stray "4" looked exactly
# like a note reference, the note-reference rule dropped it, and Total
# Assets was recorded as 453,103 instead of 4,453,103 — wrong by four
# billion rupees, and entirely plausible on screen.

SPLIT_THOUSANDS_LINES = {
    "Total Assets 4 ,453,103 3,807,110 3,853,375 3,559,834": ("total_assets", Decimal("4453103")),
    "Total Current Assets 2 ,822,064 2,181,824 1,720,129 1,397,287": (
        "total_current_assets",
        Decimal("2822064"),
    ),
    "Total Current Liabilities 2 ,048,107 1,728,581 1,143,600 1,113,525": (
        "total_current_liabilities",
        Decimal("2048107"),
    ),
    "Total Equity 1 ,785,912 1,643,031 2,487,901 2,394,220": ("total_equity", Decimal("1785912")),
    "Total Liabilities 2 ,667,191 2,164,079 1,365,474 1,165,614": (
        "total_liabilities",
        Decimal("2667191"),
    ),
}


@pytest.mark.parametrize(("line", "expected"), SPLIT_THOUSANDS_LINES.items())
def test_split_thousands_group_is_rejoined_not_truncated(line, expected):
    key, value = expected
    result = split_label_and_values(line)
    assert result is not None
    assert result.statement_line == key
    assert result.primary_value == value


def test_the_specific_regression_four_billion_not_four_hundred_million():
    """Named explicitly because the failure mode is a plausible number,
    not a crash — the kind of bug that survives review."""
    result = split_label_and_values("Total Assets 4 ,453,103 3,807,110 3,853,375 3,559,834")
    assert result.primary_value == Decimal("4453103")
    assert result.primary_value != Decimal("453103")


def test_a_comma_leading_fragment_is_not_a_valid_number():
    """The root permissiveness: the old value pattern accepted
    ",453,103" as a number. Nothing should parse a bare fragment."""
    result = split_label_and_values("Some Label ,453,103")
    assert result is None or result.primary_value != Decimal("453103")


# --- accounting identities ----------------------------------------------


def _values(text: str) -> dict[str, Decimal]:
    return {
        line.statement_line: line.primary_value
        for line in extract_candidate_lines(text)
        if line.statement_line and line.primary_value is not None
    }


def test_identities_pass_on_a_correctly_extracted_balance_sheet():
    checks = check_accounting_identities(_values(BALANCE_SHEET_TEXT))
    assert checks, "expected at least one identity to be checkable"
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_identities_pass_on_a_correctly_extracted_income_statement():
    checks = check_accounting_identities(_values(INCOME_STATEMENT_TEXT))
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_identities_pass_on_a_correctly_extracted_cash_flow_statement():
    checks = check_accounting_identities(_values(CASH_FLOW_STATEMENT_TEXT))
    assert checks, "expected the CFO + investing + financing identity to be checkable"
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_identities_catch_the_split_thousands_corruption_independently():
    """The safety net: even if the regex fix were reverted, an identity
    check on the corrupted figures fails, because the two sides of the
    balance sheet get mangled by different amounts."""
    corrupted = {
        "total_assets": Decimal("453103"),  # what the bug produced
        "total_equity": Decimal("785912"),
        "total_liabilities": Decimal("667191"),
    }
    checks = check_accounting_identities(corrupted)
    identity = next(c for c in checks if c.name == "assets = equity + liabilities")
    assert not identity.passed
    assert "differs by" in identity.detail


def test_identities_skip_what_cannot_be_checked_rather_than_failing():
    checks = check_accounting_identities({"total_assets": Decimal("100")})
    assert checks == []


class TestDetectUnitScale:
    """A REAL bug, found live (18 Aug 2026): every value this module ever
    extracted was stored exactly as printed, with no unit-scale
    conversion — off by 1000x on any "Rs.'000"-declared statement,
    confirmed against COMB.N0000's real 30.06.2026 interim filing (its
    own balance-sheet page literally reads "Rs.'000 Rs.'000 % Rs.'000
    Rs.'000"). See `detect_unit_scale`'s own module-level comment for the
    full finding. Every case below is a REAL, independently-verified
    filing's own real header text, not an invented example — three
    distinct real thousands-wordings and one real full-value wording,
    covering the actual variety already known to exist across CSE
    filings before assuming a single pattern generalises."""

    def test_jfps_real_rs_000_header_is_a_thousands_scale(self):
        assert detect_unit_scale(BALANCE_SHEET_TEXT) == Decimal(1000)

    def test_ahpls_real_in_rs_000s_header_is_a_thousands_scale(self):
        assert detect_unit_scale(BALANCE_SHEET_TEXT_AHPL) == Decimal(1000)

    def test_combs_real_rs_apostrophe_000_header_is_a_thousands_scale(self):
        """Verified 18 Aug 2026 by downloading COMB.N0000's real
        30.06.2026 interim PDF directly and reading page 8's own column
        header text."""
        comb_header = (
            "STATEMENT OF FINANCIAL POSITION\n"
            "Group Bank\n"
            "As at 30.06.2026 31.12.2025 Change 30.06.2026 31.12.2025 Change\n"
            "(Audited) (Audited) (Audited)\n"
            "Rs.'000 Rs.'000 % Rs.'000 Rs.'000\n"
        )
        assert detect_unit_scale(comb_header) == Decimal(1000)

    def test_swadeshis_real_rs_header_is_a_full_value_scale(self):
        """Swadeshi Industrial Works PLC's real statements are genuinely
        NOT in thousands — Revenue of 4,649,049,764 is a real ~4.6bn LKR
        figure; interpreted as thousands it would be an impossible 4.6
        trillion. A blanket "always 1000" fix would have been wrong for
        this real, already-verified filing."""
        assert detect_unit_scale(BALANCE_SHEET_TEXT_SWAD) == Decimal(1)
        assert detect_unit_scale(INCOME_STATEMENT_TEXT_SWAD) == Decimal(1)

    def test_no_recognisable_unit_declaration_refuses_rather_than_guesses(self):
        assert detect_unit_scale("Total Assets 3,807,110 3,722,727 3,559,834 3,453,018") is None

    def test_a_lone_incidental_rs_does_not_falsely_signal_full_value(self):
        """A single "Rs." mentioned once in body text (e.g. a threshold
        in a note) must not be mistaken for a genuine repeated per-column
        header declaration — `_UNIT_FULL_VALUE_RE` requires at least two
        consecutive occurrences, matching every real full-value header
        actually seen (always one "Rs." per comparative column, at least
        two columns)."""
        assert detect_unit_scale("Amounts below Rs. 500,000 are immaterial.") is None
