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
_NOTE_REF_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){0,3}$")
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
    "income_tax_expense": ("income tax expense",),
    "net_income": ("profit for the year", "profit for the period"),
    "total_comprehensive_income": ("total comprehensive income for the year", "total comprehensive income for the period"),
}

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

    return checks


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
