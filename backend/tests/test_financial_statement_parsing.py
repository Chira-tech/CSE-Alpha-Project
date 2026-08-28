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
    _count_year_tokens,
    check_accounting_identities,
    check_extraction_quality,
    check_magnitude_plausibility,
    derive_additional_line_items,
    detect_expected_value_columns,
    detect_unit_scale,
    extract_candidate_lines,
    match_canonical_label,
    normalize_label,
    reconcile_ambiguous_values_via_identities,
    reconcile_magnitude_implausible_values,
    repair_character_doubling,
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

# The FULL, real, RAW (un-repaired) text of page 4 of Nations Trust Bank
# PLC's (NTB.N0000) real interim statement for the six months ended 30
# June 2026, downloaded fresh (18 Aug 2026) from
# https://cdn.cse.lk/cmt/upload_report_file/387_1786611868010.pdf via
# `app.ingestion.financial_reports_archive_loader.fetch_report_archive`.
# Captured directly from `pdfplumber`'s own `page.extract_text()` output —
# NOT hand-edited — to preserve the real character-doubling artifact this
# fixture exists to test: bold-rendered rows (the title, and every
# subtotal row — Total Assets, Total Liabilities, Total Shareholders'
# Equity, Total Equity and Liabilities, Contingent Liabilities and
# Commitments) come out with every character glyph doubled, while
# ordinary (non-bold) body rows on the SAME page — e.g. "Cash and Cash
# Equivalents" two lines below the doubled title — are completely
# unaffected. See `repair_character_doubling`'s own docstring in
# app.domain.financial_statement_parsing for the full finding; this
# fixture is what proved it, and what its regression test is built on.
BALANCE_SHEET_TEXT_NTB_DOUBLED = """\
NNAATTIIOONNSS TTRRUUSSTT BBAANNKK PPLLCC
SSTTAATTEEMMEENNTT OOFF FFIINNAANNCCIIAALL PPOOSSIITTIIOONN
BBaannkk GGrroouupp
AAss aatt 3300..0066..22002266 3311..1122..22002255 CChhaannggee 3300..0066..22002266 3311..1122..22002255 CChhaannggee
LLKKRR ''000000 LLKKRR ''000000 ((%%)) LLKKRR ''000000 LLKKRR ''000000 ((%%))
((AAuuddiitteedd)) ((AAuuddiitteedd))
AASSSSEETTSS
Cash and Cash Equivalents 37,873,231 19,864,631 91 37,873,234 19,864,477 9 1
Balances with Central Bank of Sri Lanka 7,156,843 2,045,786 250 7,156,843 2,045,786 2 50
Placements with banks 2,052,451 1,437,818 4 3 2,052,451 1,437,818 4 3
Reverse Repurchase Agreements 4,831,577 645,794 648 4,831,577 645,794 6 48
Derivative Financial Instruments 5,793,695 613,468 844 5,793,695 613,468 8 44
Financial Assets Recognised through Profit or Loss - Measured at Fair Value 2,472,028 11,589,905 ( 79) 2,472,028 11,589,905 ( 79)
Financial Assets Recognised through Profit or Loss - Designated at Fair Value - - - - - -
Financial Assets at Fair Value through Other Comprehensive Income 168,457,067 133,112,729 27 168,457,067 133,112,729 2 7
Financial Assets at Amortised Cost - Debt Instruments 109,836,207 88,897,718 2 4 109,836,207 88,897,718 2 4
Financial Assets at Amortised Cost - Loans and Advances 541,891,956 430,368,007 2 6 541,891,956 430,368,007 2 6
Current Tax Asset 104,609 - 100 36,927 - 1 00
Other Assets 5,730,461 2,412,826 137 5,801,929 2,444,550 1 37
Investments in Subsidiaries 678,710 678,710 - - - -
Investments in associates and joint ventures - - - - - -
Property, Plant & Equipment 5,798,856 4,026,924 44 6,873,131 5,110,266 3 4
Investment properties - - - - - -
Right of Use (ROU) Assets 2,163,614 1,970,691 1 0 1,840,919 1,540,432 2 0
Intangible Assets 2,296,075 1,782,628 29 2,296,342 1,782,965 2 9
Provisional Goodwill 22,190,416 - 1 22,190,416 - 1
Deferred Tax Assets 3,847,363 1,127,396 2 41 3,575,756 854,968 3 18
TToottaall AAsssseettss 992233,,117755,,115599 770000,,557755,,003311 33 22 992222,,998800,,447788 770000,,330088,,888833 33 22
LLIIAABBIILLIITTIIEESS
Due to Banks 29,765,443 42,772,586 ( 30) 29,765,443 42,772,586 ( 30)
Derivative Financial Instruments 888,282 37,822 2 ,249 888,282 37,822 2 ,249
Financial Liabilities Recognised through Profit or Loss - Measured at Fair Value - - - - - -
Financial Liabilities Recognised through Profit or Loss - Designated at Fair Value - - - - - -
Financial Liabilities at Amortised Cost
Due to Depositors 688,914,454 502,605,592 3 7 687,953,741 502,219,078 3 7
Due to debt securities holders - Repurchase Agreements 32,744,826 23,479,164 3 9 32,376,296 20,909,241 5 5
Due to Other Borrowers 27,878,020 10,005,840 1 79 27,528,640 9,552,599 1 88
Debt Securities Issued 21,231,250 5,973,778 2 55 21,231,250 5,973,778 2 55
Retirement Benefit Obligations 1,808,769 1,659,228 9 1,819,346 1,668,811 9
Current Tax Liabilities - 5,568,268 ( 100) - 5,632,064 ( 100)
Due to subsidiaries - - - - - -
Other Liabilities 16,015,436 14,580,677 1 0 16,387,594 14,627,281 1 2
TToottaall LLiiaabbiilliittiieess 881199,,224466,,448800 660066,,668822,,995555 33 55 881177,,995500,,559922 660033,,339933,,226600 33 66
EEQQUUIITTYY
Stated Capital 13,990,603 13,007,641 8 13,990,603 13,007,641 8
Statutory Reserve Fund 4,554,407 4,554,407 - 4,554,407 4,554,407 -
Retained Earnings 84,531,740 69,679,491 2 1 84,999,699 72,069,790 1 8
OCI Reserve (262,992) 5,535,616 ( 105) (262,992) 5,535,616 ( 105)
Revaluation Reserve 1,114,921 1,114,921 - 1,748,169 1,748,169 -
TToottaall SShhaarreehhoollddeerrss'' EEqquuiittyy 110033,,992288,,667799 9933,,889922,,007766 11 11 110055,,002299,,888866 9966,,991155,,662233 88
NNoonn--ccoonnttrroolllliinngg iinntteerreessttss -- -- -- -- -- --
TToottaall EEqquuiittyy aanndd LLiiaabbiilliittiieess 992233,,117755,,115599 770000,,557755,,003311 33 22 992222,,998800,,447788 770000,,330088,,888833 33 22
CCoonnttiinnggeenntt LLiiaabbiilliittiieess aanndd CCoommmmiittmmeennttss 665599,,002233,,551155 448866,,664466,,991144 33 55 665599,,002233,,551155 448866,,664466,,991144 33 55
MMeemmoorraanndduumm IInnffoorrmmaattiioonn
Number of Employees 2 ,752 2 ,444 2 ,771 2 ,462
Number of Branches 9 6 9 0 9 6 9 0
Number of Off-Site ATMs and CRMs 1 5 2 4 1 5 2 4
Note: Amounts stated are net of impairment and depreciation.
CCEERRTTIIFFIICCAATTIIOONN ::
I certify that these financial statements comply with the requirements of the Companies Act No. 07 of 2007.
Sgd
Kushlani Allis
Chief Financial Officer
We, the undersigned being the Chairperson, Director and Executive Director/Chief Executive Officer of Nations Trust Bank PLC certify jointly that:
(a) the above financial statements have been prepared in compliance with the format and definitions prescribed by the Central Bank of Sri Lanka;
(b) the information contained in these financial statements has been extracted from the unaudited financial statements of the Bank and the Group, unless indicated as audited.
Sgd Sgd Sgd
Sherin Cader Coralie Pietersz Hemantha D Gunetilleke
Chairperson Director Executive Director/Chief Executive Officer
12 August 2026
Colombo
"""


# Real text from page 1 (the actual Statement of Financial Position) of
# Panasian Power PLC's (PAP.N0000) real interim statement for the quarter
# ended 30 June 2026, downloaded fresh (18 Aug 2026) from
# https://cdn.cse.lk/cmt/upload_report_file/1040_1786442603758.pdf.
# Sought out specifically because both of PAP.N0000's two most recent
# quarterly filings produced 0 drafts. Two real, independent gaps found
# on this one page: its own real unit declaration is a bare, repeated
# "LKR LKR LKR LKR" — no "'000" suffix — which `detect_unit_scale`
# refused before this fix (neither the thousands pattern, which needs a
# "'000" suffix, nor the full-value pattern, which only recognised a
# repeated "Rs.", matched a bare repeated "LKR"); and every one of PAP's
# own printed values already carries the exact same split-thousands
# space artifact ("6 ,861,409,400" instead of "6,861,409,400") already
# fixed for J.F. Packaging PLC's own real interim statement, kept exactly
# as printed rather than cleaned up, since `_repair_split_thousands`
# needs to prove it still fires correctly here too.
BALANCE_SHEET_TEXT_PAP = """\
PANASIAN POWER PLC
INTERIM CONDENSED FINANCIAL STATEMENTS - QUARTER ENDED 30 JUNE 2026
PROVISIONAL FINANCIAL STATEMENTS
STATEMENT OF FINANCIAL POSITION
Group Company
As at 30 June 2026 As at 31 March 2026 As at 30 June 2026 As at 31 March 2026
ASSETS
Unaudited Audited Unaudited Audited
LKR LKR LKR LKR
Non - Current Assets
Property, plant and equipment 6 ,861,409,400 6 ,927,768,540 1 03,140,713 1 04,896,835
Capital work in progress 9 9,646,295 8 3,059,907 2 4,059,332 2 2,884,896
Right of use assets 7 9,440,582 8 3,263,928 2 5,310,665 2 8,461,457
Intangible assets 6 8,354,680 6 9,279,487 2 ,160,711 1 ,720,879
Investment in subsidiaries - - 1 ,427,377,715 1 ,427,377,715
Investment in preference shares - - 2 3,000,000 2 3,000,000
Investment in equity accounted investees 1 4,921,727 1 4,586,054 - -
Deferred tax assets 1 ,044,130,868 1 ,124,818,417 - -
8 ,167,903,552 8 ,302,776,333 1 ,605,049,136 1 ,608,341,782
Current Assets
Inventories 3 17,353,093 1 39,446,076 1 ,472,811 1 ,267,145
Trade and other receivables 8 76,481,667 8 23,614,765 6 1,039,874 4 4,952,748
Amount due from related parties 7 48,127 6 46,280 8 7,689,462 5 7,791,461
Income tax receivables 6 ,449,177 6 ,449,177 - -
Financial assets at fair value through profit or loss 1 ,604,640 1 68,380,097 3 80,546 3 0,320,958
Other financial asset 7 3,905,706 5 7,755,715 - -
Cash and cash equivalents 3 84,286,322 1 62,105,530 2 8,609,139 4 3,033,783
1 ,660,828,732 1 ,358,397,640 1 79,191,832 1 77,366,095
TOTAL ASSETS 9,828,732,284 9 ,661,173,973 1,784,240,968 1 ,785,707,877
EQUITY AND LIABILITIES
Equity
Stated capital 1 ,030,000,000 1 ,030,000,000 1 ,030,000,000 1 ,030,000,000
Retained earnings 1 ,224,148,208 1 ,136,974,494 4 68,932,838 4 75,303,102
Equity attributable to equity holders of the company 2 ,254,148,208 2 ,166,974,494 1 ,498,932,838 1 ,505,303,102
Non controlling interest 8 73,126,859 8 08,673,078 - -
Total Equity 3 ,127,275,067 2 ,975,647,572 1 ,498,932,838 1 ,505,303,102
Non-Current Liabilities
Retirement benefit obligations 2 1,142,435 1 9,987,008 1 7,275,324 1 6,425,654
Lease liabilities 7 5,654,323 7 8,685,138 1 7,495,039 2 2,194,299
Interest bearing loans and borrowings 4 ,570,259,968 4 ,819,421,657 - -
Deferred tax liabilities 2 14,939,207 2 24,593,816 5 ,819,692 9 ,430,067
4 ,881,995,933 5 ,142,687,619 4 0,590,055 4 8,050,020
Current Liabilities
Lease liabilities 1 7,548,820 1 6,691,578 1 7,500,049 1 6,644,189
Interest bearing loans and borrowings 1 ,235,775,952 1 ,119,926,170 2 2,813,897 3 4,221,746
Amount due to related parties - - 1 01,822,989 1 23,098,554
Trade and other payables 3 97,237,417 2 47,249,393 3 4,838,726 4 8,316,358
Provisions 1 6,859,908 5 7,554,334 - -
Income tax payable 8 6,949,035 8 9,992,525 9 ,600,253 8 ,228,788
Bank overdraft 6 5,090,152 1 1,424,782 5 8,142,161 1 ,845,120
1 ,819,461,284 1 ,542,838,782 2 44,718,075 2 32,354,755
Total Liabilities 6 ,701,457,217 6 ,685,526,401 2 85,308,130 2 80,404,775
TOTAL EQUITY AND LIABILITIES 9,828,732,284 9 ,661,173,973 1,784,240,968 1 ,785,707,877
Net asset per share 3 .61 3 .47 2 .40 2 .41
(1) 0 0 0
These financial statements are in compliance with the requirements of the Companies Act. No 7 of 2007.
Ms. Lakmali Egodawaththa
Finance Manager
The Board of Directors is responsible for the preparation and presentation of these Financial Statements.
Signed for and on behalf of the Board by,
Mr.L.Silva Mr. P. Poddiwala
Chairman CEO / Executive Director
11-Aug-2026
"""


# Real text from page 1 of Lanka Walltiles PLC's (LWL.N0000) real interim
# statement for the period ended 30 June 2026, downloaded fresh (18 Aug
# 2026) from https://cdn.cse.lk/cmt/upload_report_file/678_1786015830338
# .pdf. Sought out specifically because this real filing's own extraction
# failed check_accounting_identities's "assets = current + non-current"
# check live: "62,364,259,000 vs 61,998,177,000", a 366,082,000 gap.
# NOT an extraction bug — LWL's own real balance sheet has a genuine
# THIRD bucket, "Assets held for sale 366,082 277,606 - -" (IFRS 5,
# printed between "Total current assets" and "Total assets", with a
# matching "Reserves of a disposal group held for sale" equity line
# confirming a real disposal group), that this system didn't extract at
# all before this fix. See `assets_held_for_sale`'s own comment in
# CANONICAL_LABELS for the full finding.
BALANCE_SHEET_TEXT_LWL = """\
STATEMENT OF FINANCIAL POSITION
As at 30th June 2026
GROUP COMPANY
As at 30.06.2026 As at 31.03.2026 As at 30.06.2026 As at 31.03.2026
Unaudited Audited Unaudited Audited
Rs.000 Rs.000 Rs.000 Rs.000
ASSETS
Non-current assets
Property, plant and equipment 28,495,679 28,544,668 12,512,000 12,673,190
Investment properties 830,874 830,874 - -
Intangible assets 225,848 230,318 26,906 27,485
Investments in subsidiaries - - 1,696,035 1,696,035
Investments in associates 202,378 202,352 - -
Right of use assets 332,297 138,657 8,011 8,141
Deferred tax asset 180,787 159,355 - -
Total non-current assets 30,267,863 30,106,224 14,242,952 14,404,851
Current assets
Inventories 21,611,776 20,430,499 6,926,947 6,084,766
Trade and Other Receivables 8,543,630 8,444,292 1,015,343 844,489
Amounts Due from Related Parties 16,449 65,092 91,810 90,074
Short Term Investment 4,796 4,726 4,796 4,726
Cash and balances with banks 1,553,663 2,067,478 91,827 79,798
Total current assets 31,730,314 31,012,087 8,130,723 7,103,853
Assets held for sale 366,082 277,606 - -
Total assets 62,364,259 61,395,917 22,373,675 21,508,704
EQUITY AND LIABILITIES
Stated Capital 787,765 787,765 787,765 787,765
Reserves 5,073,440 5,073,440 2,506,339 2,506,339
Reserves of a disposal group held for sale (7,401) (5,609) - -
Retained earnings 16,774,267 16,464,489 4,340,985 4,304,736
Total equity attributable to equity holders of the company 22,628,071 22,320,085 7,635,089 7,598,840
Non- controlling interest 7,591,380 7,430,056 - -
Total equity 30,219,451 29,750,141 7,635,089 7,598,840
Non-current liabilities
Interest bearing liabilities 4,382,220 4,661,957 2,249,029 2,472,199
Deferred tax liabilities 3,112,137 3,119,596 734,086 754,526
Retirement benefit liability 903,782 884,067 310,092 301,935
Total Non-current liabilities 8,398,139 8,665,620 3,293,207 3,528,660
Current liabilities
Trade and other payables 5,508,959 6,383,922 1,235,397 968,147
Contract liability 172,449 267,202 71,189 102,410
Income tax liabilities 430,156 357,615 560 560
Amounts due to related parties 437,418 438,464 3,572,383 3,086,060
Interest bearing liabilities 16,784,737 15,217,192 6,565,849 6,224,027
Total Current liabilities 23,333,719 22,664,394 11,445,378 10,381,204
Liabilities associated with assets held for sale 412,950 315,762 - -
Total equity and liabilities 62,364,259 61,395,917 22,373,674 21,508,704
Net Assets Value Per Share (Rs.) 83 82 28 28
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


def test_extract_candidate_lines_finds_every_canonical_item_on_paps_real_balance_sheet():
    """Panasian Power PLC's real balance sheet, split-thousands artifact
    and all ("6 ,861,409,400" etc, exactly as pdfplumber printed it) —
    `_repair_split_thousands` must still recover every real figure
    correctly on this genuinely different real filing, not just J.F.
    Packaging's."""
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT_PAP)
    by_statement_line = {l.statement_line: l.primary_value for l in lines if l.statement_line}

    assert by_statement_line["total_assets"] == Decimal("9828732284")
    assert by_statement_line["total_equity"] == Decimal("3127275067")
    assert by_statement_line["total_liabilities"] == Decimal("6701457217")
    assert by_statement_line["total_equity_and_liabilities"] == Decimal("9828732284")
    assert by_statement_line["total_assets"] == by_statement_line["total_equity_and_liabilities"]
    # NOTE: "inventories" is deliberately NOT asserted here — see
    # `_repair_split_leading_digits`'s own docstring for why this one
    # specific real row (a MIXED pattern: only 2 of its 4 columns are
    # actually split) falls outside that repair's deliberately narrow,
    # safe scope, and is a real, documented, unfixed-for-now limitation
    # rather than a silently-wrong assertion here.
    assert by_statement_line["trade_receivables"] == Decimal("876481667")
    assert by_statement_line["trade_payables"] == Decimal("397237417")
    # "Interest bearing loans and borrowings" prints twice — once under
    # Non-current Liabilities, once under Current — the same real
    # maturity-split presentation already verified on Swadeshi and J.F.
    # Packaging's own filings.
    debt_lines = [l.primary_value for l in lines if l.statement_line == "total_interest_bearing_debt"]
    assert sorted(debt_lines) == [Decimal("1235775952"), Decimal("4570259968")]


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


def test_a_variance_pct_column_is_dropped_not_folded_into_the_label():
    """Real regression, found live: Hikkaduwa Beach Resort PLC's interim
    statement for the quarter ended 30 June 2026 prints a "Change %"
    column between real value columns — "Revenue from contracts with
    customers 163,267,528 360,646,918 (55%) 1,878,722,846". Before
    `_VARIANCE_PCT_RE` existed, the right-to-left scan hit "(55%)" (not
    value-shaped) and stopped immediately, folding every real value to
    its left into `raw_label` — `match_canonical_label` was then handed
    "revenue from contracts with customers 163,267,528 360,646,918 (55%)"
    instead of the clean label, and the line silently produced no draft
    at all despite `revenue` already being a canonical key."""
    result = split_label_and_values(
        "Revenue from contracts with customers 163,267,528 360,646,918 (55%) 1,878,722,846"
    )
    assert result is not None
    assert result.raw_label == "Revenue from contracts with customers"
    assert result.statement_line == "revenue"
    assert result.values == (Decimal("163267528"), Decimal("360646918"), Decimal("1878722846"))


def test_a_variance_pct_column_between_two_pairs_of_values_is_dropped():
    """Same real gap, independently verified on Amãna Bank PLC's interim
    statement for the quarter ended 30 June 2026, which prints TWO
    variance-% columns on one line (six-months change, then quarter
    change): "Profit for the Period 1,124,622 901,334 25% 622,661 467,208
    33%". Both must be dropped, leaving exactly the four real value
    columns the statement's own six-months/quarter comparative layout
    declares."""
    result = split_label_and_values(
        "Profit for the Period 1,124,622 901,334 25% 622,661 467,208 33%"
    )
    assert result is not None
    assert result.raw_label == "Profit for the Period"
    assert result.statement_line == "net_income"
    assert result.values == (
        Decimal("1124622"), Decimal("901334"), Decimal("622661"), Decimal("467208"),
    )


def test_a_line_that_is_only_a_variance_pct_column_returns_none():
    """A line with a "%"-shaped trailing token but no real value at all
    (e.g. a stray "Change %" sub-header repeated mid-page) must not
    produce a bogus all-None-value draft."""
    assert split_label_and_values("Change % (55%) 18%") is None


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


# A DIFFERENT real split-digit artifact, found live (18 Aug 2026) on
# Wealthtrust Securities PLC's (WLTH.N0000) real interim statement for
# the period ended 30 June 2026 — see `_repair_split_leading_digits`'s
# own module-level comment for the full finding, including the
# cross-check against the balance sheet's own real, independently-
# verified total that confirms this reading rather than assuming it.
SPLIT_LEADING_DIGIT_LINES = {
    "Total Assets 4 7,325,768,494 4 3,942,985,474": (
        "total_assets",
        Decimal("47325768494"),
    ),
    "Total Liabilities 4 0,918,613,066 3 7,080,599,730": (
        "total_liabilities",
        Decimal("40918613066"),
    ),
    "Total Equity and Liabilities 4 7,325,768,494 4 3,942,985,474": (
        "total_equity_and_liabilities",
        Decimal("47325768494"),
    ),
}


@pytest.mark.parametrize(("line", "expected"), SPLIT_LEADING_DIGIT_LINES.items())
def test_split_leading_digit_is_rejoined_not_dropped_as_a_note_reference(line, expected):
    key, value = expected
    result = split_label_and_values(line)
    assert result is not None
    assert result.statement_line == key
    assert result.primary_value == value


def test_aafs_real_odd_count_split_digit_is_a_named_unfixed_gap():
    """Characterises, rather than fixes, a real case found live (19 Aug
    2026) reviewing AAF.N0000's backfilled annual reports: "Profit for
    the year 1 18,561,733 45,196,117" — an ODD token count, so
    `_repair_split_leading_digits` correctly declines to touch it (same
    guard that protects JF Packaging's genuine note-reference line right
    below), and the lone "1" is read as a syntactically valid, wrong
    net_income. See that function's own docstring for why fixing this
    from token shape alone would break the JF Packaging case — this test
    exists so a future attempt at a real fix has a concrete, real
    regression case to check against, not so this wrong answer is
    endorsed."""
    result = split_label_and_values("Profit for the year 1 18,561,733 45,196,117")
    assert result is not None
    assert result.statement_line == "net_income"
    assert result.primary_value == Decimal("1")  # the known-wrong reading, not the real 118,561,733


def test_jf_packagings_real_note_reference_is_not_wrongly_merged():
    """The safety boundary `_repair_split_leading_digits` is deliberately
    narrow to protect: J.F. Packaging PLC's real Revenue line has a
    genuine note reference ("5"), not a split digit. It has an ODD
    number of numeric tokens (5), so the new repair must never touch
    it — merging "5" into "4,504,801" would silently turn a currently-
    correct extraction into a wrong one."""
    result = split_label_and_values("Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137")
    assert result is not None
    assert result.statement_line == "revenue"
    assert result.primary_value == Decimal("4504801")


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


def test_extract_candidate_lines_finds_lwls_real_assets_held_for_sale_lines():
    """LWL's real, genuine IFRS 5 held-for-sale lines — verified present
    and extractable, not just theorised."""
    by_statement_line = {
        l.statement_line: l.primary_value
        for l in extract_candidate_lines(BALANCE_SHEET_TEXT_LWL)
        if l.statement_line
    }
    assert by_statement_line["assets_held_for_sale"] == Decimal("366082")
    assert by_statement_line["liabilities_associated_with_assets_held_for_sale"] == Decimal("412950")


def test_identities_pass_on_lwls_real_balance_sheet_including_assets_held_for_sale():
    """A REAL bug, found live (18 Aug 2026): LWL.N0000's real interim
    statement for the period ended 30 June 2026 failed
    check_accounting_identities's "assets = current + non-current"
    check — "62,364,259,000 vs 61,998,177,000", a 366,082,000 gap. NOT an
    extraction bug: the gap is LWL's own real "Assets held for sale"
    line, a genuine third balance-sheet bucket under IFRS 5 that this
    system didn't extract at all before this fix. With
    `assets_held_for_sale` now extracted and folded into the identity as
    an optional addend, this real filing's own real figures now balance
    exactly."""
    values = _values(BALANCE_SHEET_TEXT_LWL)
    checks = check_accounting_identities(values)
    assert checks, "expected at least one identity to be checkable"
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    identity = next(c for c in checks if c.name == "assets = current + non-current")
    assert "includes assets held for sale = 366,082" in identity.detail


def test_assets_held_for_sale_identity_is_a_pure_addition_not_a_behaviour_change():
    """A company with no held-for-sale line (every real fixture already
    verified before LWL) must see this identity exactly as before —
    `assets_held_for_sale` simply defaults to zero when absent."""
    checks = check_accounting_identities(_values(BALANCE_SHEET_TEXT))
    identity = next(c for c in checks if c.name == "assets = current + non-current")
    assert identity.passed
    assert "held for sale" not in identity.detail


# --- magnitude plausibility ----------------------------------------------


def test_magnitude_plausibility_catches_aafs_real_failure_shape():
    """The exact failure shape named (but deliberately left unfixed at the
    parsing layer) in commit 313afdc: AAF.N0000's real FY2022 net_income
    read as the literal digit "1" against a total_assets of ~19.3bn on
    the same filing — no accounting identity happened to cover net_income
    for this filing (income_tax_expense wasn't also extracted), so it
    passed check_accounting_identities completely clean. This is the gap
    check_magnitude_plausibility exists to close."""
    values = {"total_assets": Decimal("19300000000"), "net_income": Decimal("1")}
    checks = check_magnitude_plausibility(values)
    assert len(checks) == 1
    assert not checks[0].passed
    assert checks[0].name == "net_income implausibly small vs total_assets"


def test_magnitude_plausibility_catches_vlls_real_failure_shape():
    """A second, independent real case, found live running this check for
    the first time against VLL.N0000's real FY ended 2012-03-31 filing:
    one leg of "pre-tax profit - tax = net income" reads as the literal
    value 30 against a net_income of 59,130,635 on the same filing —
    same shape as AAF, a different company and a different filing."""
    values = {"net_income": Decimal("59130635"), "income_tax_expense": Decimal("30")}
    checks = check_magnitude_plausibility(values)
    assert len(checks) == 1
    assert not checks[0].passed
    assert checks[0].name == "income_tax_expense implausibly small vs net_income"


def test_magnitude_plausibility_does_not_flag_a_genuinely_thin_real_margin():
    """A real, thin-but-genuine net income relative to total assets (here
    ~1 part in 10,000 — far tighter than any real filing checked so far)
    must NOT be flagged; this is a plausibility floor self-scaled to the
    filing's own size, not a guess at what a "normal" margin looks like."""
    values = {"total_assets": Decimal("5000000000"), "net_income": Decimal("500000")}
    assert check_magnitude_plausibility(values) == []


def test_magnitude_plausibility_needs_at_least_two_values():
    assert check_magnitude_plausibility({"total_assets": Decimal("100")}) == []
    assert check_magnitude_plausibility({}) == []


def test_a_genuine_exact_zero_subtotal_is_never_flagged():
    """REAL BUG THIS CLOSES, found live (28 Aug 2026) tracing Pan Asia
    Power PLC's real confirmed `total_non_current_liabilities`, printed
    as a literal "0" on 16 independent real filings across consecutive
    years ("Total Non current liabilities 0 922,963" — the company
    simply repaid all its long-term debt that year): before this fix,
    `ratio = abs(0) / largest` is always 0, always below the floor, so a
    genuine zero subtotal could NEVER pass this check no matter how many
    times it was re-verified against the live source PDF — permanently,
    falsely un-confirmable. A corrupted read (a split-off leading digit,
    a stray footnote number) is never itself exactly zero, so exempting
    a literal 0 loses no real detection power."""
    values = {"total_assets": Decimal("8033527"), "total_non_current_liabilities": Decimal("0")}
    assert check_magnitude_plausibility(values) == []
    # A genuinely corrupted near-zero (not exactly 0) must still be caught:
    values_corrupted = {"total_assets": Decimal("8033527"), "total_non_current_liabilities": Decimal("1")}
    checks = check_magnitude_plausibility(values_corrupted)
    assert len(checks) == 1
    assert not checks[0].passed


def test_magnitude_plausibility_does_not_flag_real_filings():
    """Regression guard: every real fixture this module already trusts
    (J.F. Packaging's real balance sheet, income statement, cash-flow
    statement) must produce zero magnitude-plausibility flags — this
    check must never second-guess a filing that genuinely balances and
    was never in question."""
    for text in (BALANCE_SHEET_TEXT, INCOME_STATEMENT_TEXT, CASH_FLOW_STATEMENT_TEXT):
        checks = check_magnitude_plausibility(_values(text))
        assert checks == [], checks


class TestReconcileMagnitudeImplausibleValues:
    """REAL BUG THIS CLOSES, found live (28 Aug 2026) tracing Serendib
    Hotels PLC's real confirmed `inventories`, stored as the literal
    digit 3: its real balance sheet line ("Inventories 13 3 7,890 33,761
    8 ,306 7,597") already computes the correct `alt_values` reading
    (37,890) via the exact same split-pair machinery every other real
    case in this module already relies on — but `inventories` has no
    sibling accounting identity, so `reconcile_ambiguous_values_via_
    identities` never even considers it. See `reconcile_magnitude_
    implausible_values`'s own docstring for the full real case and the
    narrower acceptance rule this pass uses instead of an identity."""

    def test_serendibs_real_inventories_line_is_corrected(self):
        values = {"total_assets": Decimal("4340271000"), "inventories": Decimal("3")}
        alt_values = {"inventories": Decimal("37890")}
        assert reconcile_magnitude_implausible_values(values, alt_values) == {
            "inventories": Decimal("37890"),
        }

    def test_a_key_with_no_alt_candidate_is_left_alone(self):
        """Flagged but nothing to substitute — no correction offered,
        same as the flag standing untouched for a human to check."""
        values = {"total_assets": Decimal("4340271000"), "inventories": Decimal("3")}
        assert reconcile_magnitude_implausible_values(values, {}) == {}

    def test_an_alt_that_is_still_implausible_is_not_accepted(self):
        """The alt itself must actually clear the floor — a partial fix
        (still implausibly small) is not treated as good enough."""
        values = {"total_assets": Decimal("4340271000"), "inventories": Decimal("3")}
        alt_values = {"inventories": Decimal("30")}  # still ~7.6x below the floor
        assert reconcile_magnitude_implausible_values(values, alt_values) == {}

    def test_a_key_that_was_never_flagged_is_never_touched_even_with_an_alt(self):
        """`alt_values` is offered for every excess-token line regardless
        of plausibility (see `ExtractedLine.alt_values`'s own docstring)
        — this pass must ignore an alt for a key that wasn't already
        flagged, exactly like identity-based reconciliation already does
        for J.F. Packaging's own genuine note-reference line."""
        values = {"total_assets": Decimal("4340271000"), "revenue": Decimal("4504801")}
        alt_values = {"revenue": Decimal("54504801")}
        assert reconcile_magnitude_implausible_values(values, alt_values) == {}

    def test_a_correction_that_would_newly_implicate_another_key_is_rejected(self):
        """Accepting a correction can change WHICH key is the filing's
        own "largest" value, shrinking some other key's ratio below the
        floor for the first time — this pass must not trade one flagged
        key for a different one."""
        values = {"total_assets": Decimal("10000000"), "inventories": Decimal("3")}
        # inventories/10,000,000 = 3e-7, flagged; substituting inventories
        # -> 1e14 would make it the new largest, and total_assets' own
        # ratio against THAT (1e-7) would newly drop below the floor —
        # correction rejected even though inventories' own flag clears.
        alt_values = {"inventories": Decimal("100000000000000")}
        assert reconcile_magnitude_implausible_values(values, alt_values) == {}


def test_check_extraction_quality_combines_identities_and_magnitude():
    """A filing that fails ONLY the magnitude floor (no accounting
    identity is even computable — matching AAF's real case, where the
    missing income_tax_expense meant no identity covered net_income
    either) must still come back as a failure from the combined
    function, not silently pass because check_accounting_identities
    alone had nothing to check."""
    values = {"total_assets": Decimal("19300000000"), "net_income": Decimal("1")}
    assert check_accounting_identities(values) == []  # nothing computable — the real AAF gap
    checks = check_extraction_quality(values)
    assert any(not c.passed for c in checks)


def test_check_extraction_quality_passes_cleanly_on_real_filings():
    """Every real fixture that already passes check_accounting_identities
    cleanly must also pass the combined check cleanly — adding the
    magnitude floor must never turn a real, correct filing into a
    false positive."""
    for text in (BALANCE_SHEET_TEXT, INCOME_STATEMENT_TEXT, CASH_FLOW_STATEMENT_TEXT):
        checks = check_extraction_quality(_values(text))
        assert all(c.passed for c in checks), [c for c in checks if not c.passed]


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

    def test_combs_2019_annual_report_uses_a_unicode_right_quote_not_ascii_apostrophe(self):
        """A REAL, SEPARATE encoding variant found live: COMB.N0000's
        2019 annual report (a different filing/toolchain vintage from its
        2026 interim statement above) renders the same "Rs.'000"
        declaration with U+2019 (RIGHT SINGLE QUOTATION MARK, "’"), not
        the straight ASCII apostrophe (U+0027, "'") — pdfplumber decodes
        whichever glyph that PDF's own embedded font actually maps to
        that position. Found by a dedicated diagnostic run against the
        real PDF after the ASCII-only pattern silently dropped 11 real,
        extractable pages from this one filing alone, including the
        primary balance sheet itself — not a theoretical variant."""
        real_header_with_unicode_quote = (
            "GROUP BANK\n"
            "As at December 31, 2019 2018 Change 2019 2018 Change\n"
            "Note Page No. Rs. ’000 Rs. ’000 % Rs. ’000 Rs. ’000 %\n"
        )
        assert detect_unit_scale(real_header_with_unicode_quote) == Decimal(1000)

    def test_ntbs_real_lkr_000_header_is_a_thousands_scale(self):
        """A REAL, SEPARATE currency-prefix variant found live (18 Aug
        2026): Nations Trust Bank PLC's real interim statement for the
        six months ended 30 June 2026 declares its units as "LKR '000",
        never "Rs." at all, on its real Statement of Cash Flows page.
        Found via a dedicated diagnostic download of NTB.N0000's own real
        filing after the "rs"-only pattern refused every one of its real
        primary-statement pages and produced 0 drafts across two separate
        backfill runs, even though a real, well-formed unit declaration
        WAS present — just spelled with a different currency
        abbreviation than every previously-seen real filing."""
        ntb_header = (
            "NATIONS TRUST BANK PLC\n"
            "STATEMENT OF CASH FLOWS\n"
            "Bank Group\n"
            "Six Months Ended 30 June Six Months Ended 30 June\n"
            "2026 2025 2026 2025\n"
            "LKR '000 LKR '000 LKR '000 LKR '000\n"
        )
        assert detect_unit_scale(ntb_header) == Decimal(1000)

    def test_swadeshis_real_rs_header_is_a_full_value_scale(self):
        """Swadeshi Industrial Works PLC's real statements are genuinely
        NOT in thousands — Revenue of 4,649,049,764 is a real ~4.6bn LKR
        figure; interpreted as thousands it would be an impossible 4.6
        trillion. A blanket "always 1000" fix would have been wrong for
        this real, already-verified filing."""
        assert detect_unit_scale(BALANCE_SHEET_TEXT_SWAD) == Decimal(1)
        assert detect_unit_scale(INCOME_STATEMENT_TEXT_SWAD) == Decimal(1)

    def test_paps_real_bare_lkr_header_is_a_full_value_scale(self):
        """A REAL, SEPARATE gap found live (18 Aug 2026): Panasian Power
        PLC's (PAP.N0000) real interim statement declares its units as a
        bare, repeated "LKR LKR LKR LKR" — no "'000" suffix, and not
        "Rs." either. Before this fix, neither pattern matched: the
        thousands pattern correctly refused (no "'000"/"000" suffix
        present), but the full-value pattern ALSO refused, because it
        only recognised a repeated "Rs." — the whole page was silently
        skipped, 0 drafts, despite its own Total Assets (9,828,732,284)
        only being plausible as a genuine full-LKR figure (read as
        thousands it would be a nonsensical ~9.8 trillion LKR for a small
        hydro/solar power company)."""
        assert detect_unit_scale(BALANCE_SHEET_TEXT_PAP) == Decimal(1)

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


class TestRepairCharacterDoubling:
    """A REAL bug, found live (18 Aug 2026) against Nations Trust Bank
    PLC's (NTB.N0000) real interim statement for the six months ended 30
    June 2026: bold-rendered text on several real pages comes out of
    pdfplumber's own `extract_text()` with every character glyph doubled
    — see `repair_character_doubling`'s own module-level comment in
    app.domain.financial_statement_parsing for the full finding. Left
    unrepaired, page 4's own doubled title never matched
    `_STATEMENT_PAGE_MARKERS` and its doubled "LKR '000" unit declaration
    never matched `_UNIT_THOUSANDS_RE` either — the real balance sheet on
    NTB's own newest quarter was silently skipped, 0 drafts."""

    def test_ntbs_real_doubled_title_is_recovered(self):
        repaired = repair_character_doubling(BALANCE_SHEET_TEXT_NTB_DOUBLED)
        lines = repaired.splitlines()
        assert lines[0] == "NATIONS TRUST BANK PLC"
        assert lines[1] == "STATEMENT OF FINANCIAL POSITION"
        assert "LKR '000 LKR '000" in repaired

    def test_ntbs_real_doubled_page_is_now_recognised_as_a_thousands_scale(self):
        repaired = repair_character_doubling(BALANCE_SHEET_TEXT_NTB_DOUBLED)
        assert detect_unit_scale(repaired) == Decimal(1000)

    def test_ntbs_real_doubled_subtotal_rows_recover_the_real_printed_figures(self):
        """Every doubled subtotal row (bold on the real PDF) recovers its
        real printed value exactly — not a coincidence: confirmed by
        cross-checking against `check_accounting_identities` in
        test_full_extraction below, the same technique that originally
        caught the split-thousands and split-leading-digit bugs."""
        repaired = repair_character_doubling(BALANCE_SHEET_TEXT_NTB_DOUBLED)
        assert "Total Assets 923,175,159 700,575,031" in repaired
        assert "Total Liabilities 819,246,480 606,682,955" in repaired
        assert "Total Shareholders' Equity 103,928,679 93,892,076" in repaired
        assert "Total Equity and Liabilities 923,175,159 700,575,031" in repaired

    def test_ntbs_real_undoubled_body_rows_on_the_same_page_are_left_untouched(self):
        """The same real page's own non-bold body rows were never doubled
        in the first place — proof the repair operates per-token/per-row,
        not as a blanket whole-page transform, which is exactly what lets
        it avoid corrupting a genuinely normal page (see the
        no-real-fixture-misfires tests below)."""
        repaired = repair_character_doubling(BALANCE_SHEET_TEXT_NTB_DOUBLED)
        assert "Cash and Cash Equivalents 37,873,231 19,864,631" in repaired
        assert "Balances with Central Bank of Sri Lanka 7,156,843 2,045,786" in repaired

    @pytest.mark.parametrize(
        "real_text",
        [
            BALANCE_SHEET_TEXT,
            INCOME_STATEMENT_TEXT,
            CASH_FLOW_STATEMENT_TEXT,
            INCOME_STATEMENT_TEXT_SWAD,
            CASH_FLOW_STATEMENT_TEXT_SWAD,
            BALANCE_SHEET_TEXT_SWAD,
            BALANCE_SHEET_TEXT_AHPL,
        ],
    )
    def test_does_not_misfire_on_real_non_doubled_filings(self, real_text):
        """Every real, already-verified, genuinely NON-doubled filing
        fixture in this file must round-trip completely untouched —
        proof this repair is narrowly gated (per
        `_page_looks_character_doubled`) rather than a blanket transform
        that would risk corrupting a normal page's own real, genuinely
        repeated-looking short values."""
        assert repair_character_doubling(real_text) == real_text

    @pytest.mark.parametrize("word", ["COMMITTEE", "OFFICE", "ANNOUNCEMENT", "NOMINATION", "ADDRESS"])
    def test_a_real_word_with_naturally_doubled_letters_does_not_misfire_standalone(self, word):
        """Real English words with doubled letters (COMMITTEE's MM/TT/EE,
        OFFICE's FF) must not be mistaken for the doubling artifact even
        when tested in isolation — none of them round-trip as a fully
        doubled run (`_is_doubled_run`), because the artifact doubles
        EVERY character, not just some."""
        page = f"{word} REPORT\nSome ordinary body text about the {word.lower()} below.\n"
        assert repair_character_doubling(page) == page


# Real text from page 2 of Tea Smallholder Factories PLC's (TSML.N0000)
# real interim statement for the quarter ended 30 June 2026, downloaded
# fresh (20 Aug 2026) from https://cdn.cse.lk/cmt/upload_report_file/
# 490_1786628491802.pdf — sought out specifically because this filing's
# own "Revenue from Contracts with Customers" line reads "... 8 27,386
# 731,119 13": pdfplumber splits the real value 827,386 into a standalone
# "8" and "27,386", and this statement's real 3-column layout (current
# quarter / prior-year quarter / change, no Group/Company split at all)
# meant the OLD hardcoded 4-column assumption masked the split entirely
# rather than flagging it as excess. Proven live: 827,386 - 791,413 =
# 35,973, exactly the real printed Gross Profit.
INCOME_STATEMENT_TEXT_TSML = """\
TEA SMALLHOLDER FACTORIES PLC
INCOME STATEMENT
Three months ended
30.06.2026 30.06.2025 Change
Unaudited Unaudited
RS. '000 RS. '000 %
Continuing Operations
Revenue from Contracts with Customers 8 27,386 731,119 13
Cost of Sales (791,413) (700,296) 13
Gross Profit / (Loss) 35,973 30,823 17
"""

# Real text from page 2 of eChannelling PLC's (ECL.N0000) real interim
# statement for the quarter ended 30 June 2026, downloaded fresh (20 Aug
# 2026) from https://cdn.cse.lk/cmt/upload_report_file/374_1786701666452
# .pdf — a genuine 2-column (current period / prior period) single-
# entity layout with NO Group/Company split at all ("As at 30.06.2026
# 31.12.2025", two dates, not four), sought out specifically because two
# of its own real subtotal lines split their leading digit: "Total
# Current Liabilities 2 19,185,791 148,727,991" (real: 219,185,791) and
# "Total Liabilities 2 38,125,232 162,155,722" (real: 238,125,232) — and
# because BOTH the subtotal and one of its own components are wrong by
# the identical missing digit, "liabilities = current + non-current"
# PASSES on the wrong values (the error cancels in that one sum), which
# is exactly why fixing either alone (rather than both together) was the
# real, live bug `reconcile_ambiguous_values_via_identities` closes — see
# that function's own docstring.
BALANCE_SHEET_TEXT_ECL = """\
eChannelling PLC
STATEMENT OF FINANCIAL POSITION
As at 30.06.2026 31.12.2025
LKR LKR
Non Current Assets
Total Non Current Assets 3 3,730,618 2 1,886,752
Current Assets
Total Current Assets 7 55,720,897 6 56,674,427
Total Assets 7 89,451,516 6 78,561,179
EQUITY AND LIABILITIES
Equity
Total Equity 5 51,326,283 5 16,405,457
Non Current Liabilities
Total Non Current Liabilities 1 8,939,441 1 3,427,731
Current Liabilities
Total Current Liabilities 2 19,185,791 148,727,991
Total Liabilities 2 38,125,232 162,155,722
Total Equity & Liabilities 7 89,451,516 678,561,179
"""

# Asia Asset Finance PLC's real Statement of Cash Flows header (FY2019/20
# annual report, downloaded live 27 Aug 2026) — genuinely 2 columns
# (current/prior year), but written as Sri Lankan fiscal-year RANGES
# ("2019/2020 2018/2019") rather than plain single years. See
# `_YEAR_RANGE_TOKEN_RE`'s own docstring for the real corruption this
# closes: `_YEAR_TOKEN_RE` alone double-counts each range as two year
# tokens, so this header used to detect as 4 columns instead of 2.
CASH_FLOW_HEADER_TEXT_AAF = """\
Asia Asset Finance PLC | Annual Report 2019/20
Statement Of Cash Flows
2019/2020 2018/2019
Note Rs. Rs.
Cash flows from operating activities
Profit before income tax 93,316,292 93,907,039
Acquisition of property, plant and equipment 20 (27,787,206) (57,293,522)
"""

# Ownally Holdings PLC's real Statement of Profit or Loss (FY2021/22
# annual report, downloaded live 28 Aug 2026, page 43) — genuinely 2
# columns (2022/2021), but pdfplumber has merged the page's own title
# line ("Year ended 31 March 2022", whose trailing year just completes
# that sentence) with the table's real header row ("2022 2021") onto one
# line: "Year ended 31 March 2022 2022 2021". `_count_year_tokens` used
# to double-count the title's own year, detecting 3 columns instead of 2,
# which let this statement's real "Revenue from contracts with customers
# 6 213,037,864 181,702,922" line (note reference "6" + 2 real values)
# pass the `len(numeric_tokens) > expected_value_columns` check as
# 3 > 3 = False, so the note reference "6" was kept as the value instead
# of correctly dropped — confirmed live as `revenue` stored as the
# literal digit 6.
ONAL_INCOME_STATEMENT_TEXT = """\
STATEMENT OF PROFIT OR LOSS
Year ended 31 March 2022 2022 2021
Note Rs. Rs.
Revenue from contracts with customers 6 213,037,864 181,702,922
Other operating income 7 11,921,652 12,518,396
Other operating expense (77,554,904) (61,186,266)
Operating profit 147,404,612 133,035,052
Fair value gain on investment property 13 674,010,544 19,793,375
Finance income 8 48,381,853 49,093,946
Profit/(Loss) before Tax 9 869,797,009 201,922,373
Income tax expense 10 (210,902,487) 39,796,074
Profit/(Loss) for the year 658,894,522 241,718,447
"""

# Chemanex PLC's real Statement of Profit or Loss (quarterly report for
# the period ended 30 June 2018, downloaded live 28 Aug 2026, page 2) —
# genuinely 3 columns (current, prior, variance %), with the "%" sharing
# the YEAR line itself ("2018 2017 Variance %") rather than the unit-
# declaration line the way Tea Smallholder's real header does ("RS.'000
# RS.'000 %") — a different real arrangement of the same 3-column shape.
# `unit_count` alone only ever sees 1 there (a single, non-repeated "(In
# Rs. '000) Note" declaration — AHPL's already-known shape), and
# `max(year_count, unit_count)` picked year_count=2, losing the real 3rd
# column and corrupting the real `revenue` line — confirmed live as
# `revenue` stored as the literal digit 1. `Revenue`'s own real line
# additionally has a genuine 2-digit-note-reference-immediately-before-
# a-split-pair shape ("1 1 07,573 1 81,246 (41)" — note "1", then two
# split pairs "1"+"07,573" and "1"+"81,246"), the second real bug this
# fixture pins (see `_merge_all_split_pairs`'s own docstring).
CHEMANEX_INCOME_STATEMENT_TEXT = """\
CHEMANEX PLC
STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME
Three months ended 30 June
2018 2017 Variance %
(In Rs. '000) Note
Revenue 1 1 07,573 1 81,246 (41)
Cost of sales ( 84,645) ( 142,516) (41)
Gross profit 2 2,928 3 8,730 (41)
Other income 2 3 9,995 1 ,775 2 ,153
Net finance income 3 9 ,088 8 ,440 (8)
Administrative expenses ( 11,598) ( 30,595) (62)
Distribution expenses ( 3,494) ( 14,474) (76)
Profit before tax 5 6,269 3 ,595 1 ,465
Income tax expense ( 11,018) ( 4,580) 1 41
"""

# Serendib Hotels PLC's real Statement of Financial Position (annual
# report for the year ended 31 March 2020, downloaded live 28 Aug 2026,
# page 5) — the split-leading-digit artifact ("4 ,340,271" already fixed
# by `_repair_split_thousands`, "3 7,890" needing `_repair_split_leading_
# digits`/`_merge_all_split_pairs` instead) runs through nearly every
# line on this page. `inventories` and `trade_receivables` are the real
# case `reconcile_magnitude_implausible_values` exists for: genuine
# BALANCE-SHEET COMPONENT lines with no sibling identity in this module
# (`check_accounting_identities` never sums current-asset components),
# so their own correct `alt_values` reading sat unused even though
# `check_magnitude_plausibility` already flags the default outright.
SHOT_BALANCE_SHEET_TEXT = """\
Serendib Hotels PLC
STATEMENT OF FINANCIAL POSITION
Group Company
As at Note 31.03.2020 31.03.2019 31.03.2020 31.03.2019
Rs.'000 Audited Audited
ASSETS
Non-Current Assets
Property, Plant & Equipment 10 3 ,908,853 4,016,721 6 77,922 708,955
Leasehold Property 11 - 25,572 - 23,824
Intangible Assets 12 1 46,840 160,114 8 ,666 14,139
Other Non Current Financial Assets 12 1 29,588 212,202 1 24,622 206,741
4 ,340,271 4,414,609 1 ,858,662 1,906,926
Current Assets
Inventories 13 3 7,890 33,761 8 ,306 7,597
Trade and Other Receivables 14 3 06,895 341,671 1 03,988 75,196
Cash and Cash Equivalents 24 2 93,497 442,357 6 8,632 56,550
6 54,954 836,966 2 90,119 145,280
Total Assets 4 ,995,225 5 ,251,575 2 ,148,780 2,052,206
"""


class TestDetectExpectedValueColumns:
    """See `detect_expected_value_columns`'s own docstring for the real,
    live bug this closes. Every already-verified real fixture in this
    file is checked here too — the whole point is that detecting the
    real count changes NOTHING for any filing that already assumed the
    right default."""

    @pytest.mark.parametrize(
        ("real_text", "expected"),
        [
            (BALANCE_SHEET_TEXT, 4),  # J.F. Packaging PLC — Group/Company x this-year/last-year
            (INCOME_STATEMENT_TEXT, 4),
            (CASH_FLOW_STATEMENT_TEXT, 4),
            (INCOME_STATEMENT_TEXT_SWAD, 4),
            (BALANCE_SHEET_TEXT_SWAD, 4),
            (BALANCE_SHEET_TEXT_AHPL, 4),
            (BALANCE_SHEET_TEXT_PAP, 4),
            (BALANCE_SHEET_TEXT_LWL, 4),
            (BALANCE_SHEET_TEXT_ECL, 2),  # genuinely 2-column, no Group/Company split
            (INCOME_STATEMENT_TEXT_TSML, 3),  # 2 monetary columns + 1 separate change-% column
            (CASH_FLOW_HEADER_TEXT_AAF, 2),  # genuinely 2-column, written as fiscal-year RANGES
        ],
    )
    def test_real_filings_detect_their_own_real_column_count(self, real_text, expected):
        assert detect_expected_value_columns(real_text) == expected

    def test_a_page_with_no_reliable_signal_returns_none(self):
        """A single stray year mention (or none at all) isn't a reliable
        column-count signal — callers fall back to the existing default
        in this case, exactly as they always have."""
        assert detect_expected_value_columns("NOTES TO THE FINANCIAL STATEMENTS\n2026\n") is None
        assert detect_expected_value_columns("Nothing date-like on this page at all.\n") is None

    def test_fiscal_year_range_label_counts_as_one_column_not_two(self):
        """The exact regression this fix targets, isolated from the rest
        of AAF's real header: a bare `_YEAR_TOKEN_RE.findall` over
        "2019/2020 2018/2019" finds FOUR 4-digit runs for what is
        genuinely two columns — `_count_year_tokens` must not."""
        assert _count_year_tokens("2019/2020 2018/2019") == 2
        # A mix of range and plain years (hypothetical but worth pinning):
        # each range still counts once, each plain year still counts once.
        assert _count_year_tokens("2019/2020 2025 2018/2019 2025") == 4

    def test_plain_year_headers_are_unaffected_by_the_range_fix(self):
        """J.F. Packaging's real style — four bare, non-range years, one
        per real column — must still count as 4, unchanged."""
        assert _count_year_tokens("2026 2025 2026 2025") == 4

    def test_adjacent_duplicate_year_from_a_merged_title_and_header_line_counts_once(self):
        """Ownally Holdings PLC's real income-statement header (see
        `ONAL_INCOME_STATEMENT_TEXT`'s own docstring) — pdfplumber merges
        the page's title line, whose own trailing year just completes the
        sentence "Year ended 31 March 2022", with the table's real header
        row "2022 2021" onto one line of text: "Year ended 31 March 2022
        2022 2021". A bare `_YEAR_TOKEN_RE.findall` finds THREE 4-digit
        runs for what is genuinely a 2-column (2022/2021) statement;
        `_count_year_tokens` must not."""
        assert _count_year_tokens("Year ended 31 March 2022 2022 2021") == 2
        # Non-adjacent repeats (J.F. Packaging's real shape) must NOT collapse:
        assert _count_year_tokens("2022 2021 2022 2021") == 4

    def test_real_filings_detect_their_own_real_column_count_for_onal(self):
        assert detect_expected_value_columns(ONAL_INCOME_STATEMENT_TEXT) == 2

    def test_a_bare_percent_sharing_the_year_line_itself_still_counts(self):
        """Chemanex PLC's real header shape — "2018 2017 Variance %", the
        "%" sharing the YEAR line rather than a dedicated unit line (Tea
        Smallholder's own shape). `year_count` alone (2) and `unit_count`
        alone (1, from a single non-repeated "%") each undercount; the
        two signals must be summed when they cooccur on the same line."""
        assert detect_expected_value_columns(CHEMANEX_INCOME_STATEMENT_TEXT) == 3
        # J.F. Packaging's real 4-column header (no "%" on its year line
        # at all) is already covered above and stays exactly 4 — this
        # fix only adds a signal, never removes one.


class TestAafsRealFiscalYearRangeCapexExtraction:
    """End-to-end regression for the live bug this fix closes — not just
    the column-count detector in isolation, but the actual downstream
    consequence: AAF.N0000's real "Acquisition of property, plant and
    equipment 20 (27,787,206) (57,293,522)" line (a genuine note
    reference "20" immediately before two real values) used to store the
    note reference itself (`primary_value == 20`) because the page's
    mis-detected 4-column count made `len(numeric_tokens) > expected_
    value_columns` (3 > 4) false, so the note-reference-drop rule never
    fired. Verified against the real filing live (27 Aug 2026,
    https://cdn.cse.lk/cmt/upload_report_file/1108_1608806151470.pdf,
    page 106) before this fix landed — this pins that same real shape as
    a permanent regression test."""

    def test_note_reference_is_dropped_not_kept_as_the_value(self):
        result = split_label_and_values(
            "Acquisition of property, plant and equipment 20 (27,787,206) (57,293,522)",
            expected_value_columns=detect_expected_value_columns(CASH_FLOW_HEADER_TEXT_AAF),
        )
        assert result is not None
        assert result.statement_line == "capital_expenditure"
        assert result.primary_value == Decimal("-27787206")


class TestOnalsRealAdjacentDuplicateYearRevenueExtraction:
    """End-to-end regression for the live bug the adjacent-duplicate-year
    fix closes — not just the column-count detector in isolation, but the
    actual downstream consequence: Ownally Holdings PLC's real confirmed
    `revenue` stored as the literal digit 6. See `ONAL_INCOME_STATEMENT_
    TEXT`'s own docstring for the real header shape that caused it."""

    def test_note_reference_is_dropped_not_kept_as_the_value(self):
        result = split_label_and_values(
            "Revenue from contracts with customers 6 213,037,864 181,702,922",
            expected_value_columns=detect_expected_value_columns(ONAL_INCOME_STATEMENT_TEXT),
        )
        assert result is not None
        assert result.statement_line == "revenue"
        assert result.primary_value == Decimal("213037864")


class TestSplitOpenParenRepair:
    """`_SPLIT_OPEN_PAREN_RE`'s own narrow repair, isolated from the rest
    of Chemanex's real line — see its own docstring for the real bug."""

    def test_a_stray_space_after_an_opening_paren_before_a_digit_is_repaired(self):
        result = split_label_and_values("Cost of sales ( 84,645) ( 142,516) (41)", expected_value_columns=3)
        assert result is not None
        assert result.statement_line == "cost_of_sales"
        assert result.values == (Decimal("-84645"), Decimal("-142516"), Decimal("-41"))

    def test_a_genuine_label_parenthetical_is_never_touched(self):
        """"(Loss)"/"(Increase)/Decrease" style label text — a LETTER,
        not a digit, follows the opening paren — must be completely
        unaffected: the repair's `(?=\\d)` lookahead is what keeps it
        narrow."""
        result = split_label_and_values(
            "Profit/(Loss) after tax from continuing operations 45,251 (985)"
        )
        assert result is not None
        assert result.raw_label == "Profit/(Loss) after tax from continuing operations"
        assert result.values == (Decimal("45251"), Decimal("-985"))


class TestChemanexsRealNoteReferenceAdjacentToASplitPairExtraction:
    """End-to-end regression for THREE combined real bugs, all found live
    (28 Aug 2026) tracing Chemanex PLC's real confirmed `revenue` (stored
    as the literal digit 1) and `gross_profit` (stored as 2,928 instead
    of 22,928): (1) `detect_expected_value_columns` undercounting a "%"
    that shares the YEAR line rather than the unit line (see
    `CHEMANEX_INCOME_STATEMENT_TEXT`'s own docstring), (2)
    `_merge_all_split_pairs` unable to offer an alternate at all when a
    genuine leading note reference sits directly in front of a split
    pair's own leading digit, and (3) a stray space after a negative
    value's own opening parenthesis ("( 84,645)") breaking `cost_of_
    sales`'s extraction entirely, which the accounting-identity
    reconciliation that fixes (1) and (2) actually depends on being
    right. Fixing all three together lets the ALREADY-EXISTING
    `reconcile_ambiguous_values_via_identities` machinery do what it was
    built for — no new reconciliation logic needed, just three blocked
    inputs to it, unblocked."""

    def test_revenue_and_gross_profit_both_resolve_correctly_via_the_existing_identity_check(self):
        cols = detect_expected_value_columns(CHEMANEX_INCOME_STATEMENT_TEXT)
        lines = extract_candidate_lines(CHEMANEX_INCOME_STATEMENT_TEXT, expected_value_columns=cols)
        values = {l.statement_line: l.primary_value for l in lines if l.statement_line}
        alt_values = {
            l.statement_line: l.alt_values[0] for l in lines if l.statement_line and l.alt_values
        }
        # Before any of the three fixes, `values["revenue"] == 1` and
        # `values["cost_of_sales"]` wasn't even extracted (swallowed into
        # the label — see `_SPLIT_OPEN_PAREN_RE`'s own docstring):
        assert values["cost_of_sales"] == Decimal("-84645")
        corrected = reconcile_ambiguous_values_via_identities(values, alt_values)
        assert corrected["revenue"] == Decimal("107573")
        assert corrected["gross_profit"] == Decimal("22928")


class TestAltValuesForAmbiguousExcessTokens:
    """`ExtractedLine.alt_values` — the alternate reading offered for a
    line whose excess numeric tokens are genuinely ambiguous (a real
    note reference vs. a real split-off leading digit — see that field's
    own docstring). Never applied here; only ever offered as a candidate
    for `reconcile_ambiguous_values_via_identities` to accept or reject."""

    def test_jf_packagings_genuine_note_reference_gets_an_alt_too(self):
        """The alt-computation itself is deliberately AGGRESSIVE (it
        would happily "rejoin" a genuine trailing note reference) — the
        real protection against misusing this for J.F. Packaging's own
        real line lives in `reconcile_ambiguous_values_via_identities`,
        not here. This test documents that `alt_values` is offered
        regardless; the next class proves it never gets ACCEPTED for
        this line."""
        result = split_label_and_values("Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137")
        assert result is not None
        assert result.values == (
            Decimal("4504801"), Decimal("4385214"), Decimal("2356951"), Decimal("2371137"),
        )
        assert result.alt_values == (
            Decimal("54504801"), Decimal("4385214"), Decimal("2356951"), Decimal("2371137"),
        )

    def test_tea_smallholders_real_split_digit_produces_the_correct_alt(self):
        result = split_label_and_values(
            "Revenue from Contracts with Customers 8 27,386 731,119 13",
            expected_value_columns=3,
        )
        assert result is not None
        assert result.values == (Decimal("27386"), Decimal("731119"), Decimal("13"))
        assert result.alt_values == (Decimal("827386"), Decimal("731119"), Decimal("13"))

    def test_swisstek_real_two_independent_splits_on_one_line_both_merge(self):
        """Swisstek (Ceylon) PLC's real "Total liabilities" line — TWO of
        its four columns split independently (columns 1 and 2, not just
        the first), which a single-leading-token restriction would miss
        entirely."""
        result = split_label_and_values(
            "Total liabilities 1 0,216,971 1 0,163,128 2,881,063 2,481,861",
            expected_value_columns=4,
        )
        assert result is not None
        assert result.alt_values == (
            Decimal("10216971"), Decimal("10163128"), Decimal("2881063"), Decimal("2481861"),
        )

    def test_no_excess_tokens_means_no_alt_offered(self):
        result = split_label_and_values("Total Assets 3,807,110 3,722,727 3,559,834 3,453,018")
        assert result is not None
        assert result.alt_values is None

    def test_a_leading_excess_token_immediately_before_a_split_pair_still_gets_the_right_alt(self):
        """A genuine leading note reference sitting directly in front of
        a split-pair's own leading digit — REAL BUG THIS PINS, found live
        (28 Aug 2026) tracing Chemanex PLC's real confirmed `revenue`
        (see `TestChemanexsRealNoteReferenceAdjacentToASplitPairExtraction`
        for the full end-to-end case): "11" (a genuine 2-digit note
        reference) then "22" — itself the split-off leading digits of
        "22" + "4,504,801" = "224,504,801" — is exactly this shape one
        level more excess than J.F. Packaging's own single-note-reference
        line. `_merge_all_split_pairs` must retry with the leading token
        dropped when the direct greedy scan overshoots, not give up."""
        result = split_label_and_values(
            "Some Line 11 22 4,504,801 4,385,214 2,356,951 2,371,137", expected_value_columns=4,
        )
        assert result is not None
        assert result.alt_values == (
            Decimal("224504801"), Decimal("4385214"), Decimal("2356951"), Decimal("2371137"),
        )

    def test_a_merge_that_does_not_land_on_the_expected_count_even_with_the_leading_token_dropped_offers_no_alt(self):
        """Excess tokens that DON'T resolve to a clean merge either way —
        neither the direct scan nor the leading-token-dropped retry lands
        on the expected count — must not produce a guessed alternate:
        `None`, not a wrong one."""
        result = split_label_and_values(
            "Some Line 11 22 33 4,504,801 4,385,214 2,356,951 2,371,137", expected_value_columns=4,
        )
        assert result is not None
        assert result.alt_values is None

    def test_jat_holdings_real_percent_suffixed_variance_columns_unlock_the_correct_alt(self):
        """REAL BUG, found live (28 Aug 2026): JAT Holdings PLC's real
        confirmed net_income was stored as the literal digit "2" — this
        is that exact real line (page 2 of https://cdn.cse.lk/cmt/
        upload_report_file/2353_1635392277137.pdf). The page's own
        header ("Rs. Rs. % Rs. Rs. %") makes `detect_expected_value_
        columns` return 6, budgeting one slot per "%" the same way it
        correctly does for Tea Smallholder's real bare-number "%"-column
        above — but JAT's OWN real "%"-column values carry a literal "%"
        suffix on every row ("177%", "-1991%"), which `_VARIANCE_PCT_RE`
        already strips as never-a-real-value, leaving only 4 real
        monetary tokens after strip-and-split — the effective-column
        adjustment (subtracting however many `_VARIANCE_PCT_RE` tokens
        THIS line actually stripped) is what un-inflates the comparison
        back down to 4, unlocking the correct alt_values here."""
        result = split_label_and_values(
            "Profit for the Period 2 38,401,649 85,982,747 177% 4 00,051,561 (21,150,114) -1991%",
            expected_value_columns=6,
        )
        assert result is not None
        assert result.values == (
            Decimal("38401649"), Decimal("85982747"), Decimal("4"), Decimal("51561"), Decimal("-21150114"),
        )
        assert result.alt_values == (
            Decimal("238401649"), Decimal("85982747"), Decimal("400051561"), Decimal("-21150114"),
        )

    def test_amanas_real_percent_suffixed_line_with_no_split_is_unaffected(self):
        """Regression guard, using the SAME real fixture `_VARIANCE_PCT_
        RE`'s own docstring already cites (Amãna Bank PLC's real interim
        statement): a "%"-suffixed variance line with NO split-digit
        artifact at all must still read cleanly, both before and after
        the effective-column adjustment — the two real "%" tokens get
        stripped either way, correctly leaving 2 real monetary columns
        for a 2-column statement (no Group/Company split), and no excess
        remains to trigger alt_values at all."""
        result = split_label_and_values(
            "Profit for the Period 1,124,622 901,334 25% 622,661 467,208 33%",
            expected_value_columns=4,
        )
        assert result is not None
        assert result.values == (Decimal("1124622"), Decimal("901334"), Decimal("622661"), Decimal("467208"))
        assert result.alt_values is None


class TestReconcileAmbiguousValuesViaIdentities:
    """See `reconcile_ambiguous_values_via_identities`'s own docstring
    for the real cases this closes and the hard constraint it never
    violates."""

    def test_jf_packagings_real_revenue_alt_is_rejected_not_applied(self):
        """The default reading already satisfies "revenue - cost of
        sales = gross profit" — the alternate (however plausible-looking
        on its own) must never be accepted, since doing so would BREAK
        an identity that already held."""
        values = {
            "revenue": Decimal("4504801"), "cost_of_sales": Decimal("-3335742"),
            "gross_profit": Decimal("1169059"),
        }
        alt_values = {"revenue": Decimal("54504801")}
        assert reconcile_ambiguous_values_via_identities(values, alt_values) == {}

    def test_echannellings_real_confounded_pair_is_resolved_only_together(self):
        """Real, live case: correcting EITHER `total_current_liabilities`
        or `total_liabilities` alone turns "liabilities = current + non-
        current" from passing (on the wrong values, which happen to
        cancel) to failing — only accepting BOTH together fixes "assets =
        equity + liabilities" while leaving the current/non-current
        identity exactly where it started."""
        values = {
            "total_assets": Decimal("789451516"),
            "total_current_assets": Decimal("755720897"),
            "total_non_current_assets": Decimal("33730618"),
            "total_equity": Decimal("551326283"),
            "total_non_current_liabilities": Decimal("18939441"),
            "total_current_liabilities": Decimal("19185791"),  # wrong: missing leading "2"
            "total_liabilities": Decimal("38125232"),  # wrong: missing leading "2"
        }
        alt_values = {
            "total_current_liabilities": Decimal("219185791"),
            "total_liabilities": Decimal("238125232"),
        }
        corrections = reconcile_ambiguous_values_via_identities(values, alt_values)
        assert corrections == {
            "total_current_liabilities": Decimal("219185791"),
            "total_liabilities": Decimal("238125232"),
        }

    def test_tea_smallholders_real_single_key_correction(self):
        values = {
            "revenue": Decimal("27386"), "cost_of_sales": Decimal("-791413"),
            "gross_profit": Decimal("35973"),
        }
        alt_values = {"revenue": Decimal("827386")}
        assert reconcile_ambiguous_values_via_identities(values, alt_values) == {
            "revenue": Decimal("827386"),
        }

    def test_no_alt_values_returns_no_corrections(self):
        assert reconcile_ambiguous_values_via_identities({"total_assets": Decimal(100)}, {}) == {}

    def test_an_already_clean_statement_gets_no_corrections_even_with_an_alt_offered(self):
        """If nothing is actually wrong, there is nothing to "fix" — an
        alt_value present for a key that isn't causing any identity to
        fail must not be applied just because it exists."""
        values = {
            "total_assets": Decimal("100"), "total_equity": Decimal("60"),
            "total_liabilities": Decimal("40"),
        }
        alt_values = {"total_liabilities": Decimal("99999")}
        assert reconcile_ambiguous_values_via_identities(values, alt_values) == {}


def test_end_to_end_echannellings_real_filing_reconciles_correctly():
    """`extract_candidate_lines` (page-level, no reconciliation applied
    yet — that's `app.ingestion.financial_pdf_extractor`'s own job) still
    produces the WRONG default values for both split subtotal lines here
    — proving the reconciliation step is a genuinely separate stage, not
    something `extract_candidate_lines` already does on its own."""
    lines = extract_candidate_lines(BALANCE_SHEET_TEXT_ECL, expected_value_columns=2)
    by_key = {line.statement_line: line for line in lines if line.statement_line}
    assert by_key["total_current_liabilities"].primary_value == Decimal("19185791")
    assert by_key["total_current_liabilities"].alt_values == (
        Decimal("219185791"), Decimal("148727991"),
    )
    assert by_key["total_liabilities"].primary_value == Decimal("38125232")
    assert by_key["total_liabilities"].alt_values == (Decimal("238125232"), Decimal("162155722"))

    values = {k: v.primary_value for k, v in by_key.items() if v.primary_value is not None}
    alt_values = {
        k: v.alt_values[0] for k, v in by_key.items() if v.alt_values is not None
    }
    corrections = reconcile_ambiguous_values_via_identities(values, alt_values)
    assert corrections == {
        "total_current_liabilities": Decimal("219185791"),
        "total_liabilities": Decimal("238125232"),
    }
