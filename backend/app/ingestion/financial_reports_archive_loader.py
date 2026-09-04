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

import concurrent.futures
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

import httpx

from app.config import settings
from app.domain.financial_statement_parsing import check_extraction_quality
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import (
    ExtractedLine,
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

# A REAL, live, reproducible bug — NOT hypothetical: BALA.N0000's actual
# FY2024 annual report (id 705_1780046541693.pdf) hung a full reconcile
# sweep for over 20 minutes of continuous CPU burn, with zero progress.
# Isolated independently of this module's own code: even a bare
# `pdfplumber` page.extract_text() call on this exact file hangs, before
# any of `financial_statement_parsing`'s own regex/token logic ever runs
# — a pdfplumber-level performance pathology on this one file's content,
# not a bug this pipeline introduced. One pathological PDF must not be
# able to block an entire universe-wide sweep indefinitely; see
# `_extract_with_timeout` below.
#: Raised from 90s (4 Sep 2026) now that `extract_financial_statement_
#: candidates` bounds its own page scan to the primary-statements block
#: (`_STATEMENT_BLOCK_END_GAP` / `_MAX_SCAN_PAGES`) instead of calling
#: `page.extract_text()` on every page of a 300-page annual report. The
#: bound is the real fix; this is the backstop for a genuinely
#: pathological single page.
_EXTRACTION_TIMEOUT_SECONDS = 200.0


def _extract_with_timeout(pdf_bytes: bytes) -> list[tuple[int, ExtractedLine]]:
    """`extract_financial_statement_candidates`, bounded. A fresh single-
    worker executor per call (not a shared module-level pool) — sharing
    one would mean a single stuck file's thread permanently occupies the
    only worker, silently timing out and then HANGING every subsequent
    call forever, the exact failure mode this function exists to avoid.

    On timeout, deliberately does NOT wait for the stuck thread to exit
    (`executor.shutdown(wait=True)` would block on the very thread this
    function is escaping from, defeating the entire point) — the thread
    is left running in the background. A real, bounded cost (one extra
    idle-ish thread for the process's remaining lifetime, only for the
    rare pathological file) traded against the alternative: a batch sweep
    of hundreds of tickers stuck forever on one bad PDF.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(extract_financial_statement_candidates, pdf_bytes)
    try:
        result = future.result(timeout=_EXTRACTION_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(
            f"PDF extraction exceeded {_EXTRACTION_TIMEOUT_SECONDS:.0f}s — a real, "
            "reproducible pdfplumber performance pathology on this specific file "
            "(confirmed live on BALA.N0000's FY2024 annual report), not a bug in "
            "this pipeline's own extraction logic."
        ) from None
    else:
        executor.shutdown(wait=False)
        return result


_ERRATA_CHECK_TIMEOUT_SECONDS = 15.0


def _first_page_text_uncached(pdf_bytes: bytes) -> str | None:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            return None
        return pdf.pages[0].extract_text() or ""


def _first_page_text(pdf_bytes: bytes) -> str | None:
    """The errata check below (`ingest_archived_report`) needs only the
    FIRST page's text, not a full extraction — but even one page's
    `extract_text()` can hang pathologically on the wrong file (the same
    real, reproducible pdfplumber issue `_extract_with_timeout` above
    exists for, on a different file). Bounded the same way, with a
    shorter timeout since a single page is a much smaller unit of work
    than a full document. Returns `None` — never raises — on timeout or
    any other failure: an errata check this pipeline can't safely run is
    treated as "not an errata," never as a reason to abort ordinary
    ingestion of a filing that might be perfectly fine.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_first_page_text_uncached, pdf_bytes)
    try:
        result = future.result(timeout=_ERRATA_CHECK_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — see docstring: never block ordinary ingestion
        logger.warning("first-page errata check failed or timed out; proceeding as normal ingestion")
        return None
    else:
        executor.shutdown(wait=False)
        return result


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
    reconcile: bool = False,
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

    `reconcile=True` — A REAL, NARROW GAP THIS PARAMETER CLOSES: a parser
    fix (or a new canonical-label alias) landing after a filing was
    already ingested previously had NO way to benefit from it —
    `_already_ingested_by_source`'s idempotency check skips a filing
    outright the moment ANY `Fundamental` row carries its `source_url`,
    regardless of how INCOMPLETE that extraction was. The real, live case
    this closes: `_VARIANCE_PCT_RE` (see `app.domain.financial_statement_
    parsing`'s own docstring) fixed a corrupted-label bug that silently
    dropped `revenue`/`net_income` on any statement with an embedded
    "Change %" column — a real gap verified on Hikkaduwa Beach Resort
    PLC's and Amãna Bank PLC's real filings — but every filing already
    ingested before that fix landed still has only whatever partial set
    of lines the OLD parser could reach, because the ordinary (non-
    reconcile) path skips it as done.

    `reconcile=True` still re-downloads and re-parses the filing, but
    instead of skipping, DIFFS the freshly-extracted lines against what
    THIS EXACT `source_url` already has on file and inserts ONLY the
    statement lines genuinely missing — at the SAME `version`/
    `restated_flag` those existing rows already carry, never a new
    version (this is not a new filing, just a deeper read of the same
    one). It NEVER touches, replaces, or deletes an existing row —
    confirmed or not — which is the entire point: a human reviewer's
    confirmation must never be silently discarded just because a parser
    improvement came along later. If the exact source_url this filing's
    existing rows carry can no longer be told apart (see
    `effective_source_url` below), or there is genuinely nothing new to
    add, this returns 0, exactly like the ordinary skip path.

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
    already_primary = _already_ingested_by_source(db, ticker, source_url)
    already_fallback = fallback_url is not None and _already_ingested_by_source(db, ticker, fallback_url)
    if already_primary or already_fallback:
        if not reconcile:
            # A row from before this fix, filed under the old (un-
            # normalized, 403-ing) URL — `already_fallback` is only
            # reachable for a filing whose catalogue path already lacked
            # cmt/ AND which somehow still succeeded under the literal
            # path (the defensive fallback below actually working).
            # Recognised as done rather than reprocessed.
            return 0
        # Reconcile mode: this filing already has rows on file, under
        # whichever of the two URLs actually matched above — new lines
        # must be filed under THAT SAME url, not silently re-homed under
        # the other one just because it happens to be checked first.
        effective_source_url = source_url if already_primary else fallback_url
    else:
        effective_source_url = None  # resolved after download, exactly as before

    download_url = effective_source_url or source_url
    try:
        pdf_bytes = download_pdf(download_url, user_agent=settings.cse_user_agent)
    except httpx.HTTPStatusError as exc:
        if effective_source_url is not None or fallback_url is None:
            logger.info(
                "archived report unavailable (status %s) for %s, id=%s: %s",
                exc.response.status_code, ticker, report.id, download_url,
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
    if effective_source_url is not None:
        source_url = effective_source_url

    # REAL BUG THIS CLOSES, found live (27 Aug 2026) tracing MFPE.N0000's
    # real duplicate-period contamination (R1_VALIDATION.md's own named,
    # unfixed finding): a CSE "ERRATA" announcement is a CORRECTION LETTER
    # about an already-filed annual/quarterly report, not a distinct new
    # filing — but its catalogue metadata's own `manualDate` does NOT
    # reliably carry the ORIGINAL period_end the errata is correcting
    # (verified: MFPE's real errata, "ERRATA — CORRECTION TO THE NET
    # ASSET VALUE (NAV) RATIOS... FOR THE YEAR ENDED 31ST MARCH 2025,"
    # catalogued with `manualDate` = 22 Oct 2025 — the errata's OWN
    # submission date, not the March 2025 period it's actually about).
    # Ingesting it as an ordinary filing created a phantom SECOND "annual"
    # period for a company that only ever had one, with every extracted
    # figure identical to the original (this errata explicitly states "no
    # impact on the financial figures"). Rather than trying to parse the
    # real period out of the errata's own free-text explanation — a much
    # less certain signal than every other date this pipeline already
    # trusts (see this module's own docstring on why `uploadedDate` is
    # trusted) — skip it outright: "skip rather than guess" is this
    # project's own standing rule (`classify_period_type`'s "return None,
    # don't guess" already does the same thing one level up, for
    # unrecognised period wording).
    first_page_text = _first_page_text(pdf_bytes)
    if first_page_text is not None and "errata" in first_page_text.lower():
        logger.info(
            "skipping archived report id=%s for %s: an ERRATA/correction letter, not a distinct "
            "filing — its own catalogue manualDate does not reliably carry the period it corrects",
            report.id, ticker,
        )
        return 0

    candidates = _extract_with_timeout(pdf_bytes)

    extracted_values = {
        line.statement_line: line.primary_value
        for _page, line in candidates
        if line.statement_line and line.primary_value is not None
    }
    failed_identities = [c for c in check_extraction_quality(extracted_values) if not c.passed]
    if failed_identities:
        logger.error(
            "archived extraction for %s %s failed %d accounting identity/magnitude check(s): %s",
            ticker, period_end, len(failed_identities),
            "; ".join(f"{c.name} ({c.detail})" for c in failed_identities),
        )

    if effective_source_url is not None:
        # Reconciling an already-seen filing: build the FULL set of drafts
        # a from-scratch parse would produce (reusing build_fundamental_
        # drafts' own first-occurrence-wins / SUM_ACROSS_OCCURRENCES
        # logic unchanged), then keep only the statement lines this exact
        # source_url does NOT already have on file — confirmed or not,
        # never overwritten, never duplicated. `version`/`restated_flag`
        # are copied from whatever this source_url's existing rows
        # already carry (this is not a new filing, just a deeper read of
        # the one already on file) rather than recomputed via
        # `_next_version`, which would incorrectly mint a new version.
        existing_lines = set(
            db.scalars(
                select(Fundamental.statement_line).where(
                    Fundamental.ticker == ticker, Fundamental.source_url == source_url
                )
            ).all()
        )
        existing_version = db.scalar(
            select(Fundamental.version)
            .where(Fundamental.ticker == ticker, Fundamental.source_url == source_url)
            .limit(1)
        )
        version = existing_version if existing_version is not None else _next_version(
            db, ticker, period_end, period_type
        )
        all_drafts = build_fundamental_drafts(
            ticker=ticker,
            period_end=period_end,
            period_type=period_type,
            first_available_date=first_available_date,
            source_url=source_url,
            candidates=candidates,
        )
        drafts = [d for d in all_drafts if d.statement_line not in existing_lines]
    else:
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
    if drafts or effective_source_url is None:
        # Recorded REGARDLESS of drafted_count, including zero — see
        # IngestedFilingLog's own docstring for the real bug this closes:
        # a filing that genuinely produced 0 drafts (or one whose
        # processing crashed before this point in a prior run) must
        # still be distinguishable, on retry, from a filing never
        # attempted at all. A reconciliation pass that finds nothing new
        # to add, though, does NOT get its own log row — this filing
        # already has one from its original ingest, and a second
        # zero-drafted entry would just be noise on every future
        # reconciliation sweep of an already-fully-extracted filing.
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
    client: CseClient, db: Session, ticker: str, *, max_per_type: int | None = None,
    reconcile: bool = False,
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

    `reconcile`, passed straight through to `ingest_archived_report` —
    see that function's own docstring for what it does and, critically,
    what it never does (never touches an existing row, confirmed or
    not). Every filing is still re-downloaded and re-parsed under this
    flag, including ones already fully extracted — there is no cheaper
    way to find out whether a parser fix changed anything for a given
    filing without re-running it, so a reconcile sweep costs the same
    request budget as a fresh one.
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
                drafted += ingest_archived_report(
                    client, db, ticker, report, period_type=period_type, reconcile=reconcile
                )
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
