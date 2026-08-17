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
     produce false matches).
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

import datetime as dt
import io
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pdfplumber
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.financial_statement_parsing import (
    DERIVED_DIFFERENCES,
    DERIVED_SUMS,
    NET_WORKING_CAPITAL_ASSET_COMPONENTS,
    NET_WORKING_CAPITAL_LIABILITY_COMPONENTS,
    SUM_ACROSS_OCCURRENCES,
    ExtractedLine,
    check_accounting_identities,
    derive_additional_line_items,
    extract_candidate_lines,
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
_NOTES_PAGE_MARKER = "notes to the"


def _is_primary_statement_page(page_text_lower: str) -> bool:
    if _NOTES_PAGE_MARKER in page_text_lower:
        return False
    return any(marker in page_text_lower for marker in _STATEMENT_PAGE_MARKERS)


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


def extract_financial_statement_candidates(
    pdf_bytes: bytes,
) -> list[tuple[int, ExtractedLine]]:
    """Returns (page_number, ExtractedLine) pairs for every canonical
    line item found on a statement page. page_number is 0-indexed,
    matching pdfplumber's own indexing, and is stored as-is in
    Fundamental.source_page so a reviewer's page reference matches what
    their PDF viewer would show when combined with the usual +1 offset
    for human-readable page numbers — see the confirm-queue UI, not yet
    built (ROADMAP.md).
    """
    results: list[tuple[int, ExtractedLine]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lower = text.lower()
            if not _is_primary_statement_page(lower):
                continue
            for line in extract_candidate_lines(text):
                if line.statement_line is not None and line.primary_value is not None:
                    results.append((page_number, line))
    return results


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

    # Independent arithmetic check before anything is stored. A statement
    # that doesn't balance means the extraction is wrong, and the failure
    # mode this guards against is a plausible number rather than a crash —
    # a split thousands separator once turned 4,453,103 into 453,103 and
    # nothing else in the pipeline noticed. Drafts still get written
    # (they're unconfirmed by definition), but the failure is recorded on
    # every row's notes so a reviewer sees it before promoting anything.
    extracted_values = {
        line.statement_line: line.primary_value
        for _page, line in candidates
        if line.statement_line and line.primary_value is not None
    }
    failed_identities = [c for c in check_accounting_identities(extracted_values) if not c.passed]
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
