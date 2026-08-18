"""
Deterministic line-item extraction from CSE financial-statement PDF text.

Master Spec §5 describes the intended pipeline as "PDF table extraction ->
LLM-assisted line-item mapping -> mandatory human confirm queue." This
module is NOT that — it's a Phase-1 stand-in that gets a genuinely useful
subset of line items (see CANONICAL_LABELS below) without an LLM call,
using patterns verified against a real annual report (J.F. Packaging PLC,
FY2025/26, downloaded via the verified `getFinancialAnnouncement`
endpoint — see app/ingestion/README_ENDPOINTS.md). Wiring an actual LLM
extraction step is a real Phase-1/2 decision that needs an API key and a
cost/model choice from the user — not something to bake in silently — so
it's tracked as an open item rather than implemented here. Every value
this module produces is written with provenance_tier=AI_ASSISTED and
cannot enter a valuation until a human confirms it (§8) — see
app/api/routes/fundamentals.py.

WHY extract_tables() ISN'T USED: pdfplumber's table detector relies on
ruled lines/borders. CSE annual report statement pages are typically
positioned text with no visible grid, and `extract_tables()` on a real
example collapsed the entire page into one text blob plus a column of
numbers completely disconnected from their labels — useless. Working from
`extract_text()`'s line-by-line output instead, with a right-to-left
token scan to separate a label from its trailing numbers, is what
actually works on real documents.

THE NOTE-REFERENCE PROBLEM: a statement line often has a note number
between the label and the actual values, e.g.
    "Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137"
but not always:
    "Total Assets 3,807,110 3,722,727 3,559,834 3,453,018"
A note reference is a short, comma-free, dot-separated number ("5", "6.1",
"24.1.1", "10.1") immediately followed by a properly comma-formatted
value. Confusing one with a value would silently extract "5" as Revenue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Strict: a well-formed figure is either comma-grouped in threes
# (4,453,103) or has no grouping at all (453103), optionally negative via
# parentheses and optionally with decimals. Deliberately does NOT match a
# fragment like ",453,103".
#
# The earlier version of this pattern was `^\(?[\d,]+(\.\d+)?\)?$`, which
# happily accepted a leading comma — and that permissiveness silently
# corrupted a real filing. See _repair_split_thousands below.
_VALUE_RE = re.compile(r"^\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")
# Verified on J.F. Packaging PLC's cash flow statement (FY2025/26): a line
# item split across two notes is referenced as "11/13" (PPE note 11 +
# intangibles note 13), not the dot-separated sub-note form ("6.1", "20.1.2")
# this pattern already handled. A slash never appears in a real value
# (Rs.000 figures are digits/commas/parens only), so allowing it here is
# safe and motivated by a real filing, not a guess at wording variance.
_NOTE_REF_RE = re.compile(r"^\d{1,3}([./]\d{1,3}){0,3}$")
_NIL = "-"

# pdfplumber sometimes emits a space between a number's leading digit and
# its first comma group: "4 ,453,103" instead of "4,453,103". Observed on
# J.F. Packaging PLC's June 2026 interim statements (but NOT on its annual
# report — same company, same layout family, different rendering).
#
# Left unrepaired this is worse than a parse failure: the line still
# tokenises, the leading "4" looks exactly like a note reference, gets
# dropped by the note-reference rule, and "Total Assets" is recorded as
# 453,103 instead of 4,453,103 — off by four billion rupees and entirely
# plausible on screen. Repairing before tokenising, and refusing
# comma-leading fragments after, closes it from both directions.
_SPLIT_THOUSANDS_RE = re.compile(r"(\d)\s+(?=,\d{3})")


def _repair_split_thousands(line: str) -> str:
    return _SPLIT_THOUSANDS_RE.sub(r"\1", line)

# CSE comparative statements consistently print exactly this many value
# columns (Group this-year, Group last-year, Company this-year, Company
# last-year — verified on J.F. Packaging PLC, whose own column header
# reads "Notes Rs.000 Rs.000 Rs.000 Rs.000"). This is the signal used to
# tell a leading note-reference token apart from a genuine value: "5" and
# "13.2" are indistinguishable from real values by shape alone (a note
# ref and a small value/a decimal EPS figure can look identical), but a
# line with 5 numeric tokens when exactly 4 are expected almost certainly
# has a note reference in the extra slot. KNOWN LIMITATION: a company
# whose statements aren't laid out as a 4-column Group/Company
# comparative (e.g. a single-entity or single-year presentation) would
# need a different expected count — not handled generically this session,
# see README_ENDPOINTS.md / ROADMAP.md.
DEFAULT_EXPECTED_VALUE_COLUMNS = 4

# Canonical statement-line key -> exact normalised label text(s) that map
# to it. Deliberately EXACT match (post-normalisation), not substring —
# "total assets" must never match "total non-current assets". Verified
# against J.F. Packaging PLC's FY2025/26 statements; expand as more real
# filings are processed rather than guessing at wording variance across
# the ~286 listed companies up front.
CANONICAL_LABELS: dict[str, tuple[str, ...]] = {
    "total_assets": ("total assets",),
    "total_current_assets": ("total current assets",),
    "total_non_current_assets": ("total non-current assets", "total non current assets"),
    "total_equity": ("total equity", "total shareholders funds", "total shareholders' funds"),
    "total_liabilities": ("total liabilities",),
    "total_current_liabilities": ("total current liabilities",),
    "total_non_current_liabilities": ("total non-current liabilities", "total non current liabilities"),
    "total_equity_and_liabilities": ("total equity and liabilities",),
    "revenue": ("revenue", "turnover"),
    "cost_of_sales": ("cost of sales",),
    "gross_profit": ("gross profit",),
    "operating_profit": ("operating profit",),
    "profit_before_tax": ("profit before tax",),
    "income_tax_expense": (
        "income tax expense",
        # Swadeshi Industrial Works PLC's real FY2025/26 income statement
        # (17 Aug) — the line's own printed wording carries the
        # loss-period alternative inline rather than as a separate line,
        # unlike every other canonical key's variants seen so far. Found
        # live: without this, `income_tax_expense` — and therefore
        # `effective_tax_rate` and every model that needs it (DCF, WACC's
        # cost of debt) — silently failed to extract for this real
        # filing despite every other required DCF input succeeding.
        "income tax (expense) / reversal",
    ),
    "net_income": ("profit for the year", "profit for the period"),
    "total_comprehensive_income": ("total comprehensive income for the year", "total comprehensive income for the period"),
    # Cash-flow-statement lines — verified against TWO real, independent
    # filings: J.F. Packaging PLC's FY2025/26 statement of cash flow
    # (first) and Swadeshi Industrial Works PLC's FY2025/26 statement of
    # cash flows (second, 17 Aug — deliberately sought out to check
    # whether one company's wording generalised, per this file's own
    # "expand as more real filings are processed rather than guessing"
    # rule). It did NOT: every one of these four line concepts is worded
    # completely differently between the two companies — proof this
    # discipline is load-bearing, not decorative. See
    # _STATEMENT_PAGE_MARKERS in app.ingestion.financial_pdf_extractor,
    # and PARAMETERS.md #9's history of this gap. "Cash generated from/
    # (Used in) Operations" (JFP) is the pre-tax, pre-interest subtotal —
    # a real, differently-named line on the same statement — and is
    # deliberately NOT mapped to `cash_flow_from_operations`, which is
    # the figure after tax and interest paid, the one `app.domain.
    # ratios`' cash-flow ratios and §18's FCFF both mean by "CFO."
    # Named `cash_flow_from_operations` to match the key
    # `app.domain.ratios.NOT_YET_COMPUTABLE` has used since Phase 2 for
    # this exact concept, rather than inventing a second name for the
    # same figure across the two modules.
    "cash_flow_from_operations": (
        "net cash flow from/ (used in) operating activities",  # JFP
        "net cash from / used in operating activities",  # SWAD
    ),
    "net_cash_from_investing_activities": (
        "net cash flow generated from / (used in) investing activities",  # JFP
        "net cash flows (used in) / from investing activities",  # SWAD
    ),
    "net_cash_from_financing_activities": (
        "net cash flow generated from / (used in) financing activities",  # JFP
        "net cash flows from /(used in) financing activities",  # SWAD
    ),
    "net_increase_in_cash": (
        "net increase/(decrease) in cash & cash equivalents during the year",  # JFP
        "net (decrease) / increase in cash and cash equivalents",  # SWAD
    ),
    # Combined D&A on one line, verified on J.F. Packaging PLC. Swadeshi
    # Industrial Works PLC reports "Depreciation" and "Amortization" as
    # two SEPARATE lines instead — `depreciation_expense` and
    # `amortisation_expense` below capture those individually, and
    # `derive_combined_depreciation_and_amortisation` sums them into this
    # same canonical concept when the combined line itself isn't present,
    # so the two wordings converge on one figure rather than needing every
    # caller to know which shape a given company uses.
    "depreciation_and_amortisation": ("depreciation / amortization",),  # JFP
    # Verified on Swadeshi Industrial Works PLC only, and deliberately
    # scoped to statement pages (_STATEMENT_PAGE_MARKERS) — a bare
    # "Depreciation" is common enough wording that matching it outside
    # the primary statements (e.g. a PP&E movement note) would be a real
    # false-positive risk; on the cash-flow-statement page specifically
    # it has never meant anything else in either filing checked so far.
    "depreciation_expense": ("depreciation",),  # SWAD
    "amortisation_expense": ("amortization",),  # SWAD
    # Capital expenditure — genuinely NEW as of this filing. J.F.
    # Packaging PLC's equivalent label ("Purchase & Construction of
    # Property, Plant & Equipment & Intangible Assets") wraps across two
    # physical lines on that statement and was left unmapped for exactly
    # that reason (see this module's earlier commit); Swadeshi's shorter
    # label doesn't wrap, so this key is extractable for at least this
    # wording. PP&E only — Swadeshi reports "Acquisition of Intangible
    # Assets" as a separate, smaller line this key deliberately excludes,
    # so a company with material intangible capex will read slightly
    # low here, a real, stated incompleteness rather than a silent one.
    "capital_expenditure": ("acquisition of property, plant and equipment",),  # SWAD
    # The two bookend subtotals of the operating-activities working-
    # capital section — verified on BOTH real filings, and the reason
    # `change_in_net_working_capital` below can be derived at all without
    # summing an unpredictable, company-varying set of component lines
    # (J.F. Packaging lists 5 such lines — inventories, receivables,
    # payables, amounts due from/to related parties; Swadeshi lists 4
    # differently-named ones — inventories, receivables, advances and
    # prepayments, payables). "Operating Profit before Working Capital
    # Changes" is worded byte-identically on both companies' statements,
    # a genuine, confirmed reusable label rather than one that happened
    # to match once. "Cash generated from Operations" (the subtotal AFTER
    # working-capital movements, BEFORE tax and interest — the same line
    # `cash_flow_from_operations`'s own docstring already distinguishes
    # from CFO) needed a second wording, same as every other cash-flow
    # line here.
    "operating_profit_before_working_capital_changes": (
        "operating profit before working capital changes",  # JFP + SWAD, identical
    ),
    "cash_generated_from_operations": (
        "cash generated from/ (used in) operations",  # JFP
        "cash generated from operations",  # SWAD
    ),
    # WACC's cost-of-debt input — verified on Swadeshi Industrial Works
    # PLC's real balance sheet, where "Interest Bearing Loans and
    # Borrowings" prints TWICE, byte-identically, once under Non-current
    # Liabilities (11,672,993) and once under Current Liabilities
    # (634,163,111) — the standard maturity-split presentation for one
    # debt figure. See `SUM_ACROSS_OCCURRENCES` below: this key is
    # deliberately summed across every match on the statement rather
    # than keeping only the first (which would silently keep the smaller
    # non-current portion and drop the much larger current one).
    "total_interest_bearing_debt": (
        "interest bearing loans and borrowings",  # SWAD
        "interest bearing borrowings",  # JFP — ALSO prints twice, same reason
    ),
    # The cash-flow statement's own interest-expense figure — the
    # non-cash add-back line, not "... Paid" (a real, differently-worded
    # line on the same statement, the cash actually disbursed, which is
    # NOT what a WACC cost-of-debt calculation wants — that wants the
    # period's expense, whether or not it was paid in cash this period).
    "interest_expense": (
        "finance costs",  # SWAD
        "interest expense",  # JFP — same cash-flow-statement accrual add-back concept
    ),
    # Working-capital STOCK components (§18's `working_capital_pct_
    # revenue`) — verified on BOTH real balance sheets, where "Inventories",
    # "Trade and Other Receivables" and "Trade and Other Payables" are
    # byte-identical wording across both companies. Neither company's
    # component SET is complete on its own — J.F. Packaging breaks out
    # related-party amounts Swadeshi doesn't have; Swadeshi has "Advances
    # and Prepayments" J.F. Packaging doesn't — which is exactly why
    # `derive_net_working_capital` below sums WHICHEVER of these are
    # present for a given company rather than requiring all of them.
    # Cross-checked against each statement's own totals: (Total Current
    # Assets - Cash - tax/other non-operating items) and (Total Current
    # Liabilities - debt - tax) both equal the sum of exactly these
    # components on both real filings, confirming this is the right set
    # rather than an arbitrary one.
    "inventories": ("inventories",),  # JFP + SWAD, identical
    "trade_receivables": ("trade and other receivables",),  # JFP + SWAD, identical
    "trade_payables": ("trade and other payables",),  # JFP + SWAD, identical
    "advances_and_prepayments": ("advances and prepayments",),  # SWAD
    "amounts_due_from_related_parties_trade": ("amounts due from related parties - trade",),  # JFP
    "amounts_due_from_related_parties_non_trade": ("amounts due from related parties - non trade",),  # JFP
    "amounts_due_to_related_parties_trade": ("amounts due to related parties - trade",),  # JFP
    "amounts_due_to_related_parties_non_trade": ("amounts due to related parties - non trade",),  # JFP
    # §22 rule 1's hard-book input — verified against FOUR real filings,
    # deliberately sought out in the sector §22 itself names ("plantations,
    # property and hotels"), and genuinely NOT one consistent shape.
    # Kelani Valley Plantations PLC's real Statement of Financial Position
    # has NO revaluation-related equity line at all — real, verified,
    # zero-nonzero evidence, not an extraction gap: Sri Lanka's regional
    # plantation companies (KVPL among them) hold estate land on 99-year
    # GOVERNMENT LEASES from the 1992 privatisation, not freehold, so
    # freehold PP&E/bearer biological assets are carried at cost, and
    # there is nothing to revalue. Asian Hotels and Properties PLC (owns
    # Cinnamon Grand Colombo) prints a single COMBINED line instead,
    # "Other components of equity" — CORRECTED 17 Aug, re-verified
    # directly against the actual currently-public filing after an
    # earlier version of this comment cited a later FY2025/26 report and
    # figures that could not be found or reproduced: AHPL's real FY2023/24
    # Statement of Financial Position (page 164, downloaded fresh from
    # `https://cdn.cse.lk/cmt/upload_report_file/690_1716340840640.pdf`)
    # prints "Other components of equity 23 21,752,125 20,613,338
    # 21,142,080 20,112,228" — extracted end-to-end through the real
    # pipeline (`extract_financial_statement_candidates`) without a
    # notes-page or double-count issue. Its own Statement of Changes in
    # Equity/Note 23 (a differently-shaped, multi-reserve-column statement
    # this extractor cannot parse — see below) breaks the combined figure
    # down into a Revaluation Reserve plus a smaller Other Capital
    # Reserve, confirming the combined line is REVALUATION-DOMINATED for
    # this company but is NOT a pure revaluation-reserve figure — used
    # here as the best genuinely available real proxy, never silently
    # presented as an exact revaluation figure (see `app.domain.
    # valuation_view.hard_book_for`'s own docstring). Galadari
    # Hotels (Lanka) PLC's real FY2025 Statement of Financial Position
    # prints a genuinely PURE, standalone "Revaluation reserve" line
    # (6,454,099,241) — no bundling at all — but that filing's statement is
    # two-column (2025/2024 only, no Group/Company split), which this
    # extractor's note-reference-stripping heuristic does not yet handle
    # (see DEFAULT_EXPECTED_VALUE_COLUMNS's own "KNOWN LIMITATION" comment)
    # — added as a verified real wording for when a 4-column filing uses it,
    # but Galadari's OWN filing is not correctly end-to-end extractable
    # through this pipeline today, a pre-existing, separately-tracked gap,
    # not fixed here. Ceylon Hotels Corporation PLC and Serendib Hotels PLC
    # were also checked and bundle the same way AHPL does, but each under a
    # generic wording ("Reserves", "Other Components of Equity") too broad
    # or duplicative to add safely as further variants.
    # Deliberately NOT in SUM_ACROSS_OCCURRENCES below: unlike
    # total_interest_bearing_debt, a revaluation/other-components-of-
    # equity balance has no current/non-current maturity split to sum —
    # it is one number, printed once, on every real filing checked.
    "revaluation_reserves": (
        "other components of equity",  # AHPL — combined, revaluation-dominated proxy (verified end-to-end)
        "revaluation reserve",  # Galadari — pure, but not yet live-extractable (2-column filing)
    ),
}

#: The working-capital STOCK's two sides — see `derive_net_working_
#: capital`. A company's own filing determines which of these are
#: actually present; summing "whichever apply" rather than requiring a
#: fixed set is what makes this generalise across two real filings with
#: genuinely different component breakdowns.
NET_WORKING_CAPITAL_ASSET_COMPONENTS: frozenset[str] = frozenset(
    {
        "inventories",
        "trade_receivables",
        "advances_and_prepayments",
        "amounts_due_from_related_parties_trade",
        "amounts_due_from_related_parties_non_trade",
    }
)
NET_WORKING_CAPITAL_LIABILITY_COMPONENTS: frozenset[str] = frozenset(
    {
        "trade_payables",
        "amounts_due_to_related_parties_trade",
        "amounts_due_to_related_parties_non_trade",
    }
)

#: Canonical keys where multiple occurrences on the same statement are
#: expected — the standard current/non-current maturity split for one
#: balance-sheet concept — and should be SUMMED into one figure rather
#: than the usual "first occurrence wins, the rest are dropped" rule
#: `build_fundamental_drafts` otherwise applies. Kept as an explicit
#: allowlist rather than a default behaviour, because most repeated
#: canonical matches on a real page ARE a bug worth catching (see
#: `build_fundamental_drafts`'s own "shouldn't happen given the page-
#: marker filter, but PDFs are messy" comment) — this set names the
#: specific, verified exception to that rule, not a blanket assumption
#: that a repeat is always fine to sum.
SUM_ACROSS_OCCURRENCES: frozenset[str] = frozenset({"total_interest_bearing_debt"})

_LABEL_TO_STATEMENT_LINE: dict[str, str] = {
    variant: key for key, variants in CANONICAL_LABELS.items() for variant in variants
}


def normalize_label(text: str) -> str:
    """Lowercase, collapse whitespace, strip a handful of decorations
    that appear in real headers but carry no meaning for matching (unit
    annotations, footnote markers)."""
    cleaned = text.strip().lower()
    cleaned = re.sub(r"\(rs\.?\s*'?000\)?", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -")


def match_canonical_label(label: str) -> str | None:
    return _LABEL_TO_STATEMENT_LINE.get(normalize_label(label))


# REAL BUG, FOUND LIVE (18 Aug 2026): every value this module ever
# extracted was stored exactly as printed, with no unit-scale conversion
# at all. `normalize_label` above already recognised a "(Rs.'000)"-style
# annotation — but only to STRIP it as label noise, never to capture it
# and scale the VALUE. Confirmed by downloading COMB.N0000's real
# 30.06.2026 interim statement PDF directly and reading its own balance-
# sheet page: the column header literally reads "Rs.'000 Rs.'000 % Rs.'000
# Rs.'000", and the stored `total_equity` figure (363,888,905) is exactly
# 1000x too small to be COMB's real total equity — the true value is
# LKR 363,888,905,000 (≈364 billion), the only figure in the right order
# of magnitude for Sri Lanka's largest private bank by assets. Every
# downstream fair value computed from an unscaled figure was wrong by the
# same 1000x.
#
# NOT EVERY CSE FILING IS IN THOUSANDS, THOUGH — a real, already-verified
# counter-example already lived in this project's own test fixtures
# before this fix: Swadeshi Industrial Works PLC's real FY2025/26
# statements print "Rs. Rs. Rs. Rs." as their column header (see
# BALANCE_SHEET_TEXT_SWAD/INCOME_STATEMENT_TEXT_SWAD in test_financial_
# statement_parsing.py) — genuinely FULL Rupee values, no scaling at all
# (Revenue of 4,649,049,764 is a real ~4.6bn LKR annual figure for that
# company; interpreted as thousands it would be an impossible 4.6
# TRILLION). A single "always multiply by 1000" fix would have been
# WRONG for this real, already-known case — this is why detection, not a
# blanket assumption, is required.
#
# Three real, verified thousands-declaration wordings feed
# `_UNIT_THOUSANDS_RE`: J.F. Packaging PLC's "Rs.000" (no apostrophe),
# Asian Hotels & Properties PLC's "In Rs.'000s" (apostrophe + trailing
# "s"), and Commercial Bank of Ceylon PLC's "Rs.'000" (apostrophe, no
# trailing "s") — real evidence from three independently-verified real
# filings, not one pattern generalised from a single example.
# `_UNIT_FULL_VALUE_RE` requires "Rs." to repeat at least twice
# consecutively (matching Swadeshi's real "Rs. Rs. Rs. Rs." header
# exactly) rather than matching on a single stray "Rs." anywhere on the
# page, which could appear incidentally in unrelated body text.
#
# THE APOSTROPHE ITSELF HAS TWO REAL ENCODINGS, FOUND LIVE. COMB.N0000's
# own real 2019 annual report (a different filing/toolchain vintage from
# its 2026 interim statement checked first) renders the SAME "Rs.'000"
# declaration with a Unicode RIGHT SINGLE QUOTATION MARK (U+2019, "’"),
# not the straight ASCII apostrophe (U+0027, "'") the original pattern
# only matched — pdfplumber decodes whichever glyph the PDF's own
# embedded font actually maps to that position, and this is a genuine,
# observed difference across real filings, not an OCR error. Confirmed
# by inspecting the exact codepoint on a real downloaded PDF
# (`Rs. ’000`) after this exact gap silently dropped 11 real,
# extractable statement/summary pages (including the real primary
# balance sheet on page 142) from that one filing alone — caught by a
# dedicated diagnostic run, not by re-reading the regex in the abstract.
#
# THE CURRENCY PREFIX ITSELF ISN'T ALWAYS "RS." EITHER. Nations Trust
# Bank PLC's real interim statement for the six months ended 30 June
# 2026 declares its units as "LKR '000" on its real Statement of Cash
# Flows page — never "Rs." at all. This is a genuine, verified fourth
# wording variant, not a guess: the original "rs"-only pattern refused
# every one of NTB.N0000's real primary-statement pages (0 drafts
# produced across two separate backfill runs) even though a real,
# well-formed unit declaration WAS present on the page, just spelled
# with a different currency abbreviation. Found live via a dedicated
# diagnostic download of NTB.N0000's own real filing, the same method
# used for the two gaps documented above.
_UNIT_THOUSANDS_RE = re.compile(r"(?:rs\.?|lkr)\s*['’]?000s?\b")
_UNIT_FULL_VALUE_RE = re.compile(r"(?:\brs\.\s*){2,}")


def detect_unit_scale(page_text: str) -> Decimal | None:
    """The multiplier every value extracted from this page must be
    multiplied by to reach real LKR — `Decimal(1000)` for a confirmed
    "Rs.'000"-style declaration, `Decimal(1)` for a confirmed "Rs."
    (full-value, no scaling) declaration.

    `None` — never a guessed default — when NEITHER pattern is found
    anywhere on the page. §5's own extraction pipeline has already shown
    real filings use genuinely different units (see the module-level
    comment above); silently assuming either 1 or 1000 for an
    undetected case would produce exactly the "plausible wrong number"
    failure mode `check_accounting_identities` exists to catch for
    arithmetic errors — but a uniform 1000x scale error passes every one
    of those identity checks (both sides of `assets = equity +
    liabilities` are wrong by the same factor), so detection has to be
    the first line of defence here, not a fallback. The caller (`app.
    ingestion.financial_pdf_extractor.extract_financial_statement_
    candidates`) skips a page entirely when this returns `None`, the
    same "refuse rather than guess" rule `classify_period_type` and
    `resolve_first_available_date` already apply to their own
    can't-tell cases.

    NOT APPLICABLE TO PER-SHARE LINES. A page-wide scale is correct for
    balance-sheet/income-statement totals, but NOT for a per-share figure
    like EPS (real filings print EPS in actual Rupees even on a page
    whose other lines are in thousands — verified on J.F. Packaging
    PLC's own real statement: "Diluted EPS (Rs.) ... 1.37"). No canonical
    key in `CANONICAL_LABELS` currently maps EPS, so this doesn't yet
    create a real double-scaling risk — but it would the moment one did,
    and that key would need to be excluded from page-wide scaling rather
    than assumed to follow it."""
    lower = page_text.lower()
    if _UNIT_THOUSANDS_RE.search(lower):
        return Decimal(1000)
    if _UNIT_FULL_VALUE_RE.search(lower):
        return Decimal(1)
    return None


def _parse_value_token(token: str) -> Decimal | None:
    if token == _NIL:
        return None
    negative = token.startswith("(") and token.endswith(")")
    digits = token.strip("()").replace(",", "")
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


@dataclass(frozen=True)
class ExtractedLine:
    raw_label: str
    statement_line: str | None  # None if the label didn't match any canonical key
    values: tuple[Decimal | None, ...]  # in the order printed, left to right
    raw_text: str

    @property
    def primary_value(self) -> Decimal | None:
        """The first (left-most) numeric column. CSE statements
        conventionally list the most recent period first and Group before
        Company — verified on J.F. Packaging PLC — but this is a
        convention, not a guarantee; every column CSE actually printed is
        preserved in `raw_text` for a human reviewer to check before
        confirming."""
        return self.values[0] if self.values else None


def split_label_and_values(
    line: str, expected_value_columns: int = DEFAULT_EXPECTED_VALUE_COLUMNS
) -> ExtractedLine | None:
    """Right-to-left token scan: pull numeric-looking tokens off the end
    of the line until hitting one that isn't a value, a note reference, or
    a nil marker. Returns None if the line has no trailing numeric tokens
    at all (i.e. it's not a data line — a heading, a page footer, etc.).
    """
    tokens = _repair_split_thousands(line).split()
    i = len(tokens)
    while i > 0 and (_VALUE_RE.match(tokens[i - 1]) or _NOTE_REF_RE.match(tokens[i - 1]) or tokens[i - 1] == _NIL):
        i -= 1

    numeric_tokens = tokens[i:]
    label_tokens = tokens[:i]
    if not numeric_tokens or not label_tokens:
        return None

    # Drop a leading note-reference token: one more numeric token than the
    # statement's own declared column count, AND that extra leading token
    # is shaped like a note reference (short, comma-free, optionally
    # dot-separated) — see DEFAULT_EXPECTED_VALUE_COLUMNS above for why
    # count is the signal, not the token's shape alone (a bare "5" or
    # "13.2" is indistinguishable from a real small/decimal value on
    # shape).
    if len(numeric_tokens) > expected_value_columns and _NOTE_REF_RE.match(numeric_tokens[0]):
        numeric_tokens = numeric_tokens[1:]

    values = tuple(_parse_value_token(t) for t in numeric_tokens)
    if all(v is None for v in values):
        return None  # every token was a bare "-" — not useful, and likely not a real data line

    label = " ".join(label_tokens)
    return ExtractedLine(
        raw_label=label,
        statement_line=match_canonical_label(label),
        values=values,
        raw_text=line,
    )


@dataclass(frozen=True)
class IdentityCheck:
    name: str
    passed: bool
    detail: str


def check_accounting_identities(values: dict[str, Decimal]) -> list[IdentityCheck]:
    """Independent arithmetic checks on an extracted period.

    A statement that doesn't balance means the extraction is wrong, and
    this catches classes of corruption no regex can — it was an identity
    failure (equity + liabilities != assets) that exposed the split-
    thousands bug, because the two sides were mangled by different
    amounts. Cheap, deterministic, and it fails loudly on exactly the
    error mode that is otherwise invisible: a plausible wrong number.

    Only checks identities where BOTH sides were extracted; a missing
    line item is not a failure, it's simply not checkable.
    """
    checks: list[IdentityCheck] = []

    def have(*keys: str) -> bool:
        return all(k in values for k in keys)

    # Assets = Equity + Liabilities
    if have("total_assets", "total_equity", "total_liabilities"):
        lhs = values["total_assets"]
        rhs = values["total_equity"] + values["total_liabilities"]
        ok = lhs == rhs
        checks.append(
            IdentityCheck(
                "assets = equity + liabilities",
                ok,
                f"{lhs:,} vs {rhs:,}" + ("" if ok else f" — differs by {abs(lhs - rhs):,}"),
            )
        )

    # The balance sheet's own footing line must agree with total assets.
    if have("total_assets", "total_equity_and_liabilities"):
        lhs, rhs = values["total_assets"], values["total_equity_and_liabilities"]
        ok = lhs == rhs
        checks.append(IdentityCheck("assets = equity and liabilities", ok, f"{lhs:,} vs {rhs:,}"))

    # Current + non-current = total, both sides of the balance sheet.
    if have("total_assets", "total_current_assets", "total_non_current_assets"):
        lhs = values["total_assets"]
        rhs = values["total_current_assets"] + values["total_non_current_assets"]
        ok = lhs == rhs
        checks.append(IdentityCheck("assets = current + non-current", ok, f"{lhs:,} vs {rhs:,}"))

    if have("total_liabilities", "total_current_liabilities", "total_non_current_liabilities"):
        lhs = values["total_liabilities"]
        rhs = values["total_current_liabilities"] + values["total_non_current_liabilities"]
        ok = lhs == rhs
        checks.append(IdentityCheck("liabilities = current + non-current", ok, f"{lhs:,} vs {rhs:,}"))

    # Revenue - cost of sales = gross profit (cost stored negative).
    if have("revenue", "cost_of_sales", "gross_profit"):
        lhs = values["revenue"] + values["cost_of_sales"]
        rhs = values["gross_profit"]
        ok = lhs == rhs
        checks.append(IdentityCheck("revenue - cost of sales = gross profit", ok, f"{lhs:,} vs {rhs:,}"))

    # Profit before tax - tax = profit for the period (tax stored negative).
    if have("profit_before_tax", "income_tax_expense", "net_income"):
        lhs = values["profit_before_tax"] + values["income_tax_expense"]
        rhs = values["net_income"]
        ok = lhs == rhs
        checks.append(IdentityCheck("pre-tax profit - tax = net income", ok, f"{lhs:,} vs {rhs:,}"))

    # CFO + investing + financing = net change in cash — the cash-flow
    # statement's own footing line. Verified against J.F. Packaging PLC's
    # real FY2025/26 figures: 174,382 + (-244,852) + 12,302 = -58,168,
    # exactly matching the printed "Net Increase/(Decrease) in Cash".
    if have(
        "cash_flow_from_operations",
        "net_cash_from_investing_activities",
        "net_cash_from_financing_activities",
        "net_increase_in_cash",
    ):
        lhs = (
            values["cash_flow_from_operations"]
            + values["net_cash_from_investing_activities"]
            + values["net_cash_from_financing_activities"]
        )
        rhs = values["net_increase_in_cash"]
        ok = lhs == rhs
        checks.append(
            IdentityCheck("CFO + investing + financing = net change in cash", ok, f"{lhs:,} vs {rhs:,}")
        )

    return checks


#: Canonical keys that get derived by summing OTHER canonical keys, and
#: exactly which ones. Kept as data (not scattered ad-hoc across callers)
#: so `derive_additional_line_items` stays a single, inspectable place —
#: adding a second derived concept later is a new dict entry, not a new
#: function.
DERIVED_SUMS: dict[str, tuple[str, ...]] = {
    "depreciation_and_amortisation": ("depreciation_expense", "amortisation_expense"),
}

#: Canonical keys derived as (minuend - subtrahend) of two OTHER
#: canonical keys — the same "data, not a hardcoded branch" discipline
#: as DERIVED_SUMS, for concepts that are a DIFFERENCE rather than a
#: total. `change_in_net_working_capital`: the operating-activities
#: section of the cash-flow statement runs
#:   Operating Profit before Working Capital Changes
#:     + (net cash effect of every working-capital line item)
#:     = Cash generated from Operations
#: — verified on BOTH J.F. Packaging PLC and Swadeshi Industrial Works
#: PLC's real filings, where the two bookend subtotals are consistently
#: worded even though the individual component lines between them are
#: not (5 differently-named lines on one filing, 4 on the other — see
#: CANONICAL_LABELS' own comment on these two keys). Rearranging:
#:   net cash effect = cash_generated_from_operations
#:                        - operating_profit_before_working_capital_changes
#: which is POSITIVE when working capital released cash and NEGATIVE
#: when it absorbed cash. §18's DCF convention is the opposite sign — an
#: INCREASE in net working capital (cash absorbed) is a POSITIVE
#: `change_in_net_working_capital` that REDUCES FCFF when subtracted —
#: so the derived value here is the negation, expressed directly as
#: (operating_profit_before_working_capital_changes - cash_generated_
#: from_operations) rather than computing the cash effect and flipping
#: its sign in a second step. Verified against J.F. Packaging's real
#: figures: 681,378 - 493,497 = 187,881, matching the independently
#: hand-summed total of all 5 real working-capital component lines on
#: that filing exactly.
DERIVED_DIFFERENCES: dict[str, tuple[str, str]] = {
    "change_in_net_working_capital": (
        "operating_profit_before_working_capital_changes",
        "cash_generated_from_operations",
    ),
}


def derive_additional_line_items(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Canonical concepts that only exist as an arithmetic combination of
    OTHER extracted lines on at least one real filing shape — currently:

      - `depreciation_and_amortisation`, when a company reports
        Depreciation and Amortization as two separate cash-flow-statement
        lines (verified: Swadeshi Industrial Works PLC) rather than one
        combined line (verified: J.F. Packaging PLC).
      - `change_in_net_working_capital`, computed from the two bookend
        subtotals of the working-capital-changes section rather than
        summing its unpredictable, company-varying set of component
        lines — see `DERIVED_DIFFERENCES`'s own comment for the identity
        this rests on.
      - `net_working_capital` (the STOCK §18's `working_capital_pct_
        revenue` needs, a different figure from the CHANGE above), summed
        from `NET_WORKING_CAPITAL_ASSET_COMPONENTS` minus
        `NET_WORKING_CAPITAL_LIABILITY_COMPONENTS` — WHICHEVER of each
        group's keys are actually present for a given company, since the
        two real filings this was verified against have genuinely
        different component breakdowns (see those constants' own
        comment).

    All three follow the same core rules: a key is only derived when its
    required inputs are present, and NEVER when the key itself was
    already directly extracted (a company that prints a figure directly
    is trusted on that figure, never silently overwritten by a derived
    one computed from elsewhere on the same page). A partial derivation
    is never produced either — a missing input skips that key entirely
    rather than guessing, which would look exactly as precise as a real
    figure while being wrong. `net_working_capital` applies this same
    "no partial derivation" rule at the GROUP level: at least one asset
    component AND at least one liability component must be present, or
    nothing is derived — a one-sided figure (all assets, no liabilities
    counted) would look like a real net position while actually being
    gross assets alone.
    """
    derived: dict[str, Decimal] = {}
    for target_key, component_keys in DERIVED_SUMS.items():
        if target_key in values:
            continue
        if all(k in values for k in component_keys):
            derived[target_key] = sum((values[k] for k in component_keys), Decimal(0))

    for target_key, (minuend_key, subtrahend_key) in DERIVED_DIFFERENCES.items():
        if target_key in values:
            continue
        if minuend_key in values and subtrahend_key in values:
            derived[target_key] = values[minuend_key] - values[subtrahend_key]

    if "net_working_capital" not in values:
        asset_keys_present = [k for k in NET_WORKING_CAPITAL_ASSET_COMPONENTS if k in values]
        liability_keys_present = [k for k in NET_WORKING_CAPITAL_LIABILITY_COMPONENTS if k in values]
        if asset_keys_present and liability_keys_present:
            assets_total = sum((values[k] for k in asset_keys_present), Decimal(0))
            liabilities_total = sum((values[k] for k in liability_keys_present), Decimal(0))
            derived["net_working_capital"] = assets_total - liabilities_total

    return derived


def extract_candidate_lines(
    page_text: str, expected_value_columns: int = DEFAULT_EXPECTED_VALUE_COLUMNS
) -> list[ExtractedLine]:
    """All parseable lines from one page's text, not just canonical
    matches — callers that want only line items usable as Fundamental
    drafts should filter on `.statement_line is not None`, but keeping
    everything here makes this function's output independently
    inspectable/debuggable."""
    results = []
    for raw_line in page_text.splitlines():
        parsed = split_label_and_values(raw_line, expected_value_columns)
        if parsed is not None:
            results.append(parsed)
    return results
