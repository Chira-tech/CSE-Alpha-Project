"""
P1.1 (`docs/CLAUDE_CODE_BRIEF.md`, TASK 1.1): the manual "Run Capture"
control. Every endpoint here is deliberately thin — `app.jobs.runner`
already holds the concurrency guard, the 15-minute manual cooldown, and
the actual job execution; this module's only job is turning that into
the four HTTP verbs the brief specifies and never running a job inline
in a request handler (§ "Execution rules — these are not optional").

`POST /{job}/run` inserts a `queued` row and returns immediately (202) —
the row is picked up and actually run by `app.jobs.scheduler`'s own
`manual_job_queue_poll` interval job, in the always-on worker process,
not here.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import threading
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.jobs.registry import JOBS, job_definition
from app.jobs.runner import JobConflict, JobCooldown, enqueue
from app.jobs.scheduler import MARKET_TZ, build_scheduler
from app.models.job_run import JobRun

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Built once, never started — a pure source of each REAL Colombo-timed
# cron trigger already registered in app.jobs.scheduler, so "next
# scheduled time" below can never silently drift from the actual
# schedule the worker runs. Rebuilding it per request (13 CronTriggers,
# no I/O) would be wasteful for no benefit.
_SCHEDULE_LOOKUP = build_scheduler()

# Only jobs with a real cron equivalent in app.jobs.scheduler get a next-
# scheduled time; recompute, rebuild_adjustment_factors,
# rebuild_factor_series and capture_all have none (see that module's own
# job list) and correctly report None rather than a guessed time.
_JOB_TO_SCHEDULER_ID = {
    # The next automatic price capture is the intraday 20-minute tick
    # while the market is open, not the midnight settled-close snapshot —
    # that is the time a human deciding whether to hit "Run Capture"
    # actually wants to see.
    "capture_prices": "intraday_price_snapshot",
    "capture_market": "capture_market_internals",
    "capture_macro": "cbsl_indicators",
    "capture_filings": "financial_statement_scan",
    "capture_corporate_actions": "corporate_actions_scan",
    "enrich_securities": "enrich_securities",
    "refresh_stale_fundamentals": "refresh_stale_fundamentals",
    "universe_integrity_checks": "universe_integrity_checks",
    "recompute_composite_ranking": "recompute_composite_ranking",
    "auto_confirm_corroborated_fundamentals": "auto_confirm_corroborated_fundamentals",
}


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite (this project's real dev database — see `JobRun`'s own
    docstring) round-trips a `DateTime(timezone=True)` column back as
    NAIVE; Postgres preserves it. Every timestamp on this table is
    always written as UTC-aware, so a naive read is unambiguously UTC —
    but serialised as-is, Pydantic emits an offset-less ISO string, and
    `new Date(...)` on the frontend then parses that as the BROWSER's
    own local time, not UTC (confirmed live: on a host 8 hours ahead of
    UTC, a job that had just finished showed as "8h ago" in the sidebar
    instead of "just now"). This is the same class of bug already fixed
    in `app.jobs.runner.enqueue`'s cooldown check, at the API's own
    serialization boundary this time rather than inside a comparison.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)


def _next_scheduled_at(job_key: str) -> dt.datetime | None:
    scheduler_id = _JOB_TO_SCHEDULER_ID.get(job_key)
    if scheduler_id is None:
        return None
    job = _SCHEDULE_LOOKUP.get_job(scheduler_id)
    if job is None:
        return None
    return job.trigger.get_next_fire_time(None, dt.datetime.now(MARKET_TZ))


class JobRunOut(BaseModel):
    id: int
    job: str
    label: str
    trigger: str
    status: str
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    progress_pct: Decimal
    progress_note: str | None
    rows_written: int
    error: str | None
    cancel_requested: bool
    created_at: dt.datetime

    @classmethod
    def from_model(cls, row: JobRun) -> "JobRunOut":
        definition = job_definition(row.job)
        return cls(
            id=row.id,
            job=row.job,
            label=definition.label if definition is not None else row.job,
            trigger=row.trigger,
            status=row.status,
            started_at=_as_utc(row.started_at),
            finished_at=_as_utc(row.finished_at),
            progress_pct=row.progress_pct,
            progress_note=row.progress_note,
            rows_written=row.rows_written,
            error=row.error,
            cancel_requested=row.cancel_requested,
            created_at=_as_utc(row.created_at),
        )


class JobStatusEntry(BaseModel):
    job: str
    label: str
    est_seconds: int
    last_run: JobRunOut | None
    next_scheduled_at: dt.datetime | None


class JobsStatus(BaseModel):
    jobs: list[JobStatusEntry]


@router.get("/status", response_model=JobsStatus)
def jobs_status(db: Session = Depends(get_db)) -> JobsStatus:
    """Every registered job (§ registry.py), whether or not it has ever
    been run — a job with no `last_run` is a real, honest state (this
    install has never captured that data), not an error."""
    entries: list[JobStatusEntry] = []
    for key, definition in JOBS.items():
        last_run = db.scalar(
            select(JobRun).where(JobRun.job == key).order_by(JobRun.created_at.desc()).limit(1)
        )
        entries.append(
            JobStatusEntry(
                job=key,
                label=definition.label,
                est_seconds=definition.est_seconds,
                last_run=JobRunOut.from_model(last_run) if last_run is not None else None,
                next_scheduled_at=_next_scheduled_at(key),
            )
        )
    return JobsStatus(jobs=entries)


@router.post("/{job}/run", response_model=JobRunOut, status_code=202)
def trigger_job(job: str, db: Session = Depends(get_db)) -> JobRunOut:
    if job_definition(job) is None:
        raise HTTPException(404, f"unknown job {job!r}")
    try:
        run = enqueue(db, job, trigger="manual")
    except JobConflict:
        raise HTTPException(409, f"job '{job}' is already queued or running") from None
    except JobCooldown as exc:
        raise HTTPException(
            429,
            {
                "message": (
                    f"job '{job}' was already triggered manually within the last 15 minutes"
                ),
                "retry_after": exc.retry_after_seconds,
            },
        ) from None

    # Run it now, in a daemon thread, so "Run Capture" works for anyone
    # running just `uvicorn app.main:app` without a separate
    # `python -m app.worker`. `runner.execute` atomically claims the
    # queued row, so if a worker IS also up its `poll_and_run_one` just
    # finds nothing to do — no double execution.
    from app.config import settings

    if settings.execute_manual_jobs_in_process:
        run_id = run.id
        threading.Thread(
            target=_execute_safely, args=(run_id,), name=f"job-{run_id}-{job}", daemon=True
        ).start()

    return JobRunOut.from_model(run)


def _execute_safely(run_id: int) -> None:
    from app.jobs.runner import execute

    try:
        execute(run_id)
    except Exception:  # noqa: BLE001 — a daemon thread must never die noisily
        logging.getLogger("cse_alpha.api.jobs").exception("in-process job run %s crashed", run_id)


@router.post("/{run_id}/cancel", response_model=JobRunOut)
def cancel_job(run_id: int, db: Session = Depends(get_db)) -> JobRunOut:
    """Cooperative cancel (§ "scraper checks a flag between tickers").
    A still-`queued` run has never actually started, so this cancels it
    outright rather than waiting for a worker that hasn't picked it up
    yet — flipping `status` off `queued` is also what stops `app.jobs.
    runner.poll_and_run_one` from ever picking it up. A `running` run
    only gets `cancel_requested=True`; the runner's own loop (per-ticker
    for the two sweeps, post-completion for every single-call job) is
    what actually honours it — see that module's docstring."""
    run = db.get(JobRun, run_id)
    if run is None:
        raise HTTPException(404, f"no job run with id {run_id}")
    if not run.is_open:
        raise HTTPException(409, f"job run {run_id} already finished ({run.status})")

    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = dt.datetime.now(dt.timezone.utc)
    run.cancel_requested = True
    db.commit()
    db.refresh(run)
    return JobRunOut.from_model(run)


@router.get("/{run_id}/stream")
async def stream_job(run_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    """SSE progress stream — polls `job_runs` once a second until the run
    reaches a terminal status, then closes.

    Deliberately opens a FRESH `SessionLocal()` inside the generator
    below rather than reusing the `db` session injected above. FastAPI
    tears a `Depends(get_db)` session down the moment this function
    RETURNS its `StreamingResponse`, not once the streamed body has
    actually finished sending — reusing `db` inside the generator would
    read from an already-closed session on the very first poll after the
    initial one. Every other multi-step operation in this codebase
    (`app.jobs.runner.execute`, every `app.jobs.scheduler` job) already
    opens its own short-lived session for exactly this kind of reason;
    this reuses that same pattern instead of fighting the framework. The
    `db` parameter above still matters: it 404s immediately, inside the
    normal request/response cycle, if `run_id` doesn't exist at all.
    """
    if db.get(JobRun, run_id) is None:
        raise HTTPException(404, f"no job run with id {run_id}")

    async def event_source():
        while True:
            session = SessionLocal()
            try:
                run = session.get(JobRun, run_id)
                if run is None:
                    yield f"event: error\ndata: {json.dumps({'detail': 'job run no longer exists'})}\n\n"
                    return
                payload = json.loads(JobRunOut.from_model(run).model_dump_json())
            finally:
                session.close()
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] not in ("queued", "running"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        event_source(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
