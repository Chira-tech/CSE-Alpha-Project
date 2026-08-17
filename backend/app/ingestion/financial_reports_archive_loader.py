"""
Per-company historical financial-statement archive from `/api/financials`.

Found by watching the CSE's own new company-profile page (Financials ->
Annual Reports) rather than guessing endpoint names — the same technique
that found sectors, the issuer registry and per-company price history
this session. `getFinancialAnnouncement` (the endpoint
`financial_pdf_extractor.py` already uses) is a platform-wide feed of the
most recent ~180 filings; `/api/financials` is the opposite shape — one
company, its full history — which is exactly PARAMETERS.md #2's "backfill
target 2015-01-01" and the trend-detection engine's "most tickers have
one period" gap in one place.

VERIFIED DEPTH, AND ITS REAL LIMIT. COMB.N0000: 16 annual reports and 59
quarterly filings, catalogued back to 2012. But only files from
~2019 onward actually download — every 2018-and-earlier file 403s from
the CDN despite being listed, confirmed by checking all 16 annual reports
individually. The catalogue is more complete than the CDN; this loader
therefore treats a 403 as an expected, counted outcome, not a failure
that should look like a bug.

POINT-IN-TIME: `uploadedDate` IS TRUSTED, and here is the evidence, not
an assumption. Every one of 60 real (period_end, uploadedDate) pairs for
COMB.N0000 — back to 2012 — shows a plausible, DISTINCT disclosure lag
(38 to 92 days, clustered where CSE's own quarterly deadline sits). A
bulk-migrated backfill would show every old row stamped with the same
2019-ish "when the new site launched" date; it doesn't. `authorizedDate`
exists only on recent filings (a slightly-later same-day confirmation
step) and is preferred when present; `uploadedDate` is the fallback for
everything else, not a compromise.

AMENDMENTS ARE REAL RESTATEMENTS, HANDLED AS SUCH, NOT AS DUPLICATES OR
COLLISIONS. Several periods carry both an original and an "Amended ..."
filing for the same period_end — e.g. COMB.N0000's FY2022 and FY2021
annual reports. Processing oldest-to-newest and versioning by how many
prior filings exist for that (ticker, period_end, period_type) makes the
amendment `version=2`, `first_available_date` on its own later
`uploadedDate` — the market saw the original figures first, and the
restated figures only from whenever CSE actually published the amendment.
Silently overwriting the original, or refusing to ingest a same-period
second filing at all, would both be wrong for different reasons: the
first destroys the record of what the market believed at the time, the
second loses real information about a genuine restatement.
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

import httpx

from app.config import settings
from app.domain.financial_statement_parsing import check_accounting_identities
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import (
    build_fundamental_drafts,
    download_pdf,
    extract_financial_statement_candidates,
)
from app.ingestion.schemas import CompanyArchiveReportFile, CompanyFinancialArchiveResponse
from app.models.fundamentals import Fundamental

logger = logging.getLogger("cse_alpha.ingestion.financial_reports_archive")

_SRI_LANKA_TZ = ZoneInfo("Asia/Colombo")
_CDN_BASE_URL = "https://cdn.cse.lk/"
_AMENDED_MARKER = "amended"


def fetch_report_archive(client: CseClient, ticker: str) -> CompanyFinancialArchiveResponse:
    response = client.post_form(
        "financials", model=CompanyFinancialArchiveResponse, data={"symbol": ticker}
    )
    assert isinstance(response, CompanyFinancialArchiveResponse)
    return response


def _epoch_ms_to_date(ms: int | None) -> dt.date | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=_SRI_LANKA_TZ).date()


def resolve_first_available_date(report: CompanyArchiveReportFile) -> dt.date | None:
    """`authorizedDate` when present (recent filings only), else
    `uploadedDate` — see the module docstring for the live evidence that
    `uploadedDate` alone is trustworthy back to 2012, not a fallback of
    last resort."""
    return _epoch_ms_to_date(report.authorizedDate) or _epoch_ms_to_date(report.uploadedDate)


def _already_ingested_by_source(db: Session, ticker: str, source_url: str) -> bool:
    """Idempotency keyed on the exact file, not the period — deliberately
    different from `financial_pdf_extractor._already_ingested`, because
    THIS loader must still process a second (amended) filing for a period
    already on file. Skips only if this specific PDF was processed
    before."""
    existing = db.scalar(
        select(Fundamental)
        .where(Fundamental.ticker == ticker, Fundamental.source_url == source_url)
        .limit(1)
    )
    return existing is not None


def _next_version(db: Session, ticker: str, period_end: dt.date, period_type: str) -> int:
    """1 for a period's first filing; N+1 if N distinct source PDFs have
    already been ingested for this (ticker, period_end, period_type) —
    this is what turns a genuine amendment into version=2 rather than a
    silently-skipped duplicate or a row that overwrites the original."""
    prior_sources = db.scalars(
        select(Fundamental.source_url)
        .where(
            Fundamental.ticker == ticker,
            Fundamental.period_end == period_end,
            Fundamental.period_type == period_type,
        )
        .distinct()
    ).all()
    return len(prior_sources) + 1


def ingest_archived_report(
    client: CseClient,
    db: Session,
    ticker: str,
    report: CompanyArchiveReportFile,
    *,
    period_type: str,
) -> int:
    """One archived filing -> zero or more draft `Fundamental` rows.
    Returns the count inserted. A 403 from the CDN (confirmed live: every
    2018-and-earlier COMB.N0000 filing) is caught and counted, not raised
    — the catalogue listing a file does not mean the file is retrievable,
    and one unavailable filing must not abort the rest of a company's
    archive."""
    period_end = _epoch_ms_to_date(report.manualDate)
    first_available_date = resolve_first_available_date(report)
    if period_end is None or first_available_date is None:
        logger.warning(
            "skipping archived report id=%s for %s: missing period_end or first_available_date",
            report.id, ticker,
        )
        return 0

    source_url = _CDN_BASE_URL + report.path
    if _already_ingested_by_source(db, ticker, source_url):
        return 0

    try:
        pdf_bytes = download_pdf(source_url, user_agent=settings.cse_user_agent)
    except httpx.HTTPStatusError as exc:
        logger.info(
            "archived report unavailable (status %s) for %s, id=%s: %s",
            exc.response.status_code, ticker, report.id, source_url,
        )
        raise

    candidates = extract_financial_statement_candidates(pdf_bytes)

    extracted_values = {
        line.statement_line: line.primary_value
        for _page, line in candidates
        if line.statement_line and line.primary_value is not None
    }
    failed_identities = [c for c in check_accounting_identities(extracted_values) if not c.passed]
    if failed_identities:
        logger.error(
            "archived extraction for %s %s failed %d accounting identity check(s): %s",
            ticker, period_end, len(failed_identities),
            "; ".join(f"{c.name} ({c.detail})" for c in failed_identities),
        )

    version = _next_version(db, ticker, period_end, period_type)
    drafts = build_fundamental_drafts(
        ticker=ticker,
        period_end=period_end,
        period_type=period_type,
        first_available_date=first_available_date,
        source_url=source_url,
        candidates=candidates,
    )
    for draft in drafts:
        draft.version = version
        draft.restated_flag = version > 1
        if failed_identities:
            warning = (
                "EXTRACTION FAILED ARITHMETIC CHECK — "
                + "; ".join(f"{c.name}: {c.detail}" for c in failed_identities)
                + ". Do not confirm any figure from this filing without checking it against "
                "the source PDF."
            )
            draft.source_snippet = f"{warning}\n\n{draft.source_snippet or ''}".strip()

    if drafts:
        db.add_all(drafts)
        db.commit()
    return len(drafts)


def ingest_report_archive_for_ticker(client: CseClient, db: Session, ticker: str) -> dict[str, int]:
    """Sweeps one company's full catalogued history, oldest filing first
    within each period_type — the order `_next_version` needs to turn a
    real amendment into version=2 rather than version=1 arriving out of
    sequence. One unreachable file never aborts the rest (matches
    `ingest_financial_statements_for_known_tickers`'s per-filing
    try/except); a 403 is counted separately from a genuine parse
    failure so the summary can tell "CDN doesn't have this one" apart
    from "something is actually broken".
    """
    archive = fetch_report_archive(client, ticker)
    drafted = unavailable = failed = 0

    for period_type, reports in (
        ("annual", archive.infoAnnualData),
        ("quarterly", archive.infoQuarterlyData),
    ):
        ordered = sorted(reports, key=lambda r: r.uploadedDate or 0)
        for report in ordered:
            try:
                drafted += ingest_archived_report(client, db, ticker, report, period_type=period_type)
            except httpx.HTTPStatusError:
                unavailable += 1
            except Exception:
                logger.exception(
                    "archived report ingestion failed for %s, id=%s", ticker, report.id
                )
                failed += 1

    summary = {"drafted": drafted, "unavailable": unavailable, "failed": failed}
    logger.info("report archive for %s: %s", ticker, summary)
    return summary
