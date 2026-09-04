"""
Master Spec §5: "Company financials (quarterly + annual) — CSE company
disclosures (PDF), annual reports — Quarterly / annual — PDF table
extraction -> LLM-assisted line-item mapping -> mandatory human confirm
queue."

This is the Phase-1 version of that pipeline. It is NOT the LLM-assisted
mapping the spec ultimately describes — see
app.domain.financial_statement_parsing's module docstring for why an
actual LLM integration is tracked as an open decision rather than baked
in here. What this module does provide, verified against a real filing:

  1. `fetch_recent_financial_announcements` — the verified
     `getFinancialAnnouncement` endpoint (README_ENDPOINTS.md). It's a
     GLOBAL feed (the `symbol` parameter is silently ignored — verified
     by comparing two different symbol values and getting byte-identical
     responses) of the ~180 most recent filings across every listed
     company, not a per-company historical archive — fine for
     event-driven "a new filing just landed" ingestion (§52), not for
     backfilling history (Part O #2).
  2. `download_pdf` — fetches the PDF from CSE's CDN.
  3. `extract_financial_statement_candidates` — runs
     app.domain.financial_statement_parsing over the statement pages only
     (identified by header text, not the whole ~160-page document — notes
     pages reuse words like "Total" for sub-schedules and would otherwise
     produce false matches), and scales every value to real LKR via
     app.domain.financial_statement_parsing.detect_unit_scale — a REAL
     bug, found live (18 Aug 2026) against COMB.N0000's real filing: this
     function used to store every value exactly as printed, off by 1000x
     on any "Rs.'000"-declared statement (see that function's own
     docstring for the full finding and why a blanket "always multiply by
     1000" fix would itself have been wrong for at least one already-
     verified real filing).
  4. `build_fundamental_drafts` — turns candidates into draft
     `Fundamental` rows, provenance_tier=AI_ASSISTED, confirmed_by=None
     always. See app.api.routes.fundamentals for the confirm workflow.
  5. `build_derived_fundamental_drafts` — a second, smaller pass for
     canonical concepts that only exist as a SUM of other extracted
     lines on some companies' filings (e.g. combined depreciation &
     amortisation, when a company reports the two separately) — see
     app.domain.financial_statement_parsing.derive_additional_line_items
     for which sums, and why a derived draft's `source_snippet` cites
     its components rather than quoting one printed line, because there
     isn't one.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import io
import logging
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
import pdfplumber
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.financial_statement_parsing import (
    DEFAULT_EXPECTED_VALUE_COLUMNS,
    DERIVED_DIFFERENCES,
    DERIVED_SUMS,
    NET_WORKING_CAPITAL_ASSET_COMPONENTS,
    NET_WORKING_CAPITAL_LIABILITY_COMPONENTS,
    SUM_ACROSS_OCCURRENCES,
    ExtractedLine,
    check_extraction_quality,
    derive_additional_line_items,
    detect_expected_value_columns,
    detect_unit_scale,
    extract_candidate_lines,
    reconcile_ambiguous_values_via_identities,
    reconcile_magnitude_implausible_values,
    repair_character_doubling,
)
from app.ingestion.cse_client import CseClient
from app.ingestion.schemas import FinancialAnnouncementResponse, FinancialAnnouncementRow
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental

logger = logging.getLogger("cse_alpha.ingestion.financial_pdf_extractor")

_SRI_LANKA_TZ = ZoneInfo("Asia/Colombo")
_CDN_BASE_URL = "https://cdn.cse.lk/"

# Header phrases that mark a page as a primary statement page, verified
# against J.F. Packaging PLC. Restricting extraction to these pages (out
# of a document that can run 100+ pages) is deliberate — notes/schedule
# pages elsewhere reuse words like "Total" for unrelated sub-totals.
_STATEMENT_PAGE_MARKERS = (
    "statement of financial position",
    "statement of profit or loss",
    "income statement",
    "statement of cash flow",  # verified: J.F. Packaging PLC's FY2025/26 header, singular "flow"
    # Panasian Power PLC's (PAP.N0000) real interim statement for the
    # quarter ended 30 June 2026 titles its income statement page
    # "STATEMENT OF COMPREHENSIVE INCOME" — no "profit or loss" wording
    # at all, a genuinely different real title from every filing checked
    # so far (J.F. Packaging PLC's own equivalent page is titled
    # "STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME",
    # matching the marker above already). Verified this phrase appears
    # on exactly one real page of PAP's own filing (the genuine income
    # statement) and nowhere else in it, so adding it does not risk
    # pulling in an unrelated note/schedule page for this filing.
    "statement of comprehensive income",
)

# A real, verified false-positive: J.F. Packaging PLC's Note 25
# ("Financial Instruments") is subtitled "25.1. Financial Instruments -
# Statement of Financial Position" — the note's OWN heading literally
# contains a `_STATEMENT_PAGE_MARKERS` phrase, so it passed the marker
# filter and its figures (a genuine, exact reprint of the real balance-
# sheet debt lines, not a coincidental wording collision) got counted as
# a SECOND real occurrence of `total_interest_bearing_debt`, doubling it.
# Caught by a real end-to-end run against the live PDF, not a fixture —
# `SUM_ACROSS_OCCURRENCES` genuinely can't tell "the same figure legally
# reprinted in a note" from "two real, distinct maturity-split amounts"
# without this. CSE annual reports consistently header every notes page
# this way (this project's own earliest test fixture for the ORIGINAL
# "notes reuse words like Total" risk already used exactly this phrase),
# so it is checked FIRST and unconditionally excludes the page,
# regardless of which positive marker also happens to match.
#
# SECOND real case, found live tracing HNB.N0000's real ~15x net_income
# error (27 Aug 2026, R1_VALIDATION.md's own named, unfixed finding):
# HNB's real FY2024 annual report has a note, "34 (d) Summarised
# Statement Of Profit Or Loss Of Joint Venture - Acuity Partners (Pvt)
# Ltd and its Subsidiaries" (page 403), that prints a miniature income
# statement for its OWN joint venture — same canonical labels (Revenue,
# Profit before tax, Profit for the year...) as HNB's real consolidated
# statement, but a completely different, much smaller entity's figures.
# It does NOT contain "notes to the" (it's a continuation page deep
# inside note 34, not the notes section's own opening header), so the
# existing marker missed it, and it happens to appear BEFORE HNB's own
# real income statement in page order — "first occurrence wins"
# (`build_fundamental_drafts`) then kept the joint venture's own
# net_income as if it were HNB's. "Summarised Statement of ..." is a
# reliable, generalisable signal distinct from this marker's first case:
# a genuine PRIMARY statement is never described as "summarised" in its
# own real heading (summarised implies an abbreviated recap of a fuller
# statement located elsewhere — i.e. note content, by definition), so
# this catches the same shape for ANY company's joint-venture/associate/
# segment sub-schedule, not just Acuity Partners specifically.
_NOTES_PAGE_MARKERS = ("notes to the", "summarised statement of", "summarized statement of")

# THIRD real case, found live in the SAME HNB.N0000 investigation as the
# marker tuple above, tracing why the fix for the second case still
# wasn't enough: HNB's real PRIMARY income statement page (its own
# genuine "STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME")
# was ALSO being excluded — by the FIRST marker, "notes to the", firing
# on this completely ordinary footer line every real primary statement
# page in this filing carries: "The notes to the financial statements
# from pages 298 to 466 form an integral part of these financial
# statements." (verified: line 39 of 41 on that real page — a footer
# disclosure, not a section header). `_NOTES_PAGE_MARKERS` was built and
# verified only against genuine notes-SECTION headers, which real
# filings checked so far always print within the first few lines of the
# page (J.F. Packaging's own "NOTES TO THE CONSOLIDATED FINANCIAL
# STATEMENTS" sits on line 1) — never against a page whose exclusion
# marker shows up as ordinary running/footer text instead. Scoping the
# `_NOTES_PAGE_MARKERS` check to the page's own first
# `_NOTES_MARKER_SEARCH_LINES` lines (matching `financial_statement_
# parsing._HEADER_SEARCH_LINES`'s own precedent for exactly this "only
# look at where a real header actually lives" discipline) fixes this
# without narrowing what it was built to catch — every real notes-
# section header and every real "Summarised Statement of ..." sub-
# schedule heading checked so far still sits well within this window.
_NOTES_MARKER_SEARCH_LINES = 10


def _is_primary_statement_page(page_text: str) -> bool:
    header_lower = "\n".join(page_text.splitlines()[:_NOTES_MARKER_SEARCH_LINES]).lower()
    if any(marker in header_lower for marker in _NOTES_PAGE_MARKERS):
        return False
    return any(marker in page_text.lower() for marker in _STATEMENT_PAGE_MARKERS)


def fetch_recent_financial_announcements(client: CseClient) -> list[FinancialAnnouncementRow]:
    response = client.post_form("getFinancialAnnouncement", model=FinancialAnnouncementResponse, data={})
    assert isinstance(response, FinancialAnnouncementResponse)
    return response.reqFinancialAnnouncemnets


def announcements_for_ticker(
    rows: list[FinancialAnnouncementRow], ticker: str
) -> list[FinancialAnnouncementRow]:
    """The feed's `symbol` field is the bare ticker without the CSE board
    suffix (e.g. "JFP" for "JFP.N0000") — verified live."""
    bare = ticker.split(".")[0].upper()
    return [r for r in rows if r.symbol and r.symbol.upper() == bare]


def classify_period_type(file_text: str | None) -> str | None:
    """"Annual Report as at ..." -> 'annual'; "Interim Financial
    Statements for the Quarter ended ..." -> 'quarterly'. Verified live;
    returns None (not a guess) for wording not yet seen."""
    if not file_text:
        return None
    lower = file_text.lower()
    if "annual report" in lower:
        return "annual"
    if "interim" in lower and "quarter" in lower:
        return "quarterly"
    return None


def _epoch_ms_to_date(ms: int | None) -> dt.date | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=_SRI_LANKA_TZ).date()


def _parse_cse_datetime(text: str | None) -> dt.date | None:
    """"14 Aug 2026 08:16:24 PM" -> date. Verified format from
    `authorizedDate`/`uploadedDate` on the getFinancialAnnouncement feed."""
    if not text:
        return None
    try:
        return dt.datetime.strptime(text.strip(), "%d %b %Y %I:%M:%S %p").date()
    except ValueError:
        logger.warning("could not parse CSE datetime string %r", text)
        return None


def resolve_first_available_date(row: FinancialAnnouncementRow) -> dt.date | None:
    """`authorizedDate` (when CSE actually published the filing) is the
    correct point-in-time date — preferred over `uploadedDate` (an
    internal staging step that precedes it) and far preferred over
    `manualDate` (the period-end date, which is exactly what §6 warns
    against using as first_available_date)."""
    return _parse_cse_datetime(row.authorizedDate) or _parse_cse_datetime(row.uploadedDate)


def download_pdf(url: str, *, user_agent: str, timeout: float = 60.0) -> bytes:
    response = httpx.get(url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _scale_extracted_line(line: ExtractedLine, scale: Decimal) -> ExtractedLine:
    """Every value column scaled uniformly — see `app.domain.financial_
    statement_parsing.detect_unit_scale`'s own docstring for why this is
    a page-wide multiplier, not applied per-line, and its documented
    "not applicable to per-share lines" caveat. `alt_values` (see that
    field's own docstring) gets the identical scale — it's the same
    printed figures, just a different candidate reading of them, not a
    different unit."""
    return dataclasses.replace(
        line,
        values=tuple(v * scale if v is not None else None for v in line.values),
        alt_values=(
            tuple(v * scale for v in line.alt_values) if line.alt_values is not None else None
        ),
    )


#: How many pages either side of a declaration-less statement page may be
#: consulted for the unit scale. A financial-statements section runs the
#: primary statements back to back (income statement, balance sheet,
#: cash flow, changes in equity), so ±3 covers "the declaration is on the
#: section's first page" without reaching a different section.
_UNIT_INHERIT_WINDOW = 3

#: Once at least one primary-statement page has been seen, stop scanning
#: after this many CONSECUTIVE non-statement pages — the primary
#: statements are a contiguous block (with at most a page or two of
#: accounting policies between them, and the parent-company set right
#: after the group set), so a run this long means the section is over
#: and the rest is notes / appendices. Bounds a 300-page annual report's
#: work to the statements block plus a margin, instead of an
#: `extract_text()` call on every page (the real cause of the 90s
#: pdfplumber timeouts on AAIC / AGST / BALA-shaped reports, 4 Sep 2026).
_STATEMENT_BLOCK_END_GAP = 30

#: A hard cap on how many pages are read at all — if the primary
#: statements haven't started by here, this is not a filing shape this
#: extractor can use (or it is pathological), and reading on only risks
#: the timeout it is meant to avoid.
_MAX_SCAN_PAGES = 320


def _inherited_unit_scale(
    pages: list[tuple[int, str, bool, "Decimal | None"]], idx: int
) -> "Decimal | None":
    """The unit scale for `pages[idx]` — a primary statement page with no
    declaration of its own — taken from a nearby statement page.

    Deliberately narrow, to keep the "refuse rather than guess" contract
    `detect_unit_scale` establishes:
      - only pages that are THEMSELVES primary statement pages and carry
        their OWN detected scale are consulted (a narrative or notes page
        that merely says "Rs." is not);
      - only within `_UNIT_INHERIT_WINDOW` pages;
      - the scales found must be UNANIMOUS. If two nearby statement pages
        disagree (one "Rs.'000", one "Rs."), that is the genuinely
        ambiguous case the original page-at-a-time skip exists for, and
        `None` is returned so the page is still skipped.
    """
    found: set[Decimal] = set()
    lo = max(0, idx - _UNIT_INHERIT_WINDOW)
    hi = min(len(pages), idx + _UNIT_INHERIT_WINDOW + 1)
    for j in range(lo, hi):
        if j == idx:
            continue
        _pn, _text, is_stmt, own_scale = pages[j]
        if is_stmt and own_scale is not None:
            found.add(own_scale)
    return next(iter(found)) if len(found) == 1 else None


def extract_financial_statement_candidates(
    pdf_bytes: bytes,
) -> list[tuple[int, ExtractedLine]]:
    """Returns (page_number, ExtractedLine) pairs for every canonical
    line item found on a statement page, scaled to real LKR (see `app.
    domain.financial_statement_parsing.detect_unit_scale` — a REAL bug,
    found live against COMB.N0000's real filing: every value used to be
    stored exactly as printed, off by 1000x on any "Rs.'000"-declared
    statement, which is most of them). A statement page whose own unit
    declaration can't be found at all is skipped entirely — refusing to
    guess a scale rather than risk a second, silent 1000x-style error on
    a filing shape not yet seen. page_number is 0-indexed, matching
    pdfplumber's own indexing, and is stored as-is in
    Fundamental.source_page so a reviewer's page reference matches what
    their PDF viewer would show when combined with the usual +1 offset
    for human-readable page numbers — see the confirm-queue UI, not yet
    built (ROADMAP.md).
    """
    # Read every page once first, so a statement page that carries no
    # unit declaration of its own can inherit one from a NEARBY statement
    # page. Sri Lankan annual reports routinely print "Amounts in
    # Rs. '000" once at the head of the financial-statements section and
    # every page after it — the balance sheet, the cash-flow statement,
    # the statement of changes in equity — relies on that single
    # declaration. The old page-at-a-time scan skipped all of those,
    # which is why AAIC / AGST / TYRE's balance sheets never extracted
    # (3 Sep 2026). See `_inherited_unit_scale` for the deliberately
    # narrow rules that keep this from guessing.
    pages: list[tuple[int, str, bool, Decimal | None]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        seen_statement = False
        consecutive_non_statement = 0
        for page_number, page in enumerate(pdf.pages):
            if page_number >= _MAX_SCAN_PAGES:
                logger.warning(
                    "stopping the page scan at %d pages — primary statements either "
                    "start later than this extractor reads or the file is pathological",
                    _MAX_SCAN_PAGES,
                )
                break
            if seen_statement and consecutive_non_statement >= _STATEMENT_BLOCK_END_GAP:
                break  # past the end of the primary-statements block
            # A real, narrowly-scoped repair for NTB.N0000's real bold-
            # text character-doubling artifact — see app.domain.
            # financial_statement_parsing.repair_character_doubling's own
            # docstring for the full finding. A no-op on every page that
            # doesn't show strong evidence of the bug (i.e. every page of
            # every other real filing checked so far).
            text = repair_character_doubling(page.extract_text() or "")
            is_stmt = _is_primary_statement_page(text)
            pages.append((page_number, text, is_stmt, detect_unit_scale(text) if is_stmt else None))
            if is_stmt:
                seen_statement = True
                consecutive_non_statement = 0
            else:
                consecutive_non_statement += 1

    results: list[tuple[int, ExtractedLine]] = []
    for idx, (page_number, text, is_stmt, own_scale) in enumerate(pages):
        if not is_stmt:
            continue
        scale = own_scale if own_scale is not None else _inherited_unit_scale(pages, idx)
        if scale is None:
            logger.warning(
                "page %d looks like a primary statement page but no unit declaration "
                "(e.g. \"Rs.'000\" or \"Rs.\") could be found on it or on any adjacent "
                "statement page — skipping rather than guessing the scale every value "
                "on it should be multiplied by",
                page_number,
            )
            continue
        # This page's OWN real column count, read from its own header
        # — see `detect_expected_value_columns`'s own docstring for
        # the real, live bug this closes (a company whose statement
        # isn't the assumed 4-column Group/Company comparative used
        # to silently get the wrong expected count). Falls back to
        # the same default every page used before this existed.
        expected_columns = (
            detect_expected_value_columns(text) or DEFAULT_EXPECTED_VALUE_COLUMNS
        )
        for line in extract_candidate_lines(text, expected_columns):
            if line.statement_line is not None and line.primary_value is not None:
                results.append((page_number, _scale_extracted_line(line, scale)))

    _apply_identity_reconciled_corrections(results)
    return results


def _apply_identity_reconciled_corrections(results: list[tuple[int, ExtractedLine]]) -> None:
    """Mutates `results` IN PLACE, replacing a line's `values` with its
    own `alt_values` reading wherever either of TWO reconciliation passes
    (app.domain.financial_statement_parsing) accepts the correction: (1)
    `reconcile_ambiguous_values_via_identities` — a substitution that
    turns a FAILING accounting identity into a passing one without
    breaking one that already passed; then (2) `reconcile_magnitude_
    implausible_values`, run against the values AFTER pass (1)'s own
    corrections are applied — the narrower, identity-free acceptance rule
    for a component line (`inventories`, `trade_receivables`) that no
    accounting identity in this module mentions at all, so pass (1) never
    even considers it however implausible the default reading is. See
    that function's own docstring for the real case (Serendib Hotels
    PLC's real confirmed `inventories`) and its own acceptance rule.

    Built from the FIRST occurrence of each statement_line, matching
    `build_fundamental_drafts`'s own "first occurrence wins" rule
    exactly — a correction is only meaningful if it lands on the same
    occurrence that rule would actually keep as the real draft; a second
    (e.g. Company-column) occurrence of the same canonical key is never
    consulted or corrected here, same as it's never used for the draft
    either.
    """
    values: dict[str, Decimal] = {}
    alt_values: dict[str, Decimal] = {}
    first_index_by_key: dict[str, int] = {}
    for index, (_page, line) in enumerate(results):
        if line.statement_line is None or line.primary_value is None:
            continue
        if line.statement_line in values:
            continue
        values[line.statement_line] = line.primary_value
        first_index_by_key[line.statement_line] = index
        if line.alt_values is not None:
            alt_values[line.statement_line] = line.alt_values[0]

    corrections = dict(reconcile_ambiguous_values_via_identities(values, alt_values))
    values_after_identity_pass = {**values, **corrections}
    magnitude_corrections = reconcile_magnitude_implausible_values(
        values_after_identity_pass, alt_values
    )
    corrections.update(magnitude_corrections)

    for statement_line, corrected_value in corrections.items():
        index = first_index_by_key[statement_line]
        page_number, line = results[index]
        assert line.alt_values is not None  # only ever offered as a correction if this line had one
        results[index] = (
            page_number,
            dataclasses.replace(line, values=line.alt_values),
        )
        reason = (
            "magnitude-plausibility cross-check; see app.domain.financial_statement_parsing."
            "reconcile_magnitude_implausible_values"
            if statement_line in magnitude_corrections
            else "accounting-identity cross-check; see app.domain.financial_statement_parsing."
            "reconcile_ambiguous_values_via_identities"
        )
        logger.info(
            "reconciled %s: %s -> %s (%s)",
            statement_line, values[statement_line], corrected_value, reason,
        )


def build_fundamental_drafts(
    *,
    ticker: str,
    period_end: dt.date,
    period_type: str,
    first_available_date: dt.date,
    source_url: str,
    candidates: list[tuple[int, ExtractedLine]],
) -> list[Fundamental]:
    """One draft row per DISTINCT statement_line — if the same canonical
    line somehow matches on more than one page in a single extraction run
    (shouldn't happen given the page-marker filter, but PDFs are messy),
    the first occurrence wins and the rest are dropped rather than
    inserting conflicting drafts for the same (ticker, period_end,
    statement_line) — UNLESS the key is in `SUM_ACROSS_OCCURRENCES`
    (currently: `total_interest_bearing_debt`, verified to print twice on
    a real balance sheet — once as the current portion, once as the
    non-current — a real, standard presentation this rule exists
    specifically for), in which case every occurrence is summed into one
    draft instead, with a `source_snippet` that lists each contributing
    value rather than only the total.
    """
    seen: set[str] = set()
    to_sum: dict[str, list[tuple[int, Decimal]]] = {}
    drafts: list[Fundamental] = []
    for page_number, line in candidates:
        assert line.statement_line is not None and line.primary_value is not None
        if line.statement_line in SUM_ACROSS_OCCURRENCES:
            to_sum.setdefault(line.statement_line, []).append((page_number, line.primary_value))
            continue
        if line.statement_line in seen:
            continue
        seen.add(line.statement_line)
        drafts.append(
            Fundamental(
                ticker=ticker,
                period_end=period_end,
                period_type=period_type,
                first_available_date=first_available_date,
                version=1,
                statement_line=line.statement_line,
                value=line.primary_value,
                currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED,
                restated_flag=False,
                source_url=source_url,
                source_page=page_number,
                source_snippet=line.raw_text,
                confirmed_by=None,
                confirmed_at=None,
            )
        )

    for statement_line, occurrences in to_sum.items():
        total = sum((value for _page, value in occurrences), Decimal(0))
        pages = sorted({page for page, _value in occurrences})
        drafts.append(
            Fundamental(
                ticker=ticker,
                period_end=period_end,
                period_type=period_type,
                first_available_date=first_available_date,
                version=1,
                statement_line=statement_line,
                value=total,
                currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED,
                restated_flag=False,
                source_url=source_url,
                source_page=pages[0] if len(pages) == 1 else None,
                source_snippet=(
                    f"SUM of {len(occurrences)} occurrences on page(s) {pages}: "
                    + "; ".join(f"{v:,}" for _p, v in occurrences)
                    + f" = {total:,}. This canonical concept prints as a current/non-current "
                    "maturity split on this filing's shape; both are summed for the total."
                ),
                confirmed_by=None,
                confirmed_at=None,
            )
        )
    return drafts


def build_derived_fundamental_drafts(
    *,
    ticker: str,
    period_end: dt.date,
    period_type: str,
    first_available_date: dt.date,
    source_url: str,
    candidates: list[tuple[int, ExtractedLine]],
) -> list[Fundamental]:
    """Additional draft rows for canonical concepts derived arithmetically
    from OTHER extracted lines — a sum (e.g. `depreciation_and_
    amortisation`, when Depreciation and Amortization print as two
    separate cash-flow-statement lines rather than one combined line) or
    a difference (`change_in_net_working_capital`, from the two bookend
    subtotals of the working-capital-changes section) — see
    `app.domain.financial_statement_parsing.derive_additional_line_items`
    for both. Kept as a separate function from `build_fundamental_drafts`
    rather than folded in, because a derived value has no single
    `raw_text`/`source_page` of its own — it's computed from two others —
    and the draft's `source_snippet` says so explicitly, and cites both
    real inputs, rather than pretending to quote one line CSE printed.
    """
    values = {
        line.statement_line: line.primary_value
        for _page, line in candidates
        if line.statement_line and line.primary_value is not None
    }
    derived = derive_additional_line_items(values)
    if not derived:
        return []

    drafts: list[Fundamental] = []
    for statement_line, value in derived.items():
        if statement_line == "net_working_capital":
            asset_keys = sorted(k for k in NET_WORKING_CAPITAL_ASSET_COMPONENTS if k in values)
            liability_keys = sorted(k for k in NET_WORKING_CAPITAL_LIABILITY_COMPONENTS if k in values)
            note = (
                "assets (" + "; ".join(f"{k} = {values[k]:,}" for k in asset_keys) + ") minus "
                "liabilities (" + "; ".join(f"{k} = {values[k]:,}" for k in liability_keys) + ")"
            )
        elif statement_line in DERIVED_SUMS:
            component_keys = DERIVED_SUMS[statement_line]
            note = "sum of " + "; ".join(f"{k} = {values[k]:,}" for k in component_keys)
        else:
            minuend_key, subtrahend_key = DERIVED_DIFFERENCES[statement_line]
            note = f"{minuend_key} = {values[minuend_key]:,} minus {subtrahend_key} = {values[subtrahend_key]:,}"
        drafts.append(
            Fundamental(
                ticker=ticker,
                period_end=period_end,
                period_type=period_type,
                first_available_date=first_available_date,
                version=1,
                statement_line=statement_line,
                value=value,
                currency="LKR",
                provenance_tier=ProvenanceTier.AI_ASSISTED,
                restated_flag=False,
                source_url=source_url,
                source_page=None,
                source_snippet=(
                    f"DERIVED, not read from a single printed line — {note} = {value:,}. "
                    "Check every input against the source PDF before confirming, not just the total."
                ),
                confirmed_by=None,
                confirmed_at=None,
            )
        )
    return drafts


def _already_ingested(db: Session, ticker: str, period_end: dt.date, period_type: str) -> bool:
    """One check per filing, not per statement line: if we've already
    processed this (ticker, period_end, period_type) at all — draft or
    confirmed — skip re-downloading and re-parsing a potentially large
    PDF. A partial prior run (e.g. it crashed after inserting only some
    lines) would be masked by this check; acceptable for Phase 1, see
    ROADMAP.md."""
    existing = db.scalar(
        select(Fundamental)
        .where(
            Fundamental.ticker == ticker,
            Fundamental.period_end == period_end,
            Fundamental.period_type == period_type,
        )
        .limit(1)
    )
    return existing is not None


def ingest_financial_statement(
    client: CseClient,
    db: Session,
    ticker: str,
    row: FinancialAnnouncementRow,
    *,
    user_agent: str | None = None,
) -> int:
    """One filing -> zero or more draft Fundamental rows. Returns the
    count inserted. Skips (returns 0) rather than guessing whenever a
    required field can't be resolved — see classify_period_type and
    resolve_first_available_date's own "return None, don't guess" rules.
    """
    period_type = classify_period_type(row.fileText)
    if period_type is None:
        logger.info("skipping filing id=%s for %s: unrecognised fileText %r", row.id, ticker, row.fileText)
        return 0

    period_end = _epoch_ms_to_date(row.manualDate)
    first_available_date = resolve_first_available_date(row)
    if period_end is None or first_available_date is None:
        logger.warning("skipping filing id=%s for %s: missing period_end or first_available_date", row.id, ticker)
        return 0

    if _already_ingested(db, ticker, period_end, period_type):
        return 0

    source_url = _CDN_BASE_URL + row.path
    pdf_bytes = download_pdf(source_url, user_agent=user_agent or settings.cse_user_agent)
    candidates = extract_financial_statement_candidates(pdf_bytes)

    # Independent arithmetic + magnitude check before anything is stored.
    # A statement that doesn't balance means the extraction is wrong, and
    # the failure mode this guards against is a plausible number rather
    # than a crash — a split thousands separator once turned 4,453,103
    # into 453,103 and nothing else in the pipeline noticed.
    # check_extraction_quality also catches the narrower case an identity
    # can't: a value with no computable identity covering it at all (see
    # check_magnitude_plausibility's own docstring — real cases:
    # AAF.N0000, VLL.N0000). Drafts still get written (they're
    # unconfirmed by definition), but the failure is recorded on every
    # row's notes so a reviewer sees it before promoting anything.
    extracted_values = {
        line.statement_line: line.primary_value
        for _page, line in candidates
        if line.statement_line and line.primary_value is not None
    }
    failed_identities = [c for c in check_extraction_quality(extracted_values) if not c.passed]
    if failed_identities:
        logger.error(
            "extraction for %s %s failed %d accounting identity check(s): %s",
            ticker,
            period_end,
            len(failed_identities),
            "; ".join(f"{c.name} ({c.detail})" for c in failed_identities),
        )

    drafts = build_fundamental_drafts(
        ticker=ticker,
        period_end=period_end,
        period_type=period_type,
        first_available_date=first_available_date,
        source_url=source_url,
        candidates=candidates,
    )
    drafts += build_derived_fundamental_drafts(
        ticker=ticker,
        period_end=period_end,
        period_type=period_type,
        first_available_date=first_available_date,
        source_url=source_url,
        candidates=candidates,
    )

    if failed_identities:
        warning = (
            "EXTRACTION FAILED ARITHMETIC CHECK — "
            + "; ".join(f"{c.name}: {c.detail}" for c in failed_identities)
            + ". Do not confirm any figure from this filing without checking it against "
            "the source PDF; the statement does not balance, which means at least one "
            "number here was read wrongly."
        )
        for draft in drafts:
            draft.source_snippet = f"{warning}\n\n{draft.source_snippet or ''}".strip()

    if drafts:
        db.add_all(drafts)
        db.commit()
    return len(drafts)


def ingest_financial_statements_for_known_tickers(client: CseClient, db: Session, tickers: list[str]) -> int:
    """§52-style job entry point: one fetch of the (global, unfilterable —
    see module docstring) recent-filings feed, then per-ticker matching
    and ingestion. Returns the total number of new draft rows across every
    ticker."""
    rows = fetch_recent_financial_announcements(client)
    total = 0
    for ticker in tickers:
        for row in announcements_for_ticker(rows, ticker):
            try:
                total += ingest_financial_statement(client, db, ticker, row)
            except Exception:
                logger.exception("financial statement ingestion failed for %s filing id=%s", ticker, row.id)
    return total


@dataclasses.dataclass(frozen=True)
class StaleRefreshResult:
    """What `refresh_stale_fundamentals` actually did to one filing's
    already-stored rows — reported per-line so a caller can print an
    honest summary rather than a bare success/failure flag."""

    updated: tuple[str, ...]
    """statement_line keys whose stored value changed."""
    unchanged: int
    """Rows whose fresh re-extraction matched what was already stored."""
    skipped_confirmed: int
    """Rows left untouched because they're already human-confirmed
    (Reported) — this function never edits confirmed data, matching every
    other confirm-queue write path in this codebase."""
    still_failing: bool
    """True if the FRESH extraction still fails `check_accounting_
    identities` (or found nothing at all) — nothing was written in this
    case; re-extracting is not a fix in itself, only a candidate that
    still has to earn its way in by actually balancing."""
    note: str


def refresh_stale_fundamentals(
    db: Session, ticker: str, period_end: dt.date, period_type: str, pdf_bytes: bytes
) -> StaleRefreshResult:
    """Re-runs TODAY's extractor against a filing this system already has
    draft rows for, and repairs any row a since-FIXED extraction bug left
    wrong — real, confirmed cases: HNB.N0000/HNB.X0000 (`total_equity`
    short by exactly LKR 200bn), CALH.N0000 (`total_assets` short by
    80-100bn across 6 real quarters), COCR.N0000 (`total_liabilities` AND
    `total_equity` both independently short, ~110bn combined) — all three
    traced by hand against the real source PDF: `_repair_split_leading_
    digits` genuinely mis-handled these rows when they were first
    ingested, but re-running `extract_financial_statement_candidates`
    against the identical PDF TODAY reads every one of them correctly —
    something upstream of that function (column-count / variance-%
    detection) was fixed since, independently of this repair.

    The real problem this closes: `_already_ingested` treats "any row
    already exists for this (ticker, period_end, period_type)" as done,
    so a routine `backfill-financials` re-run — no matter how many times
    it's run — never revisits these rows to pick up the fix. Nothing
    short of an explicit re-extraction (this function) ever will.

    Deliberately conservative in three ways, matching every other write
    path onto this table:
      1. NEVER touches an already-confirmed (Reported) row — only
         still-AI-assisted, unconfirmed drafts are eligible, exactly like
         `POST /fundamentals/{id}/confirm`'s own refusal to edit one.
      2. The fresh reading is only ever applied if it makes `check_
         extraction_quality` pass CLEANLY — every computable identity
         AND magnitude check, not just whichever one used to fail —
         using the exact same acceptance bar `reconcile_ambiguous_
         values_via_identities` already established for its own,
         narrower "ambiguous alt_values" case. A fresh extraction that
         still doesn't balance is not "more recent," it's just a
         different wrong number, and is refused the same as the current
         stale one.
      3. All-or-nothing per filing: if the fresh extraction can't be
         trusted, NO row for this filing is touched, not even the ones
         that happened to already match.
    """
    candidates = extract_financial_statement_candidates(pdf_bytes)
    fresh_values: dict[str, Decimal] = {}
    fresh_source: dict[str, tuple[int, ExtractedLine]] = {}
    for page, line in candidates:
        if (
            line.statement_line is not None
            and line.primary_value is not None
            and line.statement_line not in fresh_values
        ):
            fresh_values[line.statement_line] = line.primary_value
            fresh_source[line.statement_line] = (page, line)

    if not fresh_values:
        return StaleRefreshResult((), 0, 0, True, "fresh extraction found no statement pages/lines at all")

    failed = [c for c in check_extraction_quality(fresh_values) if not c.passed]
    if failed:
        return StaleRefreshResult(
            (), 0, 0, True,
            "fresh extraction still fails: " + "; ".join(f"{c.name} ({c.detail})" for c in failed),
        )

    existing_rows = db.scalars(
        select(Fundamental).where(
            Fundamental.ticker == ticker,
            Fundamental.period_end == period_end,
            Fundamental.period_type == period_type,
        )
    ).all()

    updated: list[str] = []
    unchanged = 0
    skipped_confirmed = 0
    today = dt.datetime.now(_SRI_LANKA_TZ).date().isoformat()
    for row in existing_rows:
        if row.confirmed_by is not None:
            skipped_confirmed += 1
            continue
        fresh = fresh_values.get(row.statement_line)
        if fresh is None:
            continue  # this line wasn't part of what got re-extracted; leave it exactly as is
        if fresh == row.value:
            unchanged += 1
            continue
        page, line = fresh_source[row.statement_line]
        old_value = row.value
        row.value = fresh
        row.source_page = page
        row.source_snippet = (
            f"RE-EXTRACTED {today}: today's parser reads this line correctly and the filing "
            f"now balances against every other extracted total (previously stored {old_value:,}, "
            "a stale value from before a real split-leading-digit extraction bug was fixed — see "
            "ROADMAP.md's \"stale pre-fix drafts\" entry). Raw text: " + line.raw_text
        )
        updated.append(row.statement_line)

    db.commit()
    return StaleRefreshResult(tuple(updated), unchanged, skipped_confirmed, False, "")


@dataclasses.dataclass(frozen=True)
class StaleSweepOutcome:
    """One filing's outcome from `sweep_stale_fundamentals` — the SAME
    shape whether the caller is `app.cli`'s `refresh-stale-fundamentals`
    command (prints it) or `app.jobs.runner`'s scheduled/manual job
    (folds it into progress_note / rows_written)."""

    ticker: str
    period_end: dt.date
    period_type: str
    status: str
    """One of "repaired", "still_failing", "unchanged", "no_source",
    "error" — never a raw exception or a free-form string a caller would
    have to pattern-match against prose."""
    detail: str
    updated_lines: tuple[str, ...] = ()


def sweep_stale_fundamentals(
    db: Session,
    tickers: list[str],
    *,
    user_agent: str | None = None,
    on_filing: Callable[[int, int, str], bool | None] | None = None,
) -> list[StaleSweepOutcome]:
    """Every (ticker, period_end, period_type) filing across `tickers`
    whose CURRENTLY STORED fundamentals fail `check_extraction_quality`,
    re-downloaded and re-run through today's extractor via
    `refresh_stale_fundamentals` — the shared core behind BOTH `app.cli`'s
    `refresh-stale-fundamentals` command and `app.jobs.runner`'s
    corresponding job, so the two can never drift apart (this project's
    own established discipline — see `app.jobs.runner`'s own module
    docstring, "every runner wraps an already-real ingestion call", now
    true of this one too). See `refresh_stale_fundamentals`'s own
    docstring for the real repair cases and the three ways this stays
    conservative (never touches a confirmed row; only applies a fresh
    reading that passes EVERY computable check, not just the one that
    used to fail; all-or-nothing per filing).

    First groups every ticker's stored rows into filings and checks each
    one BEFORE any network call, so `on_filing`'s own `total` reflects
    only filings that actually need a download — a ticker with nothing
    currently failing costs nothing beyond one query, same as `app.cli`'s
    original loop.

    `on_filing`, when given, is called after EVERY filing CHECKED with
    `(index_completed, total_checked, "{ticker} {period_end}")` —
    mirrors `app.ingestion.security_enrichment.enrich_securities`'s own
    `on_ticker` convention exactly, including its cooperative-cancel
    contract: returning `False` stops the sweep after the filing that
    just completed. Any other return value, including `None`, continues
    the sweep unchanged.
    """
    to_check: list[tuple[str, dt.date, str, str | None]] = []
    for ticker in tickers:
        rows = db.scalars(select(Fundamental).where(Fundamental.ticker == ticker)).all()
        groups: dict[tuple[dt.date, str], list[Fundamental]] = {}
        for row in rows:
            groups.setdefault((row.period_end, row.period_type), []).append(row)
        for (period_end, period_type), group_rows in sorted(groups.items()):
            values = {r.statement_line: r.value for r in group_rows}
            if all(c.passed for c in check_extraction_quality(values)):
                continue
            source_url = next((r.source_url for r in group_rows if r.source_url), None)
            to_check.append((ticker, period_end, period_type, source_url))

    total = len(to_check)
    outcomes: list[StaleSweepOutcome] = []
    for i, (ticker, period_end, period_type, source_url) in enumerate(to_check, start=1):
        if source_url is None:
            outcomes.append(
                StaleSweepOutcome(ticker, period_end, period_type, "no_source", "no source_url stored")
            )
        else:
            try:
                pdf_bytes = download_pdf(source_url, user_agent=user_agent or settings.cse_user_agent)
                result = refresh_stale_fundamentals(db, ticker, period_end, period_type, pdf_bytes)
            except Exception as exc:  # noqa: BLE001 — one bad filing must not abort the sweep
                logger.exception("refresh sweep failed for %s %s %s", ticker, period_end, period_type)
                outcomes.append(StaleSweepOutcome(ticker, period_end, period_type, "error", str(exc)))
            else:
                if result.still_failing:
                    outcomes.append(
                        StaleSweepOutcome(ticker, period_end, period_type, "still_failing", result.note)
                    )
                elif result.updated:
                    outcomes.append(
                        StaleSweepOutcome(
                            ticker, period_end, period_type, "repaired", "", tuple(result.updated)
                        )
                    )
                else:
                    outcomes.append(
                        StaleSweepOutcome(
                            ticker, period_end, period_type, "unchanged",
                            "fresh extraction matches what's already stored — the check failure is a "
                            "real, different discrepancy, not a stale-extraction artifact",
                        )
                    )
        if on_filing is not None and on_filing(i, total, f"{ticker} {period_end}") is False:
            break
    return outcomes
