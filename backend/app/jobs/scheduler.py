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

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
from app.ingestion.cse_client import CseClient
from app.ingestion.price_loader import fetch_eod_prices, upsert_eod_prices
from app.jobs.reconciliation import run_nightly_reconciliation
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.scheduler")


def _all_tickers(db) -> list[str]:
    return [t for (t,) in db.execute(select(Security.ticker)).all()]


def _job_eod_snapshot() -> None:
    """§52: "EOD snapshot + adjustment  15:00 daily"."""
    db = SessionLocal()
    try:
        with CseClient() as client:
            rows = fetch_eod_prices(client)
        written = upsert_eod_prices(db, dt.date.today(), rows)
        logger.info("EOD snapshot: wrote %d rows", written)
    except Exception:
        logger.exception("EOD snapshot job failed")
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


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Colombo")

    scheduler.add_job(
        _job_eod_snapshot,
        CronTrigger(hour=15, minute=0, day_of_week="mon-fri"),
        id="eod_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_nightly_reconciliation,
        CronTrigger(hour=15, minute=5, day_of_week="mon-fri"),
        id="nightly_reconciliation",
        replace_existing=True,
    )
    # §5: announcements are "event-driven" in principle; polled daily here
    # as the closest Phase-1-achievable approximation (see docstring above).
    scheduler.add_job(
        _job_corporate_actions_scan,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri"),
        id="corporate_actions_scan",
        replace_existing=True,
    )

    return scheduler
