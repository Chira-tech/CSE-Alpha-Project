"""
The always-on process. Run with `python -m app.worker`.

Master Spec §52 is explicit about what "always on" actually means here:
"The CSE trades roughly 09:30-14:30 local, five days a week — about 25
hours out of 168. Your horizon is 12-36 months. What runs continuously is
the scheduler, the monitor and the overnight batch, not a firehose of
redundant polling."

So this process does almost nothing most of the time, and that is correct.
Its one job that matters today is being alive at 15:00 Colombo time on a
trading day so the EOD snapshot lands — because with no historical price
source available on the CSE API (see README_ENDPOINTS.md), forward
capture is the only way price history accumulates, and a day missed is a
day that cannot be recovered.

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

from app.config import settings
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
