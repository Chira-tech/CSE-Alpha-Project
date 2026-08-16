"""
Master Spec §52 job table, wired with APScheduler. Deliberately sparse:
only the jobs whose implementation actually exists in this phase are
scheduled. Everything else in the table (order book polling, announcement
triage, macro re-estimation, factor regressions...) is a later-phase
no-op placeholder here so the schedule's *shape* is right from day one,
per the spec's own framing: "what runs continuously is the scheduler, the
monitor and the overnight batch, not a firehose of redundant polling."
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import SessionLocal
from app.jobs.reconciliation import run_nightly_reconciliation
from app.models.securities import Security
from sqlalchemy import select

logger = logging.getLogger("cse_alpha.jobs.scheduler")


def _job_nightly_reconciliation() -> None:
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker)).all()]
        results = run_nightly_reconciliation(db, tickers)
        failures = [t for t, alert in results.items() if alert is not None]
        if failures:
            logger.warning("reconciliation raised alerts for: %s", failures)
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Colombo")

    # §52: "EOD snapshot + adjustment  15:00 daily  ... reconciliation test"
    scheduler.add_job(
        _job_nightly_reconciliation,
        CronTrigger(hour=15, minute=5, day_of_week="mon-fri"),
        id="nightly_reconciliation",
        replace_existing=True,
    )

    return scheduler
