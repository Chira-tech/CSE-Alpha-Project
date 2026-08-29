from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRun(Base):
    """TASK 1.1: one row per attempted job run, manual or scheduled — the
    record a "Run Capture" button and the Data Health screen's job
    history (TASK 1.2) both read from. See `app.jobs.runner`'s own
    module docstring for how a row moves through `queued` -> `running`
    -> `success`/`failed`/`cancelled`, and for why the concurrency guard
    (§ "never queue a duplicate") is enforced at the APPLICATION layer
    here rather than the DB-level partial unique index the brief's own
    Postgres-flavoured pseudocode names — SQLite (this project's real
    dev/test database) has no `CREATE UNIQUE INDEX ... WHERE` partial-
    index syntax; `app.jobs.runner.enqueue` re-checks for an existing
    open run inside the same transaction that inserts the new one
    instead, which is the equivalent real guarantee this engine can
    actually enforce.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
    # Declared here to match what the migrations actually created. These
    # indexes existed in the database but not on the model, so
    # `alembic revision --autogenerate` would have emitted a migration
    # DROPPING them (found in the 29 Aug audit via `alembic check`).
        Index("ix_job_runs_job", "job"),
        Index("ix_job_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)  # 'manual' | 'scheduled'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # queued | running | success | failed | cancelled
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    progress_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """§1.1's "cooperative cancel; scraper checks a flag between
    tickers" — set by `POST /api/jobs/{run_id}/cancel`, read by the
    runner's own per-ticker loop. Not in the brief's own pseudocode
    schema (which only lists a `status` column) but required to
    implement the cancel endpoint the same brief also specifies —
    `status` alone can't represent "cancel requested, not yet honoured"
    for a job the worker hasn't reached its next checkpoint in."""
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def is_open(self) -> bool:
        return self.status in ("queued", "running")
