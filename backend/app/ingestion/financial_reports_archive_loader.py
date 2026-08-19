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

VERIFIED DEPTH — AND A REAL FIX TO WHAT WAS ONCE RECORDED HERE AS A
LIMIT. COMB.N0000: 16 annual reports and 59 quarterly filings,
catalogued back to 2012. Every 2018-and-earlier file's CATALOGUED path
403s from the CDN — that part of the earlier investigation
(README_ENDPOINTS.md's own "the catalogue is more complete than the
CDN") was real. But the file itself is NOT gone: the CDN relocated
every uploaded report under a `cmt/` prefix at some point, and
`/api/financials`'s own `path` field for filings older than that move
was simply never updated to match — the SAME file id 200s the moment
`cmt/` is inserted. Confirmed live against all three of COMB's own
oldest annual reports (2012-2014, the exact ones the earlier
investigation checked and concluded were permanently unavailable) and
8 of AAF.N0000's, 8 for 8. `_resolve_download_url` below normalizes
every catalogued path to its `cmt/`-prefixed form before ever
requesting it, with the literal catalogued path tried second as a
defensive fallback in case some filing genuinely isn't reachable either
way — not assumed impossible, just not what any real case tried so far
has shown.

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
from app.models.ingestion_log import IngestedFilingLog

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
    before.

    Checks TWO sources, deliberately, not one: a `Fundamental` row
    carrying this `source_url` (a filing that produced at least one real
    draft — the ONLY signal this function used to check, and the real bug
    `IngestedFilingLog` exists to close — see that model's own docstring)
    OR an `IngestedFilingLog` row for it (every filing this loader has
    processed since that table existed, including the ones that
    genuinely produced zero drafts). Checking both, rather than switching
    over to the log table alone, means filings ingested before this fix
    — which DO have a `Fundamental` row for every draft they produced —
    stay correctly recognised as already-ingested without a backfill
    migration of historical data."""
    existing_fundamental = db.scalar(
        select(Fundamental.id)
        .where(Fundamental.ticker == ticker, Fundamental.source_url == source_url)
        .limit(1)
    )
    if existing_fundamental is not None:
        return True
    existing_log_entry = db.scalar(
        select(IngestedFilingLog.id)
        .where(IngestedFilingLog.ticker == ticker, IngestedFilingLog.source_url == source_url)
        .limit(1)
    )
    return existing_log_entry is not None


def _resolve_download_url(path: str) -> tuple[str, str | None]:
    """Returns (primary_url, fallback_url). `path` (from `/api/financials`)
    is normalized to its `cmt/`-prefixed form first — see this module's
    own docstring for the live evidence that this is where the file
    actually lives, catalogue metadata notwithstanding — with the
    literal, un-normalized path as a second try if that somehow still
    403s. A path already carrying `cmt/` (every recent filing) has
    nothing to normalize, so there is no second URL to try."""
    if path.startswith("cmt/"):
        return _CDN_BASE_URL + path, None
    return _CDN_BASE_URL + "cmt/" + path, _CDN_BASE_URL + path


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
    Returns the count inserted. The `cmt/`-normalized URL (see this
    module's own docstring) resolves every filing this session has
    actually tried, including the 2018-and-earlier COMB.N0000 ones once
    recorded here as permanently gone — but a still-403ing filing after
    BOTH the normalized and literal catalogue URL are tried is caught and
    counted, not raised, because the catalogue listing a file is real
    evidence it once existed even when neither URL still serves it, and
    one unavailable filing must not abort the rest of a company's
    archive.

    A GENUINE, UNFIXABLE REAL LIMITATION, NAMED PRECISELY RATHER THAN
    WORKED AROUND: Panasian Power PLC's (PAP.N0000) real interim
    statement for the quarter ended 31 March 2026 (id 51459, https://
    cdn.cse.lk/cmt/upload_report_file/1040_1779964134895.pdf) downloads
    successfully (200, ~4.4MB) but `pdfplumber`'s own `extract_text()`
    returns an empty string on every one of its 15 pages — confirmed by
    inspecting every page individually, not inferred from one failure.
    This is a genuinely scanned PDF with no embedded text layer at all
    (its file size, ~30x the size of PAP's own next-quarter filing for
    the same company covering the same statements, is consistent with
    embedded page-image scans rather than born-digital text). No amount
    of extraction-logic fixing can recover text that was never encoded in
    the file; the only way to read this filing at all would be OCR, which
    is out of scope for this pipeline. `extract_financial_statement_
    candidates` already handles this correctly with zero special-casing —
    every page's `_is_primary_statement_page("")` is trivially False, so
    it's naturally skipped exactly like any other non-statement page,
    producing 0 drafts, not a crash and not a fabricated figure. PAP's
    OTHER real quarterly filing (30 June 2026, same company, same
    statement shapes) has a real text layer and extracts correctly — see
    test_paps_real_bare_lkr_balance_sheet_now_produces_drafts in test_
    financial_pdf_extractor.py — confirming this is specific to this one
    scanned file, not a defect in this loader."""
    period_end = _epoch_ms_to_date(report.manualDate)
    first_available_date = resolve_first_available_date(report)
    if period_end is None or first_available_date is None:
        logger.warning(
            "skipping archived report id=%s for %s: missing period_end or first_available_date",
            report.id, ticker,
        )
        return 0

    source_url, fallback_url = _resolve_download_url(report.path)
    if _already_ingested_by_source(db, ticker, source_url):
        return 0
    if fallback_url is not None and _already_ingested_by_source(db, ticker, fallback_url):
        # A row from before this fix, filed under the old (un-normalized,
        # 403-ing) URL — only reachable here for a filing whose catalogue
        # path already lacked cmt/ AND which somehow still succeeded
        # under the literal path (the defensive fallback below actually
        # working). Recognised as done rather than reprocessed.
        return 0

    try:
        pdf_bytes = download_pdf(source_url, user_agent=settings.cse_user_agent)
    except httpx.HTTPStatusError as exc:
        if fallback_url is None:
            logger.info(
                "archived report unavailable (status %s) for %s, id=%s: %s",
                exc.response.status_code, ticker, report.id, source_url,
            )
            raise
        try:
            pdf_bytes = download_pdf(fallback_url, user_agent=settings.cse_user_agent)
            source_url = fallback_url
        except httpx.HTTPStatusError as fallback_exc:
            logger.info(
                "archived report unavailable for %s, id=%s: %s (%s) and its fallback %s (%s)",
                ticker, report.id, source_url, exc.response.status_code,
                fallback_url, fallback_exc.response.status_code,
            )
            raise fallback_exc from exc

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
    # Recorded REGARDLESS of drafted_count, including zero — see
    # IngestedFilingLog's own docstring for the real bug this closes: a
    # filing that genuinely produced 0 drafts (or one whose processing
    # crashed before this point in a prior run) must still be
    # distinguishable, on retry, from a filing never attempted at all.
    db.add(
        IngestedFilingLog(
            ticker=ticker,
            source_url=source_url,
            period_end=period_end,
            period_type=period_type,
            drafted_count=len(drafts),
            processed_at=dt.datetime.now(tz=_SRI_LANKA_TZ),
        )
    )
    db.commit()
    return len(drafts)


def ingest_report_archive_for_ticker(
    client: CseClient, db: Session, ticker: str, *, max_per_type: int | None = None
) -> dict[str, int]:
    """Sweeps one company's catalogued history, oldest filing first
    within each period_type — the order `_next_version` needs to turn a
    real amendment into version=2 rather than version=1 arriving out of
    sequence. One unreachable file never aborts the rest (matches
    `ingest_financial_statements_for_known_tickers`'s per-filing
    try/except); a 403 is counted separately from a genuine parse
    failure so the summary can tell "CDN doesn't have this one" apart
    from "something is actually broken".

    `max_per_type`, when given, keeps only the `max_per_type` MOST
    RECENT filings of each period_type — real, chosen trade-off:
    a company with a decade of history is 50-85 requests on its own at
    this project's own >=2s pacing (this module's own docstring), so a
    universe-wide sweep in full-depth (oldest-first, no cap) order
    spends its whole run on the first few alphabetically-early,
    filing-heavy companies before ever reaching the rest. Capped, a
    breadth-first pass reaches every ticker's MOST RECENT period
    quickly — the one that actually matters for a fresh valuation —
    with deeper history a genuinely separate, later pass (no `--recent`
    flag) can still backfill without redoing anything already ingested
    here (idempotent on `source_url`, same as always). Still oldest-
    first WITHIN the kept window, so `_next_version` still sees any real
    amendment among the recent filings in the right order.
    """
    archive = fetch_report_archive(client, ticker)
    drafted = unavailable = failed = 0

    for period_type, reports in (
        ("annual", archive.infoAnnualData),
        ("quarterly", archive.infoQuarterlyData),
    ):
        ordered = sorted(reports, key=lambda r: r.uploadedDate or 0)
        if max_per_type is not None:
            ordered = ordered[-max_per_type:]
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
