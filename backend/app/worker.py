"""
The always-on process. Run with `python -m app.worker`.

Master Spec §52 is explicit about what "always on" actually means here:
"The CSE trades roughly 09:30-14:30 local, five days a week — about 25
hours out of 168. Your horizon is 12-36 months. What runs continuously is
the scheduler, the monitor and the overnight batch, not a firehose of
redundant polling."

So this process does almost nothing most of the time, and that is correct.
What matters is that it is alive across the Colombo trading window so the
`intraday_price_snapshot` job keeps today's prices current every 20
minutes, and at 00:00 Colombo so the nightly batch (the settled-close
snapshot, filings, corporate actions, reconciliations, the scoreboard
recompute) lands — because with no historical price source on the CSE API
(see README_ENDPOINTS.md), forward capture is the only way price history
accumulates, and a day missed is a day that cannot be recovered.

Alternative for a single-process deployment: set
`RUN_SCHEDULER_IN_PROCESS=1` and run only `uvicorn app.main:app` (no
`--reload`) — the API process then starts this same scheduler in a
FastAPI lifespan hook. This module stays the production path where the
API and the schedule are kept separate.

Deliberately separate from the API process. `uvicorn app.main:app` serves
requests and must be restartable at will; this holds a schedule and must
not be. Running the scheduler inside the API would mean every code reload
skipped or double-fired jobs, and `--reload` in development would be
actively harmful.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
from types import FrameType

# REAL BUG, FOUND LIVE (23 Aug 2026): this process's stdout/stderr
# default to the Windows console code page (`cp1252` in this
# environment, confirmed via `sys.stdout.encoding`) even when redirected
# to a log file, not UTF-8 — Python only defaults a redirected stream to
# UTF-8 on POSIX. This codebase's own real log/progress messages
# routinely contain characters outside cp1252 (a genuine Unicode minus
# sign in a formatted negative figure, section signs, em/en dashes,
# multiplication signs, arrow/chip glyphs) — the first one logged raises
# an unhandled `UnicodeEncodeError` that kills this whole process
# instantly, with no traceback reaching anyone (stdout itself is what
# failed to write). Caught live: this exact process died silently mid-
# `recompute` job, `_job_poll_manual_job_queue` then reported "maximum
# number of running instances reached" forever after, because nothing
# was left alive to ever finish that job or start the next poll tick —
# indistinguishable from the job just hanging until this was traced.
# Reconfigured to UTF-8 before anything else runs, `errors="replace"` as
# a last-resort safety net so a still-unanticipated character degrades
# to a substitution glyph in the log rather than taking the whole
# process down again.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.config import settings
from app.db.session import SessionLocal
from app.jobs.runner import recover_orphaned_runs
from app.jobs.scheduler import build_scheduler

logger = logging.getLogger("cse_alpha.worker")

_shutdown = threading.Event()


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    logger.info("received signal %s — shutting down after current job finishes", signum)
    _shutdown.set()


def main() -> int:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # See `recover_orphaned_runs`'s own docstring: must run before the
    # scheduler starts (and therefore before `_job_poll_manual_job_queue`
    # can ever pick anything up), and only ever here — this is the one
    # moment a fresh worker process can be certain any `queued`/`running`
    # row left behind belongs to a process that no longer exists.
    with SessionLocal() as _db:
        recovered = recover_orphaned_runs(_db)
    if recovered:
        logger.warning("recovered %d job run(s) orphaned by a previous worker exit", recovered)

    scheduler = build_scheduler()
    scheduler.start()

    jobs = scheduler.get_jobs()
    logger.info("worker started with %d scheduled job(s):", len(jobs))
    for job in jobs:
        logger.info("  %-28s next run: %s", job.id, job.next_run_time)
    logger.info("timezone: Asia/Colombo. Ctrl-C to stop.")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # wait() rather than a sleep loop so a signal is acted on immediately.
    _shutdown.wait()

    # wait=True: let an in-flight job finish rather than tearing down
    # mid-write. Jobs here write prices and draft rows; a half-applied
    # batch is worse than a late shutdown.
    scheduler.shutdown(wait=True)
    logger.info("worker stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
