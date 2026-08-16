"""
Master Spec §52 job table, wired with APScheduler. Deliberately sparse:
only the jobs whose implementation actually exists in this phase are
scheduled. Everything else in the table (order book polling, macro
re-estimation, factor regressions...) is a later-phase no-op placeholder
here so the schedule's *shape* is right from day one, per the spec's own
framing: "what runs continuously is the scheduler, the monitor and the
overnight batch, not a firehose of redundant polling."

Endpoint semantics (POST, JSON vs form-urlencoded) are verified against
the live API — see app/ingestion/README_ENDPOINTS.md.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import ingest_financial_statements_for_known_tickers
from app.ingestion.market_internals import ingest_market_internals
from app.ingestion.price_loader import fetch_eod_prices, infer_session_date, upsert_eod_prices
from app.jobs.reconciliation import run_nightly_reconciliation
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.scheduler")

MARKET_TZ = ZoneInfo("Asia/Colombo")


def _all_tickers(db) -> list[str]:
    return [t for (t,) in db.execute(select(Security.ticker)).all()]


def _job_eod_snapshot() -> None:
    """§52: "EOD snapshot + adjustment  15:00 daily".

    The session date comes from the feed's own timestamps, not from
    `date.today()` — the job is scheduled Mon-Fri after close, but a
    public holiday, an unscheduled closure, or a late/missed run would
    otherwise write the previous session's prices under today's date.
    See `infer_session_date`; §6 depends on this being right.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            rows = fetch_eod_prices(client)

        session_date = infer_session_date(rows)
        if session_date is None:
            logger.error("EOD snapshot: could not determine session date from feed; nothing written")
            return

        written = upsert_eod_prices(db, session_date, rows)
        logger.info("EOD snapshot: wrote %d rows for session %s", written, session_date)
    except Exception:
        logger.exception("EOD snapshot job failed")
    finally:
        db.close()


def _job_capture_market_internals() -> None:
    """§29's variable set under "Market internals": market-wide earnings
    yield, turnover, foreign net flow. Runs with the EOD snapshot because
    it comes from the same end-of-session publication, and because the
    earnings-yield half of the hero spread is only as current as this job.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            written = ingest_market_internals(client, db)
        logger.info("market internals: wrote %d new observation(s)", written)
    except Exception:
        logger.exception("market internals capture failed")
    finally:
        db.close()


def _job_nightly_reconciliation() -> None:
    """§7 / §52: reconciliation test, run immediately after the EOD
    snapshot lands."""
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        results = run_nightly_reconciliation(db, tickers)
        failures = [t for t, alert in results.items() if alert is not None]
        if failures:
            logger.warning("reconciliation raised alerts for: %s", failures)
    finally:
        db.close()


def _job_corporate_actions_scan() -> None:
    """Not in the §52 table under this name, but implements "Corporate
    actions (splits, rights, bonus, dividends) — Event-driven — Scrape +
    mandatory human confirm" from §5. Polling per-ticker on a schedule
    (rather than truly event-driven) is a deliberate Phase-1
    simplification — a webhook/push source for CSE announcements wasn't
    identified during API verification (README_ENDPOINTS.md). Every draft
    this writes has confirmed_by=None; nothing here can affect a price.
    """
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        with CseClient() as client:
            total_drafted = 0
            for ticker in tickers:
                try:
                    total_drafted += ingest_corporate_actions_for_ticker(client, db, ticker)
                except Exception:
                    logger.exception("corporate-actions ingest failed for %s", ticker)
        if total_drafted:
            logger.info("corporate actions: drafted %d new rows awaiting human confirmation", total_drafted)
    finally:
        db.close()


def _job_financial_statement_scan() -> None:
    """§5: "Quarterly / annual — PDF table extraction -> LLM-assisted
    line-item mapping -> mandatory human confirm queue." See
    app.ingestion.financial_pdf_extractor's module docstring for what this
    Phase-1 version actually does instead of the LLM step. The feed this
    polls (getFinancialAnnouncement) returns the ~180 most recent filings
    platform-wide with no per-company filter available server-side — see
    README_ENDPOINTS.md — so this job fetches once and matches client-side
    against every known ticker, same shape as the corporate-actions scan.
    """
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        with CseClient() as client:
            try:
                total_drafted = ingest_financial_statements_for_known_tickers(client, db, tickers)
            except Exception:
                logger.exception("financial statement scan failed")
                return
        if total_drafted:
            logger.info(
                "financial statements: drafted %d new AI-assisted fundamentals awaiting confirmation",
                total_drafted,
            )
    finally:
        db.close()


def _colombo_cron(hour: int, minute: int) -> CronTrigger:
    """Every schedule in this system is anchored to the exchange's clock,
    never the host's.

    `CronTrigger` resolves its timezone AT CONSTRUCTION, defaulting to the
    machine's local zone — passing the scheduler a tz does NOT retro-fit a
    trigger that was built without one. On a host in, say, Australia/Perth
    (+08:00) that silently turns "15:00" into 12:30 Colombo, i.e. two
    hours BEFORE the CSE closes at 14:30 — so the "end of day" snapshot
    would capture a mid-session price and file it as the close. Caught on
    a real machine; hence the explicit timezone here and the test in
    tests/test_scheduler.py that pins it.
    """
    return CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri", timezone=MARKET_TZ)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=MARKET_TZ)

    # §52: "EOD snapshot + adjustment  15:00 daily" — 30 minutes after the
    # 14:30 Colombo close.
    scheduler.add_job(
        _job_eod_snapshot,
        _colombo_cron(15, 0),
        id="eod_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_capture_market_internals,
        _colombo_cron(15, 2),
        id="capture_market_internals",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_nightly_reconciliation,
        _colombo_cron(15, 5),
        id="nightly_reconciliation",
        replace_existing=True,
    )
    # §5: announcements are "event-driven" in principle; polled daily here
    # as the closest Phase-1-achievable approximation (see docstring above).
    scheduler.add_job(
        _job_corporate_actions_scan,
        _colombo_cron(16, 0),
        id="corporate_actions_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_financial_statement_scan,
        _colombo_cron(16, 30),
        id="financial_statement_scan",
        replace_existing=True,
    )

    return scheduler
